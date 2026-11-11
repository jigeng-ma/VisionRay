"""G7 专属的对话方式和录像规格验证。"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path
from xml.etree import ElementTree as ET

from .ble_commands import BleMediaCommands
from .devices import Adb
from .errors import TestBlocked
from .gallery import GalleryPage
from .settings import SettingsPage


class G7Page:
    def __init__(self, android):
        self.a = android
        self.d = android.driver
        self.package = android.context['config']['package']

    def visible_texts(self):
        return [e.get('text').strip() for e in ET.fromstring(self.d.page_source).iter()
                if e.get('package') == self.package and e.get('text', '').strip()]

    def text(self, *labels, timeout=10):
        def find():
            found = [e for e in self.d.find_elements('xpath',
                     f"//*[@package='{self.package}' and @text]")
                     if e.is_displayed() and e.text.strip() in labels]
            if len(found) > 1:
                raise AssertionError(f'设置项 {labels} 不唯一：{len(found)} 项。')
            return found[0] if found else None
        return self.a.wait(find, ' / '.join(labels), timeout)

    def conversation_modes(self):
        SettingsPage(self.a).ai()
        self.text('Dialogue Mode', 'Conversation Mode', 'Conversation Style').click()
        names = ('Single Conversation', 'Continuous Conversation', 'Interruptible Conversation')
        self.a.wait(lambda: 'Single Conversation' in self.visible_texts(),
                    '对话方式弹窗', 10)
        shown = self.visible_texts()
        required = names[:2]
        missing = [name for name in required if name not in shown]
        assert not missing, f'对话方式弹窗缺少必需选项 {missing}；实际：{shown}。'
        available = [name for name in names if name in shown]
        self.a.log('g7-dialogue-options', {'shown': shown, 'tested': available,
                                           'interruptible_hidden': names[2] not in shown})
        for name in names:
            if name not in shown:
                continue
            if name != names[0]:
                self.text('Dialogue Mode', 'Conversation Mode', 'Conversation Style').click()
            self.text(name).click()
            selected = self.text(name).get_attribute('selected') == 'true'
            assert selected, f'{name} 在弹窗中未被选中。'
            self.text('OK').click()
            self.a.assert_wait(lambda: name.replace(' Conversation', '') in self.visible_texts(), True,
                               f'{name} 切换后设置页回显', 10)
            self.a.capture('g7-' + name.lower().replace(' ', '-'))

    def capture(self):
        SettingsPage(self.a).capture()

    def _swipe_options(self):
        size = self.d.get_window_size()
        self.d.swipe(int(size['width'] * .5), int(size['height'] * .83),
                     int(size['width'] * .5), int(size['height'] * .67), 450)

    def _options(self, resource):
        return [e for e in self.d.find_elements('id', self.package + ':id/' + resource)
                if e.is_displayed() and e.text.strip()]

    @staticmethod
    def seconds(label):
        match = re.fullmatch(r'\s*(\d+)\s*(min|minute|minutes|s|sec|seconds|秒|分钟)\s*', label, re.I)
        if not match:
            raise AssertionError(f'无法识别录像时长选项：{label}。')
        return int(match[1]) * (60 if match[2].lower() in ('min', 'minute', 'minutes', '分钟') else 1)

    def option_texts(self, row_labels):
        self.text(*row_labels).click()
        resource = 'tvContent' if 'Video Specs' in row_labels else 'tv_label'
        self.a.wait(lambda: self._options(resource), '录像设置选项', 10)
        values = []
        for _ in range(12):
            visible = [e.text.strip() for e in self._options(resource)]
            new = [value for value in visible if value not in values]
            values.extend(new)
            if not new:
                break
            self._swipe_options()
        if resource == 'tvContent':
            values = [value for value in values if re.search(r'\d{3,4}\s*[x×*]\s*\d{3,4}', value)]
        if not values:
            raise AssertionError(f'{row_labels} 没有可读取的选项：{self.visible_texts()}。')
        self.d.press_keycode(4)
        self.text(*row_labels)
        return values

    def choose_option(self, row_labels, option_pattern):
        row = self.text(*row_labels)
        row.click()
        resource = 'tvContent' if 'Video Specs' in row_labels else 'tv_label'
        self.a.wait(lambda: self._options(resource), '录像设置选项', 10)
        chosen = None
        for _ in range(12):
            options = self._options(resource)
            matches = [e for e in options if re.search(option_pattern, e.text, re.I)]
            if len(matches) > 1:
                raise AssertionError(f'期望唯一选项 /{option_pattern}/，实际 {len(matches)} 项。')
            if matches:
                chosen = matches[0].text.strip()
                matches[0].click()
                break
            self._swipe_options()
        if chosen is None:
            raise AssertionError(f'没有找到录像设置选项 /{option_pattern}/；当前可见：{self.visible_texts()}。')
        normalized = re.sub(r'\s*fps\b', '', chosen, flags=re.I)
        self.a.assert_wait(lambda: any(normalized in text for text in self.visible_texts()), True,
                           f'设置项回显 {chosen}', 10)
        self.a.log('g7-capture-option', {'row': row_labels, 'chosen': chosen})
        return chosen

    def set_video(self, width, height, fps, duration):
        self.capture()
        resolution = self.choose_option(('Video Specs', 'Video Resolution', 'Video Specification', 'Video Format'),
                                        rf'{width}\s*[x×*]\s*{height}.*?\b{fps}\s*fps')
        if str(fps) not in resolution and fps != 30:
            raise AssertionError(f'视频规格未明确显示 {fps}fps：{resolution}。')
        duration_label = f'{duration // 60}Min' if duration >= 60 else f'{duration}s'
        self.choose_option(('Video Duration', 'Recording Duration'),
                           rf'(?<!\d){duration // 60}\s*[mM]in' if duration >= 60 else rf'(?<!\d){duration}\s*(?:s|sec|秒)')
        self.a.capture(f'g7-video-setting-{width}-{height}-{fps}-{duration}')
        return resolution, duration_label

    def video_rows(self):
        phone = self.a.context['phone']
        adb = Adb()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'nova_app_database'
            for suffix in ('', '-wal', '-shm'):
                try:
                    path.with_name(path.name + suffix).write_bytes(adb.run(
                        '-s', phone, 'exec-out', 'run-as', self.package,
                        'cat', 'databases/nova_app_database' + suffix, binary=True))
                except RuntimeError:
                    if not suffix:
                        raise TestBlocked('无法读取 APP 媒资数据库。') from None
            db = sqlite3.connect(path)
            try:
                return {row[0]: row[1] for row in db.execute(
                    "select id, path from file_metadata where file_type='video'")}
            finally:
                db.close()

    def metadata(self, device_path):
        ffprobe = shutil.which('ffprobe')
        if not ffprobe:
            raise TestBlocked('未找到 ffprobe；无法验证实际视频分辨率和帧率。')
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / 'captured.mp4'
            with video.open('wb') as output:
                result = subprocess.run([Adb().executable, '-s', self.a.context['phone'],
                    'exec-out', 'run-as', self.package, 'cat', device_path], stdout=output,
                    stderr=subprocess.PIPE, timeout=300)
            if result.returncode or not video.stat().st_size:
                raise AssertionError('导入视频存在于数据库，但无法读取实际视频文件：' +
                                     result.stderr.decode('utf-8', errors='replace'))
            result = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'v:0',
                '-show_entries', 'stream=codec_name,width,height,avg_frame_rate,bit_rate:format=duration,size',
                '-of', 'json', str(video)], capture_output=True, text=True, timeout=60)
            if result.returncode:
                raise AssertionError('无法解析导入视频：' + result.stderr)
            data = json.loads(result.stdout)
            streams = data.get('streams', [])
            assert len(streams) == 1, f'导入视频的画面轨数量不符：{len(streams)}。'
            stream = streams[0]
            numerator, denominator = map(int, stream['avg_frame_rate'].split('/'))
            return {'width': stream['width'], 'height': stream['height'],
                    'fps': numerator / denominator, 'seconds': float(data['format']['duration']),
                    'codec': stream.get('codec_name') or '未知',
                    'bitrate': stream.get('bit_rate') or '未知',
                    'bytes': int(data['format'].get('size') or video.stat().st_size)}

    def record_and_check(self, duration, width, height, fps):
        gallery = GalleryPage(self.a)
        before_home = gallery.pending_count_or_zero('home')
        if before_home:
            # 先导入旧的待同步媒资，避免把历史视频误认为本次录像。
            gallery.import_from('home', timeout=max(300, duration + 180))
            before_home = gallery.pending_count_or_zero('home')
        before_media = self.video_rows()
        self._video_before = before_media
        command = BleMediaCommands(self.a)
        command.start_video()
        try:
            command._hold(duration + 3)
            self.a.assert_wait(lambda: len(self.video_rows()) > len(before_media)
                or gallery.pending_count_or_zero('home') > before_home, True,
                '录像到时后新增待导入通知或空间视频', 180)
        finally:
            if (len(self.video_rows()) == len(before_media)
                    and gallery.pending_count_or_zero('home') <= before_home):
                command.stop_video()
        if len(self.video_rows()) == len(before_media):
            # 某些固件先出现首页通知，空间页的待导入卡片却不显示；首页入口仍可导入。
            gallery.import_from('home', timeout=max(300, duration + 180))
        self.a.assert_wait(lambda: len(self.video_rows()) - len(before_media), 1,
                           '录制后空间新增视频数量', max(300, duration + 180))
        added = set(self.video_rows()) - set(before_media)
        assert len(added) == 1, f'本轮导入的新视频不唯一：{added}。'
        path = self.video_rows()[added.pop()]
        self._recorded_video_path = path
        actual = self.metadata(path)
        actual['filename'] = Path(path).name
        self.a.log('g7-video-metadata', actual)
        duration_tolerance = 5 if duration >= 720 else 2
        details = (f'文件名 {actual["filename"]}；实际视频：{actual["width"]}x{actual["height"]}，'
                   f'{actual["fps"]:.2f}fps，时长 {actual["seconds"]:.2f} 秒，'
                   f'编码 {actual["codec"]}，码率 {actual["bitrate"]}bps，'
                   f'文件大小 {actual["bytes"]} 字节；'
                   f'期望：{width}x{height}，{fps}fps，时长 {duration}±{duration_tolerance} 秒。')
        assert abs(actual['seconds'] - duration) <= duration_tolerance, '视频时长错误；' + details
        assert (actual['width'], actual['height']) == (width, height), (
            '视频分辨率错误；' + details)
        assert abs(actual['fps'] - fps) <= 1, '视频帧率错误；' + details
        return actual

    def save_failed_video(self):
        """失败时把本次导入的视频保存到当前用例的证据目录。"""
        directory = os.environ.get('GLASSES_EVIDENCE_DIR')
        if not directory:
            return '未设置用例证据目录'
        path = getattr(self, '_recorded_video_path', None)
        if not path:
            before = getattr(self, '_video_before', None)
            if before is None:
                return '尚未开始录像，无法确定本次视频'
            added = set(self.video_rows()) - set(before)
            if len(added) != 1:
                return f'未唯一找到本次导入的视频（新增 {len(added)} 个）'
            path = self.video_rows()[added.pop()]
        target = Path(directory) / Path(path).name
        if target.exists():
            return f'证据目录已有同名文件，未覆盖原视频：{target.name}'
        temporary = target.with_name(target.name + '.part')
        try:
            with temporary.open('wb') as output:
                result = subprocess.run(
                    [Adb().executable, '-s', self.a.context['phone'], 'exec-out',
                     'run-as', self.package, 'cat', path],
                    stdout=output, stderr=subprocess.PIPE, timeout=1200)
            if result.returncode or not temporary.stat().st_size:
                return ('复制视频失败：' + result.stderr.decode('utf-8', errors='replace').strip())[:500]
            temporary.replace(target)
            self.a.log('g7-failed-video-saved', {'file': target.name, 'bytes': target.stat().st_size})
            return None
        finally:
            temporary.unlink(missing_ok=True)

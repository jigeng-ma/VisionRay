"""G5 拍摄设置及横竖屏媒资用例。"""

from io import BytesIO
import json
import os
from pathlib import Path
import posixpath
import shlex
import shutil
import subprocess
import tempfile
import time
from fractions import Fraction

import pytest

from PIL import Image, ImageOps

from studio.ble_commands import BleMediaCommands
from studio.devices import Adb
from studio.errors import TestBlocked
from studio.gallery import GalleryPage
from studio.settings import SettingsPage


class ShootingOrientation:
    def __init__(self, android):
        self.android = android
        self.settings = SettingsPage(android)

    def open(self):
        self.settings.capture()

    def value(self):
        row = self.settings.one('video_orientation')
        return row.find_element('id', self.settings.package + ':id/tv_hint').text

    def select(self, orientation):
        android = self.android
        self.settings.one('video_orientation').click()
        choices = lambda: [item for item in android.driver.find_elements(
            'id', self.settings.package + ':id/tv_label') if item.is_displayed()]
        android.assert_wait(lambda: sorted(item.text for item in choices()),
                            ['Landscape', 'Portrait'], '拍摄方向选项', 10)
        android.capture('orientation-options')
        next(item for item in choices() if item.text == orientation).click()
        android.assert_wait(lambda: bool(choices()), False, '拍摄方向弹窗关闭', 10)
        android.assert_wait(self.value, orientation, '拍摄设置当前方向', 15)
        android.capture('orientation-' + orientation.lower())

    def confirm_before_capture(self, orientation, minutes=None):
        self.open()
        if self.value() == orientation:
            self.select('Portrait' if orientation == 'Landscape' else 'Landscape')
        self.select(orientation)
        self.open()
        self.android.assert_wait(self.value, orientation, '开始拍摄前重新进入设置确认方向', 15)
        if minutes is not None:
            commands = BleMediaCommands(self.android)
            self.android.assert_wait(lambda: commands._read_duration('Video Duration'), minutes * 60,
                                     '开始录像前重新进入设置确认时长', 15)
        self.android.log('capture-settings-before-trigger', {'orientation': self.value(), 'minutes': minutes})
        self.android.capture(f'before-capture-{orientation.lower()}')


def test_shooting_orientation(android):
    page = ShootingOrientation(android)
    page.open()
    original = page.value()
    try:
        if original == 'Portrait':
            page.select('Landscape')
        page.select('Portrait')
        page.select('Landscape')
    finally:
        if page.value() != original:
            page.select(original)


def displayed_size(data, kind, ffprobe):
    if kind == 'image':
        with Image.open(BytesIO(data)) as image:
            return ImageOps.exif_transpose(image).size
    with tempfile.TemporaryDirectory() as directory:
        file = Path(directory) / 'capture.mp4'
        file.write_bytes(data)
        return video_dimensions(next(stream for stream in probe_video(ffprobe, file)['streams']
                                     if stream['codec_type'] == 'video'))


def probe_video(ffprobe, file, *options):
    result = subprocess.run([ffprobe, '-v', 'error', *options, '-show_streams',
                             '-show_format', '-of', 'json', str(file)],
                            check=True, capture_output=True, timeout=90)
    return json.loads(result.stdout)


def video_dimensions(stream):
    width, height = stream['width'], stream['height']
    rotation = next((item['rotation'] for item in stream.get('side_data_list', []) if 'rotation' in item),
                    stream.get('tags', {}).get('rotate', 0))
    return (height, width) if round(float(rotation)) % 180 == 90 else (width, height)


def file_versions(adb, serial, package):
    output = adb.shell(serial, 'run-as', package, 'find', 'files/media', '-type', 'f',
                       '-exec', 'stat', '-c', shlex.quote('%i|%s|%y|%n'), '{}', '+')
    return {path: version for version, path in (line.rsplit('|', 1) for line in output.splitlines())}


def imported_capture(android, gallery, adb, before, kind, timeout=300):
    gallery.import_from('home', timeout=timeout)

    def changed_files():
        after = file_versions(adb, android.context['phone'], gallery.package)
        changed = {path for path, version in after.items() if before.get(path) != version}
        # G5 can reuse a filename and database row after a prior import.
        return {path for path in gallery.imported_files(kind).values() if path and
                'files/media/' + posixpath.normpath(path).rsplit('/files/media/', 1)[-1] in changed}

    paths = android.wait(lambda: matches if len(matches := changed_files()) == 1 else None,
                         'APP 中唯一的本轮导入媒资文件', 30)
    return next(iter(paths))


def verify_captured_orientation(android, kind, record_property):
    ffprobe = shutil.which('ffprobe') if kind == 'video' else None
    if kind == 'video' and not ffprobe:
        raise TestBlocked('需要 ffprobe 读取视频尺寸和旋转信息。')
    page = ShootingOrientation(android)
    gallery = GalleryPage(android)
    commands = BleMediaCommands(android)
    adb = Adb()
    serial = android.context['phone']
    if gallery.pending_count_or_zero('home'):
        gallery.import_from('home')
    page.open()
    original = page.value()
    mismatches = []
    measurements = []
    media_label = '照片' if kind == 'image' else '视频'
    try:
        for orientation in ('Landscape', 'Portrait'):
            before = file_versions(adb, serial, gallery.package)
            if kind == 'image':
                page.confirm_before_capture(orientation)
                commands.take_photo()
            else:
                commands.record_video(duration=8, before_start=lambda: page.confirm_before_capture(orientation))
            android.assert_wait(lambda: gallery.pending_count_or_zero('home'), 1,
                                '本次拍摄新增一条待导入媒资', 60)
            path = imported_capture(android, gallery, adb, before, kind)
            data = adb.run('-s', serial, 'exec-out', 'run-as', gallery.package,
                           'cat', shlex.quote(path), binary=True, timeout=60)
            width, height = displayed_size(data, kind, ffprobe)
            byte_size = len(data)
            direction = '横屏' if orientation == 'Landscape' else '竖屏'
            measurements.append(f'设为{direction}的{media_label}：{width}×{height}，'
                                f'{byte_size / 1024**2:.2f} MiB（{byte_size:,} 字节）')
            record_property('studio_detail', '｜'.join(measurements))
            android.log('capture-media-orientation', dict(kind=kind, orientation=orientation,
                                                         width=width, height=height, bytes=byte_size))
            if not (width > height if orientation == 'Landscape' else height > width):
                mismatches.append(f'{direction}{media_label}方向不符。')
            android.capture(f'{kind}-{orientation.lower()}-imported')
            page.open()
    finally:
        if not gallery.all('video_orientation'):
            page.open()
        if page.value() != original:
            page.select(original)
    assert not mismatches, ' '.join(mismatches)


def test_photo_orientation(android, record_property):
    verify_captured_orientation(android, 'image', record_property)


def test_video_orientation(android, record_property):
    verify_captured_orientation(android, 'video', record_property)


def select_video_limit(android, commands, minutes):
    label = 'Video Duration'
    expected = minutes * 60
    current = commands._read_duration(label)
    commands._duration_row(label).click()
    options = lambda: [item for item in android.driver.find_elements(
        'id', commands.package + ':id/tv_label') if item.is_displayed()]
    choices = android.wait(options, '录像时长选项', 10)
    matches = [item for item in choices if commands._seconds(item.text) == expected]
    if len(matches) != 1:
        shown = '、'.join(item.text for item in choices)
        android.driver.press_keycode(4)
        raise TestBlocked(f'APP 未提供唯一的 {minutes} 分钟录像选项。当前选项：{shown}')
    if current == expected:
        # Tapping the currently selected row does not dismiss the dialog.
        android.driver.press_keycode(4)
        android.log('video-limit-already-selected', expected)
    else:
        matches[0].click()
    android.assert_wait(lambda: bool(options()), False, '录像时长弹窗关闭', 12)
    android.assert_wait(lambda: commands._read_duration(label), expected, '录像时长设置回显', 15)
    android.capture(f'video-limit-{minutes}min')


def save_imported_video(adb, serial, package, remote, output):
    temporary = output.with_suffix('.part')
    try:
        with temporary.open('wb') as stream:
            subprocess.run([adb.executable, '-s', serial, 'exec-out', 'run-as', package,
                            'cat', shlex.quote(remote)], stdout=stream, stderr=subprocess.PIPE,
                           check=True, timeout=180, creationflags=0x08000000 if os.name == 'nt' else 0)
        if not temporary.stat().st_size:
            raise AssertionError('导入的录像为空文件。')
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def inspect_saved_video(ffprobe, ffmpeg, path):
    data = probe_video(ffprobe, path, '-show_packets', '-show_entries',
                       'packet=stream_index,pts_time:stream:format')
    video = next(stream for stream in data['streams'] if stream['codec_type'] == 'video')
    width, height = video_dimensions(video)
    duration = float(video.get('duration') or data['format']['duration'])
    fps = float(Fraction(video['avg_frame_rate']))
    timestamps = sorted(float(packet['pts_time']) for packet in data.get('packets', [])
                        if packet['stream_index'] == video['index'] and 'pts_time' in packet)
    gaps = sum(right - left > 1.5 / fps for left, right in zip(timestamps, timestamps[1:]))
    audio = any(stream['codec_type'] == 'audio' for stream in data['streams'])
    decoded = subprocess.run([ffmpeg, '-v', 'error', '-xerror', '-i', str(path), '-map', '0:v:0',
                              '-map', '0:a?', '-f', 'null', '-'], capture_output=True, timeout=180)
    return dict(width=width, height=height, duration=duration, fps=fps, bytes=path.stat().st_size,
                gaps=gaps, audio=audio, decode_ok=decoded.returncode == 0)


def verify_video_auto_stop(android, minutes, record_property, target, orientations):
    ffprobe, ffmpeg = shutil.which('ffprobe'), shutil.which('ffmpeg')
    if not ffprobe or not ffmpeg:
        pytest.skip('需要 ffprobe 和 ffmpeg 检查录像文件。')
    gallery, page, commands = GalleryPage(android), ShootingOrientation(android), BleMediaCommands(android)
    adb = Adb()
    serial = android.context['phone']
    if gallery.pending_count_or_zero('home'):
        gallery.import_from('home')
    page.open()
    original = page.value()
    results, failures = [], []
    try:
        for orientation in orientations:
            direction = '横屏' if orientation == 'Landscape' else '竖屏'
            try:
                select_video_limit(android, commands, minutes)
            except TestBlocked as exc:
                record_property('studio_status', 'BLOCKED')
                pytest.skip(str(exc))
            before = file_versions(adb, serial, gallery.package)
            page.confirm_before_capture(orientation, minutes)
            commands.start_video()
            started = time.monotonic()
            gallery.open_home()

            def pending_video():
                if not gallery.all('devices_title'):
                    gallery.open_home()
                try:
                    return gallery.home_import_count()
                except TestBlocked:
                    return 0

            limit = minutes * 60 + 45
            stopped_automatically = True
            try:
                android.assert_wait(pending_video, 1,
                                    f'{minutes} 分钟录像自动停止后产生一条媒资', limit)
            except AssertionError:
                stopped_automatically = False
                failures.append(f'{direction}等待 {limit} 秒后仍未观察到自动停止。')
                android.log('g5-auto-stop-timeout', {'orientation': orientation, 'seconds': limit})
                # Stop only after the observation has failed, to save the diagnostic clip.
                commands.stop_video()
                android.assert_wait(lambda: gallery.pending_count_or_zero('home'), 1,
                                    '超时后停止录像产生诊断媒资', 60)
            elapsed = time.monotonic() - started
            remote = imported_capture(android, gallery, adb, before, 'video',
                                      timeout=max(300, minutes * 60 + 120))
            path = target / f'G5-{minutes}min-{orientation.lower()}.mp4'
            save_imported_video(adb, serial, gallery.package, remote, path)
            stats = inspect_saved_video(ffprobe, ffmpeg, path)
            android.log('g5-video-auto-stop', dict(orientation=orientation, target_seconds=minutes * 60,
                                                   media_seen_seconds=elapsed, file=path.name,
                                                   stopped_automatically=stopped_automatically, **stats))
            width, height, duration = stats['width'], stats['height'], stats['duration']
            stop_label = '自动停止' if stopped_automatically else '超时后停止'
            results.append(f'{direction} {stop_label}／{duration:.2f}s／{width}×{height}／{stats["fps"]:.2f} fps／'
                           f'{stats["bytes"] / 1024**2:.2f} MiB／帧间隔异常 {stats["gaps"]}，'
                           f'音轨{"有" if stats["audio"] else "无"}，'
                           f'解码{"正常" if stats["decode_ok"] else "失败"}')
            record_property('studio_detail', '｜'.join(results))
            if abs(duration - minutes * 60) > 2:
                failures.append(f'{direction}时长超出 ±2s。')
            if not (width > height if orientation == 'Landscape' else height > width):
                failures.append(f'{direction}方向不符。')
            if not stats['decode_ok'] or not stats['audio']:
                failures.append(f'{direction}录像解码失败或缺少音轨。')
            page.open()
    finally:
        if not gallery.all('video_orientation'):
            page.open()
        if page.value() != original:
            page.select(original)
    assert not failures, ' '.join(failures)


@pytest.mark.parametrize('minutes', [1, 3, 5, 7, 10], ids=lambda minutes: f'{minutes}min')
def test_video_auto_stop(android, minutes, record_property, tmp_path):
    target = Path(os.environ.get('GLASSES_EVIDENCE_DIR') or tmp_path)
    verify_video_auto_stop(android, minutes, record_property, target, ('Landscape', 'Portrait'))

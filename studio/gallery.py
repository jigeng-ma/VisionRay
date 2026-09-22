"""G 系列相册、媒资导入和空间用例的公共页面动作。"""
import os
import re
import sqlite3
import tempfile
import io
import shutil
from .errors import TestBlocked


class GalleryPage:
    def __init__(self, android):
        self.a = android
        self.d = android.driver
        self.package = android.context['config']['package']

    def all(self, resource):
        return [e for e in self.d.find_elements('id', self.package + ':id/' + resource)
                if e.is_displayed()]

    def one(self, resource, label=None, timeout=12):
        def visible():
            found = self.all(resource)
            if len(found) > 1:
                raise AssertionError(f'{resource} 匹配不唯一。')
            return found[0] if found else None
        return self.a.wait(visible, label or resource, timeout)

    def open(self):
        self.a.ensure_foreground()
        tabs = []
        for _ in range(4):
            tabs = [e for e in self.all('tabIcon') if e.is_enabled()]
            if tabs:
                break
            self.d.press_keycode(4)
        if not tabs:
            raise TestBlocked('未显示底部导航，请先完成首次引导。')
        if len(tabs) < 2:
            raise TestBlocked('未显示相册入口，请先完成首次引导。')
        tabs[1].click()
        # 相册会保留上次滚动位置；标题滚出屏幕后先回到顶部再断言。
        for _ in range(6):
            if self.all('gallery_title'):
                break
            size = self.d.get_window_size()
            self.d.swipe(size['width'] // 2, int(size['height'] * .30),
                         size['width'] // 2, int(size['height'] * .82), 300)
        title = self.one('gallery_title', 'Gallery 页面')
        assert title.text == 'Gallery'
        return self

    def open_home(self):
        """回到首页，以便读取首页的待导入卡片。"""
        self.a.ensure_foreground()
        # 与首页类用例保持一致：未绑定时先执行可恢复的配对准备。
        from .home_device import HomeDevicePage
        HomeDevicePage(self.a).home()
        tabs = []
        for _ in range(4):
            tabs = [e for e in self.all('tabIcon') if e.is_enabled()]
            if tabs:
                break
            self.d.press_keycode(4)
        if not tabs:
            raise TestBlocked('未显示首页入口，请先完成首次引导。')
        tabs[0].click()
        self.one('devices_title', '首页')
        return self

    def import_card(self):
        # 当前版本首页和空间页均使用状态通知卡片；旧版本空间页使用 import_file。
        status = self.all('status_title_tv')
        if len(status) > 1:
            raise AssertionError('待导入媒资通知匹配不唯一。')
        if status:
            return status[0]
        cards = self.all('import_file')
        if len(cards) > 1:
            raise AssertionError('待导入媒资卡片匹配不唯一。')
        return cards[0] if cards else None

    def require_import_card(self):
        card = self.import_card()
        if not card:
            raise TestBlocked('眼镜没有待导入媒资；请准备图片、视频、录音后重试。')
        button = self.one('status_action_btn' if self.all('status_title_tv') else 'import_btn', '导入按钮')
        if not button.is_enabled():
            raise TestBlocked('待导入媒资卡片存在，但导入按钮不可用。')
        return card, button

    @staticmethod
    def _card_text(card):
        values = [card.text.strip()]
        values += [e.text.strip() for e in card.find_elements('xpath', './/*[@text]')]
        return [value for value in values if value]

    def import_count(self):
        """读取待导入卡片上的媒资数；格式不明确时不猜测。"""
        card, _ = self.require_import_card()
        values = self._card_text(card)
        # 当前版本在 tv_import_title/tv_import_subtitle 中显示单个待导入数量。
        numbers = {int(value) for text in values
                   for value in re.findall(r'(?<!\d)(\d+)(?!\d)', text)}
        if len(numbers) != 1:
            raise TestBlocked('无法从待导入卡片唯一解析媒资数量：' + ' | '.join(values))
        return numbers.pop()

    def pending_count_on(self, surface):
        if surface == 'home':
            self.open_home()
            return self.home_import_count()
        elif surface == 'gallery':
            self.open()
        else:
            raise ValueError('surface 仅支持 home 或 gallery。')
        return self.import_count()

    def home_import_count(self):
        """首页通知使用 status_title_tv，例如 ``Found 13 Items``。"""
        notices = self.all('status_title_tv')
        if len(notices) != 1:
            raise TestBlocked('首页没有待导入媒资通知。')
        values = re.findall(r'(?<!\d)(\d+)(?!\d)', notices[0].text)
        if len(values) != 1:
            raise TestBlocked('无法从首页媒资通知解析数量：' + notices[0].text)
        return int(values[0])

    def assert_pending_counts(self, expected):
        """首页与空间页展示的待导入数量必须一致且等于 expected。"""
        actual = {surface: self.pending_count_on(surface) for surface in ('home', 'gallery')}
        assert actual == {'home': expected, 'gallery': expected}, (
            f'待导入媒资数量不符：期望 {expected}，实际首页 {actual["home"]}、空间页 {actual["gallery"]}。')
        self.a.log('pending-media-count', actual)

    def pending_count_or_zero(self, surface):
        if surface == 'home':
            self.open_home()
            return self.home_import_count() if self.all('status_title_tv') else 0
        elif surface == 'gallery':
            self.open()
        else:
            raise ValueError('surface 仅支持 home 或 gallery。')
        return self.import_count() if self.import_card() else 0

    def _unscrolled_count(self, container, item, label):
        root = self.one(container, label)
        if root.get_attribute('scrollable') == 'true':
            raise TestBlocked(f'{label}可滚动，当前版本无法可靠读取全部媒资数。')
        return len(self.all(item))

    def _media_counts_from_database(self):
        """以 APP 的 file_metadata 记录作为跨页媒资总数的唯一来源。"""
        from .devices import Adb
        phone = self.a.context.get('phone')
        if not phone:
            raise TestBlocked('缺少手机序列号，无法读取媒资数据库。')
        try:
            adb = Adb()
            with tempfile.TemporaryDirectory() as directory:
                path = os.path.join(directory, 'nova_app_database')
                for suffix in ('', '-wal', '-shm'):
                    try:
                        data = adb.run('-s', phone, 'exec-out', 'run-as', self.package,
                                       'cat', 'databases/nova_app_database' + suffix, binary=True)
                    except Exception:
                        if suffix == '':
                            raise
                        continue
                    with open(path + suffix, 'wb') as file:
                        file.write(data)
                database = sqlite3.connect(path)
                rows = database.execute(
                    'select file_type, count(*) from file_metadata group by file_type'
                ).fetchall()
                database.close()
        except Exception as error:
            raise TestBlocked('无法读取 APP 媒资数据库：' + str(error)) from error
        result = dict(rows)
        return {'image': result.get('image', 0), 'video': result.get('video', 0),
                'audio': result.get('audio', 0)}

    def gallery_media_count(self):
        self.open()
        counts = self._media_counts_from_database()
        return {'image': counts['image'], 'video': counts['video'],
                'total': counts['image'] + counts['video']}

    def recorder_media_count(self):
        self.open_home()
        recorder = [e for e in self.all('tv_grid_title') if e.text == 'Recorder']
        if len(recorder) != 1:
            raise TestBlocked('首页未唯一找到 Recorder 入口。')
        recorder[0].click()
        self.one('rv_audio_list', '录音机列表')
        try:
            return self._media_counts_from_database()['audio']
        finally:
            self.d.press_keycode(4)
            self.a.wait(lambda: self.all('devices_title'), '从录音机返回首页', 12)

    def imported_totals(self):
        """图片加视频在空间页统计，录音在首页 Recorder 统计。"""
        gallery = self.gallery_media_count()
        recorder = self.recorder_media_count()
        result = dict(gallery, recorder=recorder, total=gallery['total'] + recorder)
        self.a.log('imported-media-total', result)
        return result

    def import_from(self, surface):
        """在指定入口导入，并返回导入前卡片显示的真实数量。"""
        before = self.pending_count_on(surface)
        button = self.one('status_action_btn' if self.all('status_title_tv') else 'import_btn', '导入按钮')
        if not button.is_enabled():
            raise TestBlocked('待导入媒资卡片存在，但导入按钮不可用。')
        button.click()
        if self.all('status_title_tv'):
            self.a.wait(lambda: not self.all('status_title_tv'), '导入完成', 120)
        else:
            self.a.wait(lambda: not self.import_card(), '空间页导入完成', 120)
        # 导入完成后，两个入口都不应继续显示同一批待导入媒资。
        self.open_home()
        assert not self.import_card(), '首页导入完成后仍显示待导入媒资卡片。'
        self.open()
        assert not self.import_card(), '空间页导入完成后仍显示待导入媒资卡片。'
        self.a.log('imported-media-count', {'surface': surface, 'count': before})
        return before

    def media(self, minimum=1):
        # 当前 APP 的空间缩略图使用 iv_photo；旧版本使用 iv_media。
        items = self.all('iv_photo') or self.all('iv_media')
        if len(items) < minimum:
            raise TestBlocked(f'相册需要至少 {minimum} 个已导入测试媒资，当前为 {len(items)} 个。')
        return items

    def preview_first(self):
        self.media()[0].click()
        self.a.wait(lambda: self.all('media_actions') or self.all('playerView') or self.all('play_btn'),
                    '媒体预览页', 12)

    def action(self, resource, label):
        button = self.one(resource, label)
        if not button.is_enabled():
            raise TestBlocked(f'{label} 不可用。')
        button.click()

    def require_delete_permission(self):
        if os.environ.get('GLASSES_ALLOW_MEDIA_DELETE') != '1':
            raise TestBlocked('删除用例需要设置 GLASSES_ALLOW_MEDIA_DELETE=1，并仅准备可删除的测试媒资。')

    def confirm_delete(self, also_phone=False):
        self.require_delete_permission()
        self.action('ll_delete', '删除')
        if also_phone:
            checkbox = self.one('delete_radiobutton', '同时从手机相册删除')
            if checkbox.get_attribute('checked') != 'true':
                checkbox.click()
        confirm = self.a.wait(lambda: next((e for e in self.all('tv_confirm') if e.text), None), '确认删除按钮', 10)
        confirm.click()
        self.a.wait(lambda: not self.all('tv_confirm'), '删除确认弹窗关闭', 15)

    def download(self):
        self.action('ll_download', '下载')
        self.a.wait(lambda: not self.all('ll_download') or self.one('ll_download').is_enabled(), '下载完成', 60)

    def share(self):
        self.action('ll_share', '分享')
        self.a.wait(lambda: self.d.current_package != self.package, '系统分享面板', 12)

    def assert_visionray_watermark(self, video=False):
        """OCR 校验详情页实际渲染的水印，图片取底部、视频取左下角。"""
        try:
            from PIL import Image
            import pytesseract
        except ImportError as error:
            raise TestBlocked('缺少图片 OCR 依赖，无法校验水印。') from error
        executable = os.environ.get('TESSERACT_CMD') or shutil.which('tesseract')
        if not executable:
            raise TestBlocked('未找到 Tesseract；请将 tesseract.exe 加入系统 PATH，或设置 TESSERACT_CMD。')
        pytesseract.pytesseract.tesseract_cmd = executable
        image = Image.open(io.BytesIO(self.d.get_screenshot_as_png()))
        width, height = image.size
        crop = image.crop((0, int(height * (.72 if video else .80)), int(width * (.58 if video else 1)), height))
        crop = crop.resize((crop.width * 4, crop.height * 4))
        # 白色视频水印在深色画面上常被 OCR 分为 "VIS"、"ion" 等片段；合并所有识别结果。
        texts = [pytesseract.image_to_string(crop, config=f'--psm {mode}').lower() for mode in (6, 11)]
        compact = ''.join(re.sub(r'[^a-z]', '', value) for value in texts)
        if 'visionray' not in compact:
            self.a.capture('watermark-not-found')
            raise AssertionError('详情页目标水印区域未识别到 VisionRay：' + ' | '.join(value.strip() for value in texts))
        self.a.log('watermark-ocr', {'video': video, 'text': texts})

    def assert_latest_video_duration(self, expected_seconds, tolerance=5):
        """读取最新视频缩略图卡片显示的 mm:ss，并允许给定误差。"""
        self.open()
        card = self.media()[0].find_element('xpath', '..')
        values = [e.text for e in card.find_elements('xpath', './/*[@text]') if e.text]
        matches = [value for value in values if re.fullmatch(r'\d{1,2}:\d{2}', value.strip())]
        if len(matches) != 1:
            raise TestBlocked('无法从最新视频缩略图唯一读取时长：' + ' | '.join(values))
        minutes, seconds = map(int, matches[0].split(':'))
        actual = minutes * 60 + seconds
        if abs(actual - expected_seconds) > tolerance:
            raise AssertionError(f'视频缩略图时长应为 {expected_seconds}±{tolerance} 秒，实际 {matches[0]}。')
        self.a.log('video-thumbnail-duration', {'actual': actual, 'expected': expected_seconds})

    def play_pause(self):
        self.action('play_btn', '播放')
        self.one('pause_btn', '暂停播放')
        self.d.find_element('id', self.package + ':id/playerView').click()
        self.one('pause_btn', '点击空白区后仍播放')
        self.action('pause_btn', '暂停播放')
        self.one('play_btn', '暂停后播放按钮')

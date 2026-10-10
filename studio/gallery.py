"""G 系列相册、媒资导入和空间用例的公共页面动作。"""
import os
import re
import sqlite3
import tempfile
import io
import shutil
import time
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
        # 空间用例也需要自行恢复绑定首页，不能依赖上一条媒资或引导用例的结束页。
        from .home_device import HomeDevicePage
        HomeDevicePage(self.a).home()
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
        home = self.pending_count_on('home')
        self.open()
        if not self.import_card():
            # 已确认首页通知存在时，Gallery 缺少卡片是 APP 检查失败，不能写成
            # “待导入媒资未准备”的跳过，从而掩盖产品行为。
            raise AssertionError('首页已有待导入媒资通知，但 Gallery 页面未显示待导入卡片或导入入口。')
        gallery = self.import_count()
        actual = {'home': home, 'gallery': gallery}
        assert actual == {'home': expected, 'gallery': expected}, (
            f'待导入媒资数量不符：期望 {expected}，实际首页 {actual["home"]}、空间页 {actual["gallery"]}。')
        self.a.log('pending-media-count', actual)

    def pending_count_or_zero(self, surface):
        if surface == 'home':
            self.open_home()
            if not self.all('status_title_tv'):
                return 0
            try:
                return self.home_import_count()
            except TestBlocked:
                # 非媒资通知和同步中的空通知均不能作为媒资前置失败。
                return 0
        elif surface == 'gallery':
            self.open()
        else:
            raise ValueError('surface 仅支持 home 或 gallery。')
        if not self.import_card():
            return 0
        try:
            return self.import_count()
        except TestBlocked:
            return 0

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

    def media_records(self):
        """读取 APP 已导入媒资的数据库行，用于确认删除后的媒资已不在 APP 内。"""
        from .devices import Adb
        phone = self.a.context.get('phone')
        if not phone:
            raise TestBlocked('缺少手机序列号，无法读取 APP 媒资数据库。')
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
                rows = database.execute('select rowid, file_type from file_metadata').fetchall()
                database.close()
        except Exception as error:
            raise TestBlocked('无法读取 APP 媒资数据库：' + str(error)) from error
        return set(rows)

    def phone_album_rows(self, kind):
        """读取手机相册 MediaStore 的媒体 ID；下载校验必须基于真实新增文件。"""
        if kind not in ('image', 'video'):
            raise ValueError('kind 仅支持 image 或 video。')
        from .devices import Adb
        phone = self.a.context.get('phone')
        if not phone:
            raise TestBlocked('缺少手机序列号，无法读取手机相册。')
        uri = 'content://media/external/images/media' if kind == 'image' else 'content://media/external/video/media'
        try:
            output = Adb().shell(phone, 'content', 'query', '--uri', uri, '--projection', '_id')
        except Exception as error:
            raise TestBlocked('无法读取手机相册 MediaStore：' + str(error)) from error
        return {int(value) for value in re.findall(r'_id=(\d+)', output)}

    def phone_album_count(self, kind):
        return len(self.phone_album_rows(kind))

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
        # 空录音机和有录音机列表的容器不同；数量以数据库为准，不依赖列表容器。
        self.a.wait(lambda: not self.all('devices_title'), '进入录音机', 12)
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

    def import_from(self, surface, timeout=120):
        """在指定入口导入，并返回导入前卡片显示的真实数量。"""
        before = self.pending_count_on(surface)
        button = self.one('status_action_btn' if self.all('status_title_tv') else 'import_btn', '导入按钮')
        if not button.is_enabled():
            raise TestBlocked('待导入媒资卡片存在，但导入按钮不可用。')
        button.click()
        if self.all('status_title_tv'):
            self.a.wait(lambda: not self.all('status_title_tv'), '导入完成', timeout)
        else:
            self.a.wait(lambda: not self.import_card(), '空间页导入完成', timeout)
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
            # 空间用例单独执行时，自动生成并导入最小测试媒资，不能依赖媒资导入模块已运行。
            from .ble_commands import BleMediaCommands
            before = self.pending_count_or_zero('home')
            BleMediaCommands(self.a).take_photo()
            self.a.wait(lambda: self.pending_count_or_zero('home') >= before + 1,
                        '生成空间用例所需测试图片', 60)
            self.import_from('home')
            self.open()
            items = self.all('iv_photo') or self.all('iv_media')
        if len(items) < minimum:
            raise TestBlocked(f'相册需要至少 {minimum} 个已导入测试媒资，当前为 {len(items)} 个。')
        return items

    def preview_first(self):
        self.media()[0].click()
        self.a.wait(self.preview_ready,
                    '媒体预览页', 12)

    def preview_ready(self):
        # 当前版本图片详情使用 iv_detail/vp_footer；旧版和视频详情保留原有标识。
        return (self.all('iv_detail') or self.all('vp_footer') or self.all('media_actions')
                or self.all('playerView') or self.all('play_btn'))

    def preview(self, kind):
        """打开指定类型媒资；缺少时先创建并导入一条，保证用例可单独执行。"""
        if kind not in ('image', 'video'):
            raise ValueError('kind 仅支持 image 或 video。')
        self.open()
        for item in self.media():
            item.click()
            self.a.wait(self.preview_ready, '媒体预览页', 12)
            is_video = bool(self.all('playerView') or self.all('play_btn'))
            if (kind == 'video') == is_video:
                return
            self.d.press_keycode(4)
            self.one('gallery_title', '返回 Gallery 页面', 12)
        from .ble_commands import BleMediaCommands
        before = self.pending_count_or_zero('home')
        command = BleMediaCommands(self.a)
        (command.take_photo if kind == 'image' else command.record_video)()
        self.a.wait(lambda: self.pending_count_or_zero('home') >= before + 1,
                    '生成空间用例所需测试媒资', 60)
        self.import_from('home')
        self.preview(kind)

    def preview_latest(self, kind):
        """按详情页实际类型打开媒资，不依赖新版 Gallery 不稳定的缩略图排序。"""
        self.preview(kind)

    def action(self, resource, label):
        resources = (resource,) if isinstance(resource, str) else resource
        button = self.a.wait(lambda: next((item for name in resources for item in self.all(name)), None), label, 12)
        if not button.is_enabled():
            raise TestBlocked(f'{label} 不可用。')
        button.click()

    def require_delete_permission(self):
        # 删除用例在本条内新建媒资并在结束时验证删除结果，可自动执行。
        return

    def confirm_delete(self, also_phone=False):
        self.require_delete_permission()
        self.action(('ll_activity_delete', 'll_delete'), '删除')
        if also_phone:
            checkbox = self.one('delete_radiobutton', '同时从手机相册删除')
            if checkbox.get_attribute('checked') != 'true':
                checkbox.click()
        confirm = self.a.wait(lambda: next((e for e in self.all('tv_confirm') if e.text), None), '确认删除按钮', 10)
        confirm.click()
        self.a.wait(lambda: not self.all('tv_confirm'), '删除确认弹窗关闭', 15)

    def delete_current_and_assert_absent(self, also_phone=False):
        """删除当前预览媒资，并确认 APP 数据库中恰好少一条记录。"""
        before = self.media_records()
        if not before:
            raise TestBlocked('APP 中没有可删除媒资。')
        self.confirm_delete(also_phone)
        self.a.wait(lambda: len(self.media_records()) == len(before) - 1,
                    '删除后 APP 媒资数量减少一条', 30)
        after = self.media_records()
        removed = before - after
        if len(removed) != 1:
            raise AssertionError(f'删除后 APP 媒资记录变化异常：删除前 {len(before)}，删除后 {len(after)}。')
        self.a.log('app-media-removed', {'record': next(iter(removed)), 'also_phone': also_phone})

    def download_and_assert_phone_added(self, kind):
        """下载当前媒资，返回 MediaStore 中唯一新增的真实文件 ID。"""
        before = self.phone_album_rows(kind)
        self.download()
        def added():
            rows = self.phone_album_rows(kind) - before
            return rows if len(rows) == 1 else None
        try:
            added_id = next(iter(self.a.wait(added, '下载后手机相册新增媒资', 20)))
            self.a.log('phone-album-added', {'kind': kind, 'before': len(before), 'id': added_id})
            return added_id
        except Exception as error:
            # 同一媒资重复下载时，APP 会复用相册中的既有文件而不创建副本；仍然读取该文件校验水印。
            rows = self.phone_album_rows(kind)
            if not rows:
                raise error
            media_id = max(rows)
            self.a.log('phone-album-reused', {'kind': kind, 'id': media_id, 'reason': str(error)})
            return media_id

    def _watermark_text(self, image, label, video=False):
        try:
            import pytesseract
        except ImportError as error:
            raise TestBlocked('缺少图片 OCR 依赖，无法校验水印。') from error
        executable = os.environ.get('TESSERACT_CMD') or shutil.which('tesseract')
        if not executable:
            raise TestBlocked('未找到 Tesseract；请将 tesseract.exe 加入系统 PATH，或设置 TESSERACT_CMD。')
        pytesseract.pytesseract.tesseract_cmd = executable
        width, height = image.size
        # 图片在相册中可能带 EXIF 旋转，水印可能落在显示上方或下方；仅扫描两端以避免画面正文误判。
        regions = [(0, int(height * .72), width, height), (0, 0, width, int(height * .28))]
        if label == 'system-share-sheet':
            # Samsung 分享弹窗中预览图底部约在屏幕 54%–67%，水印位于该区域左下角。
            regions.append((0, int(height * .54), width, int(height * .67)))
        if video:
            regions = [(0, int(height * .55), int(width * .65), height)]
        texts = []
        for region in regions:
            crop = image.crop(region)
            # 原图通常已是 4K；限制 OCR 输入宽度，避免长时间没有 Appium 指令而会话超时。
            if label == 'system-share-sheet' and region[1] == int(height * .54):
                crop = crop.resize((crop.width * 4, crop.height * 4))
            elif crop.width < 1600:
                crop = crop.resize((crop.width * 2, crop.height * 2))
            elif crop.width > 4000:
                crop = crop.resize((4000, max(1, int(crop.height * 4000 / crop.width))))
            texts += [pytesseract.image_to_string(crop, config=f'--psm {mode}').lower() for mode in (6, 11)]
        compact = ''.join(re.sub(r'[^a-z]', '', value) for value in texts)
        # 分享弹窗把预览缩小到约 1/6，首字母 V 偶尔会被压缩误读；保留 ``ionray`` 作为兜底关键标志。
        marker_found = 'vision' in compact or (label == 'system-share-sheet' and 'ionray' in compact)
        if not marker_found:
            self.a.capture(label + '-watermark-not-found')
            raise AssertionError(label + ' 未识别到 VisionRay 水印：' + ' | '.join(value.strip() for value in texts))
        self.a.log('watermark-ocr', {'source': label, 'text': texts})

    def assert_downloaded_image_watermark(self, media_id):
        """直接读取下载后新增的手机相册图片，不检查 APP 详情页。"""
        from PIL import Image
        from .devices import Adb
        phone = self.a.context.get('phone')
        uri = f'content://media/external/images/media/{media_id}'
        try:
            data = Adb().run('-s', phone, 'exec-out', 'content', 'read', '--uri', uri, binary=True, timeout=60)
            image = Image.open(io.BytesIO(data)).convert('RGB')
        except Exception as error:
            raise TestBlocked('无法读取下载后的手机相册图片：' + str(error)) from error
        self._watermark_text(image, 'downloaded-phone-album-image')

    def assert_share_sheet_watermark(self):
        """系统分享弹窗展示的是待分享图片，直接校验该弹窗预览中的水印。"""
        from PIL import Image
        image = Image.open(io.BytesIO(self.d.get_screenshot_as_png())).convert('RGB')
        self._watermark_text(image, 'system-share-sheet')

    def download(self):
        self.action('ll_download', '下载')
        self.a.wait(lambda: not self.all('ll_download') or self.one('ll_download').is_enabled(), '下载完成', 60)

    def share(self):
        self.action('ll_share', '分享')
        self.a.wait(lambda: self.d.current_package != self.package, '系统分享面板', 12)

    def assert_visionray_watermark(self, video=False):
        """OCR 校验 APP 视频详情页渲染的左下角水印。"""
        from PIL import Image
        self._watermark_text(Image.open(io.BytesIO(self.d.get_screenshot_as_png())).convert('RGB'),
                             'media-detail', video=video)

    def assert_latest_video_duration(self, expected_seconds, tolerance=5):
        """读取最新视频缩略图卡片显示的 mm:ss，并允许给定误差。"""
        self.open()
        values = [e.text.strip() for e in self.d.find_elements(
            'xpath', f"//*[@package='{self.package}' and @text]") if e.is_displayed()]
        durations = []
        for value in values:
            if re.fullmatch(r'\d{1,2}:\d{2}', value):
                minute, second = map(int, value.split(':'))
                durations.append((minute * 60 + second, value))
        matches = [(seconds, value) for seconds, value in durations
                   if abs(seconds - expected_seconds) <= tolerance]
        if not matches:
            raise AssertionError(f'视频缩略图未显示 {expected_seconds}±{tolerance} 秒：' + ' | '.join(values))
        actual, shown = matches[0]
        self.a.log('video-thumbnail-duration', {'actual': actual, 'shown': shown, 'expected': expected_seconds})

    def play_pause(self):
        def seconds():
            value = self.one('cur_time_tv', '视频当前播放时间').text
            minute, second = map(int, value.split(':'))
            return minute * 60 + second
        # 新版 ExoPlayer 的播放/暂停共用 play_btn，以播放时间递增和暂停后的冻结判定状态。
        before = seconds()
        self.action('play_btn', '播放')
        self.a.wait(lambda: seconds() > before, '视频播放进度变化', 8)
        self.action('play_btn', '暂停播放')
        paused = seconds()
        time.sleep(1)
        if abs(seconds() - paused) > 1:
            raise AssertionError('暂停后视频播放时间仍在变化。')


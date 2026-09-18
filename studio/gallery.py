"""G 系列相册、媒资导入和空间用例的公共页面动作。"""
import os
import re
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
        title = self.one('gallery_title', 'Gallery 页面')
        assert title.text == 'Gallery'
        return self

    def open_home(self):
        """回到首页，以便读取首页的待导入卡片。"""
        self.a.ensure_foreground()
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
        cards = self.all('import_file')
        if len(cards) > 1:
            raise AssertionError('待导入媒资卡片匹配不唯一。')
        return cards[0] if cards else None

    def require_import_card(self):
        card = self.import_card()
        if not card:
            raise TestBlocked('眼镜没有待导入媒资；请准备图片、视频、录音后重试。')
        button = self.one('import_btn', '导入按钮')
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
        elif surface == 'gallery':
            self.open()
        else:
            raise ValueError('surface 仅支持 home 或 gallery。')
        return self.import_count()

    def assert_pending_counts(self, expected):
        """首页与空间页展示的待导入数量必须一致且等于 expected。"""
        actual = {surface: self.pending_count_on(surface) for surface in ('home', 'gallery')}
        assert actual == {'home': expected, 'gallery': expected}, (
            f'待导入媒资数量不符：期望 {expected}，实际首页 {actual["home"]}、空间页 {actual["gallery"]}。')
        self.a.log('pending-media-count', actual)

    def pending_count_or_zero(self, surface):
        if surface == 'home':
            self.open_home()
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

    def gallery_media_count(self):
        self.open()
        total = self._unscrolled_count('recycler_view', 'iv_photo', '空间媒资列表')
        video = len(self.all('iv_video_icon'))
        if video > total:
            raise AssertionError(f'空间视频标识数 {video} 大于媒资总数 {total}。')
        return {'image': total - video, 'video': video, 'total': total}

    def recorder_media_count(self):
        self.open_home()
        recorder = [e for e in self.all('tv_grid_title') if e.text == 'Recorder']
        if len(recorder) != 1:
            raise TestBlocked('首页未唯一找到 Recorder 入口。')
        recorder[0].click()
        self.one('rv_audio_list', '录音机列表')
        try:
            return self._unscrolled_count('rv_audio_list', 'v_play_btn2', '录音机媒资列表')
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
        button = self.one('import_btn', '导入按钮')
        if not button.is_enabled():
            raise TestBlocked('待导入媒资卡片存在，但导入按钮不可用。')
        button.click()
        self.a.wait(lambda: not self.import_card(), '导入完成', 120)
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

    def play_pause(self):
        self.action('play_btn', '播放')
        self.one('pause_btn', '暂停播放')
        self.d.find_element('id', self.package + ':id/playerView').click()
        self.one('pause_btn', '点击空白区后仍播放')
        self.action('pause_btn', '暂停播放')
        self.one('play_btn', '暂停后播放按钮')

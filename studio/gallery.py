"""G 系列相册、媒资导入和空间用例的公共页面动作。"""
import os
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
        tabs = self.a.wait(lambda: [e for e in self.all('tabIcon') if e.is_enabled()], '底部导航', 15)
        if len(tabs) < 2:
            raise TestBlocked('未显示相册入口，请先完成首次引导。')
        tabs[1].click()
        title = self.one('gallery_title', 'Gallery 页面')
        assert title.text == 'Gallery'
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

    def media(self, minimum=1):
        items = self.all('iv_media')
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

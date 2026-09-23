"""My 页面列表项的公共导航和返回校验。"""

from .auth import AuthPage
from .errors import TestBlocked
from .home_device import HomeDevicePage


class MyPage:
    def __init__(self, android):
        self.a = android
        self.d = android.driver
        self.package = android.context['config']['package']

    def open(self):
        AuthPage(self.a).registered()
        HomeDevicePage(self.a).home()
        tabs = [e for e in self.d.find_elements('id', self.package + ':id/tabIcon') if e.is_displayed()]
        if len(tabs) < 3:
            raise TestBlocked('底部导航未找到 My 标签。')
        tabs[-1].click()
        self.a.wait(lambda: self._visible('My') and self._visible('Account'), 'My 页面', 15)

    def _visible(self, text):
        return any(e.is_displayed() and e.text == text for e in self.d.find_elements(
            'xpath', f"//*[@package='{self.package}' and @text]"))

    def row(self, label):
        labels = [e for e in self.d.find_elements('id', self.package + ':id/title')
                  if e.is_displayed() and e.text == label]
        if len(labels) != 1:
            raise AssertionError(f'My 页面未唯一找到 {label}：{len(labels)} 项。')
        return labels[0].find_element('xpath', '..')

    def open_item(self, label, arrow=False):
        row = self.row(label)
        if arrow:
            arrows = [e for e in row.find_elements('id', self.package + ':id/next_iv') if e.is_displayed()]
            if len(arrows) != 1:
                raise AssertionError(f'{label} 未唯一显示 > 图标。')
            arrows[0].click()
        else:
            row.click()
        self.a.wait(lambda: not self._visible('My') or self.d.current_activity.endswith('MyActivity') is False,
                    label + ' 跳转', 15)
        self.a.capture('my-' + label.lower().replace(' ', '-').replace('&', 'and'))

    def back_button(self):
        self.d.press_keycode(4)
        self.a.wait(lambda: self._visible('My') and self._visible('Account'), '返回 My 页面', 15)

    def side_back(self):
        size = self.d.get_window_size()
        y = int(size['height'] * .5)
        self.d.swipe(3, y, int(size['width'] * .7), y, 350)
        self.a.wait(lambda: self._visible('My') and self._visible('Account'), '侧滑返回 My 页面', 15)

    def assert_two_entries(self, label):
        self.open_item(label)
        self.back_button()
        self.open_item(label, arrow=True)
        self.side_back()

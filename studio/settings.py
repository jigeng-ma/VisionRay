"""AI、拍摄及系统设置的最小公共页面动作。"""
from .errors import TestBlocked
from .home_device import HomeDevicePage


class SettingsPage:
    def __init__(self, android):
        self.a = android
        self.home = HomeDevicePage(android)
        self.package = self.home.package

    def ai(self):
        self.home.setting('DP AI')
        self.home.assert_page('DP AI Settings', 'Voice Type')

    def ai_from_history(self):
        """必须从 AI 对话记录页右上角设置进入，不能绕过入口直达设置页。"""
        self.home.home()
        labels = ('AI Conversation History', 'AI Chat History', 'AI Conversation', 'AI Chat')
        entry = next((self.home._labeled('tv_grid_title', label) for label in labels
                      if any(e.is_displayed() and e.text == label for e in self.a.driver.find_elements(
                          'id', self.package + ':id/tv_grid_title'))), None)
        if not entry:
            raise TestBlocked('首页未找到 AI 对话记录入口。')
        entry.click()
        setting = self.a.wait(lambda: next((e for e in self.a.driver.find_elements('xpath',
            f"//*[@package='{self.package}' and (contains(@resource-id, 'setting') or @content-desc='Settings')]")
            if e.is_displayed() and e.is_enabled()), None), 'AI 对话记录页右上角设置按钮', 12)
        setting.click()
        self.home.assert_page('DP AI Settings', 'Voice Type')

    def capture(self):
        self.home.setting('Capture')
        self.home.assert_page('Capture Settings', 'Photo Watermark')

    def system(self):
        self.home.setting('System Settings')
        self.home.assert_system_info()

    def one(self, resource):
        found = [e for e in self.a.driver.find_elements('id', self.package + ':id/' + resource) if e.is_displayed()]
        if len(found) != 1:
            raise AssertionError(f'{resource} 应唯一显示，实际 {len(found)} 项。')
        return found[0]

    def on(self, resource):
        control = self.one(resource)
        if control.get_attribute('checked') != 'true':
            control.click()
        self.a.wait(lambda: self.one(resource).get_attribute('checked') == 'true', resource + ' 已开启', 8)

    def toggle_round_trip(self, resource):
        control = self.one(resource)
        original = control.get_attribute('checked') == 'true'
        control.click()
        self.a.wait(lambda: (self.one(resource).get_attribute('checked') == 'true') != original,
                    resource + ' 切换', 8)
        self.one(resource).click()
        self.a.wait(lambda: (self.one(resource).get_attribute('checked') == 'true') == original,
                    resource + ' 恢复', 8)

    def toggle_labeled(self, labels):
        """按设置文案定位开关，兼容不同版本的 wake-up 资源 ID。"""
        label = next((self.home.text(value, 3) for value in labels
                      if any(e.is_displayed() and e.text == value for e in self.a.driver.find_elements('xpath',
                          f"//*[@package='{self.package}' and @text]"))), None)
        if not label:
            raise TestBlocked('未找到设置项：' + ' / '.join(labels))
        row = label.find_element('xpath', '..')
        switches = [e for e in row.find_elements('xpath', ".//*[@checkable='true']") if e.is_displayed()]
        if len(switches) != 1:
            raise AssertionError('语音唤醒开关未唯一定位。')
        original = switches[0].get_attribute('checked') == 'true'
        switches[0].click()
        self.a.wait(lambda: next((e for e in row.find_elements('xpath', ".//*[@checkable='true']")
                                  if e.is_displayed()), None).get_attribute('checked') == ('false' if original else 'true'),
                    '语音唤醒开关切换', 8)
        row.find_elements('xpath', ".//*[@checkable='true']")[0].click()

    def tutorial(self, title):
        item = self.home.text(title)
        item.find_element('xpath', '..').click()
        self.a.wait(lambda: any(e.is_displayed() and e.text.strip()
                                for e in self.a.driver.find_elements('xpath', '//*[@text]')),
                    title + ' 教程内容', 12)
        self.a.driver.press_keycode(4)
        self.home.text('DP AI Settings', 12)

    def choose_voice(self, value):
        self.one('cl_speaker').click()
        choice = self.a.wait(lambda: next((e for e in self.a.driver.find_elements('xpath',
            f"//*[@package='{self.package}' and @text='{value}']") if e.is_displayed()), None), value, 10)
        choice.click()
        self.a.wait(lambda: self.one('tv_speaker').text == value, '音色切换为 ' + value, 10)

    def set_duration(self, resource, expected):
        self.one(resource).click()
        option = self.a.wait(lambda: next((e for e in self.a.driver.find_elements('id', self.package + ':id/tv_label')
                                           if e.is_displayed() and e.text == expected), None), expected, 10)
        option.click()
        self.a.wait(lambda: not any(e.is_displayed() for e in self.a.driver.find_elements(
            'id', self.package + ':id/tv_label')), '时长弹窗关闭', 10)
        hints = [e.text for e in self.a.driver.find_elements('id', self.package + ':id/tv_hint') if e.is_displayed()]
        if expected not in hints:
            raise AssertionError(f'时长未更新为 {expected}：{hints}')

    def confirm(self, resource, success):
        self.one(resource).click()
        button = self.a.wait(lambda: next((e for e in self.a.driver.find_elements('xpath',
            "//*[@text='OK' or @text='Confirm']") if e.is_displayed() and e.is_enabled()), None), '确认按钮', 10)
        button.click()
        self.home.text(success, 20)

    def factory_reset(self):
        if __import__('os').environ.get('GLASSES_ALLOW_FACTORY_RESET') != '1':
            raise TestBlocked('恢复出厂设置会清空眼镜数据；设置 GLASSES_ALLOW_FACTORY_RESET=1 后执行。')
        self.confirm('factory_reset', 'Factory reset successful')

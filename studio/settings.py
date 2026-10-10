"""AI、拍摄及系统设置的最小公共页面动作。"""
from .errors import TestBlocked
from .home_device import HomeDevicePage
from io import BytesIO


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
        # 当前版本以首页 DP AI 卡片承载对话记录，旧版本则显示 AI Conversation History。
        labels = ('AI Conversation History', 'AI Chat History', 'AI Conversation', 'AI Chat', 'DP AI')
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

    def is_on(self, control):
        # 新版 Compose Switch 的 checkable/checked 恒为 false，以 selected 反映状态。
        if control.get_attribute('checked') == 'true' or control.get_attribute('selected') == 'true':
            return True
        # 当前 Capture 页面开关未暴露可访问状态，读取白色滑块位于控件左/右半边的位置。
        try:
            from PIL import Image
            image = Image.open(BytesIO(self.a.driver.get_screenshot_as_png())).convert('RGB')
            rect = control.rect
            middle = int(rect['x'] + rect['width'] / 2)
            y0, y1 = int(rect['y']), int(rect['y'] + rect['height'])
            pixels = image.load()
            left = right = 0
            for y in range(y0, y1, 2):
                for x in range(int(rect['x']), int(rect['x'] + rect['width']), 2):
                    red, green, blue = pixels[x, y]
                    if red > 225 and green > 225 and blue > 225:
                        if x < middle:
                            left += 1
                        else:
                            right += 1
            return right > left
        except Exception as error:
            raise TestBlocked('无法读取开关图形状态：' + str(error)) from error

    def on(self, resource):
        control = self.one(resource)
        if not self.is_on(control):
            control.click()
        self.a.wait(lambda: self.is_on(self.one(resource)), resource + ' 已开启', 8)

    def toggle_round_trip(self, resource):
        control = self.one(resource)
        original = self.is_on(control)
        control.click()
        self.a.wait(lambda: self.is_on(self.one(resource)) != original,
                    resource + ' 切换', 8)
        self.one(resource).click()
        self.a.wait(lambda: self.is_on(self.one(resource)) == original,
                    resource + ' 恢复', 8)

    def toggle_labeled(self, labels):
        """按设置文案定位开关，兼容不同版本的 wake-up 资源 ID。"""
        label = next((self.home.text(value, 3) for value in labels
                      if any(e.is_displayed() and e.text == value for e in self.a.driver.find_elements('xpath',
                          f"//*[@package='{self.package}' and @text]"))), None)
        if not label:
            raise TestBlocked('未找到设置项：' + ' / '.join(labels))
        # 新版 DP AI 暴露专用开关资源；优先读取滑块真实位置，不能用页面元素列表的
        # selected 变化判断，因为 Compose View 的 selected 始终为 false。
        direct = [e for e in self.a.driver.find_elements('id', self.package + ':id/voice_wakeup_switch')
                  if e.is_displayed()]
        if len(direct) == 1:
            control = direct[0]
            original = self.is_on(control)
            control.click()
            self.a.wait(lambda: self.is_on(self.one('voice_wakeup_switch')) != original,
                        '语音唤醒开关切换', 8)
            self.one('voice_wakeup_switch').click()
            self.a.wait(lambda: self.is_on(self.one('voice_wakeup_switch')) == original,
                        '语音唤醒开关恢复', 8)
            return
        # 旧版 UiAutomator2 不能稳定从文本节点向上查找父节点；开关位于同一行右侧。
        rect = label.rect
        x, y = int(self.a.driver.get_window_size()['width'] * .88), int(rect['y'] + rect['height'] / 2)
        def states():
            controls = [e for e in self.a.driver.find_elements(
                'xpath', f"//*[@package='{self.package}' and @clickable='true' and @resource-id]") if e.is_displayed()]
            return [(e.get_attribute('resourceId'), e.get_attribute('selected')) for e in controls]
        before = states()
        self.a.driver.execute_script('mobile: clickGesture', {'x': x, 'y': y})
        self.a.wait(lambda: states() != before,
                    '语音唤醒开关切换', 8)
        self.a.driver.execute_script('mobile: clickGesture', {'x': x, 'y': y})

    def tutorial(self, title):
        item = self.home.text(title)
        rect = item.rect
        self.a.driver.execute_script('mobile: clickGesture', {'x': int(rect['x'] + rect['width'] / 2),
                                                               'y': int(rect['y'] + rect['height'] / 2)})
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
        # 新版音色选择为独立确认弹窗；选择后必须确认，才会返回 AI 设置页。
        confirm = self.a.wait(lambda: next((e for e in self.a.driver.find_elements(
            'id', self.package + ':id/tv_confirm') if e.is_displayed() and e.is_enabled()), None),
            '确认音色选择', 8)
        confirm.click()
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
        control = None
        for _ in range(7):
            found = [e for e in self.a.driver.find_elements('id', self.package + ':id/' + resource) if e.is_displayed()]
            if len(found) == 1:
                control = found[0]
                break
            size = self.a.driver.get_window_size()
            self.a.driver.swipe(size['width'] // 2, int(size['height'] * .78),
                                size['width'] // 2, int(size['height'] * .30), 400)
        if not control:
            raise AssertionError(f'{resource} 未出现在系统设置页。')
        control.click()
        button = self.a.wait(lambda: next((e for e in self.a.driver.find_elements('xpath',
            "//*[@text='OK' or @text='Confirm']") if e.is_displayed() and e.is_enabled()), None), '确认按钮', 10)
        button.click()
        if success:
            self.home.text(success, 20)

    def factory_reset(self):
        if __import__('os').environ.get('GLASSES_ALLOW_FACTORY_RESET') != '1':
            raise TestBlocked('恢复出厂设置会清空眼镜数据；设置 GLASSES_ALLOW_FACTORY_RESET=1 后执行。')
        self.confirm('factory_reset', 'Factory reset successful')

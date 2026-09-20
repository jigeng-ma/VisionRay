"""G 系列首页和设备管理的公共页面动作。"""
from studio.errors import TestBlocked


class HomeDevicePage:
    def __init__(self, android):
        self.a = android
        self.package = android.context['config']['package']
        self.name = android.context['glasses_name']

    def text(self, value, timeout=12):
        xpath = f"//*[@package='{self.package}' and @text={value!r}]"
        return self.a.wait(lambda: next((e for e in self.a.driver.find_elements('xpath', xpath) if e.is_displayed()), None), value, timeout)

    def home(self):
        self.a.ensure_foreground()
        # 引导用例被中止时可能停在“Skip guidance?”确认框；先收敛到首页，
        # 后续首页用例才不会把该临时状态误报成元素定位失败。
        if self.a.find('pair.skip_title'):
            self.a.click('pair.skip_confirm')
            self.a.wait(lambda: self.a.find('pair.home_title'), '确认跳过引导后首页', 15)
        elif self.a.find('pair.tutorial_begin'):
            self.a.click('pair.skip')
            self.a.element('pair.skip_title')
            self.a.click('pair.skip_confirm')
            self.a.wait(lambda: self.a.find('pair.home_title'), '跳过引导后首页', 15)
        if not self.a.find('pair.home_title'):
            for _ in range(3):
                tabs = [e for e in self.a.driver.find_elements('id', self.package + ':id/tabIcon') if e.is_displayed()]
                if tabs:
                    tabs[0].click()
                else:
                    self.a.driver.press_keycode(4)
                if self.a.wait(lambda: self.a.find('pair.home_title') or [e for e in self.a.driver.find_elements('id', self.package + ':id/tabIcon') if e.is_displayed()], '返回首页', 25):
                    break
        title = self.a.element('pair.home_title', 20)
        if not title or not self.text(self.name, 5):
            raise TestBlocked('未处于目标眼镜已连接首页：' + self.name)

    def _labeled(self, resource, label):
        found = [e for e in self.a.driver.find_elements('id', self.package + ':id/' + resource) if e.is_displayed() and e.text == label]
        if len(found) != 1:
            raise AssertionError(f'未唯一找到 {label}（{resource}）：{len(found)} 项。')
        return found[0]

    def card(self, label):
        self.home(); self._labeled('tv_grid_title', label).click(); self.a.log('click-card', label)

    def setting(self, label):
        self.home(); self._labeled('tv_list_title', label).click(); self.a.log('click-setting', label)

    def assert_page(self, title, marker):
        self.text(title, 15); self.text(marker, 15); self.a.capture(title.lower().replace(' ', '-'))

    def connected(self):
        self.home()
        def battery():
            found = [e for e in self.a.driver.find_elements('id', self.package + ':id/tv_battery_percent') if e.is_displayed()]
            return found[0] if len(found) == 1 and found[0].text.strip() not in ('', '-') else None
        value = self.a.wait(battery, '等待眼镜重连并显示电量', 35)
        self.a.log('glasses-battery', value.text)

    def restart_and_reconnect(self, adb):
        self.home()
        serial = self.a.context['phone']
        adb.shell(serial, 'am', 'force-stop', self.package)
        __import__('time').sleep(2)
        # 必须使用启动器 Intent；直接启动 SplashActivity 会结束后回到桌面。
        adb.shell(serial, 'monkey', '-p', self.package, '-c', 'android.intent.category.LAUNCHER', '1')
        try:
            self.a.wait(lambda: self.a.driver.current_package == self.package, 'APP 重启后前台启动', 20)
            self.a.wait(lambda: self.a.find('pair.home_title'), 'APP 重启后首页加载', 30)
            self.connected()
        finally:
            # 即使重连断言失败，也把 APP 恢复到前台，避免污染后续用例。
            if self.a.driver.current_package != self.package:
                adb.shell(serial, 'monkey', '-p', self.package, '-c', 'android.intent.category.LAUNCHER', '1')

    def device_settings(self):
        self.home(); self.a.driver.find_element('id', self.package + ':id/devices_menu').click()
        self.a.wait(lambda: self.a.driver.current_activity.endswith('MyDevicesActivity'), '设备管理页', 12)
        controls = [e for e in self.a.driver.find_elements('id', self.package + ':id/ivSettings') if e.is_displayed()]
        if len(controls) != 1: raise AssertionError('设备管理页未唯一找到设置入口。')
        controls[0].click(); self.assert_system_info()

    def assert_system_info(self):
        self.text('System Settings', 15)
        values = [e.text.strip() for e in self.a.driver.find_elements('xpath', "//*[@package='%s' and @text]" % self.package) if e.is_displayed()]
        if 'Model' not in values or not any(v and v != '-' for v in values if v not in {'System Settings', 'Model', 'Firmware Version', 'Bluetooth MAC'}):
            raise AssertionError('系统设置页未显示有效眼镜基础信息。')
        self.a.capture('system-settings')

    def unbind(self):
        """若仍绑定目标眼镜，则进入系统设置完成解绑；已解绑时直接返回。"""
        a = self.a
        a.ensure_foreground()
        # 上轮中断在确认框时，先完成已明确打开的解绑动作，避免首页导航被模态框拦截。
        pending = [e for e in a.driver.find_elements('xpath',
            "//*[@resource-id='%s:id/tv_confirm' and (@text='Unbind' or @text='Unpair Glasses') and @clickable='true']" % self.package)
            if e.is_displayed()]
        if len(pending) == 1:
            pending[0].click(); a.log('unbind', 'complete-pending-confirmation')
            a.wait(lambda: a.find('pair.add'), '完成遗留解绑后显示 Add Device 首页', 20)
            return
        if a.find('pair.add'):
            a.log('unbind', 'already-unbound')
            return
        if a.find('pair.tutorial_begin'):
            a.click('pair.skip'); a.element('pair.skip_title'); a.click('pair.skip_confirm')
            a.wait(lambda: a.find('pair.home_title'), '跳过现有引导回到首页', 15)
        self.home()
        self.setting('System Settings')
        button = None
        for _ in range(8):
            choices = [e for e in a.driver.find_elements('xpath',
                "//*[@package='%s' and (@text='Unbind' or @text='Unbind Glasses' or @text='Unpair Glasses')]" % self.package)
                if e.is_displayed() and e.is_enabled()]
            if len(choices) == 1:
                button = choices[0]
                break
            size = a.driver.get_window_size()
            # 该页 ScrollView 与引导页一样不响应 swipeGesture，使用真实触点上滑。
            a.driver.swipe(int(size['width'] * .50), int(size['height'] * .78),
                           int(size['width'] * .50), int(size['height'] * .28), 500)
        if not button:
            a.capture('unbind-not-found')
            raise AssertionError('系统设置页滑到底部后未找到 Unbind 按钮。')
        button.click(); a.log('unbind', 'open-confirmation')
        def confirmation():
            choices = [e for e in a.driver.find_elements('xpath',
                "//*[@package='%s' and (@text='Unbind' or @text='Unpair Glasses') and @clickable='true']" % self.package) if e.is_displayed()]
            return choices[-1] if choices else None
        confirm = a.wait(confirmation, '解绑确认弹窗', 10)
        confirm.click(); a.log('unbind', 'confirmed')
        a.wait(lambda: a.find('pair.add'), '解绑后显示 Add Device 首页', 20)
        a.capture('unbound-home')

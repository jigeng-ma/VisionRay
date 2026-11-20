"""G 系列首页和设备管理的公共页面动作。"""
import re
import time
from selenium.common.exceptions import StaleElementReferenceException
from studio.errors import TestBlocked, WaitTimeout


class HomeDevicePage:
    def __init__(self, android):
        self.a = android
        self.package = android.context['config']['package']
        self.name = android.context['glasses_name']

    def text(self, value, timeout=12):
        xpath = f"//*[@package='{self.package}' and @text={value!r}]"
        return self.a.wait(lambda: next((e for e in self.a.driver.find_elements('xpath', xpath) if e.is_displayed()), None), value, timeout)

    def _bound_names(self):
        from xml.etree import ElementTree as ET
        nodes = list(ET.fromstring(self.a.driver.page_source).iter())
        def texts(resource):
            return [node.get('text', '').strip() for node in nodes
                    if node.get('resource-id') == self.package + ':id/' + resource
                    and node.get('displayed') != 'false' and node.get('text', '').strip()]

        names = texts('tv_device_name')
        if names or self.a.context['config'].get('model') != 'G5':
            return names
        # 1.2.52 的 G5 首页将当前眼镜名称直接放进标题栏。
        known = {self.name, *(item['glasses_name'] for item in self.a.context.get('glasses_inventory', []))}
        return [title for title in texts('devices_title') if title in known or re.fullmatch(
            r'(?:DPVR\s+G(?:1|3|5|6|7)[-_]\S+|(?:DPVR\s+|Flow\s+)?Nova(?:[\s_-].+)?)', title, re.I)]

    def home(self, require_target=True):
        self.a.ensure_foreground()
        from .firmware_ota import leave_completed_update, leave_failed_update
        leave_completed_update(self.a)
        leave_failed_update(self.a)
        # 每条业务用例都从已绑定首页开始。引导、型号页、Add Device 页面是前序
        # 用例正常留下的状态，统一在这里恢复，避免把前置状态误报成业务失败。
        for _ in range(6):
            leave_completed_update(self.a)
            leave_failed_update(self.a)
            if self.a.find('pair.skip_title'):
                self.a.click('pair.skip_confirm')
            elif self.a.find('pair.tutorial_begin'):
                self.a.click('pair.skip')
                self.a.wait(lambda: self.a.find('pair.skip_title') or self.a.find('pair.home_title'),
                            '跳过引导后的确认框或首页', 10)
                if self.a.find('pair.skip_title'):
                    self.a.click('pair.skip_confirm')
            elif self.a.find('pair.add'):
                from .pairing import PairingPage
                pairing = PairingPage(self.a)
                original = pairing.options.get('skip_tutorial', False)
                original_prompt = pairing.options.get('require_pairing_prompt', True)
                try:
                    pairing.options['skip_tutorial'] = True
                    # 恢复既有绑定时系统可能不再弹出蓝牙配对确认。
                    pairing.options['require_pairing_prompt'] = False
                    pairing.run()
                finally:
                    pairing.options['skip_tutorial'] = original
                    pairing.options['require_pairing_prompt'] = original_prompt
            elif self.a.find('pair.home_title'):
                if not require_target or self.name in self._bound_names():
                    break
                if self._bound_names():
                    from .pairing import PairingPage
                    PairingPage(self.a).run()
                else:
                    # The home header renders before the device card / Add Device state.
                    # Do not classify this brief loading state as a failed OTA test.
                    try:
                        self.a.wait(lambda: self.name in self._bound_names() or self.a.find('pair.add'),
                                    '首页加载目标眼镜或未绑定入口', 20)
                    except WaitTimeout as exc:
                        raise TestBlocked('首页未显示目标眼镜或 Add Device 入口：' + self.name) from exc
            else:
                try:
                    tabs = [e for e in self.a.driver.find_elements('id', self.package + ':id/tabIcon') if e.is_displayed()]
                    if tabs:
                        tabs[0].click()
                    else:
                        self.a.driver.press_keycode(4)
                except StaleElementReferenceException:
                    # 导入完成时底部导航会重绘，下一轮重新定位。
                    continue
            time.sleep(.5)
        title = self.a.element('pair.home_title', 20)
        if not title or (require_target and self.name not in self._bound_names()):
            raise TestBlocked('未处于目标眼镜已连接首页：' + self.name)
        # APP 有时保留设备卡片和电量，却明确显示连接失败。先按页面的
        # Retry 恢复一次；仍失败时报告真实前置状态，避免媒资用例空等导入。
        error = "Connection failed. Try again later."
        if any(e.is_displayed() for e in self.a.driver.find_elements(
                'xpath', f"//*[@package='{self.package}' and @text='{error}']")):
            retry = [e for e in self.a.driver.find_elements(
                'xpath', f"//*[@package='{self.package}' and @text='Retry']")
                if e.is_displayed() and e.is_enabled()]
            if len(retry) != 1:
                raise TestBlocked('APP 显示眼镜连接失败，但未找到唯一 Retry 按钮。')
            retry[0].click()
            self.a.log('glasses-connection-retry', self.name)
            try:
                self.a.wait(lambda: not any(e.is_displayed() for e in self.a.driver.find_elements(
                    'xpath', f"//*[@package='{self.package}' and @text='{error}']")),
                    'APP 眼镜连接失败提示消失', 25)
            except WaitTimeout as exc:
                raise TestBlocked(f'APP 显示目标眼镜 {self.name} 连接失败，点击 Retry 后仍未恢复。') from exc
            time.sleep(3)
            if any(e.is_displayed() for e in self.a.driver.find_elements(
                    'xpath', f"//*[@package='{self.package}' and @text='{error}']")):
                raise TestBlocked(f'APP 显示目标眼镜 {self.name} 连接失败，Retry 后再次出现失败提示。')

    def _click_labeled(self, resource, labels):
        labels = (labels,) if isinstance(labels, str) else labels
        def click():
            found = [e for e in self.a.driver.find_elements('id', self.package + ':id/' + resource)
                     if e.is_displayed() and e.text in labels]
            if len(found) > 1:
                raise AssertionError(f'入口不唯一：{labels}（{resource}），找到 {len(found)} 项。')
            if not found:
                return False
            found[0].click()
            return True
        self.a.wait(click, f'点击入口 {labels[0]}', 12)

    def card(self, label):
        self.home(); self._click_labeled('tv_grid_title', label); self.a.log('click-card', label)

    def setting(self, label, require_target=True):
        self.home(require_target=require_target)
        # 不同 APP 版本首页显示 System 或 System Settings，详情页仍叫 System Settings。
        if label == 'System Settings':
            self._click_labeled('tv_list_title', ('System', 'System Settings'))
        else:
            self._click_labeled('tv_list_title', label)
        self.a.log('click-setting', label)

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
        __import__('time').sleep(2)
        try:
            self.a.restart()
            self.a.wait(lambda: self.a.driver.current_package == self.package, 'APP 重启后前台启动', 20)
            self.a.wait(lambda: self.a.find('pair.home_title'), 'APP 重启后首页加载', 30)
            self.connected()
        finally:
            # 即使重连断言失败，也把 APP 恢复到前台，避免污染后续用例。
            self.a.ensure_foreground()

    def device_settings(self):
        self.home(); self.a.driver.find_element('id', self.package + ':id/devices_menu').click()
        self.a.wait(lambda: self.a.driver.current_activity.endswith('MyDevicesActivity'), '设备管理页', 12)
        def settings_button():
            root = self.a.driver
            if self.a.context['config'].get('model') == 'G5':
                cards = [card for card in root.find_elements('id', self.package + ':id/container')
                         if card.is_displayed() and any(label.is_displayed() and label.text.strip() == self.name
                         for label in card.find_elements('id', self.package + ':id/tvName'))]
                if len(cards) != 1:
                    return None
                root = cards[0]
            controls = [e for e in root.find_elements('id', self.package + ':id/ivSettings')
                        if e.is_displayed() and e.is_enabled()]
            return controls[0] if len(controls) == 1 else None
        button = self.a.wait(settings_button, f'设备管理页 {self.name} 的设置入口', 12)
        button.click()
        self.assert_system_info()

    def assert_system_info(self):
        self.text('System Settings', 15)
        values = [e.text.strip() for e in self.a.driver.find_elements('xpath', "//*[@package='%s' and @text]" % self.package) if e.is_displayed()]
        if 'Model' not in values or not any(v and v != '-' for v in values if v not in {'System Settings', 'Model', 'Firmware Version', 'Bluetooth MAC'}):
            raise AssertionError('系统设置页未显示有效眼镜基础信息。')
        self.a.capture('system-settings')

    def pending_media_unpair_actions(self):
        a = self.a
        unpairs = [e for e in a.driver.find_elements('id', self.package + ':id/tv_cancel')
                   if e.is_displayed() and e.is_enabled() and e.text == 'Unpair']
        imports = [e for e in a.driver.find_elements('id', self.package + ':id/tv_confirm')
                   if e.is_displayed() and e.is_enabled() and e.text == 'Import']
        return (unpairs[0], imports[0]) if len(unpairs) == len(imports) == 1 else None

    def open_unpair_confirmation(self):
        a = self.a
        self.setting('System Settings', require_target=False)
        for _ in range(8):
            choices = [e for e in a.driver.find_elements('xpath',
                "//*[@package='%s' and (@text='Unbind' or @text='Unbind Glasses' or @text='Unpair Glasses')]" %
                self.package) if e.is_displayed() and e.is_enabled()]
            if len(choices) == 1:
                choices[0].click()
                a.log('unbind', 'open-confirmation')
                return
            size = a.driver.get_window_size()
            a.driver.swipe(int(size['width'] * .50), int(size['height'] * .78),
                           int(size['width'] * .50), int(size['height'] * .28), 500)
        a.capture('unbind-not-found')
        raise AssertionError('系统设置页滑到底部后未找到 Unbind 按钮。')

    def unbind(self, *, require_empty=True, allow_discovery=False):
        """解绑当前眼镜，返回是否还有其他眼镜绑定。"""
        a = self.a
        a.ensure_foreground()

        def wait_after_confirmation(previous=frozenset()):
            def destination():
                # 有待导入媒资时，首次确认后还会出现第二层提醒。
                # 本动作已明确要求解绑，继续选择 Unpair，不能把它当首页等待。
                if actions := self.pending_media_unpair_actions():
                    a.capture('unbind-pending-media-confirmation')
                    actions[0].click()
                    a.log('unbind', 'confirmed-pending-media')
                    return None
                if a.find('pair.add'):
                    return 'empty'
                if allow_discovery or a.context['config'].get('model') == 'G5':
                    from .pairing import discovery_panel
                    if discovery_panel(a) is not None:
                        return 'discovery'
                if not require_empty and a.find('pair.home_title'):
                    names = set(self._bound_names())
                    if names and names != previous:
                        return 'remaining'
                return None

            label = ('解绑后未绑定首页或附近设备配对卡片' if require_empty
                     else '解绑后设备列表更新')
            return a.wait(destination, label, 20) == 'remaining'

        # 上轮中断在确认框时，先完成已明确打开的解绑动作，避免首页导航被模态框拦截。
        def confirmation(opened=False):
            pending = [e for e in a.driver.find_elements('xpath',
                "//*[@resource-id='%s:id/tv_confirm' and (@text='Unbind' or @text='Unpair Glasses') and @clickable='true']" % self.package)
                if e.is_displayed() and e.is_enabled()]
            if len(pending) == 1:
                return pending[0]
            media_actions = self.pending_media_unpair_actions()
            if media_actions:
                return media_actions[0]
            if opened:
                choices = [e for e in a.driver.find_elements('xpath',
                    "//*[@package='%s' and (@text='Unbind' or @text='Unpair Glasses') and @clickable='true']" % self.package)
                    if e.is_displayed() and e.is_enabled()]
                return choices[-1] if choices else None
            return None

        pending = confirmation()
        if pending is not None:
            pending.click(); a.log('unbind', 'complete-pending-confirmation')
            return wait_after_confirmation()
        if a.find('pair.add'):
            a.log('unbind', 'already-unbound')
            return False
        if a.find('pair.tutorial_begin'):
            a.click('pair.skip'); a.element('pair.skip_title'); a.click('pair.skip_confirm')
            a.wait(lambda: a.find('pair.home_title'), '跳过现有引导回到首页', 15)
        previous = frozenset()
        if not require_empty:
            self.home(require_target=False)
            previous = set(self._bound_names())
        self.open_unpair_confirmation()
        confirm = a.wait(lambda: confirmation(opened=True), '解绑确认弹窗', 10)
        confirm.click(); a.log('unbind', 'confirmed')
        remaining = wait_after_confirmation(previous)
        a.capture('remaining-devices-home' if remaining else 'unbound-home')
        return remaining

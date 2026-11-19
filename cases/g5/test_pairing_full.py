"""G5 全量表的权限检测、扫描和首项绑定。"""

from contextlib import contextmanager
import re
from xml.etree import ElementTree

import pytest

from studio.errors import TestBlocked, WaitTimeout
from studio.pairing import PairingPage


PERMISSIONS = (
    'BLUETOOTH_SCAN', 'BLUETOOTH_CONNECT', 'ACCESS_COARSE_LOCATION', 'ACCESS_FINE_LOCATION',
)
SWITCH_PROMPTS = {
    'bluetooth': r'(?:bluetooth|蓝牙).{0,45}(?:off|disabled|关闭)|(?:enable|turn on|开启|打开).{0,25}(?:bluetooth|蓝牙)',
    'location': r'(?:location|定位|位置).{0,45}(?:off|disabled|关闭)|(?:enable|turn on|开启|打开).{0,25}(?:location|定位|位置)',
}
PERMISSION_PROMPTS = {
    'bluetooth': r'nearby devices|discov\w*.*bluetooth|附近的设备|附近设备',
    'location': r'location|位置信息|访问位置',
}


class PairingChecks(PairingPage):
    def __init__(self, android, adb):
        super().__init__(android)
        self.shell = lambda *args: adb.shell(android.context['phone'], *args)
        self.package = android.context['config']['package']

    def switch_enabled(self, switch):
        if switch == 'bluetooth':
            output = self.shell('settings', 'get', 'global', 'bluetooth_on')
            if output in ('0', '1', '2'):
                return output == '1'
        else:
            output = self.shell('cmd', 'location', 'is-location-enabled')
            if output.lower() in ('true', 'false'):
                return output.lower() == 'true'
        raise TestBlocked(f'无法读取手机 {switch} 开关状态：{output}')

    def set_switch(self, switch, enabled):
        if self.switch_enabled(switch) == enabled:
            return
        if switch == 'bluetooth':
            self.shell('cmd', 'bluetooth_manager', 'enable' if enabled else 'disable')
        else:
            self.shell('cmd', 'location', 'set-location-enabled', str(enabled).lower())
        self.a.wait(lambda: self.switch_enabled(switch) == enabled,
                    f'{switch} 开关切换为 {enabled}', 12, handle_popups=False)

    def permissions(self):
        user = self.shell('am', 'get-current-user')
        package_dump = self.shell('dumpsys', 'package', self.package)
        sections = re.split(r'(?m)^\s*User (\d+):', package_dump)
        states = dict(zip(sections[1::2], sections[2::2])).get(user, '')
        permissions = {
            name: granted == 'true'
            for name, granted in re.findall(r'android\.permission\.(\w+): granted=(true|false)', states)
            if name in PERMISSIONS
        }
        if set(permissions) != set(PERMISSIONS):
            raise TestBlocked('当前 Android 或 APP 版本未提供可独立检查的附近设备和位置权限。')
        return permissions

    def set_permissions(self, desired):
        current = self.permissions()
        for name in PERMISSIONS:
            if current[name] != desired[name]:
                self.shell('pm', 'grant' if desired[name] else 'revoke', '--user', 'current',
                           self.package, 'android.permission.' + name)
        if self.permissions() != desired:
            raise TestBlocked('手机未达到所需的附近设备和位置授权状态。')

    @contextmanager
    def radio_preconditions(self, enabled):
        original = {switch: self.switch_enabled(switch) for switch in SWITCH_PROMPTS}
        original_grants = self.permissions()
        try:
            self.set_permissions(dict.fromkeys(PERMISSIONS, enabled))
            for switch in original:
                self.set_switch(switch, enabled)
            yield
        finally:
            try:
                self.set_permissions(original_grants)
            finally:
                try:
                    self.set_switch('location', original['location'])
                finally:
                    self.set_switch('bluetooth', original['bluetooth'])

    def prompt(self, switch, *, system=False):
        texts = []
        for node in ElementTree.fromstring(self.a.driver.page_source).iter():
            text = node.get('text', '')
            owner = node.get('package', '')
            if not text or node.get('enabled') == 'false':
                continue
            if system and (owner.endswith('.permissioncontroller') or owner == 'com.lbe.security.miui'):
                texts.append(text)
            elif not system and owner == self.package and text not in ('+ Add Device', 'Add Device'):
                texts.append(text)
        pattern = (PERMISSION_PROMPTS if system else SWITCH_PROMPTS)[switch]
        return re.search(pattern, ' '.join(texts), re.I)

    def expect_prompt(self, switch, *, system=False):
        def observed():
            other = 'location' if switch == 'bluetooth' else 'bluetooth'
            if self.a.find('pair.models_title') or self.prompt(other, system=system):
                raise AssertionError(f'进入 {switch} 检测前，APP 已跳到后续步骤。')
            if not system and any(self.prompt(item, system=True) for item in PERMISSION_PROMPTS):
                raise AssertionError(f'{switch} 开关未处理时 APP 已开始请求权限。')
            return self.prompt(switch, system=system)

        self.a.wait(observed, f'{switch} {"系统权限" if system else "开关"}提示', 12, handle_popups=False)
        self.a.capture(f'{switch}-{"permission" if system else "switch"}')

    def click_add(self):
        self.a.wait(lambda: self.a.find('pair.add'), 'Add Device', 12, handle_popups=False).click()

    def click_add_after_switch(self):
        self.a.wait(lambda: self.prompt('location') or self.prompt('bluetooth', system=True)
                    or self.a.find('pair.add'), '继续配对检测', 12, handle_popups=False)
        if not (self.prompt('location') or self.prompt('bluetooth', system=True)):
            self.click_add()

    def prepare_logged_in_home(self):
        from studio.auth import AuthPage

        self.prepare_add_device()
        self.ensure_english_from_home()
        auth = AuthPage(self.a)
        auth.home()
        if auth.el('hint').text == 'Not logged in':
            auth.registered()
        tabs = auth.all('tabIcon')
        if not tabs:
            raise TestBlocked('登录后未找到首页导航。')
        tabs[0].click()
        self.prepare_add_device()

    def check_detection_order(self):
        self.prepare_logged_in_home()
        with self.radio_preconditions(False):
            self.a.ensure_foreground()
            self.click_add()
            for switch in SWITCH_PROMPTS:
                self.expect_prompt(switch)
                self.a.driver.press_keycode(4)
                self.set_switch(switch, True)
                self.click_add_after_switch()
            for switch in PERMISSION_PROMPTS:
                self.expect_prompt(switch, system=True)
                if not self.a.popups.handle():
                    raise TestBlocked(f'未能处理已观察到的 {switch} 系统授权弹窗。')
            self.a.wait(lambda: self.a.find('pair.models_title'), '授权后进入设备选择页',
                        12, handle_popups=False)

    def check_all_ready(self):
        self.prepare_logged_in_home()
        with self.radio_preconditions(True):
            self.a.ensure_foreground()
            self.click_add()

            def models_without_prompt():
                if any(self.prompt(switch) or self.prompt(switch, system=True) for switch in SWITCH_PROMPTS):
                    raise AssertionError('所有开关和权限均就绪时，仍出现配对检测提示。')
                return self.a.find('pair.models_title')

            self.a.wait(models_without_prompt, '直接进入设备选择页', 12, handle_popups=False)
            self.a.capture('all-checks-passed')

    def device_cards(self):
        lists = [item for item in self.a.driver.find_elements('id', self.package + ':id/recycler_devices')
                 if item.is_displayed()]
        if len(lists) != 1:
            return []
        return [item for item in lists[0].find_elements('id', self.options['device_name_id'])
                if item.is_displayed() and item.text]

    def start_scan(self):
        self.a.click('pair.next')
        self.a.wait(lambda: self.a.find('pair.searching') or self.device_cards(),
                    'Next 后开始扫描或已显示扫描到的设备', 12)
        self.a.capture('scan-started')

    def recent_scans(self):
        # AOSP AppScanStats reports finished LE scans per package, even when results
        # replace the scanning UI while the radio is still scanning.
        output = self.shell('dumpsys', 'bluetooth_manager')
        header = re.search(rf'(?m)^\s*{re.escape(self.package)}(?: \(Registered\))?[^\S\n]*\n'
                           r'[^\S\n]*LE scans \(started/stopped\)\s*:', output)
        if not header:
            return {}
        block = re.split(r'\n\s*\n|(?m:^\s*Ongoing scans\s*:)', output[header.end():], maxsplit=1)[0]
        return {key: int(duration)
                for key, duration in re.findall(r'(?m)^\s*(\d{2}-\d{2} [\d:.]+)\s*-\s*(\d+)ms\b', block)}

    def check_scan_duration(self):
        self.prepare_model_search()
        previous = self.recent_scans()
        self.start_scan()
        name = self.a.context['glasses_name']
        self.a.wait(lambda: any(card.text == name for card in self.device_cards()),
                    '搜索结果出现本轮 G5 眼镜', 18)
        self.a.capture('scan-results')

        def completed_duration():
            scans = self.recent_scans()
            fresh = [duration for key, duration in scans.items() if key not in previous]
            if len(fresh) > 1:
                raise TestBlocked('扫描窗口内产生多笔 BLE 扫描记录，无法唯一确认本次时长。')
            return fresh[0] if fresh else None

        try:
            duration = self.a.wait(completed_duration, 'Android 已完成本次 BLE 扫描', 20)
        except WaitTimeout as exc:
            raise TestBlocked('手机未提供本轮 VisionRay 的 BLE 扫描时长记录。') from exc
        self.a.log('ble-scan-duration-ms', duration)
        assert 14500 <= duration <= 16500, f'BLE 扫描应约 15 秒，实际 {duration} ms。'

    def bind_first_card(self):
        self.prepare_model_search()
        self.start_scan()

        def multiple_cards():
            cards = self.device_cards()
            return cards if len(cards) >= 2 else None

        try:
            cards = self.a.wait(multiple_cards, '至少两台同型号眼镜出现在搜索结果', 18)
        except WaitTimeout as exc:
            raise TestBlocked('搜索结果未同时出现两台设备，无法验证点击第一项。') from exc
        name = self.a.context['glasses_name']
        if cards[0].text != name or sum(card.text == name for card in cards) != 1:
            raise TestBlocked(f'配置的目标眼镜 {name} 须唯一出现且排在第一项，当前首项为 {cards[0].text}。')
        self.a.popups.pairing_active = True
        try:
            accepted = self.a.popups.pairing_accepted
            cards[0].click()
            self.a.log('bind', name)

            def matching_loading():
                return any(node.get('package') == self.package and node.get('text') == f'Pairing with {name}'
                           for node in ElementTree.fromstring(self.a.driver.page_source).iter())

            self.a.wait(matching_loading, f'Pairing with {name}', 8, handle_popups=False)
            self.a.capture('pairing-first-device')
            self.finish_binding(accepted)
        finally:
            self.a.popups.pairing_active = False


    def check_next(self):
        self.prepare_model_search()
        self.start_scan()


@pytest.mark.parametrize('check', [
    pytest.param(PairingChecks.check_detection_order, id='detection-order'),
    pytest.param(PairingChecks.check_all_ready, id='all-checks-pass'),
    pytest.param(PairingChecks.check_next, id='next-starts-scan'),
    pytest.param(PairingChecks.check_scan_duration, id='scan-results-duration'),
    pytest.param(PairingChecks.bind_first_card, id='bind-first-card'),
])
def test_pairing_full(android, adb, request, check):
    checks = PairingChecks(android, adb)
    checks.options = dict(checks.options, skip_tutorial=False)
    try:
        check(checks)
    except TestBlocked as exc:
        android.capture('blocked')
        request.node.user_properties.append(('studio_status', 'BLOCKED'))
        pytest.skip(str(exc))

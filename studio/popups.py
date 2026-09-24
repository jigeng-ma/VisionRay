"""统一弹窗识别；只操作签名完整且属于当前任务的已知弹窗。"""
import re
from xml.etree import ElementTree as ET
from .errors import TestBlocked


def contains_device(text, name):
    return bool(name and re.search(r'(?<![\w-])' + re.escape(name) + r'(?![\w-])', text, re.I))


class PopupGuard:
    def __init__(self, android):
        self.android = android
        self.pairing_active = False
        self.pairing_accepted = 0
        self.preserve = set()

    def _allow_system_permission(self, texts, packages):
        """允许 VisionRay 首次功能使用所需的 Android 系统权限，并选择最大授权范围。"""
        if not any('Allow VisionRay to' in text for text in texts):
            return False
        if not any(package == 'android' or package.endswith('.permissioncontroller') for package in packages if package):
            return False
        a = self.android
        joined = ' '.join(texts).lower()
        # 定位权限页可能默认停在 Approximate；先显式选择 Precise，再允许使用期间访问。
        if 'location' in joined:
            precise = [e for e in a.driver.find_elements('xpath', "//*[@text='Precise']") if e.is_displayed() and e.is_enabled()]
            if len(precise) == 1:
                precise[0].click()
        preferred = ('Allow all',) if 'photos and videos' in joined else ('Allow', 'While using the app')
        for text in preferred:
            buttons = [e for e in a.driver.find_elements('xpath', f"//*[@text={text!r}]") if e.is_displayed() and e.is_enabled()]
            if len(buttons) == 1:
                a.capture('popup-system-permission')
                buttons[0].click()
                a.log('popup', {'system_permission': text})
                return True
        raise TestBlocked('已识别 VisionRay 系统权限弹窗，但未找到允许按钮。')

    def handle(self):
        a = self.android
        nodes = list(ET.fromstring(a.driver.page_source).iter())
        texts = [n.get('text', '') for n in nodes if n.get('text')]
        packages = {n.get('package') for n in nodes}
        if self._allow_system_permission(texts, packages):
            return True
        rules = a.context['config'].get('popup_rules', [])
        for rule in rules:
            kind = rule['name']
            if kind in self.preserve:
                continue
            if not set(rule['packages']).intersection(packages):
                continue
            if not any(t in texts for t in rule['titles']):
                continue
            if rule.get('confirm_texts') and not any(t in texts for t in rule['confirm_texts']):
                continue
            if kind == 'bluetooth_pair':
                if not self.pairing_active:
                    raise TestBlocked('出现蓝牙配对请求，但当前步骤未发起配对；请检查设备状态。')
                if not contains_device('\n'.join(texts), a.context.get('glasses_name', '')):
                    raise TestBlocked('蓝牙配对请求的设备名称与本轮目标不符，不自动确认。')
            spec = rule['action']
            buttons = [e for e in a.driver.find_elements(spec['by'], spec['value'])
                       if e.is_displayed() and e.is_enabled()]
            if len(buttons) != 1:
                raise TestBlocked(f'已识别 {kind}，但安全操作按钮不唯一或缺失；请更新弹窗定位。')
            a.capture('popup-' + kind)
            buttons[0].click()
            a.log('popup', kind)
            if kind == 'bluetooth_pair':
                self.pairing_accepted += 1
            return True
        return False

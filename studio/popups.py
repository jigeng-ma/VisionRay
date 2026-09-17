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

    def handle(self):
        a = self.android
        nodes = list(ET.fromstring(a.driver.page_source).iter())
        texts = [n.get('text', '') for n in nodes if n.get('text')]
        packages = {n.get('package') for n in nodes}
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

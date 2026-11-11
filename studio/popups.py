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
        if not any('Allow VisionRay to' in text or '允许“VisionRay”' in text for text in texts):
            return False
        if not any(package == 'android' or package.endswith('.permissioncontroller')
                   or package == 'com.lbe.security.miui' for package in packages if package):
            return False
        a = self.android
        joined = ' '.join(texts).lower()
        # 定位权限页可能默认停在 Approximate；先显式选择 Precise，再允许使用期间访问。
        if 'location' in joined:
            locator = ("//*[@resource-id='com.lbe.security.miui:id/precise_location']"
                       if 'com.lbe.security.miui' in packages else "//*[@text='Precise']")
            precise = [e for e in a.driver.find_elements('xpath', locator) if e.is_displayed() and e.is_enabled()]
            if len(precise) == 1:
                precise[0].click()
        preferred = ('Allow all', '允许访问所有照片') if 'photos and videos' in joined or '照片和视频' in joined else (
            'Allow all the time', 'Allow', 'Allow only while using the app',
            'While using the app', '允许', '始终允许',
            '仅在使用中允许', '使用应用时允许')
        for text in preferred:
            buttons = [e for e in a.driver.find_elements('xpath', f"//*[@text={text!r}]") if e.is_displayed() and e.is_enabled()]
            if len(buttons) == 1:
                a.capture('popup-system-permission')
                buttons[0].click()
                a.log('popup', {'system_permission': text})
                return True
        raise TestBlocked('已识别 VisionRay 系统权限弹窗，但未找到允许按钮。')

    def _accept_nova_hotspot(self, texts, packages):
        """Nova 导入媒资时，确认 Android 的临时眼镜热点连接请求。"""
        if self.android.context['config'].get('model') != 'Nova':
            return False
        if ('com.android.settings' not in packages
                or 'Connect to device' not in texts
                or not any('VisionRay app wants to use a temporary Wi' in text for text in texts)):
            return False
        buttons = [e for e in self.android.driver.find_elements('id', 'android:id/button1')
                   if e.is_displayed() and e.is_enabled() and e.text == 'Connect']
        if len(buttons) != 1:
            raise TestBlocked('已识别 Nova 眼镜热点连接请求，但 Connect 按钮不唯一或缺失。')
        self.android.capture('popup-nova-hotspot')
        buttons[0].click()
        self.android.log('popup', 'nova_hotspot_connect')
        return True

    def _accept_first_launch(self, nodes, texts, packages):
        """非首次启动验证用例遇到隐私协议时，完成必要同意并继续执行。"""
        package = self.android.context['config']['package']
        resource_ids = {n.get('resource-id') for n in nodes}
        # 登录页也会显示协议链接；仅首次 Splash 协议页有此容器/标题和同意按钮。
        # 不能依赖英文文案：系统语言切换后该页会显示中文。
        first_page = {package + ':id/ll_user_privacy', package + ':id/tvPolicyTitle'}
        if (package not in packages or not first_page.intersection(resource_ids)
                or package + ':id/tv_agree' not in resource_ids):
            return False
        if 'first_launch' in self.preserve:
            return False
        buttons = [e for e in self.android.driver.find_elements('id', package + ':id/tv_agree')
                   if e.is_displayed() and e.is_enabled()]
        if len(buttons) != 1:
            raise TestBlocked('已识别首次隐私协议弹窗，但 Agree 按钮不唯一或缺失。')
        self.android.capture('popup-first-launch')
        buttons[0].click()
        self.android.log('popup', 'first_launch')
        return True

    def handle(self):
        a = self.android
        nodes = list(ET.fromstring(a.driver.page_source).iter())
        texts = [n.get('text', '') for n in nodes if n.get('text')]
        packages = {n.get('package') for n in nodes}
        if self._accept_first_launch(nodes, texts, packages):
            return True
        if self._accept_nova_hotspot(texts, packages):
            return True
        if self._allow_system_permission(texts, packages):
            return True
        # 上一条配对用例失败后，APP 会把 Binding Failed 底部弹窗保留到下一条。
        # 配对进行中应由配对用例判断失败；其他用例先清理遗留弹窗。
        package = a.context['config']['package']
        if not self.pairing_active and 'Binding Failed' in texts:
            buttons = [e for e in a.driver.find_elements('id', package + ':id/btn_primary')
                       if e.is_displayed() and e.is_enabled() and e.text == 'OK']
            if len(buttons) == 1:
                a.capture('stale-binding-failed')
                buttons[0].click()
                a.log('popup', 'stale_binding_failed')
                return True
        rules = a.context['config'].get('popup_rules', [])
        for rule in rules:
            kind = rule['name']
            if kind in self.preserve:
                continue
            if not set(rule['packages']).intersection(packages):
                continue
            pairing_title = (kind == 'bluetooth_pair' and any(
                text.startswith('Pair with ') and text.endswith('?') for text in texts))
            if not pairing_title and not any(t in texts for t in rule['titles']):
                continue
            if rule.get('confirm_texts') and not any(t in texts for t in rule['confirm_texts']):
                continue
            if kind == 'bluetooth_pair':
                if not contains_device('\n'.join(texts), a.context.get('glasses_name', '')):
                    raise TestBlocked('蓝牙配对请求的设备名称与本轮目标不符，不自动确认。')
            if kind == 'firmware_update' and a.context['config']['package'] + ':id/top_bar_back' in {
                    n.get('resource-id') for n in nodes}:
                # 固件详情是完整页面，可由调用方返回；它不是需要点击 Cancel 的弹窗。
                return False
            spec = rule['action']
            if kind == 'bluetooth_pair':
                # 小米系统配对框使用独立资源 ID；Appium 的 XPath 对该系统浮窗
                # 可能返回空列表，因此按 ID 单独定位并核对按钮文案。
                buttons = []
                for resource in ('com.android.settings:id/pairing_accept_button', 'android:id/button1'):
                    buttons = [e for e in a.driver.find_elements('id', resource)
                               if e.is_displayed() and e.is_enabled() and e.text in ('Pair', '配对')]
                    if buttons:
                        break
            else:
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

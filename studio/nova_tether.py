"""Nova 引导中的 Android 蓝牙共享网络设置。"""
import re
import time
from xml.etree import ElementTree as ET

from .devices import Adb


class NovaBluetoothTether:
    def __init__(self, android):
        self.a = android
        self.phone = android.context['phone']
        self.adb = Adb()

    def _switch(self):
        self.adb.shell(self.phone, 'uiautomator', 'dump', '/sdcard/visionray_tether.xml')
        root = ET.fromstring(self.adb.shell(self.phone, 'cat', '/sdcard/visionray_tether.xml'))
        matches = [node for node in root.iter()
                   if node.get('class') == 'android.widget.Switch'
                   and 'Bluetooth tethering' in node.get('content-desc', '')]
        if len(matches) != 1:
            raise AssertionError(f'系统蓝牙共享网络开关数量异常：{len(matches)}。')
        return matches[0]

    def enabled(self):
        return self._switch().get('checked') == 'true'

    def enable(self):
        # 若 APP 的“去开启”未直达该系统页，使用标准 Android 设置 Intent 进入同一页。
        self.adb.shell(self.phone, 'am', 'start', '-a', 'android.settings.TETHER_SETTINGS')
        switch = self._switch()
        if switch.get('checked') == 'true':
            return False
        controls = [node for node in switch.iter()
                    if node.get('resource-id') == 'android:id/checkbox' and node.get('enabled') == 'true']
        if len(controls) != 1:
            raise AssertionError(f'系统蓝牙共享网络实际开关数量异常：{len(controls)}。')
        values = [int(value) for value in re.findall(r'\d+', controls[0].get('bounds', ''))]
        if len(values) != 4:
            raise AssertionError('系统蓝牙共享网络开关缺少坐标。')
        self.adb.shell(self.phone, 'input', 'tap', str((values[0] + values[2]) // 2),
                       str((values[1] + values[3]) // 2))
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if self.enabled():
                return True
            time.sleep(.5)
        raise AssertionError('点击系统蓝牙共享网络后开关仍未开启。')

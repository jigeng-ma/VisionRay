"""通过 Nova 眼镜的 USB/ADB 测试页面发送模拟事件。"""
import re
import time
from xml.etree import ElementTree as ET

from .devices import Adb


PACKAGE = 'com.gzshixiang.sxservice'
ACTIVITY = PACKAGE + '/.MainActivity'
EVENT_CODES = frozenset((1, 2, 3, 4, 5, 10, 11, 12, 13, 14, 20, 21,
                         30, 31, 32, 33, 40, 41, 42, 43, *range(50, 62),
                         70, *range(80, 86), 90, 91))


def _center(node):
    values = [int(value) for value in re.findall(r'\d+', node.get('bounds', ''))]
    if len(values) != 4:
        raise RuntimeError('Nova 测试页面控件缺少有效坐标。')
    return (values[0] + values[2]) // 2, (values[1] + values[3]) // 2


class NovaSimulatedEvents:
    def __init__(self, glasses_serial, adb=None):
        if not glasses_serial:
            raise ValueError('必须提供 Nova 眼镜的 USB/ADB 序列号。')
        self.serial = glasses_serial
        self.adb = adb or Adb()

    def _screen(self):
        # 眼镜调试应用的 UiTestAutomationBridge 偶发返回 null root；
        # 只重试读取 UI，不重发模拟事件。
        for attempt in range(8):
            power = self.adb.shell(self.serial, 'dumpsys', 'power')
            if 'mWakefulness=Asleep' in power:
                # 异常恢复：QtScrcpy 右键等价于 Android Back。仅在眼镜休眠时发送一次，
                # 避免正常页面误触返回；实机已验证可唤醒测试页。
                self.adb.shell(self.serial, 'input', 'keyevent', '4')
                time.sleep(1)
                if 'mWakefulness=Asleep' in self.adb.shell(self.serial, 'dumpsys', 'power'):
                    raise RuntimeError('Nova 眼镜休眠，右键/Back 唤醒后仍不可输入模拟事件。')
            result = self.adb.shell(self.serial, 'uiautomator', 'dump', '/sdcard/visionray_nova_ui.xml')
            if 'dumped to:' not in result.lower():
                if attempt == 7:
                    raise RuntimeError(f'Nova 测试页 UI 树连续读取失败：{result.strip()}')
                time.sleep(.3)
                continue
            try:
                return ET.fromstring(self.adb.shell(self.serial, 'cat', '/sdcard/visionray_nova_ui.xml'))
            except (RuntimeError, ET.ParseError):
                if attempt == 7:
                    raise
                time.sleep(.3)

    @staticmethod
    def _one(root, *, resource=None, label=None):
        found = [node for node in root.iter()
                 if (resource is None or node.get('resource-id') == PACKAGE + ':id/' + resource)
                 and (label is None or node.get('text') == label)]
        if len(found) != 1:
            raise RuntimeError(f'Nova 测试页面控件未唯一定位：{resource or label}，找到 {len(found)} 个。')
        return found[0]

    def send(self, code):
        """输入编号并单击一次“手机模拟事件”；不自动重发事件。"""
        if type(code) is not int or code not in EVENT_CODES:
            raise ValueError(f'不支持的 Nova 模拟事件编号：{code!r}')
        if not self.adb.online(self.serial):
            raise RuntimeError(f'Nova 眼镜 USB/ADB 未连接：{self.serial}')
        focus = self.adb.shell(self.serial, 'dumpsys', 'window')
        if PACKAGE not in next((line for line in focus.splitlines() if 'mCurrentFocus' in line), ''):
            self.adb.shell(self.serial, 'am', 'start', '-n', ACTIVITY)
        root = self._screen()
        field = self._one(root, resource='ed_type')
        x, y = _center(field)
        self.adb.shell(self.serial, 'input', 'tap', str(x), str(y))

        self.adb.shell(self.serial, 'input', 'keyevent', '123')  # 光标移到末尾
        for _ in field.get('text', ''):
            self.adb.shell(self.serial, 'input', 'keyevent', '67')  # 删除旧编号
        self.adb.shell(self.serial, 'input', 'text', str(code))
        for attempt in range(3):
            root = self._screen()
            if self._one(root, resource='ed_type').get('text') == str(code):
                break
            if attempt == 2:
                raise RuntimeError(f'Nova 模拟事件编号 {code} 未正确写入，未点击发送。')
            time.sleep(.3)
        button_text = self._one(root, label='手机模拟事件')
        parents = {child: parent for parent in root.iter() for child in parent}
        button = parents.get(button_text)
        if button is None or button.get('clickable') != 'true':
            raise RuntimeError('Nova 测试页面未找到可点击的“手机模拟事件”按钮。')
        x, y = _center(button)
        self.adb.shell(self.serial, 'input', 'tap', str(x), str(y))

    def pairing_mode(self):
        self.send(31)  # 折叠
        self.send(5)   # 拍摄键长按 5 秒

    def take_photo(self):
        self.send(1)

    def start_video(self):
        self.send(4)   # 拍摄键长按 2 秒

    def stop_video(self):
        self.send(1)

    def start_audio(self):
        self.send(2)   # 固件模拟双击，实际两次按键间隔须为 100～500 ms

    def stop_audio(self):
        self.send(1)

    def touchpad_tap(self):
        self.send(10)

    def touchpad_forward(self):
        self.send(20)

    def touchpad_backward(self):
        self.send(21)

    def factory_reset(self, yellow_led_check):
        if not callable(yellow_led_check):
            raise ValueError('必须提供确认黄色 LED 常亮的检查函数。')
        self.send(31)
        self.send(3)   # 拍摄键连按 5 次
        if not yellow_led_check():
            raise RuntimeError('LED 未确认黄色常亮，停止恢复出厂设置。')
        self.send(5)
        time.sleep(60)

    def fold(self):
        self.send(31)

    def unfold(self):
        self.send(30)

    def wear(self):
        self.send(40)

    def remove(self):
        self.send(41)

"""G1/G3/G6 调试页媒体命令。每次调用只点击一次，不自动重发。"""
import time
import math
import re
from .errors import TestBlocked
from .home_device import HomeDevicePage


class BleMediaCommands:
    ACTIVITY = 'com.dpvr.android.settings.activity.BleKTClientActivity'
    CLICK_INTERVAL_SECONDS = 3
    BUTTONS = {
        'take_photo': ('btn_start_photo', '拍照'),
        'start_video': ('btn_start_video', '开始录像'),
        'stop_video': ('btn_stop_video', '停止录像'),
        'start_audio': ('btn_start_audio', '开始录音'),
        'stop_audio': ('btn_stop_audio', '停止录音'),
    }

    def __init__(self, android):
        config = android.context['config']
        if config.get('product') != 'G系列' or config.get('model') not in ('G1', 'G3', 'G6'):
            raise TestBlocked('BLE 媒体命令仅适用于 G1/G3/G6。')
        self.a = android
        self.package = config['package']
        self._last_click_at = None

    def _find(self, resource):
        found = [e for e in self.a.driver.find_elements('id', self.package + ':id/' + resource)
                 if e.is_displayed()]
        if len(found) > 1:
            raise AssertionError(f'{resource} 匹配不唯一，停止操作。')
        return found[0] if found else None

    def open(self):
        """进入 我的 → BLE_COMMAND_TEST，必要时上滑一次显示媒体按钮。"""
        a = self.a
        a.ensure_foreground()
        if a.driver.current_activity != self.ACTIVITY:
            for _ in range(6):
                tabs = [e for e in a.driver.find_elements('id', self.package + ':id/tabIcon')
                        if e.is_displayed()]
                if tabs:
                    tabs[-1].click()
                    HomeDevicePage(a).text('BLE_COMMAND_TEST').click()
                    break
                a.driver.back()
                time.sleep(.5)
            else:
                raise TestBlocked('无法返回底部导航，请先完成首次引导或配对页面。')
            a.wait(lambda: a.driver.current_activity == self.ACTIVITY, 'BLE_COMMAND_TEST 页面', 15)
        if not all(self._find(resource) for resource, _ in self.BUTTONS.values()):
            size = a.driver.get_window_size()
            a.driver.swipe(int(size['width'] * .5), int(size['height'] * .78),
                           int(size['width'] * .5), int(size['height'] * .30), 600)
        a.wait(lambda: all(self._find(resource) for resource, _ in self.BUTTONS.values()),
               '拍照、录像、录音按钮可见', 10)
        return self

    def _click(self, action):
        self.open()
        resource, label = self.BUTTONS[action]
        button = self.a.wait(lambda: self._find(resource), label, 10)
        if button.text != label or not button.is_enabled():
            raise TestBlocked(f'{label} 按钮文案不符或不可用。')
        # 点击放在等待/重试循环之外，避免重复拍摄或重复开始录制。
        if self._last_click_at is not None:
            time.sleep(max(0, self.CLICK_INTERVAL_SECONDS - (time.monotonic() - self._last_click_at)))
        button.click()
        self._last_click_at = time.monotonic()
        self.a.log('ble-media-click', action)

    @staticmethod
    def _count(count):
        if type(count) is not int or count < 1:
            raise ValueError('count 必须是正整数。')

    def take_photo(self, count=1):
        self._count(count)
        for index in range(count):
            self._click('take_photo')
            if index + 1 < count:
                time.sleep(1)

    @staticmethod
    def _seconds(text):
        match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*(Min|分钟|秒|s)\s*', text, re.I)
        if not match:
            raise TestBlocked('无法识别设置时长：' + text)
        return float(match[1]) * (60 if match[2].lower() in ('min', '分钟') else 1)

    def _duration_row(self, label):
        xpath = (f"//*[@resource-id='{self.package}:id/tv_title' and @text='{label}']"
                 "/parent::*")
        for _ in range(5):
            rows = [e for e in self.a.driver.find_elements('xpath', xpath) if e.is_displayed()]
            if len(rows) == 1:
                return rows[0]
            if len(rows) > 1:
                raise TestBlocked('时长设置行不唯一：' + label)
            size = self.a.driver.get_window_size()
            self.a.driver.swipe(int(size['width']*.5), int(size['height']*.78),
                                int(size['width']*.5), int(size['height']*.3), 500)
        raise TestBlocked('未找到时长设置：' + label)

    def _read_duration(self, label):
        hints = self._duration_row(label).find_elements('id', self.package + ':id/tv_hint')
        if len(hints) != 1:
            raise TestBlocked('无法唯一读取当前时长：' + label)
        return self._seconds(hints[0].text)

    def _ensure_duration(self, kind, duration):
        page, label = (('Capture', 'Video Duration') if kind == 'video'
                       else ('System Settings', 'Recording Duration'))
        self.a.ensure_foreground()
        if self.a.find('pair.add'):
            raise TestBlocked('请先连接 G1/G3/G6 眼镜，再校验录制时长。')
        HomeDevicePage(self.a).setting(page)
        current = self._read_duration(label)
        if current >= duration:
            self.a.log('ble-duration', {'kind': kind, 'limit_seconds': current, 'changed': False})
            return
        self._duration_row(label).click()
        options = self.a.wait(lambda: [e for e in self.a.driver.find_elements(
            'id', self.package + ':id/tv_label') if e.is_displayed()], '时长选项', 10)
        maximum = 720 if kind == 'video' else 7200
        choices = [(self._seconds(e.text), e) for e in options]
        choices = [(seconds, e) for seconds, e in choices if duration <= seconds <= maximum]
        if not choices:
            raise TestBlocked(f'当前 APP 没有满足 {duration} 秒的{label}选项。')
        seconds, option = min(choices, key=lambda item: item[0])
        option.click()
        self.a.wait(lambda: not any(e.is_displayed() for e in self.a.driver.find_elements(
            'id', self.package + ':id/tv_label')), '时长选项关闭', 10)
        actual = self._read_duration(label)
        if actual < duration:
            raise TestBlocked(f'时长设置未生效：需要 {duration} 秒，读回 {actual} 秒。')
        self.a.log('ble-duration', {'kind': kind, 'limit_seconds': actual, 'changed': True})

    def _hold(self, duration):
        deadline = time.monotonic() + duration
        while (remaining := deadline - time.monotonic()) > 0:
            time.sleep(min(remaining, 20))
            if time.monotonic() < deadline:
                # 只读保活，避免长录制超过 Appium newCommandTimeout。
                _ = self.a.driver.current_package

    def _record(self, kind, count, duration):
        self._count(count)
        maximum = 720 if kind == 'video' else 7200
        if (isinstance(duration, bool) or not isinstance(duration, (int, float))
                or not math.isfinite(duration) or not 0 < duration <= maximum):
            raise ValueError(f'duration 必须大于 0 且不超过 {maximum} 秒。')
        self._ensure_duration(kind, duration)
        for index in range(count):
            self._click('start_' + kind)
            try:
                self._hold(duration)
            finally:
                self._click('stop_' + kind)
            self.a.log('ble-record-complete', {'kind': kind, 'index': index + 1, 'seconds': duration})
            if index + 1 < count:
                time.sleep(1)

    def record_video(self, count=1, duration=15):
        """录像 count 次，每次 duration 秒，最大 720 秒。"""
        self._record('video', count, duration)

    def record_audio(self, count=1, duration=15):
        """录音 count 次，每次 duration 秒，最大 7200 秒。"""
        self._record('audio', count, duration)

    def start_video(self):
        self._click('start_video')

    def stop_video(self):
        self._click('stop_video')

    def start_audio(self):
        self._click('start_audio')

    def stop_audio(self):
        self._click('stop_audio')

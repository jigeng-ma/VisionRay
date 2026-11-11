"""Nova 配对及新手引导页面动作。"""
import time
import subprocess
import re
from xml.etree import ElementTree as ET

from .nova_events import NovaSimulatedEvents
from .errors import WaitTimeout


def accept_media_hotspot(android, timeout=90):
    """Nova 媒资导入会延迟弹出 Android 临时 Wi-Fi 确认，按真实系统 UI 确认。"""
    from .devices import Adb
    adb = Adb()
    phone = android.context['phone']
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        adb.shell(phone, 'uiautomator', 'dump', '/sdcard/visionray_nova_hotspot.xml')
        root = ET.fromstring(adb.shell(phone, 'cat', '/sdcard/visionray_nova_hotspot.xml'))
        nodes = list(root.iter())
        texts = {node.get('text', '') for node in nodes}
        if any('cancelled the request to choose a device' in value for value in texts):
            raise AssertionError('Nova 导入时 Android 临时 Wi-Fi 请求已取消；热点连接未完成。')
        if ('Connect to device' in texts and
                any('VisionRay app wants to use a temporary Wi' in value for value in texts)):
            buttons = [node for node in nodes if node.get('resource-id') == 'android:id/button1'
                       and node.get('text') == 'Connect']
            if len(buttons) != 1:
                raise AssertionError(f'Nova 临时热点 Connect 按钮数量异常：{len(buttons)}。')
            x1, y1, x2, y2 = map(int, re.findall(r'\d+', buttons[0].get('bounds', '')))
            adb.shell(phone, 'input', 'tap', str((x1 + x2) // 2), str((y1 + y2) // 2))
            android.log('nova-hotspot-connect', 'Android temporary Wi-Fi confirmed')
            return
        if any(node.get('resource-id', '').endswith(':id/status_progress_tv') for node in nodes):
            return
        time.sleep(1)
    raise AssertionError(f'Nova 导入后 {timeout} 秒内未出现临时热点确认或导入进度。')


class NovaPage:
    def __init__(self, android):
        self.a = android
        self.d = android.driver
        self.package = android.context['config']['package']
        self.serial = android.context['glasses']
        if not self.serial:
            raise RuntimeError('Nova 用例必须选择 USB 连接的眼镜。')
        self.events = NovaSimulatedEvents(self.serial)

    def _text(self, label, resource=None):
        resource_filter = (f" and @resource-id='{self.package}:id/{resource}'"
                           if resource else '')
        return next((e for e in self.d.find_elements('xpath',
                     f"//*[@text='{label}'{resource_filter}]") if e.is_displayed()), None)

    def click(self, label, timeout=15):
        self.a.wait(lambda: self._text(label), label, timeout).click()

    def contains(self, *words):
        source = self.d.page_source.lower()
        return all(word.lower() in source for word in words)

    def _guide_step(self):
        titles = [e.text.strip() for e in self.d.find_elements('id', self.package + ':id/tvStepTitle')
                  if e.is_displayed() and e.text.strip()]
        details = [e.text.strip() for e in self.d.find_elements('id', self.package + ':id/tvStepDetail')
                   if e.is_displayed() and e.text.strip()]
        if details and details[0] == 'Put on the glasses':
            return 'wear'
        if titles and titles[0] == 'Take a photo':
            return 'photo'
        if titles and titles[0] == 'Start video recording':
            return 'video'
        if titles and 'live/call recording' in titles[0].lower():
            return 'audio'
        if titles and any(word in titles[0].lower() for word in ('music', 'volume', 'swipe', 'pause', 'play')):
            return 'music'
        return None

    def _step_title(self):
        titles = [e.text.strip() for e in self.d.find_elements('id', self.package + ':id/tvStepTitle')
                  if e.is_displayed() and e.text.strip()]
        return titles[0] if len(titles) == 1 else ''

    def prepare_guide(self, step):
        """各条引导用例独立准备页面，前一条跳过或失败不能阻塞后续用例。"""
        if step not in ('wear', 'photo', 'video', 'audio', 'music'):
            raise ValueError(f'未知 Nova 引导步骤：{step}')
        current = self._guide_step()
        order = {'wear': 0, 'photo': 1, 'video': 2, 'audio': 3, 'music': 4}
        title = self._step_title().lower()
        wrong_substep = ((current == 'video' and 'start video recording' not in title) or
                         (current == 'audio' and 'start live/call recording' not in title) or
                         (current == 'music' and 'play' not in title))
        if current is None or order[current] > order[step] or wrong_substep:
            from .home_device import HomeDevicePage
            if not self._text('Add Device'):
                if self._text('Skip', 'tvSkip'):
                    self.skip_guide()
                self._unpair_and_verify(require_bond=False)
            self.pair()
            current = self._guide_step()
        if step in ('photo', 'video', 'audio', 'music') and current == 'wear':
            self.wear_guide()
            current = self._guide_step()
        if step in ('video', 'audio', 'music') and current == 'photo':
            self.photo_guide()
            current = self._guide_step()
        if step in ('audio', 'music') and current == 'video':
            self.video_guide()
            current = self._guide_step()
        if step == 'music' and current == 'audio':
            self.audio_guide()
            current = self._guide_step()
        if current != step:
            raise AssertionError(f'Nova 引导前置未进入 {step}：当前 {current or "非引导页"}。')

    def pair(self):
        self.a.ensure_foreground()
        if self._text('Add Device'):
            self.click('Add Device')
        if not self.contains('Pairing Ready'):
            self.a.wait(lambda: self._text('Flow Nova', 'tvDeviceName'),
                        'Flow Nova 型号卡片', 15, handle_popups=False).click()
        self.a.wait(lambda: self.contains('Pairing Ready'), 'Nova 配对说明页', 15)
        self.events.pairing_mode()
        self.click('Next')
        suffix = self.serial[-8:].upper()
        label = 'SN:' + suffix
        self.a.wait(lambda: self._text(label), f'搜索目标 Nova {label}', 90).click()
        self.a.wait(lambda: self._text('Put on the glasses') or self._text('Pair') or
                    self._text('Binding Failed') or self._text('Add Device'),
                    'Nova 系统蓝牙配对或引导页', 30, handle_popups=False)
        if self._text('Binding Failed') or self._text('Add Device'):
            self.a.capture('nova-binding-failed')
            button = self._text('OK')
            if button:
                button.click()
            raise AssertionError('Nova 配对失败：APP 提示 Binding Failed / Please try again later；'
                                 '手机蓝牙日志需检查 Classic 配对结果。')
        pair_button = self._text('Pair')
        if pair_button:
            pair_button.click()
        self.a.wait(lambda: self.contains('Put on the glasses') or self.contains('glasses connected'),
                    'Nova 绑定完成并进入佩戴引导', 90)
        self.a.capture('nova-paired')

    def skip_guide(self):
        if not self._text('Skip', 'tvSkip'):
            self.prepare_guide('wear')
        self.a.wait(lambda: self._text('Skip', 'tvSkip'), 'Nova 新手引导 Skip', 15).click()
        self.a.wait(lambda: self._text('Skip guidance?'), '跳过引导确认弹窗', 10)
        confirms = [e for e in self.d.find_elements('id', self.package + ':id/tv_confirm')
                    if e.is_displayed() and e.text.strip() == 'Skip']
        if len(confirms) != 1:
            raise AssertionError(f'Nova 跳过引导确认按钮数量异常：{len(confirms)}。')
        confirms[0].click()
        self.a.wait(lambda: self._text('Smart Glasses', 'devices_title'), '跳过引导后首页', 20)
        # 进入配对模式时先模拟折叠；跳过引导后恢复展开，否则拍摄/录音指令被眼镜忽略。
        self.events.unfold()

    def wear_guide(self):
        self.a.wait(lambda: self.contains('Put on the glasses'), 'Nova 佩戴引导', 15)
        # 配对前置会先折叠镜腿；若不恢复展开，后续拍照会被眼镜拒绝并记录“折叠”。
        self.events.unfold()
        self.events.remove()
        self.events.wear()
        self.a.wait(lambda: self.contains('photo') and not self.contains('Put on the glasses'),
                    'Nova 佩戴后进入拍照引导', 30)

    def photo_guide(self):
        self.a.wait(lambda: self.contains('photo'), 'Nova 拍照引导', 15)
        self.events.take_photo()
        self.a.wait(lambda: self.contains('video') and not self.contains('photo'),
                    'Nova 拍照后进入录像引导', 40)

    def video_guide(self):
        self.a.wait(lambda: self.contains('video'), 'Nova 录像引导', 15)
        self.events.start_video()
        self.a.wait(lambda: 'stop video recording' in self._step_title().lower(),
                    'Nova 开始录像引导反馈', 20)
        time.sleep(3)
        self.events.stop_video()
        try:
            self.a.wait(lambda: self._guide_step() == 'audio', 'Nova 录像后进入录音引导', 40)
        except WaitTimeout:
            titles = [e.text.strip() for e in self.d.find_elements('id', self.package + ':id/tvStepTitle')
                      if e.is_displayed() and e.text.strip()]
            raise AssertionError(f'Nova 录像已停止，但未进入录音引导；当前引导页：{titles or "未知"}。') from None

    def audio_guide(self):
        """双击拍摄键开始录音，单击结束，核对每一步引导推进。"""
        before = self._step_title()
        if 'start live/call recording' not in before.lower():
            raise AssertionError(f'Nova 录音引导起点异常：{before or "无标题"}。')
        self.events.start_audio()
        try:
            self.a.wait(lambda: 'stop live/call recording' in self._step_title().lower(),
                        'Nova 开始录音后显示结束录音引导', 30)
        except WaitTimeout:
            raise AssertionError(f'Nova 双击拍摄键后未进入结束录音引导；当前：{self._step_title() or "无标题"}。') from None
        self.a.capture('nova-audio-guide-started')
        self.events.stop_audio()
        try:
            self.a.wait(lambda: self._guide_step() == 'music', 'Nova 结束录音后进入音乐引导', 30)
        except WaitTimeout:
            raise AssertionError(f'Nova 单击拍摄键后未进入音乐引导；当前：{self._step_title() or "无标题"}。') from None
        self.a.capture('nova-audio-guide-finished')

    def music_guide(self):
        """触摸板轻点、前滑、后滑、轻点，并逐步核对引导状态。"""
        actions = (
            ('播放', self.events.touchpad_tap, ('volume', 'swipe')),
            ('调大音量', self.events.touchpad_forward, ('volume', 'swipe')),
            ('调小音量', self.events.touchpad_backward, ('pause', 'music')),
            ('暂停', self.events.touchpad_tap, ('voice',)),
        )
        if self._guide_step() != 'music':
            raise AssertionError(f'Nova 音乐引导起点异常：{self._step_title() or "无标题"}。')
        for index, (label, action, next_words) in enumerate(actions, 1):
            before = self._step_title()
            action()
            try:
                self.a.wait(lambda: self._step_title() != before and
                            any(word in self._step_title().lower() for word in next_words),
                            f'Nova 音乐引导{label}后的下一步骤', 30)
            except WaitTimeout:
                raise AssertionError(f'Nova 触摸板{label}后引导未按预期推进：'
                                     f'{before or "无标题"} → {self._step_title() or "无标题"}。') from None
            self.a.capture(f'nova-music-{index}')

    def open_setting(self, label, title):
        """从 Nova 首页打开设置；入口可能位于可滚动列表的屏幕外。"""
        from .home_device import HomeDevicePage
        # 中断在解绑确认框时，Back 键不一定能关闭该 APP 弹窗。
        if self._text('Unpair Glasses', 'tv_confirm'):
            self.click('Cancel')
        home = HomeDevicePage(self.a)
        home.home(require_target=False)
        for _ in range(5):
            choices = [e for e in self.d.find_elements('id', self.package + ':id/tv_list_title')
                       if e.is_displayed() and e.text in (label, title)]
            if len(choices) == 1:
                choices[0].click()
                self.a.wait(lambda: self._text(title), f'Nova {title} 页', 15)
                return
            size = self.d.get_window_size()
            self.d.swipe(int(size['width'] * .5), int(size['height'] * .83),
                         int(size['width'] * .5), int(size['height'] * .35), 450)
        raise AssertionError(f'Nova 首页滚动后未找到 {label} 入口。')

    def system_settings(self):
        self.open_setting('System', 'System Settings')

    def rename(self):
        """修改眼镜名称、核对保存，再恢复原名称以免影响后续用例。"""
        original = self.a.context['glasses_name']
        # APP 名称输入框最多接受 18 个字符，使用短名称验证保存。
        changed = 'Nova ' + self.serial[-4:]
        self.system_settings()
        self.click('Glasses Name')
        field = self.a.wait(lambda: next((e for e in self.d.find_elements(
            'id', self.package + ':id/et_name') if e.is_displayed()), None), '眼镜名称输入框', 10)
        field.clear()
        field.send_keys(changed)
        self.click('save')
        try:
            self.a.wait(lambda: self._text(changed), '保存后的眼镜名称', 15)
            self.a.capture('nova-name-changed')
        finally:
            self.click('Glasses Name')
            field = self.a.wait(lambda: next((e for e in self.d.find_elements(
                'id', self.package + ':id/et_name') if e.is_displayed()), None), '眼镜名称输入框', 10)
            field.clear()
            field.send_keys(original)
            self.click('save')
            self.a.wait(lambda: self._text(original), '恢复后的眼镜名称', 15)
            self.a.capture('nova-name-restored')

    def _unpair_and_verify(self, require_bond=True):
        """解绑 Nova 并检查 APP/手机状态；引导前置可复用。"""
        name = self.a.context['glasses_name']

        def bonded():
            result = subprocess.run(['adb', '-s', self.a.context['phone'], 'shell',
                                     'dumpsys', 'bluetooth_manager'], capture_output=True,
                                    text=True, encoding='utf-8', errors='replace', timeout=20)
            if result.returncode:
                raise RuntimeError('无法读取手机蓝牙配对状态：' + result.stderr.strip())
            return name in result.stdout

        if require_bond and not bonded():
            raise AssertionError(f'解绑前手机蓝牙配对列表未包含 {name}，无法验证解绑清理。')
        self.system_settings()
        for _ in range(8):
            button = self._text('Unpair Glasses', 'cancel_match')
            if button:
                break
            size = self.d.get_window_size()
            self.d.swipe(int(size['width'] * .5), int(size['height'] * .78),
                         int(size['width'] * .5), int(size['height'] * .28), 450)
        else:
            raise AssertionError('Nova 系统设置页未找到 Unpair Glasses。')
        button.click()
        self.a.wait(lambda: self._text('Unpair Glasses', 'tv_confirm'), '解绑确认弹窗', 10)
        self.a.capture('nova-unpair-confirmation')
        self._text('Unpair Glasses', 'tv_confirm').click()
        self.a.wait(lambda: self._text('Add Device'), '解绑后 APP 未绑定首页', 30)
        self.a.wait(lambda: not bonded(), '手机蓝牙配对记录已清除', 30)
        self.a.capture('nova-unpaired')

    def unpair(self):
        """用例解绑后恢复本轮绑定，避免污染后续用例。"""
        try:
            self._unpair_and_verify()
        finally:
            # 只有实际到达未绑定页才重新配对；前置未触发解绑时保留原状态。
            if self._text('Add Device'):
                self.pair()
                self.skip_guide()

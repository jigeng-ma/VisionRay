"""G 系列配对页面；仅由真实断言决定用例结果。"""
import time
from .errors import TestBlocked, WaitTimeout


class PairingPage:
    def __init__(self, android):
        self.a = android
        self.options = android.context['config']['pairing']

    def select_model(self, label):
        a = self.a
        a.element('pair.models_title')
        seen = set()
        for attempt in range(self.options['max_scrolls'] + 1):
            # 每次滚动后重新定位，列表增加型号不会改变选择逻辑。
            elements = a.driver.find_elements('id', self.options['model_label_id'])
            visible = [e for e in elements if e.is_displayed()]
            matches = [e for e in visible if e.text == label]
            if len(matches) > 1:
                raise AssertionError('型号名称重复：' + label)
            if matches:
                matches[0].click()
                a.log('select-model', label)
                return
            signature = tuple(e.text for e in visible)
            if signature in seen:
                break
            seen.add(signature)
            if attempt == self.options['max_scrolls']:
                break
            try:
                size = a.driver.get_window_size()
                # 1.2.38 的型号页由 rvDeviceList 承载，旧版 scrollContent 已不存在；
                # 使用真实触点滑动可兼容两版页面。
                a.driver.swipe(int(size['width'] * .50), int(size['height'] * .78),
                               int(size['width'] * .50), int(size['height'] * .28), 500)
            except (KeyError, TypeError):
                # 保留无真实窗口的测试驱动兼容性。
                a.driver.execute_script('mobile: scrollGesture', {'direction': 'down', 'percent': .75})
            time.sleep(.3)
        a.capture('model-not-found')
        available = sorted({e.text for e in a.driver.find_elements('id', self.options['model_label_id'])
                            if e.is_displayed() and e.text})
        raise TestBlocked('当前 APP 型号列表未提供 ' + label + '；实际可选：' +
                          ('、'.join(available) if available else '无'))

    def prepare_search(self):
        a = self.a
        a.ensure_foreground()
        try:
            a.wait(lambda: a.find('pair.add') or a.find('pair.home_title') or a.find('pair.tutorial_title'),
                   'APP 启动后识别配对前提页面', 20)
        except WaitTimeout as exc:
            raise TestBlocked('APP 已打开，但未找到未绑定首页入口。当前页面：' +
                              a.driver.current_activity + '；请检查登录状态、页面或遮挡弹窗。') from exc
        if not a.find('pair.add'):
            raise TestBlocked('当前为已绑定首页或使用引导页，不满足首次绑定前提。当前页面：' +
                              a.driver.current_activity + '；请解除绑定并回到 Add Device 首页。')
        a.capture('unbound-home')
        a.click('pair.add')
        self.select_model(self.options['model_label'])
        a.element('pair.prepare_title')
        a.capture('pairing-ready')
        a.click('pair.next')
        a.wait(lambda:a.find('pair.searching') or a.find('pair.results'), '搜索弹窗', 12)
        a.capture('search-started')

    def bind(self):
        a = self.a
        name = a.context['glasses_name']
        def target():
            found = [e for e in a.driver.find_elements('id', self.options['device_name_id'])
                     if e.is_displayed() and e.text == name]
            if len(found) > 1:
                raise TestBlocked('搜索到多个同名设备，无法唯一确认本轮眼镜。')
            return found[0] if found else None
        device = a.wait(target, '搜索目标眼镜 ' + name, self.options['search_timeout'])
        a.capture('target-found')
        a.popups.pairing_active = True
        try:
            # 截图可能引起列表刷新，点击前再次通过名称定位。
            a.wait(target, '重新定位目标眼镜', 5).click()
            a.log('bind', name)
            self.finish_binding()
            a.log('bluetooth-prompt-count', a.popups.pairing_accepted)
        finally:
            a.popups.pairing_active = False


    def finish_binding(self):
        a = self.a
        a.wait(lambda: self.on_tutorial() or (self.options.get('skip_tutorial') and self.on_target_home()),
               '绑定后进入使用引导或所选跳过路径的首页', self.options['bind_timeout'])
        a.capture('binding-page-observed')
        if self.options.get('skip_tutorial') and self.on_tutorial():
            a.click('pair.skip')
            a.element('pair.skip_title')
            a.click('pair.skip_confirm')
            a.wait(self.on_target_home, '跳过引导后显示目标眼镜首页', 15)
        self.observe_late_pairing()
        a.capture('binding-success')

    def on_tutorial(self):
        a = self.a
        return (a.driver.current_activity == self.options['tutorial_activity']
                and a.find('pair.tutorial_title') and a.find('pair.tutorial_begin'))

    def on_target_home(self):
        a = self.a
        if a.driver.current_activity != self.options['home_activity'] or not a.find('pair.home_title'):
            return False
        matches = [e for e in a.driver.find_elements('id', self.options['device_name_id'])
                   if e.is_displayed() and e.text == a.context['glasses_name']]
        return len(matches) == 1

    def observe_late_pairing(self):
        a = self.a
        started = time.monotonic()
        required = self.options.get('require_pairing_prompt', True)
        a.log('observe-late-pairing', {'required': required, 'timeout': self.options['late_popup_timeout']})
        def complete():
            on_tutorial = self.on_target_home() if self.options.get('skip_tutorial') else self.on_tutorial()
            elapsed = time.monotonic() - started
            if a.popups.pairing_accepted:
                return on_tutorial and elapsed >= 5
            return on_tutorial and not required and elapsed >= self.options['optional_observation_seconds']
        a.wait(complete, '确认延迟蓝牙配对弹窗并到达本轮指定页面', self.options['late_popup_timeout'])

    def run(self):
        self.prepare_search()
        self.bind()

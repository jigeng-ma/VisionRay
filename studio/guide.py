"""使用引导及通用解绑流程。"""
import time
from .pairing import PairingPage
from .home_device import HomeDevicePage


class GuidePage:
    def __init__(self, android):
        self.a = android
        self.pairing = PairingPage(android)

    def begin(self):
        a = self.a
        a.ensure_foreground()
        if not self.pairing.on_tutorial():
            # 每轮都由用例建立前置状态，避免上轮停在首页或桌面导致失败。
            HomeDevicePage(a).unbind()
            self.pairing.options['skip_tutorial'] = False
            self.pairing.run()
        if not self.pairing.on_tutorial():
            raise AssertionError('重新绑定后未进入带 Begin 按钮的使用引导入口页。')
        a.click('pair.tutorial_begin')
        a.wait(lambda: not a.find('pair.tutorial_begin') and a.find('pair.skip'), '进入引导第一页', 12)
        a.capture('guide-first-page')

    def done_to_home(self):
        a = self.a
        a.ensure_foreground()
        if a.driver.current_activity != a.context['config']['pairing']['tutorial_activity']:
            raise AssertionError('未处于使用引导页，无法继续验证 Done。')
        done = lambda: next((e for e in a.driver.find_elements('xpath',
            "//*[@package='%s' and @text='Done']" % a.context['config']['package']) if e.is_displayed()), None)
        for _ in range(20):
            if done():
                break
            size = a.driver.get_window_size()
            # ViewPager 不响应 UiAutomator2 的 swipeGesture；使用真实触点滑动。
            a.driver.swipe(int(size['width'] * .85), int(size['height'] * .50),
                           int(size['width'] * .12), int(size['height'] * .50), 500)
            time.sleep(.5)
        button = done()
        if not button:
            a.capture('guide-done-not-found')
            raise AssertionError('连续左滑引导页后未找到 Done 按钮。')
        a.capture('guide-last-page')
        button.click(); a.log('guide', 'done')
        a.wait(self.pairing.on_target_home, '点击 Done 后进入目标眼镜首页', 20)
        a.capture('guide-complete-home')

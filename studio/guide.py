"""使用引导及通用解绑流程。"""
import time
import re
from .errors import WaitTimeout
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
            # PairingPage.prepare_search 会按当前状态解绑；这里先调用 unbind
            # 会在已解绑时经 home() 额外绑定一次，再立即解绑。
            self.pairing.options['skip_tutorial'] = False
            # 本条验证引导；附近卡片配对由 PAIR 专项覆盖。
            # 通过明确型号与完整蓝牙名称建立引导前置。
            self.pairing.require_model_list = True
            self.pairing.run()
        if not self.pairing.on_tutorial():
            raise AssertionError('重新绑定后未进入带 Begin 按钮的使用引导入口页。')
        a.click('pair.tutorial_begin')
        a.wait(lambda: not a.find('pair.tutorial_begin') and a.find('pair.skip'), '进入引导第一页', 12)
        a.capture('guide-first-page')

    def done_to_home(self):
        a = self.a
        a.ensure_foreground()
        in_guide = (a.driver.current_activity == self.pairing.options['tutorial_activity']
                    and (a.find('pair.tutorial_begin') or a.find('pair.skip')))
        if not in_guide:
            # 用例可单独运行：先建立 Begin 后的引导状态，再验证 Done。
            self.begin()
        elif a.find('pair.tutorial_begin'):
            # 配对用例结束在引导入口时，同样需先进入第一页。
            a.click('pair.tutorial_begin')
            a.wait(lambda: not a.find('pair.tutorial_begin') and a.find('pair.skip'), '进入引导第一页', 12)
        done = lambda: next((e for e in a.driver.find_elements('xpath',
            "//*[@package='%s' and @text='Done']" % a.context['config']['package']) if e.is_displayed()), None)
        def page_number():
            labels = a.driver.find_elements('id', a.context['config']['package'] + ':id/tvPageCount')
            values = [re.fullmatch(r'\s*(\d+)\s*/\s*(\d+)\s*', label.text)
                      for label in labels if label.is_displayed()]
            matches = [match for match in values if match]
            if len(matches) == 1:
                return tuple(map(int, matches[0].groups()))
            return None

        for _ in range(60):
            if done():
                break
            before = page_number()
            if before and before[0] == before[1]:
                a.wait(done, '引导最后一页显示 Done', 12)
                break
            size = a.driver.get_window_size()
            for attempt in range(3):
                a.driver.swipe(int(size['width'] * .85), int(size['height'] * .72),
                               int(size['width'] * .12), int(size['height'] * .72), 500)
                try:
                    def advanced():
                        if done():
                            return True
                        after = page_number()
                        return after if before and after and after[0] > before[0] else None
                    if before:
                        after = a.wait(advanced, f'引导从第 {before[0]} 页前进', 5)
                        a.log('guide-page-advanced', {'before': before, 'after': after})
                    else:
                        time.sleep(1)
                    break
                except WaitTimeout:
                    if attempt == 2:
                        a.capture('guide-page-stuck')
                        raise AssertionError(f'引导页 {before} 连续三次滑动后页码未前进。') from None
        button = done()
        if not button:
            a.capture('guide-done-not-found')
            raise AssertionError('连续左滑引导页后未找到 Done 按钮。')
        a.capture('guide-last-page')
        button.click(); a.log('guide', 'done')
        a.wait(lambda: a.driver.current_activity != a.context['config']['pairing']['tutorial_activity'],
               '点击 Done 后离开使用引导', 20)
        # 当前版本 Done 会回到设备选择页而非直接回首页；继续完成可恢复的绑定准备。
        if not self.pairing.on_target_home():
            HomeDevicePage(a).home()
        a.wait(self.pairing.on_target_home, '完成引导后进入目标眼镜首页', 30)
        a.capture('guide-complete-home')

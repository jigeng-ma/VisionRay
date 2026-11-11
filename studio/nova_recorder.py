"""Nova 录音列表的播放与切换检查。"""
import time

from .home_device import HomeDevicePage
from .errors import TestBlocked, WaitTimeout


class NovaRecorderPage:
    def __init__(self, android):
        self.a = android
        self.package = android.context['config']['package']

    def open(self, minimum=1):
        if not self.a.driver.current_activity.endswith('RecordActivity'):
            HomeDevicePage(self.a).card('Recorder')
        # 进度条持续刷新会使 UiAutomator 的默认“等待界面空闲”一直阻塞。
        self.a.driver.update_settings({'waitForIdleTimeout': 0})
        self.a.wait(lambda: self.a.driver.find_elements('id', self.package + ':id/title_tv'),
                    'Nova 录音页', 15)
        if len(self.buttons()) < minimum:
            raise TestBlocked(f'Nova 录音列表只有 {len(self.buttons())} 条，当前用例需要至少 {minimum} 条已导入录音。')
        time.sleep(1)

    def buttons(self):
        return [e for e in self.a.driver.find_elements('id', self.package + ':id/tv_play')
                if e.is_displayed()]

    def progress(self):
        found = [e for e in self.a.driver.find_elements('id', self.package + ':id/tv_play_time')
                 if e.is_displayed()]
        if len(found) != 1:
            raise AssertionError(f'Nova 录音展开行播放时间数量异常：{len(found)}。')
        minutes, seconds = map(int, found[0].text.split(':'))
        return minutes * 60 + seconds

    def playing_row(self):
        import re
        states = [e for e in self.a.driver.find_elements('id', self.package + ':id/cl_play_state')
                  if e.is_displayed()]
        if not states:
            return None
        if len(states) != 1:
            raise AssertionError(f'Nova 录音展开播放行数量异常：{len(states)}。')
        state_y = states[0].rect['y']
        buttons = self.buttons()
        rows = [i for i, button in enumerate(buttons) if 0 <= state_y - button.rect['y'] < 400]
        if len(rows) != 1:
            raise AssertionError(f'无法将播放区关联到录音行：播放区 y={state_y}，候选 {rows}。')
        return rows[0]

    def start(self, index):
        self.buttons()[index].click()
        try:
            self.a.wait(lambda: self.playing_row() == index, f'Nova 第 {index + 1} 条录音展开', 5)
        except WaitTimeout:
            # 刚进入列表时首击偶尔只清除加载层；最多重试一次。
            self.buttons()[index].click()
            self.a.wait(lambda: self.playing_row() == index, f'Nova 第 {index + 1} 条录音展开', 8)
        before = self.progress()
        time.sleep(2)
        if self.progress() <= before:
            # 该行本来正在播放，第一次点击会暂停；再点击一次开始播放。
            self.buttons()[index].click()
            before = self.progress()
            time.sleep(2)
            if self.progress() <= before:
                raise AssertionError(f'Nova 第 {index + 1} 条录音点击播放后进度未前进。')
        self.a.capture(f'nova-recorder-playing-{index + 1}')

    def pause(self, index):
        before = self.progress()
        self.buttons()[index].click()
        time.sleep(2)
        after = self.progress()
        if after > before + 1:
            raise AssertionError(f'Nova 录音点击暂停后进度仍前进：{before}→{after} 秒。')
        self.a.capture('nova-recorder-paused')

    def assert_controls_and_seek(self):
        for resource in ('sb_seek', 'tv_share', 'tv_delete'):
            visible = [e for e in self.a.driver.find_elements('id', self.package + ':id/' + resource)
                       if e.is_displayed()]
            if len(visible) != 1:
                raise AssertionError(f'Nova 录音播放时 {resource} 控件数量异常：{len(visible)}。')
        seek = self.a.driver.find_element('id', self.package + ':id/sb_seek')
        rect = seek.rect
        before = self.progress()
        y = int(rect['y'] + rect['height'] / 2)
        self.a.driver.swipe(int(rect['x'] + rect['width'] * .25), y,
                            int(rect['x'] + rect['width'] * .65), y, 450)
        self.a.wait(lambda: self.progress() >= before + 5,
                    'Nova 录音拖动进度条后跳转播放位置', 8)

    def switch(self, repetitions=5):
        self.start(0)
        for index in (1, 0) * repetitions:
            self.buttons()[index].click()
            self.a.wait(lambda: self.playing_row() == index,
                        f'Nova 切换至第 {index + 1} 条录音', 10)
            before = self.progress()
            time.sleep(2)
            if self.progress() <= before:
                raise AssertionError(f'Nova 切换至第 {index + 1} 条录音后进度未前进。')
        self.pause(0)

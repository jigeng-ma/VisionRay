"""Submit one feedback item from the currently selected G-series device."""

import time
from uuid import uuid4

from .errors import TestBlocked, WaitTimeout
from .feedback import FeedbackClient
from .home_device import HomeDevicePage
from .settings import SettingsPage


class FeedbackPage:
    EXPECTED = {
        'MY_008': ('tv_type2', '改进建议', True, '允许'),
        'MY_009': ('tv_type1', '功能异常', False, '禁止'),
    }

    def __init__(self, android):
        self.a = android
        self.d = android.driver
        self.package = android.context['config']['package']

    def _visible(self, resource):
        return [e for e in self.d.find_elements('id', self.package + ':id/' + resource)
                if e.is_displayed()]

    def _one(self, resource, timeout=12):
        def find():
            found = self._visible(resource)
            if len(found) > 1:
                raise AssertionError(f'{resource} 匹配不唯一。')
            return found[0] if found else None
        return self.a.wait(find, resource, timeout)

    def _scroll_to(self, resource):
        for _ in range(6):
            if self._visible(resource):
                return self._one(resource)
            size = self.d.get_window_size()
            self.d.swipe(size['width'] // 2, int(size['height'] * .78),
                         size['width'] // 2, int(size['height'] * .30), 450)
        raise TestBlocked('反馈页未显示 ' + resource)

    def open(self):
        # The workbench supplies one named device. Reuse or bind only that device.
        HomeDevicePage(self.a).home()
        tabs = self._visible('tabIcon')
        if len(tabs) < 3:
            raise TestBlocked('当前设备首页缺少 My 入口。')
        tabs[-1].click()
        row = self.a.wait(lambda: next((e for e in self._visible('title')
                                       if e.text == 'Feedback'), None), 'My → Feedback', 12)
        row.click()
        self.a.wait(lambda: self._one('title_tv').text == 'Feedback', '意见反馈页', 12)

    def _select_current_device(self):
        target = self.a.context['glasses_name']
        current = self._one('tv_device_value').text.strip()
        if current == target:
            return current
        self._one('cl_device_select').click()
        try:
            options = self.a.wait(lambda: [e for e in self.d.find_elements(
                'xpath', f"//*[@package='{self.package}' and @text]")
                if e.is_displayed() and e.text.strip() == target],
                '反馈页当前眼镜选项 ' + target, 8)
        except WaitTimeout as exc:
            raise TestBlocked('反馈页没有可选的当前眼镜：' + target) from exc
        if len(options) != 1:
            raise TestBlocked('反馈页无法唯一选择当前眼镜：' + target)
        options[0].click()
        return self.a.assert_wait(lambda: self._one('tv_device_value').text.strip(), target,
                                  '反馈页已选择眼镜', 10)

    def submit_and_verify(self, case_id):
        if case_id not in self.EXPECTED:
            raise ValueError('未知反馈用例：' + case_id)
        category_control, category, consent, followup = self.EXPECTED[case_id]
        backend = FeedbackClient()
        backend.login()
        self.open()
        device = self._select_current_device()
        self._one(category_control).click()
        description = f'VisionRay {case_id} automated feedback {uuid4().hex}'
        entry = self._one('et_input')
        entry.clear()
        entry.send_keys(description)
        if entry.text.strip() != description:
            raise AssertionError('反馈描述输入后与准备提交的内容不一致。')
        if self.d.is_keyboard_shown():
            self.d.hide_keyboard()
        switch = self._scroll_to('switch_follow_up')
        setting = SettingsPage(self.a)
        if setting.is_on(switch) != consent:
            switch.click()
        if setting.is_on(self._one('switch_follow_up')) != consent:
            raise AssertionError('提交前回访授权开关状态不符。')
        self.a.capture(case_id + '-before-submit')
        self._one('tv_submit').click()
        self.a.log('feedback-submit', {'case': case_id, 'device': device,
                                       'category': category, 'followup': followup})
        deadline = time.monotonic() + 75
        record = None
        while time.monotonic() < deadline:
            matches = [item for item in backend.list_feedbacks(1)
                       if item['desc'] == description]
            if len(matches) > 1:
                raise AssertionError('后台出现多条相同描述的反馈，无法唯一核对本次提交。')
            if matches:
                record = matches[0]
                break
            time.sleep(3)
        if not record:
            self.a.capture(case_id + '-not-in-backend')
            raise AssertionError('提交后 75 秒内后台未出现本次反馈：' + case_id)
        assert record['type'] == category, f'后台分类不符：{record["type"]}'
        assert record['followup'] == followup, f'后台回访授权不符：{record["followup"]}'
        assert record['desc'] == description, '后台描述与提交内容不一致。'
        for field in ('phone_info', 'app_version', 'device_type', 'device_sn', 'device_version'):
            assert record[field].strip() not in ('', '-', '--', 'N/A', 'null'), f'后台 {field} 为空。'
        self.a.log('feedback-verified', {'case': case_id, 'category': category,
                                         'followup': followup, 'fields': 'nonempty'})
        return record

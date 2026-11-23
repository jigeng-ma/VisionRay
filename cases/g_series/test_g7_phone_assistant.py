"""G7 首页的 Android 手机 AI 助手卡片和指引。"""

from studio.home_device import HomeDevicePage


ASSISTANTS = (
    ({'google', 'pixel'}, 'Google Assistant', '谷歌助理'),
    ({'samsung'}, 'Bixby', 'Bixby'),
    ({'xiaomi', 'redmi'}, 'XiaoAi', '小爱同学'),
    ({'oppo', 'oneplus', 'realme'}, 'Breeno Assistant', '小布助手'),
    ({'vivo', 'iqoo'}, 'Jovi', 'Jovi'),
)
DESCRIPTION = 'Call, Navigation, Schedules, Alarm, Music'
FUNCTIONS = {
    'call': 'Call',
    'navigation': 'Navigation',
    'schedules': 'Schedules',
    'alarm': 'Alarm',
    'music': 'Play Music',
}


class PhoneAssistant(HomeDevicePage):
    def visible(self, resource, parent=None):
        root = self.a.driver if parent is None else parent
        return next((item for item in root.find_elements('id', f'{self.package}:id/{resource}')
                     if item.is_displayed()), None)

    def element(self, resource, label):
        return self.a.wait(lambda: self.visible(resource), label, 15)

    def card(self):
        self.home()
        direction = 'up'

        def find_card():
            nonlocal direction
            title = self.visible('tv_phone_assistant_title')
            if title:
                return title
            listing = self.visible('recyclerView')
            if listing and direction:
                more = self.a.driver.execute_script('mobile: scrollGesture', {
                    'elementId': listing.id, 'direction': direction, 'percent': .45})
                if not more:
                    direction = 'down' if direction == 'up' else None
            return None

        return self.a.wait(find_card, 'G7 首页手机 AI 助手卡片', 15)

    def open_guide(self):
        card = self.card()
        title = card.text.strip()
        assert title, '首页手机 AI 助手标题为空。'
        card.click()
        guide = self.element('phone_assistant_guide_title', '手机 AI 助手指引标题')
        assert guide.text.strip() == title, f'指引标题 {guide.text!r} 与首页 {title!r} 不一致。'
        return title, self.element('phone_assistant_guide_back', '手机 AI 助手指引返回箭头')


def test_g7_phone_assistant_card(android, adb):
    page = PhoneAssistant(android)
    phone = android.context['phone']
    brands = {adb.shell(phone, 'getprop', prop).strip().casefold()
              for prop in ('ro.product.brand', 'ro.product.manufacturer')}
    english, chinese = next(((en, zh) for aliases, en, zh in ASSISTANTS if aliases & brands),
                            ("Phone’s Assistant", '手机AI助手'))
    title = page.card()
    text = title.text.strip().replace("'", '’')
    description = page.element('tv_phone_assistant_description', '手机 AI 助手说明').text.strip()
    english_title = f'Wake up {english}'
    if description == DESCRIPTION or text.startswith('Wake up '):
        assert text == english_title, f'预期 {english_title!r}，实际 {text!r}。'
        assert description == DESCRIPTION, f'手机 AI 助手说明不符：{description!r}。'
    else:
        assert chinese in text, f'标题应显示 {chinese!r}，实际 {text!r}。'
        assert all(part in description for part in ('电话', '导航', '日程', '闹钟', '音乐')), (
            f'中文手机 AI 助手说明不符：{description!r}。')
    icons = page.element('iv_phone_assistant_apps', '手机 AI 助手右侧图标组')
    assert icons.rect['x'] >= title.rect['x'] + title.rect['width'], '助手图标组应位于标题右侧。'
    android.capture('g7-phone-assistant-card')


def test_g7_phone_assistant_guide(android):
    page = PhoneAssistant(android)
    title, _ = page.open_guide()
    remaining = FUNCTIONS.copy()
    scroll = page.element('phone_assistant_guide_scroll', '手机 AI 助手指引列表')
    scrollable = True

    def examples_visible():
        nonlocal scrollable
        for function, expected in list(remaining.items()):
            row = page.visible(f'phone_assistant_{function}')
            if row is None:
                continue
            label = page.visible('phone_assistant_function_title', row)
            example = page.visible('phone_assistant_function_example', row)
            if not (label and label.text.strip() and example and example.text.strip()):
                continue
            if title.startswith('Wake up '):
                assert label.text.strip() == expected, f'功能名称应为 {expected!r}，实际 {label.text!r}。'
            del remaining[function]
        if not remaining:
            return True
        if scrollable:
            scrollable = android.driver.execute_script('mobile: scrollGesture', {
                'elementId': scroll.id, 'direction': 'down', 'percent': .6})
        return False

    android.wait(examples_visible, '手机 AI 助手指引显示五项功能及示例', 15)
    android.capture('g7-phone-assistant-guide')


def test_g7_phone_assistant_back(android):
    page = PhoneAssistant(android)
    title, back = page.open_guide()
    back.click()
    android.element('pair.home_title', 15)
    assert page.card().text.strip() == title, '返回首页后手机 AI 助手卡片标题发生变化。'
    android.capture('g7-phone-assistant-back-home')

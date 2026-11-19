"""G5 设备管理列表、设置与已绑定设备切换。"""
import re
import time

import pytest

from cases.g5.test_reconnect import bind_additional_glasses, other_bound_name
from studio.ble_commands import BleMediaCommands
from studio.errors import TestBlocked
from studio.gallery import GalleryPage
from studio.home_device import HomeDevicePage
from studio.pairing import PairingPage, discovery_panel


MAC = r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}'
G5_MODELS = {'Flow Echo Pilot', 'Flow Echo Crystal'}


class DeviceManagement(HomeDevicePage):
    def visible(self, resource, container=None):
        root = self.a.driver if container is None else container
        return [item for item in root.find_elements('id', f'{self.package}:id/{resource}')
                if item.is_displayed()]

    def one(self, resource, container=None):
        items = self.visible(resource, container)
        assert len(items) == 1, f'{resource} 期望显示 1 项，实际 {len(items)} 项。'
        return items[0]

    def cards(self):
        self.active_names = set(self._bound_names())
        self.one('devices_menu').click()
        self.a.wait(lambda: self.a.driver.current_activity.endswith('MyDevicesActivity'), '设备管理页', 12)
        cards = {}
        for card in self.visible('container'):
            name = self.one('tvName', card).text.strip()
            assert name and name not in cards, f'设备名称为空或重复：{name!r}。'
            cards[name] = card
        return cards

    def start(self, multiple=False):
        self.home(require_target=False)
        active = self.name in self._bound_names()
        if active:
            self.connected()
        cards = self.cards()
        if self.name not in cards:
            self.keep_only_target()
            cards = self.cards()
            active = True
        assert self.name in cards, f'设备管理未显示当前目标 {self.name}：{list(cards)}。'
        if not active:
            self.switch(cards[self.name], self.name)
            cards = self.cards()
        if multiple and len(cards) == 1:
            added = bind_additional_glasses(self.a, cards)
            self.select_home(added)
            cards = self.cards()
            assert {self.name, added} <= cards.keys(), '添加第二台后未同时显示两台设备。'
            self.switch(cards[self.name], self.name)
            cards = self.cards()
        return cards

    def select_home(self, name):
        self.a.wait(lambda: self.a.find('pair.home_title') and name in self._bound_names(),
                    f'首页显示 {name}', 35)

    def keep_only_target(self):
        """双设备用例收尾：删除辅助绑定，恢复本轮目标，不改变测试断言。"""
        self.home(require_target=False)
        active = set(self._bound_names())
        cards = self.cards()
        auxiliaries = set(cards) - {self.name}
        for name in sorted(auxiliaries):
            # 每次解绑都会重绘列表，不能复用上一次的卡片元素。
            if name in active:
                self.a.driver.press_keycode(4)
                self.select_home(name)
            else:
                self.switch(cards[name], name)
            auxiliary = HomeDevicePage(self.a)
            auxiliary.name = name
            auxiliary.unbind(require_empty=False, allow_discovery=True)
            if discovery_panel(self.a) is not None:
                PairingPage(self.a).cancel_discovery()
            if self.a.find('pair.add'):
                break
            self.home(require_target=False)
            active = set(self._bound_names())
            cards = self.cards()
        # SS_005 验证的正是解绑目标；断言完成后需重新配回目标。
        self.home()
        cards = self.cards()
        assert set(cards) == {self.name}, f'用例收尾后应仅保留 {self.name}，实际 {list(cards)}。'
        self.switch(cards[self.name], self.name)
        self.a.log('multi-device-cleanup', {'removed': sorted(auxiliaries), 'remaining': self.name})
        self.a.capture('multi-device-cleanup-target-only')

    def switch(self, card, name):
        if name in getattr(self, 'active_names', set()):
            self.a.driver.press_keycode(4)
        else:
            card.click()
        self.select_home(name)
        home = HomeDevicePage(self.a)
        home.name = name
        home.connected()

    def card_details(self, name, card):
        model = self.one('tvTag', card).text.strip()
        identifier = self.one('tvSn', card).text.strip()
        assert model, f'{name} 未显示型号。'
        if re.fullmatch(self.a.context['config']['name_pattern'], name, re.I):
            assert model in G5_MODELS, f'{name} 显示了错误的 G5 型号：{model}。'
        legacy = re.fullmatch(r'DPVR\s+(G1|G3|G6)[-_]\S+', name, re.I)
        if legacy:
            assert model.upper().removeprefix('DPVR ') == legacy[1].upper(), f'{name} 的型号不一致：{model}。'
        if re.fullmatch(r'DPVR\s+G7[-_]\S+', name, re.I):
            assert model in {'Flow Pro Pilot', 'Flow Pro Crystal'}, f'{name} 的 G7 型号不一致：{model}。'
        if re.search(r'\bNova\b', model, re.I):
            match = re.fullmatch(r'SN\s*[:：]\s*([\w-]+)', identifier, re.I)
        else:
            match = re.fullmatch(rf'MAC\s*[:：]\s*({MAC})', identifier, re.I)
        assert match, f'{name} 的设备标识格式错误：{identifier!r}。'
        self.one('ivDevice', card)
        self.one('ivSettings', card)
        return model, match[1].upper()

    def setting_value(self, label):
        selector = (f"//*[@resource-id='{self.package}:id/tv_title' and @text={label!r}]"
                    f"/parent::*//*[@resource-id='{self.package}:id/tv_hint']")
        value = self.a.wait(lambda: next((item.text.strip() for item in
                            self.a.driver.find_elements('xpath', selector) if item.is_displayed()), None),
                            f'系统设置 {label}', 12)
        return value


@pytest.fixture
def devices(android, record_property):
    return DeviceManagement(android), record_property


def run(devices, action):
    page, record_property = devices
    try:
        action(page)
    except TestBlocked as exc:
        page.a.capture('g5-device-management-blocked')
        record_property('studio_status', 'BLOCKED')
        pytest.skip(str(exc))


def test_g5_device_list(devices):
    def check(page):
        cards = page.start(multiple=True)
        details = {name: page.card_details(name, card) for name, card in cards.items()}
        assert len({identifier for _, identifier in details.values()}) == len(cards), '设备列表存在重复标识。'
        page.a.log('g5-device-list', details)
        page.a.capture('g5-device-list')
    run(devices, check)


def test_g5_device_settings(devices):
    def check(page):
        card = page.start()[page.name]
        model, address = page.card_details(page.name, card)
        page.a.capture('g5-device-settings-entry')
        settings = page.one('ivSettings', card)
        assert settings.is_enabled(), f'{page.name} 的设置入口不可点击。'
        settings.click()
        page.assert_system_info()
        assert page.setting_value('Glasses Name') == page.name, '设置页名称与设备卡片不一致。'
        assert page.setting_value('Model') == model, '设置页型号与设备卡片不一致。'
        assert page.setting_value('BT MAC').upper() == address, '设置页 MAC 与设备卡片不一致。'
    run(devices, check)


def test_g5_switch_bound_device(devices):
    def check(page):
        cards = page.start(multiple=True)
        target = other_bound_name(page.a.context, cards)
        page.switch(cards[target], target)
        page.a.log('g5-device-switched', {'from': page.name, 'to': target})
        page.a.capture('g5-device-switched-connected')
        page.switch(page.cards()[page.name], page.name)
    run(devices, check)


def test_g5_unbind_one_of_multiple_devices(devices):
    def check(page):
        before = set(page.start(multiple=True))
        assert len(before) >= 2 and page.name in before, '解绑前必须在设备管理确认目标 G5 和其他设备。'
        page.a.capture('g5-before-unbinding-one')
        page.a.driver.press_keycode(4)
        page.select_home(page.name)
        assert page.unbind(require_empty=False), '解绑一台后应跳转到其他设备首页。'
        expected = before - {page.name}
        active = set(page._bound_names())
        assert active & expected and page.name not in active, f'解绑后的首页设备不符：{sorted(active)}。'
        page.a.capture('g5-other-device-after-unbind')
        remaining = set(page.cards())
        assert remaining == expected, f'解绑后设备列表应为 {sorted(expected)}，实际 {sorted(remaining)}。'
        page.a.capture('g5-device-list-after-unbind')
    run(devices, check)


def test_g5_pair_from_device_management(devices):
    def check(page):
        page.home(require_target=False)
        active = page._bound_names()
        cards = page.cards()
        if page.name in cards:
            page.a.driver.press_keycode(4)
            try:
                before = set(page.start(multiple=True))
            except AssertionError as exc:
                if not any(marker in str(exc) for marker in ('Binding Failed', 'APP 绑定失败')):
                    raise
                page.a.log('g5-pair-preparation-retry', str(exc))
                page.a.restart()
                try:
                    before = set(page.start(multiple=True))
                except AssertionError as retry_error:
                    if not any(marker in str(retry_error) for marker in ('Binding Failed', 'APP 绑定失败')):
                        raise
                    raise TestBlocked('准备第二台已有设备时，APP 两次提示 Binding Failed。') from retry_error
            page.a.driver.press_keycode(4)
            page.select_home(page.name)
            assert page.unbind(require_empty=False), '准备配对前应保留其他已绑定设备。'
            time.sleep(60)
            active = page._bound_names()
            cards = page.cards()
            assert set(cards) == before - {page.name}, '准备配对时已有设备列表异常。'
        before = set(cards)
        if len(active) != 1 or active[0] not in before:
            raise TestBlocked('配对前无法确认设备管理页对应的已绑定眼镜。')
        context = page.a.context
        original_inventory = context.get('glasses_inventory')
        try:
            context.update(glasses_name=active[0], glasses_inventory=[
                {'product': 'G5', 'model': 'G5', 'glasses_name': page.name}])
            assert bind_additional_glasses(page.a, cards) == page.name
        finally:
            context['glasses_name'] = page.name
            if original_inventory is None:
                context.pop('glasses_inventory', None)
            else:
                context['glasses_inventory'] = original_inventory
        page.connected()
        assert set(page.cards()) == before | {page.name}, '配对成功后设备列表与原绑定不一致。'
        page.a.capture('g5-paired-from-device-management')
    run(devices, check)


def _pending_unpair_actions(page):
    a = page.a
    if discovery_panel(a) is not None:
        PairingPage(a).cancel_discovery()
    cards = page.start()
    if set(cards) != {page.name}:
        raise TestBlocked(f'本用例需要仅绑定目标 G5，当前列表：{list(cards)}。')
    a.driver.press_keycode(4)
    page.select_home(page.name)
    gallery = GalleryPage(a)
    if not gallery.pending_count_or_zero('home'):
        BleMediaCommands(a).take_photo()
        a.assert_wait(lambda: gallery.pending_count_or_zero('home'), 1, '测试照片出现在待导入通知', 60)
    page.open_unpair_confirmation()
    actions = a.wait(page.pending_media_unpair_actions, '待导入提醒同时显示 Unpair 和 Import', 15)
    a.capture('unpair-pending-media-reminder')
    return actions


def test_g5_pending_media_unpair(devices):
    def check(page):
        unpair, _ = _pending_unpair_actions(page)
        unpair.click()
        a = page.a
        a.wait(lambda: a.find('pair.add') or discovery_panel(a), '解绑后进入未绑定界面', 20)
        if discovery_panel(a) is not None:
            PairingPage(a).cancel_discovery()
        a.wait(lambda: a.find('pair.add') and not page._bound_names(), '未绑定设备首页', 15)
        a.capture('unpair-with-pending-media-home')
    run(devices, check)


def test_g5_pending_media_import(devices):
    def check(page):
        _, import_media = _pending_unpair_actions(page)
        import_media.click()
        page.select_home(page.name)
        page.a.wait(lambda: not page.pending_media_unpair_actions(), '导入后关闭解绑提醒', 15)
        page.a.capture('unpair-import-returns-home')
    run(devices, check)

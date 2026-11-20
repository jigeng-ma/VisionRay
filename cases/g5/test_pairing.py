"""G5 冒烟表中的 Flow Echo Pilot 和 Crystal 配对用例。"""

import re
from xml.etree import ElementTree as ET

import pytest

from studio.errors import TestBlocked, WaitTimeout
from studio.pairing import PairingPage, discovery_panel


def pair_flow_model(android, request, model_label):
    try:
        pairing = PairingPage(android)
        original = pairing.options.copy()
        try:
            pairing.options.update(model_label=model_label, skip_tutorial=False)
            pairing.require_model_list = True
            pairing.clear_bound_model = True
            pairing.run()
            assert pairing.on_tutorial(), f'{model_label} 绑定后未进入使用引导。'
        finally:
            pairing.options.update(original)
    except TestBlocked as exc:
        android.capture('blocked')
        request.node.user_properties.append(('studio_status', 'BLOCKED'))
        pytest.skip(str(exc))


def test_pair_flow_echo_pilot(android, request):
    pair_flow_model(android, request, 'Flow Echo Pilot')


def test_pair_flow_echo_crystal(android, request):
    pair_flow_model(android, request, 'Flow Echo Crystal')


def _nearby(android):
    pairing = PairingPage(android)
    pairing.clear_bound_model = True
    pairing.prepare_model_search()
    if discovery_panel(android) is None:
        android.log('nearby-reopen', '重启 APP 后重新检查附近设备入口')
        android.restart()
        pairing.prepare_model_search()
    if discovery_panel(android) is None:
        raise TestBlocked('重启后 Add Device 仍打开型号列表，当前未能进入附近设备卡片。')
    pairing.options.update(skip_tutorial=False, require_pairing_prompt=True)
    return pairing


def _check_card(pairing, name):
    a = pairing.a
    package = a.context['config']['package']
    snapshot = ET.fromstring(a.driver.page_source)
    by_id = lambda node, key: node.get('resource-id') == package + ':id/' + key
    cards = [card for card in snapshot.iter() if any(by_id(child, 'device_name') and child.get('text') == name
             for child in card)]
    assert len(cards) == 1, f'未找到唯一设备卡片：{name}。'
    card = cards[0]
    assert any(by_id(node, 'device_image') and node.get('displayed') != 'false' for node in card.iter()), '眼镜图片未显示。'
    addresses = [node.get('text', '') for node in card.iter() if by_id(node, 'device_address')]
    assert len(addresses) == 1 and re.fullmatch(r'(?:[0-9A-F]{2}:){5}[0-9A-F]{2}', addresses[0], re.I), '设备 MAC 缺失或格式错误。'
    pairing.discovery_action('pair', 'Pair')
    pairing.discovery_action('cancel', 'Cancel')
    a.log('discovery-card', {'name': name, 'mac': addresses[0]})
    a.capture('nearby-device-card')


def _current_card(android):
    panel = discovery_panel(android)
    if panel is None:
        return None
    package = android.context['config']['package']
    carousel = panel.find_elements('id', package + ':id/device_carousel')
    if len(carousel) != 1:
        return None
    rect = carousel[0].rect
    names = [item for item in panel.find_elements('id', package + ':id/device_name') if item.is_displayed()]
    for item in names:
        bounds = item.rect
        if abs(bounds['x'] + bounds['width'] / 2 - rect['x'] - rect['width'] / 2) < rect['width'] * .12:
            return item.text, {entry.text for entry in names}
    return None


def _run_nearby(android, record_property, action):
    try:
        action(_nearby(android))
    except TestBlocked as exc:
        android.capture('nearby-precondition-blocked')
        record_property('studio_status', 'BLOCKED')
        pytest.skip(str(exc))


def test_nearby_card_pair(android, record_property):
    name = android.context['glasses_name']
    _run_nearby(android, record_property, lambda page: page.bind_discovered(lambda _: _check_card(page, name)))


def test_nearby_swipe_pair(android, record_property):
    def swipe_and_pair(page):
        name = android.context['glasses_name']
        def multiple_cards():
            state = _current_card(android)
            return state if state and name in state[1] and len(state[1]) >= 2 else None
        try:
            current, candidates = android.wait(multiple_cards, f'附近设备显示目标 {name} 和另一台眼镜', 25)
        except WaitTimeout as exc:
            state = _current_card(android)
            observed = '、'.join(sorted(state[1])) if state else '无'
            raise TestBlocked(f'附近设备未同时显示目标 {name} 和另一台眼镜。已发现：{observed}。') from exc
        if current == name:
            alternate = sorted(candidates - {name})[0]
            page.center_discovered(alternate)
            android.log('nearby-prepare-non-target-card', alternate)
            current, _ = android.wait(lambda: _current_card(android), '确认非目标卡片居中', 10)
            assert current == alternate, '未能建立非目标卡片居中的前置条件。'
        android.log('nearby-initial-card', current)
        page.bind_discovered(lambda _: _check_card(page, name))
    _run_nearby(android, record_property, swipe_and_pair)


def test_nearby_card_cancel(android, record_property):
    def check_and_cancel(page):
        name = android.context['glasses_name']
        page.center_discovered(name)
        _check_card(page, name)
        page.cancel_discovery()
        android.capture('nearby-device-cancelled')
    _run_nearby(android, record_property, check_and_cancel)

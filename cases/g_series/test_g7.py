"""NovaAPP-G7 冒烟表中的 G7 专属用例。"""
import re
from xml.etree import ElementTree as ET

import pytest

from studio.errors import TestBlocked, WaitTimeout
from studio.g7 import G7Page
from studio.home_device import HomeDevicePage
from studio.pairing import PairingPage, discovery_panel


def _require_g7(android):
    config = android.context['config']
    if (config['product'], config['model']) != ('G7', 'G7'):
        raise TestBlocked('本用例要求选择 G7 和对应的眼镜蓝牙名称。')


def _bound_home(android):
    _require_g7(android)
    home = HomeDevicePage(android)
    try:
        home.home()
    except (TestBlocked, WaitTimeout):
        pairing = PairingPage(android)
        pairing.options['skip_tutorial'] = True
        pairing.options['require_pairing_prompt'] = False
        pairing.run()
        home.home()
    return home


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


def test_pair_flow_pro_pilot(android, request):
    pair_flow_model(android, request, 'Flow Pro Pilot')


def test_pair_flow_pro_crystal(android, request):
    pair_flow_model(android, request, 'Flow Pro Crystal')


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
        try:
            current, _ = android.wait(lambda: _current_card(android), '附近设备显示居中卡片', 25)
            if current == name:
                page.center_discovered(name, alternate=True)
                current, _ = android.wait(lambda: _current_card(android), '确认非目标卡片居中', 10)
                assert current != name, '未能建立非目标卡片居中的前置条件。'
            android.log('nearby-initial-card', current)
            page.center_discovered(name)
        except WaitTimeout as exc:
            state = _current_card(android)
            visible = '、'.join(sorted(state[1])) if state else '无'
            raise TestBlocked(f'附近设备搜索未完成：{exc} 当前可见卡片：{visible}。') from exc
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


def test_g7_device_settings(android):
    home = _bound_home(android)
    home.a.driver.find_element('id', home.package + ':id/devices_menu').click()
    home.a.wait(lambda: home.a.driver.current_activity.endswith('MyDevicesActivity'), '设备管理页', 12)
    names = [e.text for e in home.a.driver.find_elements('id', home.package + ':id/tvName')
             if e.is_displayed()]
    assert home.name in names, f'设备管理页未显示目标 G7：{home.name}，实际 {names}。'
    icons = [e for e in home.a.driver.find_elements('id', home.package + ':id/ivDevice')
             if e.is_displayed()]
    assert icons, 'G7 设备卡片未显示眼镜图标。'
    home.a.capture('g7-device-card-icon')
    settings = [e for e in home.a.driver.find_elements('id', home.package + ':id/ivSettings')
                if e.is_displayed()]
    assert len(settings) == 1, f'G7 设备设置入口数量错误：{len(settings)}。'
    settings[0].click()
    home.assert_system_info()
    home.a.capture('g7-device-settings')


def test_g7_device_switch(android):
    home = _bound_home(android)
    home.a.driver.find_element('id', home.package + ':id/devices_menu').click()
    home.a.wait(lambda: home.a.driver.current_activity.endswith('MyDevicesActivity'), '设备选择页', 12)
    cards = [e for e in home.a.driver.find_elements('id', home.package + ':id/tvName')
             if e.is_displayed() and e.text == home.name]
    assert len(cards) == 1, f'设备选择页未唯一显示 G7 {home.name}：{len(cards)} 项。'
    containers = [e for e in home.a.driver.find_elements('id', home.package + ':id/container')
                  if e.is_displayed() and any(child.text == home.name for child in
                  e.find_elements('id', home.package + ':id/tvName'))]
    assert len(containers) == 1, f'目标 G7 设备卡片不唯一：{len(containers)} 项。'
    containers[0].click()
    # 已经选中这台眼镜时，APP 保持在 My Devices；使用页面返回入口。
    if home.a.driver.current_activity.endswith('MyDevicesActivity'):
        back = [e for e in home.a.driver.find_elements('id', home.package + ':id/ivBack')
                if e.is_displayed() and e.is_enabled()]
        assert len(back) == 1, f'设备选择页返回入口数量错误：{len(back)}。'
        back[0].click()
    home.a.wait(lambda: home.a.find('pair.home_title') or home.a.find('pair.tutorial_begin'),
                '选择 G7 后首页或引导页', 30)
    home.home()
    home.connected()


def test_g7_conversation_modes(android):
    _bound_home(android)
    G7Page(android).conversation_modes()


def _video(android, width, height, fps, duration, save_on_failure=False):
    _bound_home(android)
    for attempt in range(2):
        page = G7Page(android)
        try:
            page.set_video(width, height, fps, duration)
            break
        except RuntimeError as exc:
            if attempt or not any(marker in str(exc) for marker in
                                  ('UiAutomator2 服务进程已退出', 'instrumentation process is not running')):
                raise
            android.log('g7-driver-reconnect', {'phase': 'set_video', 'error': str(exc)})
            try:
                android.close()
            except Exception:
                pass
            android.driver = None
            android.connect()
            _bound_home(android)
    try:
        page.record_and_check(duration, width, height, fps)
    except Exception:
        if save_on_failure:
            try:
                issue = page.save_failed_video()
                if issue:
                    android.log('g7-failed-video-unavailable', issue)
            except Exception as copy_error:
                android.log('g7-failed-video-unavailable', str(copy_error))
        raise


def test_g7_video_2k5_1min(android):
    _video(android, 2560, 1920, 30, 60)


def test_g7_video_2k5_30s(android):
    _video(android, 2560, 1920, 30, 30)


def test_g7_video_1080p_60fps(android):
    _video(android, 1920, 1080, 60, 30)


VIDEO_VARIANTS = (
    (3840, 2160, 30, 15), (3840, 2160, 30, 30),
    (3264, 2448, 30, 15), (3264, 2448, 30, 30),
    (2560, 1920, 30, 30), (2560, 1920, 30, 60), (2560, 1920, 30, 180),
    (1920, 1080, 60, 30), (1920, 1080, 60, 60), (1920, 1080, 60, 180),
    (1920, 1080, 60, 300), (1920, 1080, 60, 540), (1920, 1080, 60, 720),
    (1920, 1080, 30, 30), (1920, 1080, 30, 60), (1920, 1080, 30, 180),
    (1920, 1080, 30, 300), (1920, 1080, 30, 540), (1920, 1080, 30, 720),
    (1920, 2560, 30, 30), (1920, 2560, 30, 60), (1920, 2560, 30, 180),
    (1440, 2560, 30, 30), (1440, 2560, 30, 60), (1440, 2560, 30, 180),
)


@pytest.mark.parametrize('width,height,fps,duration', VIDEO_VARIANTS,
                         ids=[f'Cam_{number:03d}' for number in range(11, 36)])
def test_g7_video_variant(android, width, height, fps, duration):
    _video(android, width, height, fps, duration, save_on_failure=True)

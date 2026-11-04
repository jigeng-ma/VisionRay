"""NovaAPP-G7 冒烟表中的 G7 专属用例。"""
import re
import pytest

from studio.errors import TestBlocked, WaitTimeout
from studio.g7 import G7Page
from studio.home_device import HomeDevicePage
from studio.pairing import PairingPage


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


def _pair_flow_model(android, model):
    _require_g7(android)
    pairing = PairingPage(android)
    pairing.options['model_label'] = model
    pairing.run()
    assert pairing.on_tutorial() or pairing.on_target_home(), (
        f'选择 {model} 后，未完成到目标眼镜 {android.context["glasses_name"]} 的绑定。')


def test_pair_flow_pro_pilot(android):
    _pair_flow_model(android, 'Flow Pro Pilot')


def test_pair_flow_pro_crystal(android):
    _pair_flow_model(android, 'Flow Pro Crystal')


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


def _video(android, width, height, fps, duration):
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
    page.record_and_check(duration, width, height, fps)


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
    _video(android, width, height, fps, duration)


def test_g7_all_video_combinations(android):
    _bound_home(android)
    def fresh_page():
        try:
            android.close()
        except Exception:
            pass
        android.driver = None
        android.connect()
        return G7Page(android)

    def driver_lost(error):
        return any(marker in str(error) for marker in
                   ('UiAutomator2 服务进程已退出', 'instrumentation process is not running'))

    page = G7Page(android)
    for attempt in range(2):
        try:
            page.capture()
            specifications = page.option_texts(('Video Specs', 'Video Resolution', 'Video Specification', 'Video Format'))
            break
        except Exception as exc:
            if not driver_lost(exc) or attempt:
                raise
            page = fresh_page()
    assert specifications, '未读到视频规格选项。'
    for specification in specifications:
        size = re.search(r'(\d{3,4})\s*[x×*]\s*(\d{3,4})', specification, re.I)
        if size:
            width, height = map(int, size.groups())
        elif '2.5k' in specification.lower():
            width, height = 2560, 1920
        else:
            raise AssertionError(f'无法从视频规格读取分辨率：{specification}。')
        rate = re.search(r'(\d+)\s*fps', specification, re.I)
        if not rate:
            raise AssertionError(f'无法从视频规格读取帧率：{specification}。')
        for attempt in range(2):
            try:
                page.capture()
                page.choose_option(('Video Specs', 'Video Resolution', 'Video Specification', 'Video Format'),
                                   '^' + re.escape(specification) + '$')
                durations = page.option_texts(('Video Duration', 'Recording Duration'))
                break
            except Exception as exc:
                if not driver_lost(exc) or attempt:
                    raise
                page = fresh_page()
        assert durations, f'{specification} 未提供任何录像时长。'
        android.log('g7-video-available-durations', {'specification': specification,
                                                    'durations': durations})
        for label in durations:
            seconds = G7Page.seconds(label)
            for attempt in range(2):
                try:
                    page.capture()
                    page.choose_option(('Video Specs', 'Video Resolution', 'Video Specification', 'Video Format'),
                                       '^' + re.escape(specification) + '$')
                    page.choose_option(('Video Duration', 'Recording Duration'), '^' + re.escape(label) + '$')
                    page.record_and_check(seconds, width, height, int(rate.group(1)))
                    break
                except Exception as exc:
                    if not driver_lost(exc) or attempt:
                        raise
                    android.log('g7-driver-reconnect', {'specification': specification,
                                                        'duration': label})
                    page = fresh_page()
            android.log('g7-video-combination-passed', {'specification': specification,
                                                        'duration': label})
            page = fresh_page()

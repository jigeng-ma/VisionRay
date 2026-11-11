"""Nova 冒烟测试用例：配对与新手引导。"""
from studio.nova import NovaPage
from studio.nova_ota import run_manual_update
from studio.home_device import HomeDevicePage
from studio.nova_wifi import NovaWifiPage
from studio.nova_recorder import NovaRecorderPage
from studio.settings import SettingsPage
from studio.errors import TestBlocked
from unittest import SkipTest


def test_pair(android):
    NovaPage(android).pair()


def test_skip_guide(android):
    NovaPage(android).skip_guide()


def test_wear_guide(android):
    page = NovaPage(android)
    page.prepare_guide('wear')
    page.wear_guide()


def test_photo_guide(android):
    page = NovaPage(android)
    page.prepare_guide('photo')
    page.photo_guide()


def test_video_guide(android):
    page = NovaPage(android)
    page.prepare_guide('video')
    page.video_guide()


def test_audio_guide(android):
    page = NovaPage(android)
    page.prepare_guide('audio')
    page.audio_guide()


def test_music_guide(android):
    page = NovaPage(android)
    page.prepare_guide('music')
    page.music_guide()


def test_firmware_update(android, request):
    try:
        detail = run_manual_update(android)
    except TestBlocked as exc:
        raise SkipTest(str(exc)) from exc
    request.node.user_properties.append(('studio_detail', detail))


def test_connected_home_card(android):
    page = HomeDevicePage(android)
    page.home()
    name = android.context['glasses_name']
    if name not in page._bound_names():
        raise AssertionError(f'Nova 首页未显示已绑定眼镜 {name}。')
    values = [e.text.strip() for e in android.driver.find_elements(
        'id', page.package + ':id/tv_battery_percent') if e.is_displayed()]
    if len(values) != 1 or not values[0].rstrip('%').isdigit():
        raise AssertionError(f'Nova 首页眼镜电量显示异常：{values}。')
    android.capture('nova-connected-home-card')


def test_recorder_page(android):
    page = HomeDevicePage(android)
    page.card('Recorder')
    page.text('Recorder', 15)
    has_list = bool(android.driver.find_elements('id', page.package + ':id/recycler_view'))
    empty = bool(android.driver.find_elements('xpath', "//*[contains(@text, 'No recordings')]") )
    if not has_list and not empty:
        raise AssertionError('Nova 录音页既未显示录音列表，也未显示空列表提示。')
    android.capture('nova-recorder-page')


def test_wifi_connect(android):
    NovaWifiPage(android).connect('wifi_a')


def test_wifi_switch(android):
    page = NovaWifiPage(android)
    for key in ('wifi_a', 'wifi_b', 'wifi_a', 'wifi_b', 'wifi_a', 'wifi_b'):
        page.connect(key)


def test_rename_glasses(android):
    NovaPage(android).rename()


def test_video_stabilization_switch(android):
    NovaPage(android).open_setting('Capture', 'Capture Settings')
    settings = SettingsPage(android)
    settings.on('shake_algorithm_switch')
    settings.off('shake_algorithm_switch')
    settings.on('shake_algorithm_switch')
    android.capture('nova-stabilization-on')


def test_open_ai_chat(android):
    HomeDevicePage(android).card('AI Chat History')
    android.wait(lambda: "I'm Sunny" in android.driver.page_source,
                 'Nova DP AI 对话入口', 20)
    android.capture('nova-ai-chat-open')


def test_unpair_glasses(android):
    NovaPage(android).unpair()


def test_recorder_play_pause(android):
    page = NovaRecorderPage(android)
    page.open()
    page.start(0)
    page.assert_controls_and_seek()
    page.pause(0)


def test_recorder_switch(android):
    page = NovaRecorderPage(android)
    page.open(minimum=2)
    page.switch()

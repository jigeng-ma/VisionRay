import functools
import pytest
from studio.errors import TestBlocked
from studio.home_device import HomeDevicePage


def page(android):
    try: return HomeDevicePage(android)
    except TestBlocked as exc:
        android.capture('blocked'); pytest.skip(str(exc))


def guarded(android, action):
    try:
        action()
    except TestBlocked as exc:
        android.capture('blocked')
        pytest.skip(str(exc))


def requires_home(action):
    @functools.wraps(action)
    def run(android, *args):
        guarded(android, lambda: action(android, *args))
    return run


@requires_home
def test_bottom_navigation(android):
    def run():
        p=page(android); p.home()
        icons=[e for e in android.driver.find_elements('id', p.package + ':id/tabIcon') if e.is_displayed()]
        if len(icons) < 3: raise AssertionError('底部导航入口不足。')
        icons[1].click(); p.text('Gallery', 15)
        icons[2].click(); p.assert_page('My', 'Account')
        icons[0].click(); p.home()
    guarded(android, run)


@requires_home
def test_restart_reconnect(android, adb): page(android).restart_and_reconnect(adb)
@requires_home
def test_translation(android): p=page(android); p.card('Translation'); p.assert_page('Translation', 'Chat')
@requires_home
def test_recorder(android): p=page(android); p.card('Recorder'); p.text('Recorder', 15)
@requires_home
def test_dp_ai_card(android):
    p=page(android); p.card('DP AI'); p.text('DP AI', 15)
    icons=[e for e in android.driver.find_elements('xpath', "//*[@resource-id='com.dpvr.android.app.Occident:id/iv_setting' and @content-desc='DP AI Settings']") if e.is_displayed()]
    if len(icons) != 1: raise AssertionError('DP AI 页面未唯一显示右上设置入口。')
@requires_home
def test_dp_ai_settings(android): p=page(android); p.setting('DP AI'); p.text('DP AI Settings', 15)
@requires_home
def test_capture_settings(android): p=page(android); p.setting('Capture'); p.assert_page('Capture Settings', 'Photo Watermark')
@requires_home
def test_system_settings(android): p=page(android); p.setting('System Settings'); p.assert_system_info()
@requires_home
def test_device_system_settings(android): page(android).device_settings()


@requires_home
def test_bluetooth_reconnect(android, adb):
    p=page(android); p.home(); serial=android.context['phone']
    try:
        adb.shell(serial, 'cmd', 'bluetooth_manager', 'disable')
        android.wait(lambda: next((e for e in android.driver.find_elements('xpath', "//*[@text='Bluetooth is off']") if e.is_displayed()), None), '蓝牙断连提示', 12)
        android.capture('bluetooth-off')
        adb.shell(serial, 'cmd', 'bluetooth_manager', 'enable')
        app_turn_on = android.wait(lambda: next((e for e in android.driver.find_elements('id', p.package + ':id/btn_confirm') if e.is_displayed() and e.text == 'Turn on'), None), 'APP 蓝牙开启确认', 15)
        app_turn_on.click(); android.log('bluetooth-popup', 'app-turn-on')
        allow = android.wait(lambda: next((e for e in android.driver.find_elements('xpath', "//*[@resource-id='android:id/button1' and @text='Allow']") if e.is_displayed()), None), '系统蓝牙开启授权', 15)
        allow.click(); android.log('bluetooth-popup', 'system-allow')
        android.wait(lambda: android.driver.current_package == p.package, '返回 VisionRay', 15)
        p.connected()
    finally:
        adb.shell(serial, 'cmd', 'bluetooth_manager', 'enable')


@requires_home
def test_visual_search(android):
    p=page(android); p.card('Visual Search')
    android.wait(lambda: android.driver.current_activity.endswith('AIConversationActivity'), '拍照识图会话页', 35)
    answers=[e for e in android.driver.find_elements('id', p.package + ':id/tv_ai') if e.is_displayed() and e.text.strip()]
    if not answers: android.wait(lambda: any(e.is_displayed() and e.text.strip() for e in android.driver.find_elements('id', p.package + ':id/tv_ai')), 'AI 识图回答', 50)
    android.capture('visual-search-result')

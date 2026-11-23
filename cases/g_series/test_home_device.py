import functools
import re
import time
import pytest
from studio.errors import TestBlocked, WaitTimeout
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
    def run(android, *args, **kwargs):
        guarded(android, lambda: action(android, *args, **kwargs))
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
def test_recorder(android):
    p = page(android)
    p.card('Recorder')
    if android.context['config'].get('model') not in {'G5', 'G7'}:
        p.text('Recorder', 15)
        return

    def recorder_opened():
        titles = android.driver.find_elements('id', p.package + ':id/list_title')
        if any(title.is_displayed() and title.text == 'Recording Minutes' for title in titles):
            return True
        return not android.find('pair.home_title') and any(item.is_displayed() for item in android.driver.find_elements(
            'xpath', f"//*[@package='{p.package}' and @text='Recorder']"))
    android.wait(recorder_opened, '录音列表 Recording Minutes', 15)
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
        clicked = set()

        def resumed():
            driver = android.driver
            for resource, text, event in (
                ('android:id/button1', 'Allow', 'system-allow'),
                (p.package + ':id/btn_confirm', 'Turn on', 'app-turn-on'),
            ):
                if event == 'system-allow' and 'app-turn-on' not in clicked:
                    continue
                buttons = [e for e in driver.find_elements('id', resource)
                           if e.is_displayed() and e.is_enabled() and e.text == text]
                if buttons:
                    if len(buttons) == 1 and event not in clicked:
                        buttons[0].click()
                        clicked.add(event)
                        android.log('bluetooth-popup', event)
                    return False
            return (driver.current_package == p.package
                    and adb.shell(serial, 'settings', 'get', 'global', 'bluetooth_on') == '1'
                    and not any(e.is_displayed() for e in driver.find_elements(
                        'xpath', "//*[@text='Bluetooth is off']")))

        android.wait(resumed, 'APP 蓝牙开启确认或自动重连', 40)
        p.connected()
    finally:
        adb.shell(serial, 'cmd', 'bluetooth_manager', 'enable')


@requires_home
def test_visual_search(android, adb, record_property):
    p = page(android)
    opened = lambda: android.driver.current_activity.endswith('AIConversationActivity')
    if android.context['config'].get('model') == 'G7':
        p.connected()
        phone = android.context['phone']
        def sdk_logs():
            pid = adb.shell(phone, 'pidof', p.package)
            return adb.run('-s', phone, 'logcat', '-d', '--pid=' + pid, '-v', 'epoch', '-s',
                           'DPVRHelper:D', 'AiAssistServiceMonitor:I') if pid.isdigit() else ''

        connection_details = []

        def last_sdk_state(log):
            states = re.findall(
                r'^[ \t]*(\d+\.\d+)\s+(\d+)\s+\d+\s+\w\s+'
                r'DPVRHelper:\s+connectionState = (\w+)\b', log, re.M)
            return states[-1] if states else None

        def wait_for_connection(reconnect_after=None):
            started = time.monotonic()
            ready_since = None
            last_connected_event = None
            waited_for_reconnect = reconnect_after is not None

            def connected():
                nonlocal ready_since, last_connected_event, waited_for_reconnect
                latest = last_sdk_state(sdk_logs())
                if (not latest or latest[2] != 'CONNECTED'
                        or (reconnect_after is not None and float(latest[0]) < reconnect_after)):
                    waited_for_reconnect = True
                    ready_since = last_connected_event = None
                    return False
                now = time.monotonic()
                if latest != last_connected_event:
                    if last_connected_event is not None:
                        waited_for_reconnect = True
                    ready_since = now
                    last_connected_event = latest
                return now - ready_since >= 10

            try:
                android.wait(connected, 'G7 首页 SDK 连接稳定', 75)
            except WaitTimeout as exc:
                raise TestBlocked('等待 75 秒后仍未确认 G7 连接稳定，未点击拍照识图。') from exc
            wait_seconds = round(float(last_connected_event[0]) - reconnect_after
                                 if reconnect_after is not None else ready_since - started, 1)
            android.log('visual-search-connection-ready', {
                'reconnect_observed': waited_for_reconnect,
                'seconds_to_connected': wait_seconds,
                'sdk_connected_at': float(last_connected_event[0]),
                'stable_seconds': 10,
            })
            connection = f'首页等待回连 {wait_seconds:.1f} 秒' if waited_for_reconnect else '检查开始时已连接'
            connection_details.append(f'{connection}，连接稳定 10 秒')
            record_property('studio_detail', '；'.join(connection_details) + '后点击拍照识图。')

        wait_for_connection()
        clicked_at = float(adb.shell(phone, 'date', '+%s.%N'))
        p.card('Visual Search')

        def outcome():
            if opened():
                return 'opened'
            log = sdk_logs()
            rejected = re.findall(
                r'^\s*(\d+\.\d+)\s+\d+\s+\d+\s+I\s+AiAssistServiceMonitor:\s+'
                r'Reject visual search immediately: glasses are not connected\b',
                log, re.M)
            state = last_sdk_state(log)
            if any(float(stamp) >= clicked_at for stamp in rejected) or (
                    state and float(state[0]) >= clicked_at and state[2] == 'CONNECTED'):
                return 'reconnected'
            return None

        if android.wait(outcome, '拍照识图会话页或 SDK 回连', 45) == 'reconnected':
            wait_for_connection(reconnect_after=clicked_at)
            if not opened():
                p.card('Visual Search')
    else:
        p.card('Visual Search')
    android.wait(opened, '拍照识图会话页', 35)
    answers=[e for e in android.driver.find_elements('id', p.package + ':id/tv_ai') if e.is_displayed() and e.text.strip()]
    if not answers:
        android.assert_wait(lambda: sum(bool(e.is_displayed() and e.text.strip()) for e in
                                       android.driver.find_elements('id', p.package + ':id/tv_ai')),
                            1, 'AI 识图回答数量', 50, lambda actual, expected: actual >= expected)
    android.capture('visual-search-result')

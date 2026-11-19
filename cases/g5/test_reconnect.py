"""G5 后台状态下的手机蓝牙回连。"""

import re
import time
from collections import Counter

import pytest

from studio.errors import TestBlocked, WaitTimeout
from studio.home_device import HomeDevicePage
from studio.pairing import PairingPage


def battery_exempt(adb, phone, package):
    return any(line.split(',')[1:2] == [package]
               for line in adb.shell(phone, 'dumpsys', 'deviceidle', 'whitelist').splitlines())


def ensure_background_permission(android, adb, home):
    phone, package = android.context['phone'], home.package
    if battery_exempt(adb, phone, package):
        return
    tabs = [item for item in android.driver.find_elements('id', package + ':id/tabIcon')
            if item.is_displayed()]
    if len(tabs) < 3:
        raise TestBlocked('首页缺少 My 入口，无法设置后台运行权限。')
    tabs[-1].click()
    home.text('Background Activity Permission').click()
    home.text('Battery Optimization')
    android.driver.find_element('id', package + ':id/btn_battery').click()

    def allow():
        driver = android.driver
        if driver.current_package != 'com.android.settings':
            return None
        buttons = driver.find_elements('id', 'android:id/button1')
        messages = driver.find_elements('id', 'android:id/message')
        if len(buttons) == len(messages) == 1 and buttons[0].text == 'Allow' and 'VisionRay' in messages[0].text:
            return buttons[0]
        return None

    android.wait(allow, 'VisionRay 后台运行授权', 12, handle_popups=False).click()
    android.wait(lambda: battery_exempt(adb, phone, package), '确认 VisionRay 电池优化豁免', 12)
    home.connected()


def target_mac(android, home):
    home.setting('System Settings')
    locator = (f"//*[@resource-id='{home.package}:id/tv_title' and "
               "(@text='BT MAC' or @text='Bluetooth MAC')]/parent::*"
               f"//*[@resource-id='{home.package}:id/tv_hint']")
    rows = android.wait(lambda: [item for item in android.driver.find_elements('xpath', locator)
                                 if item.is_displayed()], '当前眼镜 BT MAC', 12)
    if len(rows) != 1 or not re.fullmatch(r'(?:[0-9A-F]{2}:){5}[0-9A-F]{2}', rows[0].text, re.I):
        raise TestBlocked('无法唯一读取当前眼镜的 BT MAC。')
    return rows[0].text


def connection_events(log, pid, mac, since):
    pattern = re.compile(
        r'^\s*(\d+\.\d+)\s+(\d+)\s+\d+\s+\w\s+BleGattCallback:\s+'
        r'onConnectionStateChange: status=(\d+), newState=(\d+), device=([0-9a-f:]+)\s*$',
        re.I | re.M)
    return [(float(stamp), int(state), int(status))
            for stamp, process, status, state, address in pattern.findall(log)
            if process == pid and address.casefold() == mac.casefold() and float(stamp) >= since]


def main_process_id(adb, phone, package):
    output = adb.shell(phone, 'ps', '-A', '-o', 'PID,NAME')
    matches = [fields[0] for line in output.splitlines() if len(fields := line.split()) == 2
               and fields[1] == package and fields[0].isdigit()]
    return matches[0] if len(matches) == 1 else None


def sdk_disconnection(log, pid, since):
    events = re.findall(
        r'^\s*(\d+\.\d+)\s+(\d+)\s+\d+\s+\w\s+DPVRHelper:\s+'
        r'connectionState = DISCONNECTED\b', log, re.M)
    return next((float(stamp) for stamp, process in reversed(events)
                 if process == pid and float(stamp) >= since), None)


def test_background_bluetooth_reconnect(android, adb, record_property):
    try:
        verify_background_bluetooth_reconnect(android, adb, record_property)
    except TestBlocked as exc:
        android.capture('background-reconnect-blocked')
        record_property('studio_status', 'BLOCKED')
        pytest.skip(str(exc))


def verify_background_bluetooth_reconnect(android, adb, record_property):
    phone = android.context['phone']
    home = HomeDevicePage(android)
    home.connected()
    ensure_background_permission(android, adb, home)
    mac = target_mac(android, home)
    home.connected()
    android.capture('target-connected-before-background')
    pid = adb.shell(phone, 'pidof', home.package)
    if not pid.isdigit():
        raise TestBlocked('无法唯一确认 VisionRay 主进程。')

    def background():
        output = adb.shell(phone, 'dumpsys', 'window')
        focus = next((line for line in output.splitlines() if 'mCurrentFocus=' in line), '')
        return focus if focus and home.package not in focus and 'null' not in focus else ''

    def wait_for_state(state, since, label, timeout):
        def observed():
            if not background():
                raise AssertionError('等待蓝牙状态变化时 VisionRay 离开了后台。')
            if adb.shell(phone, 'pidof', home.package) != pid:
                raise AssertionError('VisionRay 进程在后台测试期间重启。')
            log = adb.run('-s', phone, 'logcat', '-d', '-v', 'epoch', '-s',
                          'BleGattCallback:D', 'DPVRHelper:D')
            if state == 0:
                stamp = sdk_disconnection(log, pid, since)
                return (stamp, 0, None) if stamp else None
            events = connection_events(log, pid, mac, since)
            if events and events[-1][1] == state and events[-1][2] == 0:
                return events[-1]
            return None

        event = android.wait(observed, label, timeout, handle_popups=False)
        android.log('background-bluetooth-state', dict(target=home.name, state=state,
                                                        source='VisionRay SDK' if state == 0 else 'VisionRay GATT',
                                                        callback_status=event[2], callback_time=event[0]))
        return event

    adb.shell(phone, 'input', 'keyevent', 'KEYCODE_HOME')
    focus = android.wait(background, 'VisionRay 已退到后台', 10, handle_popups=False)
    android.log('visionray-background', {'focus': focus.strip()})
    bluetooth_disabled = False
    try:
        before_off = float(adb.shell(phone, 'date', '+%s'))
        bluetooth_disabled = True
        adb.shell(phone, 'cmd', 'bluetooth_manager', 'disable')
        android.wait(lambda: adb.shell(phone, 'settings', 'get', 'global', 'bluetooth_on') == '0',
                     '手机蓝牙开关已关闭', 15, handle_popups=False)
        disconnected = wait_for_state(0, before_off, 'APP 在后台收到目标眼镜断连回调', 25)
        before_on = float(adb.shell(phone, 'date', '+%s'))
        adb.shell(phone, 'cmd', 'bluetooth_manager', 'enable')
        android.wait(lambda: adb.shell(phone, 'settings', 'get', 'global', 'bluetooth_on') == '1',
                     '手机蓝牙开关已开启', 15, handle_popups=False)
        bluetooth_disabled = False
        connected = wait_for_state(2, max(before_on, disconnected[0]),
                                   'APP 在后台自动重连目标眼镜', 75)
        record_property('studio_detail',
                        f'{home.name} 在 APP 后台断连后自动恢复，蓝牙开启至回连约 {connected[0] - before_on:.1f} 秒。')
    finally:
        if bluetooth_disabled:
            adb.shell(phone, 'cmd', 'bluetooth_manager', 'enable')
        android.ensure_foreground()

    home.connected()
    android.capture('target-connected-after-background-reconnect')


def test_reconnect_after_switch_and_restart(android, adb, record_property):
    try:
        verify_reconnect_after_switch_and_restart(android, adb, record_property)
    except TestBlocked as exc:
        android.capture('switch-reconnect-blocked')
        record_property('studio_status', 'BLOCKED')
        pytest.skip(str(exc))


def other_bound_name(context, cards, preferred=None):
    target = context['glasses_name']
    configured = [item['glasses_name'] for item in context.get('glasses_inventory', [])
                  if item['glasses_name'] != target]
    choices = [name for name in (configured or list(cards)) if name != target and name in cards]
    if not choices:
        raise TestBlocked('设备列表中没有符合本轮配置的第二台已绑定眼镜。')
    return preferred if preferred in choices else choices[0]


def bind_additional_glasses(android, bound_names):
    """从设备管理添加另一台眼镜，保留现有绑定。"""
    # 双设备用例逐条清理辅助绑定后，下一条可能马上重绑同一副眼镜。
    # 与主配对流程一样遵守 APP 的解绑后重绑等待时间。
    android.log('additional-glasses-cooldown', '添加辅助眼镜前等待 60 秒，避免刚解绑即重绑')
    time.sleep(60)
    context = android.context
    package = context['config']['package']
    target = context['glasses_name']
    g5_pattern = context['config']['name_pattern']
    inventory = [item for item in context.get('glasses_inventory', [])
                 if item['product'] in {'G5', 'G7', 'G系列', 'Nova'}
                 and item['glasses_name'].casefold() != target.casefold()]
    configured = {item['glasses_name'].casefold() for item in inventory}
    existing = {name.casefold() for name in bound_names}
    pairing = PairingPage(android)
    options = pairing.options.copy()
    models = dict.fromkeys((options['model_label'], 'Flow Echo Crystal', 'Flow Echo Pilot'), g5_pattern)
    models.update({f'Flow Pro {label}': r'DPVR\s+G7[-_]\S+' for label in ('Pilot', 'Crystal')})
    models.update({f'DPVR {model}': rf'DPVR\s+{model}[-_]\S+' for model in ('G1', 'G3', 'G6')})
    nova_names = [re.escape(item['glasses_name']) for item in inventory if item['product'] == 'Nova']
    nova_pattern = '|'.join([r'(?:DPVR\s+|Flow\s+)?Nova(?:[\s_-].+)?', *nova_names])
    models.update(dict.fromkeys(('Flow Nova', 'DPVR Nova', 'Nova', 'NOVA'), nova_pattern))
    if configured:
        models = {model: pattern for model, pattern in models.items()
                  if any(re.fullmatch(pattern, name, re.I) for name in configured)}
    driver = android.driver
    def open_models():
        if not driver.current_activity.endswith('MyDevicesActivity'):
            android.wait(lambda: android.find('pair.home_title'), '已绑定设备首页', 12)
            driver.find_element('id', package + ':id/devices_menu').click()
            android.wait(lambda: driver.current_activity.endswith('MyDevicesActivity'), '设备管理页', 12)
        add = [button for button in driver.find_elements('id', package + ':id/btnAddDevice')
               if button.is_displayed() and button.is_enabled()]
        if len(add) != 1:
            raise TestBlocked('未找到设备管理里的唯一 Add Device 入口。')
        add[0].click()
        android.element('pair.models_title')

    def close_models_to_home():
        driver.press_keycode(4)
        if driver.current_activity.endswith('MyDevicesActivity'):
            driver.press_keycode(4)
        android.wait(lambda: android.find('pair.home_title'), '从型号页返回已绑定设备首页', 12)

    def candidates(pattern):
        names = [item.text.strip() for item in driver.find_elements('id', options['device_name_id'])
                 if item.is_displayed()]
        return [name for name in names if re.fullmatch(pattern, name, re.I)
                and name.casefold() not in existing
                and (not configured or name.casefold() in configured)]

    try:
        open_models()
        available = pairing._model_names()
        legacy = {f'DPVR {model}' for model in ('G1', 'G3', 'G6')}
        if any(model not in available and model.removeprefix('DPVR ') not in available
               for model in legacy.intersection(models)):
            close_models_to_home()
            pairing.enable_g_series_models(open_models=open_models, close_models=close_models_to_home)
            open_models()
            available = pairing._model_names()
        models = {model: pattern for model, pattern in models.items()
                  if model in available or model.removeprefix('DPVR ') in available}
        for model, pattern in models.items():
            pairing.select_model(model, retry=False)
            android.element('pair.prepare_title')
            android.click('pair.next')
            try:
                found = android.wait(lambda: candidates(pattern), f'{model} 搜索第二台未绑定眼镜', 30)
            except WaitTimeout:
                cancel = [button for button in driver.find_elements('id', package + ':id/btn_cancel')
                          if button.is_displayed() and button.is_enabled()]
                if len(cancel) == 1:
                    cancel[0].click()
                else:
                    driver.press_keycode(4)
                android.element('pair.models_title')
                continue
            found = candidates(pattern) or found
            counts = Counter(name.casefold() for name in found)
            unique = sorted((name for name in found if counts[name.casefold()] == 1), key=str.casefold)
            if not unique:
                raise TestBlocked('扫描到同名眼镜，无法唯一识别可配对的第二台：' + '、'.join(found))
            selected = unique[0]
            context['glasses_name'] = selected
            pairing.options.update(skip_tutorial=True, require_pairing_prompt=False)
            android.log('additional-glasses-selected', {'candidates': found, 'selected': selected})
            try:
                pairing.bind()
            except Exception:
                # APP 先报失败时，系统配对请求可能稍后才到；取消这次辅助
                # 配对请求，避免恢复主目标配置后被误判为陌生设备弹窗。
                from studio.popups import contains_device
                for _ in range(3):
                    source = driver.page_source
                    if 'Pair with ' in source and contains_device(source, selected):
                        buttons = [button for button in driver.find_elements('id', 'android:id/button2')
                                   if button.is_displayed() and button.text.strip().casefold() == 'cancel']
                        if len(buttons) == 1:
                            buttons[0].click()
                            android.log('cancel-late-auxiliary-pairing', selected)
                            break
                    time.sleep(1)
                raise
            android.log('additional-glasses-bound', selected)
            return selected
        raise TestBlocked('未搜索到第二台可配对的眼镜。')
    finally:
        context['glasses_name'] = target
        pairing.options.update(options)


def verify_reconnect_after_switch_and_restart(android, adb, record_property):
    home = HomeDevicePage(android)
    driver = android.driver
    phone = android.context['phone']

    def visible(resource, root=driver):
        return [item for item in root.find_elements('id', home.package + ':id/' + resource)
                if item.is_displayed()]

    def active_name():
        names = home._bound_names() if android.find('pair.home_title') else []
        return names[0] if len(names) == 1 else None

    def device_cards():
        buttons = visible('devices_menu')
        if len(buttons) != 1:
            raise TestBlocked('未找到已绑定首页的唯一设备管理入口。')
        buttons[0].click()
        android.wait(lambda: driver.current_activity.endswith('MyDevicesActivity'), '设备管理页', 12)
        cards = {}
        for card in visible('container'):
            names = visible('tvName', card)
            if len(names) != 1:
                continue
            name = names[0].text.strip()
            if name in cards:
                raise TestBlocked(f'设备列表存在同名卡片：{name}。')
            cards[name] = card
        return cards

    def switch_to(card, name):
        card.click()
        android.wait(lambda: active_name() == name, f'切换后首页显示 {name}', 35)

    def connected_card():
        return active_name() == home.name and any(
            re.fullmatch(r'\d{1,3}\s*%', item.text.strip()) for item in visible('tv_battery_percent'))

    android.ensure_foreground()
    for _ in range(4):
        if android.find('pair.home_title'):
            break
        tabs = visible('tabIcon')
        if tabs:
            tabs[0].click()
        else:
            driver.press_keycode(4)
    if android.find('pair.add'):
        raise TestBlocked('H-DM_007 需要先绑定至少两台眼镜。')
    initial = android.wait(active_name, '当前已选眼镜首页', 12)
    cards = device_cards()
    android.capture('switch-reconnect-bound-devices')
    if len(cards) == 1 and home.name in cards:
        bind_additional_glasses(android, cards)
        initial = android.wait(active_name, '新增设备后返回已选眼镜首页', 20)
        cards = device_cards()
    if len(cards) < 2 or home.name not in cards:
        raise TestBlocked(f'H-DM_007 需要至少两台已绑定眼镜，并包含本轮目标 {home.name}。当前：{", ".join(cards)}')
    previous = other_bound_name(android.context, cards, preferred=initial)
    if initial != previous:
        switch_to(cards[previous], previous)
        cards = device_cards()

    target = cards.get(home.name)
    if target is None:
        raise TestBlocked(f'切回目标眼镜时未在设备列表看到 {home.name}。')
    addresses = visible('tvSn', target)
    mac = re.search(r'(?:[0-9A-F]{2}:){5}[0-9A-F]{2}', addresses[0].text, re.I) if len(addresses) == 1 else None
    if not mac:
        raise TestBlocked(f'无法读取 {home.name} 的唯一蓝牙地址。')
    switch_to(target, home.name)
    android.wait(connected_card, '重启前切换后的眼镜已连接', 45)
    android.capture('switched-target-before-restart')

    old_pid = main_process_id(adb, phone, home.package)
    started = float(adb.shell(phone, 'date', '+%s'))
    android.restart()
    new_pid = android.wait(lambda: pid if (pid := main_process_id(adb, phone, home.package))
                           and pid != old_pid else None, 'VisionRay 主进程重新启动', 15)
    if old_pid is None:
        raise AssertionError('重启前未能唯一读取 VisionRay 主进程。')
    android.log('device-switch-app-restart', {'from': previous, 'target': home.name,
                                             'old_pid': old_pid, 'new_pid': new_pid})

    def reconnected():
        log = adb.run('-s', phone, 'logcat', '-d', '-v', 'epoch', '-s', 'BleGattCallback:D')
        events = connection_events(log, new_pid, mac.group(), started)
        return events[-1] if connected_card() and events and events[-1][1:] == (2, 0) else None

    event = android.wait(reconnected, f'APP 重启后自动回连 {home.name}', 75)
    android.capture('switched-target-reconnected-after-restart')
    record_property('studio_detail', f'从 {previous} 切到 {home.name}，APP 重启后约 {event[0] - started:.1f} 秒自动回连。')

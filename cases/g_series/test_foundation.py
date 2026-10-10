"""基础项 NF_002～NF_009：以真实 APK、系统设置和已绑定首页验收。"""
from __future__ import annotations

import re
import subprocess

import pytest

from studio.auth import AuthPage
from studio.devices import Adb
from studio.home_device import HomeDevicePage
from studio.pgyer import OVERSEAS_DOWNLOAD_PAGE, download, install, resolve_build


def _version(context):
    return context['app_version']


def _apk(context):
    """复用工作台下载目录，缺失时按当前指定 debug 版本重新下载。"""
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    version = _version(context)
    path = root / 'work' / 'downloads' / f'VisionRay-{version}.apk'
    return download(resolve_build(OVERSEAS_DOWNLOAD_PAGE, version, None, 'debug'), path)


def _install_current(adb, context, downgrade=False):
    args = ['adb', '-s', context['phone'], 'install', '-r']
    if downgrade:
        args.append('-d')
    args.append(str(_apk(context)))
    result = subprocess.run(args, text=True, capture_output=True, check=False)
    assert result.returncode == 0 and 'Success' in result.stdout, result.stdout + result.stderr
    info = adb.shell(context['phone'], 'dumpsys', 'package', context['config']['package'])
    assert f'versionName={_version(context)}' in info, '安装版本与工作台输入不符'


def _fresh_install(adb, context):
    result = adb.run('-s', context['phone'], 'uninstall', context['config']['package'])
    assert 'Success' in result, result
    _install_current(adb, context)


def _version_key(value):
    return tuple(int(x) for x in re.findall(r'\d+', value)[:3])


def _older_build(context):
    """蒲公英历史列表中选择比当前版低的 debug 包，避免在用例中写死版本。"""
    from studio import pgyer
    with pgyer.fetch(OVERSEAS_DOWNLOAD_PAGE) as response:
        page = response.read().decode('utf-8', errors='ignore')
    keys = list(dict.fromkeys(re.findall(r'(?:/app/build/|data-url=["\']/)\s*([0-9a-f]{32})', page)))
    current = _version_key(_version(context))
    for key in keys:
        with pgyer.fetch(f'https://www.pgyer.com/app/build/{key}') as response:
            detail = response.read().decode('utf-8', errors='ignore')
        match = re.search(r"aVersion\s*=\s*['\"]([^'\"]+)", detail)
        if match and match.group(1).endswith('-debug') and _version_key(match.group(1)) < current:
            return key, match.group(1)
    pytest.skip('蒲公英未提供低于当前输入版本的 debug 历史包，无法执行低版本覆盖安装。')


def _set_time_mode(adb, serial, value):
    adb.shell(serial, 'settings', 'put', 'system', 'time_12_24', value)
    assert adb.shell(serial, 'settings', 'get', 'system', 'time_12_24') == value


def _set_locale(android, adb, serial, locale):
    """通过系统 Language 设置页调整默认语言，避免不可用的 ``cmd locale set``。"""
    targets = {
        'zh-CN': 'Simplified Chinese (China)',
        'zh-Hans-CN': 'Simplified Chinese (China)',
        # 测试机已有 American Samoa 英语；它与 en-US 都应显示英文 APP 文案。
        'en-US': 'English (American Samoa)',
        'en-AS': 'English (American Samoa)',
    }
    target = targets.get(locale)
    if not target:
        raise ValueError('未配置系统语言名称：' + locale)
    adb.shell(serial, 'am', 'start', '-a', 'android.settings.LOCALE_SETTINGS')
    android.wait(lambda: android.driver.current_package == 'com.android.settings', '打开系统语言设置', 12)
    def locale_rows():
        # content-desc 会随当前系统语言本地化；英文条目的可见 text 保持英文。
        candidates = android.driver.find_elements(
            'xpath', f"//*[@content-desc={target!r} and @clickable='true']")
        candidates += android.driver.find_elements('xpath', f"//*[@text={target!r}]/../..")
        if locale.startswith('zh'):
            candidates += android.driver.find_elements('xpath',
                "//*[contains(@text, '简体')]/../.. | //*[@content-desc and contains(@content-desc, 'Simplified') and @clickable='true']")
        seen = set()
        return [e for e in candidates if e.is_displayed() and e.is_enabled()
                and not (e.id in seen or seen.add(e.id))]
    rows = android.wait(locale_rows, target, 12)
    if len(rows) != 1:
        pytest.skip('系统语言列表未唯一提供 ' + target)
    # Samsung One UI 的默认语言取列表第一项。点击右上角 Edit 后拖动目标项的
    # dragHandle 到首位，随后读取 persist.sys.locale 确认系统已实际切换。
    size = android.driver.get_window_size()
    android.driver.execute_script('mobile: clickGesture', {'x': int(size['width'] * .90), 'y': int(size['height'] * .10)})
    handle = android.wait(lambda: next((e for e in android.driver.find_elements(
        'id', 'com.android.settings:id/dragHandle') if e.is_displayed() and
        abs(e.rect['y'] - rows[0].rect['y']) < max(120, e.rect['height'])), None),
        '语言排序手柄', 8)
    android.driver.execute_script('mobile: dragGesture', {
        'startX': int(handle.rect['x'] + handle.rect['width'] / 2),
        'startY': int(handle.rect['y'] + handle.rect['height'] / 2),
        'endX': int(handle.rect['x'] + handle.rect['width'] / 2),
        'endY': int(size['height'] * .30), 'speed': 1800})
    # One UI 在退出编辑模式时才应用排序后的默认语言。
    android.driver.press_keycode(4)
    android.wait(lambda: locale.split('-')[0] in adb.shell(serial, 'getprop', 'persist.sys.locale'),
                 '系统语言切换为 ' + locale, 15)


def _assert_first_launch(android):
    android.ensure_foreground()
    source = android.driver.page_source
    assert 'User Agreement' in source and 'Privacy Policy' in source
    android.capture('first-launch-agreement')


def test_lower_version_cover_install(android, adb, context):
    key, old_version = _older_build(context)
    from pathlib import Path
    apk = download(key, Path(__file__).resolve().parents[2] / 'work' / 'downloads' / f'VisionRay-{old_version}.apk')
    result = subprocess.run(['adb', '-s', context['phone'], 'install', '-r', '-d', str(apk)], text=True, capture_output=True)
    assert result.returncode == 0 and 'Success' in result.stdout, result.stdout + result.stderr
    try:
        android.restart()
        HomeDevicePage(android).home()
        assert HomeDevicePage(android).text(context['glasses_name'], 8)
    finally:
        _install_current(adb, context, downgrade=True)


def test_uninstall_reinstall(android, adb, context):
    _fresh_install(adb, context)
    AuthPage(android).entry()
    assert AuthPage(android).el('tv_login_by_email').text == 'Log in with Email'


def test_first_launch_agreement(android, adb, context):
    android.popups.preserve.add('first_launch')
    adb.shell(context['phone'], 'pm', 'clear', context['config']['package'])
    _assert_first_launch(android)


def test_first_launch_exit_and_agree(android, adb, context):
    android.popups.preserve.add('first_launch')
    adb.shell(context['phone'], 'pm', 'clear', context['config']['package'])
    _assert_first_launch(android)
    android.driver.find_element('id', context['config']['package'] + ':id/tv_quit').click()
    focus = [line for line in adb.shell(context['phone'], 'dumpsys', 'window').splitlines()
             if 'mCurrentFocus' in line]
    assert not any(context['config']['package'] in line for line in focus), '退出后 APP 仍在实际前台'
    android.ensure_foreground()
    button = android.wait(lambda: next((e for e in android.driver.find_elements('xpath', "//*[@text='Agree']") if e.is_displayed()), None), 'Agree', 10)
    button.click()
    AuthPage(android).entry()


def _system_language_install(android, adb, context, locale, expected):
    original = adb.shell(context['phone'], 'getprop', 'persist.sys.locale')
    try:
        _set_locale(android, adb, context['phone'], locale)
        _fresh_install(adb, context)
        android.ensure_foreground()
        assert expected in android.driver.page_source
    finally:
        if original:
            _set_locale(android, adb, context['phone'], original)
        _install_current(adb, context, downgrade=True)


def test_system_language_chinese(android, adb, context):
    _system_language_install(android, adb, context, 'zh-CN', '登录')


def test_system_language_english(android, adb, context):
    _system_language_install(android, adb, context, 'en-US', 'Log in with Email')


def _time_format_login_and_bind(android, adb, context, mode):
    original = adb.shell(context['phone'], 'settings', 'get', 'system', 'time_12_24')
    try:
        _set_time_mode(adb, context['phone'], mode)
        AuthPage(android).registered(verify_password=True)
        HomeDevicePage(android).home()
    finally:
        if original and original != 'null':
            _set_time_mode(adb, context['phone'], original)
        else:
            adb.shell(context['phone'], 'settings', 'delete', 'system', 'time_12_24')


def test_time_format_12(android, adb, context):
    _time_format_login_and_bind(android, adb, context, '12')


def test_time_format_24(android, adb, context):
    _time_format_login_and_bind(android, adb, context, '24')

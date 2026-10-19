"""基础项 NF_001～NF_009：以真实 APK、系统设置和已绑定首页验收。"""
from __future__ import annotations

import re
import subprocess

import pytest

from studio.auth import AuthPage
from studio.devices import Adb
from studio.errors import WaitTimeout
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
    """遍历蒲公英构建详情中的历史列表，选择较低版本的 debug 包。"""
    from studio import pgyer
    with pgyer.fetch(OVERSEAS_DOWNLOAD_PAGE) as response:
        page = response.read().decode('utf-8', errors='ignore')
    keys = list(dict.fromkeys(re.findall(r'(?:/app/build/|data-url=["\']/)\s*([0-9a-f]{32})', page)))
    current = _version_key(_version(context))
    checked = set()
    while keys:
        key = keys.pop(0)
        if key in checked:
            continue
        checked.add(key)
        with pgyer.fetch(f'https://www.pgyer.com/app/build/{key}') as response:
            detail = response.read().decode('utf-8', errors='ignore')
        keys.extend(k for k in re.findall(r'(?:/app/build/|data-url=["\']/)\s*([0-9a-f]{32})', detail)
                    if k not in checked)
        match = re.search(r"aVersion\s*=\s*['\"]([^'\"]+)", detail)
        if match and match.group(1).endswith('-debug') and _version_key(match.group(1)) < current:
            return key, match.group(1)
    pytest.skip('蒲公英未提供低于当前输入版本的 debug 历史包，无法执行低版本覆盖安装。')


def _set_time_mode(adb, serial, value):
    adb.shell(serial, 'settings', 'put', 'system', 'time_12_24', value)
    assert adb.shell(serial, 'settings', 'get', 'system', 'time_12_24') == value


def _set_locale(android, adb, serial, locale):
    """通过系统 Language 设置页调整默认语言，兼容 One UI 和 HyperOS。"""
    targets = {
        'zh-CN': ('Simplified Chinese (China)', '中文 (简体)'),
        'zh-Hans-CN': ('Simplified Chinese (China)', '中文 (简体)'),
        'en-US': ('English (American Samoa)', 'English'),
        'en-AS': ('English (American Samoa)', 'English'),
    }.get(locale)
    if not targets:
        raise ValueError('未配置系统语言名称：' + locale)
    changed = lambda: locale.split('-')[0] in adb.shell(serial, 'getprop', 'persist.sys.locale')
    if changed():
        return
    def language_row():
        for target in targets:
            # HyperOS 中文项以 content-desc 暴露英文名，文字节点本身不可点击。
            locator = f"//*[@text={target!r} or @content-desc={target!r}]"
            for query in (f"{locator}[@clickable='true']", locator):
                found = [e for e in android.driver.find_elements('xpath', query)
                         if e.is_displayed() and e.is_enabled()]
                if len(found) == 1:
                    return found[0]
        return None
    def setting_entry(labels):
        for _ in range(8):
            for label in labels:
                query = f"//*[@text={label!r}]/ancestor::*[@clickable='true'][1]"
                found = [e for e in android.driver.find_elements('xpath', query)
                         if e.is_displayed() and e.is_enabled()]
                if len(found) == 1:
                    found[0].click()
                    return
            size = android.driver.get_window_size()
            android.driver.swipe(size['width'] // 2, int(size['height'] * .8),
                                 size['width'] // 2, int(size['height'] * .3), 350)
        android.capture('locale-settings-entry-missing')
        raise AssertionError('系统设置中未找到 ' + ' / '.join(labels) +
                             '；已保存当前设置页截图和 XML，请核对手机设置菜单。')
    def open_language_page():
        adb.shell(serial, 'am', 'start', '-a', 'android.settings.LOCALE_SETTINGS')
        android.wait(lambda: android.driver.current_package == 'com.android.settings', '打开系统语言设置', 12)
        if language_row():
            return
        # Samsung One UI 把 LOCALE_SETTINGS 意图落在 Settings 首页，需进入常规管理。
        setting_entry(('General management', '常规管理'))
        setting_entry(('Language', '语言'))

    open_language_page()
    row = android.wait(language_row, ' / '.join(targets), 12)
    # HyperOS applies the selected list item immediately.
    row.click()
    try:
        android.wait(changed, '系统语言切换为 ' + locale, 5)
        return
    except WaitTimeout:
        pass

    # One UI keeps the selected language in the list until Edit mode moves it
    # to the first position. Reopen the page because the first tap may redraw it.
    open_language_page()
    row = android.wait(language_row, ' / '.join(targets), 12)
    size = android.driver.get_window_size()
    android.driver.execute_script('mobile: clickGesture', {
        'x': int(size['width'] * .90), 'y': int(size['height'] * .10)})
    handle = android.wait(lambda: next((e for e in android.driver.find_elements(
        'id', 'com.android.settings:id/dragHandle') if e.is_displayed() and
        abs(e.rect['y'] - row.rect['y']) < max(120, e.rect['height'])), None),
        '语言排序手柄', 8)
    android.driver.execute_script('mobile: dragGesture', {
        'startX': int(handle.rect['x'] + handle.rect['width'] / 2),
        'startY': int(handle.rect['y'] + handle.rect['height'] / 2),
        'endX': int(handle.rect['x'] + handle.rect['width'] / 2),
        'endY': int(size['height'] * .30), 'speed': 1800})
    android.driver.press_keycode(4)
    android.wait(changed, '系统语言切换为 ' + locale, 15)


def _assert_first_launch(android):
    android.ensure_foreground()
    source = android.driver.page_source
    package = android.context['config']['package']
    assert f'{package}:id/ll_user_privacy' in source and f'{package}:id/tv_agree' in source
    android.capture('first-launch-agreement')


def test_lower_version_cover_install(android, adb, context):
    from pathlib import Path
    key, old_version = _older_build(context)
    apk = download(key, Path(__file__).resolve().parents[2] / 'work' / 'downloads' / f'VisionRay-{old_version}.apk')
    upgraded = False
    try:
        result = adb.run('-s', context['phone'], 'uninstall', context['config']['package'])
        assert 'Success' in result, '卸载现有 APP 失败：' + result
        result = adb.run('-s', context['phone'], 'install', str(apk))
        assert 'Success' in result, '安装低版本 APP 失败：' + result
        info = adb.shell(context['phone'], 'dumpsys', 'package', context['config']['package'])
        assert f'versionName={old_version}' in info, '低版本安装后版本号不符'
        android.restart()
        AuthPage(android).home()
        HomeDevicePage(android).home()
        assert HomeDevicePage(android).text(context['glasses_name'], 8)
        android.capture('lower-version-bound')
        _install_current(adb, context)
        upgraded = True
        android.restart()
        android.wait(lambda: android.find('pair.home_title'), '升级后保留已绑定首页', 20)
        assert HomeDevicePage(android).text(context['glasses_name'], 8), '升级后未保留目标眼镜'
        android.capture('upgraded-bound')
    finally:
        if not upgraded:
            _install_current(adb, context)


def test_install_and_relaunch(android, adb, context):
    """NF_001：全新安装后连续三次启动、退出，均不得崩溃。"""
    _fresh_install(adb, context)
    package = context['config']['package']
    for attempt in range(3):
        android.ensure_foreground()
        android.wait(lambda: android.driver.current_package == package,
                     f'第 {attempt + 1} 次启动 APP', 20)
        adb.shell(context['phone'], 'am', 'force-stop', package)
        focus = [line for line in adb.shell(context['phone'], 'dumpsys', 'window').splitlines()
                 if 'mCurrentFocus' in line]
        assert not any(package in line for line in focus), f'第 {attempt + 1} 次退出后 APP 仍在前台'


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
    button = android.wait(lambda: next((e for e in android.driver.find_elements(
        'id', android.context['config']['package'] + ':id/tv_agree')
        if e.is_displayed() and e.is_enabled()), None), '同意隐私协议', 10)
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

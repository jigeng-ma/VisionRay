"""Prepare the phone language before a fresh APP installation."""
import time


def ensure_system_english(adb, serial, emit):
    sdk = adb.shell(serial, 'getprop', 'ro.build.version.sdk').strip()
    if not sdk.isdigit() or int(sdk) < 36:
        return None  # Older Android versions retain the existing APP language fallback.

    def current():
        value = adb.shell(serial, 'cmd', 'locale', 'get-device-locale').strip()
        if not value or value.startswith('Error:'):
            raise RuntimeError(f'无法读取 Android 16 手机语言：{value or "无返回值"}')
        return value

    before = current()
    if before.lower().startswith('en'):
        emit('service', f'手机系统语言已是英文（{before}）。')
        return before
    emit('service', f'手机系统语言为 {before}，正在切换至 en-US…')
    adb.shell(serial, 'cmd', 'locale', 'set-device-locale', 'en-US')
    for _ in range(30):
        after = current()
        if after.lower().startswith('en'):
            emit('service', f'手机系统语言已切换为 {after}。')
            return after
        time.sleep(1)
    raise RuntimeError(f'手机语言切换未生效：原为 {before}，现在仍为 {after}；停止执行用例。')

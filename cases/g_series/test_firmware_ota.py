"""G 系列固件 OTA：每条用例自行准备后台任务和实际版本断言。"""

import pytest

from studio.errors import TestBlocked
from studio.firmware_ota import FirmwareUpdatePage, choose_target, prepare_target


def run(android, action, preserve_popup=False):
    # 只有启动弹窗专项用例保留 Firmware Update；普通 OTA 流程先关闭遗留弹窗再继续定位。
    if preserve_popup:
        android.popups.preserve.add("firmware_update")
    try:
        action()
    except TestBlocked as exc:
        android.capture("firmware-ota-blocked")
        pytest.skip(str(exc))
    finally:
        android.popups.preserve.discard("firmware_update")


def _restart_app(android):
    android.restart()


def _manual_update(android, firmware):
    before, target, direction = choose_target(android, firmware)
    prepare_target(target["task_id"], mandatory=False)
    page = FirmwareUpdatePage(android)
    page.open()
    page.start()
    page.wait_for_completion(target["version"], before, direction, firmware=firmware)


def _startup_update(android, firmware, mandatory):
    before, target, direction = choose_target(android, firmware)
    prepare_target(target["task_id"], mandatory=mandatory)
    if not mandatory:
        # 非强制提示通常只在新装 APP 登录并重新绑定眼镜后触发。
        from studio.auth import AuthPage, install_auth_variant
        from studio.home_device import HomeDevicePage
        install_auth_variant(android, android.context, 'debug')
        android.ensure_foreground()
        AuthPage(android).registered()
        HomeDevicePage(android).home()
    _restart_app(android)
    page = FirmwareUpdatePage(android)
    try:
        page.startup_popup(mandatory)
    except AssertionError:
        if mandatory:
            raise
        raise AssertionError("非强制升级弹窗未出现；请检查启动时弹窗证据。")
    page.wait_for_completion(target["version"], before, direction, firmware=firmware)


def test_bluetooth_firmware_update(android):
    run(android, lambda: _manual_update(android, "bluetooth"))


def test_wifi_firmware_update(android):
    run(android, lambda: _manual_update(android, "wifi"))


def test_bluetooth_forced_update_on_start(android):
    run(android, lambda: _startup_update(android, "bluetooth", mandatory=True), preserve_popup=True)


def test_wifi_optional_update_on_start(android):
    run(android, lambda: _startup_update(android, "wifi", mandatory=False), preserve_popup=True)

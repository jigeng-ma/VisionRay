"""G 系列固件 OTA：每条用例自行准备后台任务和实际版本断言。"""

import pytest

from studio.errors import TestBlocked
from studio.firmware_ota import FirmwareUpdatePage, choose_target, prepare_target


def run(android, action):
    # 默认弹窗守卫会取消 Firmware Update；OTA 用例必须保留它以验证弹窗和升级入口。
    android.popups.preserve.add("firmware_update")
    try:
        action()
    except TestBlocked as exc:
        android.capture("firmware-ota-blocked")
        pytest.skip(str(exc))
    finally:
        android.popups.preserve.discard("firmware_update")


def _restart_app(android, adb):
    package = android.context["config"]["package"]
    adb.shell(android.context["phone"], "am", "force-stop", package)
    adb.shell(android.context["phone"], "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1")
    android.wait(lambda: android.driver.current_package == package, "重启后打开 VisionRay", 25)


def _manual_update(android, firmware):
    before, target, direction = choose_target(android, firmware)
    prepare_target(target["task_id"], mandatory=False)
    page = FirmwareUpdatePage(android)
    page.open()
    page.start()
    page.wait_for_completion(target["version"], before, direction)


def _startup_update(android, adb, firmware, mandatory):
    before, target, direction = choose_target(android, firmware)
    prepare_target(target["task_id"], mandatory=mandatory)
    _restart_app(android, adb)
    page = FirmwareUpdatePage(android)
    try:
        page.startup_popup(mandatory)
    except AssertionError:
        if mandatory:
            raise
        raise TestBlocked("非强制升级弹窗未出现；请重装 APP 后登录并绑定眼镜，再执行本用例。")
    page.wait_for_completion(target["version"], before, direction)


def test_bluetooth_firmware_update(android):
    run(android, lambda: _manual_update(android, "bluetooth"))


def test_wifi_firmware_update(android):
    run(android, lambda: _manual_update(android, "wifi"))


def test_bluetooth_forced_update_on_start(android, adb):
    run(android, lambda: _startup_update(android, adb, "bluetooth", mandatory=True))


def test_wifi_optional_update_on_start(android, adb):
    run(android, lambda: _startup_update(android, adb, "wifi", mandatory=False))

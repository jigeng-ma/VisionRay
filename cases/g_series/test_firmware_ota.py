"""G 系列固件 OTA：每条用例自行准备后台任务和实际版本断言。"""

import pytest

from studio.errors import TestBlocked
from studio.firmware_ota import manual_update, startup_update


def run(android, action, preserve_popup=False):
    # 只有启动弹窗专项用例保留 Firmware Update；普通 OTA 流程先关闭遗留弹窗再继续定位。
    if preserve_popup:
        android.popups.preserve.add("firmware_update")
    try:
        return action()
    except TestBlocked as exc:
        android.capture("firmware-ota-blocked")
        pytest.skip(str(exc))
    finally:
        android.popups.preserve.discard("firmware_update")


def test_bluetooth_firmware_update(android):
    run(android, lambda: manual_update(android, "bluetooth"))


def test_wifi_firmware_update(android, request):
    detail = run(android, lambda: manual_update(android, "wifi"))
    if detail:
        request.node.user_properties.append(('studio_detail', detail))


def test_bluetooth_forced_update_on_start(android):
    run(android, lambda: startup_update(android, "bluetooth", mandatory=True), preserve_popup=True)


def test_wifi_optional_update_on_start(android):
    run(android, lambda: startup_update(android, "wifi", mandatory=False), preserve_popup=True)

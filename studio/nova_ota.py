"""Flow Nova 指定版本固件 OTA 前置校验。"""

import re
import time

from .devices import Adb
from .errors import TestBlocked
from .ota_targets import target_info


def firmware_version(serial: str, adb=None) -> str:
    """从眼镜本机读取升级后真实固件版本，不依赖降级后可能已解绑的 APP。"""
    if not serial:
        raise TestBlocked('Nova OTA 必须选择 USB 连接的眼镜。')
    value = (adb or Adb()).shell(serial, 'getprop', 'ro.build.dp_customer.version').strip()
    match = re.search(r'(?<!\d)(\d+\.\d+\.\d+)(?!\d)', value)
    if not match:
        raise TestBlocked(f'无法从 Nova 眼镜读取实际固件版本：{value!r}')
    return match.group(1)


def target_for_current(current: str, direction: str) -> dict:
    """Nova 只允许配置指定的相邻版本，禁止按大小关系推断任意可降级。"""
    if direction not in ('upgrade', 'downgrade'):
        raise ValueError(f'未知 OTA 方向：{direction}')
    target = target_info(f'Flow Nova.firmware.{direction}', 'glasses')
    opposite = target_info(f'Flow Nova.firmware.{"downgrade" if direction == "upgrade" else "upgrade"}', 'glasses')
    if not target['task_id'] or not target['version'] or not opposite['version']:
        raise TestBlocked('Flow Nova OTA 任务 ID 或目标实际版本未配置完整。')
    source = opposite['version'].lstrip('Vv')
    actual = current.lstrip('Vv')
    if actual != source:
        raise TestBlocked(f'Flow Nova 仅支持指定版本更新：{direction} 需从 {source} 到 '
                          f'{target["version"]}；当前实际版本 {actual}，未上线任务。')
    return dict(target, before=actual, direction=direction)


def assert_result(serial: str, target: dict, adb=None) -> str:
    actual = firmware_version(serial, adb)
    expected = target['version'].lstrip('Vv')
    if actual != expected:
        raise AssertionError(f'Flow Nova {target["direction"]} 后实际版本未达到目标：'
                             f'{target["before"]} -> {actual}，期望 {expected}。')
    return (f'Flow Nova 降级成功：{target["before"]} -> {actual}；眼镜数据会清空，'
            'APP 提示解绑属于预期。' if target['direction'] == 'downgrade'
            else f'Flow Nova 升级成功：{target["before"]} -> {actual}。')


def run_manual_update(android, timeout=1200):
    """按眼镜实际版本选择唯一目标，并以 USB 读到的实际版本判定结果。"""
    from .firmware_ota import FirmwareUpdatePage, clear_target
    from .ota import OtaClient

    serial = android.context['glasses']
    current = firmware_version(serial)
    if current == '7.33.0':
        target = target_for_current(current, 'upgrade')
    elif current == '7.33.1':
        target = target_for_current(current, 'downgrade')
    else:
        # Nova 固件不能任意降级，当前版本不在已配置的相邻版本范围内。
        target_for_current(current, 'upgrade')
        raise AssertionError('不可达的 Nova OTA 版本分支。')
    task = target['task_id']
    client = OtaClient()
    try:
        client.activate_only(task, (167, 168), apply=True)
        client.set_force(task, False, apply=True)
        page = FirmwareUpdatePage(android)
        page.dismiss_stale_startup_popup()
        page.open()
        page.start()
        deadline = time.monotonic() + timeout
        last = current
        while time.monotonic() < deadline:
            try:
                last = firmware_version(serial)
            except (RuntimeError, TestBlocked):
                # 固件更新和恢复出厂期间 USB/ADB 可能短暂离线。
                pass
            if last == target['version'].lstrip('Vv'):
                detail = assert_result(serial, target)
                android.log('nova-firmware-result', detail)
                return detail
            time.sleep(5)
        raise AssertionError(f'Flow Nova OTA 等待 {timeout} 秒后版本仍未达目标：'
                             f'{current} -> {last}，期望 {target["version"]}。')
    finally:
        clear_target(task)

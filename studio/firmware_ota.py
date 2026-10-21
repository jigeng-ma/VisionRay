"""G1/G3/G6 固件 OTA 的前置处理、页面操作和版本校验。"""

from __future__ import annotations

import re
import time

from .errors import TestBlocked
from .home_device import HomeDevicePage
from .ota import OtaClient
from .ota_targets import target_info


TEST_TASKS = (164, 165, 171, 155)
_MODEL_NAMES = {"G1": "DPVR G1", "G3": "DPVR G3", "G6": "DPVR G6"}


def _numbers(version: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", version)
    if not parts:
        raise ValueError(f"无法比较的固件版本：{version!r}")
    return tuple(int(part) for part in parts)


def _target(android, firmware: str, direction: str) -> dict:
    model = _MODEL_NAMES.get(android.context["config"].get("model"))
    if not model:
        raise TestBlocked("固件 OTA 仅支持已配置的 G1/G3/G6 型号。")
    node = target_info(f"{model}.{firmware}.{direction}", "glasses")
    if not node["task_id"] or not node["version"]:
        raise TestBlocked(f"{model} {firmware} {direction} 的 OTA task_id 或实际版本尚未配置。")
    return dict(node, firmware=firmware, direction=direction, model=model)


def firmware_version(android, firmware='bluetooth') -> str:
    """从 System Settings 的对应固件行读取实际版本。"""
    page = HomeDevicePage(android)
    page.setting("System Settings")
    row_id = 'wifi_sw_version' if firmware == 'wifi' else 'firmware_version'
    locator = (f"//*[@resource-id='{page.package}:id/{row_id}']"
               f"//*[@resource-id='{page.package}:id/tv_hint']")
    # 该页可能保留滚动位置，先向上找蓝牙版本，再向下找 Wi-Fi 版本。
    for _ in range(8):
        values = [e for e in android.driver.find_elements('xpath', locator) if e.is_displayed()]
        if len(values) == 1 and values[0].text.strip():
            version = values[0].text.strip()
            android.log('firmware-version', {'firmware': firmware, 'version': version})
            return version
        size = android.driver.get_window_size()
        up = firmware != 'wifi'
        android.driver.swipe(size['width'] // 2, int(size['height'] * (.30 if up else .78)),
                             size['width'] // 2, int(size['height'] * (.82 if up else .30)), 400)
    raise TestBlocked(f'系统设置页未找到 {row_id} 的实际版本。')


def choose_target(android, firmware: str) -> tuple[str, dict, str]:
    """按当前实际版本决定本轮做升级或降级，避免重复推同一版本。"""
    current = firmware_version(android, firmware)
    upgrade = _target(android, firmware, "upgrade")
    downgrade = _target(android, firmware, "downgrade")
    try:
        direction = "upgrade" if _numbers(current) < _numbers(upgrade["version"]) else "downgrade"
    except ValueError as exc:
        raise TestBlocked(str(exc)) from exc
    target = upgrade if direction == "upgrade" else downgrade
    android.log("firmware-target", {"current": current, "target": target["version"], "task_id": target["task_id"],
                                    "direction": direction, "firmware": firmware})
    return current, target, direction


def prepare_target(task_id: int, mandatory: bool) -> None:
    """只上线本轮固件，并同步本轮是否强制升级。"""
    client = OtaClient()
    client.activate_only(task_id, TEST_TASKS, apply=True)
    client.set_force(task_id, mandatory, apply=True)


def leave_failed_update(android) -> bool:
    """离开上条 OTA 失败页，供后续独立用例恢复前置页面。"""
    package = android.context['config']['package']
    def visible(resource, value):
        return next((e for e in android.driver.find_elements('id', package + ':id/' + resource)
                     if e.is_displayed() and e.text.strip() == value), None)
    failed = visible('uof_btn_text', 'Update Failed')
    quit_prompt = visible('tv_title', 'Quit the update')
    if not failed and not quit_prompt:
        return False
    if failed and not quit_prompt:
        back = [e for e in android.driver.find_elements('id', package + ':id/top_bar_back') if e.is_displayed()]
        if len(back) != 1:
            raise AssertionError('固件更新失败页缺少返回入口，无法准备后续用例。')
        back[0].click()
        android.wait(lambda: visible('tv_title', 'Quit the update') or
                     not visible('uof_btn_text', 'Update Failed'), '退出失败的固件更新', 8)
        quit_prompt = visible('tv_title', 'Quit the update')
    if not quit_prompt:
        android.log('firmware-recovery', 'left failed update')
        return True
    quit_button = visible('tv_cancel', 'Quit')
    if not quit_button:
        raise AssertionError('固件更新退出弹窗缺少 Quit 按钮。')
    quit_button.click()
    android.log('firmware-recovery', 'left failed update')
    return True


class FirmwareUpdatePage:
    def __init__(self, android):
        self.a = android
        self.package = android.context["config"]["package"]

    def _visible_text(self, values, timeout=12):
        values = tuple(values)
        return self.a.wait(lambda: next((e for e in self.a.driver.find_elements(
            "xpath", f"//*[@package='{self.package}' and @text]")
            if e.is_displayed() and e.text.strip() in values), None), " / ".join(values), timeout)

    def _any_text(self, phrases):
        texts = [e.text.strip() for e in self.a.driver.find_elements(
            "xpath", f"//*[@package='{self.package}' and @text]") if e.is_displayed()]
        return any(any(phrase.lower() in text.lower() for phrase in phrases) for text in texts)

    def open(self):
        from .errors import WaitTimeout
        for attempt in range(2):
            HomeDevicePage(self.a).setting("System Settings")
            # 入口位于设置页底部，先滚动到中部再点击整行。
            size = self.a.driver.get_window_size()
            self.a.driver.swipe(size['width'] // 2, int(size['height'] * .8),
                                size['width'] // 2, int(size['height'] * .4), 350)
            rows = self.a.wait(lambda: [e for e in self.a.driver.find_elements(
                'id', self.package + ':id/version') if e.is_displayed() and e.is_enabled()],
                'Firmware Update 设置入口', 15)
            if len(rows) != 1:
                raise TestBlocked(f'Firmware Update 设置入口不唯一：{len(rows)} 项。')
            rows[0].click()
            try:
                self.a.wait(lambda: any(e.is_displayed() for resource in ('uof_btn', 'uof_version')
                                        for e in self.a.driver.find_elements('id', self.package + ':id/' + resource)),
                            '真正进入 Firmware Update 页面', 15)
                self.a.capture("firmware-update-page")
                return
            except WaitTimeout:
                if attempt:
                    raise
                self.a.log('firmware-retry', '固件更新页未打开，确认眼镜连接后重试入口')
                HomeDevicePage(self.a).connected()

    def start(self):
        self._visible_text(("Update Now", "Update"), 15).click()
        self.a.log("firmware-update", "started")

    def startup_popup(self, mandatory: bool):
        """验证启动弹窗；非强制弹窗的安装、登录、绑定前置由调用方保证。"""
        self._visible_text(("Firmware Update", "Firmware update"), 20)
        if mandatory:
            cancel = [e for e in self.a.driver.find_elements("xpath", f"//*[@package='{self.package}' and @text='Cancel']")
                      if e.is_displayed()]
            if cancel:
                raise AssertionError("强制固件升级弹窗不应提供 Cancel。")
        self.start()

    def wait_for_completion(self, expected: str, before: str, direction: str, timeout=1200,
                            firmware='bluetooth'):
        """检查下载/传输/更新过程，并以更新后的实际版本作为最终结论。"""
        stages = (("download", ("download",)), ("transfer", ("transfer",)), ("update", ("updating", "installing")))
        deadline = time.monotonic() + timeout
        observed = set()
        outcome = 'timeout'
        while time.monotonic() < deadline:
            if self._any_text(('Update Failed', 'Upgrade Failed', 'Download Failed', 'Transfer Failed')):
                self.a.capture('firmware-update-failed')
                outcome = 'failed'
                break
            for name, words in stages:
                if name not in observed and self._any_text(words):
                    observed.add(name)
                    self.a.capture("firmware-" + name)
                    self.a.log("firmware-stage", name)
            if self._any_text(("update successful", "update complete", "updated successfully", "upgrade successful")):
                self.a.capture("firmware-success")
                outcome = 'success'
                break
            time.sleep(2)
        if outcome == 'timeout':
            self.a.capture('firmware-update-timeout')
        try:
            actual = firmware_version(self.a, firmware)
        except Exception as exc:
            raise AssertionError(f'固件更新{outcome}，且无法读取更新后的 {firmware} 实际版本：{exc}') from exc
        self.a.log('firmware-result', {'outcome': outcome, 'observed': sorted(observed),
                                       'before': before, 'expected': expected, 'actual': actual})
        if _numbers(actual) != _numbers(expected):
            raise AssertionError(f"固件更新{outcome}；版本未达到目标：期望 {expected}，实际 {actual}。")
        if direction == "upgrade" and _numbers(actual) <= _numbers(before):
            raise AssertionError(f"升级后版本未高于更新前：{before} -> {actual}。")
        if direction == "downgrade" and _numbers(actual) >= _numbers(before):
            raise AssertionError(f"降级后版本未低于更新前：{before} -> {actual}。")

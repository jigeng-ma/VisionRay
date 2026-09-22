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


def firmware_version(android) -> str:
    """从 System Settings 读取当前连接眼镜的实际固件版本。"""
    page = HomeDevicePage(android)
    page.setting("System Settings")
    labels = [e for e in android.driver.find_elements(
        "xpath", f"//*[@resource-id='{page.package}:id/tv_title' and @text='Firmware Version']")
        if e.is_displayed()]
    if len(labels) != 1:
        raise TestBlocked("系统设置页未唯一找到 Firmware Version。")
    values = [e.text.strip() for e in labels[0].find_element("xpath", "..").find_elements("xpath", ".//*[@text]")
              if e.text.strip()]
    version = next((value for value in values if value != "Firmware Version"), "")
    if not version:
        raise TestBlocked("无法读取当前眼镜固件版本。")
    android.log("firmware-version", version)
    return version


def choose_target(android, firmware: str) -> tuple[str, dict, str]:
    """按当前实际版本决定本轮做升级或降级，避免重复推同一版本。"""
    current = firmware_version(android)
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
        HomeDevicePage(self.a).setting("System Settings")
        item = self._visible_text(("Firmware Update", "Firmware update"), 15)
        item.click()
        self._visible_text(("Firmware Update", "Firmware update"), 15)
        self.a.capture("firmware-update-page")

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

    def wait_for_completion(self, expected: str, before: str, direction: str, timeout=1200):
        """检查下载/传输/更新过程，并以更新后的实际版本作为最终结论。"""
        stages = (("download", ("download",)), ("transfer", ("transfer",)), ("update", ("updating", "installing")))
        deadline = time.monotonic() + timeout
        observed = set()
        while time.monotonic() < deadline:
            for name, words in stages:
                if name not in observed and self._any_text(words):
                    observed.add(name)
                    self.a.capture("firmware-" + name)
                    self.a.log("firmware-stage", name)
            if self._any_text(("update successful", "update complete", "updated successfully", "upgrade successful")):
                self.a.capture("firmware-success")
                break
            time.sleep(2)
        else:
            raise AssertionError("固件更新未在限定时间内显示成功结果。")
        missing = {"download", "transfer", "update"} - observed
        if missing:
            raise AssertionError("固件更新未观察到阶段：" + "、".join(sorted(missing)))
        actual = firmware_version(self.a)
        if _numbers(actual) != _numbers(expected):
            raise AssertionError(f"固件更新后版本错误：期望 {expected}，实际 {actual}。")
        if direction == "upgrade" and _numbers(actual) <= _numbers(before):
            raise AssertionError(f"升级后版本未高于更新前：{before} -> {actual}。")
        if direction == "downgrade" and _numbers(actual) >= _numbers(before):
            raise AssertionError(f"降级后版本未低于更新前：{before} -> {actual}。")

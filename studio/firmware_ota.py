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
    # 系统设置页会保留上一条用例的滚动位置，先回到包含基础版本信息的顶部。
    for _ in range(5):
        labels = [e for e in android.driver.find_elements('id', page.package + ':id/tv_title') if e.is_displayed()]
        if any(label.text == 'Firmware Version' for label in labels):
            break
        size = android.driver.get_window_size()
        android.driver.swipe(size['width'] // 2, int(size['height'] * .30),
                             size['width'] // 2, int(size['height'] * .82), 400)
    labels = [e for e in android.driver.find_elements('id', page.package + ':id/tv_title') if e.is_displayed()]
    indexes = [index for index, label in enumerate(labels) if label.text == 'Firmware Version']
    if len(indexes) != 1:
        raise TestBlocked("系统设置页未唯一找到 Firmware Version。")
    values = [e for e in android.driver.find_elements('id', page.package + ':id/tv_hint') if e.is_displayed()]
    index = indexes[0]
    version = values[index].text.strip() if len(values) > index else ''
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
        HomeDevicePage(self.a).setting("System Settings")
        # 此入口在设置页底部，文字虽可见但触点会贴近导航栏；先滚动到中部，
        # 再点击可点击的整行，避免把原设置页误当成已打开的固件页。
        size = self.a.driver.get_window_size()
        self.a.driver.swipe(size['width'] // 2, int(size['height'] * .8),
                            size['width'] // 2, int(size['height'] * .4), 350)
        rows = self.a.wait(lambda: [e for e in self.a.driver.find_elements(
            'id', self.package + ':id/version') if e.is_displayed() and e.is_enabled()],
            'Firmware Update 设置入口', 15)
        if len(rows) != 1:
            raise TestBlocked(f'Firmware Update 设置入口不唯一：{len(rows)} 项。')
        rows[0].click()
        self.a.wait(lambda: any(e.is_displayed() for resource in ('uof_btn', 'uof_version')
                                for e in self.a.driver.find_elements('id', self.package + ':id/' + resource)),
                    '真正进入 Firmware Update 页面', 15)
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
            if self._any_text(('Update Failed', 'Upgrade Failed', 'Download Failed', 'Transfer Failed')):
                self.a.capture('firmware-update-failed')
                raise AssertionError('固件更新页显示 Update Failed，请查看该用例截图和手机日志。')
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

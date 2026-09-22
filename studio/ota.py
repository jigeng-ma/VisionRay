"""Manage DPVR OTA task state through the test management portal's Livewire UI."""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
from http.cookiejar import CookieJar
from urllib.request import HTTPCookieProcessor, Request, build_opener


DEFAULT_BASE_URL = "https://test.dpvr.com"
PRIVATE_CONFIG = Path(__file__).resolve().parents[1] / "configs" / "ota_private.json"


class _Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.snapshots = []
        self.csrf = ""

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get("wire:snapshot"):
            self.snapshots.append(values["wire:snapshot"])
        if values.get("data-csrf"):
            self.csrf = values["data-csrf"]
        if tag == "meta" and values.get("name") == "csrf-token":
            self.csrf = values.get("content", "")
        if tag == "input" and values.get("name") == "_token":
            self.csrf = values.get("value", "")


class OtaClient:
    """A session-scoped client. Credentials are read from environment variables only."""

    def __init__(self, email=None, password=None, config_path=PRIVATE_CONFIG):
        config = json.loads(Path(config_path).read_text(encoding="utf-8")) if Path(config_path).is_file() else {}
        self.base_url = config.get("base_url", DEFAULT_BASE_URL).rstrip("/")
        self.ota_path = config.get("ota_path", "/otas")
        self.email = email or os.environ.get("VISIONRAY_OTA_EMAIL") or config.get("email", "")
        self.password = password or os.environ.get("VISIONRAY_OTA_PASSWORD") or config.get("password", "")
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))
        self.csrf = ""

    def _get(self, path):
        request = Request(self.base_url + path, headers={"Accept": "text/html", "User-Agent": "VisionRay-OtaAutomation/1.0"})
        with self.opener.open(request, timeout=30) as response:
            return response.read().decode("utf-8", errors="replace")

    def _component(self, html, name):
        page = _Page()
        page.feed(html)
        token = page.csrf
        if not token:
            for pattern in (r'csrfToken\s*[:=]\s*["\']([^"\']+)',
                            r'csrf-token["\']?\s+content=["\']([^"\']+)',
                            r'content=["\']([^"\']+)["\']\s+name=["\']csrf-token'):
                match = re.search(pattern, html, re.I)
                if match:
                    token = match.group(1)
                    break
        self.csrf = token or self.csrf
        for snapshot in page.snapshots:
            try:
                if json.loads(snapshot).get("memo", {}).get("name") == name:
                    return snapshot
            except json.JSONDecodeError:
                continue
        raise RuntimeError(f"页面未找到 Livewire 组件：{name}")

    def _post(self, snapshot, calls, referer, updates=None):
        if not self.csrf:
            raise RuntimeError("未取得 CSRF 令牌。")
        payload = {"_token": self.csrf, "components": [{"snapshot": snapshot, "updates": updates or {}, "calls": calls}]}
        request = Request(
            self.base_url + "/livewire/update",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Accept": "application/json", "Origin": self.base_url,
                     "Referer": self.base_url + referer, "X-Livewire": "true", "User-Agent": "VisionRay-OtaAutomation/1.0"},
            method="POST",
        )
        with self.opener.open(request, timeout=30) as response:
            answer = json.loads(response.read().decode("utf-8", errors="replace"))
        if answer.get("components") and any(item.get("effects", {}).get("errors") for item in answer["components"]):
            raise RuntimeError("管理台拒绝了操作：" + json.dumps(answer, ensure_ascii=False))
        return answer

    @staticmethod
    def _response_snapshot(answer, component_name):
        for item in answer.get("components", []):
            snapshot = item.get("snapshot", "")
            try:
                if json.loads(snapshot).get("memo", {}).get("name") == component_name:
                    return snapshot
            except json.JSONDecodeError:
                pass
        raise RuntimeError(f"管理台响应未返回组件：{component_name}")

    def login(self):
        if not self.email or not self.password:
            raise RuntimeError("请设置 VISIONRAY_OTA_EMAIL 和 VISIONRAY_OTA_PASSWORD。")
        snapshot = self._component(self._get("/login"), "auth.login")
        self._post(snapshot, [{"path": "", "method": "login", "params": []}], "/login",
                   {"email": self.email, "password": self.password, "remember": True})
        # 登录成功通常是 redirect effect；用受限页面确认会话。
        self._component(self._get(self.ota_path), "versions.ota-version-list")

    def set_state(self, task_id: int, action: str, apply=False):
        """Preview or perform an OTA task online/offline transition by task ID."""
        if action not in ("online", "offline"):
            raise ValueError("action 必须是 online 或 offline。")
        if not isinstance(task_id, int) or task_id <= 0:
            raise ValueError("task_id 必须是正整数。")
        if not apply:
            return {"task_id": task_id, "action": action, "status": "DRY_RUN"}
        self.login()
        page = self._get(self.ota_path)
        modal = self._component(page, "common.confirm-modal")
        answer = self._post(modal, [{"path": "", "method": "__dispatch", "params": ["showConfirm", {
            "title": "", "subtitle": "", "action": action, "primaryKey": str(task_id)}]}], self.ota_path)
        confirmation = self._response_snapshot(answer, "common.confirm-modal")
        self._post(confirmation, [{"path": "", "method": "confirmSubmit", "params": []}], self.ota_path)
        return {"task_id": task_id, "action": action, "status": "APPLIED"}


def main():
    parser = argparse.ArgumentParser(description="按 OTA 任务 ID 上线或下线固件")
    parser.add_argument("action", choices=("online", "offline"))
    parser.add_argument("task_id", type=int)
    parser.add_argument("--apply", action="store_true", help="实际提交状态变更；省略时只预览")
    args = parser.parse_args()
    print(json.dumps(OtaClient().set_state(args.task_id, args.action, args.apply), ensure_ascii=False))


if __name__ == "__main__":
    main()

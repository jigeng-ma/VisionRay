"""Manage APP OTA task state through the management portal's Apps page."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .ota import OtaClient
from .ota_targets import TARGET_CONFIG, target_info, task_from_target


PRIVATE_CONFIG = Path(__file__).resolve().parents[1] / "configs" / "app_ota_private.json"


def main():
    parser = argparse.ArgumentParser(description="按 APP OTA 任务 ID 上线或下线版本")
    parser.add_argument("action", choices=("online", "offline"))
    parser.add_argument("task_id", type=int, nargs="?", help="APP OTA 任务 ID")
    parser.add_argument("--target", choices=("app.upgrade", "app.downgrade"), help="使用通用 APP OTA 配置")
    parser.add_argument("--targets-config", type=Path, default=TARGET_CONFIG, help="OTA 版本目标配置路径")
    parser.add_argument("--apply", action="store_true", help="实际提交状态变更；省略时只预览")
    parser.add_argument("--config", type=Path, default=PRIVATE_CONFIG, help="私密 APP OTA 配置文件路径")
    args = parser.parse_args()
    if bool(args.task_id) == bool(args.target):
        parser.error("请且只能提供 task_id 或 --target。")
    info = target_info(args.target, "", args.targets_config) if args.target else {}
    task_id = args.task_id or task_from_target(args.target, "", args.targets_config)
    result = OtaClient(config_path=args.config).set_state(task_id, args.action, args.apply)
    if args.target:
        result.update(target=args.target, expected_version=info.get("version", ""))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Manage APP OTA task state through the management portal's Apps page."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .ota import OtaClient


PRIVATE_CONFIG = Path(__file__).resolve().parents[1] / "configs" / "app_ota_private.json"


def main():
    parser = argparse.ArgumentParser(description="按 APP OTA 任务 ID 上线或下线版本")
    parser.add_argument("action", choices=("online", "offline"))
    parser.add_argument("task_id", type=int)
    parser.add_argument("--apply", action="store_true", help="实际提交状态变更；省略时只预览")
    parser.add_argument("--config", type=Path, default=PRIVATE_CONFIG, help="私密 APP OTA 配置文件路径")
    args = parser.parse_args()
    print(json.dumps(OtaClient(config_path=args.config).set_state(args.task_id, args.action, args.apply), ensure_ascii=False))


if __name__ == "__main__":
    main()

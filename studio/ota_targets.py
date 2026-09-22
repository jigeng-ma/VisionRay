"""Resolve user-editable OTA target names to management task IDs."""

from __future__ import annotations

import json
from pathlib import Path


TARGET_CONFIG = Path(__file__).resolve().parents[1] / "configs" / "ota_versions.json"


def task_from_target(target: str, group: str, config_path: Path = TARGET_CONFIG) -> int:
    data = json.loads(config_path.read_text(encoding="utf-8"))
    node = data[group] if group else data
    for part in target.split("."):
        node = node[part]
    task_id = node.get("task_id") if isinstance(node, dict) else None
    if not isinstance(task_id, int) or task_id <= 0:
        raise ValueError(f"配置目标 {target} 尚未填写有效 task_id。")
    return task_id

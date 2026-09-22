"""Resolve user-editable OTA target names to management task IDs."""

from __future__ import annotations

from pathlib import Path
import tomllib


TARGET_CONFIG = Path(__file__).resolve().parents[1] / "configs" / "ota_versions.toml"


def target_info(target: str, group: str, config_path: Path = TARGET_CONFIG) -> dict:
    with config_path.open("rb") as file:
        data = tomllib.load(file)
    node = data[group] if group else data
    for part in target.split("."):
        node = node[part]
    if not isinstance(node, dict):
        raise ValueError(f"配置目标 {target} 格式无效。")
    return node


def task_from_target(target: str, group: str, config_path: Path = TARGET_CONFIG) -> int:
    node = target_info(target, group, config_path)
    task_id = node.get("task_id") if isinstance(node, dict) else None
    if not isinstance(task_id, int) or task_id <= 0:
        raise ValueError(f"配置目标 {target} 尚未填写有效 task_id。")
    return task_id

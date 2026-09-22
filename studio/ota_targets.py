"""Resolve user-editable OTA target names to management task IDs."""

from __future__ import annotations

import configparser
from pathlib import Path


TARGET_CONFIG = Path(__file__).resolve().parents[1] / "configs" / "ota_versions.ini"


def target_info(target: str, group: str, config_path: Path = TARGET_CONFIG) -> dict:
    parser = configparser.ConfigParser()
    parser.read(config_path, encoding="utf-8")
    section = '.'.join(part for part in (group, target) if part)
    if section not in parser:
        raise ValueError(f"配置未找到目标区段 [{section}]。")
    node = parser[section]
    return {"task_id": node.getint("task_id", fallback=0), "version": node.get("version", fallback="")}


def task_from_target(target: str, group: str, config_path: Path = TARGET_CONFIG) -> int:
    node = target_info(target, group, config_path)
    task_id = node.get("task_id") if isinstance(node, dict) else None
    if not isinstance(task_id, int) or task_id <= 0:
        raise ValueError(f"配置目标 {target} 尚未填写有效 task_id。")
    return task_id

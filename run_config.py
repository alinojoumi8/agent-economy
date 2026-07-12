"""Shared run configuration loading.

Configuration inheritance is part of the reproducibility contract: every
consumer must see the same recursively merged config, not a raw YAML fragment.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml


def deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: str | Path, _seen: Optional[set[Path]] = None) -> dict:
    """Load a YAML run config and recursively resolve its ``extends`` chain."""
    cfg_path = Path(path).resolve()
    seen = set() if _seen is None else _seen
    if cfg_path in seen:
        raise ValueError(f"config inheritance cycle at {cfg_path}")
    seen.add(cfg_path)
    with cfg_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    parent = config.pop("extends", None)
    if parent:
        parent_path = (cfg_path.parent / str(parent)).resolve()
        config = deep_merge(load_config(parent_path, seen), config)
    return config

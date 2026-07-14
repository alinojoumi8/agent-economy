"""Validated scenario packs; scenario free text never mutates engine state."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from research.datasets import verify_manifest
from run_config import deep_merge, load_config


class ScenarioError(ValueError):
    pass


@dataclass(frozen=True)
class ScenarioPack:
    key: str
    version: str
    title: str
    ticks: int
    base_config: str
    dataset_manifest: str
    common_shocks: tuple[dict[str, Any], ...]
    arms: dict[str, dict[str, Any]]
    metrics: tuple[str, ...]
    limitations: str
    path: str
    checksum_sha256: str

    def config(self) -> dict[str, Any]:
        raw = yaml.safe_load(Path(self.path).read_text(encoding="utf-8")) or {}
        return deep_merge(load_config(self.base_config), raw.get("overrides", {}))


def load_scenario(path: str | Path, *, verify_data: bool = True) -> ScenarioPack:
    source = Path(path).resolve()
    raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    required = ["key", "version", "title", "ticks", "base_config", "dataset_manifest",
                "arms", "metrics", "limitations"]
    missing = [key for key in required if key not in raw]
    if missing:
        raise ScenarioError(f"scenario missing fields: {', '.join(missing)}")
    if len(raw["arms"]) < 2:
        raise ScenarioError("counterfactual scenario requires at least two arms")
    base_config = str((source.parent / raw["base_config"]).resolve())
    dataset_manifest = str((source.parent / raw["dataset_manifest"]).resolve())
    if verify_data:
        verify_manifest(dataset_manifest)
    return ScenarioPack(
        key=str(raw["key"]), version=str(raw["version"]), title=str(raw["title"]),
        ticks=max(1, int(raw["ticks"])), base_config=base_config,
        dataset_manifest=dataset_manifest,
        common_shocks=tuple(raw.get("common_shocks", [])), arms=dict(raw["arms"]),
        metrics=tuple(str(item) for item in raw["metrics"]),
        limitations=str(raw["limitations"]), path=str(source),
        checksum_sha256=hashlib.sha256(source.read_bytes()).hexdigest())

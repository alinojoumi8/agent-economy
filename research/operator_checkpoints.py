"""Bounded, read-only saved-world choices for the local pilot interface."""
from __future__ import annotations

from itertools import islice
from pathlib import Path
import sqlite3

from research.artifacts import digest_json
from research.checkpoint_origins import continuation_config, inspect_checkpoint
from research.study_results import StudyIdentityChanged

MIB = 1024 * 1024


class OperatorCheckpoints:
    MAX_SOURCE_BYTES = 16 * MIB
    MAX_CATALOG_BYTES = 128 * MIB
    MAX_SCAN = 500
    MAX_ITEMS = 20

    def __init__(self, root: Path):
        self.root = root.absolute()

    def _paths(self) -> tuple[list[Path], bool]:
        if self.root != self.root.resolve():
            raise ValueError("checkpoint directory must not be an alias")
        if not self.root.exists():
            return [], False
        # Only immediate children of the operator-configured directory. No
        # recursion, user-supplied paths or writes to the checkpoint directory.
        entries = list(islice(self.root.iterdir(), self.MAX_SCAN + 1))
        return sorted(path for path in entries[:self.MAX_SCAN] if path.suffix == ".db"), len(entries) > self.MAX_SCAN

    @staticmethod
    def identity(path: Path) -> str:
        return digest_json(path.name)[:32]

    def _inspect(self, path: Path, config: dict) -> dict:
        receipt = inspect_checkpoint(path, max_bytes=self.MAX_SOURCE_BYTES)
        expected = continuation_config({**config, "seed": receipt["seed"]})
        if (receipt["continuation_config_sha256"] != digest_json(expected)
                or not 0 <= receipt["seed"] <= 2**31 - 1 or receipt["tick"] >= 30):
            raise ValueError("checkpoint is outside the fixed pilot profile or horizon")
        return receipt

    def catalog(self, config: dict) -> dict:
        paths, truncated = self._paths()
        items, omitted, examined_bytes = [], {"oversized": 0, "unavailable_or_incompatible": 0}, 0
        for path in paths:
            try:
                size = path.lstat().st_size
                if size > self.MAX_SOURCE_BYTES:
                    omitted["oversized"] += 1
                    continue
                if len(items) >= self.MAX_ITEMS or examined_bytes + size > self.MAX_CATALOG_BYTES:
                    truncated = True
                    break
                examined_bytes += size
                receipt = self._inspect(path, config)
                items.append({"id": self.identity(path), "seed": receipt["seed"],
                    "run_id": receipt["run_id"], "tick": receipt["tick"],
                    "bytes": receipt["byte_size"], "database_sha256": receipt["database_sha256"],
                    "receipt_sha256": digest_json(receipt), "status": "admitted_saved_state"})
            except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
                omitted["unavailable_or_incompatible"] += 1
        return {"contract": "operator-checkpoint-catalog-v1", "items": items,
            "truncated": truncated, "omitted": omitted,
            "limits": {"source_bytes": self.MAX_SOURCE_BYTES, "items": self.MAX_ITEMS,
                       "scan_entries": self.MAX_SCAN, "examined_source_bytes": self.MAX_CATALOG_BYTES},
            "scope": "Closed snapshots from the configured checkpoint directory, matching the scripted 14-agent pilot. Admission checks saved state; it does not verify earlier history."}

    def resolve(self, selections: list, config: dict) -> list[Path]:
        paths, _ = self._paths()
        indexed = {self.identity(path): path for path in paths}
        selected = []
        for item in selections:
            path = indexed.get(item.id)
            if path is None:
                raise StudyIdentityChanged("Selected checkpoint is no longer listed. Refresh saved worlds and validate again.")
            try:
                receipt = self._inspect(path, config)
                if (receipt["database_sha256"] != item.database_sha256
                        or digest_json(receipt) != item.receipt_sha256):
                    raise ValueError("changed checkpoint")
            except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
                raise StudyIdentityChanged("Selected checkpoint changed or is no longer compatible. Refresh saved worlds and validate again.") from exc
            selected.append(path)
        return selected


def study_origin_view(manifest: dict) -> dict:
    """Public identity projection: no paths, configuration or input bodies."""
    spec = manifest["study"]
    origin = spec.get("origin")
    tick = origin["tick"] if origin else 0
    sources = []
    if origin:
        receipts = manifest.get("checkpoint_origins", {})
        for declared in origin["sources"]:
            receipt = receipts.get(str(declared["seed"]), {})
            sources.append({"seed": declared["seed"], "run_id": receipt.get("run_id"),
                "database_sha256": receipt.get("database_sha256"),
                "initial_state_sha256": receipt.get("initial_state_sha256"),
                "receipt_sha256": declared["receipt_sha256"]})
    return {"kind": "verified_checkpoints" if origin else "fresh_genesis", "tick": tick,
        "continuation_window": [tick + 1, spec["time"]["horizon"]],
        "independent_worlds": len(spec["randomness"]["seeds"]), "sources": sources}

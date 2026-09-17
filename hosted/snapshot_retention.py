"""Rotate only verified filesystem snapshots after catalog publication."""
from __future__ import annotations

import re

from engine.storage_policy import _is_link
from .artifacts import FilesystemArtifactStore, validate_snapshot_artifact_key

_MANAGED_NAME = re.compile(r"t[0-9]{12}-s[0-9]{8}-(tick|pause|stop)\.sqlite3")


def prune_local_snapshots(store: FilesystemArtifactStore, current_key: str, *, keep_last: int) -> dict:
    if type(keep_last) is not int or keep_last < 2:
        raise ValueError("snapshot retention must preserve at least two copies")
    current = store._artifact_dir(validate_snapshot_artifact_key(current_key))
    # head() verifies bytes, SHA, complete marker and metadata. Prove the new
    # recovery point first, then exclude pins and uncertain entries entirely.
    store.head(current_key)
    valid = []
    for candidate in current.parent.iterdir():
        if (not _MANAGED_NAME.fullmatch(candidate.name) or _is_link(candidate)
                or not candidate.is_dir() or (candidate / "pin.json").exists()):
            continue
        key = candidate.relative_to(store.root).as_posix()
        try:
            metadata = store.head(key)
        except (OSError, ValueError, RuntimeError):
            continue
        valid.append(metadata)
    # The committed catalog pointer wins even if a later orphan has a greater
    # tick/sequence. Full snapshots are immutable; no source files are touched.
    valid.sort(key=lambda item: (item.key == current_key, item.key), reverse=True)
    removed = []
    for metadata in valid[keep_last:]:
        path = store._artifact_dir(metadata.key)
        if metadata.key == current_key or (path / "pin.json").exists():
            continue
        store.head(metadata.key)
        store.delete(metadata.key)
        removed.append(metadata.key)
    return {"retained": [item.key for item in valid[:keep_last]], "removed": removed}

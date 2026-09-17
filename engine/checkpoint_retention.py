"""Verified recovery-point rotation; pinned and uncertain artifacts survive."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path

from .checkpoint_manifest import (
    build_checkpoint_manifest, canonical_json_bytes, checkpoint_manifest_path,
    file_sha256, finalize_sqlite_artifact, _fsync_directory,
)
from .storage_policy import StoragePolicy, _is_link


class CheckpointRetentionError(RuntimeError):
    pass


def pin_path(database: str | Path) -> Path:
    return Path(f"{database}.pin.json")


def _sidecars(database: Path) -> bool:
    return any(Path(f"{database}{suffix}").exists()
               for suffix in ("-wal", "-shm", "-journal"))


def verify_checkpoint(database: str | Path) -> dict:
    path = Path(database)
    manifest = checkpoint_manifest_path(path)
    if (_is_link(path) or _is_link(manifest) or _sidecars(path)
            or path.resolve() != path):
        raise CheckpointRetentionError("checkpoint is not a standalone regular artifact")
    before = path.stat()
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if (data.get("kind") != "world_checkpoint_v1"
            or data.get("schema_version") != 1 or data.get("quick_check") != "ok"
            or data.get("database") != str(path)
            or data.get("database_sha256") != file_sha256(path)):
        raise CheckpointRetentionError("checkpoint manifest or checksum mismatch")
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro&immutable=1", uri=True)
    try:
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise CheckpointRetentionError("checkpoint failed SQLite verification")
    finally:
        connection.close()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise CheckpointRetentionError("checkpoint changed during verification")
    return data


def _fingerprint(path: Path) -> tuple:
    return tuple((item.stat().st_size, item.stat().st_mtime_ns, item.stat().st_ino)
                 for item in (path, checkpoint_manifest_path(path)))


def verify_for_retention(paths: list[Path]) -> dict:
    """Expensive filesystem work, safe to perform off the serving event loop."""
    verified = {}
    for path in paths:
        try:
            before = _fingerprint(path)
            manifest = verify_checkpoint(path)
            if before != _fingerprint(path):
                raise CheckpointRetentionError("checkpoint changed during verification")
            verified[path] = (before, manifest)
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, CheckpointRetentionError):
            verified[path] = None
    return verified


def pin_checkpoint(database: str | Path, reason: str) -> Path:
    path = Path(database).absolute()
    if not reason.strip() or len(reason) > 500:
        raise ValueError("pin reason must contain 1-500 characters")
    manifest = verify_checkpoint(path)
    target = pin_path(path)
    _atomic_json(target, {
        "version": 1, "database_sha256": manifest["database_sha256"],
        "reason": reason, "run_id": manifest["state"]["run_id"],
        "tick": manifest["state"]["tick"],
    })
    return target


def unpin_checkpoint(database: str | Path) -> None:
    path = Path(database).absolute()
    verify_checkpoint(path)
    target = pin_path(path)
    if target.exists() and _is_link(target):
        raise CheckpointRetentionError("pin may not be a link")
    target.unlink(missing_ok=True)


def _atomic_json(target: Path, value: dict) -> None:
    if target.exists() and _is_link(target):
        raise CheckpointRetentionError("metadata target may not be a link")
    descriptor, name = tempfile.mkstemp(prefix=".storage-", suffix=".json", dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        _fsync_directory(target.parent)
    finally:
        temporary.unlink(missing_ok=True)


def write_recovery_checkpoint(source: str, destination: Path) -> None:
    """Publish the body only after its replacement has passed verification.

    Publishing two files cannot be one atomic rename. If the process dies
    between the body and manifest renames, retention treats the slot as
    unverified and preserves the other verified recovery points.
    """
    destination = destination.absolute()
    manifest_path = checkpoint_manifest_path(destination)
    if pin_path(destination).exists():
        raise CheckpointRetentionError("cannot replace a pinned recovery point")
    for path in (destination, manifest_path):
        if path.exists() and _is_link(path):
            raise CheckpointRetentionError("checkpoint target may not be a link")
    descriptor, name = tempfile.mkstemp(
        prefix=".checkpoint-", suffix=".sqlite3", dir=destination.parent)
    os.close(descriptor)
    temporary = Path(name)
    source_conn = target_conn = None
    try:
        source_conn = sqlite3.connect(f"{Path(source).resolve().as_uri()}?mode=ro", uri=True)
        target_conn = sqlite3.connect(temporary)
        source_conn.backup(target_conn)
        target_conn.close()
        target_conn = None
        source_conn.close()
        source_conn = None
        finalize_sqlite_artifact(temporary)
        manifest = build_checkpoint_manifest(temporary)
        if manifest["quick_check"] != "ok":
            raise CheckpointRetentionError("new checkpoint failed SQLite verification")
        manifest["database"] = str(destination)
        with temporary.open("r+b") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        _fsync_directory(destination.parent)
        _atomic_json(manifest_path, manifest)
    finally:
        if target_conn is not None:
            target_conn.close()
        if source_conn is not None:
            source_conn.close()
        temporary.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm", "-journal"):
            Path(f"{temporary}{suffix}").unlink(missing_ok=True)


def prune_checkpoints(store, directory: str | Path, policy: StoragePolicy, *, verified: dict | None = None) -> dict:
    """Run only on the owning world writer after publishing a new checkpoint."""
    root = Path(directory).resolve()
    run_id = str(store.get_meta()["run_id"])
    candidates: dict[Path, list[int]] = {}
    ticks: dict[Path, int] = {}
    for row in store.query("SELECT id,tick,path FROM checkpoints ORDER BY tick DESC,id DESC"):
        tick = int(row["tick"])
        path = root / f"{run_id}_t{tick}.db"
        if row["path"] != str(path) or path.parent != root or path.resolve() != path:
            continue
        candidates.setdefault(path, []).append(int(row["id"]))
        ticks[path] = tick
    retained, protected, removed = [], [], []
    valid: list[Path] = []
    for path in candidates:
        if (pin_path(path).exists() or not path.is_file()
                or not checkpoint_manifest_path(path).is_file()
                or _is_link(path) or _is_link(checkpoint_manifest_path(path))
                or _sidecars(path)):
            protected.append(path)
            continue
        try:
            data = json.loads(checkpoint_manifest_path(path).read_text(encoding="utf-8"))
            state = data["state"]
            if state["run_id"] != run_id or data["database"] != str(path):
                raise CheckpointRetentionError("checkpoint identity mismatch")
            # Tests and halt checkpoints may label an active phase with its
            # prior completed tick. Ownership is run/path based, not an assumed
            # equality between requested and completed simulation ticks.
            if verified is None:
                verify_checkpoint(path)
            else:
                cached = verified.get(path)
                if cached is None or cached[0] != _fingerprint(path) or cached[1] != data:
                    raise CheckpointRetentionError("checkpoint verification is missing or stale")
            valid.append(path)
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, CheckpointRetentionError):
            protected.append(path)
    retained = valid[:policy.checkpoint_keep_last]
    total = sum(path.stat().st_size for path in retained)
    while policy.checkpoint_max_bytes and total > policy.checkpoint_max_bytes and len(retained) > 2:
        total -= retained.pop().stat().st_size
    stale = [path for path in valid if path not in retained] if len(retained) >= 2 else []
    removed_bytes = 0
    for path in stale:
        if pin_path(path).exists() or _sidecars(path) or _is_link(path):
            protected.append(path)
            continue
        size = path.stat().st_size
        # Preserve the manifest as evidence if body removal fails.
        path.unlink()
        checkpoint_manifest_path(path).unlink(missing_ok=True)
        for row_id in candidates[path]:
            store.execute("DELETE FROM checkpoints WHERE id=?", (row_id,))
        store.commit()
        removed.append({"tick": ticks[path], "name": path.name, "bytes": size})
        removed_bytes += size
    protected_bytes = sum(path.stat().st_size for path in protected if path.is_file())
    receipt = {
        "version": 1, "run_id": run_id,
        "retained": [path.name for path in retained],
        "protected": len(protected), "removed": removed,
        "bytes_removed": removed_bytes,
        "retained_bytes": total + protected_bytes,
        "budget_exceeded": bool(policy.checkpoint_max_bytes
                                and total + protected_bytes > policy.checkpoint_max_bytes),
    }
    _atomic_json(root / f"{run_id}.retention.json", receipt)
    return receipt

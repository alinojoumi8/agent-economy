"""Exclusive, atomic publication for local scientific artifacts."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from uuid import uuid4


def digest_json(value: object) -> str:
    return hashlib.sha256(json_bytes(value)).hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False,
                       allow_nan=False) + "\n").encode("utf-8")


def file_sha256(path: str | Path) -> str:
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def publish_bytes(path: str | Path, payload: bytes) -> Path:
    """Publish a fully flushed file without replacing any existing artifact."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, target)  # Atomic, fails if another writer claimed it.
        if os.name != "nt":
            directory = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def publish_json(path: str | Path, value: object) -> Path:
    return publish_bytes(path, json_bytes(value))


def safe_key(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}", value):
        raise ValueError("study and arm keys must be simple path-safe identifiers")
    return value


def code_identity() -> dict:
    """Identify checked-out source, including uncommitted implementation files."""
    root = Path(__file__).resolve().parents[1]
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, stderr=subprocess.DEVNULL).decode().strip()
        paths = subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root, stderr=subprocess.DEVNULL).decode().split("\0")
    except (OSError, subprocess.CalledProcessError, UnicodeError):
        # An unverifiable source checkout must not silently become research evidence.
        raise RuntimeError("research execution requires a readable Git source identity") from None
    files = {name: file_sha256(root / name) for name in sorted(set(paths))
             if name and (root / name).is_file()}
    return {"git_commit": commit, "source_tree_sha256": digest_json(files)}


def create_batch(key: str, protocol: dict, *, data_root: str | Path,
                 out_dir: str | Path) -> dict:
    """Claim a fresh batch namespace; every retry remains independently visible."""
    safe_key(key)
    manifest = {"protocol_version": 1, **protocol, "code": code_identity()}
    manifest_sha256 = digest_json(manifest)
    batch_id = uuid4().hex
    # Full identities live in the manifest; compact folders also work under
    # ordinary Windows MAX_PATH installations and long pytest/worktree roots.
    relative = Path(key[:24]) / f"{manifest_sha256[:12]}-{batch_id[:12]}"
    data_dir = Path(data_root).resolve() / relative
    report_dir = Path(out_dir).resolve() / "studies" / relative
    data_dir.mkdir(parents=True, exist_ok=False)
    report_dir.mkdir(parents=True, exist_ok=False)
    claim = {"batch_id": batch_id, "manifest_sha256": manifest_sha256,
             "manifest": manifest}
    publish_json(data_dir / "manifest.json", claim)
    publish_json(report_dir / "manifest.json", claim)
    return {**claim, "data_dir": str(data_dir), "report_dir": str(report_dir)}

"""Self-contained, verified run copies. Sources are never rewritten or removed."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from .checkpoint_manifest import (
    build_checkpoint_manifest, canonical_json_bytes, checkpoint_manifest_path,
    file_sha256, finalize_sqlite_artifact, _fsync_directory,
)
from .checkpoint_retention import _atomic_json, verify_checkpoint, write_recovery_checkpoint
from .payloads import pack_payload, unpack_payload
from .storage_policy import GiB, StoragePolicy, database_bytes


def _new_destination(destination: str | Path) -> Path:
    path = Path(destination).absolute()
    if path.exists() or path.is_symlink() or checkpoint_manifest_path(path).exists():
        raise FileExistsError("storage output already exists; choose a new destination")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.resolve() != path:
        raise ValueError("storage output must use a canonical path without links")
    return path


def _payload_hash(connection: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    for row in connection.execute("SELECT id,request_json,response_json FROM llm_calls ORDER BY id"):
        for value in row:
            encoded = json.dumps(unpack_payload(value), ensure_ascii=False).encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
    return digest.hexdigest()


def copy_run(source: str | Path, destination: str | Path, *, encoding: str = "plain",
             min_free_bytes: int = 5 * GiB) -> dict:
    """Snapshot committed WAL data, convert only model bodies, and verify them.

    VACUUM operates solely on the new private copy. Even a corrupt packed
    payload or interrupted conversion leaves the original run unchanged.
    """
    if encoding not in {"plain", "packed"}:
        raise ValueError("encoding must be plain or packed")
    target = _new_destination(destination)
    source = Path(source).resolve(strict=True)
    StoragePolicy(min_free_bytes=min_free_bytes).check_free(
        target.parent, additional_bytes=3 * database_bytes(source))
    with tempfile.TemporaryDirectory(prefix=".run-copy-", dir=target.parent) as directory:
        staged = Path(directory) / "run.sqlite3"
        write_recovery_checkpoint(str(source), staged)
        connection = sqlite3.connect(staged)
        try:
            before = _payload_hash(connection)
            last_id = -1
            processed = 0
            while True:
                row = connection.execute(
                    "SELECT id,request_json,response_json FROM llm_calls "
                    "WHERE id>? ORDER BY id LIMIT 1", (last_id,)).fetchone()
                if row is None:
                    break
                row_id, request, response = row
                values = [unpack_payload(value) for value in (request, response)]
                # A plain export can be much larger than its compressed source.
                # Check room for the next body and journal before writing it.
                required = sum(len(value.encode("utf-8")) for value in values if value is not None)
                StoragePolicy(min_free_bytes=min_free_bytes).check_free(
                    target.parent, additional_bytes=2 * required)
                if encoding == "packed":
                    values = [pack_payload(value) for value in values]
                connection.execute(
                    "UPDATE llm_calls SET request_json=?,response_json=? WHERE id=?",
                    (*values, row_id))
                last_id = row_id
                processed += 1
                if processed % 100 == 0:
                    connection.commit()
            connection.commit()
            if before != _payload_hash(connection):
                raise ValueError("converted model payloads failed logical verification")
            StoragePolicy(min_free_bytes=min_free_bytes).check_free(
                target.parent, additional_bytes=2 * staged.stat().st_size)
            connection.execute("VACUUM")
        finally:
            connection.close()
        finalize_sqlite_artifact(staged)
        manifest = build_checkpoint_manifest(staged)
        if manifest["quick_check"] != "ok":
            raise ValueError("converted run failed SQLite verification")
        manifest["database"] = str(target)
        # A concurrent operator may have selected the same output. Hard-link
        # publication is atomic and refuses to replace an existing file.
        os.link(staged, target)
        _fsync_directory(target.parent)
        _atomic_json(checkpoint_manifest_path(target), manifest)
    return {"database": str(target), "encoding": encoding,
            "bytes": target.stat().st_size, "database_sha256": manifest["database_sha256"],
            "payloads_sha256": before}


def archive_run(source: str | Path, destination: str | Path, *,
                min_free_bytes: int = 5 * GiB) -> dict:
    target = _new_destination(destination)
    source = Path(source).resolve(strict=True)
    StoragePolicy(min_free_bytes=min_free_bytes).check_free(
        target.parent, additional_bytes=3 * database_bytes(source))
    with tempfile.TemporaryDirectory(prefix=".run-archive-", dir=target.parent) as directory:
        staged = Path(directory) / "run.db"
        write_recovery_checkpoint(str(source), staged)
        manifest = verify_checkpoint(staged)
        manifest["database"] = "run.db"
        manifest["archive_kind"] = "agent_economy_run_v1"
        manifest["database_bytes"] = staged.stat().st_size
        zipped = Path(directory) / "run.zip"
        with zipfile.ZipFile(zipped, "x", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6, allowZip64=True) as archive:
            archive.write(staged, "run.db")
            archive.writestr("manifest.json", canonical_json_bytes(manifest))
        # CRC, SHA and SQLite verification on the actual compressed output.
        restored = Path(directory) / "verified.db"
        restore_archive(zipped, restored, min_free_bytes=0)
        with zipped.open("r+b") as handle:
            os.fsync(handle.fileno())
        os.link(zipped, target)
        _fsync_directory(target.parent)
    return {"archive": str(target), "bytes": target.stat().st_size,
            "archive_sha256": file_sha256(target),
            "database_sha256": manifest["database_sha256"], "verified": True}


def restore_archive(source: str | Path, destination: str | Path, *,
                    max_database_bytes: int = 100 * GiB, min_free_bytes: int = 5 * GiB) -> dict:
    target = _new_destination(destination)
    with zipfile.ZipFile(source, "r") as archive:
        if sorted(archive.namelist()) != ["manifest.json", "run.db"]:
            raise ValueError("run archive must contain exactly one database and manifest")
        if archive.getinfo("manifest.json").file_size > 1024 * 1024:
            raise ValueError("archive manifest is too large")
        manifest = json.loads(archive.read("manifest.json"))
        size = archive.getinfo("run.db").file_size
        if (manifest.get("archive_kind") != "agent_economy_run_v1"
                or type(manifest.get("database_bytes")) is not int
                or manifest["database_bytes"] != size or not 0 < size <= max_database_bytes):
            raise ValueError("invalid archive identity or database size")
        StoragePolicy(min_free_bytes=min_free_bytes).check_free(target.parent, additional_bytes=size)
        with tempfile.TemporaryDirectory(prefix=".run-restore-", dir=target.parent) as directory:
            staged = Path(directory) / "restored.sqlite3"
            # Fixed member name; never extract a path supplied by an archive.
            with archive.open("run.db") as incoming, staged.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            if staged.stat().st_size != size or file_sha256(staged) != manifest.get("database_sha256"):
                raise ValueError("archive database checksum mismatch")
            manifest["database"] = str(staged)
            _atomic_json(checkpoint_manifest_path(staged), manifest)
            verify_checkpoint(staged)
            # Compare embedded identity with actual restored state as well.
            actual = build_checkpoint_manifest(staged)
            if actual["state_sha256"] != manifest["state_sha256"]:
                raise ValueError("archive run state mismatch")
            actual["database"] = str(target)
            os.link(staged, target)
            _fsync_directory(target.parent)
            _atomic_json(checkpoint_manifest_path(target), actual)
    return {"database": str(target), "bytes": size,
            "database_sha256": actual["database_sha256"], "verified": True}

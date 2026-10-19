"""Versioned immutable-base checkpoints with verified content-addressed chunks.

Only the small checkpoint descriptor is replaced. All roots and chunk objects
are immutable, and publication is last. Readers never trust paths from a root.
The existing v1 SQLite/manifest contract is unchanged.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from engine.checkpoint_image import logical_image
from engine.checkpoint_manifest import (
    _fsync_directory, canonical_json_bytes, checkpoint_core_evidence,
    checkpoint_state_binding, sqlite_schema_evidence,
)
from research.process_lock import process_lock
from engine.storage_policy import StorageBudgetExceeded, _is_link

CHUNK_SIZE = 64 * 1024
MAX_BYTES = 16 * 1024**3
MAX_ROOT_BYTES = 64 * 1024**2
KIND = "world_checkpoint_chunks_v2"
HEX = re.compile(r"[0-9a-f]{64}\Z")


class IncrementalCheckpointError(ValueError):
    """Invalid, corrupted or unsupported incremental checkpoint."""


def _linked(path: Path) -> bool:
    try:
        return _is_link(path)
    except FileNotFoundError:
        return False


def _hash(data: bytes) -> str:
    # Loaded only for the explicitly selected v2 format.
    from blake3 import blake3
    return blake3(data).hexdigest()


def _regular(path: Path, limit: int) -> bytes:
    if _linked(path) or not path.is_file() or path.stat().st_nlink != 1:
        raise IncrementalCheckpointError("missing or linked checkpoint object")
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise IncrementalCheckpointError("checkpoint object exceeds size limit")
    return data


def _digest(value) -> str:
    if not isinstance(value, str) or HEX.fullmatch(value) is None:
        raise IncrementalCheckpointError("invalid checkpoint digest")
    return value


def _directory(path: Path, *, create: bool = False) -> Path:
    # Reject linked ancestors as well as linked individual objects.
    if any(_linked(p) for p in (path, *path.parents)):
        raise IncrementalCheckpointError("linked checkpoint directory")
    if create:
        path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise IncrementalCheckpointError("missing checkpoint directory")
    return path


def _archive(descriptor: Path, *, create=False) -> Path:
    parent = _directory(descriptor.absolute().parent, create=create)
    return _directory(parent / ".checkpoint-v2", create=create)


def _immutable(path: Path, data: bytes) -> bool:
    """Publish once, preserving existing bytes even when they are corrupt."""
    if path.exists() or _linked(path):
        if _regular(path, len(data)) != data:
            raise IncrementalCheckpointError("immutable object content mismatch")
        return False
    fd, name = tempfile.mkstemp(dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if _regular(path, len(data)) != data:
                raise IncrementalCheckpointError("immutable object race")
    finally:
        temporary.unlink(missing_ok=True)
    return True


def _json(data: bytes) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise IncrementalCheckpointError("duplicate checkpoint key")
            result[key] = value
        return result
    try:
        value = json.loads(data, object_pairs_hook=unique)
    except (ValueError, UnicodeError) as exc:
        raise IncrementalCheckpointError("invalid checkpoint JSON") from exc
    if not isinstance(value, dict):
        raise IncrementalCheckpointError("invalid checkpoint structure")
    return value


def _root(archive: Path, digest: str) -> dict:
    data = _regular(archive / (_digest(digest) + ".root"), MAX_ROOT_BYTES)
    if hashlib.sha256(data).hexdigest() != digest:
        raise IncrementalCheckpointError("checkpoint root checksum mismatch")
    root = _json(data)
    if (root.get("kind") != KIND or root.get("version") != 2
            or root.get("chunk_size") != CHUNK_SIZE
            or root.get("packing") != "lz4-blocks-v1"
            or type(root.get("size")) is not int
            or not 0 < root["size"] <= MAX_BYTES
            or type(root.get("page_size")) is not int
            or root["page_size"] not in (512, 1024, 2048, 4096, 8192, 16384, 32768, 65536)
            or root["size"] % root["page_size"]):
        raise IncrementalCheckpointError("unsupported checkpoint root")
    packs = root.get("packs")
    if not isinstance(packs, list) or len(packs) > (MAX_BYTES // CHUNK_SIZE):
        raise IncrementalCheckpointError("invalid checkpoint pack index")
    packs = [_digest(p) for p in packs]
    entries = root.get("chunks") if root.get("base") is None else root.get("changes")
    entries = entries.values() if isinstance(entries, dict) else entries
    if not isinstance(entries, (list, type({}.values()))):
        raise IncrementalCheckpointError("invalid checkpoint chunk index")
    for entry in entries:
        if (not isinstance(entry, list) or len(entry) != 6
                or type(entry[1]) is not int or not 0 <= entry[1] < len(packs)):
            raise IncrementalCheckpointError("invalid checkpoint pack reference")
        entry[1] = packs[entry[1]]
    return root


def _entry(value):
    if (not isinstance(value, list) or len(value) != 6
            or type(value[2]) is not int or value[2] < 0
            or type(value[3]) is not int or not 0 < value[3] <= CHUNK_SIZE
            or type(value[4]) is not int or not 0 < value[4] <= CHUNK_SIZE
            or type(value[5]) is not int or value[5] not in (0, 1)
            or (value[5] == 0 and value[3] != value[4])
            or (value[5] == 1 and value[3] >= value[4])
            or value[2] + value[3] > MAX_BYTES):
        raise IncrementalCheckpointError("invalid checkpoint chunk entry")
    _digest(value[0])
    _digest(value[1])
    return value


def _index(archive: Path, root: dict) -> tuple[list[list], str | None]:
    count = (root["size"] + CHUNK_SIZE - 1) // CHUNK_SIZE
    base_digest = root.get("base")
    if base_digest is None:
        chunks = root.get("chunks")
        if not isinstance(chunks, list) or len(chunks) != count:
            raise IncrementalCheckpointError("invalid base chunk index")
        return [_entry(d) for d in chunks], None
    base = _root(archive, _digest(base_digest))
    if base.get("base") is not None:
        raise IncrementalCheckpointError("checkpoint delta chains are unsupported")
    if base["page_size"] != root["page_size"]:
        raise IncrementalCheckpointError("checkpoint base page size mismatch")
    chunks, _ = _index(archive, base)
    chunks = chunks[:count] + [None] * max(0, count - len(chunks))
    changes = root.get("changes")
    if not isinstance(changes, dict) or len(changes) > count:
        raise IncrementalCheckpointError("invalid checkpoint delta index")
    for key, digest in changes.items():
        if not isinstance(key, str) or not key.isascii() or not key.isdigit():
            raise IncrementalCheckpointError("invalid checkpoint chunk offset")
        index = int(key)
        if str(index) != key or not 0 <= index < count:
            raise IncrementalCheckpointError("invalid checkpoint chunk offset")
        chunks[index] = _entry(digest)
    if any(d is None for d in chunks):
        raise IncrementalCheckpointError("incomplete checkpoint chunk index")
    return chunks, base_digest


def read_incremental(path: str | Path) -> tuple[dict, list[list], Path, str]:
    descriptor = Path(path).absolute()
    archive = _archive(descriptor)
    declaration = _json(_regular(descriptor, 4096))
    if declaration.get("kind") != KIND or declaration.get("version") != 2:
        raise IncrementalCheckpointError("unsupported checkpoint descriptor")
    digest = _digest(declaration.get("root_sha256"))
    root = _root(archive, digest)
    chunks, _ = _index(archive, root)
    return root, chunks, archive, digest


def _pack(path: Path):
    if (_linked(path) or not path.is_file() or path.stat().st_nlink != 1
            or not 0 < path.stat().st_size <= MAX_BYTES):
        raise IncrementalCheckpointError("missing or invalid checkpoint pack")
    return path.open("rb")


def _chunk(handle, entry):
    digest, _, offset, length, raw_length, codec = entry
    handle.seek(offset)
    data = handle.read(length)
    if len(data) != length:
        raise IncrementalCheckpointError("checkpoint chunk checksum mismatch")
    if codec == 1:
        import lz4.block
        try:
            # Never use a stored compressor size header. The independently
            # bounded root length fixes the maximum native output allocation.
            data = lz4.block.decompress(data, uncompressed_size=raw_length)
        except lz4.block.LZ4BlockError as exc:
            raise IncrementalCheckpointError("invalid compressed checkpoint chunk") from exc
    if len(data) != raw_length or _hash(data) != digest:
        raise IncrementalCheckpointError("checkpoint chunk checksum mismatch")
    return data


def _verify_objects(archive: Path, chunks: list[list], size: int, *, verified=frozenset()) -> None:
    packs = {}
    for index, entry in enumerate(chunks):
        if entry[4] != min(CHUNK_SIZE, size - index * CHUNK_SIZE):
            raise IncrementalCheckpointError("checkpoint chunk length mismatch")
        if tuple(entry) not in verified:
            packs.setdefault(entry[1], {})[tuple(entry)] = entry
    for pack, entries in packs.items():
        with _pack(archive / (pack + ".pack")) as handle:
            for entry in sorted(entries.values(), key=lambda e: e[2]):
                _chunk(handle, entry)


def _source_quick_check(source: str | Path) -> list[str]:
    """An independent native reader at the writer-excluded committed cut."""
    path = Path(source).absolute()
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0)
    try:
        db.execute("PRAGMA query_only=ON")
        return [row[0] for row in db.execute("PRAGMA quick_check")]
    finally:
        db.close()


def _evidence(db: sqlite3.Connection, *, quick_check=None) -> dict:
    state = checkpoint_state_binding(db)
    core = checkpoint_core_evidence(db, checkpoint_tick=int(state["tick"]))
    quick = ([row[0] for row in db.execute("PRAGMA quick_check")]
             if quick_check is None else quick_check())
    if quick != ["ok"] or any(core["ledger"].values()):
        raise IncrementalCheckpointError("checkpoint integrity or ledger check failed")
    return {"quick_check": "ok", "schema": sqlite_schema_evidence(db),
            "state": state, "core": core}


def _publish(descriptor: Path, declaration: dict) -> None:
    if _linked(descriptor):
        raise IncrementalCheckpointError("linked checkpoint descriptor")
    fd, name = tempfile.mkstemp(dir=descriptor.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(canonical_json_bytes(declaration))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, descriptor)
        _fsync_directory(descriptor.parent)
    finally:
        temporary.unlink(missing_ok=True)


def save_incremental(source: str | Path, descriptor: str | Path,
                     *, base: str | Path | None = None,
                     max_archive_bytes: int = 0, min_free_bytes: int = 0,
                     discard: tuple[Path, ...] = (), collect: bool = False) -> dict:
    started = time.perf_counter()
    archive = _archive(Path(descriptor), create=True)
    with process_lock(archive / ".lock"):
        pin = Path(str(descriptor) + ".pin.json")
        if pin.exists() or _linked(pin):
            raise IncrementalCheckpointError("cannot replace a pinned checkpoint")
        receipt = _save_incremental(source, descriptor, base=base,
                                    max_archive_bytes=max_archive_bytes,
                                    min_free_bytes=min_free_bytes, discard=discard, collect=collect)
    receipt["seconds"] = time.perf_counter() - started
    return receipt


def _save_incremental(source: str | Path, descriptor: str | Path,
                      *, base: str | Path | None = None,
                      max_archive_bytes: int = 0, min_free_bytes: int = 0,
                      discard: tuple[Path, ...] = (), collect: bool = False) -> dict:
    """Capture, validate and durably publish; all required work is timed."""
    started = time.perf_counter()
    target = Path(descriptor).absolute()
    archive = _archive(target, create=True)
    for limit in (max_archive_bytes, min_free_bytes):
        if type(limit) is not int or limit < 0:
            raise ValueError("checkpoint storage limits must be nonnegative integers")
    base_root = None
    base_chunks = []
    if base is not None:
        previous, previous_chunks, previous_archive, previous_digest = read_incremental(base)
        if previous_archive != archive:
            raise IncrementalCheckpointError("checkpoint base belongs to another archive")
        base_root = previous.get("base") or previous_digest
        original = _root(archive, base_root)
        base_chunks, _ = _index(archive, original)
    counts = {"new_chunks": 0, "written_bytes": 0, "new_logical_bytes": 0}

    def capture(image):
        from blake3 import blake3
        import lz4.block
        known = {entry[0]: entry for entry in base_chunks}
        if base is not None:
            known.update({entry[0]: entry for entry in previous_chunks})
        chunks, pending = [], {}
        fd, name = tempfile.mkstemp(dir=archive)
        temporary = Path(name)
        pack_hash = blake3()
        try:
            with os.fdopen(fd, "wb") as output:
                for data in image.chunks(CHUNK_SIZE):
                    digest = _hash(data)
                    if digest in known:
                        entry = known[digest]
                    elif digest in pending:
                        entry = pending[digest]
                    else:
                        compressed = lz4.block.compress(data, store_size=False)
                        stored, codec = (compressed, 1) if len(compressed) < len(data) else (data, 0)
                        entry = [digest, None, output.tell(), len(stored), len(data), codec]
                        pending[digest] = entry
                        free = shutil.disk_usage(archive).free
                        if free < min_free_bytes + len(stored):
                            raise StorageBudgetExceeded("free_space", free, min_free_bytes + len(stored))
                        output.write(stored)
                        pack_hash.update(stored)
                        counts["new_chunks"] += 1
                        counts["written_bytes"] += len(stored)
                        counts["new_logical_bytes"] += len(data)
                    chunks.append(entry)
                output.flush()
                os.fsync(output.fileno())
            if pending:
                pack_digest = pack_hash.hexdigest()
                pack_path = archive / (pack_digest + ".pack")
                try:
                    os.link(temporary, pack_path)
                except FileExistsError:
                    actual = blake3()
                    with _pack(pack_path) as handle:
                        for data in iter(lambda: handle.read(CHUNK_SIZE), b""):
                            actual.update(data)
                    if actual.hexdigest() != pack_digest:
                        raise IncrementalCheckpointError("immutable pack content mismatch")
                for entry in pending.values():
                    entry[1] = pack_digest
            return chunks
        finally:
            temporary.unlink(missing_ok=True)
    with logical_image(source, max_bytes=MAX_BYTES) as (db, image):
        with ThreadPoolExecutor(max_workers=3) as pool:
            verify = (pool.submit(_verify_objects, archive, previous_chunks, previous["size"])
                      if base is not None else None)
            captured = pool.submit(capture, image)
            quick = pool.submit(_source_quick_check, source)
            evidence = _evidence(db, quick_check=quick.result)
            chunks = captured.result()
            if verify is not None:
                verify.result()
            prior_verified = {tuple(entry) for entry in previous_chunks} if base is not None else set()
            _verify_objects(archive, chunks, image.size, verified=prior_verified)
        if base is not None and (previous["evidence"]["state"]["run_id"]
                                 != evidence["state"]["run_id"]):
            raise IncrementalCheckpointError("checkpoint base run mismatch")
        root = {"kind": KIND, "version": 2, "chunk_size": CHUNK_SIZE,
                "packing": "lz4-blocks-v1",
                "size": image.size, "page_size": image.page_size,
                "evidence": evidence}
        if base_root is None:
            root["chunks"] = chunks
        else:
            root.update(base=base_root, changes={
                str(i): d for i, d in enumerate(chunks)
                if i >= len(base_chunks) or d != base_chunks[i]})
    # The context exit rechecks the committed boundary before publication.
    entries = root["chunks"] if base_root is None else list(root["changes"].values())
    packs = sorted({e[1] for e in entries})
    pack_indices = {digest: i for i, digest in enumerate(packs)}
    root["packs"] = packs
    encode_entry = lambda e: [e[0], pack_indices[e[1]], *e[2:]]
    if base_root is None:
        root["chunks"] = [encode_entry(e) for e in entries]
    else:
        root["changes"] = {key: encode_entry(e) for key, e in root["changes"].items()}
    encoded = (json.dumps(root, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    if len(encoded) > MAX_ROOT_BYTES:
        raise IncrementalCheckpointError("checkpoint root exceeds size limit")
    digest = hashlib.sha256(encoded).hexdigest()
    free = shutil.disk_usage(archive).free
    if free < min_free_bytes + len(encoded) + 4096:
        raise StorageBudgetExceeded("free_space", free, min_free_bytes + len(encoded) + 4096)
    _immutable(archive / (digest + ".root"), encoded)
    _fsync_directory(archive)
    _publish(target, {"kind": KIND, "version": 2, "root_sha256": digest})
    retention = None
    retention_error = None
    if discard or collect:
        # Reuse only proofs computed under this still-held archive lock. No
        # persisted/stat-only cache can turn corrupt bytes into verified data.
        verified = prior_verified | {tuple(entry) for entry in chunks}
        try:
            retention = _prune_incremental(target.parent, discard=list(discard), verified=verified)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            # Publication is complete. Failed maintenance must be observable
            # without turning a valid new recovery point into a failed save.
            retention_error = type(exc).__name__
    retained_bytes = sum(p.stat().st_size for p in archive.iterdir()
                         if p.is_file() and not p.is_symlink())
    return {"kind": KIND, "root_sha256": digest, "bytes": image.size,
            "chunks": len(chunks), **counts,
            "seconds": time.perf_counter() - started, "evidence": evidence,
            "retention": retention, "retention_error": retention_error,
            "retained_bytes": retained_bytes,
            "budget_exceeded": bool(max_archive_bytes and retained_bytes > max_archive_bytes)}


def restore_incremental(descriptor: str | Path, destination: str | Path,
                        *, max_bytes: int = MAX_BYTES) -> dict:
    """Verify every byte and SQLite evidence before publishing a fresh copy."""
    started = time.perf_counter()
    archive = _archive(Path(descriptor))
    with process_lock(archive / ".lock"):
        receipt = _restore_incremental(descriptor, destination, max_bytes=max_bytes)
    receipt["seconds"] = time.perf_counter() - started
    return receipt


def _restore_incremental(descriptor: str | Path, destination: str | Path,
                         *, max_bytes: int = MAX_BYTES) -> dict:
    started = time.perf_counter()
    root, chunks, archive, digest = read_incremental(descriptor)
    if type(max_bytes) is not int or max_bytes < 1 or root["size"] > max_bytes:
        raise IncrementalCheckpointError("checkpoint exceeds restore size limit")
    target = Path(destination).absolute()
    _directory(target.parent)
    if target.exists() or target.is_symlink():
        raise IncrementalCheckpointError("restore destination already exists")
    with tempfile.TemporaryDirectory(dir=target.parent) as directory:
        staged = Path(directory) / "restore.db"
        with staged.open("wb") as out:
            # One descriptor at a time bounds handles even after many saves.
            handle = None
            opened = None
            try:
                for index, entry in enumerate(chunks):
                    if entry[4] != min(CHUNK_SIZE, root["size"] - index * CHUNK_SIZE):
                        raise IncrementalCheckpointError("checkpoint chunk length mismatch")
                    if entry[1] != opened:
                        if handle is not None:
                            handle.close()
                        handle = _pack(archive / (entry[1] + ".pack"))
                        opened = entry[1]
                    out.write(_chunk(handle, entry))
            finally:
                if handle is not None:
                    handle.close()
            out.flush()
            os.fsync(out.fileno())
        db = sqlite3.connect(staged.as_uri() + "?mode=ro&immutable=1", uri=True)
        db.row_factory = sqlite3.Row
        try:
            if _evidence(db) != root.get("evidence"):
                raise IncrementalCheckpointError("restored checkpoint evidence mismatch")
        finally:
            db.close()
        # Exclusive publication avoids overwriting an unrelated destination.
        os.link(staged, target)
        _fsync_directory(target.parent)
    return {"kind": KIND, "root_sha256": digest, "bytes": root["size"],
            "seconds": time.perf_counter() - started,
            "evidence": root["evidence"]}


def prune_incremental(directory: str | Path, *, discard: list[Path]) -> dict:
    """Remove only unpinned owned descriptors and unreachable immutable packs.

    Every remaining descriptor in this archive participates, including other
    runs. Uncertain metadata aborts collection before any deletion. Concurrent
    capture/restore/pinning must use the same process-owned archive lock.
    """
    parent = _directory(Path(directory).absolute())
    archive = _archive(parent / "unused.icp.json")
    with process_lock(archive / ".lock"):
        return _prune_incremental(parent, discard=discard)


def _prune_incremental(parent: Path, *, discard: list[Path], verified=frozenset()) -> dict:
    archive = _archive(parent / "unused.icp.json")
    requested = {Path(p).absolute() for p in discard}
    if any(p.parent != parent or not p.name.endswith(".icp.json") for p in requested):
        raise IncrementalCheckpointError("invalid checkpoint retention path")
    roots, packs, removed = set(), set(), []
    descriptors = list(parent.glob("*.icp.json"))
    for descriptor in descriptors:
        root, chunks, _, digest = read_incremental(descriptor)
        _verify_objects(archive, chunks, root["size"], verified=verified)
        pin = Path(str(descriptor) + ".pin.json")
        if descriptor in requested and not (pin.exists() or _linked(pin)):
            removed.append(descriptor)
            continue
        roots.add(digest)
        if root.get("base"):
            roots.add(root["base"])
            base = _root(archive, root["base"])
            base_chunks, _ = _index(archive, base)
            _verify_objects(archive, base_chunks, base["size"], verified=verified)
            packs.update(entry[1] for entry in base_chunks)
        packs.update(entry[1] for entry in chunks)
    members = list(archive.iterdir())
    for candidate in members:
        if _linked(candidate):
            raise IncrementalCheckpointError("linked archive member")
    for descriptor in removed:
        descriptor.unlink()
    deleted_bytes = 0
    for candidate in members:
        suffix = candidate.suffix
        digest = candidate.stem
        if HEX.fullmatch(digest) and ((suffix == ".root" and digest not in roots)
                                     or (suffix == ".pack" and digest not in packs)):
            deleted_bytes += candidate.stat().st_size
            candidate.unlink()
    _fsync_directory(archive)
    _fsync_directory(parent)
    return {"removed": [str(p) for p in removed], "deleted_bytes": deleted_bytes}


def pin_incremental(descriptor: str | Path, reason: str) -> Path:
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
        raise ValueError("pin reason must contain 1-500 characters")
    path = Path(descriptor).absolute()
    archive = _archive(path)
    with process_lock(archive / ".lock"):
        with tempfile.TemporaryDirectory(prefix=".manyworld-pin-", dir=path.parent) as directory:
            receipt = _restore_incremental(path, Path(directory) / "verified.db")
        target = Path(str(path) + ".pin.json")
        _publish(target, {"version": 2, "root_sha256": receipt["root_sha256"],
                          "reason": reason, "state": receipt["evidence"]["state"]})
        return target


def unpin_incremental(descriptor: str | Path) -> None:
    path = Path(descriptor).absolute()
    archive = _archive(path)
    with process_lock(archive / ".lock"):
        root, chunks, _, _ = read_incremental(path)
        _verify_objects(archive, chunks, root["size"])
        target = Path(str(path) + ".pin.json")
        if _linked(target):
            raise IncrementalCheckpointError("linked checkpoint pin")
        target.unlink(missing_ok=True)
        _fsync_directory(path.parent)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Verify and materialize a v2 checkpoint")
    parser.add_argument("checkpoint")
    parser.add_argument("destination")
    args = parser.parse_args()
    result = restore_incremental(args.checkpoint, args.destination)
    print(json.dumps({key: result[key] for key in ("kind", "root_sha256", "bytes", "seconds")}))

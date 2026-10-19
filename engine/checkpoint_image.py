"""A bounded logical SQLite image captured while its writer is excluded.

This is a storage image, not a new scientific canonicalization. WAL-index and
WAL layout follow https://sqlite.org/walformat.html. Callers must retain this
context until all reads and SQLite evidence collection have completed.
"""
from __future__ import annotations

import os
import sqlite3
import struct
from contextlib import ExitStack, contextmanager
from pathlib import Path
from engine.storage_policy import _is_link


class CheckpointImageError(ValueError):
    """The source cannot be captured with a bounded, stable logical image."""


def _checksum(data: bytes, endian: str) -> tuple[int, int]:
    if len(data) % 8:
        raise CheckpointImageError("invalid checksum input")
    words = struct.unpack(endian + str(len(data) // 4) + "I", data)
    a = b = 0
    for i in range(0, len(words), 2):
        a = (a + words[i] + b) & 0xFFFFFFFF
        b = (b + words[i + 1] + a) & 0xFFFFFFFF
    return a, b


def _read_at(handle, offset: int, size: int) -> bytes:
    handle.seek(offset)
    data = handle.read(size)
    if len(data) != size:
        raise CheckpointImageError("truncated SQLite image")
    return data


def _open_regular(stack: ExitStack, path: Path):
    if _is_link(path) or not path.is_file() or path.stat().st_nlink != 1:
        raise CheckpointImageError("SQLite image must be a regular file")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    handle = os.fdopen(fd, "rb")
    stack.callback(handle.close)
    return handle


class LogicalImage:
    """Sequential chunk reader over main bytes and committed WAL page images."""

    def __init__(self, main, wal, page_size, page_count, frames):
        self.main = main
        self.wal = wal
        self.page_size = page_size
        self.size = page_size * page_count
        self.frames = frames
        self.main_size = os.fstat(main.fileno()).st_size

    def chunks(self, chunk_size: int = 1024 * 1024):
        if chunk_size < self.page_size or chunk_size % self.page_size:
            raise ValueError("chunk size must be page aligned")
        overlays = {}
        for page, frame in self.frames.items():
            offset = (page - 1) * self.page_size
            overlays.setdefault(offset // chunk_size, []).append((offset, frame))
        for offset in range(0, self.size, chunk_size):
            length = min(chunk_size, self.size - offset)
            available = min(length, max(0, self.main_size - offset))
            data = _read_at(self.main, offset, available)
            changes = overlays.get(offset // chunk_size, ())
            if not changes and available == length:
                yield data
                continue
            data = bytearray(data)
            data.extend(b"\0" * (length - available))
            covered = set()
            for absolute, frame in changes:
                start = absolute - offset
                data[start:start + self.page_size] = _read_at(
                    self.wal, frame, self.page_size)
                covered.add(start)
            for start in range(available, length, self.page_size):
                if start not in covered:
                    raise CheckpointImageError("missing logical page")
            yield bytes(data)


@contextmanager
def logical_image(path: str | Path, *, max_bytes: int = 64 * 1024**3,
                  max_wal_frames: int = 262144):
    """Exclude writers and expose native SQLite evidence and its exact image.

    Does not change rows, journal mode, checkpoint the WAL or create a database.
    Opening an owned WAL database may update SQLite lock/read-mark sidecars.
    No live connection is shared across threads. Connections must be closed
    before releasing this context. A busy writer is an explicit failure.
    """
    database = Path(path).absolute()
    if database.is_symlink() or not database.is_file():
        raise CheckpointImageError("source database must already exist")
    if any(_is_link(p) for p in (database, *database.parents)):
        raise CheckpointImageError("source database may not be aliased")
    with ExitStack() as stack:
        db = sqlite3.connect(database.as_uri() + "?mode=rw", uri=True,
                             timeout=0, isolation_level=None)
        stack.callback(db.close)
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        stack.callback(db.rollback)
        db.execute("PRAGMA query_only=ON")
        page_size = int(db.execute("PRAGMA page_size").fetchone()[0])
        page_count = int(db.execute("PRAGMA page_count").fetchone()[0])
        if page_size not in (512, 1024, 2048, 4096, 8192, 16384, 32768, 65536):
            raise CheckpointImageError("unsupported SQLite page size")
        if page_count < 1 or page_count * page_size > max_bytes:
            raise CheckpointImageError("SQLite image size exceeds limit")
        main = _open_regular(stack, database)
        header = _read_at(main, 0, 100)
        if header[:16] != b"SQLite format 3\0":
            raise CheckpointImageError("invalid SQLite header")
        wal_path = Path(str(database) + "-wal")
        shm_path = Path(str(database) + "-shm")
        frames = {}
        wal = None
        shm = None
        index = None
        if wal_path.exists() and wal_path.stat().st_size:
            wal = _open_regular(stack, wal_path)
            shm = _open_regular(stack, shm_path)
            # The writer lock makes SQLite's two native-endian header copies
            # stable. Never infer committed length from the physical WAL size.
            index = _read_at(shm, 0, 96)
            first = index[:48]
            if first != index[48:] or first[12] != 1:
                raise CheckpointImageError("inconsistent WAL index")
            if struct.unpack("=I", first[:4])[0] != 3007000:
                raise CheckpointImageError("unsupported WAL index version")
            if _checksum(first[:40], "=") != struct.unpack("=II", first[40:]):
                raise CheckpointImageError("invalid WAL index checksum")
            nframes, npages = struct.unpack("=II", first[16:24])
            indexed_size = struct.unpack("=H", first[14:16])[0]
            indexed_size = 65536 if indexed_size == 1 else indexed_size
            if nframes > max_wal_frames:
                raise CheckpointImageError("WAL frame limit exceeded")
            if nframes:
                wh = _read_at(wal, 0, 32)
                magic, version, wal_page_size = struct.unpack(">III", wh[:12])
                if magic not in (0x377F0682, 0x377F0683) or version != 3007000:
                    raise CheckpointImageError("unsupported WAL format")
                if wal_page_size != page_size or indexed_size != page_size:
                    raise CheckpointImageError("inconsistent WAL page size")
                if npages != page_count or wh[16:24] != first[32:40]:
                    raise CheckpointImageError("inconsistent WAL generation")
                endian = ">" if magic & 1 else "<"
                if _checksum(wh[:24], endian) != struct.unpack(">II", wh[24:]):
                    raise CheckpointImageError("invalid WAL header checksum")
                for i in range(nframes):
                    pos = 32 + i * (24 + page_size)
                    fh = _read_at(wal, pos, 24)
                    page, committed_pages = struct.unpack(">II", fh[:8])
                    if page < 1 or fh[8:16] != wh[16:24]:
                        raise CheckpointImageError("invalid WAL frame")
                    if page <= page_count:
                        frames[page] = pos + 24
                    if i == nframes - 1:
                        checksums = struct.unpack(">II", fh[16:24])
                        if committed_pages != page_count or checksums != struct.unpack(
                                "=II", first[24:32]):
                            raise CheckpointImageError("invalid WAL commit boundary")
                        _read_at(wal, pos + 24, page_size)
        image = LogicalImage(main, wal, page_size, page_count, frames)
        yield db, image
        if index is not None and _read_at(shm, 0, 96) != index:
            raise CheckpointImageError("WAL changed during capture")

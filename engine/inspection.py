"""Non-writing SQLite inspection, including committed WAL pages.

SQLite mode=ro can write WAL read marks. Diagnostics instead materialize a
checksummed, optimistic snapshot in memory. This is not a recovery mechanism.
"""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import struct

MAX_SNAPSHOT_BYTES = 512 * 1024 * 1024


class SnapshotUnavailable(ValueError):
    pass


def _stamp(path):
    try:
        stat = path.stat()
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    except FileNotFoundError:
        return None


def _checksum(data, order, value=(0, 0)):
    if len(data) % 8:
        raise SnapshotUnavailable('invalid WAL checksum input')
    a, b = value
    for x, y in struct.iter_unpack(order + 'II', data):
        a = (a + x + b) & 0xffffffff
        b = (b + y + a) & 0xffffffff
    return a, b


def _committed_image(database, wal):
    if len(database) < 100 or database[:16] != b'SQLite format 3\x00':
        raise SnapshotUnavailable('invalid SQLite header')
    image = bytearray(database)
    if wal:
        if len(wal) < 32:
            raise SnapshotUnavailable('incomplete WAL header')
        magic, version, size = struct.unpack('>III', wal[:12])
        if magic not in {0x377f0682, 0x377f0683} or version != 3007000:
            raise SnapshotUnavailable('unsupported WAL format')
        db_size = int.from_bytes(image[16:18], 'big')
        db_size = 65536 if db_size == 1 else db_size
        if size != db_size or size < 512 or size > 65536 or size & (size - 1):
            raise SnapshotUnavailable('invalid WAL page size')
        order = '<' if magic == 0x377f0682 else '>'
        checksum = _checksum(wal[:24], order)
        if checksum != struct.unpack('>II', wal[24:32]):
            raise SnapshotUnavailable('invalid WAL header checksum')
        committed, frames, pages = 0, [], 0
        for offset in range(32, len(wal) - size - 23, size + 24):
            header, page = wal[offset:offset+24], wal[offset+24:offset+24+size]
            if header[8:16] != wal[16:24]:
                break  # stale tail after WAL reset, never part of this generation
            checksum = _checksum(header[:8] + page, order, checksum)
            if checksum != struct.unpack('>II', header[16:24]):
                if committed:
                    break  # SQLite ends the valid WAL prefix here (e.g. aborted tail).
                raise SnapshotUnavailable('invalid WAL frame checksum')
            number, commit_size = struct.unpack('>II', header[:8])
            if number == 0 or number * size > MAX_SNAPSHOT_BYTES or commit_size * size > MAX_SNAPSHOT_BYTES:
                raise SnapshotUnavailable('WAL exceeds diagnostic size limit')
            frames.append((number, offset+24))
            if commit_size:
                committed, pages = len(frames), commit_size
        if committed:
            length = pages * size
            image.extend(b'\0' * max(0, length - len(image)))
            del image[length:]
            for number, offset in frames[:committed]:
                if number <= pages:
                    image[(number-1)*size:number*size] = wal[offset:offset+size]
    # The private in-memory image has no WAL sidecar; retain all committed pages.
    image[18:20] = b'\x01\x01'
    return image


@contextmanager
def inspection_snapshot(path):
    """Read bytes only; refuse concurrent changes instead of retrying/repairing."""
    source = Path(path).resolve(strict=True)
    wal, journal = Path(str(source) + '-wal'), Path(str(source) + '-journal')
    paths = (source, wal, journal)
    before = [_stamp(p) for p in paths]
    if before[2] and before[2][2]:
        raise SnapshotUnavailable('rollback journal requires owner inspection')
    if sum(s[2] for s in before if s) > MAX_SNAPSHOT_BYTES:
        raise SnapshotUnavailable('snapshot exceeds diagnostic size limit')
    database = source.read_bytes()
    log = wal.read_bytes() if before[1] else b''
    if (before != [_stamp(p) for p in paths] or database != source.read_bytes()
            or log != (wal.read_bytes() if before[1] else b'')
            or before != [_stamp(p) for p in paths]):
        raise SnapshotUnavailable('database changed during inspection; no automatic retry')
    db = sqlite3.connect(':memory:')
    try:
        db.deserialize(bytes(_committed_image(database, log)))
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        yield db
    finally:
        db.close()

"""Logical SQLite image boundaries, without the checkpoint storage format."""
import sqlite3

import pytest

from engine.checkpoint_image import CheckpointImageError, logical_image


@pytest.mark.parametrize("page_size", [512, 4096, 65536])
@pytest.mark.parametrize("wal", [False, True])
def test_logical_image_matches_native_backup(tmp_path, page_size, wal):
    path = tmp_path / "source.db"
    source = sqlite3.connect(path, isolation_level=None, timeout=0)
    source.execute(f"PRAGMA page_size={page_size}")
    source.execute("CREATE TABLE data(id INTEGER PRIMARY KEY, value BLOB)")
    source.execute("INSERT INTO data(value) VALUES (zeroblob(10000))")
    if wal:
        source.execute("PRAGMA journal_mode=WAL")
        source.execute("PRAGMA wal_autocheckpoint=0")
        source.execute("UPDATE data SET value=randomblob(18000)")
        source.execute("INSERT INTO data(value) VALUES (randomblob(150000))")
    expected = source.execute("SELECT * FROM data").fetchall()
    dest = tmp_path / "restored.db"
    with logical_image(path) as (locked, image):
        with dest.open("wb") as out:
            for chunk in image.chunks(1024 * 1024):
                out.write(chunk)
        assert locked.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            source.execute("INSERT INTO data(value) VALUES ('blocked')")
    restored = sqlite3.connect(dest.as_uri() + "?immutable=1", uri=True)
    assert restored.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert restored.execute("SELECT * FROM data").fetchall() == expected
    restored.close()
    source.close()


def test_wal_reset_and_uncommitted_tail(tmp_path):
    path = tmp_path / "source.db"
    source = sqlite3.connect(path, isolation_level=None, timeout=0)
    source.execute("PRAGMA journal_mode=WAL")
    source.execute("CREATE TABLE data(value)")
    for value in range(3):
        source.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        source.execute("INSERT INTO data VALUES (?)", (value,))
        with logical_image(path) as (_, image):
            data = b"".join(image.chunks())
        restored = tmp_path / f"restored{value}.db"
        restored.write_bytes(data)
        db = sqlite3.connect(restored.as_uri() + "?immutable=1", uri=True)
        assert db.execute("SELECT count(*) FROM data").fetchone()[0] == value + 1
        db.close()
    source.execute("BEGIN IMMEDIATE")
    source.execute("INSERT INTO data VALUES (999)")
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        with logical_image(path):
            pytest.fail("capture accepted an active writer")
    source.rollback()
    source.close()


def test_image_resource_bounds_and_missing_source(tmp_path):
    missing = tmp_path / "missing.db"
    with pytest.raises(CheckpointImageError, match="already exist"):
        with logical_image(missing):
            pass
    assert not missing.exists()
    db = sqlite3.connect(missing)
    db.execute("CREATE TABLE data(value)")
    db.close()
    with pytest.raises(CheckpointImageError, match="size exceeds"):
        with logical_image(missing, max_bytes=1):
            pass


def test_wal_ignores_physical_uncommitted_tail(tmp_path):
    path = tmp_path / 'tail.db'
    db = sqlite3.connect(path, isolation_level=None)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE values_table(value)')
    db.execute('INSERT INTO values_table VALUES (123)')
    wal = path.with_name(path.name + '-wal')
    with wal.open('ab') as output:
        output.write(b'uncommitted invalid tail' * 100)
    with logical_image(path) as (_, image):
        raw = b''.join(image.chunks())
    target = tmp_path / 'restored-tail.db'
    target.write_bytes(raw)
    recovered = sqlite3.connect(target.as_uri() + '?immutable=1', uri=True)
    assert recovered.execute('SELECT value FROM values_table').fetchone()[0] == 123
    recovered.close()
    db.close()


def test_frame_budget_refuses_without_publication(tmp_path):
    path = tmp_path / 'frames.db'
    db = sqlite3.connect(path, isolation_level=None)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE data(value)')
    with pytest.raises(CheckpointImageError, match='frame limit'):
        with logical_image(path, max_wal_frames=0):
            pytest.fail('unbounded WAL was accepted')
    db.close()

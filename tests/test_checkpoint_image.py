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


def test_logical_chunk_ranges_match_complete_wal_image(tmp_path):
    from engine.checkpoint_image import logical_image
    path = tmp_path / 'ranges.db'
    db = sqlite3.connect(path, isolation_level=None)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE range_probe(value BLOB)')
    db.execute('INSERT INTO range_probe VALUES(randomblob(?))', (1024 * 1024,))
    with logical_image(path) as (_, image):
        full = list(image.chunks(65536))
        assert list(image.chunks(65536, start=1, stop=4)) == full[1:4]
        assert list(image.chunks(65536, start=len(full))) == []
        # Changing granularity rebuilds a single bounded overlay index.
        assert b''.join(image.chunks(131072)) == b''.join(full)
        assert list(image.chunks(65536, start=2, stop=3)) == full[2:3]
        for bounds in ({'start': -1}, {'stop': len(full) + 1}, {'start': True},
                       {'start': 2, 'stop': 1}):
            with pytest.raises(ValueError, match='range'):
                list(image.chunks(65536, **bounds))
    db.close()


@pytest.mark.skipif(__import__("os").name != "posix", reason="POSIX byte-range locks")
@pytest.mark.parametrize("abort_capture", [False, True])
def test_capture_preserves_live_sqlite_locks(tmp_path, abort_capture):
    """Raw image handles must never cancel another connection's POSIX locks."""
    import json
    import subprocess
    import sys
    path = tmp_path / "locked.db"
    db = sqlite3.connect(path, isolation_level=None)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE lock_probe(value)")
        db.execute("INSERT INTO lock_probe VALUES(1)")
        probe = """import fcntl,json,os,sys
result=[]
for suffix,offset,length in [("",1073741826,510),("-shm",128,1)]:
    fd=os.open(sys.argv[1]+suffix,os.O_RDWR)
    try:
        fcntl.lockf(fd,fcntl.LOCK_EX|fcntl.LOCK_NB,length,offset)
        result.append(False)
    except BlockingIOError:
        result.append(True)
    finally:
        os.close(fd)
print(json.dumps(result))
"""
        def locks():
            return json.loads(subprocess.check_output(
                [sys.executable, "-c", probe, str(path)], text=True))
        assert locks() == [True, True]
        try:
            with logical_image(path) as (_, image):
                assert b"".join(image.chunks()).startswith(b"SQLite format 3")
                if abort_capture:
                    raise RuntimeError("capture cancelled")
        except RuntimeError as exc:
            assert str(exc) == "capture cancelled"
        assert locks() == [True, True]
        db.execute("INSERT INTO lock_probe VALUES(2)")
        assert db.execute("SELECT count(*) FROM lock_probe").fetchone()[0] == 2
    finally:
        db.close()


@pytest.mark.skipif(__import__("os").name != "posix", reason="POSIX WAL-index race")
def test_capture_with_external_reader_does_not_crash_writer(tmp_path):
    """Exercise the former walIndexAppend SIGBUS in an isolated interpreter."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    program = tmp_path / "race.py"
    program.write_text('''import sqlite3,subprocess,sys,time
from pathlib import Path
from engine.checkpoint_image import logical_image

def main():
    path=Path(sys.argv[1])
    db=sqlite3.connect(path,isolation_level=None)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE t(value)')
    db.execute('INSERT INTO t VALUES(1)')
    reader="""import sqlite3,sys,time
for _ in range(1500):
    connection=None
    try:
        connection=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True,timeout=0)
        connection.execute('SELECT count(*) FROM t').fetchone()
    except sqlite3.Error:pass
    finally:
        if connection is not None:connection.close()
    time.sleep(.001)
"""
    child=subprocess.Popen([sys.executable,'-c',reader,str(path)])
    try:
        for i in range(12):
            with logical_image(path) as (_,image):
                list(image.chunks())
            time.sleep(.005)
            db.execute('INSERT INTO t VALUES(?)',(i,))
        assert db.execute('SELECT count(*) FROM t').fetchone()[0]==13
        assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
    finally:
        child.wait(timeout=15)
        db.close()
if __name__=='__main__':main()
''')
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    completed = subprocess.run(
        [sys.executable, "-X", "faulthandler", str(program), str(tmp_path / "race.db")],
        capture_output=True, text=True, timeout=30, env=env)
    assert completed.returncode == 0, completed.stderr

"""Independent SQLite WAL snapshot correctness and strict source preservation."""
import hashlib
from pathlib import Path
import sqlite3
import pytest
from engine.inspection import inspection_snapshot, SnapshotUnavailable


def hashes(path, *, active_writer=False):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in path.parent.iterdir() if p.is_file() and not (active_writer and p.name.endswith('-shm'))}


@pytest.mark.parametrize('page_size', [512, 4096, 65536])
def test_committed_wal_snapshot_matches_sqlite_and_ignores_uncommitted(page_size, tmp_path):
    path = tmp_path / 'wal.db'
    with sqlite3.connect(path) as writer:
        writer.execute(f'PRAGMA page_size={page_size}')
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute('PRAGMA cache_size=1')
        writer.execute('CREATE TABLE facts(id INTEGER PRIMARY KEY, value TEXT)')
        writer.executemany('INSERT INTO facts(value) VALUES (?)', [('x' * 3000,)] * 20)
        writer.commit()
        expected = writer.execute('SELECT * FROM facts ORDER BY id').fetchall()
        writer.execute("UPDATE facts SET value='uncommitted'")
        # Windows denies byte reads of the writer-held SHM lock region.
        # CHECK separately verifies all three hashes on a paused WAL world.
        before = hashes(path, active_writer=True)
        with inspection_snapshot(path) as snapshot:
            assert [tuple(r) for r in snapshot.execute('SELECT * FROM facts ORDER BY id')] == expected
            assert snapshot.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
            with pytest.raises(sqlite3.OperationalError, match='readonly'):
                snapshot.execute('DELETE FROM facts')
        assert hashes(path, active_writer=True) == before
        writer.rollback()
        writer.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        writer.execute("INSERT INTO facts(value) VALUES ('new generation')")
        writer.commit()
        before = hashes(path)
        with inspection_snapshot(path) as snapshot:
            assert snapshot.execute('SELECT COUNT(*) FROM facts').fetchone()[0] == 21
        assert hashes(path) == before


def test_closed_database_and_missing_database_never_create_sidecars(tmp_path):
    path = tmp_path / 'plain.db'
    with sqlite3.connect(path) as writer:
        writer.execute('CREATE TABLE facts(value TEXT)')
        writer.execute("INSERT INTO facts VALUES ('saved')")
    before = hashes(path)
    with inspection_snapshot(path) as snapshot:
        assert snapshot.execute('SELECT value FROM facts').fetchone()[0] == 'saved'
    assert hashes(path) == before
    with pytest.raises(FileNotFoundError):
        with inspection_snapshot(tmp_path / 'missing.db'):
            pass
    assert hashes(path) == before


def test_corrupt_wal_and_changing_source_fail_without_retry(tmp_path, monkeypatch):
    path = tmp_path / 'wal.db'
    with sqlite3.connect(path) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('CREATE TABLE facts(value TEXT)')
        writer.commit()
        original = Path.read_bytes
        reads = []
        def corrupt(source):
            reads.append(source)
            data = original(source)
            if source.suffix == '.db-wal':
                data = data[:60] + bytes([data[60] ^ 0xff]) + data[61:]
            return data
        monkeypatch.setattr(Path, 'read_bytes', corrupt)
        with pytest.raises(SnapshotUnavailable, match='checksum'):
            with inspection_snapshot(path):
                pass
        assert len(reads) == 4
        monkeypatch.setattr(Path, 'read_bytes', original)
        import engine.inspection as inspection
        stamp = inspection._stamp
        calls = []
        def changed(source):
            calls.append(source)
            value = stamp(source)
            return (*value[:3], value[3] + 1, value[4]) if value and len(calls) > 3 else value
        monkeypatch.setattr(inspection, '_stamp', changed)
        with pytest.raises(SnapshotUnavailable, match='changed during inspection'):
            with inspection_snapshot(path):
                pass
        assert len(calls) == 6


def test_rollback_journal_and_oversize_are_unavailable(tmp_path, monkeypatch):
    path = tmp_path / 'plain.db'
    with sqlite3.connect(path) as writer:
        writer.execute('CREATE TABLE facts(value TEXT)')
    journal = Path(str(path) + '-journal')
    journal.write_bytes(b'pending transaction')
    with pytest.raises(SnapshotUnavailable, match='rollback journal'):
        with inspection_snapshot(path):
            pass
    journal.unlink()
    monkeypatch.setattr('engine.inspection.MAX_SNAPSHOT_BYTES', 8)
    with pytest.raises(SnapshotUnavailable, match='size limit'):
        with inspection_snapshot(path):
            pass

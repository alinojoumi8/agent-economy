from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile

import pytest

from engine.storage_archive import archive_run, copy_run, restore_archive
from engine.storage_cli import inspect_run
from engine.store import open_read_only_connection
from .recorded_replay_fixture import SOURCE_RUN_ID, restore_recorded_source


def logical_rows(path, table):
    connection = open_read_only_connection(str(path))
    try:
        return [tuple(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY id")]
    finally:
        connection.close()


def test_packed_plain_and_archive_roundtrip_preserves_every_record(tmp_path):
    source = restore_recorded_source(tmp_path / f"{SOURCE_RUN_ID}.db")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    packed, plain, restored = [tmp_path / name for name in ("packed.db", "plain.db", "restored.db")]
    copy_run(source, packed, encoding="packed", min_free_bytes=0)
    assert inspect_run(packed)["packed_requests"] > 0
    copy_run(packed, plain, encoding="plain", min_free_bytes=0)
    assert inspect_run(plain)["packed_requests"] == 0
    archive = tmp_path / "run.ae.zip"
    assert archive_run(packed, archive, min_free_bytes=0)["verified"]
    assert restore_archive(archive, restored, min_free_bytes=0)["verified"]
    with sqlite3.connect(source) as connection:
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    # All tables, including long-term memories, account history, phase and
    # PRNG metadata. Sorting tuples avoids assuming every table has an id.
    for path in (packed, plain, restored):
        a, b = open_read_only_connection(str(source)), open_read_only_connection(str(path))
        try:
            for table in tables:
                quoted = '"' + table.replace('"', '""') + '"'
                assert [tuple(r) for r in a.execute(f"SELECT * FROM {quoted}")] == [
                    tuple(r) for r in b.execute(f"SELECT * FROM {quoted}")], table
        finally:
            a.close()
            b.close()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert archive.stat().st_size < source.stat().st_size
    with pytest.raises(FileExistsError):
        restore_archive(archive, restored, min_free_bytes=0)


def test_invalid_archive_cannot_publish_database(tmp_path):
    source = restore_recorded_source(tmp_path / "source.db")
    archive = tmp_path / "run.zip"
    archive_run(source, archive, min_free_bytes=0)
    with zipfile.ZipFile(archive) as original:
        manifest = json.loads(original.read("manifest.json"))
        manifest["database_sha256"] = "0" * 64
        body = original.read("run.db")
    bad = tmp_path / "corrupt.zip"
    with zipfile.ZipFile(bad, "w") as output:
        output.writestr("manifest.json", json.dumps(manifest))
        output.writestr("run.db", body)
    destination = tmp_path / "rejected.db"
    with pytest.raises(ValueError, match="checksum"):
        restore_archive(bad, destination, min_free_bytes=0)
    assert not destination.exists()
    with pytest.raises(ValueError, match="size"):
        restore_archive(archive, destination, max_database_bytes=1, min_free_bytes=0)

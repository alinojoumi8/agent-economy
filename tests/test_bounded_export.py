"""Resource refusal and independent source/Parquet verification regressions."""
from __future__ import annotations

import hashlib
import json
import sqlite3

import duckdb
import pytest

import research.export_bundle as exporter
from research.export_bundle import ExportBundleError, ExportLimits, ExportResourceLimitError
from research.export_storage import ExportResources
from research.hashing import schema_inventory_sha256


@pytest.fixture
def source(tmp_path):
    connection = sqlite3.connect(tmp_path / "source.db")
    connection.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY, owner INTEGER, text TEXT, value REAL, data BLOB, private TEXT, ignored TEXT)")
    connection.execute("CREATE TABLE no_key(value TEXT)")
    connection.execute("CREATE TABLE empty(id INTEGER PRIMARY KEY, value REAL)")
    connection.executemany("INSERT INTO sample VALUES(?,?,?,?,?,?,?)", [
        (1, 7, "e\u0301 / 東京 / 🙂", -0.0, b"\x00\xff", "private-canary", "excluded"),
        (2, 7, None, 1.5, b"", None, "excluded"),
        (3, None, "large:" + "x" * 1000, None, None, "secret", None),
    ])
    connection.executemany("INSERT INTO no_key VALUES(?)", [("z",), (None,), ("a",), ("a",)])
    connection.commit()
    contract = {
        "id": "hash-contract-v1", "schema_version": 1,
        "schema_inventory_sha256": schema_inventory_sha256(connection),
        "authoritative_tables": ["sample", "empty"], "derived_tables": ["no_key"],
        "excluded_tables": [], "excluded_columns": {"sample": ["ignored"]},
        "json_columns": [], "json_suffixes": [],
        "default_export_redactions": {"sample": ["private"]},
        "default_export_pseudonym_columns": {"sample": ["owner"]},
    }
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    yield connection, contract_path
    connection.close()


def _export(source, tmp_path, **options):
    connection, contract = source
    return exporter.export_bundle(connection, tmp_path / "exports", contract_path=contract, **options)


def _reseal(path, mutate=lambda manifest: None):
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mutate(manifest)
    schema = {key: manifest[key] for key in ("contract_id", "schema_inventory_sha256", "tables")}
    (path / "bundle-schema.json").write_text(json.dumps(schema), encoding="utf-8")
    for name in manifest["files"]:
        raw = (path / name).read_bytes()
        manifest["files"][name] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    manifest.pop("bundle_sha256")
    manifest["bundle_sha256"] = hashlib.sha256(json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def _rewrite_table(bundle, select):
    target = bundle / "sample.parquet"
    replacement = bundle / "changed.parquet"
    with duckdb.connect() as connection:
        connection.execute("CREATE TABLE original AS SELECT * FROM read_parquet(?)", [str(target)])
        escaped = str(replacement).replace("'", "''")
        connection.execute(f"COPY ({select}) TO '{escaped}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    replacement.replace(target)
    _reseal(bundle)


def test_row_and_byte_batches_preserve_identity_privacy_duplicates_and_transactions(source, tmp_path):
    connection, contract = source
    before = connection.getlimit(sqlite3.SQLITE_LIMIT_LENGTH)
    connection.execute("UPDATE sample SET value=2.5 WHERE id=2")
    stats = {}
    limits = ExportLimits(max_batch_rows=1, max_batch_bytes=4096, max_record_bytes=2048)
    bundle = _export(source, tmp_path, limits=limits, stats=stats)
    assert connection.in_transaction and connection.getlimit(sqlite3.SQLITE_LIMIT_LENGTH) == before
    assert stats["status"] == "complete" and stats["peak_batch_rows"] == 1
    assert stats["peak_batch_bytes"] <= 4096 and stats["validated_rows"] == 7
    assert stats["validated_tables"] == 3
    assert _export(source, tmp_path) == bundle
    assert [path.name for path in bundle.parent.iterdir()] == [bundle.name]
    exporter.validate_bundle(bundle, database=connection, contract_path=contract, limits=limits)
    with duckdb.connect() as reader:
        assert reader.execute("SELECT * FROM read_parquet(?)", [str(bundle / "no_key.parquet")]).fetchall() == [(None,), ("a",), ("a",), ("z",)]
        rows = reader.execute("SELECT text,value,data,private,owner FROM read_parquet(?)", [str(bundle / "sample.parquet")]).fetchall()
    assert rows[0][0] == "e\u0301 / 東京 / 🙂" and rows[0][2] == b"\x00\xff"
    assert rows[1][1] == 2.5 and all(row[3] is None for row in rows)
    assert rows[0][4] == rows[1][4] and rows[0][4] != 7 and rows[2][4] is None
    connection.rollback()
    assert connection.execute("SELECT value FROM sample WHERE id=2").fetchone()[0] == 1.5


@pytest.mark.parametrize("select,match", [
    ("SELECT * REPLACE ('altered' AS text) FROM original", "source content mismatch"),
    ("SELECT * FROM original WHERE id<>2", "row count mismatch"),
    ("SELECT * REPLACE (CAST(id AS VARCHAR) AS id) FROM original", "source schema/privacy mismatch"),
    ("SELECT * REPLACE (CAST(42 AS BIGINT) AS owner) FROM original", "source content mismatch"),
    ("SELECT * REPLACE ('revealed' AS private) FROM original", "redaction mismatch"),
])
def test_independent_source_reader_rejects_parquet_even_after_manifest_resealed(source, tmp_path, select, match):
    bundle = _export(source, tmp_path)
    _rewrite_table(bundle, select)
    with pytest.raises(ExportBundleError, match=match):
        exporter.validate_bundle(bundle, database=source[0], contract_path=source[1])


@pytest.mark.parametrize("mutation,match", [
    (lambda m: m["tables"]["sample"]["redactions"].update(private=1), "privacy count mismatch"),
    (lambda m: m["tables"]["sample"].update(row_count=4), "Parquet row count mismatch"),
    (lambda m: (m["tables"].pop("empty"), m["files"].pop("empty.parquet")), "classified table coverage mismatch"),
])
def test_independent_reader_rejects_resealed_receipt_and_coverage_changes(source, tmp_path, mutation, match):
    bundle = _export(source, tmp_path)
    _reseal(bundle, mutation)
    with pytest.raises(ExportBundleError, match=match):
        exporter.validate_bundle(bundle, database=source[0], contract_path=source[1])


def test_writer_transformation_bug_cannot_publish_verified_manifest(source, tmp_path, monkeypatch):
    real = exporter._pseudonym
    monkeypatch.setattr(exporter, "_pseudonym", lambda salt, value: real(salt, value) + 1)
    with pytest.raises(ExportBundleError, match="source content mismatch"):
        _export(source, tmp_path)
    assert list((tmp_path / "exports").iterdir()) == []


def test_byte_limit_flushes_before_row_limit(source, tmp_path):
    source[0].executemany("INSERT INTO sample(id,text) VALUES(?,?)",
                          ((index, "x" * 1024) for index in range(4, 36)))
    stats = {}
    _export(source, tmp_path, limits=ExportLimits(
        max_batch_rows=100, max_batch_bytes=2048, max_record_bytes=2048), stats=stats)
    assert stats["peak_batch_rows"] < 100
    assert stats["peak_batch_bytes"] <= 2048 and stats["batches"] >= 32


def test_reusing_a_bundle_counts_staged_and_existing_files_together(source, tmp_path):
    stats = {}
    bundle = _export(source, tmp_path, stats=stats)
    manifest_before = (bundle / "manifest.json").read_bytes()
    cap = stats["peak_work_bytes"] + 1
    with pytest.raises(ExportResourceLimitError, match="working-disk allowance"):
        _export(source, tmp_path, limits=ExportLimits(max_temp_bytes=cap, max_work_bytes=cap))
    assert (bundle / "manifest.json").read_bytes() == manifest_before
    assert list(bundle.parent.iterdir()) == [bundle]


@pytest.mark.parametrize("limits,match", [
    (ExportLimits(max_batch_bytes=8192, max_record_bytes=8192), "record-byte allowance"),
    (ExportLimits(min_free_bytes=2**62), "free-space reserve"),
    (ExportLimits(max_temp_bytes=128, max_work_bytes=128), "working-disk allowance"),
    (ExportLimits(duckdb_memory_bytes=1), "memory/spill allowance"),
])
def test_resource_refusal_preserves_source_settings_and_publishes_nothing(source, tmp_path, limits, match):
    connection, _ = source
    if match == "record-byte allowance":
        connection.execute("UPDATE sample SET text=? WHERE id=3", ["x" * 10000])
        connection.commit()
    before_limit = connection.getlimit(sqlite3.SQLITE_LIMIT_LENGTH)
    before_bytes = (tmp_path / "source.db").read_bytes()
    with pytest.raises(ExportResourceLimitError, match=match):
        _export(source, tmp_path, limits=limits)
    assert not connection.in_transaction
    assert connection.getlimit(sqlite3.SQLITE_LIMIT_LENGTH) == before_limit
    assert (tmp_path / "source.db").read_bytes() == before_bytes
    assert list((tmp_path / "exports").iterdir()) == []


def test_spill_and_elapsed_refusal_clean_only_owned_scratch(tmp_path, monkeypatch):
    keeper = tmp_path / "keep.txt"
    keeper.write_text("preserve", encoding="utf-8")
    with pytest.raises(ExportResourceLimitError, match="temporary-disk allowance"):
        with ExportResources(tmp_path, ExportLimits(max_temp_bytes=128)) as resources:
            (resources.scratch / "spill").write_bytes(b"x" * 129)
            resources.check(full=True)
    clock = [0.0]
    monkeypatch.setattr("research.export_storage.time.monotonic", lambda: clock[0])
    with pytest.raises(ExportResourceLimitError, match="elapsed-time allowance"):
        with ExportResources(tmp_path, ExportLimits(max_elapsed_seconds=1)) as resources:
            clock[0] = 2.0
            resources.check()
    assert list(tmp_path.iterdir()) == [keeper]


def test_one_read_snapshot_survives_an_external_commit(source, tmp_path):
    connection, contract = source
    connection.execute("PRAGMA journal_mode=WAL")
    changed = False
    def concurrent_commit(name, context):
        nonlocal changed
        if name == "after_table" and not changed:
            with sqlite3.connect(tmp_path / "source.db") as writer:
                writer.execute("UPDATE sample SET text='next snapshot' WHERE id=1")
            changed = True
    bundle = _export(source, tmp_path, fault_hook=concurrent_commit)
    assert changed and not connection.in_transaction
    with pytest.raises(ExportBundleError, match="source hash mismatch"):
        exporter.validate_bundle(bundle, database=connection, contract_path=contract)
    with duckdb.connect() as reader:
        assert reader.execute("SELECT text FROM read_parquet(?) WHERE id=1", [str(bundle / "sample.parquet")]).fetchone()[0] == "e\u0301 / 東京 / 🙂"


@pytest.mark.parametrize("values", [
    {"max_batch_rows": 0}, {"max_batch_rows": True}, {"max_record_bytes": 0},
    {"max_elapsed_seconds": float("nan")}, {"min_free_bytes": -1},
    {"max_batch_bytes": 4}, {"max_work_bytes": 4},
])
def test_invalid_resource_limits_fail_before_work(values):
    with pytest.raises(ValueError):
        ExportLimits(**values)

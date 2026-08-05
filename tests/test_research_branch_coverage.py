"""Branch-complete hash-contract and deterministic export tests."""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3

import pytest

import research.export_bundle as export_module
from research.export_bundle import (
    ExportBundleError,
    _duckdb_type,
    _export_table,
    _sha256_file,
    _table_spec,
    export_bundle,
    validate_bundle,
)
from research.hashing import (
    HashContractError,
    _included_columns,
    _is_json_column,
    canonical_projection_hash,
    canonical_value,
    classified_tables,
    load_hash_contract,
    schema_inventory,
    schema_inventory_sha256,
    table_digest,
    verify_hash_contract,
)


def _simple_database():
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE sample (id INTEGER PRIMARY KEY, payload_json TEXT, value REAL, data BLOB)")
    connection.execute("CREATE TABLE no_key (value TEXT)")
    connection.execute(
        "INSERT INTO sample VALUES (1, ?, 1.5, ?)",
        (json.dumps({"b": [None, True, 2, 1.5], "a": "e\u0301"}), b"blob"))
    contract = {
        "id": "hash-contract-v1",
        "schema_version": 1,
        "schema_inventory_sha256": schema_inventory_sha256(connection),
        "authoritative_tables": ["sample"],
        "derived_tables": ["no_key"],
        "excluded_tables": [],
        "excluded_columns": {},
        "json_columns": [],
        "json_suffixes": ["_json"],
        "default_export_redactions": {},
        "default_export_pseudonym_columns": {},
    }
    return connection, contract


def test_hash_contract_loader_connection_and_classification_failures(tmp_path):
    invalid_path = tmp_path / "contract.json"
    invalid_path.write_text(json.dumps({"id": "wrong"}), encoding="utf-8")
    with pytest.raises(HashContractError, match="unsupported hash contract"):
        load_hash_contract(invalid_path)
    with pytest.raises(TypeError, match="sqlite3"):
        schema_inventory(object())

    connection, contract = _simple_database()
    try:
        overlap = {**contract, "derived_tables": ["no_key", "sample"]}
        with pytest.raises(HashContractError, match="more than once"):
            verify_hash_contract(connection, overlap)
        stale = {**contract, "excluded_tables": ["ghost"]}
        with pytest.raises(HashContractError, match="tables are absent"):
            verify_hash_contract(connection, stale)
        excluded_unknown = {**contract, "excluded_columns": {"sample": ["ghost"]}}
        with pytest.raises(HashContractError, match="excluded columns absent"):
            verify_hash_contract(connection, excluded_unknown)
        assert verify_hash_contract(connection, contract)["contract_id"] == "hash-contract-v1"
        with pytest.raises(HashContractError, match="table is unclassified"):
            table_digest(connection, "ghost", contract=contract)
        assert classified_tables(contract) == ["no_key", "sample"]
        assert classified_tables(contract, ("derived",)) == ["no_key"]
    finally:
        connection.close()


def test_typed_canonical_values_cover_every_supported_and_rejected_shape():
    projection = {
        "none": None,
        "bool": True,
        "integer": 2,
        "float": 1.5,
        "text": "e\u0301",
        "array": [1, False],
        "object": {2: "two", "1": "one"},
    }
    assert len(canonical_projection_hash(projection)) == 64
    for value in (float("inf"), float("-inf"), float("nan")):
        with pytest.raises(HashContractError, match="non-finite"):
            canonical_projection_hash(value)
        with pytest.raises(HashContractError, match="non-finite"):
            canonical_value(value)
    with pytest.raises(HashContractError, match="unsupported JSON"):
        canonical_projection_hash({1, 2})

    assert canonical_value(None)
    assert canonical_value(2)
    assert canonical_value(1.5)
    assert canonical_value(b"blob") == canonical_value(bytearray(b"blob"))
    assert canonical_value(memoryview(b"blob")) == canonical_value(b"blob")
    assert canonical_value("text")
    assert canonical_value(json.dumps(projection), parse_json=True)
    with pytest.raises(HashContractError, match="non-text"):
        canonical_value({}, parse_json=True)
    with pytest.raises(HashContractError, match="invalid JSON"):
        canonical_value("{", parse_json=True)
    with pytest.raises(HashContractError, match="unsupported SQLite"):
        canonical_value(object())


def test_json_column_and_row_order_fallbacks():
    connection, contract = _simple_database()
    try:
        inventory = {item["table"]: item for item in schema_inventory(connection)}
        assert _is_json_column("sample", "payload_json", contract)
        explicit = {**contract, "json_suffixes": [], "json_columns": ["sample.value"]}
        assert _is_json_column("sample", "value", explicit)
        assert not _is_json_column("sample", "data", explicit)
        sample_columns, sample_order = _included_columns(
            "sample", inventory["sample"], contract)
        assert sample_columns == ["id", "payload_json", "value", "data"]
        assert sample_order == ["id"]
        no_key_columns, no_key_order = _included_columns(
            "no_key", inventory["no_key"], contract)
        assert no_key_order == no_key_columns == ["value"]
        assert table_digest(connection, "sample", contract=contract)["row_count"] == 1
        assert table_digest(connection, "no_key", contract=contract)["row_count"] == 0
    finally:
        connection.close()


def test_export_helpers_cover_types_empty_rows_redaction_and_pseudonym(tmp_path):
    assert [_duckdb_type(value) for value in (
        "INTEGER", "REAL", "FLOAT", "DOUBLE", "BLOB", "TEXT", "")
    ] == ["BIGINT", "DOUBLE", "DOUBLE", "DOUBLE", "BLOB", "VARCHAR", "VARCHAR"]
    connection, contract = _simple_database()
    try:
        inventory = {item["table"]: item for item in schema_inventory(connection)}
        assert _table_spec("sample", inventory["sample"], contract)["row_order"] == ["id"]
        assert _table_spec("no_key", inventory["no_key"], contract)["row_order"] == ["value"]
        empty = _export_table(
            connection, table="no_key", spec=_table_spec(
                "no_key", inventory["no_key"], contract), contract=contract,
            pseudonym_salt="salt", destination=tmp_path / "empty.parquet")
        assert empty["row_count"] == 0

        private_contract = {
            **contract,
            "default_export_redactions": {"sample": ["payload_json"]},
            "default_export_pseudonym_columns": {"sample": ["id", "value"]},
        }
        receipt = _export_table(
            connection, table="sample", spec=_table_spec(
                "sample", inventory["sample"], private_contract),
            contract=private_contract, pseudonym_salt="salt",
            destination=tmp_path / "sample.parquet")
        assert receipt["redactions"]["payload_json"] == 1
        assert receipt["pseudonyms"] == {"id": 1, "value": 1}

        connection.execute("INSERT INTO sample VALUES (2, NULL, NULL, NULL)")
        null_receipt = _export_table(
            connection, table="sample", spec=_table_spec(
                "sample", inventory["sample"], private_contract),
            contract=private_contract, pseudonym_salt="salt",
            destination=tmp_path / "sample-null.parquet")
        assert null_receipt["redactions"]["payload_json"] == 1
        assert null_receipt["pseudonyms"] == {"id": 2, "value": 1}
    finally:
        connection.close()


def test_bundle_validation_missing_invalid_and_size_mismatch(economy, tmp_path):
    bundle = export_bundle(economy.store, tmp_path / "exports")

    invalid = tmp_path / "invalid"
    invalid.mkdir()
    (invalid / "manifest.json").write_text("{", encoding="utf-8")
    with pytest.raises(ExportBundleError, match="manifest is invalid"):
        validate_bundle(invalid)

    missing = tmp_path / "missing"
    shutil.copytree(bundle, missing)
    missing_manifest = json.loads((missing / "manifest.json").read_text(encoding="utf-8"))
    missing_name = next(iter(missing_manifest["files"]))
    (missing / missing_name).unlink()
    with pytest.raises(ExportBundleError, match="file is absent"):
        validate_bundle(missing)

    wrong_size = tmp_path / "wrong-size"
    shutil.copytree(bundle, wrong_size)
    manifest_path = wrong_size / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    filename = next(iter(manifest["files"]))
    target = wrong_size / filename
    target.write_bytes(target.read_bytes() + b"size")
    manifest["files"][filename]["sha256"] = _sha256_file(target)
    core = dict(manifest)
    core.pop("bundle_sha256")
    manifest["bundle_sha256"] = hashlib.sha256(
        json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8")).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8")
    with pytest.raises(ExportBundleError, match="file size mismatch"):
        validate_bundle(wrong_size)


def test_content_address_collision_fails_closed(economy, tmp_path, monkeypatch):
    root = tmp_path / "exports"
    bundle = export_bundle(economy.store, root)
    assert bundle.is_dir()
    monkeypatch.setattr(
        export_module, "validate_bundle", lambda _path: {"bundle_sha256": "wrong"})
    with pytest.raises(ExportBundleError, match="path conflicts"):
        export_bundle(economy.store, root)


def test_export_connection_rejects_non_sqlite():
    with pytest.raises(TypeError, match="sqlite3"):
        export_bundle(object(), ".")

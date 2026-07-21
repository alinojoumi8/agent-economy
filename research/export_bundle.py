"""Deterministic, content-addressed Parquet export bundles."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Callable

from .hashing import (
    canonical_hashes,
    classified_tables,
    load_hash_contract,
    schema_inventory,
    verify_hash_contract,
)


FaultHook = Callable[[str, dict], None]


class ExportBundleError(RuntimeError):
    """Raised when a research bundle is incomplete, corrupt, or unsupported."""


def _connection(database: Any) -> sqlite3.Connection:
    connection = getattr(database, "conn", database)
    if not isinstance(connection, sqlite3.Connection):
        raise TypeError("database must be a sqlite3 connection or Store")
    return connection


def _quote(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _duckdb_type(sqlite_type: str) -> str:
    declared = str(sqlite_type or "").upper()
    if "INT" in declared:
        return "BIGINT"
    if any(token in declared for token in ("REAL", "FLOA", "DOUB")):
        return "DOUBLE"
    if "BLOB" in declared:
        return "BLOB"
    return "VARCHAR"


def _pseudonym(salt: str, value: Any) -> int:
    digest = hashlib.sha256(f"{salt}:{value}".encode("utf-8")).hexdigest()
    return int(digest[:15], 16)


def _table_spec(table: str, inventory: dict, contract: dict) -> dict:
    excluded = set(map(str, contract.get("excluded_columns", {}).get(table, [])))
    columns = [
        column for column in inventory["columns"]
        if str(column["name"]) not in excluded
    ]
    key_columns = [
        column for column in sorted(
            columns, key=lambda item: int(item["primary_key_ordinal"]) or 10_000)
        if int(column["primary_key_ordinal"]) > 0
    ]
    return {
        "columns": columns,
        "row_order": [str(column["name"]) for column in (key_columns or columns)],
    }


def _export_table(
    sqlite_connection: sqlite3.Connection,
    *,
    table: str,
    spec: dict,
    contract: dict,
    pseudonym_salt: str,
    destination: Path,
) -> dict:
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover - dependency gate is exercised separately
        raise ExportBundleError(
            "DuckDB is required for deterministic Parquet export") from exc

    column_names = [str(column["name"]) for column in spec["columns"]]
    redacted_columns = set(
        map(str, contract.get("default_export_redactions", {}).get(table, [])))
    pseudonym_columns = set(
        map(str, contract.get("default_export_pseudonym_columns", {}).get(table, [])))
    select = ",".join(_quote(column) for column in column_names)
    order = ",".join(_quote(column) for column in spec["row_order"])
    source_rows = sqlite_connection.execute(
        f"SELECT {select} FROM {_quote(table)} ORDER BY {order}")
    rows = []
    redaction_counts = {column: 0 for column in sorted(redacted_columns)}
    pseudonym_counts = {column: 0 for column in sorted(pseudonym_columns)}
    for source in source_rows:
        row = []
        for index, column in enumerate(column_names):
            value = source[index]
            if column in redacted_columns:
                if value is not None:
                    redaction_counts[column] += 1
                value = None
            elif column in pseudonym_columns and value is not None:
                pseudonym_counts[column] += 1
                value = _pseudonym(pseudonym_salt, value)
            row.append(value)
        rows.append(tuple(row))

    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute("SET threads=1")
        connection.execute("SET preserve_insertion_order=true")
        declarations = ",".join(
            f"{_quote(column['name'])} {_duckdb_type(column['type'])}"
            for column in spec["columns"]
        )
        connection.execute(f"CREATE TABLE export_rows ({declarations})")
        if rows:
            placeholders = ",".join("?" for _ in column_names)
            connection.executemany(
                f"INSERT INTO export_rows VALUES ({placeholders})", rows)
        escaped_path = str(destination).replace("'", "''")
        connection.execute(
            f"COPY export_rows TO '{escaped_path}' "
            "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)")
    finally:
        connection.close()
    return {
        "row_count": len(rows),
        "columns": column_names,
        "row_order": spec["row_order"],
        "redactions": redaction_counts,
        "pseudonyms": pseudonym_counts,
    }


def export_bundle(
    database: Any,
    output_root: str | Path,
    *,
    contract_path: str | Path | None = None,
    fault_hook: FaultHook | None = None,
) -> Path:
    """Stage every Parquet table and publish a deterministic manifest last."""
    sqlite_connection = _connection(database)
    contract = load_hash_contract(contract_path)
    verify_hash_contract(sqlite_connection, contract)
    hashes = canonical_hashes(sqlite_connection, contract)
    output_root = Path(output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".world-os-export-", dir=output_root))
    published: Path | None = None
    try:
        inventory = {item["table"]: item for item in schema_inventory(sqlite_connection)}
        files = {}
        table_receipts = {}
        pseudonym_salt = hashes["authoritative_sha256"]
        for table in classified_tables(contract):
            destination = stage / f"{table}.parquet"
            receipt = _export_table(
                sqlite_connection,
                table=table,
                spec=_table_spec(table, inventory[table], contract),
                contract=contract,
                pseudonym_salt=pseudonym_salt,
                destination=destination,
            )
            files[destination.name] = {
                "sha256": _sha256_file(destination),
                "bytes": destination.stat().st_size,
            }
            table_receipts[table] = receipt
            if fault_hook is not None:
                fault_hook("after_table", {"table": table, "stage": str(stage)})

        schema_path = stage / "bundle-schema.json"
        schema_payload = {
            "contract_id": contract["id"],
            "schema_inventory_sha256": hashes["schema_inventory_sha256"],
            "tables": table_receipts,
        }
        schema_path.write_text(_canonical_json(schema_payload) + "\n", encoding="utf-8")
        files[schema_path.name] = {
            "sha256": _sha256_file(schema_path),
            "bytes": schema_path.stat().st_size,
        }
        manifest_core = {
            "format": "world-os-research-bundle-v1",
            "contract_id": contract["id"],
            "schema_version": int(contract["schema_version"]),
            "schema_inventory_sha256": hashes["schema_inventory_sha256"],
            "authoritative_sha256": hashes["authoritative_sha256"],
            "derived_sha256": hashes["derived_sha256"],
            "privacy_profile": "default-redacted-pseudonymous-v1",
            "files": dict(sorted(files.items())),
            "tables": table_receipts,
        }
        bundle_hash = hashlib.sha256(
            _canonical_json(manifest_core).encode("utf-8")).hexdigest()
        manifest = {**manifest_core, "bundle_sha256": bundle_hash}
        if fault_hook is not None:
            fault_hook("before_publish", {"bundle_sha256": bundle_hash, "stage": str(stage)})
        published = output_root / f"bundle-{bundle_hash}"
        if published.exists():
            existing = validate_bundle(published)
            if existing["bundle_sha256"] != bundle_hash:
                raise ExportBundleError("content-addressed bundle path conflicts")
            return published
        os.replace(stage, published)
        if fault_hook is not None:
            fault_hook(
                "after_publish_before_manifest",
                {"bundle_sha256": bundle_hash, "bundle": str(published)},
            )
        manifest_temp = published / ".manifest.json.tmp"
        manifest_temp.write_text(_canonical_json(manifest) + "\n", encoding="utf-8")
        os.replace(manifest_temp, published / "manifest.json")
        return published
    except Exception:
        if stage.exists() and stage.parent == output_root:
            shutil.rmtree(stage)
        raise


def validate_bundle(path: str | Path) -> dict:
    path = Path(path).resolve()
    manifest_path = path / "manifest.json"
    if not manifest_path.is_file():
        raise ExportBundleError("research bundle is incomplete: manifest is absent")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExportBundleError("research bundle manifest is invalid") from exc
    bundle_hash = str(manifest.get("bundle_sha256") or "")
    core = dict(manifest)
    core.pop("bundle_sha256", None)
    expected = hashlib.sha256(_canonical_json(core).encode("utf-8")).hexdigest()
    if bundle_hash != expected:
        raise ExportBundleError("research bundle manifest hash mismatch")
    for filename, expected_file in manifest.get("files", {}).items():
        file_path = path / str(filename)
        if not file_path.is_file():
            raise ExportBundleError(f"research bundle file is absent: {filename}")
        if _sha256_file(file_path) != str(expected_file["sha256"]):
            raise ExportBundleError(f"research bundle file hash mismatch: {filename}")
        if file_path.stat().st_size != int(expected_file["bytes"]):
            raise ExportBundleError(f"research bundle file size mismatch: {filename}")
    return manifest

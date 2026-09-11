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

from .export_storage import ExportBundleError, ExportLimits, ExportResourceLimitError, ExportResources
from .export_validation import validate_parquet_tables
from .hashing import (
    _contract_for_database,
    canonical_hashes,
    classified_tables,
    load_hash_contract,
    schema_inventory,
    verify_hash_contract,
)


FaultHook = Callable[[str, dict], None]


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
    limits: ExportLimits | None = None,
    stats: dict | None = None,
    resources: ExportResources | None = None,
) -> dict:
    if resources is None:
        with ExportResources(destination.parent, limits, stats) as owned:
            owned.output = destination
            with owned.sqlite_source(sqlite_connection):
                return _export_table(
                    sqlite_connection, table=table, spec=spec, contract=contract,
                    pseudonym_salt=pseudonym_salt, destination=destination, resources=owned)

    column_names = [str(column["name"]) for column in spec["columns"]]
    redacted_columns = set(
        map(str, contract.get("default_export_redactions", {}).get(table, [])))
    pseudonym_columns = set(
        map(str, contract.get("default_export_pseudonym_columns", {}).get(table, [])))
    select = ",".join(_quote(column) for column in column_names)
    order = ",".join(_quote(column) for column in spec["row_order"])
    source_rows = sqlite_connection.execute(
        f"SELECT {select} FROM {_quote(table)} ORDER BY {order}")
    redaction_counts = {column: 0 for column in sorted(redacted_columns)}
    pseudonym_counts = {column: 0 for column in sorted(pseudonym_columns)}
    row_count = 0
    with resources.duckdb() as connection:
        declarations = ",".join(
            f"{_quote(column['name'])} {_duckdb_type(column['type'])}"
            for column in spec["columns"]
        )
        connection.execute(f"CREATE TABLE export_rows ({declarations})")
        placeholders = ",".join("?" for _ in column_names)
        insert = f"INSERT INTO export_rows VALUES ({placeholders})"
        rows = []
        batch_bytes = 0
        for source in source_rows:
            resources.record_size(source)
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
            size = resources.record_size(row)
            if rows and (len(rows) >= resources.limits.max_batch_rows
                         or batch_bytes + size > resources.limits.max_batch_bytes):
                resources.batch(len(rows), batch_bytes)
                connection.executemany(insert, rows)
                rows.clear()
                batch_bytes = 0
            rows.append(tuple(row))
            batch_bytes += size
            row_count += 1
            resources.check()
        if rows:
            resources.batch(len(rows), batch_bytes)
            connection.executemany(insert, rows)
            rows.clear()
        escaped_path = str(destination).replace("'", "''")
        connection.execute(
            f"COPY export_rows TO '{escaped_path}' "
            "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)")
    return {
        "row_count": row_count,
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
    limits: ExportLimits | None = None,
    scratch_dir: str | Path | None = None,
    stats: dict | None = None,
) -> Path:
    """Bound buffers, read back against one source snapshot, publish manifest last.

    Resource statistics are operational and are excluded from bundle identity.
    The caller owns the source connection; its transaction and record limit are
    preserved. Use a closed immutable source for scientific campaign exports.
    """
    sqlite_connection = _connection(database)
    output_root = Path(output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    with ExportResources(Path(scratch_dir) if scratch_dir is not None else output_root,
                         limits, stats) as resources:
        with resources.sqlite_source(sqlite_connection):
            return _build_bundle(sqlite_connection, output_root, contract_path=contract_path,
                                 fault_hook=fault_hook, resources=resources)


def _build_bundle(sqlite_connection, output_root, *, contract_path, fault_hook, resources):
    contract = load_hash_contract(contract_path)
    if contract_path is None:
        selected = _contract_for_database(sqlite_connection)
        if selected["id"] in {"hash-contract-v3", "hash-contract-v4", "hash-contract-v5", "hash-contract-v6", "hash-contract-v7", "hash-contract-v8"}:
            contract = selected
    verify_hash_contract(sqlite_connection, contract)
    hashes = canonical_hashes(sqlite_connection, contract)
    resources.check(full=True)
    stage = Path(tempfile.mkdtemp(prefix=".world-os-export-", dir=output_root))
    resources.output = stage
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
                resources=resources,
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
        _validate_files(stage, files, resources)
        validate_parquet_tables(stage, table_receipts, resources, source=sqlite_connection,
                                contract=contract, pseudonym_salt=pseudonym_salt)
        resources.check(full=True)
        published = output_root / f"bundle-{bundle_hash}"
        if published.exists():
            resources.existing_output = published
            resources.check(full=True)
            existing_manifest = published / "manifest.json"
            if not existing_manifest.is_file():
                raise ExportBundleError("research bundle is incomplete: manifest is absent")
            existing = _read_json(existing_manifest, resources)
            _validate_manifest(published, existing, resources)
            if existing != manifest:
                raise ExportBundleError("content-addressed bundle path conflicts")
            # Identical file hashes bind this bundle to the already-read-back
            # stage. Reuse the same deadline and disk accounting throughout.
            resources.check(full=True)
            return published
        os.replace(stage, published)
        resources.output = published
        if fault_hook is not None:
            fault_hook(
                "after_publish_before_manifest",
                {"bundle_sha256": bundle_hash, "bundle": str(published)},
            )
        manifest_temp = published / ".manifest.json.tmp"
        manifest_temp.write_text(_canonical_json(manifest) + "\n", encoding="utf-8")
        resources.check(full=True)
        os.replace(manifest_temp, published / "manifest.json")
        return published
    finally:
        if stage.exists():
            resolved = stage.resolve(strict=True)
            if resolved.parent != output_root or not resolved.name.startswith(".world-os-export-"):
                raise ExportBundleError("export staging ownership changed; cleanup refused")
            shutil.rmtree(resolved)


def _validate_files(path: Path, files: dict, resources: ExportResources):
    for filename, expected_file in files.items():
        if (not isinstance(filename, str) or Path(filename).name != filename
                or "/" in filename or "\\" in filename or ":" in filename):
            raise ExportBundleError("research bundle file name is invalid")
        if (not isinstance(expected_file, dict)
                or type(expected_file.get("bytes")) is not int or expected_file["bytes"] < 0
                or not isinstance(expected_file.get("sha256"), str)):
            raise ExportBundleError("research bundle file receipt is invalid")
        file_path = path / filename
        if file_path.resolve().parent != path or file_path.is_symlink():
            raise ExportBundleError("research bundle file escapes its directory")
        if not file_path.is_file():
            raise ExportBundleError(f"research bundle file is absent: {filename}")
        if _sha256_file(file_path) != str(expected_file["sha256"]):
            raise ExportBundleError(f"research bundle file hash mismatch: {filename}")
        if file_path.stat().st_size != int(expected_file["bytes"]):
            raise ExportBundleError(f"research bundle file size mismatch: {filename}")
        resources.check(full=True)


def _read_json(path: Path, resources: ExportResources) -> dict:
    if path.stat().st_size > resources.limits.max_record_bytes:
        raise ExportResourceLimitError("export metadata record-byte allowance exceeded")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExportBundleError("research bundle manifest is invalid") from exc
    if not isinstance(value, dict):
        raise ExportBundleError("research bundle manifest is invalid")
    return value


def validate_bundle(path: str | Path, *, database: Any = None,
                    contract_path: str | Path | None = None,
                    limits: ExportLimits | None = None,
                    scratch_dir: str | Path | None = None, stats: dict | None = None) -> dict:
    """Validate files and Parquet; supplying a source also verifies its exact export.

    Without a source, v1 bundles contain no declared column types or transformed
    content hashes: only their recorded schema names, counts and redactions can
    be independently checked. A self-consistent bundle is not authenticated.
    """
    path = Path(path).resolve()
    manifest_path = path / "manifest.json"
    if not manifest_path.is_file():
        raise ExportBundleError("research bundle is incomplete: manifest is absent")
    with ExportResources(Path(scratch_dir) if scratch_dir is not None else path.parent,
                         limits, stats) as resources:
        resources.output = path
        resources.check(full=True)
        manifest = _read_json(manifest_path, resources)
        _validate_manifest(path, manifest, resources)
        if database is None:
            validate_parquet_tables(path, manifest["tables"], resources)
        else:
            connection = _connection(database)
            with resources.sqlite_source(connection):
                if contract_path is None:
                    contract_id = manifest.get("contract_id")
                    if contract_id not in {f"hash-contract-v{version}" for version in range(1, 9)}:
                        raise ExportBundleError("research bundle hash contract is unsupported")
                    contract_path = Path(__file__).with_name(f"{contract_id}.json")
                contract = load_hash_contract(contract_path)
                if manifest.get("schema_version") != contract["schema_version"]:
                    raise ExportBundleError("research bundle source schema version mismatch")
                hashes = canonical_hashes(connection, contract)
                for key in ("contract_id", "schema_inventory_sha256", "authoritative_sha256", "derived_sha256"):
                    if manifest.get(key) != hashes[key]:
                        raise ExportBundleError(f"research bundle source hash mismatch: {key}")
                validate_parquet_tables(path, manifest["tables"], resources, source=connection,
                                        contract=contract, pseudonym_salt=hashes["authoritative_sha256"])
        resources.check(full=True)
        return manifest


def _validate_manifest(path, manifest, resources):
    bundle_hash = str(manifest.get("bundle_sha256") or "")
    core = dict(manifest)
    core.pop("bundle_sha256", None)
    expected = hashlib.sha256(_canonical_json(core).encode("utf-8")).hexdigest()
    if bundle_hash != expected:
        raise ExportBundleError("research bundle manifest hash mismatch")
    files, tables = manifest.get("files"), manifest.get("tables")
    if (manifest.get("format") != "world-os-research-bundle-v1"
            or manifest.get("privacy_profile") != "default-redacted-pseudonymous-v1"
            or not isinstance(files, dict) or not isinstance(tables, dict) or not tables):
        raise ExportBundleError("research bundle manifest is invalid")
    if set(files) != {"bundle-schema.json", *(f"{table}.parquet" for table in tables)}:
        raise ExportBundleError("research bundle file/table coverage mismatch")
    _validate_files(path, files, resources)
    schema = _read_json(path / "bundle-schema.json", resources)
    expected_schema = {key: manifest[key] for key in ("contract_id", "schema_inventory_sha256", "tables")}
    if schema != expected_schema:
        raise ExportBundleError("research bundle schema receipt mismatch")

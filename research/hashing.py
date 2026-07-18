"""Typed canonical hashing for the World OS hash-contract-v1 boundary."""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import struct
import unicodedata
from pathlib import Path
from typing import Any, Iterable


CONTRACT_PATH = Path(__file__).with_name("hash-contract-v1.json")


class HashContractError(RuntimeError):
    """Raised when storage no longer matches the frozen hash classification."""


def load_hash_contract(path: str | Path | None = None) -> dict:
    contract_path = Path(path) if path is not None else CONTRACT_PATH
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if contract.get("id") != "hash-contract-v1":
        raise HashContractError("unsupported hash contract")
    return contract


def _connection(database: Any) -> sqlite3.Connection:
    connection = getattr(database, "conn", database)
    if not isinstance(connection, sqlite3.Connection):
        raise TypeError("database must be a sqlite3 connection or Store")
    return connection


def _quote(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def _tables(connection: sqlite3.Connection) -> list[str]:
    return [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]


def schema_inventory(database: Any) -> list[dict]:
    """Describe every table/column including declared key ordinals."""
    connection = _connection(database)
    inventory = []
    for table in _tables(connection):
        columns = []
        for row in connection.execute(f"PRAGMA table_info({_quote(table)})"):
            columns.append({
                "name": str(row[1]),
                "type": str(row[2] or "").upper(),
                "not_null": int(row[3]),
                "default": None if row[4] is None else str(row[4]),
                "primary_key_ordinal": int(row[5]),
            })
        inventory.append({"table": table, "columns": columns})
    return inventory


def schema_inventory_sha256(database: Any) -> str:
    payload = json.dumps(
        schema_inventory(database), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def verify_hash_contract(database: Any, contract: dict | None = None) -> dict:
    """Fail closed when any table or column is not covered by the manifest."""
    contract = contract or load_hash_contract()
    classified = {
        classification: set(map(str, contract[f"{classification}_tables"]))
        for classification in ("authoritative", "derived", "excluded")
    }
    overlaps = (
        (classified["authoritative"] & classified["derived"])
        | (classified["authoritative"] & classified["excluded"])
        | (classified["derived"] & classified["excluded"])
    )
    if overlaps:
        raise HashContractError(
            "hash contract classifies tables more than once: " + ",".join(sorted(overlaps)))
    discovered = set(_tables(_connection(database)))
    declared = set().union(*classified.values())
    missing = sorted(discovered - declared)
    stale = sorted(declared - discovered)
    if missing:
        raise HashContractError("unclassified storage tables: " + ",".join(missing))
    if stale:
        raise HashContractError("hash contract tables are absent: " + ",".join(stale))
    inventory_hash = schema_inventory_sha256(database)
    if inventory_hash != str(contract.get("schema_inventory_sha256")):
        raise HashContractError(
            "unclassified storage column or schema change: " + inventory_hash)
    inventory = {item["table"]: item for item in schema_inventory(database)}
    for table, columns in contract.get("excluded_columns", {}).items():
        discovered_columns = {item["name"] for item in inventory[str(table)]["columns"]}
        unknown = sorted(set(map(str, columns)) - discovered_columns)
        if unknown:
            raise HashContractError(
                f"excluded columns absent from {table}: " + ",".join(unknown))
    return {
        "contract_id": str(contract["id"]),
        "schema_inventory_sha256": inventory_hash,
        "tables": {key: sorted(value) for key, value in classified.items()},
    }


def _typed_json(value: Any) -> Any:
    if value is None:
        return ["null"]
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, int):
        return ["integer", str(value)]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise HashContractError("non-finite float cannot be canonicalized")
        return ["float", value.hex()]
    if isinstance(value, str):
        return ["text", unicodedata.normalize("NFC", value)]
    if isinstance(value, list):
        return ["array", [_typed_json(item) for item in value]]
    if isinstance(value, dict):
        return [
            "object",
            [[unicodedata.normalize("NFC", str(key)), _typed_json(value[key])]
             for key in sorted(value, key=str)],
        ]
    raise HashContractError(f"unsupported JSON value type: {type(value).__name__}")


def canonical_value(value: Any, *, parse_json: bool = False) -> bytes:
    if parse_json and value is not None:
        if not isinstance(value, str):
            raise HashContractError("declared JSON column contains non-text data")
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise HashContractError("declared JSON column contains invalid JSON") from exc
        typed = ["json", _typed_json(value)]
    elif value is None:
        typed = ["null"]
    elif isinstance(value, int):
        typed = ["integer", str(value)]
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise HashContractError("non-finite float cannot be canonicalized")
        typed = ["float", value.hex()]
    elif isinstance(value, (bytes, bytearray, memoryview)):
        typed = ["blob", bytes(value).hex()]
    elif isinstance(value, str):
        typed = ["text", unicodedata.normalize("NFC", value)]
    else:
        raise HashContractError(f"unsupported SQLite value type: {type(value).__name__}")
    return json.dumps(
        typed, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")


def _json_columns(contract: dict) -> set[str]:
    return set(map(str, contract.get("json_columns", [])))


def _is_json_column(table: str, column: str, contract: dict) -> bool:
    return (
        any(column.endswith(str(suffix)) for suffix in contract.get("json_suffixes", []))
        or f"{table}.{column}" in _json_columns(contract)
    )


def _length_prefix(value: bytes) -> bytes:
    return struct.pack(">Q", len(value)) + value


def _included_columns(
    table: str, inventory: dict, contract: dict,
) -> tuple[list[str], list[str]]:
    excluded = set(map(str, contract.get("excluded_columns", {}).get(table, [])))
    columns = [
        str(column["name"]) for column in inventory["columns"]
        if str(column["name"]) not in excluded
    ]
    primary_key = [
        str(column["name"])
        for column in sorted(
            inventory["columns"], key=lambda item: int(item["primary_key_ordinal"]) or 10_000)
        if int(column["primary_key_ordinal"]) > 0
        and str(column["name"]) in columns
    ]
    return columns, primary_key or columns


def table_digest(
    database: Any, table: str, *, contract: dict | None = None,
) -> dict:
    connection = _connection(database)
    contract = contract or load_hash_contract()
    verify_hash_contract(connection, contract)
    classification = next(
        (name for name in ("authoritative", "derived", "excluded")
         if table in contract[f"{name}_tables"]),
        None,
    )
    if classification is None:
        raise HashContractError(f"table is unclassified: {table}")
    inventory = next(
        item for item in schema_inventory(connection) if item["table"] == table)
    columns, row_order = _included_columns(table, inventory, contract)
    digest = hashlib.sha256()
    header = json.dumps(
        {"table": table, "columns": columns, "row_order": row_order},
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    digest.update(_length_prefix(header))
    select = ",".join(_quote(column) for column in columns)
    ordering = ",".join(_quote(column) for column in row_order)
    rows = connection.execute(
        f"SELECT {select} FROM {_quote(table)} ORDER BY {ordering}")
    row_count = 0
    for row in rows:
        encoded = bytearray()
        for index, column in enumerate(columns):
            encoded.extend(_length_prefix(canonical_value(
                row[index], parse_json=_is_json_column(table, column, contract))))
        digest.update(_length_prefix(bytes(encoded)))
        row_count += 1
    return {
        "table": table,
        "classification": classification,
        "columns": columns,
        "row_order": row_order,
        "row_count": row_count,
        "sha256": digest.hexdigest(),
    }


def canonical_hashes(database: Any, contract: dict | None = None) -> dict:
    connection = _connection(database)
    contract = contract or load_hash_contract()
    verification = verify_hash_contract(connection, contract)
    table_results = {}
    aggregate_results = {}
    for classification in ("authoritative", "derived"):
        aggregate = hashlib.sha256()
        for table in sorted(contract[f"{classification}_tables"]):
            result = table_digest(connection, table, contract=contract)
            table_results[table] = result
            aggregate.update(_length_prefix(table.encode("utf-8")))
            aggregate.update(bytes.fromhex(result["sha256"]))
        aggregate_results[classification] = aggregate.hexdigest()
    return {
        "contract_id": contract["id"],
        "schema_inventory_sha256": verification["schema_inventory_sha256"],
        "authoritative_sha256": aggregate_results["authoritative"],
        "derived_sha256": aggregate_results["derived"],
        "tables": table_results,
    }


def canonical_projection_hash(envelope: Any) -> str:
    payload = json.dumps(
        _typed_json(envelope), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def classified_tables(
    contract: dict, classifications: Iterable[str] = ("authoritative", "derived"),
) -> list[str]:
    return sorted({
        str(table)
        for classification in classifications
        for table in contract[f"{classification}_tables"]
    })

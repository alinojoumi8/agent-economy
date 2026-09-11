"""Read exported Parquet independently of the writer's row transformation."""
from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3

from .export_storage import ExportBundleError, ExportResources
from .hashing import classified_tables, schema_inventory


def _quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _source_columns(item: dict, excluded: list[str]):
    columns = [column for column in item["columns"] if column["name"] not in excluded]
    types = []
    for column in columns:
        declared = str(column["type"] or "").upper()
        if "INT" in declared:
            types.append("BIGINT")
        elif any(token in declared for token in ("REAL", "FLOA", "DOUB")):
            types.append("DOUBLE")
        elif "BLOB" in declared:
            types.append("BLOB")
        else:
            types.append("VARCHAR")
    keys = sorted((column for column in columns if column["primary_key_ordinal"]),
                  key=lambda column: column["primary_key_ordinal"])
    return ([column["name"] for column in columns], types,
            [column["name"] for column in keys or columns])


def _cast_expected(values, types, cursor):
    """Fast path for typed SQLite values; preserve legacy dynamic-type casts."""
    result = []
    for value, kind in zip(values, types):
        if value is None:
            result.append(None)
        elif kind == "DOUBLE" and type(value) in (int, float):
            result.append(float(value))
        elif ((kind == "BIGINT" and type(value) is int)
              or (kind == "VARCHAR" and type(value) is str)
              or (kind == "BLOB" and type(value) is bytes)):
            result.append(value)
        else:
            casts = ",".join(f"CAST(? AS {kind})" for kind in types)
            return cursor.execute(f"SELECT {casts}", list(values)).fetchone()
    return tuple(result)


def validate_parquet_tables(
    path: Path, receipts: dict, resources: ExportResources, *,
    source: sqlite3.Connection | None = None, contract: dict | None = None,
    pseudonym_salt: str | None = None,
):
    inventory = None
    if source is not None:
        assert contract is not None and pseudonym_salt is not None
        if set(receipts) != set(classified_tables(contract)):
            raise ExportBundleError("research bundle classified table coverage mismatch")
        inventory = {item["table"]: item for item in schema_inventory(source)}
    with resources.duckdb() as connection:
        cast_cursor = connection.cursor()
        try:
            for table, receipt in sorted(receipts.items()):
                resources.check(full=True)
                if not isinstance(receipt, dict):
                    raise ExportBundleError(f"research bundle table receipt is invalid: {table}")
                columns = receipt.get("columns")
                count = receipt.get("row_count")
                if (not isinstance(columns, list) or not columns
                        or any(not isinstance(name, str) for name in columns)
                        or len(set(columns)) != len(columns)
                        or type(count) is not int or count < 0):
                    raise ExportBundleError(f"research bundle table receipt is invalid: {table}")
                redactions = receipt.get("redactions", {})
                pseudonyms = receipt.get("pseudonyms", {})
                for counters in (redactions, pseudonyms):
                    if (not isinstance(counters, dict) or not set(counters) <= set(columns)
                            or any(type(n) is not int or n < 0 or n > count for n in counters.values())):
                        raise ExportBundleError(f"research bundle privacy receipt is invalid: {table}")
                actual = connection.execute(
                    "SELECT * FROM read_parquet(?, hive_partitioning=false)",
                    [str(path / f"{table}.parquet")],
                )
                names = [str(item[0]) for item in actual.description]
                types = [str(item[1]) for item in actual.description]
                if names != columns or not set(types) <= {"BIGINT", "DOUBLE", "VARCHAR", "BLOB"}:
                    raise ExportBundleError(f"research bundle Parquet schema mismatch: {table}")
                actual_count = cast_cursor.execute(
                    "SELECT count(*) FROM read_parquet(?, hive_partitioning=false)",
                    [str(path / f"{table}.parquet")],
                ).fetchone()[0]
                if actual_count != count:
                    raise ExportBundleError(f"research bundle Parquet row count mismatch: {table}")
                expected_rows = None
                if inventory is not None:
                    assert contract is not None and source is not None
                    expected_names, expected_types, order = _source_columns(
                        inventory[table], contract.get("excluded_columns", {}).get(table, []))
                    expected_redactions = set(contract.get("default_export_redactions", {}).get(table, []))
                    expected_pseudonyms = set(contract.get("default_export_pseudonym_columns", {}).get(table, []))
                    if (names != expected_names or types != expected_types
                            or receipt.get("row_order") != order
                            or set(redactions) != expected_redactions
                            or set(pseudonyms) != expected_pseudonyms):
                        raise ExportBundleError(f"research bundle source schema/privacy mismatch: {table}")
                    expected_rows = source.execute(
                        f"SELECT {','.join(map(_quote, names))} FROM {_quote(table)} "
                        f"ORDER BY {','.join(map(_quote, order))}")
                redaction_counts = dict.fromkeys(redactions, 0)
                pseudonym_counts = dict.fromkeys(pseudonyms, 0)
                row_count = 0
                while (row := actual.fetchone()) is not None:
                    resources.record_size(row)
                    resources.check()
                    row_count += 1
                    for index, column in enumerate(names):
                        if column in redactions and row[index] is not None:
                            raise ExportBundleError(f"research bundle redaction mismatch: {table}.{column}")
                    if expected_rows is not None:
                        original = expected_rows.fetchone()
                        if original is None:
                            raise ExportBundleError(f"research bundle source row count mismatch: {table}")
                        resources.record_size(original)
                        transformed = []
                        for index, column in enumerate(names):
                            value = original[index]
                            if column in redactions:
                                redaction_counts[column] += value is not None
                                value = None
                            elif column in pseudonyms and value is not None:
                                pseudonym_counts[column] += 1
                                raw = (str(pseudonym_salt) + ":" + str(value)).encode("utf-8")
                                value = int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") >> 4
                            transformed.append(value)
                        expected = _cast_expected(transformed, types, cast_cursor)
                        if row != expected:
                            raise ExportBundleError(f"research bundle source content mismatch: {table}, row {row_count}")
                if row_count != count:
                    raise ExportBundleError(f"research bundle Parquet row count mismatch: {table}")
                if expected_rows is not None:
                    if expected_rows.fetchone() is not None:
                        raise ExportBundleError(f"research bundle source row count mismatch: {table}")
                    if redaction_counts != redactions or pseudonym_counts != pseudonyms:
                        raise ExportBundleError(f"research bundle source privacy count mismatch: {table}")
                resources.stats["validated_tables"] += 1
                resources.stats["validated_rows"] += row_count
        finally:
            cast_cursor.close()

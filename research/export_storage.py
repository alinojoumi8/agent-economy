"""Bounded buffers and owned scratch space for research exports.

Limits are cooperative, except SQLite record and DuckDB buffer/spill limits.
Campaign callers must also supervise process RSS, elapsed time and disk usage.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import math
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time


class ExportBundleError(RuntimeError):
    """A research bundle is incomplete, corrupt, or unsupported."""


class ExportResourceLimitError(ExportBundleError):
    """A declared resource allowance was exhausted; no bundle was verified."""


@dataclass(frozen=True)
class ExportLimits:
    max_batch_rows: int = 512
    max_batch_bytes: int = 8 * 1024**2
    max_record_bytes: int = 8 * 1024**2
    duckdb_memory_bytes: int = 256 * 1024**2
    max_temp_bytes: int = 8 * 1024**3
    max_work_bytes: int = 16 * 1024**3
    min_free_bytes: int = 0
    max_elapsed_seconds: float = 600.0

    def __post_init__(self):
        for name, value in asdict(self).items():
            if name == "max_elapsed_seconds":
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not math.isfinite(value) or value <= 0):
                    raise ValueError(f"{name} must be finite and positive")
            elif type(value) is not int or value < (0 if name == "min_free_bytes" else 1):
                raise ValueError(f"{name} must be a valid integer allowance")
        if self.max_record_bytes > self.max_batch_bytes:
            raise ValueError("max_record_bytes cannot exceed max_batch_bytes")
        if self.max_temp_bytes > self.max_work_bytes:
            raise ValueError("max_temp_bytes cannot exceed max_work_bytes")


class ExportResources:
    def __init__(self, parent: Path, limits: ExportLimits | None = None,
                 stats: dict | None = None):
        self.parent = Path(parent).resolve(strict=True)
        self.limits = limits or ExportLimits()
        self.stats = stats if stats is not None else {}
        self.started = time.monotonic()
        self.last_disk_check = 0.0
        self.scratch: Path | None = None
        self.output: Path | None = None
        self.existing_output: Path | None = None
        self.stats.update(limits=asdict(self.limits), peak_batch_rows=0,
                          peak_batch_bytes=0, peak_record_bytes=0,
                          peak_temp_bytes=0, peak_work_bytes=0,
                          batches=0, validated_tables=0, validated_rows=0)

    def __enter__(self):
        self.check(full=True)
        self.scratch = Path(tempfile.mkdtemp(prefix=".world-os-export-work-", dir=self.parent))
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.stats["elapsed_seconds"] = time.monotonic() - self.started
        self.stats["status"] = "complete" if exc_type is None else "failed"
        if self.scratch is not None and self.scratch.exists():
            resolved = self.scratch.resolve(strict=True)
            if resolved.parent != self.parent or not resolved.name.startswith(".world-os-export-work-"):
                raise ExportBundleError("export scratch ownership changed; cleanup refused")
            shutil.rmtree(resolved)

    @staticmethod
    def _bytes(path: Path | None) -> int:
        if path is None or not path.exists():
            return 0
        if path.is_file():
            return path.stat().st_size
        return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())

    def check(self, *, full: bool = False):
        now = time.monotonic()
        if now - self.started > self.limits.max_elapsed_seconds:
            raise ExportResourceLimitError("export elapsed-time allowance exceeded")
        if not full and now - self.last_disk_check < 0.5:
            return
        self.last_disk_check = now
        locations = {self.parent}
        if self.output is not None:
            locations.add(self.output.parent)
        free = min(shutil.disk_usage(path).free for path in locations)
        self.stats["minimum_free_bytes"] = min(self.stats.get("minimum_free_bytes", free), free)
        if free < self.limits.min_free_bytes:
            raise ExportResourceLimitError("export free-space reserve would be violated")
        temporary = self._bytes(self.scratch)
        total = temporary + self._bytes(self.output) + self._bytes(self.existing_output)
        self.stats["peak_temp_bytes"] = max(self.stats["peak_temp_bytes"], temporary)
        self.stats["peak_work_bytes"] = max(self.stats["peak_work_bytes"], total)
        if temporary > self.limits.max_temp_bytes:
            raise ExportResourceLimitError("export temporary-disk allowance exceeded")
        if total > self.limits.max_work_bytes:
            raise ExportResourceLimitError("export working-disk allowance exceeded")

    def record_size(self, row) -> int:
        size = 0
        for value in row:
            if isinstance(value, str):
                size += len(value.encode("utf-8"))
            elif isinstance(value, (bytes, bytearray, memoryview)):
                size += len(value)
            else:
                size += 8
            size += 9  # type/length accounting, including nulls and empty values
        if size > self.limits.max_record_bytes:
            raise ExportResourceLimitError("export record-byte allowance exceeded")
        self.stats["peak_record_bytes"] = max(self.stats["peak_record_bytes"], size)
        return size

    def batch(self, rows: int, size: int):
        if rows > self.limits.max_batch_rows or size > self.limits.max_batch_bytes:
            raise ExportResourceLimitError("export batch allowance exceeded")
        self.stats["batches"] += 1
        self.stats["peak_batch_rows"] = max(self.stats["peak_batch_rows"], rows)
        self.stats["peak_batch_bytes"] = max(self.stats["peak_batch_bytes"], size)
        self.check(full=True)

    @contextmanager
    def sqlite_source(self, connection: sqlite3.Connection):
        previous = connection.getlimit(sqlite3.SQLITE_LIMIT_LENGTH)
        owned_transaction = not connection.in_transaction
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, min(previous, self.limits.max_record_bytes))
        try:
            if owned_transaction:
                connection.execute("BEGIN")
            yield
        except sqlite3.DataError as exc:
            if getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_TOOBIG:
                raise ExportResourceLimitError("export SQLite record-byte allowance exceeded") from exc
            raise
        finally:
            if owned_transaction and connection.in_transaction:
                connection.rollback()
            connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, previous)

    @contextmanager
    def duckdb(self):
        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover - dependency gate
            raise ExportBundleError("DuckDB is required for deterministic Parquet export") from exc
        assert self.scratch is not None
        connection = None
        try:
            connection = duckdb.connect(database=":memory:", config={
                "threads": "1", "preserve_insertion_order": "true",
                "memory_limit": f"{self.limits.duckdb_memory_bytes} B",
                "temp_directory": str(self.scratch),
                "max_temp_directory_size": f"{self.limits.max_temp_bytes} B",
                "autoinstall_known_extensions": "false",
            })
            yield connection
            self.check(full=True)
        except duckdb.OutOfMemoryException as exc:
            raise ExportResourceLimitError("DuckDB export memory/spill allowance exceeded") from exc
        except duckdb.Error as exc:
            raise ExportBundleError("research bundle Parquet operation failed") from exc
        finally:
            if connection is not None:
                connection.close()

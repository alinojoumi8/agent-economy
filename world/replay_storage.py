"""Bounded scratch storage for exact replay proofs; never modifies a source."""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping, MutableMapping
from contextlib import contextmanager
from dataclasses import dataclass
import json
import math
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
from typing import Any, Callable


class ReplayResourceLimitError(RuntimeError):
    """Verification stopped without producing an exactness verdict."""


@dataclass(frozen=True)
class ReplayVerificationLimits:
    max_record_bytes: int = 64 * 1024**2
    max_cache_bytes: int = 8 * 1024**2
    max_cache_entries: int = 1024
    max_scratch_bytes: int = 8 * 1024**3
    sqlite_cache_bytes: int = 2 * 1024**2
    min_free_bytes: int = 0
    max_elapsed_seconds: float = 600.0

    def __post_init__(self):
        for name in ("max_record_bytes", "max_scratch_bytes", "sqlite_cache_bytes"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        for name in ("max_cache_bytes", "max_cache_entries", "min_free_bytes"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        if self.max_scratch_bytes < 64 * 1024:
            raise ValueError("max_scratch_bytes must allow at least 64 KiB")
        if (isinstance(self.max_elapsed_seconds, bool)
                or not math.isfinite(self.max_elapsed_seconds)
                or self.max_elapsed_seconds <= 0):
            raise ValueError("max_elapsed_seconds must be finite and positive")


class ReplayStorage:
    """One owned SQLite file, bounded byte cache, and byte-ordered multiset."""

    def __init__(self, *, limits=None, scratch_dir=None, stats=None):
        self.limits = limits or ReplayVerificationLimits()
        self.stats = {} if stats is None else stats
        self.stats.update(peak_scratch_bytes=0, largest_record_bytes=0,
                          peak_cache_bytes=0, peak_cache_entries=0,
                          reference_reads=0, cache_hits=0)
        self.started = time.monotonic()
        self.directory = None
        self.connection = None
        self.page_size = 4096
        self.cache = OrderedDict()
        self.cache_bytes = 0
        self.operations = 0
        self.expanded_reference_bytes = 0
        self.parent = Path(scratch_dir or tempfile.gettempdir()).resolve()

    def __enter__(self):
        if not self.parent.is_dir():
            raise ValueError("scratch_dir must be an existing directory")
        self.check(force=True)
        self.directory = Path(tempfile.mkdtemp(prefix="ae-rv-", dir=self.parent))
        try:
            self.connection = sqlite3.connect(
                self.directory / "proof.sqlite3", isolation_level=None)
            for pragma in ("PRAGMA journal_mode=OFF", "PRAGMA synchronous=OFF",
                           "PRAGMA mmap_size=0"):
                self.connection.execute(pragma)
            kib = max(1, self.limits.sqlite_cache_bytes // 1024)
            self.connection.execute(f"PRAGMA cache_size=-{kib}")
            self.page_size = self.connection.execute("PRAGMA page_size").fetchone()[0]
            pages = self.limits.max_scratch_bytes // self.page_size
            self.connection.execute(f"PRAGMA max_page_count={pages}")
            self.execute("CREATE TABLE refs(id INTEGER PRIMARY KEY, value BLOB NOT NULL)")
            # BLOB primary-key order equals Python bytes order. The ordinal
            # retains duplicates without a second payload copy or a temp sort.
            self.execute("CREATE TABLE ordered_records("
                         "value BLOB NOT NULL, ordinal INTEGER NOT NULL,"
                         "PRIMARY KEY(value,ordinal)) WITHOUT ROWID")
            self.check(force=True)
            return self
        except BaseException:
            self.close()
            raise

    def __exit__(self, *_exc):
        self.close()

    def close(self):
        try:
            if self.connection is not None:
                self.sample_size()
        finally:
            if self.connection is not None:
                self.connection.close()
                self.connection = None
            self.cache.clear()
            self.cache_bytes = 0
            if self.directory is not None:
                target = self.directory
                # Only this newly created scratch child is disposable.
                if (target.is_symlink() or target.resolve().parent != self.parent
                        or not target.name.startswith("ae-rv-")):
                    raise RuntimeError("scratch ownership changed; retained directory")
                shutil.rmtree(target)
                self.directory = None
            self.stats["elapsed_seconds"] = time.monotonic() - self.started

    def sample_size(self):
        pages = self.connection.execute("PRAGMA page_count").fetchone()[0]
        size = pages * self.page_size
        self.stats["peak_scratch_bytes"] = max(self.stats["peak_scratch_bytes"], size)
        if size > self.limits.max_scratch_bytes:
            raise ReplayResourceLimitError("replay scratch byte limit exceeded")

    def check(self, *, force=False):
        self.operations += 1
        if not force and self.operations % 128:
            return
        if time.monotonic() - self.started > self.limits.max_elapsed_seconds:
            raise ReplayResourceLimitError("replay verification time limit exceeded")
        if shutil.disk_usage(self.parent).free < self.limits.min_free_bytes:
            raise ReplayResourceLimitError("replay free-space reserve reached")
        if self.connection is not None:
            self.sample_size()

    def execute(self, sql, parameters=()):
        self.check()
        try:
            return self.connection.execute(sql, parameters)
        except sqlite3.Error as exc:
            if getattr(exc, "sqlite_errorcode", None) in (
                    sqlite3.SQLITE_FULL, sqlite3.SQLITE_TOOBIG):
                raise ReplayResourceLimitError(
                    "replay scratch capacity or record limit exceeded") from exc
            raise

    def encode(self, value, *, exact):
        # Strict UTF-8 bytes are the existing proof contract. Internal
        # references use escaped ASCII and allow non-finite values so an
        # ignored operational row is not newly rejected during indexing.
        encoder = json.JSONEncoder(
            sort_keys=exact, separators=(",", ":"), ensure_ascii=not exact,
            allow_nan=not exact)
        result = bytearray()
        self.check()
        next_check = 1024**2
        for chunk in encoder.iterencode(value):
            encoded = chunk.encode("utf-8")
            if len(result) + len(encoded) > self.limits.max_record_bytes:
                raise ReplayResourceLimitError("canonical replay record is too large")
            result.extend(encoded)
            if len(result) >= next_check:
                self.check(force=True)
                next_check = len(result) + 1024**2
        self.stats["largest_record_bytes"] = max(
            self.stats["largest_record_bytes"], len(result))
        return bytes(result)

    def begin_record(self):
        self.expanded_reference_bytes = 0
        self.check()

    def decode_reference(self, encoded):
        # Charge every expansion, including a repeated cached reference,
        # before allocating another Python object tree. An encoded output
        # limit alone would reject only after all copies had been built.
        self.expanded_reference_bytes += len(encoded)
        if self.expanded_reference_bytes > self.limits.max_record_bytes:
            raise ReplayResourceLimitError("expanded replay reference record is too large")
        self.check()
        return json.loads(encoded)

    def cached(self, key):
        value = self.cache.get(key)
        if value is not None:
            self.cache.move_to_end(key)
            self.stats["cache_hits"] += 1
        return value

    def remember(self, key, value):
        prior = self.cache.pop(key, None)
        if prior is not None:
            self.cache_bytes -= len(prior)
        if (len(value) > self.limits.max_cache_bytes
                or not self.limits.max_cache_entries):
            return
        while self.cache and (
                self.cache_bytes + len(value) > self.limits.max_cache_bytes
                or len(self.cache) >= self.limits.max_cache_entries):
            _, evicted = self.cache.popitem(last=False)
            self.cache_bytes -= len(evicted)
        self.cache[key] = value
        self.cache_bytes += len(value)
        self.stats["peak_cache_bytes"] = max(
            self.stats["peak_cache_bytes"], self.cache_bytes)
        self.stats["peak_cache_entries"] = max(
            self.stats["peak_cache_entries"], len(self.cache))

    @contextmanager
    def read_limits(self, connection):
        previous = connection.getlimit(sqlite3.SQLITE_LIMIT_LENGTH)
        connection.setlimit(
            sqlite3.SQLITE_LIMIT_LENGTH, min(previous, self.limits.max_record_bytes))
        try:
            yield
        except sqlite3.DataError as exc:
            if getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_TOOBIG:
                raise ReplayResourceLimitError("recorded replay row is too large") from exc
            raise
        finally:
            connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, previous)

    def reset(self):
        self.check(force=True)
        self.execute("DELETE FROM refs")
        self.clear_sort()
        self.cache.clear()
        self.cache_bytes = 0

    def clear_sort(self):
        self.execute("DELETE FROM ordered_records")

    def add_sorted(self, value, ordinal):
        if len(value) > self.limits.max_record_bytes:
            raise ReplayResourceLimitError("canonical replay record is too large")
        self.execute("INSERT INTO ordered_records VALUES (?,?)", (value, ordinal))

    def sorted_records(self):
        for row in self.execute(
                "SELECT value FROM ordered_records ORDER BY value,ordinal"):
            self.check()
            yield row[0]


def _sqlite_key(key):
    return isinstance(key, int) and -(2**63) <= key < 2**63


class CallReferences(Mapping):
    """Resolve call contents on demand, retaining only bounded serialized bytes."""

    def __init__(self, connection, columns, canonicalize: Callable, storage):
        self.connection = connection
        self.columns = columns
        self.canonicalize = canonicalize
        self.storage = storage

    def __getitem__(self, key):
        if not self.columns or not _sqlite_key(key):
            raise KeyError(key)
        self.storage.check()
        encoded = self.storage.cached(("call", key))
        if encoded is None:
            row = self.connection.execute(
                "SELECT * FROM llm_calls WHERE id=?", (key,)).fetchone()
            if row is None:
                raise KeyError(key)
            value = {"llm_call": {
                column: self.canonicalize(column, row[column])
                for column in self.columns}}
            encoded = self.storage.encode(value, exact=False)
            self.storage.remember(("call", key), encoded)
            self.storage.stats["reference_reads"] += 1
        return self.storage.decode_reference(encoded)

    def __iter__(self):
        if self.columns:
            for row in self.connection.execute("SELECT id FROM llm_calls ORDER BY id"):
                yield row[0]

    def __len__(self):
        return self.connection.execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0] if self.columns else 0


class EventReferences(MutableMapping):
    """An incremental backward-reference index in the owned scratch file."""

    def __init__(self, storage):
        self.storage = storage

    def __getitem__(self, key):
        if not _sqlite_key(key):
            raise KeyError(key)
        encoded = self.storage.cached(("event", key))
        if encoded is None:
            row = self.storage.execute("SELECT value FROM refs WHERE id=?", (key,)).fetchone()
            if row is None:
                raise KeyError(key)
            encoded = row[0]
            self.storage.remember(("event", key), encoded)
            self.storage.stats["reference_reads"] += 1
        return self.storage.decode_reference(encoded)

    def __setitem__(self, key, value):
        encoded = self.storage.encode(value, exact=False)
        self.storage.execute("INSERT OR REPLACE INTO refs VALUES (?,?)", (key, encoded))
        self.storage.remember(("event", key), encoded)

    def __delitem__(self, key):
        if not _sqlite_key(key):
            raise KeyError(key)
        if not self.storage.execute("DELETE FROM refs WHERE id=?", (key,)).rowcount:
            raise KeyError(key)
        encoded = self.storage.cache.pop(("event", key), None)
        if encoded is not None:
            self.storage.cache_bytes -= len(encoded)

    def __iter__(self):
        for row in self.storage.execute("SELECT id FROM refs ORDER BY id"):
            yield row[0]

    def __len__(self):
        return self.storage.execute("SELECT COUNT(*) FROM refs").fetchone()[0]

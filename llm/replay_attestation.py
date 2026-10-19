"""Private disk-backed evidence for one replay execution, never a source writer."""
from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
import tempfile
import weakref


class ReplayCallJournal:
    """Retain consumed bytes exactly with a bounded SQLite page cache."""

    def __init__(self, directory: str | Path | None):
        self.parent = Path(directory) if directory is not None else None
        self._temporary = None
        self._connection = None
        self._finalizer = None
        self._count = 0
        self._closed = False

    def _open(self):
        if self._closed:
            raise RuntimeError("replay call journal is closed")
        if self._connection is None:
            # File-backed replays use their filesystem; OS temp may be RAM-backed.
            self._temporary = tempfile.TemporaryDirectory(
                prefix=".replay-calls-", dir=self.parent)
            try:
                self._connection = sqlite3.connect(
                    Path(self._temporary.name) / "calls.sqlite3", check_same_thread=False)
                self._finalizer = weakref.finalize(
                    self, self._release, self._connection, self._temporary)
                self._connection.executescript("""
                    PRAGMA cache_size=-2048;
                    PRAGMA mmap_size=0;
                    PRAGMA temp_store=FILE;
                    CREATE TABLE calls (
                        kind TEXT NOT NULL, seq INTEGER NOT NULL,
                        source_id INTEGER NOT NULL, purpose TEXT NOT NULL,
                        PRIMARY KEY(kind,seq)) WITHOUT ROWID;
                    CREATE INDEX call_ids ON calls(kind,source_id);
                    CREATE TABLE payloads (
                        kind TEXT NOT NULL, logical BLOB NOT NULL, seq INTEGER NOT NULL,
                        PRIMARY KEY(kind,logical,seq)) WITHOUT ROWID;
                    BEGIN;
                """)
            except BaseException:
                self.close()
                raise
        return self._connection

    def __len__(self):
        return self._count

    def __iter__(self):
        if not self._count:
            return
        rows = self._open().execute(
            "SELECT c.source_id,p.logical,c.purpose FROM payloads p "
            "JOIN calls c ON c.kind=p.kind AND c.seq=p.seq "
            "WHERE p.kind='consumed' ORDER BY c.seq")
        for source_id, logical, purpose in rows:
            yield source_id, logical.decode("utf-8"), purpose

    def _insert(self, kind, seq, record):
        source_id, logical, purpose = record
        connection = self._open()
        connection.execute("SAVEPOINT append_call")
        try:
            connection.execute("INSERT INTO calls VALUES (?,?,?,?)",
                               (kind, seq, source_id, purpose))
            connection.execute("INSERT INTO payloads VALUES (?,?,?)",
                               (kind, logical.encode("utf-8"), seq))
        except BaseException:
            connection.execute("ROLLBACK TO append_call")
            connection.execute("RELEASE append_call")
            raise
        connection.execute("RELEASE append_call")

    def append(self, record):
        self._insert("consumed", self._count + 1, record)
        self._count += 1

    def truncate(self, count):
        if count == self._count:
            return
        connection = self._open()
        connection.execute("DELETE FROM payloads WHERE kind='consumed' AND seq>?", (count,))
        connection.execute("DELETE FROM calls WHERE kind='consumed' AND seq>?", (count,))
        self._count = count

    def _summary(self, kind):
        digest, oracle_digest = hashlib.sha256(), hashlib.sha256()
        purposes = {}
        count = oracle_count = 0
        # UTF-8 BLOB order equals Python Unicode order for these canonical JSON
        # strings. The ordinal preserves duplicates; no payload-sized temp sort.
        rows = self._open().execute(
            "SELECT p.logical,c.purpose FROM payloads p "
            "JOIN calls c ON c.kind=p.kind AND c.seq=p.seq "
            "WHERE p.kind=? ORDER BY p.logical,p.seq", (kind,))
        for logical, purpose in rows:
            digest.update(logical)
            digest.update(b"\n")
            count += 1
            purposes[purpose] = purposes.get(purpose, 0) + 1
            if purpose in {"oracle", "oracle_plan"}:
                oracle_count += 1
                oracle_digest.update(logical)
                oracle_digest.update(b"\n")
        return count, digest.hexdigest(), dict(sorted(purposes.items())), oracle_count, oracle_digest.hexdigest()

    def execution_stats(self, expected):
        connection = self._open()
        connection.execute("DELETE FROM payloads WHERE kind='expected'")
        connection.execute("DELETE FROM calls WHERE kind='expected'")
        for seq, record in enumerate(expected, 1):
            self._insert("expected", seq, record)
        source_count, source_digest, source_purposes, oracle_count, oracle_digest = self._summary("expected")
        consumed_count, consumed_digest, consumed_purposes, consumed_oracle_count, consumed_oracle_digest = self._summary("consumed")
        missing = connection.execute(
            "SELECT COUNT(DISTINCT e.source_id) FROM calls e WHERE e.kind='expected' "
            "AND NOT EXISTS (SELECT 1 FROM calls c WHERE c.kind='consumed' AND c.source_id=e.source_id)"
        ).fetchone()[0]
        unexpected = connection.execute(
            "SELECT COUNT(DISTINCT c.source_id) FROM calls c WHERE c.kind='consumed' "
            "AND NOT EXISTS (SELECT 1 FROM calls e WHERE e.kind='expected' AND e.source_id=c.source_id)"
        ).fetchone()[0]
        duplicates = connection.execute(
            "SELECT COUNT(*)-COUNT(DISTINCT source_id) FROM calls WHERE kind='consumed'"
        ).fetchone()[0]
        return {
            "schema_version": 1,
            "source_nonoperational_calls": source_count,
            "consumed_source_calls": consumed_count,
            "source_logical_calls_sha256": source_digest,
            "consumed_logical_calls_sha256": consumed_digest,
            "source_purpose_counts": source_purposes,
            "consumed_purpose_counts": consumed_purposes,
            "oracle_source_calls": oracle_count,
            "oracle_consumed_calls": consumed_oracle_count,
            "oracle_source_calls_sha256": oracle_digest,
            "oracle_consumed_calls_sha256": consumed_oracle_digest,
            "missing_source_calls": missing,
            "unexpected_source_calls": unexpected,
            "duplicate_source_consumptions": duplicates,
            "all_nonoperational_calls_consumed_once": bool(
                not missing and not unexpected and not duplicates and source_count == consumed_count),
            "all_oracle_calls_consumed_once": bool(
                oracle_count == consumed_oracle_count and oracle_digest == consumed_oracle_digest),
        }

    def close(self):
        self._closed = True
        try:
            if self._finalizer is not None:
                self._finalizer()
            else:
                self._release(self._connection, self._temporary)
        finally:
            self._connection = self._temporary = self._finalizer = None

    @staticmethod
    def _release(connection, temporary):
        try:
            if connection is not None:
                connection.close()
        finally:
            if temporary is not None:
                temporary.cleanup()

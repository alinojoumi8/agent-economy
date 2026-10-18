"""Bounded, on-demand materialization of canonical backward event references."""
from collections.abc import Mapping

from world.replay_storage import EventReferences


def event_dependency_ids(value, single_keys, list_keys, skip_keys):
    """Visit raw provenance using the same key rules as canonical expansion."""
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in skip_keys:
                continue
            if key in single_keys:
                yield nested
            elif key in list_keys:
                if isinstance(nested, list):
                    yield from nested
            else:
                yield from event_dependency_ids(nested, single_keys, list_keys, skip_keys)
    elif isinstance(value, list):
        for nested in value:
            yield from event_dependency_ids(nested, single_keys, list_keys, skip_keys)


class _EarlierReferences:
    def __init__(self, references, before):
        self.references, self.before = references, before

    def get(self, key, default=None):
        return self.references.get(key, default) if key < self.before else default


class LazyEventReferences(Mapping):
    """Build only requested reference histories; still hash every event elsewhere.

    The frontier is a private SQLite queue, not a recursive Python object graph.
    Dependencies have smaller event IDs, so ascending materialization preserves
    the old incremental index's dangling/forward-reference representation.
    """

    def __init__(self, connection, storage, dependencies, canonicalize):
        self.connection, self.storage = connection, storage
        self.dependencies, self.canonicalize = dependencies, canonicalize
        self.references = EventReferences(storage)
        storage.execute("CREATE TABLE IF NOT EXISTS pending_event_refs("
                        "id INTEGER PRIMARY KEY, expanded INTEGER NOT NULL DEFAULT 0)")
        storage.execute("CREATE INDEX IF NOT EXISTS pending_event_frontier "
                        "ON pending_event_refs(expanded,id)")
        storage.execute("DELETE FROM pending_event_refs")

    def _present(self, key):
        return (("event", key) in self.storage.cache or self.storage.execute(
            "SELECT 1 FROM refs WHERE id=?", (key,)).fetchone() is not None)

    def __getitem__(self, key):
        if not isinstance(key, int) or not -(2**63) <= key < 2**63:
            raise KeyError(key)
        self.storage.check()
        if not self._present(key):
            self._materialize(key)
        return self.references[key]

    def _materialize(self, key):
        # Materialized references have their own record budgets. Restore the
        # requesting record's charge before its final decoded expansion.
        expanded_before = self.storage.expanded_reference_bytes
        input_before = self.storage.input_bound
        fragments_before = self.storage.has_fragments
        try:
            self.storage.execute("DELETE FROM pending_event_refs")
            self.storage.execute("INSERT INTO pending_event_refs(id) VALUES (?)", (key,))
            while True:
                pending = self.storage.execute(
                    "SELECT id FROM pending_event_refs WHERE expanded=0 ORDER BY id LIMIT 1").fetchone()
                if pending is None:
                    break
                current = pending[0]
                self.storage.execute("UPDATE pending_event_refs SET expanded=1 WHERE id=?", (current,))
                row = self.connection.execute("SELECT * FROM events WHERE id=?", (current,)).fetchone()
                if row is None:
                    self.storage.execute("INSERT OR IGNORE INTO missing_event_refs VALUES (?)", (current,))
                    continue
                for dependency in self.dependencies(row):
                    if (type(dependency) is int and -(2**63) <= dependency < current
                            and not self._present(dependency)):
                        self.storage.execute("INSERT OR IGNORE INTO pending_event_refs(id) VALUES (?)",
                                             (dependency,))
            for pending in self.storage.execute("SELECT id FROM pending_event_refs ORDER BY id"):
                current = pending[0]
                if self._present(current):
                    continue
                row = self.connection.execute("SELECT * FROM events WHERE id=?", (current,)).fetchone()
                if row is not None:
                    self.storage.begin_record(row)
                    self.references[current] = self.canonicalize(
                        row, _EarlierReferences(self.references, current))
            self.storage.execute("DELETE FROM pending_event_refs")
        finally:
            self.storage.expanded_reference_bytes = expanded_before
            self.storage.input_bound = input_before
            self.storage.has_fragments = fragments_before

    def __iter__(self):
        for row in self.connection.execute("SELECT id FROM events ORDER BY id"):
            yield row[0]

    def __len__(self):
        return self.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]

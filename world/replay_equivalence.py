"""Sufficient, deliberately strict input equality for canonical digest reuse."""
from itertools import zip_longest
import struct


def _quoted(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def _same_row(left, right):
    if left is None or right is None:
        return left is right
    return len(left) == len(right) and all(
        type(a) is type(b) and (
            struct.pack('!d', a) == struct.pack('!d', b) if isinstance(a, float) else a == b)
        for a, b in zip(left, right))


def identical_inputs(source, replay, storage, *, excluded_tables, ignored_columns,
                     table_ignored_columns, ignored_event_kinds):
    """Compare rows before reusing a digest, including physical reference IDs.

    This is stricter than canonical equality: reordered IDs or JSON text select
    independent canonical comparison. Every non-operational table is scanned,
    including empty historical extension tables and operational LLM calls.
    Operational event differences are allowed only when the source canonical
    traversal never looked up that ID (including unsuccessful lookups). Thus an
    extra replay event cannot turn a source's dangling reference into a valid one.
    The caller separately checks the complete comparison configuration.
    """
    def tables(connection):
        return sorted(row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            if row[0] not in excluded_tables)

    names = tables(source)
    if names != tables(replay):
        return False
    event_columns = None
    for table in names:
        storage.check()
        info = list(source.execute(f'PRAGMA table_info({_quoted(table)})'))
        other_info = list(replay.execute(f'PRAGMA table_info({_quoted(table)})'))
        if len(info) != len(other_info) or not all(_same_row(a, b) for a, b in zip(info, other_info)):
            return False
        columns = [row[1] for row in info
                   if row[1] not in ignored_columns | table_ignored_columns.get(table, set())]
        selected = ','.join(map(_quoted, columns))
        query = f'SELECT {selected} FROM {_quoted(table)}'
        parameters = ()
        if table == 'events':
            event_columns = columns
            placeholders = ','.join('?' for _ in ignored_event_kinds)
            query += f' WHERE kind NOT IN ({placeholders}) OR kind IS NULL'
            parameters = tuple(sorted(ignored_event_kinds))
        if 'id' in columns:
            query += ' ORDER BY id'
        for left, right in zip_longest(source.execute(query, parameters), replay.execute(query, parameters)):
            storage.check()
            if not _same_row(left, right):
                return False

    if event_columns is not None:
        placeholders = ','.join('?' for _ in ignored_event_kinds)
        query = (f"SELECT {','.join(map(_quoted, event_columns))} FROM events "
                 f'WHERE kind IN ({placeholders}) ORDER BY id')
        parameters = tuple(sorted(ignored_event_kinds))
        left_rows, right_rows = iter(source.execute(query, parameters)), iter(replay.execute(query, parameters))
        left, right = next(left_rows, None), next(right_rows, None)
        while left is not None or right is not None:
            storage.check()
            key = min(row['id'] for row in (left, right) if row is not None)
            a = left if left is not None and left['id'] == key else None
            b = right if right is not None and right['id'] == key else None
            if not _same_row(a, b) and storage.execute(
                    'SELECT 1 FROM refs WHERE id=? UNION ALL '
                    'SELECT 1 FROM missing_event_refs WHERE id=? LIMIT 1', (key, key)).fetchone():
                return False
            if a is not None:
                left = next(left_rows, None)
            if b is not None:
                right = next(right_rows, None)
    storage.check(force=True)
    return True

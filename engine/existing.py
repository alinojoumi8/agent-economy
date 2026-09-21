"""Strict attachment helpers: never create, migrate or repair stored artifacts."""
from contextlib import closing
from pathlib import Path
import sqlite3


def existing_path(value) -> Path:
    path = Path(value).absolute()
    if not path.is_file() or path.resolve() != path or path.stat().st_nlink != 1:
        raise ValueError(f"existing artifact must be an unaliased regular file: {path}")
    return path


def validate_schema(conn, initialize_reference) -> None:
    """Compare to a disposable current schema, without executing DDL on source."""
    if [row[0] for row in conn.execute('PRAGMA integrity_check')] != ['ok']:
        raise ValueError('existing database failed SQLite integrity_check')
    if conn.execute('PRAGMA foreign_key_check').fetchone() is not None:
        raise ValueError('existing database failed foreign_key_check')
    with closing(sqlite3.connect(':memory:')) as reference:
        initialize_reference(reference)
        for (table,) in reference.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            quoted = '"' + table.replace('"', '""') + '"'
            expected = {r[1]: (r[2], r[3], r[5]) for r in reference.execute(f'PRAGMA table_info({quoted})')}
            actual = {r[1]: (r[2], r[3], r[5]) for r in conn.execute(f'PRAGMA table_info({quoted})')}
            if any(actual.get(k) != v for k, v in expected.items()):
                raise ValueError(f'existing database has incompatible schema: {table}')
        # Required indexes/triggers are part of normal validation and ledger behavior.
        objects = {(r[0], r[1]): r[2] for r in conn.execute(
            "SELECT type,name,sql FROM sqlite_master WHERE type IN ('index','trigger')")}
        for kind, name, sql in reference.execute(
                "SELECT type,name,sql FROM sqlite_master WHERE type IN ('index','trigger')"):
            if (kind, name) not in objects:
                raise ValueError(f'existing database is missing {kind}: {name}')
            if kind == 'trigger' and objects[kind, name] != sql:
                raise ValueError(f'existing database has incompatible trigger: {name}')


def open_existing(value, validate):
    path = existing_path(value)
    conn = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True,
                           isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=0')
        conn.execute('PRAGMA query_only=ON')
        validate(conn)
        conn.execute('PRAGMA query_only=OFF')
        return conn
    except BaseException:
        conn.close()
        raise

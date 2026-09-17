"""Operator-only storage commands: python -m engine.storage_cli --help."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .checkpoint_retention import pin_checkpoint, unpin_checkpoint, verify_checkpoint
from .storage_archive import archive_run, copy_run, restore_archive
from .storage_policy import GiB, database_bytes
from .store import open_read_only_connection


def inspect_run(database: str | Path) -> dict:
    path = Path(database).resolve(strict=True)
    connection = open_read_only_connection(str(path))
    try:
        meta = connection.execute("SELECT run_id,tick,schema_version FROM run_meta WHERE id=1").fetchone()
        calls = connection.execute(
            "SELECT COUNT(*), SUM(typeof(request_json)='blob'), "
            "COALESCE(SUM(length(CAST(request_json AS BLOB))),0) + "
            "COALESCE(SUM(length(CAST(response_json AS BLOB))),0) FROM llm_calls").fetchone()
        return {"run_id": meta[0], "tick": meta[1], "schema_version": meta[2],
                "database_and_sidecar_bytes": database_bytes(path),
                "model_calls": calls[0], "packed_requests": calls[1] or 0,
                "model_payload_bytes": calls[2],
                "memory_rows": connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0]}
    finally:
        connection.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "verify", "pin", "unpin"):
        command = commands.add_parser(name)
        command.add_argument("database", type=Path)
        if name == "pin":
            command.add_argument("--reason", required=True)
    for name in ("copy", "archive", "restore"):
        command = commands.add_parser(name)
        command.add_argument("source", type=Path)
        command.add_argument("destination", type=Path)
        command.add_argument("--min-free-bytes", type=int, default=5 * GiB)
        if name == "copy":
            command.add_argument("--encoding", choices=("plain", "packed"), default="plain")
        if name == "restore":
            command.add_argument("--max-database-bytes", type=int, default=100 * GiB)
    args = parser.parse_args(argv)
    if args.command == "inspect":
        result = inspect_run(args.database)
    elif args.command == "verify":
        manifest = verify_checkpoint(args.database.resolve())
        result = {"verified": True, "database_sha256": manifest["database_sha256"]}
    elif args.command == "pin":
        result = {"pin": str(pin_checkpoint(args.database, args.reason))}
    elif args.command == "unpin":
        unpin_checkpoint(args.database)
        result = {"unpinned": True}
    else:
        options = {"min_free_bytes": args.min_free_bytes}
        operation = archive_run
        if args.command == "copy":
            operation = copy_run
            options["encoding"] = args.encoding
        elif args.command == "restore":
            operation = restore_archive
            options["max_database_bytes"] = args.max_database_bytes
        result = operation(args.source, args.destination, **options)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Read-only admission of closed scientific initial conditions.

Admission verifies the supplied state, not the historical process that produced
it. Every continuation and recorded replay receives a separate owned copy.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3

from engine.ledger import Ledger
from engine.schema import SCHEMA_VERSION
from engine.semantics import semantics_version
from engine.store import Store
from research.artifacts import digest_json, file_sha256, publish_copy, safe_key
from research.working_contracts import input_prefixes, persisted_random_state
from world.replay_verify import canonical_state_receipt, verify_replay_connections

ORIGIN_CONTRACT = "checkpoint-origin-v1"
# These controls neither initialize an economy nor change its decision policy.
OPERATIONAL_CONFIG_KEYS = {
    "checkpoint_dir", "checkpoint_every", "report_dir", "speed_delay_s",
}


def continuation_config(config: dict) -> dict:
    """Retain all economic and policy inputs, including seed and old schedules."""
    return {key: value for key, value in config.items() if key not in OPERATIONAL_CONFIG_KEYS}


def _standalone(path: Path, max_bytes: int) -> None:
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError("checkpoint byte limit must be a positive integer")
    if path.absolute() != path.resolve() or not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError("checkpoint must be a standalone, unaliased file")
    if not 0 < path.stat().st_size <= max_bytes:
        raise ValueError("checkpoint exceeds its admission size limit")
    if any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise ValueError("checkpoint must be closed without SQLite sidecars")


@contextmanager
def closed_checkpoint(path: str | Path, *, max_bytes: int):
    """Never create source-side journals or run schema migrations."""
    source = Path(path).absolute()
    _standalone(source, max_bytes)
    connection = sqlite3.connect(f"{source.as_uri()}?mode=ro&immutable=1", uri=True,
                                 isolation_level=None, cached_statements=0)
    try:
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA foreign_keys = ON")
        store = Store.from_read_only_connection(source, connection)
    except BaseException:
        connection.close()
        raise
    try:
        yield store
    finally:
        store.close()


def inspect_checkpoint(path: str | Path, *, max_bytes: int, config: dict | None = None) -> dict:
    """Bind a modern completed day and independently check its accounting."""
    source = Path(path).absolute()
    _standalone(source, max_bytes)
    digest = file_sha256(source)
    with closed_checkpoint(source, max_bytes=max_bytes) as store:
        meta = store.get_meta()
        if (meta is None or meta["schema_version"] != SCHEMA_VERSION
                or type(meta["tick"]) is not int or meta["tick"] < 0
                or meta["status"] not in {"paused", "finished", "completed"}
                or meta["active_tick"] is not None or meta["legacy_partial"]
                or meta["next_phase"] not in (None, "NIGHT_CLOSE")
                or json.loads(meta["phase_state_json"] or "{}") != {}):
            raise ValueError("checkpoint is not a compatible completed day")
        stored_config = json.loads(meta["config_json"])
        version = semantics_version(stored_config, default=1)
        if version < 7 or type(meta["seed"]) is not int or stored_config.get("seed") != meta["seed"]:
            raise ValueError("checkpoint requires explicit seed and persisted random semantics")
        if config is not None and continuation_config(config) != continuation_config(stored_config):
            raise ValueError("checkpoint economic configuration differs from the declaration")
        if meta["external_agent_influenced"] or meta["participant_influenced"]:
            raise ValueError("checkpoint has undeclared external influence")
        if store.scalar("PRAGMA quick_check") != "ok" or store.query("PRAGMA foreign_key_check"):
            raise ValueError("checkpoint database integrity failed")
        state = canonical_state_receipt(store.conn)
        if not state["references_valid"] or not Ledger(store).reconcile()[0]:
            raise ValueError("checkpoint state or accounting is invalid")
        # Recompute from actual ledger legs rather than trusting cached totals.
        mismatches = store.query(
            "SELECT a.id FROM accounts a LEFT JOIN "
            "(SELECT account_id, SUM(delta_cents) total FROM ledger_entries GROUP BY account_id) l "
            "ON l.account_id=a.id WHERE a.balance_cents<>COALESCE(l.total,0)")
        unbalanced = store.query(
            "SELECT l.txn_id FROM ledger_entries l JOIN accounts a ON a.id=l.account_id "
            "GROUP BY l.txn_id,a.currency_code HAVING SUM(l.delta_cents)<>0")
        if mismatches or unbalanced:
            raise ValueError("checkpoint ledger entries do not reconcile")
        streams = persisted_random_state(meta)
        last_id = int(store.scalar("SELECT COALESCE(MAX(id),0) FROM llm_calls", default=0))
        result = {
            "contract": ORIGIN_CONTRACT, "database_sha256": digest,
            "byte_size": source.stat().st_size, "run_id": meta["run_id"],
            "seed": meta["seed"], "tick": meta["tick"], "schema_version": SCHEMA_VERSION,
            "engine_semantics_version": version, "config_sha256": digest_json(stored_config),
            "continuation_config_sha256": digest_json(continuation_config(stored_config)),
            "state": state, "prng_sha256": digest_json(streams),
            "recorded_inputs": input_prefixes(store, {last_id})[last_id],
        }
        result["initial_state_sha256"] = digest_json({
            "state": state["sha256"], "prng": result["prng_sha256"],
            "tick": result["tick"], "seed": result["seed"],
            "configuration": result["continuation_config_sha256"],
            "inputs": result["recorded_inputs"],
        })
    _standalone(source, max_bytes)
    if file_sha256(source) != digest:
        raise ValueError("checkpoint changed during admission")
    return result


def verify_checkpoint(path: str | Path, receipt: dict, *, max_bytes: int,
                      config: dict | None = None) -> dict:
    actual = inspect_checkpoint(path, max_bytes=max_bytes, config=config)
    if actual != receipt:
        raise ValueError("checkpoint differs from its admitted origin")
    return actual


def verify_closed_replay(source: str | Path, replay: str | Path, *, max_bytes: int) -> dict:
    """Compare closed evidence without creating source-side WAL/SHM files."""
    before = [file_sha256(path) for path in (source, replay)]
    with closed_checkpoint(source, max_bytes=max_bytes) as source_store:
        with closed_checkpoint(replay, max_bytes=max_bytes) as replay_store:
            proof = verify_replay_connections(source_store.conn, replay_store.conn)
    if before != [file_sha256(path) for path in (source, replay)]:
        raise ValueError("closed replay evidence changed during comparison")
    return proof


def copy_checkpoint(path: str | Path, receipt: dict, destination: str | Path, *,
                    max_bytes: int, config: dict | None = None) -> Path:
    """Publish only a complete, verified copy; an existing child is never replaced."""
    source, target = Path(path).absolute(), Path(destination).absolute()
    if target.resolve() != target or target == source.resolve():
        raise ValueError("checkpoint child path must be independent and unaliased")
    if target.exists():
        raise FileExistsError("checkpoint child already exists")
    verify_checkpoint(source, receipt, max_bytes=max_bytes, config=config)
    publish_copy(target, source, expected_sha256=receipt["database_sha256"], max_bytes=max_bytes)
    verify_checkpoint(target, receipt, max_bytes=max_bytes, config=config)
    verify_checkpoint(source, receipt, max_bytes=max_bytes, config=config)
    return target


def open_continuation(path: str | Path, receipt: dict, destination: str | Path, *,
                      run_id: str, config: dict, interventions: list[dict], max_bytes: int,
                      replay_source: str | Path | None = None,
                      replay_source_sha256: str | None = None):
    """Create an owned world or recorded replay from the same admitted origin."""
    from world.checkpoint_branch import open_checkpoint_branch, validate_checkpoint_interventions

    safe_key(run_id)
    verify_checkpoint(path, receipt, max_bytes=max_bytes)
    validate_checkpoint_interventions(receipt, interventions)
    with closed_checkpoint(path, max_bytes=max_bytes) as origin_store:
        original_config = json.loads(origin_store.get_meta()["config_json"])
    expected = continuation_config(original_config)
    expected["shocks"] = [*(original_config.get("shocks") or []), *interventions]
    if continuation_config(config) != expected:
        raise ValueError("continuation changes more than its declared interventions")
    cfg = json.loads(json.dumps(config))
    if replay_source is not None:
        source = Path(replay_source).absolute()
        _standalone(source, max_bytes)
        if not replay_source_sha256 or file_sha256(source) != replay_source_sha256:
            raise ValueError("recorded continuation source changed")
        cfg["replay_source_path"] = str(source)
        cfg["replay_source_closed"] = True
    elif replay_source_sha256 is not None:
        raise ValueError("recorded continuation hash has no source")
    target = copy_checkpoint(path, receipt, destination, max_bytes=max_bytes)
    store = Store(str(target), create=False)
    world = None
    try:
        world = open_checkpoint_branch(store, cfg, run_id=run_id, origin=receipt,
            interventions=interventions, replay=replay_source is not None)
        if replay_source is not None and file_sha256(source) != replay_source_sha256:
            world.close()
            raise ValueError("recorded continuation source changed during initialization")
        verify_checkpoint(path, receipt, max_bytes=max_bytes)
        return store, world
    except BaseException:
        if world is not None:
            world.close()
        else:
            store.close()
        raise

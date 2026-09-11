"""Execution and independently checked eligibility for research attempts.

No economic rules live here. Worlds still mutate through engine/world, and
replay uses the ordinary recorded-input runner with a read-only source.
"""
from __future__ import annotations

import asyncio
from contextlib import ExitStack
import json
from pathlib import Path
import sqlite3
from typing import Callable
from llm.completion_guard import CompletionGuard

from engine.store import Store
from engine.semantics import semantics_version
from research.artifacts import digest_json, file_sha256, publish_json, safe_key
from research.working_contracts import PHASE_PROTOCOL, attempt_version, claim_working_protocol
from world.loop import World
from world.replay_verify import canonical_state_receipt, verify_replay


def execute_attempt(*, run_id: str, seed: int, arm: str, config: dict,
                    ticks: int, data_dir: Path,
                    collect: Callable[[Store], dict],
                    initialize: Callable[[Store], None] | None = None,
                    completion_guard: CompletionGuard | None = None) -> dict:
    """Claim, execute, close, replay and receipt one fresh world. Never retry it."""
    safe_key(arm)
    label = run_id
    cell_id = digest_json({"seed": seed, "arm": arm})[:12]
    run_id = "r-" + digest_json({"batch": data_dir.name, "cell": cell_id})[:12]
    attempt_dir = data_dir / cell_id
    attempt_dir.mkdir(parents=True, exist_ok=False)
    source_dir = attempt_dir / "source"
    source_dir.mkdir()
    source_path = source_dir / f"{run_id}.db"
    # Even accidental reuse outside the batch allocator cannot truncate a DB.
    with source_path.open("xb"):
        pass
    cfg = json.loads(json.dumps(config))
    # World defaults unversioned fresh callers to v2; the replay loader treats
    # markerless stored databases as v1. Persist the actual fresh contract.
    cfg["engine_semantics_version"] = semantics_version(cfg, default=2)
    cfg.update({"seed": seed, "checkpoint_every": 0, "speed_delay_s": 0.0,
                "checkpoint_dir": str(attempt_dir / "checkpoints"),
                "report_dir": str(attempt_dir / "reports")})
    claim = {"protocol_version": 1, "run_id": run_id, "label": label, "seed": seed, "arm": arm,
             "expected_ticks": ticks, "config_sha256": digest_json(cfg),
             "config": cfg, "execution_status": "planned"}
    claim_path = publish_json(attempt_dir / "attempt.json", claim)
    row = {"run_id": run_id, "seed": seed, "arm": arm, "ticks": 0,
           "expected_ticks": ticks, "execution_status": "failed",
           "reconciled": False, "reconciliation": None, "final_boundary": False,
           "external_agent_influenced": False, "metrics": {}, "series": {},
           "events": {}, "spend_usd": 0.0, "causal_trace": [],
           "genesis_hash": None, "event_hash": None, "replay_hash": None,
           "source_database": str(source_path), "attempt_claim": str(claim_path),
           "attempt_claim_sha256": file_sha256(claim_path), "config_sha256": digest_json(cfg)}
    store, world = None, None
    reasons = []
    try:
        store = Store(str(source_path))
        store.init_run_meta(run_id, seed, cfg)
        world = World(store, cfg, completion_guard=completion_guard)
        world.initialize()
        if initialize is not None:
            initialize(store)
        store.commit()
        genesis = canonical_state_receipt(
            store.conn, excluded_protocol_tables=("shocks", "scenario_packs"))
        # The engine and persona RNG states are part of the initial condition.
        genesis["prng_state"] = store.get_meta()["prng_state"]
        row["genesis_hash"] = digest_json({
            "state": genesis["sha256"], "prng_state": genesis["prng_state"]})
        row["genesis_receipt"] = str(publish_json(attempt_dir / "genesis.json", genesis))
        if not genesis["references_valid"]:
            reasons.append("invalid_genesis_references")
        publish_json(attempt_dir / "running.json", {**claim, "execution_status": "running"})
        asyncio.run(world.run(max_ticks=ticks))
        reasons.extend(observe_source(world, row, ticks=ticks, collect=collect))
    except Exception as exc:
        # Failed worlds remain in the assigned cohort; error text can contain
        # private model content, so the public result keeps a type/reason only.
        row["execution_status"] = "failed"
        row["error_type"] = type(exc).__name__
        if store is not None:
            row["ticks"] = store.tick
        reasons.append("execution_failed")
    finally:
        if world is not None:
            world.close()
        elif store is not None:
            store.close()

    return finalize_attempt(row, attempt_dir=attempt_dir, reasons=reasons)


def observe_source(world: World, row: dict, *, ticks: int,
                   collect: Callable[[Store], dict]) -> list[str]:
    """Measure committed state without deciding publication or retry policy."""
    store, meta = world.store, world.store.get_meta()
    row.update(collect(store))
    row["ticks"] = store.tick
    row["reconciled"], row["reconciliation"] = world.economy.ledger.reconcile()
    row["final_boundary"] = (meta["active_tick"] is None
                             and meta["next_phase"] in (None, "NIGHT_CLOSE")
                             and meta["status"] != "halted")
    row["external_agent_influenced"] = bool(meta["external_agent_influenced"])
    row["execution_status"] = (
        "completed" if row["ticks"] == ticks and row["final_boundary"]
        else "failed" if meta["status"] == "halted" else "paused")
    state = canonical_state_receipt(store.conn)
    row["event_hash"] = state["tables"]["events"]["sha256"]
    row["source_state_hash"] = state["sha256"]
    row["database_integrity"] = store.scalar("PRAGMA quick_check") == "ok"
    return [] if state["references_valid"] else ["invalid_source_references"]


def finalize_attempt(row: dict, *, attempt_dir: Path, reasons: list[str],
                     final_checks: Callable[[], list[str]] | None = None) -> dict:
    """Freeze source/replay/result receipts once; never replace prior evidence."""
    source_path = Path(row["source_database"])
    source_dir, run_id, ticks = source_path.parent, row["run_id"], row["expected_ticks"]
    row["source_database_sha256"] = file_sha256(source_path)
    source_receipt = publish_json(attempt_dir / "source-receipt.json", row)
    row["source_receipt"] = str(source_receipt)
    row["source_receipt_sha256"] = file_sha256(source_receipt)
    reasons.extend(execution_exclusions(row, expected_ticks=ticks))
    if not reasons:
        replay_store, replay_world = None, None
        try:
            claim = json.loads(Path(row["attempt_claim"]).read_text(encoding="utf-8"))
            if claim["protocol_version"] in {4, 6}:
                from research.attempt_origins import replay_checkpoint
                replay_path = replay_checkpoint(row, claim, attempt_dir)
            else:
                # Lazy import keeps the CLI dispatcher independent of research code.
                from run import open_run, replay_headless
                replay_store, replay_world, _ = open_run(
                    {}, None, run_id, data_dir=attempt_dir / "replay",
                    replay_source_dir=source_dir)
                asyncio.run(replay_headless(replay_world, ticks))
                replay_path = Path(replay_store.path)
                replay_world.close()
                replay_world, replay_store = None, None
            if claim["protocol_version"] in {4, 6}:
                from research.checkpoint_origins import verify_closed_replay
                proof = verify_closed_replay(source_path, replay_path, max_bytes=claim["checkpoint_origin"]["max_bytes"])
            else:
                proof = verify_replay(source_path, replay_path)
            receipt = {
                "protocol_version": 1, "execution": "recorded_replay",
                "attempt_claim_sha256": row["attempt_claim_sha256"],
                "source_database": str(source_path),
                "source_database_sha256": file_sha256(source_path),
                "replay_database": str(replay_path),
                "replay_database_sha256": file_sha256(replay_path), "comparison": proof,
            }
            if claim["protocol_version"] in {4, 6}:
                receipt.update(protocol_version=3 if claim["protocol_version"] == 6 else 2, execution="recorded_checkpoint_replay",
                    origin_receipt_sha256=row["origin_receipt_sha256"],
                    continuation_window=[row["origin_tick"] + 1, ticks])
                if claim["protocol_version"] == 6:
                    receipt["policy_transition_sha256"] = digest_json(claim["checkpoint_origin"]["policy_transition"])
            receipt_path = publish_json(attempt_dir / "replay-receipt.json", receipt)
            row.update({"replay_receipt": str(receipt_path),
                        "replay_receipt_sha256": file_sha256(receipt_path),
                        "replay_hash": proof["replay_hash"]})
            if not proof["exact"]:
                reasons.append("replay_mismatch")
        except Exception as exc:
            row["replay_error_type"] = type(exc).__name__
            reasons.append("replay_execution_failed")
        finally:
            if replay_world is not None:
                replay_world.close()
            elif replay_store is not None:
                replay_store.close()
    row["eligibility"] = {"status": "ineligible", "reasons": sorted(set(reasons))}
    # Reopen and check the receipts/artifacts, not just the in-memory success flag.
    if not reasons:
        reasons = verify_attempt(row, expected_ticks=ticks)
    if final_checks is not None:
        reasons.extend(final_checks())
    row["eligibility"] = {"status": "ineligible" if reasons else "eligible",
                          "reasons": sorted(set(reasons))}
    publish_json(attempt_dir / "result.json", row)
    return row


def execution_exclusions(row: dict, *, expected_ticks: int | None) -> list[str]:
    reasons = []
    if row.get("execution_status") != "completed":
        reasons.append("execution_not_completed")
    if expected_ticks is None or row.get("ticks") != expected_ticks:
        reasons.append("incomplete_horizon")
    if row.get("expected_ticks") != expected_ticks:
        reasons.append("horizon_contract_mismatch")
    if row.get("final_boundary") is not True:
        reasons.append("partial_or_invalid_boundary")
    if row.get("reconciled") is not True:
        reasons.append("reconciliation_failed")
    if row.get("database_integrity") is not True:
        reasons.append("database_integrity_failed")
    if row.get("external_agent_influenced"):
        reasons.append("external_agent_influenced")
    return reasons


def verify_attempt(row: dict, *, expected_ticks: int,
                   resolve_path: Callable[[str], Path] | None = None) -> list[str]:
    """Fail closed if a completed attempt's source, claim, or replay has changed."""
    reasons = execution_exclusions(row, expected_ticks=expected_ticks)
    locate = resolve_path or Path
    try:
        for field in ("attempt_claim", "source_database", "source_receipt", "replay_receipt"):
            if file_sha256(locate(row[field])) != row[f"{field}_sha256"]:
                reasons.append(f"{field}_changed")
        source_wal = locate(row["source_database"] + "-wal")
        if source_wal.exists() and source_wal.stat().st_size:
            reasons.append("source_database_changed")
        claim = json.loads(locate(row["attempt_claim"]).read_text(encoding="utf-8"))
        working = claim_working_protocol(claim)
        checkpoint = claim.get("protocol_version") in {4, 6}
        if (claim.get("protocol_version") not in {1, 2, 3, 4, 5, 6}
                or ("working_history" in row) != bool(working)
                or ("position" in row) != (working == PHASE_PROTOCOL)
                or working and claim["protocol_version"] != attempt_version(claim["study_manifest"]["study"])):
            reasons.append("attempt_protocol_mismatch")
        if checkpoint:
            from research.attempt_origins import verify_origin_identity
            verify_origin_identity(row, claim, resolve_path=locate)
        elif "checkpoint_origin" in claim or any(key in row for key in ("origin_tick", "origin_state_hash", "origin_receipt_sha256")):
            reasons.append("attempt_protocol_mismatch")
        source = json.loads(locate(row["source_receipt"]).read_text(encoding="utf-8"))
        replay = json.loads(locate(row["replay_receipt"]).read_text(encoding="utf-8"))
        if (claim["expected_ticks"] != expected_ticks
                or claim["config_sha256"] != row["config_sha256"]
                or digest_json(claim["config"]) != row["config_sha256"]
                or any(claim[key] != row[key] for key in ("run_id", "seed", "arm"))):
            reasons.append("attempt_contract_mismatch")
        if any(digest_json(source.get(key)) != digest_json(row.get(key)) for key in (
                "run_id", "seed", "arm", "expected_ticks", "ticks", "config_sha256",
                "source_database_sha256", "execution_status", "final_boundary",
                "reconciled", "database_integrity", "external_agent_influenced",
                "source_state_hash", "genesis_hash", "event_hash", "metrics",
                "series", "events", "spend_usd", "provider_calls", "outcome_observations",
                "origin_tick", "origin_state_hash", "origin_receipt_sha256",
                "inherited_spend_usd", "inherited_provider_calls")):
            reasons.append("source_receipt_mismatch")
        if working:
            from research.working_attempts import verify_working_history
            reasons.extend(verify_working_history(row, claim, resolve_path=locate))
            for key in ("working_history", "genesis_receipt_sha256", "prng_state_sha256", "active_wall_seconds"):
                if digest_json(source.get(key)) != digest_json(row.get(key)):
                    reasons.append("working_source_receipt_mismatch")
            if working == PHASE_PROTOCOL and source.get("position") != row.get("position"):
                reasons.append("working_source_receipt_mismatch")
        if (replay["execution"] != ("recorded_checkpoint_replay" if checkpoint else "recorded_replay")
                or replay["attempt_claim_sha256"] != row["attempt_claim_sha256"]
                or replay["source_database_sha256"] != row["source_database_sha256"]
                or locate(replay["source_database"]).resolve() != locate(row["source_database"]).resolve()
                or file_sha256(locate(replay["replay_database"])) != replay["replay_database_sha256"]):
            reasons.append("replay_receipt_mismatch")
        if checkpoint and (replay.get("protocol_version") != (3 if claim["protocol_version"] == 6 else 2)
                or replay.get("origin_receipt_sha256") != row["origin_receipt_sha256"]
                or replay.get("continuation_window") != [row["origin_tick"] + 1, expected_ticks]):
            reasons.append("replay_receipt_mismatch")
        if claim["protocol_version"] == 6 and replay.get("policy_transition_sha256") != digest_json(claim["checkpoint_origin"]["policy_transition"]):
            reasons.append("replay_receipt_mismatch")
        replay_wal = locate(replay["replay_database"] + "-wal")
        if replay_wal.exists() and replay_wal.stat().st_size:
            reasons.append("replay_receipt_mismatch")
        if locate(row["source_database"]).samefile(locate(replay["replay_database"])):
            reasons.append("replay_database_not_independent")
        # Do not accept an 'exact: true' field without comparing the bound DBs.
        if checkpoint:
            from research.checkpoint_origins import verify_closed_replay
            actual = verify_closed_replay(locate(row["source_database"]), locate(replay["replay_database"]),
                                          max_bytes=claim["checkpoint_origin"]["max_bytes"])
        else:
            actual = verify_replay(locate(row["source_database"]), locate(replay["replay_database"]))
        if (not actual["exact"] or actual != replay["comparison"]
                or actual["source_tick"] != expected_ticks
                or actual["replay_hash"] != row["replay_hash"]):
            reasons.append("replay_mismatch")
        with ExitStack() as readers:
            if checkpoint:
                from research.checkpoint_origins import closed_checkpoint
                from research.attempt_origins import verify_origin_prefix
                limit = claim["checkpoint_origin"]["max_bytes"]
                store = readers.enter_context(closed_checkpoint(locate(row["source_database"]), max_bytes=limit))
                replay_store = readers.enter_context(closed_checkpoint(locate(replay["replay_database"]), max_bytes=limit))
                verify_origin_prefix(store, claim)
                verify_origin_prefix(replay_store, claim)
            else:
                store = Store(str(locate(row["source_database"])), create=False, read_only=True)
                readers.callback(store.close)
            meta = store.get_meta()
            if (digest_json(json.loads(meta["config_json"])) != row["config_sha256"]
                    or meta["active_tick"] is not None
                    or int(meta["tick"]) != expected_ticks):
                reasons.append("source_contract_mismatch")
            if canonical_state_receipt(store.conn)["sha256"] != row["source_state_hash"]:
                reasons.append("source_state_changed")
            if working and digest_json(meta["prng_state"]) != row["prng_state_sha256"]:
                reasons.append("source_prng_state_changed")
            if working == PHASE_PROTOCOL:
                from research.working_attempts import verify_phase_history
                verify_phase_history(store, row, claim, resolve_path=locate)
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
        reasons.append("missing_or_invalid_receipt")
    return sorted(set(reasons))

"""Scripted working attempts that can resume before scientific finalization.

This is the executor seam for the resumable study supervisor. It uses an
exclusive batch lock and cooperative day-boundary limits; a supervisor must
still impose hard worker deadlines. Legacy attempts remain immutable.
"""
from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path
import sqlite3
import time
from typing import Callable

from engine.ledger import Ledger
from engine.schema import SCHEMA_VERSION
from engine.store import Store
from research.artifacts import code_identity, digest_json, file_sha256, publish_json
from research.attempts import finalize_attempt, observe_source
from research.process_lock import process_lock
from research.studies import StudySpec, validate_study_inputs
from research.study_runner import _arm_config, _disk_bytes, collect_outcomes, validate_execution
from world.loop import World
from world.replay_verify import canonical_state_receipt

PROTOCOL = "working-attempt-v2"


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("invalid working-attempt record")
    return value


def _member(root: Path, relative: str) -> Path:
    path = root / relative
    if path.resolve() != path.absolute() or not path.resolve().is_relative_to(root):
        raise ValueError("working-attempt path is aliased or outside its namespace")
    if path.is_file() and path.stat().st_nlink != 1:
        raise ValueError("working-attempt files must not be hard links")
    return path


def _duration(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("invalid cumulative active time")
    return float(value)


def _contract(batch: dict, spec: StudySpec, config: dict, input_root: Path) -> tuple[Path, Path]:
    validate_execution(spec, config, working=True)
    if spec.operations.pause_policy != "preserve_and_resume" or spec.model.engine_semantics_version < 7:
        raise ValueError("working attempts require explicit resume policy and persisted PRNG semantics")
    manifest = batch["manifest"]
    if (manifest.get("attempt_protocol") != PROTOCOL
            or manifest.get("timing_contract") != "cumulative-active-wall-v1"
            or digest_json(manifest) != batch["manifest_sha256"]):
        raise ValueError("working-study manifest mismatch")
    declared = validate_study_inputs(spec, config, input_root=input_root)
    if any(digest_json(manifest.get(key)) != digest_json(value) for key, value in declared.items()):
        raise ValueError("study contract or declared inputs changed")
    if manifest["code"] != code_identity():
        raise ValueError("study code changed")
    roots = [Path(batch[key]).absolute() for key in ("data_dir", "report_dir")]
    if any(root.resolve() != root or not root.is_dir() for root in roots):
        raise ValueError("working-study root is missing or aliased")
    if roots[0] == roots[1] or roots[0].is_relative_to(roots[1]) or roots[1].is_relative_to(roots[0]):
        raise ValueError("working-study data and report roots overlap")
    expected = {key: batch[key] for key in ("batch_id", "manifest_sha256", "manifest")}
    for root in roots:
        if _read(_member(root, "manifest.json")) != expected:
            raise ValueError("stored study manifest changed")
        if (root / "publication.json").exists() or (root / "results.json").exists():
            raise ValueError("published studies cannot resume")
    context = roots[0] / "context"
    if file_sha256(_member(context, "model-description.md")) != declared["model_description_sha256"]:
        raise ValueError("saved model description changed")
    for item in spec.inputs:
        if file_sha256(_member(context, f"inputs/{item.sha256}.blob")) != item.sha256:
            raise ValueError("saved study input changed")
    return roots[0], roots[1]


def _history(directory: Path, claim_sha256: str) -> tuple[list[dict], dict | None]:
    """Require a contiguous hash-bound sequence; an unmatched start is a crash."""
    starts = sorted(directory.glob("segment-*-start.json"))
    pauses = sorted(directory.glob("segment-*-pause.json"))
    if len(starts) != len(pauses):
        raise ValueError("unfinished segment cannot resume")
    refs, previous, row = [], None, None
    for number, (start_path, pause_path) in enumerate(zip(starts, pauses), 1):
        if (start_path.name != f"segment-{number:06d}-start.json"
                or pause_path.name != f"segment-{number:06d}-pause.json"):
            raise ValueError("working segment sequence is incomplete")
        start_path, pause_path = _member(directory, start_path.name), _member(directory, pause_path.name)
        start, pause = _read(start_path), _read(pause_path)
        if (start.get("attempt_claim_sha256") != claim_sha256
                or start.get("previous_pause_sha256") != previous
                or start.get("before_source_sha256") != (row["source_database_sha256"] if row else None)
                or pause.get("start_sha256") != file_sha256(start_path)):
            raise ValueError("working segment lineage changed")
        next_row = pause["row"]
        if (next_row["execution_status"] != "paused"
                or next_row["attempt_claim_sha256"] != claim_sha256
                or next_row["eligibility"]["status"] != "pending"
                or _duration(next_row["active_wall_seconds"]) < (_duration(row["active_wall_seconds"]) if row else 0)
                or next_row["ticks"] <= (row["ticks"] if row else 0)):
            raise ValueError("invalid paused segment")
        row, previous = next_row, file_sha256(pause_path)
        refs.extend({"path": str(path), "sha256": file_sha256(path)} for path in (start_path, pause_path))
    return refs, row


def _batch_active_seconds(data_dir: Path, spec: StudySpec) -> float:
    total = 0.0
    for seed in spec.randomness.seeds:
        for arm in spec.arms:
            directory = _member(data_dir, digest_json({"seed": seed, "arm": arm.key})[:12])
            if not directory.exists():
                continue
            result = _member(directory, "result.json")
            if result.exists():
                seal = _read(_member(directory, "finalized.json"))
                if seal.get("result_sha256") != file_sha256(result):
                    raise ValueError("finalized working result changed")
                row = _read(result)
                total += _duration(row["active_wall_seconds"]) + _duration(row.get("finalization_wall_seconds", 0))
            else:
                claim = _member(directory, "attempt.json")
                _, row = _history(directory, file_sha256(claim))
                if row is None:
                    raise ValueError("unreceipted initialization cannot resume")
                total += _duration(row["active_wall_seconds"])
    return total


def _check_source(directory: Path, row: dict, claim: dict) -> None:
    source = _member(directory, f"source/{claim['run_id']}.db")
    if str(source) != row["source_database"] or file_sha256(source) != row["source_database_sha256"]:
        raise ValueError("paused source changed")
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = _member(directory, f"source/{claim['run_id']}.db{suffix}")
        if sidecar.exists():
            raise ValueError("paused source has unclosed SQLite state")
    for key in ("run_id", "seed", "arm", "expected_ticks", "config_sha256"):
        if row[key] != claim[key]:
            raise ValueError("paused attempt contract changed")
    genesis = _member(directory, "genesis.json")
    if file_sha256(genesis) != row["genesis_receipt_sha256"]:
        raise ValueError("genesis receipt changed")
    origin = _read(genesis)
    if digest_json({"state": origin["sha256"], "prng_state": origin["prng_state"]}) != row["genesis_hash"]:
        raise ValueError("genesis identity changed")
    # Ordinary mode=ro can create WAL/SHM files on Windows. This source is
    # already hash-bound, closed, sidecar-free and protected by our writer
    # lock, so immutable=1 is appropriate here. Never use it for live/WAL data.
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
        meta = store.get_meta()
        if (meta["schema_version"] != SCHEMA_VERSION
                or digest_json(json.loads(meta["config_json"])) != claim["config_sha256"]
                or int(meta["seed"]) != claim["seed"] or meta["run_id"] != claim["run_id"]):
            raise ValueError("paused database contract changed")
        if (meta["status"] != "paused" or meta["active_tick"] is not None
                or meta["next_phase"] not in (None, "NIGHT_CLOSE")
                or int(meta["tick"]) != row["ticks"] or not 0 < row["ticks"] < claim["expected_ticks"]):
            raise ValueError("paused source is not a resumable committed day")
        if not meta["prng_state"] or digest_json(meta["prng_state"]) != row["prng_state_sha256"]:
            raise ValueError("paused PRNG state changed")
        state = canonical_state_receipt(store.conn)
        if (state["sha256"] != row["source_state_hash"] or not state["references_valid"]
                or store.scalar("PRAGMA quick_check") != "ok" or not Ledger(store).reconcile()[0]
                or meta["external_agent_influenced"]):
            raise ValueError("paused source fails integrity or influence checks")
    finally:
        store.close()
    if file_sha256(source) != row["source_database_sha256"]:
        raise ValueError("paused source changed during validation")


def verify_working_history(row: dict, claim: dict, *, resolve_path: Callable[[str], Path]) -> list[str]:
    """Verify frozen segment provenance, including after portable path mapping."""
    try:
        manifest = claim["study_manifest"]
        if (digest_json(manifest) != claim["study_manifest_sha256"]
                or manifest["attempt_protocol"] != PROTOCOL
                or manifest["study"]["operations"]["pause_policy"] != "preserve_and_resume"):
            raise ValueError("working manifest mismatch")
        refs = row["working_history"]
        if not refs or len(refs) % 2 != 1:
            raise ValueError("working history must end at its final segment start")
        previous, previous_row = None, None
        for index in range(0, len(refs), 2):
            ref = refs[index]
            path = resolve_path(ref["path"])
            if file_sha256(path) != ref["sha256"]:
                raise ValueError("segment start changed")
            start = _read(path)
            if (start["attempt_claim_sha256"] != row["attempt_claim_sha256"]
                    or start["previous_pause_sha256"] != previous
                    or start["before_source_sha256"] != (previous_row["source_database_sha256"] if previous_row else None)):
                raise ValueError("segment lineage changed")
            if index + 1 < len(refs):
                pause_ref = refs[index + 1]
                pause_path = resolve_path(pause_ref["path"])
                if file_sha256(pause_path) != pause_ref["sha256"]:
                    raise ValueError("segment pause changed")
                pause = _read(pause_path)
                current = pause["row"]
                if (pause["start_sha256"] != ref["sha256"]
                        or current["execution_status"] != "paused"
                        or current["eligibility"]["status"] != "pending"
                        or current["attempt_claim_sha256"] != row["attempt_claim_sha256"]
                        or current["ticks"] <= (previous_row["ticks"] if previous_row else 0)
                        or _duration(current["active_wall_seconds"]) < (_duration(previous_row["active_wall_seconds"]) if previous_row else 0)):
                    raise ValueError("invalid pause history")
                previous, previous_row = pause_ref["sha256"], current
        if previous_row and (row["ticks"] <= previous_row["ticks"]
                or _duration(row["active_wall_seconds"]) < _duration(previous_row["active_wall_seconds"])):
            raise ValueError("final segment did not advance")
        genesis = resolve_path(row["genesis_receipt"])
        if file_sha256(genesis) != row["genesis_receipt_sha256"]:
            raise ValueError("genesis receipt changed")
        origin = _read(genesis)
        if digest_json({"state": origin["sha256"], "prng_state": origin["prng_state"]}) != row["genesis_hash"]:
            raise ValueError("genesis identity changed")
    except (KeyError, ValueError, TypeError, OSError):
        return ["working_history_invalid"]
    return []


def execute_working_attempt(*, batch: dict, spec: StudySpec, config: dict,
                            seed: int, arm: str, input_root: str | Path,
                            max_ticks: int | None = None, resume: bool = False) -> dict:
    """Advance one scripted cell; only an intact receipted pause can resume.

    The batch supervisor/CLI/UI integration is separate. This entry point
    deliberately cannot reopen old finalized attempts or published batches.
    """
    started = time.monotonic()
    spec = StudySpec.model_validate(spec.model_dump(mode="json"))
    if type(seed) is not int or seed not in spec.randomness.seeds or arm not in {item.key for item in spec.arms}:
        raise ValueError("attempt is outside the declared assignment")
    if max_ticks is not None and (type(max_ticks) is not int or max_ticks < 1):
        raise ValueError("segment tick limit must be a positive integer")
    data_dir, report_dir = _contract(batch, spec, config, Path(input_root))
    cell = digest_json({"seed": seed, "arm": arm})[:12]
    directory = _member(data_dir, cell)

    def check_disposition():
        if resume:
            if not directory.is_dir():
                raise ValueError("working attempt is missing")
            if any(_member(directory, name).exists() for name in ("source-receipt.json", "replay-receipt.json", "result.json", "finalized.json")):
                raise ValueError("finalized attempts cannot resume")
        elif directory.exists():
            raise FileExistsError("attempt already exists; only a compatible working pause can resume")

    check_disposition()
    with process_lock(_member(data_dir, "working.lock")):
        # Resolve and validate again after acquiring ownership, before Store
        # can perform any migration, cache creation, or economic write.
        _contract(batch, spec, config, Path(input_root))
        check_disposition()
        prior_batch_time = _batch_active_seconds(data_dir, spec)

        def limits() -> list[str]:
            reasons = []
            if prior_batch_time + time.monotonic() - started >= spec.operations.max_wall_seconds:
                reasons.append("wall_time_budget_exhausted")
            if _disk_bytes(data_dir) + _disk_bytes(report_dir) >= spec.operations.max_disk_bytes:
                reasons.append("disk_budget_exhausted")
            return reasons

        if limits():
            raise ValueError("working study has exhausted its cumulative budget")
        run_id = "r-" + digest_json({"batch": data_dir.name, "cell": cell})[:12]
        cfg = _arm_config(spec, config, arm)
        cfg.update(seed=seed, checkpoint_every=0, speed_delay_s=0.0,
                   checkpoint_dir=str(directory / "checkpoints"), report_dir=str(directory / "reports"))
        claim = {"protocol_version": 2, "run_id": run_id, "seed": seed, "arm": arm,
                 "expected_ticks": spec.time.horizon, "config": cfg,
                 "config_sha256": digest_json(cfg), "execution_status": "planned",
                 "study_manifest_sha256": batch["manifest_sha256"], "study_manifest": batch["manifest"]}
        claim_path = _member(directory, "attempt.json")
        if resume:
            if _read(claim_path) != claim:
                raise ValueError("working attempt claim changed")
            refs, row = _history(directory, file_sha256(claim_path))
            if row is None:
                raise ValueError("working attempt has no receipted pause")
            _check_source(directory, row, claim)
        else:
            directory.mkdir(exist_ok=False)
            (directory / "source").mkdir()
            publish_json(claim_path, claim)
            refs, row = [], {"run_id": run_id, "seed": seed, "arm": arm, "ticks": 0,
                "expected_ticks": spec.time.horizon, "execution_status": "failed", "metrics": {}, "series": {},
                "events": {}, "spend_usd": 0.0, "replay_hash": None, "genesis_hash": None,
                "source_database": str(directory / "source" / f"{run_id}.db"),
                "attempt_claim": str(claim_path), "attempt_claim_sha256": file_sha256(claim_path),
                "config_sha256": claim["config_sha256"], "active_wall_seconds": 0.0}
        prior_attempt_time = _duration(row["active_wall_seconds"])
        number = len(refs) // 2 + 1
        start_path = publish_json(directory / f"segment-{number:06d}-start.json", {
            "attempt_claim_sha256": file_sha256(claim_path),
            "previous_pause_sha256": refs[-1]["sha256"] if refs else None,
            "before_source_sha256": row.get("source_database_sha256")})
        row["working_history"] = [*refs, {"path": str(start_path), "sha256": file_sha256(start_path)}]
        store, world, reasons = None, None, []
        try:
            if resume:
                from run import open_run
                store, world, _ = open_run({}, run_id, None, data_dir=directory / "source")
            else:
                with Path(row["source_database"]).open("xb"):
                    pass
                store = Store(row["source_database"])
                store.init_run_meta(run_id, seed, cfg)
                world = World(store, cfg)
                world.initialize()
                genesis = canonical_state_receipt(store.conn, excluded_protocol_tables=("shocks", "scenario_packs"))
                genesis["prng_state"] = store.get_meta()["prng_state"]
                genesis_path = publish_json(directory / "genesis.json", genesis)
                row.update(genesis_receipt=str(genesis_path), genesis_receipt_sha256=file_sha256(genesis_path),
                           genesis_hash=digest_json({"state": genesis["sha256"], "prng_state": genesis["prng_state"]}))
                if not genesis["references_valid"]:
                    raise ValueError("genesis references are invalid")

            def guard(_tick, _summary):
                if limits():
                    world.request_pause()

            world.on_tick = guard
            remaining = spec.time.horizon - store.tick
            asyncio.run(world.run(max_ticks=min(remaining, max_ticks) if max_ticks is not None else remaining))
            reasons.extend(observe_source(world, row, ticks=spec.time.horizon,
                                          collect=lambda current: collect_outcomes(current, spec)))
            row["prng_state_sha256"] = digest_json(store.get_meta()["prng_state"])
            if not row["final_boundary"]:
                reasons.append("partial_boundary_not_supported")
            if row.get("provider_calls", 0) or row.get("spend_usd", 0):
                reasons.append("provider_free_contract_violated")
            if row["external_agent_influenced"] or not row["reconciled"] or not row["database_integrity"]:
                reasons.append("working_source_integrity_failed")
        except Exception as exc:
            row["execution_status"], row["error_type"] = "failed", type(exc).__name__
            if store is not None:
                row["ticks"] = store.tick
            reasons.append("execution_failed")
        finally:
            if world is not None:
                world.close()
            elif store is not None:
                store.close()
        row["source_database_sha256"] = file_sha256(row["source_database"])
        try:
            _contract(batch, spec, config, Path(input_root))
        except (OSError, ValueError, RuntimeError):
            reasons.append("study_contract_changed_during_execution")
        row["active_wall_seconds"] = prior_attempt_time + time.monotonic() - started
        reasons.extend(limits())
        if row["execution_status"] == "paused" and not reasons:
            row["eligibility"] = {"status": "pending", "reasons": ["working_attempt_paused", "incomplete_horizon"]}
            publish_json(directory / f"segment-{number:06d}-pause.json", {
                "start_sha256": file_sha256(start_path), "row": row})
            return row
        if reasons:
            row["execution_status"] = "failed"
        final_started = time.monotonic()

        def final_checks():
            final_reasons = []
            try:
                _contract(batch, spec, config, Path(input_root))
            except (OSError, ValueError, RuntimeError):
                final_reasons.append("study_contract_changed_during_finalization")
            row["finalization_wall_seconds"] = time.monotonic() - final_started
            return [*final_reasons, *limits()]

        result = finalize_attempt(row, attempt_dir=directory, reasons=reasons, final_checks=final_checks)
        # Later cells consume the closed result's cumulative timings. Bind the
        # whole result before letting it contribute to another cell's budget;
        # a crash before this seal leaves that accounting unresolved.
        publish_json(directory / "finalized.json", {"result_sha256": file_sha256(directory / "result.json")})
        return result

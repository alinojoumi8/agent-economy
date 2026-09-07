"""Bind checkpoint continuations to frozen study inputs and their actual interval."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Callable

from engine.store import Store
from research.artifacts import digest_json, file_sha256, publish_json
from research.checkpoint_origins import continuation_config, open_continuation, verify_checkpoint
from research.studies import StudySpec
from research.working_contracts import input_prefixes


def checkpoint_claim_fields(spec: StudySpec, manifest: dict, data_dir: Path,
                            seed: int, arm: str) -> dict:
    """Verify the owned snapshot before allocating an attempt directory."""
    from research.study_runner import arm_interventions

    declared = next(item for item in spec.origin.sources if item.seed == seed)
    artifact = next(item for item in spec.inputs if item.key == declared.input_key)
    receipt = manifest["checkpoint_origins"][str(seed)]
    path = data_dir.absolute() / "context" / "inputs" / f"{artifact.sha256}.blob"
    if (digest_json(receipt) != declared.receipt_sha256
            or receipt["database_sha256"] != artifact.sha256
            or receipt["seed"] != seed or receipt["tick"] != spec.origin.tick):
        raise ValueError("checkpoint snapshot differs from its declared initial condition")
    verify_checkpoint(path, receipt, max_bytes=spec.operations.max_disk_bytes,
                      config={**manifest["resolved_config"], "seed": seed})
    return {"protocol_version": 4, "study_manifest": manifest,
            "study_manifest_sha256": digest_json(manifest),
            "checkpoint_origin": {"database": str(path), "receipt": receipt,
                "interventions": arm_interventions(spec, arm),
                "max_bytes": spec.operations.max_disk_bytes}}


def origin_row_fields(claim: dict) -> dict:
    receipt = claim["checkpoint_origin"]["receipt"]
    return {"origin_state_hash": receipt["initial_state_sha256"],
            "origin_tick": receipt["tick"], "origin_receipt_sha256": digest_json(receipt)}


def verify_origin_identity(row: dict, claim: dict, *,
                           resolve_path: Callable[[str], Path] = Path) -> dict:
    """Verify the origin even when a private bundle remaps the original paths."""
    from research.study_runner import _arm_config, arm_interventions

    manifest = claim["study_manifest"]
    spec = StudySpec.model_validate(manifest["study"])
    if (claim["protocol_version"] != 4 or spec.origin is None
            or digest_json(manifest) != claim["study_manifest_sha256"]
            or digest_json(manifest["resolved_config"]) != spec.model.resolved_config_sha256
            or manifest.get("origin_contract") != "admitted-state-with-recorded-continuation-v1"):
        raise ValueError("checkpoint attempt manifest changed")
    declared = next((item for item in spec.origin.sources if item.seed == claim["seed"]), None)
    if declared is None:
        raise ValueError("checkpoint attempt has an undeclared source seed")
    artifact = next(item for item in spec.inputs if item.key == declared.input_key)
    binding = claim["checkpoint_origin"]
    receipt = binding["receipt"]
    expected_path = resolve_path(row["attempt_claim"]).parent.parent / "context" / "inputs" / f"{artifact.sha256}.blob"
    if (set(binding) != {"database", "receipt", "interventions", "max_bytes"}
            or resolve_path(binding["database"]) != expected_path
            or binding["max_bytes"] != spec.operations.max_disk_bytes
            or binding["interventions"] != arm_interventions(spec, claim["arm"])
            or digest_json(receipt) != declared.receipt_sha256
            or receipt != manifest["checkpoint_origins"][str(claim["seed"])]
            or receipt["database_sha256"] != artifact.sha256
            or receipt["seed"] != claim["seed"] or receipt["tick"] != spec.origin.tick
            or any(row.get(key) != value for key, value in origin_row_fields(claim).items())
            or row.get("genesis_hash") is not None or "genesis_receipt" in row):
        raise ValueError("checkpoint attempt initial condition changed")
    baseline = {**manifest["resolved_config"], "seed": claim["seed"]}
    if continuation_config(claim["config"]) != continuation_config(_arm_config(spec, baseline, claim["arm"])):
        raise ValueError("checkpoint attempt changes undeclared economic configuration")
    return verify_checkpoint(expected_path, receipt, max_bytes=binding["max_bytes"], config=baseline)


def verify_origin_prefix(store: Store, claim: dict) -> None:
    """Inherited recorded inputs remain immutable, including across day pauses."""
    receipt = claim["checkpoint_origin"]["receipt"]
    meta = store.get_meta()
    prefix = receipt["recorded_inputs"]
    if (meta["run_id"] != claim["run_id"] or meta["parent_run_id"] != receipt["run_id"] or meta["fork_tick"] != receipt["tick"]
            or meta["seed"] != receipt["seed"] or store.tick < receipt["tick"]
            or meta["participant_influenced"] or meta["external_agent_influenced"]
            or input_prefixes(store, {prefix["last_id"]})[prefix["last_id"]] != prefix):
        raise ValueError("checkpoint continuation changed its inherited history")


def replay_checkpoint(row: dict, claim: dict, attempt_dir: Path) -> Path:
    """Execute the recorded interval from an independent copy of the origin."""
    origin = verify_origin_identity(row, claim)
    binding = claim["checkpoint_origin"]
    path = attempt_dir / "replay" / f"{row['run_id']}.db"
    config = {**claim["config"], "checkpoint_dir": str(attempt_dir / "replay" / "checkpoints"),
              "report_dir": str(attempt_dir / "replay" / "reports")}
    store, world = open_continuation(binding["database"], origin, path,
        run_id=row["run_id"], config=config, interventions=binding["interventions"],
        max_bytes=binding["max_bytes"], replay_source=row["source_database"],
        replay_source_sha256=row["source_database_sha256"])
    try:
        asyncio.run(world.run(max_ticks=row["expected_ticks"] - origin["tick"]))
        verify_origin_prefix(store, claim)
    finally:
        world.close()
    return path


def execute_checkpoint_attempt(*, run_id: str, seed: int, arm: str, config: dict,
                               ticks: int, data_dir: Path, collect: Callable[[Store], dict],
                               origin_fields: dict) -> dict:
    """Claim one frozen continuation; failures remain assigned diagnostic rows."""
    from research.attempts import finalize_attempt, observe_source

    cell = digest_json({"seed": seed, "arm": arm})[:12]
    label, run_id = run_id, "r-" + digest_json({"batch": data_dir.name, "cell": cell})[:12]
    directory = data_dir / cell
    cfg = json.loads(json.dumps(config))
    cfg.update(seed=seed, checkpoint_every=0, speed_delay_s=0.0,
               checkpoint_dir=str(directory / "checkpoints"), report_dir=str(directory / "reports"))
    claim = {**origin_fields, "run_id": run_id, "label": label, "seed": seed, "arm": arm,
             "expected_ticks": ticks, "config": cfg, "config_sha256": digest_json(cfg),
             "execution_status": "planned"}
    claim_path = directory / "attempt.json"
    row = {"run_id": run_id, "seed": seed, "arm": arm, "ticks": claim["checkpoint_origin"]["receipt"]["tick"],
           "expected_ticks": ticks, "execution_status": "failed", "reconciled": False,
           "reconciliation": None, "final_boundary": False, "external_agent_influenced": False,
           "metrics": {}, "series": {}, "events": {}, "spend_usd": 0.0, "causal_trace": [],
           "genesis_hash": None, "event_hash": None, "replay_hash": None,
           "source_database": str(directory / "source" / f"{run_id}.db"),
           "attempt_claim": str(claim_path), "config_sha256": digest_json(cfg), **origin_row_fields(claim)}
    verify_origin_identity(row, claim)
    directory.mkdir(parents=True, exist_ok=False)
    publish_json(claim_path, claim)
    row["attempt_claim_sha256"] = file_sha256(claim_path)
    store, world, reasons = None, None, []
    try:
        binding = claim["checkpoint_origin"]
        store, world = open_continuation(binding["database"], binding["receipt"], row["source_database"],
            run_id=run_id, config=cfg, interventions=binding["interventions"], max_bytes=binding["max_bytes"])
        publish_json(directory / "running.json", {**claim, "execution_status": "running"})
        asyncio.run(world.run(max_ticks=ticks - store.tick))
        verify_origin_prefix(store, claim)
        reasons.extend(observe_source(world, row, ticks=ticks, collect=collect))
    except Exception as exc:
        row.update(execution_status="failed", error_type=type(exc).__name__)
        if store is not None:
            row["ticks"] = store.tick
        reasons.append("execution_failed")
    finally:
        if world is not None:
            world.close()
        elif store is not None:
            store.close()
    return finalize_attempt(row, attempt_dir=directory, reasons=reasons)

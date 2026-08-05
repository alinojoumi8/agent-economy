"""Agent Economy entrypoint.

  python run.py --config runs/base.yaml                 # serve dashboard + world (paused)
  python run.py --config runs/base.yaml --ticks 30      # headless: run 30 ticks, report, exit
  python run.py --config runs/production.yaml --preflight       # validate real-provider config
  python run.py --config runs/production.yaml --preflight-live  # authenticate + confirm models
  python run.py --config runs/base.yaml --resume RUNID  # resume an existing run db
  python run.py --config runs/base.yaml --replay RUNID  # exact replay from stored LLM calls
  python run.py --config runs/base.yaml --fork RUNID@TICK   # what-if branch from a checkpoint
  python run.py --report RUNID                          # generate report for a stored run
  python run.py --experiment runs/experiments/x.yaml    # multi-seed experiment + comparison report
  python run.py --acceptance-report RUNID               # evaluate persisted production evidence
  python run.py --config runs/acceptance/production.yaml --acceptance-run  # paid; approval required

One process: FastAPI serves the static dashboard and drives the world loop.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from dotenv import load_dotenv

from engine.semantics import (
    UnsupportedEngineSemantics,
    semantics_version,
    validate_engine_semantics_version,
)
from engine.store import Store
from llm.gateway import Gateway
from llm.readiness import validate_llm_config
from world.loop import World, new_run_id
from observability import configure_logging, get_logger, log_event as operational_log
from run_config import load_config

DATA_DIR = Path("data/runs")
DEFAULT_CONFIG = "runs/v2-live-minimax.yaml"
logger = get_logger("cli")
REPLAY_INPUT_TABLES = (
    "dataset_manifests",
    "calibration_targets",
    "scenario_packs",
)


async def provider_preflight(config: dict, *, live: bool = False) -> dict:
    report = validate_llm_config(config, raise_on_error=False)
    if not report["ready"] or not live:
        return {**report, "live_checked": False}
    store = Store(":memory:")
    store.init_run_meta("preflight", int(config.get("seed", 42)), config)
    return await Gateway(store, config).preflight(live=True)


def require_live_inference_approval(config: dict, *, approved: bool) -> None:
    """Fail closed before a command can dispatch any configured live provider."""
    from reports.acceptance import uses_paid_providers

    if uses_paid_providers(config) and not approved:
        raise SystemExit(
            "live provider run requires explicit --approve-live-inference authorization"
        )


def _recorded_replay_inputs(source: Store) -> dict[str, list[dict]]:
    """Capture external/input rows so replay never rereads mutable manifests."""
    return {
        table: [dict(row) for row in source.query(f'SELECT * FROM "{table}" ORDER BY id')]
        for table in REPLAY_INPUT_TABLES
    }


def _restore_replay_inputs(store: Store, inputs: dict[str, list[dict]]) -> None:
    """Replace freshly loaded reference data with the source run's pinned rows."""
    store.execute("DELETE FROM calibration_targets")
    store.execute("DELETE FROM dataset_manifests")
    store.execute("DELETE FROM scenario_packs")
    for table in REPLAY_INPUT_TABLES:
        for row in inputs[table]:
            store.insert(table, **row)
    store.commit()


def _hydrate_resumed_world(world: World, meta, config: dict) -> None:
    """Restore persisted Observatory lifecycle state without reviving a task."""
    persisted = str(meta["status"] or "paused")
    # A process-local task cannot survive a restart. Treat a stale running
    # marker as paused while retaining all completed tick data.
    world.status = "paused" if persisted == "running" else persisted
    if world.status != persisted:
        world.store.set_meta(status=world.status)
        world.store.commit()
    if world.status == "finished":
        report = Path(str(config.get("report_dir", "reports/out"))) / (
            f"run_{meta['run_id']}_t{int(meta['tick'])}.html")
        if report.exists():
            world.last_report_path = str(report)


LLM_OUTPUT_BUDGET_KEYS = (
    "reporter_max_tokens",
    "newsroom_max_tokens",
    "conversation_max_tokens",
)


def activate_llm_output_budgets_for_run(world: World, profile: dict) -> dict:
    """Persist a forward-only output-budget upgrade for a completed run tick."""
    stored_llm = world.config.setdefault("llm", {})
    profile_llm = profile.get("llm", {}) or {}
    stored_contract = stored_llm.get("route_contract")
    profile_contract = profile_llm.get("route_contract")
    if stored_contract != profile_contract:
        raise RuntimeError(
            "output-budget profile route contract does not match the stored run")

    budgets = {}
    for key in LLM_OUTPUT_BUDGET_KEYS:
        if key not in profile_llm or int(profile_llm[key]) <= 0:
            raise ValueError(
                f"output-budget profile requires a positive llm.{key}")
        budgets[key] = int(profile_llm[key])

    existing_activation = stored_llm.get("output_budget_activation_tick")
    existing_budgets = {key: stored_llm.get(key) for key in LLM_OUTPUT_BUDGET_KEYS}
    if existing_activation is not None:
        if existing_budgets != budgets:
            raise RuntimeError(
                "stored output-budget activation already uses different values")
        return {"activation_tick": int(existing_activation), **budgets}
    if all(existing_budgets[key] == budgets[key] for key in LLM_OUTPUT_BUDGET_KEYS):
        # The profile was present at genesis, so no forward boundary is needed.
        return {"activation_tick": 1, **budgets}
    if any(value is not None for value in existing_budgets.values()):
        raise RuntimeError(
            "stored run has unversioned output budgets; refusing a partial upgrade")

    meta = world.store.get_meta()
    if meta["active_tick"] is not None:
        raise RuntimeError(
            "output budgets can only be activated at a completed tick boundary")
    activation_tick = int(meta["tick"]) + 1
    stored_llm.update(budgets)
    stored_llm["output_budget_activation_tick"] = activation_tick
    world.store.set_meta(config_json=json.dumps(world.config, sort_keys=True))
    world.store.log_event(
        int(meta["tick"]),
        "llm_output_budget_activation",
        {"activation_tick": activation_tick, **budgets},
        phase="OPERATOR",
        importance=2.0,
    )
    world.store.commit()
    return {"activation_tick": activation_tick, **budgets}


def activate_supply_recovery_for_run(
        world: World, *, target_headcount: int) -> dict:
    """Persist a replay-safe, forward-only supply/labor recovery boundary."""
    if int(world.config.get("engine_semantics_version", 1)) < 7:
        raise ValueError("supply recovery requires engine semantics 7")
    target = max(1, int(target_headcount))
    firms = world.config.setdefault("firms", {})
    behavior = world.config.setdefault("behavior", {})
    workforce_tick = firms.get("workforce_recovery_activation_tick")
    shopping_tick = behavior.get(
        "inventory_aware_shopping_activation_tick")
    existing_target = firms.get("workforce_recovery_target_headcount")
    meta = world.store.get_meta()
    active_tick = meta["active_tick"]
    next_untouched_tick = (
        int(active_tick) + 1
        if active_tick is not None
        else int(meta["tick"]) + 1
    )

    if workforce_tick is not None or shopping_tick is not None:
        if (
            workforce_tick is None
            or shopping_tick is None
            or int(workforce_tick) != int(shopping_tick)
            or existing_target is None
        ):
            raise RuntimeError("stored supply recovery activation is incomplete")
        if int(existing_target) != target:
            raise RuntimeError(
                "supply recovery is already active with target headcount "
                f"{int(existing_target)}")
        activation_tick = int(workforce_tick)
    else:
        activation_tick = next_untouched_tick
        firms["workforce_recovery_activation_tick"] = activation_tick
        firms["workforce_recovery_target_headcount"] = target
        behavior[
            "inventory_aware_shopping_activation_tick"
        ] = activation_tick

    operational_tick_value = firms.get(
        "workforce_recovery_operational_activation_tick")
    advanced_fields = {
        "recapitalization_tick": firms.get(
            "workforce_recovery_recapitalization_tick"),
        "batch_size": firms.get("workforce_recovery_batch_size"),
        "excluded_sectors": firms.get(
            "workforce_recovery_excluded_sectors"),
        "capital_per_worker": firms.get(
            "workforce_recovery_capital_per_worker_cents"),
        "job_application_tick": behavior.get(
            "job_application_aware_activation_tick"),
    }
    if operational_tick_value is None:
        if any(value is not None for value in advanced_fields.values()):
            raise RuntimeError(
                "stored operational supply recovery activation is incomplete")
        operational_tick = max(activation_tick, next_untouched_tick)
        firms[
            "workforce_recovery_operational_activation_tick"
        ] = operational_tick
        firms[
            "workforce_recovery_recapitalization_tick"
        ] = operational_tick
        firms["workforce_recovery_batch_size"] = 4
        firms["workforce_recovery_excluded_sectors"] = [
            "health", "insurance"]
        firms[
            "workforce_recovery_capital_per_worker_cents"
        ] = max(0, int(firms.get(
            "opening_capital_per_worker_cents", 500_000)))
        behavior[
            "job_application_aware_activation_tick"
        ] = operational_tick
    else:
        operational_tick = int(operational_tick_value)
        if (
            advanced_fields["recapitalization_tick"] is None
            or int(advanced_fields["recapitalization_tick"]) != operational_tick
            or advanced_fields["batch_size"] is None
            or advanced_fields["excluded_sectors"] is None
            or advanced_fields["capital_per_worker"] is None
            or advanced_fields["job_application_tick"] is None
            or int(advanced_fields["job_application_tick"]) != operational_tick
        ):
            raise RuntimeError(
                "stored operational supply recovery activation is incomplete")

    minimum_wage_value = firms.get(
        "workforce_recovery_min_wage_cents")
    wage_floor_tick_value = firms.get(
        "workforce_recovery_wage_floor_activation_tick")
    if minimum_wage_value is None and wage_floor_tick_value is None:
        firms["workforce_recovery_min_wage_cents"] = 250_000
        firms[
            "workforce_recovery_wage_floor_activation_tick"
        ] = max(operational_tick, next_untouched_tick)
    elif minimum_wage_value is None or wage_floor_tick_value is None:
        raise RuntimeError(
            "stored workforce recovery wage floor is incomplete")
    elif int(wage_floor_tick_value) < operational_tick:
        raise RuntimeError(
            "workforce recovery wage floor predates operational activation")

    persisted_config = json.loads(meta["config_json"])
    if persisted_config != world.config:
        world.store.set_meta(
            config_json=json.dumps(world.config, sort_keys=True))
        world.store.commit()

    expired_incompatible_offers = (
        world.economy.labor.expire_incompatible_offers(
            int(meta["tick"]), phase="FINALIZE"))
    if expired_incompatible_offers:
        world.store.commit()
        world.checkpoint(
            int(meta["tick"]),
            reason="supply_recovery_currency_cleanup",
        )

    # ContextBuilder caches activation thresholds at construction. Keep the
    # already-open live process aligned with the newly persisted config.
    world.runtime.ctx.inventory_aware_shopping_activation_tick = (
        activation_tick)
    return {
        "activation_tick": activation_tick,
        "target_headcount": target,
        "operational_activation_tick": operational_tick,
    }


def open_run(config: dict, resume: str | None, replay: str | None, *,
             data_dir: Path = DATA_DIR) -> tuple[Store, World, str]:
    data_dir.mkdir(parents=True, exist_ok=True)
    if resume:
        run_id = resume
        db = data_dir / f"{run_id}.db"
        if not db.exists():
            sys.exit(f"run database not found: {db}")
        store = Store(str(db))
        try:
            meta = store.get_meta()
            stored_cfg = json.loads(meta["config_json"])
            # Markerless databases predate completed-day finalization and must keep
            # their original phase/metric/prompt behavior for exact replay.
            stored_cfg["engine_semantics_version"] = semantics_version(
                stored_cfg, default=1)
        except Exception:
            store.close()
            raise
        stored_cfg.update({k: v for k, v in config.items() if k in ("speed_delay_s",)})
        world = World(store, stored_cfg)
        _hydrate_resumed_world(world, meta, stored_cfg)
        world.restore_prng_state()
        return store, world, run_id
    if replay:
        source_db = data_dir / f"{replay}.db"
        if not source_db.exists():
            sys.exit(f"run database not found: {source_db}")
        source_store = Store(str(source_db), create=False, read_only=True)
        try:
            source_meta = source_store.get_meta()
            replay_cfg = json.loads(source_meta["config_json"])
            replay_cfg["engine_semantics_version"] = semantics_version(
                replay_cfg, default=1)
            source_tick = int(source_meta["tick"])
            source_seed = int(source_meta["seed"])
            replay_inputs = _recorded_replay_inputs(source_store)
        finally:
            source_store.close()
        replay_cfg.update({k: v for k, v in config.items() if k in ("speed_delay_s",)})
        replay_cfg.update({
            "seed": source_seed,
            "replay_source_path": str(source_db.resolve()),
            "replay_source_run_id": replay,
            "replay_source_tick": source_tick,
        })
        run_id = f"replay-{replay}-{new_run_id()}"
        store = Store(str(data_dir / f"{run_id}.db"))
        store.init_run_meta(run_id, source_seed, replay_cfg, parent_run_id=replay, fork_tick=0)
        # Restore source-owned external inputs before genesis.  A replay must
        # never depend on the path (or current contents) of the mutable
        # dataset manifest recorded in the source configuration.
        _restore_replay_inputs(store, replay_inputs)
        missing_manifest = object()
        recorded_manifest = replay_cfg.pop("dataset_manifest", missing_manifest)
        try:
            world = World(store, replay_cfg, replay=True)
            world.initialize()
        finally:
            if recorded_manifest is not missing_manifest:
                replay_cfg["dataset_manifest"] = recorded_manifest
        return store, world, run_id
    config = dict(config)
    # Unversioned callers retain the historical v2 contract.  The checked-in
    # v2 world profiles opt into semantics 4+ explicitly.
    config["engine_semantics_version"] = semantics_version(config, default=2)
    run_id = new_run_id()
    store = Store(str(data_dir / f"{run_id}.db"))
    try:
        store.init_run_meta(run_id, int(config.get("seed", 42)), config)
        world = World(store, config)
        world.initialize()
        return store, world, run_id
    except BaseException:
        store.close()
        raise


def fork_run(spec: str, data_dir: Path = DATA_DIR, *, upgrade_semantics: int | None = None) -> str:
    """Fork a new run from a checkpoint (TECH-SPEC §13 what-if branching).

    `spec` is either a checkpoint .db path or `RUNID@TICK` (uses the newest
    checkpoint at or before TICK). The copy gets a fresh run id with
    parent_run_id + fork_tick set, so lineage is queryable.
    """
    import shutil

    src = Path(spec)
    if not src.exists() and "@" in spec:
        run_id, _, tick_s = spec.partition("@")
        parent_db = data_dir / f"{run_id}.db"
        if not parent_db.exists():
            sys.exit(f"run database not found: {parent_db}")
        parent = Store(str(parent_db))
        row = parent.query_one(
            "SELECT path, tick FROM checkpoints WHERE tick<=? ORDER BY tick DESC, id DESC LIMIT 1",
            (int(tick_s),))
        parent.close()
        if not row:
            sys.exit(f"no checkpoint at or before tick {tick_s} for run {run_id}")
        src = Path(row["path"])
    if not src.exists():
        sys.exit(f"checkpoint not found: {src}")

    new_id = new_run_id()
    data_dir.mkdir(parents=True, exist_ok=True)
    dest = data_dir / f"{new_id}.db"
    shutil.copyfile(src, dest)
    try:
        store = Store(str(dest))
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    meta = store.get_meta()
    config = json.loads(meta["config_json"])
    try:
        old_semantics = semantics_version(config, default=1)
        new_semantics = (validate_engine_semantics_version(upgrade_semantics)
                         if upgrade_semantics is not None else old_semantics)
    except UnsupportedEngineSemantics as exc:
        store.close()
        dest.unlink(missing_ok=True)
        sys.exit(str(exc))
    config["engine_semantics_version"] = old_semantics
    if upgrade_semantics is not None:
        if new_semantics <= old_semantics:
            store.close()
            dest.unlink(missing_ok=True)
            sys.exit(f"semantic upgrade must exceed stored version {old_semantics}")
        config["engine_semantics_version"] = new_semantics
    store.set_meta(run_id=new_id, parent_run_id=meta["run_id"], fork_tick=int(meta["tick"]),
                   status="paused", config_json=json.dumps(config, sort_keys=True))
    store.log_event(int(meta["tick"]), "fork", {
        "parent_run_id": meta["run_id"], "fork_tick": int(meta["tick"]),
        "new_run_id": new_id}, phase="NIGHT_CLOSE", importance=2.0)
    if upgrade_semantics is not None:
        store.log_event(int(meta["tick"]), "semantic_upgrade", {
            "parent_run_id": meta["run_id"], "old_version": old_semantics,
            "new_version": new_semantics}, phase="NIGHT_CLOSE", importance=4.0)
    store.commit()
    store.close()
    operational_log(logger, logging.INFO, "run.fork.created",
                    parent_run_id=meta["run_id"], fork_tick=int(meta["tick"]),
                    run_id=new_id)
    print(f"[agent-economy] forked {meta['run_id']} @ t{meta['tick']} -> {new_id}")
    return new_id


async def headless(world: World, ticks: int) -> None:
    await world.run(max_ticks=ticks)


def _close_run(world, store: Store) -> None:
    """Close a real World while retaining compatibility with lightweight callers."""
    close_world = getattr(world, "close", None)
    if callable(close_world):
        close_world()
    else:
        store.close()


def _recorded_acceptance_side_effects(
        source, target_tick: int) -> tuple[dict, dict, list[dict]]:
    """Load acceptance-run effects that sit outside the deterministic world loop."""
    checkpoints: dict[int, dict] = {}
    table_exists = source.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='acceptance_checkpoints'"
    ).fetchone()
    if table_exists is not None:
        for row in source.execute(
            "SELECT scheduled_tick,question,status,prediction_id,detail "
            "FROM acceptance_checkpoints WHERE scheduled_tick<=? "
            "AND prediction_id IS NOT NULL ORDER BY scheduled_tick,question",
            (target_tick,),
        ).fetchall():
            prediction_id = int(row["prediction_id"])
            if prediction_id in checkpoints:
                raise RuntimeError(
                    "recorded acceptance checkpoints reuse prediction_id "
                    f"{prediction_id}")
            checkpoints[prediction_id] = dict(row)

    completion_events: dict[int, list[dict]] = {}
    for row in source.execute(
        "SELECT id,tick,phase,subject_type,subject_id,importance,payload_json "
        "FROM events WHERE kind='acceptance_checkpoint_completed' AND tick<=? "
        "ORDER BY id", (target_tick,),
    ).fetchall():
        try:
            payload = json.loads(row["payload_json"] or "{}")
            prediction_id = int(payload["prediction_id"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "recorded acceptance completion has an invalid prediction reference"
            ) from exc
        completion_events.setdefault(prediction_id, []).append({
            **dict(row), "payload": payload,
        })

    missed_events = []
    for row in source.execute(
        "SELECT id,tick,phase,subject_type,subject_id,importance,payload_json "
        "FROM events WHERE kind='acceptance_checkpoint_missed' AND tick<=? "
        "ORDER BY id", (target_tick,),
    ).fetchall():
        try:
            payload = json.loads(row["payload_json"] or "{}")
            int(payload["scheduled_tick"])
            str(payload["question"])
            str(payload["detail"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "recorded missed acceptance checkpoint has an invalid payload"
            ) from exc
        missed_events.append({**dict(row), "payload": payload})
    return checkpoints, completion_events, missed_events


async def replay_headless(world: World, target_tick: int) -> None:
    """Replay world ticks plus externally orchestrated Oracle side effects."""
    source = world.gateway.replay_conn
    if source is None:
        await headless(world, target_tick)
        return
    checkpoints, completion_events, missed_events = _recorded_acceptance_side_effects(
        source, target_tick)
    predictions = source.execute(
        "SELECT id, asked_tick, question FROM predictions WHERE asked_tick<=? "
        "ORDER BY asked_tick, id", (target_tick,)).fetchall()
    predictions_by_tick: dict[int, list] = {}
    for prediction in predictions:
        predictions_by_tick.setdefault(
            int(prediction["asked_tick"]), []).append(prediction)
    missed_by_tick: dict[int, list[dict]] = {}
    for event in missed_events:
        missed_by_tick.setdefault(int(event["tick"]), []).append(event)

    consumed_checkpoint_ids: set[int] = set()
    consumed_completion_ids: set[int] = set()
    for action_tick in sorted(set(predictions_by_tick) | set(missed_by_tick)):
        if world.store.tick < action_tick:
            await world.run(max_ticks=action_tick - world.store.tick)
        if world.store.tick != action_tick:
            raise RuntimeError(
                f"replay paused at tick {world.store.tick} before external tick "
                f"{action_tick}")

        for prediction in predictions_by_tick.get(action_tick, []):
            source_prediction_id = int(prediction["id"])
            result = await world.oracle.ask(str(prediction["question"]))
            try:
                replay_prediction_id = int(result["prediction_id"])
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError(
                    "replayed Oracle call produced no valid prediction reference"
                ) from exc

            checkpoint = checkpoints.get(source_prediction_id)
            if checkpoint is not None:
                from reports.acceptance import _record_checkpoint

                _record_checkpoint(
                    world.store, int(checkpoint["scheduled_tick"]),
                    str(checkpoint["question"]), str(checkpoint["status"]),
                    prediction_id=replay_prediction_id, detail=checkpoint["detail"])
                consumed_checkpoint_ids.add(source_prediction_id)

            for event in completion_events.get(source_prediction_id, []):
                payload = dict(event["payload"])
                payload["prediction_id"] = replay_prediction_id
                world.store.log_event(
                    int(event["tick"]), "acceptance_checkpoint_completed", payload,
                    phase=event["phase"], subject_type=event["subject_type"],
                    subject_id=event["subject_id"],
                    importance=float(event["importance"]))
                consumed_completion_ids.add(int(event["id"]))
                world.store.commit()

        for event in missed_by_tick.get(action_tick, []):
            from reports.acceptance import _record_checkpoint

            payload = dict(event["payload"])
            _record_checkpoint(
                world.store, int(payload["scheduled_tick"]),
                str(payload["question"]), "missed", detail=str(payload["detail"]))
            world.store.log_event(
                int(event["tick"]), "acceptance_checkpoint_missed", payload,
                phase=event["phase"], subject_type=event["subject_type"],
                subject_id=event["subject_id"], importance=float(event["importance"]))
            world.store.commit()

    missing_checkpoints = sorted(set(checkpoints) - consumed_checkpoint_ids)
    missing_events = sorted(
        int(event["id"])
        for events in completion_events.values() for event in events
        if int(event["id"]) not in consumed_completion_ids)
    if missing_checkpoints or missing_events:
        raise RuntimeError(
            "recorded acceptance side effects reference missing Oracle predictions: "
            f"checkpoints={missing_checkpoints}, events={missing_events}")
    if world.store.tick < target_tick:
        await world.run(max_ticks=target_tick - world.store.tick)


def main() -> None:
    load_dotenv()
    configure_logging()
    ap = argparse.ArgumentParser(description="Agent Economy")
    ap.add_argument("--config", default=DEFAULT_CONFIG,
                    help="world config (default: 1,000-agent MiniMax M3 live profile)")
    ap.add_argument("--ticks", type=int, default=None,
                    help="run N ticks; with --serve, set a hard N-tick session boundary")
    ap.add_argument("--resume", default=None, help="resume run id")
    ap.add_argument(
        "--activate-supply-recovery",
        action="store_true",
        help=(
            "only with --resume/--fork: activate inventory-aware shopping and "
            "workforce recovery after the current partial tick"
        ),
    )
    ap.add_argument(
        "--supply-recovery-target-headcount",
        type=int,
        default=None,
        help=(
            "with --activate-supply-recovery: forward-only recovery headcount "
            "per firm (default: persisted workforce_recovery_target_headcount, "
            "else 80). Never aliases genesis firms.target_headcount."
        ),
    )
    ap.add_argument(
        "--activate-llm-output-budgets",
        action="store_true",
        help=(
            "only with --resume/--fork: persist the configured reporter, "
            "newsroom, and conversation output budgets at the next tick"
        ),
    )
    ap.add_argument("--replay", default=None, help="replay run id from stored LLM responses")
    ap.add_argument("--fork", default=None,
                    help="fork a what-if branch: checkpoint .db path or RUNID@TICK")
    ap.add_argument("--upgrade-semantics", type=int, default=None,
                    help="only with --fork: explicitly upgrade the child engine semantics")
    ap.add_argument("--report", default=None, help="generate end-of-run report for run id and exit")
    ap.add_argument("--export-static", default=None,
                    help="export a self-contained replay from a run id or database path")
    ap.add_argument("--output", default=None, help="output path for export commands")
    ap.add_argument("--experiment", default=None,
                    help="run a multi-seed experiment from a spec yaml (P1 R14) and exit")
    ap.add_argument("--counterfactual", default=None,
                    help="run a validated paired-seed scenario pack and exit")
    ap.add_argument("--seeds", type=int, default=20,
                    help="paired seed count for --counterfactual (default: 20)")
    ap.add_argument("--scenario-ticks", type=int, default=None,
                    help="override a scenario pack's horizon")
    ap.add_argument("--refresh-datasets", default=None,
                    help="explicitly refresh and repin a dataset manifest (networked)")
    ap.add_argument("--refresh-dataset-key", action="append", default=None,
                    help="with --refresh-datasets, refresh only this dataset key (repeatable)")
    ap.add_argument("--verify-datasets", default=None,
                    help="verify pinned checksums and vintages without network access")
    ap.add_argument("--acceptance-report", default=None,
                    help="evaluate a run id or .db path and write JSON/Markdown acceptance evidence")
    ap.add_argument("--acceptance-run", action="store_true",
                    help="execute the configured acceptance horizon and scheduled Oracle checks")
    ap.add_argument("--approve-live-inference", "--approve-live-spend",
                    dest="approve_live_inference", action="store_true",
                    help="explicitly authorize real-provider inference")
    ap.add_argument("--experiment-evidence", default=None,
                    help="experiment JSON to attach to an acceptance receipt")
    ap.add_argument("--phenomena-evidence", default=None,
                    help="reviewed phenomena YAML to attach to an acceptance receipt")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--serve", action="store_true", help="serve dashboard even with --ticks")
    ap.add_argument("--preflight", action="store_true",
                    help="validate provider routes and required environment variables, then exit")
    ap.add_argument("--preflight-live", action="store_true",
                    help="also authenticate and confirm configured models through provider /models APIs")
    args = ap.parse_args()
    if args.activate_supply_recovery and not (args.resume or args.fork):
        ap.error("--activate-supply-recovery requires --resume or --fork")
    if args.activate_supply_recovery and args.replay:
        ap.error("--activate-supply-recovery cannot modify a replay")
    if args.activate_llm_output_budgets and not (args.resume or args.fork):
        ap.error("--activate-llm-output-budgets requires --resume or --fork")
    if args.activate_llm_output_budgets and args.replay:
        ap.error("--activate-llm-output-budgets cannot modify a replay")
    mode = ("dataset_refresh" if args.refresh_datasets else
            "dataset_verify" if args.verify_datasets else
            "counterfactual" if args.counterfactual else
            "static_export" if args.export_static else "experiment" if args.experiment else
            "acceptance_report" if args.acceptance_report else
            "acceptance_run" if args.acceptance_run else "report" if args.report else
            "preflight" if (args.preflight or args.preflight_live) else
            "fork" if args.fork else "replay" if args.replay else
            "resume" if args.resume else "run")
    operational_log(logger, logging.INFO, "cli.command.started", mode=mode)

    if args.refresh_datasets:
        from research.datasets import refresh_datasets
        selected = set(args.refresh_dataset_key) if args.refresh_dataset_key else None
        print(json.dumps(refresh_datasets(args.refresh_datasets, keys=selected), indent=2))
        return

    if args.verify_datasets:
        from research.datasets import verify_manifest
        print(json.dumps(verify_manifest(args.verify_datasets), indent=2))
        return

    if args.counterfactual:
        from research.scenarios import load_scenario
        pack = load_scenario(args.counterfactual)
        effective_config = pack.config()
        require_live_inference_approval(
            effective_config, approved=args.approve_live_inference)
        from research.counterfactual import run_counterfactual
        result = run_counterfactual(
            pack, seeds=args.seeds, ticks=args.scenario_ticks,
            effective_config=effective_config)
        print(json.dumps({"scenario": result["scenario"], "design": result["design"],
                          "artifacts": result["artifacts"]}, indent=2))
        return

    if args.experiment:
        from experiments.harness import load_spec, run_experiment
        spec = load_spec(args.experiment)
        require_live_inference_approval(
            spec["config"], approved=args.approve_live_inference)
        # Dispatch the exact resolved config that passed the authorization gate.
        spec.pop("overrides", None)
        run_experiment(spec)
        return

    if args.report:
        db = DATA_DIR / f"{args.report}.db"
        if not db.exists():
            sys.exit(f"run database not found: {db}")
        store = Store(str(db))
        from reports.generate import generate_report
        print(generate_report(store))
        return

    if args.export_static:
        source = Path(args.export_static)
        if not source.exists():
            source = DATA_DIR / f"{args.export_static}.db"
        if not source.exists():
            sys.exit(f"run database not found: {source}")
        store = Store(str(source))
        from server.static_export import export_static_replay
        target = Path(args.output) if args.output else Path("static_exports") / f"{store.get_meta()['run_id']}.html"
        print(export_static_replay(store, target))
        store.close()
        return

    if args.acceptance_report:
        from reports.acceptance import resolve_run_db, write_acceptance_package
        receipt = write_acceptance_package(
            resolve_run_db(args.acceptance_report),
            experiment_json=args.experiment_evidence,
            phenomena_yaml=args.phenomena_evidence,
        )
        print(json.dumps(receipt, indent=2))
        if not receipt["passed"]:
            raise SystemExit(5)
        return

    config = load_config(args.config)
    operational_log(logger, logging.INFO, "config.loaded",
                    path=str(Path(args.config).resolve()), mode=mode,
                    seed=config.get("seed", 42))
    fresh_run = not args.resume and not args.fork
    if fresh_run and not (args.preflight or args.preflight_live or args.replay):
        require_live_inference_approval(
            config, approved=args.approve_live_inference)
    if args.preflight or args.preflight_live:
        report = asyncio.run(provider_preflight(config, live=args.preflight_live))
        print(json.dumps(report, indent=2))
        ready = report.get("ready", False)
        live_ready = report.get("live_ready", True) if args.preflight_live else True
        if not (ready and live_ready):
            operational_log(logger, logging.ERROR, "provider.preflight.failed",
                            live=args.preflight_live, ready=ready,
                            live_ready=live_ready, errors=report.get("errors", []))
            raise SystemExit(2)
        operational_log(logger, logging.INFO, "provider.preflight.completed",
                        live=args.preflight_live, ready=ready,
                        live_ready=live_ready)
        return
    if args.fork:
        args.resume = fork_run(args.fork, upgrade_semantics=args.upgrade_semantics)
    store, world, run_id = open_run(config, args.resume, args.replay)
    if args.activate_supply_recovery:
        try:
            firms_cfg = world.config.get("firms", {}) or {}
            if args.supply_recovery_target_headcount is not None:
                recovery_target = int(args.supply_recovery_target_headcount)
            elif firms_cfg.get("workforce_recovery_target_headcount") is not None:
                recovery_target = int(
                    firms_cfg["workforce_recovery_target_headcount"])
            else:
                # Genesis target_headcount is the pre-recovery staffing floor
                # (often 3). Recovery defaults to the flagship 80-worker target.
                recovery_target = 80
            recovery = activate_supply_recovery_for_run(
                world,
                target_headcount=recovery_target,
            )
        except BaseException:
            _close_run(world, store)
            raise
        print(
            "[agent-economy] supply recovery activates at tick "
            f"{recovery['activation_tick']} with target headcount "
            f"{recovery['target_headcount']}"
        )
    if args.activate_llm_output_budgets:
        try:
            output_budgets = activate_llm_output_budgets_for_run(world, config)
        except BaseException:
            _close_run(world, store)
            raise
        print(
            "[agent-economy] LLM output budgets activate at tick "
            f"{output_budgets['activation_tick']}"
        )
    if not args.replay:
        try:
            require_live_inference_approval(
                world.config, approved=args.approve_live_inference)
        except SystemExit:
            _close_run(world, store)
            raise
    operational_log(logger, logging.INFO, "run.opened",
                    run_id=run_id, tick=store.tick,
                    seed=store.get_meta()["seed"], replay=bool(args.replay),
                    resumed=bool(args.resume))
    print(f"[agent-economy] run {run_id} @ tick {store.tick} "
          f"(seed {store.get_meta()['seed']}, {'replay' if args.replay else 'live'})")

    if args.acceptance_run and not args.serve:
        from reports.acceptance import execute_acceptance_run, write_acceptance_package
        from reports.generate import generate_report_async
        target_tick = args.ticks or int(config.get("acceptance", {}).get("min_ticks", 365))

        async def execute_and_report_acceptance() -> str:
            await execute_acceptance_run(world, target_tick=target_tick)
            return await generate_report_async(
                store, world, out_dir=str(config.get("report_dir", "reports/out")))

        try:
            report_path = asyncio.run(execute_and_report_acceptance())
            receipt = write_acceptance_package(
                store.path,
                out_dir=str(config.get("report_dir", "reports/out")),
                experiment_json=args.experiment_evidence,
                phenomena_yaml=args.phenomena_evidence,
            )
            print(json.dumps({"run_id": run_id, "report": report_path,
                              "acceptance": receipt["artifacts"],
                              "passed": receipt["passed"]}, indent=2))
            if not receipt["passed"]:
                raise SystemExit(5)
            return
        finally:
            _close_run(world, store)

    if args.acceptance_run and args.serve:
        world.acceptance_authorized = True
        world.acceptance_target_tick = (
            args.ticks or int(config.get("acceptance", {}).get("min_ticks", 365)))
        world.acceptance_experiment_evidence = args.experiment_evidence
        world.acceptance_phenomena_evidence = args.phenomena_evidence

    replay_ticks = int(world.config.get("replay_source_tick", 0)) if args.replay else None
    ticks = args.ticks if args.ticks is not None else replay_ticks
    if ticks is not None and not args.serve:
        from reports.generate import ReportBoundaryError, generate_report_async

        async def execute_and_report() -> str:
            await (replay_headless(world, ticks) if args.replay else headless(world, ticks))
            try:
                return await generate_report_async(
                    store, world, out_dir=str(config.get("report_dir", "reports/out")))
            except ReportBoundaryError as exc:
                operational_log(
                    logger, logging.WARNING, "headless.report.deferred",
                    run_id=run_id, tick=store.tick, detail=str(exc))
                return ""

        try:
            path = asyncio.run(execute_and_report())
        except BaseException:
            _close_run(world, store)
            raise
        if args.replay:
            from world.replay_verify import verify_replay
            source = Path(str(world.config["replay_source_path"]))
            try:
                proof = verify_replay(source, store.path)
            except BaseException:
                _close_run(world, store)
                raise
            print(json.dumps(proof, indent=2))
            if not proof["exact"]:
                operational_log(logger, logging.ERROR, "replay.verification.failed",
                                run_id=run_id, source_run_id=args.replay,
                                differences=proof.get("differences"))
                _close_run(world, store)
                raise SystemExit(3)
            operational_log(logger, logging.INFO, "replay.verification.completed",
                            run_id=run_id, source_run_id=args.replay,
                            tables=proof.get("tables"))
        gov = world.gateway.governor.status()
        if world.last_pause_reason:
            reason = world.last_pause_reason.get("reason", "unknown")
            detail = str(world.last_pause_reason.get("detail", ""))[:500]
            report_label = path or "deferred (partial tick)"
            print(f"[agent-economy] paused @ tick {store.tick} · {reason}: {detail} "
                  f"· report: {report_label}")
            operational_log(logger, logging.WARNING, "headless.run.paused",
                            run_id=run_id, tick=store.tick, reason=reason,
                            detail=detail, report_path=path)
            _close_run(world, store)
            raise SystemExit(4)
        print(f"[agent-economy] done @ tick {store.tick} · spend ${gov['total_spend_usd']:.2f} "
              f"· report: {path}")
        operational_log(logger, logging.INFO, "headless.run.completed",
                        run_id=run_id, tick=store.tick,
                        spend_usd=gov["total_spend_usd"], report_path=path)
        _close_run(world, store)
        return

    import uvicorn
    from server.app import create_app
    app = create_app(
        world, served_ticks=None if args.acceptance_run else ticks)
    operational_log(logger, logging.INFO, "server.starting",
                    run_id=run_id, host=args.host, port=args.port)
    startup = "acceptance orchestration starts automatically" if args.acceptance_run else "world starts paused - press Run"
    if ticks is not None and not args.acceptance_run:
        startup += f" (bounded to tick {store.tick + ticks})"
    print(f"[agent-economy] observatory: http://{args.host}:{args.port}  ({startup})")
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    finally:
        _close_run(world, store)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        operational_log(logger, logging.CRITICAL, "cli.command.failed",
                        error_type=type(exc).__name__, error=str(exc))
        raise

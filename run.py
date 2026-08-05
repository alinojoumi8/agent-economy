"""Agent Economy entrypoint.

  python run.py --preflight-live --serve --approve-live-inference  # default evolving live dashboard
  python run.py --config runs/evolving-live.yaml --ticks 10 --preflight-live --approve-live-inference
  python run.py --config runs/base.yaml --ticks 30      # explicit provider-free mechanics profile
  python run.py --config runs/production.yaml --preflight       # validate real-provider config
  python run.py --config runs/production.yaml --preflight-live  # authenticate + confirm models
  python run.py --config runs/base.yaml --resume RUNID  # resume an existing run db
  python run.py --config runs/base.yaml --replay RUNID  # exact replay from stored LLM calls
  python run.py --config runs/base.yaml --fork RUNID@TICK   # what-if branch from a checkpoint
  python run.py --report RUNID                          # generate report for a stored run
  python run.py --experiment runs/experiments/x.yaml    # multi-seed experiment + comparison report
  python run.py --acceptance-report RUNID               # evaluate persisted production evidence
  python run.py --oracle-calibration-report MANIFEST    # curated Oracle campaign evidence
  python run.py --config runs/oracle/v4-seed-7331-control.yaml --oracle-campaign-run --approve-live-inference
  python run.py --config runs/acceptance/production.yaml --acceptance-run  # paid; approval required

One process: FastAPI serves the static dashboard and drives the world loop.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
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
DEFAULT_CONFIG = "runs/evolving-live.yaml"
logger = get_logger("cli")
REPLAY_INPUT_TABLES = (
    "dataset_manifests",
    "calibration_targets",
    "scenario_packs",
)

LIVE_ENTREPRENEURSHIP_DEFAULTS = {
    "enabled": True,
    "new_arrivals_only": False,
    "review_interval_ticks": 6,
    "minimum_ticks_after_arrival": 1,
    "minimum_age": 21,
    "minimum_risk_tolerance": 0.65,
    "minimum_opening_capital_cents": 100_000,
    "personal_reserve_cents": 100_000,
    "opening_capital_share_bps": 3_500,
    "maximum_active_competitors": 3,
    "maximum_formations_per_tick": 2,
    "sales_lookback_ticks": 30,
    "stockout_inventory_threshold": 2,
    "eligible_sectors": [
        "services", "technology", "manufacturing", "logistics",
        "healthcare", "energy", "agriculture",
    ],
    "autonomous_preseed": True,
    "preseed_pitch_delay_ticks": 1,
    "preseed_raise_cents": 250_000,
    "autonomous_mergers": True,
    "minimum_merger_age_ticks": 30,
    "maximum_merger_cash_share_bps": 4_000,
    "merger_premium_bps": 1_000,
}
LIVE_NUMERIC_GROUNDING_DEFAULTS = {
    "model_max_reserved_step": 0.05,
}


def activate_entrepreneurship_for_run(store: Store) -> dict:
    """Persist bounded startup entry at the next untouched decision boundary."""
    meta = store.get_meta()
    if str(meta["status"] or "") != "paused":
        raise RuntimeError("entrepreneurship activation requires a paused run")
    if meta["parent_run_id"] is not None or meta["fork_tick"] is not None:
        raise RuntimeError(
            "entrepreneurship activation requires an original run, not a replay or fork"
        )

    config = json.loads(meta["config_json"])
    existing = config.get("entrepreneurship")
    if isinstance(existing, dict) and bool(existing.get("enabled", False)):
        return dict(existing)

    completed_tick = int(meta["tick"])
    active_tick = (
        int(meta["active_tick"])
        if meta["active_tick"] is not None
        else completed_tick + 1
    )
    untouched_morning = (
        active_tick > completed_tick
        and str(meta["next_phase"] or "") == "MORNING"
    )
    activation_tick = (
        active_tick
        if untouched_morning
        else max(completed_tick, active_tick) + 1
    )
    settings = {
        **LIVE_ENTREPRENEURSHIP_DEFAULTS,
        "activation_tick": activation_tick,
    }
    config["entrepreneurship"] = settings
    store.set_meta(config_json=json.dumps(config, sort_keys=True))
    store.commit()
    return settings


def activate_numeric_grounding_for_run(store: Store) -> dict:
    """Persist numeric grounding at the next untouched decision boundary."""
    meta = store.get_meta()
    if str(meta["status"] or "") != "paused":
        raise RuntimeError("numeric grounding activation requires a paused run")
    if meta["parent_run_id"] is not None or meta["fork_tick"] is not None:
        raise RuntimeError(
            "numeric grounding activation requires an original run, not a replay or fork"
        )
    config = json.loads(meta["config_json"])
    beliefs = dict(config.get("beliefs") or {})
    try:
        maximum_step = float(beliefs.get(
            "model_max_reserved_step",
            LIVE_NUMERIC_GROUNDING_DEFAULTS["model_max_reserved_step"],
        ))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(
            "beliefs.model_max_reserved_step must be finite and nonnegative"
        ) from exc
    if not math.isfinite(maximum_step) or maximum_step < 0:
        raise ValueError(
            "beliefs.model_max_reserved_step must be finite and nonnegative"
        )

    existing_boundary = beliefs.get("model_grounding_from_tick")
    if existing_boundary is not None:
        try:
            boundary = max(0, int(existing_boundary))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(
                "beliefs.model_grounding_from_tick must be a nonnegative integer"
            ) from exc
        return {
            "model_grounding_from_tick": boundary,
            "model_max_reserved_step": maximum_step,
        }

    completed_tick = int(meta["tick"])
    active_tick = (
        int(meta["active_tick"])
        if meta["active_tick"] is not None
        else completed_tick + 1
    )
    untouched_morning = (
        active_tick > completed_tick
        and str(meta["next_phase"] or "") == "MORNING"
    )
    activation_tick = (
        active_tick
        if untouched_morning
        else max(completed_tick, active_tick) + 1
    )
    settings = {
        "model_grounding_from_tick": activation_tick,
        "model_max_reserved_step": maximum_step,
    }
    beliefs.update(settings)
    config["beliefs"] = beliefs
    store.set_meta(config_json=json.dumps(config, sort_keys=True))
    store.commit()
    return settings


async def provider_preflight(config: dict, *, live: bool = False) -> dict:
    report = validate_llm_config(config, raise_on_error=False)
    if not report["ready"] or not live:
        return {**report, "live_checked": False}
    store = Store(":memory:")
    store.init_run_meta("preflight", int(config.get("seed", 42)), config)
    gateway = Gateway(store, config)
    try:
        return await gateway.preflight(live=True)
    finally:
        gateway.close()
        store.close()


def require_live_inference_approval(config: dict, *, approved: bool) -> None:
    """Fail closed before a command can dispatch any configured live provider."""
    from reports.acceptance import uses_paid_providers

    if uses_paid_providers(config) and not approved:
        raise SystemExit(
            "live provider run requires explicit --approve-live-inference authorization"
        )


def validate_open_oracle_campaign_source(
    store: Store, requested_config: dict, profile_path: str | Path,
) -> None:
    """Fail before dispatch if a resumed source is not the requested fixed arm."""
    from reports.oracle_campaign import validate_oracle_campaign_profile

    meta = store.get_meta()
    stored_config = json.loads(meta["config_json"])
    stored_config["engine_semantics_version"] = semantics_version(
        stored_config, default=1)
    validate_oracle_campaign_profile(stored_config, profile_path=profile_path)
    if stored_config != requested_config:
        raise ValueError(
            "stored campaign configuration differs from the requested profile")
    if (meta["parent_run_id"] is not None or meta["fork_tick"] is not None
            or str(meta["run_id"]).startswith("replay-")
            or int(meta["participant_influenced"] or 0) != 0
            or int(meta["external_agent_influenced"] or 0) != 0):
        raise ValueError(
            "Oracle campaign source must be an original observer-only run")


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


def _tighten_resume_operational_limits(
        stored_config: dict, selected_config: dict) -> dict[str, object]:
    """Apply safer runtime limits from the selected resume profile.

    Provider identities, models, routes, prompts, and prices remain owned by
    the persisted run. A resume profile may reduce concurrency, make the
    resource guard more conservative, or lengthen operational timeouts and the
    logical deadline needed for the resulting bounded queues to drain. A
    selected profile may also add bounded transient-provider retries.
    """
    changes: dict[str, object] = {}

    stored_llm = stored_config.get("llm")
    selected_llm = selected_config.get("llm")
    if isinstance(stored_llm, dict) and isinstance(selected_llm, dict):
        for key in ("max_in_flight", "concurrency"):
            current = int(stored_llm.get(key, 0) or 0)
            selected = int(selected_llm.get(key, 0) or 0)
            if selected > 0 and (current <= 0 or selected < current):
                stored_llm[key] = selected
                changes[f"llm.{key}"] = selected

        current_deadline = float(stored_llm.get("logical_deadline_s", 0) or 0)
        selected_deadline = float(
            selected_llm.get("logical_deadline_s", 0) or 0)
        if selected_deadline > current_deadline:
            stored_llm["logical_deadline_s"] = selected_deadline
            changes["llm.logical_deadline_s"] = selected_deadline

        current_retries = int(stored_llm.get("provider_retries", 0) or 0)
        selected_retries = int(selected_llm.get("provider_retries", 0) or 0)
        if selected_retries > current_retries:
            stored_llm["provider_retries"] = selected_retries
            changes["llm.provider_retries"] = selected_retries

        stored_providers = stored_llm.get("providers")
        selected_providers = selected_llm.get("providers")
        if isinstance(stored_providers, dict) and isinstance(selected_providers, dict):
            for provider in sorted(set(stored_providers) & set(selected_providers)):
                stored_provider = stored_providers.get(provider)
                selected_provider = selected_providers.get(provider)
                if not isinstance(stored_provider, dict) or not isinstance(
                        selected_provider, dict):
                    continue
                current = int(stored_provider.get("concurrency", 0) or 0)
                selected = int(selected_provider.get("concurrency", 0) or 0)
                if selected > 0 and (current <= 0 or selected < current):
                    stored_provider["concurrency"] = selected
                    changes[f"llm.providers.{provider}.concurrency"] = selected

                current_timeout = float(
                    stored_provider.get("timeout_s", 0) or 0)
                selected_timeout = float(
                    selected_provider.get("timeout_s", 0) or 0)
                if selected_timeout > current_timeout:
                    stored_provider["timeout_s"] = selected_timeout
                    changes[
                        f"llm.providers.{provider}.timeout_s"
                    ] = selected_timeout

        stored_cohorts = stored_llm.get("citizen_model_cohorts")
        selected_cohorts = selected_llm.get("citizen_model_cohorts")
        if isinstance(stored_cohorts, list) and isinstance(selected_cohorts, list):
            selected_by_name = {
                str(cohort.get("name")): cohort
                for cohort in selected_cohorts
                if isinstance(cohort, dict) and cohort.get("name")
            }
            for stored_cohort in stored_cohorts:
                if not isinstance(stored_cohort, dict):
                    continue
                cohort_name = str(stored_cohort.get("name") or "")
                selected_cohort = selected_by_name.get(cohort_name)
                if not isinstance(selected_cohort, dict):
                    continue
                for route_name in ("primary", "fallback"):
                    stored_route = stored_cohort.get(route_name)
                    selected_route = selected_cohort.get(route_name)
                    if not isinstance(stored_route, dict) or not isinstance(
                            selected_route, dict):
                        continue
                    if (
                        stored_route.get("provider") != selected_route.get("provider")
                        or stored_route.get("model") != selected_route.get("model")
                    ):
                        continue
                    current_timeout = float(
                        stored_route.get("timeout_s", 0) or 0)
                    selected_timeout = float(
                        selected_route.get("timeout_s", 0) or 0)
                    if selected_timeout > current_timeout:
                        stored_route["timeout_s"] = selected_timeout
                        changes[
                            "llm.citizen_model_cohorts."
                            f"{cohort_name}.{route_name}.timeout_s"
                        ] = selected_timeout

    stored_guard = stored_config.setdefault("resource_guard", {})
    selected_guard = selected_config.get("resource_guard")
    if isinstance(stored_guard, dict) and isinstance(selected_guard, dict):
        if bool(selected_guard.get("enabled")) and not bool(stored_guard.get("enabled")):
            stored_guard["enabled"] = True
            changes["resource_guard.enabled"] = True

        for key in (
                "sample_interval_s",
                "max_cpu_percent",
                "max_memory_percent",
                "max_swap_percent",
                "consecutive_breaches",
        ):
            current = float(stored_guard.get(key, 0) or 0)
            selected = float(selected_guard.get(key, 0) or 0)
            if selected > 0 and (current <= 0 or selected < current):
                value: int | float = (
                    int(selected) if key == "consecutive_breaches" else selected)
                stored_guard[key] = value
                changes[f"resource_guard.{key}"] = value

        current_available = float(
            stored_guard.get("min_available_memory_gb", 0) or 0)
        selected_available = float(
            selected_guard.get("min_available_memory_gb", 0) or 0)
        if selected_available > current_available:
            stored_guard["min_available_memory_gb"] = selected_available
            changes["resource_guard.min_available_memory_gb"] = selected_available

    return changes


def _adopt_resume_local_citizenship(
        stored_config: dict, selected_config: dict) -> dict[str, object]:
    """Enable an explicitly selected local Passport UI for an older run.

    Passport ownership lives in its own control-plane database. This runtime
    overlay therefore does not rewrite the run's persisted simulation config,
    provider routes, or replay inputs. An explicit stored disable still wins.
    """
    selected_gateway = selected_config.get("external_gateway")
    if not isinstance(selected_gateway, dict):
        return {}
    selected_join = selected_gateway.get("public_join")
    if not isinstance(selected_join, dict) or not bool(
            selected_join.get("enabled", False)):
        return {}

    stored_gateway = stored_config.get("external_gateway")
    if stored_gateway is None:
        stored_gateway = {}
        stored_config["external_gateway"] = stored_gateway
    if not isinstance(stored_gateway, dict):
        return {}
    if stored_gateway.get("enabled") is False or "public_join" in stored_gateway:
        return {}

    stored_gateway["public_join"] = dict(selected_join)
    return {"external_gateway.public_join.enabled": True}


def open_run(config: dict, resume: str | None, replay: str | None, *,
             data_dir: Path = DATA_DIR,
             new_run_id_override: str | None = None,
             activate_entrepreneurship: bool = False,
             activate_numeric_grounding: bool = False) -> tuple[Store, World, str]:
    data_dir.mkdir(parents=True, exist_ok=True)
    if resume:
        run_id = resume
        db = data_dir / f"{run_id}.db"
        if not db.exists():
            sys.exit(f"run database not found: {db}")
        store = Store(str(db))
        try:
            if activate_entrepreneurship:
                activate_entrepreneurship_for_run(store)
            if activate_numeric_grounding:
                activate_numeric_grounding_for_run(store)
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
        tightened = _tighten_resume_operational_limits(stored_cfg, config)
        if tightened:
            operational_log(
                logger, logging.INFO, "run.resume.operational_limits_tightened",
                run_id=run_id, limits=tightened)
        local_control_plane = _adopt_resume_local_citizenship(
            stored_cfg, config)
        if local_control_plane:
            operational_log(
                logger, logging.INFO,
                "run.resume.local_citizenship_enabled",
                run_id=run_id, changes=local_control_plane)
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
    run_id = new_run_id_override or new_run_id()
    database = data_dir / f"{run_id}.db"
    if database.exists():
        raise FileExistsError(
            f"fresh run database already exists: {database}; use --resume")
    store = Store(str(database))
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
            checkpoint = checkpoints.get(source_prediction_id)
            governed_contract = None
            acceptance = world.config.get("acceptance", {})
            if (checkpoint is not None
                    and acceptance.get("oracle_latency_source") == "scheduled_e2e_v1"):
                matching_items = [
                    item for item in acceptance.get("oracle_questions", [])
                    if int(item.get("at_tick", -1)) == int(checkpoint["scheduled_tick"])
                    and str(item.get("question", "")) == str(checkpoint["question"])
                ]
                if len(matching_items) != 1:
                    raise RuntimeError(
                        "recorded governed Oracle checkpoint has no unique schedule item")
                from reports.acceptance import _scheduled_contract

                governed_contract = _scheduled_contract(
                    acceptance, matching_items[0])
            result = await world.oracle.ask(
                str(prediction["question"]),
                governed_contract=governed_contract)
            try:
                replay_prediction_id = int(result["prediction_id"])
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError(
                    "replayed Oracle call produced no valid prediction reference"
                ) from exc

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
    if world.store.tick != target_tick:
        raise RuntimeError(
            f"replay stopped at tick {world.store.tick} before target tick "
            f"{target_tick}")


def _validate_oracle_cli_exclusivity(args, parser: argparse.ArgumentParser) -> None:
    """Reject ambiguous Oracle evidence commands before any side effect."""
    primary = {
        "--refresh-datasets": args.refresh_datasets,
        "--verify-datasets": args.verify_datasets,
        "--counterfactual": args.counterfactual,
        "--experiment": args.experiment,
        "--report": args.report,
        "--export-static": args.export_static,
        "--acceptance-report": args.acceptance_report,
        "--acceptance-run": args.acceptance_run,
        "--replay": args.replay,
        "--fork": args.fork,
        "--serve": args.serve,
        "--preflight": args.preflight,
        "--preflight-live": args.preflight_live,
    }
    modifiers = {
        "--output": args.output,
        "--refresh-dataset-key": args.refresh_dataset_key,
        "--experiment-evidence": args.experiment_evidence,
        "--phenomena-evidence": args.phenomena_evidence,
        "--scenario-ticks": args.scenario_ticks,
        "--upgrade-semantics": args.upgrade_semantics,
        "--activate-entrepreneurship": args.activate_entrepreneurship,
        "--activate-numeric-grounding": args.activate_numeric_grounding,
    }
    if args.oracle_campaign_run:
        incompatible = [name for name, value in {
            "--oracle-calibration-report": args.oracle_calibration_report,
            **primary, **modifiers,
        }.items() if value]
        if incompatible:
            parser.error(
                "--oracle-campaign-run is mutually exclusive with "
                + ", ".join(incompatible))
    if args.oracle_calibration_report:
        incompatible = [name for name, value in {
            "--oracle-campaign-run": args.oracle_campaign_run,
            "--resume": args.resume,
            "--ticks": args.ticks,
            **primary, **modifiers,
        }.items() if value]
        if incompatible:
            parser.error(
                "--oracle-calibration-report is mutually exclusive with "
                + ", ".join(incompatible))


def _initialize_claimed_oracle_genesis(
        config: dict, campaign_claim: dict, *, data_dir: Path) -> Path:
    """Build genesis in a unique directory, then publish it without clobbering."""
    import shutil
    import tempfile
    from reports.oracle_campaign import (
        finalize_sqlite_artifact,
        publish_claimed_oracle_genesis,
        recover_claimed_oracle_genesis,
        validate_claimed_oracle_genesis,
    )

    recovered = recover_claimed_oracle_genesis(
        campaign_claim, config, data_dir=data_dir)
    if recovered is not None:
        return recovered
    pending_root = data_dir.resolve() / "oracle-pending"
    pending_root.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(tempfile.mkdtemp(
        prefix=f".{campaign_claim['run_id']}-", dir=pending_root)).resolve()
    staged_path = staging_dir / f"{campaign_claim['run_id']}.db"
    try:
        pending_store, pending_world, _ = open_run(
            config, None, None, data_dir=staging_dir,
            new_run_id_override=str(campaign_claim["run_id"]))
        _close_run(pending_world, pending_store)
        finalize_sqlite_artifact(staged_path)
        validate_claimed_oracle_genesis(
            staged_path, campaign_claim, config)
        return publish_claimed_oracle_genesis(
            staged_path, campaign_claim, config, data_dir=data_dir)
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)


def _execute_oracle_campaign_run(config: dict, args) -> None:
    """Execute the sole CLI path that may construct live campaign receipts."""
    from reports.oracle_campaign import (
        finalize_sqlite_artifact,
        load_existing_oracle_source_receipt,
        mark_oracle_campaign_initialized,
        oracle_campaign_execution_lock,
        prepare_oracle_campaign_run,
        recover_claimed_oracle_genesis,
        write_oracle_source_receipt,
        write_replay_execution_receipt,
    )

    require_live_inference_approval(
        config, approved=args.approve_live_inference)
    campaign_claim = prepare_oracle_campaign_run(
        config, args.config, data_dir=DATA_DIR,
        resume_run_id=args.resume)
    with oracle_campaign_execution_lock(campaign_claim, data_dir=DATA_DIR):
        if campaign_claim.get("create_pending_database"):
            _initialize_claimed_oracle_genesis(
                config, campaign_claim, data_dir=DATA_DIR)
        else:
            recover_claimed_oracle_genesis(
                campaign_claim, config, data_dir=DATA_DIR)
        out_dir = str(config.get("report_dir", "reports/out"))
        existing_receipt = load_existing_oracle_source_receipt(
            campaign_claim=campaign_claim, profile_path=args.config,
            out_dir=out_dir, data_dir=DATA_DIR)
        if existing_receipt is not None:
            replay_evidence = existing_receipt.get("run", {}).get("replay", {})
            print(json.dumps({
                "run_id": campaign_claim["run_id"],
                "replay_run_id": replay_evidence.get("replay_run_id"),
                "report": None,
                "source_receipt": existing_receipt["artifact"],
                "replay_execution_receipt": existing_receipt[
                    "manifest_entry"]["replay_execution_receipt"],
                "manifest_entry": existing_receipt["manifest_entry"],
                "passed": True,
                "reused": True,
            }, indent=2))
            return
        store, world, run_id = open_run(
            config, str(campaign_claim["run_id"]), None, data_dir=DATA_DIR)
        try:
            mark_oracle_campaign_initialized(campaign_claim, store.path)
            validate_open_oracle_campaign_source(store, config, args.config)
        except BaseException:
            _close_run(world, store)
            raise

        operational_log(
            logger, logging.INFO, "run.opened", run_id=run_id,
            tick=store.tick, seed=store.get_meta()["seed"], replay=False,
            resumed=bool(args.resume))
        print(f"[agent-economy] run {run_id} @ tick {store.tick} "
              f"(seed {store.get_meta()['seed']}, live)")

        from reports.acceptance import execute_acceptance_run
        from reports.generate import generate_report_async
        target_tick = args.ticks or int(config["acceptance"]["min_ticks"])
        source_path = Path(store.path).resolve()
        report_path = None

        async def execute_and_report_campaign_source() -> str:
            await execute_acceptance_run(world, target_tick=target_tick)
            return await generate_report_async(
                store, world,
                out_dir=str(config.get("report_dir", "reports/out")))

        try:
            if store.tick < target_tick:
                report_path = asyncio.run(execute_and_report_campaign_source())
            elif store.tick > target_tick:
                raise RuntimeError(
                    "Oracle campaign source advanced beyond its fixed horizon")
        finally:
            _close_run(world, store)
        finalize_sqlite_artifact(source_path)

        replay_store, replay_world, replay_run_id = open_run(
            config, None, run_id, data_dir=DATA_DIR)
        replay_path = Path(replay_store.path).resolve()
        replay_tracker = None
        try:
            asyncio.run(replay_headless(replay_world, target_tick))
            replay_tracker = replay_world.gateway.replay_execution_stats()
        finally:
            _close_run(replay_world, replay_store)
        finalize_sqlite_artifact(replay_path)

        replay_execution = write_replay_execution_receipt(
            source_path, replay_path, args.config,
            replay_tracker=replay_tracker, campaign_claim=campaign_claim,
            out_dir=out_dir)
        receipt = write_oracle_source_receipt(
            source_path, replay_path, args.config,
            replay_execution_receipt=replay_execution["artifact"],
            campaign_claim=campaign_claim, out_dir=out_dir)
        print(json.dumps({
            "run_id": run_id,
            "replay_run_id": replay_run_id,
            "report": report_path,
            "source_receipt": receipt["artifact"],
            "replay_execution_receipt": replay_execution["artifact"],
            "manifest_entry": receipt["manifest_entry"],
            "passed": receipt["passed"],
        }, indent=2))
        if not receipt["passed"]:
            raise SystemExit(5)


def main() -> None:
    load_dotenv()
    configure_logging()
    ap = argparse.ArgumentParser(description="Agent Economy")
    ap.add_argument("--config", default=DEFAULT_CONFIG,
                    help="world config (default: evolving live-agent desktop profile)")
    ap.add_argument("--ticks", type=int, default=None,
                    help="run N ticks; with --serve, set a hard N-tick session boundary")
    ap.add_argument("--resume", default=None, help="resume run id")
    ap.add_argument(
        "--activate-entrepreneurship",
        action="store_true",
        help=(
            "only with --resume: enable bounded startup entry from the next "
            "untouched decision boundary"
        ),
    )
    ap.add_argument(
        "--activate-numeric-grounding",
        action="store_true",
        help=(
            "only with --resume: ground model-authored numeric claims from "
            "the next untouched decision boundary"
        ),
    )
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
    ap.add_argument("--oracle-calibration-report", default=None,
                    help="evaluate an explicit Oracle campaign manifest and write receipts")
    ap.add_argument("--oracle-campaign-run", action="store_true",
                    help="run one predeclared live-Oracle campaign arm and exact replay")
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
    if args.activate_entrepreneurship and (
            not args.resume or args.replay or args.fork):
        ap.error(
            "--activate-entrepreneurship requires --resume and cannot use "
            "--replay/--fork"
        )
    if args.activate_numeric_grounding and (
            not args.resume or args.replay or args.fork):
        ap.error(
            "--activate-numeric-grounding requires --resume and cannot use "
            "--replay/--fork"
        )
    if args.activate_supply_recovery and not (args.resume or args.fork):
        ap.error("--activate-supply-recovery requires --resume or --fork")
    if args.activate_supply_recovery and args.replay:
        ap.error("--activate-supply-recovery cannot modify a replay")
    if args.activate_llm_output_budgets and not (args.resume or args.fork):
        ap.error("--activate-llm-output-budgets requires --resume or --fork")
    if args.activate_llm_output_budgets and args.replay:
        ap.error("--activate-llm-output-budgets cannot modify a replay")
    _validate_oracle_cli_exclusivity(args, ap)
    if args.acceptance_report and args.oracle_calibration_report:
        ap.error("--acceptance-report and --oracle-calibration-report are mutually exclusive")
    if args.acceptance_run and args.oracle_campaign_run:
        ap.error("--acceptance-run and --oracle-campaign-run are mutually exclusive")
    if args.oracle_campaign_run and args.serve:
        ap.error("--oracle-campaign-run is a finalized headless evidence command")
    if args.oracle_campaign_run and (args.fork or args.replay):
        ap.error("--oracle-campaign-run cannot use fork or replay inputs")
    mode = ("dataset_refresh" if args.refresh_datasets else
            "dataset_verify" if args.verify_datasets else
            "counterfactual" if args.counterfactual else
            "static_export" if args.export_static else "experiment" if args.experiment else
            "oracle_calibration_report" if args.oracle_calibration_report else
            "acceptance_report" if args.acceptance_report else
            "oracle_campaign_run" if args.oracle_campaign_run else
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

    if args.oracle_calibration_report:
        from reports.oracle_campaign import write_oracle_campaign_package
        receipt = write_oracle_campaign_package(args.oracle_calibration_report)
        print(json.dumps(receipt, indent=2))
        if not receipt["passed"]:
            raise SystemExit(5)
        return

    config = load_config(args.config)
    preflight_then_run = bool(
        args.preflight_live and (args.serve or args.ticks is not None))
    if args.oracle_campaign_run:
        from reports.oracle_campaign import validate_oracle_campaign_profile
        validate_oracle_campaign_profile(config, profile_path=args.config)
        campaign_horizon = int(config["acceptance"]["min_ticks"])
        if args.ticks is not None and args.ticks != campaign_horizon:
            ap.error(
                f"--oracle-campaign-run has a fixed {campaign_horizon}-tick horizon")
    operational_log(logger, logging.INFO, "config.loaded",
                    path=str(Path(args.config).resolve()), mode=mode,
                    seed=config.get("seed", 42))
    fresh_run = not args.resume and not args.fork
    if (fresh_run and not args.replay
            and bool(config.get("llm", {}).get("require_preflight_live", False))
            and not (args.preflight or args.preflight_live)):
        ap.error("this live profile requires --preflight-live before starting")
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
        if not preflight_then_run:
            return
    if args.fork:
        args.resume = fork_run(args.fork, upgrade_semantics=args.upgrade_semantics)
    if args.oracle_campaign_run:
        _execute_oracle_campaign_run(config, args)
        return
    store, world, run_id = open_run(
        config,
        args.resume,
        args.replay,
        activate_entrepreneurship=args.activate_entrepreneurship,
        activate_numeric_grounding=args.activate_numeric_grounding,
    )
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
        # Observer search is a GET projection; do not persist raw query text in access logs.
        uvicorn.run(
            app, host=args.host, port=args.port,
            log_level="warning", access_log=False)
    finally:
        _close_run(world, store)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        operational_log(logger, logging.CRITICAL, "cli.command.failed",
                        error_type=type(exc).__name__, error=str(exc))
        raise

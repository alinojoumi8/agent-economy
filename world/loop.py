"""The world loop: ticks and phases in fixed order (TECH-SPEC §3).

Phase order per tick T (determinism requires ordered execution):
  1 NIGHT_CLOSE   interest, loan payments, payroll, production, lifecycle draws,
                  shock evaluation, pre-decision reconciliation check
  2 INBOX_DELIVERY due asynchronous mail resolves (Semantics 8 only)
  3 MORNING       scheduled agents perceive + decide (LLM, concurrent)
  4 EXECUTION     validator + engine apply queued actions (deterministic order)
  5 MARKET        order book matches; session closes
  6 NEWSROOM      outlets write stories from the day's true events
  7 EVENING       conversation pairs
  8 MEMORY        nightly compression, belief extraction
  9 FINALIZE      post-action metrics, Oracle resolution, reconciliation check

A failed reconciliation halts the run with a diagnostic dump (PRD R1). The budget
governor is consulted every tick; at 100% the run pauses cleanly (PRD R7).
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import shutil
import time
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Callable, Optional

import psutil

from engine.core import Economy
from engine.checkpoint_manifest import (
    finalize_sqlite_artifact,
    write_checkpoint_manifest,
)
from engine.ledger import (
    Leg,
    ReconciliationError,
    SYS_EXTERNAL,
    SYS_HOUSING,
    SYS_INFLOW,
)
from engine.semantics import semantics_version
from engine.store import Store, load_json
from llm.gateway import Gateway, BudgetExceeded, GatewayInterrupted, ProviderUnavailable
from agents.runtime import AgentRuntime
from communications.delivery import CommunicationDelivery
from agents.personas.library import (
    configured_outlet_ids, sample_arrival_persona, sample_persona,
)
from .genesis import Genesis
from .metrics import Metrics
from .newsroom import Newsroom, Conversations
from .commons import CommonsService
from .shocks import Shocks
from .phases import (
    LEGACY_PHASE_SPECS,
    STANDARD_PHASE_SPECS,
    SEMANTICS_8_PHASE_SPECS,
    phase_names_for_semantics,
)
from oracle.analyst import Oracle
from observability import get_logger, log_event as operational_log

LEGACY_PHASES = tuple(spec.name for spec in LEGACY_PHASE_SPECS)
PHASES = tuple(spec.name for spec in STANDARD_PHASE_SPECS)
SEMANTICS_8_PHASES = tuple(spec.name for spec in SEMANTICS_8_PHASE_SPECS)
logger = get_logger("world")


class World:
    def __init__(self, store: Store, config: dict, *, replay: bool = False):
        self.store = store
        self.config = config
        self.engine_semantics_version = semantics_version(config, default=2)
        self.phases = phase_names_for_semantics(self.engine_semantics_version)
        seed = int(config.get("seed", 42))
        self.engine_prng = random.Random(seed)
        self.lifecycle_prng = random.Random(seed ^ 0x5F5E5F)
        self.persona_prng = random.Random(seed ^ 0xA11CE)

        cfg = dict(config)
        cfg["replay"] = replay
        self.economy = Economy(store, config, self.engine_prng, self.lifecycle_prng)
        self.gateway = Gateway(store, cfg)
        self.runtime = AgentRuntime(self.economy, self.gateway, config)
        self.commons = CommonsService(self.economy, self.runtime.mem)
        self.communication_delivery = CommunicationDelivery(store, config)
        self.metrics = Metrics(
            self.economy, semantics_version=self.engine_semantics_version)
        self.shocks = Shocks(self.economy, config)
        self.newsroom = Newsroom(self.economy, self.gateway, config, self.shocks)
        self.conversations = Conversations(self.economy, self.gateway, config)
        self.oracle = Oracle(self.economy, self.gateway, config)

        self.status = "created"      # created|running|paused|halted|finished
        self.speed_delay_s = float(config.get("speed_delay_s", 0.0))
        self.checkpoint_every = int(config.get("checkpoint_every", 10))
        self.resource_guard = dict(config.get("resource_guard", {}) or {})
        self._pause_requested = False
        self._stop_requested = False
        self.last_report_path: Optional[str] = None
        self.last_pause_reason: Optional[dict] = None
        self.on_tick: Optional[Callable[[int, dict], None]] = None  # dashboard hook
        self.on_event: Optional[Callable[[dict], None]] = None

    # ── lifecycle of a run ───────────────────────────────────────────────────
    def initialize(self) -> None:
        """Genesis for a fresh run (no-op if already initialised)."""
        if self.store.scalar("SELECT COUNT(*) FROM agents", default=0):
            if self.engine_semantics_version >= 12:
                self.economy.city.initialize(self.store.tick)
                self.store.commit()
            operational_log(logger, logging.DEBUG, "world.initialize.skipped",
                            run_id=self.gateway.run_id, tick=self.store.tick)
            return
        # Fresh R21 runs ingest verified supports before genesis. Replays remove
        # the mutable manifest path and restore these rows from the source DB.
        if self.config.get("dataset_manifest"):
            from research.datasets import ingest_manifest
            ingest_manifest(self.store, self.config["dataset_manifest"])
        from research.r21 import R21Calibration
        calibration = R21Calibration(
            self.store, self.config, int(self.config.get("seed", 42)))
        Genesis(
            self.economy, self.config, self.persona_prng,
            calibration=calibration).build()
        if self.config.get("behavioral_fixture", {}).get("enabled"):
            from world.behavioral_fixture import BehavioralFixtureSeeder
            BehavioralFixtureSeeder(self.economy, self.config).seed()
        if self.config.get("spec_closure_fixture", {}).get("enabled"):
            from world.spec_closure_fixture import SpecClosureFixtureSeeder
            SpecClosureFixtureSeeder(self.economy, self.config).seed()
        self.economy.cognition.seed_world(0)
        self.shocks.load_from_config()
        ok, diag = self.economy.ledger.reconcile()
        if not ok:
            raise ReconciliationError(f"genesis does not reconcile: {diag}")
        self.metrics.snapshot(0)
        self.store.set_meta(status="paused", tick=0)
        if self.engine_semantics_version >= 7:
            # Genesis consumes the persona stream. Persist it immediately so a
            # resume before tick 1 cannot reset arrival identities.
            self._save_prng_state()
        self.store.commit()
        operational_log(logger, logging.INFO, "world.initialized",
                        run_id=self.gateway.run_id, seed=self.config.get("seed", 42),
                        agents=self.store.scalar("SELECT COUNT(*) FROM agents", default=0))

    def close(self) -> None:
        """Release the run and any recorded-source handles idempotently."""
        self.gateway.close()
        self.store.close()

    async def run(self, max_ticks: Optional[int] = None) -> None:
        self.status = "running"
        self.store.set_meta(status="running")
        start_tick = self.store.tick
        end_tick = (start_tick + max_ticks) if max_ticks else None
        operational_log(logger, logging.INFO, "world.run.started",
                        run_id=self.gateway.run_id, start_tick=start_tick,
                        max_ticks=max_ticks, replay=self.gateway.replay)
        resource_task = (
            asyncio.create_task(self._monitor_resources())
            if self.resource_guard.get("enabled") and not self.gateway.replay
            else None
        )
        try:
            while not self._stop_requested:
                if end_tick is not None and self.store.tick >= end_tick:
                    break
                if self._pause_requested:
                    break
                summary = await self.step()
                if summary.get("paused"):
                    break
                if self.speed_delay_s > 0:
                    await asyncio.sleep(self.speed_delay_s)
        finally:
            if resource_task is not None:
                resource_task.cancel()
                with suppress(asyncio.CancelledError):
                    await resource_task
            new_status = "halted" if self.status == "halted" else "paused"
            if self._stop_requested:
                new_status = "finished"
            self.status = new_status
            self.store.set_meta(status=new_status)
            self._save_prng_state()
            self.store.commit()
            self.checkpoint(
                self.store.tick,
                reason="stop" if self._stop_requested else "pause")
            if self._stop_requested:
                meta = self.store.get_meta()
                if meta["active_tick"] is not None:
                    self.last_report_path = None
                    self.last_pause_reason = {
                        "reason": "report_deferred_partial_tick",
                        "active_tick": int(meta["active_tick"]),
                        "phase": str(meta["next_phase"] or meta["phase"] or "unknown"),
                        "detail": "finish the partial tick before generating an end-of-run report",
                    }
                    operational_log(
                        logger, logging.WARNING, "world.report.deferred",
                        run_id=self.gateway.run_id, tick=self.store.tick,
                        active_tick=int(meta["active_tick"]),
                        phase=self.last_pause_reason["phase"])
                else:
                    try:
                        from reports.generate import generate_report_async
                        # The run loop has exited and owns the only active provider
                        # workflow here, so the Stop interrupt can be retired before
                        # the separately bounded report request.
                        self.gateway.clear_interrupt()
                        self.last_report_path = await generate_report_async(
                            self.store, self,
                            out_dir=str(self.config.get("report_dir", "reports/out")))
                        operational_log(logger, logging.INFO, "world.report.generated",
                                        run_id=self.gateway.run_id, tick=self.store.tick,
                                        path=self.last_report_path)
                    except Exception as exc:
                        self.store.log_event(
                            self.store.tick, "report_failed", {"error": str(exc)[:500]},
                            importance=3.0)
                        self.store.commit()
                        operational_log(logger, logging.ERROR, "world.report.failed",
                                        run_id=self.gateway.run_id, tick=self.store.tick,
                                        error_type=type(exc).__name__, error=str(exc))
            self._pause_requested = False
            operational_log(logger, logging.INFO, "world.run.finished",
                            run_id=self.gateway.run_id, start_tick=start_tick,
                            end_tick=self.store.tick, status=new_status,
                            stop_requested=self._stop_requested)

    def _resource_snapshot(self) -> dict:
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()
        process = psutil.Process()
        return {
            "system_cpu_percent": round(float(psutil.cpu_percent(interval=None)), 1),
            "system_memory_percent": round(float(memory.percent), 1),
            "available_memory_gb": round(float(memory.available) / (1024 ** 3), 2),
            "system_swap_percent": round(float(swap.percent), 1),
            "available_swap_gb": round(float(swap.free) / (1024 ** 3), 2),
            "process_rss_mb": round(float(process.memory_info().rss) / (1024 ** 2), 1),
            "global_in_flight": int(self.gateway._live_in_flight),
            "global_queue_depth": int(self.gateway._global_queue_depth()),
            "provider_in_flight": {
                name: int(gate.active)
                for name, gate in sorted(self.gateway.provider_gates.items())
            },
            "provider_queue_depth": {
                name: int(gate.queued)
                for name, gate in sorted(self.gateway.provider_gates.items())
            },
        }

    def _resource_breaches(self, sample: dict) -> list[str]:
        breaches = []
        if (float(self.resource_guard.get("max_cpu_percent", 0)) > 0
                and sample["system_cpu_percent"]
                >= float(self.resource_guard["max_cpu_percent"])):
            breaches.append("system_cpu")
        if (float(self.resource_guard.get("max_memory_percent", 0)) > 0
                and sample["system_memory_percent"]
                >= float(self.resource_guard["max_memory_percent"])):
            breaches.append("system_memory")
        if (float(self.resource_guard.get("min_available_memory_gb", 0)) > 0
                and sample["available_memory_gb"]
                <= float(self.resource_guard["min_available_memory_gb"])):
            breaches.append("available_memory")
        if (float(self.resource_guard.get("max_swap_percent", 0)) > 0
                and sample["system_swap_percent"]
                >= float(self.resource_guard["max_swap_percent"])):
            breaches.append("system_swap")
        return breaches

    async def _monitor_resources(self) -> None:
        interval_s = max(
            0.1, float(self.resource_guard.get("sample_interval_s", 5.0)))
        required = max(
            1, int(self.resource_guard.get("consecutive_breaches", 3)))
        consecutive = 0
        while self.status == "running" and not self._pause_requested:
            try:
                sample = self._resource_snapshot()
                breaches = self._resource_breaches(sample)
                consecutive = consecutive + 1 if breaches else 0
                operational_log(
                    logger, logging.INFO, "runtime.resource.sample",
                    run_id=self.gateway.run_id, tick=self.store.tick,
                    breaches=breaches, consecutive_breaches=consecutive,
                    **sample)
                if consecutive >= required:
                    self.last_pause_reason = {
                        "reason": "resource_guard",
                        "breaches": breaches,
                        **sample,
                    }
                    operational_log(
                        logger, logging.CRITICAL, "runtime.resource.limit_reached",
                        run_id=self.gateway.run_id, tick=self.store.tick,
                        consecutive_breaches=consecutive, **self.last_pause_reason)
                    self.request_pause()
                    return
            except Exception as exc:
                operational_log(
                    logger, logging.WARNING, "runtime.resource.sample_failed",
                    run_id=self.gateway.run_id, tick=self.store.tick,
                    error_type=type(exc).__name__, error=str(exc))
            await asyncio.sleep(interval_s)

    def request_pause(self) -> None:
        self._pause_requested = True
        self.gateway.interrupt_pending()
        operational_log(logger, logging.INFO, "world.pause.requested",
                        run_id=self.gateway.run_id, tick=self.store.tick)

    def request_stop(self) -> None:
        self._stop_requested = True
        self.gateway.interrupt_pending()
        operational_log(logger, logging.INFO, "world.stop.requested",
                        run_id=self.gateway.run_id, tick=self.store.tick)

    def _persist_phase(self, tick: int, next_phase: str, state: dict) -> None:
        self.store.set_meta(
            active_tick=tick, next_phase=next_phase, phase=next_phase,
            phase_state_json=json.dumps(state), legacy_partial=0)
        self._save_prng_state()
        self.store.commit()

    # ── one tick ─────────────────────────────────────────────────────────────
    async def step(self) -> dict:
        meta = self.store.get_meta()
        tick = int(meta["active_tick"]) if meta["active_tick"] is not None else self.store.tick + 1
        phase = str(meta["next_phase"] or "NIGHT_CLOSE")
        if phase not in self.phases:
            phase = "NIGHT_CLOSE"
        state = load_json(meta["phase_state_json"], {}) or {}
        if meta["active_tick"] is None:
            if self.engine_semantics_version >= 9:
                await self.runtime.external.collect_online_turns(tick)
            self._persist_phase(tick, phase, state)
        elif meta["legacy_partial"] and phase == "MEMORY":
            state["observations_captured"] = bool(self.store.scalar(
                "SELECT COUNT(*) FROM memories WHERE tick=? AND kind='observation'",
                (tick,), default=0))
            self._persist_phase(tick, phase, state)
        t0 = time.time()
        decisions_count = len(state.get("decisions", []))
        try:
            for index in range(self.phases.index(phase), len(self.phases)):
                phase = self.phases[index]
                self._persist_phase(tick, phase, state)
                phase_started = time.perf_counter()
                operational_log(
                    logger, logging.INFO, "world.phase.started",
                    run_id=self.gateway.run_id, tick=tick, phase=phase)
                if phase == "NIGHT_CLOSE":
                    try:
                        with self.store.savepoint(f"tick_{tick}_night_close"):
                            self._phase_night_close(tick)
                    except ReconciliationError as exc:
                        self._record_reconciliation_halt(
                            tick, "NIGHT_CLOSE", getattr(exc, "diagnostic", {}))
                        raise
                elif phase == "INBOX_DELIVERY":
                    with self.store.savepoint(f"tick_{tick}_inbox_delivery"):
                        self.communication_delivery.deliver_due(tick)
                elif phase == "MORNING":
                    if self.gateway.governor.should_pause():
                        raise BudgetExceeded("world budget exhausted before MORNING")
                    if self.engine_semantics_version >= 7:
                        await self.runtime.enrich_pending_arrivals(tick)
                    decisions = await self.runtime.decide_all(tick)
                    if self.engine_semantics_version >= 9:
                        self.runtime.external.restore_replay_after_morning(tick)
                    state["decisions"] = decisions
                    decisions_count = len(decisions)
                elif phase == "EXECUTION":
                    with self.store.savepoint(f"tick_{tick}_execution"):
                        self.runtime.execute_decisions(tick, state.get("decisions", []))
                elif phase == "MARKET":
                    with self.store.savepoint(f"tick_{tick}_market"):
                        self._phase_market(tick)
                elif phase == "NEWSROOM":
                    await self.newsroom.publish(tick)
                elif phase == "EVENING":
                    if "conversation_pairs" not in state:
                        state["conversation_pairs"] = [
                            list(pair) for pair in self.conversations.plan_pairs(tick)]
                        self._persist_phase(tick, phase, state)
                    pairs = [tuple(pair) for pair in state["conversation_pairs"]]
                    await self.conversations.evening(tick, pairs=pairs)
                elif phase == "MEMORY":
                    if not state.get("observations_captured"):
                        with self.store.savepoint(f"tick_{tick}_observations"):
                            self.runtime.capture_event_observations(tick)
                        state["observations_captured"] = True
                        self._persist_phase(tick, phase, state)
                    await self.runtime.compress_memories(tick)
                elif phase == "FINALIZE":
                    try:
                        with self.store.savepoint(f"tick_{tick}_finalize"):
                            self._phase_finalize(tick)
                    except ReconciliationError as exc:
                        self._record_reconciliation_halt(
                            tick, "FINALIZE", getattr(exc, "diagnostic", {}))
                        raise

                operational_log(
                    logger, logging.INFO, "world.phase.completed",
                    run_id=self.gateway.run_id, tick=tick, phase=phase,
                    duration_ms=round(
                        (time.perf_counter() - phase_started) * 1000.0, 2))
                if index + 1 < len(self.phases):
                    self._persist_phase(tick, self.phases[index + 1], state)
                else:
                    self.store.set_meta(
                        tick=tick, active_tick=None, next_phase="NIGHT_CLOSE",
                        phase=self.phases[-1], phase_state_json="{}", legacy_partial=0)
                    self._save_prng_state()
                    self.store.commit()

            summary = {"tick": tick, "wall_s": round(time.time() - t0, 3),
                       "decisions": decisions_count,
                       "governor": self.gateway.governor.status()}
            self._record_runtime_tick(tick, summary)
            if self.checkpoint_every and tick % self.checkpoint_every == 0:
                self.checkpoint(tick)
            operational_log(logger, logging.INFO, "world.tick.completed",
                            run_id=self.gateway.run_id, tick=tick, phase=phase,
                            wall_s=summary["wall_s"], decisions=decisions_count)
            self._notify_tick(tick, summary)
            return summary
        except BudgetExceeded as exc:
            return self._pause_safely(
                tick, phase, "budget", self.gateway.governor.status(), t0,
                detail=str(exc))
        except ProviderUnavailable as exc:
            return self._pause_safely(
                tick, phase, "provider", exc.as_dict(), t0,
                detail=str(exc))
        except GatewayInterrupted as exc:
            summary = {
                "tick": self.store.tick,
                "active_tick": tick,
                "phase": phase,
                "interrupted": "stop" if self._stop_requested else "pause",
                "detail": str(exc),
                "governor": self.gateway.governor.status(),
            }
            self._notify_tick(self.store.tick, summary)
            return summary

    def _record_runtime_tick(self, tick: int, summary: dict) -> None:
        """Persist host/provider timing as non-authoritative acceptance evidence."""
        if self.engine_semantics_version < 11:
            return
        attempts = self.store.query_one(
            "SELECT COUNT(*) attempts,"
            "SUM(CASE WHEN outcome='success' THEN 1 ELSE 0 END) successes,"
            "SUM(CASE WHEN outcome<>'success' THEN 1 ELSE 0 END) failures,"
            "SUM(fallback_used) fallbacks,SUM(rate_limited) rate_limits "
            "FROM llm_attempts WHERE tick=?", (int(tick),))
        runtime = self.gateway.runtime_status()
        global_runtime = runtime["global"]
        self.store.execute(
            "INSERT OR REPLACE INTO runtime_tick_stats("
            "tick,wall_ms,decisions,llm_attempts,llm_successes,llm_failures,"
            "fallbacks,rate_limits,peak_live_in_flight,peak_queue_depth) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                int(tick), round(float(summary.get("wall_s", 0.0)) * 1000.0, 3),
                max(0, int(summary.get("decisions", 0))),
                int(attempts["attempts"] or 0), int(attempts["successes"] or 0),
                int(attempts["failures"] or 0), int(attempts["fallbacks"] or 0),
                int(attempts["rate_limits"] or 0),
                int(global_runtime["peak_in_flight"]),
                int(global_runtime["peak_queue_depth"]),
            ),
        )
        self.store.commit()

    def _notify_tick(self, tick: int, summary: dict) -> None:
        if self.on_tick:
            try:
                self.on_tick(tick, summary)
            except Exception as exc:
                operational_log(logger, logging.WARNING, "world.tick_callback.failed",
                                run_id=self.gateway.run_id, tick=tick,
                                error_type=type(exc).__name__, error=str(exc))

    def _pause_safely(self, tick: int, phase: str, reason: str, payload: dict,
                      started_at: float, *, detail: str = "") -> dict:
        """Commit a consistent partial tick and a durable, resumable pause record."""
        ok, diag = self.economy.ledger.reconcile()
        if not ok:
            self.status = "halted"
            self.store.log_event(tick, "reconciliation_failure", diag,
                                 phase=phase, importance=5.0)
            self.store.set_meta(
                status="halted", active_tick=tick, next_phase=phase, phase=phase)
            self.store.commit()
            self.checkpoint(self.store.tick, reason="halt")
            operational_log(logger, logging.CRITICAL, "world.reconciliation.failed",
                            run_id=self.gateway.run_id, tick=tick, phase=phase,
                            pause_reason=reason, diagnostic=diag)
            raise ReconciliationError(
                f"tick {tick}: books failed while pausing after {reason}: {diag}")

        event_kind = "budget_pause" if reason == "budget" else "provider_pause"
        event_payload = {**payload, "phase": phase, "detail": detail[:500]}
        self.status = "paused"
        self._pause_requested = True
        self.last_pause_reason = {"reason": reason, **event_payload}
        self.store.log_event(tick, event_kind, event_payload, phase=phase, importance=4.5)
        self.store.set_meta(
            status="paused", active_tick=tick, next_phase=phase, phase=phase)
        self.store.commit()
        self.checkpoint(self.store.tick, reason=event_kind)
        operational_log(logger, logging.WARNING, "world.pause.completed",
                        run_id=self.gateway.run_id, tick=tick, phase=phase,
                        reason=reason, detail=detail)
        summary = {
            "tick": self.store.tick, "active_tick": tick,
            "wall_s": round(time.time() - started_at, 3),
            "decisions": 0, "paused": reason, "phase": phase,
            "pause_reason": self.last_pause_reason,
            "governor": self.gateway.governor.status(),
        }
        self._notify_tick(self.store.tick, summary)
        return summary

    # ── phases ───────────────────────────────────────────────────────────────
    def _record_reconciliation_halt(self, tick: int, phase: str, diag: dict) -> None:
        self.status = "halted"
        self.store.log_event(
            tick, "reconciliation_failure", diag,
            phase=phase, importance=5.0)
        self.store.set_meta(
            status="halted", active_tick=tick,
            next_phase=phase, phase=phase)
        self.store.commit()
        self.checkpoint(self.store.tick, reason="halt")

    def _phase_night_close(self, tick: int) -> None:
        e = self.economy
        # A legacy semantics-7 run may opt into a forward-only supply recovery.
        # Its one-time endowment is a normal balanced ledger transaction and is
        # applied before payroll/production at the configured untouched tick.
        self._apply_supply_recovery_recapitalization(tick)
        self._enforce_workforce_recovery_job_floor(tick)
        if self.engine_semantics_version >= 12:
            # Fixed-slot presence is resolved before production. An office
            # appointment removes a worker from output, but not from payroll.
            e.city.run_nightly(tick)
        # Interest on savings (annual rate ≈ policy - 200bps, floored at 0).
        self._accrue_savings_interest(tick)
        # Loan payments + defaults.
        e.bank.process_due_loans(tick)
        # Payroll.
        e.firms.process_payroll(tick)
        # Production.
        e.firms.produce(tick)
        # Lifecycle draws (illness, deaths + estates, aging, retirement, births).
        e.lifecycle.run_nightly(tick)
        # Government: unemployment benefits + periodic elections (P1 R12).
        e.gov.run_nightly(tick)
        # VC portfolio sweep: write-offs + stale pitches (P1 R13).
        e.vc.run_nightly(tick)
        # v2 legal kernel: activate contracts, detect due breaches, and expire orders.
        if self.engine_semantics_version >= 4:
            e.legal.run_nightly(tick)
            e.information.run_nightly(tick)
            e.politics.run_nightly(tick)
            if self.engine_semantics_version >= 5:
                e.regions.run_nightly(tick)
        if self.engine_semantics_version >= 11:
            e.cognition.run_nightly(tick)
        # Arrivals due today (stable population).
        self._spawn_due_arrivals(tick)
        # Bank liquidity check: any open bank below required reserves seeks support.
        self._bank_liquidity_sweep(tick)
        # Shock evaluation.
        self.shocks.evaluate(tick)
        if self.engine_semantics_version < 2:
            # Markerless historical databases retain their original tick contract.
            self.metrics.snapshot(tick)
            self.oracle.resolve_open(tick)
        # Reconcile scheduled/opening mechanics before any LLM decisions.
        self._assert_reconciled(tick, "NIGHT_CLOSE")

    def _apply_supply_recovery_recapitalization(self, tick: int) -> None:
        firms_config = self.config.get("firms", {})
        activation_tick = firms_config.get(
            "workforce_recovery_recapitalization_tick")
        if activation_tick is None or int(tick) < int(activation_tick):
            return
        if self.store.query_one(
                "SELECT 1 FROM events "
                "WHERE kind='supply_recovery_recapitalization_applied' LIMIT 1"):
            return

        target_headcount = max(0, int(firms_config.get(
            "workforce_recovery_target_headcount",
            firms_config.get("target_headcount", 0),
        )))
        capital_per_worker = max(0, int(firms_config.get(
            "workforce_recovery_capital_per_worker_cents", 0)))
        target_capital = target_headcount * capital_per_worker
        excluded = [
            str(value).strip().lower()
            for value in firms_config.get(
                "workforce_recovery_excluded_sectors",
                ["health", "insurance"],
            )
        ]
        where = "status IN ('private','listed')"
        params: list[object] = []
        if excluded:
            where += (
                " AND lower(COALESCE(sector,'')) NOT IN ("
                + ",".join("?" for _ in excluded)
                + ")"
            )
            params.extend(excluded)
        eligible = self.store.query(
            "SELECT id,account_id,currency_code,sector FROM firms "
            f"WHERE {where} ORDER BY id",
            params,
        )

        total_endowment = 0
        funded_firms = 0
        for firm in eligible:
            account_id = int(firm["account_id"])
            previous_balance = self.economy.ledger.balance(account_id)
            shortfall = max(0, target_capital - previous_balance)
            if shortfall <= 0:
                continue
            currency = str(firm["currency_code"] or "USD")
            external = self.economy.ledger.system_account(
                SYS_EXTERNAL, currency_code=currency)
            self.economy.ledger.post(
                tick,
                "supply_recovery_recapitalization",
                [
                    Leg(account_id, shortfall, "legacy operating-capital correction"),
                    Leg(external, -shortfall, "external recovery endowment"),
                ],
                memo=f"forward-only supply recovery firm {int(firm['id'])}",
            )
            self.store.log_event(
                tick,
                "supply_recovery_recapitalized",
                {
                    "firm_id": int(firm["id"]),
                    "sector": str(firm["sector"] or ""),
                    "currency_code": currency,
                    "previous_balance_cents": previous_balance,
                    "target_balance_cents": target_capital,
                    "endowment_cents": shortfall,
                    "source_account": SYS_EXTERNAL,
                },
                phase="NIGHT_CLOSE",
                subject_type="firm",
                subject_id=int(firm["id"]),
                importance=2.5,
            )
            total_endowment += shortfall
            funded_firms += 1

        self.store.log_event(
            tick,
            "supply_recovery_recapitalization_applied",
            {
                "activation_tick": int(activation_tick),
                "eligible_firms": len(eligible),
                "funded_firms": funded_firms,
                "target_headcount": target_headcount,
                "capital_per_worker_cents": capital_per_worker,
                "target_balance_cents": target_capital,
                "total_endowment_cents": total_endowment,
                "excluded_sectors": excluded,
            },
            phase="NIGHT_CLOSE",
            importance=3.0,
        )

    def _enforce_workforce_recovery_job_floor(self, tick: int) -> None:
        firms_config = self.config.get("firms", {})
        activation_tick = firms_config.get(
            "workforce_recovery_wage_floor_activation_tick")
        operational_tick = firms_config.get(
            "workforce_recovery_operational_activation_tick")
        if (
            activation_tick is None
            or operational_tick is None
            or tick < int(activation_tick)
        ):
            return
        minimum_wage = max(0, int(firms_config.get(
            "workforce_recovery_min_wage_cents", 0)))
        excluded = {
            str(value).strip().lower()
            for value in firms_config.get(
                "workforce_recovery_excluded_sectors",
                ["health", "insurance"],
            )
        }
        rows = self.store.query(
            "SELECT j.id,j.firm_id,j.wage_cents,f.sector "
            "FROM jobs j JOIN firms f ON f.id=j.firm_id "
            "WHERE j.status='open' AND j.tick>=? AND j.wage_cents<? "
            "AND f.status IN ('private','listed') ORDER BY j.id",
            (int(operational_tick), minimum_wage),
        )
        for job in rows:
            if str(job["sector"] or "").strip().lower() in excluded:
                continue
            job_id = int(job["id"])
            application_count = int(self.store.scalar(
                "SELECT COUNT(*) FROM applications WHERE job_id=? "
                "AND state IN ('pending','negotiating')",
                (job_id,),
                default=0,
            ))
            self.store.execute(
                "UPDATE job_offers SET status='expired',decided_tick=? "
                "WHERE status='pending' AND application_id IN "
                "(SELECT id FROM applications WHERE job_id=?)",
                (tick, job_id),
            )
            self.store.execute(
                "UPDATE applications SET state='rejected' "
                "WHERE job_id=? AND state IN ('pending','negotiating')",
                (job_id,),
            )
            self.store.update("jobs", job_id, status="closed")
            self.store.log_event(
                tick,
                "workforce_recovery_job_floor_enforced",
                {
                    "job_id": job_id,
                    "firm_id": int(job["firm_id"]),
                    "sector": str(job["sector"] or ""),
                    "posted_wage_cents": int(job["wage_cents"]),
                    "minimum_wage_cents": minimum_wage,
                    "applications_rejected": application_count,
                },
                phase="NIGHT_CLOSE",
                subject_type="job",
                subject_id=job_id,
                importance=2.0,
            )

    def _phase_finalize(self, tick: int) -> None:
        if self.engine_semantics_version >= 12:
            # Civic maintenance stays inside the existing single-writer phase.
            self.economy.city.finalize(tick)
        # Tick-T metrics describe the completed day, including its settled actions.
        self.metrics.snapshot(tick)
        # Predictions resolve against completed-day state.
        self.oracle.resolve_open(tick)
        # The completed-tick invariant includes every action settled today.
        self._assert_reconciled(tick, "FINALIZE")
        if self.engine_semantics_version >= 8:
            domains = [
                "summary", "events", "communications", "causal", "snapshot",
            ]
            if self.engine_semantics_version >= 12:
                domains.extend(["city", "attention"])
            self.store.execute(
                "INSERT OR IGNORE INTO projection_commits (tick,phase,domains_json) "
                "VALUES (?,'FINALIZE',?)",
                (
                    int(tick),
                    json.dumps(domains, separators=(",", ":")),
                ),
            )

    def _assert_reconciled(self, tick: int, phase: str) -> None:
        ok, diag = self.economy.ledger.reconcile()
        if not ok:
            dump_path = Path(self.store.path).with_suffix(f".halt_t{tick}.json")
            dump_path.write_text(json.dumps(diag, indent=2))
            exc = ReconciliationError(
                f"tick {tick} {phase}: books do not reconcile → {dump_path}")
            exc.diagnostic = diag
            raise exc

    def _accrue_savings_interest(self, tick: int) -> None:
        rate_bps = max(0, self.economy.policy_rate_bps() - 200)
        if rate_bps <= 0:
            return
        daily = rate_bps / 10000.0 / 365.0
        rows = self.store.query(
            "SELECT a.id, a.balance_cents, a.bank_id FROM accounts a JOIN banks b ON b.id=a.bank_id "
            "WHERE a.kind='savings' AND a.balance_cents>0 AND b.status='open'")
        from engine.ledger import Leg
        for r in rows:
            interest = int(int(r["balance_cents"]) * daily)
            if interest <= 0:
                continue
            bank = self.economy.bank.get(int(r["bank_id"]))
            eq = int(bank["equity_account_id"])
            # Bank pays interest out of its equity (if equity lacks funds it still
            # posts — equity may go negative, which is meaningful: a weak bank).
            self.economy.ledger.post(tick, "savings_interest", [
                Leg(int(r["id"]), interest, "interest"), Leg(eq, -interest, "interest expense")])

    def _bank_liquidity_sweep(self, tick: int) -> None:
        for b in self.store.query("SELECT * FROM banks WHERE status='open'"):
            bid = int(b["id"])
            cb = self.economy.central_bank_reserve_acct(
                str(b["currency_code"] or "USD"))
            required = int(self.economy.bank.deposits(bid) *
                           int(b["reserve_requirement_bps"]) / 10000)
            shortfall = required - self.economy.bank.reserves(bid)
            if shortfall > 0:
                supported = False
                if cb is not None:
                    supported = self.economy.bank.attempt_liquidity_support(
                        tick, bid, shortfall, cb,
                        require_authorized_decision=self.engine_semantics_version >= 6,
                        phase="NIGHT_CLOSE", source="night_close")
                # ``None`` is a durable semantics-6 request awaiting the normal
                # MORNING decision/EXECUTION proposal path. Only an explicit
                # legacy denial or missing central bank fails immediately.
                if supported is False:
                    self.economy.bank.fail_bank(tick, bid)

    def _phase_market(self, tick: int) -> None:
        for f in self.store.query("SELECT id FROM firms WHERE status='listed'"):
            self.economy.exchange.match_firm(tick, int(f["id"]))
        self.economy.exchange.expire_session(tick)
        if self.engine_semantics_version >= 5:
            self.economy.regions.match_fx(tick)
        self.economy.labor.expire_stale_jobs(tick, phase="MARKET")
        # Expire stale pending loan applications (older than a week).
        self.store.execute(
            "UPDATE loan_applications SET status='expired' WHERE status='pending' AND tick < ?",
            (tick - 7,))

    # ── arrivals (R11: minted from population_inflow, visible + conserved) ────
    def _spawn_due_arrivals(self, tick: int) -> None:
        due_ids = self.economy.lifecycle.pending_arrivals(tick)
        if not due_ids:
            return
        banks = [int(r["id"]) for r in self.store.query("SELECT id FROM banks WHERE status='open'")]
        if not banks:
            return
        outlets = self.config.get("outlets", [{"id": 1}, {"id": 2}])
        outlet_ids = configured_outlet_ids(outlets)
        for sched_id in due_ids:
            if self.engine_semantics_version >= 7:
                p = sample_arrival_persona(self.persona_prng, outlet_ids)
            else:
                p = sample_persona(self.persona_prng, n_outlets=len(outlets))
            external_identity = self.runtime.external.arrival_overrides(sched_id)
            # The public identity is decided once so the agents row and the
            # public arrival event never disagree about who moved to town.
            arrival_name = (
                external_identity["name"] if external_identity else p.name)
            arrival_occupation = (
                external_identity["occupation"]
                if external_identity and external_identity["occupation"]
                else p.occupation)
            region_id = self.economy.regions.region_for_new_citizen() \
                if self.economy.regions.enabled else None
            bank_id = self.economy.regions.bank_for_region(banks, region_id) \
                if self.economy.regions.enabled else self.engine_prng.choice(banks)
            currency = self.economy.regions.currency_for_region(region_id)
            baseline_core = (
                self.engine_semantics_version >= 7
                and bool(self.config.get("population", {}).get(
                    "baseline_citizens_core", False))
                and not self.economy.regions.enabled)
            agent_id = self.store.insert(
                "agents", name=arrival_name,
                kind="citizen", occupation=arrival_occupation,
                age=max(20, min(55, p.age)), health="healthy", dependents=p.dependents,
                personality_json=json.dumps(p.personality), political_lean=p.political_lean,
                media_diet_json=json.dumps(p.media_diet), risk_tolerance=p.risk_tolerance,
                cadence_json=json.dumps({"act": 2, "portfolio": 7, "career": 30}),
                model_tier="citizen",
                population_tier="core" if baseline_core else "periphery",
                pinned_core=1 if baseline_core else 0, region_id=region_id,
                alive=1, retired=0, arrived_tick=tick)
            if self.engine_semantics_version >= 7:
                checking_cents = int(p.wealth_cents * 0.7)
                savings_cents = p.wealth_cents - checking_cents
            else:
                checking_cents = int(p.wealth_cents * 0.6)
                savings_cents = 0
            chk = self.economy.ledger.create_account(
                "agent", agent_id, "checking", bank_id=bank_id,
                label=f"agent:{agent_id}:checking", opening_cents=checking_cents,
                funding_label=SYS_INFLOW, tick=tick, currency_code=currency)
            if self.engine_semantics_version >= 7:
                sav = self.economy.ledger.create_account(
                    "agent", agent_id, "savings", bank_id=bank_id,
                    label=f"agent:{agent_id}:savings", opening_cents=savings_cents,
                    funding_label=SYS_INFLOW, tick=tick, currency_code=currency)
                self.store.update(
                    "agents", agent_id, checking_account_id=chk,
                    savings_account_id=sav)
            else:
                self.store.update("agents", agent_id, checking_account_id=chk)
            self.economy.cognition.seed_agent(agent_id, tick)
            # A new adult immediately takes on a visible move-in/rent cost. The
            # system housing account keeps the payment conserved and auditable.
            housing_cost = max(0, int(self.config.get("lifecycle", {}).get(
                "housing_cost_cents", 75_000)))
            housing_paid = min(housing_cost, self.economy.ledger.balance(chk))
            if housing_paid:
                self.economy.ledger.transfer(
                    tick, chk, self.economy.ledger.system_account(
                        SYS_HOUSING, currency_code=currency),
                    housing_paid, kind="housing_cost", memo="arrival move-in and rent")
                self.store.log_event(
                    tick, "housing_cost", {"agent_id": agent_id,
                                           "amount_cents": housing_paid,
                                           "reason": "arrival"},
                    phase="NIGHT_CLOSE", subject_type="agent",
                    subject_id=agent_id, importance=1.5)
            # Social ties to a few residents + starting beliefs.
            residents = [int(r["id"]) for r in self.store.query(
                "SELECT id FROM agents WHERE alive=1 AND id<>? ORDER BY id", (agent_id,))]
            for other in self.engine_prng.sample(residents, min(3, len(residents))):
                lo, hi = min(agent_id, other), max(agent_id, other)
                self.store.insert("social_ties", agent_a=lo, agent_b=hi,
                                  weight=round(self.engine_prng.uniform(0.2, 0.7), 3))
            for bid in banks:
                self.store.insert("beliefs", agent_id=agent_id, key=f"trust:bank:{bid}",
                                  value=0.6, updated_tick=tick)
            self.runtime.mem.observe(agent_id, tick,
                                     "I just moved to town. I need to find work and settle in.",
                                     importance=3.0, entities=["self", "arrival"])
            self.store.log_event(
                tick, "job_search_started", {"agent_id": agent_id, "reason": "arrival"},
                phase="NIGHT_CLOSE", subject_type="agent", subject_id=agent_id,
                importance=1.5)
            self.runtime.external.bind_arrival(sched_id, agent_id, tick)
            arrival_payload = {
                "agent_id": agent_id, "name": arrival_name,
                "occupation": arrival_occupation,
                "schedule_event_id": sched_id}
            if self.engine_semantics_version >= 7:
                arrival_payload.update({
                    "checking_cents": checking_cents,
                    "savings_cents": savings_cents,
                })
            self.store.log_event(tick, "arrival", arrival_payload, phase="NIGHT_CLOSE",
                subject_type="agent", subject_id=agent_id, importance=2.0)

    # ── checkpoints (SQLite backup + PRNG state, TECH-SPEC §13) ──────────────
    def checkpoint(self, tick: int, reason: str = "interval") -> Optional[str]:
        try:
            self._save_prng_state()
            # SQLite backup only sees committed pages from its separate source
            # connection. Commit status/events/PRNG before taking the snapshot.
            self.store.commit()
            ckpt_dir = Path(self.config.get("checkpoint_dir", "data/checkpoints"))
            ckpt_dir.mkdir(parents=True, exist_ok=True)
            run_id = self.store.get_meta()["run_id"]
            dest = ckpt_dir / f"{run_id}_t{tick}.db"
            src = __import__("sqlite3").connect(self.store.path)
            dst = __import__("sqlite3").connect(str(dest))
            with dst:
                src.backup(dst)
            src.close(); dst.close()
            finalize_sqlite_artifact(dest)
            write_checkpoint_manifest(dest)
            created_at = __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc).isoformat()
            existing = self.store.query_one(
                "SELECT id FROM checkpoints WHERE tick=? AND path=? ORDER BY id LIMIT 1",
                (tick, str(dest)),
            )
            if existing is None:
                self.store.insert(
                    "checkpoints", tick=tick, path=str(dest), created_at=created_at)
            else:
                # Interval completion, Run teardown, and an explicit Stop can all
                # checkpoint the same committed tick. The snapshot should be
                # refreshed, but its catalog entry is one logical artifact.
                self.store.execute(
                    "UPDATE checkpoints SET created_at=? WHERE id=?",
                    (created_at, int(existing["id"])),
                )
            self.store.commit()
            try:
                keep_last = int(self.config.get("checkpoint_keep_last", 0) or 0)
            except (TypeError, ValueError):
                keep_last = 0
            if keep_last > 0:
                self._prune_checkpoints(run_id, keep_last)
            operational_log(logger, logging.INFO, "world.checkpoint.created",
                            run_id=run_id, tick=tick, reason=reason, path=str(dest))
            return str(dest)
        except Exception as exc:
            self.store.log_event(tick, "checkpoint_failed", {"error": str(exc)}, importance=2.0)
            operational_log(logger, logging.ERROR, "world.checkpoint.failed",
                            run_id=self.gateway.run_id, tick=tick, reason=reason,
                            error_type=type(exc).__name__, error=str(exc))
            return None

    def _prune_checkpoints(self, run_id: str, keep_last: int) -> None:
        """Retain only the newest safe, current-run checkpoint rows and artifacts."""
        if keep_last <= 0:
            return
        checkpoint_dir = Path(
            self.config.get("checkpoint_dir", "data/checkpoints")).resolve()
        candidates = []
        for row in self.store.query("SELECT id,tick,path FROM checkpoints"):
            try:
                tick = int(row["tick"])
                stored_path = Path(str(row["path"])).resolve()
                expected_path = checkpoint_dir / f"{run_id}_t{tick}.db"
                resolved_expected = expected_path.resolve()
            except (OSError, RuntimeError, TypeError, ValueError):
                continue
            if (not resolved_expected.is_relative_to(checkpoint_dir)
                    or stored_path != resolved_expected):
                continue
            candidates.append((row, expected_path))
        candidates.sort(
            key=lambda item: (int(item[0]["tick"]), int(item[0]["id"])),
            reverse=True)
        retained_paths = {path for _, path in candidates[:keep_last]}
        for row, database in candidates[keep_last:]:
            if database not in retained_paths:
                deletion_failed = False
                for artifact in (Path(f"{database}.manifest.json"), database):
                    try:
                        artifact.unlink()
                    except FileNotFoundError:
                        continue
                    except OSError as exc:
                        self.store.log_event(
                            self.store.tick,
                            "checkpoint_prune_failed",
                            {
                                "checkpoint_id": int(row["id"]),
                                "checkpoint_tick": int(row["tick"]),
                                "path": artifact.name,
                                "error": type(exc).__name__,
                                "error_type": type(exc).__name__,
                            },
                            importance=2.0,
                        )
                        self.store.commit()
                        deletion_failed = True
                        break
                if deletion_failed:
                    continue
            self.store.execute(
                "DELETE FROM checkpoints WHERE id=?", (int(row["id"]),))
            self.store.commit()

    def _save_prng_state(self) -> None:
        engine_state = _prng_state(self.engine_prng)
        if self.engine_semantics_version >= 7:
            engine_state = {
                "engine": engine_state,
                "persona": _prng_state(self.persona_prng),
            }
        self.store.set_meta(
            prng_state=json.dumps(engine_state),
            lifecycle_prng_state=json.dumps(_prng_state(self.lifecycle_prng)),
            governor_json=json.dumps(self.gateway.governor.status()))

    def restore_prng_state(self) -> None:
        meta = self.store.get_meta()
        if meta["prng_state"]:
            engine_state = json.loads(meta["prng_state"])
            if isinstance(engine_state, dict):
                self.engine_prng.setstate(_from_state(engine_state["engine"]))
                self.persona_prng.setstate(_from_state(engine_state["persona"]))
            else:
                # Stored semantics 1-6 and pre-fix semantics-7 runs retain the
                # historical list-form resume contract.
                self.engine_prng.setstate(_from_state(engine_state))
        if meta["lifecycle_prng_state"]:
            self.lifecycle_prng.setstate(_from_state(json.loads(meta["lifecycle_prng_state"])))


def _prng_state(r: random.Random):
    s = r.getstate()
    return [s[0], list(s[1]), s[2]]


def _from_state(s):
    return (s[0], tuple(s[1]), s[2])


def new_run_id() -> str:
    return uuid.uuid4().hex[:10]

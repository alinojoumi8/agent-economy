"""Runtime coordination for the Observatory server.

The FastAPI app owns HTTP composition. This controller owns the mutable world
task, event-loop handoff, run transitions, and WebSocket fan-out so those
concerns do not live in one large route-registration closure.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from concurrent.futures import Future
from contextlib import asynccontextmanager
from threading import Lock
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, WebSocket

from engine.ledger import ReconciliationError
from engine.store import load_json
from observability import get_logger, log_event as operational_log
from world.loop import World


logger = get_logger("server")


class WebSocketHub:
    """Track dashboard clients and fan out structured server events."""

    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.clients.add(websocket)
        operational_log(logger, logging.INFO, "websocket.connected",
                        clients=len(self.clients))

    def disconnect(self, websocket: WebSocket) -> None:
        self.clients.discard(websocket)
        operational_log(logger, logging.INFO, "websocket.disconnected",
                        clients=len(self.clients))

    async def broadcast(self, message: dict) -> None:
        dead = []
        for websocket in list(self.clients):
            try:
                await websocket.send_text(json.dumps(message))
            except Exception as exc:
                dead.append(websocket)
                operational_log(logger, logging.WARNING, "websocket.broadcast.failed",
                                clients=len(self.clients), error_type=type(exc).__name__,
                                error=str(exc))
        for websocket in dead:
            self.disconnect(websocket)


class RunController:
    """Own the live world's task, transitions, and dashboard notifications."""

    def __init__(self, world: World, *, served_ticks: int | None = None,
                 hosted_safe: bool = False) -> None:
        self.world = world
        self.store = world.store
        self.hub = WebSocketHub()
        self.task: asyncio.Task[None] | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self._control_lock = asyncio.Lock()
        self._tick_broadcasts: set[Future[None]] = set()
        self._tick_broadcasts_lock = Lock()
        self.world.on_tick = self.on_tick
        self.participant = world.runtime.participant
        acceptance = world.config.get("acceptance", {})
        # Desktop profiles also use the acceptance block for rehearsal and
        # performance targets.  Only a configured horizon denotes a governed
        # acceptance campaign whose dashboard controls must stay locked until
        # --acceptance-run authorizes it.
        self.acceptance_configured = (
            isinstance(acceptance, dict) and "min_ticks" in acceptance)
        self.acceptance_authorized = bool(getattr(world, "acceptance_authorized", False))
        self.acceptance_target_tick = int(getattr(
            world, "acceptance_target_tick",
            acceptance.get("min_ticks", 365)))
        self.target_tick = (
            self.acceptance_target_tick if self.acceptance_authorized
            else self.store.tick + int(served_ticks) if served_ticks is not None
            else None)
        self.acceptance_artifacts: dict = {}
        self.hosted_safe = bool(hosted_safe)

    def is_running(self) -> bool:
        return bool(self.task and not self.task.done())

    def remaining_ticks(self) -> int | None:
        if self.target_tick is None:
            return None
        return max(0, self.target_tick - self.store.tick)

    def _require_mutable(self, action: str) -> None:
        if self.world.status == "halted":
            raise HTTPException(
                status_code=409,
                detail=f"run is halted; {action} requires a new run or replay")

    def _reopen_finished(self) -> None:
        if self.world.status != "finished":
            return
        self.world._stop_requested = False
        self.world.last_report_path = None
        self.world.status = "paused"
        self.store.set_meta(status="paused")
        self.store.commit()

    @asynccontextmanager
    async def lifespan(self, _app: FastAPI) -> AsyncIterator[None]:
        self.loop = asyncio.get_running_loop()
        operational_log(logger, logging.INFO, "server.started",
                        run_id=self.world.gateway.run_id, tick=self.store.tick)
        if self.acceptance_authorized:
            await self.start()
        try:
            yield
        finally:
            replay_reader = getattr(_app.state, "replay_reader", None)
            if replay_reader is not None:
                replay_reader.close()
            operator_workspace = getattr(_app.state, "operator_workspace", None)
            if operator_workspace is not None:
                operator_workspace.close()
            citizenship_service = getattr(
                _app.state, "citizenship_service", None)
            if citizenship_service is not None:
                citizenship_service.close()
            operational_log(logger, logging.INFO, "server.stopped",
                            run_id=self.world.gateway.run_id, tick=self.store.tick,
                            run_active=self.is_running())
            self.loop = None

    def on_tick(self, tick: int, summary: dict) -> None:
        if self.loop is None or not self.loop.is_running():
            return
        messages = [self.tick_payload(tick, summary)]
        if int(getattr(self.world, "engine_semantics_version", 1)) >= 8:
            from server.projections.transport import projection_delta_message
            messages.append(projection_delta_message(self.store, tick=tick))

        async def broadcast_all() -> None:
            for message in messages:
                await self.hub.broadcast(message)

        future = asyncio.run_coroutine_threadsafe(broadcast_all(), self.loop)
        with self._tick_broadcasts_lock:
            self._tick_broadcasts.add(future)
        future.add_done_callback(self._tick_broadcast_done)

    def _tick_broadcast_done(self, future: Future[None]) -> None:
        with self._tick_broadcasts_lock:
            self._tick_broadcasts.discard(future)
        try:
            future.result()
        except Exception as exc:
            operational_log(
                logger, logging.WARNING, "websocket.tick_broadcast.failed",
                run_id=self.world.gateway.run_id, tick=self.store.tick,
                error_type=type(exc).__name__, error=str(exc))

    async def _drain_tick_broadcasts(self) -> None:
        while True:
            with self._tick_broadcasts_lock:
                pending = tuple(self._tick_broadcasts)
            if not pending:
                return
            await asyncio.gather(
                *(asyncio.wrap_future(future) for future in pending),
                return_exceptions=True)
            with self._tick_broadcasts_lock:
                self._tick_broadcasts.difference_update(
                    future for future in pending if future.done())

    def tick_payload(self, tick: int, summary: dict) -> dict:
        payload = build_tick_payload(self.world, tick, summary)
        if self.hosted_safe:
            payload.pop("report_path", None)
            payload["report_artifact"] = {
                "available": bool(self.world.last_report_path), "kind": "report"}
        payload.update({
            "running": self.is_running(),
            "target_tick": self.target_tick,
            "remaining_ticks": self.remaining_ticks(),
        })
        return payload

    def run_status_payload(self, *, running: bool | None = None) -> dict:
        payload = {
            "type": "run_status",
            "tick": self.store.tick,
            "status": self.world.status,
            "running": self.is_running() if running is None else running,
            "target_tick": self.target_tick,
            "remaining_ticks": self.remaining_ticks(),
            "governor": self.world.gateway.governor.status(),
            "pause_reason": self.world.last_pause_reason,
        }
        if self.hosted_safe:
            payload["report_artifact"] = {
                "available": bool(self.world.last_report_path), "kind": "report"}
        else:
            payload["report_path"] = self.world.last_report_path
        return payload

    async def _run_world(self, max_ticks: int | None) -> None:
        try:
            if self.acceptance_authorized:
                await self._run_acceptance(max_ticks)
            else:
                await self.world.run(max_ticks=max_ticks)
        except ReconciliationError as exc:
            operational_log(logger, logging.CRITICAL, "run.halted",
                            run_id=self.world.gateway.run_id, tick=self.store.tick,
                            error_type=type(exc).__name__, error=str(exc))
            await self.hub.broadcast({"type": "halt", "reason": str(exc)})
        except Exception as exc:
            from reports.acceptance import AcceptanceCheckpointMissed
            if isinstance(exc, AcceptanceCheckpointMissed):
                self.world.status = "paused"
                self.world.last_pause_reason = {
                    "reason": "acceptance_checkpoint_missed", "detail": str(exc)}
                self.store.set_meta(status="paused")
                self.store.commit()
                operational_log(logger, logging.ERROR, "acceptance.checkpoint.missed",
                                run_id=self.world.gateway.run_id, tick=self.store.tick,
                                error=str(exc))
                await self.hub.broadcast({"type": "pause", "reason": str(exc)})
                return
            self.world.status = "paused"
            self.store.set_meta(status="paused")
            self.store.log_event(
                self.store.tick, "run_exception", {"error": str(exc)[:500]}, importance=5.0)
            self.store.commit()
            operational_log(logger, logging.ERROR, "run.unhandled_exception",
                            run_id=self.world.gateway.run_id, tick=self.store.tick,
                            error_type=type(exc).__name__, error=str(exc))
            await self.hub.broadcast({"type": "pause", "reason": f"run paused: {exc}"})
        finally:
            # Tick callbacks can be scheduled from worker threads. Await their
            # actual WebSocket sends before publishing the authoritative paused
            # or halted state so a yielding send cannot arrive stale afterward.
            await self._drain_tick_broadcasts()
            await self.hub.broadcast(self.run_status_payload(running=False))

    async def _run_acceptance(self, max_ticks: int | None) -> None:
        from reports.acceptance import advance_acceptance_run, write_acceptance_package
        from reports.generate import generate_report_async

        target = min(
            self.acceptance_target_tick,
            self.store.tick + int(max_ticks)) if max_ticks is not None else self.acceptance_target_tick
        status = await advance_acceptance_run(self.world, target_tick=target)
        if status["state"] != "completed" or self.store.tick < self.acceptance_target_tick:
            return
        report_path = await generate_report_async(
            self.store, self.world,
            out_dir=str(self.world.config.get("report_dir", "reports/out")))
        receipt = write_acceptance_package(
            self.store.path,
            out_dir=str(self.world.config.get("report_dir", "reports/out")),
            experiment_json=getattr(self.world, "acceptance_experiment_evidence", None),
            phenomena_yaml=getattr(self.world, "acceptance_phenomena_evidence", None),
        )
        self.world.last_report_path = report_path
        self.acceptance_artifacts = receipt.get("artifacts", {})
        operational_log(
            logger, logging.INFO, "acceptance.run.completed",
            run_id=self.world.gateway.run_id, tick=self.store.tick,
            passed=receipt.get("passed"), report_path=report_path,
            artifacts=self.acceptance_artifacts)

    async def start(self, max_ticks: int | None = None) -> dict:
        async with self._control_lock:
            return self._start_locked(max_ticks)

    def _start_locked(self, max_ticks: int | None = None) -> dict:
        self._require_mutable("start")
        if self.acceptance_configured and not self.acceptance_authorized:
            raise HTTPException(
                status_code=403,
                detail="acceptance runs must be launched with --acceptance-run and explicit live approval")
        if self.participant.active_agent_id() is not None:
            raise HTTPException(
                status_code=409,
                detail="continuous Run is disabled while a citizen is under participant control")
        if self.is_running():
            operational_log(logger, logging.INFO, "run.start.skipped",
                            run_id=self.world.gateway.run_id, tick=self.store.tick,
                            reason="already_running")
            return {"status": "already_running"}
        remaining = self.remaining_ticks()
        if remaining == 0:
            operational_log(logger, logging.INFO, "run.start.skipped",
                            run_id=self.world.gateway.run_id, tick=self.store.tick,
                            reason="served_tick_limit_reached", target_tick=self.target_tick)
            return {"status": "limit_reached", "tick": self.store.tick,
                    "target_tick": self.target_tick}
        self._reopen_finished()
        # A report describes one completed state boundary.  Once the world is
        # accepted for further execution, a prior artifact must not be returned
        # as though it described the later terminal tick.
        self.world.last_report_path = None
        self.world.last_pause_reason = None
        self.world._pause_requested = False
        self.world._stop_requested = False
        self.world.gateway.clear_interrupt()
        effective_max_ticks = max_ticks
        if remaining is not None:
            effective_max_ticks = (
                remaining if effective_max_ticks is None
                else min(remaining, effective_max_ticks))
        self.task = asyncio.create_task(self._run_world(effective_max_ticks))
        operational_log(logger, logging.INFO, "run.start.accepted",
                        run_id=self.world.gateway.run_id, tick=self.store.tick,
                        max_ticks=effective_max_ticks)
        return {"status": "running", "tick": self.store.tick}

    def pause(self) -> dict:
        self._require_mutable("pause")
        self.world.request_pause()
        operational_log(logger, logging.INFO, "run.pause.accepted",
                        run_id=self.world.gateway.run_id, tick=self.store.tick)
        return {"status": "pausing", "tick": self.store.tick}

    async def stop(self) -> dict:
        # Signal the world and any in-flight provider before waiting behind a
        # serialized Step. Final status/report mutation still occurs under the
        # control lock.
        self._require_mutable("stop")
        self.world.request_stop()
        async with self._control_lock:
            return await self._stop_locked()

    async def _stop_locked(self) -> dict:
        self._require_mutable("stop")
        if self.is_running():
            operational_log(logger, logging.INFO, "run.stop.accepted",
                            run_id=self.world.gateway.run_id, tick=self.store.tick,
                            running=True)
            return {"status": "stopping", "tick": self.store.tick}
        self.world.status = "finished"
        self.store.set_meta(status="finished")
        self.store.commit()
        self.world.checkpoint(self.store.tick, reason="stop")
        meta = self.store.get_meta()
        if meta["active_tick"] is not None:
            deferred = {
                "reason": "report_deferred_partial_tick",
                "active_tick": int(meta["active_tick"]),
                "phase": str(meta["next_phase"] or meta["phase"] or "unknown"),
                "detail": "finish the partial tick before generating an end-of-run report",
            }
            self.world.last_report_path = None
            self.world.last_pause_reason = deferred
            operational_log(
                logger, logging.WARNING, "run.stop.report_deferred",
                run_id=self.world.gateway.run_id, tick=self.store.tick,
                active_tick=deferred["active_tick"], phase=deferred["phase"])
            return {
                "status": "finished", "tick": self.store.tick,
                "report_path": None, "report_deferred": deferred,
            }
        if not self.world.last_report_path:
            from reports.generate import generate_report_async
            # No world/provider task is active while this control lock is held,
            # so it is safe to retire the Pause/Stop interrupt before the
            # independently bounded report call.
            self.world.gateway.clear_interrupt()
            self.world.last_report_path = await generate_report_async(
                self.store, self.world,
                out_dir=str(self.world.config.get("report_dir", "reports/out")))
        operational_log(logger, logging.INFO, "run.stop.completed",
                        run_id=self.world.gateway.run_id, tick=self.store.tick,
                        report_path=self.world.last_report_path)
        return {"status": "finished", "tick": self.store.tick,
                "report_path": self.world.last_report_path}

    async def generate_report(self) -> str:
        """Serialize report generation against Run/Step/Stop lifecycle changes."""
        async with self._control_lock:
            if self.is_running():
                raise HTTPException(
                    status_code=409,
                    detail="pause or stop the run before generating a report")
            meta = self.store.get_meta()
            if meta["active_tick"] is not None:
                raise HTTPException(
                    status_code=409,
                    detail="finish the active partial tick before generating a report")

            # A completed operator Pause leaves the gateway interrupt set.  No
            # simulation call can be active under this lock, so clearing it here
            # cannot race or revive an in-flight world request.
            self.world.gateway.clear_interrupt()
            from reports.generate import generate_report_async
            path = await generate_report_async(
                self.store, self.world,
                out_dir=str(self.world.config.get("report_dir", "reports/out")))
            self.world.last_report_path = path
            await self.hub.broadcast(self.run_status_payload(running=False))
            return path

    async def step(self) -> dict:
        async with self._control_lock:
            return await self._step_locked()

    async def _step_locked(self) -> dict:
        self._require_mutable("step")
        if self.is_running():
            operational_log(logger, logging.INFO, "run.step.skipped",
                            run_id=self.world.gateway.run_id, tick=self.store.tick,
                            reason="already_running")
            return {"status": "already_running"}
        if self.remaining_ticks() == 0:
            operational_log(logger, logging.INFO, "run.step.skipped",
                            run_id=self.world.gateway.run_id, tick=self.store.tick,
                            reason="served_tick_limit_reached", target_tick=self.target_tick)
            return {"status": "limit_reached", "tick": self.store.tick,
                    "target_tick": self.target_tick}
        if self.participant.active_agent_id() is not None and not self.participant.has_queued_action():
            raise HTTPException(
                status_code=409,
                detail="choose an explicit participant action, including do nothing, before Step")
        if self.acceptance_configured and not self.acceptance_authorized:
            raise HTTPException(
                status_code=403,
                detail="acceptance steps require --acceptance-run and explicit live approval")
        self._reopen_finished()
        self.world.last_report_path = None
        self.world.last_pause_reason = None
        self.world._pause_requested = False
        self.world._stop_requested = False
        self.world.gateway.clear_interrupt()
        if self.acceptance_configured:
            from reports.acceptance import advance_acceptance_run
            target = min(self.acceptance_target_tick, self.store.tick + 1)
            acceptance = await advance_acceptance_run(self.world, target_tick=target)
            self.world.status = "paused"
            self.store.set_meta(status="paused")
            self.store.commit()
            summary = {"tick": self.store.tick, "paused": True, "acceptance": acceptance}
            await self.hub.broadcast(self.tick_payload(self.store.tick, summary))
            return summary
        summary = await self.world.step()
        if not summary.get("paused") and self.world.status != "halted":
            self.world.status = "paused"
            self.store.set_meta(status="paused")
            self.store.commit()
        await self.hub.broadcast(self.tick_payload(summary["tick"], summary))
        operational_log(logger, logging.INFO, "run.step.completed",
                        run_id=self.world.gateway.run_id, tick=summary["tick"],
                        paused=summary.get("paused"))
        return summary

    def set_speed(self, delay_s: float) -> dict:
        self._require_mutable("speed change")
        self.world.speed_delay_s = max(0.0, float(delay_s))
        operational_log(logger, logging.INFO, "run.speed.changed",
                        run_id=self.world.gateway.run_id, tick=self.store.tick,
                        delay_s=self.world.speed_delay_s)
        return {"delay_s": self.world.speed_delay_s}

    def status(self) -> dict:
        meta = self.store.get_meta()
        orchestration = None
        if self.acceptance_configured:
            from reports.acceptance import acceptance_schedule_status
            orchestration = acceptance_schedule_status(
                self.store, self.world.config, target_tick=self.acceptance_target_tick)
            orchestration.update({
                "authorized": self.acceptance_authorized,
                "running": self.is_running(),
                "artifacts": {} if self.hosted_safe else self.acceptance_artifacts,
            })
        payload = {
            "run_id": meta["run_id"], "status": self.world.status,
            "tick": self.store.tick, "seed": meta["seed"],
            "active_tick": meta["active_tick"],
            "next_phase": meta["next_phase"],
            "legacy_partial": bool(meta["legacy_partial"]),
            "speed_delay_s": self.world.speed_delay_s,
            "target_tick": self.target_tick,
            "remaining_ticks": self.remaining_ticks(),
            "governor": self.world.gateway.governor.status(),
            "running": self.is_running(),
            "provider_readiness": self.world.gateway.readiness(),
            "rate_limit": self.world.gateway.rate_limit_status(),
            "pause_reason": self.world.last_pause_reason,
            "acceptance_orchestration": orchestration,
            "participant_active": self.participant.active_agent_id() is not None,
        }
        if self.hosted_safe:
            payload["report_artifact"] = {
                "available": bool(self.world.last_report_path), "kind": "report"}
        else:
            payload["report_path"] = self.world.last_report_path
        return payload


def build_tick_payload(world: World, tick: int, summary: dict) -> dict:
    """Build the dashboard's current world snapshot for HTTP and WebSockets."""
    store = world.store
    metric_names = ("gdp_proxy", "cpi", "unemployment", "index", "policy_rate",
                    "money_supply", "gini", "sentiment")
    metrics = {name: store.metric_latest(name, 0.0) for name in metric_names}
    events = [
        {"id": int(row["id"]), "tick": int(row["tick"]), "kind": row["kind"],
         "importance": row["importance"], "payload": load_json(row["payload_json"], {})}
        for row in store.query(
            "SELECT * FROM events WHERE tick=? AND importance>=1.5 ORDER BY id DESC LIMIT 12",
            (tick,))
    ]
    news = [
        {"headline": row["headline"], "outlet": row["outlet_name"], "tone": row["tone"]}
        for row in store.query(
            "SELECT * FROM news_articles WHERE tick=? ORDER BY id DESC LIMIT 4", (tick,))
    ]
    ticker = []
    for firm in store.query("SELECT id, name FROM firms WHERE status='listed'"):
        price = world.economy.exchange.last_price(int(firm["id"]))
        if price is not None:
            ticker.append({"firm_id": int(firm["id"]), "name": firm["name"],
                           "price_cents": price})
    return {
        "type": "tick", "tick": tick, "emitted_at_ms": int(time.time() * 1000),
        "summary": summary, "metrics": metrics, "events": events, "news": news,
        "ticker": ticker, "governor": world.gateway.governor.status(),
        "status": world.status, "pause_reason": world.last_pause_reason,
        "report_path": world.last_report_path,
    }

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
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, WebSocket

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

    def __init__(self, world: World) -> None:
        self.world = world
        self.store = world.store
        self.hub = WebSocketHub()
        self.task: asyncio.Task[None] | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.world.on_tick = self.on_tick

    def is_running(self) -> bool:
        return bool(self.task and not self.task.done())

    @asynccontextmanager
    async def lifespan(self, _app: FastAPI) -> AsyncIterator[None]:
        self.loop = asyncio.get_running_loop()
        operational_log(logger, logging.INFO, "server.started",
                        run_id=self.world.gateway.run_id, tick=self.store.tick)
        try:
            yield
        finally:
            operational_log(logger, logging.INFO, "server.stopped",
                            run_id=self.world.gateway.run_id, tick=self.store.tick,
                            run_active=self.is_running())
            self.loop = None

    def on_tick(self, tick: int, summary: dict) -> None:
        if self.loop is None or not self.loop.is_running():
            return
        asyncio.run_coroutine_threadsafe(
            self.hub.broadcast(build_tick_payload(self.world, tick, summary)), self.loop)

    async def _run_world(self, max_ticks: int | None) -> None:
        try:
            await self.world.run(max_ticks=max_ticks)
        except ReconciliationError as exc:
            operational_log(logger, logging.CRITICAL, "run.halted",
                            run_id=self.world.gateway.run_id, tick=self.store.tick,
                            error_type=type(exc).__name__, error=str(exc))
            await self.hub.broadcast({"type": "halt", "reason": str(exc)})
        except Exception as exc:
            self.world.status = "paused"
            self.store.set_meta(status="paused")
            self.store.log_event(
                self.store.tick, "run_exception", {"error": str(exc)[:500]}, importance=5.0)
            self.store.commit()
            operational_log(logger, logging.ERROR, "run.unhandled_exception",
                            run_id=self.world.gateway.run_id, tick=self.store.tick,
                            error_type=type(exc).__name__, error=str(exc))
            await self.hub.broadcast({"type": "pause", "reason": f"run paused: {exc}"})

    async def start(self, max_ticks: int | None = None) -> dict:
        if self.is_running():
            operational_log(logger, logging.INFO, "run.start.skipped",
                            run_id=self.world.gateway.run_id, tick=self.store.tick,
                            reason="already_running")
            return {"status": "already_running"}
        self.world._pause_requested = False
        self.world._stop_requested = False
        self.world.gateway.clear_interrupt()
        self.task = asyncio.create_task(self._run_world(max_ticks))
        operational_log(logger, logging.INFO, "run.start.accepted",
                        run_id=self.world.gateway.run_id, tick=self.store.tick,
                        max_ticks=max_ticks)
        return {"status": "running", "tick": self.store.tick}

    def pause(self) -> dict:
        self.world.request_pause()
        operational_log(logger, logging.INFO, "run.pause.accepted",
                        run_id=self.world.gateway.run_id, tick=self.store.tick)
        return {"status": "pausing", "tick": self.store.tick}

    async def stop(self) -> dict:
        self.world.request_stop()
        if self.is_running():
            operational_log(logger, logging.INFO, "run.stop.accepted",
                            run_id=self.world.gateway.run_id, tick=self.store.tick,
                            running=True)
            return {"status": "stopping", "tick": self.store.tick}
        self.world.status = "finished"
        self.store.set_meta(status="finished")
        self.store.commit()
        self.world.checkpoint(self.store.tick, reason="stop")
        if not self.world.last_report_path:
            from reports.generate import generate_report
            self.world.last_report_path = generate_report(
                self.store, self.world,
                out_dir=str(self.world.config.get("report_dir", "reports/out")))
        operational_log(logger, logging.INFO, "run.stop.completed",
                        run_id=self.world.gateway.run_id, tick=self.store.tick,
                        report_path=self.world.last_report_path)
        return {"status": "finished", "tick": self.store.tick,
                "report_path": self.world.last_report_path}

    async def step(self) -> dict:
        if self.is_running():
            operational_log(logger, logging.INFO, "run.step.skipped",
                            run_id=self.world.gateway.run_id, tick=self.store.tick,
                            reason="already_running")
            return {"status": "already_running"}
        summary = await self.world.step()
        if not summary.get("paused") and self.world.status != "halted":
            self.world.status = "paused"
            self.store.set_meta(status="paused")
            self.store.commit()
        await self.hub.broadcast(build_tick_payload(self.world, summary["tick"], summary))
        operational_log(logger, logging.INFO, "run.step.completed",
                        run_id=self.world.gateway.run_id, tick=summary["tick"],
                        paused=summary.get("paused"))
        return summary

    def set_speed(self, delay_s: float) -> dict:
        self.world.speed_delay_s = max(0.0, float(delay_s))
        operational_log(logger, logging.INFO, "run.speed.changed",
                        run_id=self.world.gateway.run_id, tick=self.store.tick,
                        delay_s=self.world.speed_delay_s)
        return {"delay_s": self.world.speed_delay_s}

    def status(self) -> dict:
        meta = self.store.get_meta()
        return {
            "run_id": meta["run_id"], "status": self.world.status,
            "tick": self.store.tick, "seed": meta["seed"],
            "active_tick": meta["active_tick"],
            "next_phase": meta["next_phase"],
            "legacy_partial": bool(meta["legacy_partial"]),
            "governor": self.world.gateway.governor.status(),
            "running": self.is_running(),
            "provider_readiness": self.world.gateway.readiness(),
            "rate_limit": self.world.gateway.rate_limit_status(),
            "pause_reason": self.world.last_pause_reason,
            "report_path": self.world.last_report_path,
        }


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

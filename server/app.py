"""FastAPI app: run controls, world queries, Oracle chat, shock console, WS stream.

The world loop runs as an asyncio task inside this process; each completed tick is
broadcast over WebSocket so the dashboard updates within 2s of tick completion
(PRD R8 acceptance).
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine.store import load_json
from server.controller import RunController, build_tick_payload
from world.loop import World
from world.shocks import SHOCK_KINDS, TRIGGER_TYPES
from observability import get_logger, log_event as operational_log


logger = get_logger("server")


class AskBody(BaseModel):
    question: str


class ShockBody(BaseModel):
    kind: str
    trigger_type: str = "shock"
    trigger: dict = {}
    duration_ticks: int = 0
    params: dict = {}
    label: str = ""


class SpeedBody(BaseModel):
    delay_s: float


def create_app(world: World) -> FastAPI:
    controller = RunController(world)
    hub = controller.hub
    store = world.store
    app = FastAPI(title="Agent Economy Observatory", lifespan=controller.lifespan)
    app.state.run_controller = controller

    @app.middleware("http")
    async def log_http_request(request: Request, call_next):
        started = time.perf_counter()
        operational_log(
            logger, logging.DEBUG, "http.request.started",
            method=request.method, path=request.url.path,
        )
        try:
            response = await call_next(request)
        except Exception as exc:
            operational_log(
                logger, logging.ERROR, "http.request.failed",
                method=request.method, path=request.url.path,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                error_type=type(exc).__name__, error=str(exc),
            )
            raise
        level = logging.WARNING if response.status_code >= 400 else logging.INFO
        operational_log(
            logger, level, "http.request.completed",
            method=request.method, path=request.url.path,
            status_code=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return response

    # ── run controls (PRD R7) ────────────────────────────────────────────────
    @app.post("/api/run/start")
    async def start_run(max_ticks: Optional[int] = None):
        return await controller.start(max_ticks)

    @app.post("/api/run/pause")
    async def pause_run():
        return controller.pause()

    @app.post("/api/run/stop")
    async def stop_run():
        return await controller.stop()

    @app.post("/api/run/step")
    async def step_once():
        return await controller.step()

    @app.post("/api/run/speed")
    async def set_speed(body: SpeedBody):
        return controller.set_speed(body.delay_s)

    @app.get("/api/run/status")
    async def run_status():
        return controller.status()

    # ── world queries (dashboard panels, PRD R8) ─────────────────────────────
    @app.get("/api/metrics")
    async def metrics(names: str = "gdp_proxy,cpi,unemployment,index,policy_rate,money_supply,gini,sentiment"):
        out = {}
        for name in names.split(","):
            name = name.strip()
            if name:
                out[name] = [{"tick": t, "value": v} for t, v in store.metric_series(name)]
        return out

    @app.get("/api/agents")
    async def agents():
        rows = store.query(
            "SELECT id, name, kind, role, occupation, age, health, alive, retired, employer_id "
            "FROM agents ORDER BY id")
        return [dict(r) for r in rows]

    @app.get("/api/agents/{agent_id}")
    async def agent_detail(agent_id: int):
        a = store.query_one("SELECT * FROM agents WHERE id=?", (agent_id,))
        if not a:
            return JSONResponse({"error": "not found"}, status_code=404)
        accounts = [dict(r) for r in store.query(
            "SELECT id, kind, bank_id, balance_cents FROM accounts "
            "WHERE owner_type='agent' AND owner_id=?", (agent_id,))]
        loans = [dict(r) for r in store.query(
            "SELECT * FROM loans WHERE borrower_type='agent' AND borrower_id=?", (agent_id,))]
        beliefs = {r["key"]: r["value"] for r in store.query(
            "SELECT key, value FROM beliefs WHERE agent_id=?", (agent_id,))}
        memories = [dict(r) for r in store.query(
            "SELECT tick, kind, text, importance FROM memories WHERE agent_id=? "
            "ORDER BY id DESC LIMIT 30", (agent_id,))]
        shares = [dict(r) for r in store.query(
            "SELECT firm_id, qty FROM shares WHERE holder_type='agent' AND holder_id=?", (agent_id,))]
        decisions = [
            {"tick": r["tick"], "purpose": r["purpose"], "model": r["model"],
             "request": load_json(r["request_json"], {}), "response": load_json(r["response_json"], {}),
             "cost_usd": r["cost_usd"]}
            for r in store.query(
                "SELECT * FROM llm_calls WHERE agent_id=? AND purpose IN "
                "('decision','citizen','founder','credit_officer','central_banker') "
                "ORDER BY id DESC LIMIT 10", (agent_id,))]
        persona = {k: load_json(a[k], None) for k in
                   ("personality_json", "media_diet_json", "cadence_json")}
        return {"agent": dict(a), "persona": persona, "accounts": accounts, "loans": loans,
                "beliefs": beliefs, "memories": memories, "shares": shares,
                "recent_decisions": decisions}

    @app.get("/api/banks")
    async def banks():
        out = []
        for b in store.query("SELECT * FROM banks"):
            bid = int(b["id"])
            trust = store.scalar("SELECT AVG(value) FROM beliefs WHERE key=?",
                                 (f"trust:bank:{bid}",), default=None)
            out.append({"id": bid, "name": b["name"], "status": b["status"],
                        "deposits_cents": world.economy.bank.deposits(bid),
                        "reserves_cents": world.economy.bank.reserves(bid),
                        "reserve_ratio": world.economy.bank.reserve_ratio(bid),
                        "loans_outstanding_cents": world.economy.bank.outstanding_loans(bid),
                        "avg_trust": round(float(trust), 4) if trust is not None else None})
        return out

    @app.get("/api/firms")
    async def firms():
        rows = store.query("SELECT * FROM firms ORDER BY id")
        out = []
        for f in rows:
            prod = load_json(f["product_json"], {}) or {}
            employees = int(store.scalar(
                "SELECT COUNT(*) FROM employments WHERE firm_id=? AND status='active'",
                (int(f["id"]),), default=0))
            out.append({"id": int(f["id"]), "name": f["name"], "sector": f["sector"],
                        "status": f["status"], "inventory": int(f["inventory"]),
                        "price_cents": prod.get("unit_price_cents"),
                        "product": prod.get("product"),
                        "employees": employees,
                        "last_stock_price": world.economy.exchange.last_price(int(f["id"])),
                        "cash_cents": world.economy.ledger.balance(int(f["account_id"]))
                        if f["account_id"] else None})
        return out

    @app.get("/api/news")
    async def news(limit: int = 30):
        rows = store.query("SELECT * FROM news_articles ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    @app.get("/api/conversations")
    async def conversations(limit: int = 20):
        convs = store.query("SELECT * FROM conversations ORDER BY id DESC LIMIT ?", (limit,))
        out = []
        for c in convs:
            msgs = store.query(
                "SELECT m.agent_id, a.name, m.text, m.seq FROM messages m "
                "LEFT JOIN agents a ON a.id=m.agent_id WHERE m.conv_id=? ORDER BY m.seq",
                (int(c["id"]),))
            out.append({"id": int(c["id"]), "tick": int(c["tick"]),
                        "participants": load_json(c["participant_ids"], []),
                        "messages": [dict(m) for m in msgs]})
        return out

    @app.get("/api/events")
    async def events(limit: int = 80, min_importance: float = 0.0):
        rows = store.recent_events(limit=limit, min_importance=min_importance)
        return [{"id": int(r["id"]), "tick": int(r["tick"]), "phase": r["phase"],
                 "kind": r["kind"], "importance": r["importance"],
                 "payload": load_json(r["payload_json"], {})} for r in rows]

    @app.get("/api/trades")
    async def trades(limit: int = 50):
        rows = store.query("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    @app.get("/api/cost")
    async def cost():
        by_model = [dict(r) for r in store.query(
            "SELECT model, COUNT(*) AS calls, SUM(in_tokens) AS in_tokens, "
            "SUM(out_tokens) AS out_tokens, SUM(cost_usd) AS cost_usd "
            "FROM llm_calls GROUP BY model")]
        by_purpose = [dict(r) for r in store.query(
            "SELECT purpose, COUNT(*) AS calls, SUM(cost_usd) AS cost_usd "
            "FROM llm_calls GROUP BY purpose")]
        by_agent = [dict(r) for r in store.query(
            "SELECT c.agent_id, COALESCE(a.name, 'Shared / system') AS agent_name, "
            "COALESCE(c.role, 'shared') AS role, COUNT(*) AS calls, "
            "SUM(c.in_tokens) AS in_tokens, SUM(c.out_tokens) AS out_tokens, "
            "SUM(c.cost_usd) AS cost_usd FROM llm_calls c "
            "LEFT JOIN agents a ON a.id=c.agent_id "
            "GROUP BY c.agent_id, a.name, c.role ORDER BY cost_usd DESC, calls DESC LIMIT 12")]
        return {"governor": world.gateway.governor.status(), "by_model": by_model,
                "by_purpose": by_purpose, "by_agent": by_agent}

    # ── Oracle (PRD R6) ──────────────────────────────────────────────────────
    @app.post("/api/oracle/ask")
    async def oracle_ask(body: AskBody):
        answer = await world.oracle.ask(body.question)
        await hub.broadcast({"type": "oracle", "question": body.question, "answer": answer})
        return answer

    @app.get("/api/oracle/predictions")
    async def oracle_predictions():
        rows = store.query("SELECT * FROM predictions ORDER BY id DESC")
        preds = []
        for r in rows:
            d = dict(r)
            d["resolution_rule"] = load_json(r["resolution_rule_json"], {})
            d["drivers"] = load_json(r["drivers_json"], [])
            d["evidence"] = load_json(r["evidence_json"], [])
            preds.append(d)
        return {"predictions": preds, "scorecard": world.oracle.scorecard()}

    # ── Oracle calibration (P1 R15): this run, or pooled across all runs ────
    @app.get("/api/oracle/calibration")
    async def oracle_calibration(scope: str = "run"):
        from oracle.calibration import aggregate_calibration, run_calibration
        if scope == "all":
            return aggregate_calibration()
        return run_calibration(store)

    # ── government / health / VC status strip (P1 R12/R13/R17) ─────────────
    @app.get("/api/institutions")
    async def institutions():
        e = world.economy
        gov = {"enabled": e.gov.enabled}
        if e.gov.enabled:
            last_election = store.query_one(
                "SELECT payload_json FROM events WHERE kind='election_held' ORDER BY id DESC")
            gov.update({"tax_rate_bps": e.gov.tax_rate_bps(),
                        "unemployment_benefit_cents": e.gov.benefit_cents(),
                        "treasury_cents": e.gov.treasury_balance(),
                        "last_election": load_json(last_election["payload_json"], None)
                        if last_election else None})
        vc_row = store.query_one("SELECT id FROM agents WHERE role='vc_partner' AND alive=1")
        vc = {"exists": vc_row is not None}
        if vc_row:
            acct = e.ledger.agent_checking_id(int(vc_row["id"]))
            vc.update({"fund_cents": e.ledger.balance(acct) if acct else 0,
                       "portfolio": e.vc.portfolio(int(vc_row["id"]))})
        hospital = store.query_one(
            "SELECT id, name, status FROM firms WHERE sector='health' ORDER BY id LIMIT 1")
        insurer = store.query_one(
            "SELECT id, name, status FROM firms WHERE sector='insurance' ORDER BY id LIMIT 1")
        health = {
            "hospital": dict(hospital) if hospital else None,
            "insurer": dict(insurer) if insurer else None,
            "insured_count": int(store.scalar(
                "SELECT COUNT(*) FROM insurance_policies WHERE status='active'", default=0)),
            "epidemic_multiplier": store.metric_latest("epidemic_multiplier", 1.0)}
        outlets = world.config.get("outlets", [])
        return {"government": gov, "vc": vc, "health": health, "outlets": outlets}

    # ── replay viewer (P1 R16): browse any stored run tick-by-tick ──────────
    from server.replay import ReplayReader
    reader = ReplayReader()

    @app.get("/api/replay/runs")
    async def replay_runs():
        return reader.list_runs()

    @app.get("/api/replay/{run_id}/summary")
    async def replay_summary(run_id: str):
        s = reader.summary(run_id)
        return s if s else JSONResponse({"error": "run not found"}, status_code=404)

    @app.get("/api/replay/{run_id}/metrics")
    async def replay_metrics(run_id: str, names: Optional[str] = None):
        m = reader.metrics(run_id, names)
        return m if m is not None else JSONResponse({"error": "run not found"}, status_code=404)

    @app.get("/api/replay/{run_id}/tick/{tick}")
    async def replay_tick(run_id: str, tick: int):
        v = reader.tick_view(run_id, tick)
        return v if v else JSONResponse({"error": "run not found"}, status_code=404)

    # ── shocks (PRD R9) ──────────────────────────────────────────────────────
    @app.get("/api/shocks")
    async def list_shocks():
        return {"library": {"kinds": SHOCK_KINDS, "trigger_types": TRIGGER_TYPES},
                "scheduled": [dict(r) for r in store.query("SELECT * FROM shocks ORDER BY id")]}

    @app.post("/api/shocks")
    async def fire_shock(body: ShockBody):
        if body.kind not in SHOCK_KINDS:
            operational_log(logger, logging.WARNING, "shock.rejected",
                            run_id=world.gateway.run_id, tick=store.tick,
                            kind=body.kind, reason="unknown_kind")
            return JSONResponse({"error": f"unknown kind {body.kind}"}, status_code=400)
        trigger = body.trigger or {"tick": store.tick + 1}
        sid = world.shocks.schedule(body.kind, body.trigger_type, trigger,
                                    duration_ticks=body.duration_ticks, params=body.params,
                                    label=body.label)
        operational_log(logger, logging.INFO, "shock.scheduled",
                        run_id=world.gateway.run_id, tick=store.tick,
                        shock_id=sid, kind=body.kind,
                        trigger_type=body.trigger_type)
        return {"shock_id": sid, "scheduled": True}

    # ── report (PRD R10) ─────────────────────────────────────────────────────
    @app.post("/api/report")
    async def generate_report():
        from reports.generate import generate_report as gen
        path = gen(store, world, out_dir=str(world.config.get("report_dir", "reports/out")))
        operational_log(logger, logging.INFO, "report.generated",
                        run_id=world.gateway.run_id, tick=store.tick, path=path)
        return {"path": path}

    # ── WebSocket ────────────────────────────────────────────────────────────
    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await hub.connect(ws)
        try:
            await ws.send_text(json.dumps(build_tick_payload(
                world, store.tick, {"tick": store.tick})))
            while True:
                await ws.receive_text()   # keepalive; controls go over REST
        except WebSocketDisconnect:
            hub.disconnect(ws)
        except Exception as exc:
            operational_log(logger, logging.WARNING, "websocket.failed",
                            run_id=world.gateway.run_id,
                            error_type=type(exc).__name__, error=str(exc))
            hub.disconnect(ws)

    # ── static dashboard + generated reports ────────────────────────────────
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        @app.get("/")
        async def index():
            return FileResponse(str(static_dir / "index.html"))
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    reports_dir = Path("reports/out")
    reports_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/reports", StaticFiles(directory=str(reports_dir)), name="reports")

    return app

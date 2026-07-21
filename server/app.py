"""FastAPI app: run controls, world queries, Oracle chat, shock console, WS stream.

The world loop runs as an asyncio task inside this process; each completed tick is
broadcast over WebSocket so the dashboard updates within 2s of tick completion
(PRD R8 acceptance).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine.store import load_json
from agents.participant import ParticipantError
from server.controller import RunController
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


class ParticipantControlBody(BaseModel):
    agent_id: int
    expected_tick: int


class ParticipantActionBody(BaseModel):
    expected_tick: int
    action: dict
    reasoning: str = ""


class ParticipantReleaseBody(BaseModel):
    expected_tick: int


def _hosted_safe_document(value):
    """Remove filesystem-bearing fields from a hosted JSON document."""
    if isinstance(value, dict):
        return {
            key: _hosted_safe_document(item)
            for key, item in value.items()
            if not (str(key) == "path" or str(key).endswith("_path")
                    or str(key).endswith("_paths"))
        }
    if isinstance(value, list):
        return [_hosted_safe_document(item) for item in value]
    return value


def _report_artifact_metadata(path: str, tick: int) -> dict:
    report = Path(path)
    digest = hashlib.sha256()
    size = 0
    with report.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return {
        "kind": "report",
        "tick": int(tick),
        "sha256": digest.hexdigest(),
        "size_bytes": size,
        "media_type": "text/html",
    }


def create_app(world: World, *, served_ticks: int | None = None,
               hosted_safe: bool = False) -> FastAPI:
    controller = RunController(
        world, served_ticks=served_ticks, hosted_safe=hosted_safe)
    hub = controller.hub
    store = world.store
    app = FastAPI(title="Agent Economy Observatory", lifespan=controller.lifespan)
    app.state.run_controller = controller
    from server.v2_api import install_v2_routes
    install_v2_routes(app, world, controller)
    acceptance_cache = {"result": None, "evaluated_at": 0.0}
    acceptance_lock = asyncio.Lock()

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
    async def start_run(max_ticks: Optional[int] = Query(default=None, ge=1)):
        return await controller.start(max_ticks)

    @app.post("/api/run/pause")
    async def pause_run():
        return controller.pause()

    @app.post("/api/run/stop")
    async def stop_run():
        result = await controller.stop()
        return _hosted_safe_document(result) if hosted_safe else result

    @app.post("/api/run/step")
    async def step_once():
        return await controller.step()

    @app.post("/api/run/speed")
    async def set_speed(body: SpeedBody):
        return controller.set_speed(body.delay_s)

    @app.get("/api/run/status")
    async def run_status():
        return controller.status()

    @app.get("/api/acceptance/status")
    async def acceptance_status():
        meta = store.get_meta()
        config = load_json(meta["config_json"], {})
        if not config.get("acceptance"):
            result = {"configured": False, "passed": False, "checks": []}
            return _hosted_safe_document(result) if hosted_safe else result
        # A completed receipt includes run-specific experiment/phenomena
        # attachments that cannot be reconstructed from the DB alone. Prefer it
        # only when it is bound to this run and current completed tick.
        receipt_path = Path(str(config.get("report_dir", "reports/out"))) / (
            f"acceptance_{meta['run_id']}.json")
        if receipt_path.exists():
            try:
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                receipt = None
            if (isinstance(receipt, dict)
                    and receipt.get("run", {}).get("run_id") == str(meta["run_id"])
                    and int(receipt.get("progress", {}).get("completed_ticks", -1))
                    == int(meta["tick"])):
                result = {
                    "configured": True, **receipt,
                    "orchestration": controller.status()["acceptance_orchestration"],
                }
                return _hosted_safe_document(result) if hosted_safe else result
        # A production database can be hundreds of MB. The evidence evaluator
        # reconciles the ledger and builds causal shock traces, so keep it off
        # the asyncio event loop and coalesce dashboard refreshes for two seconds.
        now = time.monotonic()
        cached = acceptance_cache["result"]
        if cached is not None and now - acceptance_cache["evaluated_at"] < 2.0:
            return _hosted_safe_document(cached) if hosted_safe else cached
        async with acceptance_lock:
            now = time.monotonic()
            cached = acceptance_cache["result"]
            if cached is not None and now - acceptance_cache["evaluated_at"] < 2.0:
                return _hosted_safe_document(cached) if hosted_safe else cached
            from reports.acceptance import evaluate_acceptance
            result = {
                "configured": True,
                **await asyncio.to_thread(evaluate_acceptance, store.path),
            }
            result["orchestration"] = controller.status()["acceptance_orchestration"]
            acceptance_cache.update(result=result, evaluated_at=time.monotonic())
            return _hosted_safe_document(result) if hosted_safe else result

    # ── participant mode (P2 R18, sandbox only) ─────────────────────────────
    def participant_error(exc: ParticipantError):
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)

    @app.get("/api/participant")
    async def participant_status():
        return controller.participant.status(running=controller.is_running())

    @app.get("/api/participant/history")
    async def participant_history(
        agent_id: int,
        limit: int = Query(default=50, ge=1, le=100),
        before_id: Optional[int] = Query(default=None, ge=1),
    ):
        try:
            return controller.participant.history(
                agent_id, limit=limit, before_id=before_id)
        except ParticipantError as exc:
            participant_error(exc)

    @app.post("/api/participant/control")
    async def participant_control(body: ParticipantControlBody):
        try:
            return controller.participant.acquire(
                body.agent_id, body.expected_tick, running=controller.is_running())
        except ParticipantError as exc:
            participant_error(exc)

    @app.post("/api/participant/action")
    async def participant_action(body: ParticipantActionBody):
        try:
            return controller.participant.queue_action(
                body.expected_tick, body.action, body.reasoning,
                running=controller.is_running())
        except ParticipantError as exc:
            participant_error(exc)

    @app.post("/api/participant/release")
    async def participant_release(body: ParticipantReleaseBody):
        try:
            return controller.participant.release(
                body.expected_tick, running=controller.is_running())
        except ParticipantError as exc:
            participant_error(exc)

    # ── world queries (dashboard panels, PRD R8) ─────────────────────────────
    @app.get("/api/metrics")
    async def metrics(names: str = Query(
        default="gdp_proxy,gdp_proxy_30d,labor_income,cpi,inflation_30d,cpi_yoy,unemployment,index,policy_rate,money_supply,gini,sentiment",
        max_length=1000,
    )):
        out = {}
        for name in names.split(",")[:50]:
            name = name.strip()
            if name:
                out[name] = [{"tick": t, "value": v} for t, v in store.metric_series(name)]
        return out

    @app.get("/api/agents")
    async def agents(
        limit: Optional[int] = Query(default=None, ge=1, le=200),
        after_id: Optional[int] = Query(default=None, ge=0),
        q: str = Query(default="", max_length=120),
        population_tier: Optional[Literal["core", "periphery"]] = None,
        region_id: Optional[int] = Query(default=None, ge=1),
    ):
        columns = (
            "a.id, a.name, a.kind, a.role, a.occupation, a.age, a.health, "
            "a.alive, a.retired, a.employer_id, a.population_tier, "
            "a.region_id, r.region_key"
        )
        base = " FROM agents a LEFT JOIN regions r ON r.id=a.region_id"
        filters: list[str] = []
        filter_params: list[object] = []
        needle = q.strip()
        if population_tier:
            filters.append("a.population_tier=?")
            filter_params.append(population_tier)
        if region_id is not None:
            filters.append("a.region_id=?")
            filter_params.append(region_id)
        if needle:
            escaped = (needle.replace("\\", "\\\\")
                       .replace("%", "\\%")
                       .replace("_", "\\_"))
            pattern = f"%{escaped}%"
            searchable = (
                "a.name", "a.occupation", "a.role", "a.kind", "a.health",
                "a.population_tier", "r.region_key",
            )
            filters.append("(" + " OR ".join(
                f"COALESCE({field}, '') LIKE ? ESCAPE '\\'"
                for field in searchable) + ")")
            filter_params.extend([pattern] * len(searchable))
        filter_sql = " WHERE " + " AND ".join(filters) if filters else ""

        paged = bool(limit is not None or after_id is not None or needle
                     or population_tier or region_id is not None)
        if not paged:
            rows = store.query("SELECT " + columns + base + " ORDER BY a.id")
            return [dict(row) for row in rows]

        page_limit = int(limit or 100)
        page_filters = list(filters)
        page_params = list(filter_params)
        if after_id is not None:
            page_filters.append("a.id>?")
            page_params.append(after_id)
        page_where = " WHERE " + " AND ".join(page_filters) if page_filters else ""
        rows = store.query(
            "SELECT " + columns + base + page_where + " ORDER BY a.id LIMIT ?",
            (*page_params, page_limit + 1),
        )
        items = [dict(row) for row in rows[:page_limit]]
        matched_total = int(store.scalar(
            "SELECT COUNT(*)" + base + filter_sql,
            filter_params,
            default=0,
        ))
        population_total = int(store.scalar(
            "SELECT COUNT(*) FROM agents", default=0))
        return {
            "items": items,
            "total": matched_total,
            "population_total": population_total,
            "limit": page_limit,
            "next_after_id": items[-1]["id"] if len(rows) > page_limit else None,
        }

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
        belief_history = [
            {"event_id": int(r["id"]), "tick": int(r["tick"]), "kind": r["kind"],
             **load_json(r["payload_json"], {})}
            for r in store.query(
                "SELECT id, tick, kind, payload_json FROM events "
                "WHERE subject_type='agent' AND subject_id=? AND kind IN "
                "('belief_updated','belief_update_normalized','belief_update_rejected') "
                "ORDER BY id DESC LIMIT 100", (agent_id,))]
        memories = [dict(r) for r in store.query(
            "SELECT tick, kind, text, importance FROM memories WHERE agent_id=? "
            "ORDER BY id DESC LIMIT 30", (agent_id,))]
        shares = [dict(r) for r in store.query(
            "SELECT firm_id, qty FROM shares WHERE holder_type='agent' AND holder_id=?", (agent_id,))]
        decisions = []
        for r in store.query(
                "SELECT * FROM llm_calls WHERE agent_id=? AND purpose IN "
                "('decision','citizen','founder','credit_officer','central_banker') "
                "ORDER BY id DESC LIMIT 10", (agent_id,)):
            decision = {
                "tick": r["tick"], "purpose": r["purpose"], "model": r["model"],
                "cost_usd": r["cost_usd"],
            }
            if not hosted_safe:
                decision.update({
                    "request": load_json(r["request_json"], {}),
                    "response": load_json(r["response_json"], {}),
                })
            decisions.append(decision)
        persona = {k: load_json(a[k], None) for k in
                   ("personality_json", "media_diet_json", "cadence_json")}
        calibration_event = store.query_one(
            "SELECT id,tick,payload_json FROM events "
            "WHERE kind='r21_household_sampled' AND subject_type='agent' "
            "AND subject_id=? ORDER BY id DESC LIMIT 1", (agent_id,))
        calibration_profile = None
        if calibration_event:
            payload = load_json(calibration_event["payload_json"], {})
            if not isinstance(payload, dict):
                payload = {}
            calibration_profile = dict(payload)
            if ("non_liquid_net_worth_cents" not in calibration_profile
                    and "net_worth_cents" in calibration_profile
                    and "liquid_wealth_cents" in calibration_profile):
                calibration_profile["non_liquid_net_worth_cents"] = (
                    int(calibration_profile["net_worth_cents"])
                    - int(calibration_profile["liquid_wealth_cents"]))
            calibration_profile["event_id"] = int(calibration_event["id"])
            calibration_profile["tick"] = int(calibration_event["tick"])
        return {"agent": dict(a), "persona": persona, "accounts": accounts, "loans": loans,
                "beliefs": beliefs, "belief_history": belief_history,
                "memories": memories, "shares": shares,
                "recent_decisions": decisions,
                "calibration_profile": calibration_profile}

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
    async def news(limit: int = Query(default=30, ge=1, le=200)):
        rows = store.query("SELECT * FROM news_articles ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    @app.get("/api/conversations")
    async def conversations(
        limit: int = Query(default=20, ge=1, le=200),
        q: Optional[str] = Query(default=None, max_length=200),
        agent_id: Optional[int] = Query(default=None, ge=1),
        tick_from: Optional[int] = Query(default=None, ge=0),
        tick_to: Optional[int] = Query(default=None, ge=0),
        before_id: Optional[int] = Query(default=None, ge=1),
    ):
        if tick_from is not None and tick_to is not None and tick_from > tick_to:
            raise HTTPException(status_code=422, detail="tick_from must be <= tick_to")

        clauses = []
        params: list[object] = []
        search = (q or "").strip()
        if search:
            # Treat wildcard characters literally: this is a substring search,
            # not a way to turn an empty query into an unbounded table scan.
            escaped = (search.replace("\\", "\\\\")
                       .replace("%", "\\%")
                       .replace("_", "\\_"))
            pattern = f"%{escaped}%"
            clauses.append(
                "(COALESCE(c.topic,'') COLLATE NOCASE LIKE ? ESCAPE '\\' OR EXISTS ("
                "SELECT 1 FROM messages sm LEFT JOIN agents sa ON sa.id=sm.agent_id "
                "WHERE sm.conv_id=c.id AND (sm.text COLLATE NOCASE LIKE ? ESCAPE '\\' "
                "OR COALESCE(sa.name,'') COLLATE NOCASE LIKE ? ESCAPE '\\')))"
            )
            params.extend((pattern, pattern, pattern))
        if agent_id is not None:
            clauses.append(
                "(EXISTS (SELECT 1 FROM json_each(c.participant_ids) "
                "WHERE CAST(json_each.value AS INTEGER)=?) OR EXISTS ("
                "SELECT 1 FROM messages am WHERE am.conv_id=c.id AND am.agent_id=?))")
            params.extend((agent_id, agent_id))
        if tick_from is not None:
            clauses.append("c.tick>=?")
            params.append(tick_from)
        if tick_to is not None:
            clauses.append("c.tick<=?")
            params.append(tick_to)
        if before_id is not None:
            clauses.append("c.id<?")
            params.append(before_id)

        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        convs = store.query(
            f"SELECT c.* FROM conversations c{where} ORDER BY c.id DESC LIMIT ?",
            (*params, limit))
        out = []
        for c in convs:
            msgs = store.query(
                "SELECT m.agent_id, a.name, m.text, m.seq FROM messages m "
                "LEFT JOIN agents a ON a.id=m.agent_id WHERE m.conv_id=? ORDER BY m.seq",
                (int(c["id"]),))
            out.append({"id": int(c["id"]), "tick": int(c["tick"]),
                        "participants": load_json(c["participant_ids"], []),
                        "topic": c["topic"],
                        "messages": [dict(m) for m in msgs]})
        return out

    @app.get("/api/events")
    async def events(
        limit: int = Query(default=80, ge=1, le=500),
        min_importance: float = Query(default=0.0, ge=0.0, le=1.0),
    ):
        rows = store.recent_events(limit=limit, min_importance=min_importance)
        return [{"id": int(r["id"]), "tick": int(r["tick"]), "phase": r["phase"],
                 "kind": r["kind"], "importance": r["importance"],
                 "payload": load_json(r["payload_json"], {})} for r in rows]

    @app.get("/api/trades")
    async def trades(limit: int = Query(default=50, ge=1, le=500)):
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
            if hosted_safe:
                raise HTTPException(
                    status_code=403,
                    detail="pooled cross-run calibration is disabled in hosted run apps")
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
    if not hosted_safe:
        from server.replay import ReplayReader
        reader = ReplayReader()
        app.state.replay_reader = reader

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
        controller._require_mutable("shock scheduling")
        if body.kind not in SHOCK_KINDS:
            operational_log(logger, logging.WARNING, "shock.rejected",
                            run_id=world.gateway.run_id, tick=store.tick,
                            kind=body.kind, reason="unknown_kind")
            return JSONResponse({"error": f"unknown kind {body.kind}"}, status_code=400)
        if body.trigger_type not in TRIGGER_TYPES:
            operational_log(logger, logging.WARNING, "shock.rejected",
                            run_id=world.gateway.run_id, tick=store.tick,
                            kind=body.kind, trigger_type=body.trigger_type,
                            reason="unknown_trigger_type")
            return JSONResponse(
                {"error": f"unknown trigger type {body.trigger_type}"}, status_code=400)
        if body.duration_ticks < 0:
            operational_log(logger, logging.WARNING, "shock.rejected",
                            run_id=world.gateway.run_id, tick=store.tick,
                            kind=body.kind, duration_ticks=body.duration_ticks,
                            reason="negative_duration")
            return JSONResponse(
                {"error": "duration_ticks must be non-negative"}, status_code=400)
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
        path = await controller.generate_report()
        operational_log(logger, logging.INFO, "report.generated",
                        run_id=world.gateway.run_id, tick=store.tick, path=path)
        if hosted_safe:
            return {"artifact": _report_artifact_metadata(path, store.tick)}
        return {"path": path}

    # ── WebSocket ────────────────────────────────────────────────────────────
    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await hub.connect(ws)
        try:
            await ws.send_text(json.dumps(controller.tick_payload(
                store.tick, {"tick": store.tick})))
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
    if not hosted_safe:
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

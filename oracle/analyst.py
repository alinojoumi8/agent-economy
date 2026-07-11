"""Oracle analyst + resolver + scoring (PRD R6).

- `ask()` assembles a read-only world digest, calls the gateway (role='oracle',
  which routes to a strong model — or the scripted analyst offline), validates the
  answer contract, and logs the prediction with its resolution rule + deadline.
- `resolve_open()` runs each tick: any prediction whose rule is machine-checkable
  against world state resolves automatically; Brier = (p − outcome)² accumulates.
- If no checkable rule can be derived, the Oracle answers `insufficient_data`
  rather than fabricating a number.
"""
from __future__ import annotations

import json
from typing import Optional

from engine.core import Economy
from engine.store import load_json
from llm.gateway import Gateway, LLMRequest
from .tools import OracleToolError, OracleTools

PLANNER_SYSTEM = """You are the read-only query planner for an economic analyst.
Choose only from the supplied tool definitions. Return JSON:
{"queries":[{"tool":"tool_name","args":{...}}]}.
Use at most 8 queries, request only evidence relevant to the question, and never
request SQL, writes, mutations, shell access, secrets, or unlisted tools.
Every from_tick/to_tick must stay inside the supplied inclusive tick_range."""

ANSWER_SYSTEM = """You are the Oracle: a rigorous, read-only economic analyst embedded in a simulated
economy. You are given a digest of true world state. Answer the operator's question as JSON:
{"p": 0.xx, "drivers": ["..."], "confidence": "low|med|high",
 "resolution_rule": {"type": "...", ...}, "deadline_tick": N, "reasoning": "..."}
Valid resolution_rule types (machine-checkable):
  {"type":"bank_run","window":5,"deposit_drop":0.30}            — any bank loses >30% deposits within any 5-tick window before deadline
  {"type":"bank_failure"}                                        — any bank fails before deadline
  {"type":"index_drop","window":N,"drop":0.20}                   — index falls >=20% within any N-tick window before deadline
  {"type":"unemployment_above","threshold":0.08}                 — unemployment exceeds threshold at any tick before deadline
  {"type":"cpi_above","threshold":110}                           — CPI exceeds threshold before deadline
  {"type":"firm_bankruptcy","firm_id":K}                         — that firm (or any, if omitted) goes bankrupt before deadline
  {"type":"metric_above","metric":"name","threshold":X}          — named metric exceeds threshold before deadline
  {"type":"metric_below","metric":"name","threshold":X}
If the question cannot be given a checkable rule from world state, reply
{"insufficient_data": true, "reason": "..."} instead. Never fabricate."""


class Oracle:
    def __init__(self, economy: Economy, gateway: Gateway, config: dict):
        self.e = economy
        self.store = economy.store
        self.gw = gateway
        self.config = config
        self.tools = OracleTools(economy)
        self.default_horizon = int(config.get("oracle", {}).get("default_horizon_ticks", 30))

    # ── ask ──────────────────────────────────────────────────────────────────
    async def ask(self, question: str) -> dict:
        tick = self.store.tick
        digest = self._world_digest(tick)
        legacy_replay = self._legacy_replay_at(tick)
        evidence = []
        if not legacy_replay:
            base_planning_context = {
                "question": question, "tick": tick,
                "available_tools": self.tools.definitions,
                "constraints": {
                    "tick_range": {"minimum": 0, "maximum": tick},
                    "maximum_queries": self.tools.MAX_QUERIES,
                    "read_only": True,
                },
            }
            validation_error = None
            attempts = self._planner_attempt_limit(tick, question)
            for _attempt in range(attempts):
                planning_context = dict(base_planning_context)
                if validation_error:
                    planning_context["previous_plan_error"] = validation_error
                    planning_context["instruction"] = (
                        "Return a corrected plan that satisfies every supplied constraint.")
                plan_req = LLMRequest(
                    role="oracle", purpose="oracle_plan", system=PLANNER_SYSTEM,
                    user=json.dumps(planning_context)[:5000], context=planning_context,
                    tick=tick, max_tokens=350, temperature=0.1)
                plan_resp = await self.gw.complete(
                    plan_req, schema_hint='{"queries":[]}')
                plan = plan_resp.parsed if isinstance(plan_resp.parsed, dict) else {}
                queries = plan.get("queries", [])
                try:
                    if not queries:
                        raise OracleToolError("at least one evidence query is required")
                    evidence = self.tools.execute_plan(queries)
                    break
                except OracleToolError as exc:
                    validation_error = str(exc)
                    evidence = [{"error": validation_error, "queries_rejected": True}]
                    self.store.log_event(
                        tick, "oracle_tool_plan_rejected",
                        {"question": question, "error": validation_error[:500]},
                        importance=1.5)
        context = {**digest, "question": question, "tick": tick,
                   "default_horizon": self.default_horizon}
        if not legacy_replay:
            context["evidence"] = evidence
        user_payload = (
            json.dumps({"question": question, "world": digest})[:6000]
            if legacy_replay else
            json.dumps({
                "question": question, "world": digest,
                "read_only_evidence": evidence})[:12000])
        req = LLMRequest(role="oracle", purpose="oracle", system=ANSWER_SYSTEM,
                         user=user_payload,
                         context=context, tick=tick, max_tokens=500, temperature=0.3)
        resp = await self.gw.complete(req)
        ans = resp.parsed if isinstance(resp.parsed, dict) else {}

        if ans.get("insufficient_data"):
            pid = self.store.insert(
                "predictions", asked_tick=tick, question=question, p=None,
                reasoning=ans.get("reason", "insufficient data"),
                evidence_json=json.dumps(evidence), status="insufficient_data")
            self.store.log_event(tick, "oracle_insufficient", {
                "prediction_id": pid, "question": question}, phase=None, importance=1.0)
            return {"insufficient_data": True, "reason": ans.get("reason", ""),
                    "prediction_id": pid, "evidence": evidence}

        # Validate the contract; refuse rather than store garbage.
        try:
            p = float(ans["p"])
            assert 0.0 <= p <= 1.0
            rule = ans.get("resolution_rule") or {}
            assert isinstance(rule, dict) and rule.get("type")
            deadline = int(ans.get("deadline_tick") or (tick + self.default_horizon))
            assert deadline > tick
        except (KeyError, AssertionError, TypeError, ValueError):
            pid = self.store.insert(
                "predictions", asked_tick=tick, question=question, p=None,
                reasoning="answer did not meet the contract",
                evidence_json=json.dumps(evidence), status="insufficient_data")
            return {"insufficient_data": True,
                    "reason": "The analyst could not produce a checkable prediction.",
                    "prediction_id": pid, "evidence": evidence}

        pid = self.store.insert(
            "predictions", asked_tick=tick, question=question, p=p,
            reasoning=str(ans.get("reasoning", ""))[:2000],
            drivers_json=json.dumps(ans.get("drivers", [])),
            confidence=str(ans.get("confidence", "med")),
            resolution_rule_json=json.dumps(rule), deadline_tick=deadline,
            evidence_json=json.dumps(evidence), status="open")
        self.store.log_event(tick, "oracle_prediction", {
            "prediction_id": pid, "question": question, "p": p, "deadline_tick": deadline,
            "rule": rule}, importance=2.0)
        return {"prediction_id": pid, "p": p, "drivers": ans.get("drivers", []),
                "confidence": ans.get("confidence", "med"), "resolution_rule": rule,
                "deadline_tick": deadline, "reasoning": ans.get("reasoning", ""),
                "evidence": evidence}

    def _planner_attempt_limit(self, tick: int, question: str) -> int:
        if not self.gw.replay or self.gw.replay_conn is None:
            # One initial plan plus two bounded corrections. Live acceptance
            # showed that a first repair can fix schema shape while still
            # guessing an entity that does not exist.
            return 3
        matching = 0
        rows = self.gw.replay_conn.execute(
            "SELECT request_json FROM llm_calls "
            "WHERE tick=? AND purpose='oracle_plan' ORDER BY id", (tick,)).fetchall()
        for row in rows:
            request = load_json(row["request_json"], {}) or {}
            context = request.get("context", {}) if isinstance(request, dict) else {}
            recorded = context.get("question") if isinstance(context, dict) else None
            if recorded == question:
                matching += 1
        return max(1, matching)

    def _legacy_replay_at(self, tick: int) -> bool:
        if not self.gw.replay or self.gw.replay_conn is None:
            return False
        row = self.gw.replay_conn.execute(
            "SELECT 1 FROM llm_calls WHERE tick=? AND purpose='oracle_plan' LIMIT 1",
            (tick,)).fetchone()
        return row is None

    # ── world digest (read-only tools rolled into one) ───────────────────────
    def _world_digest(self, tick: int) -> dict:
        m = {n: self.store.metric_latest(n, 0.0) for n in
             ("gdp_proxy", "cpi", "cpi_yoy", "unemployment", "index", "index_change_10",
              "money_supply", "gini", "sentiment", "policy_rate")}
        banks = []
        min_ratio, min_trust = 1.0, 1.0
        for b in self.store.query("SELECT * FROM banks"):
            bid = int(b["id"])
            ratio = self.e.bank.reserve_ratio(bid)
            trust = float(self.store.scalar(
                "SELECT AVG(value) FROM beliefs WHERE key=?", (f"trust:bank:{bid}",), default=0.6) or 0.6)
            banks.append({"id": bid, "name": b["name"], "status": b["status"],
                          "deposits_cents": self.e.bank.deposits(bid),
                          "reserve_ratio": round(ratio, 4), "avg_trust": round(trust, 4)})
            if b["status"] == "open":
                min_ratio = min(min_ratio, ratio)
                min_trust = min(min_trust, trust)
        recent_news = [dict(headline=r["headline"], outlet=r["outlet_name"], tone=float(r["tone"]))
                       for r in self.store.query(
                           "SELECT * FROM news_articles ORDER BY id DESC LIMIT 6")]
        recent_events = [dict(kind=r["kind"], tick=int(r["tick"]),
                              payload=load_json(r["payload_json"], {}))
                         for r in self.store.query(
                             "SELECT * FROM events WHERE importance>=2.5 ORDER BY id DESC LIMIT 10")]
        convo_sample = [r["text"] for r in self.store.query(
            "SELECT text FROM messages ORDER BY id DESC LIMIT 8")]
        return {"metrics": m, "banks": banks, "recent_news": recent_news,
                "recent_events": recent_events, "conversation_sample": convo_sample,
                "min_reserve_ratio": round(min_ratio, 4), "min_bank_trust": round(min_trust, 4)}

    # ── resolver (each tick) ─────────────────────────────────────────────────
    def resolve_open(self, tick: int) -> list[dict]:
        resolved = []
        for pred in self.store.query("SELECT * FROM predictions WHERE status='open'"):
            rule = load_json(pred["resolution_rule_json"], {}) or {}
            deadline = int(pred["deadline_tick"] or 0)
            outcome = self._check_rule(rule, int(pred["asked_tick"]), min(tick, deadline))
            final = None
            if outcome is True:
                final = 1
            elif tick >= deadline:
                final = 1 if outcome else 0
            if final is not None:
                p = float(pred["p"])
                brier = (p - final) ** 2
                self.store.update("predictions", int(pred["id"]), resolved_tick=tick,
                                  outcome=final, brier=brier, status="resolved")
                self.store.log_event(tick, "prediction_resolved", {
                    "prediction_id": int(pred["id"]), "question": pred["question"],
                    "p": p, "outcome": final, "brier": round(brier, 4)}, importance=2.0)
                resolved.append({"id": int(pred["id"]), "outcome": final, "brier": brier})
        return resolved

    def _check_rule(self, rule: dict, asked_tick: int, upto_tick: int) -> Optional[bool]:
        rtype = rule.get("type")
        if rtype == "bank_failure":
            return self.store.query_one(
                "SELECT 1 FROM events WHERE kind='bank_failure' AND tick>? AND tick<=?",
                (asked_tick, upto_tick)) is not None
        if rtype == "firm_bankruptcy":
            firm_id = rule.get("firm_id")
            if firm_id:
                return self.store.query_one(
                    "SELECT 1 FROM events WHERE kind='bankruptcy' AND tick>? AND tick<=? "
                    "AND json_extract(payload_json,'$.firm_id')=?",
                    (asked_tick, upto_tick, int(firm_id))) is not None
            return self.store.query_one(
                "SELECT 1 FROM events WHERE kind='bankruptcy' AND tick>? AND tick<=?",
                (asked_tick, upto_tick)) is not None
        if rtype == "bank_run":
            window = int(rule.get("window", 5))
            drop = float(rule.get("deposit_drop", 0.30))
            return self._bank_run_happened(asked_tick, upto_tick, window, drop)
        if rtype == "index_drop":
            window = int(rule.get("window", 30))
            drop = float(rule.get("drop", 0.20))
            series = [v for t, v in self.store.metric_series("index") if asked_tick <= t <= upto_tick]
            for i in range(len(series)):
                for j in range(i + 1, min(i + window + 1, len(series))):
                    if series[i] > 0 and (series[j] / series[i] - 1.0) <= -drop:
                        return True
            return False
        if rtype == "unemployment_above":
            return self._metric_crossed("unemployment", float(rule.get("threshold", 0.08)),
                                        asked_tick, upto_tick, above=True)
        if rtype == "cpi_above":
            return self._metric_crossed("cpi", float(rule.get("threshold", 110)),
                                        asked_tick, upto_tick, above=True)
        if rtype == "metric_above":
            return self._metric_crossed(str(rule.get("metric", "")), float(rule.get("threshold", 0)),
                                        asked_tick, upto_tick, above=True)
        if rtype == "metric_below":
            return self._metric_crossed(str(rule.get("metric", "")), float(rule.get("threshold", 0)),
                                        asked_tick, upto_tick, above=False)
        return None

    def _metric_crossed(self, name: str, threshold: float, t0: int, t1: int, above: bool) -> bool:
        rows = self.store.query(
            "SELECT 1 FROM metrics WHERE name=? AND tick>? AND tick<=? AND value" +
            (">" if above else "<") + "? LIMIT 1", (name, t0, t1, threshold))
        return bool(rows)

    def _bank_run_happened(self, t0: int, t1: int, window: int, drop: float) -> bool:
        for b in self.store.query("SELECT id FROM banks"):
            series = [(t, v) for t, v in self.store.metric_series(f"bank_deposits:{int(b['id'])}")
                      if t0 <= t <= t1]
            for i in range(len(series)):
                for j in range(i + 1, len(series)):
                    if series[j][0] - series[i][0] > window:
                        break
                    if series[i][1] > 0 and (series[j][1] / series[i][1] - 1.0) <= -drop:
                        return True
        return False

    # ── scorecard ────────────────────────────────────────────────────────────
    def scorecard(self) -> dict:
        rows = self.store.query("SELECT * FROM predictions ORDER BY id")
        resolved = [r for r in rows if r["status"] == "resolved"]
        briers = [float(r["brier"]) for r in resolved if r["brier"] is not None]
        naive = [(0.5 - int(r["outcome"])) ** 2 for r in resolved]
        return {
            "total": len(rows),
            "open": sum(1 for r in rows if r["status"] == "open"),
            "resolved": len(resolved),
            "insufficient": sum(1 for r in rows if r["status"] == "insufficient_data"),
            "mean_brier": round(sum(briers) / len(briers), 4) if briers else None,
            "naive_brier": round(sum(naive) / len(naive), 4) if naive else None,
            "beats_naive": (sum(briers) < sum(naive)) if briers else None,
        }

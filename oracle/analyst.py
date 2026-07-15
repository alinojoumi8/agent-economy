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

import hashlib
import json
import math
from typing import Optional

from engine.core import Economy
from engine.store import load_json
from llm.gateway import Gateway, LLMRequest
from .rules import ResolutionRuleError, validate_resolution_rule
from .tools import (
    MAX_PROMPT_EVIDENCE_CHARS,
    OracleToolError,
    OracleTools,
    bound_oracle_evidence,
    canonical_oracle_json,
)

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
{"insufficient_data": true, "reason": "..."} instead. Never fabricate.
When governed_forecast_contract is supplied, use its resolution_rule and
deadline_tick exactly; it defines the scheduled question being measured."""

MAX_ANSWER_USER_CHARS = 12_000
MAX_PROMPT_WORLD_CHARS = 2_500


def _canonical_json(value) -> str:
    return canonical_oracle_json(value)


def _json_sha256(value) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _bounded_json_value(value, limit: int):
    serialized = _canonical_json(value)
    if len(serialized) <= limit:
        return value
    prefix_limit = max(0, limit - 160)
    return {
        "truncated": True,
        "sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        "json_prefix": serialized[:prefix_limit],
    }


def _bound_prompt_evidence(evidence: list[dict]) -> list[dict]:
    """Compatibility wrapper around the canonical tool transcript contract."""
    return bound_oracle_evidence(evidence)


def _answer_user_json(*, question: str, tick: int, world: dict,
                      evidence: list[dict], governed_contract: dict | None) -> tuple[str, dict]:
    """Build valid bounded JSON with engine-owned forecast facts first."""
    prompt_world = _bounded_json_value(world, MAX_PROMPT_WORLD_CHARS)
    payload = {}
    if governed_contract is not None:
        payload["governed_forecast_contract"] = governed_contract
    payload["question"] = question
    payload["tick"] = tick
    payload["read_only_evidence"] = evidence
    payload["world"] = prompt_world
    encoded = canonical_oracle_json(payload)
    if len(encoded) > MAX_ANSWER_USER_CHARS:
        raise ValueError("Oracle answer prompt exceeds its structural bound")
    return encoded, prompt_world


class Oracle:
    def __init__(self, economy: Economy, gateway: Gateway, config: dict):
        self.e = economy
        self.store = economy.store
        self.gw = gateway
        self.config = config
        self.tools = OracleTools(economy)
        self.default_horizon = int(config.get("oracle", {}).get("default_horizon_ticks", 30))
        self.engine_semantics_version = int(
            config.get("engine_semantics_version", 2))
        self.strict_resolution_rules = bool(
            config.get("oracle", {}).get("strict_resolution_rules", False))

    def _metric_exists(self, name: str) -> bool:
        return self.store.query_one(
            "SELECT 1 FROM metrics WHERE name=? LIMIT 1", (name,)) is not None

    # ── ask ──────────────────────────────────────────────────────────────────
    async def ask(
        self, question: str, *, governed_contract: dict | None = None,
    ) -> dict:
        tick = self.store.tick
        governed_contract = self._normalize_governed_contract(
            governed_contract, tick=tick)
        digest = self._world_digest(tick)
        legacy_replay = self._legacy_replay_at(tick)
        hardened_evidence = self._hardened_evidence_at(tick, question)
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
            if governed_contract is not None:
                base_planning_context["governed_forecast_contract"] = governed_contract
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
                    user=(canonical_oracle_json(planning_context)
                          if hardened_evidence else
                          json.dumps(planning_context)[:5000]),
                    context=planning_context,
                    tick=tick, max_tokens=350, temperature=0.1)
                plan_resp = await self.gw.complete(
                    plan_req, schema_hint='{"queries":[]}')
                plan = plan_resp.parsed if isinstance(plan_resp.parsed, dict) else {}
                queries = plan.get("queries", [])
                try:
                    if not queries:
                        raise OracleToolError("at least one evidence query is required")
                    evidence = (
                        self.tools.execute_plan(queries)
                        if hardened_evidence else
                        self.tools.execute_plan_legacy(queries))
                    break
                except OracleToolError as exc:
                    validation_error = str(exc)
                    evidence = [{"error": validation_error, "queries_rejected": True}]
                    rejection = {
                        "question": question, "error": validation_error[:500],
                    }
                    if hardened_evidence:
                        rejection.update({
                            "attempt": _attempt + 1,
                            "plan_sha256": _json_sha256(plan),
                        })
                    self.store.log_event(
                        tick, "oracle_tool_plan_rejected", rejection,
                        importance=1.5)
        context = {**digest, "question": question, "tick": tick,
                   "default_horizon": self.default_horizon}
        if governed_contract is not None:
            context["governed_forecast_contract"] = governed_contract
        if not legacy_replay:
            context["evidence"] = evidence
        if legacy_replay:
            user_payload = json.dumps({"question": question, "world": digest})[:6000]
        elif hardened_evidence:
            user_payload, prompt_world = _answer_user_json(
                question=question, tick=tick, world=digest, evidence=evidence,
                governed_contract=governed_contract)
            context["prompt_world"] = prompt_world
        else:
            user_payload = json.dumps({
                "question": question, "world": digest,
                "read_only_evidence": evidence,
                **({"governed_forecast_contract": governed_contract}
                   if governed_contract is not None else {}),
            })[:12000]
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
            if isinstance(ans.get("p"), bool):
                raise ValueError("forecast probability must be a finite number")
            p = float(ans["p"])
            if not math.isfinite(p) or not 0.0 <= p <= 1.0:
                raise ValueError("forecast probability must be between 0 and 1")
            rule = ans.get("resolution_rule") or {}
            if self.strict_resolution_rules:
                rule = validate_resolution_rule(
                    rule, metric_exists=self._metric_exists)
            elif not isinstance(rule, dict) or not rule.get("type"):
                raise ValueError("resolution_rule.type is required")
            confidence = str(ans.get("confidence", "med"))
            if self.strict_resolution_rules and confidence not in {"low", "med", "high"}:
                raise ValueError("confidence must be low, med, or high")
            drivers = ans.get("drivers", [])
            if self.strict_resolution_rules and not (
                isinstance(drivers, list) and 1 <= len(drivers) <= 10
                and all(isinstance(driver, str) and driver.strip()
                        and len(driver) <= 300 for driver in drivers)
            ):
                raise ValueError("drivers must contain 1 to 10 bounded strings")
            raw_deadline = ans.get("deadline_tick")
            if raw_deadline is None:
                raw_deadline = tick + self.default_horizon
            if isinstance(raw_deadline, bool):
                raise ValueError("deadline_tick must be an integer")
            deadline = int(raw_deadline)
            if isinstance(raw_deadline, float) and raw_deadline != deadline:
                raise ValueError("deadline_tick must be an integer")
            if deadline <= tick:
                raise ValueError("deadline_tick must be in the future")
            if self.strict_resolution_rules:
                max_horizon = int(
                    self.config.get("oracle", {}).get("max_horizon_ticks", 365))
                if deadline > tick + max_horizon:
                    raise ValueError(
                        f"deadline_tick exceeds the {max_horizon}-tick limit")
            if governed_contract is not None:
                if rule != governed_contract["resolution_rule"]:
                    raise ValueError(
                        "resolution_rule does not match governed forecast contract")
                if deadline != governed_contract["deadline_tick"]:
                    raise ValueError(
                        "deadline_tick does not match governed forecast contract")
        except (KeyError, TypeError, ValueError, ResolutionRuleError) as exc:
            pid = self.store.insert(
                "predictions", asked_tick=tick, question=question, p=None,
                reasoning="answer did not meet the contract",
                evidence_json=json.dumps(evidence), status="insufficient_data")
            if self.strict_resolution_rules:
                self.store.log_event(tick, "oracle_rule_rejected", {
                    "prediction_id": pid, "question": question,
                    "reason": str(exc)[:300],
                }, phase=None, importance=2.0)
            return {"insufficient_data": True,
                    "reason": "The analyst could not produce a checkable prediction.",
                    "prediction_id": pid, "evidence": evidence}

        pid = self.store.insert(
            "predictions", asked_tick=tick, question=question, p=p,
            reasoning=str(ans.get("reasoning", ""))[:2000],
            drivers_json=json.dumps(drivers),
            confidence=confidence,
            resolution_rule_json=json.dumps(rule), deadline_tick=deadline,
            evidence_json=json.dumps(evidence), status="open")
        self.store.log_event(tick, "oracle_prediction", {
            "prediction_id": pid, "question": question, "p": p, "deadline_tick": deadline,
            "rule": rule}, importance=2.0)
        return {"prediction_id": pid, "p": p, "drivers": ans.get("drivers", []),
                "confidence": ans.get("confidence", "med"), "resolution_rule": rule,
                "deadline_tick": deadline, "reasoning": ans.get("reasoning", ""),
                "evidence": evidence}

    def _normalize_governed_contract(
        self, contract: dict | None, *, tick: int,
    ) -> dict | None:
        """Validate engine-owned schedule facts before they enter either prompt."""
        if contract is None:
            return None
        if not isinstance(contract, dict):
            raise ValueError("governed forecast contract must be an object")
        required = {
            "campaign_id", "campaign_version", "campaign_key", "scheduled_tick",
            "resolution_rule", "deadline_tick",
        }
        if set(contract) != required:
            raise ValueError("governed forecast contract fields are invalid")
        if not isinstance(contract["campaign_id"], str) or not contract["campaign_id"]:
            raise ValueError("governed forecast campaign_id is invalid")
        if not isinstance(contract["campaign_key"], str) or not contract["campaign_key"]:
            raise ValueError("governed forecast campaign_key is invalid")
        version = contract["campaign_version"]
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ValueError("governed forecast campaign_version is invalid")
        scheduled_tick = contract["scheduled_tick"]
        deadline_tick = contract["deadline_tick"]
        if (isinstance(scheduled_tick, bool) or not isinstance(scheduled_tick, int)
                or scheduled_tick != tick):
            raise ValueError("governed forecast scheduled_tick is invalid")
        if (isinstance(deadline_tick, bool) or not isinstance(deadline_tick, int)
                or deadline_tick <= tick):
            raise ValueError("governed forecast deadline_tick is invalid")
        max_horizon = int(
            self.config.get("oracle", {}).get("max_horizon_ticks", 365))
        if deadline_tick > tick + max_horizon:
            raise ValueError("governed forecast deadline exceeds configured horizon")
        rule = validate_resolution_rule(
            contract["resolution_rule"], metric_exists=self._metric_exists)
        return {
            "campaign_id": contract["campaign_id"],
            "campaign_version": version,
            "campaign_key": contract["campaign_key"],
            "scheduled_tick": scheduled_tick,
            "resolution_rule": rule,
            "deadline_tick": deadline_tick,
        }

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

    def _hardened_evidence_at(self, tick: int, question: str) -> bool:
        """Gate the new prompt shape and preserve recorded pre-hardening calls."""
        if self.engine_semantics_version < 7:
            return False
        if not self.gw.replay or self.gw.replay_conn is None:
            return True
        rows = self.gw.replay_conn.execute(
            "SELECT request_json FROM llm_calls WHERE tick=? AND role='oracle' "
            "AND purpose='oracle' ORDER BY id", (tick,)).fetchall()
        for row in rows:
            request = load_json(row["request_json"], {})
            context = request.get("context") if isinstance(request, dict) else None
            try:
                user = json.loads(request.get("user", "")) \
                    if isinstance(request, dict) else None
            except (TypeError, ValueError, json.JSONDecodeError):
                user = None
            if (isinstance(context, dict) and context.get("question") == question
                    and isinstance(user, dict)):
                return bool(
                    user.get("tick") == tick
                    and "prompt_world" in context
                    and user.get("world") == context.get("prompt_world"))
        # A recorded answer must exist whenever an oracle_plan call exists.
        # Missing evidence fails closed through the gateway lookup path.
        return False

    # ── world digest (read-only tools rolled into one) ───────────────────────
    def _world_digest(self, tick: int) -> dict:
        m = {n: self.store.metric_latest(n, 0.0) for n in
             ("gdp_proxy", "gdp_proxy_30d", "labor_income", "cpi", "inflation_30d",
              "cpi_yoy", "unemployment", "index", "index_change_10",
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
            if self.strict_resolution_rules:
                try:
                    validate_resolution_rule(
                        rule, metric_exists=self._metric_exists)
                except ResolutionRuleError as exc:
                    self.store.update(
                        "predictions", int(pred["id"]), status="insufficient_data",
                        reasoning="stored resolution rule is not machine-checkable")
                    self.store.log_event(tick, "oracle_resolution_invalid", {
                        "prediction_id": int(pred["id"]),
                        "question": pred["question"], "reason": str(exc)[:300],
                    }, importance=3.0)
                    continue
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

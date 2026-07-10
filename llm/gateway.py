"""The LLM gateway: routing, governor, caching, parsing, cost accounting, replay.

No LLM output ever writes state directly (TECH-SPEC §1). This layer turns a role +
context into a validated decision envelope, meters every dollar against the run
cap, and records the full request/response so a run can be replayed for free.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from .adapters import Adapter, build_adapters

# Verified pricing (TECH-SPEC §12), USD per 1M tokens: [input, output, cache_read].
DEFAULT_PRICING = {
    "minimax-m3": {"in": 0.30, "out": 1.20, "cache": 0.06},
    "kimi-k2.7": {"in": 0.95, "out": 4.00, "cache": 0.19},
    "claude-haiku-4-5-20251001": {"in": 1.00, "out": 5.00, "cache": 0.10},
    "claude-sonnet-5": {"in": 3.00, "out": 15.00, "cache": 0.30},
    "scripted": {"in": 0.0, "out": 0.0, "cache": 0.0},
    "mock": {"in": 0.0, "out": 0.0, "cache": 0.0},
}


class BudgetExceeded(Exception):
    """Raised when a call would breach the hard cap — the world pauses cleanly."""


@dataclass
class LLMRequest:
    role: str                       # citizen|central_banker|credit_officer|editor|reporter|oracle|...
    purpose: str                    # decision|conversation|memory|newsroom|oracle|persona
    system: str = ""
    user: str = ""
    context: dict = field(default_factory=dict)     # structured data for scripted policies
    agent_id: Optional[int] = None
    tick: int = 0
    max_tokens: int = 700
    temperature: float = 0.7

    def messages(self) -> list[dict]:
        msgs = []
        if self.system:
            msgs.append({"role": "system", "content": self.system})
        msgs.append({"role": "user", "content": self.user})
        return msgs


@dataclass
class LLMResponse:
    text: str
    parsed: dict
    provider: str
    model: str
    in_tokens: int
    out_tokens: int
    cost_usd: float
    cached: bool = False
    ok: bool = True


class Governor:
    """Real-time spend accounting with staged degradation (PRD R7, TECH-SPEC §8).

    Thresholds bite against the *world budget* (cap minus the Oracle carve-out) so
    interrogation never starves the world; total spend still never exceeds the cap.
    """

    def __init__(self, store, budget_cfg: dict):
        self.store = store
        self.cap_usd = float(budget_cfg.get("cap_usd", 200.0))
        self.oracle_reserve_usd = float(budget_cfg.get("oracle_reserve_usd", 10.0))
        self.thresholds = budget_cfg.get("thresholds", [0.60, 0.80, 0.95])
        self.base_conversation_pairs = int(budget_cfg.get("conversation_pairs", 15))
        self._level = 0

    # spend is read from the durable llm_calls log so it survives resume.
    def total_spend(self) -> float:
        return float(self.store.scalar("SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls", default=0.0))

    def oracle_spend(self) -> float:
        return float(self.store.scalar(
            "SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls WHERE purpose='oracle'", default=0.0))

    def world_spend(self) -> float:
        return float(self.store.scalar(
            "SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls WHERE purpose<>'oracle'", default=0.0))

    @property
    def world_budget(self) -> float:
        return max(0.01, self.cap_usd - self.oracle_reserve_usd)

    def level(self) -> int:
        frac = self.world_spend() / self.world_budget
        lvl = 0
        for i, t in enumerate(self.thresholds):
            if frac >= t:
                lvl = i + 1
        if self.world_spend() >= self.world_budget:
            lvl = len(self.thresholds) + 1  # pause level
        return lvl

    # knobs the world reads each tick ----------------------------------------
    def conversation_pairs(self) -> int:
        return {0: self.base_conversation_pairs, 1: 8, 2: 4, 3: 0}.get(min(self.level(), 3), 0)

    def cadence_multiplier(self) -> int:
        return {0: 1, 1: 1, 2: 2, 3: 4}.get(min(self.level(), 3), 4)

    def citizens_enabled(self) -> bool:
        return self.level() < 3

    def should_pause(self) -> bool:
        return self.level() >= len(self.thresholds) + 1

    def can_spend(self, est_cost: float, purpose: str) -> bool:
        if purpose == "oracle":
            return self.oracle_spend() + est_cost <= self.oracle_reserve_usd \
                and self.total_spend() + est_cost <= self.cap_usd
        return self.total_spend() + est_cost <= self.cap_usd

    def status(self) -> dict:
        return {
            "cap_usd": self.cap_usd, "oracle_reserve_usd": self.oracle_reserve_usd,
            "total_spend_usd": round(self.total_spend(), 4),
            "world_spend_usd": round(self.world_spend(), 4),
            "oracle_spend_usd": round(self.oracle_spend(), 4),
            "level": self.level(), "conversation_pairs": self.conversation_pairs(),
            "cadence_multiplier": self.cadence_multiplier(),
            "citizens_enabled": self.citizens_enabled(),
            "fraction": round(self.total_spend() / self.cap_usd, 4) if self.cap_usd else 0,
        }


class Gateway:
    def __init__(self, store, config: dict):
        self.store = store
        self.config = config
        llm_cfg = config.get("llm", {})
        self.routes: dict[str, dict] = llm_cfg.get("routes", {})
        self.default_route = llm_cfg.get("default_route", {"provider": "scripted", "model": "scripted"})
        self.pricing = {**DEFAULT_PRICING, **llm_cfg.get("pricing", {})}
        self.adapters: dict[str, Adapter] = build_adapters(llm_cfg)
        self.governor = Governor(store, config.get("budget", {}))
        self.semaphore = asyncio.Semaphore(int(llm_cfg.get("concurrency", 8)))
        self.replay = bool(config.get("replay", False))
        self._seen_prefixes: set[str] = set()

    @property
    def scripted(self):
        return self.adapters["scripted"]

    # ── routing ──────────────────────────────────────────────────────────────
    def route(self, role: str, purpose: str) -> tuple[str, str]:
        r = self.routes.get(role) or self.routes.get(purpose) or self.default_route
        return r.get("provider", "scripted"), r.get("model", "scripted")

    # ── main entry ───────────────────────────────────────────────────────────
    async def complete(self, req: LLMRequest, *, schema_hint: str = "") -> LLMResponse:
        provider, model = self.route(req.role, req.purpose)
        adapter = self.adapters.get(provider) or self.scripted
        cache_key = self._cache_key(req, provider, model)

        if self.replay:
            replayed = self._replay_lookup(cache_key)
            if replayed is not None:
                return replayed

        # Budget pre-check (skip for free providers so offline runs never pause).
        pricing = self.pricing.get(model, {"in": 0, "out": 0, "cache": 0})
        est_cost = self._estimate_cost(req, pricing)
        if est_cost > 0 and not self.governor.can_spend(est_cost, req.purpose):
            raise BudgetExceeded(
                f"call would breach cap (spend={self.governor.total_spend():.2f}, cap={self.governor.cap_usd})")

        started = datetime.now(timezone.utc)
        async with self.semaphore:
            result = await adapter.complete(
                model, req.messages(), purpose=req.purpose, context=req.context,
                max_tokens=req.max_tokens, temperature=req.temperature)
        latency_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)

        parsed, ok = self._parse(result.text)
        if not ok and provider not in ("scripted", "mock"):
            # One repair retry with the parse error appended (TECH-SPEC §8 failure policy).
            repair = LLMRequest(
                role=req.role, purpose=req.purpose, system=req.system,
                user=req.user + "\n\nYour previous reply was not valid JSON. Reply ONLY with the JSON envelope.",
                context=req.context, agent_id=req.agent_id, tick=req.tick,
                max_tokens=req.max_tokens, temperature=0.2)
            async with self.semaphore:
                result = await adapter.complete(model, repair.messages(), purpose=req.purpose,
                                                context=req.context, max_tokens=req.max_tokens,
                                                temperature=0.2)
            parsed, ok = self._parse(result.text)
        if not ok:
            parsed = {"reasoning": "unparseable output; no-op", "actions": [{"type": "do_nothing"}]}

        cached, cost = self._price(req, model, result.in_tokens, result.out_tokens, pricing)
        self._log_call(req, provider, model, cache_key, result, cost, cached, latency_ms)

        return LLMResponse(text=result.text, parsed=parsed, provider=provider, model=model,
                           in_tokens=result.in_tokens, out_tokens=result.out_tokens,
                           cost_usd=cost, cached=cached, ok=ok)

    # ── parsing ──────────────────────────────────────────────────────────────
    @staticmethod
    def _parse(text: str) -> tuple[dict, bool]:
        text = (text or "").strip()
        if not text:
            return {}, False
        # Tolerate code fences / prose around the JSON object.
        try:
            return json.loads(text), True
        except json.JSONDecodeError:
            pass
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1]), True
            except json.JSONDecodeError:
                return {}, False
        return {}, False

    # ── caching + cost ───────────────────────────────────────────────────────
    def _price(self, req: LLMRequest, model: str, in_tok: int, out_tok: int, pricing: dict) -> tuple[bool, float]:
        prefix_key = hashlib.sha1((model + "|" + req.system).encode()).hexdigest()
        prefix_tokens = max(1, len(req.system) // 4)
        cached = prefix_key in self._seen_prefixes
        self._seen_prefixes.add(prefix_key)
        cached_in = min(prefix_tokens, in_tok) if cached else 0
        noncached_in = in_tok - cached_in
        cost = (noncached_in / 1e6) * pricing["in"] + (cached_in / 1e6) * pricing["cache"] \
            + (out_tok / 1e6) * pricing["out"]
        return cached, round(cost, 8)

    def _estimate_cost(self, req: LLMRequest, pricing: dict) -> float:
        in_tok = max(1, (len(req.system) + len(req.user)) // 4)
        out_tok = req.max_tokens
        return (in_tok / 1e6) * pricing["in"] + (out_tok / 1e6) * pricing["out"]

    def _cache_key(self, req: LLMRequest, provider: str, model: str) -> str:
        blob = json.dumps({"t": req.tick, "a": req.agent_id, "p": req.purpose,
                           "m": model, "msgs": req.messages()}, sort_keys=True)
        return hashlib.sha1(blob.encode()).hexdigest()

    def _replay_lookup(self, cache_key: str) -> Optional[LLMResponse]:
        row = self.store.query_one(
            "SELECT * FROM llm_calls WHERE cache_key=? ORDER BY id LIMIT 1", (cache_key,))
        if not row:
            return None
        resp = json.loads(row["response_json"]) if row["response_json"] else {}
        parsed, ok = self._parse(resp.get("text", "{}"))
        return LLMResponse(text=resp.get("text", ""), parsed=parsed, provider=row["provider"],
                           model=row["model"], in_tokens=int(row["in_tokens"]),
                           out_tokens=int(row["out_tokens"]), cost_usd=0.0, cached=True, ok=ok)

    def _log_call(self, req: LLMRequest, provider: str, model: str, cache_key: str,
                  result, cost: float, cached: bool, latency_ms: int) -> None:
        self.store.insert(
            "llm_calls", tick=req.tick, agent_id=req.agent_id, role=req.role, provider=provider,
            model=model, purpose=req.purpose, cache_key=cache_key,
            request_json=json.dumps({"system": req.system, "user": req.user, "context": req.context}),
            response_json=json.dumps({"text": result.text, "raw": result.raw}),
            in_tokens=result.in_tokens, out_tokens=result.out_tokens, cached=1 if cached else 0,
            cost_usd=cost, latency_ms=latency_ms,
            created_at=datetime.now(timezone.utc).isoformat())

"""The LLM gateway: routing, governor, caching, parsing, cost accounting, replay.

No LLM output ever writes state directly (TECH-SPEC §1). This layer turns a role +
context into a validated decision envelope, meters every dollar against the run
cap, and records the full request/response so a run can be replayed for free.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from .adapters import Adapter, AdapterHTTPError, AdapterResult, build_adapters
from .readiness import ProviderConfigurationError, validate_llm_config
from observability import get_logger, log_event as operational_log


logger = get_logger("llm")


PRIVATE_REASONING_FIELDS = frozenset({
    "analysis",
    "chain_of_thought",
    "reasoning",
    "reasoning_content",
    "reasoning_details",
    "thinking",
    "thought",
    "thoughts",
})
PRIVATE_REASONING_TAGS = (
    "think",
    "analysis",
    "chain_of_thought",
    "reasoning_content",
    "reasoning_details",
    "thinking",
    "thought",
    "thoughts",
)
_PRIVATE_REASONING_BLOCK = re.compile(
    rf"<(?P<tag>{'|'.join(PRIVATE_REASONING_TAGS)})\b[^>]*>.*?</(?P=tag)\s*>",
    re.IGNORECASE | re.DOTALL,
)
_PRIVATE_REASONING_UNCLOSED = re.compile(
    rf"<(?:{'|'.join(PRIVATE_REASONING_TAGS)})\b[^>]*>.*\Z",
    re.IGNORECASE | re.DOTALL,
)


def sanitize_provider_text(value: str) -> str:
    """Remove provider-only tagged reasoning while retaining the public answer."""
    sanitized = value
    while True:
        redacted = _PRIVATE_REASONING_BLOCK.sub("", sanitized)
        if redacted == sanitized:
            break
        sanitized = redacted
    return _PRIVATE_REASONING_UNCLOSED.sub("", sanitized).strip()


def sanitize_provider_raw(value: Any) -> Any:
    """Remove private reasoning text while retaining billing and response metadata."""
    if isinstance(value, dict):
        return {
            key: sanitize_provider_raw(item)
            for key, item in value.items()
            if str(key).lower() not in PRIVATE_REASONING_FIELDS
        }
    if isinstance(value, list):
        return [sanitize_provider_raw(item) for item in value]
    if isinstance(value, str):
        return sanitize_provider_text(value)
    return value

# Verified pricing (TECH-SPEC §12), USD per 1M tokens: [input, output, cache_read].
DEFAULT_PRICING = {
    "minimax-m3": {"in": 0.30, "out": 1.20, "cache": 0.06},
    "MiniMax-M3": {"in": 0.30, "out": 1.20, "cache": 0.06},
    "kimi-k2.7": {"in": 0.95, "out": 4.00, "cache": 0.19},
    "kimi-for-coding": {"in": 0.95, "out": 4.00, "cache": 0.19},
    "MiniMax-M2.7": {"in": 0.30, "out": 1.20, "cache": 0.06},
    "kimi-k2.6": {"in": 0.95, "out": 4.00, "cache": 0.16},
    "claude-haiku-4-5-20251001": {"in": 1.00, "out": 5.00, "cache": 0.10},
    "claude-sonnet-5": {"in": 3.00, "out": 15.00, "cache": 0.30},
    "scripted": {"in": 0.0, "out": 0.0, "cache": 0.0},
    "mock": {"in": 0.0, "out": 0.0, "cache": 0.0},
}


class BudgetExceeded(Exception):
    """Raised when a call would breach the hard cap — the world pauses cleanly."""


class ProviderUnavailable(Exception):
    """A routed provider failed after retry; the world must pause visibly."""

    def __init__(self, provider: str, model: str, purpose: str, message: str, *,
                 latency_ms: int = 0, attempts: int = 1):
        self.provider = provider
        self.model = model
        self.purpose = purpose
        self.message = message[:500]
        self.latency_ms = latency_ms
        self.attempts = attempts
        super().__init__(f"{provider}/{model} failed for {purpose}: {self.message}")

    def as_dict(self) -> dict:
        return {
            "provider": self.provider, "model": self.model, "purpose": self.purpose,
            "error": self.message, "latency_ms": self.latency_ms, "attempts": self.attempts,
        }


class GatewayInterrupted(Exception):
    """The operator interrupted an in-flight provider cooldown."""


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
    call_id: Optional[int] = None


class Governor:
    """Real-time spend accounting with staged degradation (PRD R7, TECH-SPEC §8).

    Thresholds bite against the *world budget* (cap minus the Oracle carve-out) so
    interrogation never starves a capped world. An explicit ``cap_usd: null``
    disables degradation and budget pauses while retaining spend accounting.
    """

    def __init__(self, store, budget_cfg: dict):
        self.store = store
        cap = budget_cfg.get("cap_usd", 200.0)
        self.cap_usd = None if cap is None else float(cap)
        self.oracle_reserve_usd = float(budget_cfg.get("oracle_reserve_usd", 10.0))
        # Persisted opt-in keeps historical capped replays on their original
        # accounting while fresh runs reserve the complete Oracle workflow.
        self.oracle_plan_in_reserve = bool(
            budget_cfg.get("oracle_plan_in_reserve", False))
        self.thresholds = budget_cfg.get("thresholds", [0.60, 0.80, 0.95])
        self.base_conversation_pairs = int(budget_cfg.get("conversation_pairs", 15))
        self._last_call_id = 0
        self._total_spend_usd = 0.0
        self._oracle_spend_usd = 0.0
        self._world_spend_usd = 0.0
        self._refresh_spend()
        self._level = self._calculate_level()

    # Spend is backed by the durable append-only llm_calls log so it survives
    # resume. Runtime inserts update the cache in O(1); a cheap MAX(id) check
    # notices direct test/tool inserts and refreshes the aggregates when needed.
    def _refresh_spend(self) -> None:
        oracle_clause = (
            "purpose IN ('oracle','oracle_plan')"
            if self.oracle_plan_in_reserve else "purpose='oracle'")
        row = self.store.query_one(
            "SELECT COALESCE(MAX(id),0) AS last_id, "
            "COALESCE(SUM(cost_usd),0) AS total, "
            f"COALESCE(SUM(CASE WHEN {oracle_clause} THEN cost_usd ELSE 0 END),0) AS oracle "
            "FROM llm_calls")
        self._last_call_id = int(row["last_id"] if row else 0)
        self._total_spend_usd = float(row["total"] if row else 0.0)
        self._oracle_spend_usd = float(row["oracle"] if row else 0.0)
        self._world_spend_usd = self._total_spend_usd - self._oracle_spend_usd

    def _ensure_current(self) -> None:
        last_id = int(self.store.scalar(
            "SELECT COALESCE(MAX(id),0) FROM llm_calls", default=0))
        if last_id != self._last_call_id:
            self._refresh_spend()

    def record_cost(self, call_id: int, cost_usd: float, purpose: str) -> None:
        """Advance cached totals after the gateway appends one durable call row."""
        cost = float(cost_usd)
        self._last_call_id = max(self._last_call_id, int(call_id))
        self._total_spend_usd += cost
        if self._uses_oracle_reserve(purpose):
            self._oracle_spend_usd += cost
        else:
            self._world_spend_usd += cost

    def _uses_oracle_reserve(self, purpose: str) -> bool:
        return purpose == "oracle" or (
            self.oracle_plan_in_reserve and purpose == "oracle_plan")

    def total_spend(self) -> float:
        self._ensure_current()
        return self._total_spend_usd

    def oracle_spend(self) -> float:
        self._ensure_current()
        return self._oracle_spend_usd

    def world_spend(self) -> float:
        self._ensure_current()
        return self._world_spend_usd

    @property
    def world_budget(self) -> float:
        if self.cap_usd is None:
            return float("inf")
        return max(0.01, self.cap_usd - self.oracle_reserve_usd)

    def _calculate_level(self) -> int:
        if self.cap_usd is None:
            return 0
        frac = self._world_spend_usd / self.world_budget
        lvl = 0
        for i, t in enumerate(self.thresholds):
            if frac + 1e-12 >= t:
                lvl = i + 1
        if self._world_spend_usd + 1e-12 >= self.world_budget:
            lvl = len(self.thresholds) + 1  # pause level
        return lvl

    def level(self) -> int:
        self._ensure_current()
        self._level = self._calculate_level()
        return self._level

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
        self._ensure_current()
        if self.cap_usd is None:
            return True
        if self._uses_oracle_reserve(purpose):
            return self._oracle_spend_usd + est_cost <= self.oracle_reserve_usd \
                and self._total_spend_usd + est_cost <= self.cap_usd
        return self._total_spend_usd + est_cost <= self.cap_usd

    def status(self) -> dict:
        self._ensure_current()
        return {
            "cap_usd": self.cap_usd, "oracle_reserve_usd": self.oracle_reserve_usd,
            "total_spend_usd": round(self._total_spend_usd, 4),
            "world_spend_usd": round(self._world_spend_usd, 4),
            "oracle_spend_usd": round(self._oracle_spend_usd, 4),
            "level": self.level(), "conversation_pairs": self.conversation_pairs(),
            "cadence_multiplier": self.cadence_multiplier(),
            "citizens_enabled": self.citizens_enabled(),
            "fraction": (round(self._total_spend_usd / self.cap_usd, 4)
                         if self.cap_usd else None),
        }


class Gateway:
    def __init__(self, store, config: dict):
        self.store = store
        self.config = config
        llm_cfg = config.get("llm", {})
        self.replay = bool(config.get("replay", False))
        self.readiness_report = validate_llm_config(
            config, require_secrets=not self.replay, raise_on_error=True)
        self.routes: dict[str, dict] = llm_cfg.get("routes", {})
        self.default_route = llm_cfg.get("default_route", {"provider": "scripted", "model": "scripted"})
        self.pricing = {**DEFAULT_PRICING, **llm_cfg.get("pricing", {})}
        self.adapters: dict[str, Adapter] = build_adapters(llm_cfg)
        self.governor = Governor(store, config.get("budget", {}))
        self.semaphore = asyncio.Semaphore(int(llm_cfg.get("concurrency", 8)))
        self.provider_retries = max(0, int(llm_cfg.get("provider_retries", 1)))
        raw_backoff = llm_cfg.get("rate_limit_backoff_s", [15, 30, 60, 120, 300])
        self.rate_limit_backoff_s = tuple(
            max(0.01, float(value)) for value in raw_backoff) or (15.0, 30.0, 60.0, 120.0, 300.0)
        self._rate_limits: dict[str, dict] = {}
        self._interrupt_event = asyncio.Event()
        self._active_adapter_tasks: set[asyncio.Task] = set()
        meta = store.get_meta()
        self.run_id = str(meta["run_id"]) if meta else "uninitialized"
        self.replay_conn: Optional[sqlite3.Connection] = None
        self._replay_positions: dict[str, int] = {}
        self._replay_used_call_ids: set[int] = set()
        if self.replay:
            source = str(config.get("replay_source_path", "")).strip()
            if not source:
                raise ProviderConfigurationError(["replay_source_path is required for exact replay"])
            source_uri = f"file:{source.replace(chr(92), '/')}?mode=ro"
            self.replay_conn = sqlite3.connect(source_uri, uri=True, check_same_thread=False)
            self.replay_conn.row_factory = sqlite3.Row

    @property
    def scripted(self):
        return self.adapters["scripted"]

    # ── routing ──────────────────────────────────────────────────────────────
    def route(self, role: str, purpose: str) -> tuple[str, str]:
        r = self.routes.get(role) or self.routes.get(purpose) or self.default_route
        return r.get("provider", "scripted"), r.get("model", "scripted")

    def readiness(self) -> dict:
        return self.readiness_report

    def interrupt_pending(self) -> None:
        self._interrupt_event.set()
        for task in tuple(self._active_adapter_tasks):
            task.cancel()

    def clear_interrupt(self) -> None:
        self._interrupt_event.clear()

    def rate_limit_status(self) -> Optional[dict]:
        active = []
        now = time.time()
        for state in self._rate_limits.values():
            remaining = max(0.0, float(state["retry_at_epoch"]) - now)
            if remaining > 0:
                active.append({**state, "cooldown_remaining_s": round(remaining, 3)})
        if not active:
            return None
        return max(active, key=lambda item: item["retry_at_epoch"])

    async def _wait_for_provider(self, provider: str) -> None:
        state = self._rate_limits.get(provider)
        if not state:
            return
        remaining = float(state["retry_at_epoch"]) - time.time()
        if remaining <= 0:
            return
        try:
            await asyncio.wait_for(self._interrupt_event.wait(), timeout=remaining)
        except asyncio.TimeoutError:
            return
        raise GatewayInterrupted(f"operator interrupted {provider} rate-limit cooldown")

    def _record_rate_limit(self, provider: str, model: str, req: LLMRequest,
                           exc: AdapterHTTPError) -> dict:
        previous = self._rate_limits.get(provider)
        attempt = int(previous["attempts"]) + 1 if previous else 1
        fallback = self.rate_limit_backoff_s[
            min(attempt - 1, len(self.rate_limit_backoff_s) - 1)]
        delay = float(exc.retry_after_s) if exc.retry_after_s is not None else fallback
        retry_at_epoch = max(
            float(previous["retry_at_epoch"]) if previous else 0.0,
            time.time() + max(0.01, delay))
        state = {
            "provider": provider,
            "model": model,
            "attempts": attempt,
            "cooldown_s": round(max(0.01, delay), 3),
            "retry_at_epoch": retry_at_epoch,
            "next_retry_at": datetime.fromtimestamp(
                retry_at_epoch, timezone.utc).isoformat(),
            "status_code": exc.status_code,
            "detail": exc.detail,
        }
        self._rate_limits[provider] = state
        operational_log(
            logger, logging.WARNING, "llm.rate_limit.waiting",
            run_id=self.run_id, provider=provider, model=model,
            role=req.role, purpose=req.purpose, agent_id=req.agent_id,
            tick=req.tick, attempts=attempt, cooldown_s=state["cooldown_s"],
            next_retry_at=state["next_retry_at"])
        return state

    def _clear_rate_limit(self, provider: str, model: str, req: LLMRequest) -> None:
        state = self._rate_limits.pop(provider, None)
        if state:
            operational_log(
                logger, logging.INFO, "llm.rate_limit.recovered",
                run_id=self.run_id, provider=provider, model=model,
                role=req.role, purpose=req.purpose, agent_id=req.agent_id,
                tick=req.tick, attempts=state["attempts"])

    async def preflight(self, *, live: bool = False) -> dict:
        """Return config readiness and optionally authenticate/list routed models."""
        report = validate_llm_config(
            self.config, require_secrets=not self.replay, raise_on_error=False)
        if not live or not report["ready"]:
            operational_log(logger, logging.INFO if report["ready"] else logging.WARNING,
                            "llm.preflight.completed", run_id=self.run_id,
                            live_requested=live, ready=report["ready"],
                            live_checked=False, errors=report.get("errors", []))
            return {**report, "live_checked": False}

        checks = []
        seen: set[tuple[str, str]] = set()
        routes = [self.default_route, *self.routes.values()]
        for route in routes:
            provider = str(route.get("provider", "scripted"))
            model = str(route.get("model", "scripted"))
            pair = (provider, model)
            if pair in seen:
                continue
            seen.add(pair)
            adapter = self.adapters[provider]
            try:
                result = await adapter.healthcheck(model)
                checks.append({"provider": provider, **result})
                operational_log(logger, logging.INFO, "llm.preflight.provider_completed",
                                run_id=self.run_id, provider=provider, model=model,
                                ok=result.get("ok", False))
            except Exception as exc:
                checks.append({"provider": provider, "model": model, "ok": False,
                               "live": True, "error": str(exc)[:500]})
                operational_log(logger, logging.ERROR, "llm.preflight.provider_failed",
                                run_id=self.run_id, provider=provider, model=model,
                                error_type=type(exc).__name__, error=str(exc))
        live_ready = all(c["ok"] for c in checks)
        operational_log(logger, logging.INFO if live_ready else logging.ERROR,
                        "llm.preflight.completed", run_id=self.run_id,
                        live_requested=True, ready=report["ready"],
                        live_checked=True, live_ready=live_ready,
                        providers_checked=len(checks))
        return {**report, "live_checked": True,
                "live_ready": live_ready, "checks": checks}

    # ── main entry ───────────────────────────────────────────────────────────
    async def complete(self, req: LLMRequest, *, schema_hint: str = "") -> LLMResponse:
        provider, model = self.route(req.role, req.purpose)
        adapter = self.adapters.get(provider)
        if adapter is None:
            operational_log(logger, logging.ERROR, "llm.route.unavailable",
                            run_id=self.run_id, provider=provider, model=model,
                            role=req.role, purpose=req.purpose, tick=req.tick)
            raise ProviderConfigurationError([f"routed provider '{provider}' is unavailable"])
        cache_key = self._cache_key(req, provider, model)
        provider_cache_key = f"{self.run_id}:{req.role}:{req.purpose}:{req.agent_id or 'shared'}"
        operational_log(logger, logging.DEBUG, "llm.request.started",
                        run_id=self.run_id, provider=provider, model=model,
                        role=req.role, purpose=req.purpose, agent_id=req.agent_id,
                        tick=req.tick, replay=self.replay)

        if self.replay:
            replayed = self._replay_lookup(cache_key, req, schema_hint)
            if replayed is not None:
                response, source_row = replayed
                response.call_id = self._log_replay_call(req, cache_key, source_row)
                operational_log(logger, logging.DEBUG, "llm.replay.hit",
                                run_id=self.run_id, model=model, role=req.role,
                                purpose=req.purpose, agent_id=req.agent_id, tick=req.tick)
                return response
            operational_log(logger, logging.ERROR, "llm.replay.missing",
                            run_id=self.run_id, model=model, role=req.role,
                            purpose=req.purpose, agent_id=req.agent_id, tick=req.tick)
            raise ProviderUnavailable(
                "replay", model, req.purpose,
                f"stored response missing for cache key {cache_key}", attempts=0)

        resumed = self._durable_lookup(cache_key, schema_hint)
        if resumed is not None:
            operational_log(
                logger, logging.DEBUG, "llm.resume.hit",
                run_id=self.run_id, provider=resumed.provider, model=resumed.model,
                role=req.role, purpose=req.purpose, agent_id=req.agent_id,
                tick=req.tick)
            return resumed

        # Budget pre-check (skip for free providers so offline runs never pause).
        pricing = self.pricing.get(model, {"in": 0, "out": 0, "cache": 0})
        est_cost = self._estimate_cost(req, pricing)
        if est_cost > 0 and not self.governor.can_spend(est_cost, req.purpose):
            operational_log(logger, logging.WARNING, "llm.budget.rejected",
                            run_id=self.run_id, model=model, purpose=req.purpose,
                            tick=req.tick, estimated_cost_usd=est_cost,
                            spend_usd=self.governor.total_spend(),
                            cap_usd=self.governor.cap_usd)
            raise BudgetExceeded(
                f"call would breach cap (spend={self.governor.total_spend():.2f}, cap={self.governor.cap_usd})")

        started = datetime.now(timezone.utc)
        try:
            result, attempts = await self._call_adapter(
                provider, adapter, model, req, req.messages(), req.temperature,
                provider_cache_key)
        except GatewayInterrupted:
            raise
        except Exception as exc:
            latency_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
            failure = ProviderUnavailable(
                provider, model, req.purpose, f"{type(exc).__name__}: {exc}",
                latency_ms=latency_ms, attempts=self.provider_retries + 1)
            self.store.log_event(req.tick, "provider_failure", failure.as_dict(),
                                 phase="LLM", importance=5.0)
            operational_log(logger, logging.ERROR, "llm.request.failed",
                            run_id=self.run_id, provider=provider, model=model,
                            role=req.role, purpose=req.purpose, agent_id=req.agent_id,
                            tick=req.tick, latency_ms=latency_ms,
                            attempts=failure.attempts, error_type=type(exc).__name__,
                            error=str(exc))
            raise failure from exc
        latency_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)

        result.text = sanitize_provider_text(result.text)
        parsed, ok = self._parse(result.text)
        if ok and schema_hint:
            ok = self._matches_schema(parsed, schema_hint)
        if not ok and provider not in ("scripted", "mock"):
            # One repair retry with the parse error appended (TECH-SPEC §8 failure policy).
            operational_log(logger, logging.WARNING, "llm.repair.started",
                            run_id=self.run_id, provider=provider, model=model,
                            role=req.role, purpose=req.purpose, agent_id=req.agent_id,
                            tick=req.tick)
            initial_result = result
            repair = LLMRequest(
                role=req.role, purpose=req.purpose, system=req.system,
                user=(req.user
                      + "\n\nYour previous reply did not match the required JSON contract. "
                        "Reply ONLY with the JSON object."
                      + (f" Required shape: {schema_hint}" if schema_hint else "")),
                context=req.context, agent_id=req.agent_id, tick=req.tick,
                max_tokens=req.max_tokens, temperature=0.2)
            try:
                repaired_result, repair_attempts = await self._call_adapter(
                    provider, adapter, model, repair, repair.messages(), 0.2,
                    provider_cache_key)
                repaired_result.text = sanitize_provider_text(repaired_result.text)
                attempts += repair_attempts
            except GatewayInterrupted:
                raise
            except Exception as exc:
                latency_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
                failure = ProviderUnavailable(
                    provider, model, req.purpose, f"repair {type(exc).__name__}: {exc}",
                    latency_ms=latency_ms, attempts=attempts + self.provider_retries + 1)
                self.store.log_event(req.tick, "provider_failure", failure.as_dict(),
                                     phase="LLM", importance=5.0)
                operational_log(logger, logging.ERROR, "llm.repair.failed",
                                run_id=self.run_id, provider=provider, model=model,
                                role=req.role, purpose=req.purpose, agent_id=req.agent_id,
                                tick=req.tick, latency_ms=latency_ms,
                                attempts=failure.attempts, error_type=type(exc).__name__,
                                error=str(exc))
                raise failure from exc
            # Persist the final usable text but meter both billable completions.
            # This stays one logical gateway record, so exact replay returns the
            # repaired envelope while reproducing the complete provider cost.
            result = AdapterResult(
                text=repaired_result.text,
                in_tokens=initial_result.in_tokens + repaired_result.in_tokens,
                out_tokens=initial_result.out_tokens + repaired_result.out_tokens,
                cached_in_tokens=(initial_result.cached_in_tokens
                                  + repaired_result.cached_in_tokens),
                raw={"provider_calls": 2, "repair": {
                    "initial": initial_result.raw, "final": repaired_result.raw}},
            )
            parsed, ok = self._parse(result.text)
            if ok and schema_hint:
                ok = self._matches_schema(parsed, schema_hint)
            operational_log(logger, logging.INFO, "llm.repair.completed",
                            run_id=self.run_id, provider=provider, model=model,
                            role=req.role, purpose=req.purpose, agent_id=req.agent_id,
                            tick=req.tick, valid=ok)
        if not ok:
            parsed = {"reasoning": "unparseable output; no-op", "actions": [{"type": "do_nothing"}]}
            operational_log(logger, logging.WARNING, "llm.contract.invalid",
                            run_id=self.run_id, provider=provider, model=model,
                            role=req.role, purpose=req.purpose, agent_id=req.agent_id,
                            tick=req.tick)

        cached, cost = self._price(
            model, result.in_tokens, result.out_tokens, result.cached_in_tokens, pricing)
        call_id = self._log_call(
            req, provider, model, cache_key, result, cost, cached, latency_ms)
        operational_log(logger, logging.DEBUG, "llm.request.completed",
                        run_id=self.run_id, provider=provider, model=model,
                        role=req.role, purpose=req.purpose, agent_id=req.agent_id,
                        tick=req.tick, attempts=attempts, latency_ms=latency_ms,
                        in_tokens=result.in_tokens, out_tokens=result.out_tokens,
                        cached_in_tokens=result.cached_in_tokens, cost_usd=cost,
                        valid=ok)

        return LLMResponse(text=result.text, parsed=parsed, provider=provider, model=model,
                           in_tokens=result.in_tokens, out_tokens=result.out_tokens,
                           cost_usd=cost, cached=cached, ok=ok, call_id=call_id)

    async def _call_adapter(self, provider: str, adapter: Adapter, model: str, req: LLMRequest,
                            messages: list[dict], temperature: float,
                            provider_cache_key: str):
        last_error: Optional[Exception] = None
        transient_attempt = 0
        total_attempts = 0
        while True:
            await self._wait_for_provider(provider)
            try:
                total_attempts += 1
                async with self.semaphore:
                    if self._interrupt_event.is_set():
                        raise GatewayInterrupted(
                            f"operator interrupted {provider} request")
                    active_task = asyncio.current_task()
                    if active_task is not None:
                        self._active_adapter_tasks.add(active_task)
                    try:
                        result = await adapter.complete(
                            model, messages, purpose=req.purpose, context=req.context,
                            max_tokens=req.max_tokens, temperature=temperature,
                            cache_key=provider_cache_key)
                    finally:
                        if active_task is not None:
                            self._active_adapter_tasks.discard(active_task)
                self._clear_rate_limit(provider, model, req)
                return result, total_attempts
            except asyncio.CancelledError:
                if self._interrupt_event.is_set():
                    raise GatewayInterrupted(
                        f"operator interrupted {provider} request")
                raise
            except AdapterHTTPError as exc:
                if exc.rate_limited:
                    self._record_rate_limit(provider, model, req, exc)
                    continue
                last_error = exc
                transient_attempt += 1
            except Exception as exc:
                last_error = exc
                transient_attempt += 1
            if transient_attempt <= self.provider_retries:
                operational_log(logger, logging.WARNING, "llm.request.retry",
                                run_id=self.run_id, provider=provider, model=model,
                                role=req.role, purpose=req.purpose, agent_id=req.agent_id,
                                tick=req.tick, attempt=transient_attempt,
                                next_attempt=transient_attempt + 1,
                                error_type=type(last_error).__name__,
                                error=str(last_error))
                await asyncio.sleep(min(0.25 * (2 ** (transient_attempt - 1)), 2.0))
                continue
            break
        if last_error is None:
            raise RuntimeError("provider retry loop ended without a result or error")
        raise last_error

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

    @staticmethod
    def _matches_schema(parsed: dict, schema_hint: str) -> bool:
        """Validate required top-level keys from a JSON example schema hint."""
        try:
            expected = json.loads(schema_hint)
        except (TypeError, ValueError, json.JSONDecodeError):
            return True
        if not isinstance(expected, dict) or not isinstance(parsed, dict):
            return False
        return all(key in parsed for key in expected)

    # ── caching + cost ───────────────────────────────────────────────────────
    def _price(self, model: str, in_tok: int, out_tok: int, cached_in: int,
               pricing: dict) -> tuple[bool, float]:
        cached_in = max(0, min(int(cached_in or 0), in_tok))
        cached = cached_in > 0
        noncached_in = in_tok - cached_in
        cost = (noncached_in / 1e6) * pricing["in"] + (cached_in / 1e6) * pricing["cache"] \
            + (out_tok / 1e6) * pricing["out"]
        return cached, round(cost, 8)

    def _estimate_cost(self, req: LLMRequest, pricing: dict) -> float:
        # UTF-8 bytes are a conservative tokenizer-independent upper bound for
        # normal byte/BPE tokenizers. Include message framing and reserve a second
        # full call because invalid JSON may trigger one repair completion.
        prompt_bytes = len(req.system.encode("utf-8")) + len(req.user.encode("utf-8"))
        in_tok = max(1, prompt_bytes + 256)
        one_call = (in_tok / 1e6) * pricing["in"] \
            + (max(0, req.max_tokens) / 1e6) * pricing["out"]
        return one_call * 2

    def _cache_key(self, req: LLMRequest, provider: str, model: str) -> str:
        blob = json.dumps({"t": req.tick, "a": req.agent_id, "p": req.purpose,
                           "m": model, "msgs": req.messages()}, sort_keys=True)
        return hashlib.sha1(blob.encode()).hexdigest()

    def _replay_lookup(self, cache_key: str, req: LLMRequest,
                       schema_hint: str = ""):
        if self.replay_conn is None:
            return None
        position = self._replay_positions.get(cache_key, 0)
        row = None
        while True:
            candidate = self.replay_conn.execute(
                "SELECT * FROM llm_calls WHERE cache_key=? ORDER BY id LIMIT 1 OFFSET ?",
                (cache_key, position)).fetchone()
            position += 1
            if not candidate:
                break
            if int(candidate["id"]) not in self._replay_used_call_ids:
                row = candidate
                break
        self._replay_positions[cache_key] = position
        if row is None:
            # Historical replay must survive prompt/context improvements. Fall
            # back only to the next unused call with the same deterministic
            # semantic identity; the source request, response, and cache key are
            # copied verbatim into the replay database.
            candidates = self.replay_conn.execute(
                "SELECT * FROM llm_calls WHERE tick=? AND agent_id IS ? "
                "AND role=? AND purpose=? ORDER BY id",
                (req.tick, req.agent_id, req.role, req.purpose)).fetchall()
            row = next(
                (candidate for candidate in candidates
                 if int(candidate["id"]) not in self._replay_used_call_ids),
                None)
            if row is not None:
                operational_log(
                    logger, logging.WARNING, "llm.replay.compatibility_fallback",
                    run_id=self.run_id, tick=req.tick, agent_id=req.agent_id,
                    role=req.role, purpose=req.purpose,
                    source_call_id=int(row["id"]))
        if not row:
            return None
        self._replay_used_call_ids.add(int(row["id"]))
        resp = json.loads(row["response_json"]) if row["response_json"] else {}
        parsed, ok = self._parse(resp.get("text", "{}"))
        if ok and schema_hint:
            ok = self._matches_schema(parsed, schema_hint)
        if not ok:
            parsed = {"reasoning": "unparseable output; no-op",
                      "actions": [{"type": "do_nothing"}]}
        response = LLMResponse(
            text=resp.get("text", ""), parsed=parsed, provider=row["provider"],
            model=row["model"], in_tokens=int(row["in_tokens"]),
            out_tokens=int(row["out_tokens"]), cost_usd=float(row["cost_usd"]),
            cached=bool(row["cached"]), ok=ok)
        return response, row

    def _durable_lookup(self, cache_key: str, schema_hint: str = "") -> Optional[LLMResponse]:
        """Reuse a completed same-run call when an interrupted phase is retried."""
        row = self.store.query_one(
            "SELECT * FROM llm_calls WHERE cache_key=? ORDER BY id LIMIT 1",
            (cache_key,))
        if not row:
            return None
        resp = json.loads(row["response_json"]) if row["response_json"] else {}
        parsed, ok = self._parse(resp.get("text", "{}"))
        if ok and schema_hint:
            ok = self._matches_schema(parsed, schema_hint)
        if not ok:
            parsed = {"reasoning": "unparseable output; no-op",
                      "actions": [{"type": "do_nothing"}]}
        return LLMResponse(
            text=resp.get("text", ""), parsed=parsed,
            provider=row["provider"], model=row["model"],
            in_tokens=int(row["in_tokens"]), out_tokens=int(row["out_tokens"]),
            cost_usd=float(row["cost_usd"]), cached=bool(row["cached"]), ok=ok,
            call_id=int(row["id"]))

    def _log_replay_call(self, req: LLMRequest, cache_key: str, row) -> int:
        """Copy original accounting so governor stages and scheduling replay exactly."""
        level_before = self.governor.level()
        call_id = self.store.insert(
            "llm_calls", tick=req.tick, agent_id=req.agent_id, role=req.role,
            provider=row["provider"], model=row["model"], purpose=req.purpose,
            cache_key=row["cache_key"] or cache_key, request_json=row["request_json"],
            response_json=row["response_json"], in_tokens=int(row["in_tokens"]),
            out_tokens=int(row["out_tokens"]), cached=int(row["cached"]),
            cost_usd=float(row["cost_usd"]), latency_ms=int(row["latency_ms"] or 0),
            created_at=row["created_at"] or datetime.now(timezone.utc).isoformat())
        self.governor.record_cost(call_id, float(row["cost_usd"]), req.purpose)
        self._log_governor_transitions(req.tick, level_before)
        return call_id

    def _log_call(self, req: LLMRequest, provider: str, model: str, cache_key: str,
                  result, cost: float, cached: bool, latency_ms: int) -> int:
        level_before = self.governor.level()
        call_id = self.store.insert(
            "llm_calls", tick=req.tick, agent_id=req.agent_id, role=req.role, provider=provider,
            model=model, purpose=req.purpose, cache_key=cache_key,
            request_json=json.dumps({"system": req.system, "user": req.user, "context": req.context}),
            response_json=json.dumps({"text": result.text, "raw": sanitize_provider_raw(result.raw),
                                      "cached_in_tokens": result.cached_in_tokens}),
            in_tokens=result.in_tokens, out_tokens=result.out_tokens, cached=1 if cached else 0,
            cost_usd=cost, latency_ms=latency_ms,
            created_at=datetime.now(timezone.utc).isoformat())
        self.governor.record_cost(call_id, cost, req.purpose)
        self._log_governor_transitions(req.tick, level_before)
        return call_id

    def _log_governor_transitions(self, tick: int, level_before: int) -> None:
        """Persist every newly crossed budget stage for UI visibility and replay."""
        level_after = self.governor.level()
        for level in range(level_before + 1, level_after + 1):
            threshold = (self.governor.thresholds[level - 1]
                         if level <= len(self.governor.thresholds) else 1.0)
            self.store.log_event(tick, "budget_degradation", {
                "from_level": level - 1,
                "to_level": level,
                "threshold": threshold,
                "world_fraction": round(
                    self.governor.world_spend() / self.governor.world_budget, 6),
                "conversation_pairs": self.governor.conversation_pairs(),
                "cadence_multiplier": self.governor.cadence_multiplier(),
                "citizens_enabled": self.governor.citizens_enabled(),
                "paused": self.governor.should_pause(),
            }, phase="LLM", importance=3.0)

"""The LLM gateway: routing, governor, caching, parsing, cost accounting, replay.

No LLM output ever writes state directly (TECH-SPEC §1). This layer turns a role +
context into a validated decision envelope, meters every dollar against the run
cap, and records the full request/response so a run can be replayed for free.
"""
from __future__ import annotations

import asyncio
import heapq
import hashlib
import json
import logging
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from engine.store import ReadOnlyReplaySnapshot, open_read_only_connection
from .adapters import Adapter, AdapterHTTPError, AdapterResult, build_adapters
from .readiness import ProviderConfigurationError, validate_llm_config
from observability import get_logger, log_event as operational_log, safe_fields


logger = get_logger("llm")


REPLAY_OPERATIONAL_PURPOSES = frozenset({"report_narrative"})


def _logical_replay_call(row: Any) -> str:
    """Canonicalize one source call without its local SQLite surrogate id."""
    record: dict[str, Any] = {}
    keys = row.keys() if hasattr(row, "keys") else row
    for column in keys:
        if column in {"id", "created_at", "updated_at"}:
            continue
        value = row[column]
        if column.endswith("_json") and isinstance(value, str):
            try:
                value = json.loads(value)
            except (TypeError, json.JSONDecodeError):
                pass
        record[str(column)] = value
    return json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False)


def _logical_replay_digest(records: list[str]) -> str:
    digest = hashlib.sha256()
    for record in sorted(records):
        digest.update(record.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


PRIVATE_REASONING_FIELDS = frozenset({
    "analysis",
    "chain_of_thought",
    "redacted_thinking",
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
    "redacted_thinking",
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
_PRIVATE_REASONING_TYPES = frozenset({
    *PRIVATE_REASONING_FIELDS,
    *PRIVATE_REASONING_TAGS,
})
_PRIVATE_REASONING_KEY_MARKER = re.compile(
    rf"(?i)(?:[\"']?\s*\b(?:{'|'.join(PRIVATE_REASONING_FIELDS)})\b"
    rf"\s*[\"']?\s*[:=])"
)
_PRIVATE_REASONING_TYPE_MARKER = re.compile(
    rf"(?i)(?:[\"']?\s*type\s*[\"']?\s*[:=]\s*[\"']?\s*"
    rf"(?:{'|'.join(_PRIVATE_REASONING_TYPES)})\b)"
)
_JSON_UNICODE_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})", re.IGNORECASE)
_DROP_PRIVATE = object()
_JSON_DECODER = json.JSONDecoder()


def _canonical_noop_text() -> str:
    return json.dumps(
        {"actions": [{"type": "do_nothing"}],
         "reasoning": "unparseable output; no-op"},
        ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def sanitize_provider_text(value: str) -> str:
    """Remove provider-only tagged reasoning while retaining the public answer."""
    sanitized = value
    while True:
        redacted = _PRIVATE_REASONING_BLOCK.sub("", sanitized)
        if redacted == sanitized:
            break
        sanitized = redacted
    return _PRIVATE_REASONING_UNCLOSED.sub("", sanitized).strip()


def _sanitize_private_value(value: Any, *, preserve_root_reasoning: bool,
                            root: bool = True) -> Any:
    """Remove private reasoning fields and type-discriminated content blocks."""
    if isinstance(value, dict):
        block_type = str(value.get("type", "")).strip().lower()
        if block_type in _PRIVATE_REASONING_TYPES:
            return _DROP_PRIVATE
        sanitized: dict[Any, Any] = {}
        for key, item in value.items():
            lowered = str(key).strip().lower()
            keep_public_reasoning = (
                root and preserve_root_reasoning and lowered == "reasoning")
            if lowered in PRIVATE_REASONING_FIELDS and not keep_public_reasoning:
                continue
            clean_item = _sanitize_private_value(
                item, preserve_root_reasoning=preserve_root_reasoning, root=False)
            if clean_item is not _DROP_PRIVATE:
                sanitized[key] = clean_item
        return sanitized
    if isinstance(value, list):
        sanitized_items = []
        for item in value:
            clean_item = _sanitize_private_value(
                item, preserve_root_reasoning=preserve_root_reasoning, root=False)
            if clean_item is not _DROP_PRIVATE:
                sanitized_items.append(clean_item)
        return sanitized_items
    if isinstance(value, str):
        return _sanitize_json_text(
            value, preserve_root_reasoning=root and preserve_root_reasoning)
    return value


def _json_fragments(value: str) -> list[tuple[Any, int, int]]:
    """Return every non-overlapping JSON object/array embedded in provider text."""
    fragments: list[tuple[Any, int, int]] = []
    cursor = 0
    while cursor < len(value):
        starts = [
            position for position in (value.find("{", cursor), value.find("[", cursor))
            if position >= 0
        ]
        if not starts:
            break
        start = min(starts)
        try:
            parsed, end = _JSON_DECODER.raw_decode(value, start)
        except json.JSONDecodeError:
            cursor = start + 1
            continue
        fragments.append((parsed, start, end))
        cursor = end
    return fragments


def _has_private_reasoning_marker(value: str) -> bool:
    """Detect key/type markers left outside parseable JSON and fail closed."""
    # Provider exceptions sometimes JSON-encode a second payload, leaving its
    # key quotes escaped in the outer diagnostic string.  Normalize only for
    # detection; the persisted value is never decoded or trusted.
    probe = value
    for _ in range(3):
        probe = probe.replace(r'\"', '"').replace(r"\'", "'")
        probe = _JSON_UNICODE_ESCAPE.sub(
            lambda match: (
                chr(int(match.group(1), 16))
                if int(match.group(1), 16) <= 0x7f
                else match.group(0)
            ),
            probe,
        )
    return bool(
        _PRIVATE_REASONING_KEY_MARKER.search(probe)
        or _PRIVATE_REASONING_TYPE_MARKER.search(probe)
    )


def _sanitize_json_value(value: Any, *, preserve_root_reasoning: bool,
                         redact_credentials: bool) -> Any:
    cleaned = _sanitize_private_value(
        value, preserve_root_reasoning=preserve_root_reasoning)
    if cleaned is _DROP_PRIVATE:
        cleaned = None
    if redact_credentials:
        cleaned = safe_fields({"payload": cleaned})["payload"]
    return cleaned


def _parse_exact_json(value: str) -> Any:
    """Parse a complete JSON document, distinguishing failure from JSON null."""
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return _DROP_PRIVATE


def _sanitize_json_text(value: str, *, preserve_root_reasoning: bool,
                        redact_credentials: bool = False) -> str:
    """Strip reasoning from all JSON fragments, failing closed on malformed ones."""
    visible = sanitize_provider_text(value)
    exact = _parse_exact_json(visible)
    if exact is not _DROP_PRIVATE:
        cleaned = _sanitize_json_value(
            exact, preserve_root_reasoning=preserve_root_reasoning,
            redact_credentials=redact_credentials)
        if cleaned == exact:
            return visible
        return json.dumps(
            cleaned, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    fragments = _json_fragments(visible)
    if not fragments:
        return "[REDACTED]" if _has_private_reasoning_marker(visible) else visible

    # A public top-level ``reasoning`` field belongs only to one valid decision
    # envelope. Multiple JSON values are not that contract, so raw/provider
    # diagnostic fragments never gain the public-field exception.
    keep_fragment_reasoning = preserve_root_reasoning and len(fragments) == 1
    outside: list[str] = []
    cursor = 0
    for _, start, end in fragments:
        outside.append(visible[cursor:start])
        cursor = end
    outside.append(visible[cursor:])
    if _has_private_reasoning_marker("".join(outside)):
        return "[REDACTED]"

    rendered: list[str] = []
    cursor = 0
    for parsed, start, end in fragments:
        rendered.append(visible[cursor:start])
        cleaned = _sanitize_json_value(
            parsed, preserve_root_reasoning=keep_fragment_reasoning,
            redact_credentials=redact_credentials)
        rendered.append(json.dumps(
            cleaned, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
        cursor = end
    rendered.append(visible[cursor:])
    return "".join(rendered)


def sanitize_provider_raw(value: Any) -> Any:
    """Remove private reasoning/credentials while retaining bounded metadata."""
    if isinstance(value, (dict, list)):
        cleaned = _sanitize_private_value(
            value, preserve_root_reasoning=False)
        if cleaned is _DROP_PRIVATE:
            return None
        return safe_fields({"raw": cleaned})["raw"]
    if isinstance(value, str):
        cleaned = _sanitize_json_text(value, preserve_root_reasoning=False)
        return safe_fields({"raw": cleaned})["raw"]
    return value


def sanitize_provider_error(value: Any) -> str:
    """Bound provider diagnostics and remove credentials and private reasoning."""
    visible = _sanitize_json_text(
        str(value), preserve_root_reasoning=False, redact_credentials=True)
    return str(safe_fields({"error": visible})["error"])

# Default modeled-equivalent pricing (TECH-SPEC §12), USD per 1M tokens.
DEFAULT_PRICING = {
    "minimax-m3": {"in": 0.30, "out": 1.20, "cache": 0.06},
    "MiniMax-M3": {"in": 0.30, "out": 1.20, "cache": 0.06},
    "kimi-k2.7": {"in": 0.95, "out": 4.00, "cache": 0.19},
    "kimi-for-coding": {"in": 0.95, "out": 4.00, "cache": 0.19},
    "MiniMax-M2.7": {"in": 0.30, "out": 1.20, "cache": 0.06},
    "kimi-k2.6": {"in": 0.95, "out": 4.00, "cache": 0.16},
    "deepseek-v4-flash": {"in": 0.14, "out": 0.28, "cache": 0.0028},
    "qwen3.5:9b": {"in": 0.0, "out": 0.0, "cache": 0.0},
    "agent-economy-qwen3.5:9b-16k": {"in": 0.0, "out": 0.0, "cache": 0.0},
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
        self.message = sanitize_provider_error(message)
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


class _RouteAttemptFailed(Exception):
    def __init__(self, error: BaseException, attempt_id: int | None):
        self.error = error
        self.attempt_id = attempt_id
        super().__init__(str(error))


class _RoutePlanExhausted(Exception):
    def __init__(self, error: BaseException, attempt_ids: list[int]):
        self.error = error
        self.attempt_ids = attempt_ids
        super().__init__(str(error))


class ReplayReferenceError(ProviderUnavailable):
    """Recorded replay provenance cannot be bound to one local event."""

    def __init__(self, message: str):
        super().__init__(
            "replay", "recorded-provenance", "event_reference", message,
            attempts=0)


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


@dataclass(frozen=True)
class RouteTarget:
    provider: str
    model: str
    timeout_s: float
    route_index: int = 0


@dataclass(frozen=True)
class RoutePlan:
    assigned_tier: str
    effective_tier: str
    reason: str
    targets: tuple[RouteTarget, ...]
    tiered: bool = False


class PriorityProviderGate:
    """A small priority-aware capacity gate for one live provider pool."""

    def __init__(self, capacity: int):
        self.capacity = max(1, int(capacity))
        self.active = 0
        self.queued = 0
        self.peak_active = 0
        self.peak_queued = 0
        self._sequence = 0
        self._waiters: list[tuple[int, int, float, asyncio.Future]] = []
        self._lock = asyncio.Lock()

    async def acquire(self, priority: int) -> tuple[float, int, int]:
        enqueued = time.perf_counter()
        async with self._lock:
            active_at_start = self.active
            queued_at_start = self.queued
            if self.active < self.capacity and not self._waiters:
                self.active += 1
                self.peak_active = max(self.peak_active, self.active)
                return 0.0, active_at_start, queued_at_start
            loop = asyncio.get_running_loop()
            future = loop.create_future()
            self._sequence += 1
            heapq.heappush(
                self._waiters,
                (int(priority), self._sequence, enqueued, future),
            )
            self.queued += 1
            self.peak_queued = max(self.peak_queued, self.queued)
        try:
            await future
        except BaseException:
            future.cancel()
            async with self._lock:
                self._dispatch_locked()
            raise
        return ((time.perf_counter() - enqueued) * 1000.0,
                active_at_start, queued_at_start)

    async def release(self) -> None:
        async with self._lock:
            self.active = max(0, self.active - 1)
            self._dispatch_locked()

    def _dispatch_locked(self) -> None:
        while self.active < self.capacity and self._waiters:
            _priority, _sequence, _enqueued, future = heapq.heappop(self._waiters)
            self.queued = max(0, self.queued - 1)
            if future.cancelled() or future.done():
                continue
            self.active += 1
            self.peak_active = max(self.peak_active, self.active)
            future.set_result(True)


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
        # End-of-run prose is operational rather than behavioral.  Fresh
        # profiles opt into a small carve-out; missing means zero so historical
        # stored configs keep their original world/Oracle scheduling exactly.
        self.report_reserve_usd = max(
            0.0, float(budget_cfg.get("report_reserve_usd", 0.0)))
        # Persisted opt-in keeps historical capped replays on their original
        # accounting while fresh runs reserve the complete Oracle workflow.
        self.oracle_plan_in_reserve = bool(
            budget_cfg.get("oracle_plan_in_reserve", False))
        self.thresholds = budget_cfg.get("thresholds", [0.60, 0.80, 0.95])
        self.base_conversation_pairs = int(budget_cfg.get("conversation_pairs", 15))
        self._last_call_id = 0
        self._total_spend_usd = 0.0
        self._oracle_spend_usd = 0.0
        self._report_spend_usd = 0.0
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
            f"COALESCE(SUM(CASE WHEN {oracle_clause} THEN cost_usd ELSE 0 END),0) AS oracle, "
            "COALESCE(SUM(CASE WHEN purpose='report_narrative' "
            "THEN cost_usd ELSE 0 END),0) AS report "
            "FROM llm_calls")
        self._last_call_id = int(row["last_id"] if row else 0)
        self._total_spend_usd = float(row["total"] if row else 0.0)
        self._oracle_spend_usd = float(row["oracle"] if row else 0.0)
        self._report_spend_usd = float(row["report"] if row else 0.0)
        self._world_spend_usd = (
            self._total_spend_usd - self._oracle_spend_usd - self._report_spend_usd)

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
        if self._uses_report_reserve(purpose):
            self._report_spend_usd += cost
        elif self._uses_oracle_reserve(purpose):
            self._oracle_spend_usd += cost
        else:
            self._world_spend_usd += cost

    def _uses_oracle_reserve(self, purpose: str) -> bool:
        return purpose == "oracle" or (
            self.oracle_plan_in_reserve and purpose == "oracle_plan")

    @staticmethod
    def _uses_report_reserve(purpose: str) -> bool:
        return purpose == "report_narrative"

    def total_spend(self) -> float:
        self._ensure_current()
        return self._total_spend_usd

    def oracle_spend(self) -> float:
        self._ensure_current()
        return self._oracle_spend_usd

    def world_spend(self) -> float:
        self._ensure_current()
        return self._world_spend_usd

    def report_spend(self) -> float:
        self._ensure_current()
        return self._report_spend_usd

    @property
    def world_budget(self) -> float:
        if self.cap_usd is None:
            return float("inf")
        return max(
            0.01,
            self.cap_usd - self.oracle_reserve_usd - self.report_reserve_usd)

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
        if self._uses_report_reserve(purpose):
            return self._report_spend_usd + est_cost <= self.report_reserve_usd \
                and self._total_spend_usd + est_cost <= self.cap_usd
        if self._uses_oracle_reserve(purpose):
            return self._oracle_spend_usd + est_cost <= self.oracle_reserve_usd \
                and self._total_spend_usd + est_cost <= self.cap_usd
        return self._world_spend_usd + est_cost <= self.world_budget \
            and self._total_spend_usd + est_cost <= self.cap_usd

    def status(self) -> dict:
        self._ensure_current()
        return {
            "cap_usd": self.cap_usd, "oracle_reserve_usd": self.oracle_reserve_usd,
            "report_reserve_usd": self.report_reserve_usd,
            "total_spend_usd": round(self._total_spend_usd, 4),
            "world_spend_usd": round(self._world_spend_usd, 4),
            "oracle_spend_usd": round(self._oracle_spend_usd, 4),
            "report_spend_usd": round(self._report_spend_usd, 4),
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
        self.tier_routes: dict[str, dict] = llm_cfg.get("tier_routes", {}) or {}
        self.premium_routes: dict[str, dict] = llm_cfg.get("premium_routes", {}) or {}
        self.citizen_model_cohorts: tuple[dict, ...] = tuple(
            dict(cohort) for cohort in (
                llm_cfg.get("citizen_model_cohorts", []) or []))
        self._citizen_model_assignments: dict[int, dict] | None = None
        self.role_tiers: dict[str, str] = llm_cfg.get("role_tiers", {}) or {}
        self.background_flash_purposes = set(llm_cfg.get(
            "background_flash_purposes",
            ["conversation", "memory", "newsroom", "report_narrative"]))
        self.provider_configs: dict[str, dict] = llm_cfg.get("providers", {}) or {}
        self.pricing = {**DEFAULT_PRICING, **llm_cfg.get("pricing", {})}
        self.adapters: dict[str, Adapter] = build_adapters(llm_cfg)
        self.governor = Governor(store, config.get("budget", {}))
        self.max_in_flight = max(1, int(
            llm_cfg.get("max_in_flight", llm_cfg.get("concurrency", 8))))
        self.semaphore = asyncio.Semaphore(self.max_in_flight)
        self.global_gate = PriorityProviderGate(self.max_in_flight)
        routed_providers = {
            target.provider for target in self._all_configured_targets()
        }
        self.provider_gates = {
            provider: PriorityProviderGate(int(
                self.provider_configs.get(provider, {}).get(
                    "concurrency", self.max_in_flight)))
            for provider in self.adapters if provider in routed_providers
        }
        self.logical_deadline_s = max(
            1.0, float(llm_cfg.get("logical_deadline_s", 150.0)))
        self._live_in_flight = 0
        self._peak_live_in_flight = 0
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
        self._replay_snapshot: ReadOnlyReplaySnapshot | None = None
        self._replay_positions: dict[str, int] = {}
        self._replay_used_call_ids: set[int] = set()
        self._replay_event_id_map: dict[int, int] = {}
        self._replay_exact_key_count = 0
        self._replay_compatibility_fallback_count = 0
        self._replay_consumed_calls: list[tuple[int, str, str]] = []
        self._live_dispatch_count = 0
        if self.replay:
            source = str(config.get("replay_source_path", "")).strip()
            if not source:
                raise ProviderConfigurationError(["replay_source_path is required for exact replay"])
            if os.name == "nt":
                # Windows CPython 3.11 can retain the recorded source handle
                # after close.  Query a private SQLite backup instead so the
                # source remains immediately rotatable and archivable.
                self._replay_snapshot = ReadOnlyReplaySnapshot(source)
                self.replay_conn = self._replay_snapshot.conn
            else:
                self.replay_conn = open_read_only_connection(
                    source, check_same_thread=False)

    def close(self) -> None:
        """Release replay resources; safe to call repeatedly during teardown."""
        replay_conn = self.replay_conn
        self.replay_conn = None
        replay_snapshot = self._replay_snapshot
        self._replay_snapshot = None
        if replay_snapshot is not None:
            replay_snapshot.close()
        elif replay_conn is not None:
            replay_conn.close()

    @contextmanager
    def replay_admission(self, name: str):
        """Roll back one replay operation when downstream validation pauses."""
        if not self.replay:
            yield
            return
        snapshot = {
            "positions": dict(self._replay_positions),
            "used": set(self._replay_used_call_ids),
            "event_map": dict(self._replay_event_id_map),
            "exact": self._replay_exact_key_count,
            "fallback": self._replay_compatibility_fallback_count,
            "consumed": list(self._replay_consumed_calls),
            "governor": (
                self.governor._last_call_id,
                self.governor._total_spend_usd,
                self.governor._oracle_spend_usd,
                self.governor._report_spend_usd,
                self.governor._world_spend_usd,
                self.governor._level,
            ),
        }
        try:
            with self.store.savepoint(name):
                yield
        except BaseException:
            self._replay_positions.clear()
            self._replay_positions.update(snapshot["positions"])
            self._replay_used_call_ids.clear()
            self._replay_used_call_ids.update(snapshot["used"])
            self._replay_event_id_map.clear()
            self._replay_event_id_map.update(snapshot["event_map"])
            self._replay_exact_key_count = snapshot["exact"]
            self._replay_compatibility_fallback_count = snapshot["fallback"]
            self._replay_consumed_calls[:] = snapshot["consumed"]
            (
                self.governor._last_call_id,
                self.governor._total_spend_usd,
                self.governor._oracle_spend_usd,
                self.governor._report_spend_usd,
                self.governor._world_spend_usd,
                self.governor._level,
            ) = snapshot["governor"]
            raise

    def replay_execution_stats(self) -> dict[str, Any]:
        """Attest what this in-memory replay execution actually consumed.

        The digest deliberately excludes physical call ids and timestamps. It
        covers the same deterministic call contents used by exact replay while
        preserving multiplicity through newline-delimited sorted records.
        """
        if not self.replay or self.replay_conn is None:
            raise RuntimeError("replay execution stats require an open replay source")
        placeholders = ",".join("?" for _ in REPLAY_OPERATIONAL_PURPOSES)
        rows = self.replay_conn.execute(
            "SELECT * FROM llm_calls WHERE COALESCE(purpose,'') NOT IN "
            f"({placeholders}) ORDER BY id",
            tuple(sorted(REPLAY_OPERATIONAL_PURPOSES)),
        ).fetchall()
        expected = [
            (int(row["id"]), _logical_replay_call(row), str(row["purpose"] or ""))
            for row in rows
        ]
        consumed = list(self._replay_consumed_calls)
        expected_ids = {item[0] for item in expected}
        consumed_ids = [item[0] for item in consumed]
        duplicate_consumptions = len(consumed_ids) - len(set(consumed_ids))

        def purpose_counts(items: list[tuple[int, str, str]]) -> dict[str, int]:
            counts: dict[str, int] = {}
            for _call_id, _logical, purpose in items:
                counts[purpose] = counts.get(purpose, 0) + 1
            return dict(sorted(counts.items()))

        oracle_expected = [
            logical for _call_id, logical, purpose in expected
            if purpose in {"oracle_plan", "oracle"}
        ]
        oracle_consumed = [
            logical for _call_id, logical, purpose in consumed
            if purpose in {"oracle_plan", "oracle"}
        ]
        missing = expected_ids - set(consumed_ids)
        unexpected = set(consumed_ids) - expected_ids
        return {
            "schema_version": 1,
            "source_nonoperational_calls": len(expected),
            "consumed_source_calls": len(consumed),
            "source_logical_calls_sha256": _logical_replay_digest(
                [item[1] for item in expected]),
            "consumed_logical_calls_sha256": _logical_replay_digest(
                [item[1] for item in consumed]),
            "source_purpose_counts": purpose_counts(expected),
            "consumed_purpose_counts": purpose_counts(consumed),
            "oracle_source_calls": len(oracle_expected),
            "oracle_consumed_calls": len(oracle_consumed),
            "oracle_source_calls_sha256": _logical_replay_digest(oracle_expected),
            "oracle_consumed_calls_sha256": _logical_replay_digest(oracle_consumed),
            "exact_key_matches": self._replay_exact_key_count,
            "compatibility_fallback_matches": (
                self._replay_compatibility_fallback_count),
            "live_dispatch_count": self._live_dispatch_count,
            "missing_source_calls": len(missing),
            "unexpected_source_calls": len(unexpected),
            "duplicate_source_consumptions": duplicate_consumptions,
            "all_nonoperational_calls_consumed_once": bool(
                not missing and not unexpected and duplicate_consumptions == 0
                and len(expected) == len(consumed)),
            "all_oracle_calls_consumed_once": bool(
                len(oracle_expected) == len(oracle_consumed)
                and _logical_replay_digest(oracle_expected)
                == _logical_replay_digest(oracle_consumed)),
        }

    @property
    def scripted(self):
        return self.adapters["scripted"]

    # ── routing ──────────────────────────────────────────────────────────────
    def route(self, role: str, purpose: str) -> tuple[str, str]:
        if self.tier_routes:
            plan = self.route_plan(LLMRequest(role=role, purpose=purpose))
            return plan.targets[0].provider, plan.targets[0].model
        r = self.routes.get(role) or self.routes.get(purpose) or self.default_route
        return r.get("provider", "scripted"), r.get("model", "scripted")

    def route_plan(self, req: LLMRequest) -> RoutePlan:
        cohort = self._citizen_model_cohort(req.agent_id)
        if cohort is not None:
            assigned = (
                self._assigned_model_tier(req) if self.tier_routes else "legacy")
            targets = self._live_route_targets(
                cohort, "citizen model cohorts")
            return RoutePlan(
                assigned_tier=assigned,
                effective_tier=assigned,
                reason=(
                    f"deterministic citizen model cohort {cohort['name']}; "
                    f"agent compute plan {assigned}"),
                targets=tuple(targets[:2]),
                tiered=True,
            )
        if not self.tier_routes:
            r = self.routes.get(req.role) or self.routes.get(req.purpose) or self.default_route
            return RoutePlan(
                assigned_tier="legacy", effective_tier="legacy",
                reason="legacy role/purpose route",
                targets=(self._route_target(r, 0),), tiered=False)

        assigned = self._assigned_model_tier(req)
        effective = assigned
        reason = f"agent compute plan {assigned}"
        if assigned == "premium" and req.purpose in self.background_flash_purposes:
            effective = "flash"
            reason = f"premium agent background purpose {req.purpose} uses flash"
        route_cfg: Any
        if effective == "premium":
            route_cfg = (
                self.premium_routes.get(req.role)
                or self.premium_routes.get(req.purpose)
                or self.tier_routes.get("premium"))
            if req.role in self.premium_routes or req.purpose in self.premium_routes:
                reason += f"; premium specialization for {req.role or req.purpose}"
        else:
            route_cfg = self.tier_routes.get(effective)
        if not isinstance(route_cfg, dict):
            raise ProviderConfigurationError([
                f"no tier route configured for {effective}"])
        targets = self._live_route_targets(route_cfg, "tiered live routes")
        return RoutePlan(
            assigned_tier=assigned, effective_tier=effective,
            reason=reason, targets=tuple(targets[:2]), tiered=True)

    def _live_route_targets(self, route_cfg: dict, label: str) -> list[RouteTarget]:
        targets = [self._route_target(route_cfg.get("primary", route_cfg), 0)]
        fallback_cfg = route_cfg.get("fallback")
        if isinstance(fallback_cfg, dict):
            fallback = self._route_target(fallback_cfg, 1)
            if (fallback.provider, fallback.model) != (
                    targets[0].provider, targets[0].model):
                targets.append(fallback)
        if any(target.provider in {"scripted", "mock"} for target in targets):
            raise ProviderConfigurationError([
                f"{label} cannot use scripted or mock providers"])
        return targets

    def _assigned_model_tier(self, req: LLMRequest) -> str:
        value: object = self.role_tiers.get(req.role, "flash")
        if req.agent_id is not None:
            value = self.store.scalar(
                "SELECT model_tier FROM agents WHERE id=?", (req.agent_id,),
                default=value)
        tier = str(value or "local").lower().strip()
        if tier == "strong":
            tier = "premium"
        elif tier == "citizen":
            tier = "local"
        return tier if tier in {"local", "flash", "premium"} else "local"

    def _citizen_model_assignment_map(self) -> dict[int, dict]:
        if self._citizen_model_assignments is not None:
            return self._citizen_model_assignments
        required = sum(int(cohort["count"])
                       for cohort in self.citizen_model_cohorts)
        if required <= 0:
            self._citizen_model_assignments = {}
            return self._citizen_model_assignments
        rows = self.store.query(
            "SELECT id FROM agents WHERE kind='citizen' ORDER BY id LIMIT ?",
            (required,),
        )
        if len(rows) < required:
            # Gateway construction precedes genesis. Do not freeze a partial
            # assignment if a route is inspected before all citizens exist.
            return {}
        assignments: dict[int, dict] = {}
        offset = 0
        for cohort in self.citizen_model_cohorts:
            count = int(cohort["count"])
            for row in rows[offset:offset + count]:
                assignments[int(row["id"])] = cohort
            offset += count
        self._citizen_model_assignments = assignments
        return assignments

    def _citizen_model_cohort(self, agent_id: int | None) -> dict | None:
        if agent_id is None or not self.citizen_model_cohorts:
            return None
        return self._citizen_model_assignment_map().get(int(agent_id))

    def citizen_model_assignment_status(self) -> list[dict[str, Any]]:
        assignments = self._citizen_model_assignment_map()
        status: list[dict[str, Any]] = []
        for cohort in self.citizen_model_cohorts:
            name = str(cohort["name"])
            primary = self._route_target(cohort["primary"], 0)
            agent_ids = sorted(
                agent_id for agent_id, assigned in assignments.items()
                if str(assigned["name"]) == name)
            status.append({
                "name": name,
                "configured_count": int(cohort["count"]),
                "assigned_count": len(agent_ids),
                "agent_ids": agent_ids,
                "provider": primary.provider,
                "model": primary.model,
            })
        return status

    def _route_target(self, route: Any, route_index: int) -> RouteTarget:
        if not isinstance(route, dict):
            raise ProviderConfigurationError(["route target must be a mapping"])
        provider = str(route.get("provider", "")).strip()
        model = str(route.get("model", "")).strip()
        if not provider or not model:
            raise ProviderConfigurationError(["route target requires provider and model"])
        provider_timeout = self.provider_configs.get(provider, {}).get("timeout_s", 90.0)
        timeout_s = max(1.0, float(route.get("timeout_s", provider_timeout)))
        return RouteTarget(provider, model, timeout_s, int(route_index))

    @staticmethod
    def _request_priority(req: LLMRequest) -> int:
        strategic_roles = {
            "central_banker", "credit_officer", "vc_partner", "exchange", "lawyer",
            "regulator", "competition_regulator", "labor_regulator", "executive",
            "oracle",
        }
        if req.role in strategic_roles or req.purpose in {
                "oracle", "oracle_plan", "central_banker", "credit_officer"}:
            return 0
        if req.purpose in {"conversation", "memory", "newsroom", "report_narrative"}:
            return 3
        return 1

    def _all_configured_targets(self) -> tuple[RouteTarget, ...]:
        route_configs: list[Any] = [self.default_route, *self.routes.values()]
        for group in (self.tier_routes, self.premium_routes):
            for route in group.values():
                if isinstance(route, dict) and (
                        "primary" in route or "fallback" in route):
                    if route.get("primary") is not None:
                        route_configs.append(route["primary"])
                    if route.get("fallback") is not None:
                        route_configs.append(route["fallback"])
                else:
                    route_configs.append(route)
        for cohort in self.citizen_model_cohorts:
            route_configs.append(cohort["primary"])
            if cohort.get("fallback") is not None:
                route_configs.append(cohort["fallback"])
        targets: list[RouteTarget] = []
        seen: set[tuple[str, str]] = set()
        for route in route_configs:
            if not isinstance(route, dict):
                continue
            target = self._route_target(route, 0)
            pair = (target.provider, target.model)
            if pair not in seen:
                seen.add(pair)
                targets.append(target)
        return tuple(targets)

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
            "detail": sanitize_provider_error(exc.detail),
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
        for target in self._all_configured_targets():
            provider = target.provider
            model = target.model
            adapter = self.adapters[provider]
            try:
                health = sanitize_provider_raw(
                    safe_fields(await adapter.healthcheck(model)))
                smoke_result = await asyncio.wait_for(
                    adapter.complete(
                        model,
                        [{"role": "system", "content": (
                            "Return only valid JSON with keys ok and provider.")},
                         {"role": "user", "content": (
                            "Return {\"ok\":true,\"provider\":\"live\"} now.")}],
                        purpose="preflight", context={"preflight": True},
                        max_tokens=256, temperature=0.0,
                        cache_key=f"{self.run_id}:preflight:{provider}"),
                    timeout=target.timeout_s,
                )
                smoke_text = _sanitize_json_text(
                    smoke_result.text, preserve_root_reasoning=True)
                smoke_json, smoke_ok = self._parse(smoke_text)
                contract_ok = bool(smoke_ok and isinstance(smoke_json, dict))
                result = {
                    "provider": provider, **health,
                    "ok": bool(health.get("ok", False) and contract_ok),
                    "contract_ok": contract_ok,
                    "smoke_in_tokens": int(smoke_result.in_tokens),
                    "smoke_out_tokens": int(smoke_result.out_tokens),
                }
                checks.append(result)
                operational_log(logger, logging.INFO, "llm.preflight.provider_completed",
                                run_id=self.run_id, provider=provider, model=model,
                                ok=result.get("ok", False))
            except Exception as exc:
                provider_error = sanitize_provider_error(exc)
                checks.append({"provider": provider, "model": model, "ok": False,
                               "live": True, "error": provider_error})
                operational_log(logger, logging.ERROR, "llm.preflight.provider_failed",
                                run_id=self.run_id, provider=provider, model=model,
                                error_type=type(exc).__name__, error=provider_error)
        live_ready = all(c["ok"] for c in checks)
        operational_log(logger, logging.INFO if live_ready else logging.ERROR,
                        "llm.preflight.completed", run_id=self.run_id,
                        live_requested=True, ready=report["ready"],
                        live_checked=True, live_ready=live_ready,
                        providers_checked=len(checks))
        return {**report, "live_checked": True,
                "live_ready": live_ready, "checks": checks}

    # ── main entry ───────────────────────────────────────────────────────────
    async def complete(
            self, req: LLMRequest, *, schema_hint: str = "",
            parsed_transform: Optional[Callable[[Any], Any]] = None,
            parsed_validator: Optional[Callable[[Any], Optional[str]]] = None,
            ) -> LLMResponse:
        plan = self.route_plan(req)
        selected_target = plan.targets[0]
        provider, model = selected_target.provider, selected_target.model
        adapter = self.adapters.get(provider)
        if adapter is None:
            operational_log(logger, logging.ERROR, "llm.route.unavailable",
                            run_id=self.run_id, provider=provider, model=model,
                            role=req.role, purpose=req.purpose, tick=req.tick)
            raise ProviderConfigurationError([f"routed provider '{provider}' is unavailable"])
        cache_key = self._cache_key(req, provider, model)
        provider_cache_key = f"{self.run_id}:{req.role}:{req.purpose}:{req.agent_id or 'shared'}"
        attempt_ids: list[int] = []
        logical_deadline = time.monotonic() + self.logical_deadline_s
        operational_log(logger, logging.DEBUG, "llm.request.started",
                        run_id=self.run_id, provider=provider, model=model,
                        role=req.role, purpose=req.purpose, agent_id=req.agent_id,
                        tick=req.tick, replay=self.replay,
                        assigned_tier=plan.assigned_tier,
                        effective_tier=plan.effective_tier,
                        route_reason=plan.reason)

        if self.replay:
            replayed = self._replay_lookup(
                cache_key, req, schema_hint, parsed_transform, parsed_validator)
            if replayed is not None:
                response, source_row = replayed
                response.call_id = self._log_replay_call(req, cache_key, source_row)
                operational_log(logger, logging.DEBUG, "llm.replay.hit",
                                run_id=self.run_id, model=model, role=req.role,
                                purpose=req.purpose, agent_id=req.agent_id, tick=req.tick)
                if plan.tiered and not response.ok:
                    raise ProviderUnavailable(
                        "replay", response.model, req.purpose,
                        "recorded live response failed its JSON contract", attempts=0)
                return response
            operational_log(logger, logging.ERROR, "llm.replay.missing",
                            run_id=self.run_id, model=model, role=req.role,
                            purpose=req.purpose, agent_id=req.agent_id, tick=req.tick)
            raise ProviderUnavailable(
                "replay", model, req.purpose,
                f"stored response missing for cache key {cache_key}", attempts=0)

        resumed = None
        for durable_target in plan.targets:
            durable_key = self._cache_key(
                req, durable_target.provider, durable_target.model)
            resumed = self._durable_lookup(
                durable_key, schema_hint, parsed_validator)
            if resumed is not None:
                break
        if resumed is not None:
            if parsed_transform is not None:
                resumed.parsed = parsed_transform(resumed.parsed)
            operational_log(
                logger, logging.DEBUG, "llm.resume.hit",
                run_id=self.run_id, provider=resumed.provider, model=resumed.model,
                role=req.role, purpose=req.purpose, agent_id=req.agent_id,
                tick=req.tick)
            return resumed

        # Budget pre-check uses the most expensive permitted live target.
        pricing = self.pricing.get(model, {"in": 0, "out": 0, "cache": 0})
        est_cost = max(
            self._estimate_cost(
                req, self.pricing.get(
                    target.model, {"in": 0, "out": 0, "cache": 0}))
            for target in plan.targets)
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
            if plan.tiered:
                result, attempts, selected_target, attempt_ids = await self._call_route_plan(
                    plan, req, req.messages(), req.temperature,
                    provider_cache_key, logical_deadline)
                provider, model = selected_target.provider, selected_target.model
                adapter = self.adapters[provider]
                cache_key = self._cache_key(req, provider, model)
                pricing = self.pricing.get(
                    model, {"in": 0, "out": 0, "cache": 0})
            else:
                result, attempts = await self._call_adapter(
                    provider, adapter, model, req, req.messages(), req.temperature,
                    provider_cache_key)
        except GatewayInterrupted:
            raise
        except _RoutePlanExhausted as exhausted:
            attempt_ids = exhausted.attempt_ids
            exc = exhausted.error
            latency_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
            failure = ProviderUnavailable(
                provider, model, req.purpose, f"{type(exc).__name__}: {exc}",
                latency_ms=latency_ms, attempts=max(1, len(attempt_ids)))
            if req.purpose != "report_narrative":
                self.store.log_event(req.tick, "provider_failure", failure.as_dict(),
                                     phase="LLM", importance=5.0)
            operational_log(logger, logging.ERROR, "llm.request.failed",
                            run_id=self.run_id, provider=provider, model=model,
                            role=req.role, purpose=req.purpose, agent_id=req.agent_id,
                            tick=req.tick, latency_ms=latency_ms,
                            attempts=failure.attempts, error_type=type(exc).__name__,
                            error=failure.message)
            raise failure from None
        except Exception as exc:
            latency_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
            failure = ProviderUnavailable(
                provider, model, req.purpose, f"{type(exc).__name__}: {exc}",
                latency_ms=latency_ms, attempts=self.provider_retries + 1)
            # Report narration is generated after the simulated tick has
            # closed. Its provider outage is operational and must not mutate
            # deterministic world state that an offline replay rebuilds.
            if req.purpose != "report_narrative":
                self.store.log_event(req.tick, "provider_failure", failure.as_dict(),
                                     phase="LLM", importance=5.0)
            operational_log(logger, logging.ERROR, "llm.request.failed",
                            run_id=self.run_id, provider=provider, model=model,
                            role=req.role, purpose=req.purpose, agent_id=req.agent_id,
                            tick=req.tick, latency_ms=latency_ms,
                            attempts=failure.attempts, error_type=type(exc).__name__,
                            error=failure.message)
            raise failure from None
        latency_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        cost_override: float | None = None

        result.text = _sanitize_json_text(
            result.text, preserve_root_reasoning=True)
        parsed, ok = self._parse(result.text)
        if ok and schema_hint:
            ok = self._matches_schema(parsed, schema_hint)
        validation_error = (
            self._parsed_validation_error(parsed, parsed_validator) if ok else None)
        if validation_error is not None:
            ok = False
        if not ok and plan.tiered and attempt_ids:
            self._mark_attempt_invalid(
                attempt_ids[-1], validation_error or "invalid JSON contract")
        if not ok and provider not in ("scripted", "mock"):
            # One repair retry with the parse/contract error appended
            # (TECH-SPEC §8 failure policy).
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
                      + (f" Required shape: {schema_hint}" if schema_hint else "")
                      + (f" Contract error: {validation_error}"
                         if validation_error else "")),
                context=req.context, agent_id=req.agent_id, tick=req.tick,
                max_tokens=req.max_tokens, temperature=0.2)

            def persist_initial_completion(reason: str) -> None:
                """Meter the billable first completion even if repair cannot finish."""
                partial = AdapterResult(
                    text=(initial_result.text if plan.tiered else _canonical_noop_text()),
                    in_tokens=initial_result.in_tokens,
                    out_tokens=initial_result.out_tokens,
                    cached_in_tokens=initial_result.cached_in_tokens,
                    raw={
                        "provider_calls": 1,
                        "initial": initial_result.raw,
                        "repair_failed": reason[:120],
                    },
                )
                cached, cost = self._price(
                    model, partial.in_tokens, partial.out_tokens,
                    partial.cached_in_tokens, pricing)
                partial_latency_ms = int(
                    (datetime.now(timezone.utc) - started).total_seconds() * 1000)
                partial_call_id = self._log_call(
                    req, provider, model, cache_key, partial, cost, cached,
                    partial_latency_ms)
                self._link_attempts(partial_call_id, attempt_ids)

            try:
                if plan.tiered:
                    (repaired_result, repair_attempts, _repair_target,
                     repair_attempt_ids) = await self._call_route_plan(
                        plan, repair, repair.messages(), 0.2,
                        provider_cache_key, logical_deadline,
                        targets=(selected_target,))
                    attempt_ids.extend(repair_attempt_ids)
                else:
                    repaired_result, repair_attempts = await self._call_adapter(
                        provider, adapter, model, repair, repair.messages(), 0.2,
                        provider_cache_key)
                repaired_result.text = _sanitize_json_text(
                    repaired_result.text, preserve_root_reasoning=True)
                attempts += repair_attempts
            except GatewayInterrupted:
                persist_initial_completion("GatewayInterrupted")
                raise
            except asyncio.CancelledError:
                persist_initial_completion("CancelledError")
                raise
            except Exception as exc:
                if isinstance(exc, _RoutePlanExhausted):
                    attempt_ids.extend(exc.attempt_ids)
                    exc = exc.error
                persist_initial_completion(type(exc).__name__)
                latency_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
                failure = ProviderUnavailable(
                    provider, model, req.purpose, f"repair {type(exc).__name__}: {exc}",
                    latency_ms=latency_ms, attempts=attempts + self.provider_retries + 1)
                if req.purpose != "report_narrative":
                    self.store.log_event(req.tick, "provider_failure", failure.as_dict(),
                                         phase="LLM", importance=5.0)
                operational_log(logger, logging.ERROR, "llm.repair.failed",
                                run_id=self.run_id, provider=provider, model=model,
                                role=req.role, purpose=req.purpose, agent_id=req.agent_id,
                                tick=req.tick, latency_ms=latency_ms,
                                attempts=failure.attempts, error_type=type(exc).__name__,
                                error=failure.message)
                raise failure from None
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
            validation_error = (
                self._parsed_validation_error(parsed, parsed_validator)
                if ok else None)
            if validation_error is not None:
                ok = False
            if not ok and plan.tiered and attempt_ids:
                self._mark_attempt_invalid(
                    attempt_ids[-1], validation_error or "invalid JSON contract")
            operational_log(logger, logging.INFO, "llm.repair.completed",
                            run_id=self.run_id, provider=provider, model=model,
                            role=req.role, purpose=req.purpose, agent_id=req.agent_id,
                            tick=req.tick, valid=ok)
        if (not ok and plan.tiered and selected_target.route_index == 0
                and len(plan.targets) > 1):
            # A syntactically reachable provider can still be unusable for the
            # logical request when both its first response and repair violate
            # the JSON contract. Treat that as a route failure and use the
            # configured fallback. All billable completions remain one durable
            # logical call so replay and cost accounting preserve the full
            # primary -> repair -> fallback chain.
            failed_result = result
            failed_provider, failed_model = provider, model
            failed_pricing = pricing
            failed_cached, failed_cost = self._price(
                failed_model, failed_result.in_tokens, failed_result.out_tokens,
                failed_result.cached_in_tokens, failed_pricing)
            fallback_target = plan.targets[1]
            operational_log(
                logger, logging.WARNING, "llm.contract.fallback_started",
                run_id=self.run_id, provider=failed_provider, model=failed_model,
                fallback_provider=fallback_target.provider,
                fallback_model=fallback_target.model, role=req.role,
                purpose=req.purpose, agent_id=req.agent_id, tick=req.tick)
            try:
                (fallback_result, fallback_attempts, selected_target,
                 fallback_attempt_ids) = await self._call_route_plan(
                    plan, req, req.messages(), req.temperature,
                    provider_cache_key, logical_deadline,
                    targets=(fallback_target,))
                attempt_ids.extend(fallback_attempt_ids)
                attempts += fallback_attempts
            except GatewayInterrupted:
                raise
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if isinstance(exc, _RoutePlanExhausted):
                    attempt_ids.extend(exc.attempt_ids)
                    exc = exc.error
                latency_ms = int(
                    (datetime.now(timezone.utc) - started).total_seconds() * 1000)
                call_id = self._log_call(
                    req, failed_provider, failed_model,
                    self._cache_key(req, failed_provider, failed_model),
                    failed_result, failed_cost, failed_cached, latency_ms)
                self._link_attempts(call_id, attempt_ids)
                failure = ProviderUnavailable(
                    fallback_target.provider, fallback_target.model, req.purpose,
                    f"contract fallback {type(exc).__name__}: {exc}",
                    latency_ms=latency_ms, attempts=max(1, len(attempt_ids)))
                if req.purpose != "report_narrative":
                    self.store.log_event(
                        req.tick, "provider_failure", failure.as_dict(),
                        phase="LLM", importance=5.0)
                operational_log(
                    logger, logging.ERROR, "llm.contract.fallback_failed",
                    run_id=self.run_id, provider=fallback_target.provider,
                    model=fallback_target.model, role=req.role,
                    purpose=req.purpose, agent_id=req.agent_id, tick=req.tick,
                    latency_ms=latency_ms, attempts=failure.attempts,
                    error_type=type(exc).__name__, error=failure.message)
                raise failure from None

            provider, model = selected_target.provider, selected_target.model
            adapter = self.adapters[provider]
            cache_key = self._cache_key(req, provider, model)
            pricing = self.pricing.get(
                model, {"in": 0, "out": 0, "cache": 0})
            fallback_result.text = _sanitize_json_text(
                fallback_result.text, preserve_root_reasoning=True)
            parsed, ok = self._parse(fallback_result.text)
            if ok and schema_hint:
                ok = self._matches_schema(parsed, schema_hint)
            validation_error = (
                self._parsed_validation_error(parsed, parsed_validator)
                if ok else None)
            if validation_error is not None:
                ok = False
            if not ok and attempt_ids:
                self._mark_attempt_invalid(
                    attempt_ids[-1],
                    validation_error or "invalid JSON contract")

            if not ok and provider not in ("scripted", "mock"):
                operational_log(
                    logger, logging.WARNING, "llm.repair.started",
                    run_id=self.run_id, provider=provider, model=model,
                    role=req.role, purpose=req.purpose, agent_id=req.agent_id,
                    tick=req.tick)
                fallback_initial = fallback_result
                fallback_repair = LLMRequest(
                    role=req.role, purpose=req.purpose, system=req.system,
                    user=(
                        req.user
                        + "\n\nYour previous reply did not match the required "
                          "JSON contract. Reply ONLY with the JSON object."
                        + (f" Required shape: {schema_hint}"
                           if schema_hint else "")
                        + (f" Contract error: {validation_error}"
                           if validation_error else "")),
                    context=req.context, agent_id=req.agent_id, tick=req.tick,
                    max_tokens=req.max_tokens, temperature=0.2)
                try:
                    (repaired_fallback, repair_attempts, _repair_target,
                     repair_attempt_ids) = await self._call_route_plan(
                        plan, fallback_repair, fallback_repair.messages(), 0.2,
                        provider_cache_key, logical_deadline,
                        targets=(selected_target,))
                    attempt_ids.extend(repair_attempt_ids)
                    attempts += repair_attempts
                except GatewayInterrupted:
                    raise
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if isinstance(exc, _RoutePlanExhausted):
                        attempt_ids.extend(exc.attempt_ids)
                        exc = exc.error
                    fallback_result = AdapterResult(
                        text=fallback_initial.text,
                        in_tokens=fallback_initial.in_tokens,
                        out_tokens=fallback_initial.out_tokens,
                        cached_in_tokens=fallback_initial.cached_in_tokens,
                        raw={
                            "provider_calls": 1,
                            "initial": fallback_initial.raw,
                            "repair_failed": type(exc).__name__,
                        },
                    )
                    fallback_cached, fallback_cost = self._price(
                        model, fallback_result.in_tokens,
                        fallback_result.out_tokens,
                        fallback_result.cached_in_tokens, pricing)
                    combined = AdapterResult(
                        text=fallback_result.text,
                        in_tokens=(
                            failed_result.in_tokens + fallback_result.in_tokens),
                        out_tokens=(
                            failed_result.out_tokens + fallback_result.out_tokens),
                        cached_in_tokens=(
                            failed_result.cached_in_tokens
                            + fallback_result.cached_in_tokens),
                        raw={
                            "provider_calls": 3,
                            "contract_fallback": {
                                "failed": {
                                    "provider": failed_provider,
                                    "model": failed_model,
                                    "raw": failed_result.raw,
                                },
                                "final": {
                                    "provider": provider,
                                    "model": model,
                                    "raw": fallback_result.raw,
                                },
                            },
                        },
                    )
                    latency_ms = int(
                        (datetime.now(timezone.utc) - started).total_seconds()
                        * 1000)
                    call_id = self._log_call(
                        req, provider, model, cache_key, combined,
                        round(failed_cost + fallback_cost, 8),
                        failed_cached or fallback_cached, latency_ms)
                    self._link_attempts(call_id, attempt_ids)
                    failure = ProviderUnavailable(
                        provider, model, req.purpose,
                        f"fallback repair {type(exc).__name__}: {exc}",
                        latency_ms=latency_ms,
                        attempts=max(1, len(attempt_ids)))
                    if req.purpose != "report_narrative":
                        self.store.log_event(
                            req.tick, "provider_failure", failure.as_dict(),
                            phase="LLM", importance=5.0)
                    raise failure from None
                repaired_fallback.text = _sanitize_json_text(
                    repaired_fallback.text, preserve_root_reasoning=True)
                fallback_result = AdapterResult(
                    text=repaired_fallback.text,
                    in_tokens=(
                        fallback_initial.in_tokens + repaired_fallback.in_tokens),
                    out_tokens=(
                        fallback_initial.out_tokens
                        + repaired_fallback.out_tokens),
                    cached_in_tokens=(
                        fallback_initial.cached_in_tokens
                        + repaired_fallback.cached_in_tokens),
                    raw={"provider_calls": 2, "repair": {
                        "initial": fallback_initial.raw,
                        "final": repaired_fallback.raw}},
                )
                parsed, ok = self._parse(fallback_result.text)
                if ok and schema_hint:
                    ok = self._matches_schema(parsed, schema_hint)
                validation_error = (
                    self._parsed_validation_error(parsed, parsed_validator)
                    if ok else None)
                if validation_error is not None:
                    ok = False
                if not ok and attempt_ids:
                    self._mark_attempt_invalid(
                        attempt_ids[-1],
                        validation_error or "invalid JSON contract")
                operational_log(
                    logger, logging.INFO, "llm.repair.completed",
                    run_id=self.run_id, provider=provider, model=model,
                    role=req.role, purpose=req.purpose,
                    agent_id=req.agent_id, tick=req.tick, valid=ok)

            fallback_cached, fallback_cost = self._price(
                model, fallback_result.in_tokens, fallback_result.out_tokens,
                fallback_result.cached_in_tokens, pricing)
            failed_calls = int(
                failed_result.raw.get("provider_calls", 1)
                if isinstance(failed_result.raw, dict) else 1)
            fallback_calls = int(
                fallback_result.raw.get("provider_calls", 1)
                if isinstance(fallback_result.raw, dict) else 1)
            result = AdapterResult(
                text=fallback_result.text,
                in_tokens=failed_result.in_tokens + fallback_result.in_tokens,
                out_tokens=failed_result.out_tokens + fallback_result.out_tokens,
                cached_in_tokens=(
                    failed_result.cached_in_tokens
                    + fallback_result.cached_in_tokens),
                raw={
                    "provider_calls": failed_calls + fallback_calls,
                    "contract_fallback": {
                        "failed": {
                            "provider": failed_provider,
                            "model": failed_model,
                            "raw": failed_result.raw,
                        },
                        "final": {
                            "provider": provider,
                            "model": model,
                            "raw": fallback_result.raw,
                        },
                    },
                },
            )
            cost_override = round(failed_cost + fallback_cost, 8)
            latency_ms = int(
                (datetime.now(timezone.utc) - started).total_seconds() * 1000)
            operational_log(
                logger, logging.INFO, "llm.contract.fallback_completed",
                run_id=self.run_id, provider=provider, model=model,
                role=req.role, purpose=req.purpose, agent_id=req.agent_id,
                tick=req.tick, valid=ok)
        if not ok:
            if plan.tiered:
                if cost_override is None:
                    cached, cost = self._price(
                        model, result.in_tokens, result.out_tokens,
                        result.cached_in_tokens, pricing)
                else:
                    cached = result.cached_in_tokens > 0
                    cost = cost_override
                call_id = self._log_call(
                    req, provider, model, cache_key, result, cost, cached, latency_ms)
                self._link_attempts(call_id, attempt_ids)
                failure = ProviderUnavailable(
                    provider, model, req.purpose,
                    validation_error or "live provider returned invalid JSON after repair",
                    latency_ms=latency_ms, attempts=max(1, len(attempt_ids)))
                if req.purpose != "report_narrative":
                    self.store.log_event(req.tick, "provider_failure", failure.as_dict(),
                                         phase="LLM", importance=5.0)
                raise failure
            parsed = {"reasoning": "unparseable output; no-op", "actions": [{"type": "do_nothing"}]}
            result.text = _canonical_noop_text()
            operational_log(logger, logging.WARNING, "llm.contract.invalid",
                            run_id=self.run_id, provider=provider, model=model,
                            role=req.role, purpose=req.purpose, agent_id=req.agent_id,
                            tick=req.tick)

        if cost_override is None:
            cached, cost = self._price(
                model, result.in_tokens, result.out_tokens,
                result.cached_in_tokens, pricing)
        else:
            cached = result.cached_in_tokens > 0
            cost = cost_override
        call_id = self._log_call(
            req, provider, model, cache_key, result, cost, cached, latency_ms)
        self._link_attempts(call_id, attempt_ids)
        if parsed_transform is not None:
            parsed = parsed_transform(parsed)
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

    async def _call_route_plan(
            self, plan: RoutePlan, req: LLMRequest, messages: list[dict],
            temperature: float, provider_cache_key: str, deadline: float,
            *, targets: tuple[RouteTarget, ...] | None = None):
        attempt_ids: list[int] = []
        last_error: BaseException | None = None
        selected_targets = plan.targets if targets is None else targets
        for target_index, target in enumerate(selected_targets):
            now = time.monotonic()
            if now >= deadline:
                last_error = asyncio.TimeoutError(
                    f"logical call exceeded {self.logical_deadline_s:.0f}s deadline")
                break
            # A congested primary must not consume the fallback's entire
            # logical-call budget while waiting for a provider lane.  Reserve
            # each later target's configured timeout and bound this attempt to
            # the remaining primary window.  Single-target plans retain the
            # existing full-deadline behavior.
            later_targets = selected_targets[target_index + 1:]
            reserved_fallback_s = sum(
                max(0.0, float(later.timeout_s)) for later in later_targets)
            target_deadline = (
                max(now, deadline - reserved_fallback_s)
                if later_targets else deadline)
            state = self._rate_limits.get(target.provider)
            if state and float(state["retry_at_epoch"]) > time.time():
                error = RuntimeError(
                    f"provider {target.provider} is in rate-limit cooldown")
                attempt_id = self._insert_attempt(
                    req, plan, target, outcome="rate_limited",
                    queue_wait_ms=0.0, provider_latency_ms=0.0,
                    active_at_start=self.provider_gates[target.provider].active,
                    queued_at_start=self.provider_gates[target.provider].queued,
                    global_active_at_start=self._live_in_flight,
                    global_queued_at_start=self._global_queue_depth(),
                    error=error, rate_limited=True)
                if attempt_id is not None:
                    attempt_ids.append(attempt_id)
                last_error = error
                continue
            retry_count = 0
            while True:
                try:
                    result, attempt_id = await self._call_live_target(
                        plan, target, req, messages, temperature,
                        provider_cache_key, target_deadline)
                    if attempt_id is not None:
                        attempt_ids.append(attempt_id)
                    return result, len(attempt_ids), target, attempt_ids
                except _RouteAttemptFailed as failure:
                    if failure.attempt_id is not None:
                        attempt_ids.append(failure.attempt_id)
                    last_error = failure.error
                    if isinstance(last_error, GatewayInterrupted):
                        raise last_error from None
                    retryable_failure = (
                        isinstance(last_error, asyncio.TimeoutError)
                        or (
                            isinstance(last_error, AdapterHTTPError)
                            and not last_error.rate_limited
                            and (
                                last_error.status_code == 408
                                or 500 <= last_error.status_code < 600
                            )
                        )
                    )
                    if (
                        retryable_failure
                        and retry_count < self.provider_retries
                        and time.monotonic() < target_deadline
                    ):
                        retry_count += 1
                        operational_log(
                            logger, logging.WARNING, "llm.request.retry",
                            run_id=self.run_id, provider=target.provider,
                            model=target.model, role=req.role,
                            purpose=req.purpose, agent_id=req.agent_id,
                            tick=req.tick, attempt=retry_count,
                            next_attempt=retry_count + 1,
                            error_type=type(last_error).__name__,
                            error=sanitize_provider_error(last_error))
                        retry_delay = min(
                            0.25 * (2 ** (retry_count - 1)), 2.0,
                            max(0.0, target_deadline - time.monotonic()))
                        if retry_delay > 0:
                            try:
                                await asyncio.wait_for(
                                    self._interrupt_event.wait(),
                                    timeout=retry_delay,
                                )
                            except asyncio.TimeoutError:
                                pass
                            else:
                                raise GatewayInterrupted(
                                    "operator interrupted "
                                    f"{target.provider} retry")
                        continue
                    operational_log(
                        logger, logging.WARNING, "llm.route.attempt_failed",
                        run_id=self.run_id, provider=target.provider,
                        model=target.model, role=req.role,
                        purpose=req.purpose, agent_id=req.agent_id,
                        tick=req.tick, route_index=target.route_index,
                        fallback_next=(
                            target.route_index == 0
                            and len(selected_targets) > 1),
                        error_type=type(last_error).__name__,
                        error=sanitize_provider_error(last_error))
                    break
        if last_error is None:
            last_error = RuntimeError("route plan contained no live targets")
        raise _RoutePlanExhausted(last_error, attempt_ids)

    async def _call_live_target(
            self, plan: RoutePlan, target: RouteTarget, req: LLMRequest,
            messages: list[dict], temperature: float, provider_cache_key: str,
            deadline: float):
        adapter = self.adapters.get(target.provider)
        if adapter is None:
            raise _RouteAttemptFailed(
                ProviderConfigurationError([
                    f"routed provider '{target.provider}' is unavailable"]), None)
        gate = self.provider_gates[target.provider]
        priority = self._request_priority(req)
        wait_started = time.perf_counter()
        queue_wait_ms = 0.0
        provider_latency_ms = 0.0
        active_at_start = gate.active
        queued_at_start = gate.queued
        global_active_at_start = self._live_in_flight
        global_queued_at_start = self._global_queue_depth()
        gate_acquired = False
        global_acquired = False
        provider_started: float | None = None
        outcome = "provider_error"
        failure: BaseException | None = None
        rate_limited = False
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise asyncio.TimeoutError(
                    f"logical call exceeded {self.logical_deadline_s:.0f}s deadline")
            provider_wait_ms, active_at_start, queued_at_start = await asyncio.wait_for(
                gate.acquire(priority), timeout=remaining)
            gate_acquired = True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise asyncio.TimeoutError(
                    f"logical call exceeded {self.logical_deadline_s:.0f}s deadline")
            global_queued_at_start = self._global_queue_depth()
            global_wait_ms, global_active_at_start, _global_lane_queued = (
                await asyncio.wait_for(
                    self.global_gate.acquire(priority), timeout=remaining))
            global_acquired = True
            queue_wait_ms = provider_wait_ms + global_wait_ms
            if self._interrupt_event.is_set():
                raise GatewayInterrupted(
                    f"operator interrupted {target.provider} request")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise asyncio.TimeoutError(
                    f"logical call exceeded {self.logical_deadline_s:.0f}s deadline")
            timeout_s = min(target.timeout_s, remaining)
            active_task = asyncio.current_task()
            if active_task is not None:
                self._active_adapter_tasks.add(active_task)
            provider_started = time.perf_counter()
            self._live_in_flight += 1
            self._peak_live_in_flight = max(
                self._peak_live_in_flight, self._live_in_flight)
            try:
                self._live_dispatch_count += 1
                result = await asyncio.wait_for(
                    adapter.complete(
                        target.model, messages, purpose=req.purpose,
                        context=req.context, max_tokens=req.max_tokens,
                        temperature=temperature, cache_key=provider_cache_key),
                    timeout=timeout_s)
                outcome = "success"
            finally:
                provider_latency_ms = (
                    time.perf_counter() - provider_started) * 1000.0
                self._live_in_flight = max(0, self._live_in_flight - 1)
                if active_task is not None:
                    self._active_adapter_tasks.discard(active_task)
            self._clear_rate_limit(target.provider, target.model, req)
            attempt_id = self._insert_attempt(
                req, plan, target, outcome=outcome,
                queue_wait_ms=queue_wait_ms,
                provider_latency_ms=provider_latency_ms,
                active_at_start=active_at_start,
                queued_at_start=queued_at_start,
                global_active_at_start=global_active_at_start,
                global_queued_at_start=global_queued_at_start)
            return result, attempt_id
        except asyncio.CancelledError as exc:
            failure = (
                GatewayInterrupted(f"operator interrupted {target.provider} request")
                if self._interrupt_event.is_set() else exc)
            outcome = "cancelled"
        except asyncio.TimeoutError as exc:
            failure = exc
            outcome = "timeout"
        except AdapterHTTPError as exc:
            failure = exc
            rate_limited = bool(exc.rate_limited)
            if rate_limited:
                self._record_rate_limit(target.provider, target.model, req, exc)
                outcome = "rate_limited"
            else:
                outcome = "provider_error"
        except GatewayInterrupted as exc:
            failure = exc
            outcome = "cancelled"
        except Exception as exc:
            failure = exc
            outcome = "provider_error"
        finally:
            if provider_started is None and queue_wait_ms <= 0:
                queue_wait_ms = (time.perf_counter() - wait_started) * 1000.0
            if global_acquired:
                await self.global_gate.release()
            if gate_acquired:
                await gate.release()
        attempt_id = self._insert_attempt(
            req, plan, target, outcome=outcome,
            queue_wait_ms=max(0.0, queue_wait_ms),
            provider_latency_ms=max(0.0, provider_latency_ms),
            active_at_start=active_at_start,
            queued_at_start=queued_at_start,
            global_active_at_start=global_active_at_start,
            global_queued_at_start=global_queued_at_start,
            error=failure, rate_limited=rate_limited)
        if isinstance(failure, asyncio.CancelledError):
            raise failure
        raise _RouteAttemptFailed(
            failure or RuntimeError("provider attempt failed"), attempt_id)

    def _insert_attempt(
            self, req: LLMRequest, plan: RoutePlan, target: RouteTarget, *,
            outcome: str, queue_wait_ms: float, provider_latency_ms: float,
            active_at_start: int, queued_at_start: int,
            global_active_at_start: int | None = None,
            global_queued_at_start: int | None = None,
            error: BaseException | None = None, rate_limited: bool = False) -> int | None:
        try:
            gate = self.provider_gates.get(target.provider)
            return self.store.insert(
                "llm_attempts",
                request_key=self._cache_key(req, target.provider, target.model),
                llm_call_id=None, tick=max(0, int(req.tick)), phase="LLM",
                agent_id=req.agent_id, role=req.role, purpose=req.purpose,
                assigned_tier=plan.assigned_tier,
                route_reason=plan.reason, route_index=target.route_index,
                provider=target.provider, model=target.model,
                queue_wait_ms=round(max(0.0, queue_wait_ms), 3),
                provider_latency_ms=round(max(0.0, provider_latency_ms), 3),
                active_at_start=max(0, int(active_at_start)),
                queued_at_start=max(0, int(queued_at_start)),
                global_active_at_start=max(0, int(
                    self._live_in_flight
                    if global_active_at_start is None else global_active_at_start)),
                global_queued_at_start=max(0, int(
                    self._global_queue_depth()
                    if global_queued_at_start is None else global_queued_at_start)),
                provider_peak_observed=max(0, int(gate.peak_active if gate else 0)),
                global_peak_observed=max(0, int(self._peak_live_in_flight)),
                outcome=outcome,
                error_type=type(error).__name__ if error is not None else None,
                error_message=(sanitize_provider_error(error)[:500]
                               if error is not None else None),
                rate_limited=1 if rate_limited else 0,
                fallback_used=1 if target.route_index > 0 else 0,
            )
        except (sqlite3.OperationalError, AttributeError):
            # Compatibility for narrow third-party test stores. Real schema-15
            # run stores always persist this operational record.
            return None

    def _link_attempts(self, call_id: int, attempt_ids: list[int]) -> None:
        if not attempt_ids:
            return
        placeholders = ",".join("?" for _ in attempt_ids)
        self.store.execute(
            f"UPDATE llm_attempts SET llm_call_id=? WHERE id IN ({placeholders})",
            (int(call_id), *[int(value) for value in attempt_ids]))

    def _mark_attempt_invalid(self, attempt_id: int | None, message: str) -> None:
        if attempt_id is None:
            return
        self.store.execute(
            "UPDATE llm_attempts SET outcome='invalid_json',error_type='ContractError',"
            "error_message=? WHERE id=?", (str(message)[:500], int(attempt_id)))

    @staticmethod
    def _percentile(values: list[float], fraction: float) -> float | None:
        if not values:
            return None
        ordered = sorted(float(value) for value in values)
        index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * fraction + 0.999999)))
        return round(ordered[index], 3)

    def _global_queue_depth(self) -> int:
        return max(0, int(self.global_gate.queued)) + sum(
            max(0, int(gate.queued)) for gate in self.provider_gates.values())

    def runtime_status(self) -> dict[str, Any]:
        now = time.time()
        providers = []
        for provider in sorted(self.provider_gates):
            gate = self.provider_gates[provider]
            rows = self.store.query(
                "SELECT queue_wait_ms,provider_latency_ms,outcome,rate_limited,fallback_used,"
                "provider_peak_observed "
                "FROM llm_attempts WHERE provider=? ORDER BY id DESC LIMIT 1000",
                (provider,))
            queue_values = [float(row["queue_wait_ms"]) for row in rows]
            response_values = [float(row["provider_latency_ms"]) for row in rows]
            cooldown = self._rate_limits.get(provider)
            providers.append({
                "provider": provider,
                "capacity": gate.capacity,
                "in_flight": gate.active,
                "queue_depth": gate.queued,
                "peak_in_flight": max(
                    gate.peak_active,
                    max((int(row["provider_peak_observed"]) for row in rows), default=0)),
                "p50_queue_ms": self._percentile(queue_values, 0.50),
                "p95_queue_ms": self._percentile(queue_values, 0.95),
                "p50_response_ms": self._percentile(response_values, 0.50),
                "p95_response_ms": self._percentile(response_values, 0.95),
                "attempts": len(rows),
                "failures": sum(1 for row in rows if row["outcome"] != "success"),
                "rate_limits": sum(int(row["rate_limited"]) for row in rows),
                "fallbacks": sum(int(row["fallback_used"]) for row in rows),
                "cooldown_remaining_s": (
                    round(max(0.0, float(cooldown["retry_at_epoch"]) - now), 3)
                    if cooldown else 0.0),
            })
        global_row = self.store.query_one(
            "SELECT COALESCE(MAX(global_peak_observed),0) peak,"
            "COALESCE(MAX(global_queued_at_start),0) queued FROM llm_attempts")
        tick_rows = self.store.query(
            "SELECT wall_ms FROM runtime_tick_stats ORDER BY tick DESC LIMIT 1000")
        tick_wall_ms = [float(row["wall_ms"]) for row in tick_rows]
        persisted_queue_peak = int(self.store.scalar(
            "SELECT COALESCE(MAX(peak_queue_depth),0) FROM runtime_tick_stats",
            default=0))
        return {
            "live_only": bool(self.config.get("llm", {}).get("live_only", False)),
            "global": {
                "capacity": self.max_in_flight,
                "in_flight": self._live_in_flight,
                "queue_depth": self._global_queue_depth(),
                "peak_in_flight": max(
                    self._peak_live_in_flight, int(global_row["peak"] if global_row else 0)),
                "peak_queue_depth": max(
                    self.global_gate.peak_queued,
                    max((gate.peak_queued for gate in self.provider_gates.values()),
                        default=0),
                    int(global_row["queued"] if global_row else 0),
                    persisted_queue_peak),
                "logical_deadline_s": self.logical_deadline_s,
            },
            "providers": providers,
            "citizen_model_cohorts": self.citizen_model_assignment_status(),
            "simulated_days": {
                "samples": len(tick_wall_ms),
                "p50_wall_ms": self._percentile(tick_wall_ms, 0.50),
                "p95_wall_ms": self._percentile(tick_wall_ms, 0.95),
            },
        }

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
                        self._live_dispatch_count += 1
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
                                error=sanitize_provider_error(last_error))
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

    @staticmethod
    def _parsed_validation_error(
            parsed: Any,
            parsed_validator: Optional[Callable[[Any], Optional[str]]],
            ) -> Optional[str]:
        """Return one bounded semantic-contract error for gateway repair."""
        if parsed_validator is None:
            return None
        error = parsed_validator(parsed)
        if error is None:
            return None
        if not isinstance(error, str) or not error.strip():
            return "response failed semantic contract validation"
        return error.strip()[:500]

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

    @staticmethod
    def _event_payload_identity(payload_json: str | None) -> str:
        try:
            payload = json.loads(payload_json or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            return str(payload_json or "")
        return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False)

    def _local_event_id_for_replay(self, source_event_id: int) -> int:
        """Translate a source SQLite event ID to the same logical local event."""
        source_id = int(source_event_id)
        cached = self._replay_event_id_map.get(source_id)
        if cached is not None:
            return cached
        if self.replay_conn is None:
            return source_id
        source = self.replay_conn.execute(
            "SELECT tick,phase,kind,subject_type,subject_id,importance,payload_json "
            "FROM events WHERE id=?", (source_id,)).fetchone()
        if source is None:
            # Never carry an allocatable positive surrogate through replay. Even
            # if it is currently absent locally, an earlier ordered action could
            # create that row before this action executes and turn a source-
            # invalid reference into a valid local one.
            raise ReplayReferenceError(
                f"recorded replay event reference {source_id} is dangling in source")
        source_candidates = self.replay_conn.execute(
            "SELECT id,importance,payload_json FROM events "
            "WHERE tick=? AND phase IS ? AND kind=? AND subject_type IS ? "
            "AND subject_id IS ? AND id<=? ORDER BY id",
            (int(source["tick"]), source["phase"], source["kind"],
             source["subject_type"], source["subject_id"], source_id)).fetchall()
        local_candidates = self.store.query(
            "SELECT id,importance,payload_json FROM events "
            "WHERE tick=? AND phase IS ? AND kind=? AND subject_type IS ? "
            "AND subject_id IS ? ORDER BY id",
            (int(source["tick"]), source["phase"], source["kind"],
             source["subject_type"], source["subject_id"]))
        source_payload = self._event_payload_identity(source["payload_json"])
        source_matches = [
            int(candidate["id"]) for candidate in source_candidates
            if float(candidate["importance"]) == float(source["importance"])
            and self._event_payload_identity(candidate["payload_json"]) == source_payload
        ]
        local_matches = [
            int(candidate["id"]) for candidate in local_candidates
            if float(candidate["importance"]) == float(source["importance"])
            and self._event_payload_identity(candidate["payload_json"]) == source_payload
        ]
        if source_id not in source_matches:
            raise ReplayReferenceError(
                f"recorded replay event reference {source_id} has no source occurrence")
        occurrence = source_matches.index(source_id)
        if occurrence >= len(local_matches):
            raise ReplayReferenceError(
                f"recorded replay event reference {source_id} full-payload occurrence "
                f"ordinal {occurrence} is unavailable locally "
                f"(source_prefix={len(source_matches)}, local={len(local_matches)})")
        local_id = local_matches[occurrence]
        self._replay_event_id_map[source_id] = local_id
        return local_id

    def _localize_replay_event_references(self, value):
        """Localize event provenance embedded in a recorded model response."""
        if isinstance(value, dict):
            localized = {}
            for key, nested in value.items():
                if key == "request_event_id" and isinstance(nested, int) \
                        and not isinstance(nested, bool):
                    localized[key] = self._local_event_id_for_replay(nested)
                elif key == "evidence_event_ids" and isinstance(nested, list):
                    localized[key] = [
                        self._local_event_id_for_replay(item)
                        if isinstance(item, int) and not isinstance(item, bool) else item
                        for item in nested
                    ]
                else:
                    localized[key] = self._localize_replay_event_references(nested)
            return localized
        if isinstance(value, list):
            return [self._localize_replay_event_references(item) for item in value]
        return value

    def _replay_lookup(
            self, cache_key: str, req: LLMRequest, schema_hint: str = "",
            parsed_transform: Optional[Callable[[Any], Any]] = None,
            parsed_validator: Optional[Callable[[Any], Optional[str]]] = None):
        if self.replay_conn is None:
            return None
        position = self._replay_positions.get(cache_key, 0)
        row = None
        match_mode = "exact_key"
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
                match_mode = "compatibility_fallback"
        if not row:
            return None
        source_call_id = int(row["id"])
        resp = json.loads(row["response_json"]) if row["response_json"] else {}
        parsed, ok = self._parse(resp.get("text", "{}"))
        if ok and schema_hint:
            ok = self._matches_schema(parsed, schema_hint)
        if ok and self._parsed_validation_error(parsed, parsed_validator) is not None:
            ok = False
        if ok:
            parsed = self._localize_replay_event_references(parsed)
        if not ok:
            parsed = {"reasoning": "unparseable output; no-op",
                      "actions": [{"type": "do_nothing"}]}
        if parsed_transform is not None:
            parsed = parsed_transform(parsed)
        response = LLMResponse(
            text=resp.get("text", ""), parsed=parsed, provider=row["provider"],
            model=row["model"], in_tokens=int(row["in_tokens"]),
            out_tokens=int(row["out_tokens"]), cost_usd=float(row["cost_usd"]),
            cached=bool(row["cached"]), ok=ok)
        # Replay consumption is transactional with parsing and provenance
        # localization. A pause must retry the same recorded call rather than
        # skip a corrupt response and silently consume a later duplicate.
        self._replay_positions[cache_key] = position
        self._replay_used_call_ids.add(source_call_id)
        if match_mode == "exact_key":
            self._replay_exact_key_count += 1
        else:
            self._replay_compatibility_fallback_count += 1
            operational_log(
                logger, logging.WARNING, "llm.replay.compatibility_fallback",
                run_id=self.run_id, tick=req.tick, agent_id=req.agent_id,
                role=req.role, purpose=req.purpose,
                source_call_id=source_call_id)
        self._replay_consumed_calls.append((
            source_call_id, _logical_replay_call(row), str(row["purpose"] or "")))
        return response, row

    def _durable_lookup(
            self, cache_key: str, schema_hint: str = "",
            parsed_validator: Optional[Callable[[Any], Optional[str]]] = None,
            ) -> Optional[LLMResponse]:
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
        if ok and self._parsed_validation_error(parsed, parsed_validator) is not None:
            ok = False
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
        # End-of-run narration is an operational artifact: meter it against the
        # hard cap, but do not append simulated-world degradation events after
        # the final tick. Replay intentionally regenerates reports via the
        # deterministic engine fallback without dispatching a provider.
        if req.purpose != "report_narrative":
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

"""Memory pipeline (TECH-SPEC §7, PRD R2).

- Observation capture: engine events touching the agent + conversation lines heard
  become verbatim `memories(kind=observation)`.
- Retrieval: Generative-Agents-style scoring, no embeddings at this scale —
  score = 0.5·recency_decay + 0.3·importance + 0.2·relevance (keyword/entity match).
- Nightly compression + weekly roll-up are orchestrated by the runtime (they need
  the gateway); this module owns the durable reads/writes and the scoring.
- Beliefs are numeric so narrative → behaviour is measurable.
"""
from __future__ import annotations

import json
import math
from typing import Optional

from engine.store import Store, load_json
from .numeric_grounding import model_grounding_active

RECENCY_HALFLIFE = 10.0   # ticks


def retrieval_score(*, recency_decay: float, importance: float,
                    relevance: float) -> float:
    """Return the TECH-SPEC's authoritative additive retrieval score."""
    return 0.5 * recency_decay + 0.3 * importance + 0.2 * relevance


class Memory:
    def __init__(self, store: Store, config: Optional[dict] = None):
        self.store = store
        self.config = config or {}
        beliefs = (config or {}).get("beliefs", {})
        self.audit_history = bool(beliefs.get("audit_history", False))
        self.enforce_reserved_ranges = bool(
            beliefs.get("enforce_reserved_ranges", False))
        try:
            self.model_max_reserved_step = float(
                beliefs.get("model_max_reserved_step", 0.05))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(
                "beliefs.model_max_reserved_step must be finite and nonnegative"
            ) from exc
        if (not math.isfinite(self.model_max_reserved_step)
                or self.model_max_reserved_step < 0):
            raise ValueError(
                "beliefs.model_max_reserved_step must be finite and nonnegative")

    # ── capture ──────────────────────────────────────────────────────────────
    def observe(self, agent_id: int, tick: int, text: str, *, importance: float = 1.0,
                entities: Optional[list[str]] = None, kind: str = "observation") -> int:
        return self.store.insert(
            "memories", agent_id=agent_id, tick=tick, kind=kind, text=text,
            importance=float(importance), entities_json=json.dumps(entities or []),
            last_accessed_tick=tick, demoted=0)

    # ── retrieval ────────────────────────────────────────────────────────────
    def retrieve(self, agent_id: int, tick: int, k: int = 6,
                 query_entities: Optional[list[str]] = None) -> list[dict]:
        rows = self.store.query(
            "SELECT * FROM memories WHERE agent_id=? AND demoted=0 ORDER BY tick DESC LIMIT 200",
            (agent_id,))
        qset = set(query_entities or [])
        scored = []
        for r in rows:
            age = max(0, tick - int(r["tick"]))
            recency = 0.5 ** (age / RECENCY_HALFLIFE)
            importance = min(1.0, float(r["importance"]) / 10.0)
            ents = set(load_json(r["entities_json"], []) or [])
            relevance = (len(ents & qset) / len(qset)) if qset else 0.0
            score = retrieval_score(
                recency_decay=recency,
                importance=importance,
                relevance=relevance,
            )
            scored.append((score, r))
        scored.sort(key=lambda t: -t[0])
        top = scored[:k]
        for _, r in top:
            self.store.update("memories", int(r["id"]), last_accessed_tick=tick)
        return [{"id": int(r["id"]), "tick": int(r["tick"]), "text": r["text"],
                 "kind": r["kind"], "importance": float(r["importance"])} for _, r in top]

    def todays_observations(self, agent_id: int, tick: int) -> list[dict]:
        rows = self.store.query(
            "SELECT * FROM memories WHERE agent_id=? AND tick=? AND kind='observation' ORDER BY id",
            (agent_id, tick))
        return [{"text": r["text"], "importance": float(r["importance"]), "kind": r["kind"]} for r in rows]

    def write_summary(self, agent_id: int, tick: int, summary: str, importance: float) -> None:
        if not summary:
            return
        self.observe(agent_id, tick, summary, importance=importance, kind="summary")

    def weekly_rollup(self, agent_id: int, tick: int, summary: str,
                      importance: float = 1.0,
                      window_start: Optional[int] = None) -> None:
        """Persist one weekly synthesis, then demote the daily source summaries.

        `window_start` is the first tick of the roll-up window the runtime used.
        It defaults to the seven-day window so existing callers are unchanged.
        """
        if not summary:
            return
        existing = self.store.query_one(
            "SELECT id FROM memories WHERE agent_id=? AND kind='weekly_summary' AND tick=?",
            (agent_id, tick))
        if not existing:
            self.observe(agent_id, tick, summary, importance=importance, kind="weekly_summary")
        start = tick - 6 if window_start is None else int(window_start)
        self.store.execute(
            "UPDATE memories SET demoted=1 WHERE agent_id=? AND kind='summary' "
            "AND tick BETWEEN ? AND ? AND demoted=0",
            (agent_id, start, tick))

    # ── beliefs ──────────────────────────────────────────────────────────────
    def get_beliefs(self, agent_id: int) -> dict[str, float]:
        rows = self.store.query("SELECT key, value FROM beliefs WHERE agent_id=?", (agent_id,))
        return {r["key"]: float(r["value"]) for r in rows}

    @staticmethod
    def _reserved_range(key: str) -> Optional[tuple[float, float]]:
        if key.startswith("trust:bank:"):
            return 0.0, 1.0
        if key == "sentiment":
            return -1.0, 1.0
        if key == "inflation_expectation":
            return -0.05, 0.25
        return None

    def set_belief(
        self,
        agent_id: int,
        key: str,
        value: float,
        tick: int,
        *,
        source: str = "direct",
        source_llm_call_id: Optional[int] = None,
    ) -> float:
        raw_value = float(value)
        if not math.isfinite(raw_value):
            if self.audit_history:
                self.store.log_event(
                    tick, "belief_update_rejected", {
                        "agent_id": agent_id, "key": key,
                        "raw_value": str(raw_value), "reason": "non_finite",
                        "source": source, "source_llm_call_id": source_llm_call_id,
                    }, phase="MEMORY" if source == "memory" else "EXECUTION",
                    subject_type="agent", subject_id=agent_id, importance=1.0)
            raise ValueError("belief value must be finite")

        normalized = raw_value
        bounds = self._reserved_range(key) if self.enforce_reserved_ranges else None
        if bounds is not None:
            normalized = min(bounds[1], max(bounds[0], raw_value))

        existing = self.store.query_one(
            "SELECT id, value FROM beliefs WHERE agent_id=? AND key=?", (agent_id, key))
        old_value = float(existing["value"]) if existing else None
        if (
            bounds is not None
            and self._is_model_authored(source_llm_call_id)
            and model_grounding_active(self.config, tick)
        ):
            if existing is None:
                self._log_grounding_rejection(
                    agent_id,
                    key,
                    raw_value,
                    tick,
                    source,
                    source_llm_call_id,
                    reason="missing_model_baseline",
                    old_value=None,
                )
                raise ValueError(
                    "grounded model belief update requires an existing baseline")
            if abs(normalized - old_value) > self.model_max_reserved_step:
                self._log_grounding_rejection(
                    agent_id,
                    key,
                    raw_value,
                    tick,
                    source,
                    source_llm_call_id,
                    reason="model_reserved_step_limit",
                    old_value=old_value,
                )
                raise ValueError(
                    "grounded model belief update exceeds the configured step")
        if existing:
            self.store.update(
                "beliefs", int(existing["id"]), value=normalized, updated_tick=tick)
        else:
            self.store.insert("beliefs", agent_id=agent_id, key=key, value=normalized,
                              updated_tick=tick)

        if self.audit_history:
            payload = {
                "agent_id": agent_id, "key": key, "old_value": old_value,
                "raw_value": raw_value, "new_value": normalized,
                "normalized": normalized != raw_value, "source": source,
                "source_llm_call_id": source_llm_call_id,
            }
            phase = "MEMORY" if source == "memory" else (
                "NIGHT_CLOSE" if source == "genesis" else "EXECUTION")
            if normalized != raw_value:
                self.store.log_event(
                    tick, "belief_update_normalized", payload, phase=phase,
                    subject_type="agent", subject_id=agent_id, importance=1.0)
            self.store.log_event(
                tick, "belief_updated", payload, phase=phase,
                subject_type="agent", subject_id=agent_id, importance=0.5)
        return normalized

    def _is_model_authored(self, source_llm_call_id: Optional[int]) -> bool:
        if source_llm_call_id is None:
            return False
        provider = self.store.scalar(
            "SELECT provider FROM llm_calls WHERE id=?",
            (int(source_llm_call_id),),
            default=None,
        )
        return str(provider or "").lower() != "scripted"

    def _log_grounding_rejection(
        self,
        agent_id: int,
        key: str,
        raw_value: float,
        tick: int,
        source: str,
        source_llm_call_id: Optional[int],
        *,
        reason: str,
        old_value: Optional[float],
    ) -> None:
        self.store.log_event(
            tick,
            "belief_update_rejected",
            {
                "agent_id": agent_id,
                "key": key,
                "old_value": old_value,
                "raw_value": raw_value,
                "reason": reason,
                "source": source,
                "source_llm_call_id": source_llm_call_id,
                "model_max_reserved_step": self.model_max_reserved_step,
            },
            phase="MEMORY" if source == "memory" else "EXECUTION",
            subject_type="agent",
            subject_id=agent_id,
            importance=1.0,
        )

    def apply_belief_updates(
        self,
        agent_id: int,
        updates: list[dict],
        tick: int,
        *,
        source: str = "direct",
        source_llm_call_id: Optional[int] = None,
    ) -> None:
        for u in updates or []:
            key = u.get("key")
            if key is None:
                continue
            try:
                self.set_belief(
                    agent_id, str(key), float(u.get("value", 0.0)), tick,
                    source=source, source_llm_call_id=source_llm_call_id)
            except (TypeError, ValueError, OverflowError):
                continue

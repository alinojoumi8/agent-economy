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
from typing import Optional

from engine.store import Store, load_json

RECENCY_HALFLIFE = 10.0   # ticks


class Memory:
    def __init__(self, store: Store):
        self.store = store

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
            score = 0.5 * recency + 0.3 * importance + 0.2 * relevance
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

    def weekly_rollup(self, agent_id: int, tick: int) -> None:
        """Demote daily summaries older than a week (still queryable, rarely retrieved)."""
        self.store.execute(
            "UPDATE memories SET demoted=1 WHERE agent_id=? AND kind='summary' AND tick < ? AND demoted=0",
            (agent_id, tick - 7))

    # ── beliefs ──────────────────────────────────────────────────────────────
    def get_beliefs(self, agent_id: int) -> dict[str, float]:
        rows = self.store.query("SELECT key, value FROM beliefs WHERE agent_id=?", (agent_id,))
        return {r["key"]: float(r["value"]) for r in rows}

    def set_belief(self, agent_id: int, key: str, value: float, tick: int) -> None:
        existing = self.store.query_one(
            "SELECT id FROM beliefs WHERE agent_id=? AND key=?", (agent_id, key))
        if existing:
            self.store.update("beliefs", int(existing["id"]), value=float(value), updated_tick=tick)
        else:
            self.store.insert("beliefs", agent_id=agent_id, key=key, value=float(value),
                              updated_tick=tick)

    def apply_belief_updates(self, agent_id: int, updates: list[dict], tick: int) -> None:
        for u in updates or []:
            key = u.get("key")
            if key is None:
                continue
            try:
                self.set_belief(agent_id, key, float(u.get("value", 0.0)), tick)
            except (TypeError, ValueError):
                continue

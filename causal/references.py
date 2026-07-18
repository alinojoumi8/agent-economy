"""Closed stable-reference registry used by causal links and projections."""
from __future__ import annotations

from dataclasses import dataclass


class StableReferenceError(ValueError):
    """Raised for unknown, dangling, or malformed causal endpoints."""


PHASE_RANK = {
    "GENESIS": 0,
    "NIGHT_CLOSE": 10,
    "INBOX_DELIVERY": 20,
    "MORNING": 30,
    "EXECUTION": 40,
    "MARKET": 50,
    "NEWSROOM": 60,
    "EVENING": 70,
    "MEMORY": 80,
    "FINALIZE": 90,
    "LLM": 95,
}

KIND_RANK = {
    "message": 10,
    "memory": 20,
    "belief": 30,
    "decision": 40,
    "action_proposal": 50,
    "event": 60,
    "contract": 70,
    "case": 80,
    "article": 90,
    "ledger_transaction": 100,
}


@dataclass(frozen=True)
class StableReference:
    kind: str
    id: str
    tick: int
    phase: str
    order_key: str

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "id": self.id,
            "tick": self.tick,
            "order_key": self.order_key,
        }


class StableReferenceRegistry:
    """Resolve endpoint identity and temporal order from authoritative rows."""

    def __init__(self, store):
        self.store = store

    def resolve(self, kind: str, object_id: int | str) -> StableReference:
        if kind not in KIND_RANK:
            raise StableReferenceError(f"unsupported stable reference kind: {kind}")
        try:
            numeric_id = int(object_id)
        except (TypeError, ValueError) as exc:
            raise StableReferenceError("stable reference id must be a positive integer") from exc
        if numeric_id <= 0:
            raise StableReferenceError("stable reference id must be a positive integer")

        row, phase = self._row(kind, numeric_id)
        if row is None:
            raise StableReferenceError(f"dangling stable reference: {kind}:{numeric_id}")
        tick = int(row["tick"])
        row_phase = str(row["phase"] or phase) if "phase" in row.keys() else phase
        phase_rank = PHASE_RANK.get(row_phase, PHASE_RANK[phase])
        order_key = (
            f"{tick:012d}:{phase_rank:03d}:{KIND_RANK[kind]:03d}:"
            f"{numeric_id:020d}:{kind}"
        )
        return StableReference(kind, str(numeric_id), tick, row_phase, order_key)

    def _row(self, kind: str, object_id: int):
        if kind == "message":
            return self.store.query_one(
                "SELECT created_tick AS tick FROM comm_messages WHERE id=?", (object_id,)), "EXECUTION"
        if kind == "memory":
            return self.store.query_one(
                "SELECT tick, CASE WHEN kind='communication' THEN 'INBOX_DELIVERY' "
                "ELSE 'MEMORY' END AS phase FROM memories WHERE id=?", (object_id,)), "MEMORY"
        if kind == "belief":
            return self.store.query_one(
                "SELECT updated_tick AS tick FROM beliefs WHERE id=?", (object_id,)), "EXECUTION"
        if kind == "decision":
            return self.store.query_one(
                "SELECT tick FROM agent_decisions WHERE id=?", (object_id,)), "MORNING"
        if kind == "action_proposal":
            return self.store.query_one(
                "SELECT tick FROM action_proposals WHERE id=?", (object_id,)), "EXECUTION"
        if kind == "event":
            return self.store.query_one(
                "SELECT tick,COALESCE(phase,'EXECUTION') AS phase FROM events WHERE id=?",
                (object_id,)), "EXECUTION"
        if kind == "ledger_transaction":
            return self.store.query_one(
                "SELECT tick FROM transactions WHERE id=?", (object_id,)), "MARKET"
        if kind == "article":
            return self.store.query_one(
                "SELECT tick FROM news_articles WHERE id=?", (object_id,)), "NEWSROOM"
        if kind == "contract":
            return self.store.query_one(
                "SELECT offered_tick AS tick FROM contracts WHERE id=?", (object_id,)), "EXECUTION"
        if kind == "case":
            return self.store.query_one(
                "SELECT filed_tick AS tick FROM legal_matters WHERE id=?", (object_id,)), "EXECUTION"
        raise StableReferenceError(f"unsupported stable reference kind: {kind}")

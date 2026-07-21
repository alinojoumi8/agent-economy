"""Validated causal-link writes and bounded deterministic traversal."""
from __future__ import annotations

import hashlib
import json
from collections import deque


from .references import StableReferenceRegistry


class CausalLinkError(ValueError):
    """Raised when a causal assertion violates the closed relation contract."""


RELATION_MATRIX = {
    "observed": {
        ("message", "memory"), ("event", "memory"), ("article", "memory"),
        ("feed_impression", "information_exposure"),
        ("feed_impression", "memory"),
    },
    "delivered": {("commons_entry", "feed_impression")},
    "cited": {
        (source, target)
        for source in ("message", "memory", "belief", "event", "contract", "case", "article")
        for target in ("message", "article", "decision", "case")
    },
    "motivated": {
        (source, target)
        for source in ("message", "memory", "belief")
        for target in ("decision", "action_proposal")
    },
    "triggered": {
        ("memory", "belief"),
        ("information_exposure", "belief"),
        ("decision", "action_proposal"),
        ("action_proposal", "event"),
        ("event", "event"),
    },
    "settled": {
        (source, "ledger_transaction")
        for source in ("action_proposal", "event", "contract", "case")
    },
}
INFERRED_SOURCE_KINDS = {
    "message", "memory", "belief", "decision", "action_proposal", "event",
    "contract", "case", "article", "commons_entry", "feed_impression",
    "information_exposure",
}
INFERRED_TARGET_KINDS = {
    "belief", "decision", "action_proposal", "event", "contract", "case",
    "article", "ledger_transaction", "feed_impression", "information_exposure",
}


def _canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class CausalLinkService:
    def __init__(self, store):
        self.store = store
        self.references = StableReferenceRegistry(store)

    def create(
        self,
        source_kind: str,
        source_id: int | str,
        target_kind: str,
        target_id: int | str,
        relation: str,
        authority: str,
        *,
        created_tick: int | None = None,
        actor_agent_id: int | None = None,
        confidence: float = 1.0,
        method: str | None = None,
        model_call_id: int | None = None,
        provenance: dict | None = None,
        evidence: dict | None = None,
    ) -> int:
        source = self.references.resolve(source_kind, source_id)
        target = self.references.resolve(target_kind, target_id)
        self._validate_relation(source_kind, target_kind, relation)
        self._validate_authority(
            relation, authority, actor_agent_id, confidence, method, model_call_id)
        if source.kind == target.kind and source.id == target.id:
            raise CausalLinkError("causal self-links are forbidden")
        if authority != "model_inference" and source.order_key >= target.order_key:
            raise CausalLinkError("recorded causal links must move forward in stable order")
        link_tick = max(source.tick, target.tick) if created_tick is None else int(created_tick)
        if link_tick < source.tick or link_tick < target.tick:
            raise CausalLinkError("causal link cannot predate either endpoint")
        provenance_json = _canonical_json(provenance or {})
        evidence_json = _canonical_json(evidence or {})
        identity = {
            "source": source.as_dict(),
            "target": target.as_dict(),
            "relation": relation,
            "authority": authority,
            "actor_agent_id": int(actor_agent_id or 0),
            "confidence": float(confidence).hex(),
            "method": method or "",
            "model_call_id": int(model_call_id or 0),
            "provenance": provenance_json,
            "evidence": evidence_json,
        }
        dedupe_key = hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()
        self.store.execute(
            "INSERT OR IGNORE INTO causal_links ("
            "dedupe_key,created_tick,source_kind,source_id,source_tick,source_order_key,"
            "target_kind,target_id,target_tick,target_order_key,relation,authority,"
            "actor_agent_id,confidence,method,model_call_id,provenance_json,evidence_json"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                dedupe_key, link_tick, source.kind, source.id, source.tick, source.order_key,
                target.kind, target.id, target.tick, target.order_key, relation, authority,
                actor_agent_id, float(confidence), method, model_call_id,
                provenance_json, evidence_json,
            ),
        )
        row = self.store.query_one(
            "SELECT id FROM causal_links WHERE dedupe_key=?", (dedupe_key,))
        return int(row["id"])

    @staticmethod
    def _validate_relation(source_kind: str, target_kind: str, relation: str) -> None:
        if relation == "inferred":
            if source_kind not in INFERRED_SOURCE_KINDS or target_kind not in INFERRED_TARGET_KINDS:
                raise CausalLinkError("invalid inferred causal endpoint pair")
            return
        allowed = RELATION_MATRIX.get(relation)
        if allowed is None:
            raise CausalLinkError(f"unsupported causal relation: {relation}")
        if (source_kind, target_kind) not in allowed:
            raise CausalLinkError(
                f"invalid {relation} causal endpoint pair: {source_kind}->{target_kind}")

    @staticmethod
    def _validate_authority(
        relation: str,
        authority: str,
        actor_agent_id: int | None,
        confidence: float,
        method: str | None,
        model_call_id: int | None,
    ) -> None:
        if not 0.0 <= float(confidence) <= 1.0:
            raise CausalLinkError("causal confidence must be between zero and one")
        if authority == "engine":
            if relation == "inferred" or float(confidence) != 1.0:
                raise CausalLinkError("engine links require deterministic confidence")
            if actor_agent_id is not None or model_call_id is not None:
                raise CausalLinkError("engine links cannot claim actor or model authority")
            return
        if authority == "actor_claim":
            if relation not in {"cited", "motivated"}:
                raise CausalLinkError("actor claims may only cite or motivate")
            if actor_agent_id is None or not method:
                raise CausalLinkError("actor claims require actor and method provenance")
            return
        if authority == "model_inference":
            if relation != "inferred" or not method or model_call_id is None:
                raise CausalLinkError("model inference requires method and model call provenance")
            return
        raise CausalLinkError(f"unsupported causal authority: {authority}")

    def neighborhood(
        self,
        kind: str,
        object_id: int | str,
        *,
        depth: int = 3,
        max_nodes: int = 250,
        max_edges: int = 500,
    ) -> dict:
        if depth < 0 or depth > 6:
            raise CausalLinkError("causal depth must be between zero and six")
        if max_nodes < 1 or max_nodes > 1000 or max_edges < 1 or max_edges > 2000:
            raise CausalLinkError("causal traversal limits are outside the supported range")
        root = self.references.resolve(kind, object_id)
        queue = deque([(root.kind, root.id, 0)])
        visited = {(root.kind, root.id)}
        nodes = [root.as_dict()]
        edges = []
        truncated = False
        cycles = []
        while queue:
            current_kind, current_id, current_depth = queue.popleft()
            if current_depth >= depth:
                continue
            rows = self.store.query(
                "SELECT * FROM causal_links WHERE "
                "(source_kind=? AND source_id=?) OR (target_kind=? AND target_id=?) "
                "ORDER BY source_order_key,relation,target_order_key,dedupe_key",
                (current_kind, current_id, current_kind, current_id),
            )
            for row in rows:
                if len(edges) >= max_edges:
                    truncated = True
                    break
                edge = dict(row)
                edges.append(edge)
                if row["source_kind"] == current_kind and row["source_id"] == current_id:
                    neighbor = (str(row["target_kind"]), str(row["target_id"]))
                else:
                    neighbor = (str(row["source_kind"]), str(row["source_id"]))
                if neighbor in visited:
                    cycles.append({"kind": neighbor[0], "id": neighbor[1], "cycle": True})
                    continue
                if len(nodes) >= max_nodes:
                    truncated = True
                    break
                reference = self.references.resolve(*neighbor)
                visited.add(neighbor)
                nodes.append(reference.as_dict())
                queue.append((neighbor[0], neighbor[1], current_depth + 1))
            if truncated:
                break
        return {
            "root": root.as_dict(),
            "nodes": nodes,
            "edges": edges,
            "cycles": cycles,
            "truncated": truncated,
        }

"""Policy-filtered deterministic causal neighborhoods and semantic rows."""
from __future__ import annotations

from causal import CausalLinkService
from communications.policy import CommunicationPolicy, MessageField, Principal
from engine.store import load_json


def _message_for_memory(store, memory_id: int) -> int | None:
    value = store.scalar(
        "SELECT message_id FROM comm_deliveries WHERE memory_id=?", (int(memory_id),),
        default=None)
    return int(value) if value is not None else None


def _node_allowed(store, policy, principal, node: dict, as_of_tick: int) -> bool:
    kind = str(node["kind"])
    object_id = int(node["id"])
    if kind == "message":
        return policy.can_read_field(
            principal, object_id, MessageField.EXISTENCE, as_of_tick).allowed
    if kind == "memory":
        message_id = _message_for_memory(store, object_id)
        if message_id is not None:
            return policy.can_read_field(
                principal, message_id, MessageField.EXISTENCE, as_of_tick).allowed
    return True


def _semantic_row(store, node: dict) -> dict:
    kind = str(node["kind"])
    object_id = int(node["id"])
    base = {"stable_ref": node, "kind": kind, "id": object_id}
    if kind == "event":
        row = store.query_one(
            "SELECT tick,phase,kind,subject_type,subject_id,importance,payload_json "
            "FROM events WHERE id=?", (object_id,))
        if row:
            base.update({
                "tick": int(row["tick"]), "phase": row["phase"], "label": row["kind"],
                "subject_type": row["subject_type"], "subject_id": row["subject_id"],
                "importance": float(row["importance"]),
                "payload": load_json(row["payload_json"], {}) or {},
            })
    elif kind == "action_proposal":
        row = store.query_one(
            "SELECT tick,actor_id,action_type,validation_status,result_json "
            "FROM action_proposals WHERE id=?", (object_id,))
        if row:
            base.update({
                "tick": int(row["tick"]), "label": row["action_type"],
                "actor_id": int(row["actor_id"]), "status": row["validation_status"],
                "result": load_json(row["result_json"], None),
            })
    elif kind == "ledger_transaction":
        row = store.query_one(
            "SELECT tick,kind,memo FROM transactions WHERE id=?", (object_id,))
        if row:
            base.update({"tick": int(row["tick"]), "label": row["kind"], "memo": row["memo"]})
    else:
        base.update({"tick": int(node["tick"]), "label": kind.replace("_", " ")})
    return base


def build_causal_projection(
    store,
    principal: Principal,
    kind: str,
    object_id: int,
    *,
    as_of_tick: int,
    depth: int = 3,
    relations: tuple[str, ...] = (),
    authorities: tuple[str, ...] = (),
    truth_audit=None,
) -> dict:
    raw = CausalLinkService(store).neighborhood(kind, object_id, depth=int(depth))
    policy = CommunicationPolicy(store, truth_audit=truth_audit)
    nodes = [
        node for node in raw["nodes"]
        if int(node["tick"]) <= int(as_of_tick)
        and _node_allowed(store, policy, principal, node, int(as_of_tick))
    ]
    allowed = {(str(node["kind"]), str(node["id"])) for node in nodes}
    edges = []
    for row in raw["edges"]:
        if (str(row["source_kind"]), str(row["source_id"])) not in allowed:
            continue
        if (str(row["target_kind"]), str(row["target_id"])) not in allowed:
            continue
        if relations and str(row["relation"]) not in relations:
            continue
        if authorities and str(row["authority"]) not in authorities:
            continue
        edge = {
            "id": int(row["id"]),
            "source": {"kind": str(row["source_kind"]), "id": str(row["source_id"])},
            "target": {"kind": str(row["target_kind"]), "id": str(row["target_id"])},
            "relation": str(row["relation"]),
            "authority": str(row["authority"]),
            "confidence": float(row["confidence"]),
            "method": row["method"],
            "provenance": load_json(row["provenance_json"], {}) or {},
            "evidence": load_json(row["evidence_json"], {}) or {},
        }
        edges.append(edge)
    return {
        "root": raw["root"] if (
            str(raw["root"]["kind"]), str(raw["root"]["id"])) in allowed else None,
        "nodes": nodes,
        "edges": edges,
        "semantic_rows": [_semantic_row(store, node) for node in nodes],
        "cycles": raw["cycles"],
        "truncated": raw["truncated"],
    }

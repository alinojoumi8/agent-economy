"""Stable v4 event identities without exposing additional private evidence."""
from __future__ import annotations

import json

from llm.decisions import canonical_json, decision_hash

EVENT_KEYS = frozenset({"authority_event_id", "effect_event_id", "request_event_id",
    "event_id", "created_event_id", "publication_event_id", "root_event_id",
    "source_event_id", "outcome_event_id"})
EVENT_LIST_KEYS = frozenset({"evidence_event_ids", "source_event_ids"})
BINDINGS_KEY = "decision_reference_bindings"


def normalize_references(value, bindings):
    """Only explicit event pointers change; economic IDs and amounts stay exact."""
    references = {item["event_id"]: item["identity"] for item in bindings}
    def visit(node):
        if isinstance(node, list):
            return [visit(item) for item in node]
        if not isinstance(node, dict):
            return node
        output = {}
        for key, item in node.items():
            if key == BINDINGS_KEY:
                continue
            if key in EVENT_KEYS and type(item) is int and item in references:
                output[key + "_logical"] = references[item]
            elif key in EVENT_LIST_KEYS and isinstance(item, list):
                output[key + "_logical"] = [references[v] if type(v) is int and v in references else v for v in item]
            elif key == "domain_action_terms":
                output[key] = {canonical_json(visit(json.loads(action))): visit(terms) for action, terms in item.items()}
            else:
                output[key] = visit(item)
        return output
    return visit(value)


def bind_event_references(store, context):
    """Bind every current explicit pointer to full event contents and occurrence.

    Operational events may shift local IDs in replay. This does not weaken exact
    request matching: changed evidence, amount, actor or duplicate occurrence
    still changes the identity. Only hashes cross the observation boundary.
    """
    memo, resolving = {}, set()
    def logical_payload(value):
        if isinstance(value, list):
            return [logical_payload(v) for v in value]
        if not isinstance(value, dict):
            return value
        out = {}
        for key, item in value.items():
            if key in EVENT_KEYS and type(item) is int:
                out[key] = event_identity(item)
            elif key in EVENT_LIST_KEYS and isinstance(item, list):
                out[key] = [event_identity(v) if type(v) is int else v for v in item]
            elif key in {"model_call_id", "llm_call_id", "source_llm_call_id"} and type(item) is int:
                call = store.query_one("SELECT * FROM llm_calls WHERE id=?", (item,))
                if call is None:
                    raise ValueError("v4 evidence has a dangling model reference")
                out[key] = decision_hash({k: v for k, v in dict(call).items() if k not in {"id", "created_at"}})
            else:
                out[key] = logical_payload(item)
        return out
    def contents(row):
        return {k: (logical_payload(json.loads(v)) if k == "payload_json" else v)
                for k, v in dict(row).items() if k not in {"id", "created_at"}}
    def event_identity(event_id):
        if event_id in memo:
            return memo[event_id]
        if event_id in resolving:
            raise ValueError("v4 evidence contains cyclic event references")
        resolving.add(event_id)
        row = store.query_one("SELECT * FROM events WHERE id=?", (event_id,))
        if row is None:
            raise ValueError("v4 evidence has a dangling event reference")
        body = contents(row)
        prior = store.query("SELECT * FROM events WHERE tick=? AND kind=? AND phase IS ? "
            "AND subject_type IS ? AND subject_id IS ? AND id<? ORDER BY id",
            (row["tick"], row["kind"], row["phase"], row["subject_type"], row["subject_id"], event_id))
        occurrence = sum(contents(candidate) == body for candidate in prior)
        identity = decision_hash({"event": body, "occurrence": occurrence})
        resolving.remove(event_id)
        memo[event_id] = identity
        return identity
    def collect(value):
        if isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, dict):
            for key, item in value.items():
                if key in EVENT_KEYS and type(item) is int:
                    event_identity(item)
                elif key in EVENT_LIST_KEYS and isinstance(item, list):
                    for event_id in item:
                        if type(event_id) is int:
                            event_identity(event_id)
                else:
                    collect(item)
    collect(context)
    return [{"event_id": event_id, "identity": identity} for event_id, identity in sorted(memo.items())]

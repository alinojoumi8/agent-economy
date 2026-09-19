"""Read-only decision telemetry; never expose observations or private menus."""
import json


def decision_summary(payload):
    calls = payload.get("calls", [])
    outcomes = payload.get("outcomes", [])
    selected = next((c for c in payload.get("candidates", [])
                     if c.get("id") == payload.get("selected_candidate")), {})
    return {"status": payload.get("status"), "reason": payload.get("reason"),
        "domains": payload.get("domains", ["citizen_routine"]),
        "controller": payload.get("controller", "native"),
        "candidate_count": payload.get("candidate_count", len(payload.get("candidates", []))),
        "coverage_excluded_count": len(payload.get("coverage_exclusions", [])),
        "confidence": payload.get("confidence"), "escalated": payload.get("escalated") is True,
        "confidence_meaning": "Answer concentration, not probability of economic success",
        "action_types": [a.get("type") for a in selected.get("actions", [])],
        "accepted": sum(o.get("ok") is True for o in outcomes), "attempted": len(outcomes),
        "provider_calls": len(calls), "cost_usd": sum(c.get("cost_usd", 0) for c in calls),
        "models": sorted({c.get("resolved_model") or c.get("requested_model", "unknown") for c in calls}),
        "latency_ms": sum(c.get("latency_ms", 0) for c in calls)}


def observer_event_payload(kind, payload):
    if kind == "bounded_selection":
        return {"service": payload.get("service"), "controller": payload.get("controller"),
                "provider_calls": len(payload.get("calls", [])),
                "cost_usd": sum(c.get("cost_usd", 0) for c in payload.get("calls", []))}
    return decision_summary(payload) if kind == "typed_decision" else payload


def build_decision_workspace(store, *, as_of_tick):
    total = store.scalar("SELECT COUNT(*) FROM events WHERE kind='typed_decision' AND tick<=?", (as_of_tick,))
    rows = store.query("SELECT id,tick,subject_id,payload_json FROM events "
        "WHERE kind='typed_decision' AND tick<=? ORDER BY tick DESC,id DESC LIMIT 200", (as_of_tick,))
    totals = {"provider_calls": 0, "cost_usd": 0.0, "accepted": 0, "attempted": 0}
    for row in store.query("SELECT payload_json FROM events WHERE kind='typed_decision' AND tick<=?", (as_of_tick,)):
        summary = decision_summary(json.loads(row["payload_json"]))
        for key in totals:
            totals[key] += summary[key]
    services = {}
    for row in store.query("SELECT payload_json FROM events WHERE kind='bounded_selection' AND tick<=?", (as_of_tick,)):
        summary = observer_event_payload("bounded_selection", json.loads(row["payload_json"]))
        item = services.setdefault(summary["service"], {"service": summary["service"], "selections": 0,
            "provider_calls": 0, "cost_usd": 0.0})
        item["selections"] += 1
        item["provider_calls"] += summary["provider_calls"]
        item["cost_usd"] += summary["cost_usd"]
    return {"total": total, "window": 200, "totals": totals, "totals_scope": "all_decisions_through_as_of_tick",
        "services": [services[key] for key in sorted(services)], "items": [
        {"id": row["id"], "tick": row["tick"], "agent_id": row["subject_id"],
         **decision_summary(json.loads(row["payload_json"]))} for row in rows]}

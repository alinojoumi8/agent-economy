"""Read-only, complete-day activity for every City renderer.

Only explicitly selected public scalar facts enter cards. Private message
bodies, model responses, reasoning, and arbitrary event payloads never do.
Pagination changes the displayed rows, never the day totals or map markers.
"""
from __future__ import annotations

from collections import Counter
from math import isfinite

from engine.store import load_json
from .activity import ActivityFact, project_activity


CATEGORIES = ("all", "work", "markets", "learning", "business", "construction",
              "travel", "communications", "external", "civic", "other")
_PUBLIC_KINDS = {
    "trade", "goods_sale", "order_placed", "price_set", "wage_paid", "hired",
    "fired", "quit", "production", "skill_studied", "skill_practiced",
    "skill_level_up", "company_founded", "firm_founded", "firm_bankrupt",
    "action_rejected", "external_action_queued", "external_action_executed",
    "external_action_rejected", "belief_updated", "conversation",
    "news_published", "information_published", "public_output_published",
    "business_permit_applied", "business_permit_approved", "business_permit_denied",
    "civic_appointment_attended", "civic_appointment_scheduled", "policy_bought", "construction_started", "construction_completed",
    "construction_cancelled", "construction_demolished", "migration_requested",
    "migration_completed", "migration_cancelled", "travel_started", "travel_completed",
    "construction_project_proposed", "construction_project_approved",
    "construction_project_funded", "construction_project_worked",
    "construction_project_completed", "construction_project_cancelled",
}
_ACTOR_FIELDS = ("agent_id", "actor_id", "applicant_agent_id", "founder_agent_id",
                 "worker_id", "buyer_id", "seller_id", "buyer", "seller")


def _id(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _category(kind: str) -> str:
    if kind.startswith("external_action_"):
        return "external"
    if "construction" in kind:
        return "construction"
    if any(word in kind for word in ("migration", "travel", "settlement", "exploration")):
        return "travel"
    if kind.startswith("skill_"):
        return "learning"
    if kind in {"trade", "goods_sale", "order_placed", "price_set", "policy_bought"}:
        return "markets"
    if kind in {"wage_paid", "hired", "fired", "quit", "production"}:
        return "work"
    if kind in {"company_founded", "firm_founded", "firm_bankrupt"}:
        return "business"
    if kind in {"conversation", "news_published", "information_published", "public_output_published"}:
        return "communications"
    if any(word in kind for word in ("permit", "appointment", "legal", "bill", "vote")):
        return "civic"
    return "other"


def _outcome(kind: str) -> str:
    if kind not in _PUBLIC_KINDS:
        return "recorded"
    if any(word in kind for word in ("rejected", "denied", "failed")):
        return "rejected"
    if any(word in kind for word in ("cancelled", "demolished")):
        return "cancelled"
    if any(word in kind for word in ("queued", "requested", "proposed", "applied", "scheduled")) or kind in {"order_placed", "construction_started", "travel_started"}:
        return "pending"
    if kind in _PUBLIC_KINDS and kind != "belief_updated":
        return "completed"
    return "recorded"


def _card(row, agents: dict, firms: dict) -> dict:
    kind = str(row["kind"])
    public = kind in _PUBLIC_KINDS
    payload = (load_json(row["payload_json"], {}) or {}) if public else {}
    if not isinstance(payload, dict):
        payload = {}
    actors = {_id(payload.get(key)) for key in _ACTOR_FIELDS} if public else set()
    if row["subject_type"] == "agent":
        actors.add(_id(row["subject_id"]))
    # Legacy small talk is public, unlike the separate communications store.
    if kind == "conversation" and isinstance(payload.get("participants"), list):
        actors.update(_id(value) for value in payload["participants"])
    actors = sorted(value for value in actors if value in agents)
    firm_id = _id(payload.get("firm_id"))
    if row["subject_type"] == "firm":
        firm_id = _id(row["subject_id"])
    firm = firms.get(firm_id)
    label = kind.replace("_", " ")
    verb = {
        "order_placed": "placed an order", "trade": "traded shares",
        "goods_sale": "completed a goods sale", "wage_paid": "received wages",
        "hired": "started employment", "skill_studied": "studied a skill",
        "company_founded": "founded a company", "action_rejected": "had an action rejected",
        "external_action_queued": "queued an external action",
        "external_action_executed": "executed an external action",
        "external_action_rejected": "had an external action rejected",
        "conversation": "held a conversation", "belief_updated": "updated a belief",
        "civic_appointment_scheduled": "received an appointment",
        "policy_bought": "bought insurance", "production": "produced goods",
        "price_set": "changed its goods price",
    }.get(kind, label)
    who = ", ".join(agents[value] for value in actors[:3])
    if len(actors) > 3:
        who += f" and {len(actors) - 3} others"
    title = f"{who} · {verb}" if who else (f"{firm} · {verb}" if firm else label.capitalize())
    details = []
    if firm:
        details.append(firm)
    # Exact numbers with explicit units, no arbitrary text or nested payloads.
    for key, unit in (("qty", "units"), ("quantity", "units"), ("units", "units produced"), ("amount_cents", "cents"),
                      ("total_cents", "cents total"), ("unit_price_cents", "cents per unit"),
                      ("new_cents", "cents new price"), ("premium_cents", "cents premium"),
                      ("cost_cents", "cents committed"),
                      ("price_cents", "cents per unit"), ("limit_price_cents", "cents limit"),
                      ("work_units", "work units"), ("xp", "XP")):
        value = payload.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value):
            details.append(f"{value:,} {unit}")
    if isinstance(payload.get("side"), str) and payload["side"] in {"buy", "sell"}:
        details.insert(0, payload["side"])
    if kind == "construction_started" and _id(payload.get("completion_tick")):
        details.append(f"due tick {payload['completion_tick']}")
    outcome = _outcome(kind)
    event_id, tick = int(row["id"]), int(row["tick"])
    semantic = project_activity(ActivityFact(
        activity_id=f"event:{event_id}", tick=tick, kind=kind, stage=outcome,
        title=title, agent_id=actors[0] if actors else None, source="committed",
        evidence_ref={"kind": "event", "id": event_id, "tick": tick},
    ))
    # A vetted event outcome is more specific than the generic contract fallback.
    semantic.update(lifecycle=outcome, outcome={"status": outcome, "label": outcome},
                    verb=verb, semantic_fallback=not public)
    return {
        "id": event_id, "tick": tick, "phase": str(row["phase"] or ""), "kind": kind,
        "title": title, "detail": " · ".join(details), "category": _category(kind),
        "outcome": outcome, "actor_ids": actors,
        "actors": [{"id": value, "name": agents[value]} for value in actors],
        "firm_id": firm_id if firm else None, "firm_name": firm,
        "conversation_id": _id(payload.get("conv_id")) if kind == "conversation" else None,
        "activity": semantic,
        "evidence_ref": {"kind": "event", "id": event_id, "tick": tick},
    }


def build_city_activity(store, *, as_of_tick: int, offset: int = 0, limit: int = 40,
                        actor_id: int | None = None, category: str = "all",
                        through_id: int | None = None) -> dict:
    """Return an immutable high-water window with totals independent of paging."""
    if category not in CATEGORIES:
        raise ValueError("unsupported activity category")
    if offset < 0 or not 1 <= limit <= 200:
        raise ValueError("invalid activity page")
    agents = {int(row["id"]): str(row["name"]) for row in store.query(
        "SELECT id,name FROM agents WHERE arrived_tick<=?", (as_of_tick,))}
    firms = {int(row["id"]): str(row["name"]) for row in store.query(
        "SELECT id,name FROM firms WHERE founded_tick<=?", (as_of_tick,))}
    maximum = int(store.scalar("SELECT COALESCE(MAX(id),0) FROM events WHERE tick=?",
                              (as_of_tick,), default=0))
    boundary = maximum if through_id is None else min(maximum, max(0, through_id))
    cards = [_card(row, agents, firms) for row in store.query(
        "SELECT * FROM events WHERE tick=? AND id<=? ORDER BY id DESC",
        (as_of_tick, boundary))]
    filtered = [card for card in cards if (actor_id is None or actor_id in card["actor_ids"])
                and (category == "all" or card["category"] == category)]
    # The complete set of latest actor records powers map/list marks, regardless
    # of the visible page. A pending action must never become a settled mark.
    latest = {}
    firm_latest = {}
    for card in filtered:
        for aid in card["actor_ids"]:
            latest.setdefault(aid, card)
        if card["firm_id"]:
            firm_latest.setdefault(card["firm_id"], card)
    total = len(filtered)
    return {
        "tick": as_of_tick, "through_id": boundary, "source": "committed",
        "window": "selected_day", "total": total, "day_total": len(cards),
        "offset": offset, "limit": limit,
        "next_offset": offset + limit if offset + limit < total else None,
        "items": filtered[offset:offset + limit],
        "counts": dict(Counter(card["outcome"] for card in filtered)),
        "categories": dict(Counter(card["category"] for card in cards)),
        "actors": [{"id": aid, "name": agents[aid]} for aid in sorted({
            aid for card in cards for aid in card["actor_ids"]})],
        "changed_agents": len(latest),
        "marker_events": list({card["id"]: card for card in [*latest.values(), *firm_latest.values()]}.values()),
        "actor_activity": [{"agent_id": aid, "event": card} for aid, card in sorted(latest.items())],
    }

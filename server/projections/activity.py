"""Shared privacy-safe semantic activity projection.

The projector is deliberately read-only.  It turns already-public facts into a
small observer card, strips evidence references to stable identifiers, and
never reads event payloads.  Runtime facts are current-view data and are
therefore refused for historical projections.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ActivityFact:
    """A caller-vetted public fact ready for semantic projection."""

    activity_id: str
    tick: int
    kind: str
    stage: str
    title: str
    agent_id: int | None
    source: str
    evidence_ref: Mapping[str, Any]
    project_id: str | None = None
    raw_ref: Mapping[str, Any] | None = None
    salience: float = 0.5


@dataclass(frozen=True, slots=True)
class _SemanticRule:
    verb: str
    lifecycle: str
    outcome_label: str


_RULES: dict[tuple[str, str], _SemanticRule] = {
    ("employment", "employed"): _SemanticRule(
        "start", "active", "Employment started"),
    ("employment", "ended"): _SemanticRule(
        "finish", "completed", "Employment ended"),
    ("skill", "level"): _SemanticRule(
        "practice", "active", "Skill advanced"),
    ("firm", "founded"): _SemanticRule(
        "found", "completed", "Firm founded"),
    ("migration", "requested"): _SemanticRule(
        "request", "pending", "Migration requested"),
    ("migration", "arrived"): _SemanticRule(
        "arrive", "completed", "Migration completed"),
    ("migration", "cancelled"): _SemanticRule(
        "cancel", "cancelled", "Migration cancelled"),
    ("residence", "established"): _SemanticRule(
        "establish", "completed", "Residence established"),
    ("workplace", "established"): _SemanticRule(
        "establish", "completed", "Workplace established"),
    ("public_output", "published"): _SemanticRule(
        "publish", "completed", "Public output published"),
    ("civic_case", "applied"): _SemanticRule(
        "apply", "pending", "Application recorded"),
    ("civic_case", "submitted"): _SemanticRule(
        "submit", "pending", "Application submitted"),
    ("civic_case", "decided"): _SemanticRule(
        "decide", "completed", "Application decided"),
    ("provider_call", "streaming"): _SemanticRule(
        "process", "active", "Provider call in progress"),
    ("construction", "proposed"): _SemanticRule(
        "propose", "pending", "Construction proposed"),
    ("construction", "approved"): _SemanticRule(
        "approve", "active", "Construction approved"),
    ("construction", "funded"): _SemanticRule(
        "fund", "active", "Construction funded"),
    ("construction", "building"): _SemanticRule(
        "build", "active", "Construction in progress"),
    ("construction", "completed"): _SemanticRule(
        "complete", "completed", "Construction completed"),
    ("construction", "cancelled"): _SemanticRule(
        "cancel", "cancelled", "Construction cancelled"),
}

_EVENT_RULES: dict[str, tuple[str, str, str]] = {
    "construction_project_proposed": (
        "construction", "proposed", "Construction proposed"),
    "construction_project_approved": (
        "construction", "approved", "Construction approved"),
    "construction_project_completed": (
        "construction", "completed", "Construction completed"),
    "construction_project_cancelled": (
        "construction", "cancelled", "Construction cancelled"),
    "public_output_published": (
        "public_output", "published", "Published public output"),
}


def _safe_label(value: object, *, fallback: str) -> str:
    label = " ".join(str(value or "").split())
    return (label or fallback)[:200]


def _safe_reference(
    reference: Mapping[str, Any] | None,
    *,
    fallback_kind: str,
    fallback_id: int | str,
    fallback_tick: int,
) -> dict[str, int | str]:
    source = reference or {}
    kind = _safe_label(source.get("kind"), fallback=fallback_kind)
    record_id = source.get("id", fallback_id)
    if not isinstance(record_id, (int, str)) or isinstance(record_id, bool):
        record_id = fallback_id
    try:
        tick = int(source.get("tick", fallback_tick))
    except (TypeError, ValueError):
        tick = int(fallback_tick)
    return {"kind": kind, "id": record_id, "tick": tick}


def _rule_for(kind: str, stage: str) -> _SemanticRule | None:
    exact = _RULES.get((kind, stage))
    if exact is not None:
        return exact
    if kind == "skill" and stage.startswith("level_"):
        return _RULES[("skill", "level")]
    return None


def _salience(value: float) -> dict[str, float | str]:
    try:
        score = round(max(0.0, min(1.0, float(value))), 3)
    except (TypeError, ValueError):
        score = 0.5
    if score >= 0.67:
        level = "high"
    elif score >= 0.34:
        level = "normal"
    else:
        level = "low"
    return {"score": score, "level": level}


def project_activity(
    fact: ActivityFact,
    *,
    historical: bool = True,
) -> dict[str, Any] | None:
    """Project one vetted fact into the shared semantic activity-card shape."""

    if historical and fact.source == "runtime":
        return None

    kind = _safe_label(fact.kind, fallback="activity")
    stage = _safe_label(fact.stage, fallback="recorded")
    title = _safe_label(fact.title, fallback="Recorded activity")
    rule = _rule_for(kind, stage)
    fallback = rule is None
    if fallback:
        rule = _SemanticRule(
            "record", "recorded",
            "Recorded without a specific semantic adapter",
        )

    evidence_ref = _safe_reference(
        fact.evidence_ref,
        fallback_kind=kind,
        fallback_id=fact.activity_id,
        fallback_tick=fact.tick,
    )
    raw_ref = _safe_reference(
        fact.raw_ref or fact.evidence_ref,
        fallback_kind=kind,
        fallback_id=fact.activity_id,
        fallback_tick=fact.tick,
    )
    return {
        "activity_id": str(fact.activity_id),
        "tick": int(fact.tick),
        "kind": kind,
        "stage": stage,
        "lifecycle": rule.lifecycle,
        "title": title,
        "verb": rule.verb,
        "object": {"type": kind, "label": title},
        "outcome": {
            "status": rule.lifecycle,
            "label": rule.outcome_label,
        },
        "salience": _salience(fact.salience),
        "agent_id": int(fact.agent_id) if fact.agent_id is not None else None,
        "project_id": (
            str(fact.project_id) if fact.project_id is not None else None
        ),
        "source": str(fact.source),
        "evidence_ref": evidence_ref,
        "raw_ref": raw_ref,
        "semantic_fallback": fallback,
    }


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


def project_event_activity(
    row: Any,
    *,
    historical: bool = True,
) -> dict[str, Any] | None:
    """Project an event row without inspecting or copying its payload."""

    event_id = int(_row_value(row, "id", 0))
    tick = int(_row_value(row, "tick", 0))
    event_kind = _safe_label(
        _row_value(row, "kind", "event"), fallback="event")
    known = _EVENT_RULES.get(event_kind)
    if known is None:
        kind = event_kind
        stage = "recorded"
        title = f"Recorded {event_kind.replace('_', ' ')}"
    else:
        kind, stage, title = known
    subject_type = _row_value(row, "subject_type")
    subject_id = _row_value(row, "subject_id")
    agent_id = (
        int(subject_id)
        if subject_type == "agent" and subject_id is not None
        else None
    )
    try:
        importance = max(0.0, float(_row_value(row, "importance", 1.0)))
    except (TypeError, ValueError):
        importance = 1.0
    return project_activity(
        ActivityFact(
            activity_id=f"event:{event_id}",
            tick=tick,
            kind=kind,
            stage=stage,
            title=title,
            agent_id=agent_id,
            source="committed",
            evidence_ref={"kind": "event", "id": event_id, "tick": tick},
            raw_ref={"kind": "event", "id": event_id, "tick": tick},
            salience=min(1.0, importance / 2.0),
        ),
        historical=historical,
    )

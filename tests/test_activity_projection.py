from __future__ import annotations

import json

from server.projections.activity import (
    ActivityFact,
    project_activity,
    project_event_activity,
)
from server.projections.events import build_events


def test_activity_projection_is_semantic_and_reference_safe():
    card = project_activity(ActivityFact(
        activity_id="output:7:published",
        tick=9,
        kind="public_output",
        stage="published",
        title="Published research note",
        agent_id=3,
        project_id="public_output:7",
        source="committed",
        evidence_ref={
            "kind": "information_item",
            "id": 7,
            "tick": 9,
            "private_body": "body-canary",
        },
        raw_ref={
            "kind": "event",
            "id": 12,
            "tick": 9,
            "payload": "payload-canary",
        },
        salience=0.8,
    ))

    assert card is not None
    assert card["verb"] == "publish"
    assert card["object"] == {
        "type": "public_output",
        "label": "Published research note",
    }
    assert card["outcome"]["status"] == "completed"
    assert card["lifecycle"] == "completed"
    assert card["stage"] == "published"
    assert card["salience"] == {"score": 0.8, "level": "high"}
    assert card["evidence_ref"] == {
        "kind": "information_item", "id": 7, "tick": 9,
    }
    assert card["raw_ref"] == {"kind": "event", "id": 12, "tick": 9}
    serialized = json.dumps(card, sort_keys=True)
    assert "body-canary" not in serialized
    assert "payload-canary" not in serialized


def test_historical_activity_never_inherits_current_runtime_telemetry():
    fact = ActivityFact(
        activity_id="runtime:agent:4",
        tick=20,
        kind="provider_call",
        stage="streaming",
        title="Provider call in progress",
        agent_id=4,
        source="runtime",
        evidence_ref={"kind": "runtime", "id": "agent:4", "tick": 20},
    )

    assert project_activity(fact, historical=True) is None
    current = project_activity(fact, historical=False)
    assert current is not None
    assert current["source"] == "runtime"
    assert current["lifecycle"] == "active"


def test_unknown_event_uses_honest_generic_fallback_without_payload():
    card = project_event_activity({
        "id": 44,
        "tick": 5,
        "phase": "FINALIZE",
        "kind": "future_unmapped_event",
        "subject_type": "agent",
        "subject_id": 8,
        "importance": 1.0,
        "payload_json": json.dumps({
            "request_json": "request-canary",
            "response_json": "response-canary",
        }),
    })

    assert card is not None
    assert card["verb"] == "record"
    assert card["semantic_fallback"] is True
    assert card["object"]["label"] == "Recorded future unmapped event"
    assert card["outcome"] == {
        "status": "recorded",
        "label": "Recorded without a specific semantic adapter",
    }
    assert card["raw_ref"] == {"kind": "event", "id": 44, "tick": 5}
    serialized = json.dumps(card, sort_keys=True)
    assert "request-canary" not in serialized
    assert "response-canary" not in serialized


def test_observer_events_reuse_semantic_activity_projection(economy):
    event_id = economy.store.log_event(
        2,
        "future_unmapped_event",
        {"private_body": "observer-canary"},
        phase="FINALIZE",
        subject_type="agent",
        subject_id=1,
        importance=1.5,
    )

    item = build_events(economy.store, as_of_tick=2)["items"][0]
    assert item["id"] == event_id
    assert item["activity"]["raw_ref"] == {
        "kind": "event", "id": event_id, "tick": 2,
    }
    assert item["activity"]["semantic_fallback"] is True
    assert "observer-canary" not in json.dumps(item["activity"], sort_keys=True)

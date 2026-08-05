"""Observer search projection API, privacy, and as-of behavior."""
from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from communications.delivery import CommunicationDelivery
from communications.policy import CommunicationPolicy, MessageField, Principal
from engine.actions import ActionExecutor
from server.projections.search import build_search
from server.v2_api import install_v2_routes
from tests.conftest import make_agent, make_bank


def _search_app(economy, tmp_path):
    economy.config.update({
        "engine_semantics_version": 8,
        "communications": {},
        "operator_workspace": {
            "path": str(tmp_path / "operator.db"),
            "csrf_token": "test-csrf",
        },
    })
    economy.store.set_meta(
        tick=6,
        status="paused",
        phase="FINALIZE",
        config_json=json.dumps(economy.config, sort_keys=True),
    )
    bank_id = make_bank(economy)
    sender_id, _ = make_agent(
        economy, bank_id, name="Atlas", role="supplier_officer", arrived_tick=0)
    make_agent(economy, bank_id, name="Atlas Two", arrived_tick=0)
    future_agent_id, _ = make_agent(
        economy, bank_id, name="Future Citizen", arrived_tick=6)

    current_firm_id = economy.store.insert(
        "firms", name="Atlas Foods", sector="food", status="private", founded_tick=0)
    future_firm_id = economy.store.insert(
        "firms", name="Future Works", sector="construction", status="private", founded_tick=6)
    for marker in range(10):
        economy.store.insert(
            "events", tick=0, phase="SETUP", kind=f"fixture_event_{marker}",
            subject_type=None, subject_id=None, importance=0.0, payload_json="{}")
    current_event_id = economy.store.insert(
        "events", tick=4, phase="MARKET", kind="goods_sale",
        subject_type="firm", subject_id=current_firm_id, importance=1.0,
        payload_json=json.dumps({"private_note": "must never be searched"}),
    )
    future_event_id = economy.store.insert(
        "events", tick=6, phase="EXECUTION", kind="future_signal",
        subject_type="agent", subject_id=future_agent_id, importance=1.0,
        payload_json="{}",
    )
    place_id = economy.store.insert(
        "places",
        place_key="licensing-office-quartz",
        name="Licensing Office Quartz",
        kind="licensing_office",
        owner_type="government",
        owner_id=None,
        x=0.5,
        y=0.5,
        capacity=10,
        created_tick=0,
        metadata_json="{}",
    )
    licensing_event_id = economy.store.insert(
        "events", tick=4, phase="INSTITUTIONS", kind="licensing_visit",
        subject_type="place", subject_id=place_id, importance=0.5,
        payload_json=json.dumps({"place_name": "Licensing Office Quartz"}),
    )

    executor = ActionExecutor(economy)
    private = executor.execute_action(4, sender_id, {
        "type": "send_message",
        "audience": {"kind": "direct", "agent_ids": [future_agent_id]},
        "subject": "Classified merger",
        "body": "Licensing Office Quartz is the private meeting point.",
    })
    public = executor.execute_action(5, sender_id, {
        "type": "send_message",
        "audience": {"kind": "public"},
        "subject": "Public market bulletin",
        "body": "Public information only.",
    })
    assert private["ok"] is True
    assert public["ok"] is True
    delivery = CommunicationDelivery(economy.store, economy.config).deliver_due(6)
    assert delivery["published"] == 1
    economy.store.execute(
        "INSERT OR IGNORE INTO projection_commits (tick,phase,domains_json) "
        "VALUES (6,'FINALIZE','[\"search\"]')")
    economy.store.commit()

    world = SimpleNamespace(
        store=economy.store, config=economy.config, economy=economy)
    app = FastAPI()
    install_v2_routes(app, world, SimpleNamespace())
    return app, {
        "future_agent_id": future_agent_id,
        "future_firm_id": future_firm_id,
        "current_event_id": current_event_id,
        "future_event_id": future_event_id,
        "licensing_event_id": licensing_event_id,
        "private": private,
        "public": public,
    }


def _group(payload: dict, kind: str) -> dict:
    return next(group for group in payload["data"]["groups"] if group["kind"] == kind)


def test_search_is_grouped_deterministic_bounded_and_read_only(economy, tmp_path):
    app, ids = _search_app(economy, tmp_path)
    before = {
        "events": economy.store.scalar("SELECT COUNT(*) FROM events"),
        "ledger_entries": economy.store.scalar("SELECT COUNT(*) FROM ledger_entries"),
        "tick": economy.store.tick,
    }
    with TestClient(app) as client:
        first = client.get("/api/v2/search", params={"q": "Atlas", "limit": 1})
        second = client.get("/api/v2/search", params={"q": "Atlas", "limit": 1})
        assert first.status_code == 200
        assert first.json() == second.json()
        payload = first.json()
        assert payload["projection"] == "search.results"
        assert [group["kind"] for group in payload["data"]["groups"]] == [
            "agent", "firm", "event", "communication_thread"]
        agents = _group(payload, "agent")
        assert agents["items"][0]["label"] == "Atlas"
        assert agents["truncated"] is True
        assert set(agents["items"][0]) == {"kind", "id", "label", "sublabel"}

        exact_id = client.get(
            "/api/v2/search",
            params={"q": str(ids["current_event_id"]), "kinds": "event"},
        ).json()
        assert _group(exact_id, "event")["items"][0]["id"] == ids["current_event_id"]

    after = {
        "events": economy.store.scalar("SELECT COUNT(*) FROM events"),
        "ledger_entries": economy.store.scalar("SELECT COUNT(*) FROM ledger_entries"),
        "tick": economy.store.tick,
    }
    assert after == before
    app.state.operator_workspace.close()


def test_search_respects_tick_existence_and_safe_event_fields(economy, tmp_path):
    app, ids = _search_app(economy, tmp_path)
    with TestClient(app) as client:
        agent_before = client.get(
            "/api/v2/search", params={"q": "Future Citizen", "tick": 5, "kinds": "agent"})
        firm_before = client.get(
            "/api/v2/search", params={"q": "Future Works", "tick": 5, "kinds": "firm"})
        event_before = client.get(
            "/api/v2/search", params={"q": "future_signal", "tick": 5, "kinds": "event"})
        assert _group(agent_before.json(), "agent")["items"] == []
        assert _group(firm_before.json(), "firm")["items"] == []
        assert _group(event_before.json(), "event")["items"] == []

        agent_live = client.get(
            "/api/v2/search", params={"q": "Future Citizen", "kinds": "agent"}).json()
        firm_live = client.get(
            "/api/v2/search", params={"q": "Future Works", "kinds": "firm"}).json()
        event_live = client.get(
            "/api/v2/search", params={"q": "future_signal", "kinds": "event"}).json()
        assert _group(agent_live, "agent")["items"][0]["id"] == ids["future_agent_id"]
        assert _group(firm_live, "firm")["items"][0]["id"] == ids["future_firm_id"]
        event_item = _group(event_live, "event")["items"][0]
        assert event_item["id"] == ids["future_event_id"]
        assert set(event_item) == {"kind", "id", "label", "sublabel"}
        assert "private_note" not in json.dumps(event_live)
    app.state.operator_workspace.close()


def test_search_never_exposes_private_communications_or_places(economy, tmp_path):
    app, _ids = _search_app(economy, tmp_path)
    with TestClient(app) as client:
        private = client.get(
            "/api/v2/search",
            params={"q": "Classified merger", "kinds": "communication_thread"},
        )
        assert private.status_code == 200
        assert _group(private.json(), "communication_thread")["items"] == []
        assert "Classified merger" not in private.text
        assert "Licensing Office Quartz" not in private.text

        before_publish = client.get(
            "/api/v2/search",
            params={
                "q": "Public market bulletin",
                "tick": 5,
                "kinds": "communication_thread",
            },
        ).json()
        assert _group(before_publish, "communication_thread")["items"] == []
        published = client.get(
            "/api/v2/search",
            params={"q": "Public market bulletin", "kinds": "communication_thread"},
        ).json()
        items = _group(published, "communication_thread")["items"]
        assert [item["label"] for item in items] == ["Public market bulletin"]
        assert "body" not in json.dumps(published).lower()

        place = client.get("/api/v2/search", params={"q": "Licensing Office"})
        assert all(not group["items"] for group in place.json()["data"]["groups"])
        assert "Licensing Office Quartz" not in place.text
        licensing_event = client.get(
            "/api/v2/search", params={"q": "licensing_visit", "kinds": "event"})
        assert _group(licensing_event.json(), "event")["items"][0]["id"] == _ids[
            "licensing_event_id"]
        assert "place #" not in licensing_event.text.lower()
        assert "Licensing Office Quartz" not in licensing_event.text
    app.state.operator_workspace.close()


def test_communication_search_checks_every_required_field_gate(
        economy, tmp_path, monkeypatch):
    app, ids = _search_app(economy, tmp_path)
    public_message_id = int(ids["public"]["message_id"])
    observed: set[MessageField] = set()
    original = CommunicationPolicy.can_read_field

    def recording_gate(self, principal, message_id, field, as_of_tick):
        if int(message_id) == public_message_id:
            observed.add(MessageField(field))
        return original(self, principal, message_id, field, as_of_tick)

    monkeypatch.setattr(CommunicationPolicy, "can_read_field", recording_gate)
    result = build_search(
        economy.store,
        Principal("ordinary-dashboard"),
        query="Public market bulletin",
        as_of_tick=6,
        kinds=("communication_thread",),
    )

    assert result["groups"][0]["items"][0]["label"] == "Public market bulletin"
    assert observed == {
        MessageField.EXISTENCE,
        MessageField.SUBJECT,
        MessageField.THREAD_ENTRY,
        MessageField.MESSAGE_URL,
    }
    app.state.operator_workspace.close()


def test_search_rejects_invalid_queries_kinds_and_forks(economy, tmp_path):
    app, _ids = _search_app(economy, tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/v2/search", params={"q": " "}).status_code == 422
        assert client.get("/api/v2/search", params={"q": "  " + "a" * 100 + "  "}).status_code == 200
        assert client.get("/api/v2/search", params={"q": "a" * 101}).status_code == 422
        unknown = client.get(
            "/api/v2/search", params={"q": "Atlas", "kinds": "agent,secret"})
        assert unknown.status_code == 422
        assert unknown.json() == {"detail": "unsupported search kind"}
        assert client.get(
            "/api/v2/search", params={"q": "Atlas", "fork_id": "wrong"}).status_code == 409
    app.state.operator_workspace.close()

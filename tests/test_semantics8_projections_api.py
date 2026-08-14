"""Shared projection, REST authorization, and cursor recovery tests."""
from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from communications.delivery import CommunicationDelivery
from communications.policy import Principal
from engine.actions import ActionExecutor
from server.projections import build_envelope
from server.projections.transport import hello_message, projection_delta_message, recovery_messages
from server.v2_api import install_v2_routes
from tests.conftest import make_agent, make_bank


def _app_fixture(economy, tmp_path):
    economy.config.update({
        "engine_semantics_version": 8,
        "communications": {},
        "operator_workspace": {
            "path": str(tmp_path / "operator.db"),
            "csrf_token": "test-csrf",
        },
    })
    economy.store.set_meta(
        tick=6, status="paused", phase="FINALIZE",
        config_json=json.dumps(economy.config, sort_keys=True))
    bank_id = make_bank(economy)
    sender_id, _ = make_agent(
        economy, bank_id, name="Sender", role="supplier_officer", population_tier="core")
    recipient_id, _ = make_agent(
        economy, bank_id, name="Recipient", population_tier="core")
    outside_id, _ = make_agent(
        economy, bank_id, name="Outside", population_tier="core")
    executor = ActionExecutor(economy)
    private = executor.execute_action(5, sender_id, {
        "type": "send_message",
        "audience": {"kind": "direct", "agent_ids": [recipient_id]},
        "subject": "Private subject",
        "body": "Private body",
    })
    public = executor.execute_action(5, sender_id, {
        "type": "send_message",
        "audience": {"kind": "public"},
        "subject": "Public subject",
        "body": "Public body",
    })
    CommunicationDelivery(economy.store, economy.config).deliver_due(6)
    economy.store.execute(
        "INSERT OR IGNORE INTO projection_commits (tick,phase,domains_json) "
        "VALUES (6,'FINALIZE','[\"summary\",\"events\",\"communications\"]')")
    economy.store.commit()

    world = SimpleNamespace(
        store=economy.store, config=economy.config, economy=economy)
    controller = SimpleNamespace()
    app = FastAPI()
    install_v2_routes(app, world, controller)
    return app, private, public, sender_id, recipient_id, outside_id


def test_envelopes_are_deterministic_and_principal_scoped(economy):
    economy.store.set_meta(
        tick=4, config_json=json.dumps({"engine_semantics_version": 8}))
    economy.store.execute(
        "INSERT INTO projection_commits (tick,phase,domains_json) VALUES (4,'FINALIZE','[]')")
    ordinary = Principal("ordinary")
    agent = Principal("agent:7", agent_id=7)
    first = build_envelope(
        economy.store, ordinary, "test", {"value": 1}, as_of_tick=4)
    second = build_envelope(
        economy.store, ordinary, "test", {"value": 1}, as_of_tick=4)
    agent_view = build_envelope(
        economy.store, agent, "test", {"value": 1}, as_of_tick=4)
    assert first == second
    assert first["semantics_version"] == 8
    assert first["event_cursor"] == 1
    assert first["view_key"] != agent_view["view_key"]
    assert "ordinary" not in first["view_key"]
    assert "agent:7" not in agent_view["view_key"]


def test_rest_message_views_are_as_of_authorized_and_uniformly_hidden(economy, tmp_path):
    app, private, public, sender_id, recipient_id, outside_id = _app_fixture(economy, tmp_path)
    with TestClient(app) as client:
        denied = client.get(f"/api/v2/communications/messages/{private['message_id']}")
        assert denied.status_code == 404
        assert denied.json() == {"detail": "message not found"}
        before = client.get(
            f"/api/v2/communications/messages/{private['message_id']}",
            params={"agent_id": recipient_id, "tick": 5})
        assert before.status_code == 404
        outside = client.get(
            f"/api/v2/communications/messages/{private['message_id']}",
            params={"agent_id": outside_id})
        assert outside.status_code == 404

        recipient = client.get(
            f"/api/v2/communications/messages/{private['message_id']}",
            params={"agent_id": recipient_id}).json()
        assert recipient["data"]["body_text"] == "Private body"
        assert recipient["data"]["access_basis"] == "direct_delivery"
        assert recipient["data"]["deliveries"][0]["recipient_agent_id"] == recipient_id

        sender = client.get(
            f"/api/v2/communications/messages/{private['message_id']}",
            params={"agent_id": sender_id}).json()
        assert sender["data"]["audience"] == [{"kind": "direct", "agent_id": recipient_id}]
        assert sender["data"]["status"] == "delivered"

        published = client.get(
            f"/api/v2/communications/messages/{public['message_id']}").json()
        assert published["data"]["body_text"] == "Public body"
        assert published["data"]["access_basis"] == "public_release"
        public_before = client.get(
            f"/api/v2/communications/messages/{public['message_id']}",
            params={"tick": 5})
        assert public_before.status_code == 404

        ordinary_threads = client.get("/api/v2/communications/threads").json()["data"]
        assert [item["subject"] for item in ordinary_threads["items"]] == ["Public subject"]
        recipient_threads = client.get(
            "/api/v2/communications/threads", params={"agent_id": recipient_id}).json()["data"]
        assert {item["subject"] for item in recipient_threads["items"]} == {
            "Private subject", "Public subject"}

        summary_before = client.get(
            "/api/v2/communications/summary", params={"tick": 5}).json()["data"]
        summary_after = client.get(
            "/api/v2/communications/summary", params={"tick": 6}).json()["data"]
        assert summary_before == {"total": 2, "published": 0, "private_total": 1}
        assert summary_after == {"total": 2, "published": 1, "private_total": 1}

        truth = client.get(
            f"/api/v2/communications/messages/{private['message_id']}",
            params={"truth": True}, headers={"X-Operator-Id": "investigator"})
        assert truth.status_code == 200
        assert truth.json()["data"]["access_basis"] == "operator_truth"
        audit = app.state.operator_workspace.conn.execute(
            "SELECT action,owner_id,stable_ref_json FROM operator_audit").fetchone()
        assert audit["action"] == "truth_inspect"
        assert audit["owner_id"] == "investigator"
        assert "Private body" not in str(audit["stable_ref_json"])
    app.state.operator_workspace.close()


def test_snapshot_backfill_websocket_lineage_and_operator_api(economy, tmp_path):
    app, _private, _public, _sender, recipient_id, _outside = _app_fixture(economy, tmp_path)
    with TestClient(app) as client:
        snapshot = client.get("/api/v2/snapshot").json()
        assert snapshot["projection"] == "world.snapshot"
        assert snapshot["data"]["summary"]["ledger_balance"] == 0
        assert snapshot["data"]["communications"]["total"] == 2
        scoped = client.get(
            "/api/v2/snapshot", params={"agent_id": recipient_id}).json()
        assert scoped["view_key"] != snapshot["view_key"]

        backfill = client.get("/api/v2/backfill", params={"after": 0}).json()["data"]
        assert [item["event_cursor"] for item in backfill["commits"]] == [1, 2]
        assert backfill["commits"][1]["previous_event_cursor"] == 1

        assert client.post(
            "/api/v2/operator/investigations", json={"title": "Denied"}).status_code == 403
        created = client.post(
            "/api/v2/operator/investigations",
            headers={"X-CSRF-Token": "test-csrf"},
            json={"title": "Shipment warning"})
        assert created.status_code == 200
        record = created.json()
        conflict = client.patch(
            f"/api/v2/operator/investigations/{record['id']}",
            headers={"X-CSRF-Token": "test-csrf"},
            json={"expected_version": 2, "title": "Stale"})
        assert conflict.status_code == 409
        item = client.post(
            f"/api/v2/operator/investigations/{record['id']}/items",
            headers={"X-CSRF-Token": "test-csrf"},
            json={"item_kind": "event", "stable_ref": {"kind": "event", "id": 1},
                  "note": "Observed consequence"})
        assert item.status_code == 200
        exported = client.get(
            f"/api/v2/operator/investigations/{record['id']}/export").json()
        assert exported["json"]["redaction_manifest"]["private_message_bodies"] == "not_copied"
        assert "Observed consequence" in exported["markdown"]

    hello = hello_message(economy.store, status="paused")
    delta = projection_delta_message(economy.store, tick=6)
    assert hello["type"] == "hello"
    assert delta["type"] == "projection_delta"
    # Tick 6 commits twice (INBOX_DELIVERY -> 1, FINALIZE -> 2) and exactly one
    # delta is emitted per tick, carrying that tick's LAST cursor. So the cursor
    # a client holds before this delta is the last one of the PREVIOUS tick --
    # here none, hence 0. Chaining to the intra-tick commit 1 was the old
    # behaviour and it was a defect: no client is ever sent cursor 1, so every
    # live delta failed the client's continuity check and was discarded.
    assert delta["previous_event_cursor"] == 0
    assert delta["event_cursor"] == 2
    assert recovery_messages(economy.store, after_cursor=2)[0]["type"] == "heartbeat"
    assert recovery_messages(economy.store, after_cursor=999)[0]["code"] == "cursor_ahead"
    recovered = recovery_messages(economy.store, after_cursor=0)
    assert [message["event_cursor"] for message in recovered] == [1, 2]
    app.state.operator_workspace.close()


def test_live_deltas_chain_across_ticks_so_no_client_sees_a_gap(economy):
    """The delta stream must be continuous for the client's own continuity rule.

    A client applies a delta only when `previous_event_cursor` equals the cursor
    it currently holds (dashboard/src/app/cursorReducer.js). It holds whatever
    the last delta gave it, and one delta is emitted per tick carrying that
    tick's final cursor -- so `previous_event_cursor` has to be the previous
    TICK's final cursor, not the previous commit.

    Every tick commits more than once in practice, so resolving `previous` to
    the previous commit put an intra-tick cursor there that no client had ever
    been sent, and the payload was discarded and re-handshaked on every tick.
    """
    economy.store.set_meta(
        tick=9, config_json=json.dumps({"engine_semantics_version": 8}))
    for tick in (7, 8, 9):
        for phase in ("INBOX_DELIVERY", "FINALIZE"):
            economy.store.execute(
                "INSERT INTO projection_commits (tick,phase,domains_json) "
                "VALUES (?,?,'[]')", (tick, phase))
    economy.store.commit()

    held = None
    for tick in (7, 8, 9):
        delta = projection_delta_message(economy.store, tick=tick)
        if held is not None:
            assert delta["previous_event_cursor"] == held, (
                f"tick {tick} delta claims previous "
                f"{delta['previous_event_cursor']} but the client holds {held}")
        assert delta["event_cursor"] > (held or 0)
        held = delta["event_cursor"]

    # And each tick's delta carries that tick's LAST cursor, which is what makes
    # the previous-tick rule the correct one.
    last_of_eight = economy.store.scalar(
        "SELECT MAX(cursor) FROM projection_commits WHERE tick=8", default=0)
    assert projection_delta_message(
        economy.store, tick=8)["event_cursor"] == last_of_eight

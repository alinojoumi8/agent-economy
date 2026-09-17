import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from server.projections.city_conversations import build_city_conversations, MESSAGE_LIMIT, TEXT_LIMIT
from server.v2_api import install_v2_routes
from tests.conftest import make_agent, make_bank


@pytest.fixture
def recorded_day(economy):
    bank = make_bank(economy)
    first, _ = make_agent(economy, bank, "First speaker", 0)
    second, _ = make_agent(economy, bank, "Second speaker", 0)
    future, _ = make_agent(economy, bank, "FUTURE-SPEAKER", 0)
    store = economy.store
    store.update("agents", future, arrived_tick=4)
    conversation = store.insert("conversations", tick=2, participant_ids=json.dumps([first, second]), topic="Recorded topic")
    store.insert("messages", conv_id=conversation, tick=2, agent_id=first, text="Recorded words", seq=0)
    store.insert("messages", conv_id=conversation, tick=4, agent_id=second, text="FUTURE-MESSAGE", seq=1)
    store.insert("messages", conv_id=conversation, tick=2, agent_id=future, text="FUTURE-AUTHOR", seq=2)
    store.insert("conversations", tick=4, participant_ids=json.dumps([first, second]), topic="FUTURE-CONVERSATION")
    store.insert("conversations", tick=2, participant_ids=json.dumps([first, future]), topic="FUTURE-PARTICIPANT")
    store.insert("conversations", tick=2, participant_ids="invalid JSON", topic="MALFORMED")
    store.set_meta(tick=4, active_tick=None, status="paused")
    return economy, conversation, first


def test_recorded_day_excludes_future_transcripts_and_preserves_source(recorded_day):
    economy, conversation, first = recorded_day
    before = economy.store.conn.total_changes
    data = build_city_conversations(economy.store, as_of_tick=2)
    assert data["tick"] == 2 and data["source"] == "recorded_small_talk"
    assert [item["id"] for item in data["items"]] == [conversation]
    assert data["items"][0]["messages"] == [
        {"agent_id": first, "name": "First speaker", "text": "Recorded words", "seq": 0, "text_truncated": False}]
    assert "FUTURE" not in json.dumps(data) and "MALFORMED" not in json.dumps(data)
    assert not data["content_truncated"] and not data["has_more"]
    assert economy.store.conn.total_changes == before
    assert build_city_conversations(economy.store, as_of_tick=3)["items"] == []


def test_transcript_limits_disclose_omissions_and_keep_stable_order(recorded_day):
    economy, conversation, first = recorded_day
    store = economy.store
    store.update("conversations", conversation, topic="T" * 600)
    for seq in range(1, MESSAGE_LIMIT + 2):
        store.insert("messages", conv_id=conversation, tick=2, agent_id=first, text="x" * (TEXT_LIMIT + 1), seq=seq)
    older = store.insert("conversations", tick=2, participant_ids=json.dumps([first]), topic="Newer id")
    data = build_city_conversations(store, as_of_tick=2, limit=1)
    assert data["items"][0]["id"] == older and data["has_more"]
    data = build_city_conversations(store, as_of_tick=2)
    item = data["items"][1]
    assert data["content_truncated"] and item["messages_truncated"] and item["topic_truncated"]
    assert len(item["messages"]) == MESSAGE_LIMIT
    assert item["messages"][0]["text"] == "Recorded words"
    assert len(item["messages"][1]["text"]) == TEXT_LIMIT and item["messages"][1]["text_truncated"]
    assert store.scalar("SELECT length(text) FROM messages WHERE conv_id=? AND seq=3", (conversation,)) == TEXT_LIMIT + 1


def test_city_transcripts_enforce_run_lineage_and_read_only_contract(recorded_day):
    economy, _, _ = recorded_day
    app = FastAPI()
    install_v2_routes(app, SimpleNamespace(store=economy.store, config=economy.config, economy=economy),
                      SimpleNamespace(hosted_safe=False))
    try:
        with TestClient(app) as client:
            before = economy.store.conn.total_changes
            response = client.get("/api/v2/city/conversations?tick=2")
            assert response.status_code == 200, response.text
            frame = response.json()
            assert frame["run_id"] == "test" and frame["fork_id"] is None and frame["tick"] == 2
            assert frame["projection"] == "city.conversations" and frame["view_key"]
            assert client.get("/api/v2/city/conversations?tick=5").status_code == 409
            assert client.get("/api/v2/city/conversations?fork_id=foreign").status_code == 409
            assert client.get("/api/v2/city/conversations?limit=201").status_code == 422
            assert client.post("/api/v2/city/conversations", json={}).status_code == 405
            assert economy.store.conn.total_changes == before
            economy.store.set_meta(parent_run_id="parent", fork_tick=1)
            forked = client.get("/api/v2/city/conversations?tick=2&fork_id=test")
            assert forked.status_code == 200 and forked.json()["fork_id"] == "test"
    finally:
        app.state.operator_workspace.close()

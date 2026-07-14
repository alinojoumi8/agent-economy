"""Literal PRD R5 coverage: daily grounded news and searchable conversations."""
import asyncio
import json

from fastapi.testclient import TestClient

from engine.store import Store
from server.app import create_app
from world.loop import World


def _world(tmp_path, name="information.db", **over) -> World:
    config = {
        "seed": 42,
        "population": {"size": 14},
        "banks": {"count": 2},
        "firms": {"count": 3, "listed": 1},
        "budget": {
            "cap_usd": 200.0,
            "oracle_reserve_usd": 10.0,
            "conversation_pairs": 4,
            "thresholds": [0.60, 0.80, 0.95],
        },
        "llm": {
            "default_route": {"provider": "scripted", "model": "scripted"},
            "routes": {},
        },
        "checkpoint_every": 0,
        "information": {"daily_news_required": True},
        "outlets": [
            {"id": 1, "name": "The Ledger", "slant": "pro-market-sensational"},
            {"id": 2, "name": "Commons Dispatch", "slant": "cautious-pro-labor"},
        ],
    }
    config.update(over)
    store = Store(str(tmp_path / name))
    store.init_run_meta(name, config["seed"], config)
    world = World(store, config)
    world.initialize()
    return world


def test_daily_news_fails_closed_to_same_day_grounded_briefs(tmp_path):
    world = _world(tmp_path, "daily-news.db")

    # Invoke an otherwise empty newsroom day directly. The daily contract must
    # persist one true quiet-day fact and let both differently slanted outlets
    # publish from that local source.
    asyncio.run(world.newsroom.publish(1))
    articles = world.store.query(
        "SELECT * FROM news_articles WHERE tick=1 ORDER BY outlet_id")
    assert [row["outlet_name"] for row in articles] == [
        "The Ledger", "Commons Dispatch"]
    assert int(world.store.scalar(
        "SELECT COUNT(*) FROM events WHERE tick=1 AND kind='quiet_day'", default=0)) == 1
    for article in articles:
        source_ids = json.loads(article["source_event_ids"])
        assert source_ids
        for event_id in source_ids:
            event = world.store.query_one("SELECT tick FROM events WHERE id=?", (event_id,))
            assert event and int(event["tick"]) == 1

    # Phase retry/resume remains idempotent.
    asyncio.run(world.newsroom.publish(1))
    assert int(world.store.scalar(
        "SELECT COUNT(*) FROM news_articles WHERE tick=1", default=0)) == 2
    assert int(world.store.scalar(
        "SELECT COUNT(*) FROM events WHERE tick=1 AND kind='quiet_day'", default=0)) == 1
    world.store.close()


def test_daily_news_never_promotes_private_audit_events(tmp_path):
    world = _world(tmp_path, "private-news.db")
    secret = "private-liquidity-belief-9f8a"
    world.store.log_event(
        1, "belief_updated", {"agent_id": 1, "belief": secret},
        phase="MEMORY", importance=5.0)
    world.store.log_event(
        1, "participant_control_acquired", {"agent_id": 1, "detail": secret},
        phase="CONTROL", importance=5.0)
    world.store.commit()

    # Private/operational rows are not eligible even at high importance.  With
    # no public fact on the tick, desks receive only the engine's quiet-day fact.
    assert world.newsroom._salient_events(1) == []
    assert world.newsroom._daily_events(1) == []
    asyncio.run(world.newsroom.publish(1))
    articles = world.store.query(
        "SELECT headline,body,source_event_ids FROM news_articles WHERE tick=1")
    assert len(articles) == 2
    assert secret not in " ".join(
        str(row["headline"]) + " " + str(row["body"]) for row in articles)
    for row in articles:
        source_ids = json.loads(row["source_event_ids"])
        assert source_ids
        assert {
            world.store.scalar("SELECT kind FROM events WHERE id=?", (event_id,))
            for event_id in source_ids
        } == {"quiet_day"}
    world.store.close()


def test_news_grounding_rejects_a_mixed_valid_and_dangling_source_list(tmp_path):
    world = _world(tmp_path, "mixed-citations.db")
    event_id = world.store.log_event(
        2, "production", {"firm_id": 1, "units": 4, "private_note": "hidden"},
        phase="NIGHT_CLOSE", importance=1.0)
    world.store.commit()
    events = world.newsroom._daily_events(2)
    assert [event["id"] for event in events] == [event_id]
    assert events[0]["payload"] == {"firm_id": 1, "units": 4}

    grounded = world.newsroom._ground_article(
        world.newsroom.outlets[0], {
            "headline": "Provider claims unsupported details",
            "body": "This sentence may rely on a fabricated source.",
            "source_event_ids": [event_id, 999_999],
        }, events)

    assert grounded["headline"].startswith("The Ledger daily brief:")
    assert grounded["source_event_ids"] == [event_id]
    assert "fabricated source" not in grounded["body"]
    world.store.close()


def test_news_grounding_falls_back_on_malformed_article_fields(tmp_path):
    world = _world(tmp_path, "malformed-article.db")
    event_id = world.store.log_event(
        3, "production", {"firm_id": 1, "units": 2},
        phase="NIGHT_CLOSE", importance=2.0)
    world.store.commit()
    events = world.newsroom._salient_events(3)

    malformed_articles = (
        {"headline": 1, "body": "body", "tone": 0.0,
         "slant_tags": ["neutral"], "source_event_ids": [event_id]},
        {"headline": "headline", "body": "body", "tone": 0.0,
         "slant_tags": 1, "source_event_ids": [event_id]},
        {"headline": "headline", "body": "body", "tone": "loud",
         "slant_tags": ["neutral"], "source_event_ids": [event_id]},
    )
    for malformed in malformed_articles:
        grounded = world.newsroom._ground_article(
            world.newsroom.outlets[0], malformed, events, directive="alarm")
        assert grounded["headline"].startswith("The Ledger daily brief:")
        assert grounded["source_event_ids"] == [event_id]

    world.store.close()


def test_conversation_api_searches_full_stored_run_with_safe_filters(tmp_path):
    world = _world(tmp_path, "conversation-search.db")
    agents = world.store.query("SELECT id,name FROM agents ORDER BY id LIMIT 3")
    first, second, third = agents

    matching = world.store.insert(
        "conversations", tick=7,
        participant_ids=json.dumps([int(first["id"]), int(second["id"])]),
        topic="confidence in local banks")
    world.store.insert(
        "messages", conv_id=matching, tick=7, agent_id=int(first["id"]), seq=0,
        text="I heard a uniquely searchable liquidity warning.")
    world.store.insert(
        "messages", conv_id=matching, tick=7, agent_id=int(second["id"]), seq=1,
        text="Let us verify it against the event spine.")

    other = world.store.insert(
        "conversations", tick=9,
        participant_ids=json.dumps([int(second["id"]), int(third["id"])]),
        topic="grocery prices")
    world.store.insert(
        "messages", conv_id=other, tick=9, agent_id=int(third["id"]), seq=0,
        text="Bread prices look ordinary today.")
    world.store.commit()

    with TestClient(create_app(world)) as client:
        by_text = client.get("/api/conversations", params={
            "q": "uniquely searchable", "limit": 50}).json()
        assert [item["id"] for item in by_text] == [matching]
        assert by_text[0]["topic"] == "confidence in local banks"

        by_topic = client.get("/api/conversations", params={"q": "local banks"}).json()
        assert [item["id"] for item in by_topic] == [matching]

        by_speaker = client.get(
            "/api/conversations", params={"q": first["name"]}).json()
        assert [item["id"] for item in by_speaker] == [matching]

        by_agent_and_tick = client.get("/api/conversations", params={
            "agent_id": int(second["id"]), "tick_from": 8, "tick_to": 10,
        }).json()
        assert [item["id"] for item in by_agent_and_tick] == [other]

        literal_wildcard = client.get(
            "/api/conversations", params={"q": "%"}).json()
        assert literal_wildcard == []

        invalid_range = client.get("/api/conversations", params={
            "tick_from": 10, "tick_to": 5})
        assert invalid_range.status_code == 422

    world.store.close()

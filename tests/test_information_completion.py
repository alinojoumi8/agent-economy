"""Literal PRD R5 coverage: daily grounded news and searchable conversations."""
import asyncio
import json
import sqlite3

from fastapi.testclient import TestClient
import pytest

from engine.store import Store
from llm.gateway import LLMRequest, ReplayReferenceError
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


def test_news_grounding_labels_an_empty_citation_failure(tmp_path):
    world = _world(
        tmp_path, "missing-citation.db",
        beliefs={"model_grounding_from_tick": 1},
    )
    event_id = world.store.log_event(
        1, "production", {"firm_id": 1, "units": 4},
        phase="NIGHT_CLOSE", importance=1.0,
    )
    world.store.commit()

    article = world.newsroom._ground_article(
        world.newsroom.outlets[0],
        {
            "headline": "Production reached 4 units",
            "body": "The recorded total was 4.",
            "source_event_ids": [],
            "slant_tags": ["market"],
            "tone": 0.0,
        },
        world.newsroom._daily_events(1),
        grounding_tick=1,
    )

    assert article["source_event_ids"] == [event_id]
    assert article["numeric_claims_redacted"] is True
    assert article["numeric_claims_redaction_reason"] == "missing_source_citation"
    world.close()


def test_news_rejects_editor_arithmetic_and_api_projects_stored_rows_safely(
        tmp_path):
    active = _world(
        tmp_path,
        "numeric-news-active.db",
        beliefs={"model_grounding_from_tick": 2},
    )
    event_id = active.store.log_event(
        2,
        "production",
        {"firm_id": 1, "units": 4},
        phase="NIGHT_CLOSE",
        importance=1.0,
    )
    active.store.commit()
    events = active.newsroom._daily_events(2)
    unsupported = {
        "headline": "Firm 1 reports a 987654321% output lead",
        "body": "The company says its lead reached 987654321%.",
        "source_event_ids": [event_id],
        "slant_tags": ["market"],
        "tone": 0.2,
    }

    rejected = active.newsroom._ground_article(
        active.newsroom.outlets[0], unsupported, events, grounding_tick=2)
    supported = active.newsroom._ground_article(
        active.newsroom.outlets[0], {
            **unsupported,
            "headline": "Firm 1 produced 4 units",
            "body": "The recorded production event lists 4 units.",
        }, events, grounding_tick=2)

    assert rejected["headline"] == "The Ledger daily brief: production"
    assert "987654321" not in rejected["headline"] + rejected["body"]
    assert supported["headline"] == "Firm 1 produced 4 units"

    active.store.insert(
        "news_articles",
        tick=2,
        outlet_id=1,
        outlet_name="The Ledger",
        headline=unsupported["headline"],
        body=unsupported["body"],
        source_event_ids=json.dumps([event_id]),
        slant_tags=json.dumps(["market"]),
        tone=0.2,
        truthful=1,
    )
    active.store.set_meta(
        status="paused", tick=1, active_tick=2, next_phase="MORNING")
    active.store.commit()
    with TestClient(create_app(active)) as client:
        projected = client.get("/api/news").json()[0]
    assert projected["numeric_claims_redacted"] is True
    assert projected["numeric_claims_redaction_reason"] == (
        "ungrounded_numeric_claim")
    assert "987654321" not in projected["headline"] + projected["body"]
    active.close()

    legacy = _world(tmp_path, "numeric-news-legacy.db")
    legacy_event = legacy.store.log_event(
        2,
        "production",
        {"firm_id": 1, "units": 4},
        phase="NIGHT_CLOSE",
        importance=1.0,
    )
    legacy.store.commit()
    legacy_article = legacy.newsroom._ground_article(
        legacy.newsroom.outlets[0],
        {**unsupported, "source_event_ids": [legacy_event]},
        legacy.newsroom._daily_events(2),
        grounding_tick=2,
    )
    assert legacy_article["headline"] == unsupported["headline"]
    legacy.close()


def test_news_projection_retains_safe_field_when_other_numeric_field_is_redacted(
        tmp_path):
    world = _world(
        tmp_path,
        "numeric-news-partial.db",
        beliefs={"model_grounding_from_tick": 1},
    )
    event_id = world.store.log_event(
        1,
        "production",
        {"firm_id": 1, "units": 4},
        phase="NIGHT_CLOSE",
        importance=1.0,
    )
    world.store.commit()

    projected = world.newsroom.public_article_projection({
        "outlet_name": "The Ledger",
        "headline": "Output surged 987654321%",
        "body": "A cautious production update remains available.",
        "source_event_ids": [event_id],
        "slant_tags": [],
    }, enforcement_tick=1)

    assert projected["headline"] == ""
    assert projected["body"] == "A cautious production update remains available."
    assert projected["numeric_claims_redacted"] is True
    assert projected["numeric_claims_redaction_reason"] == (
        "ungrounded_numeric_claim")
    world.close()


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


def _duplicate_news_replay(tmp_path, prefix, *, full_payload_duplicate=False):
    source = _world(tmp_path, f"{prefix}-source.db")

    def default_event(world, loan_id):
        return world.store.log_event(
            301, "loan_default", {
                "bank_id": 1,
                "loan_id": loan_id,
                "borrower_id": loan_id + 1_000,
            }, phase="NIGHT_CLOSE", subject_type="bank", subject_id=1,
            importance=3.0)

    source_first = default_event(source, 901)
    source_second = default_event(source, 902)
    source_events = source.newsroom._salient_events(301)
    assert [event["id"] for event in source_events] == [
        source_first, source_second]
    assert source_events[0]["payload"] == {"bank_id": 1}
    assert source_events[1]["payload"] == {"bank_id": 1}

    # The persisted editor context is the authoritative source digest. An event
    # written after this call must not be retroactively treated as prompt input.
    for outlet in source.newsroom.outlets:
        source_drafts = asyncio.run(source.newsroom._report_stories(
            301, outlet, source_events))
        asyncio.run(source.newsroom._write_story(
            301, outlet, source_events, None, drafts=source_drafts))
    unadvertised_source = default_event(source, 903)
    source_full_duplicate = (
        default_event(source, 901) if full_payload_duplicate else None)
    source.store.commit()
    source_path = source.store.path
    source.store.close()

    replay = _world(tmp_path, f"{prefix}-replay.db")
    replay.store.log_event(
        301, "belief_updated", {"agent_id": 1, "belief": "private"},
        phase="MEMORY", importance=5.0)
    local_first = default_event(replay, 901)
    local_second = default_event(replay, 902)
    local_full_duplicate = (
        default_event(replay, 901) if full_payload_duplicate else None)
    replay.store.commit()
    local_events = replay.newsroom._salient_events(301)
    expected_local_ids = [local_first, local_second]
    if local_full_duplicate is not None:
        expected_local_ids.append(local_full_duplicate)
    assert [event["id"] for event in local_events] == expected_local_ids
    assert local_first != source_first

    source_conn = sqlite3.connect(source_path)
    source_conn.row_factory = sqlite3.Row
    replay.gateway.replay_conn = source_conn
    return replay, source_conn, {
        "source_first": source_first,
        "source_second": source_second,
        "unadvertised_source": unadvertised_source,
        "local_first": local_first,
        "local_second": local_second,
        "source_full_duplicate": source_full_duplicate,
        "local_full_duplicate": local_full_duplicate,
        "local_events": local_events,
    }


def test_replay_newsroom_maps_public_duplicate_citations_by_occurrence(tmp_path):
    replay, source_conn, ids = _duplicate_news_replay(tmp_path, "ordinal")
    try:
        assert replay.newsroom._logical_source_event_id(
            ids["source_first"], ids["local_events"]) == ids["local_first"]
        assert replay.newsroom._logical_source_event_id(
            ids["source_second"], ids["local_events"]) == ids["local_second"]

        grounded = replay.newsroom._ground_article(
            replay.newsroom.outlets[0], {
                "headline": "A recorded default",
                "body": "The cited bank recorded a default.",
                "tone": -0.4,
                "slant_tags": ["credit"],
                "source_event_ids": [ids["source_first"], ids["source_second"]],
            }, ids["local_events"])
        assert grounded["headline"] == "A recorded default"
        assert grounded["source_event_ids"] == [
            ids["local_first"], ids["local_second"]]

        # Gateway provenance uses the complete payload, so the private loan IDs
        # keep these same-public-payload events individually collision-safe.
        assert replay.gateway._local_event_id_for_replay(
            ids["source_first"]) == ids["local_first"]
        assert replay.gateway._local_event_id_for_replay(
            ids["source_second"]) == ids["local_second"]
    finally:
        replay.gateway.replay_conn = None
        source_conn.close()
        replay.store.close()


def test_replay_newsroom_duplicate_mismatches_fail_closed(tmp_path):
    replay, source_conn, ids = _duplicate_news_replay(tmp_path, "mismatch")
    try:
        article = {
            "headline": "A recorded default",
            "body": "The cited bank recorded a default.",
            "tone": -0.4,
            "slant_tags": ["credit"],
            "source_event_ids": [ids["source_second"]],
        }
        with pytest.raises(ReplayReferenceError, match="cardinality mismatch"):
            replay.newsroom._ground_article(
                replay.newsroom.outlets[0], article, ids["local_events"][:1])
        assert replay.newsroom._logical_source_event_id(
            ids["unadvertised_source"], ids["local_events"]) is None
        assert replay.newsroom._logical_source_event_id(
            999_999, ids["local_events"]) is None
        invalid_recorded = dict(article, source_event_ids=[999_999])
        fallback = replay.newsroom._ground_article(
            replay.newsroom.outlets[0], invalid_recorded, ids["local_events"])
        assert fallback["headline"].startswith("The Ledger daily brief:")
        assert fallback["source_event_ids"] == [ids["local_first"]]

        # Extra local occurrences cannot change which prefix occurrence the
        # recorded first event denotes; final replay verification catches the
        # extra row independently.
        replay.store.log_event(
            301, "loan_default", {
                "bank_id": 1, "loan_id": 901, "borrower_id": 1_901,
            }, phase="NIGHT_CLOSE", subject_type="bank", subject_id=1,
            importance=3.0)
        replay.store.commit()
        assert replay.gateway._local_event_id_for_replay(
            ids["source_first"]) == ids["local_first"]
        with pytest.raises(ReplayReferenceError, match="ordinal 0 is unavailable"):
            replay.gateway._local_event_id_for_replay(
                ids["unadvertised_source"])
        with pytest.raises(ReplayReferenceError, match="dangling in source"):
            replay.gateway._local_event_id_for_replay(999_999)
    finally:
        replay.gateway.replay_conn = None
        source_conn.close()
        replay.store.close()


def test_gateway_maps_equal_full_payload_duplicates_by_occurrence(tmp_path):
    replay, source_conn, ids = _duplicate_news_replay(
        tmp_path, "gateway-ordinal", full_payload_duplicate=True)
    try:
        assert replay.gateway._local_event_id_for_replay(
            ids["source_first"]) == ids["local_first"]
        assert replay.gateway._local_event_id_for_replay(
            ids["source_full_duplicate"]) == ids["local_full_duplicate"]
    finally:
        replay.gateway.replay_conn = None
        source_conn.close()
        replay.store.close()


def test_gateway_ordinal_ignores_a_later_same_tick_source_duplicate(tmp_path):
    replay, source_conn, ids = _duplicate_news_replay(
        tmp_path, "gateway-later", full_payload_duplicate=True)
    try:
        replay.store.execute(
            "DELETE FROM events WHERE id=?", (ids["local_full_duplicate"],))
        replay.store.commit()

        # The later finalized-source row was not present when the first response
        # was produced, so it cannot invalidate the first occurrence mapping.
        assert replay.gateway._local_event_id_for_replay(
            ids["source_first"]) == ids["local_first"]
        with pytest.raises(ReplayReferenceError, match="ordinal 1 is unavailable"):
            replay.gateway._local_event_id_for_replay(
                ids["source_full_duplicate"])
    finally:
        replay.gateway.replay_conn = None
        source_conn.close()
        replay.store.close()


def test_replay_recorded_dangling_newsroom_citation_reuses_brief_fallback(
        tmp_path):
    replay, source_conn, ids = _duplicate_news_replay(
        tmp_path, "recorded-dangling")
    try:
        recorded_article = {
            "headline": "Unsupported recorded story",
            "body": "This model response cited an event it was never shown.",
            "tone": -0.8,
            "slant_tags": ["alarm"],
            "source_event_ids": [999_999],
        }
        source_conn.execute(
            "UPDATE llm_calls SET response_json=? "
            "WHERE tick=301 AND purpose='newsroom'",
            (json.dumps({
                "text": json.dumps(recorded_article),
                "raw": {},
                "cached_in_tokens": 0,
            }),))
        source_conn.commit()
        replay.gateway.replay = True

        replayed_article = asyncio.run(replay.newsroom._write_story(
            301, replay.newsroom.outlets[0], ids["local_events"], None,
            drafts=[]))
        assert replayed_article["headline"].startswith("The Ledger daily brief:")
        assert replayed_article["source_event_ids"] == [ids["local_first"]]
        assert replay.gateway._live_dispatch_count == 0
    finally:
        replay.gateway.replay_conn = None
        source_conn.close()
        replay.store.close()


def test_replay_reference_failure_is_not_swallowed_as_decision_error(
        tmp_path, monkeypatch):
    replay, source_conn, ids = _duplicate_news_replay(tmp_path, "fail-fast")
    try:
        agent = replay.store.query_one("SELECT * FROM agents ORDER BY id LIMIT 1")
        monkeypatch.setattr(
            replay.runtime.scheduler, "scheduled_agents",
            lambda *args, **kwargs: [agent])

        async def dangling_decision(*args, **kwargs):
            replay.gateway._local_event_id_for_replay(
                ids["unadvertised_source"])

        monkeypatch.setattr(replay.runtime, "_decide_one", dangling_decision)
        with pytest.raises(ReplayReferenceError, match="ordinal 0 is unavailable"):
            asyncio.run(replay.runtime.decide_all(301))
        assert replay.gateway._live_dispatch_count == 0
        assert replay.store.scalar(
            "SELECT COUNT(*) FROM events WHERE kind='decision_error'", default=0) == 0
    finally:
        replay.gateway.replay_conn = None
        source_conn.close()
        replay.store.close()


def test_dangling_source_event_retries_same_replay_call_without_execution(
        tmp_path, monkeypatch):
    replay, source_conn, ids = _duplicate_news_replay(
        tmp_path, "dangling-source-resume")
    try:
        source_call = source_conn.execute(
            "SELECT * FROM llm_calls WHERE tick=301 AND purpose='newsroom' "
            "ORDER BY id LIMIT 1").fetchone()
        assert source_call is not None
        source_max = int(source_conn.execute(
            "SELECT COALESCE(MAX(id), 0) FROM events").fetchone()[0])
        local_max = int(replay.store.scalar(
            "SELECT COALESCE(MAX(id), 0) FROM events", default=0))
        dangling_id = max(source_max, local_max) + 1
        assert source_conn.execute(
            "SELECT id FROM events WHERE id=?", (dangling_id,)).fetchone() is None
        assert replay.store.query_one(
            "SELECT id FROM events WHERE id=?", (dangling_id,)) is None

        dangling_response = json.loads(source_call["response_json"])
        dangling_response["text"] = json.dumps({
            "reasoning": "corrupt recorded provenance",
            "request_event_id": dangling_id,
            "actions": [],
        })
        source_conn.execute(
            "UPDATE llm_calls SET response_json=? WHERE id=?",
            (json.dumps(dangling_response), int(source_call["id"])))

        valid_response = dict(dangling_response)
        valid_response["text"] = json.dumps({
            "reasoning": "later duplicate must never mask the corrupt call",
            "request_event_id": ids["source_first"],
            "actions": [],
        })
        source_conn.execute(
            "INSERT INTO llm_calls ("
            "tick,agent_id,role,provider,model,purpose,cache_key,request_json,"
            "response_json,in_tokens,out_tokens,cached,cost_usd,latency_ms,created_at"
            ") SELECT tick,agent_id,role,provider,model,purpose,cache_key,request_json,"
            "?,in_tokens,out_tokens,cached,cost_usd,latency_ms,created_at "
            "FROM llm_calls WHERE id=?",
            (json.dumps(valid_response), int(source_call["id"])))
        source_conn.commit()

        req = LLMRequest(
            role=str(source_call["role"]), purpose=str(source_call["purpose"]),
            agent_id=source_call["agent_id"], tick=int(source_call["tick"]))
        cache_key = str(source_call["cache_key"])

        agent = replay.store.query_one("SELECT * FROM agents ORDER BY id LIMIT 1")
        monkeypatch.setattr(
            replay.runtime.scheduler, "scheduled_agents",
            lambda *args, **kwargs: [agent])

        lookup_returns = []

        async def replay_decision(*args, **kwargs):
            lookup_returns.append(
                replay.gateway._replay_lookup(cache_key, req))
            return []

        monkeypatch.setattr(replay.runtime, "_decide_one", replay_decision)
        executions = []
        monkeypatch.setattr(
            replay.runtime, "execute_decisions",
            lambda *args, **kwargs: executions.append((args, kwargs)))
        replay.store.set_meta(
            active_tick=1, next_phase="MORNING", phase="MORNING",
            phase_state_json="{}", legacy_partial=0)
        replay.store.commit()

        initial_bookkeeping = {
            "positions": dict(replay.gateway._replay_positions),
            "used": set(replay.gateway._replay_used_call_ids),
            "exact": replay.gateway._replay_exact_key_count,
            "fallback": replay.gateway._replay_compatibility_fallback_count,
            "consumed": list(replay.gateway._replay_consumed_calls),
        }
        for _ in range(2):
            result = asyncio.run(replay.step())
            assert result["paused"] == "provider"
            assert "dangling in source" in result["pause_reason"]["detail"]
            assert dict(replay.gateway._replay_positions) == \
                initial_bookkeeping["positions"]
            assert set(replay.gateway._replay_used_call_ids) == \
                initial_bookkeeping["used"]
            assert replay.gateway._replay_exact_key_count == \
                initial_bookkeeping["exact"]
            assert replay.gateway._replay_compatibility_fallback_count == \
                initial_bookkeeping["fallback"]
            assert list(replay.gateway._replay_consumed_calls) == \
                initial_bookkeeping["consumed"]

        assert lookup_returns == []
        assert executions == []
        assert replay.gateway._live_dispatch_count == 0
        assert replay.store.scalar(
            "SELECT COUNT(*) FROM events WHERE kind='decision_error'", default=0) == 0
        assert replay.store.scalar(
            "SELECT COUNT(*) FROM events WHERE kind='provider_pause'", default=0) == 2
    finally:
        replay.gateway.replay_conn = None
        source_conn.close()
        replay.store.close()


def test_newsroom_grounding_failure_retries_same_replay_call_across_resume(
        tmp_path):
    replay, source_conn, ids = _duplicate_news_replay(
        tmp_path, "newsroom-grounding-resume")
    try:
        first_editor_id = replay.newsroom._desk_agent(
            "editor", replay.newsroom.outlets[0]["id"])
        second_editor_id = replay.newsroom._desk_agent(
            "editor", replay.newsroom.outlets[1]["id"])
        first_source_call = source_conn.execute(
            "SELECT * FROM llm_calls WHERE tick=301 AND role='editor' "
            "AND purpose='newsroom' AND agent_id=? ORDER BY id LIMIT 1",
            (first_editor_id,)).fetchone()
        source_call = source_conn.execute(
            "SELECT * FROM llm_calls WHERE tick=301 AND role='editor' "
            "AND purpose='newsroom' AND agent_id=? ORDER BY id LIMIT 1",
            (second_editor_id,)).fetchone()
        assert first_source_call is not None and source_call is not None
        assert int(source_conn.execute(
            "SELECT COUNT(*) FROM llm_calls WHERE tick=301 AND role='reporter' "
            "AND purpose='reporter'").fetchone()[0]) == 2

        first_fallback = json.loads(first_source_call["response_json"])
        first_fallback["text"] = json.dumps({
            "headline": "First outlet fallback",
            "body": "This response cites an invented source.",
            "tone": 0.0,
            "slant_tags": ["credit"],
            "source_event_ids": [999_998],
        })
        source_conn.execute(
            "UPDATE llm_calls SET response_json=? WHERE id=?",
            (json.dumps(first_fallback), int(first_source_call["id"])))

        mismatched_response = json.loads(source_call["response_json"])
        mismatched_response["text"] = json.dumps({
            "headline": "Recorded duplicate event",
            "body": "This response cites a valid source occurrence.",
            "tone": -0.2,
            "slant_tags": ["credit"],
            "source_event_ids": [ids["source_first"]],
        })
        source_conn.execute(
            "UPDATE llm_calls SET response_json=? WHERE id=?",
            (json.dumps(mismatched_response), int(source_call["id"])))

        later_fallback = dict(mismatched_response)
        later_fallback["text"] = json.dumps({
            "headline": "Later duplicate must not mask the mismatch",
            "body": "This response cites an invented source.",
            "tone": 0.0,
            "slant_tags": ["credit"],
            "source_event_ids": [999_999],
        })
        source_conn.execute(
            "INSERT INTO llm_calls ("
            "tick,agent_id,role,provider,model,purpose,cache_key,request_json,"
            "response_json,in_tokens,out_tokens,cached,cost_usd,latency_ms,created_at"
            ") SELECT tick,agent_id,role,provider,model,purpose,cache_key,request_json,"
            "?,in_tokens,out_tokens,cached,cost_usd,latency_ms,created_at "
            "FROM llm_calls WHERE id=?",
            (json.dumps(later_fallback), int(source_call["id"])))
        source_conn.commit()

        replay.store.execute(
            "DELETE FROM events WHERE id=?", (ids["local_second"],))
        replay.store.set_meta(
            active_tick=301, next_phase="NEWSROOM", phase="NEWSROOM",
            phase_state_json="{}", legacy_partial=0)
        replay.store.commit()
        replay.gateway.replay = True
        initial_call_count = int(replay.store.scalar(
            "SELECT COUNT(*) FROM llm_calls", default=0))
        initial_bookkeeping = {
            "positions": dict(replay.gateway._replay_positions),
            "used": set(replay.gateway._replay_used_call_ids),
            "exact": replay.gateway._replay_exact_key_count,
            "fallback": replay.gateway._replay_compatibility_fallback_count,
            "consumed": list(replay.gateway._replay_consumed_calls),
        }

        for _ in range(2):
            result = asyncio.run(replay.step())
            assert result["paused"] == "provider"
            assert result["phase"] == "NEWSROOM"
            assert "cardinality mismatch" in result["pause_reason"]["detail"]
            assert dict(replay.gateway._replay_positions) == \
                initial_bookkeeping["positions"]
            assert set(replay.gateway._replay_used_call_ids) == \
                initial_bookkeeping["used"]
            assert replay.gateway._replay_exact_key_count == \
                initial_bookkeeping["exact"]
            assert replay.gateway._replay_compatibility_fallback_count == \
                initial_bookkeeping["fallback"]
            assert list(replay.gateway._replay_consumed_calls) == \
                initial_bookkeeping["consumed"]
            assert int(replay.store.scalar(
                "SELECT COUNT(*) FROM llm_calls", default=0)) == initial_call_count
            assert int(replay.store.scalar(
                "SELECT COUNT(*) FROM news_articles", default=0)) == 0

        assert replay.gateway._live_dispatch_count == 0
        assert int(replay.store.scalar(
            "SELECT COUNT(*) FROM events WHERE kind='provider_pause'",
            default=0)) == 2
    finally:
        replay.gateway.replay_conn = None
        source_conn.close()
        replay.store.close()


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

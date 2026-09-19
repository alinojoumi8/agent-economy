"""City totals, actor filtering, cursor stability and disclosure boundaries."""
from server.projections.city_activity import build_city_activity
from tests.conftest import make_agent, make_bank
from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient
from server.v2_api import install_v2_routes
from server.projections.city_news import build_city_news
import json


def test_complete_day_pagination_and_outcomes(economy):
    bank = make_bank(economy)
    aid, _ = make_agent(economy, bank, name="Ada")
    for i in range(125):
        economy.store.log_event(3, "external_action_executed", {"agent_id": aid, "index": i})
    economy.store.log_event(2, "hired", {"agent_id": aid})
    economy.store.log_event(4, "hired", {"agent_id": aid})
    first = build_city_activity(economy.store, as_of_tick=3, limit=40)
    assert first["total"] == 125 and first["changed_agents"] == 1
    assert first["counts"] == {"completed": 125}
    economy.store.log_event(3, "external_action_queued", {"agent_id": aid})
    ids, offset = [], 0
    while offset is not None:
        page = build_city_activity(economy.store, as_of_tick=3, offset=offset,
                                   limit=40, through_id=first["through_id"])
        assert page["total"] == 125 and page["actor_activity"] == first["actor_activity"]
        ids.extend(row["id"] for row in page["items"])
        offset = page["next_offset"]
    assert len(ids) == len(set(ids)) == 125
    refreshed = build_city_activity(economy.store, as_of_tick=3)
    assert refreshed["counts"] == {"completed": 125, "pending": 1}
    assert refreshed["actor_activity"][0]["event"]["outcome"] == "pending"


def test_actor_filters_and_private_payloads(economy):
    bank = make_bank(economy)
    aid, _ = make_agent(economy, bank, name="Ada")
    other, _ = make_agent(economy, bank, name="Ben")
    future, _ = make_agent(economy, bank, name="Future", arrived_tick=9)
    economy.store.log_event(3, "conversation", {"participants": [aid, other], "conv_id": 7,
                                               "text": "PRIVATE_SENTINEL"})
    economy.store.log_event(3, "action_rejected", {"agent_id": aid, "reason": "PRIVATE_SENTINEL"})
    economy.store.log_event(3, "unknown_kind", {"agent_id": aid, "prompt": "PRIVATE_SENTINEL"})
    economy.store.log_event(3, "external_action_executed", {"agent_id": future})
    page = build_city_activity(economy.store, as_of_tick=3, actor_id=other)
    assert page["total"] == 1 and page["items"][0]["actors"] == [
        {"id": aid, "name": "Ada"}, {"id": other, "name": "Ben"}]
    all_rows = build_city_activity(economy.store, as_of_tick=3)
    assert "PRIVATE_SENTINEL" not in str(all_rows) and "Future" not in str(all_rows)
    assert any(row["kind"] == "unknown_kind" for row in all_rows["items"])
    assert build_city_activity(economy.store, as_of_tick=3, category="communications")["total"] == 1
    assert build_city_activity(economy.store, as_of_tick=1)["total"] == 0


def test_city_activity_routes_fail_closed_and_never_write_world(economy):
    economy.store.set_meta(tick=3, active_tick=None, status="paused")
    app = FastAPI()
    install_v2_routes(app, SimpleNamespace(store=economy.store, config=economy.config, economy=economy),
                      SimpleNamespace(hosted_safe=False))
    try:
        with TestClient(app) as client:
            before = economy.store.conn.total_changes
            for path in ("activity", "news", "conversations"):
                response = client.get(f"/api/v2/city/{path}?tick=2")
                assert response.status_code == 200, response.text
                assert response.json()["projection"] == f"city.{path}"
                assert response.json()["tick"] == 2
                assert client.get(f"/api/v2/city/{path}?tick=4").status_code == 409
                assert client.get(f"/api/v2/city/{path}?fork_id=foreign").status_code == 409
                assert client.post(f"/api/v2/city/{path}", json={}).status_code == 405
            for query in ("offset=-1", "actor_id=0", "limit=201", "category=private", "through_id=-1"):
                assert client.get(f"/api/v2/city/activity?{query}").status_code == 422
            assert economy.store.conn.total_changes == before
    finally:
        app.state.operator_workspace.close()


def test_native_activity_has_explicit_units_and_unknown_kinds_stay_neutral(economy):
    bank = make_bank(economy)
    aid, _ = make_agent(economy, bank, name="Ada")
    economy.store.log_event(2, "goods_sale", {"buyer_id": aid, "qty": 3, "unit_price_cents": 50, "total_cents": 150})
    economy.store.log_event(2, "civic_appointment_scheduled", {"applicant_agent_id": aid})
    economy.store.log_event(2, "unknown_failed_private_message", {"actor_id": aid, "body": "SECRET"})
    day = build_city_activity(economy.store, as_of_tick=2)
    assert day["counts"] == {"recorded": 1, "pending": 1, "completed": 1}
    sale = next(row for row in day["items"] if row["kind"] == "goods_sale")
    assert sale["actor_ids"] == [aid] and "150 cents total" in sale["detail"]
    assert "50 cents per unit" in sale["detail"]
    assert day["actor_activity"][0]["event"]["outcome"] == "pending"
    assert "SECRET" not in str(day)


def test_news_is_day_scoped_paged_and_never_exposes_future_sources(economy):
    store = economy.store
    past = store.log_event(2, "production", {"firm_id": 1, "units": 4})
    future = store.log_event(4, "private_event", {"secret": "FUTURE_SENTINEL"})
    for tick, headline in ((2, "Earlier story"), (2, "Later story"), (4, "FUTURE_HEADLINE")):
        store.insert("news_articles", tick=tick, outlet_id=1, headline=headline, body="Recorded story",
                     slant_tags="[]", source_event_ids=json.dumps([past, future]))
    before = store.conn.total_changes
    page = build_city_news(store, as_of_tick=2, limit=1)
    assert len(page["items"]) == 1 and page["next_before_id"]
    assert page["items"][0]["source_event_ids"] == [past]
    older = build_city_news(store, as_of_tick=2, before_id=page["next_before_id"])
    assert len(older["items"]) == 1 and older["next_before_id"] is None
    assert "FUTURE" not in str(page) + str(older)
    assert store.conn.total_changes == before

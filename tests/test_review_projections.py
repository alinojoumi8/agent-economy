"""Projection regressions from the 2026-09 review: historical exactness and privacy."""
from __future__ import annotations

import json

from communications.policy import Principal
from server.projections.events import build_backfill
from server.projections.living_agents import build_living_agents_workspace
from server.projections.search import _like_pattern
from server.projections.snapshot import build_snapshot
from server.projections.workspaces import _agent_regions_at, _settlement_as_of
from tests.conftest import make_agent, make_bank
from tests.test_search_projection import _group, _search_app


def _projection_world(economy, *, tick: int = 6) -> None:
    economy.config["engine_semantics_version"] = 8
    economy.config.setdefault("communications", {})
    economy.store.set_meta(
        tick=tick, status="paused", phase="FINALIZE",
        config_json=json.dumps(economy.config, sort_keys=True))


def test_snapshot_alerts_are_the_newest_salient_events(economy):
    _projection_world(economy)
    ids = [economy.store.log_event(1, f"alert_{index}", {}, importance=2.0)
           for index in range(25)]
    economy.store.log_event(1, "quiet", {}, importance=0.5)
    alerts = build_snapshot(
        economy.store, Principal("ordinary"), as_of_tick=6, domains=("alerts",))["alerts"]
    assert [item["id"] for item in alerts] == ids[-20:]
    assert all(item["importance"] >= 1.5 for item in alerts)


def test_snapshot_summary_counts_are_as_of_the_requested_tick(economy):
    _projection_world(economy, tick=10)
    bank_id = make_bank(economy)
    make_agent(economy, bank_id, name="Survivor", arrived_tick=0)
    departed, _ = make_agent(economy, bank_id, name="Departed", arrived_tick=0)
    economy.store.execute("UPDATE agents SET alive=0,died_tick=5 WHERE id=?", (departed,))
    economy.store.insert(
        "firms", name="Fallen", sector="food", status="bankrupt", founded_tick=1, bankrupt_tick=5)
    economy.store.insert(
        "firms", name="Standing", sector="food", status="private", founded_tick=1)

    def summary(tick: int) -> dict:
        return build_snapshot(
            economy.store, Principal("ordinary"), as_of_tick=tick, domains=("summary",))["summary"]

    assert summary(4)["agents_alive"] == summary(10)["agents_alive"] + 1
    assert summary(4)["active_firms"] == 2
    assert summary(10)["active_firms"] == 1


def test_backfill_excludes_commits_from_the_in_progress_tick(economy):
    _projection_world(economy, tick=6)
    for tick in (5, 6, 7):
        economy.store.execute(
            "INSERT INTO projection_commits (tick,phase,domains_json) VALUES (?,?,?)",
            (tick, "FINALIZE", json.dumps(["events"])))
    page = build_backfill(economy.store, after_cursor=0, limit=10)
    assert [commit["tick"] for commit in page["commits"]] == [5, 6]
    assert page["truncated"] is False


def test_event_kind_filter_list_is_bounded(economy, tmp_path):
    from fastapi.testclient import TestClient

    app, _ids = _search_app(economy, tmp_path)
    with TestClient(app) as client:
        too_many = ",".join(f"kind_{index}" for index in range(60))
        assert client.get("/api/v2/events", params={"filters": too_many}).status_code == 422
        enough = ",".join(f"kind_{index}" for index in range(50))
        assert client.get("/api/v2/events", params={"filters": enough}).status_code == 200
    app.state.operator_workspace.close()


def test_rejected_migration_is_not_projected_as_an_arrival(economy):
    _projection_world(economy, tick=12)
    economy.store.execute(
        "INSERT INTO regions (id,region_key,name,currency_code,population_target,"
        "specialization_json,x,y,legal_ruleset) VALUES "
        "(1,'north','North','USD',10,'{}',.2,.3,'rules'),"
        "(2,'south','South','USD',10,'{}',.8,.7,'rules')")
    bank_id = make_bank(economy)
    agent_id, _ = make_agent(
        economy, bank_id, name="Stayer", arrived_tick=0, region_id=1, population_tier="core")
    economy.store.insert(
        "migrations", agent_id=agent_id, origin_region_id=1, destination_region_id=2,
        requested_tick=3, completed_tick=9, reason="credit exposure", status="rejected")
    agents = [{"id": agent_id, "region_id": 1}]
    assert _agent_regions_at(economy.store, agents, 10)[agent_id] == 1

    workspace = build_living_agents_workspace(economy.store, as_of_tick=10)
    migration = next(
        project for project in workspace["projects"] if project["kind"] == "migration")
    assert migration["status"] == "cancelled"
    assert migration["stage"] == "cancelled"
    assert all(ref["kind"] != "migration_completion" for ref in migration["evidence_refs"])
    before = build_living_agents_workspace(economy.store, as_of_tick=5)
    pending = next(
        project for project in before["projects"] if project["kind"] == "migration")
    assert pending["status"] == "active"

    economy.store.insert(
        "migrations", agent_id=agent_id, origin_region_id=1, destination_region_id=2,
        requested_tick=10, completed_tick=11, reason="", status="completed")
    assert _agent_regions_at(economy.store, agents, 12)[agent_id] == 2
    assert _agent_regions_at(economy.store, agents, 10)[agent_id] == 1


def test_settlement_projection_hides_facts_written_after_the_tick():
    offer = {"status": "offered", "proposer_actor_id": 4, "proposer_side": "claimant",
             "offered_tick": 20, "remedy": {"type": "damages", "amount_cents": 500}}
    accepted = {**offer, "status": "accepted", "accepted_tick": 24, "accepted_by": 9,
                "enforcement": {"ok": True}}
    assert _settlement_as_of(offer, 19) == {}
    assert _settlement_as_of(offer, 20) == offer
    visible = _settlement_as_of(accepted, 22)
    assert visible["status"] == "offered"
    assert "accepted_by" not in visible and "enforcement" not in visible
    assert _settlement_as_of(accepted, 24) == accepted
    assert _settlement_as_of({}, 5) == {}
    assert _settlement_as_of(None, 5) is None


def test_search_matches_like_wildcards_literally(economy, tmp_path):
    from fastapi.testclient import TestClient

    assert _like_pattern("a%b_c\\") == "%a\\%b\\_c\\\\%"
    app, ids = _search_app(economy, tmp_path)
    with TestClient(app) as client:
        literal = client.get(
            "/api/v2/search", params={"q": "oods_sal", "kinds": "event"}).json()
        assert [item["id"] for item in _group(literal, "event")["items"]] == [
            ids["current_event_id"]]
        wildcard = client.get(
            "/api/v2/search", params={"q": "oods%sal", "kinds": "event"}).json()
        assert _group(wildcard, "event")["items"] == []
        upper = client.get(
            "/api/v2/search", params={"q": "GOODS_SALE", "kinds": "event"}).json()
        assert [item["id"] for item in _group(upper, "event")["items"]] == [
            ids["current_event_id"]]
    app.state.operator_workspace.close()

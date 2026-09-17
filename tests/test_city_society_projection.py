"""Historical, privacy and lineage contracts for city household/bank lenses."""
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from server.projections.city_society import build_city_households, build_city_institutions
from server.v2_api import install_v2_routes
from tests.test_semantics15_households import family  # noqa: F401


@pytest.fixture
def society(family):
    e, parent, _, bank = family
    e.store.set_meta(config_json=json.dumps(e.config), tick=10, status="paused", active_tick=None)
    e.store.update("agents", parent, population_tier="core")
    child = e.households.birth(2, parent)
    e.store.update("agents", child, name="Visible child", pinned_core=1)
    hidden = e.households.birth(3, parent)
    e.store.update("agents", hidden, name="PRIVATE-CHILD")
    household = int(e.households.membership(parent)["household_id"])
    e.store.insert("child_needs", tick=4, child_agent_id=child, household_id=household,
                   guardian_agent_id=parent, currency_code="USD", goods_sector="food",
                   required_units=2, purchased_units=1, spent_cents=90,
                   care_required_minutes=120, care_status="time_allocation_pending",
                   purchases_json='[{"private":"PRIVATE-RECEIPT"}]')
    return e, parent, child, hidden, household, bank


def test_membership_age_birth_and_child_needs_use_requested_tick(society):
    e, parent, child, _, household, _ = society
    before = e.store.conn.total_changes
    initial = build_city_households(e.store, as_of_tick=1)
    assert initial["items"][0]["id"] == household
    assert [m["agent_id"] for m in initial["items"][0]["members"]] == [parent]
    data = build_city_households(e.store, as_of_tick=4)
    member = data["items"][0]["members"][1]
    assert member["agent_id"] == child and member["age_years"] == 0
    assert member["age_band"] == "child" and member["guardian_agent_id"] == parent
    assert data["items"][0]["members"][0]["legacy_dependents"] == 2
    needs = data["items"][0]["child_needs"]
    assert len(needs) == 1 and needs[0]["purchased_units"] == 1 and needs[0]["spent_cents"] == 90
    assert needs[0]["care_status"] == "time_allocation_pending"
    assert build_city_households(e.store, as_of_tick=5)["items"][0]["child_needs"] == []
    assert e.store.conn.total_changes == before
    e.store.update("agents", child, age=99, retired=1)
    e.store.execute("UPDATE person_lifecycle SET life_stage='retired' WHERE agent_id=?", (child,))
    assert build_city_households(e.store, as_of_tick=4) == data


def test_future_departure_death_and_custody_do_not_rewrite_household_history(society):
    e, parent, child, _, household, _ = society
    original = build_city_households(e.store, as_of_tick=4)
    new_household = e.households.split_household(7, parent)
    assert new_household != household
    assert build_city_households(e.store, as_of_tick=4) == original
    seven = build_city_households(e.store, as_of_tick=7)
    assert [m["agent_id"] for m in seven["items"][0]["members"]] == [child]
    e.lifecycle.settle_death(8, parent)
    assert build_city_households(e.store, as_of_tick=4) == original
    eight = build_city_households(e.store, as_of_tick=8)
    assert not any(m["agent_id"] == parent for h in eight["items"] for m in h["members"])
    assert eight["items"][0]["members"][0]["guardian_agent_id"] is None


def test_peripheral_identities_accounts_receipts_and_exact_locations_are_absent(society):
    e, parent, _, _, _, _ = society
    data = build_city_households(e.store, as_of_tick=4)
    text = json.dumps(data)
    for secret in ("PRIVATE", "account", "birth_key", "region_id", "place_id", '"x"', '"y"', "purchases_json"):
        assert secret not in text
    e.store.update("agents", parent, population_tier="periphery", pinned_core=0)
    reduced = build_city_households(e.store, as_of_tick=4)
    assert len(reduced["items"][0]["members"]) == 1
    assert reduced["items"][0]["members"][0]["guardian_agent_id"] is None


def test_legacy_households_are_unavailable_and_bank_status_uses_failure_boundary(society):
    e, _, _, _, _, bank = society
    e.store.set_meta(config_json='{"engine_semantics_version":14}')
    data = build_city_households(e.store, as_of_tick=4)
    assert data["available"] is False and data["items"] == [] and data["reason"]
    e.store.update("banks", bank, failed_tick=8, status="failed")
    earlier = build_city_institutions(e.store, as_of_tick=7)
    later = build_city_institutions(e.store, as_of_tick=8)
    assert earlier["items"][0]["status"] == "open" and later["items"][0]["status"] == "failed"
    assert earlier["items"][0]["id"] == f"bank:{bank}"
    assert set(earlier["items"][0]) == {"id", "bank_id", "kind", "name", "currency_code", "status"}


def test_map_society_layers_are_opt_in_read_only_and_bind_fork_tick(society):
    e, _, _, _, _, _ = society
    app = FastAPI()
    install_v2_routes(app, SimpleNamespace(store=e.store, config=e.config, economy=e), SimpleNamespace(hosted_safe=False))
    try:
        with TestClient(app) as client:
            before = e.store.conn.total_changes
            url = "/api/v2/world-map?layers=households,institutions&tick=4"
            response = client.get(url)
            assert response.status_code == 200, response.text
            frame = response.json()
            assert frame["run_id"] == "test" and frame["tick"] == 4 and frame["fork_id"] is None
            assert frame["projection"] == "world.map" and set(frame["data"]) == {"households", "institutions"}
            assert frame["data"]["households"]["tick"] == frame["data"]["institutions"]["tick"] == 4
            for population in ("core", "all", "clusters"):
                assert client.get(url + f"&population={population}").json() == frame
            assert client.get(url + "&fork_id=foreign").status_code == 409
            assert client.get("/api/v2/world-map?layers=households&tick=11").status_code == 409
            assert client.post(url, json={}).status_code == 405
            assert e.store.conn.total_changes == before
            e.store.set_meta(parent_run_id="parent", fork_tick=1)
            fork = client.get(url + "&fork_id=test").json()
            assert fork["fork_id"] == "test" and fork["data"] == frame["data"]
    finally:
        app.state.operator_workspace.close()

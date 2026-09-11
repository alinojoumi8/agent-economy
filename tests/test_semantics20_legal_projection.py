"""A monetary decision snapshot cannot stand in for later cash settlement."""
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from research.hashing import canonical_hashes
from server.projections.legal_relief import monetary_relief_as_of
from server.projections.workspaces import build_politics_law_workspace
from server.v2_api import install_v2_routes

from .test_semantics20_legal_awards import award_case, claim, decide, receive, check
from .test_v2_legal import _payment_contract


def visible(case):
    for person in (case.person, case.creditor):
        case.e.store.update("agents", person, population_tier="core", pinned_core=0)


def test_history_reconstructs_held_and_released_cash_without_future_judgment_or_private_bodies(award_case):
    c = award_case
    visible(c)
    matter, event = claim(c, 150)
    c.e.lifecycle.settle_death(2, c.person)
    receive(c, 60, tick=3)
    assert decide(c, matter, event, 120, tick=4)["ok"]
    c.e.store.update("legal_filings", 1, body="private-filing-canary")
    c.e.store.update("legal_matters", matter, metadata_json=json.dumps({"private": "private-metadata-canary"}))
    before = canonical_hashes(c.e.store)["authoritative_sha256"]
    assert monetary_relief_as_of(c.e.store, matter, 0) is None
    early = monetary_relief_as_of(c.e.store, matter, 1)
    assert early["award"] is None and early["estate_reserve"] is None
    pending = monetary_relief_as_of(c.e.store, matter, 2)
    assert pending["award"] is None
    assert pending["estate_reserve"]["held_cents"] == 100
    assert pending["estate_reserve"]["resolved_tick"] is None
    assert pending["estate_reserve"]["released_cents"] == 0
    assert monetary_relief_as_of(c.e.store, matter, 3)["estate_reserve"]["held_cents"] == 150
    settled = monetary_relief_as_of(c.e.store, matter, 4)
    assert settled["award"]["paid_cents"] == 120
    assert settled["award"]["outstanding_cents"] == 0
    assert settled["estate_reserve"]["held_cents"] == 0
    assert settled["estate_reserve"]["released_cents"] == 150
    assert settled["estate_reserve"]["resolved_tick"] == 4
    public = json.dumps([pending, settled])
    assert "canary" not in public and "account" not in public and "beneficiari" not in public
    assert canonical_hashes(c.e.store)["authoritative_sha256"] == before
    workspace = build_politics_law_workspace(c.e.store, as_of_tick=4)
    assert workspace["matters"][0]["monetary_relief"] == settled
    assert workspace["obligations"][0]["status"] == "adjudicated"
    assert build_politics_law_workspace(c.e.store, as_of_tick=3)["obligations"][0]["status"] != "adjudicated"
    check(c)


def test_partial_award_payments_are_selected_day_values_even_after_full_collection(award_case):
    c = award_case
    visible(c)
    matter, event = claim(c, 170)
    assert decide(c, matter, event, 170)["ok"]
    c.e.lifecycle.settle_death(2, c.person)
    receive(c, 20, tick=3)
    receive(c, 50, tick=5)
    for tick, paid, outstanding in ((1, 100, 70), (3, 120, 50), (5, 170, 0)):
        award = monetary_relief_as_of(c.e.store, matter, tick)["award"]
        assert (award["paid_cents"], award["outstanding_cents"], award["credited_cents"]) == (paid, outstanding, 0)
        assert award["last_paid_tick"] <= tick
    check(c)


def test_prior_estate_contract_payments_are_credits_not_fresh_award_collections(award_case):
    c = award_case
    visible(c)
    contract = _payment_contract(c.executor, c.creditor, c.person, due_tick=0, amount=150)
    c.e.lifecycle.settle_death(2, c.person)
    matter, event = claim(c, 150, contract_id=contract, tick=3)
    assert decide(c, matter, event, 120, tick=3)["ok"]
    receive(c, 20, tick=4)
    award = monetary_relief_as_of(c.e.store, matter, 4)["award"]
    assert (award["awarded_cents"], award["credited_cents"], award["paid_cents"], award["outstanding_cents"]) == (120, 100, 20, 0)
    check(c)


def test_financial_visibility_uses_each_partys_selected_day_tier(award_case):
    c = award_case
    visible(c)
    matter, event = claim(c, 170)
    assert decide(c, matter, event, 170)["ok"]
    c.e.store.insert("agent_tier_history", tick=3, agent_id=c.creditor, old_tier="periphery", new_tier="core", score=1, reason_json="{}")
    assert monetary_relief_as_of(c.e.store, matter, 2) == {"visibility": "withheld", "as_of_tick": 2}
    assert monetary_relief_as_of(c.e.store, matter, 3)["award"]["awarded_cents"] == 170
    c.e.store.update("agents", c.person, population_tier="periphery")
    assert monetary_relief_as_of(c.e.store, matter, 3) == {"visibility": "withheld", "as_of_tick": 3}


def test_old_semantics_expose_no_invented_monetary_history(award_case):
    c = award_case
    config = json.loads(c.e.store.get_meta()["config_json"])
    config["engine_semantics_version"] = 19
    c.e.store.execute("UPDATE run_meta SET config_json=?", (json.dumps(config),))
    assert monetary_relief_as_of(c.e.store, 1, 3) is None


def test_both_legal_apis_use_cash_records_and_historical_workspace_retains_the_old_balance(award_case):
    c = award_case
    visible(c)
    matter, event = claim(c, 170)
    assert decide(c, matter, event, 170)["ok"]
    c.e.lifecycle.settle_death(2, c.person)
    receive(c, 70, tick=4)
    c.e.store.execute("UPDATE run_meta SET tick=4")
    app = FastAPI()
    install_v2_routes(app, SimpleNamespace(store=c.e.store, economy=c.e, config=c.e.config), SimpleNamespace(hosted_safe=False))
    before = canonical_hashes(c.e.store)["authoritative_sha256"]
    with TestClient(app) as client:
        current = client.get("/api/v2/legal")
        assert current.status_code == 200, current.text
        assert current.json()["items"][0]["monetary_relief"]["award"]["paid_cents"] == 170
        historical = client.get("/api/v2/workspaces/politics-law?tick=2")
        assert historical.status_code == 200, historical.text
        award = historical.json()["data"]["matters"][0]["monetary_relief"]["award"]
        assert (award["paid_cents"], award["outstanding_cents"]) == (100, 70)
    assert canonical_hashes(c.e.store)["authoritative_sha256"] == before

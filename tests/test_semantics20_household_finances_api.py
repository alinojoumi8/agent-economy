"""Operator scope, anonymous identities and selected-day financial API evidence."""
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from research.hashing import canonical_hashes
from server.household_finances_api import install_household_finance_routes
from server.projections.household_finances import build_household_finances
from server.projections.city_society import build_city_households
from .test_semantics20_estate_cases import estate_case
from .test_semantics20_legal_awards import award_case, claim, decide
from .test_semantics20_household_positions import committed


def public(e, *people):
    for identifier in people:
        e.store.update("agents", identifier, population_tier="core", pinned_core=0)


def client_for(e, *, hosted=False, enabled=True):
    app = FastAPI()
    world = SimpleNamespace(store=e.store, config={"operator_households": {"enabled": enabled}})
    install_household_finance_routes(app, world, SimpleNamespace(hosted_safe=hosted), csrf_token="test-finance-token")
    return TestClient(app)


def request(client, e, agent, *, token="test-finance-token", tick="0", run=None, fork=None):
    return client.get(f"/api/v2/operator/household-finances/{agent}",
        params={"tick": tick, "run_id": run or e.store.get_meta()["run_id"], **({"fork_id": fork} if fork else {})},
        headers={"X-CSRF-Token": token} if token is not None else {})


@pytest.mark.parametrize("hosted,enabled,token", [(False, True, None), (False, True, "wrong"),
                                                 (True, True, "test-finance-token"), (False, False, "test-finance-token")])
def test_financial_read_requires_local_operator_gate(estate_case, hosted, enabled, token):
    e, _, person, _, heir, _ = estate_case
    public(e, person, heir)
    committed(e, 0)
    before = canonical_hashes(e.store)["authoritative_sha256"]
    with client_for(e, hosted=hosted, enabled=enabled) as client:
        response = request(client, e, person, token=token)
    assert response.status_code == 403
    assert response.headers["cache-control"] == "private, no-store"
    assert "instruments" not in response.json()
    assert canonical_hashes(e.store)["authoritative_sha256"] == before


@pytest.mark.parametrize("params", [{"run": "another-run"}, {"fork": "another-fork"}, {"tick": "3"}, {"tick": "-1"}])
def test_invalid_run_fork_and_tick_cannot_return_another_financial_view(estate_case, params):
    e, _, person, _, heir, _ = estate_case
    public(e, person, heir)
    committed(e, 0)
    with client_for(e) as client:
        response = request(client, e, person, **params)
    assert response.status_code == 409
    assert "instruments" not in response.json()


def test_selected_tick_and_currency_values_survive_later_payments_without_source_writes(estate_case):
    e, _, person, wallet, heir, heir_wallet = estate_case
    public(e, person, heir)
    e.ledger.create_account("agent", person, "fx", currency_code="EUR", opening_cents=300, tick=2)
    e.ledger.transfer(2, wallet, heir_wallet, 70)
    committed(e, 2)
    before = canonical_hashes(e.store)["authoritative_sha256"]
    with client_for(e) as client:
        old = request(client, e, person)
        current = request(client, e, person, tick="2")
    assert old.status_code == current.status_code == 200
    assert old.headers["cache-control"] == "private, no-store"
    assert old.json()["projection"] == "operator.household-finances"
    assert old.json()["tick"] == 0 and old.json()["data"]["requested_tick"] == "0"
    data, later = old.json()["data"], current.json()["data"]
    assert data["by_currency"]["USD"]["wallet_cash_cents"] == 100
    assert later["by_currency"]["USD"]["wallet_cash_cents"] == 30
    assert "EUR" not in data["by_currency"] and "EUR" not in data["cash_inequality"]
    assert later["by_currency"]["EUR"]["wallet_cash_cents"] == 300
    assert data["cash_inequality"]["USD"]["gini"] == 0.5
    assert data["cash_inequality"]["USD"]["population_count"] == 2
    assert len(data["instruments"]) == 1
    encoded = json.dumps(data)
    assert "person_cash_cents" not in encoded and "account:" not in encoded and "evidence" not in encoded
    assert canonical_hashes(e.store)["authoritative_sha256"] == before


def test_counterparty_identity_is_anonymous_but_selected_household_claim_remains_reconciled(award_case):
    c = award_case
    public(c.e, c.creditor)
    c.e.store.update("agents", c.person, name="PRIVATE-DEBTOR-CANARY", population_tier="periphery", pinned_core=0)
    matter, event = claim(c, 170)
    assert decide(c, matter, event, 170)["ok"]
    committed(c.e, 1)
    data = build_household_finances(c.e.store, agent_id=c.creditor, as_of_tick=1)
    claims = [row for row in data["instruments"] if row["face_cents"] == 70]
    assert len(claims) == 1
    assert claims[0]["debtor"] == {"type": "private", "id": None, "name": "Private person"}
    assert data["by_currency"]["USD"]["receivable_face_cents"] == 70
    assert "PRIVATE-DEBTOR-CANARY" not in json.dumps(data)


def test_private_estate_paths_keep_fractions_without_disclosing_other_households_or_nominees(estate_case):
    e, _, person, _, heir, _ = estate_case
    public(e, heir)
    e.store.update("agents", person, name="PRIVATE-NOMINEE-CANARY", population_tier="periphery", pinned_core=0)
    e.lifecycle.settle_death(1, person)
    committed(e, 1)
    data = build_household_finances(e.store, agent_id=heir, as_of_tick=1)
    assert data["contingent_interests"][0]["fraction"] == {"numerator": "1", "denominator": "1"}
    assert data["contingent_interests"][0]["amount_cents"] is None
    assert data["estate_boundaries"][0]["name"] == "Private estate"
    assert "PRIVATE-NOMINEE-CANARY" not in json.dumps(data)
    assert "beneficiaries" not in json.dumps(data) and "escrow_account_id" not in json.dumps(data)
    public_layer = json.dumps(build_city_households(e.store, as_of_tick=1))
    assert "wallet_cash_cents" not in public_layer and "contingent_interests" not in public_layer


def test_private_and_future_selection_are_indistinguishable_and_old_tier_is_respected(estate_case):
    e, _, person, _, heir, _ = estate_case
    public(e, person, heir)
    e.store.insert("agent_tier_history", tick=2, agent_id=person, old_tier="periphery", new_tier="core", score=1, reason_json="{}")
    committed(e, 2)
    with client_for(e) as client:
        private = request(client, e, person, tick="1")
        absent = request(client, e, 999999, tick="1")
        visible = request(client, e, person, tick="2")
    assert private.status_code == absent.status_code == 404
    assert private.json() == absent.json()
    assert visible.status_code == 200


def test_active_or_incompatible_boundaries_return_no_cached_finances(estate_case):
    e, _, person, _, heir, _ = estate_case
    public(e, person, heir)
    committed(e, 1)
    with client_for(e) as client:
        e.store.execute("UPDATE run_meta SET active_tick=1")
        assert request(client, e, person, tick="1").status_code == 409
        e.store.execute("UPDATE run_meta SET active_tick=NULL,config_json=?", (json.dumps({"engine_semantics_version": 19}),))
        response = request(client, e, person, tick="1")
        assert response.status_code == 409
        assert "instruments" not in response.json()

"""Draft adjudication admission and historical residence, with retained claims.

These disposable service fixtures do not establish native World acceptance.
"""
import json

import pytest

from engine.estates import EstateError
from engine.population_history import ResidenceError

from .test_population_authority import population_property, age_at, move
from .test_population_residence_history import contents
from .test_semantics20_project_rights import property_world, validate
from .test_semantics20_legal_authority import open_matter, dismissal


def adjudicator(e):
    return e.store.query_one("SELECT * FROM agents WHERE role='labor_regulator' "
        "AND alive=1 AND age>=18 ORDER BY id LIMIT 1")


def award(e, matter, evidence):
    return {"matter_id": matter, "outcome": "claimant",
        "findings": [{"key": "disputed_loss", "value": True}],
        "evidence_event_ids": [evidence],
        "remedy": json.loads(e.store.scalar(
            "SELECT requested_remedy_json FROM legal_matters WHERE id=?", (matter,)))}


@pytest.mark.parametrize("surface", ["assessment", "decision"])
def test_decision_service_requires_valid_residence_before_authority_or_payment(population_property, surface):
    world, claimant, respondent = population_property
    e = world.economy
    matter, evidence = open_matter(world, claimant["id"], respondent["id"])
    actor = adjudicator(e)
    assert actor is not None and e.engine_semantics_version == 21
    origin_event = e.store.scalar("SELECT event_id FROM person_residence_events WHERE agent_id=? ORDER BY id LIMIT 1",
                                 (actor["id"],))
    original_payload = e.store.scalar("SELECT payload_json FROM events WHERE id=?", (origin_event,))
    e.store.update("events", origin_event, payload_json="{}")
    before = contents(e.store)
    with pytest.raises(ResidenceError):
        if surface == "assessment":
            e.legal_authority.assess(9, actor["id"], e.store.query_one("SELECT * FROM legal_matters WHERE id=?", (matter,)))
        else:
            e.legal.issue_decision(9, actor["id"], award(e, matter, evidence))
    assert contents(e.store) == before
    # Restore only this fixture's injected fault, then settle the existing case.
    e.store.update("events", origin_event, payload_json=original_payload)
    wallet = e.ledger.agent_checking_id(claimant["id"])
    balance = e.ledger.balance(wallet)
    decision = award(e, matter, evidence)
    result = e.legal.issue_decision(9, actor["id"], decision)
    assert result["ok"], result
    assert e.ledger.balance(wallet) == balance + 10
    settled = contents(e.store)
    assert not e.legal.issue_decision(9, actor["id"], decision)["ok"]
    assert contents(e.store) == settled
    e.legal_authority.check_invariants()
    assert e.ledger.reconcile()[0]


def test_absent_official_is_ineligible_even_if_a_stale_role_survives(population_property):
    world, claimant, respondent = population_property
    e = world.economy
    matter, evidence = open_matter(world, claimant["id"], respondent["id"])
    actor = adjudicator(e)
    move(e, actor["id"], 9)
    assert e.store.scalar("SELECT role FROM agents WHERE id=?", (actor["id"],)) is None
    # Fault injection: ordinary departure correctly ended the office. The
    # independent decision boundary must not trust a stale role projection.
    e.store.update("agents", actor["id"], role=actor["role"])
    assessment = e.legal_authority.assess(10, actor["id"],
        e.store.query_one("SELECT * FROM legal_matters WHERE id=?", (matter,)))
    assert not assessment["eligible"]
    before = contents(e.store)
    result = e.legal.issue_decision(10, actor["id"], award(e, matter, evidence))
    assert not result["ok"] and "locally available" in result["reason"]
    after = contents(e.store)
    assert {name for name in before if before[name] != after[name]} == {"events"}
    assert e.store.scalar("SELECT kind FROM events ORDER BY id DESC LIMIT 1") == "legal_decision_recused"
    assert e.ledger.reconcile()[0]


def test_source_audit_rejects_an_outside_decision_after_admission_fault(population_property, monkeypatch):
    world, claimant, respondent = population_property
    e = world.economy
    matter, _ = open_matter(world, claimant["id"], respondent["id"])
    actor = adjudicator(e)
    move(e, actor["id"], 9)
    e.store.update("agents", actor["id"], role=actor["role"])
    with monkeypatch.context() as fault:
        fault.setattr(e.population, "is_available", lambda *_: True)
        fault.setattr(e.population, "is_local", lambda *_: True)
        result = e.legal.issue_decision(10, actor["id"], dismissal(matter))
    assert result["ok"], result
    with pytest.raises(EstateError, match="not locally available at its event"):
        e.legal_authority.check_invariants()
    # Restored residence cannot make a past outside decision valid.
    move(e, actor["id"], 10, cause="return", key="adjudicator-return")
    with pytest.raises(EstateError, match="not locally available at its event"):
        e.legal_authority.check_invariants()


def test_valid_decision_survives_later_same_day_departure_and_return(population_property):
    world, claimant, respondent = population_property
    e = world.economy
    first, evidence = open_matter(world, claimant["id"], respondent["id"])
    second, _ = open_matter(world, claimant["id"], respondent["id"])
    actor = adjudicator(e)
    age_at(e, 9)
    result = e.legal.issue_decision(10, actor["id"], award(e, first, evidence))
    assert result["ok"], result
    proof = dict(e.store.query_one("SELECT * FROM legal_decision_authorities WHERE decision_id=?", (result["decision_id"],)))
    move(e, actor["id"], 9)
    assert not e.population.is_local(actor["id"], 10)
    assert e.population.history.is_living_resident(actor["id"], 10, event_frontier=proof["event_id"]-1)
    e.legal_authority.check_invariants()
    move(e, actor["id"], 10, cause="return", key="valid-judge-return")
    assert e.population.is_available(actor["id"])
    assert e.store.scalar("SELECT role FROM agents WHERE id=?", (actor["id"],)) is None
    before = contents(e.store)
    assert not e.legal.issue_decision(11, actor["id"], dismissal(second))["ok"]
    assert contents(e.store) == before
    assert dict(e.store.query_one("SELECT * FROM legal_decision_authorities WHERE decision_id=?", (result["decision_id"],))) == proof
    e.legal_authority.check_invariants()
    validate(world)


def test_resident_adjudicator_can_enforce_a_retained_claim_against_an_outside_party(population_property):
    world, claimant, respondent = population_property
    e = world.economy
    matter, evidence = open_matter(world, claimant["id"], respondent["id"])
    move(e, respondent["id"], 9)
    wallets = [e.ledger.agent_checking_id(person["id"]) for person in (claimant, respondent)]
    before = [e.ledger.balance(wallet) for wallet in wallets]
    actor = adjudicator(e)
    result = e.legal.issue_decision(10, actor["id"], award(e, matter, evidence))
    assert result["ok"], result
    assert [e.ledger.balance(wallet)-balance for wallet, balance in zip(wallets, before)] == [10, -10]
    assert not e.population.is_available(respondent["id"])
    e.legal_authority.check_invariants()
    e.legal_representation.check_invariants()
    validate(world)

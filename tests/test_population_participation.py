"""Draft local benefits, ballots and household consent across departure/return.

These domain fixtures do not enable public Semantics 21 or substitute for the
remaining full World source/restart/replay/export acceptance.
"""
import hashlib
import json
from pathlib import Path
import random
import shutil

import pytest

from agents.policies import _household_decision
from engine.core import Economy
from engine.government import Government
from engine.households import HouseholdError
from engine.population import MovementError, PopulationBoundary
from engine.population_history import ResidenceError
from engine.store import Store

from .test_population_authority import finance
from .test_population_movements import advance, moving, propose
from .test_population_residence_history import contents, residence_case
from .test_semantics20_estate_cases import estate_case


def enable(e):
    e.engine_semantics_version = e.labor.engine_semantics_version = 21
    e.gov.engine_semantics_version = 21
    e.population = PopulationBoundary(e)
    e.labor.population = e.gov.population = e.population
    e.gov.enabled = True
    e.gov.p.update(unemployment_benefit_cents=7, benefit_interval_ticks=1,
                   election_interval_ticks=0, benefit_step_cents=2)


@pytest.fixture
def participating(moving):
    enable(moving.e)
    moving.e.gov.initialize(0)
    return moving


def depart(c):
    identity = propose(c)
    advance(c, 1)
    assert c.e.population.settle(1, identity)["status"] == "applied"


def return_home(c):
    identity = propose(c, tick=1, due=2, cause="return", destination=1, key="back")
    advance(c, 2)
    assert c.e.population.settle(2, identity)["status"] == "applied"


def test_departure_excludes_new_benefits_and_return_resumes_without_an_endowment(participating):
    c, e = participating, participating.e
    depart(c)
    e.gov.run_nightly(1)
    assert e.ledger.balance(c.wallet) == 100
    assert e.ledger.balance(c.heir_wallet) == 7
    assert [r[0] for r in e.store.query("SELECT subject_id FROM events WHERE kind='benefit_paid'")] == [c.heir]
    before_return = finance(e)
    return_home(c)
    assert finance(e) == before_return
    e.gov.run_nightly(2)
    assert e.ledger.balance(c.wallet) == 107
    assert e.ledger.balance(c.heir_wallet) == 14
    assert e.gov.treasury_balance() == -21
    assert e.ledger.reconcile()[0]
    assert e.store.scalar("SELECT COUNT(*) FROM agents") == 2
    assert e.store.scalar("SELECT COUNT(*) FROM events WHERE kind='arrival'") == 0


@pytest.mark.parametrize("version", [1, 2, 17, 20])
def test_older_fiscal_semantics_ignore_draft_residence(participating, version):
    c, e = participating, participating.e
    depart(c)
    legacy = Government(e.store, e.ledger, {"unemployment_benefit_cents": 7,
        "benefit_interval_ticks": 1, "election_interval_ticks": 0},
        engine_semantics_version=version)
    # No population service is attached to this legacy institution.
    legacy.run_nightly(1)
    assert e.ledger.balance(c.wallet) == 107
    assert e.ledger.balance(c.heir_wallet) == 7
    assert legacy.hold_election(1)["turnout"] == 2
    assert e.ledger.reconcile()[0]


def test_election_uses_local_voters_and_restores_returning_adults(participating):
    c, e = participating, participating.e
    e.store.update("agents", c.person, political_lean=-1.0)
    e.store.update("agents", c.heir, political_lean=1.0)
    depart(c)
    before = finance(e)
    result = e.gov.hold_election(1)
    assert (result["turnout"], result["expand_votes"], result["austerity_votes"]) == (1, 0, 1)
    assert result["direction"] == "austerity"
    assert finance(e) == before
    return_home(c)
    result = e.gov.hold_election(2)
    assert (result["turnout"], result["expand_votes"], result["austerity_votes"]) == (2, 1, 1)


def test_no_residents_means_no_benefits_and_no_fiscal_mandate(participating):
    c, e = participating, participating.e
    first = propose(c)
    second = e.population.propose(0, c.heir, "departure", [c.heir], "second", due_tick=1)["movement_id"]
    advance(c, 1)
    for identity in (first, second):
        assert e.population.settle(1, identity)["status"] == "applied"
    before = finance(e)
    fiscal = e.gov.tax_rate_bps(), e.gov.benefit_cents()
    e.gov.run_nightly(1)
    result = e.gov.hold_election(1)
    assert result["turnout"] == 0 and result["direction"] == "no_voters"
    assert (e.gov.tax_rate_bps(), e.gov.benefit_cents()) == fiscal
    assert not e.store.query("SELECT 1 FROM events WHERE kind='benefit_paid'")
    assert finance(e) == before
    assert e.ledger.reconcile()[0]


@pytest.mark.parametrize("fault", ["missing_service", "corrupt_history"])
@pytest.mark.parametrize("operation", ["benefits", "election"])
def test_unknown_residence_refuses_fiscal_effects_before_any_payment(participating, fault, operation):
    c, e = participating, participating.e
    if fault == "missing_service":
        e.gov.population = None
    else:
        # Corrupt the later person's evidence: the first person must not be paid.
        event = e.store.scalar("SELECT event_id FROM person_residence_events WHERE agent_id=?", (c.heir,))
        e.store.update("events", event, payload_json="{}")
    before = contents(e.store)
    with pytest.raises(ResidenceError):
        (e.gov.run_nightly if operation == "benefits" else e.gov.hold_election)(1)
    assert contents(e.store) == before


def test_failed_nightly_benefit_rolls_back_ledger_and_retry_pays_once(participating, monkeypatch):
    c, e = participating, participating.e
    depart(c)
    before = contents(e.store)
    original = e.store.log_event

    def fail(tick, kind, *args, **kwargs):
        if kind == "benefit_paid":
            raise RuntimeError("injected benefit receipt failure")
        return original(tick, kind, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(e.store, "log_event", fail)
        with pytest.raises(RuntimeError, match="injected"):
            # Match the World caller's transaction boundary.
            with e.store.savepoint("nightly_trial"):
                e.gov.run_nightly(1)
    assert contents(e.store) == before
    with e.store.savepoint("nightly_trial"):
        e.gov.run_nightly(1)
    assert e.ledger.balance(c.wallet) == 100
    assert e.ledger.balance(c.heir_wallet) == 7
    assert e.store.scalar("SELECT COUNT(*) FROM events WHERE kind='benefit_paid'") == 1
    assert e.ledger.reconcile()[0]


@pytest.mark.parametrize("outside_is_actor", [False, True])
def test_partnership_requires_both_residents_and_return_requires_new_consent(participating, outside_is_actor):
    c, e = participating, participating.e
    depart(c)
    actor, partner = (c.person, c.heir) if outside_is_actor else (c.heir, c.person)
    before = contents(e.store)
    with pytest.raises(HouseholdError, match="local resident"):
        e.families.propose(1, actor, "partnership", "pair", partner_id=partner)
    assert e.families.decision_context(c.person, 1) is None
    assert not e.families.decision_context(c.heir, 1)["candidates"]
    assert contents(e.store) == before
    return_home(c)
    financial = finance(e)
    proposal = e.families.propose(2, actor, "partnership", "pair", partner_id=partner)
    assert proposal["status"] == "pending"
    identity = proposal["household_decision_id"]
    assert e.families.respond(2, partner, identity, "accept")["status"] == "applied"
    assert e.families.partnership(actor) is not None
    assert finance(e) == financial


def test_scripted_matching_cannot_recreate_a_departed_partner(participating):
    c, e = participating, participating.e
    e.families.p.update(scripted_matching=True, formation_interval_days=1)
    depart(c)
    for actor in (c.person, c.heir):
        assert _household_decision({"household_decisions": e.families.decision_context(actor, 1)}) is None
    assert e.store.scalar("SELECT COUNT(*) FROM household_decisions") == 0
    return_home(c)
    proposal = _household_decision({"household_decisions": e.families.decision_context(c.person, 2)})["actions"][0]
    assert proposal["type"] == "propose_partnership" and proposal["partner_id"] == c.heir
    identity = e.families.propose(2, c.person, "partnership", proposal["request_key"],
                                  partner_id=c.heir)["household_decision_id"]
    response = _household_decision({"household_decisions": e.families.decision_context(c.heir, 2)})["actions"][0]
    assert response == {"type": "respond_household", "household_decision_id": identity, "decision": "accept"}
    assert e.families.respond(2, c.heir, identity, response["decision"])["status"] == "applied"
    assert e.store.scalar("SELECT COUNT(*) FROM partnerships") == 1
    assert e.store.scalar("SELECT COUNT(*) FROM llm_calls") == 0


def test_whole_family_outside_retains_existing_partnership_and_parentage(participating):
    c, e = participating, participating.e
    identity = e.families.propose(0, c.person, "partnership", "pair", partner_id=c.heir)["household_decision_id"]
    e.families.respond(0, c.heir, identity, "accept")
    advance(c, 1)
    child = e.households.birth(1, c.person)
    e.households.record_census(1)
    partnership = dict(e.families.partnership(c.person))
    parentage = [tuple(r) for r in e.store.query("SELECT * FROM parent_child_relations ORDER BY id")]
    financial = finance(e)
    members = [c.person, c.heir, child]
    care = [{"child_id": child, "guardian_id": c.person}]
    movement = propose(c, members, tick=1, due=2, care=care)
    e.population.respond(1, c.heir, movement, "accept")
    advance(c, 2)
    assert e.population.settle(2, movement)["status"] == "applied"
    e.families.run_nightly(2)
    assert dict(e.families.partnership(c.person)) == partnership
    assert e.families.decision_context(c.person, 2) is None
    returned = propose(c, members, tick=2, due=3, key="family-back", cause="return", destination=1, care=care)
    e.population.respond(2, c.heir, returned, "accept")
    advance(c, 3)
    assert e.population.settle(3, returned)["status"] == "applied"
    e.families.run_nightly(3)
    assert dict(e.families.partnership(c.person)) == partnership
    assert [tuple(r) for r in e.store.query("SELECT * FROM parent_child_relations ORDER BY id")] == parentage
    assert finance(e) == financial
    e.households.check_invariants(3)
    assert e.ledger.reconcile()[0]


def test_return_does_not_revive_old_household_assent(participating):
    c, e = participating, participating.e
    old = e.families.propose(0, c.heir, "partnership", "old-pair", partner_id=c.person)["household_decision_id"]
    before = contents(e.store)
    with pytest.raises(MovementError, match="pending household agreement"):
        propose(c)
    assert contents(e.store) == before
    assert e.families.cancel(0, c.heir, old)["status"] == "cancelled"
    depart(c)
    assert e.store.scalar("SELECT status FROM household_decisions WHERE id=?", (old,)) == "cancelled"
    return_home(c)
    before = contents(e.store)
    with pytest.raises(HouseholdError, match="no longer pending"):
        e.families.respond(2, c.person, old, "accept")
    assert contents(e.store) == before
    assert e.families.partnership(c.person) is None


def test_fiscal_and_household_changes_match_after_store_reopen(participating, tmp_path):
    c, e = participating, participating.e
    propose(c)
    source = Path(e.store.conn.execute("PRAGMA database_list").fetchone()[2])
    e.store.close()
    stamp = hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns
    results = []
    for restart in (False, True):
        target = tmp_path / ("restart.db" if restart else "continuous.db")
        shutil.copy2(source, target)
        store = None
        try:
            for tick in range(1, 7):
                if store is None:
                    store = Store(target)
                    config = json.loads(store.scalar("SELECT config_json FROM run_meta"))
                    current = Economy(store, config, random.Random(1), random.Random(2))
                    enable(current)
                    current.gov.p["election_interval_ticks"] = 2
                with store.savepoint("participation_day"):
                    for person in store.query("SELECT * FROM agents WHERE alive=1 ORDER BY id"):
                        current.households.advance_age(tick, person)
                    current.population.run_nightly(tick)
                    if tick == 1:
                        current.population.propose(1, c.person, "return", [c.person], "back", due_tick=4,
                                                   destination_region_id=1)
                    current.gov.run_nightly(tick)
                    current.families.run_nightly(tick)
                    if tick == 5:
                        current.families.propose(5, c.person, "partnership", "pair", partner_id=c.heir)
                    if tick == 6:
                        identity = store.scalar("SELECT id FROM household_decisions WHERE request_key='pair'")
                        current.families.respond(6, c.heir, identity, "accept")
                    current.households.record_census(tick)
                if restart and tick in (2, 5):
                    store.close()
                    store = None
            assert current.families.partnership(c.person) is not None
            assert not store.query("SELECT 1 FROM events WHERE kind='benefit_paid' AND subject_id=? AND tick<4", (c.person,))
            current.households.check_invariants(6)
            current.population.commitments.check_invariants()
            assert current.ledger.reconcile()[0]
            state = contents(store)
            # Only the existing hash-contract wall clocks vary between copies.
            contract = json.loads((Path(__file__).resolve().parents[1]/"research/hash-contract-v2.json").read_text())
            for table in ("events", "transactions"):
                assert contract["excluded_columns"][table] == ["created_at"]
                columns = [r[1] for r in store.conn.execute(f"PRAGMA table_info({table})") if r[1] != "created_at"]
                state[table] = [tuple(row[name] for name in columns) for row in store.query(f"SELECT * FROM {table} ORDER BY id")]
            results.append(state)
        finally:
            if store is not None:
                store.close()
    assert results[0] == results[1]
    assert (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns) == stamp

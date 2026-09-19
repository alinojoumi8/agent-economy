"""Draft local authority after an agreed departure, without asset confiscation.

Disposable fixtures select the draft domain services after ordinary genesis.
This is not an enabled Semantics-21 World or a full recorded replay proof.
"""
import json

import pytest

from engine.business_control import BusinessControlError
from engine.estates import EstateError
from engine.migrations.v026_population_residence import SQL
from engine.population import PopulationBoundary
from engine.population_history import ResidenceHistory
from engine.project_rights import interests_at, steward_at

from .conftest import make_agent
from .test_population_movements import moving, advance, join, propose
from .test_population_residence_history import residence_case, contents
from .test_semantics20_estate_cases import estate_case
from .test_semantics19_estate_cash import spent_loan
from .test_semantics20_project_rights import property_world, validate
from .test_semantics20_civic_succession import city_world, under_review, apply, decide
from .test_semantics13_construction import _advance_to_building
from .test_semantics20_legal_authority import open_matter
from .test_semantics20_legal_representation import act


def enable_draft(world):
    e = world.economy
    e.store.conn.executescript(SQL)
    history = ResidenceHistory(e.store)
    for row in e.store.query("SELECT agent_id FROM person_lifecycle ORDER BY agent_id"):
        history.record_origin(row["agent_id"])
    history.record_census(0)
    e.engine_semantics_version = e.labor.engine_semantics_version = 21
    e.population = PopulationBoundary(e)
    e.labor.population = e.population
    e.city.engine_semantics_version = 21
    world.runtime.executor.engine_semantics_version = 21
    return world


@pytest.fixture
def population_city(city_world):
    return enable_draft(city_world)


@pytest.fixture
def population_property(property_world):
    world, owner, heir = property_world
    return enable_draft(world), owner, heir


def age_at(e, tick):
    for row in e.store.query("SELECT * FROM agents WHERE alive=1 ORDER BY id"):
        e.households.advance_age(tick, row)


def move(e, actor, tick, *, cause="departure", key="trip", members=None):
    age_at(e, tick)
    household = e.households.membership(actor)["household_id"]
    adults = e.store.query("SELECT a.id,a.age FROM household_memberships m JOIN agents a ON a.id=m.agent_id "
        "WHERE m.household_id=? AND m.left_tick IS NULL AND a.alive=1 ORDER BY a.id", (household,))
    assert all(row["age"] >= 18 for row in adults), "this authority fixture has no dependent care proposal"
    result = e.population.propose(tick, actor, cause, members or [actor], key, due_tick=tick+1,
        destination_region_id=e.store.scalar("SELECT region_id FROM agents WHERE id=?", (actor,)) if cause == "return" else None)
    movement = result["movement_id"]
    for row in adults:
        if row["id"] != actor:
            e.population.respond(tick, row["id"], movement, "accept")
    age_at(e, tick+1)
    assert e.population.settle(tick+1, movement)["status"] == "applied"
    return movement


def finance(e):
    return {table: [tuple(row) for row in e.store.query(f'SELECT * FROM "{table}" ORDER BY rowid')]
        for table in ("accounts", "ledger_entries", "transactions", "shares", "loans", "estate_beneficiaries")}


def test_departing_owner_keeps_shares_but_local_shareholder_operates(moving):
    c = moving
    firm = c.e.firms.found_firm(0, c.person, "Joint company", "manufacturing", shares=100)
    # Declared initial capital allocation, not a simulated stock-market trade.
    c.e.exchange._adjust_shares(firm, "agent", c.person, -40)
    c.e.exchange._adjust_shares(firm, "agent", c.heir, 40)
    before = finance(c.e)
    movement = propose(c)
    advance(c, 1)
    c.e.population.settle(1, movement)
    assert c.e.business_control.operator_at(firm, 0) == c.person
    assert c.e.business_control.operator_at(firm, 1) == c.heir
    assert not c.e.business_control.controls(c.person, firm)
    assert c.e.business_control.controls(c.heir, firm)
    assert c.e.store.scalar("SELECT founder_agent_id FROM firms WHERE id=?", (firm,)) == c.person
    with pytest.raises(BusinessControlError, match="locally available"):
        c.e.business_control.replace(1, firm, c.person, capacity="shareholder")
    assert finance(c.e) == before
    c.e.business_control.check_invariants()
    assert c.e.ledger.reconcile()[0]


def test_sole_owner_vacancy_and_return_reuse_identity_and_ownership(moving):
    c = moving
    firm = c.e.firms.found_firm(0, c.person, "Owner returns", "manufacturing", shares=100)
    before = finance(c.e)
    move(c.e, c.person, 0)
    assert c.e.business_control.operator_at(firm) is None
    assert c.e.store.scalar("SELECT capacity FROM firm_stewardships WHERE firm_id=? AND ended_tick IS NULL", (firm,)) == "vacant"
    move(c.e, c.person, 1, cause="return", key="return")
    assert c.e.business_control.controls(c.person, firm)
    assert c.e.business_control.operator_at(firm, 1) is None
    assert finance(c.e) == before


def test_group_departure_marks_every_candidate_outside_before_succession(moving):
    c = moving
    join(c)
    firm = c.e.firms.found_firm(0, c.person, "Group ownership", "manufacturing", shares=100)
    c.e.exchange._adjust_shares(firm, "agent", c.person, -40)
    c.e.exchange._adjust_shares(firm, "agent", c.heir, 40)
    movement = propose(c, [c.person, c.heir])
    c.e.population.respond(0, c.heir, movement, "accept")
    advance(c, 1)
    c.e.population.settle(1, movement)
    assert c.e.business_control.operator_at(firm) is None
    assert not c.e.population.is_available(c.person) and not c.e.population.is_available(c.heir)
    assert c.e.store.scalar("SELECT SUM(qty) FROM shares WHERE firm_id=?", (firm,)) == 100


def test_failed_succession_rolls_back_residence_household_role_and_assets(moving, monkeypatch):
    c = moving
    firm = c.e.firms.found_firm(0, c.person, "Atomic authority", "manufacturing", shares=100)
    c.e.store.update("agents", c.person, role="founder")
    movement = propose(c)
    advance(c, 1)
    before = contents(c.e.store)
    original = c.e.business_control.replace

    def fail_after_replacement(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected succession failure")

    monkeypatch.setattr(c.e.business_control, "replace", fail_after_replacement)
    with pytest.raises(RuntimeError, match="injected succession"):
        c.e.population.settle(1, movement)
    assert contents(c.e.store) == before
    assert c.e.population.is_available(c.person)
    assert c.e.business_control.operator_at(firm) == c.person
    monkeypatch.setattr(c.e.business_control, "replace", original)
    assert c.e.population.settle(1, movement)["status"] == "applied"


def test_departed_clerk_releases_work_for_existing_local_successor(population_city):
    world = population_city
    e, store = world.economy, world.store
    applicant, case, task, tick = under_review(world)
    clerk = task["assigned_agent_id"]
    original_case = dict(store.query_one("SELECT * FROM service_cases WHERE id=?", (case,)))
    before = finance(e)
    people = store.scalar("SELECT COUNT(*) FROM agents")
    movement = move(e, clerk, tick)
    assert dict(store.query_one("SELECT * FROM service_cases WHERE id=?", (case,))) == original_case
    assert tuple(store.query_one("SELECT status,assigned_agent_id FROM institution_tasks WHERE id=?", (task["id"],))) == ("pending", None)
    assert not decide(world, tick+1, clerk, case)["ok"]
    e.city.run_nightly(tick+1)
    successor = store.scalar("SELECT assigned_agent_id FROM institution_tasks WHERE id=?", (task["id"],))
    assert successor is not None and successor != clerk and e.population.is_available(successor)
    assert decide(world, tick+1, successor, case)["ok"]
    assert store.scalar("SELECT COUNT(*) FROM agents") == people
    assert finance(e) == before
    assert store.scalar("SELECT COUNT(*) FROM events WHERE kind='population_authority_released' "
        "AND json_extract(payload_json,'$.movement_id')=?", (movement,)) >= 2
    e.civic_authority.check_invariants()


def test_clerk_vacancy_skips_an_outside_candidate_until_the_same_person_returns(population_city):
    world = population_city
    e = world.economy
    applicant, case, task, tick = under_review(world)
    clerk = task["assigned_agent_id"]
    region = e.store.scalar("SELECT region_id FROM agents WHERE id=?", (clerk,))
    candidates = e.store.query("SELECT a.id FROM agents a WHERE a.region_id=? AND a.alive=1 "
        "AND a.kind='citizen' AND a.role IS NULL AND a.employer_id IS NULL AND a.age>=18 AND a.retired=0 "
        "AND NOT EXISTS (SELECT 1 FROM employments j WHERE j.agent_id=a.id AND j.status='active') "
        "AND NOT EXISTS (SELECT 1 FROM firm_operations f WHERE f.operator_agent_id=a.id "
        "AND f.status IN ('private','listed')) ORDER BY a.id", (region,))
    candidate = next(row["id"] for row in candidates if row["id"] != applicant)
    # Constrain the fixture to one otherwise qualified candidate; departure and
    # return still use the actual proposal, assent and settlement services.
    for row in candidates:
        if row["id"] != candidate:
            e.store.update("agents", row["id"], retired=1)
    before = finance(e)
    people = e.store.scalar("SELECT COUNT(*) FROM agents")
    move(e, candidate, tick, key="candidate-departs")
    move(e, clerk, tick+1, key="clerk-departs")
    e.city.run_nightly(tick+2)
    assert tuple(e.store.query_one("SELECT status,assigned_agent_id FROM institution_tasks WHERE id=?", (task["id"],))) == ("pending", None)
    move(e, candidate, tick+2, cause="return", key="candidate-returns")
    e.city.run_nightly(tick+3)
    assert e.store.scalar("SELECT assigned_agent_id FROM institution_tasks WHERE id=?", (task["id"],)) == candidate
    assert e.store.scalar("SELECT COUNT(*) FROM agents") == people
    assert finance(e) == before


@pytest.mark.parametrize("departing", ["applicant", "lawyer"])
def test_pending_personal_application_ends_without_refunding_paid_fees(population_city, departing):
    world = population_city
    e = world.economy
    applicant, case = apply(world)
    e.city.finalize(1)
    person = applicant if departing == "applicant" else e.store.scalar("SELECT lawyer_agent_id FROM service_cases WHERE id=?", (case,))
    before = finance(e)
    move(e, person, 1)
    row = e.store.query_one("SELECT status,reason_code FROM service_cases WHERE id=?", (case,))
    assert tuple(row) == ("abandoned", f"{departing}_departed")
    assert not e.store.query("SELECT * FROM service_appointments WHERE case_id=? AND status='scheduled'", (case,))
    assert finance(e) == before
    assert not e.store.query("SELECT * FROM estate_cases")
    e.civic_authority.check_invariants()


def test_departure_ends_legislative_and_agency_office_and_return_does_not_restore(population_city):
    world = population_city
    e = world.economy
    legislator = e.store.query_one("SELECT * FROM legislators WHERE active=1 ORDER BY id LIMIT 1")
    assert legislator is not None
    person = legislator["agent_id"]
    agency = e.store.query_one("SELECT * FROM agencies ORDER BY id LIMIT 1")
    # Declare this legislator also holds an agency leadership appointment.
    e.store.update("agencies", agency["id"], leader_agent_id=person)
    before = finance(e)
    move(e, person, 0)
    assert tuple(e.store.query_one("SELECT active,term_end_tick FROM legislators WHERE id=?", (legislator["id"],))) == (0, 1)
    assert e.store.scalar("SELECT leader_agent_id FROM agencies WHERE id=?", (agency["id"],)) is None
    move(e, person, 1, cause="return", key="office-return")
    assert e.store.scalar("SELECT active FROM legislators WHERE id=?", (legislator["id"],)) == 0
    assert e.store.scalar("SELECT role FROM agents WHERE id=?", (person,)) is None
    assert finance(e) == before


@pytest.mark.parametrize("departing", ["applicant", "lawyer"])
def test_departure_revokes_unused_personal_permit_without_rewriting_approved_case(population_city, departing):
    world = population_city
    e = world.economy
    applicant, case, task, tick = under_review(world)
    assert decide(world, tick, task["assigned_agent_id"], case)["ok"]
    permit = dict(e.store.query_one("SELECT * FROM civic_authorizations WHERE case_id=?", (case,)))
    original_case = dict(e.store.query_one("SELECT * FROM service_cases WHERE id=?", (case,)))
    person = applicant if departing == "applicant" else original_case["lawyer_agent_id"]
    before = finance(e)
    move(e, person, tick)
    assert e.store.scalar("SELECT status FROM civic_authorizations WHERE id=?", (permit["id"],)) == "revoked"
    assert e.store.scalar("SELECT holder_agent_id FROM civic_authorizations WHERE id=?", (permit["id"],)) == applicant
    assert dict(e.store.query_one("SELECT * FROM service_cases WHERE id=?", (case,))) == original_case
    assert finance(e) == before
    e.civic_authority.check_invariants()


@pytest.mark.parametrize("binding", ["applicant", "staff"])
def test_city_closure_failure_rolls_back_the_entire_departure(population_city, monkeypatch, binding):
    world = population_city
    e = world.economy
    applicant, case, task, tick = under_review(world)
    person = applicant if binding == "applicant" else task["assigned_agent_id"]
    method = "_abandon_personal_case" if binding == "applicant" else "_end_staff_assignment"
    original = getattr(e.city, method)
    observed = {}

    def fail_after_closure(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected departure closure")

    original_settle = e.population.settle

    def save_before_settlement(*args, **kwargs):
        observed["before"] = contents(e.store)
        return original_settle(*args, **kwargs)

    monkeypatch.setattr(e.city, method, fail_after_closure)
    monkeypatch.setattr(e.population, "settle", save_before_settlement)
    with pytest.raises(RuntimeError, match="injected departure closure"):
        move(e, person, tick)
    assert contents(e.store) == observed["before"]
    assert e.population.is_available(person)
    assert e.store.scalar("SELECT status FROM service_cases WHERE id=?", (case,)) == "under_review"


def test_departure_keeps_property_title_and_funding_while_control_waits_for_return(population_property):
    world, owner, _ = population_property
    e = world.economy
    project, _ = _advance_to_building(world, owner)
    before = finance(e)
    original = dict(e.construction._project(project))
    title = interests_at(e.store, project)
    move(e, owner["id"], 4)
    assert steward_at(e.store, project)["steward_agent_id"] is None
    assert steward_at(e.store, project, 4)["steward_agent_id"] == owner["id"]
    assert not e.project_rights.controls(owner["id"], e.construction._project(project))
    assert interests_at(e.store, project) == title
    assert dict(e.construction._project(project)) == original
    move(e, owner["id"], 5, cause="return", key="property-return")
    assert e.project_rights.controls(owner["id"], e.construction._project(project))
    assert finance(e) == before
    validate(world)


@pytest.mark.parametrize("accepted", [False, True])
def test_departed_client_keeps_only_a_previously_accepted_resident_counsel(population_property, accepted):
    world, owner, other = population_property
    e = world.economy
    matter, evidence = open_matter(world, owner["id"], other["id"])
    lawyer = e.store.scalar("SELECT id FROM agents WHERE role='lawyer' AND alive=1 ORDER BY id LIMIT 1")
    request = act(world, 9, owner["id"], "request_legal_counsel", matter_id=matter, side="claimant",
        counsel_agent_id=lawyer, scopes=["submit_filing"])["request_id"]
    if accepted:
        act(world, 9, lawyer, "respond_legal_counsel", request_id=request, decision="accept")
    move(e, owner["id"], 9)
    filing = {"type": "submit_filing", "matter_id": matter, "filer_type": "agent", "filer_id": owner["id"],
        "filing_type": "evidence", "evidence_event_ids": [evidence], "body": "Existing resident counsel continues the case."}
    assert not world.runtime.executor.execute_action(10, owner["id"], filing)["ok"]
    result = world.runtime.executor.execute_action(10, lawyer, filing)
    assert bool(result["ok"]) is accepted, result
    ended = e.store.scalar("SELECT reason FROM legal_counsel_ends WHERE request_id=?", (request,))
    assert ended is None if accepted else ended == "client_authority_lost"
    if accepted:
        assert e.store.scalar("SELECT filer_id FROM legal_filings WHERE id=?", (result["filing_id"],)) == owner["id"]
    e.legal_representation.check_invariants()


def test_departed_counsel_loses_mandate_but_past_filings_remain(population_property):
    world, owner, other = population_property
    e = world.economy
    matter, evidence = open_matter(world, owner["id"], other["id"])
    lawyer = e.store.scalar("SELECT id FROM agents WHERE role='lawyer' AND alive=1 ORDER BY id LIMIT 1")
    request = act(world, 9, owner["id"], "request_legal_counsel", matter_id=matter, side="claimant",
        counsel_agent_id=lawyer, scopes=["submit_filing"])["request_id"]
    act(world, 9, lawyer, "respond_legal_counsel", request_id=request, decision="accept")
    filing = {"type": "submit_filing", "matter_id": matter, "filer_type": "agent", "filer_id": owner["id"],
        "filing_type": "evidence", "evidence_event_ids": [evidence], "body": "A valid filing before departure."}
    first = world.runtime.executor.execute_action(9, lawyer, filing)
    assert first["ok"], first
    original = dict(e.store.query_one("SELECT * FROM legal_filings WHERE id=?", (first["filing_id"],)))
    move(e, lawyer, 9)
    assert e.store.scalar("SELECT reason FROM legal_counsel_ends WHERE request_id=?", (request,)) == "counsel_unavailable"
    assert not e.legal._is_lawyer(lawyer)
    assert not world.runtime.executor.execute_action(10, lawyer, filing)["ok"]
    assert dict(e.store.query_one("SELECT * FROM legal_filings WHERE id=?", (first["filing_id"],))) == original
    e.legal_representation.check_invariants()


def test_organization_mandate_ends_when_its_requester_leaves(population_property):
    world, owner, other = population_property
    e = world.economy
    firm = e.firms.found_firm(0, owner["id"], "Company client", "manufacturing", shares=100)
    matter = act(world, 8, owner["id"], "file_claim", claimant={"type": "firm", "id": firm},
        respondent={"type": "agent", "id": other["id"]}, claim_type="disputed_loss",
        requested_remedy={"type": "dismissal"})["matter_id"]
    lawyer = e.store.scalar("SELECT id FROM agents WHERE role='lawyer' AND alive=1 ORDER BY id LIMIT 1")
    request = act(world, 9, owner["id"], "request_legal_counsel", matter_id=matter, side="claimant",
        counsel_agent_id=lawyer, scopes=["submit_filing"])["request_id"]
    act(world, 9, lawyer, "respond_legal_counsel", request_id=request, decision="accept")
    move(e, owner["id"], 9)
    assert e.store.scalar("SELECT reason FROM legal_counsel_ends WHERE request_id=?", (request,)) == "client_authority_lost"
    assert e.exchange.shares_held(firm, "agent", owner["id"]) == 100
    e.legal_representation.check_invariants()


def test_source_audit_rejects_outside_filing_even_if_admission_gate_failed(population_property, monkeypatch):
    world, owner, other = population_property
    e = world.economy
    matter, evidence = open_matter(world, owner["id"], other["id"])
    move(e, owner["id"], 9)
    filing = {"type": "submit_filing", "matter_id": matter, "filer_type": "agent", "filer_id": owner["id"],
        "filing_type": "evidence", "evidence_event_ids": [evidence], "body": "Injected admission fault."}
    with monkeypatch.context() as fault:
        fault.setattr(e.population, "is_local", lambda *_: True)
        fault.setattr(e.population, "is_available", lambda *_: True)
        result = world.runtime.executor.execute_action(10, owner["id"], filing)
    assert result["ok"], result
    with pytest.raises(EstateError, match="not locally available at its event"):
        e.legal_representation.check_invariants()


def test_unknown_people_have_no_legal_or_property_authority(population_property):
    world, owner, _ = population_property
    e = world.economy
    project, _ = _advance_to_building(world, owner)
    missing = e.store.scalar("SELECT MAX(id)+1 FROM agents")
    assert not e.legal.controls(missing, "agent", missing)
    assert not e.legal._is_lawyer(missing)
    assert not e.project_rights.controls(missing, e.construction._project(project))


def test_outside_beneficiary_keeps_estate_interest_with_local_trustee_or_vacancy(moving):
    c = moving
    firm = c.e.firms.found_firm(0, c.person, "Estate remains", "manufacturing", shares=100)
    spent_loan(c.e, c.bank, c.person, c.wallet, 300)
    advance(c, 1)
    trustee, _ = make_agent(c.e, c.bank, "Local trustee", cash=0, region_id=1, role="gov_official", arrived_tick=1)
    c.e.households.register_person(1, trustee, "arrival")
    c.e.lifecycle.settle_death(1, c.person)
    estate = c.e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (c.person,))
    assert c.e.estate_securities.beneficiary_representatives(estate)
    before = finance(c.e)
    move(c.e, c.heir, 1)
    assert not c.e.estate_securities.beneficiary_representatives(estate)
    assert c.e.estate_administration.current(estate)["administrator_agent_id"] == trustee
    assert c.e.business_control.operator_at(firm) == trustee
    assert finance(c.e) == before
    move(c.e, trustee, 2, key="trustee-trip")
    assert c.e.estate_administration.current(estate)["administrator_agent_id"] is None
    assert c.e.business_control.operator_at(firm) is None
    assert finance(c.e) == before
    c.e.estate_administration.check_invariants()
    c.e.estate_cases.check_invariants()
    assert c.e.ledger.reconcile()[0]

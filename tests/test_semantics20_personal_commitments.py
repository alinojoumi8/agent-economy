"""Personal negotiations end at death; surviving institutions keep their records."""
import asyncio
import copy
import hashlib
import json

import pytest

from agents.memory import Memory
from agents.prompts import ContextBuilder
from engine.actions import ActionExecutor
from engine.estates import EstateError
from engine.lifecycle import Lifecycle
from research.hashing import canonical_hashes
from world.replay_verify import verify_replay

from .test_semantics12_civic_city import _lawyer_id, _same_region_applicants, civic_world
from .test_semantics17_household_decisions import _world
from .test_semantics20_civic_succession import city_world, civic_config, available_adult, apply, under_review, decide
from .test_semantics20_personal_authority import item_for, validate
from .test_semantics20_succession import succession


def negotiate(e, firm, operator, candidate, *, tick=1, counter=False):
    executor = ActionExecutor(e)
    job = e.labor.post_job(tick, firm, "Continuing vacancy", 1000)
    application = e.labor.apply_job(tick, candidate, job)
    assert application is not None
    offered = executor.execute_action(tick, operator, {"type": "make_job_offer", "application_id": application, "wage": 1000})
    assert offered["ok"], offered
    first = offered["offer_id"]
    if counter:
        offered = executor.execute_action(tick, candidate, {"type": "counter_job_offer", "offer_id": first, "wage": 1200})
        assert offered["ok"], offered
    return executor, job, application, first, offered["offer_id"]


@pytest.mark.parametrize("counter", [False, True])
def test_candidate_death_closes_pending_and_negotiating_requests_without_cancelling_the_job(succession, counter):
    e, _, founder, heir, candidate, firm = succession
    executor, job, application, first, offer = negotiate(e, firm, founder, candidate, counter=counter)
    second_job = e.labor.post_job(1, firm, "Another vacancy", 1000)
    pending = e.labor.apply_job(1, candidate, second_job)
    app_before = dict(e.store.query_one("SELECT * FROM applications WHERE id=?", (application,)))
    offer_before = dict(e.store.query_one("SELECT * FROM job_offers WHERE id=?", (offer,)))
    history = dict(e.store.query_one("SELECT * FROM job_offers WHERE id=?", (first,)))
    e.lifecycle.settle_death(2, candidate)
    items = {r["source_id"]: json.loads(r["snapshot_json"]) for r in e.store.query(
        "SELECT i.* FROM estate_items i JOIN estate_cases c ON c.id=i.estate_id "
        "WHERE c.deceased_agent_id=? AND i.kind='job_application'", (candidate,))}
    assert items[application] == app_before and items[pending]["state"] == "pending"
    assert json.loads(item_for(e, candidate, "job_offer")["snapshot_json"]) == offer_before
    assert tuple(e.store.query_one("SELECT status,decided_tick FROM job_offers WHERE id=?", (offer,))) == ("expired", 2)
    assert e.store.scalar("SELECT COUNT(*) FROM applications WHERE agent_id=? AND state='withdrawn'", (candidate,)) == 2
    if counter:
        assert dict(e.store.query_one("SELECT * FROM job_offers WHERE id=?", (first,))) == history
    assert not executor.execute_action(3, founder, {"type": "accept_job_offer", "offer_id": offer})["ok"]
    assert not executor.execute_action(3, candidate, {"type": "accept_job_offer", "offer_id": offer})["ok"]
    assert e.store.scalar("SELECT status FROM jobs WHERE id=?", (job,)) == "open"
    replacement = e.labor.apply_job(3, heir, job)
    new_offer = executor.execute_action(3, founder, {"type": "make_job_offer", "application_id": replacement, "wage": 1100})
    assert new_offer["ok"], new_offer
    assert executor.execute_action(3, heir, {"type": "accept_job_offer", "offer_id": new_offer["offer_id"]})["ok"]
    assert e.store.scalar("SELECT agent_id FROM employments WHERE status='active' AND firm_id=?", (firm,)) == heir
    validate(e)


@pytest.mark.parametrize("counter", [False, True])
def test_company_negotiation_survives_its_representatives_death(succession, counter):
    e, _, founder, heir, candidate, firm = succession
    executor, _, _, _, offer = negotiate(e, firm, founder, candidate, counter=counter)
    before = dict(e.store.query_one("SELECT * FROM job_offers WHERE id=?", (offer,)))
    e.lifecycle.settle_death(2, founder)
    assert e.business_control.operator_at(firm) == heir
    assert dict(e.store.query_one("SELECT * FROM job_offers WHERE id=?", (offer,))) == before
    assert item_for(e, founder, "job_offer") is None
    actor = heir if counter else candidate
    context = ContextBuilder(e, Memory(e.store, e.config), e.config).build(
        e.store.query_one("SELECT * FROM agents WHERE id=?", (actor,)), 3)
    offers = context["firm_job_offers" if counter else "incoming_job_offers"]
    assert offer in {row["offer_id"] for row in offers}
    accepted = executor.execute_action(3, actor, {"type": "accept_job_offer", "offer_id": offer})
    assert accepted["ok"], accepted
    assert e.store.scalar("SELECT firm_id FROM employments WHERE id=?", (accepted["employment_id"],)) == firm
    assert e.store.scalar("SELECT founder_agent_id FROM firms WHERE id=?", (firm,)) == founder
    validate(e)


def test_failed_death_restores_negotiation_and_its_immutable_offer_history(succession, monkeypatch):
    e, _, founder, _, candidate, firm = succession
    negotiate(e, firm, founder, candidate, counter=True)
    original = e.civic_authority.close_person

    def fail_after_inventory(*args):
        original(*args)
        raise RuntimeError("injected commitment failure")

    monkeypatch.setattr(e.civic_authority, "close_person", fail_after_inventory)
    before = canonical_hashes(e.store)["authoritative_sha256"]
    with pytest.raises(RuntimeError, match="injected commitment"):
        e.lifecycle.settle_death(2, candidate)
    assert canonical_hashes(e.store)["authoritative_sha256"] == before
    assert e.estate_cases._pending is None
    monkeypatch.setattr(e.civic_authority, "close_person", original)
    e.lifecycle.settle_death(2, candidate)
    validate(e)


@pytest.mark.parametrize("binding", ["application", "offer"])
def test_reactivated_dead_candidate_negotiation_fails_reconciliation(succession, binding):
    e, _, founder, _, candidate, firm = succession
    _, _, application, _, offer = negotiate(e, firm, founder, candidate)
    e.lifecycle.settle_death(2, candidate)
    if binding == "application":
        e.store.update("applications", application, state="negotiating")
    else:
        e.store.update("job_offers", offer, status="pending")
    with pytest.raises(EstateError, match="deceased candidate retains"):
        e.estate_cases.check_invariants()


def spare_lawyer(world):
    # A second qualified lawyer is declared in the existing genesis population.
    # No person, cash or retroactive qualification is created after a death.
    person = available_adult(world)
    world.store.update("agents", person, occupation="lawyer", role="lawyer")
    return person


@pytest.mark.parametrize("stage", ["applied", "scheduled", "review", "approved"])
def test_lawyer_death_ends_pending_service_and_allows_a_fresh_same_name_application(city_world, stage):
    world = city_world
    e, store = world.economy, world.store
    replacement = spare_lawyer(world)
    lawyer = _lawyer_id(store)
    # The original institutional lawyer has the lower genesis ID.
    assert lawyer != replacement
    if stage in {"review", "approved"}:
        person, case, task, tick = under_review(world)
        if stage == "approved":
            assert decide(world, tick + 1, task["assigned_agent_id"], case)["ok"]
            tick += 1
    else:
        person, case = apply(world)
        tick = 1
        if stage == "scheduled":
            e.city.finalize(tick)
    original = dict(store.query_one("SELECT * FROM service_cases WHERE id=?", (case,)))
    fee = [tuple(r) for r in store.query("SELECT * FROM ledger_entries WHERE txn_id=? ORDER BY id", (original["fee_transaction_id"],))]
    e.lifecycle.settle_death(tick + 1, lawyer)
    if stage == "approved":
        item = item_for(e, lawyer, "civic_counsel_authorization")
        assert json.loads(item["snapshot_json"])["lawyer_agent_id"] == lawyer
        assert store.scalar("SELECT status FROM civic_authorizations WHERE case_id=?", (case,)) == "revoked"
        assert dict(store.query_one("SELECT * FROM service_cases WHERE id=?", (case,))) == original
    else:
        assert json.loads(item_for(e, lawyer, "civic_counsel")["snapshot_json"]) == original
        assert tuple(store.query_one("SELECT status,reason_code FROM service_cases WHERE id=?", (case,))) == ("abandoned", "lawyer_deceased")
        assert not store.scalar("SELECT COUNT(*) FROM institution_tasks WHERE source_case_id=? AND status IN ('pending','assigned')", (case,))
        assert not store.scalar("SELECT COUNT(*) FROM service_appointments WHERE case_id=? AND status='scheduled'", (case,))
    assert [tuple(r) for r in store.query("SELECT * FROM ledger_entries WHERE txn_id=? ORDER BY id", (original["fee_transaction_id"],))] == fee
    assert e.city.active_authorization(person, tick + 1) is None
    payload = json.loads(original["application_payload_json"])
    payload["lawyer_agent_id"] = replacement
    fresh = e.city.apply_business_permit(tick + 2, person, payload)
    assert fresh["ok"], fresh
    assert fresh["case_id"] != case
    e.city.finalize(tick + 2)
    appointment = store.query_one("SELECT * FROM service_appointments WHERE case_id=?", (fresh["case_id"],))
    day = appointment["scheduled_tick"]
    e.city.run_nightly(day)
    e.daily_time.prepare_day(day)
    assert e.city.attend_appointment(day, person, appointment["id"])["ok"]
    e.city.finalize(day)
    clerk = store.scalar("SELECT assigned_agent_id FROM institution_tasks WHERE source_case_id=?", (fresh["case_id"],))
    assert clerk is not None
    approved = decide(world, day + 1, clerk, fresh["case_id"])
    assert approved["ok"], approved
    assert store.scalar("SELECT application_payload_json FROM service_cases WHERE id=?", (case,)) == original["application_payload_json"]
    validate(e)


def test_discretionary_approval_rechecks_qualification_and_finalization_closes_stale_work(city_world):
    world = city_world
    e, store = world.economy, world.store
    _, case, task, tick = under_review(world)
    lawyer = store.scalar("SELECT lawyer_agent_id FROM service_cases WHERE id=?", (case,))
    store.update("agents", lawyer, occupation="retired adviser")
    before = canonical_hashes(store)["authoritative_sha256"]
    rejected = decide(world, tick + 1, task["assigned_agent_id"], case)
    assert rejected == {"ok": False, "reason": "dead_or_unqualified_lawyer"}
    assert canonical_hashes(store)["authoritative_sha256"] == before
    e.city.finalize(tick + 1)
    assert store.scalar("SELECT status FROM service_cases WHERE id=?", (case,)) == "denied"
    assert store.scalar("SELECT status FROM institution_tasks WHERE id=?", (task["id"],)) == "cancelled"
    assert store.scalar("SELECT COUNT(*) FROM civic_authorizations WHERE case_id=?", (case,)) == 0
    validate(e)


def test_lawyer_death_does_not_revoke_a_consumed_permit_or_the_formed_company(city_world):
    world = city_world
    e, store = world.economy, world.store
    person, case, task, tick = under_review(world)
    lawyer = store.scalar("SELECT lawyer_agent_id FROM service_cases WHERE id=?", (case,))
    assert decide(world, tick + 1, task["assigned_agent_id"], case)["ok"]
    action = e.city.founding_opportunity(person, tick + 2)["action"]
    founded = world.runtime.executor.execute_action(tick + 2, person, action)
    assert founded["ok"], founded
    permit = dict(store.query_one("SELECT * FROM civic_authorizations WHERE case_id=?", (case,)))
    firm = dict(store.query_one("SELECT * FROM firms WHERE id=?", (founded["firm_id"],)))
    e.lifecycle.settle_death(tick + 3, lawyer)
    assert dict(store.query_one("SELECT * FROM civic_authorizations WHERE case_id=?", (case,))) == permit
    assert dict(store.query_one("SELECT * FROM firms WHERE id=?", (founded["firm_id"],))) == firm
    assert item_for(e, lawyer, "civic_counsel_authorization") is None
    assert e.business_control.controls(person, founded["firm_id"])
    validate(e)


@pytest.mark.parametrize("consumed", [False, True])
def test_active_and_consumed_permits_still_protect_their_business_name(city_world, consumed):
    world = city_world
    e, store = world.economy, world.store
    person, case, task, tick = under_review(world)
    assert decide(world, tick + 1, task["assigned_agent_id"], case)["ok"]
    if consumed:
        action = e.city.founding_opportunity(person, tick + 2)["action"]
        assert world.runtime.executor.execute_action(tick + 2, person, action)["ok"]
    other = next(row["id"] for row in _same_region_applicants(store, 2) if row["id"] != person)
    payload = json.loads(store.scalar("SELECT application_payload_json FROM service_cases WHERE id=?", (case,)))
    fresh = e.city.apply_business_permit(tick + 3, other, payload)
    assert fresh["ok"], fresh
    e.city.finalize(tick + 3)
    appointment = store.query_one("SELECT * FROM service_appointments WHERE case_id=?", (fresh["case_id"],))
    day = appointment["scheduled_tick"]
    e.city.run_nightly(day)
    e.daily_time.prepare_day(day)
    assert e.city.attend_appointment(day, other, appointment["id"])["ok"]
    e.city.finalize(day)
    assert tuple(store.query_one("SELECT status,reason_code FROM service_cases WHERE id=?", (fresh["case_id"],))) == ("denied", "duplicate_name")
    assert store.scalar("SELECT status FROM civic_authorizations WHERE case_id=?", (case,)) == ("consumed" if consumed else "active")
    validate(e)


@pytest.mark.parametrize("approved", [False, True])
def test_failed_lawyer_death_restores_pending_case_or_issued_permit(city_world, monkeypatch, approved):
    world = city_world
    e, store = world.economy, world.store
    _, case, task, tick = under_review(world)
    lawyer = store.scalar("SELECT lawyer_agent_id FROM service_cases WHERE id=?", (case,))
    if approved:
        assert decide(world, tick + 1, task["assigned_agent_id"], case)["ok"]
    method = "_revoke_authorization_after_death" if approved else "_abandon_case_after_death"
    original = getattr(e.city, method)

    def fail_after_change(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected lawyer closure failure")

    monkeypatch.setattr(e.city, method, fail_after_change)
    before = canonical_hashes(store)["authoritative_sha256"]
    with pytest.raises(RuntimeError, match="injected lawyer closure"):
        e.lifecycle.settle_death(tick + 2, lawyer)
    assert canonical_hashes(store)["authoritative_sha256"] == before
    assert e.estate_cases._pending is None
    monkeypatch.setattr(e.city, method, original)
    e.lifecycle.settle_death(tick + 2, lawyer)
    validate(e)


def test_legacy_permit_approval_retains_its_original_semantics(civic_world):
    world = civic_world
    world.economy.config["entrepreneurship"]["enabled"] = False
    world.economy.city.discretionary_competitor_floor = 0
    _, case, task, tick = under_review(world)
    lawyer = world.store.scalar("SELECT lawyer_agent_id FROM service_cases WHERE id=?", (case,))
    world.economy.lifecycle.settle_death(tick + 1, lawyer)
    assert world.economy.engine_semantics_version == 12
    assert decide(world, tick + 1, task["assigned_agent_id"], case)["ok"]
    assert world.store.scalar("SELECT COUNT(*) FROM estate_cases") == 0


def test_nightly_negotiation_and_lawyer_deaths_survive_restart_and_exact_replay(tmp_path, monkeypatch, caplog):
    config = civic_config()
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    identities = {}
    draw = Lifecycle._draw

    def forced_deaths(self, tick, person, mechanism):
        if mechanism == "mortality" and ((tick == 1 and person == identities["candidate"])
                                        or (tick == 2 and person == identities["lawyer"])):
            return 0.0
        return draw(self, tick, person, mechanism)

    monkeypatch.setattr(Lifecycle, "_draw", forced_deaths)

    def open_seeded(path, settings, *, replay=False):
        world = _world(path, settings, replay=replay)
        if world.store.tick != 0:
            return world
        e, store = world.economy, world.store
        identities["candidate"] = available_adult(world)
        firm = store.query_one(
            "SELECT f.id,f.operator_agent_id FROM firm_operations f WHERE f.status IN ('private','listed') "
            "AND f.operator_agent_id IS NOT NULL AND f.currency_code=(SELECT ac.currency_code FROM accounts ac "
            "JOIN agents a ON a.checking_account_id=ac.id WHERE a.id=?) ORDER BY f.id LIMIT 1", (identities["candidate"],))
        assert firm is not None
        _, _, application, _, offer = negotiate(e, firm["id"], firm["operator_agent_id"], identities["candidate"], tick=0, counter=True)
        identities.update(application=application, offer=offer, lawyer=_lawyer_id(store))
        applicant = _same_region_applicants(store, 1)[0]["id"]
        store.update("agents", applicant, population_tier="core", pinned_core=1, cadence_json='{"act":1,"career":1}')
        _, identities["case"] = apply(world, tick=0, applicant=applicant, name="Nightly Counsel Case")
        e.city.finalize(0)
        return world

    source_path = tmp_path / "source-commitments.db"
    for day in range(1, 4):
        source = open_seeded(source_path, config)
        try:
            asyncio.run(source.step())
            assert source.store.scalar("SELECT state FROM applications WHERE id=?", (identities["application"],)) == "withdrawn"
            assert source.store.scalar("SELECT status FROM job_offers WHERE id=?", (identities["offer"],)) == "expired"
            if day == 1:
                assert source.store.scalar("SELECT status FROM service_cases WHERE id=?", (identities["case"],)) == "under_review"
            else:
                assert item_for(source.economy, identities["lawyer"], "civic_counsel") is not None
                assert source.store.scalar("SELECT status FROM service_cases WHERE id=?", (identities["case"],)) == "abandoned"
                assert source.store.scalar("SELECT status FROM institution_tasks WHERE source_case_id=?", (identities["case"],)) == "cancelled"
            source.economy.estate_cases.check_invariants()
        finally:
            source.close()
    before = hashlib.sha256(source_path.read_bytes()).hexdigest()
    settings = copy.deepcopy(config)
    settings["replay_source_path"] = str(source_path)
    replay = open_seeded(tmp_path / "replayed-commitments.db", settings, replay=True)
    try:
        for _ in range(3):
            asyncio.run(replay.step())
        proof = verify_replay(source_path, replay.store.path)
        assert proof["exact"], proof["differences"]
        assert not any("action.execution.failed" in record.message for record in caplog.records)
        replay.economy.estate_cases.check_invariants()
    finally:
        replay.close()
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == before

"""Draft resident service/turn boundaries against actual institutions and ledgers.

Only these disposable domain fixtures select Semantics 21. They do not prove
complete new-World scenario, recorded replay or export support.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import random
import shutil
import sqlite3
from types import SimpleNamespace

import pytest

from agents.external import ExternalAgentError, ExternalAgentService
from agents.memory import Memory
from agents.participant import ParticipantError, ParticipantService
from agents.prompts import ContextBuilder
from engine.core import Economy
from engine.migrations.v026_population_residence import SQL
from engine.population import PopulationBoundary
from engine.population_history import ResidenceError, ResidenceHistory
from engine.store import Store

from .conftest import make_agent, make_bank
from .test_population_authority import finance
from .test_population_movements import advance, propose
from .test_population_participation import depart, return_home
from .test_population_residence_history import contents


def enable(e):
    e.engine_semantics_version = 21
    e.population = PopulationBoundary(e)
    for institution in (e.labor, e.lifecycle, e.gov, e.politics, e.cognition, e.information, e.regions):
        institution.engine_semantics_version = 21
        institution.population = e.population


@pytest.fixture
def resident_services(store):
    config = {"engine_semantics_version": 20, "seed": 1,
        "lifecycle": {"birth_annual_prob": 0, "population_mode": "drift"},
        "family_decisions": {"scripted_matching": False},
        "information_economy": {"enabled": True, "base_reach": 1.0},
        "political_model": {"enabled": True, "house_seats": 2, "senate_seats": 1,
                            "actor_bound_authorization": True},
        "participant_mode": {"enabled": True}}
    store.execute("UPDATE run_meta SET config_json=?", (json.dumps(config),))
    e = Economy(store, config, random.Random(1), random.Random(2))
    e.ensure_system_accounts()
    store.insert("regions", id=1, region_key="northstar", name="Home", currency_code="USD",
                 population_target=20, specialization_json="{}", x=0, y=0, legal_ruleset="test")
    bank = make_bank(e)
    store.update("banks", bank, region_id=1)
    person, wallet = make_agent(e, bank, "First citizen", cash=1_000_000, region_id=1, political_lean=-1.0)
    heir, heir_wallet = make_agent(e, bank, "Second citizen", cash=1_000_000, region_id=1, political_lean=1.0)
    e.politics.initialize(0)
    e.households.initialize()
    store.conn.executescript(SQL)
    history = ResidenceHistory(store)
    for row in store.query("SELECT agent_id FROM person_lifecycle ORDER BY agent_id"):
        history.record_origin(row["agent_id"])
    history.record_census(0)
    enable(e)
    return SimpleNamespace(e=e, bank=bank, person=person, wallet=wallet,
                           heir=heir, heir_wallet=heir_wallet, history=history)


def move_person(c, actor, *, tick=0, due=1, key="out"):
    identity = c.e.population.propose(tick, actor, "departure", [actor], key, due_tick=due)["movement_id"]
    advance(c, due)
    assert c.e.population.settle(due, identity)["status"] == "applied"


@pytest.mark.parametrize("kind", ["legislative", "executive"])
def test_federal_ballots_exclude_departure_and_restore_returning_voters(resident_services, kind):
    c, e = resident_services, resident_services.e
    depart(c)
    before = finance(e)
    outcome = e.politics.hold_election(1, kind)
    enterprise = e.store.scalar("SELECT id FROM political_parties WHERE name='Enterprise Alliance'")
    assert (outcome["turnout"], outcome["civic_votes"], outcome["enterprise_votes"]) == (1, 0, 1)
    assert outcome["winner_party_id"] == enterprise
    if kind == "legislative":
        assert {r[0] for r in e.store.query("SELECT party_id FROM legislators WHERE active=1")} == {enterprise}
    else:
        assert e.store.metric_latest("executive_party_id") == enterprise
    return_home(c)
    outcome = e.politics.hold_election(2, kind)
    assert (outcome["turnout"], outcome["civic_votes"], outcome["enterprise_votes"]) == (2, 1, 1)
    assert finance(e) == before
    assert e.ledger.reconcile()[0]


def test_empty_federal_electorate_cannot_change_seats_or_executive_and_nightly_retry_is_idempotent(resident_services):
    c, e = resident_services, resident_services.e
    first = propose(c)
    second = e.population.propose(0, c.heir, "departure", [c.heir], "other", due_tick=1)["movement_id"]
    advance(c, 1)
    for identity in (first, second):
        e.population.settle(1, identity)
    seats = [tuple(r) for r in e.store.query("SELECT * FROM legislators ORDER BY id")]
    e.store.record_metric(0, "executive_party_id", 2)
    e.politics.house_interval = e.politics.executive_interval = 1
    e.politics.run_nightly(1)
    assert [tuple(r) for r in e.store.query("SELECT * FROM legislators ORDER BY id")] == seats
    assert e.store.metric_latest("executive_party_id") == 2
    outcomes = [json.loads(r[0]) for r in e.store.query("SELECT results_json FROM elections ORDER BY id")]
    assert len(outcomes) == 2
    assert all(r["turnout"] == 0 and r["winner_party_id"] is None and r["status"] == "no_resident_voters" for r in outcomes)
    before = contents(e.store)
    e.politics.run_nightly(1)
    assert contents(e.store) == before


@pytest.mark.parametrize("version", [2, 20])
def test_legacy_federal_electorate_is_unchanged(resident_services, version):
    c, e = resident_services, resident_services.e
    depart(c)
    e.politics.engine_semantics_version = version
    outcome = e.politics.hold_election(1)
    assert outcome["turnout"] == 2 and "status" not in outcome


@pytest.mark.parametrize("role", ["legislator_house", "executive", "lobbyist"])
def test_departed_official_cannot_reuse_a_reactivated_role_or_seat(resident_services, role):
    c, e = resident_services, resident_services.e
    actor = e.store.scalar("SELECT id FROM agents WHERE role=? ORDER BY id LIMIT 1", (role,))
    move_person(c, actor)
    # Deliberately corrupt a stale binding; the owning action boundary must deny it.
    e.store.update("agents", actor, role=role)
    if role == "legislator_house":
        e.store.execute("UPDATE legislators SET active=1 WHERE agent_id=?", (actor,))
    before = contents(e.store)
    if role == "legislator_house":
        result = e.politics.sponsor_bill(1, actor, {"title": "No outside sponsor"})
        assert e.politics._legislator_for_agent(actor) is None
    elif role == "executive":
        result = e.politics.executive_action(1, actor, 1, "sign")
        assert result["reason"] == "local executive authority required"
    else:
        result = e.politics.lobby(1, actor, {"sponsor_type": "agent", "sponsor_id": actor, "amount_cents": 1})
        assert result["reason"] == "local lobbyist or lawyer required"
    assert not result["ok"] and contents(e.store) == before


def test_departed_compute_buyer_keeps_paid_cost_but_cannot_renew_or_purchase(resident_services):
    c, e = resident_services, resident_services.e
    bought = e.cognition.buy_compute_plan(0, c.person, "flash")
    assert bought["ok"]
    paid_balance = e.ledger.balance(c.wallet)
    depart(c)
    before = contents(e.store)
    assert not e.cognition.buy_compute_plan(1, c.person, "flash")["ok"]
    assert e.cognition.decision_context(c.person, 1) == {}
    assert contents(e.store) == before
    e.cognition.run_nightly(1)
    assert e.ledger.balance(c.wallet) == paid_balance
    assert not e.store.query("SELECT 1 FROM compute_subscriptions WHERE agent_id=? AND status IN ('active','pending')", (c.person,))
    assert e.store.scalar("SELECT status FROM compute_subscriptions WHERE id=?", (bought["subscription_id"],)) == "cancelled"
    return_home(c)
    assert e.cognition.buy_compute_plan(2, c.person, "flash")["ok"]
    assert e.ledger.balance(c.wallet) == paid_balance-e.cognition._plan_cost("flash")
    assert e.ledger.reconcile()[0]


def test_reactivated_outside_role_cannot_charge_public_compute(resident_services):
    c, e = resident_services, resident_services.e
    e.cognition._renew_institutional_sponsorships(0)
    depart(c)
    e.store.update("agents", c.person, role="executive")
    before = contents(e.store)
    e.cognition._renew_institutional_sponsorships(1)
    assert contents(e.store) == before


def test_premium_capacity_is_based_on_residents_and_buying_works_after_return(resident_services):
    c, e = resident_services, resident_services.e
    e.cognition.p["premium_cap_fraction"] = 0.5
    e.store.insert("agent_skills", agent_id=c.heir, skill_key="finance", xp=100, level=3, source="fixture")
    depart(c)
    before = finance(e)
    result = e.cognition.buy_compute_plan(1, c.heir, "premium")
    assert not result["ok"] and "cap" in result["reason"]
    assert finance(e) == before
    return_home(c)
    assert e.cognition.buy_compute_plan(2, c.heir, "premium")["ok"]
    e.cognition.run_nightly(3)
    assert e.cognition.current_tier(c.heir) == "premium"
    assert e.ledger.reconcile()[0]


def test_compute_nightly_refuses_corrupt_ending_before_any_public_spend(resident_services):
    c, e = resident_services, resident_services.e
    bought = e.cognition.buy_compute_plan(0, c.person, "flash")
    depart(c)
    e.store.update("compute_subscriptions", bought["subscription_id"], status="active")
    before = contents(e.store)
    with pytest.raises(ResidenceError):
        e.cognition.run_nightly(1)
    assert contents(e.store) == before


def information(c):
    claim = c.e.information.create_claim(0, c.heir, {"claim_key": "test-news", "predicate": "supply", "value": 2})
    assert claim["ok"]
    item = c.e.information.publish_item(0, c.heir, {"claim_id": claim["claim_id"], "item_type": "social_post", "body": "Recorded supply"})
    assert item["ok"] and item["virality"] == 1.0
    return claim["claim_id"], item["item_id"]


def test_outside_news_exposure_stops_preserving_prior_beliefs_and_resumes_on_return(resident_services):
    c, e = resident_services, resident_services.e
    claim, item = information(c)
    e.store.insert("beliefs", agent_id=c.person, key="prior_knowledge", value=0.25, updated_tick=0)
    depart(c)
    beliefs = [tuple(r) for r in e.store.query("SELECT * FROM beliefs WHERE agent_id=? ORDER BY key", (c.person,))]
    e.information.run_nightly(1)
    assert [tuple(r) for r in e.store.query("SELECT * FROM beliefs WHERE agent_id=? ORDER BY key", (c.person,))] == beliefs
    assert not e.store.query("SELECT 1 FROM information_exposures WHERE agent_id=?", (c.person,))
    assert e.store.query_one("SELECT 1 FROM information_exposures WHERE agent_id=? AND item_id=?", (c.heir, item))
    return_home(c)
    e.information.run_nightly(2)
    assert e.store.scalar("SELECT COUNT(*) FROM information_exposures WHERE agent_id=? AND item_id=?", (c.person, item)) == 1
    assert e.store.scalar("SELECT value FROM beliefs WHERE agent_id=? AND key='prior_knowledge'", (c.person,)) == 0.25
    assert e.store.query_one("SELECT 1 FROM beliefs WHERE agent_id=? AND key=?", (c.person, f"claim:{claim}"))


@pytest.mark.parametrize("action", ["claim", "publish", "repost", "correction"])
def test_outside_information_authorship_cannot_mutate_existing_news(resident_services, action):
    c, e = resident_services, resident_services.e
    claim, item = information(c)
    depart(c)
    before = contents(e.store)
    result = {
        "claim": lambda: e.information.create_claim(1, c.person, {"claim_key": "outside", "predicate": "supply", "value": 7}),
        "publish": lambda: e.information.publish_item(1, c.person, {"claim_id": claim}),
        "repost": lambda: e.information.repost(1, c.person, item),
        "correction": lambda: e.information.correct_claim(1, c.person, claim, {"value": 7}),
    }[action]()
    assert not result["ok"] and contents(e.store) == before


def test_outside_pinned_person_does_not_use_a_local_core_slot(resident_services):
    c, e = resident_services, resident_services.e
    e.regions.enabled = True
    e.regions.core_target = 1
    e.store.update("agents", c.person, pinned_core=1, population_tier="core")
    depart(c)
    before = finance(e)
    e.regions.rebalance_tiers(1)
    local_core = [r[0] for r in e.store.query("SELECT id FROM agents WHERE population_tier='core' ORDER BY id") if e.population.is_available(r[0])]
    assert len(local_core) == 1 and c.person not in local_core
    assert not e.store.query("SELECT 1 FROM agent_tier_history WHERE agent_id=? AND tick=1", (c.person,))
    assert finance(e) == before
    assert e.regions._qualified_migration_option(1, c.person, 2)[1] == "regional migration requires a local resident"


def controls(c):
    config = {**c.e.config, "engine_semantics_version": 21}
    participant = ParticipantService(c.e.store, ContextBuilder(c.e, Memory(c.e.store, config), config), config)
    external = ExternalAgentService(c.e, participant, config)
    # A controlled service fixture binds the already recorded genesis identity.
    # Ordinary dedicated-actor creation remains covered by gateway World tests.
    identity = "resident-services-connection"
    scopes = ["world.read", "world.act"]
    now = datetime.now(timezone.utc).isoformat()
    c.e.store.insert("external_agent_connections", id=identity, tenant_id="fixture",
        owner_id_hash="0"*64, display_name="Bound citizen", tier="actor", scopes_json=json.dumps(scopes),
        status="active", actor_id=c.person, created_tick=0, created_at=now, updated_at=now,
        lease_expires_at=(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat())
    auth = {"id": identity, "actor_id": c.person, "tenant_id": "fixture", "scopes": scopes,
            "created_tick": 0, "wake_interval_ticks": 1}
    return participant, external, auth


@pytest.mark.parametrize('value', [None, 0, -1, True, 1.5, '1', 2**63])
def test_external_invalid_target_is_rejected_before_opening_a_turn(resident_services, value):
    c = resident_services
    _, service, auth = controls(c)
    before = contents(c.e.store)
    payload = {'idempotency_key': 'invalid-target', 'action': {'type': 'do_nothing'}}
    if value is not None:
        payload['target_tick'] = value
    with pytest.raises(ExternalAgentError, match='positive integer'):
        service.submit_action(auth, payload)
    assert contents(c.e.store) == before


def test_external_cached_turn_and_queued_action_close_without_outside_fallback_or_wait(resident_services):
    c, e = resident_services, resident_services.e
    _, service, auth = controls(c)
    turn = service.turn(auth)
    receipt = service.submit_action(auth, {"idempotency_key": "old-command", "target_tick": turn["target_tick"],
        "observed_projection_hash": turn["projection_hash"], "action": {"type": "do_nothing"}})
    assert receipt["status"] == "queued"
    depart(c)
    closed = service.turn(auth)
    assert closed['turn_id'] == turn['turn_id'] and closed['turn_status'] == 'fallback'
    rejected = service.submit_action(auth, {"idempotency_key": "new-outside",
        "target_tick": closed['target_tick'], "observed_projection_hash": closed['projection_hash'],
        "action": {"type": "do_nothing"}})
    assert rejected['status'] == 'stale'
    observed = service.observe(auth)
    assert observed["actor"]["id"] == c.person and any(r["id"] == c.wallet for r in observed["accounts"])
    # Collection must not wait on the absent actor's future five-minute lease.
    asyncio.run(asyncio.wait_for(service.collect_online_turns(1), timeout=1.0))
    assert service.decisions_for_tick(1) == (set(), [])
    assert not e.store.query("SELECT 1 FROM external_turn_attendance WHERE actor_id=?", (c.person,))
    assert not e.store.query("SELECT 1 FROM events WHERE kind='external_agent_fallback' AND subject_id=?", (c.person,))
    assert e.store.scalar("SELECT status FROM external_action_submissions WHERE idempotency_key='old-command'") == "rejected"
    return_home(c)
    e.store.set_meta(tick=2)
    returned = service.turn(auth)
    assert returned["turn_id"] != turn["turn_id"]
    assert returned["target_tick"] == 3
    assert e.store.scalar("SELECT status FROM external_action_submissions WHERE idempotency_key='old-command'") == "rejected"
    assert e.store.scalar("SELECT COUNT(*) FROM llm_calls") == 0


def test_manual_control_releases_outside_actor_and_never_revives_queued_command(resident_services):
    c, e = resident_services, resident_services.e
    participant, _, _ = controls(c)
    participant.acquire(c.person, 0, running=False)
    participant.queue_action(0, {"type": "do_nothing"}, running=False)
    depart(c)
    assert participant.active_agent_id() is None
    assert {item['type'] for item in participant.action_catalog(c.person)} == {'propose_population_movement'}
    assert participant.decision_for_tick(1) is None
    assert e.store.scalar("SELECT active FROM participant_control") == 0
    assert e.store.scalar("SELECT status FROM participant_actions") == "cancelled"
    controlled = participant.acquire(c.person, 0, running=False)
    assert controlled['control_scope'] == 'return_only'
    assert participant.decision_for_tick(1) is None
    assert e.store.scalar("SELECT status FROM participant_actions") == "cancelled"
    return_home(c)
    assert participant.active_agent_id() is None
    assert e.store.scalar("SELECT status FROM participant_actions") == "cancelled"
    e.store.set_meta(tick=2)
    assert participant.acquire(c.person, 2, running=False)["active"]
    assert e.store.scalar("SELECT COUNT(*) FROM llm_calls") == 0


def test_return_without_an_intervening_control_poll_does_not_restore_the_old_lease(resident_services):
    c, e = resident_services, resident_services.e
    participant, _, _ = controls(c)
    participant.acquire(c.person, 0, running=False)
    participant.queue_action(0, {"type": "do_nothing"}, running=False)
    depart(c)
    return_home(c)
    assert participant.active_agent_id() is None
    # The stale future command must close before a different citizen is acquired.
    assert participant.acquire(c.heir, 0, running=False)["controlled_agent"]["id"] == c.heir
    assert e.store.scalar("SELECT status FROM participant_actions WHERE agent_id=?", (c.person,)) == "cancelled"


def test_future_external_window_remains_closed_after_return_without_an_outside_poll(resident_services):
    c, e = resident_services, resident_services.e
    _, service, auth = controls(c)
    auth["wake_interval_ticks"] = 3
    e.store.execute("UPDATE external_agent_connections SET wake_interval_ticks=3")
    turn = service.turn(auth)
    assert turn["target_tick"] == 3
    service.submit_action(auth, {"idempotency_key": "old-future", "target_tick": 3,
        "observed_projection_hash": turn["projection_hash"], "action": {"type": "do_nothing"}})
    depart(c)
    return_home(c)
    e.store.set_meta(tick=2)
    # Reopening the control service need not have observed the absent interval.
    asyncio.run(asyncio.wait_for(service.collect_online_turns(3), timeout=1.0))
    returned = service.turn(auth)
    assert returned["turn_id"] == turn["turn_id"] and returned["turn_status"] == "fallback"
    assert e.store.scalar("SELECT status FROM external_action_submissions WHERE idempotency_key='old-future'") == "rejected"
    # Preserve the closed window and its original envelope; do not invent consent.
    assert service.decisions_for_tick(3)[1][0]["purpose"] == "external_safe_policy"
    e.store.set_meta(tick=3)
    assert service.turn(auth)["target_tick"] == 6


def test_minor_has_no_manual_control_or_external_local_turn(resident_services):
    c, e = resident_services, resident_services.e
    advance(c, 1)
    child = e.households.birth(1, c.person)
    participant, service, auth = controls(c)
    e.store.set_meta(tick=1)
    e.store.execute("UPDATE external_agent_connections SET actor_id=?", (child,))
    auth["actor_id"] = child
    before = contents(e.store)
    assert participant.action_catalog(child) == []
    with pytest.raises(ParticipantError, match="adult resident"):
        participant.acquire(child, 1, running=False)
    with pytest.raises(ExternalAgentError, match="adult resident"):
        service.turn(auth)
    assert contents(e.store) == before


def test_failed_federal_election_rolls_back_seat_changes_and_receipt(resident_services, monkeypatch):
    c, e = resident_services, resident_services.e
    depart(c)
    before = contents(e.store)
    original = e.store.log_event

    def fail(tick, kind, *args, **kwargs):
        if kind == "federal_election_held":
            raise RuntimeError("injected election receipt failure")
        return original(tick, kind, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(e.store, "log_event", fail)
        with pytest.raises(RuntimeError, match="injected"):
            with e.store.savepoint("nightly_election"):
                e.politics.hold_election(1)
    assert contents(e.store) == before
    with e.store.savepoint("nightly_election"):
        assert e.politics.hold_election(1)["turnout"] == 1
    assert e.store.scalar("SELECT COUNT(*) FROM elections") == 1


@pytest.mark.parametrize("service", ["politics", "information", "cognition", "regions"])
def test_missing_residence_service_fails_before_state_changes(resident_services, service):
    c, e = resident_services, resident_services.e
    information(c)
    e.regions.enabled = True
    getattr(e, service).population = None
    before = contents(e.store)
    operation = {"politics": lambda: e.politics.hold_election(1),
                 "information": lambda: e.information.run_nightly(1),
                 "cognition": lambda: e.cognition.buy_compute_plan(1, c.person, "flash"),
                 "regions": lambda: e.regions.rebalance_tiers(1)}[service]
    with pytest.raises(ResidenceError, match="population history"):
        operation()
    assert contents(e.store) == before


def closed_copy(store, path):
    with sqlite3.connect(path) as destination:
        store.conn.backup(destination)
    destination.close()


def replay_controls(c, baseline, source):
    store = Store(str(baseline), create=False)
    economy = Economy(store, c.e.config, random.Random(1), random.Random(2))
    enable(economy)
    config = {**c.e.config, "engine_semantics_version": 21,
              "replay_source_path": str(source), "replay_source_closed": True}
    participant = ParticipantService(store, ContextBuilder(economy, Memory(store, config), config), config)
    external = ExternalAgentService(economy, participant, config)
    context = SimpleNamespace(**{**vars(c), "e": economy, "history": economy.population.history})
    return context, participant, external


@pytest.mark.parametrize("resident", [True, False])
@pytest.mark.parametrize("submitted", [True, False])
def test_external_replay_checks_all_actors_before_importing_a_decision_batch(
        resident_services, tmp_path, resident, submitted):
    c, e = resident_services, resident_services.e
    _, service, first = controls(c)
    connection = dict(e.store.query_one("SELECT * FROM external_agent_connections WHERE id=?", (first["id"],)))
    second = {**first, "id": "second-resident-connection", "actor_id": c.heir}
    connection.update(id=second["id"], actor_id=c.heir)
    e.store.insert("external_agent_connections", **connection)
    baseline, source = tmp_path/"replay.db", tmp_path/"closed-source.db"
    e.store.commit()
    closed_copy(e.store, baseline)
    for auth in (first, second):
        turn = service.turn(auth)
        if submitted:
            service.submit_action(auth, {"idempotency_key": "recorded-command",
                "target_tick": turn["target_tick"], "observed_projection_hash": turn["projection_hash"],
                "action": {"type": "do_nothing"}})
    _, decisions = service.decisions_for_tick(1)
    assert {row["agent_id"] for row in decisions} == {c.person, c.heir}
    for row in decisions:
        service.complete(row["external_submission_id"], [{"ok": True}], 1,
                         event_ids=[], resulting_state_hash="0"*64)
    e.store.commit()
    closed_copy(e.store, source)
    original = (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns)
    target, _, replay = replay_controls(c, baseline, source)
    try:
        if not resident:
            # The later actor is invalid: no earlier valid input, turn, memory
            # access or attendance may be imported before the batch is rejected.
            move_person(target, target.heir)
        before = contents(target.e.store)
        if resident:
            imported = replay._replay_decisions(1)
            assert {row["agent_id"] for row in imported} == {c.person, c.heir}
            assert all(row["purpose"] == ("external_agent" if submitted else "external_safe_policy")
                       for row in imported)
            assert [dict(row) for row in target.e.store.query("SELECT * FROM external_turn_attendance ORDER BY id")] == [
                dict(row) for row in e.store.query("SELECT * FROM external_turn_attendance ORDER BY id")]
        else:
            with pytest.raises(ExternalAgentError, match="no local adult actor"):
                replay._replay_decisions(1)
            assert contents(target.e.store) == before
        assert target.e.ledger.reconcile()[0]
        assert target.e.store.scalar("SELECT COUNT(*) FROM llm_calls") == 0
    finally:
        target.e.store.close()
    assert (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns) == original
    assert not any(Path(str(source)+suffix).exists() for suffix in ("-wal", "-shm", "-journal"))


@pytest.mark.parametrize("resident", [True, False])
def test_participant_replay_checks_residence_before_copying_a_recorded_action(
        resident_services, tmp_path, resident):
    c, e = resident_services, resident_services.e
    participant, _, _ = controls(c)
    baseline, source = tmp_path/"replay.db", tmp_path/"closed-source.db"
    e.store.commit()
    closed_copy(e.store, baseline)
    participant.acquire(c.person, 0, running=False)
    participant.queue_action(0, {"type": "do_nothing"}, running=False)
    identity = e.store.scalar("SELECT id FROM participant_actions WHERE agent_id=? AND target_tick=1", (c.person,))
    participant.complete(identity, [{"ok": True}], 1)
    e.store.commit()
    closed_copy(e.store, source)
    original = (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns)
    target, replay, _ = replay_controls(c, baseline, source)
    try:
        if not resident:
            depart(target)
        before = contents(target.e.store)
        if resident:
            imported = replay._replay_action(1)
            assert imported["agent_id"] == c.person and imported["status"] == "queued"
            assert imported["source_action_id"] == identity
        else:
            with pytest.raises(ParticipantError, match="no local adult actor"):
                replay._replay_action(1)
            assert contents(target.e.store) == before
        assert target.e.ledger.reconcile()[0]
        assert target.e.store.scalar("SELECT COUNT(*) FROM llm_calls") == 0
    finally:
        target.e.store.close()
    assert (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns) == original
    assert not any(Path(str(source)+suffix).exists() for suffix in ("-wal", "-shm", "-journal"))


def test_services_and_control_cancellation_match_after_store_reopens(resident_services, tmp_path):
    c, e = resident_services, resident_services.e
    information(c)
    assert e.cognition.buy_compute_plan(0, c.person, "flash")["ok"]
    participant, _, _ = controls(c)
    participant.acquire(c.person, 0, running=False)
    participant.queue_action(0, {"type": "do_nothing"}, running=False)
    propose(c)
    source = Path(e.store.conn.execute("PRAGMA database_list").fetchone()[2])
    e.store.close()
    stamp = hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns
    results = []
    for restart in (False, True):
        target = tmp_path/("restarted.db" if restart else "continuous.db")
        shutil.copy2(source, target)
        store = None
        try:
            for tick in range(1, 7):
                if store is None:
                    store = Store(target)
                    config = json.loads(store.scalar("SELECT config_json FROM run_meta"))
                    current = Economy(store, config, random.Random(1), random.Random(2))
                    enable(current)
                    current.politics.house_interval = 2
                    current.politics.executive_interval = 3
                    control_config = {**config, "engine_semantics_version": 21}
                    controller = ParticipantService(store, ContextBuilder(current, Memory(store, control_config), control_config), control_config)
                with store.savepoint("resident_service_day"):
                    for person in store.query("SELECT * FROM agents WHERE alive=1 ORDER BY id"):
                        current.households.advance_age(tick, person)
                    current.population.run_nightly(tick)
                    if tick == 1:
                        current.population.propose(1, c.person, "return", [c.person], "back", due_tick=4, destination_region_id=1)
                    current.politics.run_nightly(tick)
                    current.information.run_nightly(tick)
                    current.cognition.run_nightly(tick)
                    assert controller.decision_for_tick(tick) is None
                    current.households.record_census(tick)
                    store.set_meta(tick=tick)
                if restart and tick in (2, 4):
                    store.close()
                    store = None
            current.households.check_invariants(6)
            current.population.commitments.check_invariants()
            assert current.ledger.reconcile()[0]
            assert store.scalar("SELECT status FROM participant_actions") == "cancelled"
            assert store.scalar("SELECT active FROM participant_control") == 0
            assert store.scalar("SELECT COUNT(*) FROM llm_calls") == 0
            contract = json.loads((Path(__file__).resolve().parents[1]/"research/hash-contract-v2.json").read_text())
            state = contents(store)
            # Retain every table and economic field, applying only existing
            # column exclusions for operational clocks in this comparison.
            for table, excluded in contract["excluded_columns"].items():
                if table not in state:
                    continue
                columns = [r[1] for r in store.conn.execute(f'PRAGMA table_info("{table}")') if r[1] not in excluded]
                state[table] = [tuple(row[name] for name in columns) for row in store.query(f'SELECT * FROM "{table}" ORDER BY rowid')]
            results.append(state)
        finally:
            if store is not None:
                store.close()
    assert results[0] == results[1]
    assert (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns) == stamp

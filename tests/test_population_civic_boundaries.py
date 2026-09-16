"""Draft civic participation, direct batch rollback and declared arrival replay.

Only disposable fixtures admit Semantics 21. The arrival scenario is prescribed
evidence, not a native demographic outcome or full profile admission.
"""
import asyncio
from contextlib import closing
import hashlib
import json
from pathlib import Path

import pytest

from agents.memory import Memory
from agents.prompts import ContextBuilder
from engine.keyed_random import daily_seed, person_key, stable_key
from engine.population_history import ResidenceError
from engine.store import open_read_only_connection
from research.export_bundle import export_bundle, validate_bundle
from world.replay_verify import verify_replay_connections

from .test_population_participation import depart, return_home
from .test_population_residence_history import contents
from .test_population_resident_services import resident_services, move_person
from .test_population_scenario import scenario_world, proposal


def assert_unchanged(store, before):
    after = contents(store)
    assert [name for name in sorted(before.keys() | after.keys())
            if before.get(name) != after.get(name)] == []


@pytest.mark.parametrize('kind', ['legislative', 'executive'])
def test_late_direct_election_failure_rolls_back_then_retry_counts_residents(resident_services, monkeypatch, kind):
    c, e = resident_services, resident_services.e
    depart(c)
    original = e.store.log_event
    attempted = []

    def fail_after_receipt(tick, event_type, payload, **kwargs):
        receipt = original(tick, event_type, payload, **kwargs)
        if event_type == 'federal_election_held':
            attempted.append(payload)
            assert e.store.scalar('SELECT COUNT(*) FROM elections') == 1
            raise RuntimeError('injected election receipt failure')
        return receipt

    monkeypatch.setattr(e.store, 'log_event', fail_after_receipt)
    before = contents(e.store)
    with pytest.raises(RuntimeError, match='election receipt failure'):
        e.politics.hold_election(1, kind)
    assert len(attempted) == 1 and attempted[0]['turnout'] == 1
    assert_unchanged(e.store, before)
    monkeypatch.setattr(e.store, 'log_event', original)
    result = e.politics.hold_election(1, kind)
    assert (result['turnout'], result['civic_votes'], result['enterprise_votes']) == (1, 0, 1)
    assert e.store.scalar('SELECT COUNT(*) FROM elections') == 1
    assert e.store.scalar("SELECT COUNT(*) FROM events WHERE kind='federal_election_held'") == 1
    assert e.ledger.reconcile()[0]


def test_nightly_executive_failure_rolls_back_disclosure_and_legislative_result(resident_services, monkeypatch):
    c, e = resident_services, resident_services.e
    e.politics.disclosure_delay = 1
    e.politics.house_interval = e.politics.executive_interval = 1
    lobbyist = e.store.scalar("SELECT id FROM agents WHERE role='lobbyist' ORDER BY id LIMIT 1")
    activity = e.politics.lobby(0, lobbyist, {
        'sponsor_type': 'agent', 'sponsor_id': lobbyist, 'amount_cents': 1000})
    assert activity['ok'], activity
    depart(c)
    original = e.store.log_event
    attempted = []

    def fail_after_executive(tick, event_type, payload, **kwargs):
        receipt = original(tick, event_type, payload, **kwargs)
        if event_type == 'federal_election_held' and payload['election_type'] == 'executive':
            assert e.store.scalar('SELECT disclosed FROM lobbying_activities WHERE id=?',
                                  (activity['activity_id'],)) == 1
            assert e.store.scalar('SELECT COUNT(*) FROM elections') == 2
            attempted.append(receipt)
            raise RuntimeError('injected nightly executive failure')
        return receipt

    monkeypatch.setattr(e.store, 'log_event', fail_after_executive)
    before = contents(e.store)
    with pytest.raises(RuntimeError, match='nightly executive failure'):
        e.politics.run_nightly(1)
    assert len(attempted) == 1
    assert_unchanged(e.store, before)
    monkeypatch.setattr(e.store, 'log_event', original)
    e.politics.run_nightly(1)
    assert e.store.scalar('SELECT COUNT(*) FROM elections WHERE turnout=1') == 2
    assert e.store.scalar("SELECT COUNT(*) FROM events WHERE kind='lobbying_disclosed'") == 1
    assert e.store.scalar("SELECT COUNT(*) FROM transactions WHERE kind='lobbying_spend'") == 1
    settled = contents(e.store)
    e.politics.run_nightly(1)
    assert_unchanged(e.store, settled)
    assert e.ledger.reconcile()[0]


def test_tier_batch_late_failure_rolls_back_earlier_promotions(resident_services, monkeypatch):
    c, e = resident_services, resident_services.e
    e.regions.enabled, e.regions.core_target = True, 2
    e.store.execute("UPDATE agents SET population_tier='periphery'")
    depart(c)
    original = e.store.log_event
    attempted = []

    def fail_after_second(tick, event_type, payload, **kwargs):
        receipt = original(tick, event_type, payload, **kwargs)
        if event_type == 'agent_tier_changed':
            attempted.append(payload['agent_id'])
            if len(attempted) == 2:
                raise RuntimeError('injected second promotion failure')
        return receipt

    monkeypatch.setattr(e.store, 'log_event', fail_after_second)
    before = contents(e.store)
    with pytest.raises(RuntimeError, match='second promotion failure'):
        e.regions.rebalance_tiers(1)
    assert len(attempted) == 2 and c.person not in attempted
    assert_unchanged(e.store, before)
    monkeypatch.setattr(e.store, 'log_event', original)
    e.regions.rebalance_tiers(1)
    assert [row[0] for row in e.store.query('SELECT agent_id FROM agent_tier_history ORDER BY id')] == attempted
    settled = contents(e.store)
    e.regions.rebalance_tiers(1)
    assert_unchanged(e.store, settled)
    assert e.ledger.reconcile()[0]


def regional_guidance(c, tick):
    return c.e.regions.decision_context(c.person, tick=tick, career_day=True)


def prepare_regional_guidance(c):
    c.e.regions.enabled = True
    c.e.store.insert('currencies', code='EUR', name='Euro fixture',
                     numeraire_rate_ppm=1_100_000, issuer_region_id=1)
    assert regional_guidance(c, 0)['fx_quotes'][0]['buy_action']['type'] == 'place_fx_order'


def test_outside_regional_guidance_is_empty_and_return_reuses_wallet(resident_services):
    c, e = resident_services, resident_services.e
    prepare_regional_guidance(c)
    depart(c)
    before = contents(e.store)
    # Even a historical day cannot authorize current local work from outside.
    assert regional_guidance(c, 0) == {}
    assert regional_guidance(c, 1) == {}
    assert_unchanged(e.store, before)
    assert e.store.scalar('SELECT checking_account_id FROM agents WHERE id=?', (c.person,)) == c.wallet
    return_home(c)
    assert regional_guidance(c, 1) == {}
    returned = regional_guidance(c, 2)
    assert returned['fx_quotes'][0]['buy_action']['type'] == 'place_fx_order'
    assert next(w['account_id'] for w in returned['regional_wallets'] if w['primary']) == c.wallet
    assert e.ledger.reconcile()[0]


def executive_guidance(c):
    e = c.e
    sponsor = e.store.scalar("SELECT agent_id FROM legislators WHERE chamber='house' ORDER BY id LIMIT 1")
    bill = e.politics.sponsor_bill(0, sponsor, {'title': 'Declared executive queue',
        'policy_changes': {'tax_rate_bps': 100}})
    assert bill['ok'], bill
    # The queue status is a declared starting condition, not proof of a quorum.
    e.store.update('bills', bill['bill_id'], status='executive')
    actor = e.store.query_one("SELECT * FROM agents WHERE role='executive' ORDER BY id LIMIT 1")
    builder = ContextBuilder(e, Memory(e.store, {}), {'engine_semantics_version': 21})
    assert builder._institutional_work(actor, 0)['eligible_actions'][0]['type'] == 'executive_bill_action'
    return builder, actor


def test_departed_executive_cannot_get_actions_from_stale_role_snapshot(resident_services):
    c, e = resident_services, resident_services.e
    builder, actor = executive_guidance(c)
    move_person(c, actor['id'])
    assert e.store.scalar('SELECT role FROM agents WHERE id=?', (actor['id'],)) is None
    before = contents(e.store)
    for tick in (0, 1):
        work = builder._institutional_work(actor, tick)
        assert work['eligible_actions'] == []
        assert 'wallet' not in work
    assert_unchanged(e.store, before)


@pytest.mark.parametrize('surface', ['regional', 'institutional'])
def test_invalid_residence_fails_read_only_guidance_before_actions(resident_services, surface):
    c, e = resident_services, resident_services.e
    if surface == 'regional':
        prepare_regional_guidance(c)
        actor = c.person
        read = lambda: regional_guidance(c, 0)
    else:
        builder, row = executive_guidance(c)
        actor = row['id']
        read = lambda: builder._institutional_work(row, 0)
    event = e.store.scalar('SELECT event_id FROM person_residence_events WHERE agent_id=? ORDER BY id LIMIT 1', (actor,))
    payload = e.store.scalar('SELECT payload_json FROM events WHERE id=?', (event,))
    e.store.update('events', event, payload_json='{}')
    before = contents(e.store)
    with pytest.raises(ResidenceError):
        read()
    assert_unchanged(e.store, before)
    e.store.update('events', event, payload_json=payload)
    assert read()


def test_declared_arrival_contacts_use_residents_through_restart_replay_and_export(scenario_world, tmp_path):
    actor, due = 23, 3
    entries = [proposal('contact-out', actor=f'agent:{actor}')]

    def create(name, source=None):
        fresh = not (tmp_path/f'{name}.db').exists()
        world = scenario_world(entries, name, replay_source=source)
        if fresh:
            # Choose and record a fixed arrival identity that would rank the
            # departed person among the old all-living contact candidates.
            people = [row[0] for row in world.store.query('SELECT id FROM agents WHERE alive=1 ORDER BY id')]
            keys = {person: person_key(world.store, person) for person in people}
            for ordinal in range(256):
                source_key = f'civic-arrival-contact-{ordinal}'
                arrival_key = stable_key('arrival', source_key, 0)
                ranked = sorted(people, key=lambda person: (
                    daily_seed(world.config['seed'], 'arrival.contact', due, arrival_key, keys[person]), keys[person]))
                if actor in ranked[:3]:
                    break
            else:
                raise AssertionError('declared contact fixture was not found')
            movement = world.store.query_one('SELECT * FROM population_movements ORDER BY id LIMIT 1')
            for adult in json.loads(movement['snapshot_json'])['adult_ids']:
                if adult != actor:
                    result = world.economy.population.respond(0, adult, movement['id'], 'accept', phase='GENESIS')
                    assert result['status'] == 'pending'
            world.economy.lifecycle.schedule_arrival(0, due, source_key=source_key)
            world.store.log_event(0, 'declared_civic_arrival_contacts', {
                'departing_agent_id': actor, 'arrival_key': arrival_key,
                'arrival_day': due, 'all_living_first_contacts': ranked[:3]}, phase='GENESIS')
            world.store.commit()
        return world

    def run(name, source=None):
        world = create(name, source)
        for _ in range(2):
            asyncio.run(world.step())
        assert not world.economy.population.is_available(actor)
        old_ties = [tuple(row) for row in world.store.query(
            'SELECT agent_a,agent_b FROM social_ties WHERE agent_a=? OR agent_b=? ORDER BY id', (actor, actor))]
        asyncio.run(world.step(pause_after_phase='NIGHT_CLOSE'))
        arrival = world.store.scalar("SELECT subject_id FROM events WHERE kind='arrival' AND tick=?", (due,))
        assert arrival is not None and arrival != actor
        contacts = [row[0] for row in world.store.query(
            'SELECT CASE WHEN agent_a=? THEN agent_b ELSE agent_a END FROM social_ties '
            'WHERE agent_a=? OR agent_b=? ORDER BY id', (arrival, arrival, arrival))]
        assert len(contacts) == 3 and actor not in contacts
        assert all(world.economy.population.is_local(person, due) for person in contacts)
        assert [tuple(row) for row in world.store.query(
            'SELECT agent_a,agent_b FROM social_ties WHERE agent_a=? OR agent_b=? ORDER BY id', (actor, actor))] == old_ties
        assert world.store.scalar('SELECT COUNT(*) FROM person_lifecycle WHERE agent_id=?', (arrival,)) == 1
        assert world.store.scalar('SELECT COUNT(*) FROM person_residence_events WHERE agent_id=?', (arrival,)) == 1
        wallets = tuple(world.store.query_one('SELECT checking_account_id,savings_account_id FROM agents WHERE id=?', (arrival,)))
        scenario_world.close(world)
        world = create(name, source)
        asyncio.run(world.step())
        assert tuple(world.store.query_one('SELECT checking_account_id,savings_account_id FROM agents WHERE id=?', (arrival,))) == wallets
        assert world.store.scalar("SELECT COUNT(*) FROM events WHERE kind='arrival'") == 1
        assert world.store.scalar('SELECT arrivals FROM population_resident_census WHERE tick=?', (due,)) == 1
        assert world.economy.ledger.reconcile()[0]
        path = Path(world.store.path)
        scenario_world.close(world)
        return path

    source = run('arrival-source')
    stamp = hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns
    target = run('arrival-replay', source)
    with closing(open_read_only_connection(source, require_closed=True)) as src, \
            closing(open_read_only_connection(target, require_closed=True)) as dst:
        proof = verify_replay_connections(src, dst)
        assert proof['exact'], proof['differences']
        for database, directory in ((src, 'source-export'), (dst, 'replay-export')):
            manifest = validate_bundle(export_bundle(database, tmp_path/directory), database=database)
            assert manifest['contract_id'] == 'hash-contract-v8'
            assert database.execute("SELECT COUNT(*) FROM llm_calls WHERE provider<>'scripted'").fetchone()[0] == 0
    assert (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns) == stamp
    assert not any(Path(str(source)+suffix).exists() for suffix in ('-wal', '-shm', '-journal'))

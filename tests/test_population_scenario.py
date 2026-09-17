"""Declared movement inputs through real World phases, restart and replay.

Only disposable databases admit the unregistered semantics/migration draft.
"""
import asyncio
from contextlib import closing
import copy
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

import engine.semantics as semantics
from engine.migrations.v026_population_residence import SQL
from engine.keyed_random import person_key, stable_key
from engine.population_history import ResidenceError
from engine.population_scenario import parse_schedule
from engine.store import Store, open_read_only_connection
from world.loop import World
from world.replay_verify import verify_replay_connections
from run_config import deep_merge

from .test_population_residence_history import contents
from .test_semantics20_civic_succession import civic_config


def proposal(key='out', *, tick=0, due=2, actor='agent:23', cause='departure'):
    entry = dict(key=key, tick=tick, action='propose', actor=actor,
                 cause=cause, members=[actor], due_tick=due)
    if cause == 'return':
        entry['destination_region_id'] = 1
    return entry


def response(*, tick=1, decision='accept'):
    return dict(key='consent', tick=tick, action='respond', actor='agent:24',
                proposal='out', decision=decision)


def scenario_config(entries):
    config = civic_config()
    config['engine_semantics_version'] = 21
    config.setdefault('population', {})['movement_schedule'] = copy.deepcopy(entries)
    return config


@pytest.fixture
def scenario_world(monkeypatch, tmp_path):
    monkeypatch.setattr(semantics, 'CURRENT_ENGINE_SEMANTICS_VERSION', 21)
    worlds = []

    def create(entries, name='world', *, replay_source=None, scheduled_births=(), config_overrides=None):
        config = scenario_config(entries)
        config['households']['scheduled_births'] = list(scheduled_births)
        config = deep_merge(config, config_overrides or {})
        if replay_source:
            config.update(replay_source_path=str(replay_source), replay_source_closed=True)
        path = tmp_path / f'{name}.db'
        fresh = not path.exists()
        store = Store(str(path), create=fresh)
        try:
            if fresh:
                store.conn.executescript(SQL)
                store.init_run_meta(name, config['seed'], config)
            world = World(store, config, replay=replay_source is not None)
            world.initialize()
            world.restore_prng_state()
        except BaseException:
            store.close()
            raise
        worlds.append(world)
        return world

    def close(world):
        worlds.remove(world)
        world.close()

    create.close = close
    yield create
    for world in worlds:
        world.close()


@pytest.mark.parametrize('patch', [
    {'key': ''}, {'key': 'x' * 65}, {'tick': True}, {'tick': -1}, {'tick': 1.5},
    {'due_tick': 0}, {'due_tick': True}, {'due_tick': 2**63}, {'actor': 23},
    {'members': []}, {'members': ['agent:23', 'agent:23']}, {'members': ['agent:24']},
    {'cause': 'arrival'}, {'action': 'move'}, {'destination_region_id': 1},
    {'care_plan': [{'child': 'agent:25'}]}, {'extra': 1},
])
def test_invalid_schedule_is_rejected_before_any_world_effect(patch, store):
    entry = {**proposal(), **patch}
    before = contents(store)
    with pytest.raises(ResidenceError):
        parse_schedule(scenario_config([entry]), 21)
    assert contents(store) == before


def test_schedule_validates_all_dependencies_and_canonicalizes_order():
    entry = proposal(tick=1)
    consent = response(tick=1)
    assert parse_schedule(scenario_config([consent, entry]), 21) == parse_schedule(scenario_config([entry, consent]), 21)
    for entries in ([entry, entry], [consent], [entry, {**consent, 'tick': 3}],
                    [entry, {**consent, 'proposal': 'consent'}]):
        with pytest.raises(ResidenceError):
            parse_schedule(scenario_config(entries), 21)


def test_schedule_refuses_legacy_semantics_and_automatic_replacement(store):
    config = scenario_config([proposal()])
    config['engine_semantics_version'] = 20
    before = contents(store)
    with pytest.raises(ResidenceError, match='Semantics 21'):
        World(store, config)
    assert contents(store) == before
    config['lifecycle']['population_mode'] = 'stable'
    with pytest.raises(ResidenceError, match='without automatic replacement'):
        parse_schedule(config, 21)


def input_receipts(world):
    return [dict(row) for row in world.store.query('SELECT * FROM population_scenario_receipts ORDER BY event_id')]


def test_declared_world_schedule_restarts_inside_days_and_replays_exactly(scenario_world):
    create = scenario_world
    entries = [proposal(), proposal('back', tick=3, due=5, cause='return')]
    world = create(entries, 'source')
    original = dict(world.store.query_one('SELECT * FROM agents WHERE id=23'))
    assert original['age'] >= 18 and original['employer_id'] is not None
    for day in range(1, 7):
        if day in (2, 4):
            paused = asyncio.run(world.step(pause_after_phase='NIGHT_CLOSE'))
            assert paused['active_tick'] == day
            create.close(world)
            world = create(entries, 'source')
        asyncio.run(world.step())
        assert world.store.tick == day
        local = day < 2 or day >= 5
        assert world.economy.population.is_local(23, day) is local
        assert bool(world.store.scalar('SELECT COUNT(*) FROM effective_presence WHERE tick=? AND agent_id=23', (day,))) is local
        if not local:
            assert world.store.scalar('SELECT COUNT(*) FROM time_days WHERE tick=? AND agent_id=23', (day,)) == 0
            assert world.store.scalar('SELECT COUNT(*) FROM llm_calls WHERE tick=? AND agent_id=23', (day,)) == 0
        world.population_scenario.check_progress()
        world.economy.households.check_invariants(day)
        assert world.economy.ledger.reconcile()[0]
    assert [row['outcome'] for row in input_receipts(world)] == ['accepted', 'accepted']
    assert world.store.scalar('SELECT COUNT(*) FROM person_residence_events WHERE agent_id=23') == 3
    assert world.store.scalar('SELECT checking_account_id FROM agents WHERE id=23') == original['checking_account_id']
    assert world.store.scalar('SELECT savings_account_id FROM agents WHERE id=23') == original['savings_account_id']
    assert world.store.scalar('SELECT returns FROM population_resident_census WHERE tick=5') == 1
    assert world.store.scalar('SELECT arrivals FROM population_resident_census WHERE tick=5') == 0
    source = Path(world.store.path)
    create.close(world)
    stamp = hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns
    replay = create(entries, 'replay', replay_source=source)
    for _ in range(6):
        asyncio.run(replay.step())
    replay_path = Path(replay.store.path)
    create.close(replay)
    with closing(open_read_only_connection(source, require_closed=True)) as src, \
         closing(open_read_only_connection(replay_path, require_closed=True)) as dst:
        result = verify_replay_connections(src, dst)
        assert result['exact'], result['differences']
        for table in ('population_scenario_manifest', 'population_scenario_receipts',
                      'population_movements', 'population_movement_assents', 'population_resident_census',
                      'population_commitment_endings', 'person_residence_events'):
            assert [tuple(row) for row in src.execute(f'SELECT * FROM {table} ORDER BY rowid')] == [
                tuple(row) for row in dst.execute(f'SELECT * FROM {table} ORDER BY rowid')]
    assert stamp == (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns)
    assert not any(Path(str(source) + suffix).exists() for suffix in ('-wal', '-shm', '-journal'))


@pytest.mark.parametrize('decision', [None, 'accept', 'decline'])
def test_partial_household_needs_the_remaining_adults_declared_assent(scenario_world, decision):
    entries = [proposal(tick=1)]
    if decision:
        entries.insert(0, response(decision=decision))
    world = scenario_world(entries)
    # Explicit fixture household setup precedes the scheduled proposal. This
    # tests assent semantics; it is not evidence of endogenous family formation.
    home = world.economy.households.membership(23)['household_id']
    world.economy.families._move_members(0, [{'agent_id': 24}], home, 'fixture_join')
    for _ in range(2):
        asyncio.run(world.step())
    movement = world.store.query_one('SELECT * FROM population_movements')
    assert movement['status'] == ('applied' if decision == 'accept' else 'cancelled')
    assert world.economy.population.is_local(23, 2) is (decision != 'accept')
    assert world.economy.population.is_local(24, 2)
    assert world.economy.ledger.reconcile()[0]


def test_unresolved_origins_and_their_responses_have_permanent_rejections(scenario_world):
    entry = proposal(tick=1, actor='arrival:not-created')
    world = scenario_world([entry, response()])
    asyncio.run(world.step())
    receipts = input_receipts(world)
    assert [row['outcome'] for row in receipts] == ['rejected', 'rejected']
    assert receipts[0]['reason'] == 'unknown_person_origin:arrival:not-created'
    assert receipts[1]['reason'] == 'proposal_was_rejected'
    assert world.store.scalar('SELECT COUNT(*) FROM population_movements') == 0
    before = contents(world.store)
    world.population_scenario.apply(1)
    assert contents(world.store) == before


def test_failed_input_receipt_rolls_back_the_real_nightly_phase_and_retries(scenario_world, monkeypatch):
    world = scenario_world([proposal(tick=1)])
    before = contents(world.store)
    record = world.store.log_event

    def fail(tick, kind, payload=None, **kwargs):
        if kind == 'population_scenario_input':
            raise RuntimeError('injected population input receipt failure')
        return record(tick, kind, payload, **kwargs)

    with monkeypatch.context() as injected:
        injected.setattr(world.store, 'log_event', fail)
        with pytest.raises(RuntimeError, match='injected'):
            asyncio.run(world.step())
    after = contents(world.store)
    assert {key: value for key, value in before.items() if key != 'run_meta'} == {
        key: value for key, value in after.items() if key != 'run_meta'}
    asyncio.run(world.step())
    assert len(input_receipts(world)) == 1
    assert world.store.scalar('SELECT COUNT(*) FROM population_movements') == 1
    assert world.economy.ledger.reconcile()[0]


def test_changed_runtime_or_persisted_schedule_fails_before_the_next_world_effect(scenario_world):
    world = scenario_world([proposal(tick=1)])
    config = copy.deepcopy(world.config)
    world.config['population']['movement_schedule'][0]['due_tick'] = 3
    before = contents(world.store)
    with pytest.raises(ResidenceError, match='changed after construction'):
        asyncio.run(world.step())
    assert contents(world.store) == before
    world.config.clear()
    world.config.update(config)
    changed = copy.deepcopy(config)
    changed['population']['movement_schedule'][0]['due_tick'] = 4
    world.store.set_meta(config_json=json.dumps(changed))
    before = contents(world.store)
    with pytest.raises(ResidenceError, match='recorded run configuration'):
        asyncio.run(world.step())
    assert contents(world.store) == before


@pytest.mark.parametrize('table', ['population_scenario_manifest', 'population_scenario_receipts'])
def test_scenario_evidence_cannot_be_rewritten_or_deleted(scenario_world, table):
    world = scenario_world([proposal()])
    before = contents(world.store)
    for statement in (f'DELETE FROM {table}', f'UPDATE {table} SET event_id=event_id'):
        with pytest.raises(sqlite3.IntegrityError):
            world.store.execute(statement)
    assert contents(world.store) == before


def test_missing_receipt_after_a_committed_phase_is_an_error_not_a_late_input(scenario_world):
    world = scenario_world([proposal(tick=1)])
    asyncio.run(world.step(pause_after_phase='NIGHT_CLOSE'))
    world.store.execute('DROP TRIGGER population_scenario_receipts_no_delete')
    world.store.execute('DELETE FROM population_scenario_receipts')
    before = contents(world.store)
    with pytest.raises(ResidenceError, match='committed World phase'):
        asyncio.run(world.step())
    assert contents(world.store) == before


def test_corrupt_input_event_is_rejected_without_repair(scenario_world):
    world = scenario_world([proposal()])
    event = input_receipts(world)[0]['event_id']
    world.store.execute("UPDATE events SET payload_json=json_set(payload_json,'$.result.status','applied') WHERE id=?", (event,))
    before = contents(world.store)
    with pytest.raises(ResidenceError, match='event disagrees'):
        asyncio.run(world.step())
    assert contents(world.store) == before


def test_future_arrival_origin_binds_only_after_birth_or_arrival_registration(scenario_world):
    origin = stable_key('arrival', 'scenario-arrival-fixture', 0)
    entries = [proposal('too-early', due=1, actor=origin),
               proposal('arrival-leaves', tick=2, due=3, actor=origin),
               proposal('arrival-returns', tick=4, due=5, actor=origin, cause='return')]
    world = scenario_world(entries)
    assert input_receipts(world)[0]['outcome'] == 'rejected'
    # A separately declared test arrival exercises the existing first-arrival
    # service. The movement schedule itself does not create or fund this person.
    world.economy.lifecycle.schedule_arrival(0, 1, source_key='scenario-arrival-fixture')
    for _ in range(5):
        asyncio.run(world.step())
    receipts = input_receipts(world)
    assert [row['outcome'] for row in receipts] == ['rejected', 'accepted', 'accepted']
    actor = json.loads(receipts[1]['resolved_json'])[origin]
    assert actor != 23 and person_key(world.store, actor) == origin
    assert world.store.scalar('SELECT COUNT(*) FROM person_residence_events WHERE agent_id=?', (actor,)) == 3
    assert world.store.scalar('SELECT arrivals FROM population_resident_census WHERE tick=1') == 1
    assert world.store.scalar('SELECT departures FROM population_resident_census WHERE tick=3') == 1
    assert world.store.scalar('SELECT returns FROM population_resident_census WHERE tick=5') == 1
    assert world.store.scalar('SELECT arrivals FROM population_resident_census WHERE tick=5') == 0
    assert world.economy.ledger.reconcile()[0]


def test_later_corrupt_person_rolls_back_the_whole_input_batch(scenario_world):
    entries = [proposal('a-valid', tick=1), proposal('b-corrupt', tick=1, actor='agent:24')]
    world = scenario_world(entries)
    world.store.execute('DROP TRIGGER person_residence_no_delete')
    world.store.execute('DELETE FROM person_residence_events WHERE agent_id=24')
    world.store.set_meta(active_tick=1, next_phase='NIGHT_CLOSE')
    before = contents(world.store)
    with pytest.raises(ResidenceError):
        world.population_scenario.apply(1)
    assert contents(world.store) == before
    assert not input_receipts(world)


def test_duplicate_origin_is_a_source_failure_and_never_a_guessed_person(scenario_world):
    world = scenario_world([proposal(tick=1)])
    world.store.execute("UPDATE events SET payload_json=json_set(payload_json,'$.random_key','agent:23') "
                        "WHERE kind='person_registered' AND subject_id=24")
    world.store.set_meta(active_tick=1, next_phase='NIGHT_CLOSE')
    before = contents(world.store)
    with pytest.raises(ResidenceError, match='multiple people'):
        world.population_scenario.apply(1)
    assert contents(world.store) == before


def test_changed_schedule_is_rejected_when_reopening_the_world(scenario_world):
    world = scenario_world([proposal(tick=1)])
    scenario_world.close(world)
    with pytest.raises(ResidenceError, match='recorded run configuration'):
        scenario_world([proposal(tick=1, due=3)])
    original = scenario_world([proposal(tick=1)])
    assert original.store.tick == 0 and not input_receipts(original)
    asyncio.run(original.step())
    assert input_receipts(original)[0]['outcome'] == 'accepted'


@pytest.mark.parametrize('include_care', [True, False])
def test_scheduled_birth_precedes_group_input_and_child_requires_explicit_care(scenario_world, include_care):
    child_key = stable_key('birth', 1, 'agent:23')
    leaving = proposal(tick=1)
    leaving['members'].append(child_key)
    if include_care:
        leaving['care_plan'] = [{'child': child_key, 'guardian': 'agent:23'}]
    returning = proposal('back', tick=3, due=4, cause='return')
    returning['members'].append(child_key)
    returning['care_plan'] = [{'child': child_key, 'guardian': 'agent:23'}]
    world = scenario_world([leaving, returning] if include_care else [leaving],
        scheduled_births=[{'tick': 1, 'parent_agent_id': 23}])
    for day in range(1, 5):
        asyncio.run(world.step())
        world.population_scenario.check_progress()
        assert world.economy.ledger.reconcile()[0]
        if include_care and day in (2, 3):
            child = world.store.scalar("SELECT agent_id FROM person_lifecycle WHERE birth_key='birth:1:23'")
            assert not world.economy.population.is_local(23, day)
            assert not world.economy.population.is_local(child, day)
            assert world.store.scalar('SELECT COUNT(*) FROM time_days WHERE tick=? AND agent_id IN (?,23)', (day, child)) == 0
    receipts = input_receipts(world)
    if include_care:
        assert [row['outcome'] for row in receipts] == ['accepted', 'accepted']
        assert world.store.scalar('SELECT departures FROM population_resident_census WHERE tick=2') == 2
        assert world.store.scalar('SELECT returns FROM population_resident_census WHERE tick=4') == 2
    else:
        assert receipts[0]['outcome'] == 'rejected'
        assert 'every affected minor' in receipts[0]['reason']
        assert world.store.scalar('SELECT COUNT(*) FROM population_movements') == 0
    assert world.store.scalar('SELECT births FROM population_resident_census WHERE tick=1') == 1
    assert world.store.scalar('SELECT closing_residents FROM population_resident_census WHERE tick=4') == 48


def test_declared_withdrawal_cancels_previous_adult_assent(scenario_world):
    accept = response(tick=1)
    withdraw = {**response(tick=2, decision='withdraw'), 'key': 'withdraw'}
    world = scenario_world([proposal(tick=1, due=3), accept, withdraw])
    home = world.economy.households.membership(23)['household_id']
    world.economy.families._move_members(0, [{'agent_id': 24}], home, 'fixture_join')
    for _ in range(3):
        asyncio.run(world.step())
    movement = world.store.query_one('SELECT * FROM population_movements')
    assert movement['status'] == 'cancelled' and movement['reason'] == 'adult_withdraw'
    assert world.economy.population.is_local(23, 3)
    assert [row['outcome'] for row in input_receipts(world)] == ['accepted'] * 3
    world.population_scenario.check_progress()

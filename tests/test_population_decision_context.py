"""Resident decision guidance and return-only control in draft population worlds."""
import asyncio
from contextlib import closing
import copy
import hashlib
from pathlib import Path

import pytest

from engine.population_history import ResidenceError
from engine.store import open_read_only_connection
from research.export_bundle import export_bundle, validate_bundle
from world.replay_verify import verify_replay_connections
from .test_population_actions import movement_action
from .test_population_civic_routines import CITY_CONFIG
from .test_population_residence_history import contents
from .test_population_runtime import RUNTIME_CONFIG
from .test_population_scenario import proposal, scenario_world


def corrupt_origin(world, actor):
    event = world.store.scalar(
        'SELECT event_id FROM person_residence_events WHERE agent_id=? ORDER BY id LIMIT 1', (actor,))
    world.store.update('events', event, payload_json='{}')


def missed_wage(world):
    """Declared unfunded employer; the engine records delivered work and its debt."""
    store, e = world.store, world.economy
    actor = store.query_one('SELECT * FROM agents WHERE id=23')
    wallet = store.query_one('SELECT * FROM accounts WHERE id=?', (actor['checking_account_id'],))
    store.execute("UPDATE employments SET status='ended' WHERE agent_id=23 AND status='active'")
    firm = store.insert('firms', name='Declared unpaid employer', status='private',
                        founder_agent_id=25, region_id=actor['region_id'], founded_tick=0)
    account = e.ledger.create_account('firm', firm, 'checking', bank_id=wallet['bank_id'],
                                      currency_code=wallet['currency_code'], opening_cents=0)
    store.update('firms', firm, account_id=account)
    tick = store.tick + 1
    employment = store.insert('employments', agent_id=23, firm_id=firm, wage_cents=3000,
        pay_interval_ticks=30, start_tick=store.tick, next_pay_tick=tick, status='active')
    store.update('agents', 23, employer_id=firm)
    e.daily_time.prepare_day(tick)
    e.earned_wages.process_due(tick)
    assert store.scalar('SELECT SUM(a.earned_cents) FROM wage_accruals a JOIN wage_claims c ON c.id=a.claim_id '
                        'WHERE c.employment_id=?', (employment,)) > 0
    assert store.scalar("SELECT COUNT(*) FROM events WHERE kind='wage_missed' "
                        "AND json_extract(payload_json,'$.employment_id')=?", (employment,)) == 1
    return store.query_one('SELECT * FROM agents WHERE id=23'), tick


@pytest.mark.parametrize('state', ['outside', 'minor', 'missing_history'])
def test_wage_guidance_requires_an_available_adult_lawyer(scenario_world, state):
    world = scenario_world([proposal(actor='agent:9')] if state == 'outside' else [],
                           config_overrides=RUNTIME_CONFIG)
    if state == 'outside':
        for _ in range(2):
            asyncio.run(world.step())
    elif state == 'minor':
        world.store.update('agents', 9, age=17)
    # A second qualified, existing resident supplies a real available alternative.
    world.store.update('agents', 24, occupation='lawyer')
    actor, tick = missed_wage(world)
    if state == 'missing_history':
        corrupt_origin(world, 9)
    before = contents(world.store)
    if state == 'missing_history':
        with pytest.raises(ResidenceError):
            world.runtime.ctx._legal_work(actor, tick)
    else:
        actions = world.runtime.ctx._legal_work(actor, tick)['eligible_actions']
        assert len(actions) == 1
        assert actions[0]['counsel_agent_id'] == 24
        assert actions[0]['requested_remedy']['amount_cents'] > 0
    assert contents(world.store) == before
    if state != 'missing_history':
        result = world.economy.legal.file_claim(tick, 23, actions[0])
        assert result['ok'], result
        assert result['counsel_request_id'] > 0
        # Filing requests representation; the lawyer must still consent.
        assert world.store.scalar('SELECT counsel_agent_id FROM legal_matters WHERE id=?',
                                  (result['matter_id'],)) is None
    assert world.economy.ledger.reconcile()[0]


def test_minor_cannot_supply_engine_legal_representation(scenario_world):
    world = scenario_world([], config_overrides=RUNTIME_CONFIG)
    actor, tick = missed_wage(world)
    claim = world.runtime.ctx._legal_work(actor, tick)['eligible_actions'][0]
    world.store.update('agents', 9, age=17)
    before = contents(world.store)
    assert not world.economy.legal._is_lawyer(9)
    with pytest.raises(ValueError, match='living adult lawyer'):
        world.economy.legal.file_claim(tick, 23, claim)
    assert contents(world.store) == before


def test_unavailable_counsel_leaves_earned_wages_unfiled_and_owned(scenario_world):
    world = scenario_world([proposal(actor='agent:9')], config_overrides=RUNTIME_CONFIG)
    for _ in range(2):
        asyncio.run(world.step())
    actor, tick = missed_wage(world)
    before = contents(world.store)
    assert world.runtime.ctx._legal_work(actor, tick)['eligible_actions'] == []
    assert contents(world.store) == before


@pytest.mark.parametrize('state', ['outside', 'minor'])
def test_legacy_wage_guidance_keeps_its_original_counsel_selection(scenario_world, state):
    world = scenario_world([proposal(actor='agent:9')] if state == 'outside' else [],
                           config_overrides=RUNTIME_CONFIG)
    if state == 'outside':
        for _ in range(2):
            asyncio.run(world.step())
    actor, tick = missed_wage(world)
    if state == 'minor':
        world.store.update('agents', 9, age=17)
    # Component comparison only; the actual historical-world suites test replay.
    world.economy.engine_semantics_version = 20
    world.runtime.ctx.engine_semantics_version = 20
    assert world.runtime.ctx._legal_work(actor, tick)['eligible_actions'][0]['counsel_agent_id'] == 9
    assert world.economy.legal._is_lawyer(9)


def test_outside_return_decision_does_not_build_local_civic_context(scenario_world):
    world = scenario_world([proposal()], config_overrides=CITY_CONFIG)
    for _ in range(2):
        asyncio.run(world.step())
    decision = {'agent_id': 23, 'purpose': 'decision', 'envelope': {
        'actions': [movement_action(cause='return', tick=5)]}}
    original = copy.deepcopy(decision)
    before = contents(world.store)
    world.runtime._attach_civic_decision_context(3, decision)
    assert decision == original
    assert contents(world.store) == before


def test_invalid_controlled_actor_history_fails_before_context_effects(scenario_world):
    world = scenario_world([], config_overrides=CITY_CONFIG)
    corrupt_origin(world, 23)
    decision = {'agent_id': 23, 'purpose': 'decision'}
    original = copy.deepcopy(decision)
    before = contents(world.store)
    with pytest.raises(ResidenceError):
        world.runtime._attach_civic_decision_context(1, decision)
    assert decision == original
    assert contents(world.store) == before


@pytest.mark.parametrize('control', ['participant', 'external'])
def test_city_return_controls_restart_replay_and_export(scenario_world, tmp_path, control):
    config = {**CITY_CONFIG, 'participant_mode': {'enabled': control == 'participant'},
              'external_agents': {'enabled': control == 'external'}}
    world = scenario_world([], 'city-control-source', config_overrides=config)
    credential = None
    if control == 'external':
        connection = world.runtime.external.create_connection(tenant_id='fixture', owner_id='fixture-owner',
            display_name='Returning city resident', tier='actor', preferred_occupation='worker')
        credential = connection['credential']['token']
    asyncio.run(world.step())
    auth = (world.runtime.external.authenticate(credential, rate_limit=False)
            if credential is not None else None)
    actor = int(auth['actor_id']) if auth is not None else 23
    original = tuple(world.store.query_one(
        'SELECT checking_account_id,savings_account_id FROM agents WHERE id=?', (actor,)))
    region = world.store.scalar('SELECT region_id FROM agents WHERE id=?', (actor,))
    population = world.store.scalar('SELECT COUNT(*) FROM agents')
    assert population == (48 if control == 'external' else 47)

    def submit(cause, due_tick):
        action = movement_action(cause=cause, tick=due_tick, key=cause, actor=actor)
        if cause == 'return':
            action['destination_region_id'] = region
        if control == 'participant':
            world.runtime.participant.acquire(actor, world.store.tick, running=False)
            world.runtime.participant.queue_action(world.store.tick, action, running=False)
        else:
            service = world.runtime.external
            turn = service.turn(auth)
            if cause == 'return':
                assert {item['type'] for item in turn['action_catalog']} == {'propose_population_movement'}
            queued = service.submit_action(auth, {'idempotency_key': cause,
                'target_tick': turn['target_tick'], 'observed_projection_hash': turn['projection_hash'],
                'action': action})
            assert queued['status'] == 'queued'

    submit('departure', 4)
    for _ in range(3):
        asyncio.run(world.step())
    assert not world.economy.population.is_local(actor, 4)
    submit('return', 7)
    for day in range(5, 8):
        if day in (5, 7):
            phase = 'MORNING' if day == 5 else 'NIGHT_CLOSE'
            paused = asyncio.run(world.step(pause_after_phase=phase))
            assert paused['active_tick'] == day
            scenario_world.close(world)
            world = scenario_world([], 'city-control-source', config_overrides=config)
        asyncio.run(world.step())
        assert world.economy.ledger.reconcile()[0]
    assert world.economy.population.is_local(actor, 7)
    assert world.store.scalar('SELECT returns FROM population_resident_census WHERE tick=7') == 1
    assert world.store.scalar('SELECT arrivals FROM population_resident_census WHERE tick=7') == 0
    assert world.store.scalar('SELECT COUNT(*) FROM agents') == population
    assert tuple(world.store.query_one('SELECT checking_account_id,savings_account_id FROM agents WHERE id=?',
                                      (actor,))) == original
    for table in ('llm_calls', 'attention_contexts', 'time_allocations', 'effective_presence'):
        assert world.store.scalar(f'SELECT COUNT(*) FROM {table} WHERE agent_id=? AND tick BETWEEN 4 AND 6',
                                  (actor,)) == 0
    assert world.store.scalar('SELECT COUNT(*) FROM attention_contexts WHERE agent_id=? AND tick=2', (actor,)) > 0
    source = Path(world.store.path)
    scenario_world.close(world)
    stamp = hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns
    replay = scenario_world([], 'city-control-replay', replay_source=source, config_overrides=config)
    for day in range(1, 8):
        if day in (5, 7):
            asyncio.run(replay.step(pause_after_phase='MORNING' if day == 5 else 'NIGHT_CLOSE'))
            scenario_world.close(replay)
            replay = scenario_world([], 'city-control-replay', replay_source=source, config_overrides=config)
        asyncio.run(replay.step())
        assert replay.economy.ledger.reconcile()[0]
    target = Path(replay.store.path)
    scenario_world.close(replay)
    with closing(open_read_only_connection(source, require_closed=True)) as src, \
            closing(open_read_only_connection(target, require_closed=True)) as dst:
        proof = verify_replay_connections(src, dst)
        assert proof['exact'], proof['differences']
        for database, directory in ((src, 'source-export'), (dst, 'replay-export')):
            manifest = validate_bundle(export_bundle(database, tmp_path/directory), database=database)
            assert manifest['contract_id'] == 'hash-contract-v8'
            assert database.execute('SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls').fetchone()[0] == 0
            assert database.execute("SELECT COUNT(*) FROM llm_calls WHERE provider<>'scripted'").fetchone()[0] == 0
    assert (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns) == stamp
    assert not any(Path(str(source)+suffix).exists() for suffix in ('-wal', '-shm', '-journal'))

"""Movement commands, limited outside controls and recorded World execution."""
import asyncio
from contextlib import closing
import hashlib
from pathlib import Path

import pytest

from engine.actions import ActionExecutor
from engine.store import open_read_only_connection
from agents.participant import ParticipantError
from world.replay_verify import verify_replay_connections
from .test_population_scenario import proposal, scenario_world
from .test_population_residence_history import contents
from .test_population_runtime import RUNTIME_CONFIG
from .test_population_movements import moving, child_household, advance
from .test_population_residence_history import residence_case
from .test_semantics20_estate_cases import estate_case


def movement_action(*, cause='departure', tick=2, key='choice', actor=23):
    action = {'type': 'propose_population_movement', 'cause': cause, 'member_ids': [actor],
              'care_plan': [], 'due_tick': tick, 'request_key': key}
    if cause == 'return':
        action['destination_region_id'] = 1
    return action


def test_executor_departure_and_outside_return_preserve_accounts(scenario_world):
    world = scenario_world([], config_overrides=RUNTIME_CONFIG)
    executor = ActionExecutor(world.economy)
    account = world.store.scalar('SELECT checking_account_id FROM agents WHERE id=23')
    assert executor.execute_action(0, 23, movement_action())['ok']
    for _ in range(2):
        asyncio.run(world.step())
    assert not world.economy.population.is_local(23, 2)
    assert not executor.execute_action(2, 23, {'type': 'do_nothing'})['ok']
    result = executor.execute_action(2, 23, movement_action(cause='return', tick=4, key='back'))
    assert result['ok'], result
    for _ in range(2):
        asyncio.run(world.step())
    assert world.economy.population.is_local(23, 4)
    assert world.store.scalar('SELECT checking_account_id FROM agents WHERE id=23') == account
    assert world.economy.ledger.reconcile()[0]


@pytest.mark.parametrize('patch', [
    {'member_ids': [True]}, {'member_ids': ['23']}, {'due_tick': 2.5},
    {'cause': 'return'}, {'destination_region_id': 1},
    {'care_plan': [{'child_id': 30, 'guardian_id': 23, 'consent': True}]},
])
def test_typed_movement_rejection_precedes_proposal_or_money(scenario_world, patch):
    world = scenario_world([], config_overrides=RUNTIME_CONFIG)
    before = [tuple(row) for row in world.store.query('SELECT * FROM ledger_entries ORDER BY id')]
    result = ActionExecutor(world.economy).execute_action(0, 23, {**movement_action(), **patch})
    assert not result['ok']
    assert world.store.scalar('SELECT COUNT(*) FROM population_movements') == 0
    assert world.store.scalar('SELECT COUNT(*) FROM action_proposals') == 0
    assert before == [tuple(row) for row in world.store.query('SELECT * FROM ledger_entries ORDER BY id')]


def test_outside_catalog_offers_only_return_and_does_not_retrieve_memories(scenario_world):
    world = scenario_world([proposal()], config_overrides={**RUNTIME_CONFIG, 'participant_mode': {'enabled': True}})
    for _ in range(2):
        asyncio.run(world.step())
    participant = world.runtime.participant
    before = contents(world.store)
    catalog = participant.action_catalog(23)
    assert len(catalog) == 1 and catalog[0]['type'] == 'propose_population_movement'
    assert next(field['default'] for field in catalog[0]['fields'] if field['name'] == 'cause') == 'return'
    assert contents(world.store) == before
    status = participant.acquire(23, 2, running=False)
    assert status['active'] and participant.active_agent_id() == 23
    with pytest.raises(ParticipantError, match='not available'):
        participant.queue_action(2, {'type': 'do_nothing'}, running=False)
    command = movement_action(cause='return', tick=5, key='outside-control')
    participant.queue_action(2, command, running=False)
    asyncio.run(world.step())
    assert not participant.active_agent_id()
    assert world.store.scalar("SELECT status FROM participant_actions WHERE target_tick=3") == 'executed'
    assert world.store.scalar("SELECT COUNT(*) FROM population_movements WHERE request_key='outside-control'") == 1
    for _ in range(2):
        asyncio.run(world.step())
    assert world.economy.population.is_local(23, 5)
    assert world.economy.ledger.reconcile()[0]


def test_resident_catalog_and_validation_do_not_change_simulated_memory(scenario_world):
    world = scenario_world([], config_overrides={**RUNTIME_CONFIG, 'participant_mode': {'enabled': True}})
    asyncio.run(world.step())
    before = contents(world.store)
    participant = world.runtime.participant
    assert participant.action_catalog(23) == participant.action_catalog(23)
    assert participant.normalize_action(23, {'type': 'do_nothing'}) == {'type': 'do_nothing'}
    assert contents(world.store) == before
    agent = world.store.query_one('SELECT * FROM agents WHERE id=23')
    context = participant.ctx.build(agent, 2)
    assert context['population_boundary']['proposal_template']['cause'] == 'departure'
    assert context['memories']
    assert world.store.scalar('SELECT COUNT(*) FROM memories WHERE agent_id=23 AND last_accessed_tick=2') > 0


def test_partial_household_command_requires_care_and_each_adults_own_consent(moving, monkeypatch):
    import engine.semantics as semantics
    monkeypatch.setattr(semantics, 'CURRENT_ENGINE_SEMANTICS_VERSION', 21)
    c = moving
    c.e.config['engine_semantics_version'] = 21
    child = child_household(c)
    executor = ActionExecutor(c.e)
    terms = movement_action(actor=c.person, tick=3)
    terms['member_ids'] = [c.person, child]
    assert not executor.execute_action(1, c.person, terms)['ok']
    assert c.e.store.scalar('SELECT COUNT(*) FROM population_movements') == 0
    terms['care_plan'] = [{'child_id': child, 'guardian_id': c.person}]
    accepted = executor.execute_action(1, c.person, terms)
    assert accepted['ok'], accepted
    movement = accepted['movement_id']
    assert c.e.store.scalar('SELECT COUNT(*) FROM population_movement_assents') == 1
    response = {'type': 'respond_population_movement', 'movement_id': movement, 'decision': 'accept'}
    assert not executor.execute_action(1, child, response)['ok']
    assert executor.execute_action(1, c.heir, response)['ok']
    assert c.e.store.scalar('SELECT COUNT(*) FROM population_movement_assents') == 2
    advance(c, 3)
    assert c.e.population.settle(3, movement)['status'] == 'applied'
    assert not c.e.population.is_local(c.person, 3)
    assert not c.e.population.is_local(child, 3)
    assert c.e.population.is_local(c.heir, 3)
    assert c.e.ledger.reconcile()[0]


def assert_closed_replay(create, world, config, days, *, entries=()):
    source = Path(world.store.path)
    create.close(world)
    stamp = hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns
    replay = create(list(entries), 'action-replay', replay_source=source, config_overrides=config)
    for _ in range(days):
        asyncio.run(replay.step())
    target = Path(replay.store.path)
    create.close(replay)
    with closing(open_read_only_connection(source, require_closed=True)) as src, \
         closing(open_read_only_connection(target, require_closed=True)) as dst:
        result = verify_replay_connections(src, dst)
        assert result['exact'], result['differences']
        assert src.execute("SELECT COUNT(*) FROM llm_calls WHERE provider<>'scripted'").fetchone()[0] == 0
        assert src.execute('SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls').fetchone()[0] == 0
    assert stamp == (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns)
    assert not any(Path(str(source) + suffix).exists() for suffix in ('-wal', '-shm', '-journal'))


def test_participant_departure_and_return_commands_restart_and_replay(scenario_world):
    config = {**RUNTIME_CONFIG, 'participant_mode': {'enabled': True}}
    world = scenario_world([], 'action-source', config_overrides=config)
    participant = world.runtime.participant
    account = world.store.scalar('SELECT checking_account_id FROM agents WHERE id=23')
    participant.acquire(23, 0, running=False)
    participant.queue_action(0, movement_action(tick=3), running=False)
    paused = asyncio.run(world.step(pause_after_phase='MORNING'))
    assert paused['active_tick'] == 1
    scenario_world.close(world)
    world = scenario_world([], 'action-source', config_overrides=config)
    asyncio.run(world.step())
    participant = world.runtime.participant
    assert world.store.scalar("SELECT status FROM participant_actions WHERE target_tick=1") == 'executed'
    for day in (2, 3):
        participant.queue_action(day-1, {'type': 'do_nothing'}, running=False)
        asyncio.run(world.step())
    assert not world.economy.population.is_local(23, 3)
    assert world.store.scalar("SELECT status FROM participant_actions WHERE target_tick=3") == 'cancelled'
    assert participant.active_agent_id() is None
    participant.acquire(23, 3, running=False)
    participant.queue_action(3, movement_action(cause='return', tick=6, key='back'), running=False)
    paused = asyncio.run(world.step(pause_after_phase='MORNING'))
    assert paused['active_tick'] == 4
    scenario_world.close(world)
    world = scenario_world([], 'action-source', config_overrides=config)
    asyncio.run(world.step())
    for _ in range(2):
        asyncio.run(world.step())
    assert world.economy.population.is_local(23, 6)
    assert world.runtime.participant.active_agent_id() is None
    assert world.store.scalar('SELECT checking_account_id FROM agents WHERE id=23') == account
    assert world.store.scalar("SELECT COUNT(*) FROM llm_calls WHERE agent_id=23 AND tick BETWEEN 3 AND 5") == 0
    assert world.economy.ledger.reconcile()[0]
    assert_closed_replay(scenario_world, world, config, 6)


def test_external_first_arrival_departure_and_return_replay_without_network(scenario_world):
    config = {**RUNTIME_CONFIG, 'external_agents': {'enabled': True}}
    world = scenario_world([], 'external-source', config_overrides=config)
    service = world.runtime.external
    created = service.create_connection(tenant_id='fixture', owner_id='fixture-owner',
        display_name='Returning Citizen', tier='actor', preferred_occupation='worker')
    credential = created['credential']['token']
    asyncio.run(world.step())
    auth = service.authenticate(credential, rate_limit=False)
    actor = int(auth['actor_id'])
    original = dict(world.store.query_one('SELECT checking_account_id,savings_account_id FROM agents WHERE id=?', (actor,)))
    original_region = world.store.scalar('SELECT region_id FROM agents WHERE id=?', (actor,))
    turn = service.turn(auth)
    queued = service.submit_action(auth, {'idempotency_key': 'depart', 'target_tick': 2,
        'observed_projection_hash': turn['projection_hash'], 'action': movement_action(tick=4, actor=actor)})
    assert queued['status'] == 'queued'
    for _ in range(3):
        asyncio.run(world.step())
    assert not world.economy.population.is_local(actor, 4)
    assert service.receipt(auth, queued['submission_id'])['status'] == 'executed'
    before = contents(world.store)
    catalog = world.runtime.participant.action_catalog(actor)
    assert {item['type'] for item in catalog} == {'propose_population_movement'}
    assert contents(world.store) == before
    turn = service.turn(auth)
    queued = service.submit_action(auth, {'idempotency_key': 'return', 'target_tick': 5,
        'observed_projection_hash': turn['projection_hash'],
        'action': {**movement_action(cause='return', tick=7, key='back', actor=actor),
                   'destination_region_id': original_region}})
    assert queued['status'] == 'queued'
    paused = asyncio.run(world.step(pause_after_phase='MORNING'))
    assert paused['active_tick'] == 5
    scenario_world.close(world)
    world = scenario_world([], 'external-source', config_overrides=config)
    asyncio.run(world.step())
    for _ in range(2):
        asyncio.run(world.step())
    assert world.economy.population.is_local(actor, 7)
    assert original == dict(world.store.query_one('SELECT checking_account_id,savings_account_id FROM agents WHERE id=?', (actor,)))
    assert world.store.scalar('SELECT returns FROM population_resident_census WHERE tick=7') == 1
    assert world.store.scalar('SELECT arrivals FROM population_resident_census WHERE tick=7') == 0
    assert world.store.scalar('SELECT COUNT(*) FROM llm_calls WHERE agent_id=? AND tick BETWEEN 4 AND 6', (actor,)) == 0
    assert world.store.scalar("SELECT COUNT(*) FROM external_turn_attendance WHERE actor_id=? "
        "AND target_tick BETWEEN 4 AND 6 AND attendance_status='missed'", (actor,)) == 0
    assert world.runtime.external.receipt(auth, queued['submission_id'])['status'] == 'executed'
    assert world.economy.ledger.reconcile()[0]
    assert_closed_replay(scenario_world, world, config, 7)

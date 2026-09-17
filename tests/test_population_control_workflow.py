"""Economic observations and control rights across population boundaries."""
import asyncio
from contextlib import closing
import hashlib
import json
from pathlib import Path

import pytest

from engine.store import open_read_only_connection
from research.export_bundle import export_bundle, validate_bundle
from world.replay_verify import verify_replay_connections
from .test_population_actions import movement_action
from .test_population_residence_history import contents
from .test_population_runtime import RUNTIME_CONFIG
from .test_population_scenario import proposal, scenario_world


@pytest.mark.parametrize('outside', [False, True])
def test_external_observation_includes_private_firm_goods_quotes(scenario_world, outside):
    world = scenario_world([proposal()])
    if outside:
        for _ in range(2):
            asyncio.run(world.step())
        assert not world.economy.population.is_available(23)
    expected = {row['id'] for row in world.store.query(
        "SELECT id FROM firms WHERE status IN ('private','listed') ORDER BY id LIMIT 100")}
    private = {row['id'] for row in world.store.query("SELECT id FROM firms WHERE status='private'")}
    assert private
    before = contents(world.store)
    observed = world.runtime.external.observe({'actor_id':23, 'scopes':['world.read']})
    assert {row['firm_id'] for row in observed['market']} == expected
    assert contents(world.store) == before


def test_external_goods_quotes_keep_currency_location_and_price_basis(scenario_world):
    world = scenario_world([])
    before = contents(world.store)
    observed = world.runtime.external.observe({'actor_id':23, 'scopes':['world.read']})
    assert observed['market']
    for quote in observed['market']:
        firm = world.store.query_one('SELECT * FROM firms WHERE id=?', (quote['firm_id'],))
        assert quote['currency_code'] == firm['currency_code']
        assert quote['region_id'] == firm['region_id']
        assert quote['price_basis'] == 'posted_quote'
        assert quote['unit_price_cents'] == json.loads(firm['product_json'])['unit_price_cents']
    assert contents(world.store) == before


@pytest.mark.parametrize('version', [1, 2, 9, 20])
def test_historical_external_observation_retains_its_recorded_contract(scenario_world, version):
    world = scenario_world([])
    world.economy.engine_semantics_version = version
    before = contents(world.store)
    expected = [dict(row) for row in world.store.query(
        "SELECT f.id AS firm_id,f.name,f.sector,f.inventory,"
        "json_extract(f.product_json,'$.unit_price_cents') AS unit_price_cents "
        "FROM firms f WHERE f.status IN ('operating','listed') ORDER BY f.id LIMIT 100")]
    observed = world.runtime.external.observe({'actor_id':23, 'scopes':['world.read']})
    assert observed['market'] == expected
    assert 'population_boundary' not in observed
    assert contents(world.store) == before


def test_recorded_private_quotes_survive_departure_return_restart_and_export(scenario_world, tmp_path):
    config = {**RUNTIME_CONFIG, 'external_agents': {'enabled': True}}
    world = scenario_world([], 'quotes-source', config_overrides=config)
    service = world.runtime.external
    connection = service.create_connection(tenant_id='fixture', owner_id='fixture-owner',
        display_name='Goods researcher', tier='actor', preferred_occupation='worker')
    credential = connection['credential']['token']
    asyncio.run(world.step())
    auth = service.authenticate(credential, rate_limit=False)
    actor = int(auth['actor_id'])
    original_accounts = dict(world.store.query_one(
        'SELECT checking_account_id,savings_account_id FROM agents WHERE id=?', (actor,)))
    original_region = world.store.scalar('SELECT region_id FROM agents WHERE id=?', (actor,))
    private = {row['id'] for row in world.store.query("SELECT id FROM firms WHERE status='private'")}
    assert private
    recorded_turns = []

    def submit_movement(cause, due_tick):
        service = world.runtime.external
        before = contents(world.store)
        observation = service.observe(auth)
        assert contents(world.store) == before
        quotes = {row['firm_id']: row for row in observation['market']}
        assert private <= quotes.keys()
        assert all(quotes[firm]['price_basis'] == 'posted_quote' for firm in private)
        assert all(quotes[firm]['currency_code'] and quotes[firm]['region_id'] for firm in private)
        turn = service.turn(auth)
        assert turn['observations'] == observation
        if cause == 'return':
            assert {item['type'] for item in turn['action_catalog']} == {'propose_population_movement'}
        action = movement_action(cause=cause, tick=due_tick, key=cause, actor=actor)
        if cause == 'return':
            action['destination_region_id'] = original_region
        receipt = service.submit_action(auth, {'idempotency_key': cause,
            'target_tick': turn['target_tick'], 'observed_projection_hash': turn['projection_hash'],
            'action': action})
        assert receipt['status'] == 'queued'
        recorded_turns.append(turn['turn_id'])
        return receipt

    departed = submit_movement('departure', 4)
    for _ in range(3):
        asyncio.run(world.step())
    assert not world.economy.population.is_local(actor, 4)
    assert service.receipt(auth, departed['submission_id'])['status'] == 'executed'
    returned = submit_movement('return', 7)
    paused = asyncio.run(world.step(pause_after_phase='MORNING'))
    assert paused['active_tick'] == 5
    scenario_world.close(world)
    world = scenario_world([], 'quotes-source', config_overrides=config)
    for _ in range(3):
        asyncio.run(world.step())
    assert world.store.tick == 7
    assert world.economy.population.is_local(actor, 7)
    assert world.runtime.external.receipt(auth, returned['submission_id'])['status'] == 'executed'
    assert original_accounts == dict(world.store.query_one(
        'SELECT checking_account_id,savings_account_id FROM agents WHERE id=?', (actor,)))
    assert world.store.scalar('SELECT COUNT(*) FROM llm_calls WHERE agent_id=? AND tick BETWEEN 4 AND 6', (actor,)) == 0
    assert world.economy.ledger.reconcile()[0]
    source = Path(world.store.path)
    scenario_world.close(world)
    original = hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns
    replay = scenario_world([], 'quotes-replay', replay_source=source, config_overrides=config)
    for day in range(1, 8):
        if day == 5:
            asyncio.run(replay.step(pause_after_phase='MORNING'))
            scenario_world.close(replay)
            replay = scenario_world([], 'quotes-replay', replay_source=source, config_overrides=config)
        asyncio.run(replay.step())
        assert replay.economy.ledger.reconcile()[0]
    replay_path = Path(replay.store.path)
    scenario_world.close(replay)
    with closing(open_read_only_connection(source, require_closed=True)) as src, \
            closing(open_read_only_connection(replay_path, require_closed=True)) as dst:
        proof = verify_replay_connections(src, dst)
        assert proof['exact'], proof['differences']
        for turn_id in recorded_turns:
            query = 'SELECT projection_hash,envelope_json FROM external_agent_turns WHERE id=?'
            recorded = tuple(src.execute(query, (turn_id,)).fetchone())
            assert tuple(dst.execute(query, (turn_id,)).fetchone()) == recorded
            quotes = json.loads(recorded[1])['observations']['market']
            assert private <= {row['firm_id'] for row in quotes}
        for database, directory in ((src, 'source-export'), (dst, 'replay-export')):
            manifest = validate_bundle(export_bundle(database, tmp_path / directory), database=database)
            assert manifest['contract_id'] == 'hash-contract-v8'
            assert database.execute('SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls').fetchone()[0] == 0
            assert database.execute("SELECT COUNT(*) FROM llm_calls WHERE provider<>'scripted'").fetchone()[0] == 0
    assert (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns) == original
    assert not any(Path(str(source) + suffix).exists() for suffix in ('-wal', '-shm', '-journal'))

"""Local adult shopper guidance without losing recorded child consumption."""
import asyncio
from contextlib import closing
import hashlib
import json
from pathlib import Path

import pytest

from agents.policies import citizen_decision
from agents.prompts import ContextBuilder
from engine.population_history import ResidenceError
from engine.store import open_read_only_connection
from research.export_bundle import export_bundle, validate_bundle
from world.replay_verify import verify_replay_connections
from .test_population_civic_routines import CITY_CONFIG
from .test_population_decision_context import corrupt_origin
from .test_population_residence_history import contents
from .test_population_runtime import RUNTIME_CONFIG
from .test_population_scenario import proposal, scenario_world


def shopping_world(create, state, local):
    config = {**RUNTIME_CONFIG, 'behavior': {'inventory_aware_shopping': True, 'act_every': 1},
              'llm': {'local_currency_action_surfaces': local},
              'lifecycle': {'illness_onset_annual_young': 0, 'illness_onset_annual_old': 0}}
    world = create([proposal()] if state in {'outside', 'both'} else [],
        scheduled_births=[{'tick': 1, 'parent_agent_id': 24}] if state in {'child', 'both'} else [],
        config_overrides=config)
    # Declared component fixture: all existing adult citizens wake every day.
    for row in world.store.query("SELECT id,cadence_json FROM agents WHERE kind='citizen'"):
        cadence = json.loads(row['cadence_json'])
        cadence['act'] = 1
        world.store.update('agents', row['id'], cadence_json=json.dumps(cadence, sort_keys=True))
    for _ in range(2):
        asyncio.run(world.step())
    return world


def stock_for_two_units_per_scheduled_shopper(world):
    """Declare stock for a component test; purchases still settle through the engine."""
    tick = world.store.tick + 1
    actor = world.store.query_one('SELECT * FROM agents WHERE id=24')
    scheduled = world.runtime.scheduler.scheduled_agents(tick)
    assert 23 not in {row['id'] for row in scheduled} or world.economy.population.is_local(23, tick)
    assert all(row['age'] >= 18 for row in scheduled)
    world.runtime.ctx.prepare_decision_cohort(scheduled, tick)
    region = actor['region_id'] if world.runtime.ctx.local_currency_action_surfaces else None
    count = world.runtime.ctx._decision_shoppers_by_region[region]
    assert count > 0
    currency = world.store.scalar('SELECT currency_code FROM accounts WHERE id=?', (actor['checking_account_id'],))
    offers = world.runtime.ctx._goods_offers(currency)
    assert offers
    seller = offers[0]['firm_id']
    world.store.execute('UPDATE firms SET inventory=0')
    world.store.update('firms', seller, inventory=2*count)
    cached = world.runtime.ctx._citizen_context(actor, tick, retrieve_memories=False)
    assert cached['shopping_qty_cap'] == 2
    return actor, tick, seller


@pytest.mark.parametrize('local', [True, False])
@pytest.mark.parametrize('state', ['outside', 'child', 'both'])
def test_uncached_guidance_uses_the_same_eligible_adults_and_settles_purchase(scenario_world, state, local):
    world = shopping_world(scenario_world, state, local)
    actor, tick, seller = stock_for_two_units_per_scheduled_shopper(world)
    fresh = ContextBuilder(world.economy, world.runtime.mem, world.config)
    before = contents(world.store)
    context = fresh._citizen_context(actor, tick, retrieve_memories=False)
    assert context['shopping_qty_cap'] == 2
    assert contents(world.store) == before
    purchases = [action for action in citizen_decision(context)['actions'] if action['type'] == 'buy_goods']
    assert len(purchases) == 1 and purchases[0]['qty'] == 2
    assert purchases[0]['firm_id'] == seller
    inventory = world.store.scalar('SELECT inventory FROM firms WHERE id=?', (seller,))
    cash = world.store.scalar('SELECT balance_cents FROM accounts WHERE id=?', (actor['checking_account_id'],))
    result = world.economy.firms.buy_goods(tick, actor['id'], seller, purchases[0]['qty'])
    assert result['ok'], result
    assert result['qty'] == 2 and result['total_cents'] > 0
    assert world.store.scalar('SELECT inventory FROM firms WHERE id=?', (seller,)) == inventory - 2
    assert world.store.scalar('SELECT balance_cents FROM accounts WHERE id=?',
                              (actor['checking_account_id'],)) == cash - result['total_cents']
    assert world.economy.ledger.reconcile()[0]


@pytest.mark.parametrize('local', [True, False])
def test_uncached_shopper_history_is_checked_without_read_context_effects(scenario_world, local):
    world = shopping_world(scenario_world, 'child', local)
    actor, tick, _ = stock_for_two_units_per_scheduled_shopper(world)
    corrupt_origin(world, 25)
    fresh = ContextBuilder(world.economy, world.runtime.mem, world.config)
    before = contents(world.store)
    with pytest.raises(ResidenceError):
        fresh._citizen_context(actor, tick, retrieve_memories=False)
    assert contents(world.store) == before


@pytest.mark.parametrize('local', [True, False])
def test_legacy_fallback_keeps_its_original_population_definition(scenario_world, local):
    world = shopping_world(scenario_world, 'both', local)
    actor, tick, _ = stock_for_two_units_per_scheduled_shopper(world)
    fresh = ContextBuilder(world.economy, world.runtime.mem, world.config)
    # Component comparison; the historical-world suites cover actual old replay.
    fresh.engine_semantics_version = 20
    before = contents(world.store)
    assert fresh._citizen_context(actor, tick, retrieve_memories=False)['shopping_qty_cap'] == 1
    assert contents(world.store) == before


def test_invalid_later_child_history_rolls_back_household_provisioning(scenario_world):
    world = scenario_world([], scheduled_births=[{'tick': 1, 'parent_agent_id': parent} for parent in (24, 25)],
                           config_overrides=RUNTIME_CONFIG)
    asyncio.run(world.step())
    children = [row['agent_id'] for row in world.store.query(
        "SELECT agent_id FROM person_lifecycle WHERE origin='birth' ORDER BY agent_id")]
    assert len(children) == 2
    corrupt_origin(world, children[-1])
    before = contents(world.store)
    with pytest.raises(ResidenceError):
        world.economy.households.provision_children(2)
    assert contents(world.store) == before


@pytest.mark.parametrize('parent,has_local_food', [(24, False), (27, True)])
def test_birth_consumption_and_return_keep_cohorts_replayable(scenario_world, tmp_path, parent, has_local_food):
    config = {**CITY_CONFIG, 'behavior': {'inventory_aware_shopping': True, 'act_every': 1},
              'llm': {'local_currency_action_surfaces': True}}
    entries = [proposal(), proposal('back', tick=3, due=5, cause='return')]
    births = [{'tick': 1, 'parent_agent_id': parent}]

    def create(name, replay_source=None):
        world = scenario_world(entries, name, replay_source=replay_source,
                               scheduled_births=births, config_overrides=config)
        if world.store.tick == 0:
            # Declared genesis cadence, also applied to the replay's genesis.
            for row in world.store.query("SELECT id,cadence_json FROM agents WHERE kind='citizen'"):
                cadence = json.loads(row['cadence_json'])
                cadence['act'] = 1
                world.store.update('agents', row['id'], cadence_json=json.dumps(cadence, sort_keys=True))
        return world

    def advance(world, name, replay_source=None):
        daily = []
        for day in range(1, 8):
            if day in (2, 5):
                paused = asyncio.run(world.step(pause_after_phase='MORNING' if day == 2 else 'NIGHT_CLOSE'))
                assert paused['active_tick'] == day
                scenario_world.close(world)
                world = create(name, replay_source)
            asyncio.run(world.step())
            assert world.economy.ledger.reconcile()[0]
            child = world.store.scalar("SELECT agent_id FROM person_lifecycle WHERE origin='birth'")
            assert child is not None
            assert world.store.scalar('SELECT COUNT(*) FROM llm_calls WHERE agent_id=?', (child,)) == 0
            if 2 <= day <= 4:
                assert not world.economy.population.is_local(23, day)
                assert world.store.scalar('SELECT COUNT(*) FROM llm_calls WHERE agent_id=23 AND tick=?', (day,)) == 0
            else:
                assert world.economy.population.is_local(23, day)
            # Compare an uncached read with the actual scheduler's cohort. No
            # inventory declarations or price overrides occur in this workflow.
            tick = day + 1
            before = contents(world.store)
            scheduled = world.runtime.scheduler.scheduled_agents(tick)
            assert child not in {row['id'] for row in scheduled}
            world.runtime.ctx.prepare_decision_cohort(scheduled, tick)
            actor = world.store.query_one('SELECT * FROM agents WHERE id=24')
            cached = world.runtime.ctx._citizen_context(actor, tick, retrieve_memories=False)
            fresh = ContextBuilder(world.economy, world.runtime.mem, world.config)
            uncached = fresh._citizen_context(actor, tick, retrieve_memories=False)
            assert uncached['shopping_qty_cap'] == cached['shopping_qty_cap']
            assert contents(world.store) == before
            need = dict(world.store.query_one('SELECT required_units,purchased_units,spent_cents,guardian_agent_id '
                'FROM child_needs WHERE tick=? AND child_agent_id=?', (day, child)))
            assert need['required_units'] > 0 and need['guardian_agent_id'] == parent
            daily.append({'day': day, 'cap': uncached['shopping_qty_cap'], 'child': child,
                          'shoppers': world.runtime.ctx._decision_shoppers_by_region, 'need': need})
        return world, daily

    world = create('shopping-source')
    # The declared genesis has food production in region 2 only. Exercise both
    # a supplied household and real unmet demand; do not fabricate inventory.
    home = world.store.query_one('SELECT region_id,checking_account_id FROM agents WHERE id=?', (parent,))
    currency = world.store.scalar('SELECT currency_code FROM accounts WHERE id=?', (home['checking_account_id'],))
    assert bool(world.store.scalar("SELECT COUNT(*) FROM firms WHERE sector='food' AND region_id=? "
        "AND currency_code=?", (home['region_id'], currency))) is has_local_food
    wallets = [tuple(row) for row in world.store.query(
        'SELECT id,checking_account_id,savings_account_id FROM agents WHERE id IN (23,24,27) ORDER BY id')]
    world, daily = advance(world, 'shopping-source')
    assert world.store.scalar('SELECT COUNT(*) FROM agents') == 48
    assert [tuple(row) for row in world.store.query('SELECT id,checking_account_id,savings_account_id '
        'FROM agents WHERE id IN (23,24,27) ORDER BY id')] == wallets
    assert (sum(row['need']['purchased_units'] for row in daily) > 0) is has_local_food
    assert (sum(row['need']['spent_cents'] for row in daily) > 0) is has_local_food
    source = Path(world.store.path)
    scenario_world.close(world)
    stamp = hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns
    replay, replay_daily = advance(create('shopping-replay', source), 'shopping-replay', source)
    assert replay_daily == daily
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
    (tmp_path/'shopping-observations.json').write_text(json.dumps(daily, indent=2, sort_keys=True)+'\n')

"""Company opportunities follow current control and comparable currencies."""
import asyncio
from contextlib import closing
import hashlib
import json
from pathlib import Path

import pytest

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


SETTINGS = {'minimum_merger_age_ticks': 0, 'maximum_merger_cash_share_bps': 4000,
            'merger_premium_bps': 1000}


def companies(create, *, foreign=False, departure=False):
    world = create([proposal(actor='agent:24')] if departure else [], config_overrides=RUNTIME_CONFIG)
    e = world.economy
    # Declared component firms, with capital transferred from existing wallets.
    buyer = e.firms.found_firm(0, 25, 'Local buyer', 'technology', opening_capital_cents=200_000)
    target = e.firms.found_firm(0, 24, 'Local target', 'technology', opening_capital_cents=50_000)
    overseas = (e.firms.found_firm(0, 27, 'Foreign company', 'technology', opening_capital_cents=300_000)
                if foreign else None)
    assert e.firms.get(buyer)['currency_code'] == e.firms.get(target)['currency_code'] == 'NSD'
    if foreign:
        assert e.firms.get(overseas)['currency_code'] == 'IVC'
    return world, buyer, target, overseas


def inherited_target(world, target):
    # Explicit component inheritance relationship; the estate itself settles.
    world.store.execute('DELETE FROM social_ties WHERE agent_a=24 OR agent_b=24')
    world.store.insert('social_ties', agent_a=24, agent_b=23, weight=1)
    world.economy.lifecycle.settle_death(1, 24)
    assert world.economy.business_control.operator_at(target) == 23
    assert world.economy.exchange.shares_held(target, 'agent', 23) == 1000
    assert world.economy.exchange.shares_held(target, 'agent', 24) == 0


def suggestion(world, buyer, tick=1, *, legacy=False):
    builder = ContextBuilder(world.economy, world.runtime.mem, world.config)
    if legacy:
        builder.engine_semantics_version = 20
    before = contents(world.store)
    result = builder._autonomous_merger_action(world.economy.firms.get(buyer), tick, SETTINGS)
    assert contents(world.store) == before
    return result


@pytest.mark.parametrize('foreign', [False, True])
def test_current_successor_can_receive_and_settle_a_suggested_merger(scenario_world, foreign):
    world, buyer, target, _ = companies(scenario_world, foreign=foreign)
    inherited_target(world, target)
    action = suggestion(world, buyer)
    assert action is not None and action['target_firm_id'] == target
    assert action['price_cents'] == 55_000 and action['currency_code'] == 'NSD'
    e = world.economy
    source = e.firms.get(buyer)['account_id']
    recipient = e.ledger.agent_checking_id(23)
    cash = e.ledger.balance(source), e.ledger.balance(recipient)
    merger = e.startups.propose_merger(1, 25, action)
    assert merger['ok'], merger
    assert not e.startups.approve_merger(1, 24, merger['merger_id'])['ok']
    assert e.startups.approve_merger(1, 23, merger['merger_id'])['ok']
    regulator = world.store.scalar("SELECT id FROM agents WHERE role='competition_regulator' AND alive=1")
    review = e.startups.review_merger(1, regulator, merger['merger_id'],
                                     {'type': 'interoperability', 'duration_ticks': 180})
    assert review['ok'] and review['outcome'] in {'approved', 'approved_with_remedy'}, review
    settled = e.startups.close_merger(1, 25, merger['merger_id'])
    assert settled['ok'], settled
    assert e.ledger.balance(source) == cash[0] - 55_000
    assert e.ledger.balance(recipient) == cash[1] + 55_000
    assert e.firms.get(target)['founder_agent_id'] == 24
    assert e.firms.get(target)['status'] == 'acquired'
    assert e.ledger.reconcile()[0]


def test_foreign_nominal_cash_does_not_block_a_local_currency_opportunity(scenario_world):
    world, buyer, target, foreign = companies(scenario_world, foreign=True)
    assert world.economy.ledger.balance(world.economy.firms.get(foreign)['account_id']) > 200_000
    action = suggestion(world, buyer)
    assert action is not None and action['target_firm_id'] == target
    assert action['currency_code'] == 'NSD'


def test_a_target_without_current_local_control_is_not_suggested(scenario_world):
    world, buyer, target, _ = companies(scenario_world, departure=True)
    for _ in range(2):
        asyncio.run(world.step())
    assert not world.economy.population.is_local(24, 2)
    assert world.economy.business_control.operator_at(target) is None
    assert suggestion(world, buyer, 3) is None


def test_missing_target_controller_history_rejects_the_read_without_effects(scenario_world):
    world, buyer, target, _ = companies(scenario_world)
    corrupt_origin(world, 24)
    before = contents(world.store)
    with pytest.raises(ResidenceError):
        suggestion(world, buyer)
    assert contents(world.store) == before


@pytest.mark.parametrize('state', ['inherited', 'foreign', 'outside'])
def test_legacy_component_retains_its_original_merger_selection(scenario_world, state):
    world, buyer, target, _ = companies(scenario_world, foreign=state == 'foreign', departure=state == 'outside')
    if state == 'inherited':
        inherited_target(world, target)
    if state == 'outside':
        for _ in range(2):
            asyncio.run(world.step())
    # Actual older-world tests separately verify historical execution/replay.
    result = suggestion(world, buyer, 3 if state == 'outside' else 1, legacy=True)
    assert (result is not None) is (state == 'outside')
    if result is not None:
        assert result['target_firm_id'] == target


def test_unavailable_cheapest_target_does_not_hide_an_available_company(scenario_world):
    world, buyer, unavailable, _ = companies(scenario_world, departure=True)
    other = world.economy.firms.found_firm(0, 23, 'Available target', 'technology', opening_capital_cents=60_000)
    for _ in range(2):
        asyncio.run(world.step())
    assert world.economy.business_control.operator_at(unavailable) is None
    action = suggestion(world, buyer, 3)
    assert action is not None and action['target_firm_id'] == other


def test_unavailable_richer_company_does_not_block_current_operators(scenario_world):
    world = scenario_world([proposal(actor='agent:24')], config_overrides=RUNTIME_CONFIG)
    e = world.economy
    absent = e.firms.found_firm(0, 24, 'Absent leader', 'technology', opening_capital_cents=300_000)
    buyer = e.firms.found_firm(0, 25, 'Available buyer', 'technology', opening_capital_cents=200_000)
    target = e.firms.found_firm(0, 23, 'Available target', 'technology', opening_capital_cents=50_000)
    for _ in range(2):
        asyncio.run(world.step())
    assert e.business_control.operator_at(absent) is None
    action = suggestion(world, buyer, 3)
    assert action is not None and action['target_firm_id'] == target


def test_outside_owner_receives_merger_cash_and_returns_through_city_replay(scenario_world, tmp_path):
    entries = [proposal(actor='agent:24'),
               proposal('back', tick=6, due=8, actor='agent:24', cause='return')]
    config = {**CITY_CONFIG, 'entrepreneurship': {
        'enabled': True, 'activation_tick': 3, 'new_arrivals_only': True,
        'autonomous_preseed': False, 'autonomous_mergers': True, **SETTINGS}}

    def create(name, source=None):
        fresh = not (tmp_path/f'{name}.db').exists()
        world = scenario_world(entries, name, replay_source=source, config_overrides=config)
        e, store = world.economy, world.store
        buyer = 3
        if fresh:
            # Declared genesis companies and ownership, created through engine
            # capital transfers/share accounting. Later decisions are recorded.
            target = e.firms.found_firm(0, 24, 'Continuing manufacturing target', 'manufacturing',
                                       opening_capital_cents=50_000)
            e.exchange._adjust_shares(target, 'agent', 24, -1)
            e.exchange._adjust_shares(target, 'agent', 23, 1)
            capital = e.ledger.balance(e.firms.get(buyer)['account_id']) + 100_000
            foreign = e.firms.found_firm(0, 42, 'Foreign manufacturing company', 'manufacturing',
                                        opening_capital_cents=capital)
            assert e.firms.get(foreign)['currency_code'] == 'IVC'
            for actor in (23, 24, 25, 42):
                store.update('agents', actor, population_tier='core', pinned_core=1,
                    cadence_json='{"act":1,"portfolio":9999,"career":9999,"news":9999}')
            store.log_event(0, 'declared_merger_opportunity_cohort', {
                'acquirer_id': buyer, 'target_id': target, 'foreign_firm_id': foreign,
                'target_founder_id': 24, 'resident_shareholder_id': 23,
                'foreign_opening_capital_cents': capital, 'source_share_units': [999, 1],
                'proposal_day': 3, 'approval_day': 4, 'review_day': 5, 'close_day': 6}, phase='GENESIS')
            store.commit()
        target = store.scalar("SELECT id FROM firms WHERE name='Continuing manufacturing target'")
        foreign = store.scalar("SELECT id FROM firms WHERE name='Foreign manufacturing company'")
        regulator = store.scalar("SELECT id FROM agents WHERE role='competition_regulator' AND alive=1")
        for purpose in ('decision', 'founder', 'competition_regulator'):
            original = world.gateway.scripted.policies[purpose]
            def decisions(context, original=original):
                if source is not None:
                    raise AssertionError('replay must consume recorded merger decisions')
                actor, tick = context.get('agent', {}).get('id'), context.get('tick')
                if actor not in {23, 24, 25, 42, regulator}:
                    return original(context)
                expected = {(25, 3): 'propose_merger', (23, 4): 'approve_merger',
                            (regulator, 5): 'review_merger', (25, 6): 'close_merger'}.get((actor, tick))
                field = 'institutional_work' if actor == regulator else 'startup_work'
                choices = context.get(field, {}).get('eligible_actions', [])
                action = next((item for item in choices if item['type'] == expected), {'type': 'do_nothing'})
                if expected:
                    assert action['type'] == expected, (actor, tick, context.get(field))
                if expected == 'propose_merger':
                    assert action['acquirer_firm_id'] == buyer and action['target_firm_id'] == target
                    assert e.ledger.balance(e.firms.get(foreign)['account_id']) > e.ledger.balance(e.firms.get(buyer)['account_id'])
                return {'actions': [action], 'reasoning': 'Declared current-control merger workflow.'}
            world.gateway.scripted.policies[purpose] = decisions
        return world

    def advance(world, name, source=None):
        for day in range(1, 9):
            if day in (4, 6):
                paused = asyncio.run(world.step(pause_after_phase='MORNING' if day == 4 else 'EXECUTION'))
                assert paused['active_tick'] == day
                scenario_world.close(world)
                world = create(name, source)
            asyncio.run(world.step())
            assert world.store.tick == day, dict(world.store.get_meta())
            assert world.economy.ledger.reconcile()[0]
            assert world.economy.population.is_local(24, day) is (day < 2 or day >= 8)
            if 2 <= day <= 7:
                assert world.store.scalar('SELECT COUNT(*) FROM llm_calls WHERE agent_id=24 AND tick=?', (day,)) == 0
            if 2 <= day <= 5:
                target = world.store.scalar("SELECT id FROM firms WHERE name='Continuing manufacturing target'")
                assert world.economy.business_control.operator_at(target) == 23
        return world

    world = create('merger-source')
    accounts = [tuple(row) for row in world.store.query(
        'SELECT id,checking_account_id,savings_account_id FROM agents WHERE id IN (23,24,25,42) ORDER BY id')]
    world = advance(world, 'merger-source')
    store = world.store
    assert [tuple(row) for row in store.query('SELECT id,checking_account_id,savings_account_id '
        'FROM agents WHERE id IN (23,24,25,42) ORDER BY id')] == accounts
    assert store.scalar('SELECT COUNT(*) FROM agents') == 47
    deal = store.query_one('SELECT * FROM mergers')
    assert store.scalar('SELECT COUNT(*) FROM mergers') == 1
    assert deal['status'] == 'closed' and deal['closed_tick'] == 6 and deal['currency_code'] == 'NSD'
    assert store.scalar('SELECT founder_agent_id FROM firms WHERE id=?', (deal['target_firm_id'],)) == 24
    assert store.scalar('SELECT status FROM firms WHERE id=?', (deal['target_firm_id'],)) == 'acquired'
    assert store.scalar("SELECT COUNT(*) FROM action_proposals WHERE action_type IN "
        "('propose_merger','approve_merger','review_merger','close_merger') AND validation_status='accepted'") == 4
    transaction = store.scalar("SELECT id FROM transactions WHERE kind='merger_close'")
    legs = [dict(row) for row in store.query('SELECT account_id,delta_cents FROM ledger_entries WHERE txn_id=? ORDER BY id', (transaction,))]
    outside_wallet = dict((row[0], row[1]) for row in accounts)[24]
    successor_wallet = dict((row[0], row[1]) for row in accounts)[23]
    assert sum(row['delta_cents'] for row in legs) == 0
    credits = {row['account_id']: row['delta_cents'] for row in legs if row['delta_cents'] > 0}
    assert credits[outside_wallet] == deal['price_cents'] * 999 // 1000
    assert credits[successor_wallet] == deal['price_cents'] - credits[outside_wallet]
    assert store.scalar('SELECT returns FROM population_resident_census WHERE tick=8') == 1
    source = Path(store.path)
    scenario_world.close(world)
    stamp = hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns
    replay = advance(create('merger-replay', source), 'merger-replay', source)
    target_path = Path(replay.store.path)
    scenario_world.close(replay)
    with closing(open_read_only_connection(source, require_closed=True)) as src, \
            closing(open_read_only_connection(target_path, require_closed=True)) as dst:
        proof = verify_replay_connections(src, dst)
        assert proof['exact'], proof['differences']
        for database, directory in ((src, 'source-export'), (dst, 'replay-export')):
            manifest = validate_bundle(export_bundle(database, tmp_path/directory), database=database)
            assert manifest['contract_id'] == 'hash-contract-v8'
            assert database.execute('SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls').fetchone()[0] == 0
            assert database.execute("SELECT COUNT(*) FROM llm_calls WHERE provider<>'scripted'").fetchone()[0] == 0
    assert (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns) == stamp
    assert not any(Path(str(source)+suffix).exists() for suffix in ('-wal', '-shm', '-journal'))
    (tmp_path/'merger-observations.json').write_text(json.dumps({'price_cents': deal['price_cents'],
        'currency': deal['currency_code'], 'closed_tick': deal['closed_tick'], 'ledger_legs': legs}, indent=2)+'\n')


def paused_startup_morning(create):
    config = {**RUNTIME_CONFIG, 'entrepreneurship': {
        'enabled': True, 'activation_tick': 1, 'new_arrivals_only': True,
        'autonomous_preseed': False, 'autonomous_mergers': True, **SETTINGS}}
    world = create([], config_overrides=config)
    world.economy.firms.found_firm(0, 24, 'Queued target', 'manufacturing', opening_capital_cents=50_000)
    world.store.update('agents', 25, population_tier='core', pinned_core=1, cadence_json='{"act":1}')
    paused = asyncio.run(world.step(pause_after_phase='MORNING'))
    assert paused['active_tick'] == 1 and paused['phase'] == 'EXECUTION'
    state = json.loads(world.store.get_meta()['phase_state_json'])
    assert any(entry['actor_id'] == 25 for entry in state['startup_authorizations']['actors'])
    return world, config, state


@pytest.mark.parametrize('corruption', ['missing', 'version', 'tick', 'checksum', 'duplicate_actor', 'action_type'])
def test_corrupt_saved_startup_menu_fails_before_any_execution(scenario_world, corruption):
    world, config, state = paused_startup_morning(scenario_world)
    frame = state['startup_authorizations']
    if corruption == 'missing':
        del state['startup_authorizations']
    elif corruption == 'checksum':
        frame['sha256'] = '0' * 64
    else:
        if corruption == 'version':
            frame['version'] = 2
        elif corruption == 'tick':
            frame['tick'] = 2
        elif corruption == 'duplicate_actor':
            frame['actors'].append(frame['actors'][0])
        else:
            del frame['actors'][0]['actions'][0]['type']
        # A matching checksum alone cannot legitimize an invalid typed frame.
        body = {key: frame[key] for key in ('version', 'tick', 'actors')}
        frame['sha256'] = hashlib.sha256(json.dumps(body, sort_keys=True,
            separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    world.store.set_meta(phase_state_json=json.dumps(state))
    world.store.commit()
    scenario_world.close(world)
    world = scenario_world([], config_overrides=config)
    before = contents(world.store)
    cache = getattr(world.economy, '_startup_action_authorizations', {})
    with pytest.raises(ValueError, match='invalid saved startup authorizations'):
        asyncio.run(world.step())
    after = contents(world.store)
    assert {key: value for key, value in after.items() if key != 'run_meta'} == {
        key: value for key, value in before.items() if key != 'run_meta'}
    assert getattr(world.economy, '_startup_action_authorizations', {}) == cache


def test_restored_menu_still_rejects_a_changed_merger_price(scenario_world):
    world, config, state = paused_startup_morning(scenario_world)
    decision = next(row for row in state['decisions'] if row['agent_id'] == 25)
    action = next(item for item in decision['envelope']['actions'] if item['type'] == 'propose_merger')
    action['price_cents'] += 1
    world.store.set_meta(phase_state_json=json.dumps(state))
    world.store.commit()
    scenario_world.close(world)
    world = scenario_world([], config_overrides=config)
    asyncio.run(world.step())
    assert world.store.tick == 1
    rejected = world.store.query_one("SELECT validation_status,result_json FROM action_proposals "
        "WHERE actor_id=25 AND action_type='propose_merger'")
    assert rejected['validation_status'] == 'rejected'
    assert json.loads(rejected['result_json']) == {
        'ok': False, 'reason': 'startup action must copy a current supplied action exactly'}
    assert world.store.scalar('SELECT COUNT(*) FROM mergers') == 0
    assert world.store.scalar("SELECT COUNT(*) FROM transactions WHERE kind='merger_close'") == 0
    assert world.economy.ledger.reconcile()[0]

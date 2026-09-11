"""Local startup authority and information delivery across actual departure."""
import asyncio
from contextlib import closing
import hashlib
import json
from pathlib import Path

import pytest

from engine.population_history import ResidenceError
from engine.store import open_read_only_connection
from research.export_bundle import export_bundle, validate_bundle
from research.hashing import canonical_hashes
from world.shocks import Shocks
from world.replay_verify import verify_replay_connections

from .test_population_movements import moving, advance, propose
from .test_population_residence_history import residence_case, contents
from .test_semantics20_estate_cases import estate_case
from .test_population_scenario import scenario_world, proposal


def startup_command(c, name):
    e = c.e
    firm = e.firms.found_firm(0, c.heir, 'Local company', 'tech', shares=100)
    e.store.update('agents', c.person, role='vc_partner', occupation='venture capitalist')
    e.store.update('agents', c.heir, role='lawyer', occupation='lawyer')
    offer = {'firm_id': firm, 'instrument_type': 'preferred_equity',
             'amount_cents': 20, 'equity_bps': 2000}
    sheet = e.startups.propose_term_sheet(0, c.person, offer)
    assert sheet['ok'], sheet
    if name == 'close_funding_round':
        assert e.startups.accept_term_sheet(0, c.heir, sheet['term_sheet_id'])['ok']
        assert e.startups.run_due_diligence(0, c.heir, sheet['term_sheet_id'])['ok']
    if name in {'run_due_diligence', 'register_ip'}:
        e.store.update('agents', c.person, role='lawyer', occupation='lawyer')
    if name == 'review_merger':
        acquirer = e.firms.found_firm(0, c.heir, 'Local acquirer', 'tech', shares=100)
        merger = e.startups.propose_merger(0, c.heir,
            {'acquirer_firm_id': acquirer, 'target_firm_id': firm, 'price_cents': 1})
        assert merger['ok'], merger
        assert e.startups.approve_merger(0, c.heir, merger['merger_id'])['ok']
        e.store.update('agents', c.person, role='competition_regulator', occupation='regulator')
        return lambda day: e.startups.review_merger(day, c.person, merger['merger_id'])
    if name == 'propose_term_sheet':
        return lambda day: e.startups.propose_term_sheet(day, c.person, offer)
    if name == 'register_ip':
        return lambda day: e.startups.register_ip(day, c.person,
            {'firm_id': firm, 'asset_type': 'patent_like', 'title': 'Local invention'})
    return lambda day: getattr(e.startups, name)(day, c.person, sheet['term_sheet_id'])


@pytest.mark.parametrize('operation', [
    'propose_term_sheet', 'accept_term_sheet', 'close_funding_round',
    'run_due_diligence', 'register_ip', 'review_merger'])
def test_departed_actor_cannot_use_startup_service(moving, operation):
    c = moving
    command = startup_command(c, operation)
    movement = propose(c)
    advance(c, 1)
    assert c.e.population.settle(1, movement)['status'] == 'applied'
    assert c.e.population.is_available(c.person) is False
    before = contents(c.e.store)
    result = command(1)
    assert result['ok'] is False, result
    assert contents(c.e.store) == before
    returned = propose(c, tick=1, due=2, key='back', cause='return', destination=1)
    advance(c, 2)
    assert c.e.population.settle(2, returned)['status'] == 'applied'
    # Retained contracts/qualifications can be used on return. A vacated VC or
    # regulatory role does not return with residence.
    result = command(2)
    assert result['ok'] is (operation not in {'propose_term_sheet', 'review_merger'}), result
    assert c.e.ledger.reconcile()[0]


def test_startup_service_validates_history_before_any_effect(moving, monkeypatch):
    c = moving
    command = startup_command(c, 'close_funding_round')
    before = contents(c.e.store)
    def missing_history(actor):
        raise ResidenceError('missing residence history')
    monkeypatch.setattr(c.e.population, 'is_available', missing_history)
    with pytest.raises(ResidenceError, match='missing residence'):
        command(1)
    assert contents(c.e.store) == before


def test_rumor_with_only_outside_depositors_has_an_empty_local_audience(moving):
    c = moving
    movement = propose(c)
    advance(c, 1)
    c.e.population.settle(1, movement)
    params = {'bank_id': c.bank, 'audience': 'current_depositors', 'n_agents': 100}
    shocks = Shocks(c.e, c.e.config)
    identity = shocks.schedule('rumor', 'shock', {'tick': 1}, params=params, label='Empty local audience')
    declaration = c.e.store.query_one('SELECT * FROM shocks WHERE id=?', (identity,))
    before = contents(c.e.store)
    shocks._apply_rumor(1, declaration, params, True)
    assert params['target_agent_ids'] == []
    assert contents(c.e.store)['memories'] == before['memories']
    payload = json.loads(c.e.store.query_one("SELECT payload_json FROM events WHERE kind='rumor'")[0])
    assert payload['n_agents'] == 0 and payload['population_scope'] == 'resident_citizens'
    assert c.e.ledger.reconcile()[0]


def test_rumor_checks_all_residence_references_before_delivery(moving, monkeypatch):
    c = moving
    original = c.e.population.is_available
    def missing_later_history(actor):
        if actor == c.heir:
            raise ResidenceError('missing later residence history')
        return original(actor)
    monkeypatch.setattr(c.e.population, 'is_available', missing_later_history)
    params = {'bank_id': c.bank, 'audience': 'all_citizens', 'n_agents': 100}
    shocks = Shocks(c.e, c.e.config)
    identity = shocks.schedule('rumor', 'shock', {'tick': 1}, params=params, label='Invalid local audience')
    declaration = c.e.store.query_one('SELECT * FROM shocks WHERE id=?', (identity,))
    before = contents(c.e.store)
    with pytest.raises(ResidenceError, match='missing later residence'):
        shocks._apply_rumor(1, declaration, params, True)
    assert contents(c.e.store) == before


def test_world_local_information_and_returning_investor_restart_replay_export(scenario_world, tmp_path):
    entries = [proposal(), proposal('back', tick=3, due=5, cause='return')]
    def create(name, source=None):
        fresh = not (tmp_path/f'{name}.db').exists()
        world = scenario_world(entries, name, replay_source=source)
        if fresh:
            # Identical declared genesis business/contract in source and replay;
            # this fixture is not evidence of endogenous company formation.
            e = world.economy
            firm = e.firms.found_firm(0, 24, 'Declared investment', 'tech', shares=100)
            e.store.update('agents', 23, role='vc_partner', occupation='venture capitalist')
            e.store.update('agents', 24, role='lawyer', occupation='lawyer')
            sheet = e.startups.propose_term_sheet(0, 23, {'firm_id': firm,
                'instrument_type': 'preferred_equity', 'amount_cents': 20, 'equity_bps': 2000})
            assert sheet['ok'], sheet
            assert e.startups.accept_term_sheet(0, 24, sheet['term_sheet_id'])['ok']
            assert e.startups.run_due_diligence(0, 24, sheet['term_sheet_id'])['ok']
            account = world.store.query_one('SELECT ac.bank_id,ac.balance_cents FROM agents a '
                'JOIN accounts ac ON ac.id=a.checking_account_id WHERE a.id=23')
            assert account['balance_cents'] > 0
            for day in (3, 5):
                for audience in ('all_citizens', 'current_depositors'):
                    world.shocks.schedule('rumor', 'shock', {'tick': day}, params={
                        'bank_id': account['bank_id'], 'audience': audience, 'n_agents': 10000,
                        'text': 'Declared local information delivery'}, label=f'local-{day}-{audience}')
        sheet_id = world.store.scalar("SELECT t.id FROM term_sheets t JOIN firms f ON f.id=t.firm_id WHERE f.name='Declared investment'")
        # Exercise normal proposal recording, validation and execution. The
        # participant UI does not offer this action after a VC role is vacated.
        for purpose, original in list(world.gateway.scripted.policies.items()):
            def scenario(context, original=original):
                if source is not None:
                    raise AssertionError('replay must consume recorded responses')
                if context.get('agent', {}).get('id') == 23 and context.get('tick') == 6:
                    return {'reasoning': 'Declared retained investment after return',
                            'actions': [{'type': 'close_funding_round', 'term_sheet_id': sheet_id}]}
                return original(context)
            world.gateway.scripted.register(purpose, scenario)
        return world

    world = create('startup-rumor-source')
    sheet = world.store.scalar("SELECT t.id FROM term_sheets t JOIN firms f ON f.id=t.firm_id WHERE f.name='Declared investment'")
    for day in range(1, 7):
        if day == 4:
            asyncio.run(world.step(pause_after_phase='NIGHT_CLOSE'))
            scenario_world.close(world)
            world = create('startup-rumor-source')
        asyncio.run(world.step())
        if day in (3, 5):
            events = world.store.query("SELECT payload_json FROM events WHERE kind='rumor' AND tick=? ORDER BY id", (day,))
            assert len(events) == 2
            for row in events:
                event = json.loads(row['payload_json'])
                assert event['population_scope'] == 'resident_citizens'
                assert event['target_agent_ids']
                assert (23 in event['target_agent_ids']) is (day == 5), event
            if day == 3:
                before = contents(world.store)
                assert world.economy.startups.close_funding_round(3, 23, sheet)['ok'] is False
                assert contents(world.store) == before
                assert world.store.scalar('SELECT COUNT(*) FROM memories WHERE agent_id=23 AND tick=3 '
                    'AND text=?', ('Declared local information delivery',)) == 0
        assert world.economy.ledger.reconcile()[0]
    assert world.store.scalar('SELECT status FROM term_sheets WHERE id=?', (sheet,)) == 'closed'
    assert world.store.scalar('SELECT COUNT(*) FROM funding_rounds WHERE term_sheet_id=?', (sheet,)) == 1
    source = Path(world.store.path)
    scenario_world.close(world)
    stamp = hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns
    replay = create('startup-rumor-replay', source)
    for day in range(1, 7):
        if day == 4:
            asyncio.run(replay.step(pause_after_phase='NIGHT_CLOSE'))
            scenario_world.close(replay)
            replay = create('startup-rumor-replay', source)
        asyncio.run(replay.step())
        assert replay.economy.ledger.reconcile()[0]
    replay_path = Path(replay.store.path)
    scenario_world.close(replay)
    with closing(open_read_only_connection(source, require_closed=True)) as src, \
            closing(open_read_only_connection(replay_path, require_closed=True)) as dst:
        proof = verify_replay_connections(src, dst)
        assert proof['exact'], proof['differences']
        first, second = canonical_hashes(src), canonical_hashes(dst)
        for table in ('events', 'memories', 'shocks', 'term_sheets', 'funding_rounds',
                      'due_diligence_checks', 'shares', 'accounts', 'ledger_entries'):
            assert first['tables'][table] == second['tables'][table], table
        bundle = export_bundle(src, tmp_path/'source-export')
        assert validate_bundle(bundle, database=src)['contract_id'] == 'hash-contract-v8'
        assert src.execute('SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls').fetchone()[0] == 0
    assert (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns) == stamp
    assert not any(Path(str(source)+suffix).exists() for suffix in ('-wal', '-shm', '-journal'))

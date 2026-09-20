"""Offline catalog/executor agreement; never uses the prepared live world."""
import copy

import pytest
from agents.memory import Memory
from agents.participant import ParticipantError, ParticipantService
from agents.prompts import ContextBuilder
from engine.actions import ActionExecutor
from .conftest import make_agent
from .test_native_entrepreneurship import _economy, _citizen


def setup_catalog(store, **settings):
    economy, config, bank = _economy(store, **settings)
    actor, _ = _citizen(economy, bank)
    lawyer, _ = make_agent(economy, bank, name="Counsel", occupation="lawyer", role="lawyer")
    store.set_meta(tick=10)
    builder = ContextBuilder(economy, Memory(store, config), config)
    return economy, ParticipantService(store, builder, config), actor, lawyer


def founding(service, actor):
    return next(item for item in service.action_catalog(actor) if item['type']=='found_company')


def test_missing_opportunity_disabled_and_manual_execution_rejected(store):
    economy, service, actor, lawyer = setup_catalog(store)
    store.update('agents', actor, risk_tolerance=0.1)
    item=founding(service,actor)
    assert not item['enabled'] and not item['available']
    assert 'supplied entrepreneurship opportunity' in item['disabled_reason']
    action=dict(type='found_company',name='Invented',sector='services',lawyer_agent_id=lawyer,opening_capital=0)
    with pytest.raises(ParticipantError,match='supplied entrepreneurship opportunity'):
        service.normalize_action(actor,action)
    result=ActionExecutor(economy).execute_action(11,actor,action)
    assert not result['ok'] and result['reason']==item['disabled_reason']
    assert store.scalar('SELECT COUNT(*) FROM firms')==0


def test_current_opportunity_exact_payload_and_execution_agree(store):
    economy,service,actor,_=setup_catalog(store)
    changes=store.conn.total_changes
    item=founding(service,actor)
    assert item['available'] and item['enabled']
    assert store.conn.total_changes==changes
    action=service.normalize_action(actor,item['action'])
    assert ActionExecutor(economy).founding_prerequisite_error(11,actor,action) is None
    with pytest.raises(ParticipantError,match='stale or unavailable'):
        service.normalize_action(actor,{**action,'opening_capital':0})
    result=ActionExecutor(economy).execute_action(11,actor,action)
    assert result['ok']
    assert not founding(service,actor)['available']


@pytest.mark.parametrize('invalid', ['dead','wrong_occupation'])
def test_invalid_lawyer_not_executable(store, invalid):
    economy,service,actor,lawyer=setup_catalog(store)
    action=service.normalize_action(actor,founding(service,actor)['action'])
    store.update('agents',lawyer,**({'alive':0} if invalid=='dead' else {'occupation':'teacher'}))
    assert not founding(service,actor)['available']
    result=ActionExecutor(economy).execute_action(11,actor,action)
    assert not result['ok'] and 'living lawyer' in result['reason']


def test_stale_opportunity_not_advertised(store):
    economy,service,actor,_=setup_catalog(store)
    assert founding(service,actor)['available']
    cached=copy.deepcopy(economy._entrepreneurship_authorizations)
    store.set_meta(tick=11)
    assert not founding(service,actor)['available']
    assert economy._entrepreneurship_authorizations==cached


def test_zero_capital_rule_and_unrelated_catalog_unchanged(store):
    economy,service,actor,lawyer=setup_catalog(store,enabled=False)
    before=service.action_catalog(actor)
    item=next(i for i in before if i['type']=='found_company')
    assert item['enabled']
    action=service.normalize_action(actor,dict(type='found_company',name='Zero',sector='services',lawyer_agent_id=lawyer,opening_capital=0))
    economy.config['entrepreneurship']['enabled']=True
    economy._entrepreneurship_authorizations={(11,actor):action}
    assert ActionExecutor(economy).founding_prerequisite_error(11,actor,action) is None
    after=service.action_catalog(actor)
    assert [i for i in before if i['type']!='found_company']==[i for i in after if i['type']!='found_company']
    # Rebind the intentionally zero-capital fixture after context generation.
    economy._entrepreneurship_authorizations[(11,actor)]=action
    assert ActionExecutor(economy).execute_action(11,actor,action)['ok']

@pytest.mark.parametrize('condition,reason', [
    ('lawyer', 'living lawyer'),
    ('capital', 'insufficient opening capital'),
    ('consumed', 'already controls'),
])
def test_stale_context_rechecked_with_shared_engine_prerequisites(store, monkeypatch, condition, reason):
    economy, service, actor, lawyer = setup_catalog(store)
    row = store.query_one('SELECT * FROM agents WHERE id=?', (actor,))
    context = service.ctx.build(row, 11, read_only=True)
    action = context['entrepreneurship_opportunity']['action']
    if condition == 'lawyer':
        store.update('agents', lawyer, alive=0)
    elif condition == 'capital':
        store.execute('UPDATE accounts SET balance_cents=0 WHERE id=?', (row['checking_account_id'],))
    else:
        assert ActionExecutor(economy).execute_action(11, actor, action)['ok']
    monkeypatch.setattr(service.ctx, 'build', lambda *args, **kwargs: context)
    descriptor = founding(service, actor)
    assert not descriptor['available']
    assert reason in descriptor['disabled_reason']
    result = ActionExecutor(economy).execute_action(11, actor, action)
    assert not result['ok'] and result['reason'] == descriptor['disabled_reason']


def test_mcp_legal_action_list_reports_missing_opportunity(tmp_path):
    from fastapi.testclient import TestClient
    from server.app import create_app
    from .test_external_agent_gateway import _world, _connection
    world = _world(tmp_path)
    try:
        world.config['entrepreneurship'] = {'enabled': True}
        created = _connection(world)
        actor = world.store.scalar('SELECT actor_id FROM external_agent_connections WHERE id=?', (created['connection']['id'],))
        world.store.update('agents', actor, risk_tolerance=0.1)
        headers = {'Authorization': 'Bearer ' + created['credential']['token']}
        with TestClient(create_app(world)) as client:
            result = client.post('/mcp', headers=headers, json={
                'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                'params': {'name': 'ae_actions_list', 'arguments': {}},
            })
            assert result.status_code == 200
            actions = result.json()['result']['structuredContent']['actions']
            item = next(a for a in actions if a['type'] == 'found_company')
            assert item['enabled'] is False and item['available'] is False
            assert 'supplied entrepreneurship opportunity' in item['disabled_reason']
    finally:
        world.close()

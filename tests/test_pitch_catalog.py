"""Offline pitch catalog/engine contract tests; no external providers."""
import copy
import pytest
from agents.participant import ParticipantError
from engine.actions import ActionExecutor
from .test_founding_catalog import setup_catalog


def setup_pitch(store, *, enabled=True):
    economy, service, actor, lawyer = setup_catalog(store)
    economy.config['entrepreneurship']['enabled'] = enabled
    firm = economy.firms.found_firm(10, actor, 'Test Startup', 'services', product={
        'product': 'service', 'unit_price_cents': 500,
        'business_idea': {'mission': 'Serve customers', 'offering': 'Service', 'customer_problem': 'Need'}})
    return economy, service, actor, firm


def pitches(service, actor):
    return [a for a in service.action_catalog(actor) if a['type']=='pitch_vc']


def test_no_opportunity_and_manual_bypass(store):
    economy, service, actor, firm = setup_pitch(store)
    economy.config['entrepreneurship']['autonomous_preseed'] = False
    item = pitches(service, actor)[0]
    assert not item['enabled'] and not item['available']
    action = {'type':'pitch_vc','firm_id':firm,'ask':250000,'summary':'Invented'}
    with pytest.raises(ParticipantError, match='current supplied action'):
        service.normalize_action(actor, action)
    result = ActionExecutor(economy).execute_action(11, actor, action)
    assert not result['ok'] and result['reason']==item['disabled_reason']
    assert store.scalar('SELECT COUNT(*) FROM pitches')==0


def test_exact_opportunity_shared_eligibility_and_consumption(store):
    economy, service, actor, firm = setup_pitch(store)
    changes = store.conn.total_changes
    items = pitches(service, actor)
    assert len(items)==1 and items[0]['available']
    assert store.conn.total_changes == changes
    action = service.normalize_action(actor, items[0]['action'])
    executor = ActionExecutor(economy)
    assert executor.pitch_prerequisite_error(11,actor,action) is None
    result = executor.execute_action(11,actor,action)
    assert result['ok']
    assert all(not i['available'] for i in pitches(service,actor))
    assert not executor.execute_action(11,actor,action)['ok']
    assert store.scalar('SELECT COUNT(*) FROM pitches')==1


@pytest.mark.parametrize('field,value', [('firm_id',999),('ask',1),('summary','Changed')])
def test_bound_terms_cannot_be_changed(store,field,value):
    economy,service,actor,_ = setup_pitch(store)
    action = pitches(service,actor)[0]['action']
    changed = {**action,field:value}
    with pytest.raises(ParticipantError,match='stale or unavailable'):
        service.normalize_action(actor,changed)
    result = ActionExecutor(economy).execute_action(11,actor,{k:v for k,v in changed.items() if k!='variant'})
    assert not result['ok'] and 'current supplied action' in result['reason']


@pytest.mark.parametrize('condition', ['wrong_actor','lost_control','listed','pending','bad_ask'])
def test_precomputed_state_and_executor_agree(store,monkeypatch,condition):
    economy,service,actor,firm = setup_pitch(store)
    row=store.query_one('SELECT * FROM agents WHERE id=?',(actor,))
    context=service.ctx.build(row,11,read_only=True)
    action=context['startup_work']['eligible_actions'][0]
    if condition=='wrong_actor':
        economy._startup_action_authorizations={(11,actor+999):[action]}
    elif condition=='lost_control':
        store.update('firms',firm,founder_agent_id=actor+999)
    elif condition=='listed':
        store.update('firms',firm,status='listed')
    elif condition=='pending':
        assert ActionExecutor(economy).execute_action(11,actor,action)['ok']
    else:
        action['ask']=0
        economy._startup_action_authorizations[(11,actor)]=[copy.deepcopy(action)]
    monkeypatch.setattr(service.ctx,'build',lambda *args,**kwargs:context)
    item=pitches(service,actor)[0]
    assert not item['available']
    result=ActionExecutor(economy).execute_action(11,actor,action)
    assert not result['ok'] and result['reason']==item['disabled_reason']


def test_stale_authority_and_legacy_catalog_preserved(store,monkeypatch):
    economy,service,actor,_=setup_pitch(store,enabled=False)
    legacy=service.action_catalog(actor)
    assert next(i for i in legacy if i['type']=='pitch_vc')['enabled']
    economy.config['entrepreneurship']['enabled']=True
    active=service.action_catalog(actor)
    assert [i for i in legacy if i['type'] not in {'pitch_vc','found_company'}]==[
        i for i in active if i['type'] not in {'pitch_vc','found_company'} and not i.get('variant','').startswith('startup-')]
    row=store.query_one('SELECT * FROM agents WHERE id=?',(actor,))
    context=service.ctx.build(row,11,read_only=True)
    store.set_meta(tick=11)
    monkeypatch.setattr(service.ctx,'build',lambda *args,**kwargs:context)
    assert not pitches(service,actor)[0]['available']


def test_v4_alternative_asks_all_remain_exact_and_available(store):
    economy,service,actor,_=setup_pitch(store)
    import random
    from engine.core import Economy
    from agents.participant import ParticipantService
    from agents.prompts import ContextBuilder
    from agents.memory import Memory
    from .test_jev_domains import domain_config
    config=economy.config
    config['engine_semantics_version']=16
    config['llm']=domain_config('funding')['llm']
    economy=Economy(store,config,random.Random(101),random.Random(202))
    service=ParticipantService(store,ContextBuilder(economy,Memory(store,config),config),config)
    items=pitches(service,actor)
    assert len(items)==3 and all(i['available'] for i in items)
    assert {i['action']['ask'] for i in items}=={187500,250000,312500}
    for item in items:
        action=service.normalize_action(actor,item['action'])
        assert ActionExecutor(economy).pitch_prerequisite_error(11,actor,action) is None

@pytest.mark.parametrize('has_opportunity', [False, True])
def test_mcp_pitch_availability(tmp_path, has_opportunity):
    from fastapi.testclient import TestClient
    from server.app import create_app
    from .test_external_agent_gateway import _world, _connection
    world = _world(tmp_path)
    try:
        world.config['entrepreneurship'] = {
            'enabled': True, 'autonomous_preseed': has_opportunity,
            'preseed_pitch_delay_ticks': 0,
        }
        created = _connection(world)
        actor = world.store.scalar('SELECT actor_id FROM external_agent_connections WHERE id=?',
                                   (created['connection']['id'],))
        world.economy.firms.found_firm(0, actor, 'MCP Startup', 'services', product={
            'product': 'service', 'business_idea': {'mission': 'Serve customers'}})
        with TestClient(create_app(world)) as client:
            result = client.post('/mcp', headers={
                'Authorization': 'Bearer ' + created['credential']['token']}, json={
                'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                'params': {'name': 'ae_actions_list', 'arguments': {}},
            })
            assert result.status_code == 200
            actions = result.json()['result']['structuredContent']['actions']
            items = [a for a in actions if a['type'] == 'pitch_vc']
            assert len(items) == 1
            assert items[0]['available'] == has_opportunity
            if has_opportunity:
                assert all(f['kind'] == 'hidden' for f in items[0]['fields'])
            else:
                assert 'current supplied action' in items[0]['disabled_reason']
    finally:
        world.close()

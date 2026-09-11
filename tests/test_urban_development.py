"""Authoritative construction success, rejection, escrow and history contracts."""
import pytest
from engine.store import Store
from engine.actions import ActionExecutor
from run_config import load_config
from world.loop import World
from tests.test_semantics12_civic_city import _permit_authorization

@pytest.fixture
def urban(tmp_path):
    cfg=load_config('runs/simcity.yaml');cfg['population']['target_total']=44
    cfg['checkpoint_every']=0
    store=Store(str(tmp_path/'urban.db'));store.init_run_meta('urban-test',cfg['seed'],cfg)
    world=World(store,cfg);world.initialize()
    founder,permit,ex=_permit_authorization(world)
    tick=int(permit['issued_tick'])+1
    result=ex.execute_action(tick,founder,world.economy.city.founding_opportunity(founder,tick)['action'])
    assert result['ok'],result
    firm=store.query_one('SELECT * FROM firms WHERE id=?',(result['firm_id'],))
    parcel=store.scalar("SELECT id FROM urban_parcels WHERE region_id=? AND zone_key='commercial' AND blocked=0 ORDER BY id LIMIT 1",(firm['region_id'],))
    action={'type':'construct_building','firm_id':firm['id'],'parcel_id':parcel,'template_key':'workplace','request_key':'first'}
    yield world,ex,founder,firm,tick+1,action
    store.close()

def test_escrow_cancel_idempotency_and_history(urban):
    w,ex,a,f,t,action=urban;s=w.store;u=w.economy.urban
    before=w.economy.ledger.balance(f['account_id'])
    r=ex.execute_action(t,a,action);assert r['ok'],r
    assert w.economy.ledger.balance(f['account_id'])==before-50000
    assert ex.execute_action(t,a,action)['project_id']==r['project_id']
    assert s.scalar("SELECT count(*) FROM transactions WHERE kind='construction_escrow'")==1
    assert not ex.execute_action(t,a,{**action,'parcel_id':action['parcel_id']+1})['ok']
    cancel={'type':'cancel_construction','project_id':r['project_id'],'request_key':'cancel'}
    assert ex.execute_action(t+1,a,cancel)['ok']
    assert ex.execute_action(t+2,a,cancel)['ok']
    assert w.economy.ledger.balance(f['account_id'])==before
    assert u.projection(t)['projects'][0]['status']=='building'
    assert u.projection(t+1)['projects'][0]['status']=='cancelled'
    w.economy.ledger.reconcile()

def test_completion_demolition_no_resurrection(urban):
    w,ex,a,f,t,action=urban;s=w.store;u=w.economy.urban
    r=ex.execute_action(t,a,action);assert r['ok'],r
    u.finalize(t+2);assert s.scalar('SELECT status FROM construction_projects')=='building'
    u.finalize(t+3);u.finalize(t+3)
    assert s.scalar("SELECT count(*) FROM transactions WHERE kind='construction_settlement'")==1
    place=s.scalar('SELECT place_id FROM construction_projects')
    cash=w.economy.ledger.balance(f['account_id'])
    demolition={'type':'demolish_building','project_id':r['project_id'],'request_key':'demolish'}
    assert ex.execute_action(t+4,a,demolition)['ok']
    assert ex.execute_action(t+5,a,demolition)['ok']
    w.economy.city._sync_firm_workplaces(t+5)
    assert s.scalar('SELECT active FROM places WHERE id=?',(place,))==0
    assert w.economy.ledger.balance(f['account_id'])==cash
    w.economy.ledger.reconcile()

@pytest.mark.parametrize('change',[{'cost_cents':1},{'firm_id':True},{'parcel_id':-1},{'template_key':'palace'},{'request_key':' '}])
def test_strict_rejections(urban,change):
    w,ex,a,f,t,action=urban
    cash=w.economy.ledger.balance(f['account_id'])
    assert not ex.execute_action(t,a,{**action,**change})['ok']
    assert w.store.scalar('SELECT count(*) FROM construction_projects')==0
    assert w.economy.ledger.balance(f['account_id'])==cash

@pytest.mark.parametrize('reason',['blocked','zone','authority','funds','death','bankruptcy'])
def test_rejection_and_lifecycle_refunds(urban,reason):
    w,ex,a,f,t,action=urban;s=w.store
    if reason=='blocked':s.update('urban_parcels',action['parcel_id'],blocked=1)
    if reason=='zone':s.update('urban_parcels',action['parcel_id'],zone_key='residential')
    if reason=='authority':a+=1
    if reason=='funds':
        cash=w.economy.ledger.balance(f['account_id'])
        sink=w.economy.ledger.ensure_system_account('sys:construction',currency_code=s.scalar('SELECT currency_code FROM accounts WHERE id=?',(f['account_id'],)))
        w.economy.ledger.transfer(t,f['account_id'],sink,cash,kind='test_drain')
    r=ex.execute_action(t,a,action)
    if reason in {'death','bankruptcy'}:
        assert r['ok'],r
        if reason=='death':w.economy.lifecycle.settle_death(t+1,a)
        else:w.economy.firms.bankrupt_firm(t+1,f['id'])
        assert s.scalar('SELECT status FROM construction_projects')=='cancelled'
        assert s.scalar("SELECT COUNT(*) FROM transactions WHERE kind='construction_refund'")==1
        assert s.scalar("SELECT balance_cents FROM accounts WHERE owner_type='construction'")==0
    else:
        assert not r['ok'],r
        assert s.scalar('SELECT COUNT(*) FROM construction_projects')==0
    w.economy.ledger.reconcile()

def test_recorded_participant_build_replay_and_resume(tmp_path):
    import asyncio
    import hashlib
    from run import open_run
    from world.replay_verify import verify_replay
    cfg=load_config('runs/simcity.yaml');cfg['population']['target_total']=44;cfg['checkpoint_every']=0
    s,w,run_id=open_run(cfg,None,None,data_dir=tmp_path)
    replay=None
    try:
        asyncio.run(w.run(max_ticks=12))
        f=s.query_one("SELECT f.* FROM firms f JOIN civic_authorizations c ON c.consumed_by_firm_id=f.id JOIN agents a ON a.id=f.founder_agent_id WHERE f.status<>'bankrupt' AND a.alive=1 ORDER BY f.id LIMIT 1")
        assert f is not None
        parcel=s.scalar("SELECT id FROM urban_parcels WHERE region_id=? AND blocked=0 AND zone_key='commercial' ORDER BY id LIMIT 1",(f['region_id'],))
        participant=w.runtime.participant
        participant.acquire(f['founder_agent_id'],s.tick,running=False)
        action={'type':'construct_building','firm_id':f['id'],'parcel_id':parcel,'template_key':'workplace','request_key':'recorded-build'}
        participant.queue_action(s.tick,action,running=False)
        asyncio.run(w.run(max_ticks=1))
        assert s.scalar("SELECT count(*) FROM construction_projects WHERE status='building'")==1
        s.commit();s.close()
        s,w,_=open_run({},run_id,None,data_dir=tmp_path)
        asyncio.run(w.run(max_ticks=4));s.commit()
        assert s.scalar("SELECT status FROM construction_projects")=='completed'
        before=hashlib.sha256(open(s.path,'rb').read()).hexdigest()
        replay,rw,_=open_run({},None,run_id,data_dir=tmp_path)
        asyncio.run(rw.run(max_ticks=17));replay.commit()
        proof=verify_replay(s.path,replay.path)
        assert proof['exact'],proof['differences']
        assert hashlib.sha256(open(s.path,'rb').read()).hexdigest()==before
    finally:
        if replay:replay.close()
        s.close()

def test_second_start_and_live_projection_privacy(urban):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from server.v2_api import install_v2_routes
    w,ex,a,f,t,action=urban;s=w.store
    assert ex.execute_action(t,a,action)['ok']
    assert not ex.execute_action(t,a,{**action,'request_key':'second-click'})['ok']
    assert s.scalar("SELECT COUNT(*) FROM transactions WHERE kind='construction_escrow'")==1
    before=s.conn.total_changes
    history=w.economy.urban.projection(t-1)
    assert history['projects']==[]
    view=w.economy.urban.projection(t)
    project=view['projects'][0]
    assert not {'actor_agent_id','escrow_account_id','request_key','balance_cents'} & project.keys()
    assert s.conn.total_changes==before
    s.set_meta(tick=t)
    app=FastAPI();install_v2_routes(app,w,SimpleNamespace())
    with TestClient(app) as client:
        response=client.get('/api/v2/urban-development',params={'tick':str(t-1)})
        assert response.status_code==200,response.text
        assert response.json()['data']['projects']==[]
        assert client.get('/api/v2/urban-development').json()['data']['projects'][0]['id']==project['id']


def test_schema19_additive_and_checksums(tmp_path):
    import sqlite3
    from engine.migrations.registry import registered_migrations, migration_checksum
    s=Store(str(tmp_path/'schema.db'))
    assert s.scalar('SELECT MAX(version) FROM schema_migrations')==19
    for m in registered_migrations():
        assert m.checksum_sha256==migration_checksum(m.sql)
    assert not s.query('PRAGMA foreign_key_check')
    s.close()

def test_completed_bankruptcy_and_blocked_completion(urban):
    w,ex,a,f,t,action=urban;s=w.store
    r=ex.execute_action(t,a,action);assert r['ok']
    s.update('urban_parcels',action['parcel_id'],blocked=1)
    w.economy.urban.finalize(t+3)
    assert s.scalar('SELECT status FROM construction_projects')=='cancelled'
    s.update('urban_parcels',action['parcel_id'],blocked=0)
    r=ex.execute_action(t+4,a,{**action,'request_key':'restart'});assert r['ok']
    w.economy.urban.finalize(t+7)
    w.economy.firms.bankrupt_firm(t+8,f['id'])
    assert s.scalar('SELECT status FROM construction_projects WHERE id=?',(r['project_id'],))=='closed'
    assert s.scalar("SELECT COUNT(*) FROM accounts WHERE owner_type='construction' AND balance_cents<>0")==0
    w.economy.ledger.reconcile()

@pytest.mark.parametrize('failure',['missing_permit','wrong_region','dead'])
def test_authority_rejections_leave_money_untouched(urban,failure):
    w,ex,a,f,t,action=urban;s=w.store
    if failure=='missing_permit':s.execute("UPDATE civic_authorizations SET status='revoked' WHERE consumed_by_firm_id=?",(f['id'],))
    if failure=='wrong_region':action['parcel_id']=s.scalar('SELECT id FROM urban_parcels WHERE region_id<>? ORDER BY id LIMIT 1',(f['region_id'],))
    if failure=='dead':s.update('agents',a,alive=0)
    cash=w.economy.ledger.balance(f['account_id'])
    assert not ex.execute_action(t,a,action)['ok']
    assert w.economy.ledger.balance(f['account_id'])==cash
    assert s.scalar('SELECT count(*) FROM construction_projects')==0

def test_two_permitted_firms_compete_for_same_parcel(urban,monkeypatch):
    w,ex,a,f,t,action=urban;s=w.store
    original=w.runtime.ctx.build
    def same_region_context(agent,tick):
        context=original(agent,tick)
        if agent['region_id']!=f['region_id']:
            context.pop('entrepreneurship_opportunity',None)
        return context
    monkeypatch.setattr(w.runtime.ctx,'build',same_region_context)
    second,permit,ex2=_permit_authorization(w)
    founding_tick=int(permit['issued_tick'])+1
    founded=ex2.execute_action(founding_tick,second,w.economy.city.founding_opportunity(second,founding_tick)['action'])
    assert founded['ok'],founded
    assert second!=a and founded['firm_id']!=f['id']
    second_firm=s.query_one('SELECT * FROM firms WHERE id=?',(founded['firm_id'],))
    assert second_firm['region_id']==f['region_id']
    assert ex.execute_action(t,a,action)['ok']
    cash=w.economy.ledger.balance(second_firm['account_id'])
    contested={**action,'firm_id':second_firm['id'],'request_key':'competing-firm'}
    rejected=ex2.execute_action(t,second,contested)
    assert not rejected['ok'] and 'occupied' in rejected['reason']
    assert w.economy.ledger.balance(second_firm['account_id'])==cash
    assert s.scalar('SELECT COUNT(*) FROM construction_projects')==1
    w.economy.ledger.reconcile()

def test_schema19_failure_rolls_back_without_touching_prior_history(tmp_path,monkeypatch):
    from engine.migrations import registry
    from engine.migrations.registry import Migration,MigrationError
    original=registry.registered_migrations()
    predecessors=tuple(m for m in original if m.version<19)
    v19=next(m for m in original if m.version==19)
    monkeypatch.setattr(registry,'_MIGRATIONS',predecessors)
    s=Store(str(tmp_path/'pre19.db'))
    before=[tuple(r) for r in s.query('SELECT * FROM schema_migrations ORDER BY version')]
    broken=Migration.create(19,v19.name,v19.sql+'\nINSERT INTO no_such_table VALUES(1);')
    monkeypatch.setattr(registry,'_MIGRATIONS',(*predecessors,broken))
    with pytest.raises(MigrationError,match='failed applying migration v19'):
        registry.apply_migrations(s.conn,source_schema=18,target_schema=19)
    assert [tuple(r) for r in s.query('SELECT * FROM schema_migrations ORDER BY version')]==before
    assert not s.scalar("SELECT COUNT(*) FROM sqlite_master WHERE name='urban_parcels'")
    monkeypatch.setattr(registry,'_MIGRATIONS',original)
    registry.apply_migrations(s.conn,source_schema=18,target_schema=19)
    assert s.scalar('SELECT MAX(version) FROM schema_migrations')==19
    assert [tuple(r) for r in s.query('SELECT * FROM schema_migrations WHERE version<19 ORDER BY version')]==before
    s.close()

@pytest.mark.parametrize('kind',['construct_building','cancel_construction','demolish_building'])
def test_accepted_receipt_retries_have_no_economic_or_skill_effect(urban,kind):
    import json
    w,ex,actor,firm,tick,build=urban
    store=w.store
    assert w.economy.cognition.enabled
    post_calls=[]
    ex.post_action_hook=lambda *args:post_calls.append(args)
    action=build
    if kind!='construct_building':
        started=ex.execute_action(tick,actor,build)
        assert started['ok']
        if kind=='demolish_building':
            w.economy.urban.finalize(tick+3)
            tick+=4
        else:
            tick+=1
        action={'type':kind,'project_id':started['project_id'],'request_key':kind+'-once'}
    first=ex.execute_action(tick,actor,action)
    assert first['ok'] and not first.get('idempotent_retry')
    # Compare full persisted economic rows, not only the one funded account.
    domain_tables=(
        'accounts','account_ledger_totals','transactions','ledger_entries',
        'agent_skills','agent_skill_history','events','causal_links',
        'urban_parcels','construction_projects','construction_receipts',
        'urban_projection_history','places','occupancy_leases',
    )
    def domain_state():
        return {table:[tuple(row) for row in store.query(f'SELECT * FROM {table} ORDER BY rowid')]
                for table in domain_tables}
    before=domain_state()
    proposals=store.scalar('SELECT COUNT(*) FROM action_proposals')
    hook_calls=len(post_calls)
    retry=ex.execute_action(tick+1,actor,action)
    assert retry=={**first,'idempotent_retry':True}
    assert domain_state()==before
    assert len(post_calls)==hook_calls
    assert store.scalar('SELECT COUNT(*) FROM action_proposals')==proposals+1
    audit=store.query_one('SELECT validation_status,result_json FROM action_proposals ORDER BY id DESC LIMIT 1')
    assert audit['validation_status']=='accepted'
    assert json.loads(audit['result_json'])==retry
    w.economy.ledger.reconcile()

def test_http_participant_catalog_wait_release_and_exact_replay(tmp_path):
    import asyncio
    import hashlib
    from fastapi.testclient import TestClient
    from server.app import create_app
    from run import open_run
    from world.replay_verify import verify_replay
    cfg=load_config('runs/simcity.yaml');cfg['population']['target_total']=44;cfg['checkpoint_every']=0
    source,world,run_id=open_run(cfg,None,None,data_dir=tmp_path)
    replay=None
    try:
        asyncio.run(world.run(max_ticks=12))
        firm=source.query_one("SELECT f.* FROM firms f JOIN civic_authorizations c ON c.consumed_by_firm_id=f.id JOIN agents a ON a.id=f.founder_agent_id WHERE f.status='private' AND a.alive=1 ORDER BY f.id LIMIT 1")
        parcel=source.scalar("SELECT id FROM urban_parcels WHERE region_id=? AND blocked=0 AND zone_key='commercial' ORDER BY id LIMIT 1",(firm['region_id'],))
        with TestClient(create_app(world)) as client:
            controlled=client.post('/api/participant/control',json={'agent_id':firm['founder_agent_id'],'expected_tick':12})
            assert controlled.status_code==200,controlled.text
            for tick in range(12,16):
                # Browser polling the next-turn catalog must be completely read-only.
                changes=source.conn.total_changes
                memories=[tuple(r) for r in source.query('SELECT * FROM memories ORDER BY id')]
                for _ in range(3):assert client.get('/api/participant').status_code==200
                assert source.conn.total_changes==changes
                assert [tuple(r) for r in source.query('SELECT * FROM memories ORDER BY id')]==memories
                action=({'type':'construct_building','firm_id':firm['id'],'parcel_id':parcel,'template_key':'workplace','request_key':'http-build'} if tick==12 else {'type':'do_nothing'})
                queued=client.post('/api/participant/action',json={'expected_tick':tick,'action':action,'reasoning':'City construction proposal' if tick==12 else ''})
                assert queued.status_code==200,queued.text
                advanced=client.post('/api/run/step')
                assert advanced.status_code==200,advanced.text
                assert advanced.json()['tick']==tick+1
            assert source.scalar('SELECT status FROM construction_projects')=='completed'
            changes=source.conn.total_changes
            assert client.get('/api/participant').status_code==200
            assert source.conn.total_changes==changes
            assert client.post('/api/participant/release',json={'expected_tick':16}).status_code==200
        source.commit()
        before=hashlib.sha256(open(source.path,'rb').read()).hexdigest()
        replay,rw,_=open_run({},None,run_id,data_dir=tmp_path)
        asyncio.run(rw.run(max_ticks=16));replay.commit()
        proof=verify_replay(source.path,replay.path)
        assert proof['exact'],proof['differences']
        assert hashlib.sha256(open(source.path,'rb').read()).hexdigest()==before
    finally:
        if replay:replay.close()
        source.close()


def test_attention_context_uses_logical_event_identity_and_detects_tampering(tmp_path):
    from world.replay_verify import verify_replay
    worlds=[]
    try:
        cfg=load_config('runs/simcity.yaml');cfg['population']['target_total']=44;cfg['checkpoint_every']=0
        for side in ('source','replay'):
            s=Store(str(tmp_path/(side+'.db')));s.init_run_meta(side,cfg['seed'],cfg)
            w=World(s,cfg);w.initialize();worlds.append(w)
        keys=[]
        for index,w in enumerate(worlds):
            if index:w.store.log_event(0,'participant_action_queued',{'agent_id':1})
            eid=w.store.log_event(0,'business_permit_approved',{'agent_id':1,'case_id':17})
            keys.append(w.economy.city.persist_attention_context(1,0,'participant',{
                'activity':[{'source_event_id':eid,'event_kind':'business_permit_approved','occurred_tick':0,'title':'Approved','summary':'A committed civic fact.'}]
            })[0])
            w.store.commit()
        assert keys[0]==keys[1]
        assert verify_replay(worlds[0].store.path,worlds[1].store.path)['exact']
        worlds[1].store.execute("UPDATE attention_contexts SET snapshot_json=replace(snapshot_json,'A committed civic fact.','Tampered attention.')")
        worlds[1].store.commit()
        proof=verify_replay(worlds[0].store.path,worlds[1].store.path)
        assert not proof['exact'] and 'attention_contexts' in proof['differences']
    finally:
        for w in worlds:w.store.close()

@pytest.mark.parametrize('semantics',[2,12,13])
def test_http_catalog_is_read_only_on_legacy_and_current_runs(tmp_path,semantics):
    from fastapi.testclient import TestClient
    from server.app import create_app
    cfg=load_config('runs/simcity.yaml')
    cfg['engine_semantics_version']=semantics
    cfg['city']['enabled']=semantics>=12
    cfg['urban_development']['enabled']=semantics>=13
    cfg['population']['target_total']=44
    s=Store(str(tmp_path/f'catalog-{semantics}.db'));s.init_run_meta('catalog',cfg['seed'],cfg)
    w=World(s,cfg);w.initialize()
    try:
        agent=s.scalar("SELECT id FROM agents WHERE alive=1 AND kind='citizen' AND role IS NULL ORDER BY id LIMIT 1")
        w.runtime.mem.observe(agent,0,'Remember this before viewing a catalog.')
        with TestClient(create_app(w)) as client:
            assert client.post('/api/participant/control',json={'agent_id':agent,'expected_tick':0}).status_code==200
            before=[tuple(row) for row in s.query('SELECT * FROM memories ORDER BY id')]
            changes=s.conn.total_changes
            for _ in range(3):assert client.get('/api/participant').status_code==200
            assert s.conn.total_changes==changes
            assert [tuple(row) for row in s.query('SELECT * FROM memories ORDER BY id')]==before
        # Actual engine cognition still marks access at the decision tick.
        row=s.query_one('SELECT * FROM agents WHERE id=?',(agent,))
        w.runtime.ctx.build(row,1)
        assert s.scalar('SELECT MAX(last_accessed_tick) FROM memories WHERE agent_id=?',(agent,))==1
    finally:s.close()

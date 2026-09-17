"""Declared construction funding and civic staffing across actual World departures."""
import asyncio
from contextlib import closing
import hashlib
import json
from pathlib import Path

import pytest

from engine.lifecycle import Lifecycle
from engine.population_history import ResidenceError
from engine.project_rights import interests_at, steward_at
from engine.store import open_read_only_connection
from research.export_bundle import export_bundle, validate_bundle
from world.replay_verify import _agent_role, verify_replay_connections

from .conftest import make_agent
from .test_population_residence_history import contents
from .test_population_scenario import scenario_world, proposal
from .test_semantics20_project_rights import validate
from .test_semantics20_civic_succession import city_world


OWNER, APPLICANT, CLERK, SUCCESSOR = 25, 23, 45, 24


@pytest.fixture
def construction_world(scenario_world, tmp_path):
    entries = [proposal('owner-out', actor=f'agent:{OWNER}'),
        proposal('clerk-out', actor=f'agent:{CLERK}'),
        proposal('owner-back', tick=3, due=5, actor=f'agent:{OWNER}', cause='return'),
        proposal('clerk-back', tick=6, due=8, actor=f'agent:{CLERK}', cause='return')]

    def create(name='construction-source', *, source=None, approve_pending=False, work=False,
               successor_departure=False):
        fresh = not (tmp_path/f'{name}.db').exists()
        run_entries = entries + ([proposal('successor-out', tick=3, due=4,
            actor=f'agent:{SUCCESSOR}')] if successor_departure else [])
        world = scenario_world(run_entries, name, replay_source=source, config_overrides={
            'construction': {'enabled': True, 'agent_initiation': False},
            'lifecycle': {'illness_onset_annual_young': 0, 'illness_onset_annual_old': 0},
            'budget': {'conversation_pairs': 0}})
        e, store = world.economy, world.store
        if fresh:
            assert store.scalar("SELECT agent_id FROM agency_staff WHERE region_id=1 "
                "AND role_key='permit_clerk' AND active=1") == CLERK
            execute = world.runtime.executor.execute_action
            for actor, key in ((OWNER, 'retained-home'), (APPLICANT, 'pending-home')):
                proposed = execute(0, actor, {'type': 'propose_construction',
                    'owner_type': 'agent', 'owner_id': actor, 'region_id': 1,
                    'site_key': key, 'target_place_type': 'private_home', 'name': key,
                    'required_funding_cents': 1200, 'required_work_units': 6,
                    'dedupe_key': f'genesis-{key}-propose'})
                assert proposed['ok'], proposed
                project = proposed['project_id']
                applied = execute(0, actor, {'type': 'apply_construction_permit',
                    'project_id': project, 'dedupe_key': f'genesis-{key}-apply'})
                assert applied['ok'], applied
                if actor == OWNER or approve_pending:
                    decided = execute(0, CLERK, {'type': 'decide_construction_permit',
                        'case_id': applied['permit_case_id'], 'decision': 'approve',
                        'reason_code': 'requirements_verified', 'dedupe_key': f'genesis-{key}-permit'})
                    assert decided['ok'], decided
                if actor == OWNER:
                    funded = execute(0, OWNER, {'type': 'contribute_construction_funding',
                        'project_id': project, 'amount_cents': 1200, 'dedupe_key': 'genesis-home-fund'})
                    assert funded['ok'], funded
            e.ledger.create_account('agent', OWNER, 'fx', currency_code='IVC',
                                    opening_cents=37, label='Declared construction foreign holding')
            if work:
                # Declare one existing eligible resident, as in the civic
                # succession fixture; this is not a modeled resignation.
                assert not store.query_one("SELECT 1 FROM firm_operations WHERE operator_agent_id=? "
                    "AND status IN ('private','listed')", (SUCCESSOR,))
                assert store.scalar("SELECT COUNT(*) FROM agents WHERE id=? AND alive=1 AND age>=18 "
                    "AND kind='citizen' AND role IS NULL AND retired=0 AND region_id=1", (SUCCESSOR,)) == 1
                store.execute("UPDATE employments SET status='ended',end_tick=0 "
                              "WHERE agent_id=? AND status='active'", (SUCCESSOR,))
                store.update('agents', SUCCESSOR, employer_id=None)
            for actor in (OWNER, APPLICANT, CLERK, *((SUCCESSOR,) if work else ())):
                store.update('agents', actor, population_tier='core', pinned_core=1,
                    cadence_json='{"act":1,"portfolio":9999,"career":9999,"news":9999}')
            store.log_event(0, 'declared_population_construction_cohort', {
                'owner_id': OWNER, 'applicant_id': APPLICANT, 'clerk_id': CLERK,
                'declared_unemployed_candidate': SUCCESSOR if work else None,
                'successor_departure': successor_departure,
                'pending_permit_approved_in_genesis': approve_pending,
                'return_work_days': [5,6,7] if work else []}, phase='GENESIS')
        home = store.scalar("SELECT id FROM construction_projects WHERE site_key='retained-home'")
        pending = store.scalar("SELECT id FROM construction_permit_cases WHERE project_id="
            "(SELECT id FROM construction_projects WHERE site_key='pending-home')")
        for purpose in ('decision','founder','permit_clerk'):
            original = world.gateway.scripted.policies[purpose]
            def decisions(context, original=original, purpose=purpose):
                if source is not None:
                    raise AssertionError('replay must consume recorded construction decisions')
                actor = context.get('agent',{}).get('id')
                tick = context.get('tick')
                if actor not in (OWNER, APPLICANT, CLERK, *((SUCCESSOR,) if work else ())) and purpose != 'permit_clerk':
                    return original(context)
                action = {'type':'do_nothing'}
                if work and actor == OWNER and tick in (5,6,7):
                    action = {'type':'perform_construction_work','project_id':home,
                        'work_units':2,'wage_cents':100,'procurement_cents':100,
                        'dedupe_key':f'returned-owner-work-{tick}'}
                elif work and purpose == 'permit_clerk' and actor != CLERK and tick >= 2:
                    case = store.query_one('SELECT * FROM construction_permit_cases WHERE id=?', (pending,))
                    if case['status'] == 'submitted' and e.construction._staffs_agency(
                            actor, case['agency_id'], case['region_id']):
                        action = {'type':'decide_construction_permit','case_id':pending,
                            'decision':'approve','reason_code':'requirements_verified',
                            'dedupe_key':f'successor-permit-{tick}'}
                return {'reasoning':'Declared construction and staff departure workflow','actions':[action]}
            world.gateway.scripted.register(purpose, decisions)
        return world

    create.close = scenario_world.close
    return create


def construction_state(world):
    return {table:[tuple(row) for row in world.store.query(f'SELECT * FROM "{table}" ORDER BY rowid')]
        for table in ('accounts','transactions','ledger_entries','construction_projects',
            'construction_permit_cases','construction_contributions','project_interest_lots',
            'project_stewardships','places')}


def test_outside_contributor_cannot_spend_retained_wallet_directly(construction_world):
    world = construction_world(approve_pending=True)
    for _ in range(2): asyncio.run(world.step())
    assert not world.economy.population.is_available(OWNER)
    project = world.store.scalar("SELECT id FROM construction_projects WHERE site_key='pending-home'")
    before = construction_state(world)
    result = world.economy.construction.contribute_funding(2, OWNER, {
        'project_id':project,'amount_cents':100,'dedupe_key':'outside-contributor'})
    assert not result['ok'], result
    assert construction_state(world) == before


def test_outside_clerk_cannot_decide_with_stale_staff_assignment(construction_world):
    world = construction_world()
    for _ in range(2): asyncio.run(world.step())
    assert not world.economy.population.is_available(CLERK)
    # Fault injection: an obsolete assignment must not reauthorize its actor.
    world.store.execute('UPDATE agency_staff SET active=1,ended_tick=NULL WHERE agent_id=?', (CLERK,))
    world.store.update('agents', CLERK, role='permit_clerk')
    case = world.store.scalar("SELECT id FROM construction_permit_cases WHERE status='submitted'")
    before = construction_state(world)
    result = world.economy.construction.decide_permit(2, CLERK, {
        'case_id':case,'decision':'approve','reason_code':'requirements_verified',
        'dedupe_key':'outside-clerk'})
    assert not result['ok'], result
    assert construction_state(world) == before


@pytest.mark.parametrize('surface',['funding','context'])
def test_missing_construction_actor_history_precedes_effects(construction_world, surface):
    world = construction_world(approve_pending=True)
    e, store = world.economy, world.store
    person, _ = make_agent(e, store.scalar('SELECT id FROM banks ORDER BY id LIMIT 1'),
                          'Unregistered construction actor', cash=10000, region_id=1)
    e.construction.config['agent_initiation'] = True
    project = store.scalar("SELECT id FROM construction_projects WHERE site_key='pending-home'")
    before = contents(store)
    with pytest.raises(ResidenceError):
        if surface == 'funding':
            e.construction.contribute_funding(0, person, {'project_id':project,
                'amount_cents':100,'dedupe_key':'missing-construction-history'})
        else:
            e.construction.decision_context(person, 0)
    assert contents(store) == before


def test_retained_project_and_staff_successor_survive_return_restart_replay_export(
        construction_world, tmp_path):
    def facts(world, day):
        e, store = world.economy, world.store
        home = store.query_one("SELECT * FROM construction_projects WHERE site_key='retained-home'")
        assert store.scalar('SELECT checking_account_id FROM agents WHERE id=?',(OWNER,)) == wallet
        assert store.scalar("SELECT balance_cents FROM accounts WHERE label='Declared construction foreign holding'") == 37
        assert len(interests_at(store,home['id'])) == 1
        assert interests_at(store,home['id'])[0]['agent_id'] == OWNER
        assert store.scalar('SELECT COUNT(*) FROM agents') == people
        assert e.population.is_available(OWNER) is (day == 1 or day >= 5)
        assert e.population.is_available(CLERK) is (day == 1 or day >= 8)
        assert store.scalar('SELECT COUNT(*) FROM llm_calls WHERE agent_id=? AND tick BETWEEN 2 AND 4',(OWNER,)) == 0
        assert store.scalar('SELECT COUNT(*) FROM llm_calls WHERE agent_id=? AND tick BETWEEN 2 AND 7',(CLERK,)) == 0
        if 2 <= day <= 4:
            assert home['status'] == 'building' and home['contributed_work_units'] == 0
            assert home['contributed_funding_cents'] == 1200 and e.ledger.balance(home['escrow_account_id']) == 1200
            assert steward_at(store,home['id'])['steward_agent_id'] is None
        if day >= 2:
            assert store.scalar('SELECT role FROM agents WHERE id=?',(CLERK,)) is None
            assert store.scalar('SELECT COUNT(*) FROM agency_staff WHERE agent_id=? AND active=1',(CLERK,)) == 0
            case = store.query_one("SELECT c.* FROM construction_permit_cases c JOIN construction_projects p "
                "ON p.id=c.project_id WHERE p.site_key='pending-home'")
            assert case['status'] == 'approved'
            assert case['decision_actor_id'] != CLERK and e.population.is_available(case['decision_actor_id'])
            assert case['decided_tick'] == 2
        if day >= 5:
            assert e.project_rights.controls(OWNER,home)
            assert home['contributed_work_units'] == min(6,2*(day-4))
        if day >= 7:
            assert home['status'] == 'completed' and home['completed_tick'] == 7
            assert home['spent_funding_cents'] == home['refunded_funding_cents'] == 600
            assert e.ledger.balance(home['escrow_account_id']) == 0
            assert e.project_rights.household_home(1,OWNER) == home['place_id']
            work = store.query("SELECT model_call_id,result_json FROM action_proposals WHERE actor_id=? "
                "AND action_type='perform_construction_work' AND tick BETWEEN 5 AND 7",(OWNER,))
            assert len(work) == 3 and all(r['model_call_id'] is not None and json.loads(r['result_json'])['ok'] for r in work)
        validate(world)
        e.civic_authority.check_invariants()
        e.households.check_invariants(day)
        world.population_scenario.check_progress()

    source_world = construction_world(work=True)
    wallet = source_world.store.scalar('SELECT checking_account_id FROM agents WHERE id=?',(OWNER,))
    people = source_world.store.scalar('SELECT COUNT(*) FROM agents')
    for day in range(1,10):
        if day == 3:
            asyncio.run(source_world.step(pause_after_phase='NIGHT_CLOSE'))
            construction_world.close(source_world)
            source_world = construction_world(work=True)
        asyncio.run(source_world.step())
        facts(source_world,day)
    source = Path(source_world.store.path)
    construction_world.close(source_world)
    stamp = hashlib.sha256(source.read_bytes()).hexdigest(),source.stat().st_mtime_ns
    replay = construction_world('construction-replay',source=source,work=True)
    for day in range(1,10):
        if day == 3:
            asyncio.run(replay.step(pause_after_phase='NIGHT_CLOSE'))
            construction_world.close(replay)
            replay = construction_world('construction-replay',source=source,work=True)
        asyncio.run(replay.step())
        facts(replay,day)
    replay_path = Path(replay.store.path)
    construction_world.close(replay)
    with closing(open_read_only_connection(source,require_closed=True)) as src, \
            closing(open_read_only_connection(replay_path,require_closed=True)) as dst:
        proof = verify_replay_connections(src,dst)
        assert proof['exact'],proof['differences']
        bundle = export_bundle(src,tmp_path/'source-export')
        assert validate_bundle(bundle,database=src)['contract_id'] == 'hash-contract-v8'
        assert src.execute('SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls').fetchone()[0] == 0
    assert (hashlib.sha256(source.read_bytes()).hexdigest(),source.stat().st_mtime_ns) == stamp
    assert not any(Path(str(source)+suffix).exists() for suffix in ('-wal','-shm','-journal'))


@pytest.mark.parametrize('corruption',['none','missing','duplicate','phase','assignment'])
def test_role_history_orders_promotion_and_later_departure(construction_world, corruption):
    world = construction_world(work=True, successor_departure=True)
    for _ in range(4): asyncio.run(world.step())
    store = world.store
    assert _agent_role(store.conn,SUCCESSOR,tick=1) == ('citizen',True)
    assert _agent_role(store.conn,SUCCESSOR,tick=2) == ('permit_clerk',True)
    assert _agent_role(store.conn,SUCCESSOR,tick=3) == ('permit_clerk',True)
    assert _agent_role(store.conn,SUCCESSOR,tick=4) == ('citizen',True)
    event = store.query_one("SELECT * FROM events WHERE kind='agency_staff_succeeded' AND subject_id=?",(SUCCESSOR,))
    assert event is not None and event['tick'] == 2
    if corruption == 'missing':
        store.update('events',event['id'],kind='injected_missing_promotion')
    elif corruption == 'duplicate':
        store.log_event(2,'agency_staff_succeeded',json.loads(event['payload_json']),
            phase='NIGHT_CLOSE',subject_type='agent',subject_id=SUCCESSOR)
    elif corruption == 'phase':
        store.update('events',event['id'],phase='EXECUTION')
    elif corruption == 'assignment':
        store.execute('UPDATE agency_staff SET effective_tick=3 WHERE agent_id=?',(SUCCESSOR,))
    before = contents(store)
    result = _agent_role(store.conn,SUCCESSOR,tick=1)
    assert result == (('citizen',True) if corruption == 'none' else (None,False))
    assert contents(store) == before


def test_semantics20_staff_promotion_keeps_prior_decision_role(city_world, monkeypatch):
    world, store = city_world, city_world.store
    candidate = store.scalar("SELECT a.id FROM agents a WHERE a.alive=1 AND a.kind='citizen' "
        "AND a.region_id=1 AND a.role IS NULL AND a.retired=0 AND a.age>=18 AND a.employer_id IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM employments j WHERE j.agent_id=a.id AND j.status='active') "
        "AND NOT EXISTS (SELECT 1 FROM firm_operations f WHERE f.operator_agent_id=a.id "
        "AND f.status IN ('private','listed')) ORDER BY a.id LIMIT 1")
    assert candidate is not None
    clerk = store.scalar("SELECT agent_id FROM agency_staff WHERE region_id=1 AND active=1")
    original_draw = Lifecycle._draw
    def draw(self,tick,actor,mechanism):
        return 0.0 if tick == 2 and actor == clerk and mechanism == 'mortality' else original_draw(self,tick,actor,mechanism)
    monkeypatch.setattr(Lifecycle,'_draw',draw)
    store.update('agents',candidate,population_tier='core',pinned_core=1,cadence_json='{"act":1}')
    world.gateway.scripted.register('decision',lambda context:{
        'reasoning':'Declared available successor','actions':[{'type':'do_nothing'}]})
    for _ in range(2): asyncio.run(world.step())
    assert store.scalar('SELECT role FROM agents WHERE id=?',(candidate,)) == 'permit_clerk'
    assert store.scalar("SELECT COUNT(*) FROM llm_calls WHERE agent_id=? AND tick=1 "
        "AND role='citizen' AND purpose='decision'",(candidate,)) == 1
    assert _agent_role(store.conn,candidate,tick=1) == ('citizen',True)
    assert _agent_role(store.conn,candidate,tick=2) == ('permit_clerk',True)

"""Local workforce recovery across real departure, return and stale offers."""
import asyncio
from contextlib import closing
import copy
import hashlib
import json
from pathlib import Path

import pytest

from engine.population_history import ResidenceError
from engine.store import Store, open_read_only_connection
from research.export_bundle import export_bundle, validate_bundle
from world.loop import World
from world.replay_verify import _canonical_llm_reference, _event_llm_expectations, verify_replay_connections

from .test_population_residence_history import contents
from .test_population_scenario import scenario_world, proposal
from .test_prd_completion import _world as legacy_world


MOVER, LOCAL = 23, 24


@pytest.fixture
def recovery_world(scenario_world, tmp_path):
    entries = [proposal(actor=f'agent:{MOVER}'),
               proposal('back', tick=3, due=5, actor=f'agent:{MOVER}', cause='return')]

    def create(name='recovery-source', *, source=None):
        fresh = not (tmp_path/f'{name}.db').exists()
        world = scenario_world(entries, name, replay_source=source, config_overrides={
            'firms': {'workforce_recovery_activation_tick': 3,
                'workforce_recovery_operational_activation_tick': 3,
                'workforce_recovery_target_headcount': 5,
                'workforce_recovery_batch_size': 2,
                'workforce_recovery_minimum_wage_cents': 250000,
                'workforce_recovery_excluded_sectors': ['health','insurance']},
            'lifecycle': {'illness_onset_annual_young': 0, 'illness_onset_annual_old': 0},
            'budget': {'conversation_pairs': 0}})
        e, store = world.economy, world.store
        if fresh:
            firm = store.query_one("SELECT f.* FROM firm_operations f JOIN agents a "
                "ON a.employer_id=f.id WHERE a.id=?", (MOVER,))
            assert firm and firm['sector'] not in ('health','insurance')
            for candidate in (MOVER, LOCAL):
                assert not store.query_one('SELECT 1 FROM firm_operations WHERE operator_agent_id=?', (candidate,))
                store.execute("UPDATE employments SET status='ended',end_tick=0 "
                    "WHERE agent_id=? AND status='active'", (candidate,))
                store.update('agents', candidate, employer_id=None, population_tier='core',
                    pinned_core=1, cadence_json='{"act":9999,"career":9999,"portfolio":9999,"news":9999}')
            store.update('agents', MOVER,
                cadence_json='{"act":1,"career":9999,"portfolio":9999,"news":9999}')
            e.ledger.create_account('agent', MOVER, 'fx', currency_code='IVC', opening_cents=37,
                label='Declared recovery foreign holding')
            job = e.labor.post_job(0, firm['id'], 'Declared recovery vacancy', 250000)
            for candidate in (MOVER, LOCAL):
                application = e.labor.apply_job(0, candidate, job)
                assert application is not None
                offer = e.labor.make_offer(0, application, firm['operator_agent_id'], 250000)
                assert offer is not None
            store.log_event(0, 'declared_population_recovery_cohort', {
                'candidates': [MOVER, LOCAL], 'firm_id': firm['id'], 'job_id': job,
                'unemployment_declared_at_genesis': True,
                'policy_activation_tick': 3}, phase='GENESIS')
        for purpose in ('decision','founder'):
            original = world.gateway.scripted.policies[purpose]
            def idle(context, original=original):
                if source is not None:
                    raise AssertionError('replay must consume recorded model decisions')
                if context.get('agent',{}).get('id') in (MOVER, LOCAL):
                    return {'reasoning':'declared cohort waits for a recorded offer',
                        'actions':[{'type':'do_nothing'}], 'belief_updates':[]}
                return original(context)
            world.gateway.scripted.policies[purpose] = idle
        return world

    create.close = scenario_world.close
    return create


def offers(world):
    return {int(row['agent_id']): dict(row) for row in world.store.query(
        "SELECT jo.*,ap.agent_id,ap.job_id,j.firm_id FROM job_offers jo "
        "JOIN applications ap ON ap.id=jo.application_id JOIN jobs j ON j.id=ap.job_id "
        "WHERE j.title='Declared recovery vacancy' ORDER BY jo.id")}


def departed_with_stale_offer(create):
    world = create()
    for _ in range(2):
        asyncio.run(world.step())
    assert not world.economy.population.is_available(MOVER)
    old = offers(world)[MOVER]
    assert old['status'] != 'pending'
    # Fault injection: cancellation is already verified above. Independent
    # admission must not turn an obsolete offer into an outside decision.
    world.store.update('applications', old['application_id'], state='negotiating')
    world.store.update('job_offers', old['id'], status='pending', decided_tick=None)
    return world


def acceptance(candidate, offer):
    return {'agent_id':candidate, 'purpose':'decision', 'llm_call_id':None,
        'reasoning':'accepting a recorded offer', 'envelope':{
            'reasoning':'accepting a recorded offer', 'belief_updates':[],
            'actions':[{'type':'accept_job_offer','offer_id':offer}]}}


def test_outside_offer_does_not_take_the_local_candidates_recovery_slot(recovery_world):
    world = departed_with_stale_offer(recovery_world)
    before = contents(world.store)
    decisions = world.runtime._workforce_recovery_candidate_decisions(3, [], participant_agent_id=None)
    assert [row['agent_id'] for row in decisions] == [LOCAL], decisions
    assert contents(world.store) == before


@pytest.mark.parametrize('participant', [None, MOVER])
def test_outside_acceptance_cannot_reserve_a_job_against_a_local_candidate(recovery_world, participant):
    world = departed_with_stale_offer(recovery_world)
    recorded = offers(world)
    decisions = [acceptance(person, recorded[person]['id']) for person in (MOVER, LOCAL)]
    before = contents(world.store)
    world.runtime._coordinate_workforce_recovery_candidate_acceptances(3, decisions,
        participant_agent_id=participant)
    assert decisions[1]['envelope']['actions'] == [
        {'type':'accept_job_offer','offer_id':recorded[LOCAL]['id']}], decisions
    if participant is None:
        assert decisions[0]['envelope']['actions'] == []
    assert contents(world.store) == before


def test_hiring_context_excludes_outside_applicants_and_their_pending_offer_count(recovery_world):
    world = departed_with_stale_offer(recovery_world)
    recorded = offers(world)
    old = recorded[MOVER]
    before = contents(world.store)
    applications = world.runtime.ctx._firm_applications(old['firm_id'], actionable_only=True)
    candidates = {row['agent_id'] for row in applications}
    assert MOVER not in candidates and LOCAL in candidates, applications
    retained_count = world.store.scalar("SELECT COUNT(*) FROM job_offers jo "
        "JOIN applications ap ON ap.id=jo.application_id "
        "WHERE ap.job_id=? AND jo.status='pending' AND ap.agent_id<>?", (old['job_id'], MOVER))
    assert retained_count >= 1
    assert all(row['job_pending_offer_count'] == retained_count for row in applications)
    assert world.runtime.ctx._incoming_job_offers(MOVER) == []
    assert contents(world.store) == before
    world.store.update('job_offers', old['id'], proposer_agent_id=MOVER)
    before = contents(world.store)
    assert MOVER not in {row['candidate_agent_id'] for row in
        world.runtime.ctx._firm_job_offers(old['firm_id'], actionable_only=True)}
    assert contents(world.store) == before


@pytest.mark.parametrize('surface', ['candidate','coordination','applications','counteroffers','incoming'])
def test_missing_candidate_history_is_reported_before_recovery_effects(recovery_world, surface):
    world = recovery_world()
    e, store = world.economy, world.store
    example = offers(world)[MOVER]
    person = store.insert('agents', name='Unregistered recovery candidate', kind='citizen',
        occupation='worker', age=35, alive=1, region_id=1)
    currency = store.scalar('SELECT currency_code FROM firms WHERE id=?', (example['firm_id'],))
    wallet = e.ledger.create_account('agent', person, 'checking', currency_code=currency,
        opening_cents=10000, label='Declared unregistered recovery wallet')
    store.update('agents', person, checking_account_id=wallet)
    application = store.insert('applications', tick=0, job_id=example['job_id'],
        agent_id=person, state='negotiating')
    offer = store.insert('job_offers', application_id=application, tick=0,
        proposer_agent_id=person if surface=='counteroffers' else example['proposer_agent_id'],
        wage_cents=250000, status='pending')
    decisions = [acceptance(LOCAL, offers(world)[LOCAL]['id']), acceptance(person, offer)]
    old_decisions = copy.deepcopy(decisions)
    before = contents(store)
    with pytest.raises(ResidenceError):
        if surface == 'candidate':
            world.runtime._workforce_recovery_candidate_decisions(3, [], participant_agent_id=None)
        elif surface == 'coordination':
            world.runtime._coordinate_workforce_recovery_candidate_acceptances(3, decisions,
                participant_agent_id=None)
        elif surface == 'applications':
            world.runtime.ctx._firm_applications(example['firm_id'], actionable_only=True)
        elif surface == 'counteroffers':
            world.runtime.ctx._firm_job_offers(example['firm_id'], actionable_only=True)
        else:
            world.runtime.ctx._incoming_job_offers(person)
    assert decisions == old_decisions
    assert contents(store) == before


def test_context_actor_exclusion_keeps_the_local_pending_offer_count(recovery_world):
    world = recovery_world()
    firm = offers(world)[MOVER]['firm_id']
    before = contents(world.store)
    applications = world.runtime.ctx._firm_applications(firm, actionable_only=True,
        exclude_agent_id=LOCAL)
    assert [row['agent_id'] for row in applications] == [MOVER]
    assert applications[0]['job_pending_offer_count'] == 2
    assert contents(world.store) == before


@pytest.mark.parametrize('kind', [
    'workforce_recovery_model_action_replaced',
    'workforce_recovery_candidate_actions_coordinated'], ids=['model-actions','candidate-actions'])
@pytest.mark.parametrize('change', ['none','actor','tick','phase','missing_link','purpose',
                                  'call_type','oversized_call'])
def test_workforce_event_reference_requires_its_recorded_decision(recovery_world, kind, change):
    world = recovery_world()
    for _ in range(4):
        asyncio.run(world.step())
    store = world.store
    row = next(dict(row) for row in store.query('SELECT * FROM events WHERE kind=? ORDER BY id', (kind,))
        if json.loads(row['payload_json']).get('model_call_id') is not None)
    payload = json.loads(row['payload_json'])
    original_call_id = payload['model_call_id']
    call = dict(store.query_one('SELECT tick,agent_id,role,purpose FROM llm_calls WHERE id=?',
        (payload['model_call_id'],)))
    decision = store.query_one('SELECT * FROM agent_decisions WHERE tick=? AND agent_id=? AND model_call_id=?',
        (row['tick'],payload['agent_id'],payload['model_call_id']))
    assert decision is not None
    if change == 'actor':
        payload['agent_id'] = LOCAL
    elif change == 'tick':
        row['tick'] += 1
    elif change == 'phase':
        row['phase'] = 'MORNING'
    elif change == 'missing_link':
        unrelated_call = store.scalar('SELECT id FROM llm_calls WHERE id<>? ORDER BY id LIMIT 1',
            (payload['model_call_id'],))
        store.update('agent_decisions', decision['id'], model_call_id=unrelated_call)
    elif change == 'purpose':
        store.update('agent_decisions', decision['id'], purpose='memory')
    elif change == 'call_type':
        payload['model_call_id'] = {'id':original_call_id}
    elif change == 'oversized_call':
        payload['model_call_id'] = 2**63
    before = contents(store)
    expected, context_valid = _event_llm_expectations(store.conn,row,payload,'model_call_id',payload)
    _, valid = _canonical_llm_reference(payload['model_call_id'],
        {original_call_id:{'llm_call':call}}, expected, context_valid)
    assert valid is (change == 'none'), (expected,call,context_valid)
    assert contents(store) == before


def test_semantics7_workforce_events_replay_before_decision_rows_existed(tmp_path):
    world = legacy_world(tmp_path, 'legacy-source.db', engine_semantics_version=7,
        population={'target_total':120}, firms={'count':3,'listed':1,'target_headcount':3,
            'workforce_recovery_activation_tick':1,
            'workforce_recovery_operational_activation_tick':1,
            'workforce_recovery_target_headcount':5,'workforce_recovery_batch_size':2})
    try:
        for _ in range(4):
            asyncio.run(world.step())
        assert world.store.scalar('SELECT COUNT(*) FROM agent_decisions') == 0
        assert world.store.scalar("SELECT COUNT(*) FROM events WHERE "
            "kind='workforce_recovery_candidate_actions_coordinated' "
            "AND json_extract(payload_json,'$.model_call_id') IS NOT NULL") > 0
        source = Path(world.store.path)
        config = copy.deepcopy(world.config)
    finally:
        world.close()
    stamp = hashlib.sha256(source.read_bytes()).hexdigest(),source.stat().st_mtime_ns
    replay_path = tmp_path/'legacy-replay.db'
    config.update(replay_source_path=str(source),replay_source_closed=True)
    store = Store(str(replay_path))
    store.init_run_meta('legacy-replay',config['seed'],config)
    replay = World(store,config,replay=True)
    try:
        replay.initialize()
        for _ in range(4):
            asyncio.run(replay.step())
    finally:
        replay.close()
    with closing(open_read_only_connection(source,require_closed=True)) as src, \
            closing(open_read_only_connection(replay_path,require_closed=True)) as dst:
        proof = verify_replay_connections(src,dst)
        assert proof['exact'],proof['differences']
    assert (hashlib.sha256(source.read_bytes()).hexdigest(),source.stat().st_mtime_ns) == stamp
    assert not any(Path(str(source)+s).exists() for s in ('-wal','-shm','-journal'))


def test_local_recovery_hiring_survives_departure_return_restart_replay_and_export(recovery_world, tmp_path):
    def facts(world, day):
        store, e = world.store, world.economy
        recorded = offers(world)
        assert store.scalar('SELECT COUNT(*) FROM agents') == people
        assert store.scalar('SELECT checking_account_id FROM agents WHERE id=?', (MOVER,)) == wallet
        assert store.scalar("SELECT balance_cents FROM accounts WHERE label='Declared recovery foreign holding'") == 37
        assert e.population.is_available(MOVER) is (day == 1 or day >= 5)
        if day >= 2:
            assert recorded[MOVER]['status'] == 'rejected'
            assert store.scalar('SELECT state FROM applications WHERE id=?',
                (recorded[MOVER]['application_id'],)) == 'rejected'
        if 2 <= day <= 4:
            assert store.scalar('SELECT COUNT(*) FROM time_days WHERE tick=? AND agent_id=?', (day, MOVER)) == 0
            assert store.scalar('SELECT COUNT(*) FROM agent_decisions WHERE tick=? AND agent_id=?', (day, MOVER)) == 0
        if day >= 3:
            assert recorded[LOCAL]['status'] == 'accepted'
            employment = store.query_one("SELECT * FROM employments WHERE agent_id=? "
                "AND title='Declared recovery vacancy' AND start_tick=3", (LOCAL,))
            assert employment and employment['status'] == 'active'
            assert employment['pay_interval_ticks'] == 30
            assert store.scalar("SELECT COUNT(*) FROM agent_decisions WHERE tick=3 "
                "AND agent_id=? AND purpose='workforce_recovery_candidate'", (LOCAL,)) == 1
            if day >= 4:
                assert store.scalar('SELECT SUM(accrued_cents) FROM wage_claims WHERE employment_id=?',
                    (employment['id'],)) > 0
            if day >= 33:
                assert store.scalar('SELECT SUM(paid_cents) FROM wage_claims WHERE employment_id=?',
                    (employment['id'],)) > 0
        assert store.scalar('SELECT COUNT(*) FROM llm_calls WHERE tick BETWEEN 2 AND 4 AND agent_id=?', (MOVER,)) == 0
        if day >= 5:
            assert store.scalar('SELECT COUNT(*) FROM llm_calls WHERE tick=5 AND agent_id=?', (MOVER,)) > 0
        world.population_scenario.check_progress()
        e.households.check_invariants(day)
        assert e.ledger.reconcile()[0]

    source_world = recovery_world()
    people = source_world.store.scalar('SELECT COUNT(*) FROM agents')
    wallet = source_world.store.scalar('SELECT checking_account_id FROM agents WHERE id=?', (MOVER,))
    for day in range(1, 35):
        if day == 3:
            asyncio.run(source_world.step(pause_after_phase='NIGHT_CLOSE'))
            recovery_world.close(source_world)
            source_world = recovery_world()
        asyncio.run(source_world.step())
        facts(source_world, day)
    source = Path(source_world.store.path)
    recovery_world.close(source_world)
    stamp = hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns
    replay = recovery_world('recovery-replay', source=source)
    for day in range(1, 35):
        if day == 3:
            asyncio.run(replay.step(pause_after_phase='NIGHT_CLOSE'))
            recovery_world.close(replay)
            replay = recovery_world('recovery-replay', source=source)
        asyncio.run(replay.step())
        facts(replay, day)
    replay_path = Path(replay.store.path)
    recovery_world.close(replay)
    with closing(open_read_only_connection(source, require_closed=True)) as src, \
            closing(open_read_only_connection(replay_path, require_closed=True)) as dst:
        proof = verify_replay_connections(src, dst)
        assert proof['exact'], proof['differences']
        bundle = export_bundle(src, tmp_path/'source-export')
        assert validate_bundle(bundle, database=src)['contract_id'] == 'hash-contract-v8'
        assert src.execute('SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls').fetchone()[0] == 0
    assert (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns) == stamp
    assert not any(Path(str(source)+s).exists() for s in ('-wal','-shm','-journal'))

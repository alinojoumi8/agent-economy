"""Recovery capacity follows available actors and retained firm obligations."""
import asyncio
from contextlib import closing
import copy
import hashlib
import json
from pathlib import Path

import pytest

from engine.population_history import ResidenceError
from engine.store import open_read_only_connection
from research.export_bundle import export_bundle, validate_bundle
from world.replay_verify import verify_replay_connections
from .test_population_residence_history import contents
from .test_population_scenario import proposal, scenario_world
from .test_population_workforce_recovery import (
    LOCAL, MOVER, acceptance, departed_with_stale_offer, offers, recovery_world,
)


def one_remaining_slot(world, firm_id):
    employees = world.store.scalar(
        "SELECT COUNT(*) FROM employments WHERE firm_id=? AND status='active'", (firm_id,))
    world.runtime.config['firms']['workforce_recovery_target_headcount'] = employees + 1
    assert world.runtime._workforce_recovery_firm_slots(3)[firm_id] == 1


def test_outside_existing_acceptance_does_not_hide_a_local_recovery_candidate(recovery_world):
    world = departed_with_stale_offer(recovery_world)
    recorded = offers(world)
    one_remaining_slot(world, recorded[LOCAL]['firm_id'])
    existing = [acceptance(MOVER, recorded[MOVER]['id'])]
    original, before = copy.deepcopy(existing), contents(world.store)
    decisions = world.runtime._workforce_recovery_candidate_decisions(
        3, existing, participant_agent_id=None)
    assert [decision['agent_id'] for decision in decisions] == [LOCAL]
    assert existing == original and contents(world.store) == before


@pytest.mark.parametrize('surface', ['candidate', 'coordination'])
def test_local_operator_cannot_reserve_capacity_for_an_outside_candidate(recovery_world, surface):
    world = departed_with_stale_offer(recovery_world)
    recorded = offers(world)
    firm_id = recorded[LOCAL]['firm_id']
    one_remaining_slot(world, firm_id)
    operator = world.economy.business_control.operator_at(firm_id)
    assert operator not in (MOVER, LOCAL)
    assert world.economy.population.is_local(operator, 3)
    world.store.update('job_offers', recorded[MOVER]['id'], proposer_agent_id=MOVER)
    decisions = [acceptance(operator, recorded[MOVER]['id'])]
    before = contents(world.store)
    if surface == 'candidate':
        original = copy.deepcopy(decisions)
        generated = world.runtime._workforce_recovery_candidate_decisions(
            3, decisions, participant_agent_id=None)
        assert [decision['agent_id'] for decision in generated] == [LOCAL]
        assert decisions == original
    else:
        decisions.append(acceptance(LOCAL, recorded[LOCAL]['id']))
        world.runtime._coordinate_workforce_recovery_candidate_acceptances(
            3, decisions, participant_agent_id=None)
        assert decisions[1]['envelope']['actions'] == [
            {'type': 'accept_job_offer', 'offer_id': recorded[LOCAL]['id']}]
    assert contents(world.store) == before


@pytest.mark.parametrize('surface', ['candidate', 'coordination'])
def test_missing_existing_actor_history_fails_before_recovery_effects(recovery_world, surface):
    world = recovery_world()
    recorded = offers(world)
    actor = world.store.insert('agents', name='Unregistered recovery actor',
        kind='citizen', occupation='worker', age=35, alive=1, region_id=1)
    decisions = [acceptance(LOCAL, recorded[LOCAL]['id']), acceptance(actor, recorded[MOVER]['id'])]
    original, before = copy.deepcopy(decisions), contents(world.store)
    with pytest.raises(ResidenceError):
        if surface == 'candidate':
            world.runtime._workforce_recovery_candidate_decisions(
                3, decisions, participant_agent_id=None)
        else:
            world.runtime._coordinate_workforce_recovery_candidate_acceptances(
                3, decisions, participant_agent_id=None)
    assert decisions == original and contents(world.store) == before


@pytest.mark.parametrize('surface', ['candidate', 'coordination'])
def test_local_counteroffer_keeps_its_shared_capacity_reservation(recovery_world, surface):
    world = recovery_world()
    recorded = offers(world)
    firm_id = recorded[LOCAL]['firm_id']
    one_remaining_slot(world, firm_id)
    operator = world.economy.business_control.operator_at(firm_id)
    world.store.update('job_offers', recorded[MOVER]['id'], proposer_agent_id=MOVER)
    decisions = [acceptance(operator, recorded[MOVER]['id'])]
    before = contents(world.store)
    if surface == 'candidate':
        assert world.runtime._workforce_recovery_candidate_decisions(
            3, decisions, participant_agent_id=None) == []
    else:
        decisions.append(acceptance(LOCAL, recorded[LOCAL]['id']))
        world.runtime._coordinate_workforce_recovery_candidate_acceptances(
            3, decisions, participant_agent_id=None)
        assert decisions[1]['envelope']['actions'] == []
    assert decisions[0]['envelope']['actions'] == [
        {'type': 'accept_job_offer', 'offer_id': recorded[MOVER]['id']}]
    assert contents(world.store) == before


def test_later_missing_history_does_not_publish_part_of_a_reservation_batch(recovery_world):
    world = recovery_world()
    recorded = offers(world)
    actor = world.store.insert('agents', name='Unregistered reservation actor',
        kind='citizen', age=35, alive=1, region_id=1)
    decisions = [acceptance(LOCAL, recorded[LOCAL]['id']), acceptance(actor, recorded[MOVER]['id'])]
    slots = {recorded[LOCAL]['firm_id']: 2}
    before, original = contents(world.store), dict(slots)
    with pytest.raises(ResidenceError):
        world.runtime._consume_accept_slots(decisions, slots, tick=3)
    assert slots == original and contents(world.store) == before


@pytest.mark.parametrize('surface', ['replacement', 'recovery'])
@pytest.mark.parametrize('history', ['outside', 'missing'])
def test_firm_overlay_preflights_operator_residence_before_context_or_edits(
        recovery_world, monkeypatch, surface, history):
    world = departed_with_stale_offer(recovery_world) if history == 'outside' else recovery_world()
    if history == 'outside':
        actor = MOVER
    else:
        actor = world.store.insert('agents', name='Unregistered operator',
            kind='citizen', age=35, alive=1, region_id=1)
    # An inconsistent current firm row must not bypass independent admission.
    # Firm 3 follows two valid operators, exercising whole-batch preflight.
    world.store.update('firms', 3, founder_agent_id=actor)
    assert world.economy.business_control.operator_at(3) == actor
    calls = []
    def context(operator, tick, *, firm_id):
        calls.append(operator['id'])
        assert operator['id'] != actor
        return {}
    monkeypatch.setattr(world.runtime.ctx, 'build', context)
    local_operator = world.economy.business_control.operator_at(2)
    decisions = [{'agent_id': person, 'envelope': {'actions': [{
        'type': 'post_job', 'firm_id': firm, 'title': 'worker', 'wage': 250000}]}}
        for person, firm in ((local_operator, 2), (actor, 3))]
    original, before = copy.deepcopy(decisions), contents(world.store)
    def run():
        if surface == 'replacement':
            world.runtime._replace_operational_workforce_actions(3, decisions, participant_agent_id=None)
        else:
            assert all(row['agent_id'] != actor for row in world.runtime._workforce_recovery_decisions(
                3, decisions, participant_agent_id=None))
    if history == 'missing':
        with pytest.raises(ResidenceError):
            run()
        assert decisions == original and calls == []
    else:
        run()
        assert decisions[-1] == original[-1]
        assert actor not in calls
    assert contents(world.store) == before


@pytest.fixture
def operator_world(scenario_world, tmp_path):
    owner, successor, candidate = 32, 23, 24
    entries = [proposal(actor=f'agent:{owner}'),
        proposal('owner-back', tick=3, due=5, actor=f'agent:{owner}', cause='return')]
    def create(name='operator-source', *, source=None):
        fresh = not (tmp_path/f'{name}.db').exists()
        world = scenario_world(entries, name, replay_source=source, config_overrides={
            'firms': {'workforce_recovery_activation_tick': 3,
                'workforce_recovery_operational_activation_tick': 3,
                'workforce_recovery_target_headcount': 2,
                'workforce_recovery_batch_size': 2,
                'workforce_recovery_minimum_wage_cents': 250000,
                'workforce_recovery_excluded_sectors': ['health','insurance']},
            'lifecycle': {'illness_onset_annual_young': 0, 'illness_onset_annual_old': 0},
            'budget': {'conversation_pairs': 0}})
        e, store = world.economy, world.store
        if fresh:
            assert e.business_control.operator_at(2) == owner
            assert store.scalar('SELECT employer_id FROM agents WHERE id=?', (successor,)) == 2
            store.execute("UPDATE employments SET status='ended',end_tick=0 "
                "WHERE agent_id=? AND status='active'", (candidate,))
            store.update('agents', candidate, employer_id=None)
            for person in (owner, successor, candidate):
                store.update('agents', person, population_tier='core', pinned_core=1,
                    cadence_json='{"act":9999,"career":9999,"portfolio":9999,"news":9999}')
            e.exchange._adjust_shares(2, 'agent', owner, -1)
            e.exchange._adjust_shares(2, 'agent', successor, 1)
            e.ledger.create_account('agent', owner, 'fx', currency_code='IVC', opening_cents=37,
                label='Declared operator foreign holding')
            job = e.labor.post_job(0, 2, 'Declared successor vacancy', 250000)
            application = e.labor.apply_job(0, candidate, job)
            offer = e.labor.make_offer(0, application, owner, 250000)
            assert offer is not None
            counter = e.labor.make_offer(0, application, candidate, 300000, parent_offer_id=offer)
            assert counter is not None
            store.log_event(0, 'declared_recovery_operator_cohort', {
                'owner': owner, 'successor': successor, 'candidate': candidate,
                'firm_id': 2, 'job_id': job, 'counteroffer_id': counter,
                'successor_genesis_shares': 1, 'unemployment_declared_at_genesis': True,
                'policy_activation_tick': 3}, phase='GENESIS')
        for purpose in ('decision', 'founder'):
            original = world.gateway.scripted.policies[purpose]
            def idle(context, original=original):
                if source is not None:
                    raise AssertionError('replay must consume recorded model decisions')
                if context.get('agent', {}).get('id') in (owner, successor, candidate):
                    return {'reasoning':'declared cohort waits for the recorded hiring pipeline',
                        'actions':[{'type':'do_nothing'}], 'belief_updates':[]}
                return original(context)
            world.gateway.scripted.policies[purpose] = idle
        return world
    create.close = scenario_world.close
    return create


def test_current_operator_hires_while_outside_owner_retains_shares_through_return_and_replay(
        operator_world, tmp_path):
    owner, successor, candidate = 32, 23, 24
    def facts(world, day):
        e, store = world.economy, world.store
        assert store.scalar('SELECT COUNT(*) FROM agents') == people
        assert store.scalar('SELECT checking_account_id FROM agents WHERE id=?', (owner,)) == wallet
        assert store.scalar("SELECT balance_cents FROM accounts WHERE label='Declared operator foreign holding'") == 37
        assert store.scalar("SELECT qty FROM shares WHERE firm_id=2 AND holder_type='agent' AND holder_id=?", (owner,)) == 999
        assert store.scalar("SELECT qty FROM shares WHERE firm_id=2 AND holder_type='agent' AND holder_id=?", (successor,)) == 1
        assert e.business_control.operator_at(2) == (owner if day == 1 else successor)
        assert e.population.is_available(owner) is (day == 1 or day >= 5)
        if day >= 2:
            assert not e.business_control.controls(owner, 2)
            assert e.business_control.controls(successor, 2)
        assert store.scalar('SELECT COUNT(*) FROM agent_decisions WHERE agent_id=? AND tick BETWEEN 2 AND 4', (owner,)) == 0
        assert store.scalar('SELECT COUNT(*) FROM llm_calls WHERE agent_id=? AND tick BETWEEN 2 AND 4', (owner,)) == 0
        if day >= 3:
            employment = store.query_one("SELECT * FROM employments WHERE agent_id=? "
                "AND title='Declared successor vacancy' AND start_tick=3", (candidate,))
            assert employment and employment['firm_id'] == 2 and employment['wage_cents'] == 300000
            assert employment['status'] == 'active'
            decisions = store.query("SELECT * FROM agent_decisions WHERE tick=3 AND agent_id=? "
                "AND purpose='workforce_recovery'", (successor,))
            assert len(decisions) == 1
            event = store.query_one("SELECT payload_json FROM events WHERE tick=3 AND kind='job_offer_accepted' "
                "AND json_extract(payload_json,'$.candidate_agent_id')=?", (candidate,))
            assert json.loads(event['payload_json'])['accepting_agent_id'] == successor
            assert world.runtime._workforce_recovery_firm_slots(day)[2] == 0
            if day >= 4:
                assert store.scalar('SELECT SUM(accrued_cents) FROM wage_claims WHERE employment_id=?', (employment['id'],)) > 0
        world.population_scenario.check_progress()
        e.business_control.check_invariants()
        e.households.check_invariants(day)
        assert e.ledger.reconcile()[0]
    world = operator_world()
    people = world.store.scalar('SELECT COUNT(*) FROM agents')
    wallet = world.store.scalar('SELECT checking_account_id FROM agents WHERE id=?', (owner,))
    for day in range(1, 9):
        if day == 3:
            asyncio.run(world.step(pause_after_phase='NIGHT_CLOSE'))
            operator_world.close(world)
            world = operator_world()
        asyncio.run(world.step())
        facts(world, day)
    source = Path(world.store.path)
    operator_world.close(world)
    stamp = hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns
    replay = operator_world('operator-replay', source=source)
    for day in range(1, 9):
        if day == 3:
            asyncio.run(replay.step(pause_after_phase='NIGHT_CLOSE'))
            operator_world.close(replay)
            replay = operator_world('operator-replay', source=source)
        asyncio.run(replay.step())
        facts(replay, day)
    replay_path = Path(replay.store.path)
    operator_world.close(replay)
    with closing(open_read_only_connection(source, require_closed=True)) as src, \
            closing(open_read_only_connection(replay_path, require_closed=True)) as dst:
        proof = verify_replay_connections(src, dst)
        assert proof['exact'], proof['differences']
        bundle = export_bundle(src, tmp_path/'operator-export')
        assert validate_bundle(bundle, database=src)['contract_id'] == 'hash-contract-v8'
        assert src.execute('SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls').fetchone()[0] == 0
    assert (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns) == stamp
    assert not any(Path(str(source)+suffix).exists() for suffix in ('-wal','-shm','-journal'))

"""Declared near-majority cohort with real daily aging and mixed population inputs.

These people start at synthetic ages; this is not native generational evidence.
"""
import asyncio
from contextlib import closing
import hashlib
import json
from pathlib import Path

import pytest

from engine.households import Households
from engine.lifecycle import Lifecycle
from engine.store import open_read_only_connection
from research.export_bundle import export_bundle, validate_bundle
from world.replay_verify import verify_replay_connections

from .test_population_scenario import scenario_world, proposal


OWNER, COMPANION, MOVER, WARD = 25, 29, 32, 38
ADULT_DAY = 38


@pytest.mark.parametrize('death_lead_days', [1, 0], ids=['guardian-day-before', 'same-day'])
def test_declared_majority_guardian_loss_and_stale_group_assent_replay(
        scenario_world, tmp_path, monkeypatch, death_lead_days):
    death_day = ADULT_DAY - death_lead_days
    late = proposal('late', tick=35, due=ADULT_DAY, actor=f'agent:{OWNER}')
    late['members'].append(f'agent:{WARD}')
    late['care_plan'] = [{'child': f'agent:{WARD}', 'guardian': f'agent:{OWNER}'}]
    entries = [proposal(actor=f'agent:{MOVER}'),
               proposal('back', tick=3, due=5, actor=f'agent:{MOVER}', cause='return'),
               late, {'key': 'late-consent', 'tick': 36, 'action': 'respond',
                      'actor': f'agent:{COMPANION}', 'proposal': 'late', 'decision': 'accept'}]
    original_register = Households.register_new_people
    original_draw = Lifecycle._draw

    def register(self, tick, *, genesis=False):
        declare = genesis and not self.store.query_one(
            'SELECT 1 FROM person_lifecycle WHERE agent_id=?', (WARD,))
        if declare:
            assert tick == 0
            assert self.store.scalar('SELECT age FROM agents WHERE id=?', (WARD,)) >= 65
            assert self.store.scalar("SELECT COUNT(*) FROM employments WHERE agent_id=? AND status='active'", (WARD,)) == 0
            # Declare age before the first origin and census; never rewrite a
            # recorded birth basis or jump the clock during the simulation.
            self.store.update('agents', WARD, age=17, retired=0, occupation='child')
        original_register(self, tick, genesis=genesis)
        if declare:
            household = self.membership(OWNER)['household_id']
            for actor, role in ((COMPANION, 'adult'), (WARD, 'dependent')):
                previous = self.membership(actor)
                self.store.update('household_memberships', previous['id'], left_tick=0,
                                  end_reason='declared_genesis_household')
                self.store.insert('household_memberships', household_id=household,
                                  agent_id=actor, role=role, joined_tick=0)
                self._dissolve_empty(0, previous['household_id'])
            self.store.insert('guardianships', child_agent_id=WARD, guardian_agent_id=OWNER,
                              started_tick=0, reason='declared_genesis_custody')
            self.store.execute('DELETE FROM social_ties WHERE agent_a=? OR agent_b=?', (OWNER, OWNER))
            self.store.insert('social_ties', agent_a=OWNER, agent_b=WARD, weight=100)
            self.store.log_event(0, 'declared_population_lifecycle_cohort', {
                'guardian_id': OWNER, 'companion_id': COMPANION, 'ward_id': WARD,
                'ward_genesis_age': 17, 'adult_day': ADULT_DAY, 'death_day': death_day,
                'inheritance_basis': 'social_tie'}, phase='GENESIS')
            self.check_invariants(0)

    def draw(self, tick, actor, mechanism):
        if mechanism == 'mortality':
            return 0.0 if actor == OWNER and tick == death_day else 1.0
        return original_draw(self, tick, actor, mechanism)

    monkeypatch.setattr(Households, 'register_new_people', register)
    monkeypatch.setattr(Lifecycle, '_draw', draw)

    def create(name, source=None):
        fresh = not (tmp_path/f'{name}.db').exists()
        world = scenario_world(entries, name, replay_source=source, config_overrides={
            'lifecycle': {'illness_onset_annual_young': 0, 'illness_onset_annual_old': 0},
            'budget': {'conversation_pairs': 0}})
        e, store = world.economy, world.store
        if fresh:
            assert store.scalar('SELECT birth_tick FROM person_lifecycle WHERE agent_id=?', (WARD,)) + 18*365 == ADULT_DAY
            e.firms.found_firm(0, OWNER, 'Declared majority issuer', 'manufacturing',
                               opening_capital_cents=10000, shares=11)
            e.ledger.create_account('agent', MOVER, 'fx', currency_code='IVC',
                                    opening_cents=37, label='Declared retained foreign holding')
            for actor in (OWNER, COMPANION, MOVER, WARD):
                store.update('agents', actor, population_tier='core', pinned_core=1,
                             cadence_json='{"act":1,"portfolio":9999,"career":9999,"news":9999}')
            e.city.initialize(0)
        firm = store.scalar("SELECT id FROM firms WHERE name='Declared majority issuer'")
        for purpose in ('decision', 'founder'):
            original = world.gateway.scripted.policies[purpose]
            def decisions(context, original=original):
                if source is not None:
                    raise AssertionError('replay must consume recorded decisions')
                actor = context.get('agent', {}).get('id')
                if actor not in (OWNER, COMPANION, MOVER, WARD):
                    return original(context)
                action = {'type': 'do_nothing'}
                if actor == WARD and context.get('tick') == ADULT_DAY:
                    action = {'type': 'set_price', 'firm_id': firm, 'price': 321}
                return {'reasoning': 'Declared population and majority boundary', 'actions': [action]}
            world.gateway.scripted.register(purpose, decisions)
        return world

    def facts(world, day):
        e, store = world.economy, world.store
        assert e.population.is_available(MOVER) is (day == 1 or day >= 5)
        assert store.scalar('SELECT checking_account_id FROM agents WHERE id=?', (MOVER,)) == mover_wallet
        assert store.scalar("SELECT balance_cents FROM accounts WHERE label='Declared retained foreign holding'") == 37
        assert store.scalar('SELECT COUNT(*) FROM llm_calls WHERE agent_id=? AND tick BETWEEN 2 AND 4', (MOVER,)) == 0
        assert store.scalar('SELECT age FROM agents WHERE id=?', (WARD,)) == (17 if day < ADULT_DAY else 18)
        assert e.population.is_available(WARD)
        firm = store.scalar("SELECT id FROM firms WHERE name='Declared majority issuer'")
        if day >= 35:
            movement = store.query_one("SELECT * FROM population_movements WHERE request_key='scenario:late'")
            assert movement is not None
            assert movement['status'] == ('pending' if day < ADULT_DAY else 'cancelled')
            if day >= ADULT_DAY:
                assert movement['closed_tick'] == ADULT_DAY
                assert movement['reason'] == 'household_snapshot_changed'
        if day >= 36:
            receipt = store.query_one("SELECT outcome FROM population_scenario_receipts WHERE input_key='late-consent'")
            assert receipt['outcome'] == 'accepted'
        if day >= death_day:
            assert store.scalar('SELECT alive FROM agents WHERE id=?', (OWNER,)) == 0
            assert e.exchange.shares_held(firm, 'agent', WARD) == 11
            assert store.scalar('SELECT founder_agent_id FROM firms WHERE id=?', (firm,)) == OWNER
            assert store.scalar('SELECT deaths FROM population_census WHERE tick=?', (death_day,)) == 1
            assert store.scalar("SELECT COUNT(*) FROM person_residence_events WHERE agent_id=? AND cause='departure'", (WARD,)) == 0
            if day < ADULT_DAY:
                assert e.households.guardian_id(WARD) == COMPANION
                assert e.business_control.operator_at(firm) == COMPANION
        if day >= ADULT_DAY:
            assert e.households.guardian_id(WARD) is None
            assert e.households.membership(WARD)['role'] == 'adult'
            assert e.business_control.operator_at(firm) == WARD
            assert store.scalar("SELECT COUNT(*) FROM events WHERE kind='adulthood' AND subject_id=? "
                "AND tick=? AND json_extract(payload_json,'$.endowment_cents')=0", (WARD, ADULT_DAY)) == 1
        if day >= ADULT_DAY:
            assert e.firms.product(e.firms.get(firm))['unit_price_cents'] == 321
            price = store.query_one(
                "SELECT model_call_id,result_json FROM action_proposals WHERE actor_id=? "
                "AND tick=? AND action_type='set_price'", (WARD, ADULT_DAY))
            assert price is not None and price['model_call_id'] is not None
            assert json.loads(price['result_json'])['ok']
        e.households.check_invariants(day)
        world.population_scenario.check_progress()
        assert e.ledger.reconcile()[0]

    world = create('lifecycle-source')
    mover_wallet = world.store.scalar('SELECT checking_account_id FROM agents WHERE id=?', (MOVER,))
    for day in range(1, ADULT_DAY + 2):
        if day == death_day - 1:
            asyncio.run(world.step(pause_after_phase='NIGHT_CLOSE'))
            scenario_world.close(world)
            world = create('lifecycle-source')
        asyncio.run(world.step())
        facts(world, day)
    source = Path(world.store.path)
    scenario_world.close(world)
    stamp = hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns
    replay = create('lifecycle-replay', source)
    for day in range(1, ADULT_DAY + 2):
        if day == death_day - 1:
            asyncio.run(replay.step(pause_after_phase='NIGHT_CLOSE'))
            scenario_world.close(replay)
            replay = create('lifecycle-replay', source)
        asyncio.run(replay.step())
        facts(replay, day)
    replay_path = Path(replay.store.path)
    scenario_world.close(replay)
    with closing(open_read_only_connection(source, require_closed=True)) as src, \
            closing(open_read_only_connection(replay_path, require_closed=True)) as dst:
        proof = verify_replay_connections(src, dst)
        assert proof['exact'], proof['differences']
        bundle = export_bundle(src, tmp_path/'source-export')
        assert validate_bundle(bundle, database=src)['contract_id'] == 'hash-contract-v8'
        assert src.execute('SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls').fetchone()[0] == 0
    assert (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns) == stamp
    assert not any(Path(str(source)+suffix).exists() for suffix in ('-wal','-shm','-journal'))

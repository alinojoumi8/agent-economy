"""Household identity, available local decisions and continuing outside care."""
import asyncio
from contextlib import closing
import hashlib
import json
from pathlib import Path

import pytest

from engine.households import HouseholdError, Households
from engine.daily_time import TimeBudgetError
from engine.keyed_random import stable_key
from engine.lifecycle import Lifecycle
from engine.population_history import ResidenceError
from engine.store import open_read_only_connection
from research.export_bundle import export_bundle, validate_bundle
from world.replay_verify import verify_replay_connections
from .test_population_civic_routines import CITY_CONFIG
from .test_population_movements import moving, join, child_household, propose, advance
from .test_population_residence_history import residence_case, contents
from .test_population_scenario import proposal, scenario_world
from .test_semantics20_estate_cases import estate_case


def corrupt_person(c, person):
    event = c.e.store.scalar('SELECT event_id FROM person_residence_events WHERE agent_id=? ORDER BY id LIMIT 1', (person,))
    c.e.store.update('events', event, payload_json='{}')


def outside_pair(c):
    join(c)
    movement = propose(c, [c.person, c.heir])
    c.e.population.respond(0, c.heir, movement, 'accept')
    advance(c, 1)
    assert c.e.population.settle(1, movement)['status'] == 'applied'
    assert not c.e.population.is_available(c.person)


def test_outside_adult_cannot_split_a_household_through_the_direct_service(moving):
    c = moving
    outside_pair(c)
    before = contents(c.e.store)
    with pytest.raises(HouseholdError, match='local resident'):
        c.e.households.split_household(1, c.person)
    assert contents(c.e.store) == before


def test_family_separation_validates_the_child_before_recording_a_decision(moving):
    c = moving
    child = child_household(c)
    corrupt_person(c, child)
    before = contents(c.e.store)
    with pytest.raises(ResidenceError):
        c.e.families.propose(1, c.person, 'separation', 'checked-ward')
    assert contents(c.e.store) == before


def test_named_local_care_plan_validates_the_child_before_recording(moving):
    c = moving
    child = child_household(c)
    corrupt_person(c, child)
    before = contents(c.e.store)
    with pytest.raises(ResidenceError):
        c.e.daily_time.submit_plan(1, c.person, {'type':'set_time_plan',
            'request_key':'checked-care', 'work_minutes':0, 'care_minutes':120,
            'care_child_ids':[child]})
    assert contents(c.e.store) == before


def test_custody_reconciliation_validates_the_child_before_assigning_a_guardian(moving):
    c = moving
    child = child_household(c)
    c.e.store.execute("UPDATE guardianships SET ended_tick=1,end_reason='declared_fixture_gap' WHERE child_agent_id=?", (child,))
    corrupt_person(c, child)
    before = contents(c.e.store)
    with pytest.raises(ResidenceError):
        c.e.households.reconcile_custody(1)
    assert contents(c.e.store) == before


def test_local_separation_keeps_wards_and_their_submitted_care_is_delivered(moving):
    c = moving
    child = child_household(c)
    prior = c.e.households.membership(c.person)['household_id']
    result = c.e.families.propose(1, c.person, 'separation', 'local-wards')
    assert result['status'] == 'applied'
    assert c.e.households.membership(c.person)['household_id'] != prior
    assert c.e.households.membership(c.person)['household_id'] == c.e.households.membership(child)['household_id']
    assert c.e.households.membership(c.heir)['household_id'] == prior
    required = c.e.households.p['care_minutes_per_child']
    plan = c.e.daily_time.submit_plan(1, c.person, {'type':'set_time_plan', 'request_key':'ward-care',
        'work_minutes':0, 'care_minutes':required, 'care_child_ids':[child]})
    assert plan['ok'] and plan['effective_tick'] == 2
    advance(c, 2)
    c.e.daily_time.prepare_day(2)
    care = c.e.store.query_one('SELECT * FROM child_care_days WHERE tick=2 AND child_id=?', (child,))
    assert care['required_minutes'] == care['delivered_minutes'] == required
    assert c.e.households.guardian_id(child) == c.person
    assert c.e.ledger.reconcile()[0]


def test_custody_checks_the_replacement_adult_before_changing_any_relation(moving):
    c = moving
    child = child_household(c)
    # A declared transitional membership gap, as reconciliation sees after a move.
    destination = c.e.store.insert('households', region_id=1, formed_tick=1, policy='guardian_basic_needs_v1')
    c.e.families._move_members(1, [{'agent_id':c.person}], destination, 'declared_fixture_move')
    corrupt_person(c, c.heir)
    before = contents(c.e.store)
    with pytest.raises(ResidenceError):
        c.e.households.reconcile_custody(1)
    assert contents(c.e.store) == before


def test_late_custody_failure_rolls_back_the_new_guardian_and_control_changes(moving, monkeypatch):
    c = moving
    child = child_household(c)
    c.e.store.execute("UPDATE guardianships SET ended_tick=1,end_reason='declared_fixture_gap' WHERE child_agent_id=?", (child,))
    before = contents(c.e.store)
    def fail(tick):
        assert c.e.households.guardian_id(child) == c.person
        raise RuntimeError('declared late custody fault')
    monkeypatch.setattr(c.e.project_rights, 'refresh', fail)
    with pytest.raises(RuntimeError, match='declared late custody fault'):
        c.e.households.reconcile_custody(1)
    assert contents(c.e.store) == before


def test_residence_reconciliation_rolls_back_earlier_splits_if_a_later_person_is_invalid(moving):
    c = moving
    join(c)
    c.e.store.insert('regions', id=2, region_key='next', name='Next', currency_code='USD',
        population_target=5, specialization_json='{}', x=1, y=1, legal_ruleset='test')
    c.e.store.execute('UPDATE agents SET region_id=2 WHERE id IN (?,?)', (c.person, c.heir))
    corrupt_person(c, c.heir)
    before = contents(c.e.store)
    with pytest.raises(ResidenceError):
        c.e.households.reconcile_residence(1)
    assert contents(c.e.store) == before


def test_outside_household_keeps_custody_without_local_time_or_consumption(moving):
    c = moving
    child = child_household(c)
    movement = propose(c, [c.person,c.heir,child], tick=1, due=2,
        care=[{'child_id':child,'guardian_id':c.person}])
    c.e.population.respond(1, c.heir, movement, 'accept')
    advance(c, 2)
    assert c.e.population.settle(2, movement)['status'] == 'applied'
    before = contents(c.e.store)
    c.e.households.reconcile_custody(2)
    assert contents(c.e.store) == before
    assert c.e.households.guardian_id(child) == c.person
    assert c.e.households.decision_context(c.person, 2)['responsible_child_count'] == 1
    assert c.e.daily_time.care_targets(c.person) == []
    c.e.daily_time.prepare_day(2)
    c.e.households.provision_children(2)
    for table in ('time_days','child_care_days','child_needs'):
        assert c.e.store.scalar(f'SELECT COUNT(*) FROM {table} WHERE tick=2') == 0


@pytest.mark.parametrize('operation', ['custody','family','time_plan'])
def test_mixed_residence_membership_cannot_authorize_local_family_or_care_work(moving, operation):
    c = moving
    child = child_household(c)
    movement = propose(c, [c.person,child], tick=1, due=2,
        care=[{'child_id':child,'guardian_id':c.person}])
    c.e.population.respond(1, c.heir, movement, 'accept')
    advance(c, 2)
    assert c.e.population.settle(2, movement)['status'] == 'applied'
    # Inject invalid membership only; actual residence evidence stays unchanged.
    destination = c.e.households.membership(child)['household_id']
    c.e.families._move_members(2, [{'agent_id':c.heir}], destination, 'declared_mixed_membership_fault')
    before = contents(c.e.store)
    with pytest.raises(TimeBudgetError if operation == 'time_plan' else HouseholdError):
        if operation == 'custody':
            c.e.households.reconcile_custody(2)
        elif operation == 'family':
            c.e.families.propose(2, c.heir, 'separation', 'mixed-family')
        else:
            c.e.daily_time.submit_plan(2, c.heir, {'type':'set_time_plan','request_key':'mixed-care',
                'work_minutes':0,'care_minutes':120,'care_child_ids':[child]})
    assert contents(c.e.store) == before


@pytest.mark.parametrize('operation', ['outside_split','family','time_plan','custody'])
def test_legacy_component_keeps_original_household_and_care_behavior(moving, operation):
    c = moving
    if operation == 'outside_split':
        outside_pair(c)
        original = c.e.households.membership(c.person)['household_id']
        c.e.engine_semantics_version = 20
        assert c.e.households.split_household(1, c.person) != original
        return
    child = child_household(c)
    if operation == 'custody':
        c.e.store.execute("UPDATE guardianships SET ended_tick=1,end_reason='declared_fixture_gap' WHERE child_agent_id=?", (child,))
    corrupt_person(c, child)
    # This is a legacy component check; actual old worlds have separate replay tests.
    c.e.engine_semantics_version = 20
    if operation == 'family':
        assert c.e.families.propose(1, c.person, 'separation', 'legacy-separation')['status'] == 'applied'
    elif operation == 'time_plan':
        assert c.e.daily_time.submit_plan(1, c.person, {'type':'set_time_plan',
            'request_key':'legacy-care', 'work_minutes':0, 'care_minutes':120, 'care_child_ids':[child]})['ok']
    else:
        c.e.households.reconcile_custody(1)
        assert c.e.households.guardian_id(child) == c.person


def test_outside_guardian_death_successor_care_and_return_in_city_replay(scenario_world, tmp_path, monkeypatch):
    parent, companion = 27, 30
    child_key = stable_key('birth', 1, f'agent:{parent}')
    leaving = proposal(tick=1, due=3, actor=f'agent:{parent}')
    leaving['members'] += [f'agent:{companion}', child_key]
    leaving['care_plan'] = [{'child':child_key, 'guardian':f'agent:{parent}'}]
    returning = proposal('back', tick=5, due=7, actor=f'agent:{companion}', cause='return')
    returning['members'].append(child_key)
    returning['destination_region_id'] = 2
    returning['care_plan'] = [{'child':child_key, 'guardian':f'agent:{companion}'}]
    entries = [leaving, {'key':'assent','tick':2,'action':'respond','actor':f'agent:{companion}',
                        'proposal':'out','decision':'accept'}, returning]
    original_register, original_draw = Households.register_new_people, Lifecycle._draw

    def register(self, tick, *, genesis=False):
        declare = genesis and not self.store.query_one('SELECT 1 FROM person_lifecycle WHERE agent_id=?', (parent,))
        original_register(self, tick, genesis=genesis)
        if declare:
            assert tick == 0
            assert self.store.scalar('SELECT COUNT(*) FROM agents WHERE id IN (?,?) AND region_id=2', (parent,companion)) == 2
            home = self.membership(parent)['household_id']
            self.e.families._move_members(0, [{'agent_id':companion}], home, 'declared_genesis_care_household')
            self._event(0, 'declared_care_household', parent,
                {'companion_id':companion,'birth_day':1,'departure_day':3,'guardian_death_day':4,'return_day':7})
            self.check_invariants(0)

    def draw(self, tick, actor, mechanism):
        if mechanism == 'mortality':
            return 0.0 if actor == parent and tick == 4 else 1.0
        return original_draw(self, tick, actor, mechanism)

    monkeypatch.setattr(Households, 'register_new_people', register)
    monkeypatch.setattr(Lifecycle, '_draw', draw)

    def create(name, source=None):
        world = scenario_world(entries, name, replay_source=source,
            scheduled_births=[{'tick':1,'parent_agent_id':parent}], config_overrides=CITY_CONFIG)
        for purpose in ('decision','founder'):
            original = world.gateway.scripted.policies[purpose]
            def decide(context, original=original):
                if source is not None:
                    raise AssertionError('replay must consume recorded responses')
                if context.get('agent', {}).get('id') in (parent,companion):
                    return {'actions':[{'type':'do_nothing'}], 'reasoning':'Declared household care journey.'}
                return original(context)
            world.gateway.scripted.policies[purpose] = decide
        return world

    def advance_world(world, name, source=None):
        for day in range(1,8):
            if day in (3,4,7):
                paused = asyncio.run(world.step(pause_after_phase='MORNING' if day == 7 else 'NIGHT_CLOSE'))
                assert paused['active_tick'] == day
                scenario_world.close(world)
                world = create(name, source)
            asyncio.run(world.step())
            assert world.store.tick == day, dict(world.store.get_meta())
            store, e = world.store, world.economy
            child = store.scalar("SELECT agent_id FROM person_lifecycle WHERE birth_key='birth:1:27'")
            assert child is not None
            assert e.households.guardian_id(child) == (parent if day < 4 else companion)
            assert e.population.is_local(child, day) is (day < 3 or day == 7)
            care = store.query_one('SELECT required_minutes,delivered_minutes FROM child_care_days WHERE child_id=? AND tick=?', (child,day))
            needs = store.query_one('SELECT required_units,purchased_units,spent_cents FROM child_needs WHERE child_agent_id=? AND tick=?', (child,day))
            if 3 <= day <= 6:
                assert care is None and needs is None
                assert store.scalar('SELECT COUNT(*) FROM time_days WHERE agent_id IN (?,?) AND tick=?', (child,companion,day)) == 0
                assert store.scalar('SELECT COUNT(*) FROM llm_calls WHERE agent_id IN (?,?) AND tick=?', (parent,companion,day)) == 0
            else:
                assert care and care['required_minutes'] > 0 and care['required_minutes'] == care['delivered_minutes']
                assert needs and needs['required_units'] == 1
                if day < 3:
                    assert needs['purchased_units'] == 1 and needs['spent_cents'] == 874
                else:
                    # Actual stock is exhausted by adult purchases before the
                    # automatic household purchase. Care still gets delivered.
                    assert needs['purchased_units'] == needs['spent_cents'] == 0
                    assert e.ledger.balance(e.ledger.agent_checking_id(companion)) > 0
                    assert store.scalar("SELECT SUM(inventory) FROM firms WHERE sector='food' AND region_id=2") == 0
                    assert store.scalar("SELECT COUNT(*) FROM events WHERE tick=7 AND kind='goods_sale' "
                        "AND json_extract(payload_json,'$.firm_id')=1") > 0
            assert store.scalar('SELECT COUNT(*) FROM llm_calls WHERE agent_id=?', (child,)) == 0
            e.households.check_invariants(day)
            assert e.ledger.reconcile()[0]
        return world

    world = create('care-source')
    accounts = [tuple(row) for row in world.store.query('SELECT id,checking_account_id,savings_account_id FROM agents WHERE id IN (?,?) ORDER BY id', (parent,companion))]
    world = advance_world(world, 'care-source')
    store = world.store
    assert [tuple(row) for row in store.query('SELECT id,checking_account_id,savings_account_id FROM agents WHERE id IN (?,?) ORDER BY id', (parent,companion))] == accounts
    assert store.scalar('SELECT COUNT(*) FROM agents') == 48
    assert store.scalar('SELECT COUNT(*) FROM agents WHERE alive=1') == 47
    assert store.scalar('SELECT departures FROM population_resident_census WHERE tick=3') == 3
    assert store.scalar('SELECT returns FROM population_resident_census WHERE tick=7') == 2
    assert store.scalar('SELECT closing_residents FROM population_resident_census WHERE tick=7') == 47
    assert store.scalar("SELECT COUNT(*) FROM population_movements WHERE status='applied'") == 2
    facts = {'care':[dict(row) for row in store.query('SELECT * FROM child_care_days ORDER BY tick,child_id')],
             'needs':[dict(row) for row in store.query('SELECT * FROM child_needs ORDER BY tick,child_agent_id')],
             'custody':[dict(row) for row in store.query('SELECT * FROM guardianships ORDER BY id')]}
    source = Path(store.path)
    scenario_world.close(world)
    stamp = hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns
    replay = advance_world(create('care-replay',source), 'care-replay', source)
    target = Path(replay.store.path)
    scenario_world.close(replay)
    with closing(open_read_only_connection(source, require_closed=True)) as src, \
            closing(open_read_only_connection(target, require_closed=True)) as dst:
        proof = verify_replay_connections(src,dst)
        assert proof['exact'], proof['differences']
        for database, directory in ((src,'source-export'),(dst,'replay-export')):
            manifest = validate_bundle(export_bundle(database,tmp_path/directory),database=database)
            assert manifest['contract_id'] == 'hash-contract-v8'
            assert database.execute('SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls').fetchone()[0] == 0
            assert database.execute("SELECT COUNT(*) FROM llm_calls WHERE provider<>'scripted'").fetchone()[0] == 0
    assert (hashlib.sha256(source.read_bytes()).hexdigest(),source.stat().st_mtime_ns) == stamp
    assert not any(Path(str(source)+suffix).exists() for suffix in ('-wal','-shm','-journal'))
    (tmp_path/'care-observations.json').write_text(json.dumps(facts,indent=2,sort_keys=True)+'\n')

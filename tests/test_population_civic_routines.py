"""Current professional availability in civic applications and permit review."""
import asyncio
from contextlib import closing
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


LAWYER, APPLICANT = 9, 23
CITY_CONFIG = {'living_world': {'core_agents': 100}, 'budget': {'conversation_pairs': 0},
               'lifecycle': {'illness_onset_annual_young': 0, 'illness_onset_annual_old': 0}}


def application(name='Available professional permit'):
    return {'type': 'apply_business_permit', 'name': name, 'sector': 'repair',
            'lawyer_agent_id': LAWYER, 'opening_capital': 500,
            'business_idea': {'mission': 'Maintain local equipment.',
                'customer_problem': 'Customers need working equipment.',
                'offering': 'Local equipment repair.'}}


def corrupt_lawyer_origin(world):
    event = world.store.scalar('SELECT event_id FROM person_residence_events WHERE agent_id=? ORDER BY id LIMIT 1', (LAWYER,))
    world.store.update('events', event, payload_json='{}')


@pytest.mark.parametrize('state', ['outside', 'missing_history', 'minor'])
def test_permit_application_validates_lawyer_before_fee_or_case(scenario_world, state):
    world = scenario_world([proposal(actor=f'agent:{LAWYER}')] if state == 'outside' else [],
                           config_overrides=CITY_CONFIG)
    if state == 'outside':
        for _ in range(2):
            asyncio.run(world.step())
        assert not world.economy.population.is_available(LAWYER)
    elif state == 'missing_history':
        corrupt_lawyer_origin(world)
    else:
        world.store.update('agents', LAWYER, age=17)
    before = contents(world.store)
    if state == 'missing_history':
        with pytest.raises(ResidenceError):
            world.economy.city.apply_business_permit(world.store.tick, APPLICANT, application())
    else:
        result = world.economy.city.apply_business_permit(world.store.tick, APPLICANT, application())
        assert not result['ok'], result
    assert contents(world.store) == before


@pytest.mark.parametrize('surface', ['clerk', 'automatic'])
def test_clerk_cannot_approve_with_missing_lawyer_residence_history(scenario_world, surface):
    world = scenario_world([], config_overrides=CITY_CONFIG)
    city = world.economy.city
    result = city.apply_business_permit(0, APPLICANT, application())
    assert result['ok'], result
    city.finalize(0)
    asyncio.run(world.step())
    case_id = result['case_id']
    assert world.store.scalar('SELECT status FROM service_cases WHERE id=?', (case_id,)) == 'under_review'
    clerk = world.store.scalar("SELECT assigned_agent_id FROM institution_tasks WHERE source_case_id=? AND status='assigned'", (case_id,))
    assert clerk is not None
    corrupt_lawyer_origin(world)
    before = contents(world.store)
    with pytest.raises(ResidenceError):
        if surface == 'clerk':
            city.decide_business_permit(2, clerk, case_id, 'approve', 'market_capacity_supported')
        else:
            city._resolve_submitted_cases(2)
    assert contents(world.store) == before


@pytest.mark.parametrize('state', ['outside', 'minor'])
def test_legacy_application_keeps_its_original_professional_validation_stage(scenario_world, state):
    world = scenario_world([proposal(actor=f'agent:{LAWYER}')] if state == 'outside' else [],
                           config_overrides=CITY_CONFIG)
    if state == 'outside':
        for _ in range(2):
            asyncio.run(world.step())
    else:
        world.store.update('agents', LAWYER, age=17)
    # Component comparison only: the actual older-world suites cover replay.
    world.economy.engine_semantics_version = 20
    world.economy.city.engine_semantics_version = 20
    result = world.economy.city.apply_business_permit(world.store.tick, APPLICANT, application())
    assert result['ok'], result
    case = world.store.query_one('SELECT * FROM service_cases WHERE id=?', (result['case_id'],))
    assert world.economy.city._mechanical_failure(case) is None
    assert case['fee_cents'] == 2500
    assert world.economy.ledger.reconcile()[0]


def test_returned_professional_and_successor_complete_real_city_workflow(scenario_world, tmp_path):
    entries = [proposal('lawyer-out', actor=f'agent:{LAWYER}'),
        proposal('lawyer-back', tick=3, due=5, actor=f'agent:{LAWYER}', cause='return'),
        proposal('clerk-out', tick=2, due=4, actor='agent:45'),
        proposal('clerk-back', tick=6, due=8, actor='agent:45', cause='return')]
    new_application = application('Returned Civic Workshop')
    formation = {**new_application, 'type': 'found_company'}

    def create(name, source=None):
        fresh = not (tmp_path/f'{name}.db').exists()
        world = scenario_world(entries, name, replay_source=source, config_overrides=CITY_CONFIG)
        if fresh:
            # Declare one existing unemployed adult for the office vacancy.
            # The census and account identities are unchanged; no worker is created.
            assert world.store.scalar('SELECT COUNT(*) FROM agents') == 47
            assert world.store.scalar("SELECT agent_id FROM agency_staff WHERE active=1 AND region_id=1") == 45
            world.store.execute("UPDATE employments SET status='ended',end_tick=0 WHERE agent_id=24 AND status='active'")
            world.store.update('agents', 24, employer_id=None)
            world.store.update('agents', APPLICANT, population_tier='core', pinned_core=1,
                cadence_json='{"act":1,"portfolio":9999,"career":9999,"news":9999}')
            world.store.log_event(0, 'declared_civic_availability_cohort', {
                'applicant_id': APPLICANT, 'lawyer_id': LAWYER, 'clerk_id': 45,
                'available_successor_id': 24, 'application_days': [1, 3, 6],
                'company_formation_day': 9, 'applicant_act_cadence': 1}, phase='GENESIS')
            world.store.commit()
        for purpose in ('decision', 'founder', 'permit_clerk'):
            original = world.gateway.scripted.policies[purpose]
            def decisions(context, original=original, purpose=purpose):
                if source is not None:
                    raise AssertionError('replay must use recorded civic decisions')
                actor, tick = context.get('agent', {}).get('id'), context.get('tick')
                if actor != APPLICANT and purpose != 'permit_clerk':
                    return original(context)
                action = {'type': 'do_nothing'}
                if actor == APPLICANT:
                    if tick == 1:
                        action = application('Ended Lawyer Permit')
                    elif tick in (3, 6):
                        action = new_application
                    elif tick == 9:
                        action = formation
                    else:
                        action = world.economy.city.required_appointment_action(actor, tick) or action
                else:
                    choices = world.economy.city.clerk_work(actor, tick)['eligible_actions']
                    action = next((item for item in choices if item['decision'] == 'approve'), action)
                return {'actions': [action], 'reasoning': 'Declared civic availability workflow.'}
            world.gateway.scripted.policies[purpose] = decisions
        return world

    world = create('civic-source')
    identities = [tuple(row) for row in world.store.query(
        'SELECT id,checking_account_id,savings_account_id FROM agents ORDER BY id')]
    original_accounts = {row['id']: tuple(row) for row in world.store.query(
        "SELECT id,owner_type,owner_id,currency_code FROM accounts WHERE owner_type='agent'")}
    for day in range(1, 10):
        if day in (4, 8):
            asyncio.run(world.step(pause_after_phase='NIGHT_CLOSE' if day == 4 else 'EXECUTION'))
            scenario_world.close(world)
            world = create('civic-source')
        asyncio.run(world.step())
        assert world.economy.ledger.reconcile()[0]
        for actor, outside in ((LAWYER, 2 <= day <= 4), (45, 4 <= day <= 7)):
            assert world.economy.population.is_available(actor) is not outside
            assert bool(world.store.scalar('SELECT COUNT(*) FROM effective_presence WHERE tick=? AND agent_id=?', (day, actor))) is not outside
            if outside:
                assert world.store.scalar('SELECT COUNT(*) FROM llm_calls WHERE tick=? AND agent_id=?', (day, actor)) == 0
                assert world.store.scalar('SELECT COUNT(*) FROM time_days WHERE tick=? AND agent_id=?', (day, actor)) == 0
        if day >= 2:
            assert world.store.scalar("SELECT status FROM service_cases WHERE business_name='Ended Lawyer Permit'") == 'abandoned'
        if 3 <= day <= 5:
            assert world.store.scalar('SELECT COUNT(*) FROM service_cases') == 1
            assert world.store.scalar("SELECT COUNT(*) FROM transactions WHERE kind='business_permit_fee'") == 1
        if day >= 4:
            assert world.store.scalar("SELECT agent_id FROM agency_staff WHERE active=1 AND region_id=1") == 24
        if day in (6, 7, 8, 9):
            assert world.store.scalar('SELECT status FROM service_cases WHERE business_name=?', (new_application['name'],)) == {
                6: 'appointment_scheduled', 7: 'under_review', 8: 'approved', 9: 'approved'}[day]
    current_identities = [tuple(row) for row in world.store.query(
        'SELECT id,checking_account_id,savings_account_id FROM agents ORDER BY id')]
    assert [row[0] for row in identities] == [row[0] for row in current_identities]
    cohort = {LAWYER, APPLICANT, 24, 45}
    assert [row for row in identities if row[0] in cohort] == [row for row in current_identities if row[0] in cohort]
    # Other people may migrate internally and select a different currency wallet.
    # Their original wallets and financial ownership still have to remain intact.
    current_accounts = {row['id']: tuple(row) for row in world.store.query(
        "SELECT id,owner_type,owner_id,currency_code FROM accounts WHERE owner_type='agent'")}
    assert all(current_accounts.get(key) == value for key, value in original_accounts.items())
    assert world.store.scalar('SELECT COUNT(*) FROM agents') == 47
    assert world.store.scalar("SELECT COUNT(*) FROM action_proposals WHERE tick=3 AND actor_id=? AND action_type='apply_business_permit'", (APPLICANT,)) == 1
    rejected = world.store.query_one("SELECT validation_status,result_json FROM action_proposals WHERE tick=3 AND actor_id=? AND action_type='apply_business_permit'", (APPLICANT,))
    assert rejected['validation_status'] == 'rejected'
    assert json.loads(rejected['result_json']) == {'ok': False, 'reason': 'lawyer_unavailable'}
    fees = world.store.query("SELECT id FROM transactions WHERE kind='business_permit_fee' ORDER BY id")
    assert len(fees) == 2
    account = world.store.scalar('SELECT checking_account_id FROM agents WHERE id=?', (APPLICANT,))
    for fee in fees:
        assert world.store.scalar('SELECT delta_cents FROM ledger_entries WHERE txn_id=? AND account_id=?', (fee['id'], account)) == -2500
    firm = world.store.query_one('SELECT * FROM firms WHERE name=?', (new_application['name'],))
    assert firm is not None and firm['founded_tick'] == 9 and firm['founder_agent_id'] == APPLICANT
    capital = world.store.query("SELECT id FROM transactions WHERE kind='equity_investment' AND memo=?", (f"found {new_application['name']}",))
    assert len(capital) == 1
    assert {row['account_id']: row['delta_cents'] for row in world.store.query(
        'SELECT account_id,delta_cents FROM ledger_entries WHERE txn_id=?', (capital[0]['id'],))} == {account: -500, firm['account_id']: 500}
    assert world.store.scalar('SELECT currency_code FROM accounts WHERE id=?', (firm['account_id'],)) == 'NSD'
    issuance = world.store.query_one("SELECT * FROM share_movements WHERE firm_id=? AND movement_type='founder_issuance'", (firm['id'],))
    assert issuance['qty'] == 1000 and issuance['price_cents'] is None and issuance['amount_cents'] == 0
    assert world.store.scalar("SELECT status FROM civic_authorizations WHERE case_id=(SELECT id FROM service_cases WHERE business_name=?)", (new_application['name'],)) == 'consumed'
    source = Path(world.store.path)
    scenario_world.close(world)
    stamp = hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns
    replay = create('civic-replay', source)
    for day in range(1, 10):
        if day in (4, 8):
            asyncio.run(replay.step(pause_after_phase='NIGHT_CLOSE' if day == 4 else 'EXECUTION'))
            scenario_world.close(replay)
            replay = create('civic-replay', source)
        asyncio.run(replay.step())
        assert replay.economy.ledger.reconcile()[0]
    target = Path(replay.store.path)
    scenario_world.close(replay)
    with closing(open_read_only_connection(source, require_closed=True)) as src, \
            closing(open_read_only_connection(target, require_closed=True)) as dst:
        proof = verify_replay_connections(src, dst)
        assert proof['exact'], proof['differences']
        for database, directory in ((src, 'source-export'), (dst, 'replay-export')):
            manifest = validate_bundle(export_bundle(database, tmp_path/directory), database=database)
            assert manifest['contract_id'] == 'hash-contract-v8'
            assert database.execute('SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls').fetchone()[0] == 0
            assert database.execute("SELECT COUNT(*) FROM llm_calls WHERE provider<>'scripted'").fetchone()[0] == 0
    assert (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns) == stamp
    assert not any(Path(str(source)+suffix).exists() for suffix in ('-wal', '-shm', '-journal'))

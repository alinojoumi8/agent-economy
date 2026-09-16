"""Available professional services at company-formation boundaries."""
import asyncio
from contextlib import closing
import hashlib
import json
from pathlib import Path

import pytest

from engine.actions import ActionExecutor
from engine.population_history import ResidenceError
from engine.store import open_read_only_connection
from agents.participant import ParticipantError
from research.export_bundle import export_bundle, validate_bundle
from world.replay_verify import verify_replay_connections
from .test_population_authority import finance
from .test_population_residence_history import contents
from .test_population_runtime import RUNTIME_CONFIG
from .test_population_scenario import proposal, scenario_world


LAWYER = 9
FOUNDER = 23
ALTERNATIVE = 24


def formation_world(create, *, native=False, alternative=False, departing=LAWYER):
    config = {**RUNTIME_CONFIG, 'entrepreneurship': {'enabled': native,
        'activation_tick': 3, 'new_arrivals_only': False, 'minimum_ticks_after_arrival': 0,
        'review_interval_ticks': 2, 'allow_employed_applicants': True,
        'minimum_age': 18, 'minimum_risk_tolerance': 0, 'minimum_opening_capital_cents': 500,
        'maximum_opening_capital_cents': 500, 'personal_reserve_cents': 0,
        'eligible_sectors': ['repair'], 'maximum_active_competitors': 100}}
    entries = [proposal(actor=f'agent:{departing}')] if departing is not None else []
    world = create(entries, config_overrides=config)
    if alternative:
        # A declared existing local professional, not a newly minted person.
        world.store.update('agents', ALTERNATIVE, occupation='lawyer')
        world.store.commit()
    for _ in range(2):
        asyncio.run(world.step())
    if departing is not None:
        assert not world.economy.population.is_available(departing)
    return world


def test_found_company_rejects_outside_lawyer_before_firm_or_capital_changes(scenario_world):
    world = formation_world(scenario_world)
    before = finance(world.economy)
    companies = world.store.scalar('SELECT COUNT(*) FROM firms')
    result = ActionExecutor(world.economy).execute_action(3, FOUNDER, {
        'type': 'found_company', 'name': 'Outside professional probe', 'sector': 'repair',
        'lawyer_agent_id': LAWYER, 'opening_capital': 500})
    assert not result['ok']
    assert finance(world.economy) == before
    assert world.store.scalar('SELECT COUNT(*) FROM firms') == companies
    assert world.economy.ledger.reconcile()[0]


def test_manual_formation_catalog_excludes_outside_lawyer(scenario_world):
    world = formation_world(scenario_world)
    before = contents(world.store)
    catalog = world.runtime.participant.action_catalog(FOUNDER)
    formation = next(item for item in catalog if item['type'] == 'found_company')
    field = next(field for field in formation['fields'] if field['name'] == 'lawyer_agent_id')
    assert LAWYER not in {option['value'] for option in field['options']}
    assert not formation['enabled']
    assert contents(world.store) == before


def test_native_opportunity_chooses_existing_local_lawyer(scenario_world):
    world = formation_world(scenario_world, native=True, alternative=True)
    founder = world.store.query_one('SELECT * FROM agents WHERE id=?', (FOUNDER,))
    balance = world.economy.ledger.balance(founder['checking_account_id'])
    before = contents(world.store)
    opportunity = world.runtime.participant.ctx._entrepreneurship_opportunity(
        founder, 3, {'state': {'employed': True, 'checking_balance': balance}})
    assert opportunity is not None
    assert opportunity['lawyer']['agent_id'] == ALTERNATIVE
    assert opportunity['action']['lawyer_agent_id'] == ALTERNATIVE
    assert contents(world.store) == before


@pytest.mark.parametrize('departing', [LAWYER, FOUNDER])
def test_native_formation_requires_available_founder_and_professional(scenario_world, departing):
    world = formation_world(scenario_world, native=True, departing=departing)
    founder = world.store.query_one('SELECT * FROM agents WHERE id=?', (FOUNDER,))
    before = contents(world.store)
    opportunity = world.runtime.participant.ctx._entrepreneurship_opportunity(
        founder, 3, {'state': {'employed': False, 'checking_balance': 100_000}})
    assert opportunity is None
    assert contents(world.store) == before


def test_missing_lawyer_history_rejects_incorporation_without_capital_effects(scenario_world):
    world = formation_world(scenario_world, departing=None)
    event = world.store.scalar('SELECT event_id FROM person_residence_events WHERE agent_id=?', (LAWYER,))
    world.store.update('events', event, payload_json='{}')
    before = finance(world.economy)
    companies = world.store.scalar('SELECT COUNT(*) FROM firms')
    result = ActionExecutor(world.economy).execute_action(3, FOUNDER, {
        'type': 'found_company', 'name': 'Missing professional history', 'sector': 'repair',
        'lawyer_agent_id': LAWYER, 'opening_capital': 500})
    assert not result['ok']
    assert finance(world.economy) == before
    assert world.store.scalar('SELECT COUNT(*) FROM firms') == companies


@pytest.mark.parametrize('surface', ['catalog', 'native'])
def test_later_missing_professional_history_precedes_catalog_or_opportunity(scenario_world, surface):
    world = formation_world(scenario_world, native=surface == 'native', alternative=True, departing=None)
    event = world.store.scalar('SELECT event_id FROM person_residence_events WHERE agent_id=?', (ALTERNATIVE,))
    world.store.update('events', event, payload_json='{}')
    before = contents(world.store)
    with pytest.raises(ResidenceError):
        if surface == 'catalog':
            world.runtime.participant.action_catalog(FOUNDER)
        else:
            founder = world.store.query_one('SELECT * FROM agents WHERE id=?', (FOUNDER,))
            world.runtime.participant.ctx._entrepreneurship_opportunity(
                founder, 3, {'state': {'employed': False, 'checking_balance': 100_000}})
    assert contents(world.store) == before


def test_legacy_formation_keeps_its_pre_population_professional_rule(scenario_world):
    world = formation_world(scenario_world, native=True, alternative=True)
    builder = world.runtime.participant.ctx
    builder.engine_semantics_version = 20
    founder = world.store.query_one('SELECT * FROM agents WHERE id=?', (FOUNDER,))
    opportunity = builder._entrepreneurship_opportunity(
        founder, 3, {'state': {'employed': False, 'checking_balance': 100_000}})
    assert opportunity['lawyer']['agent_id'] == LAWYER
    world.economy.config['entrepreneurship']['enabled'] = False
    participant = world.runtime.participant
    participant.engine_semantics_version = 20
    formation = next(item for item in participant.action_catalog(FOUNDER) if item['type'] == 'found_company')
    field = next(field for field in formation['fields'] if field['name'] == 'lawyer_agent_id')
    assert LAWYER in {option['value'] for option in field['options']}
    executor = ActionExecutor(world.economy)
    executor.engine_semantics_version = 20
    result = executor.execute_action(3, FOUNDER, {'type': 'found_company', 'name': 'Legacy rule probe',
        'sector': 'repair', 'lawyer_agent_id': LAWYER, 'opening_capital': 500})
    assert result['ok']
    assert world.economy.ledger.reconcile()[0]


@pytest.mark.parametrize('fault', ['outside', 'missing_history'])
def test_direct_permit_application_requires_available_applicant_before_fee(scenario_world, fault):
    entries = [proposal(actor=f'agent:{FOUNDER}')] if fault == 'outside' else []
    world = scenario_world(entries, config_overrides={'entrepreneurship': {'enabled': False}})
    for _ in range(2):
        asyncio.run(world.step())
    if fault == 'missing_history':
        event = world.store.scalar('SELECT event_id FROM person_residence_events WHERE agent_id=?', (FOUNDER,))
        world.store.update('events', event, payload_json='{}')
    action = {'type': 'apply_business_permit', 'name': 'Absent applicant permit', 'sector': 'repair',
        'lawyer_agent_id': LAWYER, 'opening_capital': 500,
        'business_idea': {'mission': 'Repair local equipment', 'customer_problem': 'Broken equipment',
                          'offering': 'Equipment repairs'}}
    before = contents(world.store)
    if fault == 'outside':
        result = world.economy.city.apply_business_permit(3, FOUNDER, action)
        assert not result['ok']
    else:
        with pytest.raises(ResidenceError):
            world.economy.city.apply_business_permit(3, FOUNDER, action)
    assert contents(world.store) == before


def test_returning_applicant_can_pay_one_current_permit_fee(scenario_world):
    entries = [proposal(actor=f'agent:{FOUNDER}'),
        proposal('back', actor=f'agent:{FOUNDER}', tick=3, due=5, cause='return')]
    world = scenario_world(entries, config_overrides={'entrepreneurship': {'enabled': False}})
    for _ in range(5):
        asyncio.run(world.step())
    assert world.economy.population.is_available(FOUNDER)
    checking = world.store.scalar('SELECT checking_account_id FROM agents WHERE id=?', (FOUNDER,))
    before = world.economy.ledger.balance(checking)
    action = {'type': 'apply_business_permit', 'name': 'Returning applicant permit', 'sector': 'repair',
        'lawyer_agent_id': LAWYER, 'opening_capital': 500,
        'business_idea': {'mission': 'Repair local equipment', 'customer_problem': 'Broken equipment',
                          'offering': 'Equipment repairs'}}
    result = world.economy.city.apply_business_permit(6, FOUNDER, action)
    assert result['ok']
    assert world.economy.ledger.balance(checking) == before - world.economy.city.application_fee_cents
    after = contents(world.store)
    duplicate = world.economy.city.apply_business_permit(6, FOUNDER, action)
    assert not duplicate['ok']
    assert contents(world.store) == after
    assert world.economy.ledger.reconcile()[0]


def test_returning_lawyer_supports_one_company_after_restart_replay_and_export(scenario_world, tmp_path):
    entries = [proposal(actor=f'agent:{LAWYER}'),
        proposal('back', actor=f'agent:{LAWYER}', tick=3, due=5, cause='return')]
    config = {**RUNTIME_CONFIG, 'entrepreneurship': {'enabled': False}, 'participant_mode': {'enabled': True}}
    world = scenario_world(entries, 'formation-source', config_overrides=config)
    original_people = world.store.scalar('SELECT COUNT(*) FROM agents')
    original_accounts = [tuple(row) for row in world.store.query(
        'SELECT id,checking_account_id,savings_account_id FROM agents WHERE id IN (?,?) ORDER BY id', (LAWYER, FOUNDER))]
    world.runtime.participant.acquire(FOUNDER, 0, running=False)
    action = {'type': 'found_company', 'name': 'Returning Lawyer Works', 'sector': 'repair',
              'lawyer_agent_id': LAWYER, 'opening_capital': 500}
    for day in range(1, 8):
        if day in (3, 6):
            phase = 'MORNING' if day == 3 else 'EXECUTION'
            paused = asyncio.run(world.step(pause_after_phase=phase))
            assert paused['active_tick'] == day
            scenario_world.close(world)
            world = scenario_world(entries, 'formation-source', config_overrides=config)
        asyncio.run(world.step())
        if day == 2:
            assert not world.economy.population.is_available(LAWYER)
            before = contents(world.store)
            with pytest.raises(ParticipantError):
                world.runtime.participant.queue_action(2, action, running=False)
            assert contents(world.store) == before
        if day == 5:
            assert world.economy.population.is_available(LAWYER)
            formation = next(item for item in world.runtime.participant.action_catalog(FOUNDER)
                             if item['type'] == 'found_company')
            assert formation['enabled']
            world.runtime.participant.queue_action(5, action, running=False)
        assert world.economy.ledger.reconcile()[0]
    assert world.store.scalar("SELECT status FROM participant_actions WHERE target_tick=6") == 'executed'
    assert world.store.scalar('SELECT COUNT(*) FROM agents') == original_people
    assert original_accounts == [tuple(row) for row in world.store.query(
        'SELECT id,checking_account_id,savings_account_id FROM agents WHERE id IN (?,?) ORDER BY id', (LAWYER, FOUNDER))]
    assert world.store.scalar('SELECT COUNT(*) FROM llm_calls WHERE agent_id=? AND tick BETWEEN 2 AND 4', (LAWYER,)) == 0
    firm = world.store.query_one('SELECT * FROM firms WHERE name=?', (action['name'],))
    assert firm is not None and firm['founded_tick'] == 6 and firm['founder_agent_id'] == FOUNDER
    assert world.store.scalar('SELECT COUNT(*) FROM firms WHERE name=?', (action['name'],)) == 1
    assert world.store.scalar("SELECT qty FROM shares WHERE firm_id=? AND holder_type='agent' AND holder_id=?",
                              (firm['id'], FOUNDER)) == 1000
    assert world.store.scalar("SELECT COUNT(*) FROM transactions WHERE kind='equity_investment' AND memo=?",
                              (f"found {action['name']}",)) == 1
    transaction_id = world.store.scalar("SELECT id FROM transactions WHERE kind='equity_investment' AND memo=?",
                                        (f"found {action['name']}",))
    founder_account = world.store.scalar('SELECT checking_account_id FROM agents WHERE id=?', (FOUNDER,))
    assert {row['account_id']: row['delta_cents'] for row in world.store.query(
        'SELECT account_id,delta_cents FROM ledger_entries WHERE txn_id=?', (transaction_id,))} == {
        founder_account: -500, firm['account_id']: 500}
    issuance = world.store.query_one("SELECT * FROM share_movements WHERE firm_id=? AND movement_type='founder_issuance'", (firm['id'],))
    assert issuance['qty'] == 1000 and issuance['price_cents'] is None and issuance['amount_cents'] == 0
    event = json.loads(world.store.scalar("SELECT payload_json FROM events WHERE kind='company_founded' AND subject_id=?", (firm['id'],)))
    assert event['founder_agent_id'] == FOUNDER
    source = Path(world.store.path)
    scenario_world.close(world)
    original = hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns
    replay = scenario_world(entries, 'formation-replay', replay_source=source, config_overrides=config)
    for day in range(1, 8):
        if day in (3, 6):
            asyncio.run(replay.step(pause_after_phase='MORNING' if day == 3 else 'EXECUTION'))
            scenario_world.close(replay)
            replay = scenario_world(entries, 'formation-replay', replay_source=source, config_overrides=config)
        asyncio.run(replay.step())
        assert replay.economy.ledger.reconcile()[0]
    target = Path(replay.store.path)
    scenario_world.close(replay)
    with closing(open_read_only_connection(source, require_closed=True)) as src, \
            closing(open_read_only_connection(target, require_closed=True)) as dst:
        proof = verify_replay_connections(src, dst)
        assert proof['exact'], proof['differences']
        for database, directory in ((src, 'source-export'), (dst, 'replay-export')):
            manifest = validate_bundle(export_bundle(database, tmp_path / directory), database=database)
            assert manifest['contract_id'] == 'hash-contract-v8'
            assert database.execute('SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls').fetchone()[0] == 0
            assert database.execute("SELECT COUNT(*) FROM llm_calls WHERE provider<>'scripted'").fetchone()[0] == 0
    assert (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns) == original
    assert not any(Path(str(source) + suffix).exists() for suffix in ('-wal', '-shm', '-journal'))

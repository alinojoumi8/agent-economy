"""Declared credit/VC workflow through departure, return, restart and replay.

This is integration evidence for the unregistered population draft, not native
company formation, autonomous underwriting or a long-run economic experiment.
"""
import asyncio
from contextlib import closing
import hashlib
import json
from pathlib import Path

from engine.credit import LoanTerms
from engine.store import open_read_only_connection
from research.export_bundle import export_bundle, validate_bundle
from research.hashing import canonical_hashes
from world.replay_verify import verify_replay_connections

from .test_population_scenario import scenario_world, proposal


PERSON, SUCCESSOR = 23, 24
COMPANY = 'Declared continuing company'


def test_departing_founder_retains_debt_and_equity_through_world_replay(scenario_world, tmp_path):
    entries = [proposal(), proposal('back', tick=10, due=12, cause='return')]

    def create(name, source=None):
        fresh = not (tmp_path/f'{name}.db').exists()
        world = scenario_world(entries, name, replay_source=source)
        e, store = world.economy, world.store
        if fresh:
            # Source and replay receive the same declared genesis contracts.
            # All subsequent financing decisions use recorded agent actions.
            firm = e.firms.found_firm(0, PERSON, COMPANY, 'tech',
                                     opening_capital_cents=10000, shares=100)
            e.exchange._adjust_shares(firm, 'agent', PERSON, -40)
            e.exchange._adjust_shares(firm, 'agent', SUCCESSOR, 40)
            bank = store.scalar('SELECT ac.bank_id FROM agents a JOIN accounts ac '
                                'ON ac.id=a.checking_account_id WHERE a.id=?', (PERSON,))
            loan = e.bank.disburse_loan(0, bank, 'agent', PERSON,
                LoanTerms(7000, 0, 28, 7), purpose='Existing personal obligation')
            assert loan is not None
            foreign = store.scalar('SELECT code FROM currencies WHERE code != '
                '(SELECT currency_code FROM banks WHERE id=?) ORDER BY code LIMIT 1', (bank,))
            assert foreign
            e.ledger.create_account('agent', PERSON, 'savings', opening_cents=37,
                                    currency_code=foreign, label='Declared foreign holding')
            actions = [
                {'type': 'apply_loan', 'bank_id': bank, 'amount': 2000,
                 'purpose': 'Pending personal credit'},
                {'type': 'apply_loan', 'bank_id': bank, 'amount': 3000,
                 'as_firm': True, 'firm_id': firm, 'purpose': 'Pending company credit'},
                {'type': 'pitch_vc', 'firm_id': firm, 'ask': 2000,
                 'summary': 'Declared continuing business investment'},
            ]
            for action in actions:
                result = world.runtime.executor.execute_action(0, PERSON, action)
                assert result['ok'], result

        firm = store.scalar('SELECT id FROM firms WHERE name=?', (COMPANY,))
        personal = store.scalar("SELECT id FROM loan_applications WHERE borrower_type='agent' "
                               "AND borrower_id=? AND purpose='Pending personal credit'", (PERSON,))
        company = store.scalar("SELECT id FROM loan_applications WHERE borrower_type='firm' "
                              "AND borrower_id=? AND purpose='Pending company credit'", (firm,))
        pitch = store.scalar('SELECT id FROM pitches WHERE firm_id=?', (firm,))
        officer = store.scalar("SELECT a.id FROM agents a JOIN loan_applications l "
            "ON l.bank_id=a.employer_id WHERE a.role='credit_officer' AND l.id=? ORDER BY a.id LIMIT 1",
            (company,))
        investor = store.scalar("SELECT id FROM agents WHERE role='vc_partner' ORDER BY id LIMIT 1")
        finance_actors = {row['id'] for row in store.query(
            "SELECT id FROM agents WHERE role IN ('credit_officer','vc_partner')")}
        assert officer in finance_actors and investor in finance_actors
        def decisions(context):
            if source is not None:
                raise AssertionError('replay must consume the recorded financial decisions')
            actor, tick = context.get('agent', {}).get('id'), context.get('tick')
            action = None
            if actor == officer and tick == 3:
                action = {'type': 'approve_loan', 'application_id': personal}
            elif actor == officer and tick == 4:
                action = {'type': 'approve_loan', 'application_id': company,
                          'rate_bps': 300, 'term_ticks': 30}
            elif actor == investor and tick == 3:
                action = {'type': 'fund_pitch', 'pitch_id': pitch,
                          'amount': 2000, 'equity_bps': 2000}
            assert actor in finance_actors
            return {'reasoning': 'Declared financing schedule',
                    'actions': [action or {'type': 'do_nothing'}]}

        for purpose in ('credit_officer', 'vc_partner'):
            world.gateway.scripted.register(purpose, decisions)
        return world

    def facts(world, day):
        e, store = world.economy, world.store
        firm = store.scalar('SELECT id FROM firms WHERE name=?', (COMPANY,))
        assert e.population.is_available(PERSON) is (day < 2 or day >= 12)
        assert store.scalar('SELECT checking_account_id FROM agents WHERE id=?', (PERSON,)) == wallet
        foreign = store.query_one("SELECT id,balance_cents FROM accounts WHERE label='Declared foreign holding'")
        assert (foreign['id'], foreign['balance_cents']) == (foreign_id, 37)
        assert store.scalar("SELECT qty FROM shares WHERE firm_id=? AND holder_type='agent' AND holder_id=?",
                            (firm, PERSON)) == 60
        assert store.scalar("SELECT status FROM loan_applications WHERE borrower_type='agent' "
                            "AND borrower_id=? AND purpose='Pending personal credit'", (PERSON,)) == (
                                'pending' if day < 2 else 'expired')
        company = store.query_one("SELECT status,loan_id FROM loan_applications WHERE borrower_type='firm' "
                                 "AND borrower_id=? AND purpose='Pending company credit'", (firm,))
        assert company['status'] == ('pending' if day < 4 else 'approved')
        if day >= 2:
            assert e.business_control.operator_at(firm) == SUCCESSOR
            assert store.scalar("SELECT COUNT(*) FROM population_commitment_endings "
                "WHERE kind='loan_application' AND agent_id=?", (PERSON,)) == 1
        if day >= 3:
            pitch = store.query_one('SELECT * FROM pitches WHERE firm_id=?', (firm,))
            assert (pitch['status'], pitch['decided_tick'], pitch['invested_cents'], pitch['shares_issued']) == (
                'funded', 3, 2000, 25)
            attempt = store.query_one("SELECT result_json FROM action_proposals WHERE tick=3 "
                                     "AND action_type='approve_loan'")
            assert json.loads(attempt['result_json']) == {'ok': False, 'reason': 'application not pending'}
        if day >= 4:
            credit = store.query_one('SELECT * FROM loans WHERE id=?', (company['loan_id'],))
            assert (credit['borrower_type'], credit['borrower_id'], credit['origin_tick'], credit['principal_cents']) == (
                'firm', firm, 4, 3000)
        personal = store.query_one("SELECT * FROM loans WHERE purpose='Existing personal obligation'")
        assert personal['outstanding_cents'] == 7000 - 1750 * (day // 7)
        assert personal['missed_payments'] == 0
        assert e.ledger.reconcile()[0]

    world = create('finance-source')
    wallet = world.store.scalar('SELECT checking_account_id FROM agents WHERE id=?', (PERSON,))
    foreign_id = world.store.scalar("SELECT id FROM accounts WHERE label='Declared foreign holding'")
    for day in range(1, 16):
        if day == 5:
            asyncio.run(world.step(pause_after_phase='NIGHT_CLOSE'))
            scenario_world.close(world)
            world = create('finance-source')
        asyncio.run(world.step())
        facts(world, day)
    source = Path(world.store.path)
    scenario_world.close(world)
    stamp = hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns

    replay = create('finance-replay', source)
    for day in range(1, 16):
        if day == 5:
            asyncio.run(replay.step(pause_after_phase='NIGHT_CLOSE'))
            scenario_world.close(replay)
            replay = create('finance-replay', source)
        asyncio.run(replay.step())
        facts(replay, day)
    replay_path = Path(replay.store.path)
    scenario_world.close(replay)
    with closing(open_read_only_connection(source, require_closed=True)) as src, \
            closing(open_read_only_connection(replay_path, require_closed=True)) as dst:
        proof = verify_replay_connections(src, dst)
        assert proof['exact'], proof['differences']
        first, second = canonical_hashes(src), canonical_hashes(dst)
        for table in ('events', 'accounts', 'ledger_entries', 'loans', 'loan_applications',
                      'pitches', 'shares', 'action_proposals', 'population_commitment_endings'):
            assert first['tables'][table] == second['tables'][table], table
        bundle = export_bundle(src, tmp_path/'source-export')
        assert validate_bundle(bundle, database=src)['contract_id'] == 'hash-contract-v8'
        assert src.execute('SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls').fetchone()[0] == 0
        loan = src.execute("SELECT id FROM loans WHERE purpose='Existing personal obligation'").fetchone()[0]
        payments = src.execute("SELECT tick FROM transactions WHERE kind='loan_payment' "
                               "AND memo=? ORDER BY tick", (f'loan {loan} payment',)).fetchall()
        assert [row[0] for row in payments] == [7, 14]
    assert (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns) == stamp
    assert not any(Path(str(source)+suffix).exists() for suffix in ('-wal', '-shm', '-journal'))

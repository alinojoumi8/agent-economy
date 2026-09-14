"""Central-bank admission follows residence, including stale role/provenance rows."""
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

from .test_lolr_decisions import _model_call
from .test_population_residence_history import contents
from .test_population_scenario import scenario_world, proposal


@pytest.fixture
def outside_governor(scenario_world):
    world = scenario_world([proposal(actor='agent:1')])
    governor = world.store.query_one("SELECT id FROM agents WHERE role='central_banker'")
    assert governor['id'] == 1
    world.gateway.scripted.register('central_banker', lambda context: {
        'reasoning': 'Hold policy during declared departure', 'actions': [{'type': 'do_nothing'}]})
    for _ in range(2):
        asyncio.run(world.step())
    assert world.economy.population.is_available(1) is False
    assert world.store.scalar('SELECT role FROM agents WHERE id=1') is None
    # A stale or restored role field must not undo the real residence ending.
    world.store.update('agents', 1, role='central_banker')
    return world


@pytest.mark.parametrize('decision', ['approve', 'deny'])
def test_outside_governor_cannot_use_matching_model_provenance(outside_governor, decision):
    world = outside_governor
    bank = world.economy.bank
    request = bank.request_liquidity_support(2, 1, 100, phase='NIGHT_CLOSE', source='declared test')
    model = _model_call(world, 2, 1)
    reserve = world.economy.central_bank_reserve_acct(bank.get(1)['currency_code'])
    before = contents(world.store)
    result = bank.decide_liquidity_support(2, 1, request, decision, model, reserve, phase='EXECUTION')
    assert result['ok'] is False, result
    assert contents(world.store) == before
    assert world.economy.ledger.reconcile()[0]


def test_outside_governor_cannot_keep_a_distress_request_waiting(outside_governor):
    world = outside_governor
    bank = world.economy.bank
    request = bank.request_liquidity_support(2, 1, 100, phase='NIGHT_CLOSE', source='declared test')
    reserve = world.economy.central_bank_reserve_acct(bank.get(1)['currency_code'])
    assert bank._has_living_central_banker() is False
    assert bank.attempt_liquidity_support(2, 1, 100, reserve,
        require_authorized_decision=True) is False
    assert world.store.scalar('SELECT status FROM liquidity_support_requests WHERE request_event_id=?',
                              (request,)) == 'denied'
    assert world.store.scalar("SELECT COUNT(*) FROM events WHERE kind='lolr_granted'") == 0
    assert world.economy.ledger.reconcile()[0]


def test_missing_later_official_history_precedes_interbank_or_request_effects(scenario_world, monkeypatch):
    world = scenario_world([])
    e = world.economy
    # Validate every candidate, even when the first central banker is valid.
    world.store.update('agents', 2, role='central_banker')
    original = e.population.is_available
    def missing_history(actor):
        if actor == 2:
            raise ResidenceError('missing later official residence')
        return original(actor)
    monkeypatch.setattr(e.population, 'is_available', missing_history)
    reserve = e.central_bank_reserve_acct(e.bank.get(1)['currency_code'])
    before = contents(world.store)
    with pytest.raises(ResidenceError, match='missing later official'):
        e.bank.attempt_liquidity_support(0, 1, 100, reserve, require_authorized_decision=True)
    assert contents(world.store) == before


def test_missing_decision_actor_history_precedes_rescue_effects(scenario_world, monkeypatch):
    world = scenario_world([])
    e = world.economy
    request = e.bank.request_liquidity_support(0, 1, 100, phase='NIGHT_CLOSE', source='declared test')
    model = _model_call(world, 0, 1)
    reserve = e.central_bank_reserve_acct(e.bank.get(1)['currency_code'])
    def missing_history(*args):
        raise ResidenceError('missing official residence')
    monkeypatch.setattr(e.population, 'is_available', missing_history)
    monkeypatch.setattr(e.population, 'is_local', missing_history)
    before = contents(world.store)
    with pytest.raises(ResidenceError, match='missing official'):
        e.bank.decide_liquidity_support(0, 1, request, 'approve', model, reserve, phase='EXECUTION')
    assert contents(world.store) == before


def test_local_rescue_and_official_departure_restart_replay_export(scenario_world, tmp_path):
    entries = [proposal(actor='agent:1'),
               proposal('back', tick=3, due=4, actor='agent:1', cause='return')]
    def create(name, source=None):
        fresh = not (tmp_path/f'{name}.db').exists()
        world = scenario_world(entries, name, replay_source=source)
        if fresh:
            # Controlled, identical request in each genesis. The subsequent
            # local policy decision is recorded through the real runtime.
            world.economy.bank.request_liquidity_support(
                0, 1, 100, phase='NIGHT_CLOSE', source='declared population rescue')
        request = world.store.scalar('SELECT request_event_id FROM liquidity_support_requests '
                                     'WHERE bank_id=1 AND requested_tick=0 ORDER BY id LIMIT 1')
        def decision(context):
            if source is not None:
                raise AssertionError('replay must consume recorded policy decisions')
            assert context['agent']['id'] == 1 and context['tick'] == 1
            return {'reasoning': 'Declared local support decision', 'actions': [{
                'type': 'decide_liquidity_support', 'request_event_id': request,
                'decision': 'approve', 'evidence_event_ids': [request]}]}
        world.gateway.scripted.register('central_banker', decision)
        return world

    def step(world, day):
        asyncio.run(world.step())
        assert world.economy.population.is_available(1) is (day == 1 or day >= 4)
        assert world.store.scalar('SELECT role FROM agents WHERE id=1') == (
            'central_banker' if day == 1 else None)
        assert world.store.scalar('SELECT status FROM liquidity_support_requests '
                                 'WHERE bank_id=1 AND requested_tick=0') == 'approved'
        assert world.store.scalar("SELECT COUNT(*) FROM events WHERE kind='lolr_granted'") == 1
        assert world.store.scalar('SELECT COUNT(*) FROM llm_calls WHERE agent_id=1 AND tick IN (2,3)') == 0
        assert world.economy.ledger.reconcile()[0]

    world = create('local-rescue-source')
    for day in range(1, 6):
        if day == 3:
            asyncio.run(world.step(pause_after_phase='NIGHT_CLOSE'))
            scenario_world.close(world)
            world = create('local-rescue-source')
        step(world, day)
    source = Path(world.store.path)
    scenario_world.close(world)
    stamp = hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns
    replay = create('local-rescue-replay', source)
    for day in range(1, 6):
        if day == 3:
            asyncio.run(replay.step(pause_after_phase='NIGHT_CLOSE'))
            scenario_world.close(replay)
            replay = create('local-rescue-replay', source)
        step(replay, day)
    replay_path = Path(replay.store.path)
    scenario_world.close(replay)
    with closing(open_read_only_connection(source, require_closed=True)) as src, \
            closing(open_read_only_connection(replay_path, require_closed=True)) as dst:
        proof = verify_replay_connections(src, dst)
        assert proof['exact'], proof['differences']
        proposal_row = src.execute("SELECT model_call_id,result_json FROM action_proposals "
                                   "WHERE action_type='decide_liquidity_support'").fetchall()
        assert len(proposal_row) == 1 and proposal_row[0]['model_call_id'] is not None
        assert json.loads(proposal_row[0]['result_json'])['ok'] is True
        assert src.execute("SELECT COUNT(*) FROM transactions WHERE kind='lolr'").fetchone()[0] == 1
        assert src.execute('SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls').fetchone()[0] == 0
        bundle = export_bundle(src, tmp_path/'source-export')
        assert validate_bundle(bundle, database=src)['contract_id'] == 'hash-contract-v8'
    assert (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns) == stamp
    assert not any(Path(str(source)+suffix).exists() for suffix in ('-wal', '-shm', '-journal'))

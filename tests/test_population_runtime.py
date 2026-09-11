"""Resident admission for social activity and model memory work in draft worlds."""
import asyncio
from contextlib import closing
import hashlib
import json
from pathlib import Path

import pytest

from engine.population_history import ResidenceError
from engine.store import open_read_only_connection
from world.replay_verify import verify_replay_connections

from .test_population_residence_history import contents
from .test_population_scenario import proposal, scenario_world


RUNTIME_CONFIG = {'city': {'enabled': False}, 'living_world': {'core_agents': 100},
                  'conversations': {'turns': 2}}


def departed_world(create):
    world = create([proposal()], config_overrides=RUNTIME_CONFIG)
    assert world.store.scalar('SELECT population_tier FROM agents WHERE id=23') == 'core'
    for _ in range(2):
        asyncio.run(world.step())
    assert not world.economy.population.is_local(23, 2)
    assert world.economy.population.is_local(24, 2)
    return world


def test_social_pair_sampling_without_city_excludes_outside_people(scenario_world):
    world = departed_world(scenario_world)
    # An explicit fixture graph makes the unavailable edge the only candidate.
    world.store.execute('DELETE FROM social_ties')
    world.store.insert('social_ties', agent_a=23, agent_b=24, weight=1.0)
    before = contents(world.store)
    assert world.conversations._sample_pairs(2, 1) == []
    assert contents(world.store) == before


def test_restored_explicit_pair_cannot_converse_with_an_outside_person(scenario_world):
    world = departed_world(scenario_world)
    before = contents(world.store)
    assert asyncio.run(world.conversations.evening(2, pairs=[(23, 24)])) == 0
    assert contents(world.store) == before


def test_direct_weekly_reflection_cannot_use_an_outside_persons_old_memories(scenario_world):
    world = departed_world(scenario_world)
    assert world.store.scalar("SELECT COUNT(*) FROM memories WHERE agent_id=23 AND kind='summary'") > 0
    before = contents(world.store)
    assert asyncio.run(world.runtime._rollup_week(7, 23, 1)) is None
    assert contents(world.store) == before


def test_direct_daily_compression_skips_outside_people(scenario_world):
    world = departed_world(scenario_world)
    assert world.runtime.mem.todays_observations(23, 2)
    before = contents(world.store)
    assert asyncio.run(world.runtime._compress_one(2, 23)) is None
    assert contents(world.store) == before


def test_remaining_local_pairs_keep_their_original_topic_slot(scenario_world, monkeypatch):
    world = departed_world(scenario_world)
    calls = []

    async def record(tick, a, b, *, topic_slot=0):
        calls.append((tick, a, b, topic_slot))

    monkeypatch.setattr(world.conversations, '_converse', record)
    assert asyncio.run(world.conversations.evening(2, pairs=[(23, 24), (24, 25)])) == 1
    assert calls == [(2, 24, 25, 1)]


@pytest.mark.parametrize('entrypoint', ['sampling', 'evening', 'direct'])
def test_missing_later_participant_history_fails_before_any_social_effect(scenario_world, entrypoint):
    world = departed_world(scenario_world)
    world.store.execute('DROP TRIGGER person_residence_no_delete')
    world.store.execute('DELETE FROM person_residence_events WHERE agent_id=25')
    world.store.execute('DELETE FROM social_ties')
    world.store.insert('social_ties', agent_a=23, agent_b=25, weight=1.0)
    before = contents(world.store)
    with pytest.raises(ResidenceError):
        if entrypoint == 'sampling':
            world.conversations._sample_pairs(2, 1)
        elif entrypoint == 'evening':
            asyncio.run(world.conversations.evening(2, pairs=[(24, 26), (25, 27)]))
        else:
            asyncio.run(world.conversations._converse(2, 23, 25))
    assert contents(world.store) == before


def test_invalid_weekly_candidate_prevents_earlier_daily_summary_effects(scenario_world):
    world = departed_world(scenario_world)
    world.runtime.mem.observe(24, 7, 'A declared test observation.', importance=2.0)
    world.runtime.mem.write_summary(25, 6, 'An earlier declared test summary.', 2.0)
    world.store.execute('DROP TRIGGER person_residence_no_delete')
    world.store.execute('DELETE FROM person_residence_events WHERE agent_id=25')
    before = contents(world.store)
    with pytest.raises(ResidenceError):
        asyncio.run(world.runtime.compress_memories(7))
    assert contents(world.store) == before


def test_outside_owners_keep_raw_payment_notices_without_local_memory_work(scenario_world):
    world = departed_world(scenario_world)
    ledger = world.economy.ledger
    source = world.store.scalar('SELECT checking_account_id FROM agents WHERE id=24')
    target = world.store.scalar('SELECT checking_account_id FROM agents WHERE id=23')
    before = ledger.balance(target)
    # A declared fixture payment between existing owners uses real ledger legs.
    # Its passive notice remains available even while the recipient is outside.
    transaction = ledger.transfer(3, source, target, 21, kind='fixture_owner_receipt')
    world.store.log_event(3, 'fixture_owner_receipt', {'transaction_id': transaction},
                         phase='EXECUTION', subject_type='agent', subject_id=23)
    world.runtime.capture_event_observations(3)
    assert world.runtime.mem.todays_observations(23, 3)
    memories = [tuple(row) for row in world.store.query('SELECT * FROM memories WHERE agent_id=23 ORDER BY id')]
    asyncio.run(world.runtime.compress_memories(3))
    assert memories == [tuple(row) for row in world.store.query('SELECT * FROM memories WHERE agent_id=23 ORDER BY id')]
    assert ledger.balance(target) == before + 21 and ledger.reconcile()[0]
    assert world.store.scalar('SELECT COUNT(*) FROM llm_calls WHERE agent_id=23 AND tick=3') == 0


def test_outside_week_then_return_restarts_and_replays_without_absent_model_calls(scenario_world):
    create = scenario_world
    entries = [proposal(), proposal('back', tick=8, due=9, cause='return')]
    world = create(entries, 'runtime-source', config_overrides=RUNTIME_CONFIG)
    assert world.store.scalar('SELECT population_tier FROM agents WHERE id=23') == 'core'
    original_account = world.store.scalar('SELECT checking_account_id FROM agents WHERE id=23')
    for day in range(1, 15):
        if day in (7, 9):
            paused = asyncio.run(world.step(pause_after_phase='EVENING'))
            assert paused['active_tick'] == day and paused['phase'] == 'MEMORY'
            create.close(world)
            world = create(entries, 'runtime-source', config_overrides=RUNTIME_CONFIG)
        asyncio.run(world.step())
        assert world.store.tick == day
        if 2 <= day < 9:
            assert not world.economy.population.is_local(23, day)
            assert world.store.scalar('SELECT COUNT(*) FROM llm_calls WHERE agent_id=23 AND tick=?', (day,)) == 0
            assert world.store.scalar("SELECT COUNT(*) FROM memories WHERE agent_id=23 AND tick=? AND kind IN ('summary','weekly')", (day,)) == 0
            participants = [json.loads(row[0]) for row in world.store.query('SELECT participant_ids FROM conversations WHERE tick=?', (day,))]
            assert all(23 not in group for group in participants)
        assert world.economy.ledger.reconcile()[0]
        world.population_scenario.check_progress()
    assert world.economy.population.is_local(23, 14)
    assert world.store.scalar("SELECT COUNT(*) FROM llm_calls WHERE agent_id=23 AND tick=14 AND purpose='memory'") > 0
    assert world.store.scalar('SELECT checking_account_id FROM agents WHERE id=23') == original_account
    source = Path(world.store.path)
    create.close(world)
    stamp = hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns
    replay = create(entries, 'runtime-replay', replay_source=source, config_overrides=RUNTIME_CONFIG)
    for _ in range(14):
        asyncio.run(replay.step())
    replay_path = Path(replay.store.path)
    create.close(replay)
    with closing(open_read_only_connection(source, require_closed=True)) as src, \
         closing(open_read_only_connection(replay_path, require_closed=True)) as dst:
        result = verify_replay_connections(src, dst)
        assert result['exact'], result['differences']
        for table in ('population_scenario_manifest', 'population_scenario_receipts',
                      'population_movements', 'population_movement_assents', 'population_resident_census',
                      'population_commitment_endings', 'person_residence_events'):
            assert [tuple(row) for row in src.execute(f'SELECT * FROM {table} ORDER BY rowid')] == [
                tuple(row) for row in dst.execute(f'SELECT * FROM {table} ORDER BY rowid')]
        assert src.execute("SELECT COUNT(*) FROM llm_calls WHERE provider<>'scripted'").fetchone()[0] == 0
        assert src.execute('SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls').fetchone()[0] == 0
    assert stamp == (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns)
    assert not any(Path(str(source) + suffix).exists() for suffix in ('-wal', '-shm', '-journal'))


@pytest.mark.parametrize('role,actor', [('reporter', 6), ('editor', 5)])
def test_newsroom_departure_requires_resident_staff_and_return_does_not_restore_a_job(scenario_world, role, actor):
    entries = [proposal(actor=f'agent:{actor}'),
               proposal('back', tick=3, due=4, actor=f'agent:{actor}', cause='return')]
    world = scenario_world(entries, config_overrides=RUNTIME_CONFIG)
    for day in range(1, 5):
        asyncio.run(world.step())
        if day in (2, 3):
            assert world.newsroom._desk_agent(role, 1) is None
            assert world.store.scalar('SELECT COUNT(*) FROM llm_calls WHERE agent_id=? AND tick=?', (actor, day)) == 0
            assert world.store.scalar("SELECT COUNT(*) FROM llm_calls WHERE agent_id IS NULL AND tick=? "
                                      "AND purpose IN ('reporter','newsroom')", (day,)) == 0
            assert world.store.scalar('SELECT COUNT(*) FROM news_articles WHERE outlet_id=1 AND tick=?', (day,)) == (1 if role == 'reporter' else 0)
            before = contents(world.store)
            outlet = world.newsroom.outlets[0]
            if role == 'reporter':
                assert asyncio.run(world.newsroom._report_stories(day, outlet, [])) == []
            else:
                assert asyncio.run(world.newsroom._write_story(day, outlet, [], None)) is None
            assert contents(world.store) == before
    assert world.economy.population.is_local(actor, 4)
    assert world.newsroom._desk_agent(role, 1) is None
    assert world.store.scalar('SELECT COUNT(*) FROM news_articles WHERE outlet_id=1 AND tick=4') == (1 if role == 'reporter' else 0)
    before = contents(world.store)
    asyncio.run(world.newsroom.publish(2))
    assert contents(world.store) == before
    assert world.economy.ledger.reconcile()[0]
    source = Path(world.store.path)
    scenario_world.close(world)
    stamp = hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns
    replay = scenario_world(entries, 'newsroom-replay', replay_source=source, config_overrides=RUNTIME_CONFIG)
    for _ in range(4):
        asyncio.run(replay.step())
    replay_path = Path(replay.store.path)
    scenario_world.close(replay)
    with closing(open_read_only_connection(source, require_closed=True)) as src, \
         closing(open_read_only_connection(replay_path, require_closed=True)) as dst:
        result = verify_replay_connections(src, dst)
        assert result['exact'], result['differences']
    assert stamp == (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns)
    assert not any(Path(str(source) + suffix).exists() for suffix in ('-wal', '-shm', '-journal'))


def test_missing_editor_history_prevents_reporter_and_quiet_day_effects(scenario_world):
    world = departed_world(scenario_world)
    world.store.execute('DROP TRIGGER person_residence_no_delete')
    world.store.execute('DELETE FROM person_residence_events WHERE agent_id=5')
    before = contents(world.store)
    with pytest.raises(ResidenceError):
        asyncio.run(world.newsroom.publish(3))
    assert contents(world.store) == before


@pytest.mark.parametrize('damage', ['actor', 'movement', 'duplicate'])
def test_replay_rejects_unbound_personal_role_history(scenario_world, damage):
    world = scenario_world([proposal(actor='agent:6')], config_overrides=RUNTIME_CONFIG)
    for _ in range(2):
        asyncio.run(world.step())
    conn = world.store.conn
    assert verify_replay_connections(conn, conn)['exact']
    release = world.store.query_one(
        "SELECT * FROM events WHERE kind='population_authority_released' AND subject_id=6 "
        "AND json_extract(payload_json,'$.binding_kind')='personal_role'")
    payload = json.loads(release['payload_json'])
    if damage == 'duplicate':
        world.store.log_event(2, release['kind'], payload, phase='NIGHT_CLOSE',
                              subject_type='agent', subject_id=6)
    else:
        payload['agent_id' if damage == 'actor' else 'movement_id'] = 99999
        world.store.update('events', release['id'], payload_json=json.dumps(payload))
    before = contents(world.store)
    result = verify_replay_connections(conn, conn)
    assert not result['exact']
    assert {'action_proposals', 'agent_decisions', 'events'} <= set(result['differences'])
    assert contents(world.store) == before


def test_desk_selection_skips_stale_outside_role_for_an_existing_resident(scenario_world):
    world = scenario_world([proposal(actor='agent:5')], config_overrides=RUNTIME_CONFIG)
    for _ in range(2):
        asyncio.run(world.step())
    # Explicit corrupt/stale first candidate and a separate existing resident
    # desk-holder fixture. The selector must never call the unavailable person.
    world.store.update('agents', 5, role='editor')
    world.store.update('agents', 24, role='editor', personality_json=json.dumps({'outlet_id': 1}))
    before = contents(world.store)
    assert world.newsroom._desk_agent('editor', 1, tick=2) == 24
    assert contents(world.store) == before

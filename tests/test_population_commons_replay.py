"""Full draft Commons command order, control interleaving and closed artifacts."""
import asyncio
from contextlib import closing
import hashlib
import json
from pathlib import Path

import duckdb
import pytest

from agents.external import ExternalAgentError
from engine.store import open_read_only_connection
from research.export_bundle import ExportLimits, export_bundle, validate_bundle
from research.hashing import canonical_hashes
from world.commons import CommonsError, CommonsService
from world.commons_journal import CommonsReplayError, KIND, OPERATIONS
from world.replay_verify import verify_replay_connections

from .test_population_commons import commons_case
from .test_population_residence_history import contents
from .test_population_resident_services import closed_copy, controls, replay_controls, resident_services
from .test_population_scenario import proposal, scenario_world


def seed_claim(economy):
    """Identical declared genesis claim for source and fresh replay fixtures."""
    prior = economy.store.query_one("SELECT id FROM claims WHERE claim_key='region:1:commons_fixture'")
    if prior:
        return prior['id']
    event = economy.store.log_event(0, 'commons_fixture_claim_seed', {'value': True},
                                    subject_type='region', subject_id=1)
    result = economy.information.create_claim(0, 24, {'claim_key': 'region:1:commons_fixture',
        'subject_type': 'region', 'subject_id': 1, 'predicate': 'commons_fixture', 'value': True,
        'truth_status': 'verified', 'source_event_ids': [event]})
    return result['claim_id']


def exercise_social(service, reader, author, claim_id=None):
    assert service.feed(reader)['entries'] == []
    service.ensure_profile(author, biography='PRIVATE_BIO in its profile row')
    group = service.create_community(author, name='Declared group', description='Group description', visibility='members')
    service.join_community(reader, group['id'])
    service.follow(reader, author)
    first = service.publish(author, body='PRIVATE_BODY in its entry row', community_id=group['id'])
    reply = service.publish(reader, body='Reply from the other member', parent_entry_id=first['id'])
    feed = service.feed(reader, kind='community', community_id=group['id'])
    impression = next(row['impression_id'] for row in feed['entries'] if row['id'] == first['id'])
    assert service.read(reader, impression)['memory_id'] is not None
    assert service.read(reader, impression)['idempotent'] is True
    service.react(reader, first['id'], 'like')
    service.feed(reader, kind='hot')
    service.react(reader, first['id'], 'like', active=False)
    service.follow(reader, author, active=False)
    moderation = service.moderate(author, reply['id'], action='label', reason='Recorded reason')
    service.appeal(reader, moderation['moderation_action_id'], 'PRIVATE_APPEAL in its owning row')
    service.moderate(author, reply['id'], action='hide', reason='Hidden pending review')
    service.feed(reader)
    service.moderate(author, reply['id'], action='restore', reason='Review complete')
    service.moderate(author, reply['id'], action='limit_author', reason='Recorded author limit')
    if claim_id is not None:
        factual = service.publish(author, body='Factual record', claim_id=claim_id)
        delivered = service.feed(reader)
        impression = next(row['impression_id'] for row in delivered['entries'] if row['id'] == factual['id'])
        assert service.read(reader, impression)['exposure_id'] is not None
    return group, first, reply


def normalized_rows(store, table):
    columns = [row['name'] for row in store.query(f'PRAGMA table_info({table})') if row['name'] != 'created_at']
    return [tuple(row) for row in store.query(f'SELECT {",".join(columns)} FROM {table} ORDER BY rowid')]


def test_all_commands_replay_with_memory_and_text_references_and_no_duplicate_helpers(commons_case, tmp_path):
    c = commons_case
    baseline, source = tmp_path/'target.db', tmp_path/'source.db'
    closed_copy(c.e.store, baseline)
    exercise_social(c.commons, c.person, c.heir)
    receipts = [json.loads(row['payload_json']) for row in c.e.store.query('SELECT payload_json FROM events WHERE kind=? ORDER BY id', (KIND,))]
    assert set(row['operation'] for row in receipts) == set(OPERATIONS)
    assert sum(row['operation'] == 'ensure_profile' for row in receipts) == 1
    assert all(text not in json.dumps(receipts) for text in ('PRIVATE_BODY', 'PRIVATE_BIO', 'PRIVATE_APPEAL'))
    closed_copy(c.e.store, source)
    original = hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns
    target, _, replay = replay_controls(c, baseline, source)
    try:
        replay.restore_population_inputs(1)
        tables = [row['name'] for row in c.e.store.query("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'commons_%'")]
        tables += ['events', 'memories', 'social_ties', 'causal_links']
        for table in tables:
            assert normalized_rows(target.e.store, table) == normalized_rows(c.e.store, table), table
        before = contents(target.e.store)
        replay.restore_population_inputs(1)
        assert contents(target.e.store) == before
        assert target.e.ledger.reconcile()[0]
    finally:
        target.e.store.close()
    assert (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns) == original
    assert not any(Path(str(source)+suffix).exists() for suffix in ('-wal', '-shm', '-journal'))


@pytest.mark.parametrize('field,value', [
    ('version', 2), ('operation', '__init__'), ('result_hash', '0'*64),
    ('frontier_event_id', 0), ('arguments', {'parent_entry_id': 999999}),
    ('text_hashes', {'body': '0'*64}),
])
def test_later_invalid_receipt_rolls_back_every_earlier_input(commons_case, tmp_path, field, value):
    c = commons_case
    baseline, source = tmp_path/'target.db', tmp_path/'source.db'
    closed_copy(c.e.store, baseline)
    c.commons.publish(c.person, body='Earlier valid post')
    c.commons.publish(c.heir, body='Later changed input')
    last = c.e.store.query_one('SELECT id,payload_json FROM events WHERE kind=? ORDER BY id DESC LIMIT 1', (KIND,))
    data = json.loads(last['payload_json'])
    data[field] = value
    c.e.store.execute('UPDATE events SET payload_json=? WHERE id=?', (json.dumps(data), last['id']))
    closed_copy(c.e.store, source)
    original = hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns
    target, _, replay = replay_controls(c, baseline, source)
    try:
        before = contents(target.e.store)
        with pytest.raises(CommonsReplayError):
            replay.restore_population_inputs(1)
        assert contents(target.e.store) == before
    finally:
        target.e.store.close()
    assert (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns) == original


def test_missing_receipt_is_a_draft_compatibility_error_not_inferred_order(commons_case, tmp_path):
    c = commons_case
    baseline, source = tmp_path/'target.db', tmp_path/'source.db'
    closed_copy(c.e.store, baseline)
    c.commons.publish(c.person, body='Unordered old draft post')
    c.e.store.execute('DELETE FROM events WHERE kind=?', (KIND,))
    closed_copy(c.e.store, source)
    target, _, replay = replay_controls(c, baseline, source)
    try:
        before = contents(target.e.store)
        with pytest.raises(CommonsReplayError, match='ordering is missing'):
            replay.restore_population_inputs(1)
        assert contents(target.e.store) == before
    finally:
        target.e.store.close()


@pytest.mark.parametrize('kind', ['manual', 'arrival', 'external', 'negative_external'])
def test_late_result_mismatch_rolls_back_interleaved_control_inputs(commons_case, tmp_path, kind):
    c = commons_case
    participant, external, auth = controls(c)
    baseline, source = tmp_path/'target.db', tmp_path/'source.db'
    closed_copy(c.e.store, baseline)
    c.commons.publish(c.heir, body='First valid social input')
    if kind == 'manual':
        participant.acquire(c.person, 0, running=False)
        participant.queue_action(0, {'type': 'do_nothing'}, 'Recorded command', running=False)
    elif kind == 'arrival':
        external.create_connection(tenant_id='fixture', owner_id='owner', display_name='Pending arrival', tier='actor')
    else:
        turn = external.turn(auth)
        result = external.submit_action(auth, {'idempotency_key': kind,
            'target_tick': turn['target_tick'], 'observed_projection_hash': turn['projection_hash'],
            'action': {'type': 'do_nothing' if kind == 'external' else 'unsupported_action'}})
        assert result['status'] == ('queued' if kind == 'external' else 'rejected')
    c.commons.publish(c.heir, body='Last input with altered result evidence')
    row = c.e.store.query_one('SELECT id,payload_json FROM events WHERE kind=? ORDER BY id DESC LIMIT 1', (KIND,))
    value = json.loads(row['payload_json']); value['result_hash'] = '0' * 64
    c.e.store.execute('UPDATE events SET payload_json=? WHERE id=?', (json.dumps(value), row['id']))
    closed_copy(c.e.store, source)
    target, _, replay = replay_controls(c, baseline, source)
    try:
        before = contents(target.e.store)
        with pytest.raises(CommonsReplayError, match='does not match replay'):
            replay.restore_population_inputs(1)
        assert contents(target.e.store) == before
    finally:
        target.e.store.close()


@pytest.mark.parametrize('kind', ['future_parent', 'other_viewer'])
def test_argument_references_are_preflighted_before_earlier_effects(commons_case, tmp_path, kind):
    c = commons_case
    baseline, source = tmp_path/'target.db', tmp_path/'source.db'
    closed_copy(c.e.store, baseline)
    c.commons.publish(c.person, body='Earlier post')
    if kind == 'future_parent':
        c.commons.publish(c.heir, body='Recorded post')
        receipt = c.e.store.query_one('SELECT id,payload_json FROM events WHERE kind=? ORDER BY id DESC LIMIT 1', (KIND,))
        c.e.store.set_meta(tick=1)
        future = c.commons.publish(c.heir, body='Later-day parent')
        value = json.loads(receipt['payload_json']); value['arguments']['parent_entry_id'] = future['id']
        error = 'future argument reference'
    else:
        first = c.commons.feed(c.heir)['entries'][0]['impression_id']
        other = c.commons.feed(c.person)['entries'][0]['impression_id']
        c.commons.read(c.heir, first)
        receipt = c.e.store.query_one('SELECT id,payload_json FROM events WHERE kind=? ORDER BY id DESC LIMIT 1', (KIND,))
        value = json.loads(receipt['payload_json']); value['arguments']['impression_id'] = other
        error = 'another viewer'
    c.e.store.execute('UPDATE events SET payload_json=? WHERE id=?', (json.dumps(value), receipt['id']))
    closed_copy(c.e.store, source)
    target, _, replay = replay_controls(c, baseline, source)
    try:
        before = contents(target.e.store)
        with pytest.raises(CommonsReplayError, match=error):
            replay.restore_population_inputs(1)
        assert contents(target.e.store) == before
    finally:
        target.e.store.close()


def test_in_phase_modeled_inputs_reject_while_observation_remains_pure(commons_case):
    c = commons_case
    _, external, auth = controls(c)
    c.commons.publish(c.heir, body='Visible while a day runs')
    c.e.store.set_meta(active_tick=1, next_phase='MORNING')
    before = contents(c.e.store)
    for call in (lambda: c.commons.feed(c.person),
                 lambda: c.commons.publish(c.person, body='Not yet at a boundary')):
        with pytest.raises(CommonsError, match='committed day boundary'):
            call()
        assert contents(c.e.store) == before
    with pytest.raises(ExternalAgentError, match='committed day boundary'):
        external.create_connection(tenant_id='fixture', owner_id='fixture', display_name='Pending', tier='actor')
    with pytest.raises(ExternalAgentError, match='committed day boundary'):
        external.submit_action(auth, {'idempotency_key': 'in-phase'})
    assert c.commons.preview_feed(c.person)['observation_only'] is True
    assert contents(c.e.store) == before


def test_complete_world_social_sequence_control_interleaving_restart_and_export(scenario_world, tmp_path):
    entries = [proposal(), proposal('back', tick=3, due=5, cause='return')]
    overrides = {'participant_mode': {'enabled': True}, 'external_agents': {'enabled': True}}
    def create(name, source=None):
        world = scenario_world(entries, name, replay_source=source, config_overrides=overrides)
        seed_claim(world.economy)
        return world
    world = create('ordered-source')
    asyncio.run(world.step())
    # These source inputs deliberately alternate command families.
    world.commons.feed(23)
    arrival = world.runtime.external.create_connection(tenant_id='fixture', owner_id='owner',
        display_name='Interleaved arrival', tier='actor')
    participant = world.runtime.participant
    participant.acquire(23, 1, running=False)
    world.commons.ensure_profile(24, biography='Interleaved profile')
    participant.queue_action(1, {'type': 'do_nothing'}, 'First queued version', running=False)
    world.commons.publish(24, body='Between queue versions')
    participant.queue_action(1, {'type': 'do_nothing'}, 'Final queued version', running=False)
    claim = world.store.scalar("SELECT id FROM claims WHERE claim_key='region:1:commons_fixture'")
    # Exercise every social command before departure, then retain those records
    # through outside observation, return and a final-tail input.
    group = world.commons.create_community(24, name='Research members', visibility='members')
    world.commons.join_community(23, group['id'])
    world.commons.follow(23, 24)
    post = world.commons.publish(24, body='PRIVATE_BODY authoritative source', community_id=group['id'])
    reply = world.commons.publish(23, body='Member reply', parent_entry_id=post['id'])
    feed = world.commons.feed(23, kind='community', community_id=group['id'])
    impression = next(row['impression_id'] for row in feed['entries'] if row['id'] == post['id'])
    world.commons.read(23, impression)
    world.commons.read(23, impression)
    world.commons.react(23, post['id'], 'like')
    world.commons.feed(23, kind='hot')
    world.commons.react(23, post['id'], 'like', active=False)
    world.commons.follow(23, 24, active=False)
    label = world.commons.moderate(24, reply['id'], action='label', reason='Context')
    world.commons.appeal(23, label['moderation_action_id'], 'Please review')
    world.commons.moderate(24, reply['id'], action='hide', reason='Reviewing')
    world.commons.feed(23)
    world.commons.moderate(24, reply['id'], action='restore', reason='Reviewed')
    factual = world.commons.publish(24, body='Factual statement', claim_id=claim)
    impression = next(row['impression_id'] for row in world.commons.feed(23)['entries'] if row['id'] == factual['id'])
    world.commons.read(23, impression)
    for day in range(2, 7):
        if day == 4:
            asyncio.run(world.step(pause_after_phase='NIGHT_CLOSE'))
            scenario_world.close(world)
            world = create('ordered-source')
        asyncio.run(world.step())
        if day == 3:
            before = contents(world.store)
            assert world.commons.feed_for_agent(23)['observation_only'] is True
            assert contents(world.store) == before
            world.commons.moderate(24, reply['id'], action='limit_author', reason='Outside author retained')
            auth = world.runtime.external.authenticate(arrival['credential']['token'], rate_limit=False)
            turn = world.runtime.external.turn(auth)
            world.commons.publish(24, body='Before external submission')
            queued = world.runtime.external.submit_action(auth, {'idempotency_key': 'interleaved',
                'target_tick': turn['target_tick'], 'observed_projection_hash': turn['projection_hash'],
                'action': {'type': 'do_nothing'}})
            assert queued['status'] == 'queued'
            world.commons.feed(24)
        if day == 5:
            world.commons.publish(23, body='Returning member', community_id=group['id'])
            world.commons.feed(23)
        assert world.economy.ledger.reconcile()[0]
    # A final-tail input must replay without advancing a seventh economic day.
    world.commons.publish(23, body='Last committed boundary')
    world.commons.feed(23)
    source = Path(world.store.path)
    scenario_world.close(world)
    original = hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns
    replay = create('ordered-replay', source)
    for day in range(1, 7):
        if day == 4:
            asyncio.run(replay.step(pause_after_phase='NIGHT_CLOSE'))
            scenario_world.close(replay)
            replay = create('ordered-replay', source)
        asyncio.run(replay.step())
        assert replay.economy.ledger.reconcile()[0]
    assert replay.store.tick == 6
    replay_path = Path(replay.store.path)
    scenario_world.close(replay)
    with closing(open_read_only_connection(source, require_closed=True)) as src, \
            closing(open_read_only_connection(replay_path, require_closed=True)) as dst:
        proof = verify_replay_connections(src, dst)
        assert proof['exact'], proof['differences']
        source_hashes, replay_hashes = canonical_hashes(src), canonical_hashes(dst)
        for table in ('events', 'commons_profiles', 'commons_communities', 'commons_memberships',
                      'commons_follows', 'commons_entries', 'commons_feed_impressions', 'commons_reactions',
                      'commons_moderation_actions', 'commons_appeals', 'memories', 'beliefs', 'causal_links'):
            assert source_hashes['tables'][table] == replay_hashes['tables'][table], table
        first = export_bundle(src, tmp_path/'source-export', limits=ExportLimits(max_batch_rows=13))
        second = export_bundle(src, tmp_path/'source-export-large', limits=ExportLimits(max_batch_rows=128))
        assert first.name == second.name
        manifest = validate_bundle(first, database=src)
        assert manifest['contract_id'] == 'hash-contract-v8'
        validate_bundle(second, database=src)
        exported_replay = export_bundle(dst, tmp_path/'replay-export')
        validate_bundle(exported_replay, database=dst)
        with duckdb.connect() as reader:
            for table in ('commons_profiles', 'commons_communities', 'commons_memberships', 'commons_follows',
                          'commons_entries', 'commons_feed_impressions', 'commons_reactions',
                          'commons_moderation_actions', 'commons_appeals'):
                rows = reader.execute('SELECT * FROM read_parquet(?)', [str(first/f'{table}.parquet')]).fetchall()
                # Independently apply the declared 60-bit pseudonym rule to the
                # manifest's marked identity columns, then compare every field.
                expected = []
                for row in src.execute(f'SELECT * FROM {table}'):
                    values = []
                    for column in manifest['tables'][table]['columns']:
                        value = row[column]
                        if value is not None and column in manifest['tables'][table]['pseudonyms']:
                            raw = f"{manifest['authoritative_sha256']}:{value}".encode('utf-8')
                            value = int.from_bytes(hashlib.sha256(raw).digest()[:8], 'big') >> 4
                        values.append(value)
                    expected.append(tuple(values))
                assert sorted(rows, key=repr) == sorted(expected, key=repr), table
        assert src.execute('SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls').fetchone()[0] == 0
        operations = {json.loads(row[0])['operation'] for row in src.execute('SELECT payload_json FROM events WHERE kind=?', (KIND,))}
        assert operations == set(OPERATIONS)
    assert (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns) == original
    assert not any(Path(str(source)+suffix).exists() for suffix in ('-wal', '-shm', '-journal'))

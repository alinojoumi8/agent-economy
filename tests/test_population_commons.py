"""Draft local Commons activity, observation, rollback and recorded replay.

Semantics 21 is admitted only in disposable fixtures. The inferred legacy
Commons importer still does not support every social action or their ordering.
"""
import asyncio
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agents.memory import Memory
from engine.population_history import ResidenceError
from engine.store import open_read_only_connection
from server.external_api import install_external_routes
from world.commons import CommonsError, CommonsService
from world.replay_verify import verify_replay_connections

from .test_population_participation import depart, return_home
from .test_population_residence_history import contents
from .test_population_resident_services import (
    closed_copy, controls, move_person, replay_controls, resident_services,
)
from .test_population_scenario import proposal, scenario_world


@pytest.fixture
def commons_case(resident_services):
    c = resident_services
    c.commons = CommonsService(c.e, Memory(c.e.store, c.e.config))
    return c


def _unchanged_rejection(store, call, message='local resident'):
    before = contents(store)
    with pytest.raises(CommonsError, match=message):
        call()
    assert contents(store) == before


def test_departure_rejects_every_modeled_action_before_any_effect(commons_case):
    c, service = commons_case, commons_case.commons
    group = service.create_community(c.person, name='Recorded owners')
    entry = service.publish(c.person, body='Before departure', community_id=group['id'])
    delivery = service.feed(c.person)['entries'][0]['impression_id']
    moderation = service.moderate(c.person, entry['id'], action='label', reason='Review')
    # An earlier historical read cannot leave current eligibility cached as local.
    assert c.e.population.is_local(c.person, 0)
    depart(c)
    actions = [
        lambda: service.publish(c.person, body='Outside post'),
        lambda: service.publish(c.person, body='Outside claim', claim_id=999),
        lambda: service.feed(c.person),
        lambda: service.read(c.person, delivery),
        lambda: service.react(c.person, entry['id'], 'like'),
        lambda: service.follow(c.person, c.heir),
        lambda: service.create_community(c.person, name='Outside group'),
        lambda: service.join_community(c.person, group['id']),
        lambda: service.moderate(c.person, entry['id'], action='remove', reason='Outside'),
        lambda: service.appeal(c.person, moderation['moderation_action_id'], 'Outside appeal'),
        lambda: service.overview(c.person),
        lambda: service.act(c.person, {'type': 'post', 'body': 'Dispatched outside post'}),
    ]
    for action in actions:
        _unchanged_rejection(c.e.store, action)
    assert c.e.store.scalar('SELECT alive FROM agents WHERE id=?', (c.person,)) == 1
    assert c.e.store.scalar('SELECT COUNT(*) FROM llm_calls') == 0
    assert c.e.ledger.reconcile()[0]


def test_outside_observation_preserves_profiles_content_and_membership_acl(commons_case):
    c, service = commons_case, commons_case.commons
    group = service.create_community(c.person, name='Members', visibility='members')
    private = service.publish(c.person, body='Member record', community_id=group['id'])
    public = service.publish(c.heir, body='Public record')
    profile = service.profile(c.person)
    recorded_profile = service.ensure_profile(c.person)
    depart(c)
    before = contents(c.e.store)
    observed = service.feed_for_agent(c.person, kind='community', community_id=group['id'])
    assert observed['observation_only'] is True
    assert [row['id'] for row in observed['entries']] == [private['id']]
    assert all(row['impression_id'] is None and row['read'] is None for row in observed['entries'])
    assert service.profile(c.person) == profile
    assert service.ensure_profile(c.person) == recorded_profile
    assert service.entry(private['id'])['body'] == 'Member record'
    assert contents(c.e.store) == before
    _unchanged_rejection(c.e.store, lambda: service.preview_feed(c.heir, community_id=group['id']),
                         'membership')
    permitted = service.preview_feed(c.heir)
    assert [row['id'] for row in permitted['entries']] == [public['id']]
    assert contents(c.e.store) == before


def test_missing_profile_inspection_and_outside_preview_do_not_create_a_profile(commons_case):
    c, service = commons_case, commons_case.commons
    service.publish(c.heir, body='Readable without a new profile')
    _unchanged_rejection(c.e.store, lambda: service.profile(c.person), 'profile not found')
    depart(c)
    before = contents(c.e.store)
    assert service.feed_for_agent(c.person)['observation_only'] is True
    assert service.preview_feed(c.person)['entries']
    assert contents(c.e.store) == before
    _unchanged_rejection(c.e.store, lambda: service.ensure_profile(c.person))
    _unchanged_rejection(c.e.store, lambda: service.profile(c.person), 'profile not found')


def test_local_people_can_interact_with_outside_authors_and_returning_owner_can_act(commons_case):
    c, service = commons_case, commons_case.commons
    group = service.create_community(c.person, name='Retained role')
    entry = service.publish(c.person, body='Retained author', community_id=group['id'])
    depart(c)
    service.follow(c.heir, c.person)
    assert service.react(c.heir, entry['id'], 'like')['ok']
    delivered = service.feed(c.heir)['entries'][0]
    read = service.read(c.heir, delivered['impression_id'])
    assert read['memory_id'] is not None
    assert service.profile(c.person)['reputation'] == 1
    return_home(c)
    c.e.store.set_meta(tick=2)
    assert service.moderate(c.person, entry['id'], action='label', reason='Returned owner')['ok']
    assert service.publish(c.person, body='Returned post')['id'] > entry['id']
    assert 'observation_only' not in service.feed_for_agent(c.person)
    assert c.e.store.scalar('SELECT COUNT(*) FROM commons_memberships WHERE agent_id=?', (c.person,)) == 1
    assert c.e.store.scalar('SELECT COUNT(*) FROM commons_profiles WHERE agent_id=?', (c.person,)) == 1
    assert c.e.ledger.reconcile()[0]


def test_local_moderator_can_limit_an_outside_author_without_recreating_the_profile(commons_case):
    c, service = commons_case, commons_case.commons
    group = service.create_community(c.heir, name='Resident moderation')
    entry = service.publish(c.person, body='Recorded author', community_id=group['id'])
    depart(c)
    assert service.moderate(c.heir, entry['id'], action='limit_author', reason='Review')['ok']
    assert service.profile(c.person)['status'] == 'limited'
    assert c.e.store.scalar('SELECT COUNT(*) FROM commons_profiles WHERE agent_id=?', (c.person,)) == 1


def test_factual_delivery_is_not_exposure_and_reading_resumes_once_after_return(commons_case):
    c, service = commons_case, commons_case.commons
    event = c.e.store.log_event(0, 'recorded_region_observation', {'value': True},
                               subject_type='region', subject_id=1)
    claim = c.e.information.create_claim(0, c.heir, {'claim_key': 'region:1:observed',
        'subject_type': 'region', 'subject_id': 1, 'predicate': 'observed', 'value': True,
        'truth_status': 'verified', 'source_event_ids': [event]})
    entry = service.publish(c.heir, body='Factual Commons entry', claim_id=claim['claim_id'])
    impression = service.feed(c.person)['entries'][0]['impression_id']
    assert c.e.store.scalar('SELECT COUNT(*) FROM information_exposures') == 0
    depart(c)
    _unchanged_rejection(c.e.store, lambda: service.read(c.person, impression))
    before = contents(c.e.store)
    preview = service.feed_for_agent(c.person)
    assert preview['entries'][0]['id'] == entry['id']
    assert contents(c.e.store) == before
    return_home(c)
    c.e.store.set_meta(tick=2)
    first = service.read(c.person, impression)
    before = contents(c.e.store)
    repeated = service.read(c.person, impression)
    assert first['exposure_id'] is not None and repeated['idempotent'] is True
    assert repeated['exposure_id'] == first['exposure_id']
    after = contents(c.e.store)
    assert {k: v for k, v in after.items() if k != 'events'} == {k: v for k, v in before.items() if k != 'events'}
    assert len(after['events']) == len(before['events']) + 1
    assert c.e.store.scalar("SELECT kind FROM events ORDER BY id DESC LIMIT 1") == 'commons_operation_recorded'
    assert c.e.store.scalar('SELECT COUNT(*) FROM information_exposures WHERE agent_id=?', (c.person,)) == 1
    assert c.e.ledger.reconcile()[0]


@pytest.mark.parametrize('operation', ['publish', 'feed', 'profile', 'agent_feed'])
def test_invalid_residence_history_fails_closed_before_commons_effects(commons_case, monkeypatch, operation):
    c, service = commons_case, commons_case.commons
    def invalid(_agent):
        raise ResidenceError('invalid recorded chain')
    monkeypatch.setattr(c.e.population, 'is_available', invalid)
    calls = {'publish': lambda: service.publish(c.person, body='Rejected'),
             'feed': lambda: service.feed(c.person),
             'profile': lambda: service.ensure_profile(c.person),
             'agent_feed': lambda: service.feed_for_agent(c.person)}
    _unchanged_rejection(c.e.store, calls[operation], 'valid residence history')


@pytest.mark.parametrize('operation', ['publish', 'react', 'feed', 'read', 'community', 'follow'])
def test_failed_operation_rolls_back_profile_rows_and_every_related_effect(commons_case, monkeypatch, operation):
    c, service = commons_case, commons_case.commons
    entry = service.publish(c.heir, body='Existing post')
    impression = service.feed(c.person)['entries'][0]['impression_id'] if operation == 'read' else None
    before = contents(c.e.store)
    def fail(*_args, **_kwargs):
        raise RuntimeError('injected Commons persistence failure')
    if operation == 'feed':
        monkeypatch.setattr(service.causal, 'create', fail)
    else:
        monkeypatch.setattr(c.e.store, 'log_event', fail)
    calls = {'publish': lambda: service.publish(c.person, body='Roll back my profile and post'),
             'react': lambda: service.react(c.person, entry['id'], 'like'),
             'feed': lambda: service.feed(c.person),
             'read': lambda: service.read(c.person, impression),
             'community': lambda: service.create_community(c.person, name='Rollback'),
             'follow': lambda: service.follow(c.person, c.heir)}
    with pytest.raises(RuntimeError, match='injected Commons'):
        calls[operation]()
    assert contents(c.e.store) == before


def test_invalid_post_and_nested_caller_transaction_leave_no_partial_profile(commons_case):
    c, service = commons_case, commons_case.commons
    _unchanged_rejection(c.e.store, lambda: service.publish(c.person, body='  '), 'body is required')
    before = contents(c.e.store)
    with pytest.raises(RuntimeError, match='caller rollback'):
        with c.e.store.savepoint('caller'):
            service.publish(c.person, body='Successful inner operation')
            raise RuntimeError('caller rollback')
    assert contents(c.e.store) == before


def test_rest_and_mcp_outside_reads_are_observations_and_writes_are_rejected(commons_case):
    c, commons = commons_case, commons_case.commons
    _, service, auth = controls(c)
    scopes = ['world.read', 'world.act', 'commons.read', 'commons.write', 'moderation.act']
    c.e.store.execute('UPDATE external_agent_connections SET scopes_json=? WHERE id=?',
                      (json.dumps(scopes), auth['id']))
    credential = service._issue_credential(auth['id'], 'personal', scopes, prefix='ae_pat_',
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    app = FastAPI()
    world = SimpleNamespace(runtime=SimpleNamespace(external=service), commons=commons)
    install_external_routes(app, world)
    commons.publish(c.heir, body='Transport observation')
    depart(c)
    def science():
        return {key: value for key, value in contents(c.e.store).items()
                if not key.startswith('external_')}
    before = science()
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer ' + credential['token']
        read = client.get('/api/v2/agent/commons')
        assert read.status_code == 200, read.text
        assert read.json()['observation_only'] is True
        write = client.post('/api/v2/agent/commons', json={'action': {'type': 'post', 'body': 'Outside'}})
        assert write.status_code == 409 and 'local resident' in write.text
        rpc = lambda name, args: client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1,
            'method': 'tools/call', 'params': {'name': name, 'arguments': args}}).json()
        observed = rpc('ae_commons_read', {})
        assert json.loads(observed['result']['content'][0]['text'])['observation_only'] is True
        rejected = rpc('ae_commons_act', {'action': {'type': 'post', 'body': 'Outside MCP'}})
        assert rejected['error']['code'] == -32001
        assert 'local resident' in rejected['error']['message']
        assert science() == before
        return_home(c)
        c.e.store.set_meta(tick=2)
        returned = client.get('/api/v2/agent/commons')
        assert returned.status_code == 200 and 'observation_only' not in returned.json()
        assert returned.json()['entries'][0]['impression_id'] is not None
    assert c.e.ledger.reconcile()[0]


@pytest.mark.parametrize('kind', ['post', 'feed', 'reaction', 'community'])
def test_replay_preflights_later_outside_actor_before_importing_the_first_post(commons_case, tmp_path, kind):
    c, commons = commons_case, commons_case.commons
    baseline, source = tmp_path / 'target.db', tmp_path / 'closed-source.db'
    closed_copy(c.e.store, baseline)
    first = commons.publish(c.person, body='Earlier valid actor')
    calls = {'post': lambda: commons.publish(c.heir, body='Later unavailable actor'),
             'feed': lambda: commons.feed(c.heir),
             'reaction': lambda: commons.react(c.heir, first['id'], 'like'),
             'community': lambda: commons.create_community(c.heir, name='Later owner')}
    calls[kind]()
    closed_copy(c.e.store, source)
    original = hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns
    target, _, replay = replay_controls(c, baseline, source)
    try:
        move_person(target, target.heir)
        _unchanged_rejection(target.e.store, lambda: replay._restore_replay_commons(1))
        assert target.e.ledger.reconcile()[0]
    finally:
        target.e.store.close()
    assert (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns) == original
    assert not any(Path(str(source) + suffix).exists() for suffix in ('-wal', '-shm', '-journal'))


def test_feed_reconstruction_failure_rolls_back_the_entire_commons_import(commons_case, tmp_path):
    c, commons = commons_case, commons_case.commons
    baseline, source = tmp_path / 'target.db', tmp_path / 'closed-source.db'
    closed_copy(c.e.store, baseline)
    commons.publish(c.person, body='Valid source post')
    commons.feed(c.person)
    closed_copy(c.e.store, source)
    original = hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns
    target, _, replay = replay_controls(c, baseline, source)
    try:
        # The replay's different local policy must cause exact reconstruction to
        # fail after entry/profile delivery work, without modifying the source.
        target.e.store.insert('commons_feed_policies', policy_key='replay-mismatch',
            version=2, algorithm='chronological', weights_json='{}', active=1, created_tick=0)
        before = contents(target.e.store)
        with pytest.raises(RuntimeError, match='does not match replay'):
            replay._restore_replay_commons(1)
        assert contents(target.e.store) == before
    finally:
        target.e.store.close()
    assert (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns) == original


def test_world_departure_return_and_supported_commons_inputs_replay_exactly(scenario_world):
    entries = [proposal(), proposal('back', tick=3, due=5, cause='return')]
    world = scenario_world(entries, 'commons-source')
    for day in range(1, 7):
        if day == 4:
            asyncio.run(world.step(pause_after_phase='NIGHT_CLOSE'))
            scenario_world.close(world)
            world = scenario_world(entries, 'commons-source')
        asyncio.run(world.step())
        if day in (1, 3, 5):
            actor = 23 if day != 3 else 24
            world.commons.publish(actor, body=f'Day {day} public record')
            world.commons.feed(actor)
            world.commons.publish(actor, body=f'Day {day} after delivery')
        if 2 <= day < 5:
            before = contents(world.store)
            assert world.commons.feed_for_agent(23)['observation_only'] is True
            assert contents(world.store) == before
        assert world.economy.ledger.reconcile()[0]
    source = Path(world.store.path)
    scenario_world.close(world)
    original = hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns
    replay = scenario_world(entries, 'commons-replay', replay_source=source)
    for _ in range(6):
        asyncio.run(replay.step())
    assert replay.economy.ledger.reconcile()[0]
    assert replay.store.scalar('SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls') == 0
    replay_path = Path(replay.store.path)
    scenario_world.close(replay)
    with closing(open_read_only_connection(source, require_closed=True)) as src, \
            closing(open_read_only_connection(replay_path, require_closed=True)) as dst:
        result = verify_replay_connections(src, dst)
        assert result['exact'], result['differences']
    assert (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns) == original
    assert not any(Path(str(source) + suffix).exists() for suffix in ('-wal', '-shm', '-journal'))

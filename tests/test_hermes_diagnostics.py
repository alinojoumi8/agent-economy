"""Network-free diagnostics using disposable worlds and a fake Hermes process."""
import asyncio
from argparse import Namespace
import hashlib
import json
from pathlib import Path
import socket
import sqlite3


import httpx
import pytest
import yaml
from fastapi import HTTPException
from fastapi.testclient import TestClient

from scripts.hermes_citizens import HermesCallTimeout, cohort_lock
from scripts.hermes_diagnostics import (
    DiagnosticError, DiagnosticOperator, budget_state, lock_state, parse_args, readonly_database,
)
from server.app import create_app
from server.controller import RunController
from tests.test_external_agent_gateway import _world, _connection


@pytest.fixture(autouse=True)
def no_live_calls(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('A diagnostic test attempted a real network/model/process call')
    connect = socket.socket.connect
    def checked_connect(sock, address):
        # Windows asyncio builds its internal wakeup socket pair using loopback.
        # Permit only that stdlib call site; all application connections fail.
        import sys
        fallback = getattr(socket, '_fallback_socketpair', None)
        if fallback is not None and sys._getframe(1).f_code is fallback.__code__:
            return connect(sock, address)
        return forbidden(sock, address)
    monkeypatch.setattr(socket.socket, 'connect', checked_connect)
    monkeypatch.setattr('scripts.hermes_citizens.run_hermes_process', forbidden)
    monkeypatch.setattr('scripts.hermes_citizens.CohortOperator.setup', forbidden)
    monkeypatch.setattr('scripts.hermes_citizens.CohortOperator.run', forbidden)
    monkeypatch.setattr('scripts.hermes_citizens.CohortOperator.decide', forbidden)


@pytest.fixture
def diagnostic(tmp_path):
    world = _world(tmp_path, engine_semantics_version=20, local_turn_renewal_contract="paused-next-turn-v2")
    created = _connection(world)
    root = tmp_path / 'data/control-plane/hermes-cohort/external-test'
    root.mkdir(parents=True)
    home = tmp_path / 'profiles/maya'
    home.mkdir(parents=True)
    citizen = {'profile': 'maya', 'name': 'Maya', 'goal': 'Work', 'home': str(home),
               'connection_id': created['connection']['id']}
    (root / 'manifest.json').write_text(json.dumps({'run_id': 'external-test', 'citizens': [citizen]}))
    token = created['credential']['token']
    (home / 'agent-economy.json').write_text(json.dumps({'access_token': token}))
    (home / 'config.yaml').write_text(yaml.safe_dump({
        'model': {'provider': 'openai-codex', 'default': 'gpt-5.6-luna'},
        'mcp_servers': {'agent_economy': {'url': 'http://127.0.0.1:8000/mcp',
            'headers': {'Authorization': 'Bearer ' + token},
            'tools': {'include': ['ae_identity_get', 'ae_world_observe', 'ae_turn_wait',
                                 'ae_actions_list', 'ae_action_submit', 'ae_action_receipt_get']}}}}))
    with sqlite3.connect(home / 'state.db') as db:
        db.execute('CREATE TABLE sessions (id TEXT)')
        db.execute("INSERT INTO sessions VALUES ('diagnostic-session')")
    operator = DiagnosticOperator(Namespace(run_id='external-test', url='http://127.0.0.1:8000',
        world_root=tmp_path, profiles_root=home.parent, hermes_python='never-execute', budget_db=None))
    operator.database = Path(world.store.path)
    operator.client.close()
    app = create_app(world)
    client = TestClient(app, client=("127.0.0.1", 55000))
    requests = []
    def dispatch(request):
        requests.append((request.method, request.url.path))
        reply = client.request(request.method, request.url.path, content=request.content, headers=dict(request.headers))
        return httpx.Response(reply.status_code, content=reply.content)
    operator.client = httpx.Client(base_url=operator.args.url, transport=httpx.MockTransport(dispatch))
    yield operator, world, citizen, requests
    operator.client.close()
    client.close()
    world.close()


def hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def fake_hermes(monkeypatch, world, citizen, *, action=None, fail=None, wrong_hash=False):
    calls = []
    def attempt(command, **kwargs):
        calls.append(command)
        assert kwargs['timeout'] == 240
        assert command[command.index('--max-turns') + 1] == '12'
        assert command[command.index('--run-budget') + 1] == '180'
        assert command[command.index('--provider') + 1] == 'openai-codex'
        assert '--supervise' not in command and '--setup' not in command
        kwargs['stdout'].write('Session: diagnostic-session\n')
        if fail == 'timeout':
            raise HermesCallTimeout('private provider message')
        if fail == 'no_receipt':
            return Namespace(returncode=0)
        token = json.loads((Path(citizen['home']) / 'agent-economy.json').read_text())['access_token']
        service = world.runtime.external
        auth = service.authenticate(token, rate_limit=False)
        turn = service.turn(auth)
        service.submit_action(auth, {'target_tick': turn['target_tick'],
            'observed_projection_hash': '0' * 64 if wrong_hash else turn['projection_hash'],
            'idempotency_key': 'one-attempt', 'action': action or {'type': 'do_nothing'}})
        world.store.commit()
        return Namespace(returncode=0)
    monkeypatch.setattr('scripts.hermes_citizens.run_hermes_process', attempt)
    return calls


def test_check_zero_writes_models_or_ticks(diagnostic, monkeypatch, tmp_path):
    op, world, citizen, requests = diagnostic
    before = hashes(tmp_path)
    changes = world.store.conn.total_changes
    writes = []
    def authorizer(action, *args):
        if action in {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_DELETE, sqlite3.SQLITE_UPDATE,
                      sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_CREATE_INDEX}:
            writes.append(action)
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    world.store.conn.set_authorizer(authorizer)
    monkeypatch.setattr(Path, 'mkdir', lambda *a, **k: pytest.fail('CHECK mkdir'))
    result = op.check()
    world.store.conn.set_authorizer(None)
    assert result['local']['profile_count'] == 1
    assert result['local']['profiles'][0]['admission']['status'] == 'active'
    assert result['server']['tick'] == 0 and not result['server']['running']
    assert result['snapshot_consistent']
    assert requests == [('GET', '/api/run/diagnostics')]
    assert world.store.conn.total_changes == changes and writes == []
    assert hashes(tmp_path) == before


def test_check_missing_manifest_does_not_create_directory(tmp_path):
    op = DiagnosticOperator(Namespace(run_id='missing', url='http://127.0.0.1:8000', world_root=tmp_path,
        profiles_root=tmp_path, hermes_python='unused', budget_db=None))
    try:
        with pytest.raises(FileNotFoundError):
            op.check()
        assert list(tmp_path.iterdir()) == []
    finally:
        op.client.close()


def test_readonly_database_cannot_write(tmp_path):
    path = tmp_path / 'closed.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE run_meta(tick INTEGER)')
    with readonly_database(path) as db:
        with pytest.raises(sqlite3.OperationalError, match='readonly'):
            db.execute('UPDATE run_meta SET tick=999')


def test_readonly_budget_and_lock_probe(tmp_path):
    path = tmp_path / 'budget.db'
    with sqlite3.connect(path) as db:
        db.executescript('CREATE TABLE budget_contract(singleton INTEGER,json TEXT); CREATE TABLE budget_status(singleton INTEGER,sealed INTEGER); '
            'CREATE TABLE reservations(state TEXT,reserved_input INTEGER,reserved_output INTEGER,reserved_cost INTEGER,input_tokens INTEGER,output_tokens INTEGER,usage_cost INTEGER);')
        db.execute('INSERT INTO budget_contract VALUES (1,?)', (json.dumps({'max_provider_calls': 2,'max_tokens': 50,'max_spend_nano_usd': 100}),))
        db.execute('INSERT INTO budget_status VALUES (1,0)')
        db.execute("INSERT INTO reservations VALUES ('settled',20,10,50,10,5,25)")
    lock = tmp_path / 'operator.lock'
    assert lock_state(lock) == 'absent' and not lock.exists()
    with cohort_lock(lock):
        before = path.read_bytes()
        size = lock.stat().st_size
        assert lock_state(lock) == 'held'
        state = budget_state(path)
        assert state['totals'][0]['calls'] == 1 and state['limits']['max_provider_calls'] == 2
        assert path.read_bytes() == before and lock.stat().st_size == size
    assert lock_state(lock) == 'available'


@pytest.mark.parametrize('extra', [[], ['--profile','maya','--profile','omar'], ['--profile','maya,omar'], ['--profile','maya','--days','1'], ['--profile','maya','--setup']])
def test_decide_requires_exactly_one_explicit_profile(extra):
    with pytest.raises(SystemExit):
        parse_args(['--run-id','one','--url','http://127.0.0.1:8000','decide-one',*extra])


def test_decide_queues_one_validated_action_without_advancing(diagnostic, monkeypatch):
    op, world, citizen, requests = diagnostic
    calls = fake_hermes(monkeypatch, world, citizen)
    before = world.store.tick
    result = op.decide_one('maya')
    assert result['outcome'] == 'queued', result
    assert len(calls) == 1
    assert world.store.tick == before and world.store.get_meta()['active_tick'] is None
    assert [r['status'] for r in result['receipts']] == ['queued']
    assert all(path in {'/api/run/diagnostics','/api/v2/agent/me','/api/v2/agent/turn/renew'} for _,path in requests)
    assert sum(method == 'POST' for method,_ in requests) == 1
    assert (Path(result['evidence']) / 'before.json').is_file()
    with pytest.raises(DiagnosticError, match='decision_already_recorded'):
        op.decide_one('maya')
    assert len(calls) == 1


@pytest.mark.parametrize('failure', ['timeout','no_receipt','invalid_action','stale_hash'])
def test_decide_never_retries_and_keeps_gateway_validation(diagnostic, monkeypatch, failure):
    op, world, citizen, requests = diagnostic
    calls = fake_hermes(monkeypatch, world, citizen, fail=failure,
        action={'type':'invented_action'} if failure == 'invalid_action' else None,
        wrong_hash=failure == 'stale_hash')
    result = op.decide_one('maya')
    assert result['outcome'] == 'ambiguous'
    assert len(calls) == 1 and world.store.tick == 0
    assert not any(r['status'] == 'queued' for r in result['receipts'])
    assert not (op.root / 'decision-retries.jsonl').exists()
    assert 'private provider message' not in (Path(result['evidence']) / 'after.json').read_text()


def test_decide_cannot_admit(diagnostic):
    op, world, citizen, requests = diagnostic
    world.store.execute("UPDATE external_agent_connections SET actor_id=NULL,status='pending_actor' WHERE id=?", (citizen['connection_id'],))
    world.store.commit()
    with pytest.raises(DiagnosticError, match='admission_required'):
        op.decide_one('maya')
    assert requests == [] and world.store.tick == 0
    assert world.store.scalar('SELECT COUNT(*) FROM external_action_submissions') == 0


@pytest.mark.parametrize('key,value,reason', [('run_id','other','identity_mismatch'), ('connection_id','other','identity_mismatch'),
    ('status','pending_actor','admission_required'), ('actor',{'id':999,'alive':True},'identity_not_active')])
def test_decide_rejects_stale_identity_before_model(diagnostic, key, value, reason):
    op, world, citizen, requests = diagnostic
    prior = op.client
    def handler(req):
        response = prior.send(req)
        payload = response.json()
        if req.url.path == '/api/v2/agent/me':
            payload[key] = value
        return httpx.Response(response.status_code, json=payload)
    op.client = httpx.Client(base_url=op.args.url, transport=httpx.MockTransport(handler))
    result = op.decide_one('maya')
    prior.close()
    assert result['outcome'] == 'ambiguous' and result['reason'] == reason
    assert not any(method == 'POST' for method,_ in requests)
    assert world.store.tick == 0


def test_decide_read_failure_no_transport_retry(diagnostic):
    op, world, citizen, _ = diagnostic
    calls = []
    def fail(req):
        calls.append(req)
        raise httpx.ReadError('lost response', request=req)
    op.client.close()
    op.client = httpx.Client(base_url=op.args.url, transport=httpx.MockTransport(fail))
    with pytest.raises(httpx.ReadError):
        op.decide_one('maya')
    assert len(calls) == 1 and world.store.tick == 0


@pytest.mark.parametrize('path', ['/api/run/step','/api/run/advance-one','/api/v2/public/agent-registrations','/api/run/start'])
def test_decision_transport_forbids_admission_and_clock(diagnostic, path):
    op, *_ = diagnostic
    with pytest.raises(DiagnosticError, match='diagnostic_api_forbidden'):
        op.api(path, body={})


def test_advance_whole_world_one_tick_and_reject_duplicate(diagnostic):
    op, world, citizen, requests = diagnostic
    result = op.advance_one(0)
    assert result['outcome'] == 'advanced', result
    assert world.store.tick == 1 and world.store.get_meta()['active_tick'] is None
    assert sum(path == '/api/run/advance-one' for _,path in requests) == 1
    with pytest.raises(DiagnosticError, match='stale_expected_tick'):
        op.advance_one(0)
    assert world.store.tick == 1


@pytest.mark.parametrize('run_id,tick,reason', [('other',0,'wrong_run_id'),('external-test',1,'stale_expected_tick')])
def test_server_atomically_rejects_identity_or_tick(diagnostic, run_id, tick, reason):
    _, world, *_ = diagnostic
    controller = RunController(world)
    with pytest.raises(HTTPException) as error:
        asyncio.run(controller.advance_one(run_id,tick))
    assert error.value.detail == reason and world.store.tick == 0


@pytest.mark.parametrize('guard', ['running','partial','lock'])
def test_server_rejects_running_partial_or_concurrent_world(diagnostic, guard):
    _, world, *_ = diagnostic
    controller = RunController(world)
    async def exercise():
        if guard == 'running':
            controller._step_active = True
        elif guard == 'partial':
            world.store.set_meta(active_tick=1)
        else:
            await controller._control_lock.acquire()
        try:
            with pytest.raises(HTTPException) as error:
                await controller.advance_one('external-test',0)
            return error.value.detail
        finally:
            if guard == 'lock':
                controller._control_lock.release()
    assert asyncio.run(exercise()) == {'running':'world_running','partial':'partial_tick_requires_recovery','lock':'controller_busy'}[guard]
    assert world.store.tick == 0


def test_concurrent_advance_executes_at_most_once(diagnostic, monkeypatch):
    _, world, *_ = diagnostic
    controller = RunController(world)
    real_step = world.step
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = []
    async def delayed():
        calls.append(1)
        entered.set()
        await release.wait()
        return await real_step()
    monkeypatch.setattr(world, 'step', delayed)
    async def exercise():
        first = asyncio.create_task(controller.advance_one('external-test',0))
        await entered.wait()
        with pytest.raises(HTTPException, match='controller_busy'):
            await controller.advance_one('external-test',0)
        release.set()
        return await first
    assert asyncio.run(exercise())['outcome'] == 'advanced'
    assert calls == [1] and world.store.tick == 1


def test_advance_lost_response_is_ambiguous_never_retried(diagnostic):
    op, world, citizen, _ = diagnostic
    prior = op.client
    posts = []
    def handler(req):
        response = prior.send(req)
        if req.method == 'POST':
            posts.append(req)
            raise httpx.ReadError('committed but response lost', request=req)
        return response
    op.client = httpx.Client(base_url=op.args.url, transport=httpx.MockTransport(handler))
    result = op.advance_one(0)
    prior.close()
    assert len(posts) == 1 and world.store.tick == 1
    assert result['outcome'] == 'ambiguous' and result['after']['tick'] == 1
    assert (Path(result['evidence']) / 'after.json').exists()


def test_server_keeps_acceptance_guard(diagnostic):
    _, world, *_ = diagnostic
    controller = RunController(world)
    controller.acceptance_configured = True
    controller.acceptance_authorized = False
    with pytest.raises(HTTPException) as exc:
        asyncio.run(controller.advance_one('external-test', 0))
    assert exc.value.status_code == 403 and world.store.tick == 0


def test_hosted_routes_are_not_exposed_and_request_is_strict(diagnostic):
    _, world, *_ = diagnostic
    app = create_app(world, hosted_safe=True)
    assert '/api/run/advance-one' not in {getattr(r, 'path', None) for r in app.routes}
    assert '/api/run/diagnostics' not in {getattr(r, 'path', None) for r in app.routes}
    with TestClient(create_app(world)) as client:
        for value in [True, '0', -1]:
            response = client.post('/api/run/advance-one',json={'expected_run_id':'external-test','expected_tick':value})
            assert response.status_code == 422
    assert world.store.tick == 0



def test_decide_pending_admission_precedes_profile_configuration(diagnostic):
    op, world, citizen, requests = diagnostic
    world.store.execute("UPDATE external_agent_connections SET actor_id=NULL,status='pending_actor' WHERE id=?", (citizen['connection_id'],))
    world.store.commit()
    (Path(citizen['home']) / 'config.yaml').unlink()
    with pytest.raises(DiagnosticError, match='admission_required'):
        op.decide_one('maya')
    assert world.store.tick == 0


def test_advance_ambiguous_exception_after_step_does_not_repeat(diagnostic, monkeypatch):
    _, world, *_ = diagnostic
    controller = RunController(world)
    real_step = world.step
    calls = []
    async def lost_result():
        calls.append(1)
        await real_step()
        raise RuntimeError('lost final result')
    monkeypatch.setattr(world, 'step', lost_result)
    with pytest.raises(RuntimeError, match='lost final result'):
        asyncio.run(controller.advance_one('external-test',0))
    assert calls == [1] and world.store.tick == 1
    with pytest.raises(HTTPException, match='stale_expected_tick'):
        asyncio.run(controller.advance_one('external-test',0))
    assert calls == [1]


@pytest.mark.parametrize('name', ['supervisor.lock', 'operator.lock'])
def test_existing_lock_blocks_decision_and_advance(diagnostic, name):
    op, world, *_ = diagnostic
    with cohort_lock(op.root / name):
        with pytest.raises(DiagnosticError, match='controller_busy'):
            op.decide_one('maya')
        with pytest.raises(DiagnosticError, match='controller_busy'):
            op.advance_one(0)
    assert world.store.tick == 0


def test_check_wrong_run_and_database_are_visible(diagnostic):
    op, world, citizen, requests = diagnostic
    other = op.database.with_name('different.db')
    with readonly_database(op.database) as snapshot:
        with sqlite3.connect(other) as target:
            snapshot.backup(target)
    op.database = other
    with pytest.raises(DiagnosticError, match='database_identity_mismatch'):
        op.check()
    op.database = Path(world.store.path)
    world.store.set_meta(run_id='other')
    world.store.commit()
    with pytest.raises(DiagnosticError, match='wrong_run_id'):
        op.check()


def test_stale_boundary_during_turn_renewal_stops_before_model(diagnostic):
    op, world, citizen, requests = diagnostic
    prior = op.client
    reads = []
    def handler(req):
        response = prior.send(req)
        payload = response.json()
        if req.url.path == '/api/run/diagnostics':
            reads.append(1)
            if len(reads) >= 2:
                payload['tick'] = 1
        return httpx.Response(response.status_code, json=payload)
    op.client = httpx.Client(base_url=op.args.url, transport=httpx.MockTransport(handler))
    result = op.decide_one('maya')
    prior.close()
    assert result['reason'] == 'stale_expected_tick' and result['outcome'] == 'ambiguous'
    assert not any(method == 'POST' for method,_ in requests)


def test_step_governor_pause_is_not_retried(diagnostic, monkeypatch):
    _, world, *_ = diagnostic
    controller = RunController(world)
    calls = []
    async def budget_pause():
        calls.append(1)
        world.store.set_meta(active_tick=1)
        return {'tick': 0, 'paused': 'budget'}
    monkeypatch.setattr(world,'step',budget_pause)
    result = asyncio.run(controller.advance_one('external-test',0))
    assert result['outcome'] == 'not_completed' and calls == [1]
    assert result['after']['active_tick'] == 1 and world.store.tick == 0


def test_check_keeps_local_evidence_when_server_is_unavailable(diagnostic):
    op, world, citizen, requests = diagnostic
    op.client.close()
    def unavailable(request):
        raise httpx.ConnectError('no server', request=request)
    op.client = httpx.Client(base_url=op.args.url, transport=httpx.MockTransport(unavailable))
    result = op.check()
    assert result['local']['tick'] == 0 and result['local']['profile_count'] == 1
    assert result['server']['state'] == 'unavailable'
    assert not result['snapshot_consistent']


def test_ten_profile_manifest_dispatches_only_selected_citizen(diagnostic, monkeypatch):
    op, world, citizen, requests = diagnostic
    manifest = json.loads(op.manifest_path.read_text())
    manifest['citizens'].extend({**citizen,'profile':f'other-{i}','home':str(op.profiles / f'other-{i}'),
                                'connection_id':f'other-connection-{i}'} for i in range(9))
    op.manifest_path.write_text(json.dumps(manifest))
    calls = fake_hermes(monkeypatch, world, citizen)
    result = op.decide_one('maya')
    assert result['outcome'] == 'queued' and len(calls) == 1
    assert calls[0][calls[0].index('--profile') + 1] == 'maya'
    assert world.store.tick == 0
    assert not any((op.profiles / f'other-{i}').exists() for i in range(9))


# These tests bypass DiagnosticOperator: the server is the authority even when
# the caller omits preflight, or its observation becomes stale before the lock.
def boundary_evidence(world):
    from copy import deepcopy
    return {
        'database': world.store.conn.serialize(),
        'files': hashes(Path(world.store.path).parent),
        'changes': world.store.conn.total_changes,
        'world': deepcopy({name: getattr(world, name, None) for name in (
            'status', 'last_pause_reason', 'last_report_path',
            '_pause_requested', '_stop_requested')}),
    }


@pytest.mark.parametrize('transport', ['controller', 'api'])
@pytest.mark.parametrize('guard,reason', [
    ('finished', 'world_terminal'), ('halted', 'world_terminal'),
    ('error', 'world_terminal'), ('completed', 'world_terminal'),
    ('exhausted', 'world_terminal'), ('attention', 'attention_pause_requires_recovery'),
    ('limit', 'served_tick_limit_reached'), ('stale', 'stale_expected_tick'),
    ('identity', 'wrong_run_id'), ('running', 'world_running'),
    ('task_running', 'world_running'), ('partial', 'partial_tick_requires_recovery'),
    ('acceptance', 'acceptance steps require --acceptance-run and explicit live approval'),
    ('participant', 'choose an explicit participant action, including do nothing, before Step'),
])
def test_direct_advance_rejection_preserves_state(diagnostic, monkeypatch, transport, guard, reason):
    _, world, *_ = diagnostic
    app = create_app(world)
    controller = app.state.run_controller
    run_id, tick = 'external-test', 0
    if guard in {'finished', 'halted', 'error', 'completed', 'exhausted'}:
        world.status = guard
        world.store.set_meta(status=guard)
    elif guard == 'attention':
        world.status = 'paused'
        world.last_pause_reason = {'kind': 'provider_budget', 'attention_required': True}
    elif guard == 'limit':
        controller.target_tick = 0
    elif guard == 'stale':
        tick = 1
    elif guard == 'identity':
        run_id = 'wrong-run'
    elif guard == 'running':
        world.status = 'running'
    elif guard == 'task_running':
        controller._step_active = True
    elif guard == 'partial':
        world.store.set_meta(active_tick=1)
    elif guard == 'acceptance':
        controller.acceptance_configured = True
        controller.acceptance_authorized = False
    elif guard == 'participant':
        monkeypatch.setattr(controller.participant, 'active_agent_id', lambda: 1)
        monkeypatch.setattr(controller.participant, 'has_queued_action', lambda: False)
    world.store.commit()
    before = boundary_evidence(world)
    calls = []
    async def forbidden_step():
        calls.append(1)
        pytest.fail('Rejected diagnostic reached world.step')
    monkeypatch.setattr(world, 'step', forbidden_step)
    if transport == 'controller':
        with pytest.raises(HTTPException) as exc:
            asyncio.run(controller.advance_one(run_id, tick))
        status, detail = exc.value.status_code, exc.value.detail
    else:
        # No lifespan startup/shutdown: isolate the single route invocation.
        client = TestClient(app)
        try:
            reply = client.post('/api/run/advance-one', json={
                'expected_run_id': run_id, 'expected_tick': tick})
            status, detail = reply.status_code, reply.json()['detail']
        finally:
            client.close()
    assert status == (403 if guard == 'acceptance' else 409)
    assert detail == reason
    assert calls == [] and world.store.tick == 0
    assert boundary_evidence(world) == before


@pytest.mark.parametrize('transport', ['controller', 'api'])
@pytest.mark.parametrize('transition', ['finished', 'attention'])
def test_advance_revalidates_state_at_lock_acquisition(diagnostic, monkeypatch, transport, transition):
    _, world, *_ = diagnostic
    world.status = 'paused'
    app = create_app(world)
    controller = app.state.run_controller
    # The caller observes a safe boundary, then state changes during entry into
    # the server lock. Checking only before acquisition would miss this change.
    observed = controller.diagnostic_state()
    assert observed['status'] == 'paused' and observed['pause_reason'] is None
    lock = controller._control_lock
    after_transition = []
    class TransitionLock:
        def locked(self):
            return lock.locked()
        async def __aenter__(self):
            if transition == 'finished':
                world.status = 'finished'
                world.store.set_meta(status='finished')
            else:
                world.last_pause_reason = {'kind': 'operator_attention', 'reason': 'inspect'}
            world.store.commit()
            after_transition.append(boundary_evidence(world))
            await lock.acquire()
        async def __aexit__(self, *args):
            lock.release()
    monkeypatch.setattr(controller, '_control_lock', TransitionLock())
    calls = []
    async def forbidden_step():
        calls.append(1)
        pytest.fail('Stale preflight reached world.step')
    monkeypatch.setattr(world, 'step', forbidden_step)
    if transport == 'controller':
        with pytest.raises(HTTPException) as exc:
            asyncio.run(controller.advance_one('external-test', 0))
        status, detail = exc.value.status_code, exc.value.detail
    else:
        client = TestClient(app)
        try:
            reply = client.post('/api/run/advance-one', json={
                'expected_run_id': 'external-test', 'expected_tick': 0})
            status, detail = reply.status_code, reply.json()['detail']
        finally:
            client.close()
    assert status == 409
    assert detail == ('world_terminal' if transition == 'finished'
                      else 'attention_pause_requires_recovery')
    assert len(after_transition) == 1 and calls == [] and world.store.tick == 0
    assert boundary_evidence(world) == after_transition[0]


@pytest.mark.parametrize('transport', ['controller', 'api'])
def test_direct_advance_valid_paused_world_steps_once(diagnostic, monkeypatch, transport):
    _, world, *_ = diagnostic
    world.status = 'paused'
    world.store.set_meta(status='paused')
    app = create_app(world)
    controller = app.state.run_controller
    real_step = controller._step_locked
    calls = []
    async def governed_step():
        assert controller._control_lock.locked()
        calls.append(1)
        return await real_step()
    monkeypatch.setattr(controller, '_step_locked', governed_step)
    if transport == 'controller':
        result = asyncio.run(controller.advance_one('external-test', 0))
    else:
        client = TestClient(app)
        try:
            reply = client.post('/api/run/advance-one', json={
                'expected_run_id': 'external-test', 'expected_tick': 0})
            assert reply.status_code == 200
            result = reply.json()
        finally:
            client.close()
    assert result['outcome'] == 'advanced' and calls == [1]
    assert result['before']['tick'] == 0 and result['after']['tick'] == 1
    assert world.store.tick == 1 and world.store.get_meta()['active_tick'] is None
    assert world.status == 'paused' and not controller.is_running()

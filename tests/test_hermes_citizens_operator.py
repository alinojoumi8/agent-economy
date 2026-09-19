from argparse import Namespace
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import httpx
import psutil

import pytest

from scripts.hermes_citizens import (CohortOperator, COHORT, MissingQueuedAction,
    HermesCallTimeout, run_hermes_process, write_json)


@pytest.fixture
def api_operator(monkeypatch, tmp_path):
    monkeypatch.setattr('scripts.hermes_citizens.ROOT', tmp_path)
    operator = CohortOperator(Namespace(run_id='one', url='http://127.0.0.1:8000',
        hermes_python='unused', profiles_root=str(tmp_path), days=1))
    operator.client.close()
    yield operator
    operator.client.close()


@pytest.mark.parametrize('error_type', [
    httpx.ReadError, httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError,
])
def test_operator_retries_transient_reads_without_logging_secrets(api_operator, monkeypatch, error_type):
    requests, sleeps = [], []
    def handle(request):
        requests.append(request)
        if len(requests) == 1:
            raise error_type('private-error-detail', request=request)
        return httpx.Response(200, json={'actor': {'id': 34}})
    api_operator.client = httpx.Client(base_url='http://127.0.0.1:8000', transport=httpx.MockTransport(handle))
    monkeypatch.setattr('scripts.hermes_citizens.time.sleep', sleeps.append)

    assert api_operator.api('/api/v2/agent/me?secret=private-query', token='private-token') == {'actor': {'id': 34}}
    assert len(requests) == 2 and all(r.method == 'GET' for r in requests)
    assert all(r.headers['Authorization'] == 'Bearer private-token' for r in requests)
    assert sleeps == [.25]
    journal = (api_operator.root / 'api-read-retries.jsonl').read_text()
    event = json.loads(journal)
    assert event['path'] == '/api/v2/agent/me'
    assert event['error'] == error_type.__name__ and event['attempt'] == 1
    assert 'private-' not in journal


def test_operator_stops_after_three_failed_reads(api_operator, monkeypatch):
    requests, sleeps = [], []
    def handle(request):
        requests.append(request)
        raise httpx.ReadError('connection aborted', request=request)
    api_operator.client = httpx.Client(base_url='http://127.0.0.1:8000', transport=httpx.MockTransport(handle))
    monkeypatch.setattr('scripts.hermes_citizens.time.sleep', sleeps.append)

    with pytest.raises(httpx.ReadError):
        api_operator.api('/api/run/status')
    assert len(requests) == 3 and all(r.method == 'GET' for r in requests)
    assert sleeps == [.25, .5]
    assert len((api_operator.root / 'api-read-retries.jsonl').read_text().splitlines()) == 2


@pytest.mark.parametrize('path,body', [
    ('/api/run/control', {'action': 'step'}),
    ('/api/v2/agent/turn/renew', {'target_tick': 41}),
])
def test_operator_never_repeats_a_write_with_a_lost_response(api_operator, path, body):
    applied = []
    def handle(request):
        assert request.method == 'POST'
        applied.append(json.loads(request.content))
        raise httpx.ReadError('response lost after applying request', request=request)
    api_operator.client = httpx.Client(base_url='http://127.0.0.1:8000', transport=httpx.MockTransport(handle))

    with pytest.raises(httpx.ReadError):
        api_operator.api(path, body=body)
    assert applied == [body]
    assert not (api_operator.root / 'api-read-retries.jsonl').exists()


@pytest.mark.parametrize('status', [401, 429, 503, 200])
def test_operator_does_not_retry_http_or_json_failures(api_operator, status):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(status, text='not JSON')
    api_operator.client = httpx.Client(base_url='http://127.0.0.1:8000', transport=httpx.MockTransport(handle))

    with pytest.raises(ValueError if status == 200 else httpx.HTTPStatusError):
        api_operator.api('/api/run/status')
    assert len(requests) == 1
    assert not (api_operator.root / 'api-read-retries.jsonl').exists()


@pytest.mark.parametrize('missing_attempts,timeout,exit_code', [
    (0, False, 0), (1, False, 0), (3, False, 0),
    (0, True, 0), (1, True, 0), (3, True, 0),
    (3, False, 77), (0, False, 77),
])
def test_decide_uses_profile_luna_without_deepseek_key(monkeypatch, tmp_path, missing_attempts, timeout, exit_code):
    monkeypatch.setattr('scripts.hermes_citizens.ROOT', tmp_path)
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    operator = CohortOperator(Namespace(run_id='one', url='http://127.0.0.1:8000',
        hermes_python='unused', profiles_root=str(tmp_path), days=1))
    home = tmp_path / 'maya'
    home.mkdir()
    write_json(home / 'agent-economy.json', {'access_token': 'test-only'})
    (home / 'config.yaml').write_text('model:\n  provider: openai-codex\n  default: gpt-5.6-luna\n')
    with sqlite3.connect(home / 'state.db') as db:
        db.execute('CREATE TABLE sessions(id TEXT, started_at INTEGER)')
        db.execute("INSERT INTO sessions VALUES ('saved-session',1)")
        db.execute("INSERT INTO sessions VALUES ('unrelated-diagnostic',2)")
    citizen = {'name': 'Maya Chen', 'profile': 'maya', 'home': str(home), 'goal': 'Work'}
    if timeout:
        write_json(operator.root / 'maya/session.json', {'session_id': 'saved-session'})
    queued = []
    monkeypatch.setattr(operator, 'receipts', lambda *args: queued)
    monkeypatch.setattr(operator, 'api', lambda *args, **kwargs: {'actor': {'id': 1}, 'run_id': 'one', 'tick': 63})
    attempts = []
    def run(command, **kwargs):
        assert command[command.index('--provider')+1] == 'openai-codex'
        assert command[command.index('--model')+1] == 'gpt-5.6-luna'
        assert 'DEEPSEEK_API_KEY' not in kwargs['env']
        prompt = Path(command[command.index('--query-file')+1]).read_text()
        assert 'complete 64-character projection hash' in prompt and 'ae_turn_wait' in prompt
        attempts.append(command)
        if len(attempts) > 1:
            assert command[command.index('--resume')+1] == 'saved-session'
        if len(attempts) > missing_attempts:
            queued.append({'status': 'queued'})
        if timeout:
            raise HermesCallTimeout('Call exceeded 240 seconds')
        kwargs['stdout'].write('Session: saved-session\n')
        return Namespace(returncode=exit_code)
    monkeypatch.setattr('scripts.hermes_citizens.run_hermes_process', run)
    try:
        if exit_code and missing_attempts:
            with pytest.raises(RuntimeError, match=f'Hermes exit code {exit_code}'):
                operator.decide(citizen, 64)
        elif missing_attempts == 3:
            with pytest.raises(HermesCallTimeout if timeout else MissingQueuedAction):
                operator.decide(citizen, 64)
        else:
            operator.decide(citizen, 64)
        assert len(attempts) == (1 if exit_code else min(missing_attempts+1, 3))
        assert len(list((operator.root / 'maya').glob('tick-64-attempt-*.log'))) == len(attempts)
        assert json.loads((operator.root / 'maya/session.json').read_text())['session_id'] == 'saved-session'
        if timeout:
            events = [json.loads(line) for line in (operator.root / 'decision-timeouts.jsonl').read_text().splitlines()]
            assert len(events) == len(attempts)
            assert all(event['process_cleanup'] == 'complete' for event in events)
        if exit_code or timeout:
            exits = [json.loads(line) for line in (operator.root / 'decision-process-exits.jsonl').read_text().splitlines()]
            assert len(exits) == len(attempts)
            assert all(event['exit_code'] == (-1 if timeout else exit_code) for event in exits)
            assert 'test-only' not in json.dumps(exits)
    finally:
        operator.client.close()


@pytest.mark.parametrize('interruption', ['world_changed', 'stop', 'late_receipt', 'provider_error'])
@pytest.mark.parametrize('timeout', [False, True])
def test_recovery_respects_world_stop_receipts_and_provider_failure(monkeypatch, tmp_path, interruption, timeout):
    monkeypatch.setattr('scripts.hermes_citizens.ROOT', tmp_path)
    operator = CohortOperator(Namespace(run_id='one', url='http://127.0.0.1:8000',
        hermes_python='unused', profiles_root=str(tmp_path), days=1))
    queued, calls = [], []
    monkeypatch.setattr(operator, 'receipts', lambda *args: queued)
    monkeypatch.setattr(operator, 'check_world', lambda: {'tick': 64})
    def attempt(*args, **kwargs):
        calls.append(1)
        if interruption == 'stop':
            (operator.root / 'STOP').touch()
        if interruption == 'late_receipt':
            queued.append({'status': 'queued'})
        if interruption == 'provider_error':
            raise RuntimeError('Provider unavailable')
        raise (HermesCallTimeout if timeout else MissingQueuedAction)('No receipt')
    monkeypatch.setattr(operator, '_decide_once', attempt)
    try:
        if interruption in {'world_changed', 'provider_error'}:
            with pytest.raises(RuntimeError):
                operator.decide({'name': 'Maya Chen'}, 64)
        else:
            operator.decide({'name': 'Maya Chen'}, 64)
        assert len(calls) == 1
    finally:
        operator.client.close()


@pytest.mark.parametrize('timeout', [False, True])
def test_hermes_process_reaps_child_before_return_or_timeout(tmp_path, timeout):
    child_pid = tmp_path / 'child.pid'
    parent_pid = tmp_path / 'parent.pid'
    child = "import time; time.sleep(60)"
    parent = (
        'import subprocess,sys,time,pathlib,os; '
        f'pathlib.Path({str(parent_pid)!r}).write_text(str(os.getpid())); '
        f'p=subprocess.Popen([sys.executable,"-c",{child!r}]); '
        f'pathlib.Path({str(child_pid)!r}).write_text(str(p.pid)); '
        f'time.sleep({60 if timeout else 1})'
    )
    # An unrelated process must survive cleanup, even if it runs identical code.
    unrelated = subprocess.Popen([sys.executable, '-c', child])
    try:
        if timeout:
            with pytest.raises(HermesCallTimeout, match='exceeded'):
                run_hermes_process([sys.executable, '-c', parent], timeout=3,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            result = run_hermes_process([sys.executable, '-c', parent], timeout=10,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            assert result.returncode == 0
        assert not psutil.pid_exists(int(parent_pid.read_text()))
        assert not psutil.pid_exists(int(child_pid.read_text()))
        assert unrelated.poll() is None
    finally:
        unrelated.kill()
        unrelated.wait()


def test_process_cleanup_rechecks_child_ownership_after_pid_snapshot(monkeypatch):
    """A child-list snapshot may contain a PID now owned by another worker."""
    killed = []

    class Process:
        def __init__(self, pid, parent, created):
            self.pid, self.parent_id, self.created = pid, parent, created
            self.descendants = []
        def children(self, recursive=False):
            return self.descendants
        def ppid(self):
            return self.parent_id
        def create_time(self):
            return self.created
        def poll(self):
            return 0
        def suspend(self):
            pass
        def kill(self):
            assert self.pid not in {2, 3}, 'cleanup reached another worker'
            killed.append(self.pid)
        def wait(self):
            return 0

    root = Process(1, 999, 100)
    sibling = Process(2, 999, 101)  # PID reused after children() took its snapshot.
    older = Process(3, 1, 90)  # Its original parent used this root PID earlier.
    owned = Process(4, 1, 101)
    grandchild = Process(5, 4, 102)
    root.descendants = [sibling, older, owned]
    owned.descendants = [grandchild]
    monkeypatch.setattr('scripts.hermes_citizens.psutil.Popen', lambda *args, **kwargs: root)
    monkeypatch.setattr('scripts.hermes_citizens.psutil.wait_procs', lambda processes, **kwargs: (processes, []))
    assert run_hermes_process(['fake'], timeout=1).returncode == 0
    assert set(killed) == {1, 4, 5}


def test_fast_process_exit_does_not_require_creation_time_lookup(monkeypatch):
    class ExitedProcess:
        pid = 123
        def create_time(self):
            raise psutil.NoSuchProcess(self.pid)
        children = suspend = kill = create_time
        def poll(self):
            return 0
        def wait(self):
            return 0
    monkeypatch.setattr('scripts.hermes_citizens.psutil.Popen', lambda *args, **kwargs: ExitedProcess())
    monkeypatch.setattr('scripts.hermes_citizens.psutil.wait_procs', lambda processes, **kwargs: (processes, []))
    assert run_hermes_process(['already-exited'], timeout=1).returncode == 0


def test_incomplete_process_cleanup_is_not_retryable(monkeypatch):
    monkeypatch.setattr('scripts.hermes_citizens.psutil.wait_procs', lambda *args, **kwargs: ([], [object()]))
    with pytest.raises(RuntimeError, match='cleanup failed') as error:
        run_hermes_process([sys.executable, '-c', 'pass'], timeout=10,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert not isinstance(error.value, HermesCallTimeout)


def test_hundred_day_session_pauses_at_target(monkeypatch, tmp_path):
    monkeypatch.setattr("scripts.hermes_citizens.ROOT", tmp_path)
    operator = CohortOperator(Namespace(run_id="one", url="http://127.0.0.1:8000",
        hermes_python="unused", profiles_root=str(tmp_path), days=100))
    citizens = [{"name": name, "home": str(tmp_path / slug)} for slug, name, _, _ in COHORT]
    for citizen in citizens:
        write_json(Path(citizen["home"]) / "agent-economy.json", {"access_token": "test-only"})
    write_json(operator.manifest_path, {"citizens": citizens})
    state = {"run_id": "one", "tick": 41, "status": "paused"}
    decisions = []
    def api(path, **kwargs):
        if path == "/api/run/step":
            state["tick"] += 1
        if path == "/api/v2/agent/me":
            return {"status": "active"}
        return dict(state)
    monkeypatch.setattr(operator, "api", api)
    monkeypatch.setattr(operator, "decide", lambda citizen, tick: decisions.append((citizen["name"], tick)))
    monkeypatch.setattr(operator, "receipts", lambda *args: [{"status": "executed"}])
    try:
        operator.run()
        assert state["tick"] == 141
        assert len(decisions) == 1000
        assert len(list(operator.root.glob("day-*.json"))) == 100
        assert json.loads((operator.root / "status.json").read_text()) == {"state": "paused", "tick": 141}
    finally:
        operator.client.close()


def test_operator_rejects_wrong_world_or_partial_tick(monkeypatch, tmp_path):
    monkeypatch.setattr("scripts.hermes_citizens.ROOT", tmp_path)
    operator = CohortOperator(Namespace(run_id="one", url="http://127.0.0.1:8000",
        hermes_python="unused", profiles_root=str(tmp_path), days=1))
    try:
        monkeypatch.setattr(operator, "api", lambda *a, **k: {"run_id": "other"})
        with pytest.raises(RuntimeError, match="different world"):
            operator.check_world()
        monkeypatch.setattr(operator, "api", lambda *a, **k: {"run_id": "one", "active_tick": 3})
        with pytest.raises(RuntimeError, match="current world tick"):
            operator.check_world()
    finally:
        operator.client.close()


def test_resume_skips_already_queued_action_without_launching_hermes(monkeypatch, tmp_path):
    monkeypatch.setattr("scripts.hermes_citizens.ROOT", tmp_path)
    operator = CohortOperator(Namespace(run_id="one", url="http://127.0.0.1:8000",
        hermes_python="must-not-run", profiles_root=str(tmp_path), days=1))
    try:
        monkeypatch.setattr(operator, "receipts", lambda *args: [{"status": "queued"}])
        operator.decide({"name": "Maya Chen"}, 3)
        monkeypatch.setattr(operator, "receipts", lambda *args: [])
        (operator.root / "STOP").touch()
        operator.decide({"name": "Maya Chen"}, 3)
    finally:
        operator.client.close()


@pytest.mark.parametrize('keep_active_world', [False, True])
def test_setup_can_preserve_the_existing_selected_world(monkeypatch, tmp_path, keep_active_world):
    monkeypatch.setattr('scripts.hermes_citizens.ROOT', tmp_path)
    operator = CohortOperator(Namespace(run_id='new', url='http://127.0.0.1:18774',
        hermes_python='unused', profiles_root=str(tmp_path), keep_active_world=keep_active_world))
    active = tmp_path / 'data/control-plane/hermes-city.json'
    write_json(active, {'run_id': 'existing'})
    write_json(operator.manifest_path, {'citizens': [{'name': name} for _, name, _, _ in COHORT]})
    monkeypatch.setattr(operator, 'check_world', lambda: {})
    try:
        operator.setup()
        assert json.loads(active.read_text())['run_id'] == ('existing' if keep_active_world else 'new')
    finally:
        operator.client.close()


@pytest.mark.parametrize('url,allowed', [
    ('http://127.0.0.1:18774', True), ('http://localhost:8000', True),
    ('http://example.com:8000', False), ('http://127.0.0.1:8000/path', False),
    ('http://user:password@localhost:8000', False), ('https://localhost:8000', False)])
def test_operator_accepts_only_explicit_loopback_ports(monkeypatch, url, allowed):
    from scripts.hermes_citizens import main
    monkeypatch.setattr(sys, 'argv', ['hermes_citizens.py', '--run-id', 'one', '--url', url])
    called = []

    class Operator:
        def __init__(self, args):
            self.client = Namespace(close=lambda: None)
        def run(self):
            called.append(True)

    monkeypatch.setattr('scripts.hermes_citizens.CohortOperator', Operator)
    if allowed:
        main()
        assert called
    else:
        with pytest.raises(SystemExit): main()
        assert not called


def test_cohort_failure_does_not_advance_world(monkeypatch, tmp_path):
    monkeypatch.setattr("scripts.hermes_citizens.ROOT", tmp_path)
    operator = CohortOperator(Namespace(run_id="one", url="http://127.0.0.1:8000",
        hermes_python="unused", profiles_root=str(tmp_path), days=1))
    citizens = [{"name": name, "home": str(tmp_path / slug)} for slug, name, _, _ in COHORT]
    for citizen in citizens:
        from pathlib import Path
        write_json(Path(citizen["home"]) / "agent-economy.json", {"access_token": "test-only"})
    write_json(operator.manifest_path, {"citizens": citizens})
    calls = []
    def api(path, **kwargs):
        calls.append(path)
        if path == "/api/run/status":
            return {"run_id": "one", "tick": 2, "status": "paused"}
        return {"actor": {"id": 1}, "status": "active"}
    monkeypatch.setattr(operator, "api", api)
    def fail(*args):
        raise RuntimeError("Provider unavailable")
    monkeypatch.setattr(operator, "decide", fail)
    try:
        with pytest.raises(RuntimeError, match="Provider unavailable"):
            operator.run()
        assert "/api/run/step" not in calls
    finally:
        operator.client.close()


def test_partial_day_recovers_only_with_saved_decisions(monkeypatch, tmp_path):
    monkeypatch.setattr("scripts.hermes_citizens.ROOT", tmp_path)
    operator = CohortOperator(Namespace(run_id="one", url="http://127.0.0.1:8000",
        hermes_python="unused", profiles_root=str(tmp_path), days=1))
    state = {"run_id": "one", "tick": 2, "active_tick": 3, "status": "paused"}
    calls = []
    def api(path, **kwargs):
        calls.append(path)
        if path == "/api/run/step":
            state.update(tick=3, active_tick=None)
        return dict(state)
    monkeypatch.setattr(operator, "api", api)
    monkeypatch.setattr(operator, "receipts", lambda *args: [])
    citizens = [{"name": "Maya Chen"}]
    try:
        with pytest.raises(RuntimeError, match="incomplete cohort receipts"):
            operator.recover_day(citizens)
        assert "/api/run/step" not in calls
        monkeypatch.setattr(operator, "receipts", lambda *args: [{"status": "queued"}])
        operator.recover_day(citizens)
        assert state["tick"] == 3 and state["active_tick"] is None
        assert calls.count("/api/run/step") == 1
        assert (operator.root / "day-3.json").exists()
    finally:
        operator.client.close()

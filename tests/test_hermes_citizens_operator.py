from argparse import Namespace
import json
from pathlib import Path
import sqlite3

import pytest

from scripts.hermes_citizens import CohortOperator, COHORT, MissingQueuedAction, write_json


@pytest.mark.parametrize('missing_attempts', [0, 1, 3])
def test_decide_uses_profile_luna_without_deepseek_key(monkeypatch, tmp_path, missing_attempts):
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
        kwargs['stdout'].write('Session: saved-session\n')
        return Namespace(returncode=0)
    monkeypatch.setattr('scripts.hermes_citizens.subprocess.run', run)
    try:
        if missing_attempts == 3:
            with pytest.raises(MissingQueuedAction):
                operator.decide(citizen, 64)
        else:
            operator.decide(citizen, 64)
        assert len(attempts) == min(missing_attempts+1, 3)
        assert len(list((operator.root / 'maya').glob('tick-64-attempt-*.log'))) == len(attempts)
        assert json.loads((operator.root / 'maya/session.json').read_text())['session_id'] == 'saved-session'
    finally:
        operator.client.close()


@pytest.mark.parametrize('interruption', ['world_changed', 'stop', 'late_receipt', 'provider_error'])
def test_recovery_respects_world_stop_receipts_and_provider_failure(monkeypatch, tmp_path, interruption):
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
        raise MissingQueuedAction('No receipt')
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

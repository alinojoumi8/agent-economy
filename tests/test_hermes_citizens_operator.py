from argparse import Namespace

import pytest

from scripts.hermes_citizens import CohortOperator, COHORT, write_json


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

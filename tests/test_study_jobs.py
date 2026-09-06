import json
from pathlib import Path
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from research.artifacts import file_sha256, publish_json
from research.study_jobs import LaunchRequest, PilotInputError, PilotRequest, StudyJobs, execution_lock
from research.study_library import StudyLibrary
from research.study_results import StudyIdentityChanged
from server.v2_api import install_v2_routes

CONTEXT = {"run_id": "test", "fork_id": None, "tick": "live"}
SCOPE = {"run_id": "test", "tick": "live"}
HEADERS = {"X-CSRF-Token": "test-study-csrf"}
BASE = "/api/v2/operator/research"
REQUEST = {"preset": "G2", "seeds": [1, 2], "horizon": 3, "intervention_tick": 2}


@pytest.fixture
def jobs(tmp_path):
    return StudyJobs(tmp_path / "research-jobs", data_root=tmp_path / "d", out_dir=tmp_path / "r")


@pytest.fixture
def fake_supervisor(monkeypatch):
    started = []

    def spawn(command, **kwargs):
        started.append((command, kwargs))
        return SimpleNamespace(wait=lambda: 0)

    monkeypatch.setattr("research.study_jobs.subprocess.Popen", spawn)
    # code_identity itself uses subprocess.Popen internally; isolate only the
    # identity reader in these operational tests. The real launch test uses Git.
    monkeypatch.setattr("research.study_jobs.code_identity", lambda: {"git_commit": "abc", "source_tree_sha256": "1" * 64})
    return started


def launch_body(draft, key="a" * 32):
    return LaunchRequest(draft_sha256=draft["draft_sha256"], idempotency_key=key)


def test_validation_freezes_both_domains_and_creates_no_world(jobs):
    draft = jobs.validate(PilotRequest(**REQUEST), CONTEXT)
    assert draft["executed"] is False and draft["origin"] == "fresh_genesis"
    assert draft["spec"]["domains"] == ["goods", "equities"]
    assert draft["estimate"]["worlds"] == 4
    assert draft["estimate"]["source_and_replay_ticks"] == 24
    assert draft["spec"]["operations"]["max_provider_calls"] == 0
    assert draft["spec"]["operations"]["max_spend_usd"] == 0
    assert not jobs.data_root.exists() and not jobs.out_dir.exists()
    assert not (jobs.root / "jobs").exists()
    assert jobs.draft(draft["id"], CONTEXT) == draft
    assert '"resolved_config":' not in json.dumps(draft)


@pytest.mark.parametrize("change", [
    {"seeds": [1, 1]}, {"seeds": [1, 2, 3, 4, 5, 6]}, {"horizon": 31},
    {"horizon": 3, "intervention_tick": 4}, {"seeds": [True]},
    {"max_wall_seconds": 301}, {"max_disk_mib": 129},
    {"equity_firm_id": 2}, {"config": "external.yaml"}, {"preset": "run-python"},
])
def test_unbounded_or_executable_requests_are_rejected(change, jobs):
    with pytest.raises(ValueError):
        PilotRequest(**{**REQUEST, **change})
    assert not jobs.root.exists()


def test_storage_estimate_rejects_before_publishing_draft(jobs):
    with pytest.raises(PilotInputError, match="storage estimate"):
        jobs.validate(PilotRequest(**{**REQUEST, "seeds": [1, 2, 3, 4, 5], "horizon": 30}), CONTEXT)
    assert not jobs.root.exists()


def test_launch_is_durable_idempotent_and_conflicting_key_cannot_relaunch(jobs, fake_supervisor):
    draft = jobs.validate(PilotRequest(**REQUEST), CONTEXT)
    started = jobs.launch(draft["id"], launch_body(draft), CONTEXT)
    assert started["status"] == "starting"
    reloaded = StudyJobs(jobs.root, data_root=jobs.data_root, out_dir=jobs.out_dir)
    assert reloaded.launch(draft["id"], launch_body(draft), CONTEXT)["id"] == started["id"]
    with pytest.raises(StudyIdentityChanged, match="already has a launch"):
        jobs.launch(draft["id"], launch_body(draft, "b" * 32), CONTEXT)
    assert len(fake_supervisor) == 1
    command, options = fake_supervisor[0]
    assert command[1:4] == ["-m", "research.study_jobs", "execute"]
    assert "shell" not in options
    assert not jobs.data_root.exists()


def test_stale_source_and_draft_hash_never_start_a_job(jobs, fake_supervisor, monkeypatch):
    draft = jobs.validate(PilotRequest(**REQUEST), CONTEXT)
    with pytest.raises(StudyIdentityChanged, match="draft changed"):
        jobs.launch(draft["id"], LaunchRequest(draft_sha256="0" * 64, idempotency_key="a" * 32), CONTEXT)
    monkeypatch.setattr("research.study_jobs.code_identity", lambda: {"git_commit": "changed"})
    with pytest.raises(StudyIdentityChanged, match="Source changed"):
        jobs.launch(draft["id"], launch_body(draft), CONTEXT)
    assert not fake_supervisor and not (jobs.root / "jobs").exists()


def test_active_or_interrupted_job_blocks_another_launch_until_explicit_recovery(jobs, fake_supervisor):
    draft = jobs.validate(PilotRequest(**REQUEST), CONTEXT)
    state = jobs.launch(draft["id"], launch_body(draft), CONTEXT)
    second = jobs.validate(PilotRequest(**{**REQUEST, "preset": "F2"}), CONTEXT)
    with pytest.raises(StudyIdentityChanged, match="active or needs recovery"):
        jobs.launch(second["id"], launch_body(second), CONTEXT)
    job = jobs.path("jobs", state["id"])
    with execution_lock(job / "execution.lock"):
        assert jobs.status(state["id"], CONTEXT)["status"] == "running"
        with pytest.raises(StudyIdentityChanged, match="already active"):
            jobs.recover(state["id"], CONTEXT)
    publish_json(job / "started.json", {"started_at": 1})
    claim_hash = file_sha256(job / "claim.json")
    assert jobs.status(state["id"], CONTEXT)["recoverable"]
    assert jobs.recover(state["id"], CONTEXT)["status"] == "interrupted"
    assert file_sha256(job / "claim.json") == claim_hash
    assert not (jobs.root / "active.json").exists()
    assert jobs.launch(second["id"], launch_body(second), CONTEXT)["id"] != state["id"]


def test_start_failure_is_retained_and_cannot_automatically_retry(jobs, fake_supervisor, monkeypatch):
    draft = jobs.validate(PilotRequest(**REQUEST), CONTEXT)
    def fail(*args, **kwargs):
        raise OSError("PRIVATE-PATH-MARKER")
    monkeypatch.setattr("research.study_jobs.subprocess.Popen", fail)
    result = jobs.launch(draft["id"], launch_body(draft), CONTEXT)
    assert result["status"] == "failed" and result["reason"] == "supervisor_start_failed"
    assert "PRIVATE-PATH-MARKER" not in json.dumps(result)
    assert jobs.launch(draft["id"], launch_body(draft), CONTEXT) == result


def test_edited_draft_cannot_bypass_launch_limits_with_its_new_hash(jobs, fake_supervisor):
    draft = jobs.validate(PilotRequest(**REQUEST), CONTEXT)
    path = jobs.path("drafts", draft["id"]) / "draft.json"
    stored = json.loads(path.read_text())
    stored["protocol"]["study"]["operations"]["max_wall_seconds"] = 100000
    path.write_text(json.dumps(stored))
    changed = jobs.draft(draft["id"], CONTEXT)
    with pytest.raises(StudyIdentityChanged, match="bounded pilot request"):
        jobs.launch(draft["id"], launch_body(changed), CONTEXT)
    assert not fake_supervisor


@pytest.fixture
def launch_api(economy, tmp_path):
    app = FastAPI()
    config = {**economy.config, "operator_workspace": {"csrf_token": "test-study-csrf"},
        "operator_research": {"data_root": str(tmp_path / "d"), "out_dir": str(tmp_path / "r")}}
    controller = SimpleNamespace(hosted_safe=False)
    install_v2_routes(app, SimpleNamespace(store=economy.store, config=config, economy=economy), controller)
    try:
        with TestClient(app) as client:
            yield client, app.state.study_jobs, controller, economy
    finally:
        app.state.operator_workspace.close()


def test_operator_authority_context_and_budget_rejections_precede_world_execution(launch_api):
    client, jobs, controller, economy = launch_api
    before = economy.store.conn.total_changes
    path = BASE + "/drafts/validate"
    assert client.post(path, params=SCOPE, json=REQUEST).status_code == 403
    for change in ({"tick": "1"}, {"run_id": "other"}, {"fork_id": "other"}):
        assert client.post(path, params={**SCOPE, **change}, json=REQUEST, headers=HEADERS).status_code == 409
    assert client.post(path, params=SCOPE, json={**REQUEST, "max_wall_seconds": 100000}, headers=HEADERS).status_code == 422
    assert client.get(BASE + "/jobs/" + "a" * 32, params=SCOPE, headers=HEADERS).status_code == 404
    response = client.post(path, params=SCOPE, json=REQUEST, headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert str(jobs.root) not in response.text
    assert economy.store.conn.total_changes == before
    controller.hosted_safe = True
    assert client.get(BASE + "/capabilities", params=SCOPE, headers=HEADERS).status_code == 403
    assert not jobs.data_root.exists()


def test_real_supervisor_completes_replays_and_does_not_mutate_observed_world(launch_api):
    client, jobs, _, economy = launch_api
    before = economy.store.conn.total_changes
    draft = client.post(BASE + "/drafts/validate", params=SCOPE, json=REQUEST, headers=HEADERS).json()
    body = {"draft_sha256": draft["draft_sha256"], "idempotency_key": "c" * 32}
    response = client.post(f"{BASE}/drafts/{draft['id']}/launch", params=SCOPE, json=body, headers=HEADERS)
    assert response.status_code == 202, response.text
    assert response.headers["cache-control"] == "private, no-store"
    identity = response.json()["id"]
    repeated = client.post(f"{BASE}/drafts/{draft['id']}/launch", params=SCOPE, json=body, headers=HEADERS)
    assert repeated.json()["id"] == identity
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        response = client.get(f"{BASE}/jobs/{identity}", params=SCOPE, headers=HEADERS)
        assert response.status_code == 200, response.text
        state = response.json()
        if state["status"] not in {"starting", "running"}:
            break
        time.sleep(.1)
    assert state["status"] == "completed", state
    assert state["finished_cells"] == state["expected_cells"] == state["eligible_cells"] == 4
    assert str(jobs.root) not in response.text and "source_database" not in response.text
    library = StudyLibrary(data_root=jobs.data_root, out_dir=jobs.out_dir, export_root=jobs.root / "exports")
    proof = library.verify(state["study_id"], state["result_sha256"])
    assert proof["verification"]["status"] == "verified"
    assert proof["verification"]["operations"]["provider_calls"] == 0
    assert economy.store.conn.total_changes == before
    assert len(list((jobs.out_dir / "studies").glob("*/*/results.json"))) == 1
    assert not (jobs.root / "active.json").exists()


def test_runner_binds_validated_source_before_creating_a_batch(jobs):
    from research.study_runner import run_study
    from research.studies import StudySpec
    draft = jobs.validate(PilotRequest(**REQUEST), CONTEXT)
    stored = jobs._draft(draft["id"], CONTEXT)
    with pytest.raises(ValueError, match="source changed"):
        run_study(StudySpec.model_validate(stored["protocol"]["study"]), stored["protocol"]["resolved_config"],
            input_root=Path(__file__).resolve().parents[1], data_root=jobs.data_root,
            out_dir=jobs.out_dir, expected_code={"git_commit": "not-the-reviewed-source"})
    assert not jobs.data_root.exists()


def test_orphaned_worker_stops_before_the_operator_can_release_its_slot(jobs, monkeypatch):
    import subprocess
    actual_spawn, supervisors = subprocess.Popen, []

    def spawn(command, *args, **kwargs):
        process = actual_spawn(command, *args, **kwargs)
        if isinstance(command, list) and command[1:3] == ["-m", "research.study_jobs"]:
            supervisors.append(process)
        return process

    monkeypatch.setattr("research.study_jobs.subprocess.Popen", spawn)
    draft = jobs.validate(PilotRequest(**{**REQUEST, "seeds": [1, 2, 3], "horizon": 30}), CONTEXT)
    state = jobs.launch(draft["id"], launch_body(draft), CONTEXT)
    supervisor = supervisors[0]
    job = jobs.path("jobs", state["id"])
    claim_hash = file_sha256(job / "claim.json")
    try:
        deadline, worker_active = time.monotonic() + 30, False
        while time.monotonic() < deadline and supervisor.poll() is None:
            try:
                with execution_lock(job / "worker.lock"):
                    pass
            except StudyIdentityChanged:
                worker_active = True
                break
            time.sleep(.02)
        assert worker_active, "the owned supervisor did not start its world worker"
        supervisor.kill()  # Only the process launched by this test.
        supervisor.wait(timeout=10)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            state = jobs.status(state["id"], CONTEXT)
            if state["recoverable"]:
                break
            assert state["status"] == "interrupted_worker_active", state
            time.sleep(.02)
        assert state["recoverable"], state
        recovered = jobs.recover(state["id"], CONTEXT)
        assert recovered["status"] == "interrupted" and not recovered["recoverable"]
        assert file_sha256(job / "claim.json") == claim_hash
        assert not (jobs.root / "active.json").exists()
        assert not list(jobs.out_dir.glob("studies/*/*/publication.json"))
    finally:
        if supervisor.poll() is None:
            supervisor.kill()
            supervisor.wait(timeout=10)

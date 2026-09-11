"""Real operator pauses, private evidence and explicit same-world continuations."""
import json
from pathlib import Path
import time

import pytest

from research.artifacts import file_sha256
from research.study_bundle import import_study_bundle
from research.study_jobs import ResumeRequest
from tests.test_study_jobs import BASE, CONTEXT, HEADERS, REQUEST, SCOPE, launch_api  # noqa: F401
from tests.test_working_attempts import _bytes


def _settled(client, identity):
    deadline = time.monotonic() + 75
    while time.monotonic() < deadline:
        response = client.get(f"{BASE}/jobs/{identity}", params=SCOPE, headers=HEADERS)
        assert response.status_code == 200, response.text
        state = response.json()
        if state["status"] not in {"starting", "running", "interrupted_worker_active"}:
            return state
        time.sleep(.1)
    pytest.fail(f"study did not settle: {state}")


@pytest.mark.parametrize("preset", ["G2", "F2"])
@pytest.mark.parametrize("pause_kind", ["day", "phase"])
def test_real_pause_export_resume_keeps_world_identity_budget_and_parent_evidence(launch_api, tmp_path, monkeypatch, preset, pause_kind):
    client, jobs, _, economy = launch_api
    changes = economy.store.conn.total_changes
    controls = {"pause_after_ticks": 1} if pause_kind == "day" else {"pause_after_phase": "MARKET"}
    draft = client.post(BASE + "/drafts/validate", params=SCOPE, headers=HEADERS,
                        json={**REQUEST, "preset": preset, **controls}).json()
    assert draft["spec"]["operations"]["pause_policy"] == ("preserve_and_resume" if pause_kind == "day" else "preserve_and_resume_phases")
    launched = client.post(f"{BASE}/drafts/{draft['id']}/launch", params=SCOPE, headers=HEADERS,
        json={"draft_sha256": draft["draft_sha256"], "idempotency_key": "a" * 32})
    assert launched.status_code == 202, launched.text
    parent = _settled(client, launched.json()["id"])
    assert parent["status"] == "paused" and parent["resumable"], parent
    assert parent["finished_cells"] == parent["eligible_cells"] == 0
    assert [row["ticks"] for row in parent["cells"]] == [1 if pause_kind == "day" else 0, 0, 0, 0]
    assert all(row["eligibility"]["status"] == "pending" for row in parent["cells"])
    job = jobs.path("jobs", parent["id"])
    batch = json.loads((job / "batch.json").read_text())
    data = Path(batch["data_dir"])
    source_claim = next(data.glob("*/attempt.json"))
    source = json.loads(source_claim.read_text())
    immutable = [job / "claim.json", job / "terminal.json", source_claim,
                 *data.glob("*/segment-000001-*.json"), source_claim.parent / "genesis.json"]
    hashes = {path: file_sha256(path) for path in immutable}
    item = client.get(BASE + "/studies", params=SCOPE, headers=HEADERS).json()["items"][0]
    assert item["id"] == parent["study_id"] and item["kind"] == "working"
    selection = {**SCOPE, "result_sha256": item["result_sha256"]}
    view_response = client.get(f"{BASE}/studies/{item['id']}", params=selection, headers=HEADERS)
    assert view_response.status_code == 200, view_response.text
    view = view_response.json()
    assert view["operator_job"]["id"] == parent["id"]
    assert view["state"] == "paused" and not view["comparison_available"]
    assert view["verification"]["eligibility"] == "pending"
    if pause_kind == "phase":
        position = {"completed_tick": 0, "active_tick": 1, "next_phase": "NEWSROOM"}
        assert view["attempts"][0]["position"] == parent["cells"][0]["position"] == position
    assert not ({"summary", "metrics", "outcomes", "measurements"} & view.keys())
    for secret in (str(data), "source_database", "resolved_config", "phase_state_sha256", "recorded_inputs"):
        assert secret not in view_response.text
    export_body = {"result_sha256": item["result_sha256"], "verification_sha256": view["verification_sha256"]}
    receipt = client.post(f"{BASE}/studies/{item['id']}/export", params=SCOPE, headers=HEADERS, json=export_body)
    assert receipt.status_code == 200, receipt.text
    archive = jobs.root.parent / "research-exports" / f"{receipt.json()['token']}.zip"
    imported = import_study_bundle(archive, tmp_path / "portable")
    assert imported["study_verification"]["eligibility"] == "pending"
    snapshot = _bytes(data)
    body = {"progress_sha256": parent["progress_sha256"], "resume_check_sha256": parent["resume_check_sha256"],
            "idempotency_key": "b" * 32}
    route = f"{BASE}/jobs/{parent['id']}/resume"
    with monkeypatch.context() as changed:
        changed.setattr("research.working_attempts.code_identity", lambda: {"git_commit": "new-source"})
        incompatible = client.get(f"{BASE}/jobs/{parent['id']}", params=SCOPE, headers=HEADERS).json()
        assert not incompatible["resumable"]
        assert "resume_unavailable_reason" in incompatible
        readable = client.get(f"{BASE}/studies/{item['id']}", params=selection, headers=HEADERS).json()
        assert readable["verification"]["status"] == "verified"
        assert not readable["operator_job"]["resumable"]
        refused = client.post(route, params=SCOPE, headers=HEADERS, json=body)
        assert refused.status_code == 409, refused.text
        assert str(data) not in refused.text
    assert client.post(route, params=SCOPE, json=body).status_code == 403
    for scope in ({**SCOPE, "run_id": "other"}, {**SCOPE, "fork_id": "other"}, {**SCOPE, "tick": "1"}):
        assert client.post(route, params=scope, headers=HEADERS, json=body).status_code == 409
    assert client.post(route, params=SCOPE, headers=HEADERS,
                       json={**body, "progress_sha256": "0" * 64}).status_code == 409
    assert client.post(route, params=SCOPE, headers=HEADERS,
                       json={**body, "max_wall_seconds": 300}).status_code == 422
    assert _bytes(data) == snapshot
    resumed = client.post(route, params=SCOPE, headers=HEADERS, json=body)
    assert resumed.status_code == 202, resumed.text
    assert resumed.headers["cache-control"] == "private, no-store"
    child = resumed.json()
    assert child["id"] != parent["id"] and child["parent_job_id"] == parent["id"]
    assert client.post(route, params=SCOPE, headers=HEADERS, json=body).json()["id"] == child["id"]
    assert client.post(route, params=SCOPE, headers=HEADERS,
                       json={**body, "idempotency_key": "c" * 32}).status_code == 409
    completed = _settled(client, child["id"])
    assert completed["status"] == "completed", completed
    assert completed["finished_cells"] == completed["eligible_cells"] == completed["expected_cells"] == 4
    assert completed["study_id"] == parent["study_id"]
    assert {path: file_sha256(path) for path in immutable} == hashes
    result = json.loads((Path(batch["report_dir"]) / "results.json").read_text())
    assert result["batch"] == batch
    assert result["results"][0]["run_id"] == source["run_id"]
    assert result["operations"]["elapsed_seconds"] >= parent["active_wall_seconds"]
    assert result["batch"]["manifest"]["study"]["operations"]["max_wall_seconds"] == 180
    current = client.get(BASE + "/studies", params=SCOPE, headers=HEADERS).json()["items"][0]
    assert current["id"] == item["id"] and current["kind"] == "finalized"
    proof = client.get(f"{BASE}/studies/{item['id']}", params={**SCOPE, "result_sha256": current["result_sha256"]}, headers=HEADERS)
    assert proof.json()["verification"]["status"] == "verified", proof.text
    assert client.get(f"{BASE}/jobs/{parent['id']}", params=SCOPE, headers=HEADERS).json()["continuation_job_id"] == child["id"]
    assert economy.store.conn.total_changes == changes


def test_absent_resume_does_not_create_a_job_or_lock_directory(launch_api):
    client, jobs, _, _ = launch_api
    body = ResumeRequest(progress_sha256="1" * 64, resume_check_sha256="2" * 64, idempotency_key="3" * 32)
    before = _bytes(jobs.root) if jobs.root.exists() else {}
    response = client.post(f"{BASE}/jobs/{'f' * 32}/resume", params=SCOPE, headers=HEADERS, json=body.model_dump())
    assert response.status_code == 404, response.text
    assert (_bytes(jobs.root) if jobs.root.exists() else {}) == before

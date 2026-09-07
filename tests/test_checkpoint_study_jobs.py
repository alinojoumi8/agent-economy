"""Actual operator saved-world selection, recovery, replay and private export."""
import asyncio
import json
from pathlib import Path

import pytest

from research.artifacts import file_sha256
from research.operator_checkpoints import OperatorCheckpoints
from research.study_bundle import import_study_bundle
from research.study_jobs import PilotRequest, ROOT
from run import open_run
from run_config import load_config
from tests.test_study_jobs import BASE, HEADERS, SCOPE, launch_api  # noqa: F401
from tests.test_working_study_jobs import _settled


@pytest.fixture
def saved_api(launch_api, tmp_path):
    client, jobs, controller, economy = launch_api
    jobs.checkpoints = OperatorCheckpoints(tmp_path / "c")
    sources = []
    for seed in (1, 2):
        config = load_config(ROOT / "runs/price-lab-pilot.yaml")
        config.update(seed=seed, checkpoint_every=0, checkpoint_dir=str(tmp_path / "ck"),
                      report_dir=str(tmp_path / "rp"), speed_delay_s=0.0)
        store, world, _ = open_run(config, None, None, data_dir=jobs.checkpoints.root)
        try:
            asyncio.run(world.run(max_ticks=2))
            sources.append(Path(store.path))
        finally:
            world.close()
    return client, jobs, controller, economy, {path: file_sha256(path) for path in sources}


def selections(client):
    response = client.get(BASE + "/checkpoints", params=SCOPE, headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    items = sorted(response.json()["items"], key=lambda row: row["seed"])
    assert [row["seed"] for row in items] == [1, 2]
    return [{key: row[key] for key in ("id", "database_sha256", "receipt_sha256")} for row in items]


def request_for(client, **changes):
    return {"preset": "G2", "origin": "verified_checkpoints", "checkpoints": selections(client),
            "horizon": 5, "intervention_tick": 4, "warmup_ticks": 1, **changes}


def test_catalog_authorization_precedes_source_reads(launch_api, monkeypatch):
    client, jobs, controller, _ = launch_api
    def forbidden():
        pytest.fail("unauthorized request inspected saved worlds")
    monkeypatch.setattr(jobs, "checkpoint_catalog", forbidden)
    assert client.get(BASE + "/checkpoints", params=SCOPE).status_code == 403
    for scope in ({**SCOPE, "tick": "2"}, {**SCOPE, "run_id": "foreign"}, {**SCOPE, "fork_id": "foreign"}):
        assert client.get(BASE + "/checkpoints", params=scope, headers=HEADERS).status_code == 409
    controller.hosted_safe = True
    assert client.get(BASE + "/checkpoints", params=SCOPE, headers=HEADERS).status_code == 403
    assert not jobs.root.exists()


def test_catalog_is_flat_bounded_and_does_not_hash_oversized_sources(saved_api, monkeypatch):
    client, jobs, _, _, sources = saved_api
    root = jobs.checkpoints.root
    with (root / "huge.db").open("xb") as stream:
        stream.truncate(OperatorCheckpoints.MAX_SOURCE_BYTES + 1)
    (root / "broken.db").write_bytes(b"invalid sqlite")
    (root / "nested").mkdir()
    (root / "nested" / "ignored.db").write_bytes(b"not discovered")
    original = jobs.checkpoints._inspect
    def inspected(path, config):
        assert path.name != "huge.db"
        return original(path, config)
    monkeypatch.setattr(jobs.checkpoints, "_inspect", inspected)
    response = client.get(BASE + "/checkpoints", params=SCOPE, headers=HEADERS)
    catalog = response.json()
    assert len(catalog["items"]) == 2
    assert catalog["omitted"] == {"oversized": 1, "unavailable_or_incompatible": 1}
    for private in (str(root), "huge.db", "recorded_inputs", "config_json", "source_database"):
        assert private not in response.text
    assert {path: file_sha256(path) for path in sources} == sources
    assert not list(root.glob("*-wal")) and not list(root.glob("*-shm"))
    monkeypatch.setattr(jobs.checkpoints, "MAX_SCAN", 1)
    assert jobs.checkpoint_catalog()["truncated"]


@pytest.mark.parametrize("change", [
    {"seeds": [9]}, {"checkpoints": []}, {"warmup_ticks": -1},
    {"checkpoint_root": "C:/private"}, {"origin": "active_world"},
])
def test_checkpoint_request_cannot_replace_seeds_or_accept_paths(change):
    request = {"preset": "G2", "origin": "verified_checkpoints", "horizon": 5, "intervention_tick": 4,
        "checkpoints": [{"id": "a" * 32, "database_sha256": "b" * 64, "receipt_sha256": "c" * 64}]}
    with pytest.raises(ValueError):
        PilotRequest(**{**request, **change})


def test_changed_selection_and_sources_refuse_before_any_world_claim(saved_api):
    client, jobs, _, _, sources = saved_api
    request = request_for(client)
    changed = json.loads(json.dumps(request))
    changed["checkpoints"][0]["database_sha256"] = "0" * 64
    assert client.post(BASE + "/drafts/validate", params=SCOPE, headers=HEADERS, json=changed).status_code == 409
    assert not jobs.root.exists()
    rejected = client.post(BASE + "/drafts/validate", params=SCOPE, headers=HEADERS,
        json={**request, "max_disk_mib": 32})
    assert rejected.status_code == 422, rejected.text
    assert not (jobs.root / "drafts").exists()
    draft = client.post(BASE + "/drafts/validate", params=SCOPE, headers=HEADERS, json=request).json()
    assert draft["executed"] is False and draft["origin"] == "verified_checkpoints"
    assert draft["spec"]["randomness"]["seeds"] == [1, 2]
    assert draft["origin_details"]["continuation_window"] == [3, 5]
    assert draft["estimate"]["source_and_replay_ticks"] == 24
    assert draft["estimate"]["origin_copy_bytes"] == sum(path.stat().st_size for path in sources) * 5
    source = next(iter(sources))
    with source.open("ab") as stream:
        stream.write(b"changed-after-review")
    response = client.post(f"{BASE}/drafts/{draft['id']}/launch", params=SCOPE, headers=HEADERS,
        json={"draft_sha256": draft["draft_sha256"], "idempotency_key": "a" * 32})
    assert response.status_code == 409, response.text
    assert not (jobs.root / "jobs").exists() and not jobs.data_root.exists() and not jobs.out_dir.exists()


@pytest.mark.parametrize("preset", ["G2", "F2"])
@pytest.mark.parametrize("pause", ["day", "phase"])
def test_saved_world_operator_review_resume_compare_export(saved_api, tmp_path, preset, pause):
    client, jobs, _, economy, sources = saved_api
    before = economy.store.conn.total_changes
    controls = {"pause_after_ticks": 1} if pause == "day" else {"pause_after_phase": "MARKET"}
    request = request_for(client, preset=preset, **controls)
    response = client.post(BASE + "/drafts/validate", params=SCOPE, headers=HEADERS, json=request)
    assert response.status_code == 200, response.text
    draft = response.json()
    origin = draft["origin_details"]
    assert origin["kind"] == "verified_checkpoints" and origin["independent_worlds"] == 2
    assert origin["tick"] == 2 and origin["continuation_window"] == [3, 5]
    assert not jobs.data_root.exists()
    body = {"draft_sha256": draft["draft_sha256"], "idempotency_key": "a" * 32}
    route = f"{BASE}/drafts/{draft['id']}/launch"
    response = client.post(route, params=SCOPE, headers=HEADERS, json=body)
    assert response.status_code == 202, response.text
    identity = response.json()["id"]
    assert client.post(route, params=SCOPE, headers=HEADERS, json=body).json()["id"] == identity
    parent = _settled(client, identity)
    assert parent["status"] == "paused" and parent["resumable"], parent
    assert parent["origin_details"] == origin
    assert parent["cells"][0]["ticks"] == (3 if pause == "day" else 2)
    if pause == "phase":
        assert parent["cells"][0]["position"] == {"completed_tick": 2, "active_tick": 3, "next_phase": "NEWSROOM"}
    query = {**SCOPE, "result_sha256": parent["result_sha256"]}
    view = client.get(f"{BASE}/studies/{parent['study_id']}", params=query, headers=HEADERS).json()
    assert view["origin_details"] == origin and view["state"] == "paused"
    assert view["operator_job"]["id"] == identity
    assert not view["comparison_available"]
    resume = {"progress_sha256": parent["progress_sha256"], "resume_check_sha256": parent["resume_check_sha256"],
              "idempotency_key": "b" * 32}
    resumed = client.post(f"{BASE}/jobs/{identity}/resume", params=SCOPE, headers=HEADERS, json=resume)
    assert resumed.status_code == 202, resumed.text
    completed = _settled(client, resumed.json()["id"])
    assert completed["status"] == "completed" and completed["eligible_cells"] == 4, completed
    assert completed["origin_details"] == origin
    response = client.get(f"{BASE}/studies/{completed['study_id']}",
        params={**SCOPE, "result_sha256": completed["result_sha256"]}, headers=HEADERS)
    assert response.status_code == 200, response.text
    comparison = response.json()
    assert comparison["origin_details"] == origin
    assert comparison["verification"]["status"] == "verified"
    assert {row["domain"] for row in comparison["outcomes"]} == {"goods", "equities"}
    assert comparison["verification"]["operations"]["provider_calls"] == 0
    for private in (str(jobs.checkpoints.root), "recorded_inputs", "source_database", "resolved_config"):
        assert private not in response.text
    receipt = client.post(f"{BASE}/studies/{completed['study_id']}/export", params=SCOPE, headers=HEADERS,
        json={"result_sha256": completed["result_sha256"], "verification_sha256": comparison["verification_sha256"]})
    assert receipt.status_code == 200, receipt.text
    archive = jobs.root.parent / "research-exports" / f"{receipt.json()['token']}.zip"
    imported = import_study_bundle(archive, tmp_path / "portable")
    assert imported["study_verification"]["status"] == "verified"
    assert {path: file_sha256(path) for path in sources} == sources
    assert not list(jobs.checkpoints.root.glob("*-wal")) and not list(jobs.checkpoints.root.glob("*-shm"))
    assert economy.store.conn.total_changes == before

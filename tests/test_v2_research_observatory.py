from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from research.counterfactual import paired_summary
from research.datasets import DatasetError, verify_manifest
from research.scenarios import load_scenario
from run import open_run
from run_config import load_config
from server.app import create_app
from server.static_export import export_static_replay


@pytest.fixture()
def v2_world(tmp_path: Path):
    store, world, _ = open_run(load_config("runs/v2.yaml"), None, None, data_dir=tmp_path)
    try:
        yield store, world
    finally:
        store.close()


def test_v2_observatory_projections_god_action_and_static_export(v2_world, tmp_path: Path):
    store, world = v2_world
    with TestClient(create_app(world)) as client:
        for path in ("map", "network", "legal", "politics", "information",
                     "startups", "markets", "datasets"):
            response = client.get(f"/api/v2/{path}")
            assert response.status_code == 200, response.text
        actor_id = int(store.scalar("SELECT id FROM agents WHERE alive=1 ORDER BY id LIMIT 1"))
        response = client.post("/api/v2/god/action", json={
            "actor_id": actor_id, "expected_tick": 0,
            "action": {"type": "do_nothing"}, "rationale_summary": "test action",
        })
        assert response.status_code == 200
        assert response.json()["result"] == {"ok": True}

    target = export_static_replay(store, tmp_path / "replay.html")
    document = target.read_text(encoding="utf-8")
    assert "replay-data" in document
    assert "fred-fedfunds-2020" in document
    assert "private chain-of-thought" in document


def test_dataset_manifest_fails_closed_on_checksum_and_missing_vintage(tmp_path: Path):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"vintage_date": "2020-01-01", "targets": []}), encoding="utf-8")
    base = {
        "manifest_version": 1,
        "datasets": [{
            "key": "test", "source_url": "https://example.invalid/data",
            "release_date": "2020-01-01", "vintage_date": "2020-01-01",
            "retrieval_time": "2020-01-02T00:00:00Z", "checksum_sha256": "0" * 64,
            "transform_version": "test-v1", "usage_terms": "test",
            "snapshot_path": "snapshot.json", "required": True,
        }],
    }
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(yaml.safe_dump(base), encoding="utf-8")
    with pytest.raises(DatasetError, match="checksum mismatch"):
        verify_manifest(manifest)
    base["datasets"][0]["checksum_sha256"] = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    base["datasets"][0]["vintage_date"] = ""
    manifest.write_text(yaml.safe_dump(base), encoding="utf-8")
    with pytest.raises(DatasetError, match="mandatory"):
        verify_manifest(manifest)


def test_scenario_packs_and_paired_bootstrap_are_reproducible():
    pandemic = load_scenario("scenarios/2020-pandemic.yaml")
    competition = load_scenario("scenarios/ai-competition-merger.yaml")
    assert set(pandemic.arms) == {"no_additional_relief", "targeted_relief", "broad_relief"}
    assert set(competition.arms) == {"control", "light", "strict"}
    results = [
        {"arm": "control", "seed": 1, "metrics": {"hhi": 1800}},
        {"arm": "strict", "seed": 1, "metrics": {"hhi": 1600}},
        {"arm": "control", "seed": 2, "metrics": {"hhi": 1700}},
        {"arm": "strict", "seed": 2, "metrics": {"hhi": 1550}},
    ]
    first = paired_summary(results, "control", bootstrap_samples=200)
    second = paired_summary(results, "control", bootstrap_samples=200)
    assert first == second
    effect = first["metrics"]["hhi"]["strict"]["paired_effect"]
    assert effect["mean_difference"] == -175
    assert effect["ci95_bootstrap"] == [-200.0, -150.0]

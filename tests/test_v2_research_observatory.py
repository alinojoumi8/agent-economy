from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from research.counterfactual import paired_summary
from research.datasets import DatasetError, refresh_datasets, verify_manifest
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


def test_fred_refresh_transforms_csv_deterministically(tmp_path: Path, monkeypatch):
    snapshot = tmp_path / "fred.json"
    manifest = tmp_path / "manifest.yaml"
    manifest_payload = {
        "manifest_version": 1,
        "datasets": [{
            "key": "fred-fedfunds-2020",
            "source_url": "https://fred.example/series/FEDFUNDS",
            "refresh_url": "https://fred.example/fredgraph.csv?id=FEDFUNDS",
            "release_date": "2021-01-08",
            "vintage_date": "2021-01-08",
            "retrieval_time": "pending",
            "checksum_sha256": "0" * 64,
            "transform_version": "fred-monthly-targets-v1",
            "refresh_vintage_policy": "retrieval_date",
            "usage_terms": "test terms",
            "snapshot_path": snapshot.name,
            "required": True,
            "metadata": {
                "series_id": "FEDFUNDS",
                "target_key_prefix": "policy_rate",
                "target_months": ["2020-01", "2020-04", "2020-12"],
            },
        }],
    }
    manifest.write_text(yaml.safe_dump(manifest_payload), encoding="utf-8")
    csv_body = (
        b"observation_date,FEDFUNDS\r\n"
        b"2020-12-01,0.09\r\n"
        b"2020-02-01,1.58\r\n"
        b"2020-01-01,1.55\r\n"
        b"2020-04-01,0.05\r\n"
    )

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return csv_body

    calls = []
    fixed_now = datetime(2026, 7, 14, 12, 34, 56, tzinfo=timezone.utc)

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, timeout))
        return Response()

    monkeypatch.setattr("research.datasets.urlopen", fake_urlopen)
    monkeypatch.setattr("research.datasets._utc_now", lambda: fixed_now)
    first = refresh_datasets(manifest)
    first_bytes = snapshot.read_bytes()
    second = refresh_datasets(manifest)

    assert snapshot.read_bytes() == first_bytes
    assert calls == [(manifest_payload["datasets"][0]["refresh_url"], 60)] * 2
    assert first["verification"]["ok"] and second["verification"]["ok"]
    assert json.loads(first_bytes) == {
        "dataset_key": "fred-fedfunds-2020",
        "series_id": "FEDFUNDS",
        "targets": [
            {"dimensions": {"frequency": "monthly"},
             "key": "policy_rate.2020-01", "unit": "percent", "value": 1.55},
            {"dimensions": {"frequency": "monthly"},
             "key": "policy_rate.2020-04", "unit": "percent", "value": 0.05},
            {"dimensions": {"frequency": "monthly"},
             "key": "policy_rate.2020-12", "unit": "percent", "value": 0.09},
        ],
        "vintage_date": "2026-07-14",
    }
    refreshed_manifest = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    refreshed_item = refreshed_manifest["datasets"][0]
    assert refreshed_item["vintage_date"] == "2026-07-14"
    assert refreshed_item["retrieval_time"] == fixed_now.isoformat()


def test_dataset_refresh_rejects_unknown_vintage_policy_before_network_or_write(
        tmp_path: Path, monkeypatch):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text("unchanged", encoding="utf-8")
    manifest = tmp_path / "manifest.yaml"
    payload = {
        "manifest_version": 1,
        "datasets": [{
            "key": "bad-vintage-policy",
            "source_url": "https://example.invalid/data",
            "release_date": "2021-01-08",
            "vintage_date": "2021-01-08",
            "retrieval_time": "pending",
            "checksum_sha256": "0" * 64,
            "transform_version": "fred-monthly-targets-v1",
            "refresh_vintage_policy": "invent-a-vintage",
            "usage_terms": "test terms",
            "snapshot_path": snapshot.name,
            "metadata": {
                "series_id": "FEDFUNDS",
                "target_key_prefix": "policy_rate",
                "target_months": ["2020-01"],
            },
        }],
    }
    manifest.write_text(yaml.safe_dump(payload), encoding="utf-8")
    original_manifest = manifest.read_bytes()

    def network_forbidden(*args, **kwargs):
        raise AssertionError("invalid vintage policy attempted a network request")

    monkeypatch.setattr("research.datasets.urlopen", network_forbidden)
    with pytest.raises(DatasetError, match="unsupported refresh_vintage_policy"):
        refresh_datasets(manifest)

    assert snapshot.read_text(encoding="utf-8") == "unchanged"
    assert manifest.read_bytes() == original_manifest


def test_dataset_refresh_rejects_unknown_transform_before_network_or_write(
        tmp_path: Path, monkeypatch):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text("unchanged", encoding="utf-8")
    manifest = tmp_path / "manifest.yaml"
    payload = {
        "manifest_version": 1,
        "datasets": [{
            "key": "unknown",
            "source_url": "https://example.invalid/data",
            "release_date": "2021-01-08",
            "vintage_date": "2021-01-08",
            "retrieval_time": "pending",
            "checksum_sha256": "0" * 64,
            "transform_version": "unknown-v1",
            "usage_terms": "test terms",
            "snapshot_path": snapshot.name,
        }],
    }
    manifest.write_text(yaml.safe_dump(payload), encoding="utf-8")
    original_manifest = manifest.read_bytes()

    def network_forbidden(*args, **kwargs):
        raise AssertionError("unknown transform attempted a network request")

    monkeypatch.setattr("research.datasets.urlopen", network_forbidden)
    with pytest.raises(DatasetError, match="unsupported refresh transform_version unknown-v1"):
        refresh_datasets(manifest)

    assert snapshot.read_text(encoding="utf-8") == "unchanged"
    assert manifest.read_bytes() == original_manifest


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

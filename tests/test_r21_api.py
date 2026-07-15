from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from run import open_run
from run_config import load_config
from server.app import create_app


@pytest.fixture(scope="module")
def r21_client(tmp_path_factory: pytest.TempPathFactory):
    data_dir = tmp_path_factory.mktemp("r21-api-runs")
    store, world, _ = open_run(
        load_config("runs/r21-real-us.yaml"), None, None, data_dir=data_dir)
    try:
        with TestClient(create_app(world)) as client:
            yield store, client
    finally:
        world.close()


def test_dataset_projection_is_compact_and_omits_raw_supports(r21_client):
    _store, client = r21_client
    response = client.get("/api/v2/datasets")

    assert response.status_code == 200
    assert len(response.content) < 100_000
    payload = response.json()
    assert payload["targets"]
    assert all("value_json" not in target for target in payload["targets"])
    assert all(isinstance(target["dimensions"], dict)
               for target in payload["targets"])
    assert all(set(target["value_summary"]) <= {
        "type", "value", "record_count", "class_count", "total_firms"}
        for target in payload["targets"])

    by_key = {target["dataset_key"]: target for target in payload["targets"]}
    assert by_key["federal-reserve-scf"]["value_summary"]["record_count"] == 4_595
    assert by_key["census-susb"]["value_summary"]["class_count"] == 23


def test_agent_detail_exposes_authoritative_r21_calibration_profile(r21_client):
    store, client = r21_client
    event = store.query_one(
        "SELECT id,tick,subject_id,payload_json FROM events "
        "WHERE kind='r21_household_sampled' ORDER BY id LIMIT 1")
    assert event is not None
    source_payload = json.loads(event["payload_json"])

    response = client.get(f"/api/agents/{int(event['subject_id'])}")

    assert response.status_code == 200
    profile = response.json()["calibration_profile"]
    assert profile["event_id"] == int(event["id"])
    assert profile["tick"] == int(event["tick"])
    assert profile["net_worth_cents"] == source_payload["net_worth_cents"]
    assert profile["liquid_wealth_cents"] == source_payload["liquid_wealth_cents"]
    assert profile["non_liquid_net_worth_cents"] == (
        source_payload["net_worth_cents"] - source_payload["liquid_wealth_cents"])

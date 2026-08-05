from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

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


def test_local_observatory_mode_probe_is_an_explicit_success(r21_client):
    _store, client = r21_client
    response = client.get("/api/v2/mode")

    assert response.status_code == 200
    assert response.json() == {
        "hosted": False, "mode": "local", "api_base": "/api"}


def test_hosted_safe_observatory_mode_probe_reports_hosted():
    world = SimpleNamespace(
        store=SimpleNamespace(tick=0),
        runtime=SimpleNamespace(participant=None),
        config={},
    )
    app = create_app(world, hosted_safe=True)
    route = next(
        route for route in app.routes
        if getattr(route, "path", None) == "/api/v2/mode")

    assert asyncio.run(route.endpoint()) == {
        "hosted": True, "mode": "hosted", "api_base": "/api"}


def test_agent_directory_is_cursor_paginated_searchable_and_compatible(r21_client):
    store, client = r21_client
    population = int(store.scalar("SELECT COUNT(*) FROM agents", default=0))

    legacy = client.get("/api/agents")
    assert legacy.status_code == 200
    assert isinstance(legacy.json(), list)
    assert len(legacy.json()) == population

    first = client.get("/api/agents", params={"limit": 5})
    assert first.status_code == 200
    first_page = first.json()
    assert len(first_page["items"]) == min(5, population)
    assert first_page["population_total"] == population
    assert first_page["total"] == population
    assert [item["id"] for item in first_page["items"]] == sorted(
        item["id"] for item in first_page["items"])
    assert all("population_tier" in item and "region_key" in item
               for item in first_page["items"])

    if first_page["next_after_id"] is not None:
        second = client.get("/api/agents", params={
            "limit": 5, "after_id": first_page["next_after_id"],
        }).json()
        assert not ({item["id"] for item in first_page["items"]}
                    & {item["id"] for item in second["items"]})

    core_total = int(store.scalar(
        "SELECT COUNT(*) FROM agents WHERE population_tier='core'", default=0))
    core = client.get("/api/agents", params={
        "limit": 5, "population_tier": "core",
    }).json()
    assert core["total"] == core_total
    assert all(item["population_tier"] == "core" for item in core["items"])

    named = store.query_one("SELECT name FROM agents ORDER BY id LIMIT 1")
    searched = client.get("/api/agents", params={
        "limit": 5, "q": named["name"],
    }).json()
    assert searched["total"] >= 1
    assert any(item["name"] == named["name"] for item in searched["items"])
    assert client.get("/api/agents", params={"limit": 201}).status_code == 422


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


def test_agent_output_audit_includes_all_model_purposes_and_actions(r21_client):
    store, client = r21_client
    agent_id = int(store.scalar("SELECT id FROM agents ORDER BY id LIMIT 1"))
    before_calls = int(store.scalar(
        "SELECT COUNT(*) FROM llm_calls WHERE agent_id=?", (agent_id,), default=0))
    before_actions = int(store.scalar(
        "SELECT COUNT(*) FROM action_proposals WHERE actor_id=?",
        (agent_id,), default=0))
    call_ids = []
    action_ids = []
    try:
        for tick, purpose in enumerate(
                ("lawyer", "legislator_house", "competition_regulator"), 1):
            call_ids.append(store.insert(
                "llm_calls", tick=tick, agent_id=agent_id, role=purpose,
                provider="test", model="audit-model", purpose=purpose,
                request_json=json.dumps({"purpose": purpose}),
                response_json=json.dumps({"decision": purpose}),
                in_tokens=1, out_tokens=1, cached=0, cost_usd=0.01,
                latency_ms=1, created_at="2026-01-01T00:00:00+00:00"))
        for tick, status in enumerate(("accepted", "rejected", "accepted"), 1):
            action_ids.append(store.insert(
                "action_proposals", tick=tick, actor_id=agent_id,
                action_type=f"audit_action_{tick}", payload_json="{}",
                evidence_event_ids_json="[]", model_call_id=None,
                rationale_summary="deterministic audit action",
                validation_status=status, result_json=json.dumps({"status": status})))

        detail_response = client.get(f"/api/agents/{agent_id}")
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["output_counts"]["model_calls"] == before_calls + 3
        assert detail["output_counts"]["actions"] == before_actions + 3
        assert detail["output_counts"]["deterministic_actions"] >= 3
        assert [item["purpose"] for item in detail["recent_decisions"][:3]] == [
            "competition_regulator", "legislator_house", "lawyer"]
        assert [item["action_type"] for item in detail["recent_actions"][:3]] == [
            "audit_action_3", "audit_action_2", "audit_action_1"]

        first = client.get(
            f"/api/agents/{agent_id}/outputs", params={"kind": "model", "limit": 2})
        assert first.status_code == 200
        first_page = first.json()
        assert [item["id"] for item in first_page["items"]] == call_ids[::-1][:2]
        assert first_page["next_before_id"] == call_ids[-2]

        second = client.get(
            f"/api/agents/{agent_id}/outputs",
            params={
                "kind": "model", "limit": 2,
                "before_id": first_page["next_before_id"],
            },
        )
        assert second.status_code == 200
        assert second.json()["items"][0]["id"] == call_ids[0]
    finally:
        if action_ids:
            store.execute(
                f"DELETE FROM action_proposals WHERE id IN ({','.join('?' * len(action_ids))})",
                action_ids,
            )
        if call_ids:
            store.execute(
                f"DELETE FROM llm_calls WHERE id IN ({','.join('?' * len(call_ids))})",
                call_ids,
            )

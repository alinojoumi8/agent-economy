from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from run import open_run
from run_config import load_config
from server.app import create_app


@pytest.fixture(scope="module")
def region_client(tmp_path_factory: pytest.TempPathFactory):
    data_dir = tmp_path_factory.mktemp("observatory-region-runs")
    store, world, _ = open_run(
        load_config("runs/v2.yaml"), None, None, data_dir=data_dir)
    try:
        with TestClient(create_app(world)) as client:
            yield store, client
    finally:
        world.close()


def test_agent_region_filter_combines_with_search_tier_counts_and_cursor(region_client):
    store, client = region_client
    region = store.query_one(
        "SELECT region_id, COUNT(*) AS n FROM agents WHERE region_id IS NOT NULL "
        "GROUP BY region_id ORDER BY n DESC LIMIT 1")
    region_id = int(region["region_id"])
    expected = int(store.scalar(
        "SELECT COUNT(*) FROM agents WHERE region_id=?", (region_id,), default=0))

    legacy = client.get("/api/agents")
    assert legacy.status_code == 200
    legacy_items = legacy.json()
    assert isinstance(legacy_items, list)
    legacy_ids = [item["id"] for item in legacy_items]
    assert legacy_ids == sorted(legacy_ids)

    first = client.get("/api/agents", params={"limit": 2, "region_id": region_id})
    assert first.status_code == 200
    page = first.json()
    assert page["total"] == expected
    assert page["population_total"] == len(legacy_items)
    assert page["limit"] == 2
    assert all(item["region_id"] == region_id for item in page["items"])
    assert all(item["region_key"] for item in page["items"])
    expected_cursor = (
        page["items"][-1]["id"] if expected > len(page["items"]) else None)
    assert page["next_after_id"] == expected_cursor

    if page["next_after_id"] is not None:
        second = client.get("/api/agents", params={
            "limit": 2, "region_id": region_id,
            "after_id": page["next_after_id"],
        }).json()
        assert not ({item["id"] for item in page["items"]}
                    & {item["id"] for item in second["items"]})

    agent = store.query_one(
        "SELECT name, population_tier FROM agents WHERE region_id=? ORDER BY id LIMIT 1",
        (region_id,))
    combined = client.get("/api/agents", params={
        "limit": 5, "region_id": region_id, "q": agent["name"],
        "population_tier": agent["population_tier"],
    }).json()
    assert combined["total"] >= 1
    assert all(item["region_id"] == region_id for item in combined["items"])
    assert all(item["population_tier"] == agent["population_tier"]
               for item in combined["items"])
    assert any(item["name"] == agent["name"] for item in combined["items"])
    assert client.get("/api/agents", params={"region_id": 0}).status_code == 422

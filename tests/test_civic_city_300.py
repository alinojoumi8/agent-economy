"""Deterministic 300-resident profile and observer projection contracts."""
from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from run import open_run
from run_config import load_config
from server.v2_api import install_v2_routes


def test_civic_city_300_profile_and_population_views(tmp_path) -> None:
    config = load_config("runs/civic-city-300.yaml")
    assert config["population"]["target_total"] == 297
    assert config["living_world"]["core_agents"] == 100
    assert config["checkpoint_every"] == 30
    assert config["llm"]["default_route"]["provider"] == "scripted"
    assert {
        route["provider"] for route in config["llm"]["routes"].values()
    } == {"scripted"}

    store, world, _ = open_run(config, None, None, data_dir=tmp_path)
    try:
        assert store.scalar("SELECT COUNT(*) FROM agents") == 300
        assert store.scalar(
            "SELECT COUNT(*) FROM agents WHERE population_tier='core'"
        ) == 100
        assert store.scalar(
            "SELECT COUNT(*) FROM agents WHERE population_tier='periphery'"
        ) == 200
        regional_counts = {
            row["region_key"]: int(row["resident_count"])
            for row in store.query(
                "SELECT r.region_key,COUNT(a.id) AS resident_count "
                "FROM regions r LEFT JOIN agents a ON a.region_id=r.id "
                "GROUP BY r.id ORDER BY r.id"
            )
        }
        assert regional_counts == {
            "northstar": 250,
            "ironvale": 25,
            "suncoast": 25,
        }
        reconciled, diagnostic = world.economy.ledger.reconcile()
        assert reconciled, diagnostic
        authoritative_before = (
            int(store.tick),
            int(store.scalar("SELECT COUNT(*) FROM events")),
            int(store.scalar("SELECT COUNT(*) FROM transactions")),
            int(store.scalar("SELECT COUNT(*) FROM ledger_entries")),
        )

        app = FastAPI()
        install_v2_routes(app, world, SimpleNamespace())
        with TestClient(app) as client:
            core_response = client.get(
                "/api/v2/world-map",
                params={"layers": "agents", "population": "core"},
            )
            assert core_response.status_code == 200
            core_data = core_response.json()["data"]
            assert len(core_data["agents"]) == 100
            assert core_data["population_mode"] == "core"
            assert core_data["population_summary"] == {
                "total": 300,
                "core": 100,
                "periphery": 200,
                "rendered_agents": 100,
                "clustered_agents": 0,
            }

            all_response = client.get(
                "/api/v2/world-map",
                params={"layers": "agents,presence", "population": "all"},
            )
            assert all_response.status_code == 200
            all_data = all_response.json()["data"]
            assert len(all_data["agents"]) == 300
            peripheral_agents = [
                agent for agent in all_data["agents"]
                if agent["population_tier"] == "periphery"
            ]
            assert len(peripheral_agents) == 200
            assert all(
                agent["place_id"] is None
                and agent["place_name"] is None
                and agent["x"] is None
                and agent["y"] is None
                for agent in peripheral_agents
            )
            peripheral_ids = {agent["id"] for agent in peripheral_agents}
            assert all(
                item.get("agent_id") not in peripheral_ids
                for item in all_data["presence"]
            )

            cluster_response = client.get(
                "/api/v2/world-map",
                params={"layers": "agents,presence", "population": "clusters"},
            )
            assert cluster_response.status_code == 200
            cluster_data = cluster_response.json()["data"]
            assert len(cluster_data["agents"]) == 100
            assert sum(
                cluster["count"] for cluster in cluster_data["population_clusters"]
            ) == 200
            assert cluster_data["population_summary"]["clustered_agents"] == 200
            assert all(
                set(cluster) == {
                    "id", "region_id", "label", "count", "x", "y",
                }
                for cluster in cluster_data["population_clusters"]
            )
            assert all(
                item.get("agent_id") not in peripheral_ids
                for item in cluster_data["presence"]
            )

            active_peripheral_id = min(peripheral_ids)
            world.gateway._agent_activity_tokens[1] = {
                "agent_id": active_peripheral_id,
                "state": "thinking",
                "tick": store.tick,
                "started_monotonic": 0.0,
            }
            active_response = client.get(
                "/api/v2/world-map",
                params={"layers": "agents,presence", "population": "clusters"},
            )
            assert active_response.status_code == 200
            active_data = active_response.json()["data"]
            active_agent = next(
                agent for agent in active_data["agents"]
                if agent["id"] == active_peripheral_id
            )
            assert len(active_data["agents"]) == 101
            assert active_agent["population_tier"] == "periphery"
            assert active_agent["place_id"] is None
            assert active_agent["place_name"] is None
            assert active_agent["x"] is None
            assert active_agent["y"] is None
            assert active_data["population_summary"]["clustered_agents"] == 199
            world.gateway._agent_activity_tokens.clear()

            invalid = client.get(
                "/api/v2/world-map",
                params={"layers": "agents", "population": "private"},
            )
            assert invalid.status_code == 422

            living_response = client.get(
                "/api/v2/workspaces/living-agents",
                params={"limit": 200},
            )
            assert living_response.status_code == 200
            living_data = living_response.json()["data"]
            assert living_data["summary"]["living_agents"] == 300
            assert len(living_data["agents"]) == 300
            assert living_data["summary"]["runtime_active"] == 0
            peripheral_profiles = [
                agent for agent in living_data["agents"]
                if agent["population_tier"] == "periphery"
            ]
            assert len(peripheral_profiles) == 200
            assert all(
                place is None or (
                    place["visibility"] == "region_only"
                    and "id" not in place
                    and "name" not in place
                )
                for agent in peripheral_profiles
                for place in (agent["residence"], agent["workplace"])
            )
        assert (
            int(store.tick),
            int(store.scalar("SELECT COUNT(*) FROM events")),
            int(store.scalar("SELECT COUNT(*) FROM transactions")),
            int(store.scalar("SELECT COUNT(*) FROM ledger_entries")),
        ) == authoritative_before
    finally:
        store.close()


def test_civic_city_300_construction_profile_is_forward_only_and_zero_cost() -> None:
    config = load_config("runs/civic-city-300-construction.yaml")

    assert config["engine_semantics_version"] == 13
    assert config["population"]["target_total"] == 297
    assert config["living_world"]["core_agents"] == 100
    assert config["construction"] == {
        "enabled": True,
        "agent_initiation": True,
        "private_home_funding_cents": 20_000,
        "workplace_funding_cents": 60_000,
        "public_facility_funding_cents": 80_000,
        "private_home_work_units": 4,
        "workplace_work_units": 8,
        "public_facility_work_units": 10,
        "funding_contribution_cents": 10_000,
        "work_units_per_action": 2,
    }
    assert config["budget"]["cap_usd"] == 0.0
    assert config["llm"]["default_route"]["provider"] == "scripted"
    assert {
        route["provider"] for route in config["llm"]["routes"].values()
    } == {"scripted"}

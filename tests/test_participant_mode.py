import asyncio
import json

from fastapi.testclient import TestClient
import pytest

from engine.store import Store
from server.app import create_app
from world.loop import World
from world.replay_verify import verify_replay


def _config(**updates):
    config = {
        "seed": 19,
        "population": {"size": 8},
        "banks": {"count": 2},
        "firms": {"count": 3, "listed": 1},
        "budget": {"cap_usd": 200.0, "oracle_reserve_usd": 10.0, "conversation_pairs": 1},
        "llm": {"default_route": {"provider": "scripted", "model": "scripted"}, "routes": {}},
        "participant_mode": {"enabled": True},
        "checkpoint_every": 0,
        "outlets": [{"id": 1, "name": "A", "slant": "market"},
                    {"id": 2, "name": "B", "slant": "labor"}],
    }
    config.update(updates)
    return config


def _world(tmp_path, config=None):
    config = config or _config()
    store = Store(str(tmp_path / "participant.db"))
    store.init_run_meta("participant", config["seed"], config)
    world = World(store, config)
    world.initialize()
    return store, world


def test_participant_mode_rejects_acceptance_configuration(tmp_path):
    config = _config(acceptance={"min_ticks": 3})
    store = Store(str(tmp_path / "conflict.db"))
    store.init_run_meta("conflict", config["seed"], config)
    with pytest.raises(ValueError, match="cannot be enabled"):
        World(store, config)


def test_participant_controls_one_citizen_and_executes_through_normal_engine(tmp_path):
    store, world = _world(tmp_path)
    citizen = store.query_one("SELECT id FROM agents WHERE kind='citizen' AND alive=1 ORDER BY id")
    agent_id = int(citizen["id"])
    app = create_app(world)

    with TestClient(app) as client:
        status = client.get("/api/participant").json()
        assert status["enabled"] and not status["active"]

        response = client.post("/api/participant/control", json={
            "agent_id": agent_id, "expected_tick": 0,
        })
        assert response.status_code == 200
        participant = response.json()
        assert participant["controlled_agent"]["id"] == agent_id

        assert client.post("/api/run/start").status_code == 409
        assert client.post("/api/run/step").status_code == 409

        buy = next(item for item in participant["action_catalog"]
                   if item["type"] == "buy_goods" and item["enabled"])
        firm_id = buy["fields"][0]["options"][0]["value"]
        queued = client.post("/api/participant/action", json={
            "expected_tick": 0,
            "action": {"type": "buy_goods", "firm_id": firm_id, "qty": 1},
            "reasoning": "I need supplies.",
        })
        assert queued.status_code == 200
        assert queued.json()["queued_action"]["target_tick"] == 1

        stepped = client.post("/api/run/step")
        assert stepped.status_code == 200
        assert stepped.json()["tick"] == 1

        after = client.get("/api/participant").json()
        assert after["active"] and after["queued_action"] is None
        assert after["last_result"]["status"] == "executed"
        assert store.scalar(
            "SELECT COUNT(*) FROM llm_calls WHERE agent_id=? AND tick=1 "
            "AND purpose IN ('decision','citizen','founder')", (agent_id,), default=0) == 0
        assert store.scalar(
            "SELECT COUNT(*) FROM events WHERE kind='participant_action_executed'", default=0) == 1
        assert bool(store.get_meta()["participant_influenced"])
        assert world.economy.ledger.reconcile()[0]

        stale = client.post("/api/participant/action", json={
            "expected_tick": 0, "action": {"type": "do_nothing"},
        })
        assert stale.status_code == 409
        released = client.post("/api/participant/release", json={"expected_tick": 1})
        assert released.status_code == 200
        assert not released.json()["active"]


def test_participant_rejects_staff_and_untrusted_action_fields(tmp_path):
    store, world = _world(tmp_path)
    staff = store.query_one("SELECT id FROM agents WHERE kind='staff' ORDER BY id")
    citizen = store.query_one("SELECT id FROM agents WHERE kind='citizen' AND alive=1 ORDER BY id")
    with TestClient(create_app(world)) as client:
        assert client.post("/api/participant/control", json={
            "agent_id": int(staff["id"]), "expected_tick": 0,
        }).status_code == 409
        assert client.post("/api/participant/control", json={
            "agent_id": int(citizen["id"]), "expected_tick": 0,
        }).status_code == 200
        rejected = client.post("/api/participant/action", json={
            "expected_tick": 0,
            "action": {"type": "do_nothing", "balance_cents": 999999999},
        })
        assert rejected.status_code == 400
        assert store.scalar("SELECT COUNT(*) FROM participant_actions", default=0) == 0


def test_participant_server_owns_hidden_firm_id_and_releases_dead_citizen(tmp_path):
    store, world = _world(tmp_path)
    founder = store.query_one(
        "SELECT founder_agent_id,id FROM firms WHERE founder_agent_id IS NOT NULL ORDER BY id")
    agent_id = int(founder["founder_agent_id"])
    firm_id = int(founder["id"])
    other_firm = int(store.scalar(
        "SELECT id FROM firms WHERE id<>? ORDER BY id LIMIT 1", (firm_id,)))

    with TestClient(create_app(world)) as client:
        acquired = client.post("/api/participant/control", json={
            "agent_id": agent_id, "expected_tick": 0,
        })
        assert acquired.status_code == 200
        set_price = next(item for item in acquired.json()["action_catalog"]
                         if item["type"] == "set_price")
        queued = client.post("/api/participant/action", json={
            "expected_tick": 0,
            "action": {
                "type": "set_price", "firm_id": other_firm,
                "price": set_price["fields"][1]["default"] + 1,
            },
        })
        assert queued.status_code == 200
        assert queued.json()["queued_action"]["action"]["firm_id"] == firm_id

        store.execute("UPDATE agents SET alive=0 WHERE id=?", (agent_id,))
        store.commit()
        status = client.get("/api/participant").json()
        assert not status["active"]
        release = store.query_one(
            "SELECT payload_json FROM events WHERE kind='participant_control_released' "
            "ORDER BY id DESC LIMIT 1")
        assert json.loads(release["payload_json"])["reason"] == "citizen_unavailable"
        assert store.scalar(
            "SELECT COUNT(*) FROM participant_actions WHERE status='cancelled'", default=0) == 1


def test_participant_history_is_paginated_and_rejects_invalid_scope(tmp_path):
    store, world = _world(tmp_path)
    citizen = store.query_one("SELECT id FROM agents WHERE kind='citizen' ORDER BY id")
    staff = store.query_one("SELECT id FROM agents WHERE kind='staff' ORDER BY id")
    agent_id = int(citizen["id"])
    action_ids = []
    for tick, status in ((1, "executed"), (2, "rejected"), (3, "cancelled")):
        action_ids.append(store.insert(
            "participant_actions", agent_id=agent_id, target_tick=tick,
            action_json=json.dumps({"type": "do_nothing"}), reasoning=f"day {tick}",
            status=status, result_json=json.dumps([{"ok": status == "executed"}]),
            created_at=f"2026-07-13T00:00:0{tick}+00:00"))
    store.commit()

    with TestClient(create_app(world)) as client:
        first = client.get(
            "/api/participant/history", params={"agent_id": agent_id, "limit": 2})
        assert first.status_code == 200
        first_page = first.json()
        assert [item["id"] for item in first_page["items"]] == action_ids[::-1][:2]
        assert first_page["items"][0]["reasoning"] == "day 3"
        assert first_page["next_before_id"] == action_ids[1]

        second = client.get("/api/participant/history", params={
            "agent_id": agent_id, "limit": 2,
            "before_id": first_page["next_before_id"],
        }).json()
        assert [item["id"] for item in second["items"]] == [action_ids[0]]
        assert second["next_before_id"] is None
        assert client.get(
            "/api/participant/history", params={"agent_id": 999999}).status_code == 404
        assert client.get(
            "/api/participant/history", params={"agent_id": int(staff["id"])}).status_code == 409
        assert client.get(
            "/api/participant/history", params={"agent_id": agent_id, "limit": 101}).status_code == 422


def test_participant_control_and_command_survive_restart_exactly_once(tmp_path):
    config = _config()
    path = tmp_path / "participant-resume.db"
    initial = Store(str(path))
    initial.init_run_meta("participant-resume", config["seed"], config)
    initial_world = World(initial, config)
    initial_world.initialize()
    citizen = initial.query_one(
        "SELECT id FROM agents WHERE kind='citizen' AND alive=1 ORDER BY id")
    agent_id = int(citizen["id"])
    initial_world.runtime.participant.acquire(agent_id, 0, running=False)
    initial_world.runtime.participant.queue_action(
        0, {"type": "do_nothing"}, "Persist across restart.", running=False)
    initial.close()

    resumed_store = Store(str(path))
    resumed_world = World(resumed_store, config)
    resumed_world.initialize()
    resumed_status = resumed_world.runtime.participant.status(running=False)
    assert resumed_status["controlled_agent"]["id"] == agent_id
    assert resumed_status["queued_action"]["target_tick"] == 1
    asyncio.run(resumed_world.step())
    resumed_store.close()

    verified = Store(str(path))
    actions = verified.query(
        "SELECT status,result_json FROM participant_actions WHERE agent_id=?", (agent_id,))
    assert len(actions) == 1
    assert actions[0]["status"] == "executed"
    assert json.loads(actions[0]["result_json"])[0]["ok"]
    assert verified.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='participant_action_executed'", default=0) == 1
    assert World(verified, config).runtime.participant.history(agent_id)["items"][0]["status"] == "executed"
    verified.close()


def test_participant_history_is_disabled_outside_the_sandbox(tmp_path):
    config = _config(participant_mode={"enabled": False})
    store, world = _world(tmp_path, config)
    citizen = store.query_one("SELECT id FROM agents WHERE kind='citizen' ORDER BY id")
    with TestClient(create_app(world)) as client:
        response = client.get(
            "/api/participant/history", params={"agent_id": int(citizen["id"])})
        assert response.status_code == 403
        assert "disabled" in response.json()["detail"]


def test_participant_action_replays_exactly_without_live_input(tmp_path):
    config = _config()
    source_path = tmp_path / "participant-source.db"
    source = Store(str(source_path))
    source.init_run_meta("participant-source", config["seed"], config)
    source_world = World(source, config)
    source_world.initialize()
    citizen = source.query_one(
        "SELECT id FROM agents WHERE kind='citizen' AND alive=1 ORDER BY id")
    agent_id = int(citizen["id"])
    service = source_world.runtime.participant
    service.acquire(agent_id, 0, running=False)
    buy = next(item for item in service.status(running=False)["action_catalog"]
               if item["type"] == "buy_goods" and item["enabled"])
    firm_id = buy["fields"][0]["options"][0]["value"]
    service.queue_action(
        0, {"type": "buy_goods", "firm_id": firm_id, "qty": 1},
        "Replay this purchase.", running=False)
    asyncio.run(source_world.step())
    source.close()

    replay_path = tmp_path / "participant-replay.db"
    replay_config = {**config, "replay_source_path": str(source_path)}
    replay = Store(str(replay_path))
    replay.init_run_meta("participant-replay", config["seed"], replay_config)
    replay_world = World(replay, replay_config, replay=True)
    replay_world.initialize()
    asyncio.run(replay_world.step())
    replay.commit()

    replayed = replay.query_one("SELECT source_action_id,status FROM participant_actions")
    assert replayed["source_action_id"] is not None
    assert replayed["status"] == "executed"
    proof = verify_replay(source_path, replay_path)
    assert proof["exact"], proof["differences"]
    replay.close()


def test_acceptance_run_cannot_be_started_from_an_unauthorized_browser(tmp_path):
    config = _config(participant_mode={"enabled": False}, acceptance={"min_ticks": 2})
    store, world = _world(tmp_path, config)
    with TestClient(create_app(world)) as client:
        response = client.post("/api/run/start")
        assert response.status_code == 403
        assert "--acceptance-run" in response.json()["detail"]

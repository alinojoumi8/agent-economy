import asyncio

from engine.personal_names import assign_personal_names, is_role_label
from run import open_run
from run_config import load_config
from world.replay_verify import verify_replay


def config():
    value = load_config("runs/hermes-local.yaml")
    value["population"]["size"] = 2
    value["firms"].update(count=1, listed=0)
    value["communications"]["autonomous_scripted_enabled"] = False
    value["personal_names"] = {"version": 1, "activation_tick": 2}
    return value


def test_names_activate_prospectively_and_survive_resume_and_replay(tmp_path):
    cfg = config()
    store, world, run_id = open_run(cfg, None, None, data_dir=tmp_path)
    try:
        before = [tuple(row) for row in store.query("SELECT id,name FROM agents ORDER BY id")]
        assert any(is_role_label(name) for _, name in before)
        asyncio.run(world.step())
        assert [tuple(row) for row in store.query("SELECT id,name FROM agents ORDER BY id")] == before
        asyncio.run(world.step())
        names = [tuple(row) for row in store.query("SELECT id,name FROM agents ORDER BY id")]
        assert all(not is_role_label(name) for _, name in names)
        assert len({name for _, name in names}) == len(names)
        assert assign_personal_names(store, cfg, 2) == 0
        assert world.economy.ledger.reconcile()[0]
        event_count = store.scalar("SELECT COUNT(*) FROM events")
    finally:
        world.close()
    store, world, _ = open_run({}, run_id, None, data_dir=tmp_path)
    try:
        assert store.tick == 2
        assert [tuple(row) for row in store.query("SELECT id,name FROM agents ORDER BY id")] == names
        assert store.scalar("SELECT COUNT(*) FROM events") == event_count
    finally:
        world.close()
    replay_store, replay, replay_id = open_run({}, None, run_id, data_dir=tmp_path)
    try:
        asyncio.run(replay.step())
        asyncio.run(replay.step())
    finally:
        replay.close()
    result = verify_replay(tmp_path / f"{run_id}.db", tmp_path / f"{replay_id}.db")
    assert result["differences"] == []


def test_legacy_config_and_real_names_are_unchanged(tmp_path):
    cfg = config()
    cfg.pop("personal_names")
    store, world, _ = open_run(cfg, None, None, data_dir=tmp_path)
    try:
        assert assign_personal_names(store, cfg, 10) == 0
        assert is_role_label("House Member 2")
        assert not is_role_label("Maya Chen")
        assert not is_role_label("Secretary Lin")
        assert assign_personal_names(store, {**cfg, "engine_semantics_version": 1,
                                           "personal_names": {"version": 1}}, 10) == 0
    finally:
        world.close()


def test_fresh_default_names_and_later_blank_arrival(tmp_path):
    cfg = config()
    cfg["personal_names"] = {"version": 1, "activation_tick": 0}
    store, world, _ = open_run(cfg, None, None, data_dir=tmp_path)
    try:
        assert all(not is_role_label(row["name"]) for row in store.query("SELECT name FROM agents"))
        # A future admission/succession with an empty name is repaired once.
        store.execute("UPDATE agents SET name='' WHERE id=11")
        money = [tuple(row) for row in store.query("SELECT * FROM ledger_entries ORDER BY id")]
        assert assign_personal_names(store, cfg, 1) == 1
        assert not is_role_label(store.scalar("SELECT name FROM agents WHERE id=11"))
        assert [tuple(row) for row in store.query("SELECT * FROM ledger_entries ORDER BY id")] == money
        assert assign_personal_names(store, cfg, 1) == 0
    finally:
        world.close()

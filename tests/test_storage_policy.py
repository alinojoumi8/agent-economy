from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
import time

import pytest

from engine import checkpoint_retention
from engine.checkpoint_retention import pin_checkpoint, unpin_checkpoint, verify_checkpoint
from engine.storage_policy import StorageBudgetExceeded, StoragePolicy
from engine.store import Store
from run import open_run
from world.loop import World
from .test_checkpoint_retention import _config, _checkpoint


def policy(**overrides):
    return StoragePolicy(min_free_bytes=0, max_run_bytes=0, max_tenant_bytes=0,
                         **overrides)


def world_with_policy(tmp_path, **overrides):
    config = _config(tmp_path)
    config["storage_policy"] = policy(**overrides).as_dict()
    store = Store(str(tmp_path / "world.db"))
    store.init_run_meta("retention-run", config["seed"], config)
    world = World(store, config)
    world.initialize()
    return world


@pytest.mark.parametrize("value", [{"checkpoint_keep_last": 1}, {"min_free_bytes": -1},
                                  {"max_run_bytes": True}, {"compress_payloads": "yes"},
                                  {"unknown": 2}, []])
def test_invalid_storage_policy_is_rejected(value):
    with pytest.raises(ValueError):
        StoragePolicy.from_mapping(value)


def test_rotation_preserves_pins_memories_and_two_verified_recoveries(tmp_path):
    world = world_with_policy(tmp_path, checkpoint_keep_last=2, checkpoint_max_bytes=1)
    try:
        before = [tuple(row) for row in world.store.query("SELECT * FROM memories ORDER BY id")]
        pinned = _checkpoint(world, 1)
        pin_checkpoint(pinned, "Reviewed research milestone")
        paths = [_checkpoint(world, tick) for tick in (2, 3, 4)]
        assert pinned.exists() and not paths[0].exists()
        for path in paths[1:]:
            verify_checkpoint(path)
        assert world.checkpoint(1) is None  # a pin also prevents replacement
        assert before == [tuple(row) for row in world.store.query("SELECT * FROM memories ORDER BY id")]
        receipt = json.loads((pinned.parent / "retention-run.retention.json").read_text())
        assert receipt["budget_exceeded"] and receipt["protected"] == 1
        unpin_checkpoint(pinned)
        _checkpoint(world, 5)
        assert not pinned.exists()
    finally:
        world.close()


def test_corrupt_and_foreign_artifacts_are_never_pruned(tmp_path):
    world = world_with_policy(tmp_path, checkpoint_keep_last=2)
    try:
        damaged = _checkpoint(world, 1)
        with damaged.open("r+b") as handle:
            handle.write(b"invalid header!!")
        foreign = damaged.parent / "someone-else.db"
        foreign.write_bytes(b"private file")
        for tick in (2, 3, 4):
            _checkpoint(world, tick)
        assert damaged.exists() and foreign.read_bytes() == b"private file"
        assert not (damaged.parent / "retention-run_t2.db").exists()
    finally:
        world.close()


def test_failed_publication_keeps_previous_verified_points(tmp_path, monkeypatch):
    world = world_with_policy(tmp_path, checkpoint_keep_last=2)
    try:
        old = [_checkpoint(world, tick) for tick in (1, 2)]
        def fail(*args):
            raise OSError("publication failed")
        monkeypatch.setattr(checkpoint_retention, "_atomic_json", fail)
        assert world.checkpoint(3) is None
        assert [row["tick"] for row in world.store.query("SELECT tick FROM checkpoints ORDER BY tick")] == [1, 2]
        for path in old:
            verify_checkpoint(path)
    finally:
        world.close()


def test_disk_limit_pauses_before_new_actions_and_preserves_memory(tmp_path):
    world = world_with_policy(tmp_path)
    try:
        tick = world.store.tick
        before = {table: [tuple(row) for row in world.store.query(f"SELECT * FROM {table}")]
                  for table in ("memories", "events", "ledger_entries", "llm_calls")}
        world.storage_policy = replace(world.storage_policy, max_run_bytes=1)
        asyncio.run(world.step())
        assert world.status == "paused" and world.store.tick == tick
        assert world.last_pause_reason["reason"] == "storage"
        for table, rows in before.items():
            assert rows == [tuple(row) for row in world.store.query(f"SELECT * FROM {table}")]
    finally:
        world.close()


def test_resume_policy_does_not_rewrite_recorded_config(tmp_path):
    store, world, run_id = open_run(_config(tmp_path), None, None, data_dir=tmp_path)
    recorded = store.get_meta()["config_json"]
    world.close()
    store, world, _ = open_run({"storage_policy": policy().as_dict()}, run_id, None,
                              data_dir=tmp_path)
    try:
        assert store.get_meta()["config_json"] == recorded
        assert world.storage_policy.checkpoint_keep_last == 4
        assert store.compress_payloads
        assert store.query_one("PRAGMA synchronous")[0] == 2
    finally:
        world.close()


def test_tenant_budget_counts_disk_files(tmp_path):
    (tmp_path / "run.db").write_bytes(b"x" * 100)
    limited = replace(policy(), max_tenant_bytes=120)
    limited.check_tenant(tmp_path)
    with pytest.raises(StorageBudgetExceeded, match="tenant"):
        limited.check_tenant(tmp_path, additional_bytes=21)


def test_async_retention_verification_keeps_the_serving_loop_responsive(tmp_path, monkeypatch):
    world = world_with_policy(tmp_path)
    original = checkpoint_retention.verify_checkpoint
    def slow(path):
        time.sleep(0.15)
        return original(path)
    monkeypatch.setattr(checkpoint_retention, "verify_checkpoint", slow)
    async def scenario():
        task = asyncio.create_task(world.checkpoint_async(1))
        heartbeats = 0
        while not task.done():
            await asyncio.sleep(0.01)
            heartbeats += 1
        assert await task is not None
        assert heartbeats >= 8
    try:
        asyncio.run(scenario())
    finally:
        world.close()

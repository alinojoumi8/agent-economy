"""Opt-in retention tests for finalized world checkpoint artifacts."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.store import Store
from world import loop as loop_module
from world.loop import World


def _config(tmp_path: Path, *, keep_last: int | None = None) -> dict:
    config = {
        "seed": 718,
        "engine_semantics_version": 7,
        "population": {"size": 6, "baseline_citizens_core": True},
        "banks": {"count": 2},
        "firms": {"count": 1, "listed": 0},
        "outlets": [
            {"id": 10, "name": "North", "slant": "neutral"},
            {"id": 20, "name": "South", "slant": "neutral"},
        ],
        "lifecycle": {"housing_cost_cents": 100},
        "budget": {"cap_usd": 10.0, "oracle_reserve_usd": 1.0,
                   "conversation_pairs": 0},
        "llm": {
            "default_route": {"provider": "scripted", "model": "scripted"},
            "routes": {},
        },
        "checkpoint_every": 0,
        "checkpoint_dir": str(tmp_path / "checkpoints"),
    }
    if keep_last is not None:
        config["checkpoint_keep_last"] = keep_last
    return config


def _world(tmp_path: Path, *, keep_last: int | None = None) -> World:
    config = _config(tmp_path, keep_last=keep_last)
    store = Store(str(tmp_path / "world.db"))
    store.init_run_meta("retention-run", config["seed"], config)
    world = World(store, config)
    world.initialize()
    return world


def _checkpoint(world: World, tick: int) -> Path:
    path = world.checkpoint(tick)
    assert path is not None
    return Path(path)


def _manifest(database: Path) -> Path:
    return Path(f"{database}.manifest.json")


def _checkpoint_rows(world: World):
    return world.store.query("SELECT id,tick,path FROM checkpoints ORDER BY tick,id")


def test_retention_keeps_two_newest_checkpoint_bodies_and_manifests(tmp_path):
    world = _world(tmp_path, keep_last=2)
    try:
        first, second, third = (_checkpoint(world, tick) for tick in (100, 200, 300))

        rows = _checkpoint_rows(world)

        assert [int(row["tick"]) for row in rows] == [200, 300]
        assert not first.exists()
        assert not _manifest(first).exists()
        for checkpoint in (second, third):
            assert checkpoint.exists()
            assert _manifest(checkpoint).exists()
    finally:
        world.close()


@pytest.mark.parametrize("keep_last", [None, 0, -1])
def test_retention_is_disabled_without_a_positive_keep_last(tmp_path, keep_last):
    world = _world(tmp_path, keep_last=keep_last)
    try:
        checkpoints = [_checkpoint(world, tick) for tick in (100, 200, 300)]

        assert [int(row["tick"]) for row in _checkpoint_rows(world)] == [100, 200, 300]
        assert all(checkpoint.exists() for checkpoint in checkpoints)
        assert all(_manifest(checkpoint).exists() for checkpoint in checkpoints)
    finally:
        world.close()


def test_retention_supports_relative_checkpoint_dirs_with_canonical_rows(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    world = _world(tmp_path, keep_last=2)
    try:
        world.config["checkpoint_dir"] = "checkpoints"

        checkpoints = [_checkpoint(world, tick) for tick in (100, 200, 300)]
        expected_dir = (tmp_path / "checkpoints").resolve()
        rows = _checkpoint_rows(world)

        assert [int(row["tick"]) for row in rows] == [200, 300]
        assert all(checkpoint.parent == expected_dir for checkpoint in checkpoints)
        assert [row["path"] for row in rows] == [str(path) for path in checkpoints[1:]]
        assert not checkpoints[0].exists()
        assert all(checkpoint.exists() for checkpoint in checkpoints[1:])
    finally:
        world.close()


@pytest.mark.parametrize(
    "setting",
    [True, False, 1.0, 1.9, "2", float("inf"), float("-inf"), float("nan")],
    ids=["true", "false", "whole-float", "fractional-float", "string", "inf", "neg-inf", "nan"],
)
def test_retention_requires_a_real_positive_integer_setting(tmp_path, setting):
    world = _world(tmp_path)
    try:
        world.config["checkpoint_keep_last"] = setting

        checkpoints = [world.checkpoint(tick) for tick in (100, 200, 300)]

        assert all(checkpoint is not None for checkpoint in checkpoints)
        assert [int(row["tick"]) for row in _checkpoint_rows(world)] == [100, 200, 300]
        assert all(Path(checkpoint).exists() for checkpoint in checkpoints)
        assert world.store.query_one(
            "SELECT id FROM events WHERE kind='checkpoint_failed' LIMIT 1") is None
    finally:
        world.close()


def test_retention_counts_unique_checkpoint_artifacts_not_duplicate_rows(tmp_path):
    world = _world(tmp_path, keep_last=2)
    try:
        first = _checkpoint(world, 100)
        _checkpoint(world, 200)
        newest = _checkpoint(world, 200)

        rows = _checkpoint_rows(world)

        assert [int(row["tick"]) for row in rows] == [100, 200]
        assert first.exists() and _manifest(first).exists()
        assert newest.exists() and _manifest(newest).exists()
    finally:
        world.close()


def _symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks are unavailable: {type(exc).__name__}")


def test_retention_leaves_symlink_alias_rows_outside_generated_path_scope(tmp_path):
    world = _world(tmp_path, keep_last=2)
    try:
        canonical = _checkpoint(world, 100)
        canonical_id = int(_checkpoint_rows(world)[0]["id"])
        alias = canonical.with_name("retention-alias.db")
        _symlink_or_skip(alias, canonical)
        alias_id = world.store.insert("checkpoints", tick=100, path=str(alias))
        world.store.commit()

        retained = _checkpoint(world, 200)

        row_ids = {int(row["id"]) for row in _checkpoint_rows(world)}
        assert {canonical_id, alias_id} <= row_ids
        assert canonical.exists() and _manifest(canonical).exists()
        assert alias.is_symlink()
        assert retained.exists() and _manifest(retained).exists()
    finally:
        world.close()


def test_retention_leaves_symlinked_checkpoint_artifacts_untouched(tmp_path):
    world = _world(tmp_path, keep_last=1)
    try:
        stale = _checkpoint(world, 100)
        stale_id = int(_checkpoint_rows(world)[0]["id"])
        stale_manifest = _manifest(stale)
        database_target = stale.with_name("retention-target.db")
        manifest_target = _manifest(database_target)
        database_target.write_bytes(stale.read_bytes())
        manifest_target.write_bytes(stale_manifest.read_bytes())
        stale.unlink()
        stale_manifest.unlink()
        _symlink_or_skip(stale, database_target)
        _symlink_or_skip(stale_manifest, manifest_target)

        retained = _checkpoint(world, 200)

        row_ids = {int(row["id"]) for row in _checkpoint_rows(world)}
        assert stale_id in row_ids
        assert stale.is_symlink() and stale_manifest.is_symlink()
        assert database_target.exists() and manifest_target.exists()
        assert retained.exists() and _manifest(retained).exists()
    finally:
        world.close()


def test_retention_prunes_only_current_run_paths(tmp_path):
    world = _world(tmp_path, keep_last=1)
    try:
        stale_current = _checkpoint(world, 100)
        stale_current_id = int(_checkpoint_rows(world)[0]["id"])
        checkpoint_dir = Path(world.config["checkpoint_dir"])
        foreign = checkpoint_dir / "other-run_t1.db"
        outside = tmp_path / "outside.db"
        for artifact in (foreign, outside):
            artifact.write_bytes(b"outside retention scope")
            _manifest(artifact).write_text("{}", encoding="utf-8")
        foreign_id = world.store.insert("checkpoints", tick=1, path=str(foreign))
        outside_id = world.store.insert("checkpoints", tick=2, path=str(outside))
        world.store.commit()

        retained = _checkpoint(world, 200)

        rows = _checkpoint_rows(world)
        row_ids = {int(row["id"]) for row in rows}
        assert stale_current_id not in row_ids
        assert {foreign_id, outside_id} <= row_ids
        assert [int(row["tick"]) for row in rows] == [1, 2, 200]
        assert any(str(row["path"]) == str(retained) for row in rows)
        assert not stale_current.exists()
        assert not _manifest(stale_current).exists()
        assert retained.exists() and _manifest(retained).exists()
        assert foreign.exists() and _manifest(foreign).exists()
        assert outside.exists() and _manifest(outside).exists()
    finally:
        world.close()


def test_retention_removes_a_stale_row_when_its_artifacts_are_missing(tmp_path):
    world = _world(tmp_path, keep_last=1)
    try:
        stale = _checkpoint(world, 100)
        stale.unlink()
        _manifest(stale).unlink()

        retained = _checkpoint(world, 200)

        rows = _checkpoint_rows(world)
        assert [int(row["tick"]) for row in rows] == [200]
        assert retained.exists() and _manifest(retained).exists()
    finally:
        world.close()


@pytest.mark.parametrize("missing_artifact", ["database", "manifest"])
def test_incomplete_newest_checkpoint_does_not_consume_a_retention_slot(
        tmp_path, missing_artifact):
    world = _world(tmp_path, keep_last=2)
    try:
        oldest = _checkpoint(world, 100)
        incomplete = _checkpoint(world, 200)
        orphan = incomplete if missing_artifact == "manifest" else _manifest(incomplete)
        missing = _manifest(incomplete) if missing_artifact == "manifest" else incomplete
        missing.unlink()

        newest = _checkpoint(world, 300)

        assert [int(row["tick"]) for row in _checkpoint_rows(world)] == [100, 300]
        assert oldest.exists() and _manifest(oldest).exists()
        assert newest.exists() and _manifest(newest).exists()
        assert not incomplete.exists()
        assert not _manifest(incomplete).exists()
        assert not orphan.exists()
    finally:
        world.close()


def test_retention_logs_unlink_failure_and_keeps_the_stale_row(tmp_path, monkeypatch):
    world = _world(tmp_path, keep_last=1)
    try:
        stale = _checkpoint(world, 100)
        stale_manifest = _manifest(stale)
        original_unlink = Path.unlink

        def reject_stale_manifest(path: Path, *args, **kwargs):
            if path == stale_manifest:
                raise PermissionError("checkpoint path must stay private")
            return original_unlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", reject_stale_manifest)
        retained = _checkpoint(world, 200)

        rows = _checkpoint_rows(world)
        assert [int(row["tick"]) for row in rows] == [100, 200]
        assert stale.exists() and stale_manifest.exists()
        assert retained.exists() and _manifest(retained).exists()
        event = world.store.query_one(
            "SELECT payload_json FROM events WHERE kind='checkpoint_prune_failed' "
            "ORDER BY id DESC LIMIT 1")
        assert event is not None
        payload = json.loads(event["payload_json"])
        assert payload["path"] == stale_manifest.name
        assert payload["error"] == "PermissionError"
        assert payload["error_type"] == "PermissionError"
        assert str(tmp_path) not in json.dumps(payload)
    finally:
        world.close()


def test_failed_checkpoint_creation_does_not_prune_existing_checkpoints(tmp_path, monkeypatch):
    world = _world(tmp_path, keep_last=1)
    try:
        retained = _checkpoint(world, 100)

        def fail_manifest(_database: Path) -> Path:
            raise RuntimeError("manifest write failed")

        monkeypatch.setattr(loop_module, "write_checkpoint_manifest", fail_manifest)

        assert world.checkpoint(200) is None
        assert [int(row["tick"]) for row in _checkpoint_rows(world)] == [100]
        assert retained.exists() and _manifest(retained).exists()
    finally:
        world.close()


def test_prune_failure_does_not_erase_a_successful_checkpoint_result(tmp_path, monkeypatch):
    world = _world(tmp_path, keep_last=1)
    try:
        def fail_prune(_run_id: str, _keep_last: int) -> None:
            raise RuntimeError("retention subsystem unavailable")

        monkeypatch.setattr(world, "_prune_checkpoints", fail_prune)

        created = world.checkpoint(100)

        assert created is not None
        database = Path(created)
        assert database.exists() and _manifest(database).exists()
        assert [int(row["tick"]) for row in _checkpoint_rows(world)] == [100]
        assert world.store.query_one(
            "SELECT id FROM events WHERE kind='checkpoint_failed' LIMIT 1"
        ) is None
        event = world.store.query_one(
            "SELECT payload_json FROM events WHERE kind='checkpoint_prune_failed' "
            "ORDER BY id DESC LIMIT 1"
        )
        assert event is not None
        payload = json.loads(event["payload_json"])
        assert payload["error_type"] == "RuntimeError"
        assert "retention subsystem unavailable" not in json.dumps(payload)
    finally:
        world.close()

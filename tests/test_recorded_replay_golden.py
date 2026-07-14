from __future__ import annotations

import asyncio
import json
import re

from llm.adapters import OpenAICompatAdapter
from run import open_run, replay_headless
from world.replay_verify import verify_replay

from .recorded_replay_fixture import load_recorded_fixture, restore_recorded_source


def test_fd0adc5dc1_portable_fixture_is_sanitized():
    fixture = load_recorded_fixture()
    serialized = json.dumps(fixture, sort_keys=True)

    assert not re.search(r"\bsk-[A-Za-z0-9_-]{16,}", serialized)
    assert not re.search(
        r"(?i)bearer\s+[A-Za-z0-9._-]{12,}", serialized)
    assert '"reasoning_content"' not in serialized
    assert '"private_reasoning"' not in serialized
    assert "<think>" not in serialized.lower()
    for row in fixture["tables"]["llm_calls"]:
        assert "raw_json" not in row
    assert fixture["tables"]["dataset_manifests"]
    assert all(
        str(row["snapshot_path"]).startswith("repo://research/data/")
        for row in fixture["tables"]["dataset_manifests"])
    assert not re.search(r"\b[A-Z]:\\Users\\", serialized, re.IGNORECASE)


def test_fd0adc5dc1_recorded_responses_replay_exactly_without_network(
        tmp_path, monkeypatch):
    source_id = "fd0adc5dc1"
    source_path = restore_recorded_source(tmp_path / f"{source_id}.db")

    async def network_forbidden(*args, **kwargs):
        raise AssertionError("recorded golden replay attempted network inference")

    monkeypatch.setattr(OpenAICompatAdapter, "complete", network_forbidden)
    replay_store, replay_world, _ = open_run(
        {}, None, source_id, data_dir=tmp_path)
    try:
        asyncio.run(replay_headless(replay_world, 10))
        proof = verify_replay(source_path, replay_store.path)
        source_config = json.loads(
            replay_world.gateway.replay_conn.execute(
                "SELECT config_json FROM run_meta WHERE id=1").fetchone()[0])

        # The preserved live run actually records semantics 5. Keeping that
        # fact intact is itself part of the compatibility guarantee.
        assert source_config["engine_semantics_version"] == 5
        assert proof["exact"], proof["differences"]
        assert proof["differences"] == []
        assert proof["source_tick"] == proof["replay_tick"] == 10
        assert proof["source_hash"] == proof["replay_hash"]
        assert replay_store.scalar("SELECT COUNT(*) FROM llm_calls") == 48
    finally:
        replay_store.close()

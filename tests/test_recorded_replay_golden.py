from __future__ import annotations

import asyncio
import copy
import json
import re

from llm.adapters import OpenAICompatAdapter
from run import open_run, replay_headless
from world.replay_verify import verify_replay

from .recorded_replay_fixture import (
    FIXTURE_PATH,
    FIXTURE_FORMAT_VERSION,
    RESPONSE_JSON_ALLOWLIST,
    SANITIZATION_METADATA,
    SOURCE_ENGINE_SEMANTICS_VERSION,
    SOURCE_REVISION,
    SOURCE_RUN_ID,
    SOURCE_TICKS,
    encode_recorded_fixture,
    load_recorded_fixture,
    restore_recorded_source,
    sanitize_recorded_fixture,
)


def test_fd0adc5dc1_portable_fixture_is_sanitized():
    fixture = load_recorded_fixture()
    serialized = json.dumps(fixture, sort_keys=True)

    assert fixture["fixture_format_version"] == FIXTURE_FORMAT_VERSION
    assert fixture["source_run_id"] == SOURCE_RUN_ID
    assert fixture["source_revision"] == SOURCE_REVISION
    assert fixture["source_engine_semantics_version"] == (
        SOURCE_ENGINE_SEMANTICS_VERSION)
    assert fixture["source_ticks"] == SOURCE_TICKS
    assert fixture["sanitization"] == SANITIZATION_METADATA
    assert not re.search(r"\bsk-[A-Za-z0-9_-]{16,}", serialized)
    assert not re.search(
        r"(?i)bearer\s+[A-Za-z0-9._-]{12,}", serialized)
    assert '"reasoning_content"' not in serialized
    assert '"private_reasoning"' not in serialized
    assert "<think>" not in serialized.lower()
    for row in fixture["tables"]["llm_calls"]:
        response = json.loads(row["response_json"])
        assert tuple(response) == tuple(sorted(RESPONSE_JSON_ALLOWLIST))
        assert isinstance(response["text"], str)
        assert isinstance(response["cached_in_tokens"], int)
        assert response["cached_in_tokens"] >= 0
        assert "raw" not in response
    assert fixture["tables"]["dataset_manifests"]
    assert all(
        str(row["snapshot_path"]).startswith("repo://research/data/")
        for row in fixture["tables"]["dataset_manifests"])
    assert not re.search(r"\b[A-Z]:\\Users\\", serialized, re.IGNORECASE)


def test_fd0adc5dc1_fixture_sanitizer_is_deterministic_and_strips_raw():
    fixture = load_recorded_fixture()
    dirty = copy.deepcopy(fixture)
    response = json.loads(dirty["tables"]["llm_calls"][0]["response_json"])
    response["raw"] = {"id": "provider-response-id", "usage": {"total_tokens": 1}}
    dirty["tables"]["llm_calls"][0]["response_json"] = json.dumps(response)

    first = sanitize_recorded_fixture(dirty)
    second = sanitize_recorded_fixture(dirty)

    assert first == second == fixture
    assert encode_recorded_fixture(dirty) == encode_recorded_fixture(fixture)
    assert FIXTURE_PATH.read_text(encoding="ascii") == encode_recorded_fixture(fixture)


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
        replay_world.close()

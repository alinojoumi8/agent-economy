from __future__ import annotations

import json
import sqlite3
import asyncio
import hashlib
from pathlib import Path

import pytest

from engine.payloads import (
    MAGIC, PayloadIntegrityError, configure_payload_reads,
    pack_payload, unpack_payload,
)


def test_payload_compression_is_lossless_and_substantial():
    body = json.dumps({"context": "A remembered experience. " * 5000,
                       "unicode": "\u00e9\u2764\U0001f600", "spacing": "  \n"}, ensure_ascii=False)
    encoded = pack_payload(body)
    assert isinstance(encoded, bytes)
    assert len(encoded) < len(body.encode("utf-8")) // 10
    assert unpack_payload(encoded) == body
    assert pack_payload("{}") == "{}"
    assert pack_payload(None) is None
    assert unpack_payload(b"unrelated binary data") == b"unrelated binary data"


@pytest.mark.parametrize("corrupt", [
    lambda value: value[:-1],
    lambda value: value + b"extra data",
    lambda value: value[:len(MAGIC)] + b"\xff" + value[len(MAGIC) + 1:],
    lambda value: value[:len(MAGIC) + 1] + b"\xff" * 8 + value[len(MAGIC) + 9:],
    lambda value: value[:len(MAGIC) + 9] + b"\0" * 32 + value[len(MAGIC) + 41:],
])
def test_corrupt_payload_fails_closed(corrupt):
    with pytest.raises(PayloadIntegrityError):
        unpack_payload(corrupt(pack_payload("memory " * 1000)))


def test_decoding_preserves_sqlite_rows_aliases_and_plain_legacy_records():
    connection = sqlite3.connect(":memory:")
    configure_payload_reads(connection)
    try:
        connection.execute("CREATE TABLE calls (request_json TEXT)")
        body = json.dumps({"context": "original history " * 1000})
        connection.executemany("INSERT INTO calls VALUES (?)", [(body,), (pack_payload(body),)])
        rows = connection.execute("SELECT request_json AS aliased FROM calls").fetchall()
        assert all(isinstance(row, sqlite3.Row) for row in rows)
        assert [row["aliased"] for row in rows] == [body, body]
    finally:
        connection.close()


def test_compressed_world_replays_exactly_with_memory_intact(tmp_path):
    from run import open_run, replay_headless
    from world.replay_verify import verify_replay
    from .test_checkpoint_retention import _config
    config = _config(tmp_path)
    config["storage_policy"] = {"min_free_bytes": 0}
    store, world, run_id = open_run(config, None, None, data_dir=tmp_path)
    source = Path(store.path)
    try:
        asyncio.run(world.step())
        memories = [tuple(row) for row in store.query("SELECT * FROM memories ORDER BY id")]
    finally:
        world.close()
    with sqlite3.connect(source) as raw:
        assert raw.execute("SELECT COUNT(*) FROM llm_calls WHERE typeof(request_json)='blob'").fetchone()[0] > 0
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    replay_store, replay_world, _ = open_run({}, None, run_id, data_dir=tmp_path)
    try:
        asyncio.run(replay_headless(replay_world, 1))
        proof = verify_replay(source, replay_store.path)
        assert proof["exact"], proof["differences"]
        assert memories == [tuple(row) for row in replay_store.query("SELECT * FROM memories ORDER BY id")]
    finally:
        replay_world.close()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest

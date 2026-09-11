"""Exact legacy bytes, bounded resources and cleanup for replay verification."""
import json
import sqlite3

import pytest

from world.replay_storage import (
    EventReferences, ReplayStorage, ReplayVerificationLimits, ReplayResourceLimitError,
)
from world.replay_verify import canonical_state_receipt, verify_replay_connections


def small_database(run_id="source", *, reordered=False):
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript("""
        CREATE TABLE run_meta(id INTEGER PRIMARY KEY,run_id TEXT,tick INTEGER,config_json TEXT);
        CREATE TABLE llm_calls(id INTEGER PRIMARY KEY,tick INTEGER,agent_id INTEGER,
            role TEXT,provider TEXT,model TEXT,purpose TEXT,cache_key TEXT,
            request_json TEXT,response_json TEXT,latency_ms REAL,created_at TEXT);
        CREATE TABLE memories(id INTEGER PRIMARY KEY,agent_id INTEGER,tick INTEGER,text TEXT);
        CREATE TABLE events(id INTEGER PRIMARY KEY,tick INTEGER,kind TEXT,payload_json TEXT,
            phase TEXT,subject_type TEXT,subject_id INTEGER,importance REAL);
        CREATE TABLE observations(id INTEGER PRIMARY KEY,amount INTEGER,measure REAL,raw BLOB);
    """)
    connection.execute("INSERT INTO run_meta VALUES (1,?,2,'{}')", (run_id,))
    for index, message in enumerate(("héllo", "世界"), 1):
        identifier = 100 - index if reordered else index
        connection.execute("INSERT INTO llm_calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (identifier, index, index, "citizen", "scripted", "native", "decision",
             "key:" + str(index), json.dumps({"message": message, "nested": [None, True]}),
             '{"actions":[]}', 0.25 * index, "ignored wall time"))
    texts = ["same", "z\u0000", "é", "same", "😀"]
    if reordered:
        texts.reverse()
    for index, text in enumerate(texts, 1):
        connection.execute("INSERT INTO memories VALUES (?,1,1,?)", (index, text))
    first, second = (31, 47) if reordered else (1, 2)
    connection.execute("INSERT INTO events VALUES (?,1,'note',?,'EXECUTION','agent',1,1.5)",
        (first, json.dumps({"text": "evidence", "none": None})))
    connection.execute("INSERT INTO events VALUES (?,2,'follow',?,'EXECUTION','agent',1,2.0)",
        (second, json.dumps({"event_id": first, "source_event_ids": [first, first]})))
    connection.execute("INSERT INTO observations VALUES (1,-3,-0.0,?)", (b"\0\xff",))
    connection.commit()
    return connection


# Captured with the original unbounded comparator before this change.
REFERENCE_STATE_HASH = "4c105aaf76accde4e117785b2b121bc414889ac6097d02102eff26ca0d8a36a2"


def test_exact_hashes_survive_bounded_cache_and_disk_sort(tmp_path):
    source, replay = small_database(), small_database("replay", reordered=True)
    limits = ReplayVerificationLimits(max_cache_bytes=128, max_cache_entries=2,
                                      max_record_bytes=8192, max_scratch_bytes=1024**2)
    stats = {}
    try:
        proof = verify_replay_connections(source, replay, limits=limits,
                                           scratch_dir=tmp_path, stats=stats)
        assert proof["exact"] and proof["differences"] == []
        assert proof["source_hash"] == proof["replay_hash"] == REFERENCE_STATE_HASH
        assert canonical_state_receipt(source, limits=limits,
            scratch_dir=tmp_path)["sha256"] == REFERENCE_STATE_HASH
        assert stats["peak_cache_bytes"] <= 128
        assert stats["peak_cache_entries"] <= 2
        assert 0 < stats["peak_scratch_bytes"] <= 1024**2
        assert list(tmp_path.iterdir()) == []
    finally:
        source.close()
        replay.close()


def test_identical_dangling_backward_references_still_fail(tmp_path):
    source, replay = small_database(), small_database("replay")
    try:
        for connection in (source, replay):
            connection.execute("UPDATE events SET payload_json=? WHERE id=2",
                               ('{"event_id":999999999999999999999999}',))
        proof = verify_replay_connections(source, replay, scratch_dir=tmp_path)
        assert not proof["exact"] and proof["differences"] == ["events"]
        assert proof["source_hash"] == proof["replay_hash"]
        assert list(tmp_path.iterdir()) == []
    finally:
        source.close()
        replay.close()


def test_blob_sort_preserves_byte_order_and_duplicates(tmp_path):
    values = [b"x\0", b"x", b"\xff", b"x", b"\0", "é".encode()]
    with ReplayStorage(scratch_dir=tmp_path) as storage:
        for ordinal, value in enumerate(values):
            storage.add_sorted(value, ordinal)
        assert list(storage.sorted_records()) == sorted(values)
        plan = storage.connection.execute(
            "EXPLAIN QUERY PLAN SELECT value FROM ordered_records ORDER BY value,ordinal"
        ).fetchall()
        assert not any("TEMP B-TREE" in str(row) for row in plan)
    assert list(tmp_path.iterdir()) == []


def test_oversized_source_row_restores_caller_limit_and_cleans_scratch(tmp_path):
    source = small_database()
    previous = source.getlimit(sqlite3.SQLITE_LIMIT_LENGTH)
    source.execute("UPDATE llm_calls SET request_json=?", ('{"large":"' + "x" * 8192 + '"}',))
    try:
        with pytest.raises(ReplayResourceLimitError, match="row is too large"):
            canonical_state_receipt(source, scratch_dir=tmp_path,
                limits=ReplayVerificationLimits(max_record_bytes=2048))
        assert source.getlimit(sqlite3.SQLITE_LIMIT_LENGTH) == previous
        assert source.execute("SELECT length(request_json) FROM llm_calls LIMIT 1").fetchone()[0] > 8192
        assert list(tmp_path.iterdir()) == []
    finally:
        source.close()


def test_nested_reference_expansion_has_a_record_limit(tmp_path):
    source = small_database()
    source.execute("UPDATE events SET payload_json=? WHERE id=1",
                   (json.dumps({"text": "x" * 700}),))
    source.execute("UPDATE events SET payload_json=? WHERE id=2",
                   (json.dumps({"source_event_ids": [1] * 8}),))
    try:
        with pytest.raises(ReplayResourceLimitError, match="record is too large"):
            canonical_state_receipt(source, scratch_dir=tmp_path,
                limits=ReplayVerificationLimits(max_record_bytes=2048))
        assert list(tmp_path.iterdir()) == []
    finally:
        source.close()


def test_repeated_cached_reference_is_limited_before_decoding(tmp_path, monkeypatch):
    with ReplayStorage(scratch_dir=tmp_path,
                       limits=ReplayVerificationLimits(max_record_bytes=2048)) as storage:
        references = EventReferences(storage)
        references[1] = {"text": "x" * 1200}
        storage.begin_record()
        assert references[1]["text"] == "x" * 1200

        def unexpected_decode(_value):
            raise AssertionError("second expanded object must not be allocated")

        monkeypatch.setattr("world.replay_storage.json.loads", unexpected_decode)
        with pytest.raises(ReplayResourceLimitError, match="expanded replay reference"):
            references[1]
    assert list(tmp_path.iterdir()) == []


def test_scratch_limit_returns_no_partial_proof(tmp_path):
    source = small_database()
    for index in range(10, 35):
        source.execute("INSERT INTO memories VALUES (?,1,1,?)",
                       (index, str(index) + "x" * 12000))
    stats = {}
    try:
        with pytest.raises(ReplayResourceLimitError, match="scratch"):
            canonical_state_receipt(source, scratch_dir=tmp_path, stats=stats,
                limits=ReplayVerificationLimits(max_scratch_bytes=64*1024))
        assert stats["peak_scratch_bytes"] <= 64*1024
        assert list(tmp_path.iterdir()) == []
    finally:
        source.close()


def test_resource_rejection_preserves_unrelated_files(tmp_path):
    keep = tmp_path / "keep.txt"
    keep.write_text("retained", encoding="utf-8")
    with pytest.raises(ReplayResourceLimitError, match="free-space reserve"):
        with ReplayStorage(scratch_dir=tmp_path,
                limits=ReplayVerificationLimits(min_free_bytes=2**62)):
            raise AssertionError("unreachable")
    assert keep.read_text(encoding="utf-8") == "retained"
    assert list(tmp_path.iterdir()) == [keep]


@pytest.mark.parametrize("changes", [
    {"max_record_bytes": True}, {"max_scratch_bytes": 1024},
    {"max_cache_entries": -1}, {"min_free_bytes": -1},
    {"max_elapsed_seconds": float("nan")}, {"max_elapsed_seconds": 0},
])
def test_invalid_limits_are_rejected(changes):
    with pytest.raises(ValueError):
        ReplayVerificationLimits(**changes)

"""Exact legacy bytes, bounded resources and cleanup for replay verification."""
import json
import sqlite3

import pytest

from world.replay_storage import (
    EventReferences, ReplayStorage, ReplayVerificationLimits, ReplayResourceLimitError,
)
from world.replay_verify import canonical_state_receipt, verify_replay_connections


@pytest.mark.parametrize("exact", [True, False])
def test_record_input_bounds_preserve_json_bytes(exact, tmp_path):
    from world.replay_verify import _canonical_value

    payload = {"text": "😀\u0000é", "values": [None, True, -0.0, 1e15, -1e-323],
               "rows": [{"n": n, "label": "example"} for n in range(100)]}
    raw = json.dumps(payload, ensure_ascii=False)
    with ReplayStorage(scratch_dir=tmp_path) as storage:
        storage.begin_record({"payload_json": raw})
        record = {"payload_json": _canonical_value("payload_json", raw, storage)}
        expected = json.dumps(record, sort_keys=exact, separators=(",", ":"),
                              ensure_ascii=not exact, allow_nan=not exact).encode("utf-8")
        assert storage.encode(record, exact=exact) == expected


def test_input_bound_accounts_for_unpacked_payload_before_encoding(tmp_path, monkeypatch):
    from world.replay_verify import _canonical_value

    unpacked = json.dumps({"text": "x" * 4096})
    monkeypatch.setattr("world.replay_verify.unpack_payload", lambda value: unpacked)
    with ReplayStorage(scratch_dir=tmp_path,
                       limits=ReplayVerificationLimits(max_record_bytes=2048)) as storage:
        storage.begin_record({"payload_json": b"small compressed payload"})
        value = _canonical_value("payload_json", b"small compressed payload", storage)
        with pytest.raises(ReplayResourceLimitError, match="record is too large"):
            storage.encode({"payload_json": value}, exact=True)


@pytest.mark.parametrize("stored,expected", [
    ('{"llm":{"institutional_role_purposes":true}}', True),
    ('{"llm":{"institutional_role_purposes":false}}', False),
    ('{}', None),
    (b'{"llm":{"institutional_role_purposes":true}}', None),
])
def test_snapshot_preserves_historical_routing_marker_parsing(stored, expected):
    from world.replay_verify import _VerificationSnapshot, _institutional_role_purpose_mode

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("CREATE TABLE run_meta(id INTEGER PRIMARY KEY,config_json TEXT)")
        connection.execute("INSERT INTO run_meta VALUES(1,?)", (stored,))
        assert _institutional_role_purpose_mode(_VerificationSnapshot(connection)) is expected
    finally:
        connection.close()


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


@pytest.mark.parametrize("exact", [True, False])
def test_record_encoding_preserves_json_bytes_at_size_boundary(tmp_path, exact):
    values = [
        {"z": [None, True, False, -0.0, 1e-300, 10**80],
         "a": "héllo\n\u0000世界😀", "nested": {"repeated": ["x"] * 30}},
        {"payload": "x" * 120},
        {"payload": "\\\"\n\u0000" * 30},
    ]
    for value in values:
        expected = json.dumps(value, sort_keys=exact, separators=(",", ":"),
                              ensure_ascii=not exact, allow_nan=not exact).encode("utf-8")
        with ReplayStorage(scratch_dir=tmp_path, limits=ReplayVerificationLimits(
                max_record_bytes=len(expected))) as storage:
            assert storage.encode(value, exact=exact) == expected
            assert storage.stats["largest_record_bytes"] == len(expected)
        with ReplayStorage(scratch_dir=tmp_path, limits=ReplayVerificationLimits(
                max_record_bytes=len(expected)-1)) as storage:
            with pytest.raises(ReplayResourceLimitError, match="record is too large"):
                storage.encode(value, exact=exact)


def test_record_encoding_preserves_invalid_value_rejection(tmp_path):
    circular = []
    circular.append(circular)
    with ReplayStorage(scratch_dir=tmp_path) as storage:
        assert storage.encode({"number": float("nan")}, exact=False) == b'{"number":NaN}'
        with pytest.raises(ValueError, match="Out of range"):
            storage.encode({"number": float("nan")}, exact=True)
        with pytest.raises(ValueError, match="Circular reference"):
            storage.encode(circular, exact=False)
        with pytest.raises(UnicodeEncodeError):
            storage.encode({"text": "\ud800"}, exact=True)


def test_record_encoding_does_not_bypass_elapsed_limit(tmp_path, monkeypatch):
    with ReplayStorage(scratch_dir=tmp_path,
            limits=ReplayVerificationLimits(max_elapsed_seconds=1)) as storage:
        monkeypatch.setattr("world.replay_storage.time.monotonic", lambda: storage.started + 2)
        with pytest.raises(ReplayResourceLimitError, match="time limit"):
            for _ in range(128):
                storage.encode({"message": "small"}, exact=True)


def test_reference_fragments_match_native_canonical_bytes_without_decoding(tmp_path, monkeypatch):
    from world.replay_encoding import CanonicalReference

    leaf = {"event": {"z": [None, True, -0.0, 1e-300, 10**80],
                      "a": "héllo\n\u0000世界😀"}}
    expected_value = {"duplicate": [leaf, leaf], "nested": {"leaf": leaf}, "end": "é"}
    expected = json.dumps(expected_value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    expected_ascii_size = len(json.dumps(expected_value, separators=(",", ":"),
                                        ensure_ascii=True).encode("ascii"))
    with ReplayStorage(scratch_dir=tmp_path) as storage:
        references = EventReferences(storage)
        references[1] = leaf
        storage.begin_record()
        fragment = references[1]
        value = {"duplicate": [fragment, fragment], "nested": {"leaf": fragment}, "end": "é"}
        monkeypatch.setattr(CanonicalReference, "decoded", lambda _self: pytest.fail("decoded canonical bytes"))
        assert storage.encode(value, exact=True) == expected
        assert storage.ascii_size(value) == expected_ascii_size
        assert storage.expanded_reference_bytes == len(json.dumps(leaf, separators=(",", ":")).encode("ascii"))
    assert not list(tmp_path.iterdir())


def test_call_fragments_survive_cache_eviction_without_recanonicalizing(tmp_path):
    from world.replay_storage import CallReferences
    from world.replay_verify import _canonical_value

    connection = small_database()
    canonicalized = []
    def canonicalize(column, value):
        canonicalized.append(column)
        return _canonical_value(column, value)

    try:
        with ReplayStorage(scratch_dir=tmp_path, limits=ReplayVerificationLimits(
                max_cache_entries=0, max_cache_bytes=0)) as storage:
            references = CallReferences(connection, ["tick", "agent_id", "purpose", "request_json"],
                                        canonicalize, storage)
            storage.begin_record()
            first = references[1]
            expected = storage.encode(first, exact=True)
            assert first["llm_call"]["purpose"] == "decision"
            assert first["llm_call"]["request_json"]["message"] == "héllo"
            storage.begin_record()
            assert storage.encode(references[1], exact=True) == expected
            assert canonicalized == ["tick", "agent_id", "purpose", "request_json"]
            assert not storage.cache
            assert storage.execute("SELECT COUNT(*) FROM call_refs").fetchone()[0] == 1
    finally:
        connection.close()


def test_fragment_record_limits_reject_combined_size_and_cycles(tmp_path):
    with ReplayStorage(scratch_dir=tmp_path, limits=ReplayVerificationLimits(
            max_record_bytes=2048)) as storage:
        references = EventReferences(storage)
        references[1] = {"text": "x" * 1200}
        storage.begin_record()
        fragment = references[1]
        with pytest.raises(ReplayResourceLimitError, match="record is too large"):
            storage.encode({"first": fragment, "second": fragment}, exact=True)
        cycle = [fragment]
        cycle.append(cycle)
        with pytest.raises(ValueError, match="Circular reference"):
            storage.encode(cycle, exact=True)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf'), '\ud800'])
def test_reference_index_defers_strict_value_rejection_until_comparison(tmp_path, value):
    import sqlite3
    from world.replay_storage import CallReferences

    leaf = {'payload': value, 'unicode': 'é'}
    expected = json.dumps(leaf, separators=(',', ':'), ensure_ascii=True).encode('ascii')
    connection = sqlite3.connect(':memory:')
    connection.row_factory = sqlite3.Row
    connection.execute('CREATE TABLE llm_calls(id INTEGER PRIMARY KEY,payload_json TEXT)')
    connection.execute('INSERT INTO llm_calls VALUES(1,?)', (json.dumps(leaf),))
    try:
        with ReplayStorage(scratch_dir=tmp_path) as storage:
            events = EventReferences(storage)
            events[1] = leaf
            calls = CallReferences(connection, ['payload_json'],
                                   lambda _column, raw: json.loads(raw), storage)
            for cache_round in range(2):
                storage.begin_record()
                restored = events[1]
                assert storage.encode(restored, exact=False) == expected
                with pytest.raises((ValueError, UnicodeEncodeError)):
                    storage.encode(restored, exact=True)
                storage.begin_record()
                call = calls[1]
                assert storage.encode(call, exact=False) == (
                    b'{"llm_call":{"payload_json":' + expected + b'}}')
                with pytest.raises((ValueError, UnicodeEncodeError)):
                    storage.encode(call, exact=True)
                storage.cache.clear()
                storage.cache_bytes = 0
    finally:
        connection.close()

"""Demand-built reference histories retain the old incremental identities."""
import json

from tests.test_bounded_replay import small_database
from world.replay_event_refs import LazyEventReferences, event_dependency_ids
from world.replay_storage import EventReferences, ReplayStorage
from world.replay_verify import (
    EVENT_REFERENCE_KEYS, EVENT_REFERENCE_LIST_KEYS, LLM_REFERENCE_KEYS,
    _canonical_value, _canonicalize_nested_event_references,
)


def _dependencies(row):
    return event_dependency_ids(_canonical_value("payload_json", row["payload_json"]),
                                EVENT_REFERENCE_KEYS, EVENT_REFERENCE_LIST_KEYS,
                                {"llm_call", *LLM_REFERENCE_KEYS})


def _reference(row, references):
    payload, _ = _canonicalize_nested_event_references(
        _canonical_value("payload_json", row["payload_json"]), references)
    return {"event": {
        "tick": int(row["tick"]), "kind": str(row["kind"]), "payload_json": payload,
        "phase": row["phase"], "subject_type": row["subject_type"],
        "subject_id": row["subject_id"], "importance": float(row["importance"]),
    }}


def test_lazy_references_match_incremental_history_including_forward_and_missing_ids(tmp_path):
    connection = small_database()
    try:
        for event_id, payload in [
            (3, {"event_id": 5}), (4, {"event_id": 4}),
            (5, {"source_event_ids": [1, 3, 1, 99999]}),
            (6, {"nested": [{"event_id": 5}]}),
        ]:
            connection.execute("INSERT INTO events VALUES (?,2,'follow',?,'EXECUTION','agent',1,1.0)",
                               (event_id, json.dumps(payload)))
        with ReplayStorage(scratch_dir=tmp_path) as legacy_store, ReplayStorage(scratch_dir=tmp_path) as lazy_store:
            legacy = EventReferences(legacy_store)
            for row in connection.execute("SELECT * FROM events ORDER BY id"):
                legacy_store.begin_record()
                legacy[row["id"]] = _reference(row, legacy)
            lazy = LazyEventReferences(connection, lazy_store, _dependencies, _reference)
            for key in [6, 3, 2, 1, 5, 4]:
                legacy_store.begin_record()
                lazy_store.begin_record()
                assert lazy[key] == legacy[key]
            assert list(lazy) == list(legacy)
            assert len(lazy) == len(legacy)
    finally:
        connection.close()
    assert not list(tmp_path.iterdir())


def test_unreferenced_history_is_not_copied_and_parent_expansion_is_charged(tmp_path):
    connection = small_database()
    try:
        connection.executemany("INSERT INTO events VALUES (?,2,'unused',?,'EXECUTION',NULL,NULL,1.0)",
                               ((key, json.dumps({"text": "x" * 1000})) for key in range(3, 1003)))
        with ReplayStorage(scratch_dir=tmp_path) as storage:
            lazy = LazyEventReferences(connection, storage, _dependencies, _reference)
            storage.begin_record()
            storage.expanded_reference_bytes = 17
            assert lazy[2]["event"]["kind"] == "follow"
            assert storage.execute("SELECT COUNT(*) FROM refs").fetchone()[0] == 2
            encoded_size = storage.execute("SELECT length(value) FROM refs WHERE id=2").fetchone()[0]
            assert storage.expanded_reference_bytes == 17 + encoded_size
            assert storage.execute("SELECT COUNT(*) FROM pending_event_refs").fetchone()[0] == 0
    finally:
        connection.close()

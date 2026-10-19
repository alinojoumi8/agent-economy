"""Digest reuse requires complete input equality, including negative lookups."""
import json

import pytest

from tests.test_bounded_replay import small_database
from world.replay_equivalence import _same_row
import world.replay_verify as verifier


def _event(connection, identifier, payload):
    connection.execute("INSERT INTO events VALUES (?,2,'report_generated',?,'NIGHT_CLOSE',NULL,NULL,1.0)",
                       (identifier, json.dumps(payload)))


def _compare_independent(source, replay, tmp_path, monkeypatch):
    stats = {}
    actual = verifier.verify_replay_connections(source, replay, scratch_dir=tmp_path, stats=stats)
    with monkeypatch.context() as patch:
        patch.setattr(verifier, 'identical_inputs', lambda *_args, **_kwargs: False)
        independent = verifier.verify_replay_connections(source, replay, scratch_dir=tmp_path)
    assert actual == independent
    assert not list(tmp_path.iterdir())
    return actual, stats['identical_canonical_inputs']


@pytest.mark.parametrize('case', [
    'equal', 'reordered_ids', 'changed_call', 'duplicate_memory', 'different_configuration',
    'operational_configuration', 'different_routing_representation', 'ignored_timestamp',
    'unused_report', 'referenced_report', 'newly_resolved_missing_event',
    'nested_missing_event', 'identical_invalid_reference', 'schema_difference',
])
def test_reuse_preserves_the_independent_canonical_proof(case, tmp_path, monkeypatch):
    source = small_database()
    replay = small_database('replay', reordered=case == 'reordered_ids')
    try:
        reuse = case in {'equal', 'operational_configuration', 'ignored_timestamp',
                         'unused_report', 'identical_invalid_reference'}
        exact = case not in {'changed_call', 'duplicate_memory', 'referenced_report',
                            'newly_resolved_missing_event', 'nested_missing_event', 'identical_invalid_reference'}
        if case == 'changed_call':
            replay.execute('UPDATE llm_calls SET request_json=? WHERE id=1', ('{"message":"different"}',))
        elif case == 'duplicate_memory':
            replay.execute("INSERT INTO memories VALUES(99,1,1,'same')")
        elif case == 'different_configuration':
            replay.execute('UPDATE run_meta SET config_json=?', ('{"future_semantic_option":true}',))
        elif case == 'operational_configuration':
            replay.execute('UPDATE run_meta SET config_json=?', (json.dumps({
                'replay_source_run_id': 'source', 'replay_source_path': '/input.db',
                'replay_source_tick': 2, 'checkpoint_dir': '/checkpoints', 'report_dir': '/reports'}),))
        elif case == 'different_routing_representation':
            raw = '{"llm":{"institutional_role_purposes":true}}'
            source.execute('UPDATE run_meta SET config_json=?', (raw,))
            replay.execute('UPDATE run_meta SET config_json=?', (raw.encode(),))
        elif case == 'ignored_timestamp':
            replay.execute("UPDATE llm_calls SET created_at='different clock'")
        elif case == 'unused_report':
            _event(source, 90, {'message': 'source only operational output'})
        elif case == 'referenced_report':
            _event(source, 90, {'message': 'source'})
            _event(replay, 90, {'message': 'different'})
            for connection in (source, replay):
                connection.execute('UPDATE events SET payload_json=? WHERE id=2', ('{"event_id":90}',))
        elif case == 'newly_resolved_missing_event':
            for connection in (source, replay):
                connection.execute('UPDATE events SET payload_json=? WHERE id=2', ('{"event_id":89}',))
            _event(replay, 89, {'message': 'new target'})
        elif case == 'nested_missing_event':
            for connection in (source, replay):
                _event(connection, 90, {'event_id': 89})
                connection.execute('UPDATE events SET payload_json=? WHERE id=2', ('{"event_id":90}',))
            _event(replay, 89, {'message': 'new nested target'})
        elif case == 'identical_invalid_reference':
            for connection in (source, replay):
                connection.execute('UPDATE events SET payload_json=? WHERE id=2', ('{"event_id":999}',))
        elif case == 'schema_difference':
            replay.execute('ALTER TABLE observations ADD COLUMN updated_at TEXT')
        proof, reused = _compare_independent(source, replay, tmp_path, monkeypatch)
        assert reused is reuse
        assert proof['exact'] is exact
    finally:
        source.close()
        replay.close()


@pytest.mark.parametrize('left,right,same', [
    ((1,), (1.0,), False), ((0.0,), (-0.0,), False),
    ((b'x',), ('x',), False), ((None, '\u0000', -0.0), (None, '\u0000', -0.0), True),
    (None, (None,), False), ((1,), (1, 1), False),
])
def test_raw_equality_preserves_types_bits_and_multiplicity(left, right, same):
    assert _same_row(left, right) is same

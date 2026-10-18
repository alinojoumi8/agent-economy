"""Replay evidence and resource sampling must not retain unbounded histories."""
from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import gc
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tracemalloc
from types import SimpleNamespace
import weakref

import pytest

from engine.store import Store
from llm.gateway import Gateway, _logical_replay_call
from llm.replay_attestation import ReplayCallJournal
from research.study_runner import _disk_bytes
from scripts.run_scale_validation import _MemorySampler


@pytest.fixture
def gateway_factory(tmp_path):
    gateways = []

    def create(records=()):
        directory = tmp_path / str(len(gateways))
        directory.mkdir()
        source = directory / "source.sqlite"
        conn = sqlite3.connect(source)
        conn.execute("CREATE TABLE llm_calls(id INTEGER PRIMARY KEY, purpose TEXT, request_json TEXT)")
        conn.executemany("INSERT INTO llm_calls VALUES (?,?,?)", records)
        conn.commit()
        conn.close()
        store = Store(str(directory / "replay.sqlite"))
        result = Gateway(store, {"replay": True, "replay_source_path": str(source)})
        gateways.append((result, store))
        return result

    try:
        yield create
    finally:
        for result, store in gateways:
            result.close()
            store.close()


@pytest.fixture
def gateway(gateway_factory):
    return gateway_factory()


def _digest(records):
    return hashlib.sha256(b"".join(value.encode("utf-8") + b"\n"
                                  for value in sorted(records))).hexdigest()


def test_consumed_payload_history_has_bounded_python_memory(gateway):
    tracemalloc.start()
    try:
        for index in range(96):
            gateway._replay_consumed_calls.append(
                (index + 1, f'{index:05d}:' + 'x' * (256 * 1024), "decision"))
        current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert len(gateway._replay_consumed_calls) == 96
    assert current < 2 * 1024**2
    assert peak < 4 * 1024**2


def test_execution_stats_preserve_canonical_digests_and_multiplicity(gateway_factory):
    records = [(1, "decision", '{"z":"é"}'), (2, "oracle", '{"z":"😀"}'),
               (3, "oracle_plan", '{"z":"中"}'), (4, None, '{"z":"a"}'),
               (5, "decision", '{"z":"é"}'), (6, "report_narrative", '{}')]
    gateway = gateway_factory(records)
    rows = gateway.replay_conn.execute("SELECT * FROM llm_calls ORDER BY id").fetchall()
    expected = [(int(row['id']), _logical_replay_call(row), str(row['purpose'] or ''))
                for row in rows if row['purpose'] != 'report_narrative']
    for row in reversed(expected):
        gateway._replay_consumed_calls.append(row)
    stats = gateway.replay_execution_stats()
    assert stats == gateway.replay_execution_stats()
    assert stats['schema_version'] == 1
    assert stats['source_nonoperational_calls'] == stats['consumed_source_calls'] == 5
    assert stats['source_logical_calls_sha256'] == stats['consumed_logical_calls_sha256'] == _digest([r[1] for r in expected])
    assert stats['source_purpose_counts'] == stats['consumed_purpose_counts'] == dict(Counter(r[2] for r in expected))
    oracle = [r[1] for r in expected if r[2] in {'oracle', 'oracle_plan'}]
    assert stats['oracle_source_calls'] == stats['oracle_consumed_calls'] == 2
    assert stats['oracle_source_calls_sha256'] == stats['oracle_consumed_calls_sha256'] == _digest(oracle)
    assert stats['all_nonoperational_calls_consumed_once']
    assert stats['all_oracle_calls_consumed_once']

    gateway._replay_consumed_calls.append(expected[0])
    gateway._replay_consumed_calls.append((99, 'unexpected', 'oracle'))
    stats = gateway.replay_execution_stats()
    assert stats['duplicate_source_consumptions'] == 1
    assert stats['unexpected_source_calls'] == 1
    assert stats['missing_source_calls'] == 0
    assert not stats['all_nonoperational_calls_consumed_once']
    assert not stats['all_oracle_calls_consumed_once']
    assert stats['source_logical_calls_sha256'] != stats['consumed_logical_calls_sha256']


def test_replay_admission_restores_only_new_consumption(gateway):
    first = (1, 'first', 'decision')
    gateway._replay_consumed_calls.append(first)
    for _ in range(2):
        with pytest.raises(ValueError, match='pause'):
            with gateway.replay_admission('memory_test'):
                gateway._replay_consumed_calls.append((2, 'second', 'oracle'))
                gateway._replay_exact_key_count += 1
                raise ValueError('pause')
        assert list(gateway._replay_consumed_calls) == [first]
        assert gateway._replay_exact_key_count == 0
    with gateway.replay_admission('memory_test'):
        gateway._replay_consumed_calls.append((2, 'second', 'oracle'))
    assert len(gateway._replay_consumed_calls) == 2


def test_final_verification_streams_large_source_and_consumed_payloads(gateway_factory):
    gateway = gateway_factory(
        (index + 1, "decision", json.dumps({"index": index, "text": "x" * (256 * 1024)}))
        for index in range(96))
    for row in gateway.replay_conn.execute("SELECT * FROM llm_calls ORDER BY id"):
        gateway._replay_consumed_calls.append((row["id"], _logical_replay_call(row), row["purpose"]))

    tracemalloc.start()
    try:
        stats = gateway.replay_execution_stats()
        current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert stats["all_nonoperational_calls_consumed_once"]
    assert stats["source_logical_calls_sha256"] == stats["consumed_logical_calls_sha256"]
    assert current < 2 * 1024**2
    assert peak < 4 * 1024**2


def test_empty_and_missing_call_receipts(gateway_factory):
    gateway = gateway_factory()
    stats = gateway.replay_execution_stats()
    assert stats["all_nonoperational_calls_consumed_once"]
    assert stats["all_oracle_calls_consumed_once"]
    assert stats["source_logical_calls_sha256"] == _digest([])

    gateway = gateway_factory([(1, "oracle", "{}")])
    stats = gateway.replay_execution_stats()
    assert stats["missing_source_calls"] == 1
    assert stats["unexpected_source_calls"] == stats["duplicate_source_consumptions"] == 0
    assert not stats["all_nonoperational_calls_consumed_once"]
    assert not stats["all_oracle_calls_consumed_once"]


def test_call_journal_failed_insert_is_atomic_and_close_cleans_private_files(gateway):
    journal = gateway._replay_consumed_calls
    first = (1, "first", "decision")
    journal.append(first)
    with pytest.raises(sqlite3.IntegrityError):
        journal.append((2, "invalid purpose", None))
    assert len(journal) == 1
    assert list(journal) == [first]
    journal.append((2, "second", "oracle"))
    assert len(journal) == 2
    scratch = list(Path(gateway.store.path).parent.glob(".replay-calls-*"))
    assert len(scratch) == 1
    if os.name == "posix":
        assert scratch[0].stat().st_mode & 0o077 == 0
    gateway.close()
    gateway.close()
    assert not scratch[0].exists()
    with pytest.raises(RuntimeError, match="closed"):
        journal.append((3, "late", "decision"))


def test_replay_evidence_supports_sequential_thread_handoff(gateway):
    gateway._replay_consumed_calls.append((1, "unexpected", "decision"))
    with ThreadPoolExecutor(max_workers=1) as executor:
        stats = executor.submit(gateway.replay_execution_stats).result()
        assert stats["unexpected_source_calls"] == 1
        executor.submit(gateway.close).result()
    assert not list(Path(gateway.store.path).parent.glob(".replay-calls-*"))


def test_abandoned_journal_releases_connection_before_removing_files(tmp_path):
    journal = ReplayCallJournal(str(tmp_path))
    journal.append((1, "private prompt", "decision"))
    reference = weakref.ref(journal)
    scratch = list(tmp_path.glob(".replay-calls-*"))
    del journal
    gc.collect()
    assert reference() is None
    assert len(scratch) == 1
    assert not scratch[0].exists()


def test_disk_budget_scan_survives_concurrent_replay_journal_cleanup(tmp_path, monkeypatch):
    artifact = tmp_path / "retained" / "source.bin"
    artifact.parent.mkdir()
    artifact.write_bytes(b"retained source")
    journal = ReplayCallJournal(tmp_path)
    try:
        journal.append((1, "private prompt", "decision"))
        scratch = next(tmp_path.glob(".replay-calls-*"))
        active_size = sum(path.stat().st_size for path in tmp_path.rglob("*") if path.is_file())
        assert _disk_bytes(tmp_path) == active_size > artifact.stat().st_size
        original_scandir = os.scandir
        retired = []

        def retire_before_descent(path):
            if not isinstance(path, int) and Path(path) == scratch and not retired:
                retired.append(scratch)
                journal.close()
            return original_scandir(path)

        monkeypatch.setattr(os, "scandir", retire_before_descent)
        assert _disk_bytes(tmp_path) == len(b"retained source")
        assert retired == [scratch]
        assert artifact.read_bytes() == b"retained source"
    finally:
        journal.close()


@pytest.mark.parametrize("error_type", [PermissionError, OSError])
def test_disk_budget_scan_does_not_hide_unreadable_directories(tmp_path, monkeypatch, error_type):
    blocked = tmp_path / "unreadable"
    blocked.mkdir()
    (blocked / "artifact.bin").write_bytes(b"must count")
    original_scandir = os.scandir

    def refuse_descent(path):
        if Path(path) == blocked:
            raise error_type("cannot inspect artifact directory")
        return original_scandir(path)

    monkeypatch.setattr(os, "scandir", refuse_descent)
    with pytest.raises(error_type, match="cannot inspect"):
        _disk_bytes(tmp_path)


def test_non_replay_gateway_does_not_require_a_store_path(gateway):
    class StoreWithoutPath:
        def __getattr__(self, name):
            if name == "path":
                raise AttributeError(name)
            return getattr(gateway.store, name)

    result = Gateway(StoreWithoutPath(), {})
    result.close()
    assert not list(Path(gateway.store.path).parent.glob(".replay-calls-*"))


def test_memory_store_replay_uses_system_temp_not_working_directory(gateway, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = Store(":memory:")
    result = Gateway(store, gateway.config)
    try:
        result._replay_consumed_calls.append((1, "private call", "decision"))
        assert result.replay_execution_stats()["unexpected_source_calls"] == 1
        assert not list(tmp_path.glob(".replay-calls-*"))
    finally:
        result.close()
        store.close()


def test_memory_sampler_preserves_receipt_extrema_without_sample_history(monkeypatch):
    sampler = _MemorySampler()
    rss = iter([10.125, 12.875, 9.25])
    available = iter([80.125, 78.375, 90.25])
    percent = iter([25.125, 30.875, 15.25])
    monkeypatch.setattr(sampler.process, 'memory_info', lambda: SimpleNamespace(rss=next(rss) * 1024**2))
    monkeypatch.setattr('scripts.run_scale_validation.psutil.virtual_memory',
                        lambda: SimpleNamespace(available=next(available) * 1024**3, percent=next(percent)))
    sampler.stage = 'source'
    sampler._take_sample()
    sampler.stage = 'replay'
    sampler._take_sample()
    sampler._take_sample()
    monkeypatch.setattr(sampler._thread, 'join', lambda **kwargs: None)
    receipt = sampler.stop()
    assert receipt == {
        'sample_interval_s': 0.05, 'samples': 3, 'peak_rss_mb': 12.88,
        'min_available_memory_gb': 78.38, 'max_system_memory_percent': 30.88,
        'by_stage': {
            'replay': {'samples': 2, 'peak_rss_mb': 12.88, 'min_available_memory_gb': 78.38, 'max_system_memory_percent': 30.88},
            'source': {'samples': 1, 'peak_rss_mb': 10.12, 'min_available_memory_gb': 80.12, 'max_system_memory_percent': 25.12},
        },
    }
    assert sampler.stop() == receipt


def test_memory_sampler_retention_does_not_grow_per_sample(monkeypatch):
    sampler = _MemorySampler()
    monkeypatch.setattr(sampler.process, 'memory_info', lambda: SimpleNamespace(rss=128 * 1024**2))
    monkeypatch.setattr('scripts.run_scale_validation.psutil.virtual_memory',
                        lambda: SimpleNamespace(available=80 * 1024**3, percent=25.0))
    monkeypatch.setattr(sampler._thread, 'join', lambda **kwargs: None)
    tracemalloc.start()
    try:
        for _ in range(20000):
            sampler._take_sample()
        current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert sampler.stop()['samples'] == 20000
    assert current < 256 * 1024
    assert peak < 512 * 1024

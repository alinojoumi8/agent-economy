"""Incremental roots preserve exact images, state evidence and failure boundaries."""
import json
import sqlite3
from pathlib import Path

import pytest

from engine.incremental_checkpoint import (
    IncrementalCheckpointError, read_incremental, restore_incremental,
    save_incremental,
)
from engine.store import Store
from world.loop import World


@pytest.fixture
def world(tmp_path):
    config = {
        'seed': 42, 'engine_semantics_version': 7,
        'population': {'size': 6, 'baseline_citizens_core': True},
        'banks': {'count': 2}, 'firms': {'count': 1, 'listed': 0},
        'outlets': [{'id': 10, 'name': 'North', 'slant': 'neutral'},
                    {'id': 20, 'name': 'South', 'slant': 'neutral'}],
        'llm': {'default_route': {'provider': 'scripted', 'model': 'scripted'}, 'routes': {}},
        'checkpoint_every': 0,
    }
    store = Store(str(tmp_path / 'world.db'))
    store.init_run_meta('chunk-test', 42, config)
    instance = World(store, config)
    instance.initialize()
    yield instance
    store.close()


def test_base_changes_and_same_tick_restore_exact(world, tmp_path):
    first = tmp_path / 'first.icp.json'
    initial = save_incremental(world.store.path, first)
    second = tmp_path / 'second.icp.json'
    same = save_incremental(world.store.path, second, base=first)
    assert same['new_chunks'] == 0
    assert same['root_sha256'] != initial['root_sha256']  # versioned delta root
    world.store.execute("CREATE TABLE capture_probe(value BLOB)")
    world.store.execute("INSERT INTO capture_probe VALUES (randomblob(2100000))")
    changed = save_incremental(world.store.path, second, base=second)
    assert changed['new_chunks'] > 0
    assert changed['evidence'] == initial['evidence'] | {
        'schema': changed['evidence']['schema']}
    restored = tmp_path / 'restored.db'
    receipt = restore_incremental(second, restored)
    assert receipt['root_sha256'] == changed['root_sha256']
    db = sqlite3.connect(restored.as_uri() + '?immutable=1', uri=True)
    assert db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
    assert db.execute('SELECT value FROM capture_probe').fetchall() == [tuple(r) for r in world.store.query('SELECT value FROM capture_probe')]
    assert db.execute('SELECT prng_state FROM run_meta').fetchone()[0] == world.store.get_meta()['prng_state']
    db.close()
    with pytest.raises(IncrementalCheckpointError, match='already exists'):
        restore_incremental(second, restored)


def test_corrupt_reused_chunk_fails_capture_and_restore(world, tmp_path):
    descriptor = tmp_path / 'checkpoint.icp.json'
    save_incremental(world.store.path, descriptor)
    before = descriptor.read_bytes()
    _, chunks, archive, _ = read_incremental(descriptor)
    object_path = archive / (chunks[0][1] + ".pack")
    object_path.write_bytes(b'bad')
    with pytest.raises(IncrementalCheckpointError, match='checksum'):
        save_incremental(world.store.path, descriptor, base=descriptor)
    assert descriptor.read_bytes() == before
    with pytest.raises(IncrementalCheckpointError, match='checksum'):
        restore_incremental(descriptor, tmp_path / 'restored.db')
    assert not (tmp_path / 'restored.db').exists()


def test_failed_publication_preserves_old_descriptor(world, tmp_path, monkeypatch):
    import engine.incremental_checkpoint as module
    descriptor = tmp_path / 'checkpoint.icp.json'
    save_incremental(world.store.path, descriptor)
    before = descriptor.read_bytes()
    def fail(*args):
        raise OSError('publication interrupted')
    monkeypatch.setattr(module.os, 'replace', fail)
    with pytest.raises(OSError, match='publication interrupted'):
        save_incremental(world.store.path, descriptor, base=descriptor)
    assert descriptor.read_bytes() == before
    restore_incremental(descriptor, tmp_path / 'restored.db')


def test_root_tampering_and_path_traversal_refused(world, tmp_path):
    descriptor = tmp_path / 'checkpoint.icp.json'
    save_incremental(world.store.path, descriptor)
    declaration = json.loads(descriptor.read_text())
    declaration['root_sha256'] = '../escape'
    descriptor.write_text(json.dumps(declaration))
    with pytest.raises(IncrementalCheckpointError, match='digest'):
        read_incremental(descriptor)


def test_world_retains_dependencies_and_pinned_roots(world, tmp_path):
    from engine.checkpoint_retention import pin_checkpoint, unpin_checkpoint
    from engine.incremental_checkpoint import prune_incremental
    world.config.update(checkpoint_dir=str(tmp_path / 'checkpoints'), checkpoint_keep_last=2,
                        checkpoint_format='incremental-v2')
    world.checkpoint_format = 'incremental-v2'
    first = Path(world.checkpoint(1))
    pin = pin_checkpoint(first, 'independent branch origin')
    second = Path(world.checkpoint(2))
    third = Path(world.checkpoint(3))
    fourth = Path(world.checkpoint(4))
    assert first.exists() and pin.exists()
    assert not second.exists()
    assert third.exists() and fourth.exists()
    for index, source in enumerate([first, third, fourth]):
        restore_incremental(source, tmp_path / f'kept{index}.db')
    assert world.checkpoint(1) is None  # pinned slot cannot be replaced
    unpin_checkpoint(first)
    result = prune_incremental(first.parent, discard=[first])
    assert str(first) in result['removed']
    restore_incremental(fourth, tmp_path / 'after-gc.db')
    assert {r['tick'] for r in world.store.query('SELECT tick FROM checkpoints')} >= {3, 4}


def test_world_same_tick_and_storage_budget(world, tmp_path):
    from engine.storage_policy import StorageBudgetExceeded
    world.config.update(checkpoint_dir=str(tmp_path / 'checkpoints'), checkpoint_keep_last=2,
                        checkpoint_format='incremental-v2')
    world.checkpoint_format = 'incremental-v2'
    first = Path(world.checkpoint(0))
    assert world.checkpoint(0) == str(first)
    assert len(world.store.query('SELECT * FROM checkpoints')) == 1
    before = first.read_bytes()
    with pytest.raises(StorageBudgetExceeded):
        save_incremental(world.store.path, first, base=first, max_archive_bytes=1)
    assert first.read_bytes() == before
    with pytest.raises(IncrementalCheckpointError, match='restore size limit'):
        restore_incremental(first, tmp_path / 'too-large.db', max_bytes=1)
    assert not (tmp_path / 'too-large.db').exists()


def test_v2_fork_materializes_verified_independent_db(world, tmp_path):
    from run import fork_run
    first = tmp_path / 'origin.icp.json'
    save_incremental(world.store.path, first)
    before = first.read_bytes()
    output = tmp_path / 'forks'
    child = fork_run(str(first), data_dir=output)
    db = Store(str(output / f'{child}.db'), read_only=True)
    try:
        assert db.get_meta()['parent_run_id'] == 'chunk-test'
        assert db.get_meta()['run_id'] == child
    finally:
        db.close()
    assert first.read_bytes() == before


def test_corrupt_delta_and_unknown_directory_prevent_gc(world, tmp_path):
    from engine.incremental_checkpoint import prune_incremental
    first, second = tmp_path / 'a.icp.json', tmp_path / 'b.icp.json'
    save_incremental(world.store.path, first)
    save_incremental(world.store.path, second, base=first)
    second.write_text('{}')
    with pytest.raises(IncrementalCheckpointError):
        prune_incremental(tmp_path, discard=[first])
    assert first.exists()


def test_v2_report_authenticates_artifacts_and_detects_corruption(world, tmp_path):
    from reports.supply_recovery import _checkpoint_evidence
    world.config.update(checkpoint_dir=str(tmp_path / 'checkpoints'), checkpoint_keep_last=2,
                        checkpoint_format='incremental-v2')
    world.checkpoint_format = 'incremental-v2'
    path = Path(world.checkpoint(0))
    passed, evidence = _checkpoint_evidence(world.store, 'chunk-test', world.config)
    assert passed and evidence['current_rows'][0]['manifest_valid']
    _, chunks, archive, _ = read_incremental(path)
    (archive / (chunks[0][1] + '.pack')).write_bytes(b'corrupted')
    passed, evidence = _checkpoint_evidence(world.store, 'chunk-test', world.config)
    assert not passed and not evidence['current_rows'][0]['manifest_valid']


def test_concurrent_archive_operation_refuses(world, tmp_path):
    from research.process_lock import process_lock, ProcessLockBusy
    first = tmp_path / 'first.icp.json'
    save_incremental(world.store.path, first)
    _, _, archive, _ = read_incremental(first)
    with process_lock(archive / '.lock'):
        with pytest.raises(ProcessLockBusy):
            save_incremental(world.store.path, first, base=first)

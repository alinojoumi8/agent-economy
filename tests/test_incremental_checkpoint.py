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
    world.config.update(checkpoint_dir=str(tmp_path / 'checkpoints'), checkpoint_keep_last=2,
                        checkpoint_format='incremental-v2')
    world.checkpoint_format = 'incremental-v2'
    first = Path(world.checkpoint(0))
    assert world.checkpoint(0) == str(first)
    assert len(world.store.query('SELECT * FROM checkpoints')) == 1
    before = first.read_bytes()
    receipt = save_incremental(world.store.path, first, base=first, max_archive_bytes=1)
    assert receipt['budget_exceeded']
    assert first.exists()
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


def test_archive_budget_preserves_legacy_soft_retention_contract(world, tmp_path):
    from engine.storage_policy import StoragePolicy
    world.config.update(checkpoint_dir=str(tmp_path / 'checkpoints'), checkpoint_format='incremental-v2')
    world.checkpoint_format = 'incremental-v2'
    world.storage_policy = StoragePolicy(checkpoint_keep_last=2, checkpoint_max_bytes=1,
                                         min_free_bytes=0)
    assert world.checkpoint(0) is not None


def test_reader_uses_disk_scratch_beside_archive(world, tmp_path):
    from engine.checkpoint_formats import checkpoint_database
    source = tmp_path / 'a.icp.json'
    save_incremental(world.store.path, source)
    with checkpoint_database(source) as restored:
        assert restored.parent.parent == source.parent


def test_collection_keeps_complete_immutable_base(world, tmp_path):
    from engine.incremental_checkpoint import prune_incremental
    world.store.execute('CREATE TABLE changed_blob(value)')
    world.store.execute('INSERT INTO changed_blob VALUES (randomblob(3100000))')
    first, second = tmp_path / 'a.icp.json', tmp_path / 'b.icp.json'
    save_incremental(world.store.path, first)
    base, chunks, archive, _ = read_incremental(first)
    base_packs = {e[1] for e in chunks}
    world.store.execute('UPDATE changed_blob SET value=randomblob(3100000)')
    world.store.set_meta(tick=1)
    save_incremental(world.store.path, second, base=first)
    prune_incremental(tmp_path, discard=[first])
    assert all((archive / (pack + '.pack')).exists() for pack in base_packs)


def test_same_tick_collection_does_not_accumulate_unreferenced_roots(world, tmp_path):
    world.config.update(checkpoint_dir=str(tmp_path / 'checkpoints'), checkpoint_format='incremental-v2',
                        checkpoint_keep_last=2)
    world.checkpoint_format = 'incremental-v2'
    for _ in range(4):
        assert world.checkpoint(0) is not None
    root = tmp_path / 'checkpoints/.checkpoint-v2'
    assert len(list(root.glob('*.root'))) <= 2


def test_retention_failure_preserves_successful_published_checkpoint(world, tmp_path):
    world.config.update(checkpoint_dir=str(tmp_path / 'checkpoints'), checkpoint_format='incremental-v2',
                        checkpoint_keep_last=2)
    world.checkpoint_format = 'incremental-v2'
    assert world.checkpoint(1) and world.checkpoint(2)
    unknown = tmp_path / 'checkpoints/unknown.icp.json'
    unknown.write_text('{}')
    third = world.checkpoint(3)
    assert third is not None
    assert unknown.exists()
    assert world.store.scalar("SELECT count(*) FROM events WHERE kind='checkpoint_prune_failed'") > 0


def test_compressed_output_allocation_is_bounded():
    import io
    import lz4.block
    from engine.incremental_checkpoint import _chunk, CHUNK_SIZE
    raw = b'x' * (CHUNK_SIZE * 4)
    compressed = lz4.block.compress(raw, store_size=False)
    forged = ['0' * 64, '1' * 64, 0, len(compressed), CHUNK_SIZE, 1]
    with pytest.raises(IncrementalCheckpointError, match='compressed'):
        _chunk(io.BytesIO(compressed), forged)


def test_raw_and_compressed_chunks_round_trip(world, tmp_path):
    from engine.incremental_checkpoint import CHUNK_SIZE
    world.store.execute('CREATE TABLE compression_probe(value)')
    world.store.execute('INSERT INTO compression_probe VALUES (randomblob(?))', (CHUNK_SIZE * 3,))
    world.store.execute('INSERT INTO compression_probe VALUES (zeroblob(?))', (CHUNK_SIZE * 3,))
    path = tmp_path / 'mixed.icp.json'
    save_incremental(world.store.path, path)
    _, entries, _, _ = read_incremental(path)
    assert {entry[5] for entry in entries} == {0, 1}
    target = tmp_path / 'mixed.db'
    restore_incremental(path, target)
    db = sqlite3.connect(target.as_uri() + '?immutable=1', uri=True)
    assert db.execute('SELECT value FROM compression_probe').fetchall() == [tuple(r) for r in world.store.query('SELECT value FROM compression_probe')]
    db.close()


def test_async_checkpoint_keeps_readers_and_event_loop_responsive(world, tmp_path, monkeypatch):
    import asyncio
    import time
    import engine.incremental_checkpoint as module
    world.config.update(checkpoint_dir=str(tmp_path / 'checkpoints'), checkpoint_format='incremental-v2')
    world.checkpoint_format = 'incremental-v2'
    original = module.save_incremental
    def delayed(*args, **kwargs):
        time.sleep(.08)
        return original(*args, **kwargs)
    monkeypatch.setattr(module, 'save_incremental', delayed)
    async def check():
        task = asyncio.create_task(world.checkpoint_async(0))
        reads = 0
        while not task.done():
            assert world.store.scalar('SELECT count(*) FROM agents') > 0
            reads += 1
            await asyncio.sleep(.005)
        assert await task is not None
        assert reads >= 5
    asyncio.run(check())


def test_parallel_native_integrity_failure_prevents_publication(world, tmp_path, monkeypatch):
    import engine.incremental_checkpoint as module
    monkeypatch.setattr(module, '_source_quick_check', lambda source: ['ok', 'corrupt second result'])
    target = tmp_path / 'failed.icp.json'
    with pytest.raises(IncrementalCheckpointError, match='integrity'):
        save_incremental(world.store.path, target)
    assert not target.exists()


def test_serial_and_parallel_native_evidence_agree(world, tmp_path):
    import engine.incremental_checkpoint as module
    from engine.checkpoint_image import logical_image
    with logical_image(world.store.path) as (db, _):
        assert module._evidence(db) == module._evidence(
            db, quick_check=lambda: module._source_quick_check(world.store.path))


def test_base_survives_when_every_current_chunk_is_repacked(world, tmp_path):
    import hashlib
    from blake3 import blake3
    import engine.incremental_checkpoint as module
    first, second = tmp_path / 'base.icp.json', tmp_path / 'repacked.icp.json'
    save_incremental(world.store.path, first)
    _, entries, archive, base_digest = read_incremental(first)
    base_packs = {entry[1] for entry in entries}
    payload = json.loads((archive / (base_digest + '.root')).read_bytes())
    # A valid complete overlay may store the same verified chunks in another
    # immutable pack. Base recoverability must not depend on accidental sharing.
    assert len(payload['packs']) == 1
    original = (archive / (payload['packs'][0] + '.pack')).read_bytes()
    alternate = original + b'unreferenced pack tail'
    alternate_digest = blake3(alternate).hexdigest()
    module._immutable(archive / (alternate_digest + '.pack'), alternate)
    payload['base'] = base_digest
    payload['packs'] = [alternate_digest]
    payload['changes'] = {str(i): entry for i, entry in enumerate(payload.pop('chunks'))}
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()
    digest = hashlib.sha256(encoded).hexdigest()
    module._immutable(archive / (digest + '.root'), encoded)
    module._publish(second, {'kind': module.KIND, 'version': 2, 'root_sha256': digest})
    module.prune_incremental(tmp_path, discard=[first])
    assert all((archive / (pack + '.pack')).exists() for pack in base_packs)
    restore_incremental(second, tmp_path / 'repacked.db')

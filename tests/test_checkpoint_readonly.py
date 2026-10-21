"""Scientific readers never create scratch or writer locks in source archives."""
import hashlib
import stat
from pathlib import Path

import pytest

from engine.checkpoint_formats import checkpoint_database
from engine.incremental_checkpoint import read_incremental, save_incremental
from tests.test_incremental_checkpoint import world


def _manifest(tree):
    return {str(p.relative_to(tree)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in tree.rglob('*') if p.is_file()}


@pytest.mark.parametrize('external_scratch', [False, True])
@pytest.mark.parametrize('lock_present', [False, True])
def test_materialization_preserves_readonly_archive(world, tmp_path, monkeypatch,
                                                   external_scratch, lock_present):
    import tempfile
    tree = tmp_path / 'scientific-source'
    tree.mkdir()
    descriptor = tree / 'checkpoint.icp.json'
    save_incremental(world.store.path, descriptor)
    if not lock_present:
        (tree / '.checkpoint-v2/.lock').unlink()
    scratch = tmp_path / 'private-scratch'
    scratch.mkdir()
    monkeypatch.setattr(tempfile, 'tempdir', str(scratch))
    before = _manifest(tree)
    modes = {p: stat.S_IMODE(p.stat().st_mode) for p in [tree, *tree.rglob('*')]}
    try:
        for p in modes:
            p.chmod(0o555 if p.is_dir() else 0o444)
        options = {'scratch_dir': scratch} if external_scratch else {}
        with checkpoint_database(descriptor, **options) as materialized:
            assert materialized.is_relative_to(scratch)
            assert materialized.is_file()
            assert _manifest(tree) == before
        assert _manifest(tree) == before
        assert not list(scratch.iterdir())
    finally:
        for p, mode in modes.items():
            p.chmod(mode)


def test_concurrent_pruning_rejects_reader_without_publishing(world, tmp_path, monkeypatch):
    import engine.incremental_checkpoint as module
    descriptor = tmp_path / 'checkpoint.icp.json'
    save_incremental(world.store.path, descriptor)
    _, chunks, archive, _ = read_incremental(descriptor)
    original = module._verify_root_objects
    def prune_after_verification(*args, **kwargs):
        original(*args, **kwargs)
        (archive / (chunks[0][1] + '.pack')).unlink()
    monkeypatch.setattr(module, '_verify_root_objects', prune_after_verification)
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    with pytest.raises((OSError, ValueError)):
        with checkpoint_database(descriptor, scratch_dir=scratch):
            pytest.fail('a pruned checkpoint must not be published')
    assert not list(scratch.iterdir())

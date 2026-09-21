"""Complete, non-writing pre-tick bundles for controlled validation.

Only copies are SQLite-opened. Publication is an atomic directory rename;
an incomplete staging directory is never a usable checkpoint.
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

from engine.inspection import inspection_snapshot, _stamp
from engine.checkpoint_manifest import _fsync_directory


ARTIFACTS = ('world', 'budget', 'passport', 'workspace')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_revision():
    root = Path(__file__).resolve().parents[1]
    def git(*args):
        try:
            return subprocess.check_output(['git', *args], cwd=root).decode().strip()
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError('checkpoint source revision unavailable') from exc
    files = git('ls-files').splitlines()
    hashes = {p: sha256(root / p) for p in files if (root / p).is_file()}
    return {'head': git('rev-parse', 'HEAD'), 'dirty': bool(git('status', '--porcelain', '--untracked-files=no')),
            'tracked_files_sha256': hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()}


def _stamps(paths):
    return {str(p) + suffix: _stamp(Path(str(p) + suffix))
            for p in paths.values() for suffix in ('', '-wal', '-journal')}


def snapshot_for_replay(paths, destination, *, expected_run_id, expected_tick,
                        runtime, revision=None):
    """Capture a common stable boundary, or fail without retry or source writes.

    The owner must hold its controller lock and call synchronously, before any
    await or world mutation. External writers are detected across the entire
    capture interval. Credentials in these private bundles must not be published.
    """
    if set(paths) != set(ARTIFACTS):
        raise ValueError('checkpoint requires all four explicit artifacts')
    paths = {k: Path(v).resolve(strict=True) for k, v in paths.items()}
    if len(set(paths.values())) != 4:
        raise ValueError('checkpoint artifacts must be distinct')
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('checkpoint destination already exists')
    if any(destination == p or destination in p.parents for p in paths.values()):
        raise ValueError('checkpoint destination overlaps source artifacts')
    before = _stamps(paths)
    revision = revision if revision is not None else source_revision()
    with ExitStack() as stack:
        copies = {k: stack.enter_context(inspection_snapshot(p)) for k, p in paths.items()}
        for name, db in copies.items():
            if [r[0] for r in db.execute('PRAGMA integrity_check')] != ['ok'] or db.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError(f'{name} checkpoint integrity failure')
        meta = dict(copies['world'].execute('SELECT * FROM run_meta').fetchone())
        if meta['run_id'] != expected_run_id or type(expected_tick) is not int or meta['tick'] != expected_tick:
            raise ValueError('checkpoint run/tick mismatch')
        if meta['active_tick'] is not None or meta['legacy_partial'] or meta['status'] not in {'paused', 'created'}:
            raise ValueError('checkpoint requires an inactive nonterminal boundary')
        if runtime.get('pause_reason') or runtime.get('running'):
            raise ValueError('checkpoint refuses running or attention-paused world')
        if not meta['prng_state'] or not meta['lifecycle_prng_state']:
            raise ValueError('checkpoint requires persisted random streams')
        persisted = json.loads(meta['prng_state'])
        if not isinstance(persisted, dict) or set(persisted) != {'engine', 'persona'}:
            raise ValueError('validation checkpoint requires split random streams')
        if (runtime['random']['engine'] != persisted['engine']
                or runtime['random']['persona'] != persisted['persona']
                or runtime['random']['lifecycle'] != json.loads(meta['lifecycle_prng_state'])):
            raise ValueError('runtime random streams differ from committed boundary')
        from research.provider_budget import ProviderBudget
        totals = ProviderBudget._totals(copies['budget'])
        if any(totals[k] for k in ('unresolved_calls', 'unknown_usage_calls', 'breached_calls')):
            raise ValueError('checkpoint budget has unresolved or breached reservations')
        destination.parent.mkdir(parents=True, exist_ok=True)
        stage = destination.parent / ('.checkpoint-' + uuid.uuid4().hex)
        stage.mkdir(mode=0o700)
        try:
            manifest = {'format': 'validation-pre-tick-v1', 'run_id': expected_run_id,
                        'tick': expected_tick, 'source_revision': revision, 'runtime': runtime,
                        'source_paths': {k: str(v) for k, v in paths.items()},
                        'config_sha256': hashlib.sha256(meta['config_json'].encode()).hexdigest(),
                        'budget_start': totals, 'files': {}}
            for name, db in copies.items():
                path = stage / (name + '.db')
                with path.open('xb') as output:
                    output.write(db.serialize())
                    output.flush()
                    os.fsync(output.fileno())
                manifest['files'][name] = {'path': path.name, 'sha256': sha256(path), 'size': path.stat().st_size}
            with (stage / 'manifest.json').open('x', encoding='utf-8') as output:
                json.dump(manifest, output, sort_keys=True, indent=2)
                output.flush()
                os.fsync(output.fileno())
            if before != _stamps(paths):
                raise ValueError('checkpoint source changed; no automatic retry')
            _fsync_directory(stage)
            stage.rename(destination)
            _fsync_directory(destination.parent)
            return {'path': str(destination), 'manifest_sha256': sha256(destination / 'manifest.json'),
                    'run_id': expected_run_id, 'tick': expected_tick}
        finally:
            if stage.exists():
                shutil.rmtree(stage)


def restore_replay_bundle(bundle, destination):
    """Verify and copy a bundle into a new disposable directory; never launch it.

    Stored config paths are provenance, not permission to open original stores.
    An offline consumer must bind recordings and auxiliary stores to its copies.
    """
    bundle, destination = Path(bundle).resolve(strict=True), Path(destination).resolve()
    if destination.exists():
        raise ValueError('restore destination must be new')
    manifest = json.loads((bundle / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('format') != 'validation-pre-tick-v1' or set(manifest['files']) != set(ARTIFACTS):
        raise ValueError('unsupported checkpoint manifest')
    for name, record in manifest['files'].items():
        if record['path'] != name + '.db' or sha256(bundle / record['path']) != record['sha256']:
            raise ValueError('checkpoint artifact hash mismatch')
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = destination.parent / ('.restore-' + uuid.uuid4().hex)
    try:
        # Copy only the allowlisted files, never a live sidecar or linked subtree.
        stage.mkdir(mode=0o700)
        for name, record in manifest['files'].items():
            data = (bundle / record['path']).read_bytes()
            if hashlib.sha256(data).hexdigest() != record['sha256']:
                raise ValueError('checkpoint changed during restore')
            with (stage / record['path']).open('xb') as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
        with (stage / 'manifest.json').open('x', encoding='utf-8') as output:
            json.dump(manifest, output, sort_keys=True, indent=2)
            output.flush()
            os.fsync(output.fileno())
        _fsync_directory(stage)
        stage.rename(destination)
        _fsync_directory(destination.parent)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return {name: destination / (name + '.db') for name in ARTIFACTS}

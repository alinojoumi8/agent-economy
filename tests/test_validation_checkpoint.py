"""Disposable checkpoint proofs; never operate on saved user runs."""
import asyncio
import json
from pathlib import Path
import socket
import sqlite3

import pytest
from fastapi import HTTPException

from engine.inspection import inspection_snapshot
from engine.replay_checkpoint import snapshot_for_replay, restore_replay_bundle
from engine.store import Store
from server.prepared import prepared_app
from tests.test_prepared_server import artifacts, logical
from tests.test_external_agent_gateway import _world, _connection
from world.loop import World
from world.replay_verify import verify_replay


def runtime(world):
    return json.loads(json.dumps({'running': False, 'pause_reason': None,
        'random': {'engine': world.engine_prng.getstate(), 'persona': world.persona_prng.getstate(),
                   'lifecycle': world.lifecycle_prng.getstate()}}))


def paths_of(artifacts):
    return dict(zip(('world','budget','passport','workspace'),
                    [artifacts[k] for k in ('existing_run_db','provider_budget_db','passport_db','operator_workspace_db')]))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    connect = socket.socket.connect
    def denied(sock, address):
        import sys
        fallback = getattr(socket, '_fallback_socketpair', None)
        if fallback is not None and sys._getframe(1).f_code is fallback.__code__:
            return connect(sock, address)
        pytest.fail('checkpoint test attempted external network')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr('engine.replay_checkpoint.source_revision', lambda: {'head':'fixture', 'dirty':False})


def test_complete_wal_checkpoint_restores_all_tables_and_random_state(artifacts, tmp_path):
    with prepared_app(**artifacts) as app:
        c = app.state.run_controller
        before = {k: logical(v) for k,v in paths_of(artifacts).items()}
        physical = {str(v)+s: Path(str(v)+s).read_bytes() if Path(str(v)+s).exists() else None
                    for v in paths_of(artifacts).values() for s in ('','-wal','-shm')}
        result = asyncio.run(c.snapshot_for_replay('external-test', 0))
        manifest = json.loads((Path(result['path'])/'manifest.json').read_text())
        copies = restore_replay_bundle(result['path'], tmp_path/'restored')
        assert {k: logical(v) for k,v in copies.items()} == before
        assert manifest['budget_start']['reported_tokens'] == 15
        assert manifest['budget_start']['usage_cost_nano_usd'] == 200
        assert manifest['runtime']['random'] == runtime(c.world)['random']
        with inspection_snapshot(copies['world']) as db:
            assert db.execute('select count(*) from external_actor_requests').fetchone()[0] == 1
            assert db.execute('pragma integrity_check').fetchone()[0] == 'ok'
            assert not db.execute('pragma foreign_key_check').fetchall()
        assert all((Path(p).read_bytes() if Path(p).exists() else None) == b for p,b in physical.items())
        assert {k:logical(v) for k,v in paths_of(artifacts).items()} == before
        assert not c.is_running() and c.store.tick == 0


@pytest.mark.parametrize('method', ['step','advance_one'])
def test_governed_paths_checkpoint_before_exactly_one_step(artifacts, monkeypatch, method):
    with prepared_app(**artifacts) as app:
        c = app.state.run_controller
        calls=[]
        async def one(*, entry_guard):
            bundle=Path(c.last_replay_checkpoint['path'])
            assert bundle.is_dir()
            with entry_guard:
                assert c._checkpoint_writer_held
                with inspection_snapshot(bundle/'world.db') as db:
                    assert db.execute('select tick from run_meta').fetchone()[0] == 0
            calls.append(1)
            c.store.set_meta(tick=1)
            c.store.commit()
            return {'tick':1}
        monkeypatch.setattr(c.world,'step',one)
        asyncio.run(c.step() if method=='step' else c.advance_one('external-test',0))
        assert calls == [1] and c.store.tick == 1


@pytest.mark.parametrize('method', ['step','advance_one'])
def test_checkpoint_failure_prevents_dispatch_and_preserves_source(artifacts, monkeypatch, method):
    with prepared_app(**artifacts) as app:
        c=app.state.run_controller
        before={k:logical(v) for k,v in paths_of(artifacts).items()}
        calls=[]
        def failed(*args,**kwargs):
            calls.append(1)
            raise OSError('disk full')
        monkeypatch.setattr('engine.replay_checkpoint.snapshot_for_replay', failed)
        async def forbidden():
            pytest.fail('dispatched without checkpoint')
        monkeypatch.setattr(c.world,'step',forbidden)
        with pytest.raises(HTTPException, match='validation_checkpoint_failed'):
            asyncio.run(c.step() if method=='step' else c.advance_one('external-test',0))
        assert calls == [1]
        assert {k:logical(v) for k,v in paths_of(artifacts).items()} == before


@pytest.mark.parametrize('run,tick', [('wrong',0),('external-test',1)])
def test_wrong_boundary_is_rejected(artifacts, run, tick):
    with prepared_app(**artifacts) as app:
        c=app.state.run_controller
        with pytest.raises(HTTPException):
            asyncio.run(c.snapshot_for_replay(run,tick))
        assert c.last_replay_checkpoint is None


def test_prepared_continuous_run_cannot_bypass_checkpoint(artifacts):
    with prepared_app(**artifacts) as app:
        c=app.state.run_controller
        with pytest.raises(HTTPException,match='prepared_validation_requires_bounded_step'):
            asyncio.run(c.start())
        assert c.task is None and c.store.tick == 0


def test_source_change_aborts_atomic_publication(artifacts, tmp_path, monkeypatch):
    import engine.replay_checkpoint as module
    with prepared_app(**artifacts) as app:
        c=app.state.run_controller
        original=module._stamps
        calls=[]
        def changed(paths):
            calls.append(1)
            result=original(paths)
            if len(calls)>1:
                result['synthetic-concurrent-writer']=True
            return result
        monkeypatch.setattr(module,'_stamps',changed)
        with pytest.raises(ValueError,match='source changed'):
            snapshot_for_replay(paths_of(artifacts),tmp_path/'out'/'rejected',
                expected_run_id='external-test',expected_tick=0,runtime=runtime(c.world))
        assert not list((tmp_path/'out').iterdir())


def test_random_state_drift_is_rejected_without_source_repair(artifacts):
    with prepared_app(**artifacts) as app:
        c=app.state.run_controller
        before=logical(c.store.path)
        c.world.engine_prng.random()
        with pytest.raises(HTTPException,match='validation_checkpoint_failed'):
            asyncio.run(c.snapshot_for_replay('external-test',0))
        assert logical(c.store.path)==before


def test_tampered_bundle_cannot_restore(artifacts,tmp_path):
    with prepared_app(**artifacts) as app:
        result=asyncio.run(app.state.run_controller.snapshot_for_replay('external-test',0))
    (Path(result['path'])/'budget.db').write_bytes(b'corrupt')
    with pytest.raises(ValueError,match='hash mismatch'):
        restore_replay_bundle(result['path'],tmp_path/'rejected')
    assert not (tmp_path/'rejected').exists()


def test_restored_checkpoint_replays_one_tick_with_queued_action(artifacts,tmp_path):
    root=tmp_path/'scripted';root.mkdir()
    world=_world(root,engine_semantics_version=20)
    created=_connection(world)
    service=world.runtime.external
    auth=service.authenticate(created['credential']['token'],rate_limit=False)
    turn=service.turn(auth)
    receipt=service.submit_action(auth, {'target_tick':turn['target_tick'],
        'action':{'type':'do_nothing'},'observed_projection_hash':turn['projection_hash'],
        'idempotency_key':'checkpoint-fixture'})
    world._save_prng_state();world.store.commit()
    paths=paths_of(artifacts);paths['world']=Path(world.store.path)
    before={k:logical(v) for k,v in paths.items()}
    result=snapshot_for_replay(paths,tmp_path/'bundle',expected_run_id='external-test',
        expected_tick=0,runtime=runtime(world))
    copies=restore_replay_bundle(result['path'],tmp_path/'copy')
    assert {k:logical(v) for k,v in copies.items()}==before
    with inspection_snapshot(copies['world']) as db:
        assert db.execute('select status from external_action_submissions where id=?',(receipt['submission_id'],)).fetchone()[0]=='queued'
    asyncio.run(world.step())  # scripted disposable source produces recordings only
    config=dict(world.config,replay_source_path=str(paths['world']))
    replay=World(Store(str(copies['world']),existing_only=True),config,replay=True)
    replay.restore_prng_state()
    try:
        asyncio.run(replay.step())
        assert replay.store.tick==world.store.tick==1
        proof=verify_replay(world.store.path,replay.store.path)
        assert proof['exact'],proof['differences']
        assert {k:logical(v) for k,v in paths.items() if k!='world'}=={k:v for k,v in before.items() if k!='world'}
    finally:
        replay.close();world.close()

@pytest.mark.parametrize('condition', ['attention','terminal','partial','uncommitted'])
def test_unsafe_boundary_never_clears_or_steps(artifacts, condition):
    with prepared_app(**artifacts) as app:
        c=app.state.run_controller
        if condition=='attention':
            c.world.last_pause_reason={'reason':'provider'}
        elif condition=='terminal':
            c.world.status='finished'
        elif condition=='partial':
            c.store.set_meta(active_tick=1);c.store.commit()
        else:
            c.store.conn.execute('BEGIN')
        before={k:logical(v) for k,v in paths_of(artifacts).items()}
        with pytest.raises(HTTPException):
            asyncio.run(c.step())
        assert c.store.tick==0 and c.last_replay_checkpoint is None
        assert {k:logical(v) for k,v in paths_of(artifacts).items()}==before
        if condition=='attention':
            assert c.world.last_pause_reason=={'reason':'provider'}
        c.store.conn.rollback()


def test_direct_api_snapshot_and_wrong_identity(artifacts):
    from fastapi.testclient import TestClient
    with prepared_app(**artifacts) as app:
        before={k:logical(v) for k,v in paths_of(artifacts).items()}
        with TestClient(app,client=('127.0.0.1',55000)) as client:
            bad=client.post('/api/run/snapshot-for-replay',json={'expected_run_id':'wrong','expected_tick':0})
            assert bad.status_code==409
            good=client.post('/api/run/snapshot-for-replay',json={'expected_run_id':'external-test','expected_tick':0})
            assert good.status_code==200,good.text
            assert good.json()['tick']==0
        assert {k:logical(v) for k,v in paths_of(artifacts).items()}==before


def test_missing_artifact_refuses_checkpoint(artifacts,tmp_path):
    with prepared_app(**artifacts) as app:
        c=app.state.run_controller
        c.replay_checkpoint_paths['budget']=tmp_path/'absent.db'
        with pytest.raises(HTTPException,match='validation_checkpoint_writer_unavailable'):
            asyncio.run(c.advance_one('external-test',0))
        assert c.store.tick==0
        assert not (tmp_path/'absent.db').exists()


def test_changed_server_source_refuses_advance(artifacts,monkeypatch):
    with prepared_app(**artifacts) as app:
        c=app.state.run_controller
        monkeypatch.setattr('engine.replay_checkpoint.source_revision',lambda:{'head':'different','dirty':False})
        with pytest.raises(HTTPException,match='validation_checkpoint_failed'):
            asyncio.run(c.advance_one('external-test',0))
        assert c.store.tick==0 and c.last_replay_checkpoint is None


@pytest.mark.parametrize('artifact', ['world','budget','passport','workspace'])
def test_external_write_after_capture_cannot_win_before_step(artifacts,monkeypatch,artifact):
    import engine.replay_checkpoint as module
    with prepared_app(**artifacts) as app:
        c=app.state.run_controller
        before={k:logical(v) for k,v in paths_of(artifacts).items()}
        original=module.snapshot_for_replay
        attempts=[]
        def capture_then_race(*args,**kwargs):
            result=original(*args,**kwargs)
            path=c.replay_checkpoint_paths[artifact]
            with sqlite3.connect(path,timeout=0) as writer:
                attempts.append(artifact)
                # An actual independent SQLite writer, after publication.
                writer.execute('BEGIN IMMEDIATE')
            return result
        monkeypatch.setattr(module,'snapshot_for_replay',capture_then_race)
        async def forbidden(**kwargs):
            pytest.fail('must refuse before dispatch after capture exception')
        monkeypatch.setattr(c.world,'step',forbidden)
        with pytest.raises(HTTPException,match='validation_checkpoint_failed'):
            asyncio.run(c.advance_one('external-test',0))
        assert attempts==[artifact] and c.store.tick==0
        assert not c._checkpoint_writer_held
        assert {k:logical(v) for k,v in paths_of(artifacts).items()}==before
        # All exclusions were released even on the failure path.
        for p in paths_of(artifacts).values():
            with sqlite3.connect(p,timeout=0) as writer:
                writer.execute('BEGIN IMMEDIATE');writer.rollback()


def test_world_entry_reads_boundary_while_exclusions_held(artifacts,tmp_path,monkeypatch):
    from server.controller import RunController
    import engine.replay_checkpoint as module
    root=tmp_path/'entry';root.mkdir()
    world=_world(root,engine_semantics_version=20)
    c=RunController(world)
    c.replay_checkpoint_paths=paths_of(artifacts)
    c.replay_checkpoint_paths['world']=Path(world.store.path)
    c.replay_checkpoint_root=tmp_path/'entry-checkpoints'
    c.replay_checkpoint_revision=module.source_revision()
    original=world.store.get_meta
    observed=[]
    def meta():
        if c._step_active:
            observed.append(c._checkpoint_writer_held)
        return original()
    monkeypatch.setattr(world.store,'get_meta',meta)
    try:
        asyncio.run(c.advance_one('external-test',0))
        assert observed[0] is True
        assert c.store.tick==1 and not c._checkpoint_writer_held
        assert logical(c.replay_checkpoint_paths['budget'])==logical(Path(c.last_replay_checkpoint['path'])/'budget.db')
    finally:
        world.close()

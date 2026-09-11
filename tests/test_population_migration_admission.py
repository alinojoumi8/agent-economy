"""Exercise unregistered schema 26 through the real runner in disposable copies.

Schema installation must preserve existing run semantics and canonical rows.
Public registration and the supported semantics ceiling remain unchanged.
"""
import asyncio
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil

import pytest

import engine.schema as schema
import engine.semantics as semantics
import engine.store as store_module
from engine.migrations import registry
from engine.migrations import v026_population_residence as draft
from engine.store import Store, open_read_only_connection
from research.export_bundle import export_bundle, validate_bundle
from research.hashing import HashContractError, verify_hash_contract
from world.loop import World
from world.replay_verify import verify_replay_connections

from .test_population_residence_history import contents
from .test_semantics20_civic_succession import civic_config


def stamp(path):
    return hashlib.sha256(path.read_bytes()).hexdigest(),path.stat().st_mtime_ns


def state(path):
    with closing(open_read_only_connection(path, require_closed=True)) as conn:
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {
            'rows': {table:[tuple(row) for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid')]
                     for table in tables},
            'schema': {row[0]:tuple(row[1:]) for row in conn.execute(
                "SELECT name,type,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name")},
            'meta':dict(conn.execute('SELECT * FROM run_meta').fetchone()),
        }


def install_draft(monkeypatch, migration=None, *, admit_semantics=False):
    assert 26 not in {item.version for item in registry.registered_migrations()}
    migration = migration or registry.Migration.create(26,draft.NAME,draft.SQL,verify=draft.verify)
    monkeypatch.setattr(registry,'_MIGRATIONS',registry.registered_migrations()+(migration,))
    monkeypatch.setattr(schema,'SCHEMA_VERSION',26)
    monkeypatch.setattr(store_module,'SCHEMA_VERSION',26)
    if admit_semantics:
        monkeypatch.setattr(semantics,'CURRENT_ENGINE_SEMANTICS_VERSION',21)
    return migration


@pytest.fixture
def source20(tmp_path):
    path = tmp_path/'original-schema25.db'
    config = civic_config()
    config.update(checkpoint_every=0,speed_delay_s=0)
    assert config['engine_semantics_version']==20
    assert config['llm']['default_route']['provider']=='scripted'
    store = Store(str(path))
    store.init_run_meta('original-schema25',int(config['seed']),config)
    world = World(store,config)
    try:
        world.initialize()
        asyncio.run(world.step())
        assert world.store.tick==1
        assert world.economy.ledger.reconcile()[0]
    finally:
        world.close()
    before = stamp(path)
    yield path,config
    assert stamp(path)==before
    assert not any(Path(str(path)+suffix).exists() for suffix in ('-wal','-shm','-journal'))


@pytest.mark.parametrize('failure',['late_sql','verification','history_receipt'])
def test_draft_migration_failure_rolls_back_existing_run_and_all_new_objects(source20,tmp_path,monkeypatch,failure):
    source,_ = source20
    target = tmp_path/'upgrade-failure.db'
    shutil.copy2(source,target)
    sql,verify = draft.SQL,draft.verify
    if failure=='late_sql':
        sql += '\nINVALID SQL;'
    elif failure=='verification':
        def verify(conn):
            draft.verify(conn)
            raise RuntimeError('injected population verification failure')
    else:
        with closing(Store(str(target))) as store:
            store.execute("CREATE TRIGGER refuse_population_migration BEFORE INSERT ON schema_migrations "
                          "WHEN NEW.version=26 BEGIN SELECT RAISE(ABORT,'injected history receipt failure'); END")
    before = state(target)
    migration = registry.Migration.create(26,draft.NAME,sql,verify=verify)
    install_draft(monkeypatch,migration)
    with pytest.raises(registry.MigrationError,match='failed applying migration v26'):
        Store(str(target),create=False)
    assert state(target)==before


def test_additive_upgrade_and_reopen_preserve_identity_accounts_history_and_stored_rules(source20,tmp_path,monkeypatch):
    source,config = source20
    target = tmp_path/'upgraded.db'
    shutil.copy2(source,target)
    before = state(target)
    migration = install_draft(monkeypatch)
    assert semantics.CURRENT_ENGINE_SEMANTICS_VERSION==20
    with closing(Store(str(target),create=False)) as store:
        assert store.scalar('SELECT schema_version FROM run_meta')==26
        assert json.loads(store.scalar('SELECT config_json FROM run_meta'))==config
        assert store.scalar('SELECT COUNT(*) FROM person_residence_events')==0
        assert store.scalar('SELECT COUNT(*) FROM population_resident_census')==0
        assert tuple(store.query_one(
            'SELECT version,name,checksum_sha256,source_schema,status FROM schema_migrations WHERE version=26'
        ))==(26,draft.NAME,migration.checksum_sha256,25,'applied')
        draft.verify(store.conn)
    after = state(target)
    assert {name:after['schema'][name] for name in before['schema']}==before['schema']
    assert {name:rows for name,rows in after['rows'].items() if name in before['rows'] and name not in {'run_meta','schema_migrations'}}=={
        name:rows for name,rows in before['rows'].items() if name not in {'run_meta','schema_migrations'}}
    assert after['meta']==dict(before['meta'],schema_version=26)
    assert after['rows']['schema_migrations'][:-1]==before['rows']['schema_migrations']
    assert all(not rows for name,rows in after['rows'].items() if name not in before['rows'])
    for _ in range(2):
        with closing(Store(str(target),create=False)) as store:
            assert registry.apply_migrations(store.conn,source_schema=26,target_schema=26)==()
        assert state(target)==after


@pytest.mark.parametrize('corruption',['checksum','unknown_history','missing_guard'])
def test_upgraded_history_or_missing_guard_is_rejected_without_repair(source20,tmp_path,monkeypatch,corruption):
    source,_ = source20
    target = tmp_path/'corrupt-upgrade.db'
    shutil.copy2(source,target)
    install_draft(monkeypatch)
    with closing(Store(str(target))) as store:
        if corruption=='checksum':
            store.execute("UPDATE schema_migrations SET checksum_sha256=? WHERE version=26",('0'*64,))
        elif corruption=='unknown_history':
            store.execute("INSERT INTO schema_migrations(version,name,checksum_sha256,source_schema,status) "
                          "VALUES(27,'unrecognized',?,26,'applied')",('0'*64,))
        else:
            store.execute('DROP TRIGGER person_residence_chain')
    before = state(target)
    expected = RuntimeError if corruption=='missing_guard' else registry.MigrationError
    with pytest.raises(expected):
        Store(str(target),create=False)
    assert state(target)==before


def test_semantics20_replay_into_schema26_preserves_recorded_behavior_and_v7_exports(source20,tmp_path,monkeypatch):
    source,config = source20
    install_draft(monkeypatch)
    replay_config = dict(config,replay_source_path=str(source),replay_source_closed=True)
    target = tmp_path/'old-semantics-replay.db'
    store = Store(str(target))
    store.init_run_meta('old-semantics-replay',int(config['seed']),replay_config)
    world = World(store,replay_config,replay=True)
    try:
        world.initialize()
        asyncio.run(world.step())
        assert world.engine_semantics_version==20 and world.population_scenario is None
        assert store.scalar('SELECT schema_version FROM run_meta')==26
        assert store.scalar('SELECT COUNT(*) FROM person_residence_events')==0
        assert store.scalar('SELECT COUNT(*) FROM population_resident_census')==0
        assert world.economy.ledger.reconcile()[0]
    finally:
        world.close()
    with closing(open_read_only_connection(source,require_closed=True)) as src, \
            closing(open_read_only_connection(target,require_closed=True)) as dst:
        proof = verify_replay_connections(src,dst)
        assert proof['exact'],proof['differences']
        for conn,name in ((src,'source-v7'),(dst,'replay-v7')):
            manifest = validate_bundle(export_bundle(conn,tmp_path/name),database=conn)
            assert manifest['contract_id']=='hash-contract-v7'


def test_fresh_schema26_world_registers_origins_restarts_and_replays_with_v8_exports(tmp_path,monkeypatch):
    install_draft(monkeypatch,admit_semantics=True)
    config = civic_config()
    config.update(engine_semantics_version=21,checkpoint_every=0,speed_delay_s=0)
    config.setdefault('population',{})['movement_schedule']=[]
    worlds = []

    def create(name,source=None):
        path = tmp_path/f'{name}.db'
        fresh = not path.exists()
        replay_config = dict(config)
        if source:
            replay_config.update(replay_source_path=str(source),replay_source_closed=True)
        store = Store(str(path),create=fresh)
        if fresh:
            store.init_run_meta(name,int(config['seed']),replay_config)
        try:
            world = World(store,replay_config,replay=source is not None)
            world.initialize()
            world.restore_prng_state()
        except BaseException:
            store.close()
            raise
        worlds.append(world)
        return world

    def close(world):
        worlds.remove(world)
        world.close()

    def run(name,source=None):
        world = create(name,source)
        assert world.store.scalar('SELECT schema_version FROM run_meta')==26
        people = world.store.scalar('SELECT COUNT(*) FROM agents')
        assert people>0 and world.store.scalar('SELECT COUNT(*) FROM person_residence_events')==people
        before = contents(world.store)
        world.initialize()
        assert contents(world.store)==before
        asyncio.run(world.step(pause_after_phase='NIGHT_CLOSE'))
        close(world)
        world = create(name,source)
        asyncio.run(world.step())
        assert world.store.tick==1
        assert world.economy.ledger.reconcile()[0]
        world.economy.households.check_invariants(1)
        path = Path(world.store.path)
        close(world)
        return path

    try:
        source = run('source')
        before = stamp(source)
        target = run('replay',source)
        with closing(open_read_only_connection(source,require_closed=True)) as src, \
                closing(open_read_only_connection(target,require_closed=True)) as dst:
            proof = verify_replay_connections(src,dst)
            assert proof['exact'],proof['differences']
            for conn,name in ((src,'source-v8'),(dst,'replay-v8')):
                manifest = validate_bundle(export_bundle(conn,tmp_path/name),database=conn)
                assert manifest['contract_id']=='hash-contract-v8'
        assert stamp(source)==before
        assert not any(Path(str(source)+suffix).exists() for suffix in ('-wal','-shm','-journal'))
    finally:
        for world in worlds:
            world.close()


@pytest.mark.parametrize(('semantics_version','corruption','difference'),[
    (20,'populated_population','population_resident_census'),
    (20,'unexpected_empty_table','unexpected_empty_table'),
    (20,'older_receipt','schema_migrations'),
    (21,'missing_required_table','population_resident_census'),
    (21,'current_receipt','schema_migrations'),
])
def test_replay_compatibility_keeps_population_data_unknown_tables_and_required_receipts_visible(
        tmp_path,monkeypatch,semantics_version,corruption,difference):
    install_draft(monkeypatch,admit_semantics=True)
    source,target = tmp_path/'reference.db',tmp_path/'changed.db'
    for path in (source,target):
        with closing(Store(str(path))) as store:
            store.init_run_meta('comparison',1,{'engine_semantics_version':semantics_version})
    before = stamp(source)
    with closing(Store(str(target),create=False)) as store:
        if corruption=='populated_population':
            store.execute('INSERT INTO population_resident_census VALUES(0,0,0,0,0,0,0,0,0,0,0)')
            with pytest.raises(HashContractError,match='populated population history requires hash-contract-v8'):
                verify_hash_contract(store)
        elif corruption=='unexpected_empty_table':
            store.execute('CREATE TABLE unexpected_empty_table(id INTEGER PRIMARY KEY)')
        elif corruption=='missing_required_table':
            store.execute('DROP TABLE population_resident_census')
        else:
            version = 25 if corruption=='older_receipt' else 26
            store.execute('UPDATE schema_migrations SET checksum_sha256=? WHERE version=?',('0'*64,version))
    with closing(open_read_only_connection(source,require_closed=True)) as src, \
            closing(open_read_only_connection(target,require_closed=True)) as dst:
        proof = verify_replay_connections(src,dst)
        assert not proof['exact'] and difference in proof['differences']
    assert stamp(source)==before

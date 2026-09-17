"""Explicit draft upgrades of provider-free initialization profiles.

These are prescribed initial conditions. Historical profile versions keep their
own semantics; the public version ceiling is patched only in disposable tests.
"""
import asyncio
from contextlib import closing
import hashlib
from pathlib import Path

import pytest

import engine.semantics as semantics
from engine.households import HouseholdError
from engine.migrations.v026_population_residence import SQL
from engine.store import Store, open_read_only_connection
from research.export_bundle import export_bundle, validate_bundle
from run_config import load_config
from world.loop import World
from world.replay_verify import verify_replay_connections

from .test_population_residence_history import contents


PROFILES = ['runs/life-course-rehearsal.yaml', 'runs/civic-rehearsal.yaml']


@pytest.mark.parametrize('profile', PROFILES, ids=['life-course','civic'])
def test_draft_profile_initialization_restarts_replays_and_exports(tmp_path, monkeypatch, profile):
    monkeypatch.setattr(semantics, 'CURRENT_ENGINE_SEMANTICS_VERSION', 21)
    config = load_config(profile)
    assert config['llm']['default_route']['provider'] == 'scripted'
    assert all(route['provider']=='scripted' for route in config['llm'].get('routes',{}).values())
    config['engine_semantics_version'] = 21
    config['checkpoint_every'],config['speed_delay_s'] = 0,0
    config.setdefault('lifecycle',{})['population_mode'] = 'drift'
    config.setdefault('population',{})['movement_schedule'] = []
    worlds = []

    def create(name, source=None):
        path = tmp_path/f'{name}.db'
        fresh = not path.exists()
        run_config = dict(config)
        if source:
            run_config.update(replay_source_path=str(source),replay_source_closed=True)
        store = Store(str(path),create=fresh)
        try:
            if fresh:
                store.conn.executescript(SQL)
                store.init_run_meta(name,int(config['seed']),run_config)
            world = World(store,run_config,replay=source is not None)
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

    def run(name, source=None):
        world = create(name,source)
        e,store = world.economy,world.store
        identities = [tuple(row) for row in store.query('SELECT id,checking_account_id,savings_account_id FROM agents ORDER BY id')]
        assert store.scalar('SELECT COUNT(*) FROM person_lifecycle') == len(identities)
        assert store.scalar('SELECT COUNT(*) FROM person_residence_events') == len(identities)
        e.households.check_invariants(0)
        assert e.ledger.reconcile()[0]
        for day in (1,2):
            asyncio.run(world.step(pause_after_phase='NIGHT_CLOSE'))
            close(world)
            world = create(name,source)
            asyncio.run(world.step())
            assert world.store.tick==day
            world.economy.households.check_invariants(day)
            assert world.economy.ledger.reconcile()[0]
        current = {row['id']:tuple(row) for row in world.store.query('SELECT id,checking_account_id,savings_account_id FROM agents ORDER BY id')}
        # Current wallets may change currency through valid internal migration.
        # The original identities and their personally owned accounts survive.
        assert all(row[0] in current for row in identities)
        for person,checking,savings in identities:
            for wallet in (checking,savings):
                if wallet is not None:
                    assert tuple(world.store.query_one('SELECT owner_type,owner_id FROM accounts WHERE id=?',(wallet,))) == ('agent',person)
        assert world.store.scalar("SELECT COUNT(*) FROM llm_calls WHERE provider<>'scripted'")==0
        path = Path(world.store.path)
        close(world)
        return path

    try:
        source = run('source')
        stamp = hashlib.sha256(source.read_bytes()).hexdigest(),source.stat().st_mtime_ns
        target = run('replay',source)
        with closing(open_read_only_connection(source,require_closed=True)) as src, \
                closing(open_read_only_connection(target,require_closed=True)) as dst:
            proof = verify_replay_connections(src,dst)
            assert proof['exact'],proof['differences']
            for database,directory in ((src,'source-export'),(dst,'replay-export')):
                manifest = validate_bundle(export_bundle(database,tmp_path/directory),database=database)
                assert manifest['contract_id']=='hash-contract-v8'
        assert (hashlib.sha256(source.read_bytes()).hexdigest(),source.stat().st_mtime_ns)==stamp
        assert not any(Path(str(source)+suffix).exists() for suffix in ('-wal','-shm','-journal'))
    finally:
        for world in worlds:
            world.close()


@pytest.mark.parametrize(('profile','fixture'), [
    ('runs/v2-behavioral-rehearsal.yaml','behavioral_fixture'),
    ('runs/v2-spec-closure-rehearsal.yaml','spec_closure_fixture'),
], ids=['legacy-startup','legacy-trade'])
def test_legacy_genesis_fixture_upgrade_is_refused_before_world_effects(tmp_path, monkeypatch, profile, fixture):
    monkeypatch.setattr(semantics, 'CURRENT_ENGINE_SEMANTICS_VERSION', 21)
    config = load_config(profile)
    assert config['engine_semantics_version'] < 15 and config[fixture]['enabled']
    assert config['llm']['default_route']['provider'] == 'scripted'
    config['engine_semantics_version'] = 21
    config.setdefault('lifecycle',{})['population_mode'] = 'drift'
    store = Store(str(tmp_path/'refused.db'))
    try:
        store.conn.executescript(SQL)
        store.init_run_meta('refused-upgrade',int(config['seed']),config)
        before = contents(store)
        # Preserve the pre-existing Semantics-15 identity contract. These
        # historical fixtures cannot rewrite an origin, age basis or prehistory
        # merely because an operator changes the requested semantics number.
        with pytest.raises(HouseholdError, match=fixture+' mutates historical genesis'):
            World(store,config)
        assert contents(store)==before
        assert store.scalar('SELECT COUNT(*) FROM agents')==0
        assert store.scalar('SELECT COUNT(*) FROM transactions')==0
    finally:
        store.close()

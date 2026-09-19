import asyncio
import json

import pytest

from engine.actions import ActionExecutor
from engine.frontier import snapshot_at
from run import open_run
from run_config import load_config
from server.projections.workspaces import build_world_workspace, _agent_regions_at
from world.replay_verify import verify_replay


def config(activation=0):
    cfg = load_config("runs/hermes-local.yaml")
    cfg["population"]["size"] = 8
    cfg["firms"].update(count=1, listed=0, target_headcount=0)
    cfg["communications"]["autonomous_scripted_enabled"] = False
    cfg["participant_mode"] = {"enabled": True}
    cfg["frontier"] = {"version": 1, "activation_tick": activation}
    return cfg


@pytest.fixture
def city(tmp_path):
    store, world, _ = open_run(config(), None, None, data_dir=tmp_path)
    ids = [r["id"] for r in store.query("SELECT id FROM agents WHERE kind='citizen' AND age>=18 ORDER BY id")]
    # Controlled unemployed adults for domain tests; replay uses unmodified genesis.
    for aid in ids:
        store.update("agents", aid, employer_id=None)
    yield store, world, world.economy.frontier, ActionExecutor(world.economy), ids
    world.close()


def act(executor, aid, tick, kind, **kwargs):
    result = executor.execute_action(tick, aid, {"type": kind, **kwargs})
    assert result["ok"], result
    return result


def test_activation_preserves_old_views_and_money_and_registers_arrivals(tmp_path):
    cfg = config(2)
    store, world, _ = open_run(cfg, None, None, data_dir=tmp_path)
    try:
        f = world.economy.frontier
        money = [tuple(r) for r in store.query("SELECT * FROM ledger_entries ORDER BY id")]
        rng = world.engine_prng.getstate()
        f.run_nightly(1)
        assert not store.scalar("SELECT COUNT(*) FROM regions")
        f.run_nightly(2)
        assert world.engine_prng.getstate() == rng
        assert [tuple(r) for r in store.query("SELECT * FROM ledger_entries ORDER BY id")] == money
        assert store.scalar("SELECT COUNT(*) FROM agents WHERE region_id IS NULL") == 0
        assert build_world_workspace(store, as_of_tick=1)["regions"] == []
        assert all(a["region_id"] is None for a in build_world_workspace(store, as_of_tick=1)["agents"])
        assert len(build_world_workspace(store, as_of_tick=2)["regions"]) == 1
        before = [tuple(r) for r in store.query("SELECT * FROM frontier_sites")]
        f.run_nightly(3)
        assert [tuple(r) for r in store.query("SELECT * FROM frontier_sites")] == before
        row = store.query_one("SELECT * FROM agents WHERE kind='citizen' LIMIT 1")
        values = dict(row); values.pop('id'); values.update(name='New Resident', arrived_tick=4, region_id=None)
        aid = store.insert('agents', **values)
        f.run_nightly(4)
        assert f.residence(aid)['region_id'] == 1
        assert world.economy.ledger.reconcile()[0]
    finally:
        world.close()


def test_explore_build_move_and_majority_charter_keep_history(city):
    store, world, f, ex, ids = city
    aid = ids[0]
    initial = snapshot_at(store, 0)
    assert 'resource' not in initial['sites'][1]
    wallet = store.scalar('SELECT checking_account_id FROM agents WHERE id=?', (aid,))
    before = world.economy.ledger.balance(wallet)
    task = act(ex, aid, 1, 'explore_site', site_id=2)
    assert world.economy.ledger.balance(wallet) == before - task['cost_cents']
    assert not ex.execute_action(1, aid, {'type':'apply_job', 'job_id':1})['ok']
    f.run_nightly(task['due_tick'])
    tick = task['due_tick'] + 1
    sid = act(ex, aid, tick, 'found_settlement', site_id=2, name='River Haven')['settlement_id']
    for worker in ids[:3]:
        act(ex, worker, tick+1, 'build_settlement', settlement_id=sid)
    f.run_nightly(tick+2)
    for resident in ids[:3]:
        move = act(ex, resident, tick+3, 'move_settlement', settlement_id=sid)
    f.run_nightly(move['due_tick'])
    vote_tick = move['due_tick']+1
    first = act(ex, ids[0], vote_tick, 'charter_region', settlement_id=sid)
    assert 'region_id' not in first
    second = act(ex, ids[1], vote_tick, 'charter_region', settlement_id=sid)
    assert second['region_id'] != 1
    assert store.scalar('SELECT COUNT(*) FROM currencies') == 0
    assert all(f.residence(a)['region_id'] == second['region_id'] for a in ids[:3])
    agents = [{'id': a, 'region_id': second['region_id']} for a in ids[:3]]
    assert set(_agent_regions_at(store, agents, vote_tick-1).values()) == {1}
    assert snapshot_at(store, 0) == initial
    assert len(build_world_workspace(store, as_of_tick=vote_tick-1)['regions']) == 1
    assert len(build_world_workspace(store, as_of_tick=vote_tick)['regions']) == 2
    assert world.economy.ledger.reconcile()[0]


def test_invalid_targets_duplicate_names_insufficient_funds_and_rollback(city, monkeypatch):
    store, world, f, ex, ids = city
    aid = ids[0]
    for action in ({'type':'explore_site','site_id':True}, {'type':'explore_site','site_id':999},
                   {'type':'found_settlement','site_id':2,'name':'Premature'},
                   {'type':'charter_region','settlement_id':1}):
        assert not ex.execute_action(1, aid, action)['ok']
    wallet = store.scalar('SELECT checking_account_id FROM agents WHERE id=?', (aid,))
    balance = world.economy.ledger.balance(wallet)
    original = f.publish
    monkeypatch.setattr(f, 'publish', lambda tick: (_ for _ in ()).throw(RuntimeError('injected failure')))
    assert not ex.execute_action(1, aid, {'type':'explore_site','site_id':2})['ok']
    assert not f.busy(aid)
    assert world.economy.ledger.balance(wallet) == balance
    monkeypatch.setattr(f, 'publish', original)
    task = act(ex, aid, 2, 'explore_site', site_id=2)
    f.run_nightly(task['due_tick'])
    for name in (' NORTHSTAR ', '<script>', 'x'):
        assert not ex.execute_action(6, aid, {'type':'found_settlement','site_id':2,'name':name})['ok']
    monkeypatch.setattr(world.economy.ledger, 'balance', lambda wallet: 0)
    assert 'insufficient' in ex.execute_action(6, aid, {'type':'found_settlement','site_id':2,'name':'Harbor'})['reason']


def test_participant_catalog_and_external_observation(city):
    store, world, f, ex, ids = city
    aid = ids[0]
    catalog = world.runtime.participant.action_catalog(aid)
    option = next(a for a in catalog if a['type'] == 'explore_site')
    normalized = world.runtime.participant.normalize_action(aid, option['action'])
    assert normalized['type'] == 'explore_site'
    observed = world.runtime.external.observe({'scopes':['world.read'], 'actor_id':aid})
    assert len(observed['frontier']['map']['sites']) == 9
    assert 'resource' not in observed['frontier']['map']['sites'][1]
    act(ex, aid, 1, **{'kind':'explore_site', 'site_id':2})
    assert {a['type'] for a in world.runtime.participant.action_catalog(aid)} == {'do_nothing'}


def test_restart_and_recorded_replay_of_paid_expedition(tmp_path):
    cfg = config()
    store, world, run_id = open_run(cfg, None, None, data_dir=tmp_path)
    try:
        aid = store.scalar("SELECT id FROM agents WHERE kind='citizen' AND age>=18 AND employer_id IS NULL ORDER BY id LIMIT 1")
        p = world.runtime.participant
        p.acquire(aid, 0, running=False)
        action = next(a['action'] for a in p.action_catalog(aid) if a['type']=='explore_site')
        p.queue_action(0, action, 'Explore a nearby site.', running=False)
        asyncio.run(world.step())
        task = dict(world.economy.frontier.busy(aid))
        sites = [tuple(r) for r in store.query('SELECT * FROM frontier_sites ORDER BY id')]
    finally:
        world.close()
    store, world, _ = open_run({}, run_id, None, data_dir=tmp_path)
    try:
        assert dict(world.economy.frontier.busy(aid)) == task
        assert [tuple(r) for r in store.query('SELECT * FROM frontier_sites ORDER BY id')] == sites
        for _ in range(task['due_tick'] - store.tick):
            asyncio.run(world.step())
        assert not world.economy.frontier.busy(aid)
        end_tick = store.tick
        assert world.economy.ledger.reconcile()[0]
    finally:
        world.close()
    replay_store, replay, replay_id = open_run({}, None, run_id, data_dir=tmp_path)
    try:
        for _ in range(end_tick):
            asyncio.run(replay.step())
    finally:
        replay.close()
    result = verify_replay(tmp_path/f'{run_id}.db', tmp_path/f'{replay_id}.db')
    assert result['differences'] == []


def test_opt_in_does_not_change_legacy_world(tmp_path):
    cfg = config(); cfg.pop('frontier')
    store, world, _ = open_run(cfg, None, None, data_dir=tmp_path)
    try:
        assert world.economy.frontier.context(1, 0) is None
        assert not store.scalar('SELECT COUNT(*) FROM frontier_sites')
        assert not store.scalar('SELECT COUNT(*) FROM regions')
    finally:
        world.close()


@pytest.mark.parametrize("tamper", ["frontier_sites", "frontier_history", "regions"])
def test_pre_frontier_storage_compares_without_hiding_new_state(tmp_path, monkeypatch, tamper):
    import hashlib
    import shutil
    from pathlib import Path
    from engine.migrations import registry
    from engine.store import Store

    migrations = registry._MIGRATIONS
    monkeypatch.setattr(registry, "_MIGRATIONS", tuple(m for m in migrations if m.version < 28))
    cfg = config()
    cfg.pop("frontier")
    source, world, _ = open_run(cfg, None, None, data_dir=tmp_path / "old")
    source.insert("regions", region_key="legacy", name="Legacy", currency_code="USD",
                  population_target=100, specialization_json="[]", x=0.5, y=0.5,
                  legal_ruleset="legacy")
    path = Path(source.path)
    world.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    replay_path = tmp_path / "upgraded.db"
    shutil.copy2(path, replay_path)
    monkeypatch.setattr(registry, "_MIGRATIONS", migrations)
    replay = Store(str(replay_path))
    try:
        assert verify_replay(path, replay_path)["exact"]
        if tamper == "frontier_sites":
            replay.execute("INSERT INTO frontier_sites(x,y,terrain,resource,capacity) VALUES(0,0,'plain','wood',1)")
        elif tamper == "frontier_history":
            replay.execute("INSERT INTO frontier_history(tick,data_json) VALUES(1,'{}')")
        else:
            # A changed date must remain visible even with frontier disabled.
            replay.execute("UPDATE regions SET created_tick=1")
        assert tamper in verify_replay(path, replay_path)["differences"]
    finally:
        replay.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before

"""Historical observer boundaries for disposable Semantics 21 worlds."""
import asyncio
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from communications.policy import Principal
from server.projections.city_society import build_city_households
from server.projections.living_agents import build_agent_journey, build_living_agents_workspace
from server.projections.population import PopulationProjectionError, population_at, resident_presence_at
from server.projections.snapshot import build_snapshot
from server.projections.workspaces import build_world_map_geography, build_world_workspace
from server.v2_api import install_v2_routes

from .test_population_scenario import proposal, scenario_world
from .test_population_residence_history import contents


@pytest.fixture
def returning_world(scenario_world):
    entries = [proposal(), {**proposal('back', tick=3, due=5, cause='return'), 'destination_region_id': 2}]
    world = scenario_world(entries, 'projection-source', config_overrides={'living_world': {'core_agents': 100}})
    for _ in range(6):
        asyncio.run(world.step())
    assert world.store.scalar('SELECT region_id FROM agents WHERE id=23') == 2
    return world


def test_departure_return_and_future_wallet_changes_preserve_earlier_views(returning_world):
    world = returning_world
    store = world.store
    before = contents(store)
    initial_region = json.loads(store.query_one('SELECT snapshot_json FROM population_movements ORDER BY id LIMIT 1')[0])['region_id']
    assert initial_region != 2
    for tick, region, state in [(0, initial_region, 'resident'), (1, initial_region, 'resident'),
                                (2, None, 'outside'), (4, None, 'outside'), (5, 2, 'resident'), (6, 2, 'resident')]:
        geography = build_world_map_geography(store, as_of_tick=tick)
        journey = build_agent_journey(store, agent_id=23, as_of_tick=tick)
        summary = build_snapshot(store, Principal('ordinary-dashboard'), as_of_tick=tick, domains=('summary',))['summary']
        workspace = build_world_workspace(store, as_of_tick=tick)
        assert geography['agent_regions'][23] == region
        assert journey['current_state']['modeled_residence']['state'] == state
        assert (journey['current_state']['region'] or {}).get('id') == region
        assert (23 in {row['id'] for row in workspace['agents']}) is (state == 'resident')
        assert sum(row['population'] for row in geography['regions']) == summary['resident_population']
        assert summary['agents_alive'] == summary['resident_population'] + summary['known_living_outside']
        if state == 'outside':
            assert all(journey['current_state'][field] is None for field in ('employment', 'compute', 'residence', 'workplace'))
            assert journey['runtime'] is None
        expected = {row['currency_code']: int(row['amount']) for row in store.query(
            "SELECT a.currency_code,SUM(l.delta_cents) amount FROM accounts a JOIN ledger_entries l ON l.account_id=a.id "
            "WHERE a.owner_type='agent' AND a.owner_id=23 AND a.kind IN ('checking','savings','fx') AND l.tick<=? "
            "GROUP BY a.currency_code", (tick,))}
        assert journey['current_state']['cash_by_currency'] == expected
        assert journey['current_state']['balance_cents'] is None
        assert all(ref['tick'] <= tick for ref in journey['evidence_refs'])
    assert contents(store) == before


def test_outside_households_and_history_remain_inspectable_without_local_work(returning_world):
    store = returning_world.store
    data = build_living_agents_workspace(store, as_of_tick=4,
        runtime=[dict(agent_id=23, state='thinking', active_calls=1, prompt='PRIVATE-CANARY')])
    person = next(row for row in data['agents'] if row['id'] == 23)
    assert person['modeled_residence']['state'] == 'outside' and person['runtime'] is None
    assert data['summary']['known_living_outside'] == 1
    assert data['summary']['resident_population'] + 1 == data['summary']['living_agents']
    assert not any(row['status'] == 'active' for row in data['projects']
                   if row['owner_agent_id'] == 23 and row['kind'] in {'employment', 'skill', 'residence', 'workplace', 'migration'})
    households = build_city_households(store, as_of_tick=4)
    household = next(row for row in households['items'] if any(m['agent_id'] == 23 for m in row['members']))
    member = next(m for m in household['members'] if m['agent_id'] == 23)
    assert member['modeled_residence']['state'] == 'outside'
    assert household['visible_population']['known_living_outside'] == 1
    assert 'PRIVATE-CANARY' not in json.dumps(data)


def test_later_foreign_wallet_cannot_relabel_or_change_retained_historical_cash(returning_world):
    world = returning_world
    earlier = build_agent_journey(world.store, agent_id=23, as_of_tick=4)['current_state']['cash_by_currency']
    assert 'EUR' not in earlier
    # Explicit ledger-funded fixture, not income attributed to the native model.
    world.economy.ledger.create_account('agent', 23, 'fx', currency_code='EUR', opening_cents=37, tick=6)
    now = build_agent_journey(world.store, agent_id=23, as_of_tick=6)['current_state']
    assert now['cash_by_currency']['EUR'] == 37
    assert now['balance_cents'] is None
    assert len(now['cash_by_currency']) >= 2
    assert build_agent_journey(world.store, agent_id=23, as_of_tick=4)['current_state']['cash_by_currency'] == earlier
    assert world.economy.ledger.reconcile()[0]


@pytest.mark.parametrize('mode', ['all', 'core', 'clusters'])
def test_map_routes_count_only_selected_day_residents_and_ignore_stale_runtime(returning_world, mode):
    world = returning_world
    gateway = SimpleNamespace(active_agent_status=lambda: [dict(agent_id=23, state='thinking', active_calls=1)])
    app = FastAPI()
    install_v2_routes(app, SimpleNamespace(store=world.store, config=world.config, economy=world.economy,
                                         gateway=gateway), SimpleNamespace(hosted_safe=False))
    try:
        with TestClient(app) as client:
            for tick in (1, 4, 5):
                response = client.get('/api/v2/world-map', params=dict(tick=tick, population=mode))
                assert response.status_code == 200, response.text
                data = response.json()['data']
                assert (23 in {person['id'] for person in data['agents']}) is (tick != 4)
                assert data['population_summary']['known_living_outside'] == int(tick == 4)
                assert data['population_summary']['total'] == sum(row['population'] for row in data['regions'])
                assert all(row.get('agent_id') != 23 for row in data['presence']) if tick == 4 else True
            person = client.get('/api/v2/agents/23/journey', params={'tick': 4})
            assert person.status_code == 200 and person.json()['data']['runtime'] is None
    finally:
        app.state.operator_workspace.close()


def test_presence_filter_precedes_private_office_aggregation(returning_world):
    store = returning_world.store
    office = store.query_one("SELECT id FROM places WHERE kind='licensing_office' ORDER BY id LIMIT 1")
    assert office is not None
    # Deliberate stale telemetry fixture: no claimed execution or permit attendance.
    for person in (23, 24):
        lease = store.scalar('SELECT id FROM occupancy_leases WHERE agent_id=? ORDER BY id LIMIT 1', (person,))
        assert lease is not None
        store.execute('DELETE FROM effective_presence WHERE tick=4 AND agent_id=?', (person,))
        store.insert('effective_presence', tick=4, slot='business', agent_id=person,
                     place_id=office['id'], source_type='fixture_stale', priority=1, lease_id=lease)
    before = contents(store)
    projection = resident_presence_at(store, 4, population_at(store, 4))
    assert not any(row['agent_id'] == 23 for row in projection)
    office_row = next(row for row in projection if row['place_id'] == office['id'] and row['slot'] == 'business')
    assert office_row['agent_id'] is None
    assert office_row['occupancy'] == store.scalar(
        'SELECT COUNT(*) FROM effective_presence WHERE tick=4 AND place_id=? AND slot=\'business\' AND agent_id<>23', (office['id'],))
    assert contents(store) == before


@pytest.mark.parametrize('corrupt', ['residence', 'return_terms', 'current_region'])
def test_invalid_population_evidence_refuses_a_plausible_historical_map(returning_world, corrupt):
    store = returning_world.store
    if corrupt == 'residence':
        event = store.scalar("SELECT event_id FROM person_residence_events WHERE agent_id=23 AND cause='departure'")
        store.execute("UPDATE events SET payload_json='{}' WHERE id=?", (event,))
    elif corrupt == 'return_terms':
        event = store.scalar("SELECT proposal_event_id FROM population_movements ORDER BY id DESC LIMIT 1")
        store.execute("UPDATE events SET payload_json='{}' WHERE id=?", (event,))
    else:
        store.execute('UPDATE agents SET region_id=1 WHERE id=23')
    before = contents(store)
    with pytest.raises(PopulationProjectionError):
        build_world_map_geography(store, as_of_tick=1)
    assert contents(store) == before


def test_population_projection_error_is_a_bounded_conflict(returning_world):
    world = returning_world
    world.store.execute("UPDATE events SET payload_json='{}' WHERE id=(SELECT event_id FROM person_residence_events WHERE agent_id=23 AND cause='return')")
    app = FastAPI()
    install_v2_routes(app, world, SimpleNamespace(hosted_safe=False))
    try:
        with TestClient(app) as client:
            response = client.get('/api/v2/world-map', params={'tick': 6})
            assert response.status_code == 409
            assert response.json() == {'detail': 'Population history is unavailable at the selected day.'}
    finally:
        app.state.operator_workspace.close()


def test_internal_migration_after_return_uses_both_histories_in_order(returning_world, monkeypatch):
    world = returning_world
    store = world.store
    # A controlled migration request isolates the real mover's journal. Economic
    # migration admission is covered separately; this is not an emergence claim.
    store.insert('migrations', agent_id=23, origin_region_id=2, destination_region_id=1,
                 requested_tick=6, status='pending', reason='projection_fixture')
    monkeypatch.setattr(world.economy.regions, '_agent_credit_exposure', lambda _aid: None)
    monkeypatch.setattr(world.economy.regions, '_qualified_migration_option', lambda *args, **kwargs: ({}, None))
    world.economy.regions.run_nightly(6)
    assert store.scalar('SELECT region_id FROM agents WHERE id=23') == 1
    for tick, region in [(1, 1), (4, None), (5, 2), (6, 1)]:
        assert build_world_map_geography(store, as_of_tick=tick)['agent_regions'][23] == region


def test_classic_map_directory_and_rates_use_the_committed_population(returning_world):
    from server.app import create_app
    world = returning_world
    # Inspect the committed day before the already-recorded future return.
    world.store.execute('UPDATE run_meta SET tick=4,active_tick=NULL')
    app = create_app(world)
    client = TestClient(app)
    try:
        response = client.get('/api/v2/map')
        assert response.status_code == 200, response.text
        data = response.json()
        assert 23 not in {row['id'] for row in data['core_agents']}
        assert data['population_summary']['known_living_outside'] == 1
        assert data['population_summary']['resident_population'] == sum(row['population'] for row in data['regions'])
        assert not any(row.get('agent_id') == 23 for row in data['presence'])
        person = next(row for row in client.get('/api/agents').json() if row['id'] == 23)
        assert person['modeled_residence']['state'] == 'outside'
        assert person['region_id'] is person['region_key'] is person['employer_id'] is None
        page = client.get('/api/agents', params={'limit': 100}).json()
        assert person == next(row for row in page['items'] if row['id'] == 23)
        rates = client.get('/api/metrics', params={'names': 'unemployment'}).json()['unemployment']
        assert rates[-1]['tick'] == 4
    finally:
        client.close()
        app.state.operator_workspace.close()


def test_closed_source_and_exact_replay_have_identical_population_projections(scenario_world):
    from pathlib import Path
    import hashlib
    from engine.store import Store

    entries = [proposal(), {**proposal('back', tick=3, due=5, cause='return'), 'destination_region_id': 2}]
    config = {'living_world': {'core_agents': 100}}
    source = scenario_world(entries, 'observer-source', config_overrides=config)
    for _ in range(6):
        asyncio.run(source.step())
    path = Path(source.store.path)
    expected = {tick: build_agent_journey(source.store, agent_id=23, as_of_tick=tick) for tick in (1, 4, 5)}
    scenario_world.close(source)
    stamp = hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns
    replay = scenario_world(entries, 'observer-replay', replay_source=path, config_overrides=config)
    for _ in range(6):
        asyncio.run(replay.step())
    for tick, journey in expected.items():
        assert build_agent_journey(replay.store, agent_id=23, as_of_tick=tick) == journey
    replay_path = Path(replay.store.path)
    scenario_world.close(replay)
    from contextlib import closing
    from engine.store import open_read_only_connection
    from world.replay_verify import verify_replay_connections
    with closing(open_read_only_connection(path, require_closed=True)) as original, \
         closing(open_read_only_connection(replay_path, require_closed=True)) as recorded:
        result = verify_replay_connections(original, recorded)
        assert result['exact'], result['differences']
        assert original.execute('SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls').fetchone()[0] == 0
    reopened = Store.from_read_only_connection(path, open_read_only_connection(path, require_closed=True))
    try:
        for tick, journey in expected.items():
            assert build_agent_journey(reopened, agent_id=23, as_of_tick=tick) == journey
    finally:
        reopened.close()
    assert stamp == (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
    assert not any(Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm', '-journal'))

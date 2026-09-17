"""The 3D client's source boundary: read-only, scoped, ordinary-observer records."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from run import open_run
from run_config import load_config
from server.v2_api import install_v2_routes


@pytest.mark.parametrize('profile', ['runs/base.yaml', 'runs/civic-rehearsal.yaml'])
def test_city_source_is_read_only_scoped_and_contains_no_financial_secrets(tmp_path, profile):
    config = load_config(profile)
    config['checkpoint_every'] = 0
    store, world, _ = open_run(config, None, None, data_dir=tmp_path)
    try:
        app = FastAPI()
        install_v2_routes(app, world, SimpleNamespace())
        store.conn.commit()
        store.conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        paths = [Path(store.path)]
        assert len(paths) == 1
        before = hashlib.sha256(paths[0].read_bytes()).hexdigest()
        changes = store.conn.total_changes
        with TestClient(app) as client:
            for population in ['core', 'all', 'clusters']:
                response = client.get('/api/v2/world-map', params={'population': population, 'tick': '0'})
                assert response.status_code == 200
                envelope = response.json()
                assert envelope['tick'] == 0
                assert envelope['run_id'] == str(store.get_meta()['run_id'])
                assert envelope['view_key']
                data = envelope['data']
                assert len({p['id'] for p in data['places']}) == len(data['places'])
                assert len({f['id'] for f in data['organizations']}) == len(data['organizations'])
                assert len({a['id'] for a in data['agents']}) == len(data['agents'])
                for row in data['agents']:
                    assert not {'checking_account_id','balance_cents','personality_json'} & row.keys()
                for row in data['presence']:
                    assert not (row.get('agent_id') and row.get('place_kind') == 'licensing_office')
            assert client.get('/api/v2/world-map?tick=999').status_code == 409
            assert client.get('/api/v2/world-map?fork_id=another-run').status_code == 409
        assert store.conn.total_changes == changes
        assert hashlib.sha256(paths[0].read_bytes()).hexdigest() == before
    finally:
        store.close()


def test_historic_city_keeps_future_dead_citizens_and_bank_status(tmp_path):
    config = load_config('runs/civic-rehearsal.yaml')
    config['checkpoint_every'] = 0
    store, world, _ = open_run(config, None, None, data_dir=tmp_path)
    try:
        app = FastAPI()
        install_v2_routes(app, world, SimpleNamespace())
        with TestClient(app) as client:
            before = client.get('/api/v2/world-map?tick=0&population=all').json()['data']
            agent_id = before['agents'][0]['id']
            bank_id = before['banks'][0]['id']
            store.execute('UPDATE agents SET alive=0,died_tick=5 WHERE id=?', (agent_id,))
            store.execute('UPDATE banks SET failed_tick=5 WHERE id=?', (bank_id,))
            after = client.get('/api/v2/world-map?tick=0&population=all').json()['data']
            assert after['agents'] == before['agents']
            assert after['population_summary'] == before['population_summary']
            assert after['banks'] == before['banks']
            assert all(set(bank) == {'id','name','region_id','status'} for bank in after['banks'])
            # Death at the requested tick is excluded, future arrivals are absent.
            store.execute('UPDATE agents SET died_tick=0 WHERE id=?', (agent_id,))
            store.execute('UPDATE banks SET failed_tick=0 WHERE id=?', (bank_id,))
            at_death = client.get('/api/v2/world-map?tick=0&population=all').json()['data']
            assert agent_id not in {a['id'] for a in at_death['agents']}
            assert next(b for b in at_death['banks'] if b['id']==bank_id)['status'] == 'failed'
    finally:
        store.close()

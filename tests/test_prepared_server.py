"""Prepared-server attachment tests use disposable artifacts and no transport."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

from agents.passports import SqlitePassportRepository
from engine.inspection import inspection_snapshot
from engine.store import Store
from llm.gateway import Gateway
from operator_workspace.store import OperatorWorkspace
from research.artifacts import digest_json
from research.provider_budget import ProviderBudget, ProviderBudgetContract, GatewayBinding, GatewayTarget, TokenTariff, gateway_config_identity
from server.prepared import prepared_app
from tests.test_external_agent_gateway import _world
from world.loop import World
import run


def bytes_of(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def logical(path):
    with inspection_snapshot(path) as conn:
        tables = {
            name: sorted(repr(tuple(r)) for r in conn.execute('SELECT * FROM "' + name + '"'))
            for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        tables['__schema__'] = sorted(repr(tuple(r)) for r in conn.execute('SELECT * FROM sqlite_master'))
        return tables


@pytest.fixture
def artifacts(tmp_path):
    passport = tmp_path / 'passports.db'
    workspace = tmp_path / 'operator-workspace.db'
    world = _world(tmp_path, engine_semantics_version=20, public_join={
        'enabled': True, 'passport_db_path': str(passport), 'world_slug': 'test-world',
    })
    world.runtime.external.create_connection(
        tenant_id='fixture', owner_id='owner', display_name='Pending Hermes',
        biography='fixture', preferred_occupation='builder', tier='actor')
    cfg = deepcopy(world.config)
    cfg['llm']['default_route'] = {'provider': 'fixture', 'model': 'test-model'}
    cfg['llm']['providers'] = {'fixture': {'kind': 'openai_compat',
        'base_url': 'http://127.0.0.1:1/v1', 'auth': 'none'}}
    world.store.set_meta(config_json=json.dumps(cfg))
    world.store.commit()
    world.close()
    SqlitePassportRepository(passport).close()
    OperatorWorkspace(workspace).close()
    contract = ProviderBudgetContract(
        protocol_version='typed-provider-budget-v1', study_manifest_sha256='a' * 64,
        gateway_bindings=(GatewayBinding(key='canary', config_sha256=gateway_config_identity(cfg),
            targets=(GatewayTarget(provider='fixture', model='test-model'),)),),
        max_provider_calls=2000, max_tokens=50_000_000, max_spend_nano_usd=2_000_000_000,
        tariffs=(TokenTariff(provider='fixture', model='test-model', max_input_tokens=4096,
            max_output_tokens=1024, input_nano_usd_per_token=10, output_nano_usd_per_token=20),))
    budget = ProviderBudget.create(tmp_path / 'budget.db', contract, scope='preflight', binding_key='canary')
    with sqlite3.connect(budget.path) as conn:
        conn.execute("INSERT INTO reservations(id,scope,provider,model,purpose,state,reserved_input,reserved_output,"
            "reserved_cost,input_tokens,output_tokens,usage_cost,binding_key) "
            "VALUES ('preflight','preflight','fixture','test-model','probe','settled',100,100,3000,10,5,200,'canary')")
    return dict(existing_run_db=tmp_path / 'world.db', provider_budget_db=budget.path,
        passport_db=passport, operator_workspace_db=workspace, expected_run_id='external-test',
        expected_budget_contract_sha256=digest_json(contract.model_dump(mode='json')),
        provider_budget_binding='canary', provider_budget_scope='canary', served_ticks=10)


@pytest.fixture
def inert(monkeypatch, artifacts):
    def forbidden(*args, **kwargs):
        pytest.fail('resume attempted genesis, model/preflight, subprocess or clock work')
    for obj, name in [(World, 'initialize'), (World, 'step'), (World, 'run'), (Gateway, 'preflight'),
                      (Gateway, 'complete'), (run, 'provider_preflight'), (run, 'open_run'),
                      (subprocess, 'Popen'), (httpx.AsyncClient, 'send'),
                      (ProviderBudget, 'create'), (ProviderBudget, 'complete')]:
        monkeypatch.setattr(obj, name, forbidden)
    return artifacts


def test_existing_server_startup_is_inert_and_keeps_shared_allowance(inert):
    before = {k: logical(inert[k]) for k in ('existing_run_db','provider_budget_db','passport_db','operator_workspace_db')}
    with prepared_app(**inert) as app:
        controller = app.state.run_controller
        with TestClient(app) as client:
            response = client.get('/api/run/diagnostics')
            assert response.status_code == 200
            assert controller.store.tick == 0
            assert controller.world.status == 'paused'
            assert controller.world.last_pause_reason is None
            assert controller.world.gateway._completion_guard.path == inert['provider_budget_db']
            usage = controller.world.gateway._completion_guard.snapshot()
            assert usage['provider_calls'] == 1 and usage['reported_tokens'] == 15
            assert usage['usage_cost_nano_usd'] == 200 and usage['unresolved_calls'] == 0
            assert controller.task is None and not controller.is_running()
            assert controller.remaining_ticks() == 10
            assert controller.store.scalar('SELECT COUNT(*) FROM llm_calls') == 0
            assert controller.store.scalar('SELECT COUNT(*) FROM external_action_submissions') == 0
            assert controller.store.scalar("SELECT COUNT(*) FROM external_agent_connections WHERE status='pending_actor'") == 1
            assert app.state.citizenship_service.repository.path == inert['passport_db']
    assert {k: logical(inert[k]) for k in before} == before


@pytest.mark.parametrize('field', ['existing_run_db','provider_budget_db','passport_db','operator_workspace_db'])
def test_missing_artifact_has_no_fallback_or_file_creation(inert, tmp_path, field):
    inert[field] = tmp_path / 'missing' / 'never-create.db'
    before = bytes_of(tmp_path)
    with pytest.raises(ValueError, match='existing artifact'):
        with prepared_app(**inert):
            pytest.fail('unexpected server')
    assert bytes_of(tmp_path) == before


@pytest.mark.parametrize('field,value,message', [
    ('expected_run_id','wrong-world','expected run ID'),
    ('expected_budget_contract_sha256','b'*64,'expected shared allowance'),
    ('provider_budget_binding','wrong-binding','binding differs'),
    ('provider_budget_scope','../invalid','scope'),
    ('served_ticks',0,'positive'),
])
def test_wrong_identity_or_limit_fails_without_mutation(inert, tmp_path, field, value, message):
    inert[field] = value
    before = bytes_of(tmp_path)
    with pytest.raises(ValueError, match=message):
        with prepared_app(**inert):
            pytest.fail('unexpected server')
    assert bytes_of(tmp_path) == before


@pytest.mark.parametrize('field', ['existing_run_db','provider_budget_db','passport_db','operator_workspace_db'])
def test_corrupt_artifact_fails_without_mutation(inert, tmp_path, field):
    inert[field].write_bytes(b'not a SQLite database')
    before = bytes_of(tmp_path)
    with pytest.raises((ValueError, sqlite3.Error)):
        with prepared_app(**inert):
            pytest.fail('unexpected server')
    assert bytes_of(tmp_path) == before


@pytest.mark.parametrize('field,sql,message', [
    ('existing_run_db','UPDATE run_meta SET schema_version=27','current schema'),
    ('existing_run_db','UPDATE run_meta SET schema_version=999','current schema'),
    ('existing_run_db',"UPDATE run_meta SET status='running'",'paused'),
    ('existing_run_db',"UPDATE run_meta SET status='finished'",'nonterminal'),
    ('existing_run_db','UPDATE run_meta SET active_tick=1','partial/active'),
    ('existing_run_db','DROP TABLE agent_decisions','schema'),
    ('existing_run_db','DROP TRIGGER trg_ledger_totals_insert','missing trigger'),
    ('provider_budget_db','UPDATE budget_status SET sealed=1','sealed'),
    ('provider_budget_db',"UPDATE reservations SET state='breached'",'breached'),
    ('provider_budget_db',"UPDATE reservations SET state='reserved'",'unresolved'),
    ('provider_budget_db',"UPDATE reservations SET state='unknown'",'unresolved'),
    ('provider_budget_db','UPDATE reservations SET usage_cost=3000000000','breached'),
    ('passport_db',"DELETE FROM passport_meta WHERE key='cookie_signing_key'",'signing key'),
    ('passport_db','DROP TABLE passport_oauth_requests','schema'),
])
def test_incompatible_or_unsafe_artifacts_fail_closed(inert, tmp_path, field, sql, message):
    with sqlite3.connect(inert[field]) as conn:
        conn.execute(sql)
    before = bytes_of(tmp_path)
    with pytest.raises((ValueError, sqlite3.Error), match=message):
        with prepared_app(**inert):
            pytest.fail('unexpected server')
    assert bytes_of(tmp_path) == before


def test_wrong_passport_file_is_rejected(inert, tmp_path):
    other = tmp_path / 'other-passports.db'
    SqlitePassportRepository(other).close()
    inert['passport_db'] = other
    before = bytes_of(tmp_path)
    with pytest.raises(ValueError, match='recorded world identity'):
        with prepared_app(**inert):
            pytest.fail('unexpected server')
    assert bytes_of(tmp_path) == before


@pytest.mark.parametrize('configured', [False, True])
def test_unrelated_valid_workspace_is_rejected(inert, tmp_path, configured):
    if configured:
        with sqlite3.connect(inert['existing_run_db']) as conn:
            cfg = json.loads(conn.execute('SELECT config_json FROM run_meta').fetchone()[0])
            cfg['operator_workspace'] = {'path': str(inert['operator_workspace_db'])}
            conn.execute('UPDATE run_meta SET config_json=?', (json.dumps(cfg),))
    other = tmp_path / 'unrelated-workspace.db'
    OperatorWorkspace(other).close()
    inert['operator_workspace_db'] = other
    before = bytes_of(tmp_path)
    with pytest.raises(ValueError, match='recorded world workspace'):
        with prepared_app(**inert):
            pytest.fail('unexpected server')
    assert bytes_of(tmp_path) == before


def test_explicit_recorded_workspace_loads(inert, tmp_path):
    configured = tmp_path / 'configured-workspace.db'
    inert['operator_workspace_db'].rename(configured)
    with sqlite3.connect(inert['existing_run_db']) as conn:
        cfg = json.loads(conn.execute('SELECT config_json FROM run_meta').fetchone()[0])
        cfg['operator_workspace'] = {'path': str(configured)}
        conn.execute('UPDATE run_meta SET config_json=?', (json.dumps(cfg),))
    inert['operator_workspace_db'] = configured
    before = {k: logical(inert[k]) for k in ('existing_run_db','provider_budget_db','passport_db','operator_workspace_db')}
    with prepared_app(**inert) as app:
        with TestClient(app):
            assert app.state.operator_workspace.path == configured
    assert {k: logical(inert[k]) for k in before} == before


def test_durable_attention_pause_is_not_cleared(inert):
    store = Store(str(inert['existing_run_db']), existing_only=True)
    store.log_event(0, 'budget_pause', {'phase':'NIGHT_CLOSE','detail':'attention required'})
    store.close()
    before = logical(inert['existing_run_db'])
    with prepared_app(**inert) as app:
        world = app.state.run_controller.world
        assert world.status == 'paused' and world._pause_requested
        assert world.last_pause_reason == {'reason':'budget','phase':'NIGHT_CLOSE','detail':'attention required'}
        with TestClient(app) as client:
            assert client.get('/api/run/diagnostics').status_code == 200
    assert logical(inert['existing_run_db']) == before


def test_state_change_before_writer_lock_is_rejected_without_retry(inert, monkeypatch):
    import server.prepared as prepared
    attempts, concurrent_state = [], []
    def raced_store(*args, **kwargs):
        store = Store(*args, **kwargs)
        store.conn.execute('UPDATE run_meta SET tick=1')
        concurrent_state.append(logical(inert['existing_run_db']))
        attempts.append(1)
        return store
    monkeypatch.setattr(prepared, 'Store', raced_store)
    with pytest.raises(ValueError, match='changed during attachment'):
        with prepared_app(**inert):
            pytest.fail('unexpected server')
    assert attempts == [1]
    assert logical(inert['existing_run_db']) == concurrent_state[0]


def test_accidental_runtime_startup_write_is_rejected(inert, monkeypatch):
    import server.prepared as prepared
    before = logical(inert['existing_run_db'])
    def writing_constructor(store, *args, **kwargs):
        store.conn.execute('UPDATE run_meta SET tick=1')
        pytest.fail('write should have been blocked')
    monkeypatch.setattr(prepared, 'World', writing_constructor)
    with pytest.raises(sqlite3.OperationalError, match='readonly'):
        with prepared_app(**inert):
            pytest.fail('unexpected server')
    assert logical(inert['existing_run_db']) == before


def cli(inert):
    argv = ['run.py','--serve','--ticks',str(inert['served_ticks'])]
    for k, v in inert.items():
        if k != 'served_ticks':
            argv.extend(['--' + k.replace('_','-'), str(v)])
    return argv


def test_cli_dispatches_existing_mode_without_normal_startup(inert, monkeypatch):
    called = []
    def serve(app, **kwargs):
        called.append(app.state.run_controller.store.tick)
        with TestClient(app) as client:
            assert client.get('/api/run/diagnostics').status_code == 200
    import uvicorn
    monkeypatch.setattr(uvicorn,'run',serve)
    monkeypatch.setattr(run,'load_config',lambda *a: pytest.fail('normal config loading'))
    monkeypatch.setattr(sys,'argv',cli(inert))
    run.main()
    assert called == [0]


@pytest.mark.parametrize('extra', [
    ['--preflight'], ['--preflight-live'], ['--resume','external-test'],
    ['--config','runs/base.yaml'], ['--acceptance-run'], ['--approve-live-inference'],
    ['--host','0.0.0.0'], ['--ticks','0'],
])
def test_resume_cli_cannot_enter_other_startup_modes(inert, monkeypatch, tmp_path, extra):
    monkeypatch.setattr(sys,'argv',cli(inert) + extra)
    before = bytes_of(tmp_path)
    with pytest.raises(SystemExit) as exc:
        run.main()
    assert exc.value.code == 2
    assert bytes_of(tmp_path) == before


def test_partial_resume_flags_never_fall_back_to_new_world(inert, monkeypatch):
    monkeypatch.setattr(sys,'argv',['run.py','--expected-run-id','external-test'])
    with pytest.raises(SystemExit) as exc:
        run.main()
    assert exc.value.code == 2


def test_normal_new_world_startup_still_initializes(tmp_path, monkeypatch):
    # Exercise the actual ordinary CLI/open_run/genesis path with offline config.
    import uvicorn
    original = run.open_run
    worlds = []
    def isolated(config, resume, replay, **kwargs):
        assert resume is replay is None
        config['population']['size'] = 4
        config['firms'].update(count=2, listed=1)
        config['banks']['count'] = 1
        result = original(config, resume, replay, data_dir=tmp_path, **kwargs)
        worlds.append(result[1])
        return result
    monkeypatch.setattr(run,'open_run',isolated)
    monkeypatch.setattr(sys,'argv',['run.py','--config','runs/base.yaml','--serve'])
    def serve(app, **kw):
        with TestClient(app):
            pass
    monkeypatch.setattr(uvicorn,'run',serve)
    run.main()
    assert len(worlds) == 1
    with inspection_snapshot(worlds[0].store.path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM agents').fetchone()[0] > 0
        assert conn.execute('SELECT tick FROM run_meta').fetchone()[0] == 0

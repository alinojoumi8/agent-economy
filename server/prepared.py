"""Explicit, inert attachment of a prepared world and its existing control plane."""
from contextlib import ExitStack, contextmanager
import json
import re
import sqlite3
from pathlib import Path

from agents.passports import SqlitePassportRepository
from engine.existing import existing_path, validate_schema
from engine.inspection import inspection_snapshot
from engine.schema import SCHEMA_VERSION, initialize_schema
from engine.semantics import semantics_version
from engine.store import Store
from llm.completion_guard import BudgetExceeded
from operator_workspace.store import OperatorWorkspace, SCHEMA as WORKSPACE_SCHEMA
from research.artifacts import digest_json
from research.provider_budget import (
    ProviderBudget, ProviderBudgetContract, gateway_config_identity,
)
from world.loop import World


def _world_state(conn, expected_run_id):
    rows = conn.execute('SELECT * FROM run_meta').fetchall()
    if len(rows) != 1 or rows[0]['run_id'] != expected_run_id:
        raise ValueError('expected run ID does not match existing run')
    meta = dict(rows[0])
    if meta['schema_version'] != SCHEMA_VERSION:
        raise ValueError('existing run requires current schema; migration is forbidden')
    if meta['status'] not in {'paused', 'created'}:
        raise ValueError('existing run must be paused and nonterminal')
    if meta['active_tick'] is not None or meta['legacy_partial']:
        raise ValueError('existing run has a partial/active tick; explicit recovery required')
    cfg = json.loads(meta['config_json'])
    if not isinstance(cfg, dict) or 'engine_semantics_version' not in cfg:
        raise ValueError('existing run must declare its semantics version')
    semantics_version(cfg, default=2)
    return meta, cfg


def _passport_binding(conn, passport, config):
    join = config.get('external_gateway', {}).get('public_join', {})
    if not join.get('enabled') or not join.get('passport_db_path'):
        raise ValueError('run must declare existing local passport storage')
    if existing_path(join['passport_db_path']) != passport:
        raise ValueError('passport path differs from recorded world identity storage')
    with inspection_snapshot(passport) as identities:
        validate_schema(identities, lambda ref: ref.executescript(SqlitePassportRepository._SCHEMA))
        key = identities.execute("SELECT value FROM passport_meta WHERE key='cookie_signing_key'").fetchone()
        if key is None or not re.fullmatch(r'[a-f0-9]{64}', key[0]):
            raise ValueError('existing passport signing key is missing or incompatible')
        for row in conn.execute('SELECT id,passport_id FROM external_agent_connections WHERE passport_id IS NOT NULL'):
            link = identities.execute(
                'SELECT 1 FROM passport_citizenships c JOIN agent_passports p ON p.id=c.passport_id '
                'WHERE c.connection_id=? AND c.passport_id=? AND c.run_id=?',
                (row['id'], row['passport_id'], conn.execute('SELECT run_id FROM run_meta').fetchone()[0]),
            ).fetchone()
            if link is None:
                raise ValueError('passport storage does not match a recorded citizen identity')


def _budget_contract(path, expected_hash, binding, config):
    if not re.fullmatch(r'[a-f0-9]{64}', expected_hash):
        raise ValueError('expected budget contract SHA256 must be explicit')
    with inspection_snapshot(path) as conn:
        if [r[0] for r in conn.execute('PRAGMA integrity_check')] != ['ok']:
            raise ValueError('provider budget failed SQLite integrity_check')
        rows = conn.execute('SELECT json FROM budget_contract').fetchall()
        if len(rows) != 1:
            raise ValueError('provider budget contract is missing or ambiguous')
        contract = ProviderBudgetContract.model_validate_json(rows[0][0])
        if digest_json(contract.model_dump(mode='json')) != expected_hash:
            raise ValueError('provider budget is not the expected shared allowance')
        choices = contract.gateway_bindings or ()
        selected = next((b for b in choices if b.key == binding), None)
        if selected is None or selected.config_sha256 != gateway_config_identity(config):
            raise ValueError('provider budget binding differs from existing world configuration')
        status = conn.execute('SELECT sealed FROM budget_status WHERE singleton=1').fetchone()
        if status is None or status[0] != 0:
            raise ValueError('provider budget is sealed or has no disposition')
        totals = ProviderBudget._totals(conn)
        if any(totals[k] for k in ('breached_calls', 'unresolved_calls', 'unknown_usage_calls')):
            raise ValueError('provider budget has breached or unresolved reservations')
        if (totals['provider_calls'] > contract.max_provider_calls
                or totals['encumbered_tokens'] > contract.max_tokens
                or totals['encumbered_nano_usd'] > contract.max_spend_nano_usd):
            raise ValueError('provider budget allowance is breached')
        return contract


@contextmanager
def prepared_app(*, existing_run_db, provider_budget_db, passport_db,
                 operator_workspace_db, expected_run_id,
                 expected_budget_contract_sha256, provider_budget_binding,
                 provider_budget_scope, served_ticks):
    """Validate all artifacts before attachment; no genesis, migration or preflight."""
    if not expected_run_id or type(served_ticks) is not int or served_ticks <= 0:
        raise ValueError('expected run ID and a positive served tick allowance are required')
    paths = [existing_path(p) for p in (
        existing_run_db, provider_budget_db, passport_db, operator_workspace_db)]
    if len(set(paths)) != 4:
        raise ValueError('world, budget, passport and workspace paths must be distinct')
    database, budget_path, passport, workspace_path = paths
    ProviderBudget._validate_scope(provider_budget_scope)
    with inspection_snapshot(database) as conn:
        meta, config = _world_state(conn, expected_run_id)
        validate_schema(conn, initialize_schema)
        _passport_binding(conn, passport, config)
    configured_workspace = config.get('operator_workspace', {}).get(
        'path', database.parent / 'operator-workspace.db')
    if existing_path(Path(configured_workspace)) != workspace_path:
        raise ValueError('operator workspace path differs from recorded world workspace')
    with inspection_snapshot(workspace_path) as conn:
        validate_schema(conn, lambda ref: ref.executescript(WORKSPACE_SCHEMA))
    contract = _budget_contract(budget_path, expected_budget_contract_sha256,
                                provider_budget_binding, config)
    from engine.replay_checkpoint import source_revision
    checkpoint_revision = source_revision()
    with ExitStack() as stack:
        store = Store(str(database), existing_only=True)
        stack.callback(store.close)
        # Hold the normal SQLite writer exclusion while rechecking and constructing
        # runtime objects. query_only catches accidental startup economic writes.
        store.conn.execute('BEGIN IMMEDIATE')
        store.conn.execute('PRAGMA query_only=ON')
        locked_meta, locked_config = _world_state(store.conn, expected_run_id)
        if locked_meta != meta:
            raise ValueError('existing world changed during attachment; no automatic retry')
        identities = SqlitePassportRepository(passport, existing_only=True)
        stack.callback(identities.close)
        identities._conn.execute('BEGIN IMMEDIATE')
        identities._conn.execute('PRAGMA query_only=ON')
        _passport_binding(store.conn, passport, locked_config)
        workspace = OperatorWorkspace(workspace_path, world_path=database, existing_only=True)
        stack.callback(workspace.close)
        workspace.conn.execute('BEGIN IMMEDIATE')
        workspace.conn.execute('PRAGMA query_only=ON')
        guard = ProviderBudget(budget_path, contract, scope=provider_budget_scope,
                               binding_key=provider_budget_binding)
        guard.validate_config(config)
        _budget_contract(budget_path, expected_budget_contract_sha256,
                         provider_budget_binding, config)
        world = World(store, config, completion_guard=guard)
        stack.callback(world.gateway.close)
        world.status = meta['status']
        world.restore_prng_state()
        # Retain durable attention evidence at this boundary. Do not silently
        # turn an unresolved provider/budget pause into an ordinary paused world.
        pause = store.conn.execute(
            "SELECT kind,payload_json FROM events WHERE kind IN ('provider_pause','budget_pause') "
            'AND tick>=? ORDER BY id DESC LIMIT 1', (meta['tick'],)).fetchone()
        if pause is not None:
            world.last_pause_reason = {
                **json.loads(pause['payload_json']),
                'reason': 'budget' if pause['kind'] == 'budget_pause' else 'provider',
            }
            world._pause_requested = True
        from server.app import create_app
        app = create_app(world, served_ticks=served_ticks, passport_repository=identities,
                         operator_workspace=workspace)
        # Prepared servers are controlled validation surfaces. Both Step (used
        # by the production cohort) and ADVANCE-ONE require a complete pre-tick
        # bundle; continuous Run is intentionally unavailable on this surface.
        controller = app.state.run_controller
        controller.replay_checkpoint_paths = dict(world=database, budget=budget_path,
                                                  passport=passport, workspace=workspace_path)
        controller.replay_checkpoint_root = database.parent / 'validation-checkpoints'
        controller.replay_checkpoint_revision = checkpoint_revision
        reader = getattr(app.state, 'replay_reader', None)
        if reader is not None:
            stack.callback(reader.close)
        for conn in (workspace.conn, identities._conn, store.conn):
            conn.rollback()
            conn.execute('PRAGMA query_only=OFF')
        yield app


FLAGS = {
    'existing_run_db', 'provider_budget_db', 'passport_db', 'operator_workspace_db',
    'expected_run_id', 'expected_budget_contract_sha256', 'provider_budget_binding',
    'provider_budget_scope',
}


def add_arguments(parser):
    for name in sorted(FLAGS):
        parser.add_argument('--' + name.replace('_', '-'), default=None,
                            help='required explicit existing-artifact attachment value')


def handle_cli(parser, args):
    """Exclusive early dispatch, before normal CLI config/preflight/open_run."""
    if not any(getattr(args, name) is not None for name in FLAGS):
        return False
    missing = [name for name in sorted(FLAGS) if not getattr(args, name)]
    if missing:
        parser.error('resume-existing requires: ' + ', '.join('--' + n.replace('_', '-') for n in missing))
    if not args.serve or args.ticks is None or args.ticks <= 0:
        parser.error('resume-existing requires --serve and positive --ticks (a limit, not automatic execution)')
    allowed = FLAGS | {'serve', 'ticks', 'host', 'port'}
    for action in parser._actions:
        if action.dest not in allowed | {'help'} and getattr(args, action.dest) != action.default:
            parser.error('resume-existing cannot be combined with ' + action.option_strings[0])
    if args.host not in {'127.0.0.1', '::1'}:
        parser.error('resume-existing requires a loopback host')
    try:
        with prepared_app(**{name: getattr(args, name) for name in FLAGS}, served_ticks=args.ticks) as app:
            import uvicorn
            uvicorn.run(app, host=args.host, port=args.port, log_level='warning', access_log=False)
    except (ValueError, OSError, sqlite3.Error, BudgetExceeded) as exc:
        parser.error(f'resume-existing refused: {exc}')
    return True

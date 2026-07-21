from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import hosted.config as hosted_config_module

from hosted.catalog import (
    CatalogConflict,
    CatalogError,
    HostedCatalog,
    MembershipRecord,
    TENANT_CONTEXT_SQL,
)
from hosted.config import (
    HostedConfig,
    HostedDatabaseConfig,
    create_postgres_pool,
    create_hosted_application,
    load_hosted_config,
)


class Cursor:
    def __init__(self, *, rows=(), one=None, rowcount=0):
        self._rows = list(rows)
        self._one = one
        self.rowcount = rowcount

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._one


class CatalogConnection:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.calls = []
        self.closed = False
        self.commits = 0
        self.rollbacks = 0

    @contextmanager
    def transaction(self):
        try:
            yield
        except BaseException:
            self.rollbacks += 1
            raise
        else:
            self.commits += 1

    def execute(self, sql, params=()):
        self.calls.append((sql, tuple(params)))
        if sql == TENANT_CONTEXT_SQL:
            return Cursor()
        if self.responses:
            return self.responses.pop(0)
        return Cursor()

    def close(self):
        self.closed = True


class Connections:
    def __init__(self, *connections):
        self.connections = list(connections)
        self.opened = 0

    def __call__(self, _dsn):
        connection = self.connections[self.opened]
        self.opened += 1
        return connection


def run_row(tenant_id, run_id, owner_id, *, status="running"):
    return {
        "id": run_id,
        "tenant_id": tenant_id,
        "owner_user_id": owner_id,
        "run_key": "run-one",
        "display_name": "Run One",
        "status": status,
        "schema_version": 11,
        "engine_semantics_version": 7,
        "catalog_json": {},
        "snapshot_object_key": None,
        "snapshot_sha256": None,
        "snapshot_size_bytes": None,
        "writer_lease_owner": None,
        "writer_lease_token": None,
        "writer_lease_expires_at": None,
    }


def test_every_tenant_transaction_sets_local_context_first_and_closes():
    tenant_id = uuid4()
    connection = CatalogConnection()
    catalog = HostedCatalog("postgresql://example", connect=Connections(connection))

    with catalog.tenant_transaction(tenant_id) as active:
        assert active is connection
        active.execute("SELECT * FROM runs WHERE tenant_id = %s", (str(tenant_id),))

    assert connection.calls[0] == (TENANT_CONTEXT_SQL, (str(tenant_id),))
    assert "set_config('app.tenant_id', %s, true)" in TENANT_CONTEXT_SQL
    assert connection.commits == 1
    assert connection.closed is True


def test_tenant_transaction_rolls_back_and_invalid_tenant_never_connects():
    connection = CatalogConnection()
    factory = Connections(connection)
    catalog = HostedCatalog("postgresql://example", connect=factory)

    with pytest.raises(RuntimeError, match="boom"):
        with catalog.tenant_transaction(uuid4()):
            raise RuntimeError("boom")
    assert connection.rollbacks == 1
    assert connection.commits == 0

    with pytest.raises(ValueError, match="tenant id must be a UUID"):
        with catalog.tenant_transaction("not-a-tenant"):
            pass
    assert factory.opened == 1


def test_raw_catalog_connector_receives_the_configured_timeout(monkeypatch):
    captured = {}
    connection = CatalogConnection([Cursor(one={"ready": 1})])

    def connect(dsn, *, connect_timeout_seconds=10):
        captured.update(dsn=dsn, timeout=connect_timeout_seconds)
        return connection

    monkeypatch.setattr(HostedCatalog, "_default_connect", staticmethod(connect))
    catalog = HostedCatalog(
        "postgresql://example/control", connect_timeout_seconds=7
    )

    assert catalog.ready() is True
    assert captured == {"dsn": "postgresql://example/control", "timeout": 7}


def test_live_dsn_role_and_capability_are_verified_before_startup():
    safe_web = {
        "current_user": "agent_economy_app",
        "rolsuper": False,
        "rolbypassrls": False,
        "owns_tenant_table": False,
        "can_enumerate_runs": False,
        "can_lookup_auth": True,
        "can_transfer_run_owners": True,
        "has_forbidden_table_privilege": False,
        "has_web_privileges": True,
        "has_supervisor_privileges": False,
        "has_peer_role": False,
        "has_create_privilege": False,
    }
    catalog = HostedCatalog(
        "postgresql://example",
        connect=Connections(CatalogConnection([Cursor(one=safe_web)])),
        expected_role="agent_economy_app",
        capability="web",
    )
    catalog.assert_runtime_security()

    unsafe = dict(safe_web, current_user="postgres", rolsuper=True)
    catalog = HostedCatalog(
        "postgresql://example",
        connect=Connections(CatalogConnection([Cursor(one=unsafe)])),
        expected_role="agent_economy_app",
        capability="web",
    )
    with pytest.raises(CatalogError, match="configured runtime role"):
        catalog.assert_runtime_security()

    wrong_scope = dict(safe_web, can_enumerate_runs=True)
    catalog = HostedCatalog(
        "postgresql://example",
        connect=Connections(CatalogConnection([Cursor(one=wrong_scope)])),
        expected_role="agent_economy_app",
        capability="web",
    )
    with pytest.raises(CatalogError, match="run-discovery privilege"):
        catalog.assert_runtime_security()

    safe_supervisor = dict(
        safe_web,
        current_user="agent_economy_supervisor",
        can_enumerate_runs=True,
        can_lookup_auth=False,
        can_transfer_run_owners=False,
        has_web_privileges=False,
        has_supervisor_privileges=True,
    )
    catalog = HostedCatalog(
        "postgresql://example",
        connect=Connections(CatalogConnection([Cursor(one=safe_supervisor)])),
        expected_role="agent_economy_supervisor",
        capability="supervisor",
    )
    catalog.assert_runtime_security()


def test_catalog_reuses_a_bounded_pool_under_concurrent_pressure():
    class BlockingConnection(CatalogConnection):
        def __init__(self, release):
            super().__init__()
            self.release = release

        def execute(self, sql, params=()):
            if sql == "SELECT 1 AS ready":
                self.release.wait(timeout=2)
                return Cursor(one={"ready": 1})
            return super().execute(sql, params)

    class BoundedPool:
        def __init__(self, limit):
            self.limit = limit
            self.active = 0
            self.max_active = 0
            self.checkouts = 0
            self.lock = threading.Lock()
            self.full = threading.Event()
            self.release = threading.Event()

        @contextmanager
        def connection(self):
            with self.lock:
                if self.active >= self.limit:
                    raise RuntimeError("pool capacity")
                self.active += 1
                self.checkouts += 1
                self.max_active = max(self.max_active, self.active)
                if self.active == self.limit:
                    self.full.set()
            try:
                yield BlockingConnection(self.release)
            finally:
                with self.lock:
                    self.active -= 1

    pool = BoundedPool(2)
    catalog = HostedCatalog("postgresql://example", pool=pool)
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(catalog.ready) for _ in range(6)]
        assert pool.full.wait(timeout=2)
        time.sleep(0.05)
        pool.release.set()
        results = []
        for future in futures:
            try:
                results.append(future.result())
            except RuntimeError:
                results.append(False)

    assert results.count(True) == 2
    assert pool.max_active == 2
    assert pool.checkouts == 2


def test_pool_factory_honors_web_and_supervisor_bounds():
    database = HostedDatabaseConfig(
        "postgresql://web@example/control",
        supervisor_dsn="postgresql://supervisor@example/control",
        pool_min_size=0,
        pool_max_size=2,
        connect_timeout_seconds=3,
    )
    config = HostedConfig(
        enabled=True,
        database=database,
        public_base_url="https://economy.example",
    )
    web = create_postgres_pool(config, purpose="web", open_pool=False)
    supervisor = create_postgres_pool(config, purpose="supervisor", open_pool=False)
    try:
        assert (web.min_size, web.max_size, web.max_waiting, web.timeout) == (0, 2, 8, 3)
        assert (supervisor.min_size, supervisor.max_size) == (0, 2)
        assert "web@example" in web.conninfo
        assert "supervisor@example" in supervisor.conninfo
    finally:
        web.close()
        supervisor.close()


def test_hosted_lifespan_opens_verifies_and_closes_both_owned_pools(
    monkeypatch, tmp_path
):
    events = []

    class Pool:
        def __init__(self, purpose):
            self.purpose = purpose
            self.opened = 0
            self.waited = []
            self.closed = 0

        def open(self, *, wait=False):
            assert wait is False
            self.opened += 1
            events.append(f"open:{self.purpose}")

        def wait(self, *, timeout):
            assert self.opened == 1
            self.waited.append(timeout)
            events.append(f"wait:{self.purpose}")

        def close(self, *, timeout):
            self.closed += 1
            events.append(f"close:{self.purpose}")

    class Catalog:
        def __init__(self, purpose, pool):
            self.purpose = purpose
            self.pool = pool

        def assert_runtime_security(self):
            assert self.pool.opened == 1
            events.append(f"security:{self.purpose}")

        def ready(self):
            return True

    class Supervisor:
        def __init__(self, catalog):
            self.catalog = catalog
            self.profiles = {}
            self.recovered = False
            self.closed = False

        async def recover_active_runs(self):
            self.recovered = True
            events.append("recover")

        async def shutdown(self):
            self.closed = True
            events.append("supervisor:shutdown")

        def ready(self):
            return True

    pools = {}

    def pool_factory(_config, *, purpose, open_pool):
        assert open_pool is False
        pool = Pool(purpose)
        pools[purpose] = pool
        return pool

    def catalog_factory(_config, *, purpose="web", pool=None, **_kwargs):
        return Catalog(purpose, pool)

    monkeypatch.setattr(hosted_config_module, "create_postgres_pool", pool_factory)
    monkeypatch.setattr(hosted_config_module, "create_catalog", catalog_factory)
    monkeypatch.setattr(
        hosted_config_module,
        "create_supervisor",
        lambda _config, *, catalog, **_kwargs: Supervisor(catalog),
    )
    config = HostedConfig(
        enabled=True,
        database=HostedDatabaseConfig(
            "postgresql://web@example/control",
            supervisor_dsn="postgresql://supervisor@example/control",
            connect_timeout_seconds=4,
        ),
        public_base_url="https://economy.example",
    )
    app = create_hosted_application(
        config,
        auth=object(),
        artifact_store=SimpleNamespace(root=tmp_path),
    )

    with TestClient(app, base_url="https://testserver"):
        assert app.state.supervisor.recovered
        assert {name: pool.waited for name, pool in pools.items()} == {
            "web": [4],
            "supervisor": [4],
        }
        assert events == [
            "open:web",
            "wait:web",
            "open:supervisor",
            "wait:supervisor",
            "security:web",
            "security:supervisor",
            "recover",
        ]

    assert app.state.supervisor.closed
    assert all(pool.closed == 1 for pool in pools.values())
    assert events[-3:] == [
        "supervisor:shutdown",
        "close:supervisor",
        "close:web",
    ]


def test_membership_lookup_is_parameterized_scoped_and_typed():
    tenant_id = uuid4()
    user_id = uuid4()
    connection = CatalogConnection(
        [Cursor(one={
            "tenant_id": tenant_id,
            "user_id": user_id,
            "role": "observer",
            "status": "active",
        })]
    )
    catalog = HostedCatalog("postgresql://example", connect=Connections(connection))

    membership = catalog.get_membership(tenant_id, user_id)

    assert membership == MembershipRecord(tenant_id, user_id, "observer", "active")
    sql, params = connection.calls[1]
    assert "tenant_id = %s AND user_id = %s" in sql
    assert params == (str(tenant_id), str(user_id))
    assert str(tenant_id) not in sql
    assert str(user_id) not in sql


def test_writer_lease_acquisition_is_atomic_and_bounded():
    tenant_id = uuid4()
    run_id = uuid4()
    lease_token = uuid4()
    connection = CatalogConnection([Cursor(one={"writer_lease_token": lease_token})])
    catalog = HostedCatalog("postgresql://example", connect=Connections(connection))

    # Stabilize only the assertion surface: the returned token comes from the DB.
    acquired = catalog.acquire_writer_lease(
        tenant_id, run_id, owner="worker-1", ttl_seconds=45
    )

    assert acquired == lease_token
    sql, params = connection.calls[1]
    assert "writer_lease_expires_at <= clock_timestamp()" in sql
    assert "RETURNING writer_lease_token" in sql
    assert params[0] == "worker-1"
    assert params[2] == 45
    assert params[3:] == (str(tenant_id), str(run_id))

    with pytest.raises(ValueError, match="between 5 and 3600"):
        catalog.acquire_writer_lease(tenant_id, run_id, owner="worker", ttl_seconds=1)


def test_snapshot_pointer_requires_the_live_writer_lease():
    tenant_id = uuid4()
    run_id = uuid4()
    lease_token = uuid4()
    connection = CatalogConnection([Cursor(rowcount=1)])
    catalog = HostedCatalog("postgresql://example", connect=Connections(connection))

    updated = catalog.update_snapshot_pointer(
        tenant_id,
        run_id,
        lease_token=lease_token,
        object_key=f"tenants/{tenant_id}/runs/{run_id}/snapshot.sqlite",
        sha256="a" * 64,
        size_bytes=1234,
    )

    assert updated is True
    sql, params = connection.calls[1]
    assert "writer_lease_token = %s" in sql
    assert "writer_lease_expires_at > clock_timestamp()" in sql
    assert params[-3:] == (str(tenant_id), str(run_id), str(lease_token))


def test_session_and_invitation_inputs_fail_closed_before_database_access():
    factory = Connections(CatalogConnection())
    catalog = HostedCatalog("postgresql://example", connect=factory)
    tenant_id = uuid4()
    user_id = uuid4()

    with pytest.raises(ValueError, match="SHA-256"):
        catalog.create_session(
            tenant_id,
            user_id,
            token_hash="plaintext-token",
            csrf_secret_hash="b" * 64,
            expires_at=datetime.now(timezone.utc),
        )
    with pytest.raises(ValueError, match="observer, agent_owner, or admin"):
        catalog.create_invitation(
            tenant_id,
            email="member@example.com",
            role="owner",
            token_hash="a" * 64,
            invited_by_user_id=user_id,
            expires_at=datetime.now(timezone.utc),
        )
    assert factory.opened == 0


def test_public_oauth_client_registration_is_canonical_and_retrievable():
    client_id = "ae_client_1234567890abcdef"
    row = {
        "client_id": client_id,
        "client_name": "OpenClaw",
        "redirect_uris": ["https://agent.example/callback"],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }
    registered = CatalogConnection([Cursor(one=row)])
    retrieved = CatalogConnection([Cursor(one=row)])
    catalog = HostedCatalog(
        "postgresql://example", connect=Connections(registered, retrieved))

    created = catalog.register_external_oauth_client(
        client_name=" OpenClaw ",
        redirect_uris=["https://agent.example/callback"],
        grant_types=["refresh_token", "authorization_code"],
        response_types=["code"],
    )
    loaded = catalog.get_external_oauth_client(client_id)

    assert created == loaded == row
    insert_sql, insert_params = registered.calls[0]
    assert "INSERT INTO external_oauth_clients" in insert_sql
    assert insert_params[1:] == (
        "OpenClaw", ["https://agent.example/callback"],
        ["authorization_code", "refresh_token"], ["code"])
    select_sql, select_params = retrieved.calls[0]
    assert "FROM external_oauth_clients" in select_sql
    assert select_params == (client_id,)

    with pytest.raises(ValueError, match="unsupported OAuth public-client"):
        catalog.register_external_oauth_client(
            client_name="Confidential client",
            redirect_uris=["https://agent.example/callback"],
            grant_types=["client_credentials"], response_types=["code"],
            token_endpoint_auth_method="client_secret_basic")


def test_audit_api_only_exposes_append_and_uses_json_parameters():
    tenant_id = uuid4()
    actor_id = uuid4()
    connection = CatalogConnection([Cursor(one={"id": 41})])
    catalog = HostedCatalog("postgresql://example", connect=Connections(connection))

    audit_id = catalog.append_audit(
        tenant_id,
        actor_user_id=actor_id,
        action="run.created",
        target_type="run",
        target_id="run-1",
        details={"safe": True},
    )

    assert audit_id == 41
    sql, params = connection.calls[1]
    assert sql.lstrip().startswith("INSERT INTO audit_log")
    assert "%s::jsonb" in sql
    assert params[-1] == '{"safe":true}'
    assert not hasattr(catalog, "update_audit")
    assert not hasattr(catalog, "delete_audit")


def test_session_hash_lookup_discovers_only_scope_then_reads_under_rls():
    tenant_id = uuid4()
    user_id = uuid4()
    session_id = uuid4()
    token_hash = "a" * 64
    expires_at = datetime.now(timezone.utc)
    scope = CatalogConnection([Cursor(one={"tenant_id": tenant_id})])
    scoped = CatalogConnection([Cursor(one={
        "id": session_id,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "token_hash": token_hash,
        "csrf_secret_hash": "b" * 64,
        "expires_at": expires_at,
        "revoked_at": None,
    })])
    catalog = HostedCatalog(
        "postgresql://example", connect=Connections(scope, scoped)
    )

    session = catalog.lookup_session_by_hash(token_hash)

    assert session is not None and session.id == session_id
    assert "hosted_active_session_tenant(%s)" in scope.calls[0][0]
    assert all(sql != TENANT_CONTEXT_SQL for sql, _ in scope.calls)
    assert scoped.calls[0] == (TENANT_CONTEXT_SQL, (str(tenant_id),))
    assert "s.tenant_id = %s AND s.token_hash = %s" in scoped.calls[1][0]
    assert "t.status = 'active'" in scoped.calls[1][0]
    assert "m.status = 'active'" in scoped.calls[1][0]


def test_invitation_consumption_claims_and_membership_in_one_scoped_statement():
    tenant_id = uuid4()
    user_id = uuid4()
    token_hash = "c" * 64
    scope = CatalogConnection([Cursor(one={"tenant_id": tenant_id})])
    scoped = CatalogConnection([Cursor(one={
        "tenant_id": tenant_id,
        "user_id": user_id,
        "role": "observer",
        "status": "active",
    })])
    catalog = HostedCatalog(
        "postgresql://example", connect=Connections(scope, scoped)
    )

    membership = catalog.consume_invitation(token_hash, user_id=user_id)

    assert membership == MembershipRecord(tenant_id, user_id, "observer", "active")
    sql, params = scoped.calls[1]
    assert "WITH authorized AS" in sql
    assert "inviter.role = 'admin'" in sql
    assert "t.status = 'active'" in sql
    assert "accepted_at = clock_timestamp()" in sql
    assert "i.expires_at > clock_timestamp()" in sql
    assert "u.email_normalized = i.email_normalized" in sql
    assert "INSERT INTO memberships" in sql
    assert params == (str(tenant_id), token_hash, str(user_id), str(user_id))


def test_invitation_registration_links_only_the_verified_existing_user_without_update():
    tenant_id = uuid4()
    expected_user_id = uuid4()
    proposed_user_id = uuid4()
    token_hash = "d" * 64
    redeemed_at = datetime.now(timezone.utc)
    scope = CatalogConnection([Cursor(one={"tenant_id": tenant_id})])
    scoped = CatalogConnection([Cursor(one=None)])
    catalog = HostedCatalog(
        "postgresql://example", connect=Connections(scope, scoped)
    )

    result = catalog.redeem_invitation_with_user(
        token_hash,
        email="member@example.test",
        display_name="Member",
        password_hash="encoded-password-hash",
        redeemed_at=redeemed_at,
        user_id=proposed_user_id,
        expected_existing_user_id=expected_user_id,
    )

    assert result is None
    sql, params = scoped.calls[1]
    assert "expected_existing_user_id" in sql
    assert "FROM existing_user UNION ALL" in sql
    assert "ON CONFLICT DO NOTHING" in sql
    assert "ON CONFLICT (email_normalized) DO UPDATE" not in sql
    assert "UPDATE users" not in sql
    assert params[:9] == (
        str(expected_user_id),
        str(tenant_id),
        token_hash,
        "member@example.test",
        redeemed_at,
        str(expected_user_id),
        str(expected_user_id),
        str(expected_user_id),
        str(proposed_user_id),
    )


def test_invitation_issue_locks_active_admin_and_supersedes_pending_token():
    tenant_id = uuid4()
    inviter_id = uuid4()
    invitation_id = uuid4()
    expires_at = datetime.now(timezone.utc)
    invitation_row = {
        "id": invitation_id,
        "tenant_id": tenant_id,
        "email_normalized": "member@example.test",
        "role": "admin",
        "token_hash": "a" * 64,
        "invited_by_user_id": inviter_id,
        "expires_at": expires_at,
        "accepted_at": None,
        "revoked_at": None,
    }
    connection = CatalogConnection([
        Cursor(),
        Cursor(one={"id": tenant_id}),
        Cursor(rowcount=1),
        Cursor(one=invitation_row),
    ])
    catalog = HostedCatalog("postgresql://example", connect=Connections(connection))

    invitation = catalog.create_invitation(
        tenant_id,
        email="Member@example.test",
        role="admin",
        token_hash="a" * 64,
        invited_by_user_id=inviter_id,
        expires_at=expires_at,
        invitation_id=invitation_id,
    )

    assert invitation.id == invitation_id
    assert "pg_advisory_xact_lock" in connection.calls[1][0]
    assert "FOR UPDATE OF inviter" in connection.calls[2][0]
    assert "inviter.status = 'active'" in connection.calls[2][0]
    assert "inviter_user.disabled_at IS NULL" in connection.calls[2][0]
    assert "UPDATE invitations SET revoked_at" in connection.calls[3][0]
    assert connection.calls[3][1] == (str(tenant_id), "member@example.test")

    denied = CatalogConnection([Cursor(), Cursor(one=None)])
    denied_catalog = HostedCatalog(
        "postgresql://example", connect=Connections(denied)
    )
    with pytest.raises(CatalogConflict, match="active tenant administrator"):
        denied_catalog.create_invitation(
            tenant_id,
            email="member@example.test",
            role="observer",
            token_hash="b" * 64,
            invited_by_user_id=inviter_id,
            expires_at=expires_at,
        )


def test_membership_change_revokes_addressed_and_unauthorized_issued_invites():
    tenant_id = uuid4()
    user_id = uuid4()
    connection = CatalogConnection([
        Cursor(one={
            "tenant_id": tenant_id,
            "user_id": user_id,
            "role": "observer",
            "status": "active",
        }),
        Cursor(rowcount=3),
    ])
    catalog = HostedCatalog("postgresql://example", connect=Connections(connection))

    membership = catalog.update_membership(
        tenant_id, user_id, role="observer", enabled=True
    )

    assert membership == MembershipRecord(tenant_id, user_id, "observer", "active")
    revoke_sql, revoke_params = connection.calls[2]
    assert "UPDATE invitations AS i SET revoked_at" in revoke_sql
    assert "i.email_normalized = (SELECT u.email_normalized" in revoke_sql
    assert revoke_params == (str(tenant_id), str(user_id), True, str(user_id))


def test_login_throttle_reservation_locks_account_and_client_atomically():
    tenant_id = uuid4()
    current = datetime.now(timezone.utc)
    account_hash = "1" * 64
    client_hash = "2" * 64
    connection = CatalogConnection([
        Cursor(one={"id": tenant_id}),
        Cursor(),
        Cursor(),
        Cursor(rows=[]),
        Cursor(one={"id": 99}),
    ])
    catalog = HostedCatalog("postgresql://example", connect=Connections(connection))

    reservation = catalog.reserve_login_attempt(
        tenant_id,
        account_hash,
        client_hash,
        since=current - timedelta(hours=1),
        occurred_at=current,
        max_failures=5,
    )

    assert reservation.tenant_active is True
    assert reservation.reserved is True
    assert reservation.account_failures == (current,)
    assert reservation.client_account_failures == (current,)
    assert "FOR SHARE" not in connection.calls[1][0]
    lock_calls = [call for call in connection.calls if "pg_advisory_xact_lock" in call[0]]
    assert len(lock_calls) == 2
    reservation_sql, reservation_params = connection.calls[-1]
    assert "INSERT INTO auth_attempts" in reservation_sql
    assert reservation_params[1:3] == (account_hash, client_hash)


def test_run_status_requires_optional_live_lease_and_terminal_state_clears_it():
    tenant_id = uuid4()
    run_id = uuid4()
    owner_id = uuid4()
    lease_token = uuid4()
    connection = CatalogConnection([
        Cursor(one=run_row(tenant_id, run_id, owner_id, status="stopped"))
    ])
    catalog = HostedCatalog("postgresql://example", connect=Connections(connection))

    record = catalog.update_run_status(
        tenant_id, run_id, "stopped", lease_token=lease_token
    )

    assert record is not None and record.status == "stopped"
    sql, params = connection.calls[1]
    assert "writer_lease_token = NULL" in sql
    assert "writer_lease_token = %s" in sql
    assert "writer_lease_expires_at > clock_timestamp()" in sql
    assert params == ("stopped", str(tenant_id), str(run_id), str(lease_token))


def test_restart_discovery_returns_scope_only_then_reads_each_run_under_rls():
    tenant_id = uuid4()
    run_id = uuid4()
    owner_id = uuid4()
    discovery = CatalogConnection([
        Cursor(rows=[{"tenant_id": tenant_id, "run_id": run_id}])
    ])
    scoped = CatalogConnection([
        Cursor(one=run_row(tenant_id, run_id, owner_id))
    ])
    catalog = HostedCatalog(
        "postgresql://example", connect=Connections(discovery, scoped)
    )

    records = catalog.list_active_runs()

    assert len(records) == 1 and records[0].id == run_id
    assert discovery.calls == [("SELECT tenant_id, run_id FROM hosted_active_run_scopes()", ())]
    assert scoped.calls[0] == (TENANT_CONTEXT_SQL, (str(tenant_id),))
    assert "tenant_id = %s AND id = %s" in scoped.calls[1][0]


def test_hosted_example_resolves_dsn_from_environment_and_enforces_host_cookie():
    from psycopg.conninfo import conninfo_to_dict

    config = load_hosted_config(
        "config/hosted.example.yaml",
        environ={
            "AGENT_ECONOMY_HOSTED_DATABASE_URL": "postgresql://runtime@example/control",
            "AGENT_ECONOMY_HOSTED_DATABASE_PASSWORD": "web @:/% # password",
            "AGENT_ECONOMY_HOSTED_SUPERVISOR_DATABASE_URL": "postgresql://supervisor@example/control",
            "AGENT_ECONOMY_HOSTED_SUPERVISOR_DATABASE_PASSWORD": "super @:/% # password",
        },
    )
    resolved = conninfo_to_dict(config.database.dsn)
    assert resolved["user"] == "runtime"
    assert resolved["host"] == "example"
    assert resolved["dbname"] == "control"
    assert resolved["password"] == "web @:/% # password"
    assert config.session_cookie_name == "__Host-ae_session"


def test_database_password_env_uses_libpq_safe_conninfo_escaping():
    from psycopg.conninfo import conninfo_to_dict

    password = "p@ss:/% # with spaces and 'quotes'"
    config = load_hosted_config(
        "config/hosted.example.yaml",
        environ={
            "AGENT_ECONOMY_HOSTED_DATABASE_URL": "postgresql://runtime@example/control",
            "AGENT_ECONOMY_HOSTED_DATABASE_PASSWORD": password,
            "AGENT_ECONOMY_HOSTED_SUPERVISOR_DATABASE_URL": "postgresql://supervisor@example/control",
            "AGENT_ECONOMY_HOSTED_SUPERVISOR_DATABASE_PASSWORD": password,
        },
    )

    assert conninfo_to_dict(config.database.dsn)["password"] == password
    assert conninfo_to_dict(config.database.supervisor_dsn)["password"] == password
    assert password not in repr(config) + repr(config.redacted())

    with pytest.raises(ValueError, match="must be __Host-ae_session"):
        HostedConfig(
            enabled=True,
            database=HostedDatabaseConfig("postgresql://example/control"),
            public_base_url="https://economy.example",
            session_cookie_name="session",
        )


def test_hosted_config_rejects_lookalike_localhost_and_non_boolean_enablement(tmp_path):
    with pytest.raises(ValueError, match="HTTPS outside localhost"):
        HostedConfig(
            enabled=True,
            database=HostedDatabaseConfig("postgresql://example/control"),
            public_base_url="http://localhost.evil.example",
        )

    path = tmp_path / "hosted.yaml"
    path.write_text(
        "enabled: 'false'\npublic_base_url: https://example.test\n"
        "database:\n  dsn_env: HOSTED_TEST_DSN\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="enabled must be a boolean"):
        load_hosted_config(path, environ={"HOSTED_TEST_DSN": "postgresql://example/control"})

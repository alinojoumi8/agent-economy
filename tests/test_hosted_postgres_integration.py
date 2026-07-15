from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import os
from uuid import uuid4

import pytest

from hosted.catalog import HostedCatalog, TENANT_CONTEXT_SQL
from hosted.catalog_auth import CatalogAuthService
from hosted.migrations import migrate
from hosted.security import hash_password


ADMIN_DSN = os.environ.get("AGENT_ECONOMY_TEST_POSTGRES_ADMIN_DSN", "")
RUNTIME_DSN = os.environ.get("AGENT_ECONOMY_TEST_POSTGRES_RUNTIME_DSN", "")
SUPERVISOR_DSN = os.environ.get("AGENT_ECONOMY_TEST_POSTGRES_SUPERVISOR_DSN", "")

pytestmark = pytest.mark.skipif(
    not (ADMIN_DSN and RUNTIME_DSN and SUPERVISOR_DSN),
    reason="hosted PostgreSQL integration DSNs are not configured",
)


@pytest.fixture(scope="module")
def catalog() -> HostedCatalog:
    report = migrate(
        ADMIN_DSN,
        runtime_role="agent_economy_app",
        supervisor_role="agent_economy_supervisor",
    )
    assert report.current_version >= 1
    # The second invocation proves migration history and checksums are stable.
    assert migrate(
        ADMIN_DSN,
        runtime_role="agent_economy_app",
        supervisor_role="agent_economy_supervisor",
    ).applied_versions == ()
    return HostedCatalog(
        RUNTIME_DSN,
        expected_role="agent_economy_app",
        capability="web",
    )


@pytest.fixture(scope="module")
def supervisor_catalog(catalog: HostedCatalog) -> HostedCatalog:
    catalog.assert_runtime_security()
    supervisor = HostedCatalog(
        SUPERVISOR_DSN,
        expected_role="agent_economy_supervisor",
        capability="supervisor",
    )
    supervisor.assert_runtime_security()
    return supervisor


@pytest.fixture(scope="module")
def two_tenants(catalog: HostedCatalog, supervisor_catalog: HostedCatalog):
    suffix = uuid4().hex[:12]
    password_hash = hash_password(
        "integration password with enough length",
        random_bytes=lambda size: b"i" * size,
    )
    bootstrap = HostedCatalog(ADMIN_DSN)
    tenant_a, admin_a, _ = bootstrap.create_tenant_with_admin(
        slug=f"tenant-a-{suffix}",
        tenant_name="Tenant A",
        email=f"admin-a-{suffix}@example.test",
        user_name="Admin A",
        password_hash=password_hash,
    )
    tenant_b, admin_b, _ = bootstrap.create_tenant_with_admin(
        slug=f"tenant-b-{suffix}",
        tenant_name="Tenant B",
        email=f"admin-b-{suffix}@example.test",
        user_name="Admin B",
        password_hash=password_hash,
    )
    run_a = supervisor_catalog.create_run(
        tenant_a.id,
        owner_user_id=admin_a.id,
        run_key=f"run-a-{suffix}",
        display_name="Run A",
        schema_version=11,
        engine_semantics_version=7,
    )
    run_b = supervisor_catalog.create_run(
        tenant_b.id,
        owner_user_id=admin_b.id,
        run_key=f"run-b-{suffix}",
        display_name="Run B",
        schema_version=11,
        engine_semantics_version=7,
    )
    return (tenant_a, admin_a, run_a), (tenant_b, admin_b, run_b)


def test_runtime_role_is_non_privileged_and_rls_defaults_to_deny(two_tenants) -> None:
    import psycopg

    (tenant_a, _admin_a, run_a), (tenant_b, _admin_b, run_b) = two_tenants
    with psycopg.connect(RUNTIME_DSN) as connection:
        role = connection.execute(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
        assert role == (False, False)
        assert connection.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
        connection.execute(TENANT_CONTEXT_SQL, (str(tenant_a.id),))
        visible = connection.execute(
            "SELECT id FROM runs ORDER BY id"
        ).fetchall()
        assert visible == [(run_a.id,)]
        assert connection.execute(
            "SELECT id FROM runs WHERE id=%s", (str(run_b.id),)
        ).fetchone() is None
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT * FROM hosted_active_run_scopes()")
        connection.rollback()

    with psycopg.connect(RUNTIME_DSN) as connection:
        connection.execute(TENANT_CONTEXT_SQL, (str(tenant_a.id),))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "INSERT INTO runs "
                "(id,tenant_id,owner_user_id,run_key,display_name,status,"
                "schema_version,engine_semantics_version) "
                "VALUES (%s,%s,%s,%s,%s,'created',11,7)",
                (
                    str(uuid4()), str(tenant_b.id), str(_admin_a.id),
                    f"foreign-{uuid4().hex}", "Forbidden foreign run",
                ),
            )

    # The catalog repeats tenant scope for every transaction; a foreign UUID
    # is indistinguishable from a missing one.
    catalog = HostedCatalog(RUNTIME_DSN)
    assert catalog.get_run(tenant_a.id, run_a.id) == run_a
    assert catalog.get_run(tenant_a.id, run_b.id) is None


def test_restart_discovery_returns_only_scoped_records(two_tenants) -> None:
    catalog = HostedCatalog(SUPERVISOR_DSN)
    (tenant_a, _admin_a, run_a), (tenant_b, _admin_b, run_b) = two_tenants
    catalog.update_run_status(tenant_a.id, run_a.id, "paused")
    catalog.update_run_status(tenant_b.id, run_b.id, "running")

    active = catalog.list_active_runs()
    active_ids = {record.id for record in active}
    assert {run_a.id, run_b.id} <= active_ids
    assert catalog.list_runs(tenant_a.id) == (catalog.get_run(tenant_a.id, run_a.id),)
    assert catalog.list_runs(tenant_b.id) == (catalog.get_run(tenant_b.id, run_b.id),)


def test_concurrent_tenant_reads_do_not_bleed(two_tenants) -> None:
    (tenant_a, _admin_a, run_a), (tenant_b, _admin_b, run_b) = two_tenants

    def probe(tenant_id, own_id, foreign_id) -> tuple[bool, bool, int]:
        catalog = HostedCatalog(RUNTIME_DSN)
        own = catalog.get_run(tenant_id, own_id)
        foreign = catalog.get_run(tenant_id, foreign_id)
        return own is not None, foreign is not None, len(catalog.list_runs(tenant_id))

    work = [
        (tenant_a.id, run_a.id, run_b.id) if index % 2 == 0
        else (tenant_b.id, run_b.id, run_a.id)
        for index in range(40)
    ]
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda args: probe(*args), work))
    assert results == [(True, False, 1)] * len(work)


def test_expired_session_lookup_fails_closed(two_tenants) -> None:
    catalog = HostedCatalog(RUNTIME_DSN)
    (tenant_a, admin_a, _run_a), _ = two_tenants
    now = datetime.now(timezone.utc)
    token_hash = hashlib.sha256(uuid4().bytes).hexdigest()
    csrf_hash = hashlib.sha256(uuid4().bytes).hexdigest()
    session = catalog.create_session(
        tenant_a.id,
        admin_a.id,
        token_hash=token_hash,
        csrf_secret_hash=csrf_hash,
        expires_at=now + timedelta(minutes=5),
    )
    assert catalog.lookup_session_by_hash(session.token_hash) is not None
    assert catalog.revoke_session_by_hash(session.token_hash) is True
    assert catalog.lookup_session_by_hash(session.token_hash) is None


def test_runtime_role_can_complete_login_and_append_redacted_audit(two_tenants) -> None:
    catalog = HostedCatalog(RUNTIME_DSN)
    (tenant_a, admin_a, _run_a), _ = two_tenants
    now = datetime.now(timezone.utc)
    auth = CatalogAuthService(catalog)

    credentials = auth.login(
        tenant_id=tenant_a.id,
        email=admin_a.email_normalized,
        password="integration password with enough length",
        client_key=f"integration-{uuid4().hex}",
        now=now,
    )
    authenticated = auth.authenticate_session(credentials.session_token, now=now)

    assert str(authenticated.user.user_id) == str(admin_a.id)
    assert str(authenticated.session.tenant_id) == str(tenant_a.id)

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from uuid import UUID

import hosted.config as hosted_config_module

from hosted.catalog import HostedCatalog
from run_config import load_config
from tests.hosted_catalog_test_support import CatalogConnection, Connections, Cursor


NOW = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)
TENANT_ID = UUID("10000000-0000-4000-8000-000000000001")
OWNER_ID = UUID("20000000-0000-4000-8000-000000000002")
RUN_ID = UUID("30000000-0000-4000-8000-000000000003")
CONNECTION_ID = UUID("40000000-0000-4000-8000-000000000004")
CREDENTIAL_ID = UUID("50000000-0000-4000-8000-000000000005")


def agent_row(*, status: str = "active"):
    return {
        "id": CONNECTION_ID,
        "tenant_id": TENANT_ID,
        "owner_user_id": OWNER_ID,
        "run_id": RUN_ID,
        "run_connection_id": CONNECTION_ID,
        "display_name": "Outside observer",
        "biography": "",
        "preferred_occupation": "",
        "tier": "observer",
        "scopes": ["world.read"],
        "status": status,
        "actor_id": None,
        "last_seen_at": None,
        "lease_expires_at": None,
        "created_at": NOW,
    }


def credential_row():
    return {
        "id": CREDENTIAL_ID,
        "tenant_id": TENANT_ID,
        "external_agent_id": CONNECTION_ID,
        "kind": "personal",
        "token_hash": "a" * 64,
        "scopes": ["world.read"],
        "audience": "agent-economy",
        "expires_at": NOW + timedelta(days=30),
        "revoked_at": None,
        "created_at": NOW,
    }


def test_default_hosted_profiles_include_external_agent_compatible_world():
    profiles = hosted_config_module.default_hosted_profiles()

    assert "world-os-external" in profiles
    config = load_config(profiles["world-os-external"])
    assert int(config["engine_semantics_version"]) >= 9
    assert config["external_gateway"]["enabled"] is True
    assert int(load_config(profiles["v2"])["engine_semantics_version"]) == 7


def test_external_agent_creation_keeps_security_audit_insert_only():
    class InsertOnlyAuditConnection(CatalogConnection):
        def execute(self, sql, params=()):
            if "external_security_audit_events" in sql:
                audit_cte = sql.split("external_security_audit_events", 1)[1]
                if "RETURNING id" in audit_cte:
                    raise PermissionError("audit INSERT attempted to read a protected column")
            return super().execute(sql, params)

    connection = InsertOnlyAuditConnection(responses=(
        Cursor(),
        Cursor(one={"role": "admin", "max_external_agents_per_run": 100}),
        Cursor(one={"count": 0}),
        Cursor(one=agent_row()),
        Cursor(one=credential_row()),
    ))
    catalog = HostedCatalog(
        "postgresql://example/control", connect=Connections(connection)
    )

    created_agent, created_credential = catalog.create_external_agent_with_credential(
        TENANT_ID,
        owner_user_id=OWNER_ID,
        run_id=RUN_ID,
        run_connection_id=CONNECTION_ID,
        external_agent_id=CONNECTION_ID,
        credential_id=CREDENTIAL_ID,
        display_name="Outside observer",
        biography="",
        preferred_occupation="",
        tier="observer",
        scopes=["world.read"],
        token_hash="a" * 64,
        credential_expires_at=NOW + timedelta(days=30),
    )

    assert created_agent.id == CONNECTION_ID
    assert created_credential.id == CREDENTIAL_ID
    create_sql = next(
        sql for sql, _params in connection.calls if "WITH created_agent AS" in sql
    )
    audit_cte = create_sql.split("external_security_audit_events", 1)[1]
    assert "FROM created_agent RETURNING 1" in audit_cte


def test_list_external_agents_for_run_is_tenant_and_run_scoped():
    connection = CatalogConnection(responses=(Cursor(rows=(agent_row(),)),))
    catalog = HostedCatalog(
        "postgresql://example/control", connect=Connections(connection)
    )

    records = catalog.list_external_agents_for_run(TENANT_ID, RUN_ID)

    assert len(records) == 1 and records[0].id == CONNECTION_ID
    query, params = next(
        call for call in connection.calls if "FROM external_agents" in call[0]
    )
    assert "tenant_id=%s AND run_id=%s" in query
    assert params == (str(TENANT_ID), str(RUN_ID))


def test_admin_credential_rotation_authorizes_cross_owner_and_audits_it():
    prior_id = UUID("60000000-0000-4000-8000-000000000006")
    connection = CatalogConnection(responses=(
        Cursor(one={"id": CONNECTION_ID}),
        Cursor(one={"id": prior_id}),
        Cursor(one=credential_row()),
    ))
    catalog = HostedCatalog(
        "postgresql://example/control", connect=Connections(connection)
    )

    result = catalog.replace_external_personal_credential(
        TENANT_ID,
        CONNECTION_ID,
        owner_user_id=OWNER_ID,
        token_hash="a" * 64,
        scopes=["world.read"],
        audience="agent-economy",
        expires_at=NOW + timedelta(days=30),
        credential_id=CREDENTIAL_ID,
        admin=True,
    )

    assert result.id == CREDENTIAL_ID
    authorization_sql, authorization_params = next(
        call for call in connection.calls if "FOR UPDATE" in call[0]
    )
    assert "(%s OR owner_user_id=%s)" in authorization_sql
    assert authorization_params == (
        str(TENANT_ID), str(CONNECTION_ID), True, str(OWNER_ID)
    )
    audit_params = next(
        params for sql, params in connection.calls
        if "'credential.rotated'" in sql
    )
    assert json.loads(audit_params[-1]) == {"admin": True}

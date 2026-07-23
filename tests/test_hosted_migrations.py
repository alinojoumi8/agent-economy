from contextlib import contextmanager
from pathlib import Path

import pytest

from hosted.migrations import (
    MigrationError,
    TENANT_TABLES,
    load_migrations,
    migrate_connection,
    rotate_database_passwords_connection,
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


class MigrationConnection:
    def __init__(self, *, role=(False, False), initial_history=(), rls=True):
        self.role = role
        self.history = [tuple(row) for row in initial_history]
        self.rls = rls
        self.calls = []
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
        params = tuple(params)
        rendered = sql if isinstance(sql, str) else sql.as_string()
        self.calls.append((rendered, params))
        compact = " ".join(rendered.split())
        if compact.startswith("SELECT version, name, checksum_sha256"):
            return Cursor(rows=self.history)
        if compact.startswith("INSERT INTO schema_migrations"):
            self.history.append(params)
            return Cursor(rowcount=1)
        if "FROM pg_catalog.pg_roles" in compact:
            return Cursor(one={"rolsuper": self.role[0], "rolbypassrls": self.role[1]})
        if "FROM pg_catalog.pg_class" in compact:
            rows = [
                {
                    "relname": table,
                    "relrowsecurity": self.rls,
                    "relforcerowsecurity": self.rls,
                }
                for table in TENANT_TABLES
            ]
            return Cursor(rows=rows)
        return Cursor()


class RotationConnection(MigrationConnection):
    class PgConnection:
        def __init__(self):
            self.calls = []

        def encrypt_password(self, password, user, algorithm):
            self.calls.append((password, user, algorithm))
            return b"SCRAM-SHA-256$4096:test-salt$stored-key:server-key"

    def __init__(self):
        super().__init__()
        self.pgconn = self.PgConnection()

    def execute(self, sql, params=()):
        rendered = sql if isinstance(sql, str) else sql.as_string()
        if "SELECT current_user" in " ".join(rendered.split()):
            self.calls.append((rendered, tuple(params)))
            return Cursor(one={"current_user": "postgres"})
        return super().execute(sql, params)


def test_control_plane_migration_declares_forced_rls_and_append_only_audit():
    migrations = load_migrations()
    migration = migrations[0]
    external = migrations[1]
    combined_sql = "\n".join(item.sql for item in migrations)

    assert migration.version == 1
    assert migration.name == "control_plane"
    assert external.version == 2
    assert external.name == "external_agents"
    assert len(migration.checksum_sha256) == 64
    for table in TENANT_TABLES:
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in combined_sql
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in combined_sql
    assert "current_setting('app.tenant_id', true)" in migration.sql
    assert "reject_audit_log_mutation" in migration.sql
    assert "CHECK (role IN ('observer', 'agent_owner', 'admin'))" in external.sql
    assert "CREATE TABLE external_oauth_clients" in external.sql
    assert "redirect_uris text[]" in external.sql
    assert "SECURITY DEFINER" in migration.sql
    assert "hosted_active_session_tenant" in migration.sql
    assert "hosted_active_invitation_tenant" in migration.sql
    assert "hosted_active_run_scopes" in migration.sql
    assert "REVOKE ALL ON FUNCTION hosted_active_session_tenant" in migration.sql
    assert "invitations_one_pending_per_email_idx" in migration.sql
    assert "inviter.status = 'active'" in migration.sql
    assert "inviter.role = 'admin'" in migration.sql
    assert "inviter_user.disabled_at IS NULL" in migration.sql
    assert "t.status = 'active'" in migration.sql
    assert "m.status = 'active'" in migration.sql


def test_external_agent_migration_declares_tenant_scoped_run_key_before_fks():
    external = load_migrations()[1]
    compact = " ".join(external.sql.split())
    unique_key = (
        "ALTER TABLE runs ADD CONSTRAINT runs_tenant_id_id_key "
        "UNIQUE (tenant_id, id)"
    )
    tenant_fk = (
        "FOREIGN KEY (tenant_id, run_id) "
        "REFERENCES runs(tenant_id, id)"
    )

    assert unique_key in compact
    assert compact.index(unique_key) < compact.index(tenant_fk)


def test_migration_identity_is_stable_across_lf_and_crlf_checkouts(tmp_path):
    lf_dir = tmp_path / "lf"
    crlf_dir = tmp_path / "crlf"
    lf_dir.mkdir()
    crlf_dir.mkdir()
    source = b"CREATE TABLE example (id integer);\nSELECT 1;\n"
    (lf_dir / "001_example.sql").write_bytes(source)
    (crlf_dir / "001_example.sql").write_bytes(source.replace(b"\n", b"\r\n"))

    lf = load_migrations(lf_dir)[0]
    crlf = load_migrations(crlf_dir)[0]
    assert lf.checksum_sha256 == crlf.checksum_sha256
    assert lf.sql == crlf.sql == source.decode("utf-8")


def test_migration_runner_is_ordered_atomic_and_idempotent():
    connection = MigrationConnection()

    first = migrate_connection(connection, runtime_role="agent_economy_app")
    assert first.current_version == 2
    assert first.applied_versions == (1, 2)
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert "pg_advisory_xact_lock" in connection.calls[0][0]

    second = migrate_connection(connection, runtime_role="agent_economy_app")
    assert second.current_version == 2
    assert second.applied_versions == ()
    migration_script_calls = [sql for sql, _ in connection.calls if "CREATE TABLE tenants" in sql]
    assert len(migration_script_calls) == 1
    grants = "\n".join(sql for sql, _ in connection.calls if sql.startswith("GRANT"))
    assert "hosted_active_run_scopes() TO \"agent_economy_supervisor\"" in grants
    assert "hosted_active_run_scopes() TO \"agent_economy_app\"" not in grants
    assert "hosted_active_session_tenant(text)" in grants
    assert 'SELECT (id) ON TABLE audit_log TO "agent_economy_app"' in grants


def test_database_password_rotation_is_atomic_parameterized_and_redacted():
    connection = RotationConnection()
    report = rotate_database_passwords_connection(
        connection,
        runtime_role="agent_economy_app",
        runtime_password="runtime-secret-with-length",
        supervisor_role="agent_economy_supervisor",
        supervisor_password="supervisor-secret-with-length",
        administrator_password="administrator-secret-with-length",
    )

    assert connection.commits == 1
    alters = [(sql, params) for sql, params in connection.calls if sql.startswith("ALTER ROLE")]
    assert [sql.split(" PASSWORD", 1)[0] for sql, _params in alters] == [
        'ALTER ROLE "agent_economy_app"',
        'ALTER ROLE "agent_economy_supervisor"',
        'ALTER ROLE "postgres"',
    ]
    assert all(params == () for _sql, params in alters)
    assert all("SCRAM-SHA-256$" in sql for sql, _params in alters)
    assert [call[1] for call in connection.pgconn.calls] == [
        b"agent_economy_app",
        b"agent_economy_supervisor",
        b"postgres",
    ]
    rendered = repr(report) + "\n".join(sql for sql, _params in connection.calls)
    assert "secret-with-length" not in rendered


def test_database_password_rotation_rejects_reuse_before_writes():
    connection = RotationConnection()
    with pytest.raises(MigrationError, match="must be distinct"):
        rotate_database_passwords_connection(
            connection,
            runtime_role="agent_economy_app",
            runtime_password="same-secret-with-length",
            supervisor_role="agent_economy_supervisor",
            supervisor_password="same-secret-with-length",
            administrator_password="administrator-secret-with-length",
        )
    assert connection.calls == []


@pytest.mark.parametrize("role", [(True, False), (False, True), (True, True)])
def test_migration_runner_rejects_runtime_roles_that_bypass_rls(role):
    connection = MigrationConnection(role=role)

    with pytest.raises(MigrationError, match="NOSUPERUSER and NOBYPASSRLS"):
        migrate_connection(connection, runtime_role="agent_economy_app")

    assert connection.commits == 0
    assert connection.rollbacks == 1


def test_unknown_or_changed_database_history_fails_closed():
    migration = load_migrations()[0]
    future = MigrationConnection(initial_history=[(3, "future", "0" * 64)])
    with pytest.raises(MigrationError, match="unknown future"):
        migrate_connection(future, runtime_role="agent_economy_app")

    changed = MigrationConnection(
        initial_history=[(1, migration.name, "f" * 64)]
    )
    with pytest.raises(MigrationError, match="does not exactly match"):
        migrate_connection(changed, runtime_role="agent_economy_app")


def test_missing_or_unforced_rls_fails_the_migration_transaction():
    connection = MigrationConnection(rls=False)
    with pytest.raises(MigrationError, match="enabled and forced row security"):
        migrate_connection(connection, runtime_role="agent_economy_app")
    assert connection.rollbacks == 1


def test_migration_files_must_be_a_contiguous_known_sequence(tmp_path: Path):
    (tmp_path / "002_second.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(MigrationError, match="contiguous"):
        load_migrations(tmp_path)

    (tmp_path / "notes.txt").write_text("not a migration", encoding="utf-8")
    with pytest.raises(MigrationError, match="unexpected migration filenames"):
        load_migrations(tmp_path)

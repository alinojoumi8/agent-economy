from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from engine.schema import SCHEMA_VERSION
from engine.store import Store
from hosted.artifacts import ArtifactIntegrityError, FilesystemArtifactStore
from hosted.cli import main
from hosted.config import (
    HostedArtifactConfig,
    HostedConfig,
    HostedDatabaseConfig,
    HostedRuntimeConfig,
    create_artifact_store,
    load_hosted_config,
    artifact_readiness_check,
)
from hosted.ops import (
    HostedOperationError,
    HostedOperations,
    bootstrap_initial_tenant,
    run_database_path,
)


PASSWORD = "a very secret bootstrap password"


def config(tmp_path: Path) -> HostedConfig:
    return HostedConfig(
        enabled=True,
        database=HostedDatabaseConfig("postgresql://user:database-secret@example/control"),
        public_base_url="https://economy.example",
        artifacts=HostedArtifactConfig(
            backend="filesystem", filesystem_root=tmp_path / "artifacts"
        ),
        runtime=HostedRuntimeConfig(
            run_directory=tmp_path / "runs",
            snapshot_directory=tmp_path / "staging",
        ),
    )


class BootstrapCatalog:
    def __init__(self):
        self.membership = None
        self.user = None
        self.password_hash = None

    def get_membership(self, tenant_id, user_id):
        return self.membership

    def get_user_by_id(self, user_id):
        return self.user

    def create_tenant_with_admin(self, **kwargs):
        self.password_hash = kwargs["password_hash"]
        self.user = SimpleNamespace(
            id=kwargs["user_id"], email_normalized=kwargs["email"],
            display_name=kwargs["user_name"],
        )
        self.membership = SimpleNamespace(
            tenant_id=kwargs["tenant_id"], user_id=kwargs["user_id"],
            role="admin", status="active",
        )
        return SimpleNamespace(id=kwargs["tenant_id"]), self.user, self.membership


class SnapshotCatalog:
    def __init__(self, record):
        self.record = record
        self.token = uuid4()
        self.pointer_updates = []
        self.releases = 0
        self.renewed = True

    def get_run(self, tenant_id, run_id):
        if str(tenant_id) == str(self.record.tenant_id) and str(run_id) == str(self.record.id):
            return self.record
        return None

    def list_active_runs(self):
        return (self.record,)

    def acquire_writer_lease(self, tenant_id, run_id, **kwargs):
        return self.token

    def update_snapshot_pointer(self, tenant_id, run_id, **kwargs):
        self.pointer_updates.append(kwargs)
        self.record.snapshot_object_key = kwargs["object_key"]
        self.record.snapshot_sha256 = kwargs["sha256"]
        self.record.snapshot_size_bytes = kwargs["size_bytes"]
        return True

    def renew_writer_lease(self, tenant_id, run_id, **kwargs):
        return self.renewed and kwargs.get("token") == self.token

    def release_writer_lease(self, tenant_id, run_id, **kwargs):
        self.releases += 1
        return True


def make_run_database(cfg: HostedConfig):
    record = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        run_key="world_run_1",
        schema_version=SCHEMA_VERSION,
        status="paused",
        snapshot_object_key=None,
        snapshot_sha256=None,
        snapshot_size_bytes=None,
    )
    path = run_database_path(cfg, record)
    store = Store(str(path))
    store.init_run_meta(record.run_key, 7, {"engine_semantics_version": 7})
    store.close()
    return record, path


def test_s3_config_resolves_exact_env_references_and_never_serializes_secrets():
    environment = {
        "AGENT_ECONOMY_PUBLIC_BASE_URL": "https://hosted.example",
        "AGENT_ECONOMY_HOSTED_DATABASE_URL": "postgresql://app@db/control",
        "AGENT_ECONOMY_HOSTED_DATABASE_PASSWORD": "dsn-secret",
        "AGENT_ECONOMY_HOSTED_SUPERVISOR_DATABASE_URL": "postgresql://supervisor@db/control",
        "AGENT_ECONOMY_HOSTED_SUPERVISOR_DATABASE_PASSWORD": "supervisor-secret",
        "AGENT_ECONOMY_S3_ENDPOINT_URL": "http://minio:9000",
        "AWS_ACCESS_KEY_ID": "access-secret",
        "AWS_SECRET_ACCESS_KEY": "object-secret",
    }
    loaded = load_hosted_config("config/hosted.docker.yaml", environ=environment)

    rendered = repr(loaded) + repr(loaded.redacted())
    for secret in ("dsn-secret", "supervisor-secret", "access-secret", "object-secret"):
        assert secret not in rendered
    assert loaded.public_base_url == "https://hosted.example"
    assert loaded.artifacts.backend == "s3"
    store = create_artifact_store(loaded, client=None)
    wire = store._client_options["config"]
    assert wire.connect_timeout == 10
    assert wire.read_timeout == 10
    assert wire.retries["mode"] == "standard"
    assert wire.retries["max_attempts"] == 2
    assert wire.s3["addressing_style"] == "path"


def test_serve_bounds_uvicorn_graceful_shutdown(tmp_path):
    loaded = config(tmp_path)
    application = object()
    observed = {}

    def runner(app, **kwargs):
        observed["app"] = app
        observed.update(kwargs)

    result = main(
        ["serve", "--config", "unused.yaml", "--host", "127.0.0.1", "--port", "9000"],
        config_loader=lambda *_args, **_kwargs: loaded,
        application_factory=lambda _config: application,
        uvicorn_runner=runner,
    )

    assert result == 0
    assert observed == {
        "app": application,
        "host": "127.0.0.1",
        "port": 9000,
        "timeout_graceful_shutdown": loaded.runtime.shutdown_grace_seconds,
    }


def test_cli_rotates_database_passwords_without_emitting_secrets(tmp_path):
    loaded = config(tmp_path)
    output = StringIO()
    observed = {}

    def rotate(dsn, **kwargs):
        observed["dsn"] = dsn
        observed.update(kwargs)
        return SimpleNamespace(
            administrator_role="postgres",
            runtime_role="agent_economy_app",
            supervisor_role="agent_economy_supervisor",
        )

    environment = {
        "APP_DATABASE_PASSWORD": "runtime-secret-with-length",
        "SUPERVISOR_DATABASE_PASSWORD": "supervisor-secret-with-length",
        "AGENT_ECONOMY_NEW_POSTGRES_PASSWORD": "administrator-secret-with-length",
    }
    result = main(
        ["rotate-database-passwords", "--config", "unused.yaml"],
        environ=environment,
        stdout=output,
        config_loader=lambda *_args, **_kwargs: loaded,
        credential_rotator=rotate,
    )

    assert result == 0
    assert observed["runtime_password"] == environment["APP_DATABASE_PASSWORD"]
    assert observed["supervisor_password"] == environment["SUPERVISOR_DATABASE_PASSWORD"]
    assert observed["administrator_password"] == environment[
        "AGENT_ECONOMY_NEW_POSTGRES_PASSWORD"
    ]
    rendered = output.getvalue()
    assert json.loads(rendered)["rotated_roles"] == [
        "postgres",
        "agent_economy_app",
        "agent_economy_supervisor",
    ]
    assert not any(secret in rendered for secret in environment.values())


def test_scoped_s3_readiness_uses_location_not_bucket_wide_head():
    class Client:
        def __init__(self):
            self.calls = []

        def get_bucket_location(self, **kwargs):
            self.calls.append(("location", kwargs))
            return {"LocationConstraint": "us-east-1"}

        def head_bucket(self, **_kwargs):
            raise AssertionError("scoped credentials must not require HeadBucket")

    client = Client()
    store = SimpleNamespace(_client=client, bucket="scoped-bucket")
    assert artifact_readiness_check(store) is True
    assert client.calls == [("location", {"Bucket": "scoped-bucket"})]


def test_config_rejects_partial_substitution_literal_secrets_and_insecure_url(tmp_path):
    base = (
        "enabled: true\n"
        "public_base_url: ${PUBLIC_URL}/suffix\n"
        "database:\n  dsn_env: DATABASE_URL\n"
        "artifacts:\n  backend: filesystem\n  root: C:/safe/artifacts\n"
        "runtime:\n  run_directory: C:/safe/runs\n  snapshot_directory: C:/safe/snapshots\n"
    )
    path = tmp_path / "hosted.yaml"
    path.write_text(base, encoding="utf-8")
    with pytest.raises(ValueError, match="exact .*ENV_VAR"):
        load_hosted_config(
            path,
            environ={"PUBLIC_URL": "https://example", "DATABASE_URL": "postgresql://db"},
        )

    path.write_text(base.replace("${PUBLIC_URL}/suffix", "http://example.com").replace(
        "dsn_env: DATABASE_URL", "dsn: postgresql://user:secret@db/control"
    ), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown database config fields"):
        load_hosted_config(path, environ={"DATABASE_URL": "postgresql://db"})

    path.write_text(base.replace("${PUBLIC_URL}/suffix", "http://example.com"), encoding="utf-8")
    with pytest.raises(ValueError, match="HTTPS outside localhost"):
        load_hosted_config(path, environ={"DATABASE_URL": "postgresql://db"})

    path.write_text(base.replace("${PUBLIC_URL}/suffix", "https://example.com/private"), encoding="utf-8")
    with pytest.raises(ValueError, match="exact origin"):
        load_hosted_config(path, environ={"DATABASE_URL": "postgresql://db"})


def test_bootstrap_is_deterministic_idempotent_and_never_persists_raw_password():
    catalog = BootstrapCatalog()
    first = bootstrap_initial_tenant(
        catalog,
        tenant_slug="initial-tenant",
        tenant_name="Initial Tenant",
        admin_email="admin@example.com",
        admin_name="Administrator",
        password=PASSWORD,
    )
    second = bootstrap_initial_tenant(
        catalog,
        tenant_slug="initial-tenant",
        tenant_name="Initial Tenant",
        admin_email="admin@example.com",
        admin_name="Administrator",
        password=PASSWORD,
    )

    assert first.created is True and second.created is False
    assert (first.tenant_id, first.user_id) == (second.tenant_id, second.user_id)
    assert catalog.password_hash != PASSWORD
    assert PASSWORD not in repr(first) + repr(second) + repr(catalog.password_hash)

    catalog.membership.role = "observer"
    with pytest.raises(HostedOperationError, match="does not match"):
        bootstrap_initial_tenant(
            catalog,
            tenant_slug="initial-tenant",
            tenant_name="Initial Tenant",
            admin_email="admin@example.com",
            admin_name="Administrator",
            password=PASSWORD,
        )


def test_snapshot_publish_verify_restore_and_checksum_failure(tmp_path):
    cfg = config(tmp_path)
    record, database = make_run_database(cfg)
    catalog = SnapshotCatalog(record)
    artifact_store = FilesystemArtifactStore(cfg.artifacts.filesystem_root)
    operations = HostedOperations(cfg, catalog, artifact_store, lease_owner="test-ops")

    result = operations.snapshot_run(record.tenant_id, record.id)
    assert result.metadata.key == record.snapshot_object_key
    assert catalog.pointer_updates and catalog.releases == 1
    verified = operations.verify_snapshot(record.tenant_id, record.id)
    assert verified.sha256 == record.snapshot_sha256
    assert verified.schema_version == SCHEMA_VERSION

    database.unlink()
    restored = operations.restore_snapshot(record.tenant_id, record.id)
    assert restored.path == database and database.is_file()
    with pytest.raises(HostedOperationError, match="explicit replace"):
        operations.restore_snapshot(record.tenant_id, record.id)

    artifact_dir = artifact_store._artifact_dir(record.snapshot_object_key)
    payload = artifact_dir / artifact_store._PAYLOAD_NAME
    with payload.open("r+b") as handle:
        handle.seek(0)
        handle.write(b"corrupt")
    with pytest.raises(ArtifactIntegrityError):
        operations.verify_snapshot(record.tenant_id, record.id)


def test_restore_never_publishes_when_lease_expires_after_verification(tmp_path):
    cfg = config(tmp_path)
    record, database = make_run_database(cfg)
    catalog = SnapshotCatalog(record)
    artifact_store = FilesystemArtifactStore(cfg.artifacts.filesystem_root)
    operations = HostedOperations(cfg, catalog, artifact_store, lease_owner="test-ops")
    operations.snapshot_run(record.tenant_id, record.id)

    original = database.read_bytes()
    catalog.renewed = False
    with pytest.raises(HostedOperationError, match="expired before restore publication"):
        operations.restore_snapshot(record.tenant_id, record.id, replace=True)

    assert database.read_bytes() == original
    assert catalog.releases == 2  # snapshot publication plus failed restore
    assert not list(database.parent.glob(".r-*.db"))


def test_run_and_restore_paths_fail_closed_on_windows_style_traversal(tmp_path):
    cfg = config(tmp_path)
    record, _database = make_run_database(cfg)
    record.run_key = "..\\outside"
    with pytest.raises(HostedOperationError, match="safe filesystem identifier"):
        run_database_path(cfg, record)

    record.run_key = "world_run_1"
    catalog = SnapshotCatalog(record)
    store = FilesystemArtifactStore(cfg.artifacts.filesystem_root)
    operations = HostedOperations(cfg, catalog, store)
    with pytest.raises(HostedOperationError):
        operations.restore_snapshot(
            record.tenant_id,
            record.id,
            destination=tmp_path / "outside.db",
        )


def test_cli_never_logs_password_or_adapter_exception_text(tmp_path):
    cfg = config(tmp_path)
    output = StringIO()
    errors = StringIO()
    catalog = BootstrapCatalog()
    code = main(
        [
            "bootstrap", "--config", "unused.yaml",
            "--tenant-slug", "initial-tenant",
            "--tenant-name", "Initial Tenant",
            "--admin-email", "admin@example.com",
            "--admin-name", "Administrator",
        ],
        environ={"AGENT_ECONOMY_BOOTSTRAP_PASSWORD": PASSWORD},
        stdout=output,
        stderr=errors,
        config_loader=lambda _path, **_kwargs: cfg,
        catalog_factory=lambda _config: catalog,
    )
    assert code == 0
    assert PASSWORD not in output.getvalue() + errors.getvalue()

    def explode(_config):
        raise RuntimeError(f"provider failed with {PASSWORD}")

    output = StringIO()
    errors = StringIO()
    code = main(
        ["readiness", "--config", "unused.yaml"],
        stdout=output,
        stderr=errors,
        config_loader=lambda _path, **_kwargs: cfg,
        catalog_factory=explode,
    )
    assert code == 1
    assert PASSWORD not in output.getvalue() + errors.getvalue()
    assert "RuntimeError" in errors.getvalue()

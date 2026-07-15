from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _compose() -> dict:
    return yaml.safe_load((ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8"))


def test_hosted_compose_has_durable_control_plane_and_artifacts() -> None:
    compose = _compose()
    services = compose["services"]

    assert {
        "postgres",
        "minio",
        "minio-init",
        "migrate",
        "bootstrap",
        "rotate-database-passwords",
        "app",
        "caddy",
        "prometheus",
    } <= set(services)
    assert services["postgres"]["volumes"]
    assert services["minio"]["volumes"]
    assert services["app"]["volumes"] == ["run-cache:/var/lib/agent-economy"]
    assert compose["networks"]["backend"]["internal"] is True
    assert "ports" not in services["app"]
    assert "ports" not in services["postgres"]
    assert "ports" not in services["minio"]
    assert services["caddy"]["ports"]


def test_hosted_compose_fails_closed_on_missing_secrets() -> None:
    source = (ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")

    for name in (
        "POSTGRES_PASSWORD",
        "APP_DATABASE_PASSWORD",
        "SUPERVISOR_DATABASE_PASSWORD",
        "MINIO_ROOT_USER",
        "MINIO_ROOT_PASSWORD",
        "S3_ACCESS_KEY_ID",
        "S3_SECRET_ACCESS_KEY",
    ):
        assert f"${{{name}:?" in source
    assert "changeme" not in source.lower()
    assert "password: password" not in source.lower()

    template = (ROOT / ".env.example").read_text(encoding="utf-8")
    for name in (
        "POSTGRES_PASSWORD",
        "APP_DATABASE_PASSWORD",
        "SUPERVISOR_DATABASE_PASSWORD",
        "MINIO_ROOT_USER",
        "MINIO_ROOT_PASSWORD",
        "S3_ACCESS_KEY_ID",
        "S3_SECRET_ACCESS_KEY",
    ):
        assert f"{name}=\n" in template


def test_hosted_containers_drop_privilege_and_gate_startup() -> None:
    services = _compose()["services"]

    for name in ("app", "migrate", "bootstrap", "rotate-database-passwords"):
        assert services[name]["read_only"] is True
        assert services[name]["cap_drop"] == ["ALL"]
        assert "no-new-privileges:true" in services[name]["security_opt"]
    assert services["app"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert services["app"]["depends_on"]["minio-init"]["condition"] == "service_completed_successfully"
    assert services["app"]["healthcheck"]["test"]
    assert services["app"]["stop_grace_period"] == "90s"

    hosted_config = yaml.safe_load(
        (ROOT / "config" / "hosted.docker.yaml").read_text(encoding="utf-8")
    )
    shutdown_seconds = hosted_config["runtime"]["shutdown_grace_seconds"]
    connect_seconds = hosted_config["database"]["connect_timeout_seconds"]
    # Uvicorn drain + supervisor shutdown + sequential web/supervisor pool close.
    required_seconds = shutdown_seconds * 2 + connect_seconds * 2
    assert int(services["app"]["stop_grace_period"].removesuffix("s")) > required_seconds

    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "--require-hashes -r requirements.lock" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert "HEALTHCHECK" in dockerfile


def test_hosted_runtime_config_references_environment_secrets_only() -> None:
    for filename in ("hosted.docker.yaml", "hosted.migrate.docker.yaml"):
        source = (ROOT / "config" / filename).read_text(encoding="utf-8")
        config = yaml.safe_load(source)
        assert set(config) >= {"enabled", "database", "artifacts", "runtime"}
        assert config["database"]["dsn_env"].startswith("AGENT_ECONOMY_")
        if config["artifacts"]["backend"] == "s3":
            assert config["artifacts"]["access_key_env"] == "AWS_ACCESS_KEY_ID"
            assert config["artifacts"]["secret_key_env"] == "AWS_SECRET_ACCESS_KEY"
        else:
            assert config["artifacts"]["backend"] == "filesystem"
            assert PurePosixPath(config["artifacts"]["root"]).is_absolute()
        assert "postgresql://" not in source
        assert "secret_access_key:" not in source


def test_postgres_runtime_role_is_forced_non_privileged() -> None:
    source = (ROOT / "deploy" / "postgres" / "init" / "001_roles.sh").read_text(
        encoding="utf-8"
    )

    assert "NOSUPERUSER" in source
    assert "NOCREATEDB" in source
    assert "NOCREATEROLE" in source
    assert "NOINHERIT" in source
    assert "NOBYPASSRLS" in source
    assert "APP_DATABASE_PASSWORD is required" in source
    assert "SUPERVISOR_DATABASE_PASSWORD is required" in source
    assert "agent_economy_supervisor" in source


def test_admin_migration_dsn_is_not_present_in_runtime_containers() -> None:
    services = _compose()["services"]
    admin_key = "AGENT_ECONOMY_HOSTED_MIGRATION_DATABASE_URL"
    supervisor_key = "AGENT_ECONOMY_HOSTED_SUPERVISOR_DATABASE_URL"

    assert admin_key in services["migrate"]["environment"]
    assert services["bootstrap"]["environment"] == services["migrate"]["environment"]
    assert services["bootstrap"]["profiles"] == ["ops"]
    assert services["bootstrap"]["command"] == ["bootstrap", "--help"]
    rotation = services["rotate-database-passwords"]
    assert rotation["profiles"] == ["ops"]
    assert rotation["environment"][admin_key] == services["migrate"]["environment"][admin_key]
    assert "AGENT_ECONOMY_NEW_POSTGRES_PASSWORD" in rotation["environment"]
    assert "AGENT_ECONOMY_NEW_POSTGRES_PASSWORD" not in services["app"]["environment"]
    for name in ("app", "snapshot-all"):
        assert admin_key not in services[name]["environment"]
        assert supervisor_key in services[name]["environment"]
    assert supervisor_key not in services["migrate"]["environment"]


def test_database_passwords_are_separate_from_base_conninfo() -> None:
    services = _compose()["services"]
    pairs = (
        (
            services["app"]["environment"],
            "AGENT_ECONOMY_HOSTED_DATABASE_URL",
            "AGENT_ECONOMY_HOSTED_DATABASE_PASSWORD",
        ),
        (
            services["app"]["environment"],
            "AGENT_ECONOMY_HOSTED_SUPERVISOR_DATABASE_URL",
            "AGENT_ECONOMY_HOSTED_SUPERVISOR_DATABASE_PASSWORD",
        ),
        (
            services["migrate"]["environment"],
            "AGENT_ECONOMY_HOSTED_MIGRATION_DATABASE_URL",
            "AGENT_ECONOMY_HOSTED_MIGRATION_DATABASE_PASSWORD",
        ),
        (
            services["bootstrap"]["environment"],
            "AGENT_ECONOMY_HOSTED_MIGRATION_DATABASE_URL",
            "AGENT_ECONOMY_HOSTED_MIGRATION_DATABASE_PASSWORD",
        ),
    )
    for environment, dsn_key, password_key in pairs:
        assert "@postgres:5432/" in environment[dsn_key]
        assert "${" not in environment[dsn_key]
        assert password_key in environment
        assert environment[password_key]


def test_runtime_uses_bucket_scoped_s3_identity_not_minio_root() -> None:
    services = _compose()["services"]
    for name in ("app", "snapshot-all"):
        environment = services[name]["environment"]
        assert "S3_ACCESS_KEY_ID" in environment["AWS_ACCESS_KEY_ID"]
        assert "S3_SECRET_ACCESS_KEY" in environment["AWS_SECRET_ACCESS_KEY"]
        assert "MINIO_ROOT" not in str(environment)
    assert "AWS_ACCESS_KEY_ID" not in services["migrate"]["environment"]
    assert "MINIO_ROOT_USER" in services["minio-init"]["environment"]
    policy = json.loads(
        (ROOT / "deploy" / "minio" / "app-policy.json").read_text(encoding="utf-8")
    )
    actions = {
        action
        for statement in policy["Statement"]
        for action in statement["Action"]
    }
    assert {"s3:GetObject", "s3:PutObject", "s3:ListBucket"} <= actions
    assert not any(action.startswith("s3:Delete") for action in actions)


def test_s3_bucket_and_prefix_match_config_policy_compose_and_ci() -> None:
    hosted_config = yaml.safe_load(
        (ROOT / "config" / "hosted.docker.yaml").read_text(encoding="utf-8")
    )
    bucket = hosted_config["artifacts"]["bucket"]
    prefix = hosted_config["artifacts"]["prefix"]
    policy_source = (ROOT / "deploy" / "minio" / "app-policy.json").read_text(
        encoding="utf-8"
    )
    compose_source = (ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")
    ci_source = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert f"arn:aws:s3:::{bucket}" in policy_source
    assert f"arn:aws:s3:::{bucket}/{prefix}/*" in policy_source
    assert f"local/{bucket}" in compose_source
    assert f"AGENT_ECONOMY_TEST_S3_BUCKET: {bucket}" in ci_source


def test_metrics_are_internal_and_public_proxy_hides_them() -> None:
    compose = _compose()
    assert compose["services"]["prometheus"]["networks"] == ["backend"]
    caddy = (ROOT / "deploy" / "Caddyfile").read_text(encoding="utf-8")
    assert "@internal path /metrics" in caddy
    assert "respond @internal 404" in caddy


def test_example_public_origin_matches_the_only_published_https_port() -> None:
    compose = _compose()
    ports = compose["services"]["caddy"]["ports"]
    assert ports == ["${HTTPS_PORT:-443}:443"]

    values = {}
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    assert values["AGENT_ECONOMY_PUBLIC_BASE_URL"] == (
        f"https://localhost:{values['HTTPS_PORT']}"
    )
    assert "HTTP_PORT" not in values

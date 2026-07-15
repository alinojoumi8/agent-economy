"""Strict configuration and lazy component factories for hosted R22.

Configuration files contain environment-variable *names*, never database or
object-store credentials.  Importing this module does not import PostgreSQL,
S3, ASGI, or supervisor dependencies, preserving the local simulator's small
dependency surface.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import inspect
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

import yaml


_ROLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,127}$")
_ENV_REFERENCE_RE = re.compile(r"^\$\{([A-Z][A-Z0-9_]{1,127})\}$")
_BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_REGION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,62}$")
_SECRET_CONFIG_KEYS = {
    "dsn",
    "database_url",
    "endpoint_url",
    "access_key",
    "access_key_id",
    "secret_key",
    "secret_access_key",
    "password",
    "token",
}


@dataclass(frozen=True)
class HostedDatabaseConfig:
    dsn: str = field(repr=False)
    runtime_role: str = "agent_economy_app"
    supervisor_dsn: str | None = field(default=None, repr=False)
    supervisor_role: str = "agent_economy_supervisor"
    migration_lock_key: int = 7_321_104_221
    connect_timeout_seconds: int = 10
    pool_min_size: int = 1
    pool_max_size: int = 10

    def __post_init__(self) -> None:
        if not isinstance(self.dsn, str) or not self.dsn.strip():
            raise ValueError("hosted database DSN must not be empty")
        if not _ROLE_RE.fullmatch(self.runtime_role):
            raise ValueError("hosted runtime_role must be a PostgreSQL identifier")
        if self.supervisor_dsn is not None and not self.supervisor_dsn.strip():
            raise ValueError("hosted supervisor DSN must not be empty")
        if not _ROLE_RE.fullmatch(self.supervisor_role):
            raise ValueError("hosted supervisor_role must be a PostgreSQL identifier")
        if self.supervisor_role == self.runtime_role:
            raise ValueError("hosted runtime and supervisor roles must be distinct")
        _bounded_int(self.connect_timeout_seconds, "hosted connect_timeout_seconds", 1, 300)
        _bounded_int(self.migration_lock_key, "hosted migration_lock_key", -(2**63), 2**63 - 1)
        _bounded_int(self.pool_min_size, "hosted pool_min_size", 0, 100)
        _bounded_int(self.pool_max_size, "hosted pool_max_size", 1, 500)
        if self.pool_min_size > self.pool_max_size:
            raise ValueError("hosted pool_min_size must not exceed pool_max_size")


@dataclass(frozen=True)
class HostedArtifactConfig:
    backend: str
    filesystem_root: Path | None = None
    bucket: str | None = None
    prefix: str = ""
    endpoint_url: str | None = field(default=None, repr=False)
    region: str | None = None
    access_key_id: str | None = field(default=None, repr=False)
    secret_access_key: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.backend not in {"filesystem", "s3"}:
            raise ValueError("hosted artifact backend must be filesystem or s3")
        if self.backend == "filesystem":
            if self.filesystem_root is None:
                raise ValueError("filesystem artifact backend requires an absolute root")
            _require_absolute_path(self.filesystem_root, "artifact filesystem root")
            if any(
                value is not None
                for value in (self.bucket, self.endpoint_url, self.region, self.access_key_id, self.secret_access_key)
            ) or self.prefix:
                raise ValueError("filesystem artifact backend may not define S3 settings")
            return
        if self.filesystem_root is not None:
            raise ValueError("S3 artifact backend may not define filesystem_root")
        if not isinstance(self.bucket, str) or _BUCKET_RE.fullmatch(self.bucket) is None:
            raise ValueError("S3 artifact bucket must be a valid lowercase bucket name")
        if "\\" in self.prefix or any(part in {"", ".", ".."} for part in self.prefix.split("/") if self.prefix):
            raise ValueError("invalid S3 artifact prefix")
        if not isinstance(self.region, str) or _REGION_RE.fullmatch(self.region) is None:
            raise ValueError("S3 artifact region is invalid")
        endpoint = urlsplit(self.endpoint_url or "")
        if endpoint.scheme not in {"http", "https"} or not endpoint.hostname:
            raise ValueError("S3 endpoint URL must be an absolute HTTP(S) URL")
        if endpoint.username is not None or endpoint.password is not None:
            raise ValueError("S3 endpoint URL must not contain credentials")
        if not self.access_key_id or not self.secret_access_key:
            raise ValueError("S3 artifact credentials must be supplied through environment variables")


def _default_artifacts() -> HostedArtifactConfig:
    return HostedArtifactConfig(
        backend="filesystem",
        filesystem_root=(Path.cwd() / ".hosted-artifacts").resolve(),
    )


@dataclass(frozen=True)
class HostedRuntimeConfig:
    run_directory: Path = field(default_factory=lambda: (Path.cwd() / ".hosted-runs").resolve())
    snapshot_directory: Path = field(default_factory=lambda: (Path.cwd() / ".hosted-snapshots").resolve())
    writer_lease_seconds: int = 30
    snapshot_interval_ticks: int = 5
    shutdown_grace_seconds: int = 30

    def __post_init__(self) -> None:
        _require_absolute_path(self.run_directory, "hosted run_directory")
        _require_absolute_path(self.snapshot_directory, "hosted snapshot_directory")
        if _paths_equivalent(self.run_directory, self.snapshot_directory):
            raise ValueError("hosted run and snapshot directories must differ")
        _bounded_int(self.writer_lease_seconds, "writer_lease_seconds", 5, 3_600)
        _bounded_int(self.snapshot_interval_ticks, "snapshot_interval_ticks", 1, 1_000_000)
        _bounded_int(self.shutdown_grace_seconds, "shutdown_grace_seconds", 1, 3_600)


@dataclass(frozen=True)
class HostedConfig:
    enabled: bool
    database: HostedDatabaseConfig
    public_base_url: str
    session_cookie_name: str = "__Host-ae_session"
    session_ttl_seconds: int = 43_200
    artifacts: HostedArtifactConfig = field(default_factory=_default_artifacts)
    runtime: HostedRuntimeConfig = field(default_factory=HostedRuntimeConfig)

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("hosted enabled must be a boolean")
        _validate_public_url(self.public_base_url)
        if self.session_cookie_name != "__Host-ae_session":
            raise ValueError("hosted session_cookie_name must be __Host-ae_session")
        _bounded_int(self.session_ttl_seconds, "hosted session_ttl_seconds", 300, 31_536_000)
        if (
            self.artifacts.backend == "filesystem"
            and self.artifacts.filesystem_root is not None
            and _paths_equivalent(self.artifacts.filesystem_root, self.runtime.run_directory)
        ):
            raise ValueError("artifact filesystem root must differ from run_directory")

    def redacted(self) -> dict[str, Any]:
        """Return operational configuration without credentials or internal DSNs."""

        artifact: dict[str, Any] = {"backend": self.artifacts.backend}
        if self.artifacts.backend == "filesystem":
            artifact["filesystem_root"] = str(self.artifacts.filesystem_root)
        else:
            artifact.update(
                bucket=self.artifacts.bucket,
                prefix=self.artifacts.prefix,
                region=self.artifacts.region,
                endpoint_configured=bool(self.artifacts.endpoint_url),
                credentials_configured=bool(
                    self.artifacts.access_key_id and self.artifacts.secret_access_key
                ),
            )
        return {
            "enabled": self.enabled,
            "public_base_url": self.public_base_url,
            "session_cookie_name": self.session_cookie_name,
            "session_ttl_seconds": self.session_ttl_seconds,
            "database": {
                "runtime_role": self.database.runtime_role,
                "supervisor_role": self.database.supervisor_role,
                "supervisor_dsn_configured": bool(self.database.supervisor_dsn),
                "connect_timeout_seconds": self.database.connect_timeout_seconds,
                "pool_min_size": self.database.pool_min_size,
                "pool_max_size": self.database.pool_max_size,
            },
            "artifacts": artifact,
            "runtime": {
                "run_directory": str(self.runtime.run_directory),
                "snapshot_directory": str(self.runtime.snapshot_directory),
                "writer_lease_seconds": self.runtime.writer_lease_seconds,
                "snapshot_interval_ticks": self.runtime.snapshot_interval_ticks,
                "shutdown_grace_seconds": self.runtime.shutdown_grace_seconds,
            },
        }


def _mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return value


def _reject_unknown(mapping: Mapping[str, Any], allowed: set[str], *, label: str) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise ValueError(f"unknown {label} fields: {', '.join(unknown)}")


def _bounded_int(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not (minimum <= value <= maximum):
        raise ValueError(f"{label} must be an integer between {minimum} and {maximum}")
    return value


def _boolean(value: Any, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean")
    return value


def _env_name(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or _ENV_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must name an uppercase environment variable")
    return value


def _environment_value(
    mapping: Mapping[str, str], name: str, *, label: str
) -> str:
    value = mapping.get(name, "")
    if not isinstance(value, str) or not value:
        raise ValueError(f"required hosted environment variable is missing: {name} ({label})")
    return value


def _database_conninfo(
    environment: Mapping[str, str],
    dsn_env: str,
    password_env: str | None,
    *,
    label: str,
) -> str:
    base = _environment_value(environment, dsn_env, label=f"{label} DSN")
    if password_env is None:
        return base
    password = _environment_value(environment, password_env, label=f"{label} password")
    try:
        from psycopg.conninfo import make_conninfo
    except ImportError as exc:  # pragma: no cover - deployment preflight
        raise RuntimeError("hosted PostgreSQL configuration requires psycopg") from exc
    # make_conninfo performs libpq-safe escaping.  Never interpolate a secret
    # into a URI: reserved characters in strong passwords are meaningful there.
    return make_conninfo(base, password=password)


def _resolve_exact_env_reference(value: Any, environment: Mapping[str, str], *, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    if "$" not in value:
        return value
    match = _ENV_REFERENCE_RE.fullmatch(value)
    if match is None:
        raise ValueError(f"{label} only permits an exact ${{ENV_VAR}} reference")
    return _environment_value(environment, match.group(1), label=label)


def _validate_public_url(value: str) -> None:
    if not isinstance(value, str):
        raise ValueError("hosted public_base_url must be a string")
    parsed = urlsplit(value)
    local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not local_http:
        raise ValueError("hosted public_base_url must use HTTPS outside localhost")
    if not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError("hosted public_base_url must be an absolute URL without credentials")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("hosted public_base_url contains an invalid port") from exc
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("hosted public_base_url must be an exact origin without a path, query, or fragment")


def _require_absolute_path(value: Path, label: str) -> Path:
    text = str(value)
    is_absolute = (
        value.is_absolute()
        or PurePosixPath(text).is_absolute()
        or PureWindowsPath(text).is_absolute()
        # A POSIX absolute path parsed by pathlib on Windows is represented
        # with one leading backslash and no drive. It remains absolute in the
        # target Linux container described by the config.
        or (os.name == "nt" and text.startswith("\\") and not text.startswith("\\\\"))
    )
    if not is_absolute:
        raise ValueError(f"{label} must be absolute")
    if text in {"/", "\\"} or PureWindowsPath(text).parent == PureWindowsPath(text):
        raise ValueError(f"{label} may not be a filesystem root")
    return value


def _paths_equivalent(left: Path, right: Path) -> bool:
    try:
        return left.resolve(strict=False) == right.resolve(strict=False)
    except OSError:
        return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(os.path.abspath(str(right)))


def _path(value: Any, *, label: str) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value or "$" in value:
        raise ValueError(f"{label} must be an absolute literal path")
    result = Path(value).expanduser()
    _require_absolute_path(result, label)
    return result


def _load_artifacts(raw: Mapping[str, Any], environment: Mapping[str, str]) -> HostedArtifactConfig:
    backend = raw.get("backend")
    if backend == "filesystem":
        _reject_unknown(raw, {"backend", "root"}, label="artifact")
        return HostedArtifactConfig(
            backend="filesystem",
            filesystem_root=_path(raw.get("root"), label="artifact root"),
        )
    if backend == "s3":
        _reject_unknown(
            raw,
            {"backend", "bucket", "prefix", "endpoint_url_env", "region", "access_key_env", "secret_key_env"},
            label="artifact",
        )
        endpoint_env = _env_name(raw.get("endpoint_url_env"), label="artifact endpoint_url_env")
        access_env = _env_name(raw.get("access_key_env"), label="artifact access_key_env")
        secret_env = _env_name(raw.get("secret_key_env"), label="artifact secret_key_env")
        return HostedArtifactConfig(
            backend="s3",
            bucket=raw.get("bucket"),
            prefix=str(raw.get("prefix", "")).strip("/"),
            endpoint_url=_environment_value(environment, endpoint_env, label="S3 endpoint"),
            region=raw.get("region"),
            access_key_id=_environment_value(environment, access_env, label="S3 access key"),
            secret_access_key=_environment_value(environment, secret_env, label="S3 secret key"),
        )
    raise ValueError("hosted artifact backend must be filesystem or s3")


def load_hosted_config(path: str | Path, *, environ: Mapping[str, str] | None = None) -> HostedConfig:
    """Load a strict hosted config and resolve only explicitly named env values."""

    environment = os.environ if environ is None else environ
    with Path(path).open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    root = _mapping(raw, label="hosted config")
    _reject_unknown(
        root,
        {"enabled", "public_base_url", "session_cookie_name", "session_ttl_seconds", "database", "artifacts", "runtime"},
        label="hosted config",
    )
    db = _mapping(root.get("database", {}), label="hosted database config")
    _reject_unknown(
        db,
        {"dsn_env", "password_env", "runtime_role", "supervisor_dsn_env", "supervisor_password_env", "supervisor_role", "migration_lock_key", "connect_timeout_seconds", "pool_min_size", "pool_max_size"},
        label="database config",
    )
    if set(db) & _SECRET_CONFIG_KEYS:
        raise ValueError("database credentials must be supplied through a dsn_env reference")
    dsn_env = _env_name(db.get("dsn_env"), label="hosted database.dsn_env")
    password_env = (
        _env_name(db.get("password_env"), label="hosted database.password_env")
        if db.get("password_env") is not None
        else None
    )
    supervisor_dsn_env = (
        _env_name(db.get("supervisor_dsn_env"), label="hosted database.supervisor_dsn_env")
        if db.get("supervisor_dsn_env") is not None
        else None
    )
    supervisor_password_env = (
        _env_name(
            db.get("supervisor_password_env"),
            label="hosted database.supervisor_password_env",
        )
        if db.get("supervisor_password_env") is not None
        else None
    )
    if supervisor_password_env is not None and supervisor_dsn_env is None:
        raise ValueError("supervisor_password_env requires supervisor_dsn_env")
    enabled = _boolean(root.get("enabled", False), label="hosted enabled")
    artifacts = _load_artifacts(
        _mapping(root.get("artifacts", {}), label="hosted artifact config"), environment
    )
    runtime = _mapping(root.get("runtime", {}), label="hosted runtime config")
    _reject_unknown(
        runtime,
        {"run_directory", "snapshot_directory", "writer_lease_seconds", "snapshot_interval_ticks", "shutdown_grace_seconds"},
        label="runtime config",
    )
    public_url = _resolve_exact_env_reference(
        root.get("public_base_url", "http://127.0.0.1:8000"),
        environment,
        label="hosted public_base_url",
    ).rstrip("/")
    return HostedConfig(
        enabled=enabled,
        database=HostedDatabaseConfig(
            dsn=_database_conninfo(
                environment, dsn_env, password_env, label="database"
            ),
            runtime_role=str(db.get("runtime_role", "agent_economy_app")),
            supervisor_dsn=(
                _database_conninfo(
                    environment,
                    supervisor_dsn_env,
                    supervisor_password_env,
                    label="supervisor database",
                )
                if supervisor_dsn_env is not None
                else None
            ),
            supervisor_role=str(db.get("supervisor_role", "agent_economy_supervisor")),
            migration_lock_key=db.get("migration_lock_key", 7_321_104_221),
            connect_timeout_seconds=db.get("connect_timeout_seconds", 10),
            pool_min_size=db.get("pool_min_size", 1),
            pool_max_size=db.get("pool_max_size", 10),
        ),
        public_base_url=public_url,
        session_cookie_name=str(root.get("session_cookie_name", "__Host-ae_session")),
        session_ttl_seconds=root.get("session_ttl_seconds", 43_200),
        artifacts=artifacts,
        runtime=HostedRuntimeConfig(
            run_directory=_path(runtime.get("run_directory"), label="hosted run_directory"),
            snapshot_directory=_path(runtime.get("snapshot_directory"), label="hosted snapshot_directory"),
            writer_lease_seconds=runtime.get("writer_lease_seconds", 30),
            snapshot_interval_ticks=runtime.get("snapshot_interval_ticks", 5),
            shutdown_grace_seconds=runtime.get("shutdown_grace_seconds", 30),
        ),
    )


def create_catalog(
    config: HostedConfig,
    *,
    connect: Callable[[str], Any] | None = None,
    pool: Any | None = None,
    purpose: str = "web",
):
    from .catalog import HostedCatalog

    if purpose == "web":
        return HostedCatalog(
            config.database.dsn,
            connect=connect,
            pool=pool,
            expected_role=config.database.runtime_role,
            capability="web",
            forbidden_role=config.database.supervisor_role,
            connect_timeout_seconds=config.database.connect_timeout_seconds,
        )
    if purpose == "supervisor":
        if not config.database.supervisor_dsn:
            raise ValueError("hosted supervisor_dsn_env is required for supervisor operations")
        return HostedCatalog(
            config.database.supervisor_dsn,
            connect=connect,
            pool=pool,
            expected_role=config.database.supervisor_role,
            capability="supervisor",
            forbidden_role=config.database.runtime_role,
            connect_timeout_seconds=config.database.connect_timeout_seconds,
        )
    raise ValueError("catalog purpose must be web or supervisor")


def create_postgres_pool(
    config: HostedConfig,
    *,
    purpose: str = "web",
    open_pool: bool = False,
    **kwargs: Any,
):
    """Lazily construct a psycopg pool without opening network connections by default."""

    try:
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool
    except ImportError as exc:  # pragma: no cover - deployment preflight
        raise RuntimeError("hosted PostgreSQL pooling requires psycopg[pool]") from exc
    if purpose == "web":
        conninfo = config.database.dsn
    elif purpose == "supervisor":
        conninfo = config.database.supervisor_dsn
        if not conninfo:
            raise ValueError("hosted supervisor_dsn_env is required for supervisor pool")
    else:
        raise ValueError("pool purpose must be web or supervisor")
    options = {
        "conninfo": conninfo,
        "min_size": config.database.pool_min_size,
        "max_size": config.database.pool_max_size,
        "open": open_pool,
        "kwargs": {
            "connect_timeout": config.database.connect_timeout_seconds,
            "row_factory": dict_row,
        },
        "timeout": config.database.connect_timeout_seconds,
        "max_waiting": max(1, config.database.pool_max_size * 4),
    }
    options.update(kwargs)
    return ConnectionPool(**options)


def create_artifact_store(config: HostedConfig, *, client: Any = None):
    from .artifacts import FilesystemArtifactStore, S3ArtifactStore

    artifact = config.artifacts
    if artifact.backend == "filesystem":
        assert artifact.filesystem_root is not None
        return FilesystemArtifactStore(artifact.filesystem_root)
    try:
        from botocore.config import Config as BotocoreConfig
    except ImportError as exc:  # pragma: no cover - deployment preflight
        raise RuntimeError("hosted S3 storage requires botocore") from exc
    io_timeout = max(
        1,
        min(
            config.database.connect_timeout_seconds,
            max(1, config.runtime.shutdown_grace_seconds // 2),
        ),
    )
    return S3ArtifactStore(
        artifact.bucket or "",
        prefix=artifact.prefix,
        client=client,
        client_options={
            "endpoint_url": artifact.endpoint_url,
            "region_name": artifact.region,
            "aws_access_key_id": artifact.access_key_id,
            "aws_secret_access_key": artifact.secret_access_key,
            "config": BotocoreConfig(
                connect_timeout=io_timeout,
                read_timeout=io_timeout,
                retries={"mode": "standard", "max_attempts": 2},
                s3={"addressing_style": "path"},
            ),
        },
    )


def create_auth_service(config: HostedConfig, *, catalog: Any = None):
    from datetime import timedelta

    from .catalog_auth import CatalogAuthService

    resolved_catalog = catalog or create_catalog(config, purpose="web")
    return CatalogAuthService(
        resolved_catalog,
        session_ttl=timedelta(seconds=config.session_ttl_seconds),
    )


def default_hosted_profiles() -> dict[str, Path]:
    """Return the bounded, free-by-default server-owned profile allowlist."""

    root = Path(__file__).resolve().parents[1]
    return {
        "v2": root / "runs" / "v2.yaml",
        "v2-rehearsal": root / "runs" / "v2-spec-closure-rehearsal.yaml",
        "r21-real-us": root / "runs" / "r21-real-us.yaml",
    }


def create_supervisor(
    config: HostedConfig,
    *,
    catalog: Any = None,
    artifact_store: Any = None,
    profiles: Mapping[str, Any] | None = None,
    instance_id: str = "hosted-supervisor",
    max_loaded_runs: int = 32,
):
    from .supervisor import HostedRunSupervisor

    resolved_catalog = catalog or create_catalog(config, purpose="supervisor")
    resolved_store = artifact_store or create_artifact_store(config)
    return HostedRunSupervisor(
        resolved_catalog,
        resolved_store,
        work_root=config.runtime.run_directory,
        profiles=dict(profiles or default_hosted_profiles()),
        instance_id=instance_id,
        max_loaded_runs=max_loaded_runs,
        lease_ttl_seconds=config.runtime.writer_lease_seconds,
        snapshot_interval_ticks=config.runtime.snapshot_interval_ticks,
        shutdown_grace_seconds=config.runtime.shutdown_grace_seconds,
    )


def artifact_readiness_check(artifact_store: Any) -> bool:
    """Probe the configured store without exposing a key, bucket, or credential."""

    root = getattr(artifact_store, "root", None)
    if root is not None:
        path = Path(root)
        return path.is_dir() and os.access(path, os.R_OK | os.W_OK)
    client = getattr(artifact_store, "_client", None)
    bucket = getattr(artifact_store, "bucket", None)
    if client is None or not bucket:
        return False
    # Scoped artifact credentials may have prefix-conditioned ListBucket but
    # no bucket-wide HeadBucket permission. Location is a harmless liveness
    # probe and is granted explicitly by the deployment policy.
    client.get_bucket_location(Bucket=bucket)
    return True


def create_hosted_application(
    config: HostedConfig,
    *,
    catalog: Any = None,
    artifact_store: Any = None,
    auth: Any = None,
    supervisor: Any = None,
    profiles: Mapping[str, Any] | None = None,
    readiness_checks: Mapping[str, Callable[[], Any]] | None = None,
):
    """Lazily compose the durable hosted app and lifecycle hooks."""

    from .app import create_hosted_app

    owned_pools: list[Any] = []
    if catalog is None:
        web_pool = create_postgres_pool(config, purpose="web", open_pool=False)
        owned_pools.append(web_pool)
        resolved_catalog = create_catalog(config, pool=web_pool)
    else:
        resolved_catalog = catalog
    resolved_store = artifact_store or create_artifact_store(config)
    resolved_auth = auth or create_auth_service(config, catalog=resolved_catalog)
    if supervisor is None:
        supervisor_pool = create_postgres_pool(
            config, purpose="supervisor", open_pool=False
        )
        owned_pools.append(supervisor_pool)
        supervisor_catalog = create_catalog(
            config, purpose="supervisor", pool=supervisor_pool
        )
        resolved_supervisor = create_supervisor(
            config,
            catalog=supervisor_catalog,
            artifact_store=resolved_store,
            profiles=profiles,
        )
    else:
        resolved_supervisor = supervisor
    @asynccontextmanager
    async def hosted_lifespan(_app: Any):
        opened_pools: list[Any] = []
        supervisor_started = False
        try:
            for pool in owned_pools:
                pool.open(wait=False)
                opened_pools.append(pool)
                pool.wait(timeout=config.database.connect_timeout_seconds)

            web_check = getattr(resolved_catalog, "assert_runtime_security", None)
            if web_check is not None:
                web_check()
            supervisor_catalog = getattr(resolved_supervisor, "catalog", None)
            supervisor_check = getattr(supervisor_catalog, "assert_runtime_security", None)
            if supervisor_check is not None:
                supervisor_check()

            supervisor_started = True
            recovered = resolved_supervisor.recover_active_runs()
            if inspect.isawaitable(recovered):
                await recovered
            yield
        finally:
            try:
                if supervisor_started:
                    stopped = resolved_supervisor.shutdown()
                    if inspect.isawaitable(stopped):
                        await stopped
            finally:
                for pool in reversed(opened_pools):
                    pool.close(timeout=config.database.connect_timeout_seconds)

    checks = {"artifacts": lambda: artifact_readiness_check(resolved_store)}
    checks.update(dict(readiness_checks or {}))
    app = create_hosted_app(
        catalog=resolved_catalog,
        auth=resolved_auth,
        supervisor=resolved_supervisor,
        readiness_checks=checks,
        lifespan=hosted_lifespan,
    )
    app.state.database_pools = tuple(owned_pools)
    return app


# Conventional factory alias for CLI/deployment code.
create_app = create_hosted_application

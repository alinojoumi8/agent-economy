"""Operations entrypoint for the optional hosted R22 deployment."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
from typing import Any, Callable, Mapping, Sequence, TextIO

from .config import (
    HostedConfig,
    create_artifact_store,
    create_catalog,
    create_hosted_application,
    load_hosted_config,
)
from .ops import HostedOperations, bootstrap_initial_tenant, check_readiness


_ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,127}$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m hosted.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def command(name: str, help_text: str) -> argparse.ArgumentParser:
        item = subparsers.add_parser(name, help=help_text)
        item.add_argument(
            "--config",
            default=os.environ.get("AGENT_ECONOMY_HOSTED_CONFIG", "config/hosted.example.yaml"),
        )
        return item

    command("migrate", "apply exact hosted PostgreSQL migrations")

    rotate = command(
        "rotate-database-passwords",
        "atomically rotate hosted PostgreSQL role passwords",
    )
    rotate.add_argument("--runtime-password-env", default="APP_DATABASE_PASSWORD")
    rotate.add_argument(
        "--supervisor-password-env", default="SUPERVISOR_DATABASE_PASSWORD"
    )
    rotate.add_argument(
        "--administrator-password-env",
        default="AGENT_ECONOMY_NEW_POSTGRES_PASSWORD",
    )

    serve = command("serve", "serve the authenticated hosted API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    bootstrap = command("bootstrap", "create the initial tenant and administrator")
    bootstrap.add_argument("--tenant-slug", required=True)
    bootstrap.add_argument("--tenant-name", required=True)
    bootstrap.add_argument("--admin-email", required=True)
    bootstrap.add_argument("--admin-name", required=True)
    bootstrap.add_argument("--password-env", default="AGENT_ECONOMY_BOOTSTRAP_PASSWORD")

    snapshot = command("snapshot-run", "publish one immutable run snapshot")
    snapshot.add_argument("--tenant-id", required=True)
    snapshot.add_argument("--run-id", required=True)

    command("snapshot-all", "snapshot every active catalog run")

    verify = command("verify-snapshot", "verify the current durable run snapshot")
    verify.add_argument("--tenant-id", required=True)
    verify.add_argument("--run-id", required=True)

    restore = command("restore-snapshot", "restore the current verified run snapshot")
    restore.add_argument("--tenant-id", required=True)
    restore.add_argument("--run-id", required=True)
    restore.add_argument("--replace", action="store_true")

    command("readiness", "check PostgreSQL, artifacts, and runtime directories")
    return parser


def _emit(stream: TextIO, payload: Mapping[str, Any]) -> None:
    stream.write(json.dumps(dict(payload), sort_keys=True, separators=(",", ":")) + "\n")


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    getpass_fn: Callable[[str], str] = getpass.getpass,
    config_loader: Callable[..., HostedConfig] = load_hosted_config,
    catalog_factory: Callable[[HostedConfig], Any] = create_catalog,
    artifact_factory: Callable[[HostedConfig], Any] = create_artifact_store,
    application_factory: Callable[[HostedConfig], Any] = create_hosted_application,
    uvicorn_runner: Callable[..., Any] | None = None,
    credential_rotator: Callable[..., Any] | None = None,
) -> int:
    output = stdout or sys.stdout
    errors = stderr or sys.stderr
    environment = os.environ if environ is None else environ
    args = _parser().parse_args(list(argv) if argv is not None else None)
    try:
        config = config_loader(args.config, environ=environment)
        if not config.enabled and args.command == "serve":
            raise RuntimeError("hosted serving is disabled by configuration")

        if args.command == "migrate":
            from .migrations import migrate

            report = migrate(
                config.database.dsn,
                runtime_role=config.database.runtime_role,
                supervisor_role=config.database.supervisor_role,
                lock_key=config.database.migration_lock_key,
                connect_timeout_seconds=config.database.connect_timeout_seconds,
            )
            _emit(
                output,
                {
                    "status": "ok",
                    "current_version": report.current_version,
                    "applied_versions": list(report.applied_versions),
                },
            )
            return 0

        if args.command == "rotate-database-passwords":
            environment_names = (
                args.runtime_password_env,
                args.supervisor_password_env,
                args.administrator_password_env,
            )
            if any(_ENV_RE.fullmatch(name) is None for name in environment_names):
                raise ValueError(
                    "database password options must name uppercase environment variables"
                )
            secrets = [environment.get(name) for name in environment_names]
            if any(not secret for secret in secrets):
                raise ValueError("required database rotation environment variable is missing")
            rotator = credential_rotator
            if rotator is None:
                from .migrations import rotate_database_passwords

                rotator = rotate_database_passwords
            report = rotator(
                config.database.dsn,
                runtime_role=config.database.runtime_role,
                runtime_password=secrets[0],
                supervisor_role=config.database.supervisor_role,
                supervisor_password=secrets[1],
                administrator_password=secrets[2],
                connect_timeout_seconds=config.database.connect_timeout_seconds,
            )
            _emit(
                output,
                {
                    "status": "ok",
                    "rotated_roles": [
                        report.administrator_role,
                        report.runtime_role,
                        report.supervisor_role,
                    ],
                },
            )
            return 0

        if args.command == "serve":
            if not (1 <= args.port <= 65_535):
                raise ValueError("port must be between 1 and 65535")
            app = application_factory(config)
            runner = uvicorn_runner
            if runner is None:
                import uvicorn

                runner = uvicorn.run
            runner(
                app,
                host=args.host,
                port=args.port,
                timeout_graceful_shutdown=config.runtime.shutdown_grace_seconds,
            )
            return 0

        supervisor_commands = {
            "snapshot-run", "snapshot-all", "verify-snapshot", "restore-snapshot"
        }
        if catalog_factory is create_catalog and args.command in supervisor_commands:
            catalog = create_catalog(config, purpose="supervisor")
        else:
            catalog = catalog_factory(config)
        if args.command == "bootstrap":
            if _ENV_RE.fullmatch(args.password_env) is None:
                raise ValueError("password-env must name an uppercase environment variable")
            password = environment.get(args.password_env)
            if password is None:
                password = getpass_fn("Initial administrator password: ")
            result = bootstrap_initial_tenant(
                catalog,
                tenant_slug=args.tenant_slug,
                tenant_name=args.tenant_name,
                admin_email=args.admin_email,
                admin_name=args.admin_name,
                password=password,
            )
            _emit(
                output,
                {
                    "status": "ok",
                    "created": result.created,
                    "tenant_id": str(result.tenant_id),
                    "user_id": str(result.user_id),
                },
            )
            return 0

        store = artifact_factory(config)
        operations = HostedOperations(config, catalog, store)
        if args.command == "snapshot-run":
            result = operations.snapshot_run(args.tenant_id, args.run_id)
            _emit(
                output,
                {
                    "status": "ok",
                    "tenant_id": str(result.tenant_id),
                    "run_id": str(result.run_id),
                    "snapshot_key": result.metadata.key,
                    "sha256": result.metadata.sha256,
                    "size_bytes": result.metadata.size_bytes,
                },
            )
            return 0
        if args.command == "snapshot-all":
            results = operations.snapshot_all()
            _emit(output, {"status": "ok", "snapshot_count": len(results)})
            return 0
        if args.command == "verify-snapshot":
            snapshot = operations.verify_snapshot(args.tenant_id, args.run_id)
            _emit(
                output,
                {
                    "status": "ok",
                    "sha256": snapshot.sha256,
                    "size_bytes": snapshot.size_bytes,
                    "schema_version": snapshot.schema_version,
                },
            )
            return 0
        if args.command == "restore-snapshot":
            snapshot = operations.restore_snapshot(
                args.tenant_id, args.run_id, replace=bool(args.replace)
            )
            _emit(
                output,
                {
                    "status": "ok",
                    "sha256": snapshot.sha256,
                    "size_bytes": snapshot.size_bytes,
                    "schema_version": snapshot.schema_version,
                },
            )
            return 0
        if args.command == "readiness":
            report = check_readiness(config, catalog=catalog, artifact_store=store)
            _emit(
                output,
                {"status": "ready" if report.ready else "not_ready", "checks": report.checks},
            )
            return 0 if report.ready else 1
        raise RuntimeError("unsupported hosted command")
    except KeyboardInterrupt:
        errors.write("hosted operation interrupted\n")
        return 130
    except Exception as exc:
        # Never stringify an adapter exception: database and provider errors can
        # contain DSNs, headers, or secret-bearing request fragments.
        errors.write(f"hosted operation failed ({type(exc).__name__})\n")
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

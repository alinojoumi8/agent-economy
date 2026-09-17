"""Pinned Litestream recovery for the Hostinger filesystem deployment."""
from __future__ import annotations

import copy
import os
import re
import sqlite3
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

import yaml

from engine.checkpoint_manifest import _fsync_directory
from .artifacts import _verify_sqlite_database

LITESTREAM_VERSION = "0.5.17"
_RUN_PATH = re.compile(
    r"tenants/[0-9a-f-]{36}/runs/[0-9a-f-]{36}/data/[A-Za-z0-9_-]{1,128}\.db")


class LitestreamRecoveryError(RuntimeError):
    pass


def load_replication_config(path: str | Path, run_root: Path, *, environ=None) -> dict:
    environment = os.environ if environ is None else environ
    # Expand only named variables; fail on a missing setting instead of
    # silently selecting an unverified SSH host or an empty remote root.
    def expand(match):
        value = environment.get(match.group(1))
        if not value:
            raise ValueError(f"missing backup environment variable: {match.group(1)}")
        return value
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    def resolve(value):
        if isinstance(value, str):
            return re.sub(r"\$\{([A-Z][A-Z0-9_]+)\}", expand, value)
        if isinstance(value, list):
            return [resolve(item) for item in value]
        if isinstance(value, dict):
            return {key: resolve(item) for key, item in value.items()}
        return value
    config = resolve(raw)
    if not isinstance(config, dict) or len(config.get("dbs", [])) != 1:
        raise ValueError("backup config must watch exactly one live run directory")
    database = config["dbs"][0]
    if (Path(database.get("dir", "")).resolve() != run_root.resolve()
            or database.get("pattern") != "*.db" or database.get("recursive") is not True
            or database.get("watch") is not True or "path" in database):
        raise ValueError("backup watcher must match the configured live run directory")
    replica = database.get("replica", {})
    if (replica.get("type") != "sftp" or any(key in replica for key in ("url", "password"))
            or not all(replica.get(key) for key in ("host", "user", "key-path", "host-key", "path"))):
        raise ValueError("production backups require SFTP, a private key and a verified host key")
    remote_root = PurePosixPath(replica["path"])
    if not remote_root.is_absolute() or str(remote_root) == "/" or ".." in remote_root.parts:
        raise ValueError("backup path must be a dedicated absolute SFTP directory")
    if config.get("retention", {}).get("enabled", True) is not True:
        raise ValueError("Litestream retention must be enabled")
    snapshot = config.get("snapshot", {})
    if snapshot.get("retention") != "168h" or snapshot.get("interval") != "24h":
        raise ValueError("Hostinger backup policy requires daily snapshots and seven-day retention")
    return config


class LitestreamBackup:
    def __init__(self, *, binary: str, run_root: Path, config: dict):
        self.binary = binary
        self.run_root = run_root.resolve()
        self.config = copy.deepcopy(config)

    def verify_binary(self) -> None:
        try:
            result = subprocess.run([self.binary, "version"], capture_output=True,
                                    text=True, timeout=10, check=True)
        except (OSError, subprocess.SubprocessError) as exc:
            raise LitestreamRecoveryError("Litestream binary is unavailable") from exc
        if result.stdout.strip() != LITESTREAM_VERSION:
            raise LitestreamRecoveryError("Litestream binary version does not match this release")

    def restore(self, destination: Path, *, run_key: str, schema_version: int) -> None:
        """Recover the stream into a private file; no fallback to stale snapshots."""
        target = destination.absolute()
        relative = target.relative_to(self.run_root).as_posix()
        if (not _RUN_PATH.fullmatch(relative) or target.stem != run_key
                or target.resolve() != target):
            raise LitestreamRecoveryError("restore path is outside the hosted run namespace")
        if target.exists() or any(Path(f"{target}{suffix}").exists() for suffix in ("-wal", "-shm")):
            raise LitestreamRecoveryError("restore requires a missing database and no sidecars")
        self.verify_binary()
        target.parent.mkdir(parents=True, exist_ok=True)
        replica = copy.deepcopy(self.config["dbs"][0]["replica"])
        replica["path"] = str(PurePosixPath(replica["path"]) / relative)
        # Directory watcher entries are not addressable by `restore db-path`.
        # Materialize a single explicit entry with exactly the same remote path.
        config = {"dbs": [{"path": str(target), "replica": replica}]}
        with tempfile.TemporaryDirectory(prefix=".litestream-restore-", dir=target.parent) as directory:
            staged = Path(directory) / "restored.sqlite3"
            config_path = Path(directory) / "restore.yaml"
            config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
            try:
                subprocess.run(
                    [self.binary, "restore", "-config", str(config_path),
                     "-o", str(staged), str(target)],
                    capture_output=True, timeout=600, check=True)
            except (OSError, subprocess.SubprocessError) as exc:
                # CLI output can contain hostnames and paths. Operators can use
                # the private Litestream logs; never return it through the API.
                raise LitestreamRecoveryError("stream restore failed; operator recovery is required") from exc
            _verify_sqlite_database(staged, schema_version)
            connection = sqlite3.connect(f"{staged.as_uri()}?mode=ro&immutable=1", uri=True)
            try:
                row = connection.execute("SELECT run_id FROM run_meta WHERE id=1").fetchone()
                if row is None or row[0] != run_key:
                    raise LitestreamRecoveryError("restored database identity does not match the catalog")
            finally:
                connection.close()
            with staged.open("r+b") as handle:
                os.fsync(handle.fileno())
            os.link(staged, target)  # cannot replace another restorer's publication
            _fsync_directory(target.parent)


def create_litestream_backup(runtime):
    if runtime.recovery_mode != "litestream":
        return None
    config = load_replication_config(runtime.litestream_config, runtime.run_directory)
    backup = LitestreamBackup(binary=runtime.litestream_binary,
                              run_root=runtime.run_directory, config=config)
    backup.verify_binary()
    return backup

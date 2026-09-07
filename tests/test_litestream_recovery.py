from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import subprocess
import time
from contextlib import closing, ExitStack
from copy import deepcopy
from uuid import uuid4

import pytest
import yaml

from hosted.litestream import LitestreamBackup, LitestreamRecoveryError, load_replication_config


def run_path(root):
    return root / "tenants" / str(uuid4()) / "runs" / str(uuid4()) / "data" / "drill.db"


def test_sftp_settings_fail_closed_and_use_exact_watcher_root(tmp_path):
    root = tmp_path / "runs"
    source = Path("deploy/hostinger/litestream.yml").read_text()
    config = yaml.safe_load(source)
    config["dbs"][0]["dir"] = str(root)
    path = tmp_path / "replication.yaml"
    path.write_text(yaml.safe_dump(config))
    env = {"AE_BACKUP_SFTP_HOST": "backup.example.test:22", "AE_BACKUP_SFTP_USER": "backup",
           "AE_BACKUP_SFTP_HOST_KEY": "ssh-ed25519 AAAATEST", "AE_BACKUP_SFTP_PATH": "/backups/worlds"}
    loaded = load_replication_config(path, root, environ=env)
    assert loaded["dbs"][0]["replica"]["host"] == env["AE_BACKUP_SFTP_HOST"]
    for name in env:
        with pytest.raises(ValueError, match="missing backup"):
            load_replication_config(path, root, environ={k: v for k, v in env.items() if k != name})
    with pytest.raises(ValueError, match="watcher"):
        load_replication_config(path, tmp_path / "checkpoints", environ=env)


def test_restore_failure_does_not_publish_or_fallback(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    target = run_path(root)
    backup = LitestreamBackup(binary="litestream", run_root=root,
                              config={"dbs": [{"replica": {"type": "file", "path": "/backup"}}]})
    monkeypatch.setattr(backup, "verify_binary", lambda: None)
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "restore", stderr=b"private details")
    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(LitestreamRecoveryError, match="operator recovery") as failure:
        backup.restore(target, run_key="drill", schema_version=20)
    assert "private details" not in str(failure.value)
    assert not target.exists()


@pytest.mark.parametrize("wrong_identity,wrong_schema", [(True, False), (False, True)])
def test_restore_checks_actual_run_identity_and_schema(tmp_path, monkeypatch, wrong_identity, wrong_schema):
    root = tmp_path / "runs"
    target = run_path(root)
    backup = LitestreamBackup(binary="litestream", run_root=root,
                              config={"dbs": [{"replica": {"type": "file", "path": "/backup"}}]})
    monkeypatch.setattr(backup, "verify_binary", lambda: None)
    def restore(args, **kwargs):
        with closing(sqlite3.connect(args[args.index("-o") + 1])) as connection:
            connection.execute("CREATE TABLE run_meta(id INTEGER PRIMARY KEY,run_id TEXT,schema_version INTEGER)")
            connection.execute("INSERT INTO run_meta VALUES(1,?,?)",
                               ("foreign" if wrong_identity else "drill", 19 if wrong_schema else 20))
            connection.commit()
    monkeypatch.setattr(subprocess, "run", restore)
    with pytest.raises(RuntimeError):
        backup.restore(target, run_key="drill", schema_version=20)
    assert not target.exists()


@pytest.mark.skipif(not os.environ.get("AE_LITESTREAM_BIN"), reason="set AE_LITESTREAM_BIN for the real binary drill")
@pytest.mark.parametrize("replica_type", ["file", "sftp"])
def test_real_litestream_recovers_committed_wal_memory_and_action_history(tmp_path, replica_type):
    """Real pinned binary, dynamic directory watcher, and incremental restore."""
    binary = str(Path(os.environ["AE_LITESTREAM_BIN"]).resolve())
    root = tmp_path / "runs"
    root.mkdir()
    remote = tmp_path / "replica"
    remote.mkdir()
    stack = ExitStack()
    if replica_type == "sftp":
        pytest.importorskip("paramiko", reason="install tests/requirements-storage.lock for SFTP drill")
        from .storage_sftp_support import sftp_replica
        replica = stack.enter_context(sftp_replica(remote, tmp_path))
    else:
        replica = {"type": "file", "path": str(remote)}
    replica["sync-interval"] = "100ms"
    config = {"dbs": [{"dir": str(root), "pattern": "*.db", "recursive": True, "watch": True,
                       "replica": replica}]}
    recovery_config = deepcopy(config)
    if replica_type == "sftp":
        reader_keys = tmp_path / "reader-keys"
        reader_keys.mkdir()
        recovery_config["dbs"][0]["replica"] = stack.enter_context(
            sftp_replica(remote, reader_keys, username="drill-reader", read_only=True))
    path = tmp_path / "replication.yml"
    path.write_text(yaml.safe_dump(config))
    log_path = tmp_path / "litestream.log"
    with stack, log_path.open("wb") as log:
        process = subprocess.Popen([binary, "replicate", "-config", str(path)], stdout=log, stderr=log)
        writer = None
        try:
            # Create after watcher startup to exercise dynamic tenant admission.
            time.sleep(1)
            target = run_path(root)
            target.parent.mkdir(parents=True)
            writer = sqlite3.connect(target)
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("PRAGMA wal_autocheckpoint=0")
            writer.execute("CREATE TABLE run_meta(id INTEGER PRIMARY KEY,run_id TEXT,schema_version INTEGER)")
            writer.execute("INSERT INTO run_meta VALUES(1,'drill',20)")
            writer.execute("CREATE TABLE memories(id INTEGER PRIMARY KEY,body TEXT)")
            writer.execute("CREATE TABLE events(id INTEGER PRIMARY KEY,action TEXT)")
            writer.commit()
            # The restore must be tested against a distinct missing cache path,
            # with its replica definition still pointing to the original run.
            restored_root = tmp_path / "recovered"
            destination = restored_root / target.relative_to(root)
            recovery = LitestreamBackup(binary=binary, run_root=restored_root, config=recovery_config)
            for number in (1, 2):
                writer.execute("INSERT INTO memories VALUES(?,?)", (number, f"experience {number}"))
                writer.execute("INSERT INTO events VALUES(?,?)", (number, f"action {number}"))
                writer.commit()
                deadline = time.monotonic() + 30
                last_error = None
                while True:
                    try:
                        recovery.restore(destination, run_key="drill", schema_version=20)
                        with closing(sqlite3.connect(destination)) as restored:
                            count = restored.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
                        if count == number:
                            break
                    except LitestreamRecoveryError as exc:
                        last_error = str(getattr(exc.__cause__, "stderr", exc))
                    destination.unlink(missing_ok=True)
                    if process.poll() is not None or time.monotonic() >= deadline:
                        pytest.fail(f"Litestream restore failed: {last_error}; " + log_path.read_text())
                    time.sleep(0.2)
                with closing(sqlite3.connect(destination)) as restored:
                    assert restored.execute("SELECT body FROM memories ORDER BY id").fetchall() == [
                        (f"experience {i}",) for i in range(1, number + 1)]
                    assert restored.execute("SELECT action FROM events ORDER BY id").fetchall() == [
                        (f"action {i}",) for i in range(1, number + 1)]
                destination.unlink()
        finally:
            if writer is not None:
                writer.close()
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

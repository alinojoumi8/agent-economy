"""Real PostgreSQL + SFTP + Litestream replacement drill, explicitly opt-in.

Both DSNs must point to disposable databases named ae_ops_drill. The two servers
must be different. This exercises local replacement infrastructure, not off-host
durability or public TLS. No provider calls are made.
"""
from __future__ import annotations

import asyncio
from contextlib import closing, ExitStack
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import time

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
import pytest
import uvicorn
import yaml

from hosted.app import create_hosted_app
from engine.ledger import Ledger
from hosted.artifacts import FilesystemArtifactStore
from hosted.catalog import HostedCatalog
from hosted.catalog_auth import CatalogAuthService
from hosted.litestream import LitestreamBackup, LitestreamRecoveryError
from hosted.load_test import LoadUser, run_load_test
from hosted.migrations import migrate
from hosted.security import hash_password
from hosted.supervisor import HostedRunSupervisor
from tests.storage_sftp_support import sftp_replica
from tests.test_catalog_backup_retention import backup_module
from tests.test_hosted_supervisor import tiny_external_profile


SOURCE = os.environ.get("AE_OPS_SOURCE_DSN", "")
TARGET = os.environ.get("AE_OPS_TARGET_DSN", "")
pytestmark = pytest.mark.skipif(not (SOURCE and TARGET), reason="disposable ops drill DSNs required")


def _database(dsn):
    fields = conninfo_to_dict(dsn)
    assert fields["dbname"] == "ae_ops_drill", "refuse a non-drill database"
    with psycopg.connect(dsn) as connection:
        assert connection.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'").fetchone()[0] == 0
        for role in ("agent_economy_app", "agent_economy_supervisor"):
            connection.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS").format(
                sql.Identifier(role), sql.Literal(fields["password"])))
    return fields


def _catalog(dsn, role):
    return HostedCatalog(make_conninfo(dsn, user=role), expected_role=role,
                         capability="supervisor" if role.endswith("supervisor") else "web")


def test_catalog_and_world_replacement_resume_without_duplicate_action(tmp_path, monkeypatch):
    assert conninfo_to_dict(SOURCE)["host"] != conninfo_to_dict(TARGET)["host"]
    source_fields = _database(SOURCE)
    target_fields = _database(TARGET)
    migrate(SOURCE, runtime_role="agent_economy_app", supervisor_role="agent_economy_supervisor")
    password = "disposable ops drill password"
    bootstrap = HostedCatalog(SOURCE)
    tenants = [bootstrap.create_tenant_with_admin(
        slug=f"drill-{i}", tenant_name=f"Drill {i}", email=f"drill-{i}@example.test",
        user_name="Drill", password_hash=hash_password(password))[:2] for i in range(2)]
    source_catalog = _catalog(SOURCE, "agent_economy_supervisor")
    web = _catalog(SOURCE, "agent_economy_app")
    source_catalog.assert_runtime_security()
    web.assert_runtime_security()
    root = tmp_path / "source"
    root.mkdir()
    remote = tmp_path / "backup-server"
    (remote / "backup").mkdir(parents=True)
    reader_keys = tmp_path / "reader-keys"
    reader_keys.mkdir()
    binary = os.environ["AE_LITESTREAM_BIN"]
    started = time.monotonic()
    with ExitStack() as resources:
        replica = resources.enter_context(sftp_replica(remote, tmp_path))
        reader = resources.enter_context(sftp_replica(remote, reader_keys, username="restore", read_only=True))
        replica["sync-interval"] = "100ms"
        config = {"dbs": [{"dir": str(root), "pattern": "*.db", "recursive": True, "watch": True, "replica": replica}]}
        path = tmp_path / "litestream.yml"
        path.write_text(yaml.safe_dump(config))
        log = resources.enter_context((tmp_path / "litestream.log").open("wb"))
        process = subprocess.Popen([binary, "replicate", "-config", str(path)], stdout=log, stderr=log)
        # Match production ordering: the watcher is started before admitting worlds.
        time.sleep(1)

        async def scenario():
            profile = tiny_external_profile()
            first = HostedRunSupervisor(source_catalog, FilesystemArtifactStore(tmp_path / "snapshots-source"),
                work_root=root, profiles={"drill": profile}, instance_id="source",
                streaming_backup=LitestreamBackup(binary=binary, run_root=root, config=config), snapshot_interval_ticks=0)
            second = None
            try:
                tenant, owner = tenants[0]
                handle = await first.create_run(tenant.id, owner.id, "drill", "Recovery drill")
                foreign = await first.create_run(tenants[1][0].id, tenants[1][1].id, "drill", "Other tenant")
                service = handle.world.runtime.external
                created = service.create_connection(tenant_id=str(tenant.id), owner_id=str(owner.id), display_name="Drill actor", tier="actor")
                token = created["credential"]["token"]
                connection_id = created["connection"]["id"]
                web.create_external_agent_with_credential(tenant.id, owner_user_id=owner.id,
                    run_id=handle.public_run_id, run_connection_id=connection_id, display_name="Drill actor",
                    biography="", preferred_occupation="", tier="actor", scopes=["world.read", "world.act"],
                    token_hash=hashlib.sha256(token.encode()).hexdigest(),
                    credential_expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
                await handle.controller.step()
                auth = service.authenticate(token, rate_limit=False)
                turn = service.turn(auth)
                action = {"target_tick": turn["target_tick"], "action": {"type": "do_nothing"},
                    "observed_projection_hash": turn["projection_hash"], "idempotency_key": "replacement-once"}
                queued = service.submit_action(auth, action)
                assert service.submit_action(auth, action)["submission_id"] == queued["submission_id"]
                await handle.controller.step()
                receipt = service.receipt(auth, queued["submission_id"])
                assert receipt["status"] == "executed"
                before_tick = handle.world.store.tick
                schema_version = handle.world.store.get_meta()["schema_version"]
                before_events = handle.world.store.scalar("SELECT COUNT(*) FROM events")
                before_accounts = [dict(row) for row in handle.world.store.query("SELECT * FROM accounts ORDER BY id")]
                assert Ledger(handle.world.store).reconcile()[0]
                original_path = handle.database_path
                await first.shutdown()  # fence the writer before selecting a consistent recovery point

                replacement = tmp_path / "replacement"
                restore_config = deepcopy(config)
                restore_config["dbs"][0]["replica"] = reader
                recovery = LitestreamBackup(binary=binary, run_root=replacement, config=restore_config)
                # Confirm the latest committed boundary reached the remote replica.
                staged_root = tmp_path / "watermark-check"
                check = LitestreamBackup(binary=binary, run_root=staged_root, config=restore_config)
                destination = staged_root / original_path.relative_to(root)
                deadline = time.monotonic() + 45
                last_error = ""
                while True:
                    try:
                        check.restore(destination, run_key=handle.world_run_id, schema_version=schema_version)
                        with closing(sqlite3.connect(destination)) as db:
                            if db.execute("SELECT tick FROM run_meta").fetchone()[0] == before_tick:
                                break
                    except LitestreamRecoveryError as exc:
                        last_error = str(getattr(exc.__cause__, "stderr", exc))
                    destination.unlink(missing_ok=True)
                    assert process.poll() is None and time.monotonic() < deadline, (last_error, (tmp_path / "litestream.log").read_text())
                    await asyncio.sleep(0.25)
                # Stop the source replication process; replacement cannot read live source files.
                process.terminate()
                await asyncio.to_thread(process.wait, 10)
                module = backup_module()
                monkeypatch.setattr(module, "STATE", tmp_path / "catalog-receipt.json")
                for setting in ("host", "user", "host-key", "path"):
                    monkeypatch.setenv("AE_BACKUP_SFTP_" + setting.replace("-", "_").upper(), replica[setting])
                original_server = module.BackupServer

                class TestServer(original_server):
                    def __init__(self, directory):
                        super().__init__(directory)
                        self.args[self.args.index("-i") + 1] = replica["key-path"]

                monkeypatch.setattr(module, "BackupServer", TestServer)
                for key, value in source_fields.items():
                    if key in {"host", "port", "user", "password", "dbname"}:
                        monkeypatch.setenv("PG" + ("DATABASE" if key == "dbname" else key.upper()), value)
                await asyncio.to_thread(module.backup_once)
                backup_receipt = json.loads(module.STATE.read_text())
                dump = tmp_path / "downloaded-catalog.dump"
                await asyncio.to_thread(module.fetch, backup_receipt["name"], dump)
                env = dict(os.environ)
                for key, value in target_fields.items():
                    if key in {"host", "port", "user", "password", "dbname"}:
                        env["PG" + ("DATABASE" if key == "dbname" else key.upper())] = value
                await asyncio.to_thread(subprocess.run, ["pg_restore", "--exit-on-error", "--dbname=ae_ops_drill", str(dump)],
                    env=env, check=True, capture_output=True, timeout=120)
                restored_catalog = _catalog(TARGET, "agent_economy_supervisor")
                restored_web = _catalog(TARGET, "agent_economy_app")
                restored_catalog.assert_runtime_security()
                restored_web.assert_runtime_security()
                assert restored_web.get_run(tenants[1][0].id, handle.public_run_id) is None
                second = HostedRunSupervisor(restored_catalog, FilesystemArtifactStore(tmp_path / "snapshots-replacement"),
                    work_root=replacement, profiles={"drill": profile}, instance_id="replacement",
                    streaming_backup=recovery, snapshot_interval_ticks=0)
                restored = await second.get_handle(tenant.id, handle.public_run_id)
                assert restored.database_path != original_path
                assert restored.world.store.tick == before_tick
                assert restored.world.store.scalar("SELECT COUNT(*) FROM events") == before_events
                assert [dict(row) for row in restored.world.store.query("SELECT * FROM accounts ORDER BY id")] == before_accounts
                assert Ledger(restored.world.store).reconcile()[0]
                restored_service = restored.world.runtime.external
                restored_auth = restored_service.authenticate(token, rate_limit=False)
                assert restored_service.receipt(restored_auth, queued["submission_id"]) == receipt
                assert restored_service.submit_action(restored_auth, action)["submission_id"] == queued["submission_id"]
                await restored.controller.step()
                assert restored.world.store.tick == before_tick + 1
                assert Ledger(restored.world.store).reconcile()[0]
                assert restored_service.receipt(restored_auth, queued["submission_id"]) == receipt
                # Real TLS socket traffic against the recovered app, with both tenants.
                auth_service = CatalogAuthService(restored_web)
                app = create_hosted_app(catalog=restored_web, auth=auth_service, supervisor=second)
                certificate, key = tmp_path / "cert.pem", tmp_path / "key.pem"
                subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
                    "-out", str(certificate), "-days", "1", "-subj", "/CN=localhost"], check=True, capture_output=True, timeout=30)
                listener = socket.socket()
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
                server = uvicorn.Server(uvicorn.Config(app, ssl_keyfile=str(key), ssl_certfile=str(certificate),
                    access_log=False, log_level="error"))
                task = asyncio.create_task(server.serve(sockets=[listener]))
                try:
                    for _ in range(100):
                        if server.started:
                            break
                        assert not task.done(), "TLS server failed to start"
                        await asyncio.sleep(0.05)
                    assert server.started
                    monkeypatch.setenv("AE_DRILL_PASSWORD", password)
                    users = [LoadUser(t.id, f"drill-{i}@example.test", "AE_DRILL_PASSWORD",
                        __import__("uuid").UUID(handle.public_run_id if i == 0 else foreign.public_run_id))
                        for i, (t, _) in enumerate(tenants)]
                    results = []
                    soak_start = time.monotonic()
                    for _ in range(6):
                        result = await run_load_test(base_url=f"https://127.0.0.1:{port}", users=users,
                            requests_per_user=50, concurrency=8, allow_insecure_loopback=True, max_p95_ms=2000)
                        assert result["status"] == "passed", result
                        results.append(result)
                        await asyncio.sleep(10)
                    report = {"scope": "local-disposable-replacement", "status": "passed",
                        "source_tick": before_tick, "resumed_tick": restored.world.store.tick,
                        "duplicate_action": False, "catalog_sha256": backup_receipt["sha256"],
                        "elapsed_seconds": round(time.monotonic() - started, 3),
                        "soak_seconds": round(time.monotonic() - soak_start, 3), "load_rounds": results}
                    print("OPS_DRILL_RECEIPT=" + json.dumps(report, sort_keys=True))
                    if os.environ.get("AE_OPS_RECEIPT"):
                        Path(os.environ["AE_OPS_RECEIPT"]).write_text(json.dumps(report, indent=2) + "\n")
                finally:
                    server.should_exit = True
                    await asyncio.wait_for(task, timeout=15)
                    listener.close()
            finally:
                if second is not None:
                    await second.shutdown()
                await first.shutdown()

        try:
            asyncio.run(scenario())
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

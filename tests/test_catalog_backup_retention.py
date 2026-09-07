from datetime import datetime, timedelta
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


def backup_module():
    path = Path(__file__).resolve().parents[1] / "deploy/hostinger/catalog_backup.py"
    spec = importlib.util.spec_from_file_location("catalog_backup_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_catalog_retention_keeps_daily_and_weekly_recovery_points():
    module = backup_module()
    today = datetime(2026, 9, 7)
    names = [(today - timedelta(hours=n)).strftime("catalog-%Y%m%dT%H%M%SZ.dump")
             for n in range(60 * 24)]
    retained = module.retained_names(names + ["foreign.dump", "../catalog-20260907T000000Z.dump"])
    assert set(names[:24]) <= retained
    assert 24 <= len(retained) <= 35
    assert len({datetime.strptime(name[8:-5], "%Y%m%dT%H%M%SZ").isocalendar()[:2]
                for name in retained}) == 4
    assert not any(".." in name or name == "foreign.dump" for name in retained)


@pytest.mark.parametrize("receipt_failure", [False, True])
def test_catalog_sftp_round_trip_and_failed_publication(tmp_path, monkeypatch, receipt_failure):
    """Exercise real OpenSSH/SFTP; PostgreSQL tools supply a fixture dump here."""
    if os.name != "posix" or not shutil.which("sftp"):
        pytest.skip("catalog SFTP drill needs Linux OpenSSH")
    pytest.importorskip("paramiko")
    from .storage_sftp_support import sftp_replica
    module = backup_module()
    replica_root = tmp_path / "remote"
    (replica_root / "backup").mkdir(parents=True)
    payload = b"disposable catalog dump fixture\n" * 2000
    real_run = subprocess.run

    def fixture_postgres(args, **kwargs):
        if args[0] == "pg_dump":
            Path(args[args.index("--file") + 1]).write_bytes(payload)
            return subprocess.CompletedProcess(args, 0)
        if args[0] == "pg_restore":
            return subprocess.CompletedProcess(args, 0, stdout=b"fixture TOC")
        return real_run(args, **kwargs)

    monkeypatch.setattr(module.subprocess, "run", fixture_postgres)
    monkeypatch.setattr(module, "STATE", tmp_path / "receipt.json")
    with sftp_replica(replica_root, tmp_path) as replica:
        for setting in ("host", "user", "host-key", "path"):
            monkeypatch.setenv("AE_BACKUP_SFTP_" + setting.replace("-", "_").upper(), replica[setting])
        original = module.BackupServer

        class TestServer(original):
            def __init__(self, directory):
                super().__init__(directory)
                self.args[self.args.index("-i") + 1] = replica["key-path"]

            def batch(self, commands):
                if receipt_failure and any(command.startswith('rename ') and '.json"' in command
                                           for command in commands):
                    raise RuntimeError("receipt publication failed")
                return super().batch(commands)

        monkeypatch.setattr(module, "BackupServer", TestServer)
        if receipt_failure:
            with pytest.raises(RuntimeError, match="receipt publication failed"):
                module.backup_once()
            assert not list((replica_root / "backup/catalog").glob("*.dump"))
            assert not module.STATE.exists()
            return
        module.backup_once()
        receipt = json.loads(module.STATE.read_text())
        target = tmp_path / "restored.dump"
        module.fetch(receipt["name"], target)
        assert target.read_bytes() == payload
        (replica_root / "backup/catalog" / receipt["name"]).write_bytes(b"corrupt")
        with pytest.raises(ValueError, match="failed verification"):
            module.fetch(receipt["name"], tmp_path / "rejected.dump")
        assert not (tmp_path / "rejected.dump").exists()

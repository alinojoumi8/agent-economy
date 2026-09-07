"""Opt-in Docker/PostgreSQL/SFTP disaster-recovery drill; disposable data only."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import subprocess
import time
from uuid import uuid4

import psycopg
import pytest


def test_real_catalog_dump_sftp_fetch_and_postgres_restore(tmp_path):
    image = os.environ.get("AE_CATALOG_BACKUP_IMAGE")
    if not image or os.name != "posix":
        pytest.skip("set AE_CATALOG_BACKUP_IMAGE after building the Linux backup image")
    pytest.importorskip("paramiko")
    from .storage_sftp_support import sftp_replica
    name = "ae-storage-catalog-test-" + uuid4().hex
    environment = {**os.environ, "POSTGRES_PASSWORD": secrets.token_urlsafe(32)}

    def docker(*args, input=None, env=None):
        return subprocess.run(["docker", *args], input=input, env=env,
                              capture_output=True, check=True, timeout=120).stdout

    started = False
    try:
        docker("run", "--detach", "--name", name, "--publish", "127.0.0.1::5432",
               "-e", "POSTGRES_PASSWORD", "-e", "POSTGRES_DB=catalog_source",
               "postgres:17-bookworm", env=environment)
        started = True
        port = int(docker("port", name, "5432/tcp").decode().strip().rsplit(":", 1)[1])
        connection = None
        deadline = time.monotonic() + 60
        while connection is None:
            try:
                connection = psycopg.connect(host="127.0.0.1", port=port, dbname="catalog_source",
                                            user="postgres", password=environment["POSTGRES_PASSWORD"],
                                            autocommit=True, connect_timeout=2)
            except psycopg.OperationalError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.2)
        with connection:
            connection.execute("CREATE ROLE agent_economy_app NOLOGIN")
            connection.execute("CREATE ROLE agent_economy_supervisor NOLOGIN")
            connection.execute("CREATE TABLE agent_ownership (agent_id integer PRIMARY KEY, owner_name text)")
            connection.execute("INSERT INTO agent_ownership VALUES (7, 'owner fixture')")
            connection.execute("ALTER TABLE agent_ownership OWNER TO agent_economy_app")
            connection.execute("GRANT SELECT ON agent_ownership TO agent_economy_supervisor")
            connection.execute("CREATE DATABASE catalog_restored")
        remote = tmp_path / "remote"
        (remote / "backup").mkdir(parents=True)
        output = tmp_path / "output"
        output.mkdir(mode=0o777)
        output.chmod(0o777)  # writable scratch for the image's production UID
        with sftp_replica(remote, tmp_path) as replica:
            environment.update({"PGHOST": "127.0.0.1", "PGPORT": str(port), "PGUSER": "postgres",
                                "PGDATABASE": "catalog_source", "PGPASSWORD": environment["POSTGRES_PASSWORD"]})
            for setting in ("host", "user", "host-key", "path"):
                environment["AE_BACKUP_SFTP_" + setting.replace("-", "_").upper()] = replica[setting]
            # Only the generated fixture key changes ownership. Exercise the
            # image's real unprivileged user, including OpenSSH key checks.
            docker("run", "--rm", "--user", "0:0", "--entrypoint", "chown", "--volume",
                   f"{replica['key-path']}:/key", image, "10001:10001", "/key")
            arguments = ["run", "--rm", "--network", "host",
                         "--volume", f"{replica['key-path']}:/run/secrets/backup_key:ro",
                         "--volume", f"{output}:/scratch"]
            for setting in ("PGHOST", "PGPORT", "PGUSER", "PGDATABASE", "PGPASSWORD",
                            "AE_BACKUP_SFTP_HOST", "AE_BACKUP_SFTP_USER",
                            "AE_BACKUP_SFTP_HOST_KEY", "AE_BACKUP_SFTP_PATH"):
                arguments += ["-e", setting]
            receipt = json.loads(docker(*arguments, image, "once", env=environment).decode().splitlines()[-1])
            docker(*arguments, image, "fetch", "--name", receipt["name"],
                   "--output", "/scratch/restored.dump", env=environment)
        dump = docker("run", "--rm", "--entrypoint", "cat", "--volume", f"{output}:/scratch:ro",
                      image, "/scratch/restored.dump")
        docker("exec", "-i", name, "pg_restore", "--exit-on-error", "--username=postgres",
               "--dbname=catalog_restored", input=dump)
        with psycopg.connect(host="127.0.0.1", port=port, dbname="catalog_restored",
                             user="postgres", password=environment["POSTGRES_PASSWORD"]) as restored:
            assert restored.execute("SELECT * FROM agent_ownership").fetchall() == [(7, "owner fixture")]
            assert restored.execute(
                "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid='agent_ownership'::regclass"
            ).fetchone()[0] == "agent_economy_app"
            assert restored.execute(
                "SELECT has_table_privilege('agent_economy_supervisor','agent_ownership','SELECT')"
            ).fetchone()[0] is True
    finally:
        if started:
            # This exact generated name is the only container the drill owns.
            docker("rm", "--force", name)

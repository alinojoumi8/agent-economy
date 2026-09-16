"""Hourly PostgreSQL catalog backups over verified SFTP; no third-party Python dependencies."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import time

NAME = re.compile(r"catalog-(\d{8}T\d{6}Z)\.dump")
STATE = Path("/tmp/catalog-backup-success.json")


def digest(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def retained_names(names):
    ordered = sorted({name for name in names if NAME.fullmatch(name)}, reverse=True)
    keep = set(ordered[:24])
    days, weeks = set(), set()
    for name in ordered:
        moment = datetime.strptime(NAME.fullmatch(name)[1], "%Y%m%dT%H%M%SZ")
        week = moment.isocalendar()[:2]
        if moment.date() not in days and len(days) < 7:
            keep.add(name)
            days.add(moment.date())
        if week not in weeks and len(weeks) < 4:
            keep.add(name)
            weeks.add(week)
    return keep


class BackupServer:
    def __init__(self, directory):
        raw_host = os.environ["AE_BACKUP_SFTP_HOST"]
        match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9.-]*)(?::([0-9]{1,5}))?", raw_host)
        if not match:
            raise ValueError("backup host must be a DNS name or IPv4 address with optional port")
        host, port = match[1], int(match[2] or 22)
        user = os.environ["AE_BACKUP_SFTP_USER"]
        if not 1 <= port <= 65535 or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", user):
            raise ValueError("invalid backup port or user")
        root = os.environ["AE_BACKUP_SFTP_PATH"]
        if (not re.fullmatch(r"/[A-Za-z0-9_./-]+", root)
                or ".." in PurePosixPath(root).parts or root == "/"):
            raise ValueError("backup path must be a dedicated absolute directory")
        self.remote = root.rstrip("/") + "/catalog"
        key = os.environ["AE_BACKUP_SFTP_HOST_KEY"]
        if not re.fullmatch(r"(?:ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp\d+) [A-Za-z0-9+/=]+", key):
            raise ValueError("invalid SSH public host key")
        known_hosts = Path(directory) / "known_hosts"
        known_hosts.write_text(f"[{host}]:{port} {key}\n{host} {key}\n", encoding="ascii")
        self.args = ["sftp", "-q", "-b", "-", "-P", str(port), "-i", "/run/secrets/backup_key",
                     "-oBatchMode=yes", "-oStrictHostKeyChecking=yes", "-oConnectTimeout=15",
                     f"-oUserKnownHostsFile={known_hosts}", f"{user}@{host}"]

    def batch(self, commands):
        try:
            result = subprocess.run(self.args, input="\n".join(commands) + "\n", text=True,
                                    capture_output=True, timeout=600, check=True)
            return result.stdout
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError("catalog SFTP operation failed") from exc


def backup_once():
    with tempfile.TemporaryDirectory(prefix="catalog-backup-") as directory:
        root = Path(directory)
        server = BackupServer(root)
        name = datetime.now(timezone.utc).strftime("catalog-%Y%m%dT%H%M%SZ.dump")
        dump = root / name
        # PG* environment variables keep credentials out of process arguments.
        subprocess.run(["pg_dump", "--format=custom", "--compress=6", "--file", str(dump)],
                       check=True, timeout=1800, capture_output=True)
        subprocess.run(["pg_restore", "--list", str(dump)], check=True, timeout=60, capture_output=True)
        checksum = digest(dump)
        manifest = root / (name + ".json")
        manifest.write_text(json.dumps({"version": 1, "name": name, "sha256": checksum,
                                        "bytes": dump.stat().st_size}), encoding="utf-8")
        remote = f"{server.remote}/{name}"
        verification = root / "downloaded.dump"
        pending = f"{server.remote}/catalog-upload.pending"
        server.batch([f'-mkdir "{server.remote}"',
                      f'put "{dump}" "{pending}"',
                      f'get "{pending}" "{verification}"'])
        if digest(verification) != checksum:
            raise RuntimeError("remote catalog backup failed checksum verification")
        # Publish the tiny receipt first and the verified dump last. A failed
        # receipt rename must not strand an untracked full dump on every retry.
        server.batch([f'put "{manifest}" "{pending}.json"',
                      f'rename "{pending}.json" "{remote}.json"',
                      f'rename "{pending}" "{remote}"'])
        # Only this command's fixed catalog namespace and completed dump/receipt
        # pairs are eligible. Litestream's LTX chain is managed by Litestream.
        listing = server.batch([f'ls -1 "{server.remote}"'])
        listed = {PurePosixPath(line.strip()).name for line in listing.splitlines()}
        names = {item for item in listed if NAME.fullmatch(item) and item + ".json" in listed}
        stale = sorted(names - retained_names(names))
        for item in stale:
            server.batch([f'rm "{server.remote}/{item}"', f'rm "{server.remote}/{item}.json"'])
        receipt = {"completed_at": time.time(), "name": name, "sha256": checksum,
                   "bytes": dump.stat().st_size, "pruned": len(stale)}
        STATE.write_text(json.dumps(receipt), encoding="utf-8")
        print(json.dumps(receipt), flush=True)


def fetch(name, destination):
    if not NAME.fullmatch(name):
        raise ValueError("choose a catalog-YYYYMMDDTHHMMSSZ.dump backup name")
    target = Path(destination).absolute()
    if target.exists():
        raise FileExistsError("catalog restore output already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="catalog-restore-", dir=target.parent) as directory:
        root = Path(directory)
        server = BackupServer(root)
        staged = root / name
        manifest = root / (name + ".json")
        server.batch([f'get "{server.remote}/{name}.json" "{manifest}"',
                      f'get "{server.remote}/{name}" "{staged}"'])
        receipt = json.loads(manifest.read_text(encoding="utf-8"))
        if (receipt.get("version") != 1 or receipt.get("name") != name
                or receipt.get("sha256") != digest(staged)
                or receipt.get("bytes") != staged.stat().st_size):
            raise ValueError("catalog download failed verification")
        subprocess.run(["pg_restore", "--list", str(staged)], check=True, timeout=60, capture_output=True)
        os.link(staged, target)
        print(json.dumps({"verified": True, "sha256": receipt["sha256"], "output": str(target)}))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "once", "health", "fetch"))
    parser.add_argument("--name")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    if args.command == "health":
        if not STATE.is_file() or time.time() - json.loads(STATE.read_text())["completed_at"] > 90 * 60:
            raise SystemExit(1)
    elif args.command == "fetch":
        if not args.name or not args.output:
            parser.error("fetch requires --name and --output")
        fetch(args.name, args.output)
    elif args.command == "once":
        backup_once()
    else:
        while True:
            try:
                backup_once()
                time.sleep(3600)
            except Exception as exc:
                print(json.dumps({"backup_failed": type(exc).__name__}), flush=True)
                time.sleep(300)


if __name__ == "__main__":
    main()

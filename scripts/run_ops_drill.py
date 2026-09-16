"""Run the local replacement drill in isolated Docker resources, then remove only those resources."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import time
from uuid import uuid4

from scripts.docker_preflight import ensure_ready


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="ae-ops-test:local")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("tmp/ops-drill"))
    args = parser.parse_args(argv)
    docker = shutil.which("docker")
    if not docker or ensure_ready(docker, wait_seconds=0)["status"] != "ready":
        raise SystemExit("Docker is unavailable; no resources were changed")
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    receipt = output / "receipt.json"
    if receipt.exists():
        raise SystemExit("Choose a fresh output directory; preserve the previous receipt")
    log_path = output / "drill.log"
    prefix = "ae-ops-drill-" + uuid4().hex[:12]
    containers = []
    network_created = False
    env = dict(os.environ)
    env["POSTGRES_PASSWORD"] = secrets.token_urlsafe(32)
    with log_path.open("w", encoding="utf-8") as log:
        def run(*command, timeout=180, check=True):
            result = subprocess.run([docker, *command], env=env, stdout=log, stderr=log,
                                    timeout=timeout, cwd=root)
            if check and result.returncode:
                raise RuntimeError("Docker drill step failed; inspect private drill.log")
            return result

        try:
            if not args.skip_build:
                run("build", "-f", "deploy/hostinger/Dockerfile.ops-test", "-t", args.image, ".", timeout=900)
            run("network", "create", prefix)
            network_created = True
            for side in ("source", "replacement"):
                name = prefix + "-" + side
                containers.append(name)
                run("run", "-d", "--name", name, "--network", prefix, "--network-alias", side,
                    "--label", "agent-economy.disposable-ops-drill=true", "-e", "POSTGRES_PASSWORD",
                    "-e", "POSTGRES_DB=ae_ops_drill", "postgres:17-bookworm")
                deadline = time.monotonic() + 60
                while run("exec", name, "pg_isready", "-U", "postgres", "-d", "ae_ops_drill", check=False).returncode:
                    if time.monotonic() > deadline:
                        raise RuntimeError("Disposable PostgreSQL did not become ready")
                    time.sleep(1)
            for side, setting in (("source", "AE_OPS_SOURCE_DSN"), ("replacement", "AE_OPS_TARGET_DSN")):
                env[setting] = f"host={side} port=5432 dbname=ae_ops_drill user=postgres password={env['POSTGRES_PASSWORD']}"
            name = prefix + "-runner"
            containers.append(name)
            run("run", "--name", name, "--network", prefix,
                "--label", "agent-economy.disposable-ops-drill=true",
                "--mount", f"type=bind,source={root},target=/app,readonly",
                "--mount", f"type=bind,source={output},target=/evidence",
                "-e", "AE_OPS_SOURCE_DSN", "-e", "AE_OPS_TARGET_DSN", "-e", "AE_OPS_RECEIPT=/evidence/receipt.json",
                args.image, "-q", "-s", "--basetemp=/tmp/pytest-ops", "-p", "no:cacheprovider",
                "tests/test_hosted_replacement_drill.py", timeout=600)
            result = json.loads(receipt.read_text())
            if result.get("status") != "passed":
                raise RuntimeError("Drill did not produce a passing receipt")
            print(json.dumps({"status": "passed", "receipt": str(receipt), "scope": result["scope"]}))
        finally:
            for name in reversed(containers):
                # Names are generated here, never read from an inventory or user path.
                run("rm", "--force", "--volumes", name, check=False, timeout=45)
            if network_created:
                run("network", "rm", prefix, check=False, timeout=45)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Bounded Docker Desktop readiness check; never resets or restarts the engine.

Use --start only to launch a stopped Desktop once. Diagnostics deliberately omit
container environments, logs and raw daemon errors, which may contain secrets.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time


def probe(docker):
    try:
        result = subprocess.run([docker, "info", "--format", "{{json .ServerVersion}}"],
                                capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            version = json.loads(result.stdout)
            if isinstance(version, str) and version:
                return version
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return None


def desktop_running():
    result = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                            capture_output=True, text=True, timeout=10, check=True)
    return any(name in result.stdout.lower() for name in ("docker desktop.exe", "com.docker.backend.exe"))


def ensure_ready(docker, *, start=False, wait_seconds=60):
    deadline = time.monotonic() + wait_seconds
    version = probe(docker)
    if version:
        return {"status": "ready", "server_version": version, "desktop_started": False}
    started = False
    if start and os.name == "nt" and not desktop_running():
        executable = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Docker/Docker/Docker Desktop.exe"
        if not executable.is_file():
            raise RuntimeError("Docker Desktop executable is missing")
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        subprocess.Popen([str(executable)], startupinfo=startup,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        started = True
    while time.monotonic() < deadline:
        time.sleep(min(2, max(0, deadline - time.monotonic())))
        version = probe(docker)
        if version:
            return {"status": "ready", "server_version": version, "desktop_started": started}
    return {"status": "unavailable", "desktop_started": started,
            "action": "Stop Docker-dependent work. Inspect Desktop diagnostics; preserve containers, volumes and sockets."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", action="store_true")
    parser.add_argument("--wait-seconds", type=int, default=60)
    args = parser.parse_args(argv)
    if not 0 <= args.wait_seconds <= 180:
        parser.error("wait-seconds must be between 0 and 180")
    docker = shutil.which("docker")
    if not docker:
        parser.error("Docker CLI not found on PATH")
    try:
        result = ensure_ready(docker, start=args.start, wait_seconds=args.wait_seconds)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        result = {"status": "unavailable", "error_type": type(exc).__name__}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())

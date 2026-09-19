"""Linux-only, per-call child subreaper for an isolated Hermes process tree."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import time

import psutil


def contain_children():
    """Adopt orphan descendants, and clean up if the calling worker exits."""
    parent = os.getppid()
    libc = ctypes.CDLL(None, use_errno=True)
    for option, value in ((36, 1), (1, signal.SIGTERM)):
        if libc.prctl(option, value, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "Could not contain Hermes descendants")
    if os.getppid() != parent:
        raise InterruptedError("The calling worker exited")


def reap_children(timeout=10):
    """Kill only this guardian's children, including newly adopted orphans."""
    deadline = time.monotonic() + timeout
    guardian = psutil.Process()
    while True:
        # Killing parents causes their descendants to become our direct
        # children. Repeat discovery until waitpid proves there are none left.
        for child in guardian.children():
            try:
                if child.ppid() == guardian.pid:
                    child.suspend()
                    child.kill()
            except psutil.NoSuchProcess:
                pass
        try:
            while os.waitpid(-1, os.WNOHANG)[0]:
                pass
        except ChildProcessError:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)


def supervise(command, timeout):
    def interrupted(_signum, _frame):
        raise InterruptedError("Hermes guardian interrupted")

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    result = {"state": "failed"}
    process = None
    try:
        contain_children()
        process = subprocess.Popen(command)
        try:
            code = process.wait(timeout=timeout)
            result = {"state": "complete", "returncode": code}
        except subprocess.TimeoutExpired:
            result = {"state": "timed_out"}
    except BaseException as exc:
        result = {"state": "failed", "error_type": type(exc).__name__}
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            clean = reap_children()
        except Exception:
            clean = False
        if not clean:
            result = {"state": "cleanup_failed"}
        if process is not None:
            # The subreaper may already have collected the root during cleanup.
            process.poll()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("A Hermes command is required")
    result = supervise(command, args.timeout)
    args.result.write_text(json.dumps(result), encoding="utf-8")
    return 0 if result["state"] in {"complete", "timed_out"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

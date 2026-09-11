"""Run the production city -> two price studies workflow in isolated local worlds.

No main-run paths, paid providers, Vite proxy, or mocked HTTP responses. Artifacts
are retained in a new directory, including on failure. Run from a stable checkout:
editing source during a study correctly invalidates its scientific identity.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import psutil
import uvicorn

from research.study_bundle import import_study_bundle
from run import open_run
from run_config import load_config
from server.app import create_app


def _dump_sha256(store) -> str:
    digest = hashlib.sha256()
    for statement in store.conn.iterdump():
        digest.update(statement.encode("utf-8") + b"\n")
    return digest.hexdigest()


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


@contextmanager
def _serve(app):
    """Keep the prebound socket alive until Uvicorn has stopped accepting."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
        errors = []

        def run_server():
            try:
                server.run(sockets=[listener])
            except BaseException as exc:
                errors.append(f"{type(exc).__name__}: {exc}")

        thread = threading.Thread(target=run_server, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 30
            while not server.started:
                if not thread.is_alive() or time.monotonic() > deadline:
                    raise RuntimeError(f"Production server did not start: {errors}")
                time.sleep(0.1)
            yield url
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            if thread.is_alive() or errors:
                raise RuntimeError(f"Production server did not stop cleanly: {errors}")


def _stop_children(owned: dict[int, psutil.Process]) -> list[int]:
    """Only processes created by this standalone driver may be terminated."""
    for child in psutil.Process().children(recursive=True):
        owned[child.pid] = child
    alive = []
    for child in owned.values():
        try:
            # psutil checks creation time before signalling, protecting PID reuse.
            child.terminate()
            alive.append(child)
        except psutil.NoSuchProcess:
            pass
    _, remaining = psutil.wait_procs(alive, timeout=5)
    for child in remaining:
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass
    _, remaining = psutil.wait_procs(remaining, timeout=5)
    return [child.pid for child in remaining]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, help="New directory; never reuse or delete an existing run")
    args = parser.parse_args()
    node = shutil.which("node")
    cli = ROOT / "dashboard/node_modules/@playwright/test/cli.js"
    if not node or not cli.is_file() or not (ROOT / "server/static/index.html").is_file():
        parser.error("Install dashboard dependencies and build the production bundle first.")
    # Windows research tests retain large artifacts elsewhere; preserve the same
    # 40-GiB headroom. A fresh Linux CI runner needs 5 GiB for this bounded check.
    base = Path(tempfile.gettempdir())
    windows_base = Path.home() / ".codex/tmp"
    if os.name == "nt" and windows_base.is_dir():
        base = windows_base
    if args.output_root:
        target = args.output_root.absolute()
        if target.exists() or target.is_symlink():
            parser.error("--output-root must not already exist")
        base = target.parent
    minimum = (40 if os.name == "nt" else 5) * 1024**3
    if not base.is_dir() or shutil.disk_usage(base).free < minimum:
        parser.error(f"Need an existing parent directory with {minimum // 1024**3} GiB free")
    if args.output_root:
        root = target
        root.mkdir()
    else:
        root = Path(tempfile.mkdtemp(prefix="ae-city-", dir=base))
    root = root.resolve()
    print(f"Acceptance evidence: {root}", flush=True)
    config = load_config(ROOT / "runs/city-research-acceptance.yaml")
    routes = [config["llm"]["default_route"], *config["llm"].get("routes", {}).values()]
    if any(route.get("provider") != "scripted" for route in routes):
        raise ValueError("The acceptance profile must use only scripted decisions")
    config.update({
        "checkpoint_dir": str(root / "checkpoints"), "report_dir": str(root / "reports"),
        "operator_workspace": {"path": str(root / "operator/workspace.db")},
        "operator_research": {"data_root": str(root / "studies"),
                              "out_dir": str(root / "study-reports"),
                              "checkpoint_root": str(root / "study-checkpoints"),
                              "policy_root": str(root / "policies")},
    })
    store = world = None
    owned: dict[int, psutil.Process] = {}
    receipt = {"contract": "city-research-acceptance-v1", "status": "failed", "output_root": str(root)}
    started = time.monotonic()
    try:
        store, world, run_id = open_run(config, None, None, data_dir=root / "worlds")
        asyncio.run(world.run(max_ticks=3))
        if store.tick != 3 or world.status != "paused":
            raise RuntimeError("Fixture did not complete three days and pause")
        person = dict(store.query(
            "SELECT a.id,a.name,e.firm_id FROM agents a JOIN employments e ON e.agent_id=a.id "
            "WHERE a.role IS NULL AND e.status='active' ORDER BY a.id LIMIT 1")[0])
        trade = dict(store.query("SELECT tick,firm_id,price_cents,qty FROM trades ORDER BY id LIMIT 1")[0])
        if (store.scalar("SELECT COUNT(*) FROM places") < 1
                or store.scalar("SELECT COUNT(*) FROM events WHERE kind='goods_sale'") < 1
                or store.scalar("SELECT COUNT(*) FROM llm_calls WHERE provider<>'scripted' OR cost_usd<>0")
                or store.scalar("SELECT COUNT(*) FROM llm_attempts")):
            raise RuntimeError("Fixture lacks city/market evidence or has external-provider activity")
        fixture = {"run_id": run_id, "tick": store.tick, "person": person, "trade": trade,
                   "population": store.scalar("SELECT COUNT(*) FROM agents"), "output_root": str(root)}
        app = create_app(world)
        with _serve(app) as url:
            fixture["base_url"] = url
            _write(root / "fixture.json", fixture)
            with urlopen(url + "/api/run/status", timeout=5) as response:
                if json.load(response)["tick"] != 3:
                    raise RuntimeError("Server is not observing the owned fixture")
            before = _dump_sha256(store)
            receipt["world_dump_before"] = before
            env = {**os.environ, "AE_CITY_ACCEPTANCE_FIXTURE": str(root / "fixture.json")}
            with (root / "browser.log").open("w", encoding="utf-8") as log:
                browser = subprocess.Popen(
                    [node, str(cli), "test", "--config", "playwright.city-research.config.ts"],
                    cwd=ROOT / "dashboard", env=env, stdin=subprocess.DEVNULL,
                    stdout=log, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                deadline = time.monotonic() + 600
                while browser.poll() is None:
                    for child in psutil.Process().children(recursive=True):
                        owned[child.pid] = child
                    if time.monotonic() > deadline:
                        raise TimeoutError("City/research browser exceeded the ten-minute limit")
                    time.sleep(0.25)
                if browser.returncode:
                    raise RuntimeError(f"Browser workflow failed ({browser.returncode}); see {root / 'browser.log'}")
            evidence = json.loads((root / "browser-evidence.json").read_text(encoding="utf-8"))
            if {study["preset"] for study in evidence["studies"]} != {"G2", "F2"} or len(evidence["studies"]) != 2:
                raise RuntimeError("Both price studies must complete exactly once")
            imports = []
            for study in evidence["studies"]:
                # Only the browser's exact bounded download filename is admitted.
                archive = root / "downloads" / f"study-{study['id']}.zip"
                imported = import_study_bundle(archive, root / f"import-{study['preset']}",
                                              expected_sha256=study["sha256"], max_bytes=128 * 1024**2)
                if imported["status"] != "verified":
                    raise RuntimeError("Downloaded evidence did not verify independently")
                imports.append({"preset": study["preset"], "status": imported["status"],
                                "sha256": imported["bundle_sha256"]})
            after = _dump_sha256(store)
            if before != after or store.tick != 3 or world.status != "paused":
                raise RuntimeError("Observing the city or running independent studies changed the source world")
            receipt.update(status="passed", run_id=run_id, population=fixture["population"], tick=3,
                           world_dump_before=before, world_dump_after=after,
                           studies=evidence["studies"], imports=imports)
    except Exception as exc:
        receipt.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        print(receipt["error"], file=sys.stderr, flush=True)
    finally:
        remaining = _stop_children(owned)
        if remaining:
            receipt.update(status="failed", cleanup_error="Owned processes did not stop", remaining_pids=remaining)
        if store:
            receipt["world_dump_after"] = _dump_sha256(store)
            if (receipt["status"] == "passed"
                    and receipt["world_dump_before"] != receipt["world_dump_after"]):
                receipt.update(status="failed", error="Source world changed during server shutdown")
        if world:
            world.close()
        if store:
            store.close()
        receipt["elapsed_seconds"] = round(time.monotonic() - started, 2)
        _write(root / "acceptance.json", receipt)
    print(json.dumps(receipt), flush=True)
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

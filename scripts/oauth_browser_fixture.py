"""Disposable, provider-free HTTP world for Chromium OAuth regression tests."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import socket
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn

from engine.store import Store
from run_config import load_config
from server.app import create_app
from world.loop import World


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    args = parser.parse_args()
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    config = load_config("runs/hermes-local.yaml")
    config["checkpoint_dir"] = str(directory / "checkpoints")
    config["external_gateway"]["public_join"]["passport_db_path"] = str(
        directory / "passports.db")
    store = Store(str(directory / "world.db"))
    store.init_run_meta("oauth-browser", 42, config)
    world = World(store, config)
    try:
        world.initialize()
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            address = f"http://127.0.0.1:{listener.getsockname()[1]}"
            (directory / "ready.json").write_text(json.dumps({"url": address}))
            server = uvicorn.Server(uvicorn.Config(
                create_app(world), log_level="warning", access_log=False))
            def stop_when_requested() -> None:
                while not server.should_exit:
                    if (directory / "stop").exists():
                        server.should_exit = True
                        return
                    time.sleep(0.1)
            threading.Thread(target=stop_when_requested, daemon=True).start()
            server.run(sockets=[listener])
    finally:
        world.close()


if __name__ == "__main__":
    main()

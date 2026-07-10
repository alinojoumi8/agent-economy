"""Agent Economy entrypoint.

  python run.py --config runs/base.yaml                 # serve dashboard + world (paused)
  python run.py --config runs/base.yaml --ticks 30      # headless: run 30 ticks, report, exit
  python run.py --config runs/base.yaml --resume RUNID  # resume an existing run db
  python run.py --config runs/base.yaml --replay RUNID  # exact replay from stored LLM calls
  python run.py --config runs/base.yaml --fork RUNID@TICK   # what-if branch from a checkpoint
  python run.py --report RUNID                          # generate report for a stored run
  python run.py --experiment runs/experiments/x.yaml    # multi-seed experiment + comparison report

One process: FastAPI serves the static dashboard and drives the world loop.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import yaml

from engine.store import Store
from world.loop import World, new_run_id

DATA_DIR = Path("data/runs")


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def open_run(config: dict, resume: str | None, replay: str | None) -> tuple[Store, World, str]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if resume or replay:
        run_id = resume or replay
        db = DATA_DIR / f"{run_id}.db"
        if not db.exists():
            sys.exit(f"run database not found: {db}")
        store = Store(str(db))
        stored_cfg = json.loads(store.get_meta()["config_json"])
        stored_cfg.update({k: v for k, v in config.items() if k in ("speed_delay_s",)})
        world = World(store, stored_cfg, replay=bool(replay))
        world.restore_prng_state()
        return store, world, run_id
    run_id = new_run_id()
    store = Store(str(DATA_DIR / f"{run_id}.db"))
    store.init_run_meta(run_id, int(config.get("seed", 42)), config)
    world = World(store, config)
    world.initialize()
    return store, world, run_id


def fork_run(spec: str, data_dir: Path = DATA_DIR) -> str:
    """Fork a new run from a checkpoint (TECH-SPEC §13 what-if branching).

    `spec` is either a checkpoint .db path or `RUNID@TICK` (uses the newest
    checkpoint at or before TICK). The copy gets a fresh run id with
    parent_run_id + fork_tick set, so lineage is queryable.
    """
    import shutil

    src = Path(spec)
    if not src.exists() and "@" in spec:
        run_id, _, tick_s = spec.partition("@")
        parent_db = data_dir / f"{run_id}.db"
        if not parent_db.exists():
            sys.exit(f"run database not found: {parent_db}")
        parent = Store(str(parent_db))
        row = parent.query_one(
            "SELECT path, tick FROM checkpoints WHERE tick<=? ORDER BY tick DESC, id DESC LIMIT 1",
            (int(tick_s),))
        parent.close()
        if not row:
            sys.exit(f"no checkpoint at or before tick {tick_s} for run {run_id}")
        src = Path(row["path"])
    if not src.exists():
        sys.exit(f"checkpoint not found: {src}")

    new_id = new_run_id()
    data_dir.mkdir(parents=True, exist_ok=True)
    dest = data_dir / f"{new_id}.db"
    shutil.copyfile(src, dest)
    store = Store(str(dest))
    meta = store.get_meta()
    store.set_meta(run_id=new_id, parent_run_id=meta["run_id"], fork_tick=int(meta["tick"]),
                   status="paused")
    store.log_event(int(meta["tick"]), "fork", {
        "parent_run_id": meta["run_id"], "fork_tick": int(meta["tick"]),
        "new_run_id": new_id}, phase="NIGHT_CLOSE", importance=2.0)
    store.commit()
    store.close()
    print(f"[agent-economy] forked {meta['run_id']} @ t{meta['tick']} -> {new_id}")
    return new_id


async def headless(world: World, ticks: int) -> None:
    await world.run(max_ticks=ticks)


def main() -> None:
    ap = argparse.ArgumentParser(description="Agent Economy")
    ap.add_argument("--config", default="runs/base.yaml")
    ap.add_argument("--ticks", type=int, default=None, help="run N ticks headless then exit")
    ap.add_argument("--resume", default=None, help="resume run id")
    ap.add_argument("--replay", default=None, help="replay run id from stored LLM responses")
    ap.add_argument("--fork", default=None,
                    help="fork a what-if branch: checkpoint .db path or RUNID@TICK")
    ap.add_argument("--report", default=None, help="generate end-of-run report for run id and exit")
    ap.add_argument("--experiment", default=None,
                    help="run a multi-seed experiment from a spec yaml (P1 R14) and exit")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--serve", action="store_true", help="serve dashboard even with --ticks")
    args = ap.parse_args()

    if args.experiment:
        from experiments.harness import run_experiment
        run_experiment(args.experiment)
        return

    if args.report:
        db = DATA_DIR / f"{args.report}.db"
        if not db.exists():
            sys.exit(f"run database not found: {db}")
        store = Store(str(db))
        from reports.generate import generate_report
        print(generate_report(store))
        return

    config = load_config(args.config)
    if args.fork:
        args.resume = fork_run(args.fork)
    store, world, run_id = open_run(config, args.resume, args.replay)
    print(f"[agent-economy] run {run_id} @ tick {store.tick} "
          f"(seed {store.get_meta()['seed']}, {'replay' if args.replay else 'live'})")

    if args.ticks is not None and not args.serve:
        asyncio.run(headless(world, args.ticks))
        from reports.generate import generate_report
        path = generate_report(store, world)
        gov = world.gateway.governor.status()
        print(f"[agent-economy] done @ tick {store.tick} · spend ${gov['total_spend_usd']:.2f} "
              f"· report: {path}")
        return

    import uvicorn
    from server.app import create_app
    app = create_app(world)
    print(f"[agent-economy] observatory: http://{args.host}:{args.port}  (world starts paused - press Run)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

"""Agent Economy entrypoint.

  python run.py --config runs/base.yaml                 # serve dashboard + world (paused)
  python run.py --config runs/base.yaml --ticks 30      # headless: run 30 ticks, report, exit
  python run.py --config runs/production.yaml --preflight       # validate real-provider config
  python run.py --config runs/production.yaml --preflight-live  # authenticate + confirm models
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
import logging
import sys
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

from engine.store import Store
from llm.gateway import Gateway
from llm.readiness import validate_llm_config
from world.loop import World, new_run_id
from observability import configure_logging, get_logger, log_event as operational_log

DATA_DIR = Path("data/runs")
DEFAULT_CONFIG = "runs/production.yaml"
logger = get_logger("cli")


def _deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: str, _seen: Optional[set[Path]] = None) -> dict:
    cfg_path = Path(path).resolve()
    seen = set() if _seen is None else _seen
    if cfg_path in seen:
        raise ValueError(f"config inheritance cycle at {cfg_path}")
    seen.add(cfg_path)
    with cfg_path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    parent = config.pop("extends", None)
    if parent:
        parent_path = (cfg_path.parent / str(parent)).resolve()
        config = _deep_merge(load_config(str(parent_path), seen), config)
    return config


async def provider_preflight(config: dict, *, live: bool = False) -> dict:
    report = validate_llm_config(config, raise_on_error=False)
    if not report["ready"] or not live:
        return {**report, "live_checked": False}
    store = Store(":memory:")
    store.init_run_meta("preflight", int(config.get("seed", 42)), config)
    return await Gateway(store, config).preflight(live=True)


def open_run(config: dict, resume: str | None, replay: str | None, *,
             data_dir: Path = DATA_DIR) -> tuple[Store, World, str]:
    data_dir.mkdir(parents=True, exist_ok=True)
    if resume:
        run_id = resume
        db = data_dir / f"{run_id}.db"
        if not db.exists():
            sys.exit(f"run database not found: {db}")
        store = Store(str(db))
        stored_cfg = json.loads(store.get_meta()["config_json"])
        stored_cfg.update({k: v for k, v in config.items() if k in ("speed_delay_s",)})
        world = World(store, stored_cfg)
        world.restore_prng_state()
        return store, world, run_id
    if replay:
        source_db = data_dir / f"{replay}.db"
        if not source_db.exists():
            sys.exit(f"run database not found: {source_db}")
        source_store = Store(str(source_db))
        source_meta = source_store.get_meta()
        replay_cfg = json.loads(source_meta["config_json"])
        source_tick = int(source_meta["tick"])
        source_seed = int(source_meta["seed"])
        source_store.close()
        replay_cfg.update({k: v for k, v in config.items() if k in ("speed_delay_s",)})
        replay_cfg.update({
            "seed": source_seed,
            "replay_source_path": str(source_db.resolve()),
            "replay_source_run_id": replay,
            "replay_source_tick": source_tick,
        })
        run_id = f"replay-{replay}-{new_run_id()}"
        store = Store(str(data_dir / f"{run_id}.db"))
        store.init_run_meta(run_id, source_seed, replay_cfg, parent_run_id=replay, fork_tick=0)
        world = World(store, replay_cfg, replay=True)
        world.initialize()
        return store, world, run_id
    run_id = new_run_id()
    store = Store(str(data_dir / f"{run_id}.db"))
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
    operational_log(logger, logging.INFO, "run.fork.created",
                    parent_run_id=meta["run_id"], fork_tick=int(meta["tick"]),
                    run_id=new_id)
    print(f"[agent-economy] forked {meta['run_id']} @ t{meta['tick']} -> {new_id}")
    return new_id


async def headless(world: World, ticks: int) -> None:
    await world.run(max_ticks=ticks)


def main() -> None:
    load_dotenv()
    configure_logging()
    ap = argparse.ArgumentParser(description="Agent Economy")
    ap.add_argument("--config", default=DEFAULT_CONFIG,
                    help="world config (default: locked MiniMax/Kimi production profile)")
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
    ap.add_argument("--preflight", action="store_true",
                    help="validate provider routes and required environment variables, then exit")
    ap.add_argument("--preflight-live", action="store_true",
                    help="also authenticate and confirm configured models through provider /models APIs")
    args = ap.parse_args()
    mode = ("experiment" if args.experiment else "report" if args.report else
            "preflight" if (args.preflight or args.preflight_live) else
            "fork" if args.fork else "replay" if args.replay else
            "resume" if args.resume else "run")
    operational_log(logger, logging.INFO, "cli.command.started", mode=mode)

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
    operational_log(logger, logging.INFO, "config.loaded",
                    path=str(Path(args.config).resolve()), mode=mode,
                    seed=config.get("seed", 42))
    if args.preflight or args.preflight_live:
        report = asyncio.run(provider_preflight(config, live=args.preflight_live))
        print(json.dumps(report, indent=2))
        ready = report.get("ready", False)
        live_ready = report.get("live_ready", True) if args.preflight_live else True
        if not (ready and live_ready):
            operational_log(logger, logging.ERROR, "provider.preflight.failed",
                            live=args.preflight_live, ready=ready,
                            live_ready=live_ready, errors=report.get("errors", []))
            raise SystemExit(2)
        operational_log(logger, logging.INFO, "provider.preflight.completed",
                        live=args.preflight_live, ready=ready,
                        live_ready=live_ready)
        return
    if args.fork:
        args.resume = fork_run(args.fork)
    store, world, run_id = open_run(config, args.resume, args.replay)
    operational_log(logger, logging.INFO, "run.opened",
                    run_id=run_id, tick=store.tick,
                    seed=store.get_meta()["seed"], replay=bool(args.replay),
                    resumed=bool(args.resume))
    print(f"[agent-economy] run {run_id} @ tick {store.tick} "
          f"(seed {store.get_meta()['seed']}, {'replay' if args.replay else 'live'})")

    replay_ticks = int(world.config.get("replay_source_tick", 0)) if args.replay else None
    ticks = args.ticks if args.ticks is not None else replay_ticks
    if ticks is not None and not args.serve:
        asyncio.run(headless(world, ticks))
        if args.replay:
            from world.replay_verify import verify_replay
            source = Path(str(world.config["replay_source_path"]))
            proof = verify_replay(source, store.path)
            print(json.dumps(proof, indent=2))
            if not proof["exact"]:
                operational_log(logger, logging.ERROR, "replay.verification.failed",
                                run_id=run_id, source_run_id=args.replay,
                                differences=proof.get("differences"))
                raise SystemExit(3)
            operational_log(logger, logging.INFO, "replay.verification.completed",
                            run_id=run_id, source_run_id=args.replay,
                            tables=proof.get("tables"))
        from reports.generate import generate_report
        path = generate_report(
            store, world, out_dir=str(config.get("report_dir", "reports/out")))
        gov = world.gateway.governor.status()
        if world.last_pause_reason:
            reason = world.last_pause_reason.get("reason", "unknown")
            detail = str(world.last_pause_reason.get("detail", ""))[:500]
            print(f"[agent-economy] paused @ tick {store.tick} · {reason}: {detail} "
                  f"· report: {path}")
            operational_log(logger, logging.WARNING, "headless.run.paused",
                            run_id=run_id, tick=store.tick, reason=reason,
                            detail=detail, report_path=path)
            raise SystemExit(4)
        print(f"[agent-economy] done @ tick {store.tick} · spend ${gov['total_spend_usd']:.2f} "
              f"· report: {path}")
        operational_log(logger, logging.INFO, "headless.run.completed",
                        run_id=run_id, tick=store.tick,
                        spend_usd=gov["total_spend_usd"], report_path=path)
        return

    import uvicorn
    from server.app import create_app
    app = create_app(world)
    operational_log(logger, logging.INFO, "server.starting",
                    run_id=run_id, host=args.host, port=args.port)
    print(f"[agent-economy] observatory: http://{args.host}:{args.port}  (world starts paused - press Run)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        operational_log(logger, logging.CRITICAL, "cli.command.failed",
                        error_type=type(exc).__name__, error=str(exc))
        raise

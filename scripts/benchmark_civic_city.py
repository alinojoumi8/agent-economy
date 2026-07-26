"""Benchmark the Semantics-12 city substrate at 100 and 1,000 agents.

The benchmark uses the deterministic rehearsal profile, exercises two complete
single-writer ticks, and fails if the encounter query is not rooted in indexed
social ties and effective place co-presence.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
import tempfile
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.store import Store
from run_config import load_config
from world.loop import World


def _query_plan(store: Store) -> list[str]:
    rows = store.query(
        "EXPLAIN QUERY PLAN "
        "SELECT st.agent_a,st.agent_b,ep1.place_id "
        "FROM social_ties st "
        "JOIN effective_presence ep1 ON ep1.agent_id=st.agent_a "
        "AND ep1.tick=? AND ep1.slot='evening' "
        "JOIN effective_presence ep2 ON ep2.agent_id=st.agent_b "
        "AND ep2.tick=ep1.tick AND ep2.slot=ep1.slot "
        "AND ep2.place_id=ep1.place_id "
        "WHERE st.weight>0 ORDER BY st.agent_a,st.agent_b LIMIT 32",
        (2,),
    )
    return [str(row["detail"]) for row in rows]


def benchmark(size: int) -> dict:
    config = load_config("runs/civic-rehearsal.yaml")
    config["population"]["target_total"] = int(size)
    config["checkpoint_every"] = 0
    config["speed_delay_s"] = 0.0
    config["resource_guard"] = {"enabled": False}
    with tempfile.TemporaryDirectory(prefix=f"civic-{size}-") as directory:
        store = Store(str(Path(directory) / "run.db"))
        try:
            store.init_run_meta(f"civic-benchmark-{size}", 42, config)
            started = perf_counter()
            world = World(store, config)
            world.initialize()
            initialized = perf_counter()
            asyncio.run(world.run(max_ticks=2))
            completed = perf_counter()
            plan = _query_plan(store)
            if any("SCAN ep" in detail for detail in plan):
                raise RuntimeError(
                    "encounter query regressed to a presence-table scan")
            return {
                "requested_agents": int(size),
                "actual_agents": int(store.scalar(
                    "SELECT COUNT(*) FROM agents")),
                "places": int(store.scalar("SELECT COUNT(*) FROM places")),
                "effective_presence_rows": int(store.scalar(
                    "SELECT COUNT(*) FROM effective_presence")),
                "attention_contexts": int(store.scalar(
                    "SELECT COUNT(*) FROM attention_contexts")),
                "genesis_seconds": round(initialized - started, 6),
                "two_tick_seconds": round(completed - initialized, 6),
                "ledger_reconciled": bool(
                    world.economy.ledger.reconcile()[0]),
                "encounter_algorithm": (
                    "indexed social_ties -> effective_presence self-join"),
                "encounter_query_plan": plan,
            }
        finally:
            store.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sizes", nargs="+", type=int, default=[100, 1000])
    parser.add_argument(
        "--output", default="reports/out/civic_city_benchmark.json")
    args = parser.parse_args()
    results = [benchmark(size) for size in args.sizes]
    payload = {
        "profile": "runs/civic-rehearsal.yaml",
        "ticks": 2,
        "results": results,
    }
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

"""Golden-run fixture (TECH-SPEC §14): a 10-tick scripted world whose event log
is committed to the repo; CI replays it and diffs, so any unintended change to
engine behaviour fails loudly.

Regenerate after an INTENTIONAL behaviour change:
    python -m tests.golden_run
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

GOLDEN_PATH = Path(__file__).parent / "golden" / "golden_events.jsonl"
GOLDEN_TICKS = 10

# Exercises every subsystem: banks, firms, exchange (breaker armed), government,
# health (epidemic mid-run), VC seat, newsroom two-stage, conversations, oracle
# resolver. Everything scripted → free and deterministic.
GOLDEN_CONFIG = {
    "seed": 20260710,
    "population": {"size": 14},
    "banks": {"count": 2},
    "firms": {"count": 3, "listed": 1},
    "exchange": {"circuit_breaker_drop": 0.20},
    "budget": {"cap_usd": 200.0, "oracle_reserve_usd": 10.0, "conversation_pairs": 4,
               "thresholds": [0.60, 0.80, 0.95]},
    "llm": {"default_route": {"provider": "scripted", "model": "scripted"}, "routes": {}},
    "checkpoint_every": 0,
    "outlets": [{"id": 1, "name": "A", "slant": "pro-market-sensational"},
                {"id": 2, "name": "B", "slant": "cautious-pro-labor"}],
    "government": {"tax_rate_bps": 1500, "unemployment_benefit_cents": 60_000,
                   "benefit_interval_ticks": 5, "election_interval_ticks": 8},
    "vc": {"fund_cents": 5_000_000},
    "health": {"hospital": True, "insurer": True, "premium_cents": 3000,
               "coverage_bps": 8000, "premium_interval_ticks": 5},
    "shocks": [
        {"kind": "epidemic", "trigger": "trend", "trigger_params": {"start": 3},
         "duration_ticks": 2, "params": {"multiplier": 300.0}},
        {"kind": "rumor", "trigger": "shock", "trigger_params": {"tick": 6},
         "params": {"bank_id": 1, "n_agents": 8}},
    ],
}


def build_and_run(db_path: str):
    from engine.store import Store
    from world.loop import World
    store = Store(db_path)
    store.init_run_meta("golden", GOLDEN_CONFIG["seed"], GOLDEN_CONFIG)
    world = World(store, GOLDEN_CONFIG)
    world.initialize()

    async def go():
        for _ in range(GOLDEN_TICKS):
            await world.step()
    asyncio.run(go())
    return store, world


def event_dump(store) -> list[str]:
    """Canonical event-log lines: id order, timestamps excluded."""
    rows = store.query("SELECT tick, phase, kind, payload_json FROM events ORDER BY id")
    return [json.dumps({"t": int(r["tick"]), "ph": r["phase"], "k": r["kind"],
                        "p": json.loads(r["payload_json"] or "{}")},
                       sort_keys=True, separators=(",", ":"))
            for r in rows]


def regenerate() -> None:
    import sys
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        store, world = build_and_run(str(Path(td) / "golden.db"))
        ok, diag = world.economy.ledger.reconcile()
        if not ok:
            sys.exit(f"golden run does not reconcile: {diag}")
        lines = event_dump(store)
        store.close()
    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"golden fixture regenerated: {GOLDEN_PATH} ({len(lines)} events)")


if __name__ == "__main__":
    regenerate()

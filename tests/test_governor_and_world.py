"""Governor thresholds (60/80/95/100), world determinism + reconciliation property
test, checkpoint/resume, rumor pilot (PRD R5/R7, §14)."""
import asyncio
import json
import random

import pytest

from engine.store import Store
from llm.gateway import Governor
from world.loop import World


def _cfg(**over):
    cfg = {
        "seed": 42,
        "population": {"size": 24},
        "banks": {"count": 2},
        "firms": {"count": 5, "listed": 2},
        "budget": {"cap_usd": 200.0, "oracle_reserve_usd": 10.0, "conversation_pairs": 15,
                   "thresholds": [0.60, 0.80, 0.95]},
        "llm": {"default_route": {"provider": "scripted", "model": "scripted"}, "routes": {}},
        "checkpoint_every": 0,
        "outlets": [{"id": 1, "name": "A", "slant": "pro-market-sensational"},
                    {"id": 2, "name": "B", "slant": "cautious-pro-labor"}],
    }
    cfg.update(over)
    return cfg


def _fresh_world(tmp_path, name="w.db", **over) -> World:
    s = Store(str(tmp_path / name))
    cfg = _cfg(**over)
    s.init_run_meta(name, cfg["seed"], cfg)
    w = World(s, cfg)
    w.initialize()
    return w


# ── governor thresholds (cost test, §14) ─────────────────────────────────────
def test_governor_stages(tmp_path):
    s = Store(str(tmp_path / "g.db"))
    s.init_run_meta("g", 1, {})
    gov = Governor(s, {"cap_usd": 100.0, "oracle_reserve_usd": 10.0, "conversation_pairs": 15})

    def spend(amount, purpose="decision"):
        s.insert("llm_calls", tick=0, purpose=purpose, cost_usd=amount,
                 in_tokens=0, out_tokens=0, cached=0)

    assert gov.level() == 0 and gov.conversation_pairs() == 15
    spend(0.60 * 90)   # exact 60% of world budget (cap 100 - 10 oracle = 90)
    assert gov.level() == 1 and gov.conversation_pairs() == 8
    spend(0.20 * 90)   # exact 80%
    assert gov.level() == 2 and gov.conversation_pairs() == 4 and gov.cadence_multiplier() == 2
    spend(0.15 * 90)   # exact 95%
    assert gov.level() == 3 and not gov.citizens_enabled()
    spend(0.05 * 90)   # exact 100%
    assert gov.should_pause()
    # Oracle carve-out: oracle can still spend if within its reserve.
    assert gov.can_spend(1.0, "oracle")
    assert not gov.can_spend(20.0, "decision") or gov.total_spend() + 20.0 <= gov.cap_usd


def test_governor_supports_explicit_uncapped_runs(tmp_path):
    store = Store(str(tmp_path / "uncapped.db"))
    store.init_run_meta("uncapped", 1, {})
    governor = Governor(store, {
        "cap_usd": None, "oracle_reserve_usd": 10.0, "conversation_pairs": 15,
    })
    store.insert("llm_calls", tick=0, purpose="decision", cost_usd=10_000.0,
                 in_tokens=0, out_tokens=0, cached=0)

    assert governor.cap_usd is None
    assert governor.level() == 0
    assert governor.conversation_pairs() == 15
    assert governor.cadence_multiplier() == 1
    assert governor.citizens_enabled()
    assert not governor.should_pause()
    assert governor.can_spend(1_000_000.0, "oracle")
    assert governor.status()["fraction"] is None


# ── reconciliation property test over a real run ─────────────────────────────
def test_world_runs_and_reconciles_30_ticks(tmp_path):
    w = _fresh_world(tmp_path)

    async def go():
        for _ in range(30):
            await w.step()
    asyncio.run(go())
    ok, diag = w.economy.ledger.reconcile()
    assert ok, diag
    assert w.store.tick == 30
    # Economy is alive: sales, payroll (tick 30 = payday), news, conversations.
    assert w.store.scalar("SELECT COUNT(*) FROM events WHERE kind='goods_sale'") > 0
    assert w.store.scalar("SELECT COUNT(*) FROM events WHERE kind='wage_paid'") > 0
    assert w.store.scalar("SELECT COUNT(*) FROM news_articles") > 0
    assert w.store.scalar("SELECT COUNT(*) FROM conversations") > 0


# ── determinism: same seed ⇒ identical event log (scripted) ─────────────────
def test_same_seed_same_event_log(tmp_path):
    def event_log(name):
        w = _fresh_world(tmp_path, name)

        async def go():
            for _ in range(12):
                await w.step()
        asyncio.run(go())
        rows = w.store.query("SELECT tick, kind, payload_json FROM events ORDER BY id")
        out = [(r["tick"], r["kind"], r["payload_json"]) for r in rows]
        w.store.close()
        return out

    assert event_log("d1.db") == event_log("d2.db")


# ── rumor pilot (R5 acceptance, scripted scale-down) ─────────────────────────
def test_rumor_propagation_moves_beliefs_and_deposits(tmp_path):
    w = _fresh_world(tmp_path, "rumor.db")
    target_bank = 1

    async def go():
        for _ in range(3):
            await w.step()
        baseline_start = w.store.tick - 2
        pre_deposits = w.economy.bank.deposits(target_bank)
        pre_trust = {int(r["agent_id"]): float(r["value"]) for r in w.store.query(
            "SELECT agent_id, value FROM beliefs WHERE key=?",
            (f"trust:bank:{target_bank}",))}
        baseline_outflow = sum(
            int(json.loads(r["payload_json"])["amount_cents"])
            for r in w.store.query(
                "SELECT payload_json FROM events WHERE kind='deposit_move' "
                "AND tick BETWEEN ? AND ?", (baseline_start, w.store.tick))
            if int(json.loads(r["payload_json"])["from_bank"]) == target_bank)
        w.shocks.schedule("rumor", "shock", {"tick": w.store.tick + 1},
                          params={"bank_id": target_bank, "n_agents": 14})
        rumor_start = w.store.tick + 1
        for _ in range(10):
            await w.step()
        return pre_deposits, pre_trust, baseline_outflow, rumor_start

    pre_deposits, pre_trust, baseline_outflow, rumor_start = asyncio.run(go())
    post_deposits = w.economy.bank.deposits(target_bank)
    rumor_event = w.store.query_one(
        "SELECT payload_json FROM events WHERE kind='rumor' ORDER BY id DESC LIMIT 1")
    exposed = json.loads(rumor_event["payload_json"])["target_agent_ids"]
    dropped = 0
    for agent_id in exposed:
        current = float(w.store.scalar(
            "SELECT value FROM beliefs WHERE agent_id=? AND key=?",
            (agent_id, f"trust:bank:{target_bank}")))
        if pre_trust[agent_id] - current >= 0.2:
            dropped += 1

    conversations = int(w.store.scalar(
        "SELECT COUNT(*) FROM conversations WHERE tick BETWEEN ? AND ?",
        (rumor_start, rumor_start + 9), default=0))
    post_outflow = sum(
        int(json.loads(r["payload_json"])["amount_cents"])
        for r in w.store.query(
            "SELECT payload_json FROM events WHERE kind='deposit_move' "
            "AND tick BETWEEN ? AND ?", (rumor_start, rumor_start + 9))
        if int(json.loads(r["payload_json"])["from_bank"]) == target_bank)

    assert conversations >= 5
    assert dropped / len(exposed) >= 0.25
    assert post_outflow > 2 * (baseline_outflow / 3.0 * 10.0)
    assert post_deposits < pre_deposits
    ok, diag = w.economy.ledger.reconcile()
    assert ok, diag


# ── checkpoint / resume ──────────────────────────────────────────────────────
def test_checkpoint_and_resume(tmp_path):
    w = _fresh_world(tmp_path, "ck.db", checkpoint_every=5,
                     checkpoint_dir=str(tmp_path / "ckpts"))

    async def go(world, n):
        for _ in range(n):
            await world.step()
    asyncio.run(go(w, 6))
    assert w.store.query("SELECT * FROM checkpoints")
    tick_before = w.store.tick
    w._save_prng_state()
    w.store.commit()
    path = w.store.path
    w.store.close()

    s2 = Store(path)
    import json as _json
    cfg = _json.loads(s2.get_meta()["config_json"])
    w2 = World(s2, cfg)
    w2.restore_prng_state()
    asyncio.run(go(w2, 4))
    assert w2.store.tick == tick_before + 4
    ok, _ = w2.economy.ledger.reconcile()
    assert ok


# ── oracle ask/resolve offline ───────────────────────────────────────────────
def test_oracle_prediction_and_resolution(tmp_path):
    w = _fresh_world(tmp_path, "oracle.db")

    async def go():
        for _ in range(2):
            await w.step()
        asked_tick = w.store.tick
        ans = await w.oracle.ask("What is the probability of a bank run within 30 ticks?")
        assert "p" in ans and 0 <= ans["p"] <= 1
        assert ans["deadline_tick"] == asked_tick + 30
        for _ in range(31):
            await w.step()
        return ans
    ans = asyncio.run(go())
    pred = w.store.query_one("SELECT * FROM predictions WHERE id=?", (ans["prediction_id"],))
    assert pred["status"] == "resolved"
    assert pred["brier"] is not None
    # Unanswerable question refuses rather than fabricates.
    ans2 = asyncio.run(w.oracle.ask("Is the moon made of cheese?"))
    assert ans2.get("insufficient_data")

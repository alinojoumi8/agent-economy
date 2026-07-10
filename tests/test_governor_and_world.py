"""Governor thresholds (60/80/95/100), world determinism + reconciliation property
test, checkpoint/resume, rumor pilot (PRD R5/R7, §14)."""
import asyncio
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
    spend(0.61 * 90)   # 60% of world budget (cap 100 - 10 oracle = 90)
    assert gov.level() == 1 and gov.conversation_pairs() == 8
    spend((0.81 - 0.61) * 90)
    assert gov.level() == 2 and gov.conversation_pairs() == 4 and gov.cadence_multiplier() == 2
    spend((0.96 - 0.81) * 90)
    assert gov.level() == 3 and not gov.citizens_enabled()
    spend((1.01 - 0.96) * 90)
    assert gov.should_pause()
    # Oracle carve-out: oracle can still spend if within its reserve.
    assert gov.can_spend(1.0, "oracle")
    assert not gov.can_spend(20.0, "decision") or gov.total_spend() + 20.0 <= gov.cap_usd


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
        pre_deposits = w.economy.bank.deposits(target_bank)
        pre_trust = w.store.scalar(
            "SELECT AVG(value) FROM beliefs WHERE key=?", (f"trust:bank:{target_bank}",))
        w.shocks.schedule("rumor", "shock", {"tick": w.store.tick + 1},
                          params={"bank_id": target_bank, "n_agents": 14})
        for _ in range(10):
            await w.step()
        return pre_deposits, float(pre_trust)

    pre_deposits, pre_trust = asyncio.run(go())
    post_trust = float(w.store.scalar(
        "SELECT AVG(value) FROM beliefs WHERE key=?", (f"trust:bank:{target_bank}",)))
    post_deposits = w.economy.bank.deposits(target_bank)

    # Belief moved down and deposits flowed out (or the bank failed outright).
    bank_status = w.store.query_one("SELECT status FROM banks WHERE id=?", (target_bank,))["status"]
    assert post_trust < pre_trust
    assert post_deposits < pre_deposits or bank_status == "failed"
    # The rumor reached conversations.
    rumor_msgs = w.store.scalar(
        "SELECT COUNT(*) FROM messages WHERE text LIKE '%pulling money%' OR text LIKE '%worried%'")
    assert rumor_msgs > 0
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
        ans = await w.oracle.ask("What is the probability of a bank run within 5 ticks?")
        assert "p" in ans and 0 <= ans["p"] <= 1
        assert ans["deadline_tick"] > w.store.tick
        for _ in range(8):
            await w.step()
        return ans
    ans = asyncio.run(go())
    pred = w.store.query_one("SELECT * FROM predictions WHERE id=?", (ans["prediction_id"],))
    assert pred["status"] == "resolved"
    assert pred["brier"] is not None
    # Unanswerable question refuses rather than fabricates.
    ans2 = asyncio.run(w.oracle.ask("Is the moon made of cheese?"))
    assert ans2.get("insufficient_data")

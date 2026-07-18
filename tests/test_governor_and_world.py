"""Governor thresholds (60/80/95/100), world determinism + reconciliation property
test, checkpoint/resume, rumor pilot (PRD R5/R7, §14)."""
import asyncio
import json
import random

import pytest

from engine.store import Store
from llm.gateway import GatewayInterrupted, Governor, LLMRequest
from oracle.rules import ResolutionRuleError, validate_resolution_rule
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


def test_provider_request_is_cancelled_when_operator_interrupts(tmp_path):
    world = _fresh_world(tmp_path, "interrupt.db")

    async def scenario():
        started = asyncio.Event()
        cancelled = asyncio.Event()

        class SlowAdapter:
            async def complete(self, *args, **kwargs):
                started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    raise

        world.gateway.adapters["scripted"] = SlowAdapter()
        request = LLMRequest(
            role="citizen", purpose="decision", system="system", user="user",
            agent_id=1, tick=1)
        task = asyncio.create_task(world.gateway.complete(request))
        await asyncio.wait_for(started.wait(), timeout=0.5)
        world.gateway.interrupt_pending()
        with pytest.raises(GatewayInterrupted):
            await asyncio.wait_for(task, timeout=0.5)
        assert cancelled.is_set()

    asyncio.run(scenario())


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


def test_oracle_planner_reserve_is_persisted_and_replay_versioned(tmp_path):
    store = Store(str(tmp_path / "oracle-budget.db"))
    store.init_run_meta("oracle-budget", 1, {})
    budget = {
        "cap_usd": 0.2, "oracle_reserve_usd": 0.1,
        "oracle_plan_in_reserve": True,
    }
    governor = Governor(store, budget)
    call_id = store.insert(
        "llm_calls", tick=0, role="oracle", purpose="oracle_plan",
        cost_usd=0.04, in_tokens=0, out_tokens=0, cached=0)
    governor.record_cost(call_id, 0.04, "oracle_plan")

    assert governor.total_spend() == pytest.approx(0.04)
    assert governor.oracle_spend() == pytest.approx(0.04)
    assert governor.world_spend() == pytest.approx(0.0)
    assert governor.can_spend(0.06, "oracle_plan")
    assert not governor.can_spend(0.061, "oracle_plan")

    restored = Governor(store, budget)
    assert restored.oracle_spend() == pytest.approx(0.04)
    assert restored.world_spend() == pytest.approx(0.0)

    # Markerless stored configs preserve the historical planner accounting.
    legacy = Governor(store, {"cap_usd": 0.2, "oracle_reserve_usd": 0.1})
    assert legacy.oracle_spend() == pytest.approx(0.0)
    assert legacy.world_spend() == pytest.approx(0.04)
    store.close()


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


def test_semantics7_baseline_citizens_are_active_core_without_r19(tmp_path):
    maintained = _fresh_world(
        tmp_path, "sem7-baseline.db", engine_semantics_version=7,
        population={"size": 12, "baseline_citizens_core": True})
    citizens = maintained.store.query(
        "SELECT id,population_tier,pinned_core FROM agents "
        "WHERE role IS NULL ORDER BY id")

    assert citizens
    assert {row["population_tier"] for row in citizens} == {"core"}
    assert {int(row["pinned_core"]) for row in citizens} == {1}
    scheduled_ids = {
        int(agent["id"])
        for tick in range(1, 31)
        for agent in maintained.runtime.scheduler.scheduled_agents(tick)
        if agent["role"] is None
    }
    assert scheduled_ids == {int(row["id"]) for row in citizens}

    # Markerless stored semantics 7 and every semantics 1-6 run retain the
    # historical implicit peripheral tier.
    unmarked = _fresh_world(
        tmp_path, "sem7-unmarked.db", engine_semantics_version=7,
        population={"size": 12})
    assert unmarked.store.scalar(
        "SELECT COUNT(*) FROM agents WHERE role IS NULL "
        "AND population_tier='core'", default=0) == 0

    legacy = _fresh_world(
        tmp_path, "sem6-baseline.db", engine_semantics_version=6,
        population={"size": 12, "baseline_citizens_core": True})
    assert legacy.store.scalar(
        "SELECT COUNT(*) FROM agents WHERE role IS NULL "
        "AND population_tier='core'", default=0) == 0
    assert legacy.store.scalar(
        "SELECT COUNT(*) FROM agents WHERE role IS NULL "
        "AND population_tier='periphery'", default=0) > 0


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
    w.gateway.scripted.register("oracle", lambda _context: {
        "p": 1.5, "reasoning": "invalid probability",
        "deadline_tick": w.store.tick,
        "resolution_rule": {},
    })
    invalid = asyncio.run(w.oracle.ask("Will this invalid forecast be stored?"))
    assert invalid.get("insufficient_data")
    stored = w.store.query_one(
        "SELECT p, status FROM predictions WHERE id=?", (invalid["prediction_id"],))
    assert stored["p"] is None and stored["status"] == "insufficient_data"


@pytest.mark.parametrize("rule", [
    {"type": "invented_rule"},
    {"type": "bank_run", "window": 1.5, "deposit_drop": 0.3},
    {"type": "bank_run", "window": 5, "deposit_drop": float("nan")},
    {"type": "metric_above", "metric": "missing metric", "threshold": 1},
    {"type": "bank_failure", "unexpected": True},
])
def test_resolution_rule_contract_rejects_unknown_or_unbounded_rules(rule):
    with pytest.raises(ResolutionRuleError):
        validate_resolution_rule(rule, metric_exists=lambda _name: False)


def test_strict_unknown_resolution_rule_fails_closed_without_false_score(tmp_path):
    world = _fresh_world(
        tmp_path, "strict-oracle.db",
        oracle={"default_horizon_ticks": 30, "max_horizon_ticks": 365,
                "strict_resolution_rules": True})
    world.gateway.scripted.register("oracle", lambda context: {
        "p": 0.8,
        "drivers": ["bounded evidence"],
        "confidence": "med",
        "resolution_rule": {"type": "invented_rule"},
        "deadline_tick": int(context["tick"]) + 30,
        "reasoning": "unsupported contract",
    })
    rejected = asyncio.run(world.oracle.ask("Will an invented event happen?"))
    assert rejected["insufficient_data"] is True
    assert world.store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='oracle_rule_rejected'") == 1

    strict_id = world.store.insert(
        "predictions", asked_tick=0, question="strict stored rule", p=0.8,
        resolution_rule_json=json.dumps({"type": "invented_rule"}),
        deadline_tick=1, status="open")
    assert world.oracle.resolve_open(1) == []
    strict = world.store.query_one(
        "SELECT status,outcome,brier FROM predictions WHERE id=?", (strict_id,))
    assert strict["status"] == "insufficient_data"
    assert strict["outcome"] is None and strict["brier"] is None
    assert world.store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='oracle_resolution_invalid'") == 1

    # Markerless/stored historical configs retain the old resolver behavior.
    world.oracle.strict_resolution_rules = False
    legacy_id = world.store.insert(
        "predictions", asked_tick=0, question="legacy stored rule", p=0.8,
        resolution_rule_json=json.dumps({"type": "invented_rule"}),
        deadline_tick=1, status="open")
    resolved = world.oracle.resolve_open(1)
    assert resolved == [{"id": legacy_id, "outcome": 0, "brier": pytest.approx(0.64)}]
    legacy = world.store.query_one(
        "SELECT status,outcome,brier FROM predictions WHERE id=?", (legacy_id,))
    assert legacy["status"] == "resolved"
    assert legacy["outcome"] == 0 and legacy["brier"] == pytest.approx(0.64)

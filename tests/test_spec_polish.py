"""Spec-fidelity items finished after P1: exchange circuit breaker (§9),
two-stage newsroom (§10), fork-from-checkpoint (§13)."""
import asyncio
import json

from agents.policies import newsroom_policy, reporter_draft
from engine.store import Store
from world.loop import World
from run import fork_run
from tests.conftest import make_bank, make_agent


# ── circuit breaker (§9) ─────────────────────────────────────────────────────
def test_circuit_breaker_halts_symbol_intraday(economy):
    economy.exchange.circuit_breaker_drop = 0.20
    bank = make_bank(economy)
    seller, _ = make_agent(economy, bank, "Seller", 0)
    buyer, _ = make_agent(economy, bank, "Buyer", 1_000_000)
    founder, _ = make_agent(economy, bank, "Founder", 10_000)
    firm_id = economy.firms.found_firm(0, founder, "CrashCo", "tech")
    economy.exchange._adjust_shares(firm_id, "agent", seller, 100)
    economy.store.update("firms", firm_id, status="listed")
    economy.store.record_metric(0, f"stock:{firm_id}", 1000)   # previous close $10

    # A large resting sell at 750 (−25% vs close → breaker) faced by two buys:
    # the first fill trips the halt, leaving a still-crossing pair on the book.
    economy.exchange.place_order(1, seller, firm_id, "sell", 20, 750)
    economy.exchange.place_order(1, buyer, firm_id, "buy", 10, 750)
    economy.exchange.place_order(1, buyer, firm_id, "buy", 10, 760)

    fills = economy.exchange.match_firm(1, firm_id)

    assert len(fills) == 1 and fills[0].price_cents == 750
    assert economy.store.query_one(
        "SELECT 1 FROM events WHERE kind='circuit_breaker' "
        "AND json_extract(payload_json,'$.firm_id')=?", (firm_id,))
    open_orders = economy.store.scalar(
        "SELECT COUNT(*) FROM orders WHERE firm_id=? AND status IN ('open','partial')",
        (firm_id,), default=0)
    assert open_orders == 2   # a crossing pair rests unmatched: the symbol is halted
    ok, diag = economy.ledger.reconcile()
    assert ok, diag

    # Without the breaker the same leftover book trades immediately.
    economy.exchange.circuit_breaker_drop = None
    fills2 = economy.exchange.match_firm(1, firm_id)
    assert len(fills2) == 1 and fills2[0].price_cents == 750


# ── two-stage newsroom (§10) ─────────────────────────────────────────────────
def _world(tmp_path, name="w.db", **over):
    cfg = {
        "seed": 42, "population": {"size": 14}, "banks": {"count": 2},
        "firms": {"count": 3, "listed": 1},
        "budget": {"cap_usd": 200.0, "oracle_reserve_usd": 10.0, "conversation_pairs": 4,
                   "thresholds": [0.60, 0.80, 0.95]},
        "llm": {"default_route": {"provider": "scripted", "model": "scripted"}, "routes": {}},
        "checkpoint_every": 0,
        "outlets": [{"id": 1, "name": "A", "slant": "pro-market-sensational"},
                    {"id": 2, "name": "B", "slant": "cautious-pro-labor"}],
    }
    cfg.update(over)
    s = Store(str(tmp_path / name))
    s.init_run_meta(name, cfg["seed"], cfg)
    w = World(s, cfg)
    w.initialize()
    return w


def test_newsroom_runs_reporter_then_editor(tmp_path):
    # A rumor at t1 guarantees a salient event, so both desks fire immediately.
    w = _world(tmp_path, "news.db",
               shocks=[{"kind": "rumor", "trigger": "shock", "trigger_params": {"tick": 1},
                        "params": {"bank_id": 1, "n_agents": 6}}])

    async def go():
        for _ in range(3):
            await w.step()
    asyncio.run(go())

    reporter_calls = w.store.scalar(
        "SELECT COUNT(*) FROM llm_calls WHERE purpose='reporter'", default=0)
    editor_calls = w.store.scalar(
        "SELECT COUNT(*) FROM llm_calls WHERE purpose='newsroom'", default=0)
    assert reporter_calls > 0 and editor_calls > 0
    # Desk calls are attributed to the outlet's staff agents (inspector-visible).
    assert w.store.scalar(
        "SELECT COUNT(*) FROM llm_calls c JOIN agents a ON a.id=c.agent_id "
        "WHERE c.purpose='reporter' AND a.role='reporter'", default=0) == reporter_calls
    # Both outlets still publish, with distinct slant voices.
    heads = [r["headline"] for r in w.store.query(
        "SELECT headline FROM news_articles ORDER BY id")]
    assert heads
    assert any("INVESTORS ON EDGE" in h for h in heads)
    assert any("workers weigh the fallout" in h for h in heads)


def test_scripted_sensational_desk_prioritizes_a_firm_scandal():
    events = [
        {"id": 10, "kind": "firm_scandal"},
        {"id": 11, "kind": "bankruptcy"},
    ]
    drafts = reporter_draft({
        "engine_semantics_version": 7,
        "salient_events": events,
    })["stories"]
    article = newsroom_policy({
        "engine_semantics_version": 7,
        "outlet": {"slant": "pro-market-sensational"},
        "drafts": drafts,
        "salient_events": events,
    })

    assert article["source_event_ids"] == [10]
    assert "ACCOUNTING INVESTIGATION" in article["headline"]


def test_scripted_newsroom_preserves_pre_semantics7_scandal_behavior():
    events = [
        {"id": 10, "kind": "firm_scandal"},
        {"id": 11, "kind": "bankruptcy"},
    ]
    for semantics in (None, 1, 2, 3, 4, 5, 6):
        context = {"salient_events": events}
        if semantics is not None:
            context["engine_semantics_version"] = semantics
        drafts = reporter_draft(context)["stories"]

        scandal = drafts[0]
        assert scandal == {
            "headline": "Markets in Motion",
            "body": "Activity picked up across the economy.",
            "tone": 0.1,
            "kind": "firm_scandal",
            "source_event_ids": [10],
        }
        article = newsroom_policy({
            **context,
            "outlet": {"slant": "pro-market-sensational"},
            "drafts": drafts,
        })
        assert article["source_event_ids"] == [11]


def test_newsroom_request_context_marks_only_semantics7(tmp_path):
    events = [{"id": 10, "kind": "firm_scandal"}]

    async def run_desk(semantics: int):
        world = _world(
            tmp_path, f"news-semantics-{semantics}.db",
            engine_semantics_version=semantics,
        )
        outlet = world.newsroom.outlets[0]
        drafts = await world.newsroom._report_stories(1, outlet, events)
        article = await world.newsroom._write_story(
            1, outlet, events, None, drafts=[])
        contexts = [
            json.loads(row["request_json"])["context"]
            for row in world.store.query(
                "SELECT request_json FROM llm_calls ORDER BY id")
        ]
        world.store.close()
        return drafts, article, contexts

    legacy_drafts, legacy_article, legacy_contexts = asyncio.run(run_desk(6))
    current_drafts, current_article, current_contexts = asyncio.run(run_desk(7))

    assert legacy_drafts[0]["headline"] == "Markets in Motion"
    assert legacy_article["headline"].startswith("MARKETS IN MOTION")
    assert all("engine_semantics_version" not in item for item in legacy_contexts)
    assert current_drafts[0]["headline"] == "Firm Faces Accounting Investigation"
    assert current_article["headline"].startswith(
        "FIRM FACES ACCOUNTING INVESTIGATION")
    assert all(item["engine_semantics_version"] == 7 for item in current_contexts)


# ── fork from checkpoint (§13) ───────────────────────────────────────────────
def test_fork_creates_branch_and_parent_stays_intact(tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    ckpt_dir = tmp_path / "ckpts"
    cfg_over = {"checkpoint_every": 3, "checkpoint_dir": str(ckpt_dir)}
    s = Store(str(runs_dir / "parent01.db"))
    cfg = {
        "seed": 7, "population": {"size": 14}, "banks": {"count": 2},
        "firms": {"count": 3, "listed": 1},
        "budget": {"cap_usd": 200.0, "oracle_reserve_usd": 10.0, "conversation_pairs": 4,
                   "thresholds": [0.60, 0.80, 0.95]},
        "llm": {"default_route": {"provider": "scripted", "model": "scripted"}, "routes": {}},
        "outlets": [{"id": 1, "name": "A", "slant": "pro-market-sensational"},
                    {"id": 2, "name": "B", "slant": "cautious-pro-labor"}],
        **cfg_over,
    }
    s.init_run_meta("parent01", cfg["seed"], cfg)
    w = World(s, cfg)
    w.initialize()

    async def go(world, n):
        for _ in range(n):
            await world.step()
    asyncio.run(go(w, 6))
    w._save_prng_state()
    w.store.commit()
    parent_tick = w.store.tick

    new_id = fork_run("parent01@6", data_dir=runs_dir)

    fork_db = runs_dir / f"{new_id}.db"
    assert fork_db.exists()
    fs = Store(str(fork_db))
    meta = fs.get_meta()
    assert meta["run_id"] == new_id
    assert meta["parent_run_id"] == "parent01"
    assert int(meta["fork_tick"]) == 6
    assert fs.query_one("SELECT 1 FROM events WHERE kind='fork'")

    # The fork resumes and diverges forward; the parent is untouched.
    import json as _json
    w2 = World(fs, _json.loads(meta["config_json"]))
    w2.restore_prng_state()
    asyncio.run(go(w2, 2))
    assert fs.tick == 8
    ok, diag = w2.economy.ledger.reconcile()
    assert ok, diag
    assert w.store.tick == parent_tick == 6
    fs.close()
    w.store.close()

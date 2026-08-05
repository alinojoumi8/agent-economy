"""Regression tests for workforce-recovery correctness bugs found in review."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

import run as cli
from agents.policies import workforce_recovery_actions
from agents.runtime import AgentRuntime
from engine.core import Economy
from engine.store import Store
from world.loop import World

from tests.conftest import make_agent, make_bank


def _config(tmp_path: Path, **over) -> dict:
    cfg = {
        "seed": 42,
        "population": {"size": 12},
        "banks": {"count": 1},
        "firms": {"count": 2, "listed": 0, "target_headcount": 3},
        "behavior": {"act_every": 1, "run_threshold": 0.35},
        "budget": {
            "cap_usd": 200.0,
            "oracle_reserve_usd": 10.0,
            "conversation_pairs": 0,
            "thresholds": [0.60, 0.80, 0.95],
        },
        "llm": {
            "provider_retries": 0,
            "default_route": {"provider": "scripted", "model": "scripted"},
            "routes": {},
        },
        "checkpoint_every": 0,
        "checkpoint_dir": str(tmp_path / "checkpoints"),
        "report_dir": str(tmp_path / "reports"),
        "outlets": [
            {"id": 1, "name": "A", "slant": "pro-market-sensational"},
            {"id": 2, "name": "B", "slant": "cautious-pro-labor"},
        ],
        "engine_semantics_version": 7,
    }
    cfg.update(over)
    return cfg


def _world(tmp_path: Path, name: str, **over) -> World:
    cfg = _config(tmp_path, **over)
    store = Store(str(tmp_path / name))
    store.init_run_meta(name, int(cfg["seed"]), cfg)
    world = World(store, cfg)
    world.initialize()
    return world


def test_cli_supply_recovery_defaults_to_recovery_headcount_not_genesis(
        monkeypatch):
    """Genesis target_headcount must not silently become the recovery target."""
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(cli, "configure_logging", lambda: None)
    monkeypatch.setattr(cli, "operational_log", lambda *_a, **_k: None)
    monkeypatch.setattr(sys, "argv", [
        "run.py",
        "--config", "ignored.yaml",
        "--resume", "saved-run",
        "--activate-supply-recovery",
    ])
    monkeypatch.setattr(
        cli, "load_config",
        lambda _path: {"firms": {"target_headcount": 3}},
    )

    class FakeWorld:
        config = {
            "engine_semantics_version": 7,
            "firms": {"target_headcount": 3},
        }

        @staticmethod
        def close():
            pass

    monkeypatch.setattr(
        cli, "open_run",
        lambda *_a, **_k: (object(), FakeWorld(), "saved-run"),
    )

    seen: dict[str, int] = {}

    def activate(_world, *, target_headcount):
        seen["target_headcount"] = int(target_headcount)
        raise RuntimeError("recovery target checked")

    monkeypatch.setattr(cli, "activate_supply_recovery_for_run", activate)

    with pytest.raises(RuntimeError, match="recovery target checked"):
        cli.main()
    assert seen["target_headcount"] == 80


def test_cli_supply_recovery_prefers_persisted_recovery_target(monkeypatch):
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(cli, "configure_logging", lambda: None)
    monkeypatch.setattr(cli, "operational_log", lambda *_a, **_k: None)
    monkeypatch.setattr(sys, "argv", [
        "run.py",
        "--config", "ignored.yaml",
        "--resume", "saved-run",
        "--activate-supply-recovery",
    ])
    monkeypatch.setattr(
        cli, "load_config",
        lambda _path: {"firms": {"target_headcount": 3}},
    )

    class FakeWorld:
        config = {
            "engine_semantics_version": 7,
            "firms": {
                "target_headcount": 3,
                "workforce_recovery_target_headcount": 42,
            },
        }

        @staticmethod
        def close():
            pass

    monkeypatch.setattr(
        cli, "open_run",
        lambda *_a, **_k: (object(), FakeWorld(), "saved-run"),
    )

    seen: dict[str, int] = {}

    def activate(_world, *, target_headcount):
        seen["target_headcount"] = int(target_headcount)
        raise RuntimeError("persisted recovery target checked")

    monkeypatch.setattr(cli, "activate_supply_recovery_for_run", activate)

    with pytest.raises(RuntimeError, match="persisted recovery target checked"):
        cli.main()
    assert seen["target_headcount"] == 42


def test_cli_supply_recovery_flag_override(monkeypatch):
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(cli, "configure_logging", lambda: None)
    monkeypatch.setattr(cli, "operational_log", lambda *_a, **_k: None)
    monkeypatch.setattr(sys, "argv", [
        "run.py",
        "--config", "ignored.yaml",
        "--resume", "saved-run",
        "--activate-supply-recovery",
        "--supply-recovery-target-headcount", "55",
    ])
    monkeypatch.setattr(
        cli, "load_config",
        lambda _path: {"firms": {"target_headcount": 3}},
    )

    class FakeWorld:
        config = {
            "engine_semantics_version": 7,
            "firms": {"target_headcount": 3},
        }

        @staticmethod
        def close():
            pass

    monkeypatch.setattr(
        cli, "open_run",
        lambda *_a, **_k: (object(), FakeWorld(), "saved-run"),
    )

    seen: dict[str, int] = {}

    def activate(_world, *, target_headcount):
        seen["target_headcount"] = int(target_headcount)
        raise RuntimeError("override checked")

    monkeypatch.setattr(cli, "activate_supply_recovery_for_run", activate)

    with pytest.raises(RuntimeError, match="override checked"):
        cli.main()
    assert seen["target_headcount"] == 55


def test_workforce_recovery_skips_employed_counter_offers():
    context = {
        "workforce_recovery_enabled": True,
        "workforce_recovery_operational_enabled": True,
        "workforce_recovery_batch_size": 4,
        "my_firm": {
            "firm_id": 1,
            "employees": 0,
            "target_headcount": 2,
            "cash": 10_000_000,
            "payroll": 0,
            "price": 500,
            "open_jobs": 0,
        },
        "firm_job_offers": [{
            "offer_id": 11,
            "requested_wage": 250_000,
            "candidate_agent_id": 99,
            "candidate_employed": True,
        }],
        "firm_applications": [],
    }

    actions = workforce_recovery_actions(context)

    assert all(action.get("type") != "accept_job_offer" for action in actions)


def test_invalid_recovery_hiring_inputs_keep_their_fail_closed_reason(
        tmp_path, monkeypatch):
    world = _world(tmp_path, "invalid-recovery-inputs.db")
    firm = world.store.query_one("SELECT * FROM firms ORDER BY id LIMIT 1")
    founder_id = int(firm["founder_agent_id"])
    firm_id = int(firm["id"])
    monkeypatch.setattr(
        world.runtime.ctx,
        "_firm_view",
        lambda _firm, _tick: {
            "recovery": {"active": True, "settings": {}, "inputs": {}},
        },
    )

    reason = world.runtime._pre_recovery_employment_action(
        1,
        founder_id,
        {"type": "post_job", "firm_id": firm_id, "title": "worker", "wage": 100},
        "EXECUTION",
    )

    assert reason == "recovery policy rejects action: recovery pricing inputs are invalid"
    world.close()


def test_recovery_post_hook_ignores_success_without_an_employment_id(tmp_path):
    world = _world(tmp_path, "missing-employment-id.db")

    world.runtime._post_recovery_employment_action(
        1, 1, {"type": "hire"}, "EXECUTION",
        {"ok": True, "employment_id": None},
    )

    assert world.runtime._recovery_completed_hires == {}
    world.close()


def test_joint_firm_and_candidate_accepts_respect_remaining_headcount(
        tmp_path):
    """Firm counter-accept + candidate auto-accept must share one capacity budget."""
    world = _world(
        tmp_path,
        "joint-capacity.db",
        firms={
            "count": 1,
            "listed": 0,
            "target_headcount": 3,
            "workforce_recovery_activation_tick": 1,
            "workforce_recovery_target_headcount": 2,
            "workforce_recovery_operational_activation_tick": 1,
            "workforce_recovery_batch_size": 4,
            "workforce_recovery_excluded_sectors": ["health", "insurance"],
        },
        health={"hospital": False, "insurer": False},
    )
    firm = world.store.query_one(
        "SELECT * FROM firms ORDER BY id LIMIT 1")
    firm_id = int(firm["id"])
    founder_id = int(firm["founder_agent_id"])
    # Leave the firm with one active employee so recovery target 2 has gap 1.
    existing = world.store.query(
        "SELECT id, agent_id FROM employments WHERE firm_id=? AND status='active' "
        "ORDER BY id",
        (firm_id,),
    )
    for row in existing[1:]:
        world.store.update("employments", int(row["id"]), status="ended")
        world.store.execute(
            "UPDATE agents SET employer_id=NULL WHERE id=?",
            (int(row["agent_id"]),),
        )
    employees = int(world.store.scalar(
        "SELECT COUNT(*) FROM employments WHERE firm_id=? AND status='active'",
        (firm_id,), default=0))
    assert employees == 1

    currency = str(firm["currency_code"] or "USD")
    candidates = world.store.query(
        "SELECT a.id FROM agents a "
        "JOIN accounts ac ON ac.id=a.checking_account_id "
        "WHERE a.kind='citizen' AND a.alive=1 AND a.retired=0 "
        "AND a.employer_id IS NULL AND a.id<>? "
        "AND ac.currency_code=? ORDER BY a.id LIMIT 2",
        (founder_id, currency),
    )
    assert len(candidates) == 2
    counter_candidate = int(candidates[0]["id"])
    fair_candidate = int(candidates[1]["id"])

    # Counter-offer path: candidate proposed, firm would accept.
    job_a = world.economy.labor.post_job(1, firm_id, "worker", 250_000)
    app_a = world.economy.labor.apply_job(1, counter_candidate, job_a)
    counter_offer = world.economy.labor.make_offer(
        1, int(app_a), counter_candidate, 260_000)

    # Fair firm-made offer path: candidate would auto-accept.
    job_b = world.economy.labor.post_job(1, firm_id, "worker", 250_000)
    app_b = world.economy.labor.apply_job(1, fair_candidate, job_b)
    firm_offer = world.economy.labor.make_offer(
        1, int(app_b), founder_id, 250_000)

    world.runtime.scheduler.scheduled_agents = lambda *args, **kwargs: []
    decisions = asyncio.run(world.runtime.decide_all(2))
    world.runtime.execute_decisions(2, decisions)

    accepts = []
    for decision in decisions:
        for action in (decision.get("envelope") or {}).get("actions", []):
            if isinstance(action, dict) and action.get("type") == "accept_job_offer":
                accepts.append(int(action["offer_id"]))

    # Gap was 1: only one of the two pending hires may complete.
    final_employees = int(world.store.scalar(
        "SELECT COUNT(*) FROM employments WHERE firm_id=? AND status='active'",
        (firm_id,), default=0))
    assert final_employees == 2
    assert len(accepts) == 1
    assert set(accepts).issubset({int(counter_offer), int(firm_offer)})
    world.store.close()


def test_multi_firm_founder_recovery_binds_each_firm(store):
    """Each firm owned by the same founder gets its own recovery context."""
    import random
    from llm.gateway import Gateway

    config = {
        "seed": 7,
        "engine_semantics_version": 7,
        "firms": {
            "target_headcount": 3,
            "workforce_recovery_activation_tick": 1,
            "workforce_recovery_target_headcount": 5,
            "workforce_recovery_operational_activation_tick": 1,
            "workforce_recovery_batch_size": 2,
            "workforce_recovery_excluded_sectors": [],
        },
        "behavior": {"act_every": 1},
        "llm": {
            "default_route": {"provider": "scripted", "model": "scripted"},
            "routes": {},
        },
        "budget": {"cap_usd": 50.0, "oracle_reserve_usd": 1.0,
                   "conversation_pairs": 0, "thresholds": [0.9]},
    }
    economy = Economy(store, config, random.Random(1), random.Random(2))
    economy.ensure_system_accounts()
    bank_id = make_bank(economy)
    founder, _ = make_agent(economy, bank_id, name="Dual Founder", cash=5_000_000)
    firm_a = economy.firms.found_firm(
        0, founder, "Alpha Co", "services",
        opening_capital_cents=2_000_000, shares=1_000)
    firm_b = economy.firms.found_firm(
        0, founder, "Beta Co", "tech",
        opening_capital_cents=2_000_000, shares=1_000)
    store.update("firms", firm_a, status="private")
    store.update("firms", firm_b, status="private")

    gateway = Gateway(store, config)
    runtime = AgentRuntime(economy, gateway, config)
    runtime.scheduler.scheduled_agents = lambda *args, **kwargs: []
    runtime.participant.decision_for_tick = lambda tick: None

    decisions = asyncio.run(runtime.decide_all(1))
    recovery = [
        d for d in decisions if d.get("purpose") == "workforce_recovery"
    ]
    firm_ids = set()
    for decision in recovery:
        for action in decision["envelope"]["actions"]:
            if action.get("type") == "post_job":
                firm_ids.add(int(action["firm_id"]))

    assert firm_ids == {int(firm_a), int(firm_b)}

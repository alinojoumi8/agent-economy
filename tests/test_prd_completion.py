"""Executable acceptance evidence for the remaining PRD-v1 completion gates."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import run as run_module
from agents.memory import Memory
from engine.ledger import ReconciliationError
from engine.store import Store, load_json
from llm.adapters import AdapterResult, OpenAICompatAdapter
from llm.gateway import Gateway, LLMRequest
from llm.readiness import validate_llm_config
from run import load_config, open_run, replay_headless
from server.app import create_app
from server.controller import RunController
from world.loop import LEGACY_PHASES, PHASES, World
from world.recovery import assess_recovery, recovery_settings
from world.replay_verify import verify_replay
from oracle.tools import OracleToolError


def _config(tmp_path: Path, **over) -> dict:
    cfg = {
        "seed": 42,
        "population": {"size": 10},
        "banks": {"count": 2},
        "firms": {"count": 3, "listed": 1},
        "behavior": {"act_every": 1, "run_threshold": 0.35},
        "budget": {"cap_usd": 200.0, "oracle_reserve_usd": 10.0,
                   "conversation_pairs": 0, "thresholds": [0.60, 0.80, 0.95]},
        "llm": {"provider_retries": 0,
                "default_route": {"provider": "scripted", "model": "scripted"},
                "routes": {}},
        "checkpoint_every": 0,
        "checkpoint_dir": str(tmp_path / "checkpoints"),
        "report_dir": str(tmp_path / "reports"),
        "outlets": [{"id": 1, "name": "A", "slant": "pro-market-sensational"},
                    {"id": 2, "name": "B", "slant": "cautious-pro-labor"}],
    }
    cfg.update(over)
    return cfg


def _world(tmp_path: Path, name: str = "acceptance.db", **over) -> World:
    cfg = _config(tmp_path, **over)
    store = Store(str(tmp_path / name))
    store.init_run_meta(name, int(cfg["seed"]), cfg)
    world = World(store, cfg)
    world.initialize()
    return world


def test_finalize_metrics_include_same_day_sales_and_are_idempotent(tmp_path):
    world = _world(tmp_path, "finalize-metrics.db")
    buyer_id = int(world.store.scalar(
        "SELECT ag.id FROM agents ag JOIN accounts a ON a.id=ag.checking_account_id "
        "WHERE ag.alive=1 ORDER BY a.balance_cents DESC, ag.id LIMIT 1"))
    firm_id = int(world.store.scalar(
        "SELECT id FROM firms WHERE status IN ('private','listed') ORDER BY id LIMIT 1"))

    async def no_decisions(tick):
        return []

    def buy_during_execution(tick, decisions):
        result = world.economy.firms.buy_goods(tick, buyer_id, firm_id, 1)
        assert result["ok"]

    world.runtime.decide_all = no_decisions
    world.runtime.execute_decisions = buy_during_execution
    asyncio.run(world.step())

    sale_cents = int(world.store.scalar(
        "SELECT json_extract(payload_json,'$.total_cents') FROM events "
        "WHERE tick=1 AND kind='goods_sale' LIMIT 1"))
    assert world.store.metric_at_or_before("gdp_proxy", 1) == pytest.approx(sale_cents / 100)
    assert world.store.scalar(
        "SELECT COUNT(*) FROM metrics WHERE tick=1 AND name='gdp_proxy'") == 1

    world._phase_finalize(1)
    assert world.store.scalar(
        "SELECT COUNT(*) FROM metrics WHERE tick=1 AND name='gdp_proxy'") == 1
    world.store.close()


def test_finalize_reconciliation_catches_execution_corruption(tmp_path):
    world = _world(tmp_path, "finalize-reconcile.db")
    account_id = int(world.store.scalar("SELECT id FROM accounts ORDER BY id LIMIT 1"))

    async def no_decisions(tick):
        return []

    def corrupt_during_execution(tick, decisions):
        world.store.execute(
            "UPDATE accounts SET balance_cents=balance_cents+1 WHERE id=?", (account_id,))

    world.runtime.decide_all = no_decisions
    world.runtime.execute_decisions = corrupt_during_execution
    with pytest.raises(ReconciliationError):
        asyncio.run(world.step())

    meta = world.store.get_meta()
    assert meta["status"] == "halted"
    assert meta["tick"] == 0 and meta["active_tick"] == 1
    assert meta["next_phase"] == "FINALIZE"
    assert world.store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='reconciliation_failure'") == 1
    world.store.close()


def test_cpi_uses_fixed_genesis_goods_basket(tmp_path):
    world = _world(tmp_path, "fixed-cpi.db")
    baseline = world.metrics._cpi()
    firm_id = int(world.store.scalar(
        "SELECT id FROM firms WHERE founded_tick=0 "
        "AND sector NOT IN ('health','insurance') ORDER BY id LIMIT 1"))
    world.store.update("firms", firm_id, status="bankrupt", bankrupt_tick=1)
    world.store.insert(
        "firms", name="Diagnostic Hospital", sector="health", status="private",
        product_json=json.dumps({"product": "care", "unit_price_cents": 999999}),
        founded_tick=0)

    assert world.metrics._cpi() == pytest.approx(baseline)
    world.store.close()


def test_goods_context_excludes_zero_inventory(tmp_path):
    world = _world(tmp_path, "stocked-offers.db")
    firm_id = int(world.store.scalar(
        "SELECT id FROM firms WHERE status IN ('private','listed') ORDER BY id LIMIT 1"))
    world.store.update("firms", firm_id, inventory=0)
    assert firm_id not in {offer["firm_id"] for offer in world.runtime.ctx._goods_offers()}
    world.store.update("firms", firm_id, inventory=1)
    assert firm_id in {offer["firm_id"] for offer in world.runtime.ctx._goods_offers()}
    world.store.close()


def test_recovery_genesis_uses_the_feasible_configured_wage_floor(tmp_path):
    profile = {
        "enabled": True,
        "wage_floor_cents": 15_000,
        "gross_margin_coverage_bps": 12_500,
        "cash_payroll_coverage_periods": 2,
        "max_hires_per_firm_per_period": 1,
        "demand_buffer_ticks": 5,
        "sales_observation_ticks": 30,
    }
    world = _world(tmp_path, "recovery-genesis.db", supply_recovery=profile)
    try:
        rows = world.store.query(
            "SELECT e.wage_cents,f.product_json FROM employments e JOIN firms f "
            "ON f.id=e.firm_id WHERE e.status='active' "
            "AND json_extract(f.product_json,'$.output_per_worker') IS NOT NULL "
            "ORDER BY e.id"
        )
        settings = recovery_settings(world.config)

        assert rows
        assert {int(row["wage_cents"]) for row in rows} == {15_000}
        for row in rows:
            product = load_json(row["product_json"], {})
            assessment = assess_recovery(
                enabled=True,
                price_cents=int(product["unit_price_cents"]),
                input_cost_cents=int(product["base_input_cost_cents"]),
                output_per_worker=int(product["output_per_worker"]),
                pay_interval_ticks=int(world.config.get("firms", {}).get(
                    "pay_interval_ticks", 30)),
                wage_cents=int(row["wage_cents"]),
                cash_cents=1_000_000,
                current_payroll_cents=0,
                current_headcount=0,
                target_headcount=1,
                recent_sales_units=0,
                settings=settings,
            )
            assert int(row["wage_cents"]) <= assessment.safe_wage_ceiling_cents
    finally:
        world.store.close()


def test_recovery_genesis_respects_the_activation_tick(tmp_path):
    profile = {
        "enabled": True,
        "wage_floor_cents": 15_000,
        "gross_margin_coverage_bps": 12_500,
        "cash_payroll_coverage_periods": 2,
        "max_hires_per_firm_per_period": 1,
        "demand_buffer_ticks": 5,
        "sales_observation_ticks": 30,
        "activation_tick": 1,
    }
    world = _world(tmp_path, "recovery-preactivation-genesis.db", supply_recovery=profile)
    try:
        wages = [int(row["wage_cents"]) for row in world.store.query(
            "SELECT e.wage_cents FROM employments e JOIN firms f ON f.id=e.firm_id "
            "WHERE e.status='active' "
            "AND json_extract(f.product_json,'$.output_per_worker') IS NOT NULL "
            "ORDER BY e.id"
        )]

        assert wages and all(wage >= 250_000 for wage in wages)
    finally:
        world.store.close()


def test_recovery_runtime_blocks_an_unsustainable_employer_action(tmp_path):
    profile = {
        "enabled": True,
        "wage_floor_cents": 15_000,
        "gross_margin_coverage_bps": 12_500,
        "cash_payroll_coverage_periods": 2,
        "max_hires_per_firm_per_period": 1,
        "demand_buffer_ticks": 5,
        "sales_observation_ticks": 30,
    }
    world = _world(tmp_path, "recovery-runtime.db", supply_recovery=profile)
    try:
        firm = world.store.query_one(
            "SELECT id,founder_agent_id FROM firms WHERE "
            "json_extract(product_json,'$.output_per_worker') IS NOT NULL ORDER BY id LIMIT 1"
        )
        assert firm is not None
        world.store.log_event(1, "goods_sale", {
            "firm_id": int(firm["id"]), "qty": 1_000,
        })

        world.runtime.execute_decisions(1, [{
            "agent_id": int(firm["founder_agent_id"]),
            "purpose": "founder",
            "envelope": {"actions": [{
                "type": "post_job", "firm_id": int(firm["id"]),
                "title": "worker", "wage": 250_000,
            }]},
            "llm_call_id": None,
        }])

        assert world.store.scalar(
            "SELECT COUNT(*) FROM jobs WHERE firm_id=?", (int(firm["id"]),)) == 0
    finally:
        world.store.close()


def test_recovery_runtime_allows_a_feasible_floor_wage_action(tmp_path):
    profile = {
        "enabled": True,
        "wage_floor_cents": 15_000,
        "gross_margin_coverage_bps": 12_500,
        "cash_payroll_coverage_periods": 2,
        "max_hires_per_firm_per_period": 1,
        "demand_buffer_ticks": 5,
        "sales_observation_ticks": 30,
    }
    world = _world(tmp_path, "recovery-runtime-floor.db", supply_recovery=profile)
    try:
        firm = world.store.query_one(
            "SELECT id,founder_agent_id FROM firms WHERE "
            "json_extract(product_json,'$.output_per_worker') IS NOT NULL ORDER BY id LIMIT 1"
        )
        assert firm is not None
        world.store.log_event(1, "goods_sale", {
            "firm_id": int(firm["id"]), "qty": 1_000,
        })

        world.runtime.execute_decisions(1, [{
            "agent_id": int(firm["founder_agent_id"]),
            "purpose": "founder",
            "envelope": {"actions": [{
                "type": "post_job", "firm_id": int(firm["id"]),
                "title": "worker", "wage": 15_000,
            }]},
            "llm_call_id": None,
        }])

        assert world.store.scalar(
            "SELECT wage_cents FROM jobs WHERE firm_id=?", (int(firm["id"]),)) == 15_000
    finally:
        world.store.close()


def test_recovery_feature_off_keeps_legacy_runtime_job_posting(tmp_path):
    world = _world(tmp_path, "recovery-feature-off-runtime.db")
    try:
        firm = world.store.query_one(
            "SELECT id,founder_agent_id FROM firms WHERE "
            "json_extract(product_json,'$.output_per_worker') IS NOT NULL ORDER BY id LIMIT 1"
        )
        assert firm is not None

        world.runtime.execute_decisions(1, [{
            "agent_id": int(firm["founder_agent_id"]),
            "purpose": "founder",
            "envelope": {"actions": [{
                "type": "post_job", "firm_id": int(firm["id"]),
                "title": "worker", "wage": 250_000,
            }]},
            "llm_call_id": None,
        }])

        assert world.store.scalar(
            "SELECT wage_cents FROM jobs WHERE firm_id=?", (int(firm["id"]),)) == 250_000
    finally:
        world.store.close()


def test_inventory_aware_shopping_is_explicit_in_context_and_prompt(tmp_path):
    world = _world(
        tmp_path,
        "inventory-aware-context.db",
        engine_semantics_version=7,
        behavior={
            "act_every": 1,
            "run_threshold": 0.35,
            "inventory_aware_shopping": True,
        },
    )
    agent = world.store.query_one(
        "SELECT * FROM agents WHERE kind='citizen' AND alive=1 ORDER BY id LIMIT 1")

    context = world.runtime.ctx.build(agent, 1)
    _, prompt = world.runtime.ctx.render_prompt(context)

    assert context["inventory_aware_shopping_enabled"] is True
    assert "shared morning snapshot" in prompt
    world.store.close()


def test_supply_recovery_activation_is_forward_only_and_idempotent(tmp_path):
    world = _world(
        tmp_path,
        "supply-recovery.db",
        engine_semantics_version=7,
        population={"target_total": 1_000},
        firms={"count": 12, "listed": 3, "target_headcount": 3},
    )

    activated = run_module.activate_supply_recovery_for_run(
        world, target_headcount=80)
    repeated = run_module.activate_supply_recovery_for_run(
        world, target_headcount=80)
    stored_config = json.loads(world.store.get_meta()["config_json"])

    assert activated == repeated == {
        "activation_tick": 1,
        "target_headcount": 80,
        "operational_activation_tick": 1,
    }
    assert stored_config["firms"]["target_headcount"] == 3
    assert stored_config["firms"]["workforce_recovery_activation_tick"] == 1
    assert stored_config["firms"]["workforce_recovery_target_headcount"] == 80
    assert stored_config[
        "firms"]["workforce_recovery_operational_activation_tick"] == 1
    assert stored_config["firms"]["workforce_recovery_recapitalization_tick"] == 1
    assert stored_config["firms"]["workforce_recovery_min_wage_cents"] == 250_000
    assert stored_config[
        "firms"]["workforce_recovery_wage_floor_activation_tick"] == 1
    assert stored_config["behavior"]["inventory_aware_shopping_activation_tick"] == 1
    assert stored_config["behavior"]["job_application_aware_activation_tick"] == 1
    assert "inventory_aware_shopping_enabled" not in world.runtime.ctx.build(
        world.store.query_one(
            "SELECT * FROM agents WHERE kind='citizen' ORDER BY id LIMIT 1"),
        0,
    )
    citizen = world.store.query_one(
        "SELECT * FROM agents WHERE kind='citizen' ORDER BY id LIMIT 1")
    assert "job_application_aware_enabled" not in world.runtime.ctx.build(
        citizen, 0)
    activated_citizen_context = world.runtime.ctx.build(citizen, 1)
    assert activated_citizen_context["inventory_aware_shopping_enabled"] is True
    assert activated_citizen_context["job_application_aware_enabled"] is True
    founder = world.store.query_one(
        "SELECT a.* FROM agents a JOIN firms f ON f.founder_agent_id=a.id "
        "ORDER BY f.id LIMIT 1")
    assert "workforce_recovery_enabled" not in world.runtime.ctx.build(founder, 0)
    assert world.runtime.ctx.build(
        founder, 1)["workforce_recovery_enabled"] is True
    world.store.close()


def test_existing_supply_recovery_is_upgraded_at_the_next_untouched_tick(tmp_path):
    world = _world(
        tmp_path,
        "supply-recovery-upgrade.db",
        engine_semantics_version=7,
        population={"target_total": 1_000},
        firms={
            "count": 12,
            "listed": 3,
            "target_headcount": 3,
            "workforce_recovery_activation_tick": 34,
            "workforce_recovery_target_headcount": 80,
        },
        behavior={
            "act_every": 1,
            "run_threshold": 0.35,
            "inventory_aware_shopping_activation_tick": 34,
        },
    )
    world.store.set_meta(
        tick=34,
        config_json=json.dumps(world.config, sort_keys=True),
    )
    world.store.commit()

    activated = run_module.activate_supply_recovery_for_run(
        world, target_headcount=80)
    repeated = run_module.activate_supply_recovery_for_run(
        world, target_headcount=80)
    stored = json.loads(world.store.get_meta()["config_json"])

    assert activated == repeated == {
        "activation_tick": 34,
        "target_headcount": 80,
        "operational_activation_tick": 35,
    }
    assert stored["firms"]["workforce_recovery_operational_activation_tick"] == 35
    assert stored["firms"]["workforce_recovery_recapitalization_tick"] == 35
    assert stored["firms"]["workforce_recovery_batch_size"] == 4
    assert stored["firms"]["workforce_recovery_excluded_sectors"] == [
        "health", "insurance"]
    assert stored["firms"]["workforce_recovery_capital_per_worker_cents"] == 500_000
    assert stored["firms"]["workforce_recovery_min_wage_cents"] == 250_000
    assert stored[
        "firms"]["workforce_recovery_wage_floor_activation_tick"] == 35
    assert stored["behavior"]["job_application_aware_activation_tick"] == 35
    world.store.close()


def test_recapitalization_is_balanced_one_time_and_excludes_service_firms(tmp_path):
    world = _world(
        tmp_path,
        "supply-recapitalization.db",
        engine_semantics_version=7,
        population={"target_total": 1_000},
        firms={
            "count": 3,
            "listed": 1,
            "target_headcount": 3,
            "workforce_recovery_activation_tick": 1,
            "workforce_recovery_target_headcount": 80,
            "workforce_recovery_recapitalization_tick": 1,
            "workforce_recovery_capital_per_worker_cents": 500_000,
            "workforce_recovery_excluded_sectors": ["health", "insurance"],
        },
        health={"hospital": True, "insurer": True},
    )
    ordinary = world.store.query(
        "SELECT id,account_id FROM firms "
        "WHERE sector NOT IN ('health','insurance') ORDER BY id")
    services = world.store.query(
        "SELECT id,account_id FROM firms "
        "WHERE sector IN ('health','insurance') ORDER BY id")
    service_balances = {
        int(row["id"]): world.economy.ledger.balance(int(row["account_id"]))
        for row in services
    }

    world._apply_supply_recovery_recapitalization(1)
    balances_once = {
        int(row["id"]): world.economy.ledger.balance(int(row["account_id"]))
        for row in ordinary
    }
    world._apply_supply_recovery_recapitalization(1)

    assert set(balances_once.values()) == {40_000_000}
    assert {
        int(row["id"]): world.economy.ledger.balance(int(row["account_id"]))
        for row in ordinary
    } == balances_once
    assert {
        int(row["id"]): world.economy.ledger.balance(int(row["account_id"]))
        for row in services
    } == service_balances
    assert world.store.scalar(
        "SELECT COUNT(*) FROM events "
        "WHERE kind='supply_recovery_recapitalized' AND tick=1") == len(ordinary)
    assert world.store.scalar(
        "SELECT COUNT(*) FROM events "
        "WHERE kind='supply_recovery_recapitalization_applied' AND tick=1") == 1
    assert world.economy.ledger.reconcile()[0] is True
    world.store.close()


def test_recapitalization_applies_once_when_first_seen_after_activation(tmp_path):
    world = _world(
        tmp_path,
        "late-supply-recapitalization.db",
        engine_semantics_version=7,
        firms={
            "count": 3,
            "listed": 1,
            "target_headcount": 3,
            "workforce_recovery_target_headcount": 9,
            "workforce_recovery_recapitalization_tick": 1,
            "workforce_recovery_capital_per_worker_cents": 100_000,
            "workforce_recovery_excluded_sectors": ["health", "insurance"],
        },
    )

    world._apply_supply_recovery_recapitalization(2)
    world._apply_supply_recovery_recapitalization(3)

    events = world.store.query(
        "SELECT tick,payload_json FROM events "
        "WHERE kind='supply_recovery_recapitalization_applied' ORDER BY id")
    assert len(events) == 1
    assert int(events[0]["tick"]) == 2
    assert json.loads(events[0]["payload_json"])["activation_tick"] == 1
    world.store.close()


def test_existing_operational_recovery_adds_wage_floor_forward_only(tmp_path):
    world = _world(
        tmp_path,
        "supply-recovery-wage-upgrade.db",
        engine_semantics_version=7,
        population={"target_total": 1_000},
        firms={
            "count": 3,
            "listed": 1,
            "target_headcount": 3,
            "workforce_recovery_activation_tick": 34,
            "workforce_recovery_target_headcount": 80,
            "workforce_recovery_operational_activation_tick": 35,
            "workforce_recovery_recapitalization_tick": 35,
            "workforce_recovery_batch_size": 4,
            "workforce_recovery_excluded_sectors": ["health", "insurance"],
            "workforce_recovery_capital_per_worker_cents": 500_000,
        },
        behavior={
            "act_every": 1,
            "run_threshold": 0.35,
            "inventory_aware_shopping_activation_tick": 34,
            "job_application_aware_activation_tick": 35,
        },
    )
    world.store.set_meta(
        tick=35,
        config_json=json.dumps(world.config, sort_keys=True),
    )
    world.store.commit()

    run_module.activate_supply_recovery_for_run(
        world, target_headcount=80)
    repeated = run_module.activate_supply_recovery_for_run(
        world, target_headcount=80)
    stored = json.loads(world.store.get_meta()["config_json"])

    assert repeated["operational_activation_tick"] == 35
    assert stored["firms"]["workforce_recovery_min_wage_cents"] == 250_000
    assert stored[
        "firms"]["workforce_recovery_wage_floor_activation_tick"] == 36
    world.store.close()


def test_operational_recovery_closes_only_underfloor_ordinary_jobs(tmp_path):
    world = _world(
        tmp_path,
        "recovery-wage-floor.db",
        engine_semantics_version=7,
        population={"target_total": 1_000},
        firms={
            "count": 3,
            "listed": 1,
            "target_headcount": 3,
            "workforce_recovery_activation_tick": 1,
            "workforce_recovery_target_headcount": 80,
            "workforce_recovery_operational_activation_tick": 1,
            "workforce_recovery_min_wage_cents": 250_000,
            "workforce_recovery_wage_floor_activation_tick": 1,
            "workforce_recovery_excluded_sectors": ["health", "insurance"],
        },
        health={"hospital": True, "insurer": True},
    )
    ordinary_firm = int(world.store.scalar(
        "SELECT id FROM firms WHERE sector NOT IN ('health','insurance') "
        "ORDER BY id LIMIT 1"))
    service_firm = int(world.store.scalar(
        "SELECT id FROM firms WHERE sector IN ('health','insurance') "
        "ORDER BY id LIMIT 1"))
    low_job = world.store.insert(
        "jobs", tick=1, firm_id=ordinary_firm, title="worker",
        wage_cents=5_000, status="open")
    valid_job = world.store.insert(
        "jobs", tick=1, firm_id=ordinary_firm, title="worker",
        wage_cents=275_200, status="open")
    service_job = world.store.insert(
        "jobs", tick=1, firm_id=service_firm, title="orderly",
        wage_cents=200_000, status="open")

    world._enforce_workforce_recovery_job_floor(2)
    world._enforce_workforce_recovery_job_floor(2)

    assert world.store.scalar(
        "SELECT status FROM jobs WHERE id=?", (low_job,)) == "closed"
    assert world.store.scalar(
        "SELECT status FROM jobs WHERE id=?", (valid_job,)) == "open"
    assert world.store.scalar(
        "SELECT status FROM jobs WHERE id=?", (service_job,)) == "open"
    assert world.store.scalar(
        "SELECT COUNT(*) FROM events "
        "WHERE kind='workforce_recovery_job_floor_enforced'") == 1
    world.store.close()


def test_operational_recruiting_runs_for_unscheduled_ordinary_founders(tmp_path):
    world = _world(
        tmp_path,
        "operational-recruiting.db",
        engine_semantics_version=7,
        population={"target_total": 1_000},
        firms={
            "count": 3,
            "listed": 1,
            "target_headcount": 3,
            "workforce_recovery_activation_tick": 1,
            "workforce_recovery_target_headcount": 80,
            "workforce_recovery_operational_activation_tick": 1,
            "workforce_recovery_recapitalization_tick": 1,
            "workforce_recovery_capital_per_worker_cents": 500_000,
            "workforce_recovery_batch_size": 4,
            "workforce_recovery_excluded_sectors": ["health", "insurance"],
        },
        health={"hospital": True, "insurer": True},
    )
    world.runtime.scheduler.scheduled_agents = lambda *args, **kwargs: []
    world._apply_supply_recovery_recapitalization(1)

    decisions = asyncio.run(world.runtime.decide_all(1))
    founder_sectors = {
        int(row["founder_agent_id"]): row["sector"]
        for row in world.store.query(
            "SELECT founder_agent_id,sector FROM firms "
            "WHERE founder_agent_id IS NOT NULL")
    }
    recovery = [
        decision for decision in decisions
        if decision["purpose"] == "workforce_recovery"
    ]
    service_founder = world.store.query_one(
        "SELECT a.* FROM agents a JOIN firms f ON f.founder_agent_id=a.id "
        "WHERE f.sector IN ('health','insurance') ORDER BY f.id LIMIT 1")
    service_context = world.runtime.ctx.build(service_founder, 1)

    assert recovery
    assert "workforce_recovery_enabled" not in service_context
    assert service_context["my_firm"]["target_headcount"] == 3
    assert {
        founder_sectors[int(decision["agent_id"])]
        for decision in recovery
    }.isdisjoint({"health", "insurance"})
    assert {
        founder_sectors[int(decision["agent_id"])]
        for decision in recovery
    } == {
        row["sector"] for row in world.store.query(
            "SELECT DISTINCT sector FROM firms "
            "WHERE sector NOT IN ('health','insurance')")
    }
    assert all(decision["llm_call_id"] is None for decision in recovery)
    assert all(
        len([
            action for action in decision["envelope"]["actions"]
            if action["type"] == "post_job"
        ]) == 4
        for decision in recovery
    )
    world.store.close()


def test_recruit_to_target_uses_configured_recovery_headcount_without_tick(tmp_path):
    world = _world(
        tmp_path,
        "recruit-to-target-headcount.db",
        engine_semantics_version=7,
        firms={
            "count": 3,
            "listed": 1,
            "target_headcount": 3,
            "recruit_to_target": True,
            "workforce_recovery_target_headcount": 9,
            "workforce_recovery_excluded_sectors": ["health", "insurance"],
        },
    )
    founder = world.store.query_one(
        "SELECT a.* FROM agents a JOIN firms f ON f.founder_agent_id=a.id "
        "WHERE f.sector NOT IN ('health','insurance') ORDER BY f.id LIMIT 1")

    context = world.runtime.ctx.build(founder, 0)

    assert context["workforce_recovery_enabled"] is True
    assert context["my_firm"]["target_headcount"] == 9
    world.store.close()


def test_operational_recovery_replaces_model_staffing_with_audited_actions(tmp_path):
    world = _world(
        tmp_path,
        "operational-staffing-owner.db",
        engine_semantics_version=7,
        population={"target_total": 1_000},
        firms={
            "count": 3,
            "listed": 1,
            "target_headcount": 3,
            "workforce_recovery_activation_tick": 1,
            "workforce_recovery_target_headcount": 80,
            "workforce_recovery_operational_activation_tick": 1,
            "workforce_recovery_batch_size": 4,
            "workforce_recovery_excluded_sectors": ["health", "insurance"],
        },
    )
    founder = world.store.query_one(
        "SELECT a.*,f.id AS firm_id FROM agents a "
        "JOIN firms f ON f.founder_agent_id=a.id "
        "WHERE f.sector NOT IN ('health','insurance') ORDER BY f.id LIMIT 1")
    decision = {
        "agent_id": int(founder["id"]),
        "purpose": "founder",
        "envelope": {
            "actions": [
                {
                    "type": "post_job",
                    "firm_id": int(founder["firm_id"]),
                    "title": "worker",
                    "wage": 5_000,
                },
                {
                    "type": "set_price",
                    "firm_id": int(founder["firm_id"]),
                    "price": 600,
                },
            ],
        },
        "llm_call_id": 99,
    }

    world.runtime._replace_operational_workforce_actions(
        1, [decision], participant_agent_id=None)

    assert decision["envelope"]["actions"] == [{
        "type": "set_price",
        "firm_id": int(founder["firm_id"]),
        "price": 600,
    }]
    assert decision["operational_overrides"] == [{
        "type": "post_job",
        "firm_id": int(founder["firm_id"]),
        "title": "worker",
        "wage": 5_000,
    }]
    decision["llm_call_id"] = None
    world.runtime.execute_decisions(1, [decision])
    assert world.store.scalar(
        "SELECT COUNT(*) FROM events "
        "WHERE kind='workforce_recovery_model_action_replaced'") == 1
    world.store.close()


def test_operational_recovery_wakes_candidate_for_a_fair_recorded_offer(tmp_path):
    world = _world(
        tmp_path,
        "operational-candidate-response.db",
        engine_semantics_version=7,
        population={"target_total": 1_000},
        firms={
            "count": 3,
            "listed": 1,
            "target_headcount": 3,
            "workforce_recovery_activation_tick": 1,
            "workforce_recovery_target_headcount": 80,
            "workforce_recovery_operational_activation_tick": 1,
            "workforce_recovery_batch_size": 4,
            "workforce_recovery_excluded_sectors": ["health", "insurance"],
        },
    )
    firm = world.store.query_one(
        "SELECT * FROM firms WHERE sector NOT IN ('health','insurance') "
        "ORDER BY id LIMIT 1")
    founder_id = int(firm["founder_agent_id"])
    candidate_id = int(world.store.scalar(
        "SELECT a.id FROM agents a "
        "JOIN accounts ac ON ac.id=a.checking_account_id "
        "WHERE a.kind='citizen' AND a.alive=1 AND a.retired=0 "
        "AND a.employer_id IS NULL AND a.id NOT IN "
        "(SELECT founder_agent_id FROM firms WHERE founder_agent_id IS NOT NULL) "
        "AND ac.currency_code=? ORDER BY a.id LIMIT 1",
        (firm["currency_code"],),
    ))
    job_id = world.economy.labor.post_job(
        1, int(firm["id"]), "worker", 250_000)
    application_id = world.economy.labor.apply_job(
        1, candidate_id, job_id)
    offer_id = world.economy.labor.make_offer(
        1, int(application_id), founder_id, 250_000)
    world.runtime.scheduler.scheduled_agents = lambda *args, **kwargs: []

    decisions = asyncio.run(world.runtime.decide_all(2))
    candidate_decisions = [
        decision for decision in decisions
        if decision["purpose"] == "workforce_recovery_candidate"
    ]

    assert candidate_decisions == [{
        "agent_id": candidate_id,
        "purpose": "workforce_recovery_candidate",
        "envelope": {
            "reasoning": "accepting a fair recorded recovery offer",
            "actions": [{
                "type": "accept_job_offer",
                "offer_id": int(offer_id),
            }],
            "belief_updates": [],
        },
        "reasoning": "accepting a fair recorded recovery offer",
        "llm_call_id": None,
    }]
    world.runtime.execute_decisions(2, candidate_decisions)
    assert world.store.scalar(
        "SELECT COUNT(*) FROM employments "
        "WHERE agent_id=? AND status='active'",
        (candidate_id,),
    ) == 1
    world.store.close()


def test_operational_recovery_accepts_at_most_one_offer_per_job(tmp_path):
    world = _world(
        tmp_path,
        "operational-candidate-job-reservation.db",
        engine_semantics_version=7,
        population={"target_total": 1_000},
        firms={
            "count": 3,
            "listed": 1,
            "target_headcount": 3,
            "workforce_recovery_activation_tick": 1,
            "workforce_recovery_target_headcount": 80,
            "workforce_recovery_operational_activation_tick": 1,
            "workforce_recovery_batch_size": 4,
            "workforce_recovery_excluded_sectors": ["health", "insurance"],
        },
    )
    firm = world.store.query_one(
        "SELECT * FROM firms WHERE sector NOT IN ('health','insurance') "
        "ORDER BY id LIMIT 1")
    founder_id = int(firm["founder_agent_id"])
    candidate_ids = [
        int(row["id"]) for row in world.store.query(
            "SELECT a.id FROM agents a "
            "JOIN accounts ac ON ac.id=a.checking_account_id "
            "WHERE a.kind='citizen' AND a.alive=1 AND a.retired=0 "
            "AND a.employer_id IS NULL AND a.id NOT IN "
            "(SELECT founder_agent_id FROM firms WHERE founder_agent_id IS NOT NULL) "
            "AND ac.currency_code=? ORDER BY a.id LIMIT 2",
            (firm["currency_code"],),
        )
    ]
    first_job = world.economy.labor.post_job(
        1, int(firm["id"]), "worker", 250_000)
    second_job = world.economy.labor.post_job(
        1, int(firm["id"]), "worker", 250_000)
    first_on_first = world.economy.labor.apply_job(
        1, candidate_ids[0], first_job)
    first_on_second = world.economy.labor.apply_job(
        1, candidate_ids[0], second_job)
    second_on_first = world.economy.labor.apply_job(
        1, candidate_ids[1], first_job)
    world.economy.labor.make_offer(
        1, int(first_on_first), founder_id, 250_000)
    first_second_offer = world.economy.labor.make_offer(
        1, int(first_on_second), founder_id, 250_000)
    second_first_offer = world.economy.labor.make_offer(
        1, int(second_on_first), founder_id, 250_000)
    world.runtime.scheduler.scheduled_agents = lambda *args, **kwargs: []

    decisions = asyncio.run(world.runtime.decide_all(2))
    candidate_decisions = [
        decision for decision in decisions
        if decision["purpose"] == "workforce_recovery_candidate"
    ]

    assert {
        decision["envelope"]["actions"][0]["offer_id"]
        for decision in candidate_decisions
    } == {int(first_second_offer), int(second_first_offer)}
    world.runtime.execute_decisions(2, candidate_decisions)
    assert world.store.scalar(
        "SELECT COUNT(*) FROM employments "
        "WHERE agent_id IN (?,?) AND status='active'",
        tuple(candidate_ids),
    ) == 2
    assert world.store.scalar(
        "SELECT COUNT(*) FROM action_proposals "
        "WHERE tick=2 AND action_type='accept_job_offer' "
        "AND validation_status='rejected'",
    ) == 0
    world.store.close()


def test_operational_recovery_coordinates_scheduled_candidate_acceptances(tmp_path):
    world = _world(
        tmp_path,
        "operational-scheduled-candidate-reservation.db",
        engine_semantics_version=7,
        population={"target_total": 1_000},
        firms={
            "count": 3,
            "listed": 1,
            "target_headcount": 3,
            "workforce_recovery_activation_tick": 1,
            "workforce_recovery_target_headcount": 80,
            "workforce_recovery_operational_activation_tick": 1,
            "workforce_recovery_batch_size": 4,
            "workforce_recovery_excluded_sectors": ["health", "insurance"],
        },
    )
    firm = world.store.query_one(
        "SELECT * FROM firms WHERE sector NOT IN ('health','insurance') "
        "ORDER BY id LIMIT 1")
    founder_id = int(firm["founder_agent_id"])
    candidate_ids = [
        int(row["id"]) for row in world.store.query(
            "SELECT a.id FROM agents a "
            "JOIN accounts ac ON ac.id=a.checking_account_id "
            "WHERE a.kind='citizen' AND a.alive=1 AND a.retired=0 "
            "AND a.employer_id IS NULL AND a.id NOT IN "
            "(SELECT founder_agent_id FROM firms WHERE founder_agent_id IS NOT NULL) "
            "AND ac.currency_code=? ORDER BY a.id LIMIT 2",
            (firm["currency_code"],),
        )
    ]
    job_id = world.economy.labor.post_job(
        1, int(firm["id"]), "worker", 250_000)
    offers = []
    for candidate_id in candidate_ids:
        application_id = world.economy.labor.apply_job(
            1, candidate_id, job_id)
        offers.append(world.economy.labor.make_offer(
            1, int(application_id), founder_id, 250_000))
    decisions = [{
        "agent_id": candidate_id,
        "purpose": "decision",
        "envelope": {
            "reasoning": "accepting the available fair offer",
            "actions": [{
                "type": "accept_job_offer",
                "offer_id": int(offer_id),
            }],
            "belief_updates": [],
        },
        "reasoning": "accepting the available fair offer",
        "llm_call_id": None,
    } for candidate_id, offer_id in zip(candidate_ids, offers)]

    world.runtime._coordinate_workforce_recovery_candidate_acceptances(
        2, decisions, participant_agent_id=None)
    world.runtime.execute_decisions(2, decisions)

    assert world.store.scalar(
        "SELECT COUNT(*) FROM action_proposals "
        "WHERE tick=2 AND action_type='accept_job_offer' "
        "AND validation_status='accepted'",
    ) == 1
    assert world.store.scalar(
        "SELECT COUNT(*) FROM action_proposals "
        "WHERE tick=2 AND action_type='accept_job_offer' "
        "AND validation_status='rejected'",
    ) == 0
    world.store.close()


def test_operational_recovery_leaves_malformed_offer_for_validation(tmp_path):
    world = _world(
        tmp_path,
        "operational-malformed-offer.db",
        engine_semantics_version=7,
        firms={
            "count": 3,
            "listed": 1,
            "target_headcount": 3,
            "workforce_recovery_activation_tick": 1,
            "workforce_recovery_target_headcount": 80,
            "workforce_recovery_operational_activation_tick": 1,
            "workforce_recovery_batch_size": 4,
            "workforce_recovery_excluded_sectors": ["health", "insurance"],
        },
    )
    candidate_id = int(world.store.scalar(
        "SELECT id FROM agents WHERE kind='citizen' AND alive=1 ORDER BY id LIMIT 1"))
    decisions = [{
        "agent_id": candidate_id,
        "purpose": "decision",
        "envelope": {
            "reasoning": "attempting a malformed offer reference",
            "actions": [{"type": "accept_job_offer", "offer_id": None}],
            "belief_updates": [],
        },
        "reasoning": "attempting a malformed offer reference",
        "llm_call_id": None,
    }]

    world.runtime._coordinate_workforce_recovery_candidate_acceptances(
        2, decisions, participant_agent_id=None)
    world.runtime.execute_decisions(2, decisions)

    proposal = world.store.query_one(
        "SELECT validation_status,result_json FROM action_proposals "
        "WHERE tick=2 AND action_type='accept_job_offer'")
    assert proposal["validation_status"] == "rejected"
    assert json.loads(proposal["result_json"]) == {
        "ok": False,
        "reason": "offer_id must be a positive integer",
    }
    world.store.close()


def test_citizen_goods_context_only_exposes_same_currency_sellers(tmp_path):
    world = _world(
        tmp_path, "local-goods-offers.db",
        llm={"local_currency_action_surfaces": True,
             "default_route": {"provider": "scripted", "model": "scripted"},
             "routes": {}},
    )
    agent = world.store.query_one(
        "SELECT a.* FROM agents a JOIN accounts c "
        "ON c.owner_type='agent' AND c.owner_id=a.id AND c.kind='checking' "
        "ORDER BY a.id LIMIT 1")
    checking_id = int(world.store.scalar(
        "SELECT id FROM accounts WHERE owner_type='agent' AND owner_id=? "
        "AND kind='checking' ORDER BY id LIMIT 1", (int(agent["id"]),)))
    firms = world.store.query(
        "SELECT id FROM firms WHERE status IN ('private','listed') ORDER BY id LIMIT 2")
    local_id, foreign_id = (int(firms[0]["id"]), int(firms[1]["id"]))
    world.store.update("accounts", checking_id, currency_code="NSD")
    world.store.update("firms", local_id, currency_code="NSD", inventory=10)
    world.store.update("firms", foreign_id, currency_code="IVC", inventory=10)

    context = world.runtime.ctx._citizen_context(agent, 1)
    offered = {offer["firm_id"] for offer in context["prices"]}

    assert context["state"]["currency_code"] == "NSD"
    assert local_id in offered
    assert foreign_id not in offered
    world.store.close()


def test_v2_currency_surfaces_follow_primary_wallet_and_reject_foreign_ids(tmp_path):
    config = load_config("runs/v2-institutional-rehearsal.yaml")
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    store, world, _ = open_run(config, None, None, data_dir=tmp_path)
    try:
        actor = store.query_one(
            "SELECT a.* FROM agents a JOIN regions r ON r.id=a.region_id "
            "WHERE a.kind='citizen' AND a.alive=1 AND r.currency_code='NSD' "
            "AND NOT EXISTS (SELECT 1 FROM firms f WHERE f.founder_agent_id=a.id) "
            "AND NOT EXISTS (SELECT 1 FROM loan_applications p "
            "WHERE p.borrower_type='agent' AND p.borrower_id=a.id) ORDER BY a.id LIMIT 1")
        actor_id = int(actor["id"])
        old_primary = int(actor["checking_account_id"])
        old_balance = world.economy.ledger.balance(old_primary)

        placed = world.economy.regions.place_fx_order(0, actor_id, {
            "pair": "IVC/NSD", "side": "buy", "qty": 5_000,
        })
        assert placed["ok"] and len(world.economy.regions.match_fx(0)) == 1
        ivc_wallet = store.query_one(
            "SELECT id,balance_cents FROM accounts WHERE owner_type='agent' AND owner_id=? "
            "AND currency_code='IVC' ORDER BY id DESC LIMIT 1", (actor_id,))
        assert old_balance > int(ivc_wallet["balance_cents"])
        store.update("agents", actor_id, checking_account_id=int(ivc_wallet["id"]))
        actor = store.query_one("SELECT * FROM agents WHERE id=?", (actor_id,))

        local_firm = store.query_one(
            "SELECT * FROM firms WHERE currency_code='IVC' AND founder_agent_id IS NOT NULL "
            "ORDER BY id LIMIT 1")
        foreign_firm = store.query_one(
            "SELECT * FROM firms WHERE currency_code<>'IVC' AND founder_agent_id IS NOT NULL "
            "ORDER BY id LIMIT 1")
        local_id, foreign_id = int(local_firm["id"]), int(foreign_firm["id"])
        store.update("firms", local_id, status="listed", inventory=10)
        store.update("firms", foreign_id, status="listed", inventory=10)
        local_job = world.economy.labor.post_job(0, local_id, "local role", 100)
        foreign_job = world.economy.labor.post_job(0, foreign_id, "foreign role", 100)
        local_bank = int(store.scalar(
            "SELECT id FROM banks WHERE currency_code='IVC' AND status='open' ORDER BY id LIMIT 1"))
        foreign_bank = int(store.scalar(
            "SELECT id FROM banks WHERE currency_code<>'IVC' AND status='open' ORDER BY id LIMIT 1"))

        context = world.runtime.ctx._citizen_context(actor, 1)
        assert context["state"]["currency_code"] == "IVC"
        assert context["state"]["checking_balance"] == int(ivc_wallet["balance_cents"])
        assert {row["currency_code"] for row in context["prices"]} <= {"IVC"}
        assert {row["currency_code"] for row in context["jobs"]} <= {"IVC"}
        assert {row["currency_code"] for row in context["listed_firms"]} <= {"IVC"}
        assert {row["currency_code"] for row in context["banks"]} == {"IVC"}
        assert local_job in {row["job_id"] for row in context["jobs"]}
        assert foreign_job not in {row["job_id"] for row in context["jobs"]}
        assert local_id in {row["firm_id"] for row in context["listed_firms"]}
        assert foreign_id not in {row["firm_id"] for row in context["listed_firms"]}
        assert local_bank in {row["id"] for row in context["banks"]}
        assert foreign_bank not in {row["id"] for row in context["banks"]}

        catalog = world.runtime.participant.action_catalog(actor_id)
        transfer = next(row for row in catalog if row["type"] == "transfer")
        recipient_ids = [int(option["value"]) for option in transfer["fields"][0]["options"]]
        recipient_currencies = {str(row["currency_code"]) for row in store.query(
            f"SELECT DISTINCT currency_code FROM accounts WHERE id IN "
            f"({','.join('?' for _ in recipient_ids)})", tuple(recipient_ids))} if recipient_ids else set()
        assert recipient_currencies <= {"IVC"}

        executor = world.runtime.executor
        assert executor.local_currency_action_surfaces is True
        assert world.runtime.participant.local_currency_action_surfaces is True
        assert world.economy.bank.local_currency_action_surfaces is True
        assert world.economy.regions.local_currency_action_surfaces is True
        order_count = int(store.scalar("SELECT COUNT(*) FROM orders"))
        app_count = int(store.scalar("SELECT COUNT(*) FROM applications"))
        loan_count = int(store.scalar("SELECT COUNT(*) FROM loan_applications"))
        assert not executor.execute_action(1, actor_id, {
            "type": "place_order", "firm_id": foreign_id, "side": "buy",
            "qty": 1, "limit_price": 1,
        })["ok"]
        assert executor.execute_action(1, actor_id, {
            "type": "apply_job", "job_id": foreign_job,
        }) == {
            "ok": False,
            "reason": "job must use the applicant's primary currency",
        }
        assert not executor.execute_action(1, actor_id, {
            "type": "apply_loan", "bank_id": foreign_bank, "amount": 100,
            "purpose": "foreign currency",
        })["ok"]
        assert store.scalar("SELECT COUNT(*) FROM orders") == order_count
        assert store.scalar("SELECT COUNT(*) FROM applications") == app_count
        assert store.scalar("SELECT COUNT(*) FROM loan_applications") == loan_count

        assert executor.execute_action(1, actor_id, {
            "type": "place_order", "firm_id": local_id, "side": "buy",
            "qty": 1, "limit_price": 1,
        })["ok"]
        store.update("jobs", local_job, status="filled")
        assert executor.execute_action(1, actor_id, {
            "type": "apply_job", "job_id": local_job,
        }) == {
            "ok": False,
            "reason": "job unavailable",
        }
        store.update("jobs", local_job, status="open")
        assert executor.execute_action(1, actor_id, {
            "type": "apply_job", "job_id": local_job,
        })["ok"]
        assert executor.execute_action(1, actor_id, {
            "type": "apply_loan", "bank_id": local_bank, "amount": 100,
            "purpose": "local currency",
        })["ok"]

        bypassed = world.economy.labor.apply_job(1, actor_id, foreign_job)
        assert bypassed is not None
        assert int(bypassed) not in {
            application["application_id"]
            for application in world.runtime.ctx._firm_applications(foreign_id)
        }
        assert not executor.execute_action(1, int(foreign_firm["founder_agent_id"]), {
            "type": "hire", "application_id": bypassed,
        })["ok"]
        assert store.scalar(
            "SELECT COUNT(*) FROM employments WHERE agent_id=? AND firm_id=? AND status='active'",
            (actor_id, foreign_id)) == 0

        moved = executor.execute_action(1, actor_id, {
            "type": "move_deposits", "to_bank_id": local_bank, "amount": 0,
        })
        assert moved["ok"]
        new_primary = int(store.scalar(
            "SELECT checking_account_id FROM agents WHERE id=?", (actor_id,)))
        assert new_primary != old_primary
        assert store.scalar(
            "SELECT currency_code FROM accounts WHERE id=?", (new_primary,)) == "IVC"
        assert world.economy.ledger.reconcile()[0]
    finally:
        store.close()


def test_foreign_currency_action_guards_are_opt_in_for_legacy_replay(tmp_path):
    world = _world(tmp_path, "legacy-currency-actions.db")
    store = world.store
    try:
        executor = world.runtime.executor
        assert executor.local_currency_action_surfaces is False
        assert world.runtime.participant.local_currency_action_surfaces is False
        assert world.economy.bank.local_currency_action_surfaces is False
        assert world.economy.regions.local_currency_action_surfaces is False
        actor = store.query_one(
            "SELECT * FROM agents WHERE kind='citizen' AND alive=1 "
            "AND id NOT IN (SELECT founder_agent_id FROM firms WHERE founder_agent_id IS NOT NULL) "
            "ORDER BY id LIMIT 1")
        actor_id = int(actor["id"])
        firm = store.query_one(
            "SELECT * FROM firms WHERE founder_agent_id IS NOT NULL ORDER BY id LIMIT 1")
        firm_id = int(firm["id"])
        founder_id = int(firm["founder_agent_id"])
        bank_id = int(store.scalar("SELECT id FROM banks WHERE status='open' ORDER BY id LIMIT 1"))
        store.update("accounts", int(actor["checking_account_id"]), currency_code="NSD")
        store.update("firms", firm_id, status="listed", currency_code="IVC", inventory=10)
        store.update("banks", bank_id, currency_code="IVC")
        job_id = world.economy.labor.post_job(0, firm_id, "legacy foreign role", 100)

        application = executor.execute_action(
            1, actor_id, {"type": "apply_job", "job_id": job_id})
        assert application["ok"]
        assert executor.execute_action(1, founder_id, {
            "type": "hire", "application_id": application["application_id"],
        })["ok"]
        assert executor.execute_action(1, actor_id, {
            "type": "place_order", "firm_id": firm_id, "side": "buy",
            "qty": 1, "limit_price": 1,
        })["ok"]
        loan_application = executor.execute_action(1, actor_id, {
            "type": "apply_loan", "bank_id": bank_id, "amount": 100,
            "purpose": "legacy foreign currency",
        })
        assert loan_application["ok"]

        officer_id = int(store.scalar(
            "SELECT id FROM agents WHERE role='credit_officer' AND alive=1 ORDER BY id LIMIT 1"))
        approval = executor.execute_action(1, officer_id, {
            "type": "approve_loan", "application_id": loan_application["application_id"],
            "rate_bps": 500, "term_ticks": 30,
        })
        assert not approval["ok"]
        assert "unbalanced transaction 'loan_disburse' by currency" in approval["reason"]
        assert store.scalar(
            "SELECT COUNT(*) FROM events WHERE kind='loan_denied_currency'") == 0
        assert store.scalar("SELECT COUNT(*) FROM loans WHERE borrower_type='agent' "
                            "AND borrower_id=?", (actor_id,)) == 0
    finally:
        store.close()


def test_legacy_replay_flag_preserves_richest_deposit_and_all_recipient_surfaces(tmp_path):
    world = _world(tmp_path, "legacy-deposits-and-recipients.db")
    store = world.store
    try:
        actor = store.query_one(
            "SELECT * FROM agents WHERE kind='citizen' AND alive=1 ORDER BY id LIMIT 1")
        actor_id = int(actor["id"])
        primary_id = int(actor["checking_account_id"])
        primary = store.query_one("SELECT * FROM accounts WHERE id=?", (primary_id,))
        destination_bank = int(store.scalar(
            "SELECT id FROM banks WHERE id<>? AND status='open' ORDER BY id LIMIT 1",
            (int(primary["bank_id"]),)))
        richer_id = world.economy.ledger.create_account(
            "agent", actor_id, "checking", bank_id=int(primary["bank_id"]),
            label="legacy richer checking",
            opening_cents=int(primary["balance_cents"]) + 1_000)
        foreign_recipient_id = world.economy.ledger.create_account(
            "system", None, "external", label="legacy foreign recipient",
            currency_code="IVC")
        primary_before = world.economy.ledger.balance(primary_id)
        richer_before = world.economy.ledger.balance(richer_id)

        moved = world.runtime.executor.execute_action(1, actor_id, {
            "type": "move_deposits", "to_bank_id": destination_bank, "amount": 100,
        })

        assert moved["ok"]
        assert world.economy.ledger.balance(richer_id) == richer_before - 100
        assert world.economy.ledger.balance(primary_id) == primary_before
        catalog = world.runtime.participant.action_catalog(actor_id)
        transfer = next(row for row in catalog if row["type"] == "transfer")
        recipient_ids = {int(option["value"])
                         for option in transfer["fields"][0]["options"]}
        assert foreign_recipient_id in recipient_ids
        assert world.economy.ledger.reconcile()[0]
    finally:
        store.close()


def test_legacy_replay_flag_leaves_migration_credit_guards_disabled(tmp_path):
    config = load_config("runs/v2-institutional-rehearsal.yaml")
    config["engine_semantics_version"] = 6
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    config["llm"]["local_currency_action_surfaces"] = False
    store, world, _ = open_run(config, None, None, data_dir=tmp_path)
    try:
        actor = store.query_one(
            "SELECT a.* FROM agents a JOIN accounts ac ON ac.id=a.checking_account_id "
            "WHERE a.kind='citizen' AND a.alive=1 AND a.region_id IS NOT NULL "
            "AND a.health='healthy' AND a.retired=0 AND a.role IS NULL "
            "AND NOT EXISTS (SELECT 1 FROM employments e WHERE e.agent_id=a.id "
            "AND e.status='active') "
            "AND ac.bank_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM loan_applications p WHERE p.borrower_type='agent' "
            "AND p.borrower_id=a.id) ORDER BY a.id LIMIT 1")
        actor_id = int(actor["id"])
        bank_id = int(store.scalar(
            "SELECT bank_id FROM accounts WHERE id=?", (int(actor["checking_account_id"]),)))
        destination_region_id = int(store.scalar(
            "SELECT id FROM regions WHERE id<>? ORDER BY id LIMIT 1",
            (int(actor["region_id"]),)))
        store.insert(
            "loans", bank_id=bank_id, borrower_type="agent", borrower_id=actor_id,
            principal_cents=100, outstanding_cents=100, rate_bps=0, term_ticks=30,
            origin_tick=1, payment_cents=100, payment_interval_ticks=30,
            next_due_tick=31, missed_payments=0, collateral_json="{}", status="active")

        requested = world.economy.regions.request_migration(
            1, actor_id, destination_region_id, "legacy replay")
        assert requested["ok"]
        applied = world.runtime.executor.execute_action(1, actor_id, {
            "type": "apply_loan", "bank_id": bank_id, "amount": 100,
            "purpose": "legacy pending migration",
        })
        assert applied["ok"]
        world.economy.regions.run_nightly(1)

        assert store.scalar(
            "SELECT status FROM migrations WHERE id=?", (requested["migration_id"],)) == "completed"
        assert store.scalar("SELECT region_id FROM agents WHERE id=?", (actor_id,)) == destination_region_id
    finally:
        store.close()


def test_migration_rejects_and_rechecks_agent_credit_exposure(tmp_path):
    config = load_config("runs/v2-institutional-rehearsal.yaml")
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    store, world, _ = open_run(config, None, None, data_dir=tmp_path)
    try:
        actor = store.query_one(
            "SELECT a.* FROM agents a JOIN accounts ac ON ac.id=a.checking_account_id "
            "WHERE a.kind='citizen' AND a.alive=1 AND a.region_id IS NOT NULL "
            "AND a.health='healthy' AND a.retired=0 AND a.role IS NULL "
            "AND NOT EXISTS (SELECT 1 FROM employments e WHERE e.agent_id=a.id "
            "AND e.status='active') "
            "AND ac.bank_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM loans l WHERE l.borrower_type='agent' "
            "AND l.borrower_id=a.id AND l.status='active') "
            "AND NOT EXISTS (SELECT 1 FROM loan_applications p WHERE p.borrower_type='agent' "
            "AND p.borrower_id=a.id AND p.status='pending') ORDER BY a.id LIMIT 1")
        actor_id = int(actor["id"])
        origin_region_id = int(actor["region_id"])
        destination_firm = store.query_one(
            "SELECT id,region_id FROM firms WHERE region_id<>? "
            "AND status NOT IN ('bankrupt','acquired') ORDER BY id LIMIT 1",
            (origin_region_id,))
        destination_region_id = int(destination_firm["region_id"])
        store.insert(
            "jobs", tick=0, firm_id=int(destination_firm["id"]),
            title="qualified migration role", wage_cents=100_000_000, status="open")
        cadence = json.loads(actor["cadence_json"] or "{}")
        career_every = max(1, int(cadence.get("career", 30)))
        career_tick = actor_id % career_every
        bank_id = int(store.scalar(
            "SELECT bank_id FROM accounts WHERE id=?", (int(actor["checking_account_id"]),)))

        pending_id = store.insert(
            "loan_applications", tick=career_tick, bank_id=bank_id, borrower_type="agent",
            borrower_id=actor_id, amount_cents=100, purpose="pending", status="pending")
        rejected = world.economy.regions.request_migration(
            career_tick, actor_id, destination_region_id, "pending credit")
        assert not rejected["ok"] and "pending loan application" in rejected["reason"]
        store.update("loan_applications", pending_id, status="denied", decided_tick=1)

        loan_id = store.insert(
            "loans", bank_id=bank_id, borrower_type="agent", borrower_id=actor_id,
            principal_cents=100, outstanding_cents=100, rate_bps=0, term_ticks=30,
            origin_tick=1, payment_cents=100, payment_interval_ticks=30,
            next_due_tick=31, missed_payments=0, collateral_json="{}", status="active")
        rejected = world.economy.regions.request_migration(
            career_tick, actor_id, destination_region_id, "active debt")
        assert not rejected["ok"] and "active loan debt" in rejected["reason"]
        store.update("loans", loan_id, status="paid", outstanding_cents=0)

        requested = world.economy.regions.request_migration(
            career_tick, actor_id, destination_region_id, "clear at request time")
        assert requested["ok"]
        assert not world.runtime.executor.execute_action(career_tick, actor_id, {
            "type": "apply_loan", "bank_id": bank_id, "amount": 100,
            "purpose": "while migrating",
        })["ok"]

        raced_application_id = store.insert(
            "loan_applications", tick=career_tick, bank_id=bank_id, borrower_type="agent",
            borrower_id=actor_id, amount_cents=100, purpose="simulated race", status="pending")
        officer_id = int(store.scalar(
            "SELECT id FROM agents WHERE role='credit_officer' AND alive=1 ORDER BY id LIMIT 1"))
        assert not world.runtime.executor.execute_action(career_tick, officer_id, {
            "type": "approve_loan", "application_id": raced_application_id,
            "rate_bps": 500, "term_ticks": 30,
        })["ok"]

        world.economy.regions.run_nightly(career_tick + 1)
        migration = store.query_one(
            "SELECT status,completed_tick FROM migrations WHERE id=?",
            (requested["migration_id"],))
        assert migration["status"] == "rejected"
        assert int(migration["completed_tick"]) == career_tick + 1
        assert store.scalar("SELECT region_id FROM agents WHERE id=?", (actor_id,)) == origin_region_id
        assert store.scalar(
            "SELECT COUNT(*) FROM events WHERE kind='migration_rejected_credit_exposure' "
            "AND subject_id=?", (actor_id,)) == 1
    finally:
        store.close()


def test_cross_currency_loan_payment_becomes_arrears_without_posting(tmp_path):
    config = load_config("runs/v2-institutional-rehearsal.yaml")
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    store, world, _ = open_run(config, None, None, data_dir=tmp_path)
    try:
        actor = store.query_one(
            "SELECT a.*,ac.bank_id,ac.currency_code FROM agents a "
            "JOIN accounts ac ON ac.id=a.checking_account_id "
            "WHERE a.kind='citizen' AND a.alive=1 AND ac.bank_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM loans l WHERE l.borrower_type='agent' "
            "AND l.borrower_id=a.id AND l.status='active') ORDER BY a.id LIMIT 1")
        actor_id = int(actor["id"])
        loan_id = store.insert(
            "loans", bank_id=int(actor["bank_id"]), borrower_type="agent",
            borrower_id=actor_id, principal_cents=100, outstanding_cents=100,
            rate_bps=0, term_ticks=30, origin_tick=0, payment_cents=100,
            payment_interval_ticks=30, next_due_tick=1, missed_payments=0,
            collateral_json="{}", status="active")
        foreign_currency = str(store.scalar(
            "SELECT code FROM currencies WHERE code<>? ORDER BY code LIMIT 1",
            (str(actor["currency_code"]),)))
        foreign_wallet = world.economy.regions._wallet(
            "agent", actor_id, foreign_currency, create=True)
        store.update("agents", actor_id, checking_account_id=foreign_wallet)
        transaction_count = int(store.scalar("SELECT COUNT(*) FROM transactions"))

        world.economy.bank.process_due_loans(1)

        loan = store.query_one(
            "SELECT outstanding_cents,missed_payments,status FROM loans WHERE id=?", (loan_id,))
        assert int(loan["outstanding_cents"]) == 100
        assert int(loan["missed_payments"]) == 1 and loan["status"] == "active"
        assert store.scalar("SELECT COUNT(*) FROM transactions") == transaction_count
        arrears = store.query_one(
            "SELECT payload_json FROM events WHERE kind='loan_arrears' "
            "AND subject_id=? ORDER BY id DESC LIMIT 1", (actor_id,))
        assert "primary currency no longer matches bank" in load_json(
            arrears["payload_json"], {})["reason"]
        assert world.economy.ledger.reconcile()[0]
    finally:
        store.close()


def test_real_model_prompt_exposes_market_and_founder_decision_surfaces(tmp_path):
    world = _world(
        tmp_path, "rendered-market-context.db",
        population={"size": 30},
        firms={"count": 12, "listed": 3, "target_headcount": 3},
    )
    world.store.execute(
        "UPDATE firms SET inventory=100 WHERE status IN ('private','listed')")
    founder = world.store.query_one(
        "SELECT a.* FROM agents a JOIN firms f ON f.founder_agent_id=a.id "
        "WHERE f.status IN ('private','listed') ORDER BY f.id LIMIT 1")
    firm_id = int(world.store.scalar(
        "SELECT id FROM firms WHERE founder_agent_id=?", (founder["id"],)))
    applicant_id = int(world.store.scalar(
        "SELECT id FROM agents WHERE kind='citizen' AND id<>? ORDER BY id DESC LIMIT 1",
        (founder["id"],)))
    job_id = world.economy.labor.post_job(0, firm_id, "Operator", 250000)
    application_id = world.economy.labor.apply_job(0, applicant_id, job_id)

    context = world.runtime.ctx.build(founder, 1)
    context["portfolio_day"] = True
    context["career_day"] = True
    system, prompt = world.runtime.ctx.render_prompt(context)

    assert "approve_loan{application_id,rate_bps,term_ticks}" in system
    assert "[MACRO" in prompt and "[BANKS" in prompt
    assert "[LISTED FIRMS" in prompt and "[PORTFOLIO REVIEW DUE]" in prompt
    assert "VALUE YOUR limit_price FROM FUNDAMENTALS" in prompt
    assert "[CAREER REVIEW DUE]" in prompt
    assert '"book_value_per_share":' in prompt
    assert '"recent_revenue_7":' in prompt
    assert "[YOUR FIRM" in prompt and '"unit_cost":' in prompt
    assert '"employee_roster":' in prompt and '"employment_id":' in prompt
    assert '"target_headcount":3' in prompt
    assert "[APPLICANTS" in prompt
    assert f'"application_id":{application_id}' in prompt
    assert f'"occupation":' in prompt
    assert "Manage your firm" in prompt
    assert "at most 10% per review" in prompt
    visible_goods = context["prices"][:16]
    assert len(visible_goods) == 12
    assert all(f'"firm_id":{offer["firm_id"]}' in prompt for offer in visible_goods)

    central_banker = world.store.query_one(
        "SELECT * FROM agents WHERE role='central_banker' LIMIT 1")
    cb_prompt = world.runtime.ctx.render_prompt(
        world.runtime.ctx.build(central_banker, 1))[1]
    assert "[CENTRAL BANK]" in cb_prompt
    assert "set_policy_rate{rate_bps}" in cb_prompt
    assert "natural_unemployment=" in cb_prompt

    founder_id = int(founder["id"])
    cadence = load_json(founder["cadence_json"], {})
    portfolio_tick = founder_id % int(cadence["portfolio"])
    career_tick = founder_id % int(cadence["career"])
    assert world.runtime.scheduler._citizen_wakes(founder, portfolio_tick, 1)
    assert world.runtime.scheduler._citizen_wakes(founder, career_tick, 1)

    class CapturingGateway:
        def __init__(self):
            self.request = None

        async def complete(self, request, **_kwargs):
            self.request = request
            return SimpleNamespace(parsed={
                "reasoning": "wait", "actions": [{"type": "do_nothing"}],
                "belief_updates": [],
            })

    gateway = CapturingGateway()
    world.runtime.gw = gateway
    asyncio.run(world.runtime._decide_one(1, founder))
    assert gateway.request.max_tokens == 900
    world.store.close()


def test_engine_semantics_version_preserves_markerless_runs(tmp_path):
    cfg = _config(tmp_path)
    fresh_store, fresh_world, _ = open_run(cfg, None, None, data_dir=tmp_path)
    persisted = json.loads(fresh_store.get_meta()["config_json"])
    assert persisted["engine_semantics_version"] == 2
    assert fresh_world.phases == PHASES
    fresh_store.close()

    legacy_id = "markerless-legacy"
    legacy_store = Store(str(tmp_path / f"{legacy_id}.db"))
    legacy_store.init_run_meta(legacy_id, int(cfg["seed"]), cfg)
    legacy_store.close()

    resumed_store, resumed_world, _ = open_run(
        {}, legacy_id, None, data_dir=tmp_path)
    assert resumed_world.engine_semantics_version == 1
    assert resumed_world.phases == LEGACY_PHASES
    resumed_world.initialize()
    firm_id = int(resumed_store.scalar(
        "SELECT id FROM firms WHERE status IN ('private','listed') ORDER BY id LIMIT 1"))
    resumed_store.update("firms", firm_id, inventory=0)
    assert firm_id in {
        offer["firm_id"] for offer in resumed_world.runtime.ctx._goods_offers()}
    resumed_store.close()

    replay_store, replay_world, _ = open_run(
        {}, None, legacy_id, data_dir=tmp_path)
    assert replay_world.engine_semantics_version == 1
    assert replay_world.phases == LEGACY_PHASES
    assert json.loads(replay_store.get_meta()["config_json"])[
        "engine_semantics_version"] == 1
    replay_world.close()


def test_exact_replay_rebuilds_fresh_database_and_proves_every_table(tmp_path):
    cfg = _config(tmp_path)
    source_store, source_world, source_id = open_run(
        cfg, None, None, data_dir=tmp_path)
    asyncio.run(source_world.run(max_ticks=4))

    replay_store, replay_world, replay_id = open_run(
        {}, None, source_id, data_dir=tmp_path)
    assert replay_id != source_id
    assert replay_store.tick == 0
    assert replay_world.gateway.replay
    asyncio.run(replay_world.run(max_ticks=4))

    proof = verify_replay(source_store.path, replay_store.path)
    assert proof["exact"], proof["differences"]
    assert proof["source_tick"] == proof["replay_tick"] == 4
    assert proof["source_hash"] == proof["replay_hash"]
    assert {table["table"] for table in proof["tables"]} >= {
        "accounts", "agents", "events", "ledger_entries", "llm_calls", "metrics"}

    replay_store.execute("UPDATE accounts SET balance_cents=balance_cents+1 WHERE id=1")
    replay_store.commit()
    changed = verify_replay(source_store.path, replay_store.path)
    assert not changed["exact"]
    assert "accounts" in changed["differences"]


@pytest.mark.parametrize("manifest_state", ["missing", "corrupt"])
def test_exact_replay_uses_recorded_inputs_without_current_manifest(
        tmp_path, manifest_state):
    snapshot = tmp_path / "offline-targets.json"
    snapshot_bytes = json.dumps({
        "vintage_date": "2026-01-01",
        "targets": [{
            "key": "offline.target",
            "value": 7,
            "unit": "index",
            "dimensions": {"scope": "test"},
        }],
    }, sort_keys=True).encode("utf-8")
    snapshot.write_bytes(snapshot_bytes)
    manifest = tmp_path / "offline-manifest.yaml"
    manifest.write_text(json.dumps({
        "manifest_version": 1,
        "datasets": [{
            "key": "offline-replay-v1",
            "source_url": "https://example.invalid/offline-replay-v1",
            "release_date": "2026-01-01",
            "vintage_date": "2026-01-01",
            "retrieval_time": "2026-01-02T00:00:00Z",
            "checksum_sha256": hashlib.sha256(snapshot_bytes).hexdigest(),
            "transform_version": "test-v1",
            "usage_terms": "test fixture",
            "snapshot_path": snapshot.name,
        }],
    }, sort_keys=True), encoding="utf-8")

    source_store, source_world, source_id = open_run(
        _config(tmp_path, dataset_manifest=str(manifest)),
        None, None, data_dir=tmp_path)
    replay_store = None
    replay_world = None
    try:
        assert source_store.scalar("SELECT COUNT(*) FROM dataset_manifests") == 1
        assert source_store.scalar("SELECT COUNT(*) FROM calibration_targets") == 1
        asyncio.run(source_world.run(max_ticks=2))

        if manifest_state == "missing":
            manifest.unlink()
        else:
            manifest.write_text("manifest_version: [", encoding="utf-8")

        replay_store, replay_world, _ = open_run(
            {}, None, source_id, data_dir=tmp_path)
        asyncio.run(replay_headless(replay_world, 2))
        proof = verify_replay(source_store.path, replay_store.path)

        assert proof["exact"], proof["differences"]
        assert proof["differences"] == []
        assert replay_store.scalar("SELECT COUNT(*) FROM dataset_manifests") == 1
        assert replay_store.scalar("SELECT COUNT(*) FROM calibration_targets") == 1
    finally:
        if replay_world is not None:
            replay_world.close()
        source_store.close()


def test_open_run_closes_source_store_when_replay_input_capture_fails(
        tmp_path, monkeypatch):
    source_store, _, source_id = open_run(
        _config(tmp_path), None, None, data_dir=tmp_path)
    source_store.close()
    opened = []

    class TrackingStore(Store):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.was_closed = False
            opened.append(self)

        def close(self):
            self.was_closed = True
            super().close()

    def fail_capture(_source):
        raise RuntimeError("capture failed")

    monkeypatch.setattr(run_module, "Store", TrackingStore)
    monkeypatch.setattr(run_module, "_recorded_replay_inputs", fail_capture)

    with pytest.raises(RuntimeError, match="capture failed"):
        run_module.open_run({}, None, source_id, data_dir=tmp_path)

    assert len(opened) == 1
    assert opened[0].was_closed


def test_replay_compares_llm_provenance_by_logical_call_identity(tmp_path):
    source = Store(str(tmp_path / "provenance-source.db"))
    replay = Store(str(tmp_path / "provenance-replay.db"))
    source.init_run_meta("provenance-source", 42, {})
    replay.init_run_meta("provenance-replay", 42, {})

    def insert_agent(store, agent_id, role):
        store.insert(
            "agents", id=agent_id, name=f"Agent {agent_id}", kind="staff",
            role=role)

    def insert_call(
            store, call_id, agent_id, *, tick=1,
            role="credit_officer", purpose=None):
        purpose = purpose or role
        return store.insert(
            "llm_calls", id=call_id, tick=tick, agent_id=agent_id,
            role=role, provider="minimax", model="MiniMax-M3",
            purpose=purpose, cache_key=f"call-{agent_id}-{tick}-{role}",
            request_json=json.dumps({
                "agent_id": agent_id, "tick": tick, "role": role,
            }, sort_keys=True),
            response_json=json.dumps({
                "text": '{"reasoning":"bounded","actions":[{"type":"do_nothing"}]}',
                "raw": {}, "cached_in_tokens": 0,
            }, sort_keys=True),
            in_tokens=100 + agent_id, out_tokens=20, cached=0,
            cost_usd=0.001, latency_ms=1000 + agent_id,
            created_at="2026-07-14T00:00:00+00:00")

    def insert_action(store, proposal_id, actor_id, model_call_id):
        store.insert(
            "action_proposals", id=proposal_id, tick=1, actor_id=actor_id,
            action_type="do_nothing", payload_json="{}",
            evidence_event_ids_json="[]", model_call_id=model_call_id,
            rationale_summary="bounded", validation_status="accepted",
            result_json='{"ok": true}')

    for store in (source, replay):
        insert_agent(store, 2, "credit_officer")
        insert_agent(store, 3, "judge")

    insert_call(source, 1, 2)
    insert_call(source, 2, 3, role="judge")
    insert_call(source, 3, 2, tick=2)
    insert_call(source, 4, 2, role="lawyer")
    insert_action(source, 1, 2, 1)
    insert_action(source, 2, 3, 2)

    # Replay completion order is reversed, so its correct local surrogate IDs
    # differ even though both proposals retain the same logical provenance.
    insert_call(replay, 1, 3, role="judge")
    insert_call(replay, 2, 2)
    insert_call(replay, 3, 2, tick=2)
    insert_call(replay, 4, 2, role="lawyer")
    insert_action(replay, 1, 2, 2)
    insert_action(replay, 2, 3, 1)
    source.commit()
    replay.commit()

    proof = verify_replay(source.path, replay.path)
    assert proof["exact"], proof["differences"]
    assert proof["source_hash"] == proof["replay_hash"]

    def insert_belief_event(store, source_llm_call_id):
        store.insert(
            "events", id=1, tick=1, phase="EXECUTION", kind="belief_updated",
            subject_type="agent", subject_id=2, importance=0.5,
            payload_json=json.dumps({
                "agent_id": 2, "key": "sentiment", "new_value": 0.5,
                "source": "credit_officer",
                "source_llm_call_id": source_llm_call_id,
            }, sort_keys=True))

    # Nested event provenance is also local to each database and must resolve
    # through the referenced call rather than compare physical IDs.
    insert_belief_event(source, 1)
    insert_belief_event(replay, 2)
    source.commit()
    replay.commit()
    nested = verify_replay(source.path, replay.path)
    assert nested["exact"], nested["differences"]

    replay.execute(
        "UPDATE events SET payload_json=? WHERE id=1",
        (json.dumps({
            "agent_id": 2, "key": "sentiment", "new_value": 0.5,
            "source": "credit_officer", "source_llm_call_id": 1,
        }, sort_keys=True),))
    replay.commit()
    wrong_nested = verify_replay(source.path, replay.path)
    assert not wrong_nested["exact"]
    assert wrong_nested["differences"] == ["events"]

    dangling_payload = json.dumps({
        "agent_id": 2, "key": "sentiment", "new_value": 0.5,
        "source": "credit_officer", "source_llm_call_id": 999,
    }, sort_keys=True)
    source.execute("UPDATE events SET payload_json=? WHERE id=1", (dangling_payload,))
    replay.execute("UPDATE events SET payload_json=? WHERE id=1", (dangling_payload,))
    source.commit()
    replay.commit()
    dangling_nested = verify_replay(source.path, replay.path)
    assert not dangling_nested["exact"]
    assert dangling_nested["differences"] == ["events"]

    # Malformed types must fail closed and remain JSON-safe rather than being
    # coerced to a physical ID or crashing the verifier.
    for malformed in (True, 1.9, float("inf"), float("nan"), "1"):
        source.execute(
            "UPDATE events SET payload_json=? WHERE id=1",
            (json.dumps({
                "agent_id": 2, "key": "sentiment", "new_value": 0.5,
                "source": "credit_officer",
                "source_llm_call_id": malformed,
            }, sort_keys=True),))
        replay.execute(
            "UPDATE events SET payload_json=? WHERE id=1",
            (json.dumps({
                "agent_id": 2, "key": "sentiment", "new_value": 0.5,
                "source": "credit_officer", "source_llm_call_id": 2,
            }, sort_keys=True),))
        source.commit()
        replay.commit()
        malformed_proof = verify_replay(source.path, replay.path)
        assert not malformed_proof["exact"]
        assert malformed_proof["differences"] == ["events"]

    source.execute("UPDATE events SET payload_json=? WHERE id=1", (json.dumps({
        "agent_id": 2, "key": "sentiment", "new_value": 0.5,
        "source": "credit_officer", "source_llm_call_id": 1,
    }, sort_keys=True),))
    replay.execute("UPDATE events SET payload_json=? WHERE id=1", (json.dumps({
        "agent_id": 2, "key": "sentiment", "new_value": 0.5,
        "source": "credit_officer", "source_llm_call_id": 2,
    }, sort_keys=True),))
    source.commit()
    replay.commit()

    replay.execute("UPDATE action_proposals SET model_call_id=1 WHERE id=1")
    replay.commit()
    wrong = verify_replay(source.path, replay.path)
    assert not wrong["exact"]
    assert wrong["differences"] == ["action_proposals"]

    # A wrong-but-local pointer must fail even when source and replay make the
    # same logical mistake. Hash equality alone cannot prove actor provenance.
    source.execute("UPDATE action_proposals SET model_call_id=2 WHERE id=1")
    replay.execute("UPDATE action_proposals SET model_call_id=1 WHERE id=1")
    source.commit()
    replay.commit()
    wrong_actor = verify_replay(source.path, replay.path)
    assert not wrong_actor["exact"]
    assert wrong_actor["differences"] == ["action_proposals"]

    # The same invariant covers a local call from the wrong turn or role.
    for source_call_id, replay_call_id in ((3, 3), (4, 4)):
        source.execute(
            "UPDATE action_proposals SET model_call_id=? WHERE id=1",
            (source_call_id,))
        replay.execute(
            "UPDATE action_proposals SET model_call_id=? WHERE id=1",
            (replay_call_id,))
        source.commit()
        replay.commit()
        wrong_turn_or_role = verify_replay(source.path, replay.path)
        assert not wrong_turn_or_role["exact"]
        assert wrong_turn_or_role["differences"] == ["action_proposals"]

    # Nested belief provenance is actor-bound too, not merely local.
    source.execute("UPDATE action_proposals SET model_call_id=1 WHERE id=1")
    replay.execute("UPDATE action_proposals SET model_call_id=2 WHERE id=1")
    source.execute("UPDATE events SET payload_json=? WHERE id=1", (json.dumps({
        "agent_id": 2, "key": "sentiment", "new_value": 0.5,
        "source": "credit_officer", "source_llm_call_id": 2,
    }, sort_keys=True),))
    replay.execute("UPDATE events SET payload_json=? WHERE id=1", (json.dumps({
        "agent_id": 2, "key": "sentiment", "new_value": 0.5,
        "source": "credit_officer", "source_llm_call_id": 1,
    }, sort_keys=True),))
    source.commit()
    replay.commit()
    wrong_nested_actor = verify_replay(source.path, replay.path)
    assert not wrong_nested_actor["exact"]
    assert wrong_nested_actor["differences"] == ["events"]

    source.execute("UPDATE events SET payload_json=? WHERE id=1", (json.dumps({
        "agent_id": 2, "key": "sentiment", "new_value": 0.5,
        "source": "credit_officer", "source_llm_call_id": 1,
    }, sort_keys=True),))
    replay.execute("UPDATE events SET payload_json=? WHERE id=1", (json.dumps({
        "agent_id": 2, "key": "sentiment", "new_value": 0.5,
        "source": "credit_officer", "source_llm_call_id": 2,
    }, sort_keys=True),))

    # Even identical dangling IDs on both sides must fail closed rather than
    # compare as equivalent provenance.
    source.execute("UPDATE action_proposals SET model_call_id=999 WHERE id=1")
    replay.execute("UPDATE action_proposals SET model_call_id=999 WHERE id=1")
    source.commit()
    replay.commit()
    dangling = verify_replay(source.path, replay.path)
    assert not dangling["exact"]
    assert dangling["differences"] == ["action_proposals"]


def test_replay_canonicalizes_communication_model_provenance(tmp_path):
    source = Store(str(tmp_path / "communication-source.db"))
    replay = Store(str(tmp_path / "communication-replay.db"))
    config = {"engine_semantics_version": 11,
              "llm": {"institutional_role_purposes": True}}
    source.init_run_meta("communication-source", 42, config)
    replay.init_run_meta("communication-replay", 42, config)

    for store, call_id, event_id in ((source, 5, 3), (replay, 9, 1)):
        store.insert(
            "agents", id=2, name="Credit officer", kind="staff",
            role="credit_officer")
        store.insert(
            "llm_calls", id=call_id, tick=1, agent_id=2,
            role="credit_officer", provider="minimax", model="MiniMax-M3",
            purpose="credit_officer", cache_key="communication-call",
            request_json='{"agent_id":2,"tick":1}',
            response_json='{"text":"bounded","raw":{}}',
            in_tokens=10, out_tokens=5, cached=0, cost_usd=0.001,
            latency_ms=100, created_at="2026-07-21T00:00:00+00:00")
        if store is source:
            store.insert(
                "events", id=1, tick=1, phase="MORNING",
                kind="provider_failure", payload_json='{"reason":"transient"}')
            store.insert(
                "events", id=2, tick=1, phase="MORNING",
                kind="provider_pause", payload_json='{"reason":"transient"}')
        store.insert(
            "events", id=event_id, tick=1, phase="EXECUTION",
            kind="communication_queued", payload_json="{}")
        store.insert(
            "comm_threads", id=1, created_tick=1, created_by_agent_id=2,
            subject="Bounded update", status="open", root_event_id=event_id)
        store.insert(
            "comm_messages", id=1, thread_id=1, sender_agent_id=2,
            created_tick=1, deliver_at_tick=2, visibility="participants",
            body_text="Status update", model_call_id=call_id,
            created_event_id=event_id, status="queued")
        action_result = {
            "ok": True, "thread_id": 1, "message_id": 1,
            "created_event_id": event_id,
        }
        store.insert(
            "action_proposals", id=1, tick=1, actor_id=2,
            action_type="send_message", payload_json="{}",
            evidence_event_ids_json="[]", model_call_id=call_id,
            rationale_summary="bounded", validation_status="executed",
            result_json=json.dumps(action_result))
        store.insert(
            "causal_links", id=1, dedupe_key="c" * 64, created_tick=1,
            source_kind="action_proposal", source_id="1", source_tick=1,
            source_order_key="0001", target_kind="event",
            target_id=str(event_id), target_tick=1, target_order_key="0002",
            relation="triggered", authority="engine",
            confidence=1.0,
            provenance_json=json.dumps({
                "action_type": "send_message",
                "action_result": action_result,
            }),
            evidence_json="{}")
        store.insert(
            "agent_decisions", id=1, dedupe_key="d" * 64,
            tick=1, agent_id=2, purpose="credit_officer",
            method="model_call", model_call_id=call_id,
            reasoning_fingerprint="r" * 64)
        store.commit()

    proof = verify_replay(source.path, replay.path)

    assert proof["exact"], proof["differences"]
    assert proof["source_hash"] == proof["replay_hash"]


def test_replay_rejects_same_actor_turn_wrong_llm_purpose(tmp_path):
    source = Store(str(tmp_path / "purpose-source.db"))
    replay = Store(str(tmp_path / "purpose-replay.db"))
    config = {"llm": {"institutional_role_purposes": True}}
    source.init_run_meta("purpose-source", 42, config)
    replay.init_run_meta("purpose-replay", 42, config)

    for store in (source, replay):
        store.insert("agents", id=1, name="Citizen", kind="citizen")
        # NIGHT_CLOSE bankruptcy at tick 1 precedes that tick's MORNING
        # decision. This former founder must therefore route as a citizen.
        store.insert(
            "firms", id=1, name="Closed firm", founder_agent_id=1,
            status="bankrupt", founded_tick=0, bankrupt_tick=1)
        for call_id, purpose in ((1, "decision"), (2, "memory")):
            store.insert(
                "llm_calls", id=call_id, tick=1, agent_id=1,
                role="citizen", provider="minimax", model="MiniMax-M3",
                purpose=purpose, cache_key=f"citizen-{purpose}",
                request_json="{}", response_json='{"text":"bounded","raw":{}}',
                in_tokens=10, out_tokens=5, cached=0, cost_usd=0.001,
                latency_ms=10, created_at="2026-07-14T00:00:00+00:00")
        # The actor, tick, role, and local existence all match. Only purpose
        # proves this is a memory call rather than the decision that acted.
        store.insert(
            "action_proposals", id=1, tick=1, actor_id=1,
            action_type="do_nothing", payload_json="{}",
            evidence_event_ids_json="[]", model_call_id=2,
            rationale_summary="bounded", validation_status="accepted",
            result_json='{"ok":true}')
        store.commit()

    wrong_purpose = verify_replay(source.path, replay.path)
    assert not wrong_purpose["exact"]
    assert wrong_purpose["differences"] == ["action_proposals"]

    source.execute("UPDATE action_proposals SET model_call_id=1 WHERE id=1")
    replay.execute("UPDATE action_proposals SET model_call_id=1 WHERE id=1")
    source.commit()
    replay.commit()
    corrected = verify_replay(source.path, replay.path)
    assert corrected["exact"], corrected["differences"]


def test_replay_validates_legal_model_reference_owners(tmp_path):
    source = Store(str(tmp_path / "legal-provenance-source.db"))
    replay = Store(str(tmp_path / "legal-provenance-replay.db"))
    source.init_run_meta("legal-provenance-source", 42, {})
    replay.init_run_meta("legal-provenance-replay", 42, {})

    def insert_agent(store, agent_id, role):
        store.insert(
            "agents", id=agent_id, name=f"Agent {agent_id}", kind="staff",
            role=role)

    def insert_call(store, call_id, agent_id, role):
        store.insert(
            "llm_calls", id=call_id, tick=1, agent_id=agent_id, role=role,
            provider="minimax", model="MiniMax-M3", purpose=role,
            cache_key=f"legal-{agent_id}", request_json="{}",
            response_json='{"text":"bounded","raw":{}}', in_tokens=10,
            out_tokens=5, cached=0, cost_usd=0.001, latency_ms=10,
            created_at="2026-07-14T00:00:00+00:00")

    def insert_rows(store, lawyer_call_id, judge_call_id):
        store.insert(
            "action_proposals", id=1, tick=1, actor_id=1,
            action_type="submit_filing", payload_json="{}",
            evidence_event_ids_json="[]", model_call_id=lawyer_call_id,
            rationale_summary="bounded filing", validation_status="accepted",
            result_json='{"filing_id":1,"ok":true}')
        store.insert(
            "action_proposals", id=2, tick=1, actor_id=2,
            action_type="issue_legal_decision", payload_json="{}",
            evidence_event_ids_json="[]", model_call_id=judge_call_id,
            rationale_summary="bounded decision", validation_status="accepted",
            result_json='{"decision_id":1,"ok":true}')
        store.insert(
            "legal_filings", id=1, matter_id=1, tick=1,
            filer_type="agent", filer_id=1, filing_type="brief", body="bounded",
            evidence_event_ids_json="[]", admitted=0,
            model_call_id=lawyer_call_id, rationale_summary="bounded filing")
        store.insert(
            "legal_decisions", id=1, matter_id=1, tick=1,
            decision_maker_id=2, outcome="dismissed", findings_json="[]",
            evidence_event_ids_json="[]", remedy_json='{"type":"none"}',
            validation_status="valid", validation_errors_json="[]",
            model_call_id=judge_call_id, rationale_summary="bounded decision")

    for store in (source, replay):
        insert_agent(store, 1, "lawyer")
        insert_agent(store, 2, "judge")
    insert_call(source, 1, 1, "lawyer")
    insert_call(source, 2, 2, "judge")
    insert_rows(source, 1, 2)
    insert_call(replay, 1, 2, "judge")
    insert_call(replay, 2, 1, "lawyer")
    insert_rows(replay, 2, 1)
    source.commit()
    replay.commit()

    reordered = verify_replay(source.path, replay.path)
    assert reordered["exact"], reordered["differences"]

    # Both databases point the filing at the same logical but wrong judge call.
    source.execute("UPDATE legal_filings SET model_call_id=2 WHERE id=1")
    replay.execute("UPDATE legal_filings SET model_call_id=1 WHERE id=1")
    source.commit()
    replay.commit()
    wrong_filer = verify_replay(source.path, replay.path)
    assert not wrong_filer["exact"]
    assert wrong_filer["differences"] == ["legal_filings"]

    source.execute("UPDATE legal_filings SET model_call_id=1 WHERE id=1")
    replay.execute("UPDATE legal_filings SET model_call_id=2 WHERE id=1")
    source.execute("UPDATE legal_decisions SET model_call_id=1 WHERE id=1")
    replay.execute("UPDATE legal_decisions SET model_call_id=2 WHERE id=1")
    source.commit()
    replay.commit()
    wrong_decider = verify_replay(source.path, replay.path)
    assert not wrong_decider["exact"]
    assert wrong_decider["differences"] == ["legal_decisions"]


def test_replay_reports_legacy_missing_llm_table_without_crashing(tmp_path):
    source = Store(str(tmp_path / "legacy-source.db"))
    replay = Store(str(tmp_path / "legacy-replay.db"))
    source.init_run_meta("legacy-source", 42, {})
    replay.init_run_meta("legacy-replay", 42, {})
    source.execute("DROP TABLE llm_calls")
    source.commit()
    replay.commit()

    proof = verify_replay(source.path, replay.path)

    assert not proof["exact"]
    assert proof["differences"] == ["llm_calls"]


def test_served_tick_bound_applies_to_dashboard_run_action(tmp_path):
    world = _world(tmp_path, "served-tick-bound.db")

    with TestClient(create_app(world, served_ticks=3)) as client:
        started = client.post("/api/run/start?max_ticks=1")
        assert started.status_code == 200
        for _ in range(100):
            status = client.get("/api/run/status").json()
            if not status["running"]:
                break
        assert status["tick"] == 1
        assert status["semantics_version"] == world.engine_semantics_version
        assert status["target_tick"] == 3
        assert status["remaining_ticks"] == 2

        stepped = client.post("/api/run/step").json()
        assert stepped["tick"] == 2

        started = client.post("/api/run/start?max_ticks=99")
        assert started.status_code == 200
        for _ in range(100):
            status = client.get("/api/run/status").json()
            if not status["running"]:
                break
        assert status["tick"] == 3
        assert status["status"] == "paused"
        assert status["remaining_ticks"] == 0

        assert client.post("/api/run/start").json()["status"] == "limit_reached"
        assert client.post("/api/run/step").json()["status"] == "limit_reached"
        assert world.store.tick == 3


def test_served_run_broadcasts_authoritative_completion_status(tmp_path):
    world = _world(tmp_path, "served-completion-broadcast.db")
    controller = RunController(world, served_ticks=1)
    messages = []

    async def capture(payload):
        if payload.get("type") == "tick":
            # Model a real WebSocket send that yields before it completes. The
            # terminal run_status must still be delivered after this tick.
            await asyncio.sleep(0.01)
        messages.append(payload)

    async def run_once():
        controller.hub.broadcast = capture
        controller.loop = asyncio.get_running_loop()
        assert (await controller.start())["status"] == "running"
        await controller.task

    asyncio.run(run_once())

    assert messages[-1] == {
        **controller.run_status_payload(running=False),
        "type": "run_status",
    }
    assert messages[-1]["tick"] == messages[-1]["target_tick"] == 1
    assert messages[-1]["remaining_ticks"] == 0
    assert messages[-1]["status"] == "paused"
    assert messages[-1]["running"] is False
    assert any(message.get("type") == "tick" for message in messages[:-1])
    world.store.close()


def test_concurrent_steps_cannot_cross_the_served_tick_bound(tmp_path):
    world = _world(tmp_path, "served-concurrent-step.db")
    controller = RunController(world, served_ticks=1)

    async def yielding_step():
        await asyncio.sleep(0)
        tick = world.store.tick + 1
        world.store.set_meta(tick=tick)
        world.store.commit()
        return {"tick": tick}

    world.step = yielding_step

    async def run_two():
        return await asyncio.gather(controller.step(), controller.step())

    results = asyncio.run(run_two())

    assert world.store.tick == 1
    assert sum(result.get("status") == "limit_reached" for result in results) == 1
    assert controller.remaining_ticks() == 0
    world.store.close()


def test_dashboard_status_reports_an_inflight_step_as_running(tmp_path):
    world = _world(tmp_path, "served-inflight-step-status.db")
    controller = RunController(world, served_ticks=1)

    async def observe_inflight_step():
        entered = asyncio.Event()
        release = asyncio.Event()

        async def yielding_step():
            entered.set()
            await release.wait()
            tick = world.store.tick + 1
            world.store.set_meta(tick=tick)
            world.store.commit()
            return {"tick": tick}

        world.step = yielding_step
        task = asyncio.create_task(controller.step())
        await entered.wait()
        status = controller.status()
        release.set()
        result = await task
        return status, result

    status, result = asyncio.run(observe_inflight_step())

    assert status["status"] == "running"
    assert status["running"] is True
    assert result["tick"] == 1
    world.store.close()


def test_stop_interrupts_before_waiting_for_an_active_step(tmp_path):
    world = _world(tmp_path, "served-stop-interrupt.db")
    controller = RunController(world, served_ticks=1)

    async def contend_with_step():
        await controller._control_lock.acquire()
        try:
            stop_task = asyncio.create_task(controller.stop())
            await asyncio.sleep(0)
            assert world._stop_requested is True
        finally:
            controller._control_lock.release()
        return await stop_task

    stopped = asyncio.run(contend_with_step())

    assert stopped["status"] == "finished"
    assert world.status == "finished"
    world.store.close()


def test_replay_missing_response_pauses_without_calling_a_provider(tmp_path):
    cfg = _config(tmp_path)
    source_store, source_world, source_id = open_run(
        cfg, None, None, data_dir=tmp_path)
    asyncio.run(source_world.run(max_ticks=1))
    source_store.execute("DELETE FROM llm_calls WHERE id=(SELECT MIN(id) FROM llm_calls)")
    source_store.commit()

    replay_store, replay_world, _ = open_run({}, None, source_id, data_dir=tmp_path)

    class MustNotRun:
        async def complete(self, *args, **kwargs):
            raise AssertionError("replay attempted a live provider call")

    replay_world.gateway.adapters["scripted"] = MustNotRun()
    result = asyncio.run(replay_world.step())
    assert result["paused"] == "provider"
    assert replay_store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='provider_pause'") == 1


def test_production_config_inherits_world_and_enforces_minimax_m3():
    cfg = load_config("runs/production.yaml")
    assert cfg["budget"]["cap_usd"] is None
    assert cfg["population"]["size"] == 63
    assert cfg["banks"]["count"] == 2
    assert cfg["llm"]["default_route"] == {
        "provider": "minimax", "model": "MiniMax-M3"}
    assert cfg["llm"]["concurrency"] == 3
    assert cfg["llm"]["providers"]["minimax"]["timeout_s"] == 180
    assert cfg["llm"]["providers"]["minimax"]["request_defaults"] == {
        "reasoning_split": True, "max_completion_tokens": 4096}
    assert cfg["llm"]["routes"]["oracle"] == {
        "provider": "minimax", "model": "MiniMax-M3"}
    assert cfg["llm"]["route_contract"] == {
        "provider": "minimax", "model": "MiniMax-M3"}
    assert set(cfg["llm"]["providers"]) == {"minimax"}
    assert {
        (route["provider"], route["model"])
        for route in [cfg["llm"]["default_route"], *cfg["llm"]["routes"].values()]
    } == {("minimax", "MiniMax-M3")}

    missing = validate_llm_config(cfg, environ={}, raise_on_error=False)
    assert not missing["ready"]
    assert any("MINIMAX_API_KEY" in error for error in missing["errors"])

    ready = validate_llm_config(
        cfg, environ={"MINIMAX_API_KEY": "sk-cp-present"},
        raise_on_error=False)
    assert ready["ready"] and ready["mode"] == "network"
    assert {p["name"] for p in ready["providers"]} == {"minimax"}
    assert ready["route_contract"] == {
        "enforced": True, "provider": "minimax", "model": "MiniMax-M3",
        "scope": "all_gateway_routes",
    }
    assert all("api_key" not in p for p in ready["providers"])

    route_drift = load_config("runs/production.yaml")
    route_drift["llm"]["routes"]["oracle"] = {
        "provider": "scripted", "model": "scripted"}
    mismatch = validate_llm_config(
        route_drift, environ={"MINIMAX_API_KEY": "sk-cp-present"},
        raise_on_error=False)
    assert not mismatch["ready"]
    assert any("violates llm.route_contract" in error for error in mismatch["errors"])

    wrong_minimax_service = load_config("runs/production.yaml")
    wrong_minimax_service["llm"]["providers"]["minimax"]["base_url"] = \
        "https://api.minimaxi.com/v1"
    minimax_mismatch = validate_llm_config(
        wrong_minimax_service,
        environ={"MINIMAX_API_KEY": "sk-cp-present"},
        raise_on_error=False)
    assert not minimax_mismatch["ready"]
    assert any("MiniMax Token Plan key" in error
               for error in minimax_mismatch["errors"])


def test_gateway_retries_once_and_bills_provider_reported_cache_tokens(tmp_path, caplog):
    caplog.set_level(logging.DEBUG, logger="agent_economy.llm")
    cfg = _config(tmp_path)
    cfg["llm"] = {
        "provider_retries": 1,
        "default_route": {"provider": "mock", "model": "metered-test"},
        "routes": {},
        "pricing": {"metered-test": {"in": 1.0, "out": 2.0, "cache": 0.1}},
    }
    store = Store(str(tmp_path / "cache.db"))
    store.init_run_meta("cache", 42, cfg)
    gateway = Gateway(store, cfg)

    class FailOnce:
        def __init__(self):
            self.calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary provider outage")
            return AdapterResult(
                text='{"reasoning":"ok","actions":[{"type":"do_nothing"}]}',
                in_tokens=100, out_tokens=10, cached_in_tokens=80,
                raw={"usage": "provider-reported"})

        async def healthcheck(self, model):
            return {"ok": True, "model": model, "live": True}

    adapter = FailOnce()
    gateway.adapters["mock"] = adapter
    response = asyncio.run(gateway.complete(
        LLMRequest(role="citizen", purpose="decision", system="stable", user="dynamic")))

    assert adapter.calls == 2
    assert response.cached
    assert response.cost_usd == pytest.approx(0.000048)
    row = store.query_one("SELECT * FROM llm_calls ORDER BY id DESC LIMIT 1")
    assert row["cached"] == 1
    assert load_json(row["response_json"], {})["cached_in_tokens"] == 80
    events = [getattr(record, "event_name", "") for record in caplog.records]
    assert "llm.request.retry" in events
    assert "llm.request.completed" in events
    completed = next(record for record in caplog.records
                     if getattr(record, "event_name", "") == "llm.request.completed")
    assert completed.event_fields["attempts"] == 2
    assert completed.event_fields["cached_in_tokens"] == 80


def test_openai_compat_returns_metered_empty_completion_for_contract_repair(monkeypatch):
    import httpx

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": None}, "finish_reason": "length"}],
                "usage": {
                    "prompt_tokens": 120, "completion_tokens": 4096,
                    "prompt_tokens_details": {"cached_tokens": 80},
                },
            }

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    adapter = OpenAICompatAdapter({
        "base_url": "https://provider.invalid/v1", "api_key_env": "TEST_KEY",
    })
    result = asyncio.run(adapter.complete("model", [{"role": "user", "content": "JSON"}]))

    assert result.text == ""
    assert result.in_tokens == 120 and result.out_tokens == 4096
    assert result.cached_in_tokens == 80
    assert result.raw["choices"][0]["finish_reason"] == "length"


def test_provider_failure_pauses_on_a_reconciled_checkpoint(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="agent_economy.llm")
    caplog.set_level(logging.INFO, logger="agent_economy.world")
    world = _world(tmp_path, "provider.db")

    class AlwaysFail:
        async def complete(self, *args, **kwargs):
            raise RuntimeError("synthetic outage")

        async def healthcheck(self, model):
            return {"ok": False, "model": model, "live": True}

    world.gateway.adapters["scripted"] = AlwaysFail()
    summary = asyncio.run(world.step())

    assert summary["paused"] == "provider"
    assert summary["phase"] == "MORNING"
    assert world.status == "paused" and world.store.tick == 0
    assert world.store.active_tick == 1
    assert world.store.next_phase == "MORNING"
    assert world.store.get_meta()["status"] == "paused"
    assert world.store.scalar("SELECT COUNT(*) FROM events WHERE kind='provider_failure'") > 0
    assert world.store.scalar("SELECT COUNT(*) FROM events WHERE kind='provider_pause'") == 1
    events = [getattr(record, "event_name", "") for record in caplog.records]
    assert "llm.request.failed" in events
    assert "world.pause.completed" in events
    checkpoint = world.store.query_one("SELECT path FROM checkpoints ORDER BY id DESC LIMIT 1")
    assert checkpoint and Path(checkpoint["path"]).exists()
    ok, diag = world.economy.ledger.reconcile()
    assert ok, diag


def test_provider_pause_resumes_same_phase_without_duplicate_calls(tmp_path):
    world = _world(tmp_path, "provider-resume.db")
    delegate = world.gateway.adapters["scripted"]

    class FailOnceMidPhase:
        def __init__(self):
            self.calls = 0
            self.failed = False

        async def complete(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 3 and not self.failed:
                self.failed = True
                raise RuntimeError("synthetic mid-phase outage")
            return await delegate.complete(*args, **kwargs)

        async def healthcheck(self, model):
            return {"ok": True, "model": model, "live": False}

    adapter = FailOnceMidPhase()
    world.gateway.adapters["scripted"] = adapter
    paused = asyncio.run(world.step())

    assert paused["paused"] == "provider"
    assert world.store.tick == 0
    assert world.store.active_tick == 1
    assert world.store.next_phase == "MORNING"
    calls_before_resume = world.store.scalar("SELECT COUNT(*) FROM llm_calls")
    assert calls_before_resume > 0

    world._pause_requested = False
    resumed = asyncio.run(world.step())

    assert resumed["tick"] == 1
    assert world.store.tick == 1
    assert world.store.active_tick is None
    assert world.store.next_phase == "NIGHT_CLOSE"
    assert world.store.scalar(
        "SELECT COUNT(*) FROM llm_calls") == world.store.scalar(
            "SELECT COUNT(DISTINCT cache_key) FROM llm_calls")
    assert world.store.scalar(
        "SELECT COUNT(*) FROM metrics WHERE tick=1 AND name='cpi'") == 1
    assert world.store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='provider_pause'") == 1


def test_oracle_read_tools_are_bounded_and_prediction_keeps_evidence(tmp_path):
    world = _world(tmp_path, "oracle-tools.db")
    asyncio.run(world.step())
    tools = world.oracle.tools
    changes_before_reads = world.store.conn.total_changes

    metrics = tools.query_metrics(
        ["cpi", "unemployment"], from_tick=0, to_tick=1, limit=20)
    assert metrics["cpi"] and metrics["unemployment"]
    assert tools.inspect_agent(1)["agent"]["id"] == 1
    ledger_agent = int(world.store.scalar(
        "SELECT owner_id FROM accounts WHERE owner_type='agent' "
        "AND owner_id IS NOT NULL ORDER BY owner_id LIMIT 1"))
    assert tools.get_ledger_summary("agent", ledger_agent)["accounts"]
    assert isinstance(tools.read_news(from_tick=0, to_tick=1, limit=5), list)
    assert isinstance(tools.sample_conversations(
        from_tick=0, to_tick=1, limit=5), list)
    assert isinstance(tools.read_order_book(depth=5), list)
    assert world.store.conn.total_changes == changes_before_reads

    with pytest.raises(OracleToolError):
        tools.execute_plan([{"tool": "execute_sql", "args": {
            "sql": "DELETE FROM accounts"}}])
    with pytest.raises(OracleToolError, match="invalid arguments"):
        tools.execute_plan([{"tool": "get_ledger_summary", "args": {
            "entity_type": "bank", "entity_id": 1,
            "available_bank_ids": [1, 2],
        }}])
    with pytest.raises(OracleToolError):
        tools.read_order_book(depth=21)
    with pytest.raises(OracleToolError):
        tools.execute_plan([
            {"tool": "read_news", "args": {"limit": 1}}
            for _ in range(9)])
    legacy = tools.execute_plan_legacy([{
        "tool": "read_news",
        "args": {"from_tick": 0, "to_tick": 1, "limit": "2"},
    }])
    assert len(legacy) == 1
    with pytest.raises(OracleToolError):
        tools.execute_plan([{
            "tool": "read_news",
            "args": {"from_tick": 0, "to_tick": 1, "limit": "2"},
        }])

    answer = asyncio.run(world.oracle.ask(
        "What is the probability of a bank run within 30 ticks?"))
    assert answer["prediction_id"]
    assert answer["evidence"]
    prediction = world.store.query_one(
        "SELECT * FROM predictions WHERE id=?", (answer["prediction_id"],))
    evidence = load_json(prediction["evidence_json"], [])
    assert {item["tool"] for item in evidence} >= {
        "query_metrics", "read_news", "sample_conversations",
        "get_ledger_summary"}
    assert world.store.scalar(
        "SELECT COUNT(*) FROM llm_calls WHERE purpose='oracle_plan'") == 1
    assert world.store.scalar(
        "SELECT COUNT(*) FROM llm_calls WHERE purpose='oracle'") == 1
    with TestClient(create_app(world)) as client:
        payload = client.get("/api/oracle/predictions").json()
    assert payload["predictions"][0]["evidence"] == evidence


def test_oracle_repairs_a_rejected_plan_before_answering(tmp_path):
    world = _world(tmp_path, "oracle-plan-repair.db")
    asyncio.run(world.step())

    class RepairingGateway:
        replay = False
        replay_conn = None

        def __init__(self):
            self.requests = []

        async def complete(self, req, **_kwargs):
            self.requests.append(req)
            plans = [r for r in self.requests if r.purpose == "oracle_plan"]
            if req.purpose == "oracle_plan" and len(plans) == 1:
                return SimpleNamespace(parsed={"queries": [{
                    "tool": "query_metrics", "args": {
                        "names": ["gdp_proxy"], "from_tick": -1,
                        "to_tick": world.store.tick, "limit": 10,
                    },
                }]})
            if req.purpose == "oracle_plan":
                assert req.context["previous_plan_error"] == "invalid tick range"
                return SimpleNamespace(parsed={"queries": [{
                    "tool": "query_metrics", "args": {
                        "names": ["gdp_proxy"], "from_tick": 0,
                        "to_tick": world.store.tick, "limit": 10,
                    },
                }]})
            return SimpleNamespace(parsed={
                "p": 0.25, "drivers": ["stable output"], "confidence": "med",
                "resolution_rule": {"type": "bank_failure"},
                "deadline_tick": world.store.tick + 30,
                "reasoning": "bounded evidence",
            })

    gateway = RepairingGateway()
    world.oracle.gw = gateway
    answer = asyncio.run(world.oracle.ask("Will a bank fail within 30 ticks?"))

    assert [req.purpose for req in gateway.requests] == [
        "oracle_plan", "oracle_plan", "oracle"]
    assert answer["evidence"][0]["tool"] == "query_metrics"
    assert world.store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='oracle_tool_plan_rejected'") == 1


def test_oracle_can_repair_a_schema_error_then_an_unknown_entity(tmp_path):
    world = _world(tmp_path, "oracle-second-repair.db")
    asyncio.run(world.step())
    bank_ids = [int(row["id"]) for row in world.store.query(
        "SELECT id FROM banks ORDER BY id")]

    class TwiceRepairingGateway:
        replay = False
        replay_conn = None

        def __init__(self):
            self.requests = []

        async def complete(self, req, **_kwargs):
            self.requests.append(req)
            plans = [r for r in self.requests if r.purpose == "oracle_plan"]
            if req.purpose == "oracle_plan" and len(plans) == 1:
                assert req.context["available_tools"][4][
                    "available_entity_ids"]["bank"] == bank_ids
                return SimpleNamespace(parsed={"queries": [{
                    "tool": "get_ledger_summary",
                    "args": {"entity_type": "bank", "entity_id": None},
                }]})
            if req.purpose == "oracle_plan" and len(plans) == 2:
                assert req.context["previous_plan_error"] == "entity_id is required"
                return SimpleNamespace(parsed={"queries": [{
                    "tool": "get_ledger_summary",
                    "args": {"entity_type": "bank", "entity_id": 99999},
                }]})
            if req.purpose == "oracle_plan":
                assert req.context["previous_plan_error"] == (
                    "entity ledger accounts not found")
                return SimpleNamespace(parsed={"queries": [{
                    "tool": "get_ledger_summary",
                    "args": {"entity_type": "bank", "entity_id": bank_ids[0]},
                }]})
            return SimpleNamespace(parsed={
                "p": 0.2, "drivers": ["stable deposits"], "confidence": "med",
                "resolution_rule": {"type": "bank_failure"},
                "deadline_tick": world.store.tick + 30,
                "reasoning": "bounded evidence",
            })

    gateway = TwiceRepairingGateway()
    world.oracle.gw = gateway
    answer = asyncio.run(world.oracle.ask("Will a bank fail within 30 ticks?"))

    assert [req.purpose for req in gateway.requests] == [
        "oracle_plan", "oracle_plan", "oracle_plan", "oracle"]
    assert answer["evidence"][0]["result"]["entity_id"] == bank_ids[0]
    assert world.store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='oracle_tool_plan_rejected'") == 2


def test_replay_falls_back_to_recorded_semantic_call_identity(tmp_path):
    config = _config(tmp_path)
    source_path = tmp_path / "compat-source.db"
    source = Store(str(source_path))
    source.init_run_meta("compat-source", config["seed"], config)
    source_gateway = Gateway(source, config)
    old_request = LLMRequest(
        role="citizen", purpose="decision", system="old prompt",
        user="old context", agent_id=1, tick=0)
    asyncio.run(source_gateway.complete(old_request))
    original = source.query_one("SELECT * FROM llm_calls")
    source.close()

    replay_config = {
        **config, "replay": True,
        "replay_source_path": str(source_path),
    }
    replay = Store(str(tmp_path / "compat-replay.db"))
    replay.init_run_meta("compat-replay", config["seed"], replay_config)
    replay_gateway = Gateway(replay, replay_config)
    changed_request = LLMRequest(
        role="citizen", purpose="decision", system="improved prompt",
        user="new context", agent_id=1, tick=0)
    response = asyncio.run(replay_gateway.complete(changed_request))
    copied = replay.query_one("SELECT * FROM llm_calls")

    assert response.text
    assert copied["cache_key"] == original["cache_key"]
    assert copied["request_json"] == original["request_json"]
    assert replay.scalar("SELECT COUNT(*) FROM llm_calls") == 1


def test_exact_replay_reasks_recorded_oracle_predictions(tmp_path):
    config = _config(tmp_path)
    source_store, source_world, source_id = open_run(
        config, None, None, data_dir=tmp_path)
    asyncio.run(source_world.run(max_ticks=1))
    asyncio.run(source_world.oracle.ask("Will a bank fail within 30 ticks?"))
    asyncio.run(source_world.run(max_ticks=2))
    source_tick = source_store.tick
    source_store.close()

    replay_store, replay_world, _ = open_run(
        config, None, source_id, data_dir=tmp_path)
    asyncio.run(replay_headless(replay_world, source_tick))
    proof = verify_replay(tmp_path / f"{source_id}.db", replay_store.path)

    assert replay_store.scalar("SELECT COUNT(*) FROM predictions") == 1
    assert proof["exact"], proof["differences"]


def test_active_reconciliation_failure_halts_and_checkpoints(tmp_path):
    world = _world(tmp_path, "halt.db")
    account = world.store.query_one("SELECT id FROM accounts ORDER BY id LIMIT 1")
    world.store.execute(
        "UPDATE accounts SET balance_cents=balance_cents+1 WHERE id=?", (int(account["id"]),))

    with pytest.raises(ReconciliationError):
        asyncio.run(world.step())

    assert world.status == "halted"
    assert world.store.get_meta()["status"] == "halted"
    assert world.store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='reconciliation_failure'") == 1
    assert list(tmp_path.glob("halt.halt_t1.json"))
    assert world.store.active_tick == 1
    assert world.store.scalar("SELECT COUNT(*) FROM checkpoints WHERE tick=0") == 1


def test_interactive_stop_generates_complete_standalone_report(tmp_path):
    world = _world(tmp_path, "report.db")
    app = create_app(world)
    with TestClient(app) as client:
        response = client.post("/api/run/stop")
        assert response.status_code == 200
        body = response.json()

    assert body["status"] == "finished"
    html_path = Path(body["report_path"])
    md_path = html_path.with_suffix(".md")
    assert html_path.exists() and md_path.exists()
    html = html_path.read_text(encoding="utf-8")
    markdown = md_path.read_text(encoding="utf-8")
    for section in ("Narrative", "Timeline of key events", "Metrics", "Oracle scorecard",
                    "Cost summary", "Reproduction"):
        assert section in html
    for section in ("Reviewer companion", "Metric snapshot", "Oracle", "Cost",
                    "Reproduction", f"Seed: `{world.store.get_meta()['seed']}`"):
        assert section in markdown
    assert world.store.scalar("SELECT COUNT(*) FROM events WHERE kind='report_generated'") == 1


def test_running_world_stop_finishes_with_report(tmp_path):
    world = _world(tmp_path, "running-stop.db", speed_delay_s=0.01)

    async def stop_after_first_tick():
        task = asyncio.create_task(world.run())
        while world.store.tick < 1:
            await asyncio.sleep(0.002)
        world.request_stop()
        await task

    asyncio.run(stop_after_first_tick())
    assert world.status == "finished"
    assert world.last_report_path and Path(world.last_report_path).exists()
    assert world.store.get_meta()["status"] == "finished"
    assert world.store.scalar("SELECT COUNT(*) FROM events WHERE kind='report_generated'") == 1


def test_controller_reopens_reported_run_and_rejects_halted_mutations(tmp_path):
    world = _world(tmp_path, "controller-transitions.db")
    app = create_app(world)
    with TestClient(app) as client:
        speed = client.post("/api/run/speed", json={"delay_s": 1.0})
        assert speed.status_code == 200
        assert client.get("/api/run/status").json()["speed_delay_s"] == 1.0

        stopped = client.post("/api/run/stop")
        assert stopped.status_code == 200
        report_path = stopped.json()["report_path"]
        tick = world.store.tick

        stepped = client.post("/api/run/step")
        assert stepped.status_code == 200
        assert world.store.tick == tick + 1
        assert world.status == "paused"
        assert world.last_report_path is None
        assert report_path

        world.status = "halted"
        world.store.set_meta(status="halted")
        world.store.commit()
        mutations = (
            client.post("/api/run/start"),
            client.post("/api/run/step"),
            client.post("/api/run/pause"),
            client.post("/api/run/stop"),
            client.post("/api/run/speed", json={"delay_s": 0.0}),
            client.post("/api/shocks", json={
                "kind": "oil", "trigger_type": "shock",
                "params": {"multiplier": 2.0},
            }),
        )
        assert all(response.status_code == 409 for response in mutations)


def test_weekly_memory_is_synthesized_before_daily_sources_are_demoted(tmp_path):
    store = Store(str(tmp_path / "memory.db"))
    store.init_run_meta("memory", 42, {})
    memory = Memory(store)
    for tick in range(1, 8):
        memory.write_summary(1, tick, f"day {tick}", importance=float(tick))
    memory.weekly_rollup(1, 7, "week one synthesis", importance=8.0)

    weekly = store.query_one(
        "SELECT * FROM memories WHERE agent_id=1 AND kind='weekly_summary'")
    assert weekly["text"] == "week one synthesis" and weekly["demoted"] == 0
    assert store.scalar(
        "SELECT COUNT(*) FROM memories WHERE agent_id=1 AND kind='summary' AND demoted=1") == 7


def test_two_year_lifecycle_run_settles_death_and_integrates_arrival(tmp_path):
    world = _world(
        tmp_path, "two-years.db",
        population={"size": 4},
        behavior={"act_every": 1000, "run_threshold": 0.35},
        lifecycle={"critical_death_per_tick": 1.0,
                   "critical_recovery_per_tick": 0.0,
                   "housing_cost_cents": 75_000,
                   "population_mode": "stable"},
        outlets=[{"id": 1, "name": "A", "slant": "neutral"}],
    )
    doomed = world.store.query_one(
        "SELECT id FROM agents WHERE kind='citizen' AND alive=1 ORDER BY id LIMIT 1")
    world.store.update("agents", int(doomed["id"]), health="critical")
    world.economy.lifecycle.schedule_arrival(0, 1)
    firm_id = int(world.store.scalar(
        "SELECT id FROM firms WHERE status<>'bankrupt' ORDER BY id LIMIT 1"))
    for idx in range(12):
        world.economy.labor.post_job(0, firm_id, f"arrival opening {idx}", 120_000 + idx)
    world.store.commit()

    async def run_two_years():
        for _ in range(730):
            result = await world.step()
            assert not result.get("paused"), result

    asyncio.run(run_two_years())

    assert world.store.scalar("SELECT COUNT(*) FROM events WHERE kind='death'") >= 1
    arrival = world.store.query_one(
        "SELECT subject_id AS agent_id, tick FROM events WHERE kind='arrival' ORDER BY id LIMIT 1")
    assert arrival is not None
    arrival_id, arrival_tick = int(arrival["agent_id"]), int(arrival["tick"])
    housing = world.store.query_one(
        "SELECT tick, payload_json FROM events WHERE kind='housing_cost' AND subject_id=?",
        (arrival_id,))
    assert housing and int(housing["tick"]) - arrival_tick <= 10
    application = world.store.query_one(
        "SELECT tick FROM applications WHERE agent_id=? ORDER BY id LIMIT 1", (arrival_id,))
    assert application and int(application["tick"]) - arrival_tick <= 10
    ok, diag = world.economy.ledger.reconcile()
    assert ok, diag


def test_websocket_and_http_paths_emit_operational_logs(tmp_path, caplog):
    caplog.set_level(logging.DEBUG, logger="agent_economy.server")
    world = _world(tmp_path, "ws.db")
    app = create_app(world)
    assert isinstance(app.state.run_controller, RunController)
    assert app.state.run_controller.world is world
    assert world.on_tick == app.state.run_controller.on_tick
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            initial = ws.receive_json()
            assert initial["tick"] == 0
            response = client.post("/api/run/step")
            assert response.status_code == 200
            assert client.get("/api/run/status").json()["status"] == "paused"
            payload = ws.receive_json()
            assert payload["tick"] == 1
            assert int(time.time() * 1000) - payload["emitted_at_ms"] < 2_000
        rejected = client.post("/api/shocks", json={"kind": "not-a-shock"})
        assert rejected.status_code == 400
        rejected_trigger = client.post("/api/shocks", json={
            "kind": "oil", "trigger_type": "invalid-trigger"})
        assert rejected_trigger.status_code == 400
        rejected_duration = client.post("/api/shocks", json={
            "kind": "oil", "duration_ticks": -1})
        assert rejected_duration.status_code == 400

    events = [getattr(record, "event_name", "") for record in caplog.records]
    assert "server.started" in events and "server.stopped" in events
    assert "websocket.connected" in events and "websocket.disconnected" in events
    assert "run.step.completed" in events
    assert "shock.rejected" in events
    started = [record for record in caplog.records
               if getattr(record, "event_name", "") == "http.request.started"]
    assert any(record.event_fields == {"method": "POST", "path": "/api/run/step"}
               for record in started)
    assert any(record.event_fields == {"method": "POST", "path": "/api/shocks"}
               for record in started)
    completed = [record for record in caplog.records
                 if getattr(record, "event_name", "") == "http.request.completed"]
    assert any(record.event_fields["path"] == "/api/run/step"
               and record.event_fields["status_code"] == 200 for record in completed)
    assert any(record.event_fields["path"] == "/api/shocks"
               and record.event_fields["status_code"] == 400 for record in completed)
    assert next(record for record in completed
                if record.event_fields["path"] == "/api/run/status").levelno == logging.DEBUG
    assert next(record for record in completed
                if record.event_fields["path"] == "/api/run/step").levelno == logging.INFO


def test_react_dashboard_bundle_is_local_and_current():
    package = json.loads(Path("dashboard/package.json").read_text(encoding="utf-8"))
    assert {"react", "react-dom", "recharts"} <= package["dependencies"].keys()
    assert {"vite", "tailwindcss", "@tailwindcss/vite"} <= package["devDependencies"].keys()

    html = Path("server/static/index.html").read_text(encoding="utf-8")
    assert 'id="root"' in html
    assert 'src="/static/assets/' in html
    assert 'href="/static/assets/' in html
    assert "https://" not in html and "http://" not in html
    for relative in set(part.split('"')[0] for part in html.split("/static/")[1:]):
        assert (Path("server/static") / relative).is_file(), relative


def test_world_os_deep_links_serve_spa_entrypoint(tmp_path):
    world = _world(tmp_path, "world-os-deep-links.db")

    with TestClient(create_app(world)) as client:
        for path in (
            "/runs/run-demo/overview",
            "/runs/run-demo/news-communications/thread-1?tick=2",
            "/commons/overview",
        ):
            response = client.get(path)
            assert response.status_code == 200, path
            assert response.headers["content-type"].startswith("text/html")
            assert 'id="root"' in response.text


def test_local_mode_probe_reports_non_hosted_v2_api(tmp_path):
    world = _world(tmp_path, "local-mode-probe.db")

    with TestClient(create_app(world)) as client:
        response = client.get("/api/v2/mode")

    assert response.status_code == 200
    assert response.json() == {
        "mode": "local",
        "hosted": False,
        "api_base": "/api/v2",
    }


def test_each_required_shock_has_a_logged_downstream_effect(tmp_path):
    async def fire(kind: str, params: dict, name: str) -> World:
        world = _world(tmp_path, name)
        world.shocks.schedule(kind, "shock", {"tick": 1}, params=params,
                              duration_ticks=3 if kind == "slant" else 0)
        await world.step()
        assert world.store.scalar(
            "SELECT COUNT(*) FROM events WHERE kind='shock_fired'") == 1
        return world

    policy = asyncio.run(fire("policy_rate", {"rate_bps": 875}, "policy.db"))
    assert policy.economy.policy_rate_bps() == 875

    oil = asyncio.run(fire("oil", {"multiplier": 1.8}, "oil.db"))
    assert oil.economy.firms.commodity_index() == pytest.approx(1.8)

    rumor = asyncio.run(fire("rumor", {"bank_id": 1, "n_agents": 6}, "rumor-shock.db"))
    rumor_event = rumor.store.query_one(
        "SELECT payload_json FROM events WHERE kind='rumor' ORDER BY id DESC LIMIT 1")
    targets = load_json(rumor_event["payload_json"], {})["target_agent_ids"]
    assert len(targets) == 6
    assert rumor.store.scalar(
        "SELECT COUNT(*) FROM memories WHERE tick=1 AND importance>=4") >= 6

    slant = asyncio.run(fire(
        "slant", {"outlet_id": 1, "directive": "Frame as alarming"}, "slant.db"))
    slanted = slant.store.query_one(
        "SELECT slant_tags FROM news_articles WHERE outlet_id=1 ORDER BY id DESC LIMIT 1")
    assert slanted and "directed" in load_json(slanted["slant_tags"], [])

    scandal = asyncio.run(fire(
        "scandal", {"firm_id": 1, "description": "Accounting investigation"}, "scandal.db"))
    assert scandal.store.scalar("SELECT COUNT(*) FROM news_articles WHERE tick=1") > 0


def test_company_lifecycle_runs_lawyer_to_revenue_to_bankruptcy(tmp_path):
    world = _world(tmp_path, "company.db")
    executor = world.runtime.executor
    citizens = world.store.query(
        "SELECT id FROM agents WHERE kind='citizen' AND alive=1 ORDER BY id LIMIT 4")
    founder, lawyer, worker, buyer = (int(row["id"]) for row in citizens)
    world.store.update("agents", lawyer, occupation="lawyer")

    founded = executor.execute_action(1, founder, {
        "type": "found_company", "lawyer_agent_id": lawyer,
        "name": "Acceptance Works", "sector": "manufacturing",
        "opening_capital": 100_000,
        "product": {"product": "widgets", "unit_price_cents": 2_000,
                    "base_input_cost_cents": 500, "output_per_worker": 5},
    })
    assert founded["ok"]
    firm_id = int(founded["firm_id"])

    applied = executor.execute_action(2, founder, {
        "type": "apply_loan", "bank_id": 1, "amount": 300_000,
        "purpose": "working capital", "as_firm": True, "firm_id": firm_id,
    })
    assert applied["ok"]
    officer = int(world.store.scalar(
        "SELECT id FROM agents WHERE role='credit_officer' ORDER BY id LIMIT 1"))
    approved = executor.execute_action(3, officer, {
        "type": "approve_loan", "application_id": applied["application_id"],
        "rate_bps": 900, "term_ticks": 360,
    })
    assert approved["ok"]

    posted = executor.execute_action(4, founder, {
        "type": "post_job", "firm_id": firm_id, "title": "widget maker",
        "wage": 90_000,
    })
    assert posted["ok"]
    job_id = int(posted["job_id"])
    application = executor.execute_action(
        5, worker, {"type": "apply_job", "job_id": job_id})
    assert application["ok"]
    hired = executor.execute_action(
        6, founder, {"type": "hire", "application_id": application["application_id"]})
    assert hired["ok"]

    world.economy.firms.produce(7)
    sale = executor.execute_action(
        8, buyer, {"type": "buy_goods", "firm_id": firm_id, "qty": 2})
    assert sale["ok"] and sale["total_cents"] > 0
    assert world.store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='goods_sale'", default=0) >= 1

    world.economy.firms.bankrupt_firm(9, firm_id, reason="acceptance lifecycle")
    firm = world.store.query_one("SELECT status FROM firms WHERE id=?", (firm_id,))
    assert firm["status"] == "bankrupt"
    assert world.store.scalar(
        "SELECT COUNT(*) FROM employments WHERE firm_id=? AND status='active'",
        (firm_id,), default=0) == 0
    for kind in ("company_founded", "loan_application", "loan_originated", "hired",
                 "goods_sale", "bankruptcy"):
        assert world.store.scalar(
            "SELECT COUNT(*) FROM events WHERE kind=?", (kind,), default=0) >= 1, kind
    ok, diag = world.economy.ledger.reconcile()
    assert ok, diag

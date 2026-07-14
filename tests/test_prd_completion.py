"""Executable acceptance evidence for the remaining PRD-v1 completion gates."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

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
        assert not executor.execute_action(1, actor_id, {
            "type": "apply_job", "job_id": foreign_job,
        })["ok"]
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
        assert executor.execute_action(1, actor_id, {
            "type": "apply_job", "job_id": local_job,
        })["ok"]
        assert executor.execute_action(1, actor_id, {
            "type": "apply_loan", "bank_id": local_bank, "amount": 100,
            "purpose": "local currency",
        })["ok"]

        bypassed = world.economy.labor.apply_job(1, actor_id, foreign_job)
        assert bypassed is not None
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
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    config["llm"]["local_currency_action_surfaces"] = False
    store, world, _ = open_run(config, None, None, data_dir=tmp_path)
    try:
        actor = store.query_one(
            "SELECT a.* FROM agents a JOIN accounts ac ON ac.id=a.checking_account_id "
            "WHERE a.kind='citizen' AND a.alive=1 AND a.region_id IS NOT NULL "
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
            "AND ac.bank_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM loans l WHERE l.borrower_type='agent' "
            "AND l.borrower_id=a.id AND l.status='active') "
            "AND NOT EXISTS (SELECT 1 FROM loan_applications p WHERE p.borrower_type='agent' "
            "AND p.borrower_id=a.id AND p.status='pending') ORDER BY a.id LIMIT 1")
        actor_id = int(actor["id"])
        origin_region_id = int(actor["region_id"])
        destination_region_id = int(store.scalar(
            "SELECT id FROM regions WHERE id<>? ORDER BY id LIMIT 1", (origin_region_id,)))
        bank_id = int(store.scalar(
            "SELECT bank_id FROM accounts WHERE id=?", (int(actor["checking_account_id"]),)))

        pending_id = store.insert(
            "loan_applications", tick=1, bank_id=bank_id, borrower_type="agent",
            borrower_id=actor_id, amount_cents=100, purpose="pending", status="pending")
        rejected = world.economy.regions.request_migration(
            1, actor_id, destination_region_id, "pending credit")
        assert not rejected["ok"] and "pending loan application" in rejected["reason"]
        store.update("loan_applications", pending_id, status="denied", decided_tick=1)

        loan_id = store.insert(
            "loans", bank_id=bank_id, borrower_type="agent", borrower_id=actor_id,
            principal_cents=100, outstanding_cents=100, rate_bps=0, term_ticks=30,
            origin_tick=1, payment_cents=100, payment_interval_ticks=30,
            next_due_tick=31, missed_payments=0, collateral_json="{}", status="active")
        rejected = world.economy.regions.request_migration(
            1, actor_id, destination_region_id, "active debt")
        assert not rejected["ok"] and "active loan debt" in rejected["reason"]
        store.update("loans", loan_id, status="paid", outstanding_cents=0)

        requested = world.economy.regions.request_migration(
            1, actor_id, destination_region_id, "clear at request time")
        assert requested["ok"]
        assert not world.runtime.executor.execute_action(1, actor_id, {
            "type": "apply_loan", "bank_id": bank_id, "amount": 100,
            "purpose": "while migrating",
        })["ok"]

        raced_application_id = store.insert(
            "loan_applications", tick=1, bank_id=bank_id, borrower_type="agent",
            borrower_id=actor_id, amount_cents=100, purpose="simulated race", status="pending")
        officer_id = int(store.scalar(
            "SELECT id FROM agents WHERE role='credit_officer' AND alive=1 ORDER BY id LIMIT 1"))
        assert not world.runtime.executor.execute_action(1, officer_id, {
            "type": "approve_loan", "application_id": raced_application_id,
            "rate_bps": 500, "term_ticks": 30,
        })["ok"]

        world.economy.regions.run_nightly(1)
        migration = store.query_one(
            "SELECT status,completed_tick FROM migrations WHERE id=?",
            (requested["migration_id"],))
        assert migration["status"] == "rejected" and int(migration["completed_tick"]) == 1
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
    replay_store.close()


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


def test_replay_compares_llm_provenance_by_logical_call_identity(tmp_path):
    source = Store(str(tmp_path / "provenance-source.db"))
    replay = Store(str(tmp_path / "provenance-replay.db"))
    source.init_run_meta("provenance-source", 42, {})
    replay.init_run_meta("provenance-replay", 42, {})

    def insert_call(store, call_id, agent_id):
        return store.insert(
            "llm_calls", id=call_id, tick=1, agent_id=agent_id,
            role="credit_officer", provider="minimax", model="MiniMax-M3",
            purpose="credit_officer", cache_key=f"call-{agent_id}",
            request_json=json.dumps({"agent_id": agent_id}, sort_keys=True),
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

    insert_call(source, 1, 2)
    insert_call(source, 2, 3)
    insert_action(source, 1, 2, 1)
    insert_action(source, 2, 3, 2)

    # Replay completion order is reversed, so its correct local surrogate IDs
    # differ even though both proposals retain the same logical provenance.
    insert_call(replay, 1, 3)
    insert_call(replay, 2, 2)
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

    # Even identical dangling IDs on both sides must fail closed rather than
    # compare as equivalent provenance.
    source.execute("UPDATE action_proposals SET model_call_id=999 WHERE id=1")
    replay.execute("UPDATE action_proposals SET model_call_id=999 WHERE id=1")
    source.commit()
    replay.commit()
    dangling = verify_replay(source.path, replay.path)
    assert not dangling["exact"]
    assert dangling["differences"] == ["action_proposals"]


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


def test_production_config_inherits_world_and_requires_both_keys():
    cfg = load_config("runs/production.yaml")
    assert cfg["budget"]["cap_usd"] is None
    assert cfg["population"]["size"] == 87
    assert cfg["banks"]["count"] == 2
    assert cfg["llm"]["default_route"] == {
        "provider": "minimax", "model": "MiniMax-M3"}
    assert cfg["llm"]["concurrency"] == 3
    assert cfg["llm"]["providers"]["minimax"]["timeout_s"] == 180
    assert cfg["llm"]["providers"]["minimax"]["request_defaults"] == {
        "reasoning_split": True, "max_completion_tokens": 4096}
    assert cfg["llm"]["routes"]["oracle"] == {
        "provider": "kimi", "model": "kimi-for-coding"}
    kimi = cfg["llm"]["providers"]["kimi"]
    assert kimi["base_url"] == "https://api.kimi.com/coding/v1"
    assert kimi["timeout_s"] == 180
    assert kimi["max_tokens_field"] == "max_tokens"
    assert kimi["request_defaults"] == {
        "reasoning_effort": "medium", "temperature": 1.0,
        "max_tokens": 4096}

    missing = validate_llm_config(cfg, environ={}, raise_on_error=False)
    assert not missing["ready"]
    assert any("MINIMAX_API_KEY" in error for error in missing["errors"])
    assert any("KIMI_API_KEY" in error for error in missing["errors"])

    ready = validate_llm_config(
        cfg, environ={"MINIMAX_API_KEY": "sk-cp-present",
                      "KIMI_API_KEY": "sk-kimi-present"},
        raise_on_error=False)
    assert ready["ready"] and ready["mode"] == "network"
    assert {p["name"] for p in ready["providers"]} == {"minimax", "kimi"}
    assert all("api_key" not in p for p in ready["providers"])

    wrong_service = load_config("runs/production.yaml")
    wrong_service["llm"]["providers"]["kimi"]["base_url"] = \
        "https://api.moonshot.ai/v1"
    mismatch = validate_llm_config(
        wrong_service,
        environ={"MINIMAX_API_KEY": "sk-cp-present",
                 "KIMI_API_KEY": "sk-kimi-present"},
        raise_on_error=False)
    assert not mismatch["ready"]
    assert any("Kimi Code key" in error for error in mismatch["errors"])

    wrong_minimax_service = load_config("runs/production.yaml")
    wrong_minimax_service["llm"]["providers"]["minimax"]["base_url"] = \
        "https://api.minimaxi.com/v1"
    minimax_mismatch = validate_llm_config(
        wrong_minimax_service,
        environ={"MINIMAX_API_KEY": "sk-cp-present",
                 "KIMI_API_KEY": "sk-kimi-present"},
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

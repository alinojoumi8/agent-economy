from __future__ import annotations

import asyncio
import json

import pytest

from llm.readiness import validate_llm_config
from run import open_run, replay_headless
from run_config import load_config
from world.replay_verify import verify_replay
from world.spec_closure_fixture import (
    SpecClosureFixtureError,
    SpecClosureFixtureSeeder,
)


TARGET_ACTIONS = {
    "withdraw_savings", "create_trade_shipment", "request_migration",
}


def _open_rehearsal(tmp_path):
    config = load_config("runs/v2-spec-closure-rehearsal.yaml")
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    store, world, run_id = open_run(config, None, None, data_dir=tmp_path / "runs")
    # This explicit call keeps the focused test usable before and after the
    # World.initialize integration hook lands; the seeder is idempotent.
    payload = SpecClosureFixtureSeeder(world.economy, config).seed()
    return config, store, world, run_id, payload


def test_closure_profiles_are_bounded_and_have_no_local_provider_dependency(
        monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-cp-test-only")
    rehearsal = load_config("runs/v2-spec-closure-rehearsal.yaml")
    live = load_config("runs/v2-spec-closure-live.yaml")

    assert rehearsal["engine_semantics_version"] == 7
    assert rehearsal["ticks"] == 5
    assert rehearsal["checkpoint_every"] == 1
    assert rehearsal["spec_closure_fixture"]["enabled"] is True
    assert rehearsal["llm"]["default_route"] == {
        "provider": "scripted", "model": "scripted",
    }
    assert rehearsal["llm"]["routes"] == {}
    assert validate_llm_config(rehearsal, raise_on_error=False)["ready"]

    assert live["engine_semantics_version"] == 7
    assert live["ticks"] == 5
    assert live["budget"]["cap_usd"] == 1.0
    assert set(live["llm"]["providers"]) == {"minimax"}
    assert "ollama" not in json.dumps(live["llm"]).lower()
    assert live["llm"]["providers"]["minimax"]["prompt_cache_mode"] == (
        "provider_automatic")
    assert live["llm"]["default_route"]["provider"] == "scripted"
    assert set(live["llm"]["routes"]) == {
        "persona", "central_banker", "credit_officer", "vc_partner", "lawyer",
    }
    assert {route["model"] for route in live["llm"]["routes"].values()} == {
        "MiniMax-M3"}
    report = validate_llm_config(live, raise_on_error=False)
    assert report["ready"], report["errors"]


def test_closure_fixture_is_semantics_gated_idempotent_action_ready_and_balanced(
        tmp_path):
    config, store, world, _, payload = _open_rehearsal(tmp_path)
    try:
        assert payload is not None
        assert payload["engine_semantics_version"] == 7
        repeated = SpecClosureFixtureSeeder(world.economy, config).seed()
        assert repeated == payload
        assert store.scalar(
            "SELECT COUNT(*) FROM events WHERE kind='spec_closure_fixture_seeded'") == 1
        assert store.scalar(
            "SELECT COUNT(*) FROM loans WHERE id=?", (payload["default_loan_id"],)) == 1

        retiree = store.query_one(
            "SELECT * FROM agents WHERE id=?", (payload["retiree_agent_id"],))
        checking = store.query_one(
            "SELECT * FROM accounts WHERE id=?",
            (payload["retiree_checking_account_id"],))
        savings = store.query_one(
            "SELECT * FROM accounts WHERE id=?",
            (payload["retiree_savings_account_id"],))
        assert retiree["retired"] == 1 and retiree["population_tier"] == "core"
        assert checking["owner_id"] == retiree["id"]
        assert savings["owner_id"] == retiree["id"]
        assert checking["currency_code"] == savings["currency_code"]
        assert int(checking["balance_cents"]) < payload[
            "retirement_liquidity_target_cents"]
        assert int(savings["balance_cents"]) >= payload[
            "retirement_liquidity_target_cents"]

        scheduled = store.query_one(
            "SELECT payload_json FROM events WHERE id=? AND kind='arrival_scheduled'",
            (payload["arrival_schedule_event_id"],))
        assert json.loads(scheduled["payload_json"])["due_tick"] == 1

        loan = store.query_one(
            "SELECT * FROM loans WHERE id=?", (payload["default_loan_id"],))
        assert loan["status"] == "active"
        assert loan["missed_payments"] == 2 and loan["next_due_tick"] == 1
        assert json.loads(loan["collateral_json"])["cash"] == payload[
            "collateral_recovery_cents"]

        trade = world.economy.regions.decision_context(
            payload["exporter_founder_agent_id"], tick=1,
            exporter_firm_id=payload["exporter_firm_id"], career_day=False)
        opportunity = trade["trade_opportunities"][0]
        assert opportunity["contract_id"] == payload["trade_contract_id"]
        assert opportunity["invoice_currency"] == store.scalar(
            "SELECT currency_code FROM firms WHERE id=?",
            (payload["importer_firm_id"],))
        assert opportunity["quantity"] <= config["living_world"][
            "max_trade_quantity"]

        migration = world.economy.regions.decision_context(
            payload["migration_candidate_agent_id"], tick=1, career_day=True)
        option = migration["migration_options"][0]
        assert option["destination_region_id"] == payload[
            "migration_destination_region_id"]
        assert option["wage_gain_bps"] >= config["living_world"][
            "migration_wage_gain_bps"]

        ok, diagnostic = world.economy.ledger.reconcile()
        assert ok, diagnostic
        assert all(value == 0 for value in diagnostic["currency_sums"].values())

        legacy = {**config, "engine_semantics_version": 6}
        with pytest.raises(SpecClosureFixtureError, match="semantics_version >= 7"):
            SpecClosureFixtureSeeder(world.economy, legacy).seed()
    finally:
        store.close()


def test_five_tick_closure_rehearsal_exercises_every_effect_and_replays_exactly(
        tmp_path):
    config, source_store, source_world, source_id, payload = _open_rehearsal(tmp_path)
    replay_store = None
    try:
        asyncio.run(source_world.run(max_ticks=5))
        assert source_store.tick == 5

        for kind in (
            "loan_default",
            "retirement_savings_withdrawal",
            "arrival",
            "persona_enriched",
            "trade_shipment_created",
            "trade_shipment_delivered",
            "agent_migrated",
        ):
            assert source_store.scalar(
                "SELECT COUNT(*) FROM events WHERE kind=?", (kind,), default=0) >= 1

        default_event = source_store.query_one(
            "SELECT payload_json FROM events WHERE kind='loan_default' "
            "AND json_extract(payload_json,'$.loan_id')=? ORDER BY id LIMIT 1",
            (payload["default_loan_id"],))
        default_payload = json.loads(default_event["payload_json"])
        assert default_payload["recovered_cents"] == payload[
            "collateral_recovery_cents"]
        assert default_payload["net_charged_off_cents"] == payload[
            "expected_net_chargeoff_cents"]
        chargeoff_legs = source_store.query(
            "SELECT le.delta_cents FROM ledger_entries le "
            "JOIN transactions t ON t.id=le.txn_id "
            "WHERE t.kind='loan_loss_chargeoff' AND le.account_id=?",
            (payload["default_bank_equity_account_id"],))
        assert sum(int(row["delta_cents"]) for row in chargeoff_legs) == -payload[
            "expected_net_chargeoff_cents"]

        accepted = {str(row["action_type"]) for row in source_store.query(
            "SELECT DISTINCT action_type FROM action_proposals "
            "WHERE validation_status='accepted'")}
        assert TARGET_ACTIONS <= accepted
        placeholders = ",".join("?" for _ in TARGET_ACTIONS)
        assert source_store.scalar(
            "SELECT COUNT(*) FROM action_proposals "
            f"WHERE validation_status='rejected' AND action_type IN ({placeholders})",
            tuple(sorted(TARGET_ACTIONS)), default=0) == 0
        assert source_store.scalar(
            "SELECT COUNT(*) FROM llm_calls WHERE role='persona' AND purpose='persona'") == 1
        assert source_store.scalar(
            "SELECT COUNT(*) FROM llm_calls WHERE provider<>'scripted'") == 0
        assert source_store.scalar(
            "SELECT COUNT(DISTINCT tick) FROM checkpoints WHERE tick BETWEEN 1 AND 5") == 5
        assert source_store.scalar(
            "SELECT status FROM trade_shipments WHERE exporter_firm_id=?",
            (payload["exporter_firm_id"],)) == "delivered"
        assert source_store.scalar(
            "SELECT status FROM migrations WHERE agent_id=?",
            (payload["migration_candidate_agent_id"],)) == "completed"
        ok, diagnostic = source_world.economy.ledger.reconcile()
        assert ok, diagnostic

        replay_store, replay_world, _ = open_run(
            {}, None, source_id, data_dir=tmp_path / "runs")
        SpecClosureFixtureSeeder(
            replay_world.economy, replay_world.config).seed()
        asyncio.run(replay_headless(replay_world, 5))
        proof = verify_replay(source_store.path, replay_store.path)
        assert proof["exact"], proof["differences"]
        assert proof["differences"] == []
        assert proof["source_tick"] == proof["replay_tick"] == 5
        assert proof["source_hash"] == proof["replay_hash"]
    finally:
        source_store.close()
        if replay_store is not None:
            replay_store.close()

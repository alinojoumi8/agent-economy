from __future__ import annotations

import asyncio
import json

from llm.readiness import validate_llm_config
from run import open_run
from run_config import load_config


def test_live_behavioral_profile_is_bounded_and_routes_lawyer(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-cp-test-only")
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama")
    config = load_config("runs/v2-live-behavioral.yaml")

    report = validate_llm_config(config, raise_on_error=False)
    assert report["ready"], report["errors"]
    assert config["population"]["target_total"] == 36
    assert sum(region["population"] for region in config["living_world"]["regions"]) == 36
    assert config["living_world"]["core_agents"] == 4
    assert config["behavioral_fixture"]["key"] == "seeded-startup-behavior-v1"
    assert config["budget"]["cap_usd"] == 0.50
    assert config["llm"]["routes"]["lawyer"] == {
        "provider": "minimax", "model": "MiniMax-M3",
    }


def test_institutional_gate_keeps_the_live_shape_and_scripts_its_rehearsal(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-cp-test-only")
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama")
    live = load_config("runs/v2-live-institutional.yaml")
    rehearsal = load_config("runs/v2-institutional-rehearsal.yaml")

    assert validate_llm_config(live, raise_on_error=False)["ready"]
    assert live["population"]["target_total"] == 36
    assert live["living_world"]["core_agents"] == 22
    assert live["budget"]["cap_usd"] == 2.0
    assert live["political_model"]["actor_bound_authorization"] is True
    assert live["llm"]["institutional_role_purposes"] is True
    assert live["llm"]["local_currency_action_surfaces"] is True
    assert rehearsal["living_world"]["core_agents"] == 22
    assert rehearsal["political_model"]["actor_bound_authorization"] is True
    assert rehearsal["llm"]["institutional_role_purposes"] is True
    assert rehearsal["llm"]["local_currency_action_surfaces"] is True
    rehearsal_routes = [
        rehearsal["llm"]["default_route"],
        *rehearsal["llm"]["routes"].values(),
    ]
    assert {route["provider"] for route in rehearsal_routes} == {"scripted"}


def test_institutional_rehearsal_executes_bounded_role_work_without_rejections(tmp_path):
    config = load_config("runs/v2-institutional-rehearsal.yaml")
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    store, world, _ = open_run(config, None, None, data_dir=tmp_path)
    try:
        first_legislator = store.query_one(
            "SELECT a.* FROM agents a JOIN legislators l ON l.agent_id=a.id "
            "WHERE l.active=1 ORDER BY l.id LIMIT 1")
        context = world.runtime.ctx.build(first_legislator, 1)
        assert context["institutional_work"]["eligible_actions"][0]["type"] == "sponsor_bill"
        system, prompt = world.runtime.ctx.render_prompt(context)
        assert "sponsor_bill" in system
        assert "INSTITUTIONAL WORK" in prompt
        assert "ONLY eligible_actions MAY BE USED" in prompt

        asyncio.run(world.run(max_ticks=6))
        expected = {
            "exchange", "gov_official", "legislator_house", "legislator_senate",
            "regulator", "competition_regulator", "labor_regulator", "executive",
            "lobbyist",
        }
        purposes = {str(row["purpose"]) for row in store.query(
            "SELECT DISTINCT purpose FROM llm_calls WHERE tick>0")}
        assert expected <= purposes
        reporter_calls = int(store.scalar(
            "SELECT COUNT(*) FROM llm_calls WHERE role='reporter' AND purpose='reporter'"))
        newsroom_calls = int(store.scalar(
            "SELECT COUNT(*) FROM llm_calls WHERE role='editor' AND purpose='newsroom'"))
        assert reporter_calls == newsroom_calls and reporter_calls > 0
        assert store.scalar(
            "SELECT COUNT(*) FROM llm_calls WHERE role='editor' AND purpose='editor'") == 0
        assert store.scalar(
            "SELECT COUNT(*) FROM action_proposals WHERE validation_status='rejected'") == 0
        exercised = {str(row["action_type"]) for row in store.query(
            "SELECT DISTINCT action_type FROM action_proposals WHERE tick>0 "
            "AND validation_status='accepted'")}
        assert {
            "sponsor_bill", "committee_vote", "cast_legislative_vote",
            "executive_bill_action", "lobby", "review_merger", "place_fx_order",
        } <= exercised
        assert store.scalar("SELECT COUNT(*) FROM bills WHERE status='enacted'") == 1
        assert store.scalar("SELECT COUNT(*) FROM merger_reviews") == 1
        assert store.scalar("SELECT COUNT(*) FROM lobbying_activities") == 1
        assert store.scalar("SELECT COUNT(*) FROM fx_trades") == 1
        ok, diagnostic = world.economy.ledger.reconcile()
        assert ok, diagnostic
    finally:
        store.close()


def test_month_one_dashboard_has_engine_measured_activity(tmp_path):
    config = load_config("runs/v2-institutional-rehearsal.yaml")
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    store, world, _ = open_run(config, None, None, data_dir=tmp_path)
    try:
        asyncio.run(world.run(max_ticks=31))

        latest = {
            name: store.scalar(
                "SELECT value FROM metrics WHERE name=? ORDER BY tick DESC LIMIT 1",
                (name,))
            for name in ("gdp_proxy_30d", "unemployment", "index")
        }
        assert float(latest["gdp_proxy_30d"]) > 0
        assert 0 < float(latest["unemployment"]) < 1
        assert latest["index"] is not None and float(latest["index"]) > 0
        assert store.scalar("SELECT COUNT(*) FROM trades") > 0
        assert store.scalar("SELECT COUNT(*) FROM term_sheets") > 0
        assert store.scalar("SELECT COUNT(*) FROM due_diligence_checks") > 0
        assert store.scalar("SELECT COUNT(*) FROM funding_rounds") > 0
        assert store.scalar("SELECT COUNT(*) FROM ip_assets") > 0
        ok, diagnostic = world.economy.ledger.reconcile()
        assert ok, diagnostic
    finally:
        store.close()


def test_ten_tick_rehearsal_exercises_credit_vc_law_and_information(tmp_path):
    config = load_config("runs/v2-behavioral-rehearsal.yaml")
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    store, world, _ = open_run(config, None, None, data_dir=tmp_path)
    try:
        fixture = store.query_one(
            "SELECT * FROM events WHERE kind='behavioral_fixture_seeded' ORDER BY id LIMIT 1")
        assert fixture is not None
        fixture_payload = json.loads(fixture["payload_json"])
        assert store.scalar("SELECT COUNT(*) FROM agents") == 36
        assert store.scalar("SELECT COUNT(*) FROM agents WHERE population_tier='core'") == 4
        assert store.scalar("SELECT COUNT(*) FROM loan_applications WHERE status='pending'") == 1
        assert store.scalar("SELECT COUNT(*) FROM pitches WHERE status='pending'") == 1
        assert store.scalar("SELECT COUNT(*) FROM legal_matters WHERE status='filed'") == 1
        assert store.scalar("SELECT COUNT(*) FROM firm_disclosures") == 1

        vc_partner = store.query_one(
            "SELECT * FROM agents WHERE role='vc_partner' ORDER BY id LIMIT 1")
        vc_context = world.runtime.ctx.build(vc_partner, 1)
        assert vc_context["startup_work"]["eligible_actions"][0]["type"] == "propose_term_sheet"

        lawyer = store.query_one("SELECT * FROM agents WHERE role='lawyer' ORDER BY id LIMIT 1")
        context = world.runtime.ctx.build(lawyer, 1)
        assert context["purpose"] == "lawyer"
        assert context["assigned_legal_matters"][0]["evidence_events"]
        system, prompt = world.runtime.ctx.render_prompt(context)
        assert "submit_filing" in system
        assert f"agent_id {lawyer['id']}" in prompt
        assert "ASSIGNED LEGAL MATTERS" in prompt
        assert "obligation_breached" in prompt

        asyncio.run(world.run(max_ticks=10))

        assert store.tick == 10
        assert store.scalar(
            "SELECT status FROM loan_applications WHERE id=?",
            (fixture_payload["loan_application_id"],)) != "pending"
        assert store.scalar(
            "SELECT status FROM pitches WHERE id=?",
            (fixture_payload["pitch_id"],)) == "funded"
        assert store.scalar("SELECT COUNT(*) FROM legal_filings WHERE admitted=1") >= 1
        assert store.scalar("SELECT COUNT(*) FROM legal_matters WHERE status='settlement_offered'") == 1
        assert store.scalar("SELECT COUNT(*) FROM term_sheets") == 1
        assert store.scalar("SELECT COUNT(*) FROM due_diligence_checks") == 1
        assert store.scalar("SELECT COUNT(*) FROM funding_rounds") == 1
        assert store.scalar("SELECT COUNT(*) FROM ip_assets") == 1
        assert store.scalar("SELECT COUNT(*) FROM news_articles") >= 1
        assert store.scalar("SELECT COUNT(*) FROM information_exposures") >= 1
        assert store.scalar("SELECT COUNT(*) FROM llm_calls WHERE purpose='lawyer'") == 10
        assert store.scalar("SELECT COUNT(*) FROM llm_calls WHERE provider<>'scripted'") == 0
        rejected_types = {row["action_type"] for row in store.query(
            "SELECT DISTINCT action_type FROM action_proposals "
            "WHERE validation_status='rejected'")}
        assert rejected_types <= {"buy_goods"}

        attributed = store.query(
            "SELECT p.action_type,p.model_call_id,p.rationale_summary FROM action_proposals p "
            "JOIN agents a ON a.id=p.actor_id WHERE p.tick>0 "
            "AND a.population_tier='core' AND p.action_type IN "
            "('deny_loan','propose_term_sheet','run_due_diligence','close_funding_round',"
            "'submit_filing','propose_settlement')")
        assert {row["action_type"] for row in attributed} == {
            "deny_loan", "propose_term_sheet", "run_due_diligence",
            "close_funding_round", "submit_filing", "propose_settlement",
        }
        assert all(row["model_call_id"] is not None for row in attributed)
        assert all(row["rationale_summary"] for row in attributed)
        filing = store.query_one("SELECT model_call_id, rationale_summary FROM legal_filings")
        assert filing["model_call_id"] is not None
        assert filing["rationale_summary"]

        exercised = {row["action_type"] for row in store.query(
            "SELECT DISTINCT action_type FROM action_proposals WHERE tick>0 "
            "AND validation_status='accepted' AND action_type<>'do_nothing'")}
        assert {"deny_loan", "propose_term_sheet", "accept_term_sheet",
                "run_due_diligence", "close_funding_round", "register_ip",
                "submit_filing", "propose_settlement"} <= exercised
        ok, diagnostic = world.economy.ledger.reconcile()
        assert ok, diagnostic
        assert diagnostic["currency_sums"] == {"IVC": 0, "NSD": 0, "SCD": 0, "USD": 0}
    finally:
        store.close()

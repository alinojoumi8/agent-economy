from __future__ import annotations

import asyncio

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


def test_ten_tick_rehearsal_exercises_credit_vc_law_and_information(tmp_path):
    config = load_config("runs/v2-behavioral-rehearsal.yaml")
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    store, world, _ = open_run(config, None, None, data_dir=tmp_path)
    try:
        fixture = store.query_one(
            "SELECT * FROM events WHERE kind='behavioral_fixture_seeded' ORDER BY id LIMIT 1")
        assert fixture is not None
        assert store.scalar("SELECT COUNT(*) FROM agents") == 36
        assert store.scalar("SELECT COUNT(*) FROM agents WHERE population_tier='core'") == 4
        assert store.scalar("SELECT COUNT(*) FROM loan_applications WHERE status='pending'") == 1
        assert store.scalar("SELECT COUNT(*) FROM pitches WHERE status='pending'") == 1
        assert store.scalar("SELECT COUNT(*) FROM legal_matters WHERE status='filed'") == 1
        assert store.scalar("SELECT COUNT(*) FROM firm_disclosures") == 1

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
        assert store.scalar("SELECT COUNT(*) FROM loan_applications WHERE status='pending'") == 0
        assert store.scalar("SELECT COUNT(*) FROM pitches WHERE status='pending'") == 0
        assert store.scalar("SELECT COUNT(*) FROM legal_filings WHERE admitted=1") >= 1
        assert store.scalar("SELECT COUNT(*) FROM legal_matters WHERE status='settlement_offered'") == 1
        assert store.scalar("SELECT COUNT(*) FROM news_articles") >= 1
        assert store.scalar("SELECT COUNT(*) FROM information_exposures") >= 1
        assert store.scalar("SELECT COUNT(*) FROM llm_calls WHERE purpose='lawyer'") == 10
        assert store.scalar("SELECT COUNT(*) FROM llm_calls WHERE provider<>'scripted'") == 0
        assert store.scalar("SELECT COUNT(*) FROM action_proposals WHERE validation_status='rejected'") == 0

        attributed = store.query(
            "SELECT action_type, model_call_id, rationale_summary FROM action_proposals "
            "WHERE tick>0 AND action_type IN "
            "('deny_loan','fund_pitch','submit_filing','propose_settlement')")
        assert {row["action_type"] for row in attributed} == {
            "deny_loan", "fund_pitch", "submit_filing", "propose_settlement",
        }
        assert all(row["model_call_id"] is not None for row in attributed)
        assert all(row["rationale_summary"] for row in attributed)
        filing = store.query_one("SELECT model_call_id, rationale_summary FROM legal_filings")
        assert filing["model_call_id"] is not None
        assert filing["rationale_summary"]

        exercised = {row["action_type"] for row in store.query(
            "SELECT DISTINCT action_type FROM action_proposals WHERE tick>0 "
            "AND validation_status='accepted' AND action_type<>'do_nothing'")}
        assert {"deny_loan", "fund_pitch", "submit_filing", "propose_settlement"} <= exercised
        ok, diagnostic = world.economy.ledger.reconcile()
        assert ok, diagnostic
        assert diagnostic["currency_sums"] == {"IVC": 0, "NSD": 0, "SCD": 0, "USD": 0}
    finally:
        store.close()

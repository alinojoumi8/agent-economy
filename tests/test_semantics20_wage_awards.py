"""Fixed earnings periods, one receivable, actual taxed collection and succession."""
import asyncio
import copy
import hashlib
import json

import pytest

from agents.memory import Memory
from agents.prompts import ContextBuilder
from engine.ledger import SYS_EXTERNAL, SYS_GOV
from engine.lifecycle import Lifecycle
from research.hashing import canonical_hashes
from research.export_bundle import export_bundle, validate_bundle
from server.projections.legal_relief import monetary_relief_as_of
from world.metrics import Metrics
from world.replay_verify import verify_replay

from .conftest import make_agent
from .test_semantics18_daily_time import employer
from .test_semantics20_legal_awards import award_case, decide, check
from .test_semantics13_construction import _config
from .test_semantics17_household_decisions import _world


def wage_case(c, *, daily=150, tax=2000, currency="USD"):
    c.firm, c.firm_wallet, c.employment = employer(c.e, c.bank, c.creditor, wage=daily * 30,
                                                   interval=30, cash=0, founder=c.person)
    if currency != "USD":
        c.firm_wallet = c.e.regions._wallet("firm", c.firm, currency, create=True)
        c.e.store.update("firms", c.firm, account_id=c.firm_wallet)
    c.e.store.update("employments", c.employment, next_pay_tick=1)
    c.e.store.record_metric(0, "tax_rate_bps", tax)
    c.e.daily_time.prepare_day(1)
    c.wage_claim = c.e.store.scalar("SELECT id FROM wage_claims WHERE employment_id=?", (c.employment,))
    assert c.wage_claim is not None
    assert wage_owed(c) == daily
    return c


def wage_owed(c):
    return c.e.earned_wages.outstanding(c.e.store.query_one("SELECT * FROM wage_claims WHERE id=?", (c.wage_claim,)))


def fund(c, amount, *, tick=1):
    currency = c.e.store.scalar("SELECT currency_code FROM accounts WHERE id=?", (c.firm_wallet,))
    return c.e.ledger.transfer(tick, c.e.ledger.system_account(SYS_EXTERNAL, currency_code=currency), c.firm_wallet,
                               amount, kind="fixture_firm_funding")


def file_wages(c, amount=150, *, tick=1, scopes=None):
    if scopes is None:
        scopes = [{"claim_id": c.wage_claim, "through_accrual_id": c.e.store.scalar("SELECT MAX(id) FROM wage_accruals WHERE claim_id=?", (c.wage_claim,))}]
    currency = c.e.store.scalar("SELECT currency_code FROM wage_claims WHERE id=?", (c.wage_claim,))
    result = c.e.legal.file_claim(tick, c.creditor, {"matter_type": "labor", "claim_type": "unpaid_wages",
        "claimant": {"type": "agent", "id": c.creditor}, "respondent": {"type": "firm", "id": c.firm},
        "requested_remedy": {"type": "damages", "amount_cents": amount, "currency_code": currency, "wage_scopes": scopes}})
    assert result["ok"], result
    evidence = c.e.store.scalar("SELECT id FROM events WHERE kind='wage_earned' AND subject_id=? ORDER BY id DESC LIMIT 1", (c.creditor,))
    assert evidence is not None
    filed = c.e.legal.submit_filing(tick, c.creditor, {"matter_id": result["matter_id"], "filer_type": "agent", "filer_id": c.creditor,
        "filing_type": "evidence", "evidence_event_ids": [evidence], "body": "Recorded work defines the compensation period."})
    assert filed["ok"], filed
    return result["matter_id"], evidence


def verify(c):
    c.e.earned_wages.check_invariants()
    c.e.wage_awards.check_invariants()
    check(c)


def test_prior_gross_wages_are_credited_and_the_old_receivable_cannot_collect_again(award_case, tmp_path):
    c = wage_case(award_case)
    fund(c, 50)
    assert c.e.earned_wages.settle(1, c.wage_claim) == 50
    matter, evidence = file_wages(c)
    result = decide(c, matter, evidence, 120, tick=2)
    assert result["ok"], result
    award = result["enforcement"]["award_id"]
    assert result["enforcement"]["credited_cents"] == 50
    assert result["enforcement"]["unpaid_cents"] == 70
    assert wage_owed(c) == 0
    assert c.e.store.scalar("SELECT written_off_cents FROM wage_claims") == 0
    assert c.e.store.scalar("SELECT removed_cents FROM wage_claim_novations") == 100
    fund(c, 100, tick=3)
    c.e.earned_wages.process_due(3)
    assert c.e.legal_awards.paid(award) == 70
    assert c.e.ledger.balance(c.creditor_wallet) == 96  # 120 gross less 24 actual tax.
    assert c.e.ledger.balance(c.firm_wallet) == 30
    assert c.e.earned_wages.settle(3, c.wage_claim) == 0
    metrics = Metrics(c.e, semantics_version=20)
    assert [metrics._labor_income(t) for t in (1, 2, 3)] == [0.5, 0.0, 0.7]
    assert metrics._gdp_proxy(3) == 0.0
    assert Metrics(c.e, semantics_version=19)._labor_income(3) == 0.0
    assert validate_bundle(export_bundle(c.e.store, tmp_path / "wage-award-export"))["tables"]["wage_claim_novations"]["row_count"] == 1
    verify(c)


def test_later_work_and_a_second_judgment_keep_disjoint_earnings_and_payment_credits(award_case):
    c = wage_case(award_case)
    matter, evidence = file_wages(c)
    c.e.daily_time.prepare_day(2)
    fund(c, 100, tick=2)
    assert c.e.earned_wages.settle(2, c.wage_claim) == 100
    assert decide(c, matter, evidence, 120, tick=2)["ok"]
    assert wage_owed(c) == 150
    fund(c, 100, tick=3)
    c.e.earned_wages.process_due(3)
    assert wage_owed(c) == 70
    second, evidence = file_wages(c, tick=4)
    result = decide(c, second, evidence, 100, tick=4)
    assert result["ok"], result
    assert result["enforcement"]["credited_cents"] == 80
    assert result["enforcement"]["unpaid_cents"] == 20
    assert [tuple(r) for r in c.e.store.query("SELECT start_cents,end_cents FROM legal_wage_scopes ORDER BY id")] == [(0,150),(150,300)]
    fund(c, 50, tick=5)
    c.e.earned_wages.process_due(5)
    assert wage_owed(c) == 0
    assert c.e.ledger.balance(c.creditor_wallet) == 176  # 220 gross, 44 tax.
    assert c.e.ledger.balance(c.firm_wallet) == 30
    verify(c)


def test_net_compensation_after_worker_death_follows_the_nominee_estate(award_case):
    c = wage_case(award_case, daily=100)
    matter, evidence = file_wages(c, 100)
    assert decide(c, matter, evidence, 100, tick=2)["ok"]
    c.e.lifecycle.settle_death(3, c.creditor)
    fund(c, 100, tick=4)
    c.e.earned_wages.process_due(4)
    assert c.e.ledger.balance(c.creditor_wallet) == 0
    assert c.e.ledger.balance(c.heir_wallet) == 80
    assert c.e.store.scalar("SELECT SUM(received_cents) FROM estate_receipts WHERE origin_transaction_id IN "
                            "(SELECT transaction_id FROM legal_award_payments)") == 80
    assert Metrics(c.e, semantics_version=20)._labor_income(4) == 1.0
    verify(c)


def test_bankruptcy_pays_remaining_cash_and_records_loss_without_reopening_original_wages(award_case):
    c = wage_case(award_case, daily=100)
    matter, evidence = file_wages(c, 100)
    assert decide(c, matter, evidence, 100, tick=2)["ok"]
    fund(c, 50, tick=3)
    c.e.firms.bankrupt_firm(3, c.firm)
    assert c.e.store.scalar("SELECT amount_cents FROM legal_award_losses") == 50
    assert c.e.store.scalar("SELECT SUM(amount_cents) FROM legal_award_payments") == 50
    assert c.e.ledger.balance(c.creditor_wallet) == 40
    assert Metrics(c.e, semantics_version=20)._labor_income(3) == 0.5
    assert wage_owed(c) == 0
    assert c.e.store.scalar("SELECT written_off_cents FROM wage_claims") == 0
    fund(c, 100, tick=4)
    c.e.earned_wages.process_due(4)
    assert c.e.ledger.balance(c.creditor_wallet) == 40
    verify(c)


def test_fully_withheld_compensation_closes_the_gross_award_without_inventing_net_cash(award_case):
    c = wage_case(award_case, daily=100, tax=10_000)
    fund(c, 100)
    matter, evidence = file_wages(c, 100)
    before = c.e.ledger.balance(c.e.ledger.system_account(SYS_GOV))
    result = decide(c, matter, evidence, 100, tick=2)
    assert result["ok"], result
    assert result["enforcement"]["tax_cents"] == 100
    assert result["enforcement"]["unpaid_cents"] == 0
    assert c.e.ledger.balance(c.creditor_wallet) == 0
    assert c.e.ledger.balance(c.e.ledger.system_account(SYS_GOV)) == before + 100
    verify(c)


def test_failed_payment_recording_rolls_back_the_judgment_and_both_receivables(award_case, monkeypatch):
    c = wage_case(award_case)
    matter, evidence = file_wages(c)
    fund(c, 100)
    before = canonical_hashes(c.e.store)["authoritative_sha256"]
    def fail(*args, **kwargs):
        raise RuntimeError("injected wage award collection failure")
    monkeypatch.setattr(c.e.legal_awards, "note_payment", fail)
    with pytest.raises(RuntimeError, match="injected wage award"):
        decide(c, matter, evidence, 150, tick=2)
    assert canonical_hashes(c.e.store)["authoritative_sha256"] == before
    assert wage_owed(c) == 150
    verify(c)


def test_invalid_and_overlapping_wage_filings_are_atomic_and_cutoff_cannot_be_amended(award_case):
    c = wage_case(award_case)
    matter, evidence = file_wages(c)
    before = canonical_hashes(c.e.store)["authoritative_sha256"]
    duplicate = c.e.legal.file_claim(2, c.creditor, {"claim_type": "unpaid_wages", "claimant": {"type": "agent", "id": c.creditor},
        "respondent": {"type": "firm", "id": c.firm}, "requested_remedy": {"type": "damages", "amount_cents": 150}})
    assert not duplicate["ok"] and "pending" in duplicate["reason"]
    assert canonical_hashes(c.e.store)["authoritative_sha256"] == before
    c.e.daily_time.prepare_day(2)
    amended = decide(c, matter, evidence, 150, tick=2, wage_scopes=[{"claim_id": c.wage_claim,
        "through_accrual_id": c.e.store.scalar("SELECT MAX(id) FROM wage_accruals")}])
    assert not amended["ok"] and "interval" in amended["reason"]
    assert wage_owed(c) == 300
    verify(c)


def test_scripted_claim_offer_supplies_actual_gross_scope_and_suppresses_duplicate_pending_claims(award_case):
    c = wage_case(award_case)
    make_agent(c.e, c.bank, "Counsel", cash=0, kind="staff", occupation="lawyer", role="lawyer")
    fund(c, 50)
    c.e.earned_wages.process_due(1)
    builder = ContextBuilder(c.e, Memory(c.e.store, c.e.config), c.e.config)
    actor = c.e.store.query_one("SELECT * FROM agents WHERE id=?", (c.creditor,))
    offer = builder._legal_work(actor, 2)["eligible_actions"][0]
    assert offer["requested_remedy"]["amount_cents"] == 150
    assert offer["requested_remedy"]["wage_scopes"][0]["claim_id"] == c.wage_claim
    assert c.executor.execute_action(2, c.creditor, offer)["ok"]
    assert builder._legal_work(actor, 2)["eligible_actions"] == []
    verify(c)


@pytest.mark.parametrize("invalid", ["claimant", "dual_party", "employer", "currency", "future"])
def test_wage_filing_rejects_other_parties_currency_and_future_work_without_a_partial_matter(award_case, invalid):
    c = wage_case(award_case)
    actor, firm, currency = c.creditor, c.firm, "USD"
    if invalid == "claimant":
        # An unrelated living person reaches wage ownership validation.
        actor = c.heir
    elif invalid == "dual_party":
        # Procedural standing does not make the employer's owner the worker.
        actor = c.person
    elif invalid == "employer":
        firm, _, _ = employer(c.e, c.bank, founder=c.person)
    elif invalid == "currency":
        currency = "EUR"
    else:
        c.e.daily_time.prepare_day(2)
    cutoff = c.e.store.scalar("SELECT MAX(id) FROM wage_accruals WHERE claim_id=?", (c.wage_claim,))
    before = canonical_hashes(c.e.store)["authoritative_sha256"]
    result = c.e.legal.file_claim(1, actor, {"claim_type": "unpaid_wages",
        "claimant": {"type": "agent", "id": actor}, "respondent": {"type": "firm", "id": firm},
        "requested_remedy": {"type": "damages", "amount_cents": 150, "currency_code": currency,
            "wage_scopes": [{"claim_id": c.wage_claim, "through_accrual_id": cutoff}]}})
    assert not result["ok"]
    expected = {"currency": "currency"}.get(invalid, "recorded work")
    assert expected in result["reason"]
    assert canonical_hashes(c.e.store)["authoritative_sha256"] == before
    verify(c)


def test_foreign_wage_compensation_uses_its_earned_currency_and_leaves_domestic_cash_separate(award_case):
    c = wage_case(award_case, currency="EUR")
    domestic = c.e.store.scalar("SELECT id FROM accounts WHERE owner_type='firm' AND owner_id=? AND currency_code='USD' AND kind='checking'", (c.firm,))
    c.e.ledger.transfer(1, c.e.ledger.system_account(SYS_EXTERNAL), domestic, 300, kind="fixture_domestic_cash")
    fund(c, 25)
    assert c.e.earned_wages.settle(1, c.wage_claim) == 25
    matter, evidence = file_wages(c)
    before = canonical_hashes(c.e.store)["tables"]
    rejected = decide(c, matter, evidence, 120, tick=2, currency_code="USD")
    assert not rejected["ok"] and "currency" in rejected["reason"]
    after = canonical_hashes(c.e.store)["tables"]
    assert {table for table in before if before[table] != after[table]} == {"events"}
    assert after["events"]["row_count"] == before["events"]["row_count"] + 1
    assert c.e.store.scalar("SELECT kind FROM events ORDER BY id DESC LIMIT 1") == "legal_decision_validation_failed"
    fund(c, 95, tick=2)
    result = decide(c, matter, evidence, 120, tick=2, currency_code="EUR")
    assert result["ok"], result
    assert result["enforcement"]["credited_cents"] == 25
    assert result["enforcement"]["paid_cents"] == 95
    assert c.e.ledger.balance(domestic) == 300
    assert c.e.ledger.balance(c.creditor_wallet) == 0
    foreign = c.e.regions._wallet("agent", c.creditor, "EUR", create=False)
    assert c.e.ledger.balance(foreign) == 96
    assert wage_owed(c) == 0
    verify(c)


def test_accepted_wage_settlement_replaces_the_same_earnings_and_collects_only_the_remaining_gross(award_case):
    c = wage_case(award_case)
    fund(c, 30)
    assert c.e.earned_wages.settle(1, c.wage_claim) == 30
    matter, _ = file_wages(c)
    offered = c.e.legal.propose_settlement(2, c.creditor, matter,
        {"remedy": {"type": "damages", "amount_cents": 120, "currency_code": "USD"}})
    assert offered["ok"], offered
    fund(c, 60, tick=2)
    accepted = c.e.legal.accept_settlement(2, c.person, matter)
    assert accepted["ok"], accepted
    assert (accepted["enforcement"]["credited_cents"], accepted["enforcement"]["paid_cents"],
            accepted["enforcement"]["unpaid_cents"]) == (30, 60, 30)
    assert c.e.store.scalar("SELECT basis FROM legal_awards") == "settlement"
    assert wage_owed(c) == 0
    fund(c, 30, tick=3)
    c.e.earned_wages.process_due(3)
    assert c.e.ledger.balance(c.creditor_wallet) == 96
    assert c.e.ledger.balance(c.firm_wallet) == 0
    verify(c)


def test_a_pending_case_credits_prior_bankruptcy_discharge_without_recording_the_loss_twice(award_case):
    c = wage_case(award_case)
    matter, evidence = file_wages(c)
    c.e.firms.bankrupt_firm(2, c.firm)
    assert c.e.store.scalar("SELECT written_off_cents FROM wage_claims") == 150
    before = c.e.ledger.total_deposits_cents()
    result = decide(c, matter, evidence, 120, tick=3)
    assert result["ok"], result
    assert result["enforcement"]["credited_loss_cents"] == 120
    assert result["enforcement"]["unpaid_cents"] == 0
    assert result["enforcement"]["paid_cents"] == 0
    assert c.e.store.scalar("SELECT COUNT(*) FROM legal_award_losses") == 0
    assert c.e.store.scalar("SELECT SUM(removed_cents) FROM wage_claim_novations") == 0
    assert c.e.ledger.total_deposits_cents() == before
    verify(c)


def test_selected_day_wage_projection_distinguishes_tax_net_cash_and_later_losses(award_case):
    c = wage_case(award_case, daily=100)
    c.e.store.update("agents", c.creditor, population_tier="core", pinned_core=0)
    matter, evidence = file_wages(c, 100)
    assert decide(c, matter, evidence, 100, tick=2)["ok"]
    fund(c, 50, tick=3)
    c.e.firms.bankrupt_firm(3, c.firm)
    before = monetary_relief_as_of(c.e.store, matter, 2)["award"]
    after = monetary_relief_as_of(c.e.store, matter, 3)["award"]
    assert (before["paid_cents"], before["outstanding_cents"], before["written_off_cents"]) == (0, 100, 0)
    assert after["payment_basis"] == "gross_wages"
    assert (after["paid_cents"], after["tax_cents"], after["net_received_cents"], after["written_off_cents"], after["outstanding_cents"]) == (50, 10, 40, 50, 0)
    verify(c)


def test_earned_compensation_survives_worker_death_restart_and_actual_recorded_replay(tmp_path, monkeypatch, caplog):
    config = _config(semantics=20)
    config["construction"].update(enabled=False, agent_initiation=False)
    config.setdefault("entrepreneurship", {})["enabled"] = False
    config.setdefault("households", {})["scheduled_births"] = []
    config.setdefault("lifecycle", {}).update(population_mode="drift", birth_annual_prob=0)
    config.setdefault("legal", {})["response_ticks"] = 2
    config.setdefault("llm", {})["institutional_role_purposes"] = True
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    worker_id = None
    original_draw = Lifecycle._draw

    def draw(self, tick, agent_id, mechanism):
        if tick == 1 and agent_id == worker_id and mechanism == "mortality":
            return 0.0
        return original_draw(self, tick, agent_id, mechanism)

    monkeypatch.setattr(Lifecycle, "_draw", draw)

    def open_seeded(path, settings, *, replay=False):
        nonlocal worker_id
        world = _world(path, settings, replay=replay)
        if world.store.tick != 0:
            return world
        e = world.economy
        employment = e.store.query_one("SELECT p.* FROM employments p JOIN agents a ON a.id=p.agent_id "
            "WHERE p.status='active' AND a.alive=1 AND a.age>=18 AND a.retired=0 AND a.kind='citizen' "
            "ORDER BY p.firm_id,p.id LIMIT 1")
        assert employment is not None
        worker_id = employment["agent_id"]
        e.store.update("agents", worker_id, population_tier="core", pinned_core=1)
        regulator = e.store.scalar("SELECT id FROM agents WHERE role='labor_regulator' AND alive=1")
        assert regulator is not None
        e.store.update("agents", regulator, population_tier="core", pinned_core=1)
        e.store.update("employments", employment["id"], wage_cents=510000, pay_interval_ticks=30, next_pay_tick=30)
        firm = e.firms.get(employment["firm_id"])
        currency = e.store.scalar("SELECT currency_code FROM accounts WHERE id=?", (firm["account_id"],))
        cash = e.ledger.balance(firm["account_id"])
        if cash > 0:
            e.ledger.transfer(0, firm["account_id"], e.ledger.system_account(SYS_EXTERNAL, currency_code=currency),
                              cash, kind="fixture_liquidity_withdrawal")
        product = json.loads(firm["product_json"])
        product.update(unit_price_cents=100, base_input_cost_cents=0)
        e.store.update("firms", firm["id"], product_json=json.dumps(product), inventory=50)
        e.store.record_metric(0, "tax_rate_bps", 2500)
        # Declared genesis work, large unpaid compensation and goods stock.
        # Ordinary payroll can pay part before adjudication; later sales fund
        # the remainder after the normally scheduled regulator's decision.
        e.daily_time.prepare_day(0)
        claim = e.store.query_one("SELECT * FROM wage_claims WHERE employment_id=?", (employment["id"],))
        assert claim is not None and claim["accrued_cents"] > 0
        through = e.store.scalar("SELECT MAX(id) FROM wage_accruals WHERE claim_id=?", (claim["id"],))
        evidence = e.store.scalar("SELECT id FROM events WHERE kind='wage_earned' AND subject_id=? ORDER BY id DESC LIMIT 1", (worker_id,))
        filed = e.legal.file_claim(0, worker_id, {"matter_type": "labor", "claim_type": "unpaid_wages",
            "claimant": {"type": "agent", "id": worker_id}, "respondent": {"type": "firm", "id": firm["id"]},
            "requested_remedy": {"type": "damages", "amount_cents": claim["accrued_cents"], "currency_code": currency,
                "wage_scopes": [{"claim_id": claim["id"], "through_accrual_id": through}]}})
        assert filed["ok"], filed
        admitted = e.legal.submit_filing(0, worker_id, {"matter_id": filed["matter_id"], "filer_type": "agent", "filer_id": worker_id,
            "filing_type": "stipulation", "evidence_event_ids": [evidence], "body": "Declared unpaid compensation for genesis work."})
        assert admitted["ok"], admitted
        return world

    path = tmp_path / "source.db"
    for day in (1, 2, 3):
        source = open_seeded(path, config)
        try:
            asyncio.run(source.step())
            assert source.store.scalar("SELECT alive FROM agents WHERE id=?", (worker_id,)) == 0
            if day == 3:
                award = source.store.query_one("SELECT * FROM legal_awards WHERE claimant_type='agent' AND claimant_id=?", (worker_id,))
                assert award is not None
                assert 0 < award["credited_cents"] < award["awarded_cents"]
                net = source.store.scalar("SELECT COALESCE(SUM(amount_cents-tax_cents),0) FROM legal_award_payments WHERE award_id=?", (award["id"],))
                assert net > 0, "the replay fixture must exercise actual new award collection"
                assert source.store.scalar("SELECT COALESCE(SUM(received_cents),0) FROM estate_receipts WHERE origin_transaction_id IN "
                    "(SELECT transaction_id FROM legal_award_payments WHERE award_id=?)", (award["id"],)) == net
                assert source.store.scalar("SELECT COUNT(*) FROM wage_claim_novations WHERE award_id=?", (award["id"],)) == 1
            source.economy.earned_wages.check_invariants()
            source.economy.legal_awards.check_invariants()
        finally:
            source.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    replay_config = copy.deepcopy(config)
    replay_config["replay_source_path"] = str(path)
    replay = open_seeded(tmp_path / "replay.db", replay_config, replay=True)
    try:
        for _ in range(3):
            asyncio.run(replay.step())
        proof = verify_replay(path, replay.store.path)
        assert proof["exact"], proof["differences"]
        replay.economy.earned_wages.check_invariants()
        replay.economy.legal_awards.check_invariants()
        assert not any("action.execution.failed" in record.message for record in caplog.records)
    finally:
        replay.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before

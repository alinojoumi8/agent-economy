import random

from engine.actions import ActionExecutor
from engine.core import Economy

from .conftest import make_agent, make_bank


def _world(store):
    economy = Economy(store, {"legal": {"enabled": True}}, random.Random(31), random.Random(32))
    economy.ensure_system_accounts()
    bank_id = make_bank(economy, reserves=5_000_000)
    founder, _ = make_agent(economy, bank_id, name="Founder", cash=2_000_000)
    buyer_founder, _ = make_agent(economy, bank_id, name="Buyer Founder", cash=2_000_000)
    third_founder, _ = make_agent(economy, bank_id, name="Third Founder", cash=2_000_000)
    vc, _ = make_agent(economy, bank_id, name="VC", cash=2_000_000, kind="staff",
                       occupation="venture capitalist", role="vc_partner")
    lawyer, _ = make_agent(economy, bank_id, name="Counsel", cash=100_000, kind="staff",
                           occupation="lawyer", role="lawyer")
    regulator, _ = make_agent(economy, bank_id, name="Regulator", cash=100_000, kind="staff",
                              occupation="regulator", role="competition_regulator")
    target = economy.firms.found_firm(0, founder, "Target AI", "tech", opening_capital_cents=200_000)
    acquirer = economy.firms.found_firm(0, buyer_founder, "Acquirer AI", "tech",
                                        opening_capital_cents=500_000)
    third = economy.firms.found_firm(0, third_founder, "Third AI", "tech",
                                     opening_capital_cents=200_000)
    return economy, ActionExecutor(economy), founder, buyer_founder, vc, lawyer, regulator, target, acquirer, third


def test_typed_term_sheet_diligence_ip_and_round_close(store):
    economy, executor, founder, _, vc, lawyer, _, target, _, _ = _world(store)
    ip = executor.execute_action(1, lawyer, {
        "type": "register_ip", "firm_id": target, "asset_type": "patent_like",
        "title": "Adaptive inference scheduler", "creator_agent_id": founder,
        "valuation_cents": 300_000,
    })
    assert ip["ok"]
    proposed = executor.execute_action(1, vc, {
        "type": "propose_term_sheet", "firm_id": target,
        "instrument_type": "preferred_equity", "amount_cents": 250_000,
        "pre_money_cents": 1_000_000, "equity_bps": 2000,
        "liquidation_preference_bps": 10000, "pro_rata": True,
    })
    sheet_id = proposed["term_sheet_id"]
    assert executor.execute_action(1, founder, {
        "type": "accept_term_sheet", "term_sheet_id": sheet_id})["status"] == "accepted"
    diligence = executor.execute_action(1, lawyer, {
        "type": "run_due_diligence", "term_sheet_id": sheet_id})
    assert diligence["ok"] and diligence["findings"]["registered_ip"] == 1
    before = economy.ledger.balance(int(economy.firms.get(target)["account_id"]))

    closed = executor.execute_action(1, vc, {
        "type": "close_funding_round", "term_sheet_id": sheet_id})

    assert closed["ok"]
    assert economy.ledger.balance(int(economy.firms.get(target)["account_id"])) == before + 250_000
    assert economy.startups.cap_table_reconciles(target)
    assert store.scalar("SELECT status FROM term_sheets WHERE id=?", (sheet_id,)) == "closed"
    assert economy.ledger.reconcile()[0]


def test_disclosures_are_derived_from_events_and_books(store):
    economy, executor, founder, _, _, _, _, target, _, _ = _world(store)
    source_event = store.log_event(2, "goods_sale", {
        "firm_id": target, "buyer_id": 999, "qty": 2,
        "unit_price_cents": 5000, "total_cents": 10000}, phase="MARKET")

    disclosure = executor.execute_action(2, founder, {
        "type": "publish_disclosure", "firm_id": target,
        "disclosure_type": "earnings", "lookback_ticks": 30})

    assert disclosure["ok"]
    assert disclosure["facts"]["revenue_cents"] == 10000
    row = store.query_one("SELECT * FROM firm_disclosures WHERE id=?", (disclosure["disclosure_id"],))
    assert str(source_event) in row["source_event_ids_json"]


def test_merger_screen_requires_remedy_and_closes_with_conserved_cash(store):
    economy, executor, _, buyer_founder, _, _, regulator, target, acquirer, _ = _world(store)
    target_founder = int(economy.firms.get(target)["founder_agent_id"])
    proposed = executor.execute_action(3, buyer_founder, {
        "type": "propose_merger", "acquirer_firm_id": acquirer,
        "target_firm_id": target, "price_cents": 100_000})
    merger_id = proposed["merger_id"]
    assert executor.execute_action(3, target_founder, {
        "type": "approve_merger", "merger_id": merger_id})["ok"]
    challenged = executor.execute_action(3, regulator, {
        "type": "review_merger", "merger_id": merger_id})
    assert challenged["outcome"] == "challenged"

    # A separate deal demonstrates a bounded interoperability remedy.
    store.update("mergers", merger_id, status="pending_review")
    store.execute("DELETE FROM merger_reviews WHERE merger_id=?", (merger_id,))
    remedied = executor.execute_action(3, regulator, {
        "type": "review_merger", "merger_id": merger_id,
        "remedy": {"type": "interoperability", "duration_ticks": 180}})
    assert remedied["outcome"] == "approved_with_remedy"
    before_total = sum(int(row["balance_cents"]) for row in store.query("SELECT balance_cents FROM accounts"))

    closed = executor.execute_action(3, buyer_founder, {
        "type": "close_merger", "merger_id": merger_id})

    assert closed["ok"]
    assert store.scalar("SELECT status FROM firms WHERE id=?", (target,)) == "acquired"
    assert sum(int(row["balance_cents"]) for row in store.query("SELECT balance_cents FROM accounts")) == before_total
    assert economy.ledger.reconcile()[0]

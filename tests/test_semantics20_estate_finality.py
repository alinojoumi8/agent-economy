"""Completed distributions are final; admitted claims follow retained assets and later cash."""
import asyncio
import copy
import hashlib
import json
import sqlite3
from types import SimpleNamespace

import pytest

from engine.estates import EstateError
from engine.actions import ActionExecutor
from engine.lifecycle import Lifecycle
from engine.project_rights import interests_at
from research.export_bundle import export_bundle, validate_bundle
from research.hashing import canonical_hashes
from world.replay_verify import verify_replay

from .conftest import make_agent
from .test_semantics13_construction import _config, _owner
from .test_semantics17_household_decisions import _world
from .test_semantics20_estate_cases import estate_case, validate
from .test_semantics20_estate_disputes import reserve
from .test_semantics20_estate_property import personal_loan
from .test_semantics20_legal_awards import award_case, check, claim, decide, receive
from .test_semantics20_project_rights import property_world
from .test_semantics20_property_sales import sale_case as property_sale_case, bid as property_bid, accept as property_accept
from .test_semantics20_unlisted_sales import sale_case as share_sale_case, bid as share_bid, accept as share_accept


POLICY = "prospective_receipts_no_clawback_v1"


def legal_context(e, person, wallet, heir_wallet):
    bank = e.store.scalar("SELECT bank_id FROM accounts WHERE id=?", (wallet,))
    region = e.store.scalar("SELECT region_id FROM agents WHERE id=?", (person,))
    creditor, creditor_wallet = make_agent(e, bank, "Later claimant", cash=0, region_id=region)
    currency = e.store.scalar("SELECT currency_code FROM accounts WHERE id=?", (wallet,))
    if e.store.scalar("SELECT currency_code FROM accounts WHERE id=?", (creditor_wallet,)) != currency:
        creditor_wallet = e.ledger.create_account("agent", creditor, "checking", bank_id=bank,
            currency_code=currency, label="Later claimant: matching currency")
        e.store.update("agents", creditor, checking_account_id=creditor_wallet)
    judge, _ = make_agent(e, bank, "Independent finality judge", cash=0, region_id=region,
                          kind="staff", occupation="judge", role="judge")
    for actor in (creditor, judge):
        e.households.register_person(0, actor, "genesis")
    return SimpleNamespace(e=e, person=person, wallet=wallet, heir_wallet=heir_wallet,
        creditor=creditor, creditor_wallet=creditor_wallet, judge=judge, executor=ActionExecutor(e))


def test_estate_records_immutable_finality_policy_in_its_opening_evidence(award_case):
    c = award_case
    c.e.lifecycle.settle_death(2, c.person)
    estate = c.e.store.query_one("SELECT * FROM estate_cases WHERE deceased_agent_id=?", (c.person,))
    assert estate["distribution_finality_policy"] == POLICY
    event = c.e.store.query_one("SELECT * FROM events WHERE id=?", (estate["completed_event_id"],))
    payload = json.loads(event["payload_json"])
    assert payload["distribution_finality_policy"] == POLICY
    assert c.e.estate_cases.finality_at(estate["id"], 1) is None
    status = c.e.estate_cases.finality_at(estate["id"], 2)
    assert status["opening_inventory_recorded"]
    assert status["distribution_finality_policy"] == POLICY
    assert status["outstanding_claims_by_currency"] == []
    assert status["unresolved_disputes"] == 0
    with pytest.raises(sqlite3.IntegrityError):
        c.e.store.update("estate_cases", estate["id"], distribution_finality_policy=POLICY)
    changed = dict(payload)
    changed.pop("distribution_finality_policy")
    c.e.store.update("events", event["id"], payload_json=json.dumps(changed))
    with pytest.raises(EstateError, match="finality"):
        c.e.estate_cases.check_invariants()
    c.e.store.update("events", event["id"], payload_json=event["payload_json"])
    check(c)


@pytest.mark.parametrize("receipt_before_admission", [False, True])
def test_same_tick_admission_preserves_earlier_cash_and_collects_only_later_receipts(award_case, receipt_before_admission):
    c = award_case
    c.e.lifecycle.settle_death(2, c.person)
    opening = [dict(row) for row in c.e.store.query("SELECT * FROM estate_disbursements ORDER BY id")]
    assert c.e.ledger.balance(c.heir_wallet) == 100
    if receipt_before_admission:
        receive(c, 90, tick=3)
    frontier = c.e.estate_cases._receipt_frontier()
    matter, event = claim(c, 80, contract=False, tick=3)
    held = reserve(c, matter)
    assert held["registered_after_receipt_id"] == frontier
    assert c.e.ledger.balance(held["escrow_account_id"]) == 0
    if not receipt_before_admission:
        receive(c, 90, tick=3)
    receive(c, 30, tick=3)
    assert c.e.ledger.balance(c.heir_wallet) == (190 if receipt_before_admission else 140)
    assert c.e.ledger.balance(held["escrow_account_id"]) == (30 if receipt_before_admission else 80)
    assert [dict(c.e.store.query_one("SELECT * FROM estate_disbursements WHERE id=?", (row["id"],))) for row in opening] == opening
    assert decide(c, matter, event, 60, tick=5)["ok"]
    receive(c, 40, tick=6)
    assert c.e.ledger.balance(c.creditor_wallet) == 60
    assert c.e.ledger.balance(c.heir_wallet) == 200
    assert not c.e.store.scalar("SELECT id FROM ledger_entries WHERE account_id=? AND delta_cents<0", (c.heir_wallet,))
    estate = c.e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (c.person,))
    before_read = canonical_hashes(c.e.store)
    status = c.e.estate_cases.finality_at(estate, 3)
    assert status["opening_inventory_recorded"] and status["unresolved_disputes"] == 1
    assert status["outstanding_claims_by_currency"] == []
    assert c.e.estate_cases.finality_at(estate, 2)["unresolved_disputes"] == 0
    assert c.e.estate_cases.finality_at(estate, 5)["outstanding_claims_by_currency"] == (
        [{"currency_code": "USD", "claim_count": 1, "remaining_cents": 30}] if receipt_before_admission else [])
    assert c.e.estate_cases.finality_at(estate, 6)["outstanding_claims_by_currency"] == []
    assert canonical_hashes(c.e.store) == before_read
    check(c)


@pytest.mark.parametrize("sold", [False, True])
def test_late_claim_preserves_completed_private_share_disposition_and_its_same_tick_order(estate_case, sold):
    e, _, person, wallet, _, heir_wallet = estate_case
    legal = legal_context(e, person, wallet, heir_wallet)
    c = share_sale_case(estate_case)
    if sold:
        offer = share_bid(c)
        assert offer["ok"], offer
        assert share_accept(c, offer["bid_id"])["ok"]
    else:
        receive(legal, 100, tick=3)
    owner = c.buyer if sold else c.heir
    assert e.exchange.shares_held(c.firm, "agent", owner) == 10
    release = dict(e.store.query_one("SELECT * FROM estate_security_releases WHERE lot_id=?", (c.lot,)))
    holdings = [dict(row) for row in e.store.query("SELECT * FROM shares WHERE firm_id=? ORDER BY holder_type,holder_id", (c.firm,))]
    cash = e.ledger.balance(heir_wallet)
    matter, event = claim(legal, 80, contract=False, tick=3)
    held = reserve(legal, matter)
    assert release["tick"] == held["registered_tick"]
    assert release["reserve_frontier"] < held["id"]
    assert e.ledger.balance(heir_wallet) == cash
    assert decide(legal, matter, event, 60, tick=5)["ok"]
    receive(legal, 90, tick=6)
    assert e.ledger.balance(legal.creditor_wallet) == 60
    assert e.ledger.balance(heir_wallet) == cash + 30
    assert [dict(row) for row in e.store.query("SELECT * FROM shares WHERE firm_id=? ORDER BY holder_type,holder_id", (c.firm,))] == holdings
    assert dict(e.store.query_one("SELECT * FROM estate_security_releases WHERE lot_id=?", (c.lot,))) == release
    assert e.estate_cases.finality_at(c.estate, 2)["retained_security_lots"] == 1
    assert e.estate_cases.finality_at(c.estate, 3)["retained_security_lots"] == 0
    validate(e)


@pytest.mark.parametrize("sold", [False, True])
def test_late_claim_preserves_completed_property_disposition_and_original_title(property_world, sold):
    world, owner, heir = property_world
    legal = legal_context(world.economy, owner["id"], owner["checking_account_id"], heir["checking_account_id"])
    c = property_sale_case(property_world)
    if sold:
        offer = property_bid(c)
        assert offer["ok"], offer
        assert property_accept(c, offer["bid_id"])["ok"]
    else:
        receive(legal, 100, tick=11, currency=c.currency)
    holder = c.buyer["id"] if sold else heir["id"]
    assert [row["agent_id"] for row in interests_at(c.store, c.project, 11)] == [holder]
    lots = [dict(row) for row in c.store.query("SELECT * FROM project_interest_lots WHERE project_id=? ORDER BY id", (c.project,))]
    release = dict(c.store.query_one("SELECT * FROM estate_project_releases WHERE custody_id=?", (c.custody,)))
    cash = c.e.ledger.balance(legal.heir_wallet)
    matter, event = claim(legal, 80, contract=False, tick=11, currency=c.currency)
    assert release["tick"] == reserve(legal, matter)["registered_tick"]
    assert release["reserve_frontier"] < reserve(legal, matter)["id"]
    assert c.e.ledger.balance(legal.heir_wallet) == cash
    assert decide(legal, matter, event, 60, tick=13)["ok"]
    receive(legal, 90, tick=14, currency=c.currency)
    assert c.e.ledger.balance(legal.creditor_wallet) == 60
    assert c.e.ledger.balance(legal.heir_wallet) == cash + 30
    assert [dict(row) for row in c.store.query("SELECT * FROM project_interest_lots WHERE project_id=? ORDER BY id", (c.project,))] == lots
    assert dict(c.store.query_one("SELECT * FROM estate_project_releases WHERE custody_id=?", (c.custody,))) == release
    assert c.e.estate_cases.finality_at(c.estate, 10)["retained_property_interests"] == 1
    assert c.e.estate_cases.finality_at(c.estate, 11)["retained_property_interests"] == 0
    check(legal)
    c.e.project_rights.check_invariants()


def test_late_claim_can_collect_from_an_asset_that_the_estate_still_retains(estate_case):
    e, _, person, wallet, _, heir_wallet = estate_case
    legal = legal_context(e, person, wallet, heir_wallet)
    c = share_sale_case(estate_case)
    matter, event = claim(legal, 80, contract=False, tick=2)
    assert decide(legal, matter, event, 60, tick=4)["ok"]
    status = e.estate_cases.finality_at(c.estate, 4)
    assert status["retained_security_lots"] == 1
    assert status["outstanding_claims_by_currency"] == [{"currency_code": "USD", "claim_count": 2, "remaining_cents": 160}]
    offer = share_bid(c, tick=5, expires_tick=8)
    assert offer["ok"], offer
    assert share_accept(c, offer["bid_id"], tick=6)["ok"]
    assert e.store.scalar("SELECT status FROM loans WHERE id=?", (c.loan,)) == "paid"
    assert e.ledger.balance(legal.creditor_wallet) == 60
    assert e.ledger.balance(heir_wallet) == 40
    assert e.estate_cases.finality_at(c.estate, 6)["outstanding_claims_by_currency"] == []
    validate(e)


def test_late_claim_does_not_reopen_a_beneficiarys_completed_succession(award_case):
    c = award_case
    successor, successor_wallet = make_agent(c.e, c.bank, "Later beneficiary", cash=0, region_id=1)
    c.e.households.register_person(0, successor, "genesis")
    c.e.store.insert("social_ties", agent_a=c.heir, agent_b=successor, weight=100)
    c.e.lifecycle.settle_death(2, c.person)
    c.e.lifecycle.settle_death(3, c.heir)
    assert c.e.ledger.balance(successor_wallet) == 100
    earlier = [dict(row) for row in c.e.store.query("SELECT * FROM estate_disbursements ORDER BY id")]
    matter, event = claim(c, 80, contract=False, tick=4)
    assert c.e.ledger.balance(successor_wallet) == 100
    receive(c, 90, tick=5)
    assert decide(c, matter, event, 60, tick=6)["ok"]
    assert c.e.ledger.balance(c.creditor_wallet) == 60
    assert c.e.ledger.balance(successor_wallet) == 130
    assert [dict(c.e.store.query_one("SELECT * FROM estate_disbursements WHERE id=?", (row["id"],))) for row in earlier] == earlier
    assert not c.e.store.scalar("SELECT id FROM ledger_entries WHERE account_id=? AND delta_cents<0", (successor_wallet,))
    check(c)


def test_late_claim_respects_currency_boundaries_after_initial_distribution(award_case):
    c = award_case
    euro = c.e.ledger.create_account("agent", c.person, "fx", currency_code="EUR")
    receive(c, 100, tick=0, wallet=euro, currency="EUR")
    c.e.lifecycle.settle_death(2, c.person)
    heir_euro = c.e.store.scalar("SELECT id FROM accounts WHERE owner_type='agent' AND owner_id=? AND currency_code='EUR'", (c.heir,))
    assert c.e.ledger.balance(heir_euro) == 100
    matter, event = claim(c, 80, contract=False, tick=3)
    receive(c, 90, tick=4, wallet=euro, currency="EUR")
    assert c.e.ledger.balance(heir_euro) == 190
    assert c.e.ledger.balance(reserve(c, matter)["escrow_account_id"]) == 0
    assert decide(c, matter, event, 60, tick=5)["ok"]
    estate = c.e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (c.person,))
    assert c.e.estate_cases.finality_at(estate, 5)["outstanding_claims_by_currency"] == [{"currency_code": "USD", "claim_count": 1, "remaining_cents": 60}]
    receive(c, 90, tick=6)
    assert c.e.ledger.balance(c.heir_wallet) == 130
    assert c.e.ledger.balance(heir_euro) == 190
    assert c.e.ledger.balance(c.creditor_wallet) == 60
    check(c)


def test_failed_and_duplicate_late_admission_preserve_final_distributions(award_case, monkeypatch):
    c = award_case
    c.e.lifecycle.settle_death(2, c.person)
    matter, event = claim(c, 80, contract=False, tick=3)
    before = canonical_hashes(c.e.store)
    insert = c.e.store.insert

    def fail(table, **fields):
        if table == "estate_claims" and fields.get("kind") == "legal_award":
            raise RuntimeError("injected finality admission failure")
        return insert(table, **fields)

    with monkeypatch.context() as context:
        context.setattr(c.e.store, "insert", fail)
        with pytest.raises(RuntimeError, match="injected finality"):
            decide(c, matter, event, 60, tick=5)
    assert canonical_hashes(c.e.store) == before
    assert c.e.ledger.balance(c.heir_wallet) == 100
    result = decide(c, matter, event, 60, tick=5)
    assert result["ok"], result
    estate = c.e.store.query_one("SELECT * FROM estate_cases WHERE deceased_agent_id=?", (c.person,))
    award = c.e.store.query_one("SELECT * FROM legal_awards WHERE id=?", (result["enforcement"]["award_id"],))
    admission = c.e.store.scalar("SELECT id FROM estate_claims WHERE kind='legal_award' AND source_id=?", (award["id"],))
    before_retry = canonical_hashes(c.e.store)
    assert c.e.estate_cases.register_award(5, estate, award) == admission
    assert canonical_hashes(c.e.store) == before_retry
    receive(c, 90, tick=6)
    assert c.e.ledger.balance(c.heir_wallet) == 130
    assert c.e.ledger.balance(c.creditor_wallet) == 60
    check(c)


def test_late_claim_after_property_sale_collects_from_other_retained_shares(property_world):
    world, owner, heir = property_world
    e = world.economy
    legal = legal_context(e, owner["id"], owner["checking_account_id"], heir["checking_account_id"])
    firm = e.firms.found_firm(0, owner["id"], "Mixed estate issuer", "manufacturing",
        opening_capital_cents=10_000, shares=10)
    _, earlier_loan = personal_loan(e, owner["id"], 400)
    c = property_sale_case(property_world)
    initial_heir_cash = e.ledger.balance(legal.heir_wallet)
    offer = property_bid(c, amount_cents=200)
    assert offer["ok"], offer
    assert property_accept(c, offer["bid_id"])["ok"]
    title = [dict(row) for row in c.store.query("SELECT * FROM project_interest_lots WHERE project_id=? ORDER BY id", (c.project,))]
    matter, event = claim(legal, 80, contract=False, tick=11, currency=c.currency)
    status = e.estate_cases.finality_at(c.estate, 11)
    assert status["retained_property_interests"] == 0 and status["retained_security_lots"] == 1
    assert status["outstanding_claims_by_currency"] == [{"currency_code": c.currency, "claim_count": 2, "remaining_cents": 300}]
    assert status["unresolved_disputes"] == 1
    assert decide(legal, matter, event, 60, tick=13)["ok"]
    lot = c.store.scalar("SELECT id FROM estate_security_lots WHERE estate_id=? AND firm_id=?", (c.estate, firm))
    bought = c.world.runtime.executor.execute_action(14, c.buyer["id"], {"type": "place_estate_unlisted_bid",
        "lot_id": lot, "qty": 10, "buyer_account_id": c.buyer["checking_account_id"], "amount_cents": 500,
        "currency_code": c.currency, "expires_tick": 18, "request_key": "remaining-private-shares"})
    assert bought["ok"], bought
    sold = c.world.runtime.executor.execute_action(15, c.representative,
        {"type": "accept_estate_unlisted_bid", "bid_id": bought["bid_id"]})
    assert sold["ok"], sold
    assert all(c.store.scalar("SELECT status FROM loans WHERE id=?", (loan,)) == "paid" for loan in (earlier_loan, c.loan))
    assert e.ledger.balance(legal.creditor_wallet) == 60
    assert e.ledger.balance(legal.heir_wallet) == initial_heir_cash + 140
    assert e.exchange.shares_held(firm, "agent", c.buyer["id"]) == 10
    assert [dict(row) for row in c.store.query("SELECT * FROM project_interest_lots WHERE project_id=? ORDER BY id", (c.project,))] == title
    assert e.estate_cases.finality_at(c.estate, 15)["retained_security_lots"] == 0
    assert e.estate_cases.finality_at(c.estate, 15)["outstanding_claims_by_currency"] == []
    check(legal)
    e.project_rights.check_invariants()


def test_late_claim_and_funded_collection_preserve_final_transfers_across_restart_export_and_replay(tmp_path, monkeypatch, caplog):
    config = _config(semantics=20)
    config.setdefault("households", {})["scheduled_births"] = []
    config.setdefault("lifecycle", {}).update(population_mode="drift", birth_annual_prob=0,
        illness_onset_annual_young=0, illness_onset_annual_old=0)
    config.setdefault("legal", {})["response_ticks"] = 2
    config.setdefault("llm", {})["institutional_role_purposes"] = True
    config.update(checkpoint_every=0, checkpoint_dir=str(tmp_path / "checkpoints"))
    ids = {}
    original_draw = Lifecycle._draw

    def draw(self, tick, actor, mechanism):
        if tick == 1 and actor == ids["owner"] and mechanism == "mortality":
            return 0.0
        return original_draw(self, tick, actor, mechanism)

    monkeypatch.setattr(Lifecycle, "_draw", draw)

    def open_seeded(path, settings, *, replay=False):
        world = _world(path, settings, replay=replay)
        e, store = world.economy, world.store
        if store.tick == 0:
            owner = _owner(world)
            currency = store.scalar("SELECT currency_code FROM accounts WHERE id=?", (owner["checking_account_id"],))
            actors = store.query("SELECT a.* FROM agents a JOIN accounts w ON w.id=a.checking_account_id "
                "WHERE a.alive=1 AND a.age>=18 AND a.retired=0 AND a.kind='citizen' AND a.region_id=? "
                "AND a.id<>? AND w.currency_code=? AND w.balance_cents>=10000 ORDER BY a.id LIMIT 3",
                (owner["region_id"], owner["id"], currency))
            assert len(actors) == 3
            heir, creditor, payer = actors
            judge = store.scalar("SELECT id FROM agents WHERE alive=1 AND role='labor_regulator' ORDER BY id LIMIT 1")
            assert judge is not None
            store.execute("DELETE FROM social_ties WHERE agent_a=? OR agent_b=?", (owner["id"], owner["id"]))
            store.insert("social_ties", agent_a=owner["id"], agent_b=heir["id"], weight=100)
            firm = e.firms.found_firm(0, owner["id"], "Final inheritance issuer", "manufacturing",
                opening_capital_cents=10_000, shares=10)
            proposal = e.legal.propose_contract(0, owner["id"], {"contract_type": "supplier", "title": "Declared later estate receipt",
                "parties": [{"type": "agent", "id": owner["id"], "role": "supplier"},
                            {"type": "agent", "id": payer["id"], "role": "buyer"}],
                "clauses": [{"clause_key": "price", "clause_type": "payment", "terms": {"obligor_role": "buyer",
                    "obligee_role": "supplier", "amount_cents": 2000, "due_tick": 4, "currency_code": currency}}]})
            assert proposal["ok"], proposal
            for actor in (owner["id"], payer["id"]):
                assert e.legal.accept_contract(0, actor, proposal["contract_id"], "agent", actor)["ok"]
            obligation = store.scalar("SELECT id FROM obligations WHERE contract_id=?", (proposal["contract_id"],))
            evidence = store.log_event(0, "fixture_loss_evidence", {"amount_cents": 1000, "currency_code": currency}, phase="EXECUTION")
            ids.update(owner=owner["id"], heir=heir["id"], creditor=creditor["id"], payer=payer["id"], judge=judge,
                owner_wallet=owner["checking_account_id"], firm=firm, obligation=obligation, evidence=evidence, currency=currency)
            for actor in (ids["owner"], ids["heir"], ids["creditor"], ids["payer"], judge):
                store.update("agents", actor, population_tier="core", pinned_core=1,
                    cadence_json='{"act":1,"portfolio":9999,"career":9999,"news":9999}')
            e.city.initialize(0)
        for purpose, original in list(world.gateway.scripted.policies.items()):
            def scenario(context, original=original):
                if replay:
                    raise AssertionError("replay must use recorded decisions")
                actor = context.get("agent", {}).get("id")
                if actor not in (ids["owner"], ids["heir"], ids["creditor"], ids["payer"], ids["judge"]):
                    return original(context)
                tick = context["tick"]
                action = {"type": "do_nothing"}
                matter = store.scalar("SELECT id FROM legal_matters WHERE claimant_type='agent' AND claimant_id=? "
                    "AND respondent_type='agent' AND respondent_id=? ORDER BY id LIMIT 1", (ids["creditor"], ids["owner"]))
                if actor == ids["creditor"] and tick == 2:
                    action = {"type": "file_claim", "matter_type": "labor", "claim_type": "stipulated_loss",
                        "claimant": {"type": "agent", "id": ids["creditor"]},
                        "respondent": {"type": "agent", "id": ids["owner"]},
                        "requested_remedy": {"type": "damages", "amount_cents": 1000, "currency_code": ids["currency"]}}
                elif actor == ids["creditor"] and tick == 3 and matter:
                    action = {"type": "submit_filing", "matter_id": matter, "filer_type": "agent", "filer_id": actor,
                        "filing_type": "stipulation", "evidence_event_ids": [ids["evidence"]], "body": "Declared loss scenario."}
                elif actor == ids["judge"] and tick == 4 and matter:
                    action = {"type": "issue_legal_decision", "matter_id": matter, "outcome": "claimant",
                        "findings": [{"key": "liability", "value": True}], "evidence_event_ids": [ids["evidence"]],
                        "remedy": {"type": "damages", "amount_cents": 1000, "currency_code": ids["currency"]}}
                elif actor == ids["payer"] and tick == 4:
                    action = {"type": "perform_obligation", "obligation_id": ids["obligation"]}
                return {"reasoning": "Declared late claim, independent decision and funded contract payment.", "actions": [action]}
            world.gateway.scripted.register(purpose, scenario)
        return world

    path = tmp_path / "source-finality.db"
    committed = None
    position_history = {}
    opening_payments = None
    released_shares = None
    for day in range(1, 5):
        source = open_seeded(path, config)
        try:
            if committed is not None:
                assert canonical_hashes(source.store)["authoritative_sha256"] == committed
            asyncio.run(source.step())
            estate = source.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (ids["owner"],))
            assert estate is not None
            status = source.economy.estate_cases.finality_at(estate, day)
            assert status["opening_inventory_recorded"] and status["distribution_finality_policy"] == POLICY
            assert source.economy.exchange.shares_held(ids["firm"], "agent", ids["heir"]) == 10
            if day == 1:
                opening_payments = [dict(row) for row in source.store.query("SELECT d.* FROM estate_disbursements d "
                    "JOIN estate_receipts r ON r.id=d.receipt_id WHERE r.estate_id=? AND d.beneficiary_id IS NOT NULL ORDER BY d.id", (estate,))]
                assert opening_payments
                released_shares = [dict(row) for row in source.store.query("SELECT * FROM share_movements WHERE firm_id=? ORDER BY id", (ids["firm"],))]
                assert any(row["from_holder_id"] == ids["owner"] and row["to_holder_id"] == ids["heir"]
                           and row["qty"] == 10 for row in released_shares)
            else:
                assert [dict(source.store.query_one("SELECT * FROM estate_disbursements WHERE id=?", (row["id"],))) for row in opening_payments] == opening_payments
                assert [dict(row) for row in source.store.query("SELECT * FROM share_movements WHERE firm_id=? ORDER BY id", (ids["firm"],))] == released_shares
            if day == 2:
                assert status["unresolved_disputes"] == 1
                assert source.store.scalar("SELECT SUM(a.balance_cents) FROM estate_legal_reserves r JOIN accounts a ON a.id=r.escrow_account_id WHERE r.estate_id=?", (estate,)) == 0
            if day == 4:
                assert source.store.scalar("SELECT status FROM obligations WHERE id=?", (ids["obligation"],)) == "performed"
                assert source.store.scalar("SELECT SUM(p.amount_cents) FROM legal_award_payments p JOIN legal_awards a ON a.id=p.award_id "
                    "WHERE a.respondent_type='agent' AND a.respondent_id=? AND a.claimant_id=?", (ids["owner"], ids["creditor"])) == 1000
                assert status["outstanding_claims_by_currency"] == [] and status["unresolved_disputes"] == 0
                assert source.economy.estate_cases.finality_at(estate, 2)["unresolved_disputes"] == 1
                manifest = validate_bundle(export_bundle(source.store, tmp_path / "finality-export"))
                assert manifest["tables"]["estate_cases"]["row_count"] >= 1
            validate(source.economy)
            source.economy.legal_awards.check_invariants()
            from research.household_positions import household_positions
            from research.metric_registry import read_metric_observation
            for earlier_tick, earlier_positions in position_history.items():
                assert household_positions(source.store, tick=earlier_tick) == earlier_positions
            position_history[day] = household_positions(source.store, tick=day)
            for currency, distribution in position_history[day]["cash_distribution"].items():
                observation = read_metric_observation(source.store, f"cash_gini:{currency}", day)
                assert observation["value"] == distribution["gini"]
            committed = canonical_hashes(source.store)["authoritative_sha256"]
        finally:
            source.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    settings = copy.deepcopy(config)
    settings["replay_source_path"] = str(path)
    replay = open_seeded(tmp_path / "replay-finality.db", settings, replay=True)
    try:
        for _ in range(4):
            asyncio.run(replay.step())
        proof = verify_replay(path, replay.store.path)
        assert proof["exact"], proof["differences"]
        for day, positions in position_history.items():
            assert household_positions(replay.store, tick=day) == positions
        validate(replay.economy)
        assert not any("action.execution.failed" in record.message for record in caplog.records)
    finally:
        replay.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before

"""A funded buyer receives retained title while creditors receive real cash."""
from types import SimpleNamespace
import asyncio
import copy
import hashlib
import json
import sqlite3

import pytest

from agents.policies import scripted_decision
from agents.participant import ParticipantError, ParticipantService
from agents.citizen_actions import citizen_world_action_types
from engine.estates import EstateError
from engine.lifecycle import Lifecycle
from engine.project_rights import interests_at, steward_at
from research.export_bundle import export_bundle, validate_bundle
from research.hashing import canonical_hashes
from world.replay_verify import verify_replay

from .test_semantics13_construction import _advance_to_building, _config, _owner, _permit_clerk
from .test_semantics17_household_decisions import _world
from .test_semantics20_estate_property import drain_cash, personal_loan
from .test_semantics20_project_rights import property_world, finish, join_household, validate


def sale_case(property_world, public=False, guardian=False, completed=True):
    world, owner, heir = property_world
    e = world.economy
    currency = e.store.scalar("SELECT currency_code FROM accounts WHERE id=?", (owner["checking_account_id"],))
    buyer = e.store.query_one("SELECT a.* FROM agents a JOIN accounts w ON w.id=a.checking_account_id "
        "WHERE a.alive=1 AND a.age>=18 AND a.id NOT IN (?,?) AND a.region_id=? "
        "AND w.currency_code=? AND w.balance_cents>=300 ORDER BY a.id LIMIT 1",
        (owner["id"], heir["id"], owner["region_id"], currency))
    assert buyer is not None
    _, loan = personal_loan(e, owner["id"], 100)
    project, _ = _advance_to_building(world, owner)
    if completed:
        finish(world, owner["id"], project)
    drain_cash(e, owner["id"], 8)
    child = None
    if guardian:
        child = e.households.birth(8, owner["id"])
        join_household(e, heir["id"], owner["id"], 8)
        e.households.reconcile_custody(8)
    if public:
        e.store.execute("DELETE FROM social_ties WHERE agent_a=? OR agent_b=?", (owner["id"], owner["id"]))
    e.lifecycle.settle_death(9, owner["id"])
    estate = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (owner["id"],))
    custody = e.estate_property.pending(estate)[0]
    representative = e.estate_property.representatives(estate)[0]["actor_id"]
    return SimpleNamespace(world=world, e=e, store=e.store, owner=owner, heir=heir,
        buyer=buyer, loan=loan, project=project, custody=custody["id"], estate=estate,
        representative=representative, currency=currency, child=child)


def bid(c, tick=10, **changes):
    action = dict(type="place_estate_property_bid", custody_id=c.custody,
        buyer_account_id=c.buyer["checking_account_id"], amount_cents=300,
        currency_code=c.currency, expires_tick=14, request_key="funded-property")
    action.update(changes)
    return c.world.runtime.executor.execute_action(tick, c.buyer["id"], action)


def accept(c, bid_id, tick=11, actor=None):
    return c.world.runtime.executor.execute_action(tick, c.representative if actor is None else actor,
        dict(type="accept_estate_property_bid", bid_id=bid_id))


@pytest.mark.parametrize("public", [False, True])
def test_funded_sale_pays_creditors_and_preserves_original_project_history(property_world, public):
    c = sale_case(property_world, public)
    original = dict(c.e.construction._project(c.project))
    contributions = [dict(row) for row in c.store.query("SELECT * FROM construction_contributions WHERE project_id=?", (c.project,))]
    before_buyer = c.e.ledger.balance(c.buyer["checking_account_id"])
    before_heir = c.e.ledger.balance(c.heir["checking_account_id"])
    trades = c.store.scalar("SELECT COUNT(*) FROM trades")
    offered = bid(c)
    assert offered["ok"], offered
    assert c.e.ledger.balance(c.buyer["checking_account_id"]) == before_buyer
    assert interests_at(c.store, c.project)[0]["agent_id"] == c.owner["id"]
    result = accept(c, offered["bid_id"])
    assert result["ok"], result
    assert c.e.ledger.balance(c.buyer["checking_account_id"]) == before_buyer - 300
    assert c.e.ledger.balance(c.owner["checking_account_id"]) == 0
    assert c.store.scalar("SELECT status FROM loans WHERE id=?", (c.loan,)) == "paid"
    assert c.e.ledger.balance(c.heir["checking_account_id"]) == before_heir + (0 if public else 200)
    assert [(p["agent_id"], p["numerator"], p["denominator"]) for p in interests_at(c.store, c.project)] == [(c.buyer["id"], "1", "1")]
    assert interests_at(c.store, c.project, 10)[0]["agent_id"] == c.owner["id"]
    assert steward_at(c.store, c.project)["steward_agent_id"] == c.buyer["id"]
    assert c.store.scalar("SELECT disposition FROM estate_project_releases WHERE custody_id=?", (c.custody,)) == "sold"
    assert c.e.estate_administration.current(c.estate) is None
    assert dict(c.e.construction._project(c.project)) == original
    assert [dict(row) for row in c.store.query("SELECT * FROM construction_contributions WHERE project_id=?", (c.project,))] == contributions
    assert c.store.scalar("SELECT COUNT(*) FROM trades") == trades
    validate(c.world)


def economic_state(c):
    return {name: value for name, value in canonical_hashes(c.store)["tables"].items()
            if name not in {"action_proposals", "events"}}


def test_cross_bank_sale_records_the_cash_payment_and_both_reserve_legs(property_world):
    c = sale_case(property_world)
    reserve = c.e.ledger.create_account("bank", None, "reserve", currency_code=c.currency,
        opening_cents=10_000, tick=10, label="Property buyer bank reserves")
    equity = c.e.ledger.create_account("bank", None, "equity", currency_code=c.currency,
        label="Property buyer bank equity")
    bank = c.store.insert("banks", name="Property buyer bank", reserve_account_id=reserve,
        equity_account_id=equity, currency_code=c.currency, region_id=c.owner["region_id"],
        risk_policy_json="{}", reserve_requirement_bps=1000, status="open")
    for account in (reserve, equity):
        c.store.update("accounts", account, owner_id=bank)
    wallet = c.e.ledger.create_account("agent", c.buyer["id"], "checking", bank_id=bank,
        currency_code=c.currency, label="Property buyer's second bank wallet")
    c.e.ledger.transfer(10, c.buyer["checking_account_id"], wallet, 300)
    offered = bid(c, buyer_account_id=wallet)
    assert offered["ok"], offered
    before = c.e.ledger.balance(reserve)
    result = accept(c, offered["bid_id"])
    assert result["ok"], result
    nominee_reserve = c.store.scalar("SELECT b.reserve_account_id FROM banks b JOIN accounts a "
        "ON a.bank_id=b.id WHERE a.id=?", (c.owner["checking_account_id"],))
    legs = {row["account_id"]: row["delta_cents"] for row in c.store.query(
        "SELECT account_id,delta_cents FROM ledger_entries WHERE txn_id=?", (result["transaction_id"],))}
    assert legs == {wallet: -300, c.owner["checking_account_id"]: 300, reserve: -300, nominee_reserve: 300}
    assert c.e.ledger.balance(reserve) == before - 300
    assert c.e.ledger.balance(wallet) == 0
    assert c.store.scalar("SELECT status FROM loans WHERE id=?", (c.loan,)) == "paid"
    validate(c.world)


def test_buyer_completes_an_unfinished_project_while_the_original_funder_keeps_refunds(property_world):
    c = sale_case(property_world, completed=False)
    original = dict(c.e.construction._project(c.project))
    contributions = [dict(row) for row in c.store.query(
        "SELECT * FROM construction_contributions WHERE project_id=? ORDER BY id", (c.project,))]
    offered = bid(c)
    assert offered["ok"], offered
    result = accept(c, offered["bid_id"])
    assert result["ok"], result
    assert steward_at(c.store, c.project)["steward_agent_id"] == c.buyer["id"]
    finish(c.world, c.buyer["id"], c.project, start=12)
    project = c.e.construction._project(c.project)
    assert project["owner_id"] == original["owner_id"] == c.owner["id"]
    assert project["initiator_agent_id"] == original["initiator_agent_id"]
    for contribution in contributions:
        assert dict(c.store.query_one("SELECT * FROM construction_contributions WHERE id=?",
            (contribution["id"],))) == contribution
    assert c.store.scalar("SELECT actor_agent_id FROM construction_contributions "
        "WHERE project_id=? AND contribution_type='refund'", (c.project,)) == c.owner["id"]
    assert c.e.ledger.balance(c.owner["checking_account_id"]) == 0
    assert interests_at(c.store, c.project)[0]["agent_id"] == c.buyer["id"]
    validate(c.world)


@pytest.mark.parametrize("changes", [
    {"amount_cents": 0}, {"amount_cents": -1}, {"amount_cents": True}, {"amount_cents": 2.5},
    {"amount_cents": 1_000_000_000_001}, {"expires_tick": 10}, {"expires_tick": 41},
    {"currency_code": "XXX"}, {"qty": 1}, {"buyer_account_id": 999999999},
])
def test_bid_rejects_invalid_amounts_terms_and_foreign_funding_without_economic_mutation(property_world, changes):
    c = sale_case(property_world)
    before = economic_state(c)
    assert not bid(c, **changes)["ok"]
    assert economic_state(c) == before
    validate(c.world)


def test_guardian_sale_preserves_the_minors_cash_and_records_the_guardians_capacity(property_world):
    c = sale_case(property_world, guardian=True)
    assert c.representative == c.heir["id"]
    guardian_cash = c.e.ledger.balance(c.heir["checking_account_id"])
    child_cash = c.e.ledger.agent_checking_id(c.child)
    before_child = c.e.ledger.balance(child_cash)
    offered = bid(c)
    result = accept(c, offered["bid_id"])
    assert result["ok"], result
    sale = c.store.query_one("SELECT * FROM estate_property_sales WHERE id=?", (result["sale_id"],))
    proof = json.loads(sale["authority_json"])
    assert proof["guardian_id"] is not None and proof["beneficiary_id"] == c.child
    assert c.e.ledger.balance(c.heir["checking_account_id"]) == guardian_cash
    assert c.e.ledger.balance(child_cash) == before_child + 200
    validate(c.world)


@pytest.mark.parametrize("change", ["expiry", "withdrawal", "buyer_death", "representative_loss", "self_accept"])
def test_unavailable_or_unauthorized_acceptance_preserves_money_and_title(property_world, change):
    c = sale_case(property_world, public=change == "representative_loss")
    placed = bid(c)
    assert placed["ok"], placed
    tick, actor = 11, c.representative
    if change == "expiry":
        tick = 14
        c.e.project_rights.refresh(tick)
        assert c.store.scalar("SELECT reason FROM estate_property_bid_ends WHERE bid_id=?", (placed["bid_id"],)) == "expired"
    elif change == "withdrawal":
        result = c.world.runtime.executor.execute_action(11, c.buyer["id"], {"type": "withdraw_estate_property_bid", "bid_id": placed["bid_id"]})
        assert result["ok"], result
    elif change == "buyer_death":
        c.e.lifecycle.settle_death(11, c.buyer["id"])
        assert c.store.scalar("SELECT reason FROM estate_property_bid_ends WHERE bid_id=?", (placed["bid_id"],)) == "buyer_unavailable"
    elif change == "representative_loss":
        c.store.update("agents", actor, role=None)
    else:
        actor = c.buyer["id"]
    before = economic_state(c)
    assert not accept(c, placed["bid_id"], tick=tick, actor=actor)["ok"]
    assert economic_state(c) == before
    c.e.project_rights.refresh(tick)
    validate(c.world)


def test_bid_retry_and_sale_retry_do_not_duplicate_cash_or_title(property_world):
    c = sale_case(property_world)
    placed = bid(c)
    repeated = bid(c, tick=11)
    assert placed["ok"] and repeated["existing"] and placed["bid_id"] == repeated["bid_id"]
    assert not bid(c, amount_cents=301)["ok"]
    sold = accept(c, placed["bid_id"])
    assert sold["ok"], sold
    before = economic_state(c)
    assert not accept(c, placed["bid_id"])["ok"]
    assert economic_state(c) == before
    assert c.store.scalar("SELECT COUNT(*) FROM estate_property_sales") == 1
    validate(c.world)


@pytest.mark.parametrize("failure_table", ["project_interest_lots", "estate_property_sales", "estate_disbursements"])
def test_failure_after_payment_or_title_rolls_back_and_the_same_bid_can_retry(property_world, monkeypatch, failure_table):
    c = sale_case(property_world)
    placed = bid(c)
    assert placed["ok"], placed
    before = economic_state(c)
    original = c.store.insert
    def fail(table, *args, **kwargs):
        if table == failure_table:
            raise RuntimeError("injected property sale failure")
        return original(table, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(c.store, "insert", fail)
        result = accept(c, placed["bid_id"])
    assert not result["ok"] and "injected" in result["reason"], result
    assert economic_state(c) == before
    assert c.e.estate_cases._pending is None
    assert accept(c, placed["bid_id"])["ok"]
    validate(c.world)


def test_default_context_skips_unfunded_bids_and_preserves_required_civic_work(property_world):
    c = sale_case(property_world)
    high = bid(c, amount_cents=600, request_key="high")
    low = bid(c, amount_cents=300, request_key="low")
    assert high["ok"] and low["ok"]
    drain_cash(c.e, c.buyer["id"], 10)
    c.e.ledger.transfer(10, c.heir["checking_account_id"], c.buyer["checking_account_id"], 300)
    actor = c.store.query_one("SELECT * FROM agents WHERE id=?", (c.representative,))
    context = c.world.runtime.ctx.build(actor, 11)
    market = context["estate_property_market"]
    assert market["selected_bid"]["bid"]["id"] == low["bid_id"]
    assert market["represented_interests"][0]["bids"][0]["blocked_reason"]
    decision = scripted_decision("decision", context)
    assert decision["actions"] == [{"type": "accept_estate_property_bid", "bid_id": low["bid_id"]}]
    required = {"type": "attend_civic_appointment", "case_id": 99}
    assert scripted_decision("decision", dict(context, civic_required_action=required))["actions"] == [required]
    buyer_context = c.e.estate_property_sales.context_for(c.buyer["id"], 11)
    assert buyer_context["represented_interests"] == []
    assert buyer_context["eligible_actions"] == []
    assert buyer_context["available_interests"][0]["custody_id"] == c.custody
    assert {row["id"] for row in buyer_context["own_bids"]} == {high["bid_id"], low["bid_id"]}
    result = c.world.runtime.executor.execute_action(11, c.representative, decision["actions"][0])
    assert result["ok"], result
    validate(c.world)


def test_bid_and_sale_evidence_is_immutable_and_reconciliation_checks_real_payment(property_world):
    c = sale_case(property_world)
    offered = bid(c)
    sold = accept(c, offered["bid_id"])
    assert sold["ok"], sold
    for table in ("estate_property_bids", "estate_property_bid_ends", "estate_property_sales"):
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            c.store.execute(f"UPDATE {table} SET id=id")
        with pytest.raises(sqlite3.IntegrityError, match="permanent"):
            c.store.execute(f"DELETE FROM {table}")
    original = c.store.scalar("SELECT delta_cents FROM ledger_entries WHERE txn_id=? AND account_id=?",
                              (sold["transaction_id"], c.buyer["checking_account_id"]))
    c.store.execute("UPDATE ledger_entries SET delta_cents=delta_cents+1 WHERE txn_id=? AND account_id=?",
                    (sold["transaction_id"], c.buyer["checking_account_id"]))
    with pytest.raises(EstateError, match="funded estate receipt"):
        c.e.estate_property_sales.check_invariants()
    c.store.execute("UPDATE ledger_entries SET delta_cents=? WHERE txn_id=? AND account_id=?",
                    (original, sold["transaction_id"], c.buyer["checking_account_id"]))
    validate(c.world)


def test_bid_funding_is_rechecked_at_acceptance_without_partial_title_or_money(property_world):
    c = sale_case(property_world)
    offered = bid(c)
    assert offered["ok"], offered
    drain_cash(c.e, c.buyer["id"], 10)
    before = canonical_hashes(c.store)["tables"]
    result = accept(c, offered["bid_id"])
    assert not result["ok"] and "fund" in result["reason"], result
    after = canonical_hashes(c.store)["tables"]
    assert {name for name in before if before[name] != after[name]} == {"action_proposals", "events"}
    assert c.store.scalar("SELECT validation_status FROM action_proposals ORDER BY id DESC LIMIT 1") == "rejected"
    validate(c.world)


def test_sale_of_a_retained_half_interest_preserves_the_other_childs_title(property_world):
    world, _, owner = property_world
    e = world.economy
    partner = e.store.query_one("SELECT a.* FROM agents a JOIN household_memberships m ON m.agent_id=a.id "
        "WHERE a.alive=1 AND a.age>=18 AND a.kind='citizen' AND a.id<>? AND a.region_id=? "
        "AND m.left_tick IS NULL AND m.household_id<>? ORDER BY a.id LIMIT 1",
        (owner["id"], owner["region_id"], e.households.membership(owner["id"])["household_id"]))
    assert partner is not None
    e.store.execute("INSERT OR IGNORE INTO social_ties(agent_a,agent_b,weight) VALUES(?,?,1)", (owner["id"], partner["id"]))
    _, loan = personal_loan(e, partner["id"], 100)
    partnership = e.families.propose(0, owner["id"], "partnership", "property-family", partner_id=partner["id"])
    e.families.respond(0, partner["id"], partnership["household_decision_id"], "accept")
    project, _ = _advance_to_building(world, owner)
    child = e.households.birth(5, owner["id"])
    finish(world, owner["id"], project)
    drain_cash(e, owner["id"], 8)
    e.lifecycle.settle_death(9, owner["id"])
    assert {p["agent_id"]: (p["numerator"], p["denominator"]) for p in interests_at(e.store, project)} == {
        partner["id"]: ("1", "2"), child: ("1", "2")}
    drain_cash(e, partner["id"], 10)
    e.lifecycle.settle_death(11, partner["id"])
    estate = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (partner["id"],))
    custody = e.estate_property.pending(estate)[0]
    representative = e.estate_property.representatives(estate)[0]["actor_id"]
    currency = e.estate_property.currency_for(e.construction._project(project))
    buyer = e.store.query_one("SELECT a.* FROM agents a JOIN accounts w ON w.id=a.checking_account_id "
        "WHERE a.alive=1 AND a.age>=18 AND a.id<>? AND w.currency_code=? AND w.balance_cents>=300 ORDER BY a.id LIMIT 1",
        (representative, currency))
    assert buyer is not None
    c = SimpleNamespace(world=world, e=e, store=e.store, owner=partner, buyer=buyer, currency=currency,
        project=project, loan=loan, custody=custody["id"], estate=estate, representative=representative)
    placed = bid(c, tick=12, expires_tick=16)
    assert placed["ok"], placed
    result = accept(c, placed["bid_id"], tick=13)
    assert result["ok"], result
    assert {p["agent_id"]: (p["numerator"], p["denominator"]) for p in interests_at(e.store, project)} == {
        buyer["id"]: ("1", "2"), child: ("1", "2")}
    assert e.store.scalar("SELECT status FROM loans WHERE id=?", (loan,)) == "paid"
    validate(world)


def test_default_property_acceptance_survives_daily_restart_export_and_exact_replay(tmp_path, monkeypatch, caplog):
    config = _config(semantics=20)
    config.setdefault("households", {})["scheduled_births"] = []
    config.setdefault("lifecycle", {}).update(population_mode="drift", birth_annual_prob=0,
        illness_onset_annual_young=0, illness_onset_annual_old=0)
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
            trustee = store.scalar("SELECT id FROM agents WHERE alive=1 AND age>=18 AND role='gov_official' "
                "AND region_id=? ORDER BY id LIMIT 1", (owner["region_id"],))
            currency = store.scalar("SELECT currency_code FROM accounts WHERE id=?", (owner["checking_account_id"],))
            buyer = store.query_one("SELECT a.* FROM agents a JOIN accounts w ON w.id=a.checking_account_id "
                "WHERE a.alive=1 AND a.age>=18 AND a.retired=0 AND a.kind='citizen' AND a.region_id=? "
                "AND a.id NOT IN (?,?) AND w.currency_code=? AND w.balance_cents>=2100000 ORDER BY w.balance_cents DESC,a.id LIMIT 1",
                (owner["region_id"], owner["id"], trustee, currency))
            assert buyer is not None and trustee is not None
            execute = world.runtime.executor.execute_action
            proposal = execute(0, owner["id"], {"type": "propose_construction", "owner_type": "agent", "owner_id": owner["id"],
                "region_id": owner["region_id"], "site_key": "estate-sale-home", "target_place_type": "private_home",
                "name": "Estate sale fixture home", "required_funding_cents": 1200, "required_work_units": 2, "dedupe_key": "sale-home"})
            assert proposal["ok"], proposal
            project = proposal["project_id"]
            applied = execute(0, owner["id"], {"type": "apply_construction_permit", "project_id": project, "dedupe_key": "sale-permit"})
            assert applied["ok"], applied
            approved = execute(0, _permit_clerk(world, owner["region_id"]), {"type": "decide_construction_permit",
                "case_id": applied["permit_case_id"], "decision": "approve", "reason_code": "requirements_verified", "dedupe_key": "sale-approve"})
            assert approved["ok"], approved
            funded = execute(0, owner["id"], {"type": "contribute_construction_funding", "project_id": project,
                "amount_cents": 1200, "dedupe_key": "sale-fund"})
            assert funded["ok"], funded
            e.daily_time.prepare_day(0)
            built = execute(0, owner["id"], {"type": "perform_construction_work", "project_id": project,
                "work_units": 2, "wage_cents": 100, "procurement_cents": 100, "dedupe_key": "sale-build"})
            assert built["ok"] and built["status"] == "completed", built
            _, loan = personal_loan(e, owner["id"], 1_000_000)
            drain_cash(e, owner["id"], 0)
            store.execute("DELETE FROM social_ties WHERE agent_a=? OR agent_b=?", (owner["id"], owner["id"]))
            for actor in (owner["id"], trustee, buyer["id"]):
                store.update("agents", actor, population_tier="core", pinned_core=1,
                    cadence_json='{"act":1,"portfolio":9999,"career":9999,"news":9999}')
            ids.update(owner=owner["id"], trustee=trustee, buyer=buyer["id"], project=project, loan=loan)
            e.city.initialize(0)
        for purpose, original in list(world.gateway.scripted.policies.items()):
            def scenario(context, original=original):
                if replay:
                    raise AssertionError("replay must use recorded decisions")
                actor = context.get("agent", {}).get("id")
                if actor not in (ids["owner"], ids["buyer"]):
                    return original(context)
                action = {"type": "do_nothing"}
                if actor == ids["buyer"] and context["tick"] == 2:
                    for item in context["estate_property_market"]["available_interests"]:
                        if item["project_id"] == ids["project"]:
                            wallet = next(w for w in item["buyer_wallets"] if w["balance_cents"] >= 2_000_000)
                            action = dict(type="place_estate_property_bid", custody_id=item["custody_id"], buyer_account_id=wallet["id"],
                                amount_cents=2_000_000, currency_code=item["currency_code"], expires_tick=6, request_key="recorded-fixture-bid")
                            break
                return {"reasoning": "Declared funded buyer; the trustee uses the default property-sale policy.", "actions": [action]}
            world.gateway.scripted.register(purpose, scenario)
        return world

    path = tmp_path / "source-property-sale.db"
    committed = None
    for day in range(1, 4):
        source = open_seeded(path, config)
        try:
            if committed is not None:
                assert canonical_hashes(source.store)["authoritative_sha256"] == committed
            asyncio.run(source.step())
            if day == 1:
                assert interests_at(source.store, ids["project"])[0]["agent_id"] == ids["owner"]
                assert source.store.scalar("SELECT COUNT(*) FROM estate_property_bids") == 0
                participant = ParticipantService(source.store, source.runtime.ctx, config)
                catalog = participant.action_catalog(ids["buyer"])
                offers = [entry for entry in catalog if entry["type"] == "place_estate_property_bid"]
                assert offers
                assert all(any(field["name"] == "amount_cents" and field["min"] == 1 for field in entry["fields"]) for entry in offers)
                action = dict(type="place_estate_property_bid", variant=offers[0]["variant"], amount_cents="300", expires_tick=6)
                normalized = participant.normalize_action(ids["buyer"], action)
                assert normalized["amount_cents"] == 300 and normalized["expires_tick"] == 6
                assert participant.normalize_action(ids["buyer"], dict(action, custody_id=999999999,
                    buyer_account_id=999999999, currency_code="WRONG", request_key="redirect")) == normalized
                for change in ({"amount_cents": 2.5}, {"amount_cents": 300.0}, {"expires_tick": 3.5},
                               {"amount_cents": True}, {"amount_cents": 1_000_000_000_001}, {"expires_tick": 999}):
                    with pytest.raises(ParticipantError):
                        participant.normalize_action(ids["buyer"], dict(action, **change))
                assert "place_estate_property_bid" in citizen_world_action_types(20)
                assert "place_estate_property_bid" not in citizen_world_action_types(19)
            if day == 2:
                catalog = ParticipantService(source.store, source.runtime.ctx, config).action_catalog(ids["buyer"])
                assert any(entry["type"] == "withdraw_estate_property_bid" for entry in catalog)
            if day == 3:
                sale = source.store.query_one("SELECT * FROM estate_property_sales")
                assert sale is not None and sale["actor_id"] == ids["trustee"]
                assert json.loads(sale["authority_json"])["administration_id"] is not None
                assert interests_at(source.store, ids["project"])[0]["agent_id"] == ids["buyer"]
                assert source.store.scalar("SELECT status FROM loans WHERE id=?", (ids["loan"],)) == "paid"
                manifest = validate_bundle(export_bundle(source.store, tmp_path / "export"))
                for table in ("estate_property_bids", "estate_property_bid_ends", "estate_property_sales"):
                    assert manifest["tables"][table]["row_count"] == 1
            validate(source)
            committed = canonical_hashes(source.store)["authoritative_sha256"]
        finally:
            source.close()
    original_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    settings = copy.deepcopy(config)
    settings["replay_source_path"] = str(path)
    replay = open_seeded(tmp_path / "replay-property-sale.db", settings, replay=True)
    try:
        for _ in range(3):
            asyncio.run(replay.step())
        proof = verify_replay(path, replay.store.path)
        assert proof["exact"], proof["differences"]
        validate(replay)
        assert not any("action.execution.failed" in record.message for record in caplog.records)
    finally:
        replay.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original_hash

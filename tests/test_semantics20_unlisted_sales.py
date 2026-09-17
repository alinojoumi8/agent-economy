"""Funded private-company share sales settle retained estates without a trade."""
import asyncio
import copy
import hashlib
import json
import sqlite3
from types import SimpleNamespace

import pytest

from engine.actions import ActionExecutor
from engine.estates import EstateError
from engine.ledger import SYS_COMMODITY
from engine.lifecycle import Lifecycle
from agents.policies import scripted_decision
from agents.participant import ParticipantError, ParticipantService
from agents.citizen_actions import citizen_world_action_types
from research.export_bundle import export_bundle, validate_bundle
from research.hashing import canonical_hashes
from world.replay_verify import verify_replay

from .conftest import make_agent
from .test_semantics20_estate_cases import estate_case, validate
from .test_semantics20_estate_securities import indebted_security_estate
from .test_semantics20_project_rights import join_household
from .test_semantics19_estate_cash import spent_loan
from .test_semantics13_construction import _config, _owner
from .test_semantics17_household_decisions import _world
from .test_semantics20_estate_property import drain_cash, personal_loan


def sale_case(estate_case, public=False, guardian=False, other_qty=0, next_owner_estate=False):
    e, bank, owner, wallet, heir, heir_wallet, loan, firm, buyer, buyer_wallet = indebted_security_estate(estate_case)
    # This fixture starts with a private issuer; no IPO or exchange execution occurs.
    e.store.update("firms", firm, status="private")
    e.store.execute("INSERT INTO currencies(code,name,numeraire_rate_ppm,issuer_region_id) "
        "VALUES('USD','US dollar',1000000,1) ON CONFLICT(code) DO NOTHING")
    if other_qty:
        e.exchange._adjust_shares(firm, "agent", owner, -other_qty)
        e.exchange._adjust_shares(firm, "agent", heir, other_qty)
        e.store.insert("share_movements", tick=0, firm_id=firm, from_holder_type="agent", from_holder_id=owner,
            to_holder_type="agent", to_holder_id=heir, qty=other_qty, movement_type="genesis_transfer", amount_cents=0)
    child = None
    if guardian:
        child = e.households.birth(1, owner)
        join_household(e, heir, owner, 1)
        e.households.reconcile_custody(1)
    successor, buyer_loan = None, None
    if next_owner_estate:
        successor, _ = make_agent(e, bank, "Second estate representative", cash=0, region_id=1)
        e.households.register_person(0, successor, "genesis")
        e.store.insert("social_ties", agent_a=buyer, agent_b=successor, weight=100)
        buyer_loan = spent_loan(e, bank, buyer, buyer_wallet, 100)
    if public:
        actor, _ = make_agent(e, bank, "Existing public trustee", cash=0, region_id=1,
            kind="institutional", role="gov_official")
        e.store.execute("DELETE FROM social_ties WHERE agent_a=? OR agent_b=?", (owner, owner))
    else:
        actor = heir
    e.lifecycle.settle_death(1, owner)
    estate = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (owner,))
    lot = e.estate_securities.lots(estate)[0]["id"]
    return SimpleNamespace(e=e, store=e.store, bank=bank, owner=owner, wallet=wallet, heir=heir,
        heir_wallet=heir_wallet, loan=loan, firm=firm, buyer=buyer, buyer_wallet=buyer_wallet,
        actor=actor, estate=estate, lot=lot, executor=ActionExecutor(e), child=child,
        successor=successor, buyer_loan=buyer_loan)


def bid(c, tick=2, **changes):
    action = dict(type="place_estate_unlisted_bid", lot_id=c.lot, qty=10,
        buyer_account_id=c.buyer_wallet, amount_cents=200, currency_code="USD",
        expires_tick=6, request_key="actual-private-buyer")
    action.update(changes)
    return c.executor.execute_action(tick, c.buyer, action)


def accept(c, bid_id, tick=3, actor=None):
    return c.executor.execute_action(tick, c.actor if actor is None else actor,
        {"type": "accept_estate_unlisted_bid", "bid_id": bid_id})


def economic_state(c):
    return {name: value for name, value in canonical_hashes(c.store)["tables"].items()
            if name not in {"action_proposals", "events"}}


@pytest.mark.parametrize("public", [False, True])
def test_funded_unlisted_sale_pays_creditors_transfers_control_and_preserves_issued_shares(estate_case, public):
    c = sale_case(estate_case, public)
    issued = c.store.scalar("SELECT SUM(qty) FROM shares WHERE firm_id=?", (c.firm,))
    placed = bid(c)
    assert placed["ok"], placed
    assert c.e.ledger.balance(c.buyer_wallet) == 200
    assert c.e.exchange.shares_held(c.firm, "agent", c.owner) == 10
    result = accept(c, placed["bid_id"])
    assert result["ok"], result
    assert c.e.exchange.shares_held(c.firm, "agent", c.buyer) == 10
    assert c.e.exchange.shares_held(c.firm, "agent", c.owner) == 0
    assert c.e.ledger.balance(c.wallet) == c.e.ledger.balance(c.buyer_wallet) == 0
    assert c.e.ledger.balance(c.heir_wallet) == (0 if public else 100)
    assert c.store.scalar("SELECT status FROM loans WHERE id=?", (c.loan,)) == "paid"
    assert c.store.scalar("SELECT SUM(qty) FROM shares WHERE firm_id=?", (c.firm,)) == issued
    assert c.store.scalar("SELECT founder_agent_id FROM firms WHERE id=?", (c.firm,)) == c.owner
    assert c.store.scalar("SELECT operator_agent_id FROM firm_operations WHERE id=?", (c.firm,)) == c.buyer
    assert c.e.estate_securities.remaining(c.store.query_one(
        "SELECT * FROM estate_security_lots WHERE id=?", (c.lot,))) == 0
    assert c.store.scalar("SELECT qty FROM estate_security_releases WHERE lot_id=?", (c.lot,)) == 0
    assert c.e.estate_administration.current(c.estate) is None
    assert c.store.scalar("SELECT COUNT(*) FROM trades") == 0
    sale = c.store.query_one("SELECT * FROM estate_unlisted_sales WHERE id=?", (result["sale_id"],))
    movement = c.store.query_one("SELECT * FROM share_movements WHERE id=?", (sale["movement_id"],))
    assert (movement["from_holder_id"], movement["to_holder_id"], movement["qty"], movement["amount_cents"]) == (c.owner, c.buyer, 10, 200)
    assert movement["price_cents"] is None and movement["transaction_id"] == sale["transaction_id"]
    assert (json.loads(sale["authority_json"])["administration_id"] is not None) == public
    validate(c.e)


@pytest.mark.parametrize("changes", [
    {"qty": 0}, {"qty": True}, {"qty": 2.5}, {"qty": 9}, {"qty": 11},
    {"amount_cents": 0}, {"amount_cents": 2.5}, {"amount_cents": True}, {"amount_cents": 1_000_000_000_001},
    {"expires_tick": 2}, {"expires_tick": 33}, {"currency_code": "XXX"}, {"unexpected": 1},
])
def test_private_bid_rejects_invalid_or_partial_terms_without_economic_mutation(estate_case, changes):
    c = sale_case(estate_case)
    before = economic_state(c)
    assert not bid(c, **changes)["ok"]
    assert economic_state(c) == before
    validate(c.e)


@pytest.mark.parametrize("change", ["expiry", "withdrawn", "buyer_death", "representative_death", "listed", "bankrupt", "cash_spent", "released", "self_accept"])
def test_stale_private_bid_cannot_move_cash_or_shares(estate_case, change):
    c = sale_case(estate_case)
    placed = bid(c)
    assert placed["ok"], placed
    actor, tick = c.actor, 3
    if change == "expiry":
        tick = 6
    elif change == "withdrawn":
        assert c.executor.execute_action(3, c.buyer, {"type": "withdraw_estate_unlisted_bid", "bid_id": placed["bid_id"]})["ok"]
    elif change in {"buyer_death", "representative_death"}:
        c.e.lifecycle.settle_death(3, c.buyer if change == "buyer_death" else c.actor)
    elif change in {"listed", "bankrupt"}:
        c.store.update("firms", c.firm, status=change)
    elif change in {"cash_spent", "released"}:
        destination = c.wallet if change == "released" else c.e.ledger.system_account(SYS_COMMODITY)
        c.e.ledger.transfer(3, c.buyer_wallet, destination, 100)
    else:
        actor = c.buyer
    c.e.estate_unlisted_sales.reconcile(tick)
    before = economic_state(c)
    assert not accept(c, placed["bid_id"], tick, actor)["ok"]
    assert economic_state(c) == before
    validate(c.e)


@pytest.mark.parametrize("failure_table", ["share_movements", "estate_unlisted_sales", "estate_disbursements", "firm_stewardships"])
def test_failed_private_settlement_rolls_back_shares_cash_receipts_and_control_then_retries(estate_case, monkeypatch, failure_table):
    c = sale_case(estate_case)
    placed = bid(c)
    before = economic_state(c)
    original = c.store.insert
    def fail(table, *args, **kwargs):
        if table == failure_table:
            raise RuntimeError("injected private sale failure")
        return original(table, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(c.store, "insert", fail)
        result = accept(c, placed["bid_id"])
    assert not result["ok"] and "injected" in result["reason"], result
    assert economic_state(c) == before
    assert c.e.estate_cases._pending is None
    assert accept(c, placed["bid_id"])["ok"]
    validate(c.e)


def test_guardian_sale_preserves_the_childs_residual_cash(estate_case):
    c = sale_case(estate_case, guardian=True)
    assert c.e.estate_securities.authority(c.estate, c.actor)["guardian_id"] is not None
    child_wallet = c.e.ledger.agent_checking_id(c.child)
    before = c.e.ledger.balance(child_wallet)
    result = accept(c, bid(c)["bid_id"])
    assert result["ok"], result
    assert c.e.ledger.balance(c.heir_wallet) == 0
    assert c.e.ledger.balance(child_wallet) == before + 100
    validate(c.e)


def test_a_whole_retained_lot_sale_preserves_other_owners_and_does_not_round_a_unit_price(estate_case):
    c = sale_case(estate_case, other_qty=3)
    result = accept(c, bid(c, qty=7, amount_cents=199)["bid_id"])
    assert result["ok"], result
    assert c.e.exchange.shares_held(c.firm, "agent", c.heir) == 3
    assert c.e.exchange.shares_held(c.firm, "agent", c.buyer) == 7
    assert c.e.ledger.balance(c.heir_wallet) == 99
    movement = c.store.query_one("SELECT * FROM share_movements WHERE id=?", (result["movement_id"],))
    assert movement["price_cents"] is None and movement["amount_cents"] == 199
    validate(c.e)


def test_default_representative_selects_a_funded_bid_and_bid_retries_cannot_duplicate_the_sale(estate_case):
    c = sale_case(estate_case)
    high = bid(c, request_key="high")
    low = bid(c, amount_cents=100, request_key="low")
    assert bid(c, tick=3, request_key="high")["existing"]
    assert not bid(c, request_key="high", amount_cents=199)["ok"]
    c.e.ledger.transfer(2, c.buyer_wallet, c.e.ledger.system_account(SYS_COMMODITY), 100)
    market = c.e.estate_unlisted_sales.context_for(c.actor, 3)
    assert market["selected_bid"]["bid"]["id"] == low["bid_id"]
    assert market["represented_lots"][0]["bids"][0]["id"] == high["bid_id"]
    assert market["represented_lots"][0]["bids"][0]["blocked_reason"]
    context = {"estate_unlisted_market": market}
    action = scripted_decision("decision", context)["actions"][0]
    assert action == {"type": "accept_estate_unlisted_bid", "bid_id": low["bid_id"]}
    required = {"type": "attend_civic_appointment", "case_id": 99}
    assert scripted_decision("decision", dict(context, civic_required_action=required))["actions"] == [required]
    assert c.executor.execute_action(3, c.actor, action)["ok"]
    before = economic_state(c)
    assert not accept(c, low["bid_id"])["ok"]
    assert economic_state(c) == before
    assert c.store.scalar("SELECT reason FROM estate_unlisted_bid_ends WHERE bid_id=?", (high["bid_id"],)) == "lot_disposed"
    validate(c.e)


def test_private_sale_evidence_and_movement_are_immutable_and_cash_tampering_is_detected(estate_case):
    c = sale_case(estate_case)
    result = accept(c, bid(c)["bid_id"])
    assert result["ok"], result
    for table in ("estate_unlisted_bids", "estate_unlisted_bid_ends", "estate_unlisted_sales"):
        for sql in (f"UPDATE {table} SET id=id", f"DELETE FROM {table}"):
            with pytest.raises(sqlite3.IntegrityError):
                c.store.execute(sql)
    for sql in ("UPDATE share_movements SET qty=qty WHERE id=?", "DELETE FROM share_movements WHERE id=?"):
        with pytest.raises(sqlite3.IntegrityError):
            c.store.execute(sql, (result["movement_id"],))
    entry = c.store.scalar("SELECT id FROM ledger_entries WHERE txn_id=? AND account_id=?", (result["transaction_id"], c.buyer_wallet))
    c.store.execute("UPDATE ledger_entries SET delta_cents=delta_cents+1 WHERE id=?", (entry,))
    with pytest.raises(EstateError, match="balanced|funded"):
        c.e.estate_unlisted_sales.check_invariants()
    c.store.execute("UPDATE ledger_entries SET delta_cents=delta_cents-1 WHERE id=?", (entry,))
    validate(c.e)


def test_listing_ends_the_private_bid_and_the_existing_exchange_sells_the_retained_lot(estate_case):
    c = sale_case(estate_case)
    placed = bid(c)
    c.store.update("firms", c.firm, status="listed")
    c.e.estate_unlisted_sales.reconcile(3)
    assert c.store.scalar("SELECT reason FROM estate_unlisted_bid_ends WHERE bid_id=?", (placed["bid_id"],)) == "issuer_status_changed"
    assert not accept(c, placed["bid_id"])["ok"]
    sell = c.executor.execute_action(3, c.actor, dict(type="place_order", estate_id=c.estate, firm_id=c.firm, side="sell", qty=10, limit_price=20))
    buy = c.executor.execute_action(3, c.buyer, dict(type="place_order", firm_id=c.firm, side="buy", qty=10, limit_price=20))
    assert sell["ok"] and buy["ok"], (sell, buy)
    assert sum(fill.qty for fill in c.e.exchange.match_firm(3, c.firm)) == 10
    assert c.store.scalar("SELECT COUNT(*) FROM estate_unlisted_sales") == 0
    assert c.store.scalar("SELECT COUNT(*) FROM estate_security_sales") == 1
    validate(c.e)


def test_successive_owners_sell_the_same_shares_through_distinct_recorded_estates(estate_case):
    c = sale_case(estate_case, next_owner_estate=True)
    assert accept(c, bid(c)["bid_id"])["ok"]
    c.e.lifecycle.settle_death(4, c.buyer)
    estate = c.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (c.buyer,))
    lot = c.e.estate_securities.lots(estate)[0]["id"]
    placed = c.executor.execute_action(5, c.heir, dict(type="place_estate_unlisted_bid", lot_id=lot, qty=10,
        buyer_account_id=c.heir_wallet, amount_cents=100, currency_code="USD", expires_tick=8, request_key="second-estate"))
    assert placed["ok"], placed
    result = c.executor.execute_action(6, c.successor, dict(type="accept_estate_unlisted_bid", bid_id=placed["bid_id"]))
    assert result["ok"], result
    assert c.e.exchange.shares_held(c.firm, "agent", c.heir) == 10
    assert c.store.scalar("SELECT COUNT(*) FROM estate_unlisted_sales") == 2
    assert c.store.scalar("SELECT status FROM loans WHERE id=?", (c.buyer_loan,)) == "paid"
    validate(c.e)


@pytest.mark.parametrize("actor_kind", ["buyer", "representative"])
def test_funded_wallets_cannot_bypass_buyer_ownership_or_estate_conflicts(estate_case, actor_kind):
    c = sale_case(estate_case)
    c.e.ledger.transfer(2, c.buyer_wallet, c.heir_wallet, 200)
    actor = c.buyer if actor_kind == "buyer" else c.actor
    before = economic_state(c)
    result = c.executor.execute_action(2, actor, dict(type="place_estate_unlisted_bid", lot_id=c.lot,
        qty=10, buyer_account_id=c.heir_wallet, amount_cents=200, currency_code="USD", expires_tick=6, request_key="conflicted"))
    assert not result["ok"]
    assert ("buyer funds" if actor_kind == "buyer" else "represent") in result["reason"]
    assert economic_state(c) == before
    validate(c.e)


def test_default_private_share_sale_survives_daily_restart_catalog_export_and_exact_replay(tmp_path, monkeypatch, caplog):
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
            firm = e.firms.found_firm(0, owner["id"], "Recorded private estate issuer", "manufacturing",
                opening_capital_cents=10_000, shares=10)
            _, loan = personal_loan(e, owner["id"], 1_000_000)
            drain_cash(e, owner["id"], 0)
            store.execute("DELETE FROM social_ties WHERE agent_a=? OR agent_b=?", (owner["id"], owner["id"]))
            for actor in (owner["id"], trustee, buyer["id"]):
                store.update("agents", actor, population_tier="core", pinned_core=1,
                    cadence_json='{"act":1,"portfolio":9999,"career":9999,"news":9999}')
            ids.update(owner=owner["id"], trustee=trustee, buyer=buyer["id"], firm=firm, loan=loan)
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
                    for item in context["estate_unlisted_market"]["available_lots"]:
                        if item["firm_id"] == ids["firm"]:
                            wallet = next(w for w in item["buyer_wallets"] if w["balance_cents"] >= 2_000_000)
                            action = dict(type="place_estate_unlisted_bid", lot_id=item["lot_id"], qty=item["qty"],
                                buyer_account_id=wallet["id"], amount_cents=2_000_000, currency_code=item["currency_code"],
                                expires_tick=6, request_key="recorded-private-bid")
                            break
                return {"reasoning": "Declared funded buyer; the trustee uses the default private-share-sale policy.", "actions": [action]}
            world.gateway.scripted.register(purpose, scenario)
        return world

    path = tmp_path / "source-private-sale.db"
    committed = None
    for day in range(1, 4):
        source = open_seeded(path, config)
        try:
            if committed is not None:
                assert canonical_hashes(source.store)["authoritative_sha256"] == committed
            asyncio.run(source.step())
            if day == 1:
                participant = ParticipantService(source.store, source.runtime.ctx, config)
                offers = [item for item in participant.action_catalog(ids["buyer"]) if item["type"] == "place_estate_unlisted_bid"]
                assert offers
                action = dict(type="place_estate_unlisted_bid", variant=offers[0]["variant"], amount_cents="300", expires_tick=6)
                normalized = participant.normalize_action(ids["buyer"], action)
                assert normalized["amount_cents"] == 300 and normalized["qty"] == 10
                assert participant.normalize_action(ids["buyer"], dict(action, lot_id=999999999,
                    qty=999, buyer_account_id=999999999, currency_code="WRONG", request_key="redirect")) == normalized
                for change in ({"amount_cents": 2.5}, {"expires_tick": 3.5}, {"amount_cents": True}, {"amount_cents": 1_000_000_000_001}):
                    with pytest.raises(ParticipantError):
                        participant.normalize_action(ids["buyer"], dict(action, **change))
                assert "place_estate_unlisted_bid" in citizen_world_action_types(20)
                assert "place_estate_unlisted_bid" not in citizen_world_action_types(19)
            if day == 2:
                catalog = ParticipantService(source.store, source.runtime.ctx, config).action_catalog(ids["buyer"])
                assert any(item["type"] == "withdraw_estate_unlisted_bid" for item in catalog)
            if day == 3:
                sale = source.store.query_one("SELECT * FROM estate_unlisted_sales")
                assert sale is not None and sale["actor_id"] == ids["trustee"]
                assert json.loads(sale["authority_json"])["administration_id"] is not None
                assert source.economy.exchange.shares_held(ids["firm"], "agent", ids["buyer"]) == 10
                assert source.store.scalar("SELECT operator_agent_id FROM firm_operations WHERE id=?", (ids["firm"],)) == ids["buyer"]
                assert source.store.scalar("SELECT status FROM loans WHERE id=?", (ids["loan"],)) == "paid"
                assert source.store.scalar("SELECT COUNT(*) FROM trades WHERE firm_id=?", (ids["firm"],)) == 0
                manifest = validate_bundle(export_bundle(source.store, tmp_path / "export"))
                for table in ("estate_unlisted_bids", "estate_unlisted_bid_ends", "estate_unlisted_sales"):
                    assert manifest["tables"][table]["row_count"] == 1
            validate(source.economy)
            committed = canonical_hashes(source.store)["authoritative_sha256"]
        finally:
            source.close()
    original_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    settings = copy.deepcopy(config)
    settings["replay_source_path"] = str(path)
    replay = open_seeded(tmp_path / "replay-private-sale.db", settings, replay=True)
    try:
        for _ in range(3):
            asyncio.run(replay.step())
        proof = verify_replay(path, replay.store.path)
        assert proof["exact"], proof["differences"]
        validate(replay.economy)
        assert not any("action.execution.failed" in record.message for record in caplog.records)
    finally:
        replay.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original_hash

"""A recorded public trustee can administer an otherwise unrepresented estate."""
import asyncio
import copy
import hashlib
import sqlite3
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agents.policies import scripted_decision
from engine.estates import EstateError
from engine.lifecycle import Lifecycle
from engine.project_rights import interests_at, steward_at
from research.export_bundle import export_bundle, validate_bundle
from research.hashing import canonical_hashes
from server.projections.construction import build_construction_project_detail
from server.projections.living_agents import build_living_agents_workspace
from server.projections.workspaces import build_world_workspace
from server.v2_api import install_v2_routes
from world.replay_verify import verify_replay

from .test_semantics20_estate_property import drain_cash, personal_loan
from .test_semantics20_project_rights import property_world, finish, join_household, validate
from .test_semantics13_construction import _config, _owner, _permit_clerk, _advance_to_building
from .test_semantics17_household_decisions import _world


@pytest.fixture
def unrepresented_assets(property_world):
    world, owner, buyer = property_world
    e = world.economy
    official = e.store.query_one("SELECT * FROM agents WHERE alive=1 AND age>=18 "
        "AND role='gov_official' AND region_id=? ORDER BY id LIMIT 1", (owner["region_id"],))
    assert official is not None
    _, loan = personal_loan(e, owner["id"], 100)
    firm = e.firms.found_firm(0, owner["id"], "Unrepresented estate issuer", "manufacturing",
        opening_capital_cents=10000, shares=10)
    e.store.update("firms", firm, status="listed")
    project, _ = _advance_to_building(world, owner)
    finish(world, owner["id"], project)
    drain_cash(e, owner["id"], 8)
    e.store.execute("DELETE FROM social_ties WHERE agent_a=? OR agent_b=?", (owner["id"], owner["id"]))
    return world, owner, buyer, official, loan, firm, project


def test_unrepresented_assets_get_a_public_trustee_without_personal_inheritance(unrepresented_assets):
    world, owner, _, official, _, firm, project = unrepresented_assets
    e = world.economy
    people_before = e.store.scalar("SELECT COUNT(*) FROM agents")
    official_cash = e.ledger.balance(official["checking_account_id"])
    e.lifecycle.settle_death(9, owner["id"])
    assert steward_at(e.store, project)["capacity"] == "administrator"
    assert steward_at(e.store, project)["steward_agent_id"] == official["id"]
    assert interests_at(e.store, project)[0]["agent_id"] == owner["id"]
    assert e.exchange.shares_held(firm, "agent", owner["id"]) == 10
    assert e.exchange.shares_held(firm, "agent", official["id"]) == 0
    assert e.store.scalar("SELECT COUNT(*) FROM agents") == people_before
    assert e.ledger.balance(official["checking_account_id"]) == official_cash
    estate = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (owner["id"],))
    appointment = e.estate_administration.current(estate)
    assert appointment["administrator_agent_id"] == official["id"]
    assert steward_at(e.store, project)["administration_id"] == appointment["id"]
    scope = e.estate_securities.context_for(official["id"], 9)
    assert scope[0]["authority"] == "public_administrator"
    assert scope[0]["beneficiary_id"] is None
    assert scope[0]["administration_id"] == appointment["id"]
    validate(world)


def quote(world, tick, person, estate, firm, side="sell", quantity=5):
    return world.runtime.executor.execute_action(tick, person, {"type": "place_order",
        "estate_id": estate, "firm_id": firm, "side": side, "qty": quantity, "limit_price": 20})


def test_actual_public_trustee_sale_pays_creditors_and_releases_residual_assets(unrepresented_assets):
    world, owner, buyer, official, loan, firm, project = unrepresented_assets
    e = world.economy
    e.lifecycle.settle_death(9, owner["id"])
    estate = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (owner["id"],))
    appointment = e.estate_administration.current(estate)
    trustee_cash = e.ledger.balance(official["checking_account_id"])
    placed = quote(world, 10, official["id"], estate, firm)
    assert placed["ok"], placed
    funded = world.runtime.executor.execute_action(10, buyer["id"], {"type": "place_order",
        "firm_id": firm, "side": "buy", "qty": 5, "limit_price": 20})
    assert funded["ok"], funded
    fills = e.exchange.match_firm(10, firm)
    assert sum(fill.qty for fill in fills) == 5
    assert e.store.scalar("SELECT status FROM loans WHERE id=?", (loan,)) == "paid"
    assert e.exchange.shares_held(firm, "agent", owner["id"]) == 0
    assert e.exchange.shares_held(firm, "agent", buyer["id"]) == 5
    assert e.exchange.shares_held(firm, "agent", official["id"]) == 0
    assert e.store.scalar("SELECT SUM(qty) FROM shares WHERE firm_id=?", (firm,)) == 10
    assert interests_at(e.store, project)[0]["agent_id"] is None
    assert e.ledger.balance(official["checking_account_id"]) == trustee_cash
    assert e.estate_administration.current(estate) is None
    ending = e.store.query_one("SELECT * FROM estate_administration_ends WHERE administration_id=?", (appointment["id"],))
    assert ending["tick"] == 10 and ending["reason"] == "assets_disposed"
    authorization = e.estate_securities.authorization(placed["order_id"])
    assert authorization["administration_id"] == appointment["id"]
    assert authorization["administration_end_frontier"] < ending["id"]
    assert authorization["beneficiary_id"] is None
    validate(world)


@pytest.mark.parametrize("invalid", ["unappointed", "purchase", "too_many"])
def test_public_trustee_scope_rejects_unappointed_actors_purchases_and_overselling(unrepresented_assets, invalid):
    world, owner, buyer, official, _, firm, _ = unrepresented_assets
    e = world.economy
    e.lifecycle.settle_death(9, owner["id"])
    estate = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (owner["id"],))
    before = e.store.scalar("SELECT COUNT(*) FROM orders")
    result = quote(world, 10, buyer["id"] if invalid == "unappointed" else official["id"], estate, firm,
        side="buy" if invalid == "purchase" else "sell", quantity=11 if invalid == "too_many" else 5)
    assert not result["ok"]
    assert e.store.scalar("SELECT COUNT(*) FROM orders") == before
    assert e.exchange.shares_held(firm, "agent", owner["id"]) == 10
    validate(world)


def test_recorded_vacancy_waits_for_an_eligible_existing_official(unrepresented_assets):
    world, owner, _, official, _, _, project = unrepresented_assets
    e = world.economy
    e.store.update("agents", official["id"], role="citizen")
    e.lifecycle.settle_death(9, owner["id"])
    estate = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (owner["id"],))
    vacant = e.estate_administration.current(estate)
    assert vacant["administrator_agent_id"] is None
    assert steward_at(e.store, project)["capacity"] == "vacant"
    e.project_rights.refresh(10)
    assert e.estate_administration.current(estate)["id"] == vacant["id"]
    validate(world)
    e.store.update("agents", official["id"], role="gov_official")
    e.business_control.refresh_custody(11)
    e.project_rights.refresh(11)
    assert e.estate_administration.current(estate)["administrator_agent_id"] == official["id"]
    assert e.store.scalar("SELECT reason FROM estate_administration_ends WHERE administration_id=?", (vacant["id"],)) == "candidate_available"
    assert steward_at(e.store, project, 10)["capacity"] == "vacant"
    assert steward_at(e.store, project, 11)["capacity"] == "administrator"
    validate(world)


@pytest.mark.parametrize("loss", ["role", "region", "death"])
def test_public_authority_loss_revokes_an_existing_quote_before_matching(unrepresented_assets, loss):
    world, owner, buyer, official, _, firm, project = unrepresented_assets
    e = world.economy
    e.lifecycle.settle_death(9, owner["id"])
    estate = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (owner["id"],))
    placed = quote(world, 10, official["id"], estate, firm)
    assert placed["ok"], placed
    if loss == "death":
        e.lifecycle.settle_death(11, official["id"])
    elif loss == "region":
        other = e.store.scalar("SELECT id FROM regions WHERE id<>? ORDER BY id LIMIT 1", (official["region_id"],))
        assert other is not None
        e.store.update("agents", official["id"], region_id=other)
    else:
        e.store.update("agents", official["id"], role="citizen")
    e.business_control.refresh_custody(11)
    e.project_rights.refresh(11)
    assert e.store.scalar("SELECT status FROM orders WHERE id=?", (placed["order_id"],)) == "cancelled"
    bought = world.runtime.executor.execute_action(11, buyer["id"], {"type": "place_order",
        "firm_id": firm, "side": "buy", "qty": 5, "limit_price": 20})
    assert bought["ok"], bought
    assert e.exchange.match_firm(11, firm) == []
    assert not e.construction._authorized_project(official["id"], e.construction._project(project))
    assert e.exchange.shares_held(firm, "agent", owner["id"]) == 10
    validate(world)


def test_guardian_return_ends_public_authority_and_preserves_the_childs_interest(unrepresented_assets):
    world, owner, guardian, official, _, firm, project = unrepresented_assets
    e = world.economy
    child = e.households.birth(8, owner["id"])
    drain_cash(e, owner["id"], 8)
    e.lifecycle.settle_death(9, owner["id"])
    estate = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (owner["id"],))
    appointment = e.estate_administration.current(estate)
    assert appointment["administrator_agent_id"] == official["id"]
    placed = quote(world, 10, official["id"], estate, firm)
    assert placed["ok"], placed
    join_household(e, guardian["id"], child, 11)
    e.households.reconcile_custody(11)
    assert e.estate_administration.current(estate) is None
    assert e.store.scalar("SELECT reason FROM estate_administration_ends WHERE administration_id=?", (appointment["id"],)) == "private_representative"
    assert e.store.scalar("SELECT status FROM orders WHERE id=?", (placed["order_id"],)) == "cancelled"
    assert steward_at(e.store, project)["capacity"] == "estate"
    assert steward_at(e.store, project)["beneficiary_id"] == child
    assert interests_at(e.store, project)[0]["agent_id"] == owner["id"]
    assert not quote(world, 11, official["id"], estate, firm)["ok"]
    assert quote(world, 11, guardian["id"], estate, firm)["ok"]
    validate(world)


def test_failed_public_appointment_rolls_back_the_entire_death(unrepresented_assets, monkeypatch):
    world, owner, _, _, _, _, _ = unrepresented_assets
    e = world.economy
    before = canonical_hashes(e.store)["authoritative_sha256"]
    insert = e.store.insert

    def fail(table, **values):
        row = insert(table, **values)
        if table == "estate_administrations":
            raise RuntimeError("injected after public appointment")
        return row

    with monkeypatch.context() as fault:
        fault.setattr(e.store, "insert", fail)
        with pytest.raises(RuntimeError, match="injected after public appointment"):
            e.lifecycle.settle_death(9, owner["id"])
    assert canonical_hashes(e.store)["authoritative_sha256"] == before
    assert e.estate_cases._pending is None
    e.lifecycle.settle_death(9, owner["id"])
    validate(world)


def test_default_trustee_policy_waits_for_a_priced_bid_and_avoids_duplicate_offers(unrepresented_assets):
    world, owner, buyer, official, _, firm, _ = unrepresented_assets
    e = world.economy
    e.lifecycle.settle_death(9, owner["id"])
    context = {"purpose": "gov_official", "estate_securities": e.estate_securities.context_for(official["id"], 10)}
    decision = scripted_decision("gov_official", context)
    action = decision["actions"][0]
    assert action["type"] == "place_order" and action["qty"] == 10
    assert "limit_price" not in action
    placed = world.runtime.executor.execute_action(10, official["id"], action)
    assert placed["ok"], placed
    assert e.exchange.match_firm(10, firm) == []
    context["estate_securities"] = e.estate_securities.context_for(official["id"], 11)
    position = context["estate_securities"][0]["securities"][0]
    assert position["pending_sale_qty"] == 10 and position["orderable_qty"] == 0
    assert scripted_decision("gov_official", context)["actions"] == [{"type": "do_nothing"}]
    funded = world.runtime.executor.execute_action(11, buyer["id"], {"type": "place_order", "firm_id": firm,
        "side": "buy", "qty": 5, "limit_price": 20})
    assert funded["ok"], funded
    assert sum(fill.qty for fill in e.exchange.match_firm(11, firm)) == 5
    # Paying the creditor releases the remaining estate shares; the unfilled
    # part of the old quote must leave the book at that same boundary.
    assert e.store.scalar("SELECT status FROM orders WHERE id=?", (placed["order_id"],)) == "cancelled"
    assert e.store.scalar("SELECT COUNT(*) FROM trades WHERE firm_id=?", (firm,)) == 1
    validate(world)


@pytest.mark.parametrize("separate_estates", [False, True])
def test_an_unmatched_position_cannot_starve_another_funded_estate_sale(unrepresented_assets, separate_estates):
    world, owner, other_owner, official, _, first_firm, _ = unrepresented_assets
    e = world.economy
    second_owner = other_owner if separate_estates else owner
    assert second_owner["region_id"] == owner["region_id"]
    if separate_estates:
        personal_loan(e, second_owner["id"], 100)
        drain_cash(e, second_owner["id"], 8)
        e.store.execute("DELETE FROM social_ties WHERE agent_a=? OR agent_b=?",
                        (second_owner["id"], second_owner["id"]))
    second_firm = e.firms.found_firm(8, second_owner["id"], "Second retained issuer", "manufacturing", shares=10)
    e.store.update("firms", second_firm, status="listed")
    e.lifecycle.settle_death(9, owner["id"])
    if separate_estates:
        e.lifecycle.settle_death(9, second_owner["id"])
    buyer = e.store.query_one("SELECT a.* FROM agents a JOIN accounts c ON c.id=a.checking_account_id "
        "WHERE a.alive=1 AND a.age>=18 AND a.role IS NULL AND a.id NOT IN (?,?,?) "
        "AND c.balance_cents>=100 AND c.currency_code=(SELECT currency_code FROM firms WHERE id=?) "
        "ORDER BY a.id LIMIT 1", (owner["id"], second_owner["id"], official["id"], second_firm))
    assert buyer is not None
    context = {"purpose": "gov_official", "estate_securities": e.estate_securities.context_for(official["id"], 10)}
    first_action = scripted_decision("gov_official", context)["actions"][0]
    assert first_action["firm_id"] == first_firm
    first_order = world.runtime.executor.execute_action(10, official["id"], first_action)
    assert first_order["ok"], first_order
    assert e.exchange.match_firm(10, first_firm) == []
    e.exchange.expire_session(10)
    assert e.store.scalar("SELECT status FROM orders WHERE id=?", (first_order["order_id"],)) == "expired"

    funded = world.runtime.executor.execute_action(11, buyer["id"], {"type": "place_order", "firm_id": second_firm,
        "side": "buy", "qty": 5, "limit_price": 20})
    assert funded["ok"], funded
    context["estate_securities"] = e.estate_securities.context_for(official["id"], 11)
    next_action = scripted_decision("gov_official", context)["actions"][0]
    assert next_action["firm_id"] == second_firm, "a repeated unpriced offer must not monopolize the trustee"
    next_order = world.runtime.executor.execute_action(11, official["id"], next_action)
    assert next_order["ok"], next_order
    assert sum(fill.qty for fill in e.exchange.match_firm(11, second_firm)) == 5
    assert e.store.scalar("SELECT COUNT(*) FROM trades WHERE firm_id=?", (first_firm,)) == 0
    estate = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (second_owner["id"],))
    currency = e.store.scalar("SELECT currency_code FROM firms WHERE id=?", (second_firm,))
    assert not e.estate_securities.needs_custody(11, estate, currency)
    validate(world)


def test_default_public_policy_does_not_invent_a_market_for_private_shares(unrepresented_assets):
    world, owner, _, official, _, firm, _ = unrepresented_assets
    e = world.economy
    e.store.update("firms", firm, status="private")
    e.lifecycle.settle_death(9, owner["id"])
    context = {"purpose": "gov_official", "estate_securities": e.estate_securities.context_for(official["id"], 10)}
    assert context["estate_securities"][0]["securities"][0]["tradeable"] is False
    assert scripted_decision("gov_official", context)["actions"] == [{"type": "do_nothing"}]
    validate(world)


def test_lost_public_role_revokes_project_and_company_actions_before_history_refresh(unrepresented_assets):
    world, owner, _, official, _, firm, project = unrepresented_assets
    e = world.economy
    e.lifecycle.settle_death(9, owner["id"])
    e.store.update("agents", official["id"], role="citizen")
    assert not e.business_control.controls(official["id"], firm)
    assert not e.construction._authorized_project(official["id"], e.construction._project(project))
    result = world.runtime.executor.execute_action(10, official["id"], {"type": "set_price", "firm_id": firm, "price": 991})
    assert not result["ok"]
    e.business_control.refresh_custody(10)
    e.project_rights.refresh(10)
    validate(world)


def test_public_administration_does_not_expose_a_private_childs_home(unrepresented_assets):
    world, owner, _, official, _, _, project = unrepresented_assets
    e = world.economy
    children = [e.households.birth(tick, owner["id"]) for tick in (8, 9)]
    for child in children:
        e.store.update("agents", child, population_tier="core", pinned_core=1)
    e.store.update("agents", children[0], population_tier="periphery", pinned_core=0)
    drain_cash(e, owner["id"], 9)
    e.lifecycle.settle_death(10, owner["id"])
    assert steward_at(e.store, project)["capacity"] == "administrator"
    assert steward_at(e.store, project)["steward_agent_id"] == official["id"]
    e.city.run_nightly(10)
    e.city.establish_effective_presence(11)
    e.store.set_meta(tick=11)
    place = e.construction._project(project)["place_id"]
    assert e.city._home_place(owner["region_id"], children[1]) == place
    before = canonical_hashes(e.store)["authoritative_sha256"]
    assert build_construction_project_detail(e.store, project_id=str(project), as_of_tick=11) is None
    workspace = build_world_workspace(e.store, as_of_tick=11)
    living = build_living_agents_workspace(e.store, as_of_tick=11, agent_id=children[1])
    assert all(row["id"] != place for row in workspace["places"])
    assert all(row["place_id"] != place for row in workspace["presence"])
    assert living["agents"][0]["residence"] is None
    app = FastAPI()
    install_v2_routes(app, world, SimpleNamespace(hosted_safe=False))
    with TestClient(app) as client:
        for path in ("/api/v2/world-map?tick=11&population=all", "/api/v2/world-map?tick=11&layers=agents", "/api/v2/map"):
            response = client.get(path)
            assert response.status_code == 200, response.text
            payload = response.json().get("data", response.json())
            assert all(row["id"] != place for row in payload.get("places", []))
            assert all(row["place_id"] != place for row in payload.get("presence", []))
            assert not any(row.get("place_id") == place for row in payload.get("agents", payload.get("core_agents", [])))
    assert canonical_hashes(e.store)["authoritative_sha256"] == before
    validate(world)


def test_appointment_evidence_is_immutable_and_order_frontier_cannot_include_its_ending(unrepresented_assets):
    world, owner, _, official, _, firm, _ = unrepresented_assets
    e = world.economy
    e.lifecycle.settle_death(9, owner["id"])
    estate = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (owner["id"],))
    placed = quote(world, 10, official["id"], estate, firm)
    assert placed["ok"], placed
    e.store.update("agents", official["id"], role="citizen")
    e.business_control.refresh_custody(10)
    e.project_rights.refresh(10)
    for table in ("estate_administrations", "estate_administration_ends"):
        assert e.store.scalar(f"SELECT COUNT(*) FROM {table}") > 0
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            e.store.execute(f"UPDATE {table} SET id=id")
        with pytest.raises(sqlite3.IntegrityError, match="permanent"):
            e.store.execute(f"DELETE FROM {table}")
    validate(world)
    e.store.execute("DROP TRIGGER estate_security_orders_immutable")
    e.store.execute("UPDATE estate_security_orders SET administration_end_frontier=(SELECT MAX(id) FROM estate_administration_ends) WHERE order_id=?",
                    (placed["order_id"],))
    with pytest.raises(EstateError, match="ended public administration"):
        e.estate_cases.check_invariants()


def test_default_public_trustee_decisions_survive_restart_export_and_exact_replay(tmp_path, monkeypatch, caplog):
    config = _config(semantics=20)
    config.setdefault("households", {})["scheduled_births"] = []
    config.setdefault("lifecycle", {}).update(population_mode="drift", birth_annual_prob=0,
        illness_onset_annual_young=0, illness_onset_annual_old=0)
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    identities = {}
    original_draw = Lifecycle._draw

    def draw(self, tick, person, mechanism):
        if tick == 1 and person == identities["owner"] and mechanism == "mortality":
            return 0.0
        return original_draw(self, tick, person, mechanism)

    monkeypatch.setattr(Lifecycle, "_draw", draw)

    def open_seeded(path, settings, *, replay=False):
        world = _world(path, settings, replay=replay)
        e, store = world.economy, world.store
        if store.tick == 0:
            owner = _owner(world)
            official = store.query_one("SELECT * FROM agents WHERE alive=1 AND age>=18 "
                "AND role='gov_official' AND region_id=? ORDER BY id LIMIT 1", (owner["region_id"],))
            assert official is not None
            currency = store.scalar("SELECT currency_code FROM accounts WHERE id=?", (owner["checking_account_id"],))
            buyer = store.query_one("SELECT a.* FROM agents a JOIN accounts ac ON ac.id=a.checking_account_id "
                "WHERE a.alive=1 AND a.age>=18 AND a.kind='citizen' AND a.retired=0 AND a.id NOT IN (?,?) "
                "AND ac.currency_code=? AND ac.balance_cents>=2100000 ORDER BY ac.balance_cents DESC,a.id LIMIT 1",
                (owner["id"], official["id"], currency))
            assert buyer is not None
            # This declared liquidity counterparty uses the recorded gateway;
            # the periphery fast path does not run adapter policy overrides.
            store.update("agents", buyer["id"], population_tier="core", pinned_core=1)
            firm = e.firms.found_firm(0, owner["id"], "Publicly administered issuer", "manufacturing",
                opening_capital_cents=10000, shares=10)
            store.update("firms", firm, status="listed")
            execute = world.runtime.executor.execute_action
            proposed = execute(0, owner["id"], {"type": "propose_construction", "owner_type": "agent",
                "owner_id": owner["id"], "region_id": owner["region_id"], "site_key": "public-trustee-home",
                "target_place_type": "private_home", "name": "Public trustee home", "required_funding_cents": 1200,
                "required_work_units": 2, "dedupe_key": "public-home-propose"})
            assert proposed["ok"], proposed
            project = proposed["project_id"]
            applied = execute(0, owner["id"], {"type": "apply_construction_permit", "project_id": project,
                "dedupe_key": "public-home-apply"})
            assert applied["ok"], applied
            approved = execute(0, _permit_clerk(world, owner["region_id"]), {"type": "decide_construction_permit",
                "case_id": applied["permit_case_id"], "decision": "approve", "reason_code": "requirements_verified",
                "dedupe_key": "public-home-approve"})
            assert approved["ok"], approved
            funded = execute(0, owner["id"], {"type": "contribute_construction_funding", "project_id": project,
                "amount_cents": 1200, "dedupe_key": "public-home-fund"})
            assert funded["ok"], funded
            e.daily_time.prepare_day(0)
            built = execute(0, owner["id"], {"type": "perform_construction_work", "project_id": project,
                "work_units": 2, "wage_cents": 100, "procurement_cents": 100, "dedupe_key": "public-home-work"})
            assert built["ok"] and built["status"] == "completed", built
            _, loan = personal_loan(e, owner["id"], 1_000_000)
            drain_cash(e, owner["id"], 0)
            store.execute("DELETE FROM social_ties WHERE agent_a=? OR agent_b=?", (owner["id"], owner["id"]))
            for person in (owner, official, buyer):
                store.update("agents", person["id"], cadence_json='{"act":1,"portfolio":9999,"career":9999,"news":9999}')
            identities.update(owner=owner["id"], official=official["id"], buyer=buyer["id"], firm=firm, project=project, loan=loan)
            e.city.initialize(0)
        adapter = world.gateway.scripted
        for purpose, original in list(adapter.policies.items()):
            def counterparty(context, original=original):
                if replay:
                    raise AssertionError("replay must read recorded decisions")
                actor = context.get("agent", {}).get("id")
                if actor not in (identities["owner"], identities["buyer"]):
                    return original(context)  # The official uses the default policy.
                actions = [{"type": "do_nothing"}]
                if actor == identities["buyer"] and context["tick"] == 2 and context.get("purpose") in ("decision", "founder"):
                    actions = [{"type": "place_order", "firm_id": identities["firm"], "side": "buy", "qty": 10, "limit_price": 200000}]
                return {"reasoning": "Declared liquidity counterparty for the public-administration acceptance case.", "actions": actions}
            adapter.register(purpose, counterparty)
        return world

    path = tmp_path / "source-public-trustee.db"
    committed = None
    for day in range(1, 4):
        source = open_seeded(path, config)
        try:
            if committed is not None:
                assert canonical_hashes(source.store)["authoritative_sha256"] == committed
            asyncio.run(source.step())
            if day == 1:
                assert steward_at(source.store, identities["project"])["capacity"] == "administrator"
            else:
                auth = source.store.query_one("SELECT * FROM estate_security_orders WHERE actor_id=?", (identities["official"],))
                assert auth is not None and auth["administration_id"] is not None
                assert auth["beneficiary_id"] is None
                assert source.store.scalar("SELECT SUM(qty) FROM trades WHERE firm_id=?", (identities["firm"],)) == 10
                assert source.store.scalar("SELECT status FROM loans WHERE id=?", (identities["loan"],)) == "paid"
                assert interests_at(source.store, identities["project"])[0]["agent_id"] is None
            validate(source)
            if day == 3:
                manifest = validate_bundle(export_bundle(source.store, tmp_path / "export"))
                for table in ("estate_administrations", "estate_administration_ends", "estate_project_custody", "estate_project_releases"):
                    assert manifest["tables"][table]["row_count"] > 0
            committed = canonical_hashes(source.store)["authoritative_sha256"]
        finally:
            source.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    settings = copy.deepcopy(config)
    settings["replay_source_path"] = str(path)
    replay = open_seeded(tmp_path / "replayed-public-trustee.db", settings, replay=True)
    try:
        for _ in range(3):
            asyncio.run(replay.step())
        proof = verify_replay(path, replay.store.path)
        assert proof["exact"], proof["differences"]
        validate(replay)
        assert not any("action.execution.failed" in record.message for record in caplog.records)
    finally:
        replay.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before

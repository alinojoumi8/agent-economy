"""Estate property preserves creditor priority, housing use and funding rights."""
import asyncio
import copy
import hashlib
import json
import sqlite3
import pytest

from engine.estate_assets import residual_people_at
from engine.estates import EstateError
from engine.ledger import SYS_COMMODITY
from engine.lifecycle import Lifecycle
from engine.project_rights import interests_at, steward_at
from research.export_bundle import export_bundle, validate_bundle
from research.hashing import canonical_hashes
from world.replay_verify import verify_replay

from .test_semantics17_household_decisions import _world
from .test_semantics19_estate_cash import foreign_bank, spent_loan
from .test_semantics20_project_rights import property_world, finish, join_household, validate
from .test_semantics13_construction import _config, _owner, _advance_to_building, _propose, _permit_clerk
from .test_v2_legal import _payment_contract


def drain_cash(e, person, tick):
    for account in e.store.query("SELECT * FROM accounts WHERE owner_type='agent' AND owner_id=? "
            "AND kind IN ('checking','savings','fx') AND balance_cents>0 ORDER BY id", (person,)):
        e.ledger.transfer(tick, account["id"], e.ledger.system_account(SYS_COMMODITY,
            currency_code=account["currency_code"]), account["balance_cents"])


def personal_loan(e, person, amount):
    wallet = e.ledger.agent_checking_id(person)
    bank = e.store.scalar("SELECT bank_id FROM accounts WHERE id=?", (wallet,))
    return bank, spent_loan(e, bank, person, wallet, amount)


def test_completed_home_stays_in_estate_custody_until_known_creditors_are_paid(property_world):
    world, owner, heir = property_world
    e = world.economy
    wallet = owner["checking_account_id"]
    bank = e.store.scalar("SELECT bank_id FROM accounts WHERE id=?", (wallet,))
    loan = spent_loan(e, bank, owner["id"], wallet, 100)
    project, _ = _advance_to_building(world, owner)
    finish(world, owner["id"], project)
    completed = e.construction._project(project)
    # Construction and its actual costs precede this declared insolvency. No
    # market valuation or new inheritance endowment is used for the house.
    for account in e.store.query("SELECT * FROM accounts WHERE owner_type='agent' AND owner_id=? "
            "AND kind IN ('checking','savings','fx') AND balance_cents>0 ORDER BY id", (owner["id"],)):
        e.ledger.transfer(8, account["id"], e.ledger.system_account(SYS_COMMODITY,
            currency_code=account["currency_code"]), account["balance_cents"])
    trades_before = e.store.scalar("SELECT COUNT(*) FROM trades")
    equity = e.bank.get(bank)["equity_account_id"]
    equity_before = e.ledger.balance(equity)
    e.lifecycle.settle_death(9, owner["id"])
    assert [share["agent_id"] for share in interests_at(e.store, project)] == [owner["id"]]
    assert steward_at(e.store, project)["steward_agent_id"] == heir["id"]
    assert steward_at(e.store, project)["capacity"] == "estate"
    assert project not in {row["id"] for row in e.project_rights.owned_projects(heir["id"])}
    assert e.city._home_place(heir["region_id"], heir["id"]) == completed["place_id"]
    assert e.ledger.balance(equity) == equity_before - 100
    item = e.store.query_one("SELECT * FROM estate_items WHERE kind='personal_project'")
    assert item["disposition"] == "retained"
    assert json.loads(item["snapshot_json"])["owner_id"] == owner["id"]
    validate(world)

    e.ledger.transfer(10, heir["checking_account_id"], wallet, 100)
    assert e.store.scalar("SELECT status FROM loans WHERE id=?", (loan,)) == "paid"
    assert e.ledger.balance(equity) == equity_before
    assert e.ledger.balance(wallet) == 0
    assert [share["agent_id"] for share in interests_at(e.store, project, 9)] == [owner["id"]]
    assert [share["agent_id"] for share in interests_at(e.store, project, 10)] == [heir["id"]]
    assert steward_at(e.store, project, 9)["capacity"] == "estate"
    assert steward_at(e.store, project, 10)["capacity"] == "owner"
    assert e.store.scalar("SELECT COUNT(*) FROM estate_project_releases") == 1
    assert e.store.scalar("SELECT COUNT(*) FROM trades") == trades_before
    assert e.construction._project(project)["owner_id"] == owner["id"]
    validate(world)


def test_representative_completes_retained_project_and_refund_recovers_only_real_cash(property_world):
    world, owner, heir = property_world
    e = world.economy
    bank, _ = personal_loan(e, owner["id"], 2000)
    project, _ = _advance_to_building(world, owner)
    drain_cash(e, owner["id"], 4)
    equity = e.bank.get(bank)["equity_account_id"]
    before = e.ledger.balance(equity)
    e.lifecycle.settle_death(5, owner["id"])
    assert steward_at(e.store, project)["capacity"] == "estate"
    finish(world, heir["id"], project)
    refund = e.store.scalar("SELECT SUM(amount_cents) FROM construction_contributions "
        "WHERE project_id=? AND contribution_type='refund' AND actor_agent_id=?", (project, owner["id"]))
    assert 0 < refund < 2000
    assert e.ledger.balance(equity) == before - 2000 + refund
    assert e.ledger.balance(owner["checking_account_id"]) == 0
    assert interests_at(e.store, project)[0]["agent_id"] == owner["id"]
    assert e.city._home_place(heir["region_id"], heir["id"]) == e.construction._project(project)["place_id"]
    assert e.store.scalar("SELECT COUNT(*) FROM estate_project_releases") == 0
    validate(world)


@pytest.mark.parametrize("has_heir", [False, True])
def test_cancellation_preserves_other_contributors_refunds_and_records_extinguished_title(property_world, has_heir):
    world, owner, heir = property_world
    e = world.economy
    bank, _ = personal_loan(e, owner["id"], 1800)
    execute = world.runtime.executor.execute_action
    proposal = _propose(world, owner, prefix="shared-funding")
    assert proposal["ok"], proposal
    project = proposal["project_id"]
    applied = execute(2, owner["id"], {"type": "apply_construction_permit", "project_id": project, "dedupe_key": "shared-permit"})
    assert applied["ok"], applied
    approved = execute(3, _permit_clerk(world, owner["region_id"]), {"type": "decide_construction_permit",
        "case_id": applied["permit_case_id"], "decision": "approve", "reason_code": "requirements_verified", "dedupe_key": "shared-approved"})
    assert approved["ok"], approved
    for contributor in (owner, heir):
        funded = execute(4, contributor["id"], {"type": "contribute_construction_funding", "project_id": project,
            "amount_cents": 600, "dedupe_key": f"shared-funder-{contributor['id']}"})
        assert funded["ok"], funded
    drain_cash(e, owner["id"], 4)
    if not has_heir:
        e.store.execute("DELETE FROM social_ties WHERE agent_a=? OR agent_b=?", (owner["id"], owner["id"]))
    equity = e.bank.get(bank)["equity_account_id"]
    before_equity, before_funder = e.ledger.balance(equity), e.ledger.balance(heir["checking_account_id"])
    e.lifecycle.settle_death(5, owner["id"])
    if has_heir:
        result = execute(6, heir["id"], {"type": "cancel_construction", "project_id": project,
            "reason_code": "owner_cancelled", "dedupe_key": "cancel-shared-project"})
        assert result["ok"], result
    assert e.construction._project(project)["status"] == "cancelled"
    refunds = e.store.query("SELECT actor_agent_id,source_account_id,amount_cents FROM construction_contributions "
                           "WHERE project_id=? AND contribution_type='refund' ORDER BY actor_agent_id", (project,))
    assert {r["actor_agent_id"]: (r["source_account_id"], r["amount_cents"]) for r in refunds} == {
        owner["id"]: (owner["checking_account_id"], 600), heir["id"]: (heir["checking_account_id"], 600)}
    assert e.ledger.balance(equity) == before_equity - 1200
    assert e.ledger.balance(heir["checking_account_id"]) == before_funder + 600
    assert e.ledger.balance(owner["checking_account_id"]) == 0
    assert e.store.scalar("SELECT disposition FROM estate_project_releases") == "cancelled"
    assert steward_at(e.store, project)["capacity"] == "vacant"
    validate(world)


@pytest.mark.parametrize("heir_death_tick", [9, 10])
def test_late_property_inheritance_faces_each_deceased_heirs_creditors(property_world, heir_death_tick):
    world, owner, heir = property_world
    e = world.economy
    _, owner_loan = personal_loan(e, owner["id"], 100)
    _, heir_loan = personal_loan(e, heir["id"], 50)
    descendant = e.store.query_one("SELECT a.* FROM agents a JOIN accounts ac ON ac.id=a.checking_account_id "
        "WHERE a.alive=1 AND a.age>=18 AND a.kind='citizen' AND a.id NOT IN (?,?) "
        "AND a.region_id=? AND ac.balance_cents>=150 ORDER BY a.id LIMIT 1",
        (owner["id"], heir["id"], heir["region_id"]))
    assert descendant is not None
    e.store.execute("DELETE FROM social_ties WHERE (agent_a=? OR agent_b=?) "
                    "AND agent_a<>? AND agent_b<>?", (heir["id"], heir["id"], owner["id"], owner["id"]))
    e.store.insert("social_ties", agent_a=heir["id"], agent_b=descendant["id"], weight=1000)
    project, _ = _advance_to_building(world, owner)
    finish(world, owner["id"], project)
    for person in (owner, heir):
        drain_cash(e, person["id"], 8)
    e.lifecycle.settle_death(9, owner["id"])
    root_estate = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (owner["id"],))
    assert residual_people_at(e.store, root_estate, 9) == {heir["id"]}
    e.lifecycle.settle_death(heir_death_tick, heir["id"])
    heir_estate = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (heir["id"],))
    if heir_death_tick > 9:
        assert residual_people_at(e.store, root_estate, 9) == {heir["id"]}
    assert residual_people_at(e.store, root_estate, heir_death_tick) == {descendant["id"]}
    e.ledger.transfer(heir_death_tick, descendant["checking_account_id"], owner["checking_account_id"], 100)
    assert e.store.scalar("SELECT status FROM loans WHERE id=?", (owner_loan,)) == "paid"
    retained = interests_at(e.store, project)
    assert [(r["agent_id"], r["estate_id"]) for r in retained] == [(heir["id"], heir_estate)]
    assert steward_at(e.store, project)["steward_agent_id"] == descendant["id"]
    assert steward_at(e.store, project)["capacity"] == "estate"
    custody = e.store.query_one("SELECT * FROM estate_project_custody WHERE estate_id=?", (heir_estate,))
    assert custody["origin"] == "inheritance"
    assert custody["opened_tick"] == heir_death_tick
    assert e.estate_property.needs_custody(heir_death_tick, heir_estate,
        e.estate_property.currency_for(e.construction._project(project)))
    validate(world)
    e.ledger.transfer(heir_death_tick + 1, descendant["checking_account_id"], heir["checking_account_id"], 50)
    assert e.store.scalar("SELECT status FROM loans WHERE id=?", (heir_loan,)) == "paid"
    assert [(r["agent_id"], r["numerator"], r["denominator"]) for r in interests_at(e.store, project)] == [
        (descendant["id"], "1", "1")]
    assert e.store.scalar("SELECT COUNT(*) FROM estate_project_releases") == 2
    assert e.ledger.balance(owner["checking_account_id"]) == e.ledger.balance(heir["checking_account_id"]) == 0
    validate(world)


def test_retained_home_keeps_minor_residuals_through_sibling_death_and_guardian_loss(property_world):
    world, owner, guardian = property_world
    e = world.economy
    personal_loan(e, owner["id"], 100)
    project, _ = _advance_to_building(world, owner)
    finish(world, owner["id"], project, start=5)
    children = [e.households.birth(tick, owner["id"]) for tick in (8, 9)]
    join_household(e, guardian["id"], owner["id"], 9)
    drain_cash(e, owner["id"], 9)
    e.lifecycle.settle_death(10, owner["id"])
    estate = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (owner["id"],))
    assert e.estate_property.beneficial_people(estate) == set(children)
    assert steward_at(e.store, project)["capacity"] == "estate"
    assert steward_at(e.store, project)["steward_agent_id"] == guardian["id"]
    assert not e.construction._authorized_project(children[0], e.construction._project(project))
    e.store.insert("social_ties", agent_a=children[0], agent_b=children[1], weight=1000)
    e.lifecycle.settle_death(11, children[0])
    assert e.estate_property.beneficial_people(estate) == {children[1]}
    membership = e.households.membership(guardian["id"])
    e.store.update("household_memberships", membership["id"], left_tick=12, end_reason="fixture_move")
    e.households.reconcile_custody(12)
    assert steward_at(e.store, project)["capacity"] == "administrator"
    assert not e.construction._authorized_project(guardian["id"], e.construction._project(project))
    assert e.city._home_place(owner["region_id"], children[1]) == e.construction._project(project)["place_id"]
    e.store.update("agents", children[1], age=18)
    e.households.reconcile_custody(13)
    assert steward_at(e.store, project)["steward_agent_id"] == children[1]
    assert steward_at(e.store, project)["capacity"] == "estate"
    assert interests_at(e.store, project)[0]["agent_id"] == owner["id"]
    e.ledger.transfer(14, guardian["checking_account_id"], owner["checking_account_id"], 100)
    assert [(r["agent_id"], r["numerator"], r["denominator"]) for r in interests_at(e.store, project)] == [
        (children[1], "1", "1")]
    assert steward_at(e.store, project, 10)["steward_agent_id"] == guardian["id"]
    assert steward_at(e.store, project, 14)["capacity"] == "owner"
    validate(world)


@pytest.fixture
def retained_home(property_world):
    world, owner, heir = property_world
    e = world.economy
    personal_loan(e, owner["id"], 100)
    project, _ = _advance_to_building(world, owner)
    finish(world, owner["id"], project)
    drain_cash(e, owner["id"], 8)
    e.lifecycle.settle_death(9, owner["id"])
    return world, owner, heir, project


def test_failed_property_release_rolls_back_the_triggering_payment_and_can_retry(retained_home, monkeypatch):
    world, owner, heir, project = retained_home
    e = world.economy
    before = canonical_hashes(e.store)["authoritative_sha256"]
    distribute = e.project_rights._distribute_lot

    def fail(*args):
        distribute(*args)
        raise RuntimeError("injected after property release")

    with monkeypatch.context() as fault:
        fault.setattr(e.project_rights, "_distribute_lot", fail)
        with pytest.raises(RuntimeError, match="injected after property release"):
            e.ledger.transfer(10, heir["checking_account_id"], owner["checking_account_id"], 100)
    assert canonical_hashes(e.store)["authoritative_sha256"] == before
    assert e.estate_cases._pending is None
    assert e.estate_cases._security_updates is None
    validate(world)
    e.ledger.transfer(10, heir["checking_account_id"], owner["checking_account_id"], 100)
    assert interests_at(e.store, project)[0]["agent_id"] == heir["id"]
    validate(world)


@pytest.mark.parametrize("invalid_frontier", [False, True])
def test_property_reconciliation_rejects_premature_or_unsupported_release(retained_home, monkeypatch, invalid_frontier):
    world, owner, heir, project = retained_home
    e = world.economy
    estate = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (owner["id"],))
    monkeypatch.setattr(e.estate_property, "needs_custody", lambda *args: False)
    if invalid_frontier:
        frontier = {**e.estate_property._frontier(), "transaction_frontier": 999999999}
        monkeypatch.setattr(e.estate_property, "_frontier", lambda: frontier)
    e.estate_cases._release_assets(10, estate)
    assert interests_at(e.store, project)[0]["agent_id"] == heir["id"]
    assert e.ledger.reconcile()[0]
    message = "invalid settlement frontier" if invalid_frontier else "before creditor settlement"
    with pytest.raises(EstateError, match=message):
        e.estate_cases.check_invariants()


def test_property_custody_and_release_evidence_are_immutable(retained_home):
    world, owner, heir, _ = retained_home
    e = world.economy
    e.ledger.transfer(10, heir["checking_account_id"], owner["checking_account_id"], 100)
    for table in ("estate_project_custody", "estate_project_releases"):
        assert e.store.scalar(f"SELECT COUNT(*) FROM {table}") > 0
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            e.store.execute(f"UPDATE {table} SET id=id")
        with pytest.raises(sqlite3.IntegrityError, match="permanent"):
            e.store.execute(f"DELETE FROM {table}")
    with pytest.raises((sqlite3.IntegrityError, EstateError), match="FOREIGN KEY|orphaned"):
        e.store.insert("estate_project_releases", custody_id=999999, tick=10,
            disposition="distributed", **e.estate_property._frontier())
        e.estate_cases.check_invariants()


def test_steward_sums_residual_interests_that_rejoin_through_two_estates(property_world):
    world, owner, payer = property_world
    e = world.economy
    personal_loan(e, owner["id"], 100)
    project, _ = _advance_to_building(world, owner)
    finish(world, owner["id"], project, start=5)
    children = [e.households.birth(tick, owner["id"]) for tick in (8, 9, 10)]
    # This isolates succession ordering by declaring adult eligibility. It is
    # not a simulation of the elapsed years needed to reach these ages.
    for child in children:
        e.store.update("agents", child, age=18)
    e.households.reconcile_custody(10)
    descendant = e.households.birth(11, children[0])
    e.store.update("agents", descendant, age=18)
    e.households.reconcile_custody(11)
    e.store.insert("social_ties", agent_a=children[1], agent_b=descendant, weight=1000)
    drain_cash(e, owner["id"], 11)
    e.lifecycle.settle_death(12, owner["id"])
    e.lifecycle.settle_death(13, children[0])
    e.lifecycle.settle_death(14, children[1])
    # Two one-third routes now belong to the same adult. A different adult's
    # single third cannot outrank their combined beneficial interest.
    assert descendant > children[2]
    assert steward_at(e.store, project)["steward_agent_id"] == descendant
    assert interests_at(e.store, project)[0]["agent_id"] == owner["id"]
    validate(world)
    e.ledger.transfer(15, payer["checking_account_id"], owner["checking_account_id"], 100)
    assert {r["agent_id"]: (r["numerator"], r["denominator"]) for r in interests_at(e.store, project)} == {
        children[2]: ("1", "3"), descendant: ("2", "3")}
    assert steward_at(e.store, project)["steward_agent_id"] == descendant
    validate(world)


def test_property_custody_uses_escrow_currency_without_cross_currency_netting(property_world):
    world, owner, heir = property_world
    e = world.economy
    currency = e.store.scalar("SELECT currency_code FROM accounts WHERE id=?", (owner["checking_account_id"],))
    other_currency = "CAD" if currency != "CAD" else "USD"
    bank = foreign_bank(e, other_currency)
    account = e.ledger.create_account("agent", owner["id"], "fx", currency_code=other_currency)
    loan = spent_loan(e, bank, owner["id"], account, 100)
    project, _ = _advance_to_building(world, owner)
    finish(world, owner["id"], project)
    drain_cash(e, owner["id"], 8)
    e.lifecycle.settle_death(9, owner["id"])
    assert e.estate_property.currency_for(e.construction._project(project)) == currency
    assert interests_at(e.store, project)[0]["agent_id"] == heir["id"]
    assert e.store.scalar("SELECT COUNT(*) FROM estate_project_custody") == 0
    assert e.store.scalar("SELECT status FROM loans WHERE id=?", (loan,)) != "paid"
    claim = e.store.query_one("SELECT * FROM estate_claims WHERE kind='bank_principal' AND source_id=?", (loan,))
    assert claim["currency_code"] == other_currency and claim["principal_cents"] == 100
    assert e.ledger.balance(e.bank.get(bank)["equity_account_id"]) == -100
    validate(world)


def test_recorded_payment_releases_property_after_restart_and_exact_replay(tmp_path, monkeypatch, caplog):
    config = _config(semantics=20)
    config.setdefault("households", {})["scheduled_births"] = []
    config.setdefault("lifecycle", {}).update(population_mode="drift", birth_annual_prob=0,
        illness_onset_annual_young=0, illness_onset_annual_old=0)
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    identities = {}
    original_draw = Lifecycle._draw

    def forced_death(self, tick, person, mechanism):
        if tick == 1 and person == identities["owner"] and mechanism == "mortality":
            return 0.0
        return original_draw(self, tick, person, mechanism)

    monkeypatch.setattr(Lifecycle, "_draw", forced_death)

    def open_seeded(path, settings, *, replay=False):
        world = _world(path, settings, replay=replay)
        e, store = world.economy, world.store
        if store.tick == 0:
            owner = _owner(world)
            currency = store.scalar("SELECT currency_code FROM accounts WHERE id=?", (owner["checking_account_id"],))
            heir = store.query_one("SELECT a.* FROM agents a JOIN accounts ac ON ac.id=a.checking_account_id "
                "WHERE a.alive=1 AND a.kind='citizen' AND a.age>=18 AND a.retired=0 AND a.id<>? "
                "AND ac.currency_code=? AND ac.balance_cents>=2100000 ORDER BY ac.balance_cents DESC,a.id LIMIT 1",
                (owner["id"], currency))
            assert heir is not None
            store.execute("DELETE FROM social_ties WHERE agent_a=? OR agent_b=?", (owner["id"], owner["id"]))
            store.insert("social_ties", agent_a=owner["id"], agent_b=heir["id"], weight=1000)
            execute = world.runtime.executor.execute_action
            # Both runs declare the same small completed home at genesis, using
            # actual permitting, funding and work. Its price remains unknown.
            proposal = execute(0, owner["id"], {"type": "propose_construction", "owner_type": "agent",
                "owner_id": owner["id"], "region_id": owner["region_id"], "site_key": "replay-retained-home",
                "target_place_type": "private_home", "name": "Retained family home", "required_funding_cents": 1200,
                "required_work_units": 2, "dedupe_key": "custody-genesis-propose"})
            assert proposal["ok"], proposal
            project = proposal["project_id"]
            applied = execute(0, owner["id"], {"type": "apply_construction_permit", "project_id": project,
                "dedupe_key": "custody-genesis-apply"})
            assert applied["ok"], applied
            approved = execute(0, _permit_clerk(world, owner["region_id"]), {"type": "decide_construction_permit",
                "case_id": applied["permit_case_id"], "decision": "approve", "reason_code": "requirements_verified",
                "dedupe_key": "custody-genesis-approve"})
            assert approved["ok"], approved
            funded = execute(0, owner["id"], {"type": "contribute_construction_funding", "project_id": project,
                "amount_cents": 1200, "dedupe_key": "custody-genesis-fund"})
            assert funded["ok"], funded
            e.daily_time.prepare_day(0)
            built = execute(0, owner["id"], {"type": "perform_construction_work", "project_id": project,
                "work_units": 2, "wage_cents": 100, "procurement_cents": 100, "dedupe_key": "custody-genesis-work"})
            assert built["ok"] and built["status"] == "completed", built
            _, loan = personal_loan(e, owner["id"], 1_000_000)
            contract = _payment_contract(world.runtime.executor, owner["id"], heir["id"], amount=2_000_000, due_tick=2)
            obligation = store.scalar("SELECT id FROM obligations WHERE contract_id=? AND obligation_type='payment'", (contract,))
            assert obligation is not None
            drain_cash(e, owner["id"], 0)
            for person in (owner, heir):
                store.update("agents", person["id"], cadence_json='{"act":1,"portfolio":9999,"career":9999,"news":9999}')
            identities.update(owner=owner["id"], heir=heir["id"], project=project, loan=loan, obligation=obligation)
            e.city.initialize(0)
        adapter = world.gateway.scripted
        for purpose, original in list(adapter.policies.items()):
            def prescribed(context, original=original):
                if replay:
                    raise AssertionError("replay must use recorded decisions")
                actor = context.get("agent", {}).get("id")
                if actor not in (identities["owner"], identities["heir"]):
                    return original(context)
                actions = [{"type": "do_nothing"}]
                if actor == identities["heir"] and context["tick"] == 2 and context.get("purpose") in ("decision", "founder"):
                    actions = [{"type": "perform_obligation", "obligation_id": identities["obligation"]}]
                return {"reasoning": "Prescribed performance of an existing payment obligation.", "actions": actions}
            adapter.register(purpose, prescribed)
        return world

    source_path = tmp_path / "source-property.db"
    committed = None
    for day in range(1, 4):
        source = open_seeded(source_path, config)
        try:
            if committed is not None:
                assert canonical_hashes(source.store)["authoritative_sha256"] == committed
            asyncio.run(source.step())
            assert source.store.scalar("SELECT COUNT(*) FROM estate_project_custody") >= 1
            if day == 1:
                assert interests_at(source.store, identities["project"])[0]["agent_id"] == identities["owner"]
                assert source.store.scalar("SELECT COUNT(*) FROM estate_project_releases") == 0
            else:
                assert source.store.scalar("SELECT status FROM obligations WHERE id=?", (identities["obligation"],)) == "performed"
                assert source.store.scalar("SELECT status FROM loans WHERE id=?", (identities["loan"],)) == "paid"
                assert interests_at(source.store, identities["project"])[0]["agent_id"] == identities["heir"]
                assert source.store.scalar("SELECT COUNT(*) FROM estate_project_releases") >= 1
            validate(source)
            if day == 3:
                manifest = validate_bundle(export_bundle(source.store, tmp_path / "export"))
                for table in ("estate_project_custody", "estate_project_releases"):
                    assert manifest["tables"][table]["row_count"] > 0
            committed = canonical_hashes(source.store)["authoritative_sha256"]
        finally:
            source.close()
    source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    settings = copy.deepcopy(config)
    settings["replay_source_path"] = str(source_path)
    replay = open_seeded(tmp_path / "replayed-property.db", settings, replay=True)
    try:
        for _ in range(3):
            asyncio.run(replay.step())
        proof = verify_replay(source_path, replay.store.path)
        assert proof["exact"], proof["differences"]
        validate(replay)
        assert not any("action.execution.failed" in record.message for record in caplog.records)
    finally:
        replay.close()
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == source_hash

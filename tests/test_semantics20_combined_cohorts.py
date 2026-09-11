"""Controlled combined losses complement, but do not replace, native aging."""
import asyncio
import copy
import hashlib
from fractions import Fraction

import pytest

from engine.ledger import SYS_COMMODITY
from engine.lifecycle import Lifecycle
from engine.project_rights import interests_at, steward_at
from research.export_bundle import export_bundle, validate_bundle
from research.hashing import canonical_hashes
from research.household_positions import household_positions
from run_config import load_config
from world.replay_verify import verify_replay

from .test_semantics17_household_decisions import _world
from .test_semantics13_construction import _config as construction_config, _permit_clerk
from .test_semantics19_estate_cash import foreign_bank, spent_loan
from .test_semantics20_estate_cases import validate
from .test_semantics20_household_positions import estate, home


@pytest.mark.parametrize("foreign_principal,with_property", [(0, False), (70, False), (70, True)],
                         ids=["usd-only", "usd-and-eur", "usd-eur-and-property"])
def test_simultaneous_owners_and_later_guardian_loss_preserve_original_assets_and_creditor_boundaries(
        tmp_path, monkeypatch, caplog, request, foreign_principal, with_property):
    """Two owners die on day 2, their surviving guardian/heir on day 3.

    Two children are born through the normal scheduled-birth mechanics. They
    remain infants throughout. This is a declared loss stress, not accelerated
    generational aging. A real accepted contract pays the first estate on day 4.
    """
    config = load_config("runs/life-course-rehearsal.yaml")
    config["lifecycle"].update(birth_annual_prob=0, illness_onset_annual_young=0,
                               illness_onset_annual_old=0)
    config["family_decisions"]["scripted_matching"] = False
    if with_property:
        config["construction"] = construction_config(semantics=20)["construction"]
    config.update(checkpoint_every=0, checkpoint_dir=str(tmp_path / "checkpoints"))
    ids = {}
    original_draw = Lifecycle._draw

    def draw(self, tick, actor, mechanism):
        if mechanism == "mortality":
            return 0.0 if ((tick == 2 and actor in (ids["a"], ids["c"]))
                           or (tick == 3 and actor == ids["b"])) else 1.0
        return original_draw(self, tick, actor, mechanism)

    monkeypatch.setattr(Lifecycle, "_draw", draw)

    def declared_project(world, owner, label, contributions, *, completed=False):
        """Record permitting, actual funding and optional work at genesis."""
        execute = world.runtime.executor.execute_action
        proposal = execute(0, owner["id"], {"type": "propose_construction", "owner_type": "agent",
            "owner_id": owner["id"], "region_id": owner["region_id"], "site_key": f"cohort-{label}",
            "target_place_type": "private_home", "name": f"Cohort {label}", "required_funding_cents": 1200,
            "required_work_units": 2 if completed else 6, "dedupe_key": f"cohort-{label}-propose"})
        assert proposal["ok"], proposal
        project = proposal["project_id"]
        applied = execute(0, owner["id"], {"type": "apply_construction_permit", "project_id": project,
            "dedupe_key": f"cohort-{label}-apply"})
        assert applied["ok"], applied
        approved = execute(0, _permit_clerk(world, owner["region_id"]), {"type": "decide_construction_permit",
            "case_id": applied["permit_case_id"], "decision": "approve", "reason_code": "requirements_verified",
            "dedupe_key": f"cohort-{label}-approve"})
        assert approved["ok"], approved
        for contributor, amount in contributions:
            funded = execute(0, contributor["id"], {"type": "contribute_construction_funding", "project_id": project,
                "amount_cents": amount, "dedupe_key": f"cohort-{label}-fund-{contributor['id']}"})
            assert funded["ok"], funded
        if completed:
            world.economy.daily_time.prepare_day(0)
            built = execute(0, owner["id"], {"type": "perform_construction_work", "project_id": project,
                "work_units": 2, "wage_cents": 100, "procurement_cents": 100, "dedupe_key": f"cohort-{label}-work"})
            assert built["ok"] and built["status"] == "completed", built
        return project

    def seeded(path, settings, *, replay=False):
        world = _world(path, settings, replay=replay)
        request.addfinalizer(world.close)
        e, store = world.economy, world.store
        if store.tick == 0:
            owners = store.query(
                "SELECT a.* FROM agents a WHERE a.kind='citizen' AND a.alive=1 "
                "AND a.age BETWEEN 18 AND 64 AND a.employer_id IS NULL "
                "AND EXISTS (SELECT 1 FROM firms f WHERE f.founder_agent_id=a.id) "
                "ORDER BY a.id LIMIT 3")
            assert len(owners) == 3
            a, b, c = owners
            payer = store.query_one(
                "SELECT a.* FROM agents a JOIN accounts w ON w.id=a.checking_account_id "
                "WHERE a.kind='citizen' AND a.alive=1 AND a.age>=18 AND w.balance_cents>=10000 "
                "AND a.id NOT IN (?,?,?) ORDER BY a.id LIMIT 1", (a["id"], b["id"], c["id"]))
            assert payer is not None
            ids.update(a=a["id"], b=b["id"], c=c["id"], payer=payer["id"])
            currency = store.scalar("SELECT currency_code FROM accounts WHERE id=?", (a["checking_account_id"],))
            assert all(store.scalar("SELECT currency_code FROM accounts WHERE id=?", (actor["checking_account_id"],))
                       == currency for actor in (b, c, payer))
            ids["currency"] = currency
            # Declared genesis social contacts, followed by actual mutual assent.
            for actor in (ids["a"], ids["b"], ids["c"]):
                store.execute("DELETE FROM social_ties WHERE agent_a=? OR agent_b=?", (actor, actor))
            store.insert("social_ties", agent_a=ids["a"], agent_b=ids["b"], weight=100)
            store.insert("social_ties", agent_a=ids["c"], agent_b=ids["b"], weight=100)
            decision = e.families.propose(0, ids["a"], "partnership", "combined-cohort-pair",
                                         partner_id=ids["b"])["household_decision_id"]
            assert e.families.respond(0, ids["b"], decision, "accept")["status"] == "applied"
            e.households.p["scheduled_births"] = [
                {"tick": 1, "parent_agent_id": ids["a"]},
                {"tick": 1, "parent_agent_id": ids["b"]}]
            ids["firm_a"] = e.firms.found_firm(0, ids["a"], "First cohort issuer", "manufacturing",
                                               opening_capital_cents=10000, shares=11)
            ids["firm_c"] = e.firms.found_firm(0, ids["c"], "Independent cohort issuer", "manufacturing",
                                               opening_capital_cents=10000, shares=13)
            if with_property:
                ids["project_a"] = declared_project(world, a, "unfinished-home", [(a, 600), (payer, 600)])
                ids["project_c"] = declared_project(world, c, "completed-home", [(c, 1200)], completed=True)
                ids["property_funding"] = [tuple(row) for row in store.query(
                    "SELECT project_id,actor_agent_id,source_account_id,amount_cents,transaction_id FROM construction_contributions "
                    "WHERE project_id IN (?,?) AND contribution_type='funding' ORDER BY id",
                    (ids["project_a"], ids["project_c"]))]
                assert len(ids["property_funding"]) == 3
            for label, actor, amount in (("loan_a", a, 1000), ("loan_b", b, 500)):
                bank = store.scalar("SELECT bank_id FROM accounts WHERE id=?", (actor["checking_account_id"],))
                ids[label] = spent_loan(e, bank, actor["id"], actor["checking_account_id"], amount)
            if foreign_principal:
                ids["foreign_bank"] = foreign_bank(e, "EUR")
                euro = e.ledger.create_account("agent", ids["a"], "fx", bank_id=ids["foreign_bank"], currency_code="EUR")
                ids["foreign_loan"] = spent_loan(e, ids["foreign_bank"], ids["a"], euro, foreign_principal)
            # Exhaust liquid personal wallets with balanced, recorded spending.
            # Company capital and ownership remain with their original issuers.
            for actor in owners:
                for wallet in store.query("SELECT * FROM accounts WHERE owner_type='agent' AND owner_id=? "
                                          "AND kind IN ('checking','savings','fx')", (actor["id"],)):
                    if wallet["balance_cents"] > 0:
                        e.ledger.transfer(0, wallet["id"], e.ledger.system_account(SYS_COMMODITY,
                            currency_code=wallet["currency_code"]), wallet["balance_cents"], kind="declared_cohort_spending")
            contract = e.legal.propose_contract(0, ids["a"], {
                "contract_type": "supplier", "title": "Declared delayed cohort receipt",
                "parties": [{"type": "agent", "id": ids["a"], "role": "supplier"},
                            {"type": "agent", "id": ids["payer"], "role": "buyer"}],
                "clauses": [{"clause_key": "price", "clause_type": "payment", "terms": {
                    "obligor_role": "buyer", "obligee_role": "supplier", "amount_cents": 1800,
                    "due_tick": 4, "currency_code": currency}}]})
            assert contract["ok"], contract
            for actor in (ids["a"], ids["payer"]):
                assert e.legal.accept_contract(0, actor, contract["contract_id"], "agent", actor)["ok"]
            ids["obligation"] = store.scalar("SELECT id FROM obligations WHERE contract_id=?", (contract["contract_id"],))
            for actor in (ids["a"], ids["b"], ids["c"], ids["payer"]):
                store.update("agents", actor, population_tier="core", pinned_core=1,
                             cadence_json='{"act":1,"portfolio":9999,"career":9999,"news":9999}')
            e.city.initialize(0)
        for purpose, original in list(world.gateway.scripted.policies.items()):
            def scenario(context, original=original):
                if replay:
                    raise AssertionError("replay must consume recorded responses")
                actor = context.get("agent", {}).get("id")
                if actor not in (ids["a"], ids["b"], ids["c"], ids["payer"]):
                    return original(context)
                action = {"type": "do_nothing"}
                if actor == ids["payer"] and context["tick"] == 4:
                    action = {"type": "perform_obligation", "obligation_id": ids["obligation"]}
                return {"reasoning": "Declared combined-loss scenario and later funded payment.", "actions": [action]}
            world.gateway.scripted.register(purpose, scenario)
        return world

    path = tmp_path / "cohort-source.db"
    history, committed = {}, None
    for day in range(1, 5):
        world = seeded(path, config)
        e, store = world.economy, world.store
        try:
            if committed is not None:
                assert canonical_hashes(store)["authoritative_sha256"] == committed
            asyncio.run(world.step())
            assert store.tick == day and store.get_meta()["active_tick"] is None
            children = [store.scalar("SELECT child_agent_id FROM parent_child_relations WHERE parent_agent_id=? "
                                     "AND formed_tick=1", (ids[label],)) for label in ("a", "b")]
            assert all(child is not None for child in children) and children[0] != children[1]
            child_a, child_b = children
            assert all(store.scalar("SELECT age FROM agents WHERE id=?", (child,)) == 0 for child in children)
            assert store.scalar("SELECT COUNT(*) FROM events WHERE kind='birth' AND json_extract(payload_json,'$.endowment_cents')=0") == 2
            for issuer, quantity in ((ids["firm_a"], 11), (ids["firm_c"], 13)):
                assert store.scalar("SELECT SUM(qty) FROM shares WHERE firm_id=?", (issuer,)) == quantity
            report = household_positions(store, tick=day)
            assert len({r["key"] for r in report["instruments"]}) == len(report["instruments"])
            if with_property:
                for label, owner_label in (("project_a", "a"), ("project_c", "c")):
                    project = ids[label]
                    current = e.construction._project(project)
                    assert current["owner_id"] == current["initiator_agent_id"] == ids[owner_label]
                    rights = interests_at(store, project)
                    assert sum((Fraction(int(row["numerator"]), int(row["denominator"])) for row in rights), Fraction()) == 1
                    instruments = [row for row in report["instruments"] if row["key"].startswith(f"property:{project}:")]
                    assert instruments
                    assert all(row["mark"] is None and row["face_cents"] is None for row in instruments)
                assert e.construction._project(ids["project_a"])["status"] == "building"
                assert e.construction._project(ids["project_c"])["status"] == "completed"
                assert [tuple(row) for row in store.query(
                    "SELECT project_id,actor_agent_id,source_account_id,amount_cents,transaction_id FROM construction_contributions "
                    "WHERE project_id IN (?,?) AND contribution_type='funding' ORDER BY id",
                    (ids["project_a"], ids["project_c"]))] == ids["property_funding"]
                assert store.scalar("SELECT COUNT(*) FROM construction_contributions WHERE project_id=? AND contribution_type='refund'",
                                    (ids["project_a"],)) == 0
                if day == 2:
                    assert [(row["agent_id"], row["numerator"], row["denominator"]) for row in interests_at(store, ids["project_c"])] == [(ids["b"], "1", "1")]
                    assert steward_at(store, ids["project_c"])["steward_agent_id"] == ids["b"]
                if day >= 3:
                    second_estate = estate(report, ids["b"])["estate_id"]
                    rights_c = interests_at(store, ids["project_c"])
                    assert [(row["agent_id"], row.get("estate_id"), row["numerator"], row["denominator"]) for row in rights_c] == [(ids["b"], second_estate, "1", "1")]
                    assert not e.construction._authorized_project(ids["b"], e.construction._project(ids["project_c"]))
                if day == 4:
                    rights_a = interests_at(store, ids["project_a"])
                    assert {(row["agent_id"], row.get("estate_id"), row["numerator"], row["denominator"]) for row in rights_a} == {
                        (child_a, None, "1", "2"), (ids["b"], second_estate, "1", "2")}
                    assert not e.construction._authorized_project(child_a, e.construction._project(ids["project_a"]))
                    assert estate(report, ids["a"])["nominee_agent_id"] == ids["a"]
                e.project_rights.check_invariants()
                e.daily_time.check_invariants()
            if day == 1:
                assert [e.households.guardian_id(child) for child in children] == [ids["a"], ids["b"]]
            if day >= 2:
                assert store.scalar("SELECT COUNT(*) FROM estate_cases WHERE opened_tick=2 AND deceased_agent_id IN (?,?)",
                                    (ids["a"], ids["c"])) == 2
                assert store.scalar("SELECT deaths FROM population_census WHERE tick=2") == 2
                assert estate(report, ids["a"])["nominee_agent_id"] == ids["a"]
            if day == 2:
                assert [e.households.guardian_id(child) for child in children] == [ids["b"], ids["b"]]
                assert e.exchange.shares_held(ids["firm_c"], "agent", ids["b"]) == 13
            if day >= 3:
                assert store.scalar("SELECT opened_tick FROM estate_cases WHERE deceased_agent_id=?", (ids["b"],)) == 3
                assert all(e.households.guardian_id(child) is None for child in children)
                assert store.scalar("SELECT unassigned_minors FROM population_census WHERE tick=?", (day,)) == 2
                assert store.scalar("SELECT COUNT(*) FROM agents WHERE id IN (?,?,?) AND alive=0", (ids["a"], ids["b"], ids["c"])) == 3
            if day == 3:
                first, second = estate(report, ids["a"]), estate(report, ids["b"])
                first_domestic = [row for row in first["creditors_in_priority_order"] if row["currency"] == ids["currency"]]
                assert first_domestic[0]["instrument_key"] == f"loan:{ids['loan_a']}"
                assert second["creditors_in_priority_order"][0]["instrument_key"] == f"loan:{ids['loan_b']}"
                path_to_child = next(row for row in home(report, child_b)["contingent_interests"]
                    if row["origin_estate_id"] == first["estate_id"] and row["beneficiary_agent_id"] == child_b)
                assert path_to_child["estate_path"] == [first["estate_id"], second["estate_id"]]
                assert path_to_child["fraction_if_intervening_claims_settled"] == {"numerator": "1", "denominator": "2"}
                assert path_to_child["amount_cents"] is None
            if day == 4:
                assert store.scalar("SELECT status FROM obligations WHERE id=?", (ids["obligation"],)) == "performed"
                assert store.scalar("SELECT outstanding_cents FROM loans WHERE id=?", (ids["loan_a"],)) == 0
                # The bank wrote off its loan asset at death. The estate still
                # owes the unpaid recovery claim; it is not the infant's loan.
                assert store.scalar("SELECT status FROM loans WHERE id=?", (ids["loan_a"],)) == "paid"
                assert store.scalar("SELECT status FROM loans WHERE id=?", (ids["loan_b"],)) == "default"
                remaining = estate(report, ids["b"])["creditors_in_priority_order"]
                assert len(remaining) == 1
                assert (remaining[0]["instrument_key"], remaining[0]["remaining_cents"], remaining[0]["currency"]) == (
                    f"loan:{ids['loan_b']}", 100, ids["currency"])
                assert store.scalar("SELECT COUNT(*) FROM loans WHERE borrower_type='agent' AND borrower_id IN (?,?)",
                                    (child_a, child_b)) == 0
                assert e.ledger.balance(e.ledger.agent_checking_id(child_a)) == 400
                assert e.ledger.balance(e.ledger.agent_checking_id(child_b)) == 0
                assert e.exchange.shares_held(ids["firm_a"], "agent", child_a) == 5
                assert e.exchange.shares_held(ids["firm_a"], "agent", ids["b"]) == 6
                assert e.exchange.shares_held(ids["firm_c"], "agent", ids["b"]) == 13
                assert e.exchange.shares_held(ids["firm_c"], "agent", child_b) == 0
                assert report["currency_conversion"] is None
                if foreign_principal:
                    foreign = estate(report, ids["a"])["creditors_in_priority_order"]
                    assert len(foreign) == 1
                    assert (foreign[0]["instrument_key"], foreign[0]["currency"], foreign[0]["remaining_cents"]) == (
                        f"loan:{ids['foreign_loan']}", "EUR", foreign_principal)
                    assert store.scalar("SELECT COALESCE(SUM(received_cents),0) FROM estate_receipts WHERE currency_code='EUR'") == 0
                    assert store.scalar("SELECT status FROM loans WHERE id=?", (ids["foreign_loan"],)) == "default"
                    equity = e.bank.get(ids["foreign_bank"])["equity_account_id"]
                    assert e.ledger.balance(equity) == -foreign_principal
                exported = validate_bundle(export_bundle(store, tmp_path / "cohort-export"))
                assert exported["tables"]["estate_cases"]["row_count"] == 3
            for tick, earlier in history.items():
                assert household_positions(store, tick=tick) == earlier
            history[day] = report
            validate(e)
            e.households.check_invariants(day)
            committed = canonical_hashes(store)["authoritative_sha256"]
        finally:
            world.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    settings = copy.deepcopy(config)
    settings["replay_source_path"] = str(path)
    replay = seeded(tmp_path / "cohort-replay.db", settings, replay=True)
    try:
        for _ in range(4):
            asyncio.run(replay.step())
        proof = verify_replay(path, replay.store.path)
        assert proof["exact"], proof["differences"]
        for tick, earlier in history.items():
            assert household_positions(replay.store, tick=tick) == earlier
        validate(replay.economy)
        assert not any("action.execution.failed" in record.message for record in caplog.records)
    finally:
        replay.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before

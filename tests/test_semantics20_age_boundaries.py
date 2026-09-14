"""Declared genesis cohorts advance daily through custody and move boundaries."""
import asyncio
import copy
import hashlib

import pytest

from engine.households import Households
from engine.lifecycle import Lifecycle
from research.export_bundle import export_bundle, validate_bundle
from research.hashing import canonical_hashes
from research.household_positions import household_positions
from run_config import load_config
from world.replay_verify import verify_replay

from .test_semantics17_household_decisions import _world
from .test_semantics20_estate_cases import validate


@pytest.mark.parametrize("death_lead_days", [1, 0], ids=["guardian-day-before", "same-day"])
def test_native_daily_majority_revokes_guardianship_and_cancels_obsolete_move(
        tmp_path, monkeypatch, caplog, request, death_lead_days):
    """Declared 17/64-year-old genesis people reach 18/65 without age jumps.

    These are synthetic initial ages, not children born during this run.
    The ward inherits through the disclosed strongest-social-tie rule, not
    a fabricated parent/child record. All citizens follow this scripted stress.
    """
    config = load_config("runs/life-course-rehearsal.yaml")
    config["lifecycle"].update(birth_annual_prob=0, illness_onset_annual_young=0,
                               illness_onset_annual_old=0)
    config["family_decisions"]["scripted_matching"] = False
    config.update(checkpoint_every=0, checkpoint_dir=str(tmp_path / "checkpoints"))
    ids = {}
    original_register = Households.register_new_people
    original_draw = Lifecycle._draw

    def register(self, tick, *, genesis=False):
        if genesis:
            assert tick == 0
            store = self.store
            owners = store.query(
                "SELECT a.id FROM agents a WHERE a.kind='citizen' AND a.alive=1 "
                "AND a.age BETWEEN 18 AND 64 AND a.employer_id IS NULL "
                "AND EXISTS (SELECT 1 FROM firms f WHERE f.founder_agent_id=a.id) "
                "ORDER BY a.id LIMIT 3")
            retired = store.query(
                "SELECT id FROM agents WHERE kind='citizen' AND retired=1 "
                "AND employer_id IS NULL ORDER BY id LIMIT 2")
            assert len(owners) == 3 and len(retired) == 2
            ids.update(owner=owners[0]["id"], companion=owners[1]["id"],
                       sponsor=owners[2]["id"], ward=retired[0]["id"],
                       retiring=retired[1]["id"])
            ids["adult_tick"] = ids["ward"] % 365
            ids["retirement_tick"] = ids["retiring"] % 365
            assert 3 < ids["adult_tick"] < ids["retirement_tick"] <= 30
            ids["death_tick"] = ids["adult_tick"] - death_lead_days
            for label, age, occupation in (("ward", 17, "child"), ("retiring", 64, "job seeker")):
                person = ids[label]
                assert store.scalar("SELECT COUNT(*) FROM employments WHERE agent_id=? AND status='active'", (person,)) == 0
                store.update("agents", person, age=age, retired=0, occupation=occupation)
            # Declare a second region before the first household census.
            store.insert("regions", id=2, region_key="boundary-destination", name="Destination",
                         currency_code="USD", population_target=10, specialization_json="{}",
                         x=0.8, y=0.5, legal_ruleset="northstar-us-inspired-1.0")
            store.update("agents", ids["sponsor"], region_id=2)
            # The new permit clerk must exist before origins and the first
            # census are recorded; late registration would invent history.
            self.e.city.initialize(0)
        original_register(self, tick, genesis=genesis)
        if genesis:
            household = self.membership(ids["owner"])["household_id"]
            for label, role in (("companion", "adult"), ("ward", "dependent")):
                member = self.membership(ids[label])
                store.update("household_memberships", member["id"], left_tick=0, end_reason="declared_genesis_household")
                store.insert("household_memberships", household_id=household, agent_id=ids[label],
                             role=role, joined_tick=0)
                self._dissolve_empty(0, member["household_id"])
            store.insert("guardianships", child_agent_id=ids["ward"], guardian_agent_id=ids["owner"],
                         started_tick=0, reason="declared_genesis_custody")
            store.execute("DELETE FROM social_ties WHERE agent_a=? OR agent_b=?", (ids["owner"], ids["owner"]))
            store.insert("social_ties", agent_a=ids["owner"], agent_b=ids["ward"], weight=100)
            store.log_event(0, "declared_boundary_cohort", {
                "genesis_ages": {str(ids["ward"]): 17, str(ids["retiring"]): 64},
                "guardian_agent_id": ids["owner"], "ward_agent_id": ids["ward"],
                "death_tick": ids["death_tick"], "inheritance_basis": "social_tie",
            }, phase="NIGHT_CLOSE")
            self.check_invariants(0)

    def draw(self, tick, actor, mechanism):
        if mechanism == "mortality":
            return 0.0 if tick == ids["death_tick"] and actor == ids["owner"] else 1.0
        return original_draw(self, tick, actor, mechanism)

    monkeypatch.setattr(Households, "register_new_people", register)
    monkeypatch.setattr(Lifecycle, "_draw", draw)

    def seeded(path, settings, *, replay=False):
        world = _world(path, settings, replay=replay)
        request.addfinalizer(world.close)
        e, store = world.economy, world.store
        if store.tick == 0:
            ids["firm"] = e.firms.found_firm(0, ids["owner"], "Boundary issuer", "manufacturing",
                                           opening_capital_cents=10000, shares=11)
            destination_firm = e.firms.found_firm(0, ids["sponsor"], "Destination issuer", "manufacturing",
                                                 opening_capital_cents=10000, shares=13)
            store.insert("jobs", tick=0, firm_id=destination_firm, title="Declared destination role",
                         wage_cents=100000000, status="open")
            for label in ("owner", "companion", "sponsor", "ward", "retiring"):
                store.update("agents", ids[label], population_tier="core", pinned_core=1,
                             cadence_json='{"act":1,"portfolio":9999,"career":1,"news":9999}')
            assert store.scalar("SELECT birth_tick FROM person_lifecycle WHERE agent_id=?", (ids["ward"],)) + 18 * 365 == ids["adult_tick"]
            assert store.scalar("SELECT birth_tick FROM person_lifecycle WHERE agent_id=?", (ids["retiring"],)) + 65 * 365 == ids["retirement_tick"]
            assert e.regions._qualified_migration_option(ids["death_tick"] - 2, ids["owner"], 2)[1] == ""
            e.city.initialize(0)
            store.commit()
        citizens = {row["id"] for row in store.query("SELECT id FROM agents WHERE kind=\'citizen\'")}
        for purpose, original in list(world.gateway.scripted.policies.items()):
            def scenario(context, original=original):
                if replay:
                    raise AssertionError("replay must consume recorded responses")
                actor = context.get("agent", {})
                if actor.get("id") not in citizens:
                    return original(context)
                action = {"type": "do_nothing"}
                tick = context["tick"]
                if actor["id"] == ids["owner"] and tick == ids["death_tick"] - 2:
                    action = {"type": "propose_household_move", "destination_region_id": 2,
                              "request_key": "pending-boundary-move"}
                elif actor["id"] == ids["companion"] and tick == ids["death_tick"] - 1:
                    pending = [row for row in context["household_decisions"]["pending"] if row["kind"] == "joint_move"]
                    assert len(pending) == 1
                    action = {"type": "respond_household", "household_decision_id": pending[0]["household_decision_id"],
                              "decision": "accept"}
                elif actor["id"] == ids["ward"] and tick == ids["adult_tick"] + 1:
                    action = {"type": "set_price", "firm_id": ids["firm"], "price": 321}
                return {"reasoning": "Declared age, guardian loss, and household assent boundary.", "actions": [action]}
            world.gateway.scripted.register(purpose, scenario)
        return world

    path = tmp_path / "boundary-source.db"
    world = seeded(path, config)
    history, committed = {}, None
    try:
        for day in range(1, ids["retirement_tick"] + 1):
            if committed is not None:
                world = seeded(path, config)
                assert canonical_hashes(world.store)["authoritative_sha256"] == committed
            e, store = world.economy, world.store
            asyncio.run(world.step())
            assert store.tick == day and store.get_meta()["active_tick"] is None
            assert store.scalar("SELECT COUNT(*) FROM person_lifecycle WHERE origin='birth'") == 0
            ward = store.query_one("SELECT * FROM agents WHERE id=?", (ids["ward"],))
            assert ward["age"] == (17 if day < ids["adult_tick"] else 18)
            assert store.scalar("SELECT SUM(qty) FROM shares WHERE firm_id=?", (ids["firm"],)) == 11
            if day == ids["death_tick"] - 2:
                assert store.scalar("SELECT status FROM household_decisions WHERE request_key='pending-boundary-move'") == "pending"
            if day == ids["death_tick"] - 1:
                assert store.scalar("SELECT status FROM household_decisions WHERE request_key='pending-boundary-move'") == "agreed"
                assert store.scalar("SELECT COUNT(*) FROM household_assents") == 2
            if day >= ids["death_tick"]:
                assert store.scalar("SELECT status FROM household_decisions WHERE request_key='pending-boundary-move'") == "cancelled"
                assert store.scalar("SELECT COUNT(*) FROM migrations WHERE agent_id IN (?,?,?)",
                                    (ids["owner"], ids["companion"], ids["ward"])) == 0
                assert {store.scalar("SELECT region_id FROM agents WHERE id=?", (ids[label],))
                        for label in ("owner", "companion", "ward")} == {1}
                assert e.exchange.shares_held(ids["firm"], "agent", ids["ward"]) == 11
                assert e.exchange.shares_held(ids["firm"], "agent", ids["companion"]) == 0
                assert store.scalar("SELECT founder_agent_id FROM firms WHERE id=?", (ids["firm"],)) == ids["owner"]
                assert e.business_control.operator_at(ids["firm"], ids["death_tick"] - 1) == ids["owner"]
                assert store.scalar("SELECT deaths FROM population_census WHERE tick=?", (ids["death_tick"],)) == 1
                assert store.scalar("SELECT basis FROM estate_beneficiaries WHERE agent_id=?", (ids["ward"],)) == "social_tie"
                if day < ids["adult_tick"]:
                    assert e.households.guardian_id(ids["ward"]) == ids["companion"]
                    assert e.business_control.operator_at(ids["firm"]) == ids["companion"]
                    assert not e.business_control.controls(ids["ward"], ids["firm"])
            if day >= ids["adult_tick"]:
                assert e.households.guardian_id(ids["ward"]) is None
                assert e.households.membership(ids["ward"])["role"] == "adult"
                assert e.business_control.operator_at(ids["firm"]) == ids["ward"]
                assert e.business_control.controls(ids["ward"], ids["firm"])
                assert not e.business_control.controls(ids["companion"], ids["firm"])
                assert store.scalar("SELECT COUNT(*) FROM events WHERE kind='adulthood' AND subject_id=? "
                                    "AND tick=? AND json_extract(payload_json,'$.endowment_cents')=0",
                                    (ids["ward"], ids["adult_tick"])) == 1
                assert store.scalar("SELECT COUNT(*) FROM loans WHERE borrower_type='agent' AND borrower_id=?", (ids["ward"],)) == 0
            if day >= ids["adult_tick"] + 1:
                assert e.firms.product(e.firms.get(ids["firm"]))["unit_price_cents"] == 321
            if day == ids["retirement_tick"]:
                retiree = store.query_one("SELECT age,retired FROM agents WHERE id=?", (ids["retiring"],))
                assert tuple(retiree) == (65, 1)
                assert store.scalar("SELECT COUNT(*) FROM events WHERE kind='retirement' AND subject_id=? AND tick=?",
                                    (ids["retiring"], day)) == 1
                manifest = validate_bundle(export_bundle(store, tmp_path / "boundary-export"))
                assert manifest["tables"]["estate_cases"]["row_count"] == 1
            report = household_positions(store, tick=day)
            for tick, previous in history.items():
                assert household_positions(store, tick=tick) == previous
            history[day] = report
            validate(e)
            e.households.check_invariants(day)
            committed = canonical_hashes(store)["authoritative_sha256"]
            world.close()
    finally:
        world.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    settings = copy.deepcopy(config)
    settings["replay_source_path"] = str(path)
    replay = seeded(tmp_path / "boundary-replay.db", settings, replay=True)
    try:
        for _ in range(ids["retirement_tick"]):
            asyncio.run(replay.step())
        proof = verify_replay(path, replay.store.path)
        assert proof["exact"], proof["differences"]
        for tick, previous in history.items():
            assert household_positions(replay.store, tick=tick) == previous
        validate(replay.economy)
        assert not any("action.execution.failed" in record.message for record in caplog.records)
    finally:
        replay.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before

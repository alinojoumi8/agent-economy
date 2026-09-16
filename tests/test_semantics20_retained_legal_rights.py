"""Unfiled estate receivables keep their owner and gain actual representation."""
import asyncio
import copy
import hashlib
import json

import pytest

from agents.memory import Memory
from agents.policies import POLICIES
from agents.prompts import ContextBuilder
from engine.lifecycle import Lifecycle
from research.export_bundle import export_bundle, validate_bundle
from research.hashing import canonical_hashes
from world.replay_verify import verify_replay

from .test_semantics20_legal_representation import act
from .test_semantics20_legal_authority import open_matter
from .test_semantics20_project_rights import property_world, validate
from .test_semantics20_legal_awards import award_case
from .test_semantics20_wage_awards import wage_case, verify
from .test_semantics20_legal_representation import counsel_case, request
from .test_semantics13_construction import _config, _owner
from .test_semantics17_household_decisions import _world


def receivable(world, claimant, respondent, *, amount=100, due_tick=2):
    currency = world.store.scalar("SELECT currency_code FROM accounts WHERE id=?",
        (world.economy.ledger.agent_checking_id(claimant),))
    contract = act(world, 0, claimant, "propose_contract", payload={
        "contract_type": "supplier", "title": "Unfiled estate payment",
        "parties": [{"type": "agent", "id": claimant, "role": "supplier"},
                    {"type": "agent", "id": respondent, "role": "buyer"}],
        "clauses": [{"clause_key": "price", "clause_type": "payment", "terms": {
            "obligor_role": "buyer", "obligee_role": "supplier", "amount_cents": amount,
            "currency_code": currency, "due_tick": due_tick, "grace_ticks": 0}}]})["contract_id"]
    for person in (claimant, respondent):
        act(world, 0, person, "accept_contract", contract_id=contract, party_type="agent", party_id=person)
    return world.store.scalar("SELECT id FROM obligations WHERE contract_id=?", (contract,))


def actual_context(world, actor, tick):
    return world.runtime.ctx.build(world.store.query_one("SELECT * FROM agents WHERE id=?", (actor,)), tick)


@pytest.mark.parametrize("public", [False, True])
def test_unfiled_contract_receivable_survives_death_and_default_filing_collects_actual_cash(property_world, public):
    world, owner, heir = property_world
    e = world.economy
    other = world.store.scalar("SELECT id FROM agents WHERE alive=1 AND age>=18 AND kind='citizen' "
        "AND region_id=? AND id NOT IN (?,?) ORDER BY id LIMIT 1", (owner["region_id"], owner["id"], heir["id"]))
    obligation = receivable(world, owner["id"], other)
    if public:
        world.store.execute("DELETE FROM social_ties WHERE agent_a=? OR agent_b=?", (owner["id"], owner["id"]))
    e.lifecycle.settle_death(1, owner["id"])
    estate = world.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (owner["id"],))
    assert world.store.scalar("SELECT COUNT(*) FROM legal_matters") == 0
    assert not e.estate_securities.lots(estate) and not e.estate_property.pending(estate)
    appointment = e.estate_administration.current(estate)
    if public:
        assert appointment is not None, "an unfiled payment right still needs a public representative"
        actor = appointment["administrator_agent_id"]
    else:
        assert appointment is None
        actor = heir["id"]
    assert actual_context(world, actor, 1)["estate_legal_work"]["eligible_actions"] == []
    e.legal.run_nightly(3)
    e.legal_representation.reconcile(3)
    assert actual_context(world, actor, 2)["estate_legal_work"]["eligible_actions"] == []
    context = actual_context(world, actor, 3)
    offered = context["estate_legal_work"]["eligible_actions"][0]
    assert offered["claimant"] == {"type": "agent", "id": owner["id"]}
    assert offered["requested_remedy"]["obligation_ids"] == [obligation]
    envelope = POLICIES[context["purpose"]](context)
    assert envelope["actions"][0] == offered
    filed = world.runtime.executor.execute_action(3, actor, offered)
    assert filed["ok"], filed
    matter = filed["matter_id"]
    assert actual_context(world, actor, 3)["estate_legal_work"]["eligible_actions"] == []
    # The same default representative supplies the actual breach evidence.
    context = actual_context(world, actor, 3)
    brief = POLICIES[context["purpose"]](context)["actions"][0]
    assert brief["type"] == "submit_filing" and brief["filer_id"] == owner["id"]
    assert world.runtime.executor.execute_action(3, actor, brief)["ok"]
    before = e.ledger.balance(heir["checking_account_id"])
    context = actual_context(world, actor, 3)
    offer = POLICIES[context["purpose"]](context)["actions"][0]
    assert offer["type"] == "propose_settlement"
    assert world.runtime.executor.execute_action(3, actor, offer)["ok"]
    act(world, 3, other, "accept_settlement", matter_id=matter)
    assert world.store.scalar("SELECT SUM(p.amount_cents) FROM legal_award_payments p JOIN legal_awards a ON a.id=p.award_id WHERE a.matter_id=?", (matter,)) == 100
    if not public:
        assert e.ledger.balance(heir["checking_account_id"]) == before + 100
    assert e.estate_administration.current(estate) is None
    assert actual_context(world, actor, 4)["estate_legal_work"]["eligible_actions"] == []
    validate(world)


@pytest.mark.parametrize("public", [False, True])
def test_unfiled_wages_remain_a_nominee_claim_in_the_representatives_context(award_case, public):
    c = wage_case(award_case)
    e = c.e
    e.earned_wages.process_due(1)
    if public:
        e.store.execute("DELETE FROM social_ties WHERE agent_a=? OR agent_b=?", (c.creditor, c.creditor))
        e.store.update("agents", c.judge, role="gov_official")
    e.lifecycle.settle_death(2, c.creditor)
    estate = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (c.creditor,))
    appointment = e.estate_administration.current(estate)
    assert not public or appointment is not None
    actor = appointment["administrator_agent_id"] if public else c.heir
    builder = ContextBuilder(e, Memory(e.store, e.config), e.config)
    context = builder.build(e.store.query_one("SELECT * FROM agents WHERE id=?", (actor,)), 2)
    action = context["estate_legal_work"]["eligible_actions"][0]
    assert action["claimant"] == {"type": "agent", "id": c.creditor}
    assert action["requested_remedy"]["amount_cents"] == 150
    assert action["requested_remedy"]["wage_scopes"][0]["claim_id"] == c.wage_claim
    assert c.executor.execute_action(2, actor, action)["ok"]
    assert e.earned_wages.holder(c.wage_claim)["owner_id"] == c.creditor
    assert builder.build(e.store.query_one("SELECT * FROM agents WHERE id=?", (actor,)), 2)["estate_legal_work"]["eligible_actions"] == []
    verify(c)


@pytest.mark.parametrize("public", [False, True])
def test_dual_party_representative_can_file_but_only_an_independent_official_can_decide(property_world, public):
    world, owner, heir = property_world
    e = world.economy
    matter, evidence = open_matter(world, owner["id"], heir["id"])
    if public:
        world.store.execute("DELETE FROM social_ties WHERE agent_a IN (?,?) OR agent_b IN (?,?)",
                            (owner["id"], heir["id"], owner["id"], heir["id"]))
    e.lifecycle.settle_death(9, owner["id"])
    actor = heir["id"]
    if public:
        e.lifecycle.settle_death(9, heir["id"])
        estates = world.store.query("SELECT id FROM estate_cases WHERE deceased_agent_id IN (?,?) ORDER BY id", (owner["id"], heir["id"]))
        representatives = {e.estate_administration.current(row["id"])["administrator_agent_id"] for row in estates}
        assert len(representatives) == 1
        actor = representatives.pop()
    for party in (owner["id"], heir["id"]):
        act(world, 10, actor, "submit_filing", matter_id=matter, filer_type="agent", filer_id=party,
            filing_type="evidence", evidence_event_ids=[evidence], body="Recorded facts for the specified party.")
    proof = json.loads(world.store.scalar("SELECT proof_json FROM legal_action_authorities ORDER BY id DESC LIMIT 1"))
    assert proof["adversarial_authority"] is not None
    lawyer = world.store.scalar("SELECT id FROM agents WHERE alive=1 AND age>=18 AND role='lawyer' ORDER BY id LIMIT 1")
    request = {"type": "request_legal_counsel", "matter_id": matter, "side": "claimant", "counsel_agent_id": lawyer}
    assert not world.runtime.executor.execute_action(10, actor, {**request, "scopes": ["accept_settlement"]})["ok"]
    accepted = world.runtime.executor.execute_action(10, actor, {**request, "scopes": ["submit_filing"]})
    assert accepted["ok"], accepted
    act(world, 10, lawyer, "respond_legal_counsel", request_id=accepted["request_id"], decision="accept")
    act(world, 10, lawyer, "submit_filing", matter_id=matter, filer_type="agent", filer_id=owner["id"],
        filing_type="brief", evidence_event_ids=[], body="Consenting counsel supplies the estate's procedural response.")
    remedy = json.loads(world.store.scalar("SELECT requested_remedy_json FROM legal_matters WHERE id=?", (matter,)))
    for proposer in (actor, lawyer):
        assert not world.runtime.executor.execute_action(10, proposer, {"type": "propose_settlement", "matter_id": matter,
            "terms": {"remedy": remedy}})["ok"]
    act(world, 10, actor, "end_legal_counsel", request_id=accepted["request_id"])
    decision = {"type": "issue_legal_decision", "matter_id": matter, "outcome": "claimant",
                "findings": [{"key": "liability", "value": True}], "evidence_event_ids": [evidence], "remedy": remedy}
    assert not world.runtime.executor.execute_action(10, actor, decision)["ok"]
    regulator = world.store.scalar("SELECT id FROM agents WHERE alive=1 AND role='labor_regulator' ORDER BY id LIMIT 1")
    assert world.runtime.executor.execute_action(10, regulator, decision)["ok"]
    assert world.store.scalar("SELECT SUM(p.amount_cents) FROM legal_award_payments p JOIN legal_awards a ON a.id=p.award_id WHERE a.matter_id=?", (matter,)) == 10
    assert world.store.scalar("SELECT COUNT(*) FROM estate_administrations a WHERE NOT EXISTS "
                              "(SELECT 1 FROM estate_administration_ends x WHERE x.administration_id=a.id)") == 0
    validate(world)


def test_payment_before_breach_releases_public_administration_without_inventing_a_case(property_world):
    world, owner, payer = property_world
    e = world.economy
    obligation = receivable(world, owner["id"], payer["id"], due_tick=3)
    world.store.execute("DELETE FROM social_ties WHERE agent_a=? OR agent_b=?", (owner["id"], owner["id"]))
    e.lifecycle.settle_death(1, owner["id"])
    estate = world.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (owner["id"],))
    assert e.estate_administration.current(estate) is not None
    act(world, 2, payer["id"], "perform_obligation", obligation_id=obligation)
    assert e.estate_administration.current(estate) is None
    assert world.store.scalar("SELECT COUNT(*) FROM legal_matters") == 0
    validate(world)


def test_oversized_or_previously_presented_right_does_not_starve_a_later_supported_claim(property_world):
    world, owner, heir = property_world
    e = world.economy
    other = world.store.scalar("SELECT id FROM agents WHERE alive=1 AND age>=18 AND kind='citizen' "
        "AND region_id=? AND id NOT IN (?,?) ORDER BY id LIMIT 1", (owner["region_id"], owner["id"], heir["id"]))
    receivable(world, owner["id"], other, amount=e.legal.max_damages_cents + 1)
    first = receivable(world, owner["id"], other, amount=40)
    second = receivable(world, owner["id"], other, amount=60)
    e.lifecycle.settle_death(1, owner["id"])
    e.legal.run_nightly(3)
    for obligation in (first, second):
        context = actual_context(world, heir["id"], 3)["estate_legal_work"]
        assert context["rights"][0]["blocked_reason"] == "requested_relief_above_ruleset_limit"
        action = context["eligible_actions"][0]
        assert action["requested_remedy"]["obligation_ids"] == [obligation]
        assert world.runtime.executor.execute_action(3, heir["id"], action)["ok"]
    assert not actual_context(world, heir["id"], 3)["estate_legal_work"]["eligible_actions"]
    validate(world)


@pytest.mark.parametrize("loss", ["private_death", "public_role"])
def test_a_cached_estate_claim_cannot_outlive_its_actors_authority(property_world, loss):
    world, owner, heir = property_world
    e = world.economy
    other = world.store.scalar("SELECT id FROM agents WHERE alive=1 AND age>=18 AND kind='citizen' "
        "AND region_id=? AND id NOT IN (?,?) ORDER BY id LIMIT 1", (owner["region_id"], owner["id"], heir["id"]))
    receivable(world, owner["id"], other)
    if loss == "public_role":
        world.store.execute("DELETE FROM social_ties WHERE agent_a=? OR agent_b=?", (owner["id"], owner["id"]))
    e.lifecycle.settle_death(1, owner["id"])
    e.legal.run_nightly(3)
    estate = world.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (owner["id"],))
    actor = heir["id"] if loss == "private_death" else e.estate_administration.current(estate)["administrator_agent_id"]
    action = actual_context(world, actor, 3)["estate_legal_work"]["eligible_actions"][0]
    if loss == "private_death":
        e.lifecycle.settle_death(3, actor)
    else:
        world.store.update("agents", actor, role=None)
    before = world.store.scalar("SELECT COUNT(*) FROM legal_matters")
    assert not world.runtime.executor.execute_action(3, actor, action)["ok"]
    assert world.store.scalar("SELECT COUNT(*) FROM legal_matters") == before
    e.legal_representation.reconcile(3)
    validate(world)


@pytest.mark.parametrize("new_owner", ["client", "counsel"])
def test_new_opposing_control_ends_an_existing_financial_counsel_mandate(counsel_case, new_owner):
    c = counsel_case
    invitation = request(c, scopes=["submit_filing", "propose_settlement", "accept_settlement"])
    act(c.world, 9, c.lawyer, "respond_legal_counsel", request_id=invitation, decision="accept")
    heir = c.owner["id"] if new_owner == "client" else c.lawyer
    c.store.execute("DELETE FROM social_ties WHERE agent_a=? OR agent_b=?", (c.other["id"], c.other["id"]))
    c.store.insert("social_ties", agent_a=c.other["id"], agent_b=heir, weight=1)
    c.e.lifecycle.settle_death(10, c.other["id"])
    assert c.e.legal_representation.assignments(c.lawyer, 10) == []
    assert not c.world.runtime.executor.execute_action(10, c.lawyer, {"type": "submit_filing", "matter_id": c.matter,
        "filer_type": "agent", "filer_id": c.owner["id"], "filing_type": "brief", "evidence_event_ids": [], "body": "Stale mandate."})["ok"]
    c.e.legal_representation.reconcile(10)
    assert c.store.scalar("SELECT reason FROM legal_counsel_ends WHERE request_id=?", (invitation,)) == (
        "client_authority_lost" if new_owner == "client" else "counsel_unavailable")
    validate(c.world)


def test_default_public_claim_after_death_collects_and_replays_through_daily_restarts(tmp_path, monkeypatch, caplog):
    config = _config(semantics=20)
    config.setdefault("households", {})["scheduled_births"] = []
    config.setdefault("lifecycle", {}).update(population_mode="drift", birth_annual_prob=0,
        illness_onset_annual_young=0, illness_onset_annual_old=0)
    config.setdefault("legal", {})["response_ticks"] = 20
    config.setdefault("llm", {})["institutional_role_purposes"] = True
    config["checkpoint_every"] = 0
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    ids = {}
    original_draw = Lifecycle._draw

    def draw(self, tick, actor, mechanism):
        if tick == 1 and actor == ids["owner"] and mechanism == "mortality":
            return 0.0
        return original_draw(self, tick, actor, mechanism)
    monkeypatch.setattr(Lifecycle, "_draw", draw)

    def open_seeded(path, settings, *, replay=False):
        world = _world(path, settings, replay=replay)
        store = world.store
        if store.tick == 0:
            owner = _owner(world)
            other = store.scalar("SELECT id FROM agents WHERE alive=1 AND age>=18 AND retired=0 AND kind='citizen' "
                "AND region_id=? AND id<>? ORDER BY id LIMIT 1", (owner["region_id"], owner["id"]))
            trustee = store.scalar("SELECT id FROM agents WHERE alive=1 AND age>=18 AND role='gov_official' "
                "AND region_id=? ORDER BY id LIMIT 1", (owner["region_id"],))
            obligation = receivable(world, owner["id"], other, due_tick=0)
            contract = store.scalar("SELECT contract_id FROM obligations WHERE id=?", (obligation,))
            assert store.scalar("SELECT COUNT(*) FROM legal_matters") == 0
            ids.update(owner=owner["id"], other=other, trustee=trustee, obligation=obligation, contract=contract)
            store.execute("DELETE FROM social_ties WHERE agent_a=? OR agent_b=?", (owner["id"], owner["id"]))
            for actor in (owner["id"], other, trustee):
                store.update("agents", actor, population_tier="core", pinned_core=1,
                    cadence_json='{"act":1,"portfolio":9999,"career":9999,"news":9999}')
        for purpose, original in list(world.gateway.scripted.policies.items()):
            def scenario(context, original=original):
                if replay:
                    raise AssertionError("replay must use recorded decisions")
                actor = context.get("agent", {}).get("id")
                if actor not in (ids["owner"], ids["other"]):
                    return original(context)
                action = {"type": "do_nothing"}
                matter = store.query_one("SELECT * FROM legal_matters WHERE contract_id=? ORDER BY id LIMIT 1", (ids["contract"],))
                if actor == ids["other"] and matter is not None and matter["status"] == "settlement_offered":
                    action = {"type": "accept_settlement", "matter_id": matter["id"]}
                return {"reasoning": "Declared missed payment and counterparty acceptance; public representation uses the default policy.", "actions": [action]}
            world.gateway.scripted.register(purpose, scenario)
        return world

    path = tmp_path / "source-unfiled.db"
    committed = None
    for day in range(1, 6):
        source = open_seeded(path, config)
        try:
            if committed is not None:
                assert canonical_hashes(source.store)["authoritative_sha256"] == committed
            asyncio.run(source.step())
            estate = source.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (ids["owner"],))
            assert estate is not None
            if day == 1:
                authority = source.store.query_one("SELECT a.* FROM legal_action_authorities a JOIN legal_matters m ON m.id=a.matter_id "
                    "WHERE m.contract_id=? AND a.action='file_claim'", (ids["contract"],))
                completed = source.store.scalar("SELECT completed_event_id FROM estate_cases WHERE id=?", (estate,))
                assert authority is not None and authority["actor_id"] == ids["trustee"]
                assert completed < authority["event_id"] < authority["effect_event_id"]
                assert source.economy.estate_administration.current(estate)["administrator_agent_id"] == ids["trustee"]
            if day == 5:
                matter = source.store.query_one("SELECT * FROM legal_matters WHERE contract_id=?", (ids["contract"],))
                assert matter["status"] == "settled"
                assert source.store.scalar("SELECT actor_id FROM legal_action_authorities WHERE matter_id=? AND action='file_claim'", (matter["id"],)) == ids["trustee"]
                assert source.store.scalar("SELECT COUNT(*) FROM legal_filings WHERE matter_id=? AND filer_id=?", (matter["id"], ids["owner"])) == 1
                assert source.store.scalar("SELECT SUM(p.amount_cents) FROM legal_award_payments p JOIN legal_awards a ON a.id=p.award_id WHERE a.matter_id=?", (matter["id"],)) == 100
                assert source.economy.estate_administration.current(estate) is None
                manifest = validate_bundle(export_bundle(source.store, tmp_path / "export"))
                assert manifest["tables"]["legal_action_authorities"]["row_count"] >= 4
            validate(source)
            committed = canonical_hashes(source.store)["authoritative_sha256"]
        finally:
            source.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    settings = copy.deepcopy(config)
    settings["replay_source_path"] = str(path)
    replay = open_seeded(tmp_path / "replay-unfiled.db", settings, replay=True)
    try:
        for _ in range(5):
            asyncio.run(replay.step())
        result = verify_replay(path, replay.store.path)
        assert result["exact"], result["differences"]
        validate(replay)
        assert not any("action.execution.failed" in record.message for record in caplog.records)
    finally:
        replay.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before

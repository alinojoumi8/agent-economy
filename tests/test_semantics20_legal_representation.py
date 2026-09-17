"""Recorded authority for an estate party and consenting legal counsel."""
import asyncio
import copy
import hashlib
import json
import sqlite3
from types import SimpleNamespace

import pytest

from agents.policies import POLICIES, scripted_decision
from research.export_bundle import export_bundle, validate_bundle
from research.hashing import canonical_hashes
from world.replay_verify import verify_replay

from .test_semantics20_legal_authority import open_matter
from .test_semantics20_project_rights import property_world, validate
from .test_semantics13_construction import _config, _owner
from .test_semantics17_household_decisions import _world


def test_open_legal_work_keeps_an_assetless_estate_represented(property_world):
    world, owner, claimant = property_world
    e = world.economy
    e.store.execute("DELETE FROM social_ties WHERE agent_a=? OR agent_b=?", (owner["id"], owner["id"]))
    matter, _ = open_matter(world, claimant["id"], owner["id"])
    e.lifecycle.settle_death(9, owner["id"])
    estate = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (owner["id"],))
    assert not e.estate_securities.lots(estate) and not e.estate_property.pending(estate)
    appointment = e.estate_administration.current(estate)
    assert appointment is not None and appointment["administrator_agent_id"] is not None
    result = world.runtime.executor.execute_action(10, appointment["administrator_agent_id"], {
        "type": "submit_filing", "matter_id": matter, "filer_type": "agent", "filer_id": owner["id"],
        "filing_type": "brief", "body": "The estate contests this claim.", "evidence_event_ids": []})
    assert result["ok"], result
    filing = e.store.query_one("SELECT * FROM legal_filings WHERE id=?", (result["filing_id"],))
    assert filing["filer_id"] == owner["id"]
    validate(world)


def test_an_unrelated_person_cannot_insert_a_filing_under_its_own_identity(property_world):
    world, owner, claimant = property_world
    matter, _ = open_matter(world, claimant["id"], owner["id"])
    outsider = world.store.scalar("SELECT id FROM agents WHERE alive=1 AND age>=18 AND id NOT IN (?,?) ORDER BY id LIMIT 1",
                                   (owner["id"], claimant["id"]))
    before = world.store.scalar("SELECT COUNT(*) FROM legal_filings")
    result = world.runtime.executor.execute_action(9, outsider, {"type": "submit_filing", "matter_id": matter,
        "filer_type": "agent", "filer_id": outsider, "filing_type": "evidence", "evidence_event_ids": [],
        "body": "An unsolicited statement from someone outside the matter."})
    assert not result["ok"], "control of an unrelated identity does not confer standing in this matter"
    assert world.store.scalar("SELECT COUNT(*) FROM legal_filings") == before


def test_a_lawyer_cannot_self_appoint_to_file_someone_elses_claim(property_world):
    world, owner, respondent = property_world
    lawyer = world.store.scalar("SELECT id FROM agents WHERE alive=1 AND age>=18 AND role='lawyer' ORDER BY id LIMIT 1")
    assert lawyer is not None
    result = world.runtime.executor.execute_action(8, lawyer, {"type": "file_claim",
        "claimant": {"type": "agent", "id": owner["id"]}, "respondent": {"type": "agent", "id": respondent["id"]},
        "counsel_agent_id": lawyer, "claim_type": "unrequested_claim", "requested_remedy": {"type": "dismissal"}})
    assert not result["ok"], "a lawyer naming itself as counsel is not a client mandate"
    assert world.store.scalar("SELECT COUNT(*) FROM legal_matters") == 0


def act(world, tick, actor, kind, **values):
    result = world.runtime.executor.execute_action(tick, actor, {"type": kind, **values})
    assert result["ok"], result
    return result


@pytest.fixture
def counsel_case(property_world):
    world, owner, other = property_world
    matter, evidence = open_matter(world, owner["id"], other["id"])
    lawyer = world.store.scalar("SELECT id FROM agents WHERE alive=1 AND age>=18 AND role='lawyer' ORDER BY id LIMIT 1")
    assert lawyer is not None
    return SimpleNamespace(world=world, e=world.economy, store=world.store, owner=owner, other=other,
                           matter=matter, evidence=evidence, lawyer=lawyer)


def request(c, side="claimant", scopes=None, tick=9):
    person = c.owner if side == "claimant" else c.other
    return act(c.world, tick, person["id"], "request_legal_counsel", matter_id=c.matter, side=side,
        counsel_agent_id=c.lawyer, scopes=scopes or ["submit_filing", "propose_settlement"])["request_id"]


def lawyer_filing(c, side="claimant"):
    person = c.owner if side == "claimant" else c.other
    return {"type": "submit_filing", "matter_id": c.matter, "filer_type": "agent", "filer_id": person["id"],
            "filing_type": "evidence", "evidence_event_ids": [c.evidence], "body": "The client relies on the recorded event."}


@pytest.mark.parametrize("side", ["claimant", "respondent"])
def test_counsel_needs_client_request_and_acceptance_for_the_named_side(counsel_case, side):
    c = counsel_case
    invitation = request(c, side)
    assert not c.world.runtime.executor.execute_action(9, c.lawyer, lawyer_filing(c, side))["ok"]
    assert not c.world.runtime.executor.execute_action(9, c.owner["id"], {
        "type": "respond_legal_counsel", "request_id": invitation, "decision": "accept"})["ok"]
    act(c.world, 9, c.lawyer, "respond_legal_counsel", request_id=invitation, decision="accept")
    filed = c.world.runtime.executor.execute_action(10, c.lawyer, lawyer_filing(c, side))
    assert filed["ok"], filed
    authority = c.store.query_one("SELECT * FROM legal_action_authorities WHERE action='submit_filing' ORDER BY id DESC LIMIT 1")
    assert authority["capacity"] == "counsel" and authority["counsel_request_id"] == invitation and authority["side"] == side
    assert c.store.scalar("SELECT filer_id FROM legal_filings WHERE id=?", (filed["filing_id"],)) != c.lawyer
    validate(c.world)


@pytest.mark.parametrize("can_accept", [False, True])
def test_settlement_acceptance_requires_its_explicit_mandate_and_real_money(counsel_case, can_accept):
    c = counsel_case
    scopes = ["submit_filing"] + (["accept_settlement"] if can_accept else [])
    invitation = request(c, "respondent", scopes)
    act(c.world, 9, c.lawyer, "respond_legal_counsel", request_id=invitation, decision="accept")
    remedy = json.loads(c.store.scalar("SELECT requested_remedy_json FROM legal_matters WHERE id=?", (c.matter,)))
    act(c.world, 10, c.owner["id"], "propose_settlement", matter_id=c.matter, terms={"remedy": remedy})
    owner_cash = c.e.ledger.balance(c.owner["checking_account_id"])
    lawyer_cash = c.e.ledger.balance(c.e.ledger.agent_checking_id(c.lawyer))
    result = c.world.runtime.executor.execute_action(10, c.lawyer, {"type": "accept_settlement", "matter_id": c.matter})
    assert bool(result["ok"]) is can_accept, result
    assert c.e.ledger.balance(c.owner["checking_account_id"]) == owner_cash + (10 if can_accept else 0)
    assert c.e.ledger.balance(c.e.ledger.agent_checking_id(c.lawyer)) == lawyer_cash
    if can_accept:
        assert c.store.scalar("SELECT reason FROM legal_counsel_ends WHERE request_id=?", (invitation,)) == "matter_closed"
    validate(c.world)


@pytest.mark.parametrize("ending", ["revocation", "withdrawal", "client_death", "counsel_death", "counsel_role_loss"])
def test_authority_loss_stops_later_filings_without_rewriting_earlier_ones(counsel_case, ending):
    c = counsel_case
    invitation = request(c)
    act(c.world, 9, c.lawyer, "respond_legal_counsel", request_id=invitation, decision="accept")
    filed = c.world.runtime.executor.execute_action(9, c.lawyer, lawyer_filing(c))
    assert filed["ok"], filed
    before = dict(c.store.query_one("SELECT * FROM legal_filings WHERE id=?", (filed["filing_id"],)))
    if ending == "revocation":
        act(c.world, 10, c.owner["id"], "end_legal_counsel", request_id=invitation)
    elif ending == "withdrawal":
        act(c.world, 10, c.lawyer, "end_legal_counsel", request_id=invitation)
    elif ending.endswith("death"):
        c.e.lifecycle.settle_death(10, c.owner["id"] if ending == "client_death" else c.lawyer)
    else:
        c.store.update("agents", c.lawyer, role=None, occupation="citizen")
    assert not c.world.runtime.executor.execute_action(10, c.lawyer, lawyer_filing(c))["ok"]
    c.e.legal_representation.reconcile(10)
    assert c.store.scalar("SELECT COUNT(*) FROM legal_counsel_ends WHERE request_id=?", (invitation,)) == 1
    assert dict(c.store.query_one("SELECT * FROM legal_filings WHERE id=?", (filed["filing_id"],))) == before
    validate(c.world)


def test_declined_expired_and_replaced_requests_preserve_each_consent(counsel_case):
    c = counsel_case
    first = request(c)
    act(c.world, 9, c.lawyer, "respond_legal_counsel", request_id=first, decision="decline")
    second = request(c, tick=10)
    c.e.legal_representation.reconcile(17)
    assert c.store.scalar("SELECT reason FROM legal_counsel_ends WHERE request_id=?", (second,)) == "expired"
    assert not c.world.runtime.executor.execute_action(17, c.lawyer, {
        "type": "respond_legal_counsel", "request_id": second, "decision": "accept"})["ok"]
    third = request(c, tick=17)
    act(c.world, 17, c.lawyer, "respond_legal_counsel", request_id=third, decision="accept")
    assert [r["id"] for r in c.e.legal_representation.assignments(c.lawyer, 17)] == [third]
    assert not c.e.legal_representation.context_for(c.lawyer, 8)["pending_requests"]
    validate(c.world)


def test_a_lawyer_cannot_swap_sides_or_later_adjudicate_its_former_matter(counsel_case):
    c = counsel_case
    invitation = request(c)
    act(c.world, 9, c.lawyer, "respond_legal_counsel", request_id=invitation, decision="accept")
    act(c.world, 10, c.lawyer, "end_legal_counsel", request_id=invitation)
    attempted = c.world.runtime.executor.execute_action(10, c.other["id"], {"type": "request_legal_counsel",
        "matter_id": c.matter, "side": "respondent", "counsel_agent_id": c.lawyer, "scopes": ["submit_filing"]})
    assert not attempted["ok"] and "opposing" in attempted["reason"]
    c.store.update("agents", c.lawyer, role="judge")
    result = c.world.runtime.executor.execute_action(10, c.lawyer, {"type": "issue_legal_decision", "matter_id": c.matter,
        "outcome": "dismissed", "findings": [{"key": "unsupported", "value": True}], "remedy": {"type": "dismissal"}})
    assert not result["ok"] and "recorded_counsel" in result["reason"]
    validate(c.world)


def test_counsel_evidence_is_immutable_and_failed_requests_roll_back(counsel_case, monkeypatch):
    c = counsel_case
    before = canonical_hashes(c.store)["authoritative_sha256"]
    insert = c.store.insert
    def fail(table, **values):
        if table == "legal_action_authorities":
            raise RuntimeError("injected mandate record failure")
        return insert(table, **values)
    monkeypatch.setattr(c.store, "insert", fail)
    with pytest.raises(RuntimeError, match="mandate record"):
        c.e.legal_representation.request(9, c.owner["id"], {"matter_id": c.matter, "side": "claimant",
            "counsel_agent_id": c.lawyer, "scopes": ["submit_filing"]})
    assert canonical_hashes(c.store)["authoritative_sha256"] == before
    monkeypatch.setattr(c.store, "insert", insert)
    invitation = request(c)
    act(c.world, 9, c.lawyer, "respond_legal_counsel", request_id=invitation, decision="accept")
    for table in ("legal_action_authorities", "legal_counsel_requests", "legal_counsel_responses"):
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            c.store.execute(f"UPDATE {table} SET id=id")
        with pytest.raises(sqlite3.IntegrityError, match="permanent"):
            c.store.execute(f"DELETE FROM {table}")
    validate(c.world)


@pytest.mark.parametrize("public", [False, True])
@pytest.mark.parametrize("estate_side", ["claimant", "respondent"])
def test_private_and_public_estate_parties_can_settle_through_actual_cash(property_world, public, estate_side):
    world, owner, heir = property_world
    e = world.economy
    other = e.store.query_one("SELECT * FROM agents WHERE alive=1 AND age>=18 AND kind='citizen' AND region_id=? "
        "AND id NOT IN (?,?) ORDER BY id LIMIT 1", (owner["region_id"], owner["id"], heir["id"]))
    assert other is not None
    if public:
        e.store.execute("DELETE FROM social_ties WHERE agent_a=? OR agent_b=?", (owner["id"], owner["id"]))
    parties = (owner["id"], other["id"]) if estate_side == "claimant" else (other["id"], owner["id"])
    matter, evidence = open_matter(world, *parties)
    e.lifecycle.settle_death(9, owner["id"])
    estate = e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (owner["id"],))
    representative = e.estate_administration.current(estate)["administrator_agent_id"] if public else heir["id"]
    act(world, 10, representative, "submit_filing", matter_id=matter, filer_type="agent", filer_id=owner["id"],
        filing_type="evidence", evidence_event_ids=[evidence], body="The representative supplies the estate's recorded evidence.")
    remedy = json.loads(e.store.scalar("SELECT requested_remedy_json FROM legal_matters WHERE id=?", (matter,)))
    recipient = heir["id"] if estate_side == "claimant" and not public else other["id"] if estate_side == "respondent" else None
    before = e.ledger.balance(e.ledger.agent_checking_id(recipient)) if recipient is not None else None
    act(world, 10, representative, "propose_settlement", matter_id=matter, terms={"remedy": remedy})
    act(world, 10, other["id"], "accept_settlement", matter_id=matter)
    assert e.store.scalar("SELECT status FROM legal_matters WHERE id=?", (matter,)) == "settled"
    assert e.store.scalar("SELECT SUM(p.amount_cents) FROM legal_award_payments p JOIN legal_awards a ON a.id=p.award_id WHERE a.matter_id=?", (matter,)) == 10
    if recipient is not None:
        assert e.ledger.balance(e.ledger.agent_checking_id(recipient)) == before + 10
    assert e.estate_administration.current(estate) is None
    validate(world)


def payment_case(world, claimant, respondent, *, breach_tick=1):
    """Create a consented payment and unbriefed claim, optionally after breach."""
    currency = world.store.scalar("SELECT currency_code FROM accounts WHERE id=?",
        (world.economy.ledger.agent_checking_id(claimant),))
    contract = act(world, 0, claimant, "propose_contract", payload={
        "contract_type": "supplier", "title": "Recorded representation payment",
        "parties": [{"type": "agent", "id": claimant, "role": "supplier"},
                    {"type": "agent", "id": respondent, "role": "buyer"}],
        "clauses": [{"clause_key": "price", "clause_type": "payment", "terms": {
            "obligor_role": "buyer", "obligee_role": "supplier", "amount_cents": 10,
            "currency_code": currency, "due_tick": 0, "grace_ticks": 0}}]})["contract_id"]
    for person in (claimant, respondent):
        act(world, 0, person, "accept_contract", contract_id=contract, party_type="agent", party_id=person)
    if breach_tick is not None:
        world.economy.legal.run_nightly(breach_tick)
    evidence = world.store.scalar("SELECT id FROM events WHERE kind='obligation_breached' AND subject_id=?", (contract,))
    assert (evidence is not None) == (breach_tick is not None)
    matter = act(world, breach_tick or 0, claimant, "file_claim", contract_id=contract,
        claimant={"type": "agent", "id": claimant}, respondent={"type": "agent", "id": respondent},
        requested_remedy={"type": "damages", "amount_cents": 10, "currency_code": currency})["matter_id"]
    return matter, evidence


@pytest.mark.parametrize("purpose", ["lawyer", "decision", "founder", "gov_official", "credit_officer", "vc_partner", "central_banker"])
@pytest.mark.parametrize("governed", [False, True])
def test_real_counsel_context_can_accept_and_file_through_each_action_policy(property_world, purpose, governed):
    world, claimant, respondent = property_world
    matter, evidence = payment_case(world, claimant["id"], respondent["id"])
    lawyer = world.store.scalar("SELECT id FROM agents WHERE alive=1 AND age>=18 AND role='lawyer' ORDER BY id LIMIT 1")
    invitation = act(world, 1, claimant["id"], "request_legal_counsel", matter_id=matter,
        side="claimant", counsel_agent_id=lawyer, scopes=["submit_filing"])["request_id"]
    for tick, expected in ((1, "respond_legal_counsel"), (2, "submit_filing")):
        context = world.runtime.ctx.build(world.store.query_one("SELECT * FROM agents WHERE id=?", (lawyer,)), tick)
        # One factual private context exercises the actual registry entry and
        # periphery dispatch used by all action-bearing role purposes.
        context["purpose"] = purpose
        system, prompt = world.runtime.ctx.render_prompt(context)
        if tick == 1:
            assert "respond_legal_counsel" in system and '"request_id":' + str(invitation) in prompt
        else:
            assigned = context["assigned_legal_matters"]
            assert assigned[0]["represented_party"] == {"type": "agent", "id": claimant["id"]}
            assert [event["event_id"] for event in assigned[0]["evidence_events"]] == [evidence]
        envelope = POLICIES[purpose](context) if governed else scripted_decision(purpose, context)
        assert envelope["actions"][0]["type"] == expected, envelope
        result = world.runtime.executor.execute_action(tick, lawyer, envelope["actions"][0])
        assert result["ok"], result
    assert world.store.scalar("SELECT filer_id FROM legal_filings WHERE matter_id=?", (matter,)) == claimant["id"]
    validate(world)


def test_estate_representative_receives_supported_work_in_actual_founder_context(property_world):
    world, owner, heir = property_world
    other = world.store.query_one("SELECT * FROM agents WHERE alive=1 AND age>=18 AND kind='citizen' "
        "AND region_id=? AND id NOT IN (?,?) ORDER BY id LIMIT 1", (owner["region_id"], owner["id"], heir["id"]))
    matter, evidence = payment_case(world, owner["id"], other["id"])
    world.economy.firms.found_firm(1, owner["id"], "Inherited legal work business", "manufacturing", opening_capital_cents=100, shares=10)
    world.economy.lifecycle.settle_death(2, owner["id"])
    context = world.runtime.ctx.build(world.store.query_one("SELECT * FROM agents WHERE id=?", (heir["id"],)), 3)
    assert context["purpose"] == "founder"
    assert context["represented_legal_matters"][0]["matter_id"] == matter
    _, prompt = world.runtime.ctx.render_prompt(context)
    assert "[REPRESENTED ESTATE MATTERS" in prompt
    envelope = POLICIES[context["purpose"]](context)
    action = envelope["actions"][0]
    assert action["type"] == "submit_filing" and action["filer_id"] == owner["id"]
    assert action["evidence_event_ids"] == [evidence]
    assert world.runtime.executor.execute_action(3, heir["id"], action)["ok"]
    validate(world)


def test_respondent_counsel_can_address_evidence_already_filed_by_the_claimant(property_world):
    world, claimant, respondent = property_world
    matter, evidence = payment_case(world, claimant["id"], respondent["id"])
    act(world, 1, claimant["id"], "submit_filing", matter_id=matter, filer_type="agent", filer_id=claimant["id"],
        filing_type="evidence", evidence_event_ids=[evidence], body="The payment is overdue.")
    lawyer = world.store.scalar("SELECT id FROM agents WHERE alive=1 AND age>=18 AND role='lawyer' ORDER BY id LIMIT 1")
    invitation = act(world, 1, respondent["id"], "request_legal_counsel", matter_id=matter,
        side="respondent", counsel_agent_id=lawyer, scopes=["submit_filing"])["request_id"]
    act(world, 1, lawyer, "respond_legal_counsel", request_id=invitation, decision="accept")
    context = world.runtime.ctx.build(world.store.query_one("SELECT * FROM agents WHERE id=?", (lawyer,)), 2)
    action = POLICIES[context["purpose"]](context)["actions"][0]
    assert action["type"] == "submit_filing" and action["filer_id"] == respondent["id"]
    assert action["evidence_event_ids"] == [evidence]
    assert world.runtime.executor.execute_action(2, lawyer, action)["ok"]
    assert world.store.scalar("SELECT COUNT(*) FROM legal_filings WHERE matter_id=?", (matter,)) == 2
    validate(world)


def test_pending_counsel_work_preserves_required_civic_attendance(counsel_case):
    c = counsel_case
    request(c)
    context = c.world.runtime.ctx.build(c.store.query_one("SELECT * FROM agents WHERE id=?", (c.lawyer,)), 9)
    appointment = {"type": "attend_appointment", "appointment_id": 77}
    context["civic_required_action"] = appointment
    # The actual pending request cannot displace a caller-supplied civic duty.
    for purpose in ("lawyer", "founder", "decision", "gov_official", "credit_officer", "vc_partner", "central_banker"):
        assert POLICIES[purpose](context)["actions"] == [appointment]


def test_default_counsel_consent_brief_offer_and_paid_settlement_survive_restart_and_replay(tmp_path, caplog):
    config = _config(semantics=20)
    config.setdefault("households", {})["scheduled_births"] = []
    config.setdefault("lifecycle", {}).update(population_mode="drift", birth_annual_prob=0,
        illness_onset_annual_young=0, illness_onset_annual_old=0)
    config.setdefault("legal", {})["response_ticks"] = 20
    config["checkpoint_every"] = 0
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    ids = {}

    def open_seeded(path, settings, *, replay=False):
        world = _world(path, settings, replay=replay)
        store = world.store
        if store.tick == 0:
            owner = _owner(world)
            other = store.query_one("SELECT * FROM agents WHERE alive=1 AND age>=18 AND retired=0 AND kind='citizen' "
                "AND region_id=? AND id<>? ORDER BY id LIMIT 1", (owner["region_id"], owner["id"]))
            lawyer = store.scalar("SELECT id FROM agents WHERE alive=1 AND age>=18 AND role='lawyer' ORDER BY id LIMIT 1")
            matter, _ = payment_case(world, owner["id"], other["id"], breach_tick=None)
            invitation = act(world, 0, owner["id"], "request_legal_counsel", matter_id=matter,
                side="claimant", counsel_agent_id=lawyer, scopes=["submit_filing", "propose_settlement"])["request_id"]
            ids.update(owner=owner["id"], other=other["id"], lawyer=lawyer, matter=matter, invitation=invitation)
            for person in (ids["owner"], ids["other"], lawyer):
                store.update("agents", person, population_tier="core", pinned_core=1,
                    cadence_json='{"act":1,"portfolio":9999,"career":9999,"news":9999}')
        for purpose, original in list(world.gateway.scripted.policies.items()):
            def scenario(context, original=original):
                if replay:
                    raise AssertionError("recorded replay must not consult the scripted policy")
                actor = context.get("agent", {}).get("id")
                if actor not in (ids["owner"], ids["other"]):
                    return original(context)
                actions = [{"type": "do_nothing"}]
                if actor == ids["other"] and store.scalar("SELECT status FROM legal_matters WHERE id=?", (ids["matter"],)) == "settlement_offered":
                    actions = [{"type": "accept_settlement", "matter_id": ids["matter"]}]
                return {"reasoning": "Declared patient client and counterparty acceptance for the counsel workflow fixture.", "actions": actions}
            world.gateway.scripted.register(purpose, scenario)
        return world

    path = tmp_path / "source-counsel.db"
    committed = None
    for day in range(1, 5):
        source = open_seeded(path, config)
        try:
            if committed is not None:
                assert canonical_hashes(source.store)["authoritative_sha256"] == committed
            asyncio.run(source.step())
            if day == 1:
                assert source.store.scalar("SELECT decision FROM legal_counsel_responses WHERE request_id=?", (ids["invitation"],)) == "accepted"
            if day >= 2:
                assert source.store.scalar("SELECT COUNT(*) FROM legal_filings WHERE matter_id=? AND filer_id=?", (ids["matter"], ids["owner"])) == 1
                assert source.store.scalar("SELECT COUNT(*) FROM legal_action_authorities WHERE matter_id=? AND actor_id=? AND action='submit_filing' AND capacity='counsel'",
                    (ids["matter"], ids["lawyer"])) == 1
            if day == 4:
                assert source.store.scalar("SELECT status FROM legal_matters WHERE id=?", (ids["matter"],)) == "settled"
                assert source.store.scalar("SELECT reason FROM legal_counsel_ends WHERE request_id=?", (ids["invitation"],)) == "matter_closed"
                assert source.store.scalar("SELECT SUM(p.amount_cents) FROM legal_award_payments p JOIN legal_awards a ON a.id=p.award_id WHERE a.matter_id=?", (ids["matter"],)) == 10
                manifest = validate_bundle(export_bundle(source.store, tmp_path / "export"))
                for table in ("legal_action_authorities", "legal_counsel_requests", "legal_counsel_responses", "legal_counsel_ends"):
                    assert manifest["tables"][table]["row_count"] > 0
            validate(source)
            committed = canonical_hashes(source.store)["authoritative_sha256"]
        finally:
            source.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    settings = copy.deepcopy(config)
    settings["replay_source_path"] = str(path)
    replay = open_seeded(tmp_path / "replay-counsel.db", settings, replay=True)
    try:
        for _ in range(4):
            asyncio.run(replay.step())
        result = verify_replay(path, replay.store.path)
        assert result["exact"], result["differences"]
        validate(replay)
        assert not any("action.execution.failed" in record.message for record in caplog.records)
    finally:
        replay.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before

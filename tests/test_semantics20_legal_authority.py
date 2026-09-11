"""Estate representatives cannot adjudicate their own administration disputes."""
import asyncio
import copy
import hashlib
import json
import sqlite3
from types import SimpleNamespace

import pytest

from agents.policies import scripted_decision
from engine.estates import EstateError
from engine.legal import DECISION_ROLES
from engine.lifecycle import Lifecycle
from research.export_bundle import export_bundle, validate_bundle
from research.hashing import canonical_hashes
from world.replay_verify import verify_replay

from .test_semantics20_estate_administration import unrepresented_assets
from .test_semantics20_project_rights import property_world, validate
from .test_semantics20_estate_property import personal_loan, drain_cash
from .test_semantics13_construction import _config, _owner
from .test_semantics17_household_decisions import _world


def open_matter(world, claimant, respondent, tick=8, *, requested_remedy=None):
    e = world.economy
    currency = e.store.scalar("SELECT currency_code FROM accounts WHERE id=?",
                              (e.ledger.agent_checking_id(claimant),))
    evidence = e.store.log_event(tick, "fixture_disputed_loss", {"claimant_id": claimant,
        "respondent_id": respondent, "amount_cents": 10}, phase="EXECUTION")
    filed = world.runtime.executor.execute_action(tick, claimant, {"type": "file_claim",
        "matter_type": "labor", "venue": "Northstar test tribunal", "claim_type": "disputed_loss",
        "claimant": {"type": "agent", "id": claimant}, "respondent": {"type": "agent", "id": respondent},
        "requested_remedy": requested_remedy if requested_remedy is not None else {
            "type": "damages", "amount_cents": 10, "currency_code": currency, "independent_damages": True}})
    assert filed["ok"], filed
    admitted = world.runtime.executor.execute_action(tick, claimant, {"type": "submit_filing",
        "matter_id": filed["matter_id"], "filer_type": "agent", "filer_id": claimant,
        "filing_type": "evidence", "evidence_event_ids": [evidence], "body": "Declared disputed loss."})
    assert admitted["ok"], admitted
    return filed["matter_id"], evidence


def dismissal(matter_id):
    return {"type": "issue_legal_decision", "matter_id": matter_id, "outcome": "dismissed",
            "findings": [{"key": "sufficient_evidence", "value": False}], "remedy": {"type": "dismissal"}}


@pytest.mark.parametrize("estate_side", ["claimant", "respondent"])
@pytest.mark.parametrize("decision_tick", [9, 10])
def test_a_public_trustee_cannot_decide_its_estates_dispute(unrepresented_assets, estate_side, decision_tick):
    world, owner, other, trustee, _, _, _ = unrepresented_assets
    parties = (owner["id"], other["id"]) if estate_side == "claimant" else (other["id"], owner["id"])
    matter_id, _ = open_matter(world, *parties)
    e = world.economy
    e.lifecycle.settle_death(9, owner["id"])
    assert e.store.scalar("SELECT administrator_agent_id FROM estate_administrations") == trustee["id"]
    before = [(row["id"], row["balance_cents"]) for row in e.store.query("SELECT id,balance_cents FROM accounts ORDER BY id")]
    result = world.runtime.executor.execute_action(decision_tick, trustee["id"], dismissal(matter_id))
    assert not result["ok"], "the estate trustee must not adjudicate its own estate's dispute"
    assert "conflict" in result["reason"]
    assert e.store.scalar("SELECT COUNT(*) FROM legal_decisions WHERE matter_id=?", (matter_id,)) == 0
    assert e.store.scalar("SELECT status FROM legal_matters WHERE id=?", (matter_id,)) == "hearing"
    assert [(row["id"], row["balance_cents"]) for row in e.store.query("SELECT id,balance_cents FROM accounts ORDER BY id")] == before
    validate(world)


@pytest.fixture
def authority_case(unrepresented_assets):
    world, owner, claimant, trustee, loan, firm, project = unrepresented_assets
    e = world.economy
    e.legal.default_response_ticks = 2
    matter, evidence = open_matter(world, claimant["id"], owner["id"])
    e.lifecycle.settle_death(9, owner["id"])
    regulator = e.store.query_one("SELECT * FROM agents WHERE role='labor_regulator' AND alive=1 AND age>=18 ORDER BY id LIMIT 1")
    assert regulator is not None
    return SimpleNamespace(world=world, e=e, owner=owner, claimant=claimant, trustee=trustee, regulator=regulator,
                           matter=matter, evidence=evidence, loan=loan, firm=firm, project=project)


def fund_reserved_case(c, tick=10):
    c.e.ledger.transfer(tick, c.e.ledger.agent_checking_id(c.claimant["id"]),
                        c.e.ledger.agent_checking_id(c.owner["id"]), 110, kind="fixture_estate_receipt")


@pytest.mark.parametrize("transition", ["role_change", "assets_disposed"])
def test_public_trustee_recusal_survives_role_loss_or_asset_disposition(authority_case, transition):
    c = authority_case
    if transition == "role_change":
        c.e.store.update("agents", c.trustee["id"], role="regulator")
        c.e.business_control.refresh_custody(10)
        c.e.project_rights.refresh(10)
        assert c.e.store.scalar("SELECT COUNT(*) FROM estate_administration_ends WHERE reason='authority_lost'") > 0
    else:
        fund_reserved_case(c)
        estate = c.e.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (c.owner["id"],))
        assert not c.e.estate_securities.lots(estate) and not c.e.estate_property.pending(estate)
        assert c.e.estate_administration.current(estate)["administrator_agent_id"] == c.trustee["id"]
        assert c.e.store.scalar("SELECT COUNT(*) FROM estate_administration_ends WHERE reason='assets_disposed'") == 0
    result = c.world.runtime.executor.execute_action(10, c.trustee["id"], dismissal(c.matter))
    assert not result["ok"] and "public_estate_trustee" in result["reason"]
    validate(c.world)


def test_a_later_same_day_appointment_does_not_rewrite_an_earlier_decision(unrepresented_assets):
    world, owner, claimant, trustee, _, _, _ = unrepresented_assets
    matter, _ = open_matter(world, claimant["id"], owner["id"])
    result = world.runtime.executor.execute_action(9, trustee["id"], dismissal(matter))
    assert result["ok"], result
    proof = world.store.query_one("SELECT * FROM legal_decision_authorities")
    assert proof["administration_frontier"] == proof["estate_frontier"] == 0
    world.economy.lifecycle.settle_death(9, owner["id"])
    assert world.store.scalar("SELECT COUNT(*) FROM estate_administrations") == 1
    validate(world)


def test_an_existing_unconflicted_official_completes_the_actual_reserved_claim(authority_case):
    c = authority_case
    fund_reserved_case(c)
    before = c.e.ledger.balance(c.e.ledger.agent_checking_id(c.claimant["id"]))
    assert not c.world.runtime.executor.execute_action(10, c.trustee["id"], dismissal(c.matter))["ok"]
    work = c.world.runtime.ctx._institutional_work(c.regulator, 10)
    action = scripted_decision(c.regulator["role"], {"purpose": c.regulator["role"], "tick": 10,
                                                    "institutional_work": work})["actions"][0]
    assert action["type"] == "issue_legal_decision" and action["matter_id"] == c.matter
    result = c.world.runtime.executor.execute_action(10, c.regulator["id"], action)
    assert result["ok"], result
    assert c.e.ledger.balance(c.e.ledger.agent_checking_id(c.claimant["id"])) == before + 10
    proof = c.e.store.query_one("SELECT * FROM legal_decision_authorities WHERE decision_id=?", (result["decision_id"],))
    decision = c.e.store.query_one("SELECT * FROM legal_decisions WHERE id=?", (result["decision_id"],))
    assert proof["actor_id"] == c.regulator["id"] and proof["event_id"] < decision["enforcement_event_id"]
    c.e.store.update("agents", c.regulator["id"], role=None)
    validate(c.world)


@pytest.mark.parametrize("role", ["judge", "labor_regulator"])
@pytest.mark.parametrize("role_purposes", [False, True])
def test_actual_decision_context_supplies_eligible_legal_work(authority_case, role, role_purposes):
    c = authority_case
    c.e.store.update("agents", c.regulator["id"], role=role)
    c.world.runtime.ctx.institutional_role_purposes = role_purposes
    actor = c.e.store.query_one("SELECT * FROM agents WHERE id=?", (c.regulator["id"],))
    context = c.world.runtime.ctx.build(actor, 10)
    assert context["institutional_work"]["due_legal_matters"][0]["matter_id"] == c.matter
    action = scripted_decision(context["purpose"], context)["actions"][0]
    assert action["type"] == "issue_legal_decision" and action["matter_id"] == c.matter
    result = c.world.runtime.executor.execute_action(10, actor["id"], action)
    assert result["ok"], result
    validate(c.world)


def test_recusal_skips_the_first_case_without_blocking_another_due_matter(authority_case):
    c = authority_case
    people = c.e.store.query("SELECT id FROM agents WHERE alive=1 AND age>=18 AND kind='citizen' AND region_id=? "
        "AND id NOT IN (?,?,?) ORDER BY id LIMIT 2", (c.owner["region_id"], c.owner["id"], c.claimant["id"], c.trustee["id"]))
    assert len(people) == 2
    other, _ = open_matter(c.world, people[0]["id"], people[1]["id"], tick=10)
    before = canonical_hashes(c.e.store)["authoritative_sha256"]
    context = c.world.runtime.ctx.build(c.trustee, 12)
    assert context["purpose"] == "founder"
    work = context["institutional_work"]
    assert [row["matter_id"] for row in work["recused_legal_matters"]] == [c.matter]
    action = scripted_decision(context["purpose"], context)["actions"][0]
    assert action["type"] == "issue_legal_decision" and action["matter_id"] == other
    assert canonical_hashes(c.e.store)["authoritative_sha256"] == before
    assert c.world.runtime.executor.execute_action(12, c.trustee["id"], action)["ok"]
    assert c.e.store.scalar("SELECT status FROM legal_matters WHERE id=?", (c.matter,)) == "hearing"
    validate(c.world)


def test_contested_cases_are_not_labeled_unanswered_in_the_default_queue(authority_case):
    c = authority_case
    # This existing claimant becomes a respondent in a separate, live dispute.
    people = c.e.store.query("SELECT id FROM agents WHERE alive=1 AND age>=18 AND kind='citizen' AND region_id=? "
        "AND id NOT IN (?,?,?) ORDER BY id LIMIT 2", (c.owner["region_id"], c.owner["id"], c.claimant["id"], c.trustee["id"]))
    other, _ = open_matter(c.world, people[0]["id"], people[1]["id"], tick=10)
    reply = c.world.runtime.executor.execute_action(11, people[1]["id"], {"type": "submit_filing", "matter_id": other,
        "filer_type": "agent", "filer_id": people[1]["id"], "filing_type": "evidence", "evidence_event_ids": [c.evidence],
        "body": "The respondent contests the allegation."})
    assert reply["ok"], reply
    work = c.world.runtime.ctx._institutional_work(c.trustee, 12)
    assert not any(action["type"] == "issue_legal_decision" for action in work["eligible_actions"])
    assert c.e.store.scalar("SELECT status FROM legal_matters WHERE id=?", (other,)) == "hearing"


@pytest.mark.parametrize("invalid", ["unsupported", "above_limit", "malformed_amount"])
def test_invalid_requested_relief_does_not_starve_a_later_eligible_case(unrepresented_assets, invalid):
    world, owner, claimant, _, _, _, _ = unrepresented_assets
    e = world.economy
    e.legal.default_response_ticks = 2
    actor = e.store.query_one("SELECT * FROM agents WHERE alive=1 AND age>=18 AND role='labor_regulator' ORDER BY id LIMIT 1")
    assert actor is not None
    remedy = {"type": "unavailable_relief"} if invalid == "unsupported" else {
        "type": "damages", "independent_damages": True,
        "amount_cents": e.legal.max_damages_cents + 1 if invalid == "above_limit" else "invalid"}
    blocked, _ = open_matter(world, claimant["id"], owner["id"], requested_remedy=remedy)
    eligible, _ = open_matter(world, claimant["id"], owner["id"])
    e.lifecycle.settle_death(9, owner["id"])
    before = canonical_hashes(e.store)["authoritative_sha256"]
    context = world.runtime.ctx.build(actor, 10)
    action = scripted_decision(context["purpose"], context)["actions"][0]
    assert action["type"] == "issue_legal_decision" and action["matter_id"] == eligible
    assert [item["matter_id"] for item in context["institutional_work"]["blocked_legal_matters"]] == [blocked]
    assert canonical_hashes(e.store)["authoritative_sha256"] == before
    result = world.runtime.executor.execute_action(10, actor["id"], action)
    assert result["ok"], result
    assert e.store.scalar("SELECT status FROM legal_matters WHERE id=?", (blocked,)) == "hearing"
    assert e.store.scalar("SELECT COUNT(*) FROM legal_decisions WHERE matter_id=?", (blocked,)) == 0
    validate(world)


@pytest.mark.parametrize("relationship", ["personal_party", "counsel", "minor", "estate_business"])
def test_adjudication_rejects_other_direct_authority_conflicts(authority_case, relationship):
    c = authority_case
    actor = c.regulator["id"]
    if relationship == "personal_party":
        actor = c.claimant["id"]
        c.e.store.update("agents", actor, role="judge")
    elif relationship == "counsel":
        c.e.store.update("legal_matters", c.matter, counsel_agent_id=actor)
    elif relationship == "minor":
        c.e.store.update("agents", actor, age=17)
    else:
        actor = c.trustee["id"]
        filed = c.world.runtime.executor.execute_action(10, c.claimant["id"], {"type": "file_claim",
            "claimant": {"type": "agent", "id": c.claimant["id"]}, "respondent": {"type": "firm", "id": c.firm},
            "claim_type": "disputed_company_loss", "requested_remedy": {"type": "damages", "amount_cents": 10}})
        assert filed["ok"], filed
        c.matter = filed["matter_id"]
    result = c.world.runtime.executor.execute_action(10, actor, dismissal(c.matter))
    assert not result["ok"]
    if relationship == "minor":
        direct = c.e.legal.issue_decision(10, actor, dismissal(c.matter))
        assert not direct["ok"] and "living adult" in direct["reason"]
    else:
        assert "conflict" in result["reason"]
    assert c.e.store.scalar("SELECT COUNT(*) FROM legal_decisions") == 0


def test_failure_after_enforcement_rolls_back_authority_and_money(authority_case, monkeypatch):
    c = authority_case
    fund_reserved_case(c)
    before = canonical_hashes(c.e.store)["authoritative_sha256"]
    original = c.e.store.insert
    def insert(table, **kwargs):
        if table == "legal_decision_authorities":
            raise RuntimeError("injected authority recording failure")
        return original(table, **kwargs)
    monkeypatch.setattr(c.e.store, "insert", insert)
    with pytest.raises(RuntimeError, match="authority recording"):
        c.e.legal.issue_decision(10, c.regulator["id"], {"matter_id": c.matter, "outcome": "claimant",
            "findings": [{"key": "supported_loss", "value": True}], "evidence_event_ids": [c.evidence],
            "remedy": {"type": "damages", "amount_cents": 10, "independent_damages": True}})
    assert canonical_hashes(c.e.store)["authoritative_sha256"] == before
    validate(c.world)


@pytest.mark.parametrize("frontier", ["administration_frontier", "estate_frontier", "stewardship_frontier"])
def test_accepted_authority_is_immutable_and_cannot_hide_a_prior_appointment(authority_case, frontier):
    c = authority_case
    result = c.world.runtime.executor.execute_action(10, c.regulator["id"], dismissal(c.matter))
    assert result["ok"], result
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        c.e.store.execute("UPDATE legal_decision_authorities SET actor_age=actor_age+1")
    with pytest.raises(sqlite3.IntegrityError, match="permanent"):
        c.e.store.execute("DELETE FROM legal_decision_authorities")
    proof = c.e.store.query_one("SELECT * FROM legal_decision_authorities")
    c.e.store.execute("DROP TRIGGER legal_decision_authorities_immutable")
    assert proof[frontier] > 0
    c.e.store.execute(f"UPDATE legal_decision_authorities SET {frontier}=0")
    event = c.e.store.query_one("SELECT * FROM events WHERE id=?", (proof["event_id"],))
    payload = json.loads(event["payload_json"])
    payload[frontier] = 0
    c.e.store.update("events", proof["event_id"], payload_json=json.dumps(payload, sort_keys=True))
    with pytest.raises(EstateError, match="frontier"):
        c.e.legal_authority.check_invariants()


def test_a_private_estate_beneficiary_cannot_adjudicate_the_estates_dispute(unrepresented_assets):
    world, owner, heir, claimant, _, _, _ = unrepresented_assets
    e = world.economy
    e.store.insert("social_ties", agent_a=owner["id"], agent_b=heir["id"], weight=1)
    e.store.update("agents", heir["id"], role="judge")
    matter, _ = open_matter(world, claimant["id"], owner["id"])
    e.lifecycle.settle_death(9, owner["id"])
    assert e.store.scalar("SELECT COUNT(*) FROM estate_administrations") == 0
    result = world.runtime.executor.execute_action(10, heir["id"], dismissal(matter))
    assert not result["ok"] and "estate_representative" in result["reason"]
    validate(world)


def test_actual_recusal_default_replacement_payment_and_history_replay(tmp_path, monkeypatch, caplog):
    config = _config(semantics=20)
    config.setdefault("households", {})["scheduled_births"] = []
    config.setdefault("lifecycle", {}).update(population_mode="drift", birth_annual_prob=0,
        illness_onset_annual_young=0, illness_onset_annual_old=0)
    config.setdefault("legal", {})["response_ticks"] = 2
    config.setdefault("llm", {})["institutional_role_purposes"] = True
    config["checkpoint_every"] = 0
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    identities = {}
    original_draw = Lifecycle._draw

    def draw(self, tick, actor, mechanism):
        if tick == 1 and actor == identities["owner"] and mechanism == "mortality":
            return 0.0
        return original_draw(self, tick, actor, mechanism)
    monkeypatch.setattr(Lifecycle, "_draw", draw)

    def open_seeded(path, settings, *, replay=False):
        world = _world(path, settings, replay=replay)
        e, store = world.economy, world.store
        if store.tick == 0:
            owner = _owner(world)
            trustee = store.query_one("SELECT * FROM agents WHERE alive=1 AND age>=18 AND role='gov_official' "
                                      "AND region_id=? ORDER BY id LIMIT 1", (owner["region_id"],))
            regulator = store.query_one("SELECT * FROM agents WHERE alive=1 AND age>=18 AND role='labor_regulator' ORDER BY id LIMIT 1")
            assert trustee is not None and regulator is not None
            currency = store.scalar("SELECT currency_code FROM accounts WHERE id=?", (owner["checking_account_id"],))
            payer = store.query_one("SELECT a.* FROM agents a JOIN accounts c ON c.id=a.checking_account_id "
                "WHERE a.alive=1 AND a.age>=18 AND a.retired=0 AND a.kind='citizen' AND a.id<>? "
                "AND c.currency_code=? AND c.balance_cents>=2100000 ORDER BY c.balance_cents DESC,a.id LIMIT 1",
                (owner["id"], currency))
            assert payer is not None
            firm = e.firms.found_firm(0, owner["id"], "Recusal case private issuer", "manufacturing",
                                      opening_capital_cents=10000, shares=10)
            proposal = e.legal.propose_contract(0, owner["id"], {"contract_type": "supplier", "title": "Declared later estate receivable",
                "parties": [{"type": "agent", "id": owner["id"], "role": "supplier"}, {"type": "agent", "id": payer["id"], "role": "buyer"}],
                "clauses": [{"clause_key": "price", "clause_type": "payment", "terms": {"obligor_role": "buyer", "obligee_role": "supplier",
                    "amount_cents": 2000000, "due_tick": 2, "currency_code": currency}}]})
            assert proposal["ok"], proposal
            contract = proposal["contract_id"]
            assert e.legal.accept_contract(0, owner["id"], contract, "agent", owner["id"])["ok"]
            assert e.legal.accept_contract(0, payer["id"], contract, "agent", payer["id"])["ok"]
            obligation = store.scalar("SELECT id FROM obligations WHERE contract_id=?", (contract,))
            matter, _ = open_matter(world, payer["id"], owner["id"], tick=0)
            _, loan = personal_loan(e, owner["id"], 1000000)
            drain_cash(e, owner["id"], 0)
            store.execute("DELETE FROM social_ties WHERE agent_a=? OR agent_b=?", (owner["id"], owner["id"]))
            for person in (owner, trustee, regulator, payer):
                store.update("agents", person["id"], population_tier="core", pinned_core=1,
                             cadence_json='{"act":1,"portfolio":9999,"career":9999,"news":9999}')
            identities.update(owner=owner["id"], trustee=trustee["id"], regulator=regulator["id"], payer=payer["id"],
                firm=firm, matter=matter, obligation=obligation, loan=loan)
            e.city.initialize(0)
        # The fixture declares availability: the trustee attempts a decision on
        # day two, the counterparty pays, and the existing regulator returns on
        # day three. Its actual decision is supplied by the default policy.
        adapter = world.gateway.scripted
        for purpose, original in list(adapter.policies.items()):
            def scenario(context, original=original):
                if replay:
                    raise AssertionError("replay must use recorded responses")
                actor = context.get("agent", {}).get("id")
                role = store.scalar("SELECT role FROM agents WHERE id=?", (actor,))
                if actor == identities["regulator"] and context.get("tick") >= 3:
                    return original(context)
                if actor not in (identities["owner"], identities["payer"], identities["trustee"]) and role not in DECISION_ROLES:
                    return original(context)
                actions = [{"type": "do_nothing"}]
                if context.get("tick") == 2 and context.get("purpose") in {"decision", "founder", *DECISION_ROLES}:
                    if actor == identities["trustee"]:
                        actions = [dismissal(identities["matter"])]
                    elif actor == identities["payer"]:
                        actions = [{"type": "perform_obligation", "obligation_id": identities["obligation"]}]
                return {"reasoning": "Declared availability and counterparty behavior for the recusal acceptance case.", "actions": actions}
            adapter.register(purpose, scenario)
        return world

    path = tmp_path / "source-recusal.db"
    committed = None
    nightly_phases = {}
    for day in range(1, 4):
        source = open_seeded(path, config)
        try:
            if committed is not None:
                assert canonical_hashes(source.store)["authoritative_sha256"] == committed
            asyncio.run(source.step())
            if day == 1:
                assert source.store.scalar("SELECT COUNT(*) FROM estate_administrations WHERE administrator_agent_id=?",
                                           (identities["trustee"],)) == 1
                nightly_phases = {row["id"]: row["phase"] for row in source.store.query(
                    "SELECT id,phase FROM events WHERE phase='NIGHT_CLOSE'")}
                assert nightly_phases
            elif day == 2:
                assert source.store.scalar("SELECT COUNT(*) FROM events WHERE kind='legal_decision_recused' AND subject_id=?",
                                           (identities["matter"],)) >= 1
                assert source.store.scalar("SELECT COUNT(*) FROM legal_decisions WHERE matter_id=?", (identities["matter"],)) == 0
                assert source.store.scalar("SELECT status FROM loans WHERE id=?", (identities["loan"],)) == "paid"
                # Paying the loan disposes of the asset work; the unresolved
                # matter still needs its appointed representative on day three.
                assert source.store.scalar("SELECT COUNT(*) FROM events WHERE tick=2 AND kind='estate_administration_ended'") == 0
                assert {row["id"]: row["phase"] for row in source.store.query(
                    "SELECT id,phase FROM events WHERE id<=?", (max(nightly_phases),))
                    if row["id"] in nightly_phases} == nightly_phases
            else:
                assert source.store.scalar("SELECT decision_maker_id FROM legal_decisions WHERE matter_id=?",
                                           (identities["matter"],)) == identities["regulator"]
                assert source.store.scalar("SELECT SUM(p.amount_cents) FROM legal_award_payments p JOIN legal_awards a ON a.id=p.award_id "
                                           "WHERE a.matter_id=?", (identities["matter"],)) == 10
                ending = source.store.query_one("SELECT id,phase FROM events WHERE tick=3 AND kind='estate_administration_ended'")
                assert ending is not None and ending["phase"] == "EXECUTION"
                trigger = source.store.query_one("SELECT * FROM causal_links WHERE source_kind='action_proposal' "
                    "AND target_kind='event' AND target_id=? AND relation='triggered'", (ending["id"],))
                assert trigger is not None and json.loads(trigger["provenance_json"])["action_type"] == "issue_legal_decision"
                assert trigger["source_order_key"] < trigger["target_order_key"]
                manifest = validate_bundle(export_bundle(source.store, tmp_path / "export"))
                assert manifest["tables"]["legal_decision_authorities"]["row_count"] > 0
            validate(source)
            committed = canonical_hashes(source.store)["authoritative_sha256"]
        finally:
            source.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    settings = copy.deepcopy(config)
    settings["replay_source_path"] = str(path)
    replay = open_seeded(tmp_path / "replay-recusal.db", settings, replay=True)
    try:
        for _ in range(3):
            asyncio.run(replay.step())
        result = verify_replay(path, replay.store.path)
        assert result["exact"], result["differences"]
        validate(replay)
        assert not any("action.execution.failed" in record.message for record in caplog.records)
    finally:
        replay.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before

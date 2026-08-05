import json
import random

from engine.actions import ActionExecutor
from engine.core import Economy
from engine.schema import SCHEMA_VERSION
from agents.memory import Memory
from agents.policies import citizen_decision, lawyer_decision
from agents.prompts import ContextBuilder

from .conftest import make_agent, make_bank


def _legal_economy(store):
    economy = Economy(
        store,
        {"legal": {"enabled": True, "response_ticks": 5},
         "central_bank": {"max_step_bps": 50}},
        random.Random(11), random.Random(12),
    )
    economy.ensure_system_accounts()
    bank_id = make_bank(economy)
    claimant, claimant_account = make_agent(economy, bank_id, name="Claimant", cash=100_000)
    respondent, respondent_account = make_agent(economy, bank_id, name="Respondent", cash=100_000)
    judge, _ = make_agent(economy, bank_id, name="Judge", cash=0, kind="staff",
                          occupation="judge", role="judge")
    return economy, claimant, claimant_account, respondent, respondent_account, judge


def _payment_contract(executor, claimant, respondent, *, due_tick=2, amount=25_000):
    result = executor.execute_action(0, claimant, {
        "type": "propose_contract",
        "payload": {
            "contract_type": "supplier",
            "title": "Deterministic supply agreement",
            "parties": [
                {"type": "agent", "id": claimant, "role": "supplier"},
                {"type": "agent", "id": respondent, "role": "buyer"},
            ],
            "clauses": [{
                "clause_key": "price",
                "clause_type": "payment",
                "terms": {"obligor_role": "buyer", "obligee_role": "supplier",
                          "amount_cents": amount, "due_tick": due_tick},
            }],
        },
        "evidence_event_ids": [],
        "rationale_summary": "A bounded commercial proposal.",
    })
    assert result["ok"]
    contract_id = result["contract_id"]
    assert executor.execute_action(0, claimant, {
        "type": "accept_contract", "contract_id": contract_id,
        "party_type": "agent", "party_id": claimant})["ok"]
    accepted = executor.execute_action(0, respondent, {
        "type": "accept_contract", "contract_id": contract_id,
        "party_type": "agent", "party_id": respondent})
    assert accepted["ok"] and accepted["status"] == "active"
    return contract_id


def test_contract_execution_compiles_and_performs_balanced_obligation(store):
    economy, claimant, claimant_account, respondent, respondent_account, _ = _legal_economy(store)
    executor = ActionExecutor(economy)
    contract_id = _payment_contract(executor, claimant, respondent)
    obligation = store.query_one("SELECT * FROM obligations WHERE contract_id=?", (contract_id,))
    before_claimant = economy.ledger.balance(claimant_account)
    before_respondent = economy.ledger.balance(respondent_account)

    performed = executor.execute_action(1, respondent, {
        "type": "perform_obligation", "obligation_id": int(obligation["id"])})

    assert performed["ok"]
    assert economy.ledger.balance(claimant_account) == before_claimant + 25_000
    assert economy.ledger.balance(respondent_account) == before_respondent - 25_000
    assert store.scalar("SELECT status FROM obligations WHERE id=?", (obligation["id"],)) == "performed"
    assert store.scalar("SELECT status FROM contracts WHERE id=?", (contract_id,)) == "performed"
    assert economy.ledger.reconcile()[0]
    proposal = store.query_one("SELECT * FROM action_proposals ORDER BY id LIMIT 1")
    assert proposal["rationale_summary"] == "A bounded commercial proposal."
    assert "prose" not in json.loads(proposal["payload_json"])


def test_due_obligation_breaches_without_automatically_filing_a_case(store):
    economy, claimant, _, respondent, _, _ = _legal_economy(store)
    executor = ActionExecutor(economy)
    contract_id = _payment_contract(executor, claimant, respondent, due_tick=0)

    economy.legal.run_nightly(1)

    assert store.scalar("SELECT status FROM contracts WHERE id=?", (contract_id,)) == "breached"
    assert store.scalar("SELECT status FROM obligations WHERE contract_id=?", (contract_id,)) == "breached"
    assert store.scalar("SELECT COUNT(*) FROM legal_matters", default=0) == 0
    assert store.query_one("SELECT 1 FROM events WHERE kind='obligation_breached'")


def test_hybrid_decision_accepts_only_admitted_evidence_and_bounded_remedy(store):
    economy, claimant, claimant_account, respondent, respondent_account, judge = _legal_economy(store)
    executor = ActionExecutor(economy)
    contract_id = _payment_contract(executor, claimant, respondent, due_tick=0, amount=10_000)
    economy.legal.run_nightly(1)
    breach_event = int(store.scalar("SELECT id FROM events WHERE kind='obligation_breached'"))
    claim = executor.execute_action(1, claimant, {
        "type": "file_claim", "contract_id": contract_id,
        "claimant": {"type": "agent", "id": claimant},
        "respondent": {"type": "agent", "id": respondent},
        "claim_type": "breach", "requested_remedy": {"type": "damages", "amount_cents": 10_000},
    })
    matter_id = claim["matter_id"]
    assert executor.execute_action(1, claimant, {
        "type": "submit_filing", "matter_id": matter_id,
        "filer_type": "agent", "filer_id": claimant, "filing_type": "evidence",
        "evidence_event_ids": [breach_event], "body": "The obligation event is the bounded record.",
    })["ok"]
    invalid = executor.execute_action(1, judge, {
        "type": "issue_legal_decision", "matter_id": matter_id,
        "outcome": "claimant", "findings": [{"key": "breach", "value": True}],
        "evidence_event_ids": [], "remedy": {"type": "damages", "amount_cents": 10_000},
    })
    assert not invalid["ok"] and invalid["repairable"]
    before_claimant = economy.ledger.balance(claimant_account)
    before_respondent = economy.ledger.balance(respondent_account)

    decision = executor.execute_action(1, judge, {
        "type": "issue_legal_decision", "matter_id": matter_id,
        "outcome": "claimant", "findings": [{"key": "breach", "value": True}],
        "evidence_event_ids": [breach_event],
        "remedy": {"type": "damages", "amount_cents": 10_000},
        "rationale_summary": "Admitted evidence proves the simulated breach.",
    })

    assert decision["ok"]
    assert economy.ledger.balance(claimant_account) == before_claimant + 10_000
    assert economy.ledger.balance(respondent_account) == before_respondent - 10_000
    assert store.scalar("SELECT validation_status FROM legal_decisions WHERE matter_id=?",
                        (matter_id,)) == "valid"
    assert economy.ledger.reconcile()[0]


def test_schema_and_ruleset_are_versioned(store):
    _legal_economy(store)
    assert SCHEMA_VERSION >= 6
    assert int(store.get_meta()["schema_version"]) == SCHEMA_VERSION
    ruleset = store.query_one("SELECT * FROM legal_rulesets")
    assert ruleset["ruleset_key"] == "northstar-us-inspired"
    assert "Not legal advice" in ruleset["disclaimer"]


def test_missed_wage_bootstraps_claimant_work_and_counsel_evidence(store):
    config = {
        "engine_semantics_version": 7,
        "legal": {"enabled": True, "response_ticks": 5},
        "central_bank": {"max_step_bps": 50},
    }
    economy = Economy(store, config, random.Random(21), random.Random(22))
    economy.ensure_system_accounts()
    bank_id = make_bank(economy)
    founder, _ = make_agent(economy, bank_id, name="Insolvent Founder", cash=500_000)
    worker, _ = make_agent(economy, bank_id, name="Unpaid Worker", cash=25_000)
    counsel, _ = make_agent(
        economy, bank_id, name="Labor Counsel", cash=25_000,
        kind="staff", occupation="lawyer", role="lawyer",
    )
    firm_id = economy.firms.found_firm(
        0, founder, "Distressed Services", "services",
        opening_capital_cents=100_000, shares=1_000,
    )
    missed_employment_id = store.insert(
        "employments", firm_id=firm_id, agent_id=worker, title="worker",
        wage_cents=250_000, start_tick=0, end_tick=30, status="ended",
        pay_interval_ticks=30, next_pay_tick=60,
    )
    store.insert(
        "employments", firm_id=firm_id, agent_id=worker, title="worker",
        wage_cents=400_000, start_tick=31, end_tick=32, status="ended",
        pay_interval_ticks=30, next_pay_tick=61,
    )
    wage_event_id = store.log_event(
        30, "wage_missed", {
            "firm_id": firm_id,
            "agent_id": worker,
            "employment_id": missed_employment_id,
            "wage_cents": 250_000,
        },
        phase="NIGHT_CLOSE", importance=1.5,
    )
    builder = ContextBuilder(economy, Memory(store, config), config)

    worker_context = builder.build(store.query_one(
        "SELECT * FROM agents WHERE id=?", (worker,)), 31)
    claim_action = worker_context["legal_work"]["eligible_actions"][0]

    assert claim_action["type"] == "file_claim"
    assert claim_action["claimant"] == {"type": "agent", "id": worker}
    assert claim_action["respondent"] == {"type": "firm", "id": firm_id}
    assert claim_action["counsel_agent_id"] == counsel
    assert claim_action["requested_remedy"] == {
        "type": "damages", "amount_cents": 250_000,
    }
    decision = citizen_decision(worker_context)
    assert decision["actions"] == [claim_action]
    filed = ActionExecutor(economy).execute_actions(
        31, worker, decision["actions"])[0]
    assert filed["ok"]

    counsel_context = builder.build(store.query_one(
        "SELECT * FROM agents WHERE id=?", (counsel,)), 32)
    matter = counsel_context["assigned_legal_matters"][0]
    assert wage_event_id in [event["event_id"] for event in matter["evidence_events"]]
    filing = lawyer_decision(counsel_context)["actions"][0]
    assert filing["type"] == "submit_filing"
    assert filing["evidence_event_ids"] == [wage_event_id]


def test_lawyer_context_preserves_explicit_evidence_when_bounded(store):
    config = {
        "engine_semantics_version": 7,
        "legal": {"enabled": True, "response_ticks": 5},
        "central_bank": {"max_step_bps": 50},
    }
    economy = Economy(store, config, random.Random(41), random.Random(42))
    economy.ensure_system_accounts()
    bank_id = make_bank(economy)
    claimant, _ = make_agent(economy, bank_id, name="Claimant", cash=25_000)
    respondent, _ = make_agent(economy, bank_id, name="Respondent", cash=25_000)
    counsel, _ = make_agent(
        economy, bank_id, name="Counsel", cash=25_000,
        kind="staff", occupation="lawyer", role="lawyer",
    )
    source_event_id = store.log_event(
        1, "wage_missed", {"agent_id": claimant, "firm_id": 1},
        phase="NIGHT_CLOSE", importance=1.5,
    )
    claim = ActionExecutor(economy).execute_action(1, claimant, {
        "type": "file_claim",
        "matter_type": "labor",
        "claimant": {"type": "agent", "id": claimant},
        "respondent": {"type": "agent", "id": respondent},
        "claim_type": "unpaid_wages",
        "counsel_agent_id": counsel,
        "requested_remedy": {"type": "damages", "amount_cents": 10_000},
        "metadata": {"evidence_event_ids": [source_event_id]},
    })
    matter_id = int(claim["matter_id"])
    related_event_ids = [
        store.log_event(
            tick, "legal_case_activity", {"sequence": tick},
            phase="EXECUTION", subject_type="legal_matter",
            subject_id=matter_id, importance=1.0,
        )
        for tick in range(2, 14)
    ]

    context = ContextBuilder(
        economy, Memory(store, config), config,
    ).build(store.query_one("SELECT * FROM agents WHERE id=?", (counsel,)), 14)
    evidence_ids = [
        event["event_id"]
        for event in context["assigned_legal_matters"][0]["evidence_events"]
    ]
    bounded_related_ids = [
        int(row["id"])
        for row in store.query(
            "SELECT id FROM events "
            "WHERE subject_type='legal_matter' AND subject_id=? ORDER BY id",
            (matter_id,),
        )
    ][:11]

    assert related_event_ids
    assert evidence_ids == [source_event_id, *bounded_related_ids]


def test_settlement_without_response_deadline_is_not_ready(store, monkeypatch):
    economy, _, _, _, _, judge = _legal_economy(store)
    original_query_one = store.query_one

    def query_one(sql, params=()):
        if sql.startswith("SELECT role FROM agents"):
            return {"role": "judge"}
        if sql.startswith("SELECT * FROM legal_matters"):
            return {
                "id": 99,
                "status": "settlement_offered",
                "response_due_tick": None,
            }
        return original_query_one(sql, params)

    monkeypatch.setattr(store, "query_one", query_one)

    result = economy.legal.issue_decision(
        10,
        judge,
        {"matter_id": 99, "outcome": "dismissed"},
    )

    assert result == {"ok": False, "reason": "matter is not ready for decision"}


def test_unanswered_settlement_reaches_labor_regulator_at_response_deadline(store):
    config = {
        "engine_semantics_version": 7,
        "legal": {"enabled": True, "response_ticks": 5},
        "central_bank": {"max_step_bps": 50},
        "llm": {"institutional_role_purposes": True},
    }
    economy = Economy(store, config, random.Random(31), random.Random(32))
    economy.ensure_system_accounts()
    bank_id = make_bank(economy)
    founder, _ = make_agent(economy, bank_id, name="Insolvent Founder", cash=500_000)
    worker, _ = make_agent(economy, bank_id, name="Unpaid Worker", cash=25_000)
    counsel, _ = make_agent(
        economy, bank_id, name="Labor Counsel", cash=25_000,
        kind="staff", occupation="lawyer", role="lawyer",
    )
    regulator, _ = make_agent(
        economy, bank_id, name="Labor Regulator", cash=0,
        kind="staff", occupation="regulator", role="labor_regulator",
    )
    firm_id = economy.firms.found_firm(
        0, founder, "Failed Employer", "services",
        opening_capital_cents=100_000, shares=1_000,
    )
    evidence_event_id = store.log_event(
        1, "wage_missed", {"firm_id": firm_id, "agent_id": worker},
        phase="NIGHT_CLOSE", importance=1.5,
    )
    executor = ActionExecutor(economy)
    claim = executor.execute_action(1, worker, {
        "type": "file_claim",
        "matter_type": "labor",
        "claimant": {"type": "agent", "id": worker},
        "respondent": {"type": "firm", "id": firm_id},
        "claim_type": "unpaid_wages",
        "counsel_agent_id": counsel,
        "requested_remedy": {"type": "damages", "amount_cents": 10_000},
        "metadata": {"evidence_event_ids": [evidence_event_id]},
    })
    matter_id = int(claim["matter_id"])
    assert executor.execute_action(2, counsel, {
        "type": "submit_filing",
        "matter_id": matter_id,
        "filer_type": "agent",
        "filer_id": counsel,
        "filing_type": "evidence",
        "evidence_event_ids": [evidence_event_id],
        "body": "The recorded wage event is admitted.",
    })["ok"]
    assert executor.execute_action(2, counsel, {
        "type": "propose_settlement",
        "matter_id": matter_id,
        "terms": {"remedy": {"type": "damages", "amount_cents": 10_000}},
    })["ok"]
    store.update("firms", firm_id, status="bankrupt")
    builder = ContextBuilder(economy, Memory(store, config), config)
    regulator_row = store.query_one("SELECT * FROM agents WHERE id=?", (regulator,))

    before_due = builder.build(regulator_row, 5)["institutional_work"]
    assert not any(
        action.get("type") == "issue_legal_decision"
        for action in before_due["eligible_actions"]
    )

    due = builder.build(regulator_row, 6)["institutional_work"]
    action = next(
        action for action in due["eligible_actions"]
        if action.get("type") == "issue_legal_decision"
    )
    assert action == {
        "type": "issue_legal_decision",
        "matter_id": matter_id,
        "outcome": "claimant",
        "findings": [{"key": "unanswered_claim", "value": True}],
        "evidence_event_ids": [evidence_event_id],
        "remedy": {"type": "damages", "amount_cents": 10_000},
    }
    result = executor.execute_action(6, regulator, action)
    assert result["ok"]
    assert store.scalar("SELECT status FROM legal_matters WHERE id=?", (matter_id,)) == "decided"


def test_due_labor_hearing_reaches_regulator_without_settlement_offer(store):
    economy, claimant, _, respondent, _, _ = _legal_economy(store)
    regulator, _ = make_agent(
        economy, int(store.scalar("SELECT id FROM banks ORDER BY id LIMIT 1")),
        name="Labor Regulator", cash=0, kind="staff",
        occupation="regulator", role="labor_regulator",
    )
    evidence_event_id = store.log_event(
        1, "wage_missed", {"agent_id": claimant, "firm_id": 1},
        phase="NIGHT_CLOSE", importance=1.5,
    )
    executor = ActionExecutor(economy)
    claim = executor.execute_action(1, claimant, {
        "type": "file_claim",
        "matter_type": "labor",
        "claimant": {"type": "agent", "id": claimant},
        "respondent": {"type": "agent", "id": respondent},
        "claim_type": "unpaid_wages",
        "requested_remedy": {"type": "damages", "amount_cents": 10_000},
    })
    matter_id = int(claim["matter_id"])
    assert executor.execute_action(2, claimant, {
        "type": "submit_filing",
        "matter_id": matter_id,
        "filer_type": "agent",
        "filer_id": claimant,
        "filing_type": "evidence",
        "evidence_event_ids": [evidence_event_id],
        "body": "The recorded wage event is admitted.",
    })["ok"]
    config = {
        "engine_semantics_version": 7,
        "legal": {"enabled": True, "response_ticks": 5},
        "central_bank": {"max_step_bps": 50},
        "llm": {"institutional_role_purposes": True},
    }
    builder = ContextBuilder(economy, Memory(store, config), config)
    regulator_row = store.query_one("SELECT * FROM agents WHERE id=?", (regulator,))

    due = builder.build(regulator_row, 6)["institutional_work"]
    action = next(
        action for action in due["eligible_actions"]
        if action.get("type") == "issue_legal_decision"
    )
    assert action["matter_id"] == matter_id
    assert executor.execute_action(6, regulator, action)["ok"]
    assert store.scalar("SELECT status FROM legal_matters WHERE id=?", (matter_id,)) == "decided"

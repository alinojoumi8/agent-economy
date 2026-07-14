import json
import random

from engine.actions import ActionExecutor
from engine.core import Economy
from engine.schema import SCHEMA_VERSION

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

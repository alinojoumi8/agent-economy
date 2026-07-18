"""Frozen branch-blind supplier-warning policy and causal-chain tests."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agents.memory import Memory
from agents.policies import (
    SUPPLIER_WARNING_BODY,
    SUPPLIER_WARNING_POLICY_CONTRACT_HASH,
    SUPPLIER_WARNING_SUBJECT,
    supplier_warning_decision,
)
from agents.prompts import ContextBuilder
from agents.runtime import AgentRuntime
from causal import CausalLinkService
from communications.delivery import CommunicationDelivery
from communications.projections import AgentKnowledgeProjection
from engine.actions import ActionExecutor
from tests.conftest import make_agent, make_bank


NEUTRAL_BODY = (
    "Batch 2026-07 is cleared. Continue the scheduled 10-unit purchase."
)


def _input(body: str | None = None) -> dict:
    inbox = []
    if body is not None:
        inbox.append({
            "sender_role": "supplier_officer",
            "subject": SUPPLIER_WARNING_SUBJECT,
            "body": body,
            "delivery_tick": 6,
        })
    return {
        "authorized_inbox": inbox,
        "cash_cents": 10_000,
        "firm_id": 17,
        "firm_inventory": 100,
        "unit_price_cents": 100,
    }


def _quantity(policy_input: dict) -> int:
    return int(supplier_warning_decision(policy_input)["actions"][0]["qty"])


def test_frozen_policy_hash_and_metamorphic_probes_follow_authorized_body_only():
    assert SUPPLIER_WARNING_POLICY_CONTRACT_HASH == (
        "f29339c7ff21c653419226f2aee4c25eaeb99ccbc2886674519f9d24b05fc9a2")
    assert _quantity(_input()) == 10
    assert _quantity(_input(NEUTRAL_BODY)) == 10
    assert _quantity(_input(SUPPLIER_WARNING_BODY)) == 5

    # Relabeling is intentionally outside the canonical input and therefore
    # cannot affect the policy. Swapping only bodies swaps the outcome.
    labels = ["control-none", "renamed-treatment", "fork-z"]
    assert {_quantity(_input(SUPPLIER_WARNING_BODY)) for _ in labels} == {5}
    swapped = [
        _quantity(_input(SUPPLIER_WARNING_BODY)),
        _quantity(_input(NEUTRAL_BODY)),
    ]
    assert swapped == [5, 10]
    # A truth row that was withheld from authorized delivery is represented by
    # an empty inbox and cannot influence the result.
    assert _quantity(_input()) == 10


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda value: value.update({"branch_label": "treatment"}), "input fields"),
        (lambda value: value["authorized_inbox"].append({"body": "x"}), "inbox fields"),
        (lambda value: value.update({"cash_cents": 999}), "preconditions"),
        (lambda value: value.update({"firm_inventory": 9}), "preconditions"),
        (lambda value: value.update({"unit_price_cents": 0}), "preconditions"),
        (lambda value: value.update({"firm_id": 0}), "preconditions"),
    ],
)
def test_frozen_policy_rejects_extra_fields_malformed_inbox_and_invalid_fixture(
        mutation, match):
    value = _input()
    mutation(value)
    with pytest.raises(ValueError, match=match):
        supplier_warning_decision(value)


def _fixture(economy):
    economy.config.update({
        "engine_semantics_version": 8,
        "communications": {},
    })
    bank_id = make_bank(economy)
    sender_id, _ = make_agent(
        economy, bank_id, name="Supplier Officer", role="supplier_officer",
        population_tier="core")
    recipient_id, recipient_account_id = make_agent(
        economy, bank_id, name="Retailer Manager", role="retailer_manager",
        population_tier="periphery", cash=10_000)
    firm_account_id = economy.ledger.create_account(
        "firm", None, "checking", bank_id=bank_id, label="Supplier:operating")
    firm_id = economy.store.insert(
        "firms", name="Supplier", sector="goods", founder_agent_id=sender_id,
        status="private", product_json=json.dumps({
            "product": "fixture good", "unit_price_cents": 100,
        }), account_id=firm_account_id, founded_tick=0, inventory=100)
    economy.store.execute(
        "UPDATE accounts SET owner_id=? WHERE id=?", (firm_id, firm_account_id))
    economy.config["communications"]["supplier_warning_policy"] = {
        "retailer_agent_id": recipient_id,
        "supplier_firm_id": firm_id,
    }
    return sender_id, recipient_id, recipient_account_id, firm_id


def test_warning_executes_five_unit_purchase_with_exact_five_link_chain(economy):
    sender_id, recipient_id, recipient_account_id, firm_id = _fixture(economy)
    executor = ActionExecutor(economy)
    sent = executor.execute_action(5, sender_id, {
        "type": "send_message",
        "audience": {"kind": "direct", "agent_ids": [recipient_id]},
        "subject": SUPPLIER_WARNING_SUBJECT,
        "body": SUPPLIER_WARNING_BODY,
    })
    assert sent["ok"] is True
    assert CommunicationDelivery(economy.store, economy.config).deliver_due(6)[
        "delivered"] == 1

    projection_builder = AgentKnowledgeProjection(economy.store, economy.config)
    projection = projection_builder.build(recipient_id, 6)
    projection_builder.persist_read_context(recipient_id, 6, projection)
    context = {
        "authorized_inbox": projection["items"],
        "state": {"checking_balance": economy.ledger.balance(recipient_account_id)},
    }
    builder = object.__new__(ContextBuilder)
    builder.config = economy.config
    builder.store = economy.store
    builder._add_supplier_warning_policy_input(
        context, economy.store.query_one("SELECT * FROM agents WHERE id=?", (recipient_id,)), 6)
    assert set(context["supplier_warning_policy_input"]) == {
        "authorized_inbox", "cash_cents", "firm_id", "firm_inventory", "unit_price_cents",
    }
    assert set(context["supplier_warning_policy_input"]["authorized_inbox"][0]) == {
        "sender_role", "subject", "body", "delivery_tick",
    }
    envelope = supplier_warning_decision(context["supplier_warning_policy_input"])

    runtime = object.__new__(AgentRuntime)
    runtime.e = economy
    runtime.store = economy.store
    runtime.config = economy.config
    runtime.mem = Memory(economy.store, economy.config)
    runtime.executor = executor
    runtime.causal = CausalLinkService(economy.store)
    runtime.participant = SimpleNamespace(complete=lambda *_args: None)
    runtime.execute_decisions(6, [{
        "agent_id": recipient_id,
        "purpose": "decision",
        "envelope": envelope,
        "reasoning": envelope["reasoning"],
        "llm_call_id": None,
        "communication_sources": projection["sources"],
        "communication_read_context_key": projection["read_context_key"],
    }])

    proposal = economy.store.query_one(
        "SELECT * FROM action_proposals WHERE actor_id=? AND action_type='buy_goods'",
        (recipient_id,))
    result = json.loads(proposal["result_json"])
    payload = json.loads(proposal["payload_json"])
    assert result == {"ok": True, "qty": 5, "total_cents": 500,
                      "unit_price_cents": 100}
    assert payload["policy_contract_hash"] == SUPPLIER_WARNING_POLICY_CONTRACT_HASH
    assert len(payload["policy_input_hash"]) == 64
    assert economy.store.scalar("SELECT inventory FROM firms WHERE id=?", (firm_id,)) == 95

    memory_id = int(projection["sources"][0]["memory_id"])
    belief_id = int(economy.store.scalar(
        "SELECT id FROM beliefs WHERE agent_id=? AND key=?",
        (recipient_id, payload["causal_belief_key"])))
    sale_event_id = int(economy.store.scalar(
        "SELECT id FROM events WHERE kind='goods_sale' AND tick=6"))
    transaction_id = int(economy.store.scalar(
        "SELECT id FROM transactions WHERE kind='goods_purchase' AND tick=6"))
    expected = [
        ("message", sent["message_id"], "memory", memory_id, "observed", "engine"),
        ("memory", memory_id, "belief", belief_id, "triggered", "engine"),
        ("belief", belief_id, "action_proposal", int(proposal["id"]),
         "motivated", "actor_claim"),
        ("action_proposal", int(proposal["id"]), "event", sale_event_id,
         "triggered", "engine"),
        ("event", sale_event_id, "ledger_transaction", transaction_id,
         "settled", "engine"),
    ]
    chain = []
    for source_kind, source_id, target_kind, target_id, relation, authority in expected:
        rows = economy.store.query(
            "SELECT * FROM causal_links WHERE source_kind=? AND source_id=? "
            "AND target_kind=? AND target_id=? AND relation=? AND authority=?",
            (source_kind, str(source_id), target_kind, str(target_id), relation, authority),
        )
        assert len(rows) == 1
        chain.append(dict(rows[0]))
    assert chain[2]["method"] == "supplier-warning-policy-v1"
    settled = chain[-1]
    evidence = json.loads(settled["evidence_json"])
    assert evidence["transaction_id"] == int(settled["target_id"])
    assert len(evidence["entry_ids"]) == 2
    assert economy.store.scalar(
        "SELECT COALESCE(SUM(delta_cents),0) FROM ledger_entries WHERE txn_id=?",
        (evidence["transaction_id"],)) == 0

"""Exhaustive branch tests for Semantics 8 causal and membership contracts."""
from __future__ import annotations

import json

import pytest

from causal.links import CausalLinkError, CausalLinkService
from causal.references import (
    StableReferenceError,
    StableReferenceRegistry,
)
from communications.membership import (
    OrganizationMembershipResolver,
    OrganizationReferenceError,
)
from engine.actions import ActionExecutor
from tests.conftest import make_agent, make_bank


def _world(economy):
    economy.config["engine_semantics_version"] = 8
    bank_id = make_bank(economy)
    first, _ = make_agent(economy, bank_id, name="First", role="founder")
    second, _ = make_agent(economy, bank_id, name="Second")
    third, _ = make_agent(economy, bank_id, name="Third")
    return bank_id, first, second, third


def _message(economy, sender: int, recipient: int, tick: int = 1) -> int:
    result = ActionExecutor(economy).execute_action(
        tick,
        sender,
        {
            "type": "send_message",
            "audience": {"kind": "direct", "agent_ids": [recipient]},
            "subject": "Reference",
            "body": "Reference body",
        },
    )
    assert result["ok"]
    return int(result["message_id"])


def _stable_objects(economy, agent_id: int, message_id: int) -> dict[str, int]:
    store = economy.store
    memory_id = store.insert(
        "memories", agent_id=agent_id, tick=2, kind="communication", text="m",
        importance=1.0, entities_json="[]", last_accessed_tick=0, demoted=0)
    ordinary_memory_id = store.insert(
        "memories", agent_id=agent_id, tick=3, kind="observation", text="m2",
        importance=1.0, entities_json="[]", last_accessed_tick=0, demoted=0)
    belief_id = store.insert(
        "beliefs", agent_id=agent_id, key="coverage", value=0.5, updated_tick=3)
    decision_id = store.insert(
        "agent_decisions", dedupe_key="d" * 64, tick=4, agent_id=agent_id,
        purpose="coverage", method="scripted_policy", model_call_id=None,
        read_context_key=None, reasoning_fingerprint="r" * 64)
    proposal_id = store.insert(
        "action_proposals", tick=5, actor_id=agent_id, action_type="wait",
        payload_json="{}", evidence_event_ids_json="[]", model_call_id=None,
        rationale_summary="", validation_status="accepted", result_json="{}")
    event_id = store.log_event(
        2, "coverage_event", {}, phase="UNREGISTERED_PHASE",
        subject_type="agent", subject_id=agent_id)
    transaction_id = store.insert(
        "transactions", tick=7, kind="coverage", memo="coverage", created_at=None)
    article_id = store.insert(
        "news_articles", tick=8, outlet_id=1, outlet_name="Outlet",
        headline="Headline", body="Body", slant_tags="[]", source_event_ids="[]",
        tone=0.0, truthful=1)
    contract_id = store.insert(
        "contracts", contract_type="sale", title="Contract", status="offered",
        jurisdiction="test", ruleset_key="coverage", version=1,
        parent_contract_id=None, drafter_agent_id=agent_id, offered_tick=9,
        executed_tick=None, effective_tick=None, expiry_tick=None,
        terminated_tick=None, prose="", metadata_json="{}")
    case_id = store.insert(
        "legal_matters", matter_type="civil", venue="test", status="filed",
        contract_id=None, claimant_type="agent", claimant_id=agent_id,
        respondent_type="agent", respondent_id=agent_id, claim_type="coverage",
        filed_tick=10, response_due_tick=11, resolved_tick=None,
        counsel_agent_id=None, requested_remedy_json="{}", settlement_json=None,
        metadata_json="{}")
    return {
        "message": message_id,
        "memory": memory_id,
        "ordinary_memory": ordinary_memory_id,
        "belief": belief_id,
        "decision": decision_id,
        "action_proposal": proposal_id,
        "event": event_id,
        "ledger_transaction": transaction_id,
        "article": article_id,
        "contract": contract_id,
        "case": case_id,
    }


def test_stable_reference_registry_resolves_every_closed_kind(economy):
    _, first, second, _ = _world(economy)
    message_id = _message(economy, first, second)
    objects = _stable_objects(economy, first, message_id)
    registry = StableReferenceRegistry(economy.store)

    expected_phases = {
        "message": "EXECUTION",
        "memory": "INBOX_DELIVERY",
        "belief": "EXECUTION",
        "decision": "MORNING",
        "action_proposal": "EXECUTION",
        "event": "UNREGISTERED_PHASE",
        "ledger_transaction": "MARKET",
        "article": "NEWSROOM",
        "contract": "EXECUTION",
        "case": "EXECUTION",
    }
    for kind, expected_phase in expected_phases.items():
        reference = registry.resolve(kind, str(objects[kind]))
        assert reference.kind == kind
        assert reference.id == str(objects[kind])
        assert reference.phase == expected_phase
        assert reference.as_dict() == {
            "kind": kind,
            "id": str(objects[kind]),
            "tick": reference.tick,
            "order_key": reference.order_key,
        }
    assert registry.resolve("memory", objects["ordinary_memory"]).phase == "MEMORY"


@pytest.mark.parametrize("kind,object_id,match", [
    ("unknown", 1, "unsupported stable reference kind"),
    ("message", None, "positive integer"),
    ("message", "not-an-id", "positive integer"),
    ("message", 0, "positive integer"),
    ("message", -1, "positive integer"),
    ("message", 999999, "dangling stable reference"),
])
def test_stable_reference_registry_rejects_every_invalid_identity(
        economy, kind, object_id, match):
    registry = StableReferenceRegistry(economy.store)
    with pytest.raises(StableReferenceError, match=match):
        registry.resolve(kind, object_id)
    with pytest.raises(StableReferenceError, match="unsupported stable reference kind"):
        registry._row("unknown", 1)


def test_causal_relation_and_authority_contract_is_exhaustive():
    validate_relation = CausalLinkService._validate_relation
    validate_authority = CausalLinkService._validate_authority

    validate_relation("message", "belief", "inferred")
    with pytest.raises(CausalLinkError, match="invalid inferred"):
        validate_relation("ledger_transaction", "belief", "inferred")
    with pytest.raises(CausalLinkError, match="invalid inferred"):
        validate_relation("message", "memory", "inferred")
    with pytest.raises(CausalLinkError, match="unsupported causal relation"):
        validate_relation("message", "memory", "unknown")
    with pytest.raises(CausalLinkError, match="invalid observed"):
        validate_relation("memory", "message", "observed")

    validate_authority("observed", "engine", None, 1.0, None, None)
    validate_authority("cited", "actor_claim", 1, 0.5, "claim", None)
    validate_authority("inferred", "model_inference", None, 0.5, "model", 1)
    for confidence in (-0.01, 1.01):
        with pytest.raises(CausalLinkError, match="between zero and one"):
            validate_authority("observed", "engine", None, confidence, None, None)
    for relation, confidence in (("inferred", 1.0), ("observed", 0.5)):
        with pytest.raises(CausalLinkError, match="deterministic confidence"):
            validate_authority(relation, "engine", None, confidence, None, None)
    for actor_id, model_id in ((1, None), (None, 1)):
        with pytest.raises(CausalLinkError, match="cannot claim actor or model"):
            validate_authority("observed", "engine", actor_id, 1.0, None, model_id)
    with pytest.raises(CausalLinkError, match="only cite or motivate"):
        validate_authority("observed", "actor_claim", 1, 1.0, "claim", None)
    for actor_id, method in ((None, "claim"), (1, None)):
        with pytest.raises(CausalLinkError, match="require actor and method"):
            validate_authority("cited", "actor_claim", actor_id, 1.0, method, None)
    for relation, method, model_id in (
        ("cited", "model", 1), ("inferred", None, 1), ("inferred", "model", None),
    ):
        with pytest.raises(CausalLinkError, match="requires method and model call"):
            validate_authority(
                relation, "model_inference", None, 0.5, method, model_id)
    with pytest.raises(CausalLinkError, match="unsupported causal authority"):
        validate_authority("observed", "unknown", None, 1.0, None, None)


def test_causal_create_dedupes_and_enforces_temporal_order(economy):
    _, first, second, _ = _world(economy)
    message_id = _message(economy, first, second)
    objects = _stable_objects(economy, first, message_id)
    service = CausalLinkService(economy.store)

    link_id = service.create(
        "event", objects["event"], "memory", objects["ordinary_memory"],
        "observed", "engine", created_tick=6,
        provenance={"z": 1}, evidence={"a": 2})
    assert service.create(
        "event", objects["event"], "memory", objects["ordinary_memory"],
        "observed", "engine", created_tick=6,
        provenance={"z": 1}, evidence={"a": 2}) == link_id

    with pytest.raises(CausalLinkError, match="self-links"):
        service.create(
            "message", message_id, "message", message_id,
            "cited", "actor_claim", actor_agent_id=first, method="claim")
    with pytest.raises(CausalLinkError, match="move forward"):
        service.create(
            "memory", objects["ordinary_memory"], "message", message_id,
            "cited", "actor_claim", actor_agent_id=first, method="claim")
    with pytest.raises(CausalLinkError, match="cannot predate"):
        service.create(
            "event", objects["event"], "memory", objects["ordinary_memory"],
            "observed", "engine", created_tick=1)

    model_call_id = economy.store.insert(
        "llm_calls", tick=6, agent_id=first, role="test", provider="test",
        model="test", purpose="decision", cache_key=None, request_json="{}",
        response_json="{}", in_tokens=0, out_tokens=0, cached=0, cost_usd=0.0,
        latency_ms=0, created_at=None)
    inferred = service.create(
        "event", objects["event"], "belief", objects["belief"],
        "inferred", "model_inference", confidence=0.25, method="probe",
        model_call_id=model_call_id)
    assert inferred > 0


def test_causal_neighborhood_bounds_cycles_and_truncation(economy):
    _, first, second, _ = _world(economy)
    message_id = _message(economy, first, second)
    objects = _stable_objects(economy, first, message_id)
    service = CausalLinkService(economy.store)
    service.create(
        "message", message_id, "memory", objects["memory"], "observed", "engine")
    service.create(
        "memory", objects["memory"], "belief", objects["belief"], "triggered", "engine")
    service.create(
        "belief", objects["belief"], "decision", objects["decision"],
        "motivated", "actor_claim", actor_agent_id=first, method="policy")

    assert service.neighborhood("message", message_id, depth=0)["edges"] == []
    graph = service.neighborhood("memory", objects["memory"], depth=3)
    assert len(graph["nodes"]) >= 3
    assert graph["cycles"]
    assert graph["truncated"] is False
    assert service.neighborhood(
        "memory", objects["memory"], depth=3, max_edges=1)["truncated"] is True
    assert service.neighborhood(
        "memory", objects["memory"], depth=3, max_nodes=1)["truncated"] is True

    for depth in (-1, 7):
        with pytest.raises(CausalLinkError, match="depth"):
            service.neighborhood("message", message_id, depth=depth)
    for kwargs in (
        {"max_nodes": 0}, {"max_nodes": 1001},
        {"max_edges": 0}, {"max_edges": 2001},
    ):
        with pytest.raises(CausalLinkError, match="limits"):
            service.neighborhood("message", message_id, **kwargs)


def test_membership_resolver_validates_and_snapshots_every_adapter(economy):
    bank_id, first, second, third = _world(economy)
    store = economy.store
    firm_id = store.insert(
        "firms", name="Firm", sector="goods", founder_agent_id=first,
        status="private", product_json="{}", founded_tick=0)
    store.insert(
        "employments", firm_id=firm_id, agent_id=second, title="staff",
        wage_cents=100, start_tick=0, end_tick=None, status="active",
        pay_interval_ticks=30, next_pay_tick=30)
    store.update("agents", second, employer_id=bank_id, role="credit_officer")
    store.update("agents", third, role="regulator")
    outlet_agent, _ = make_agent(economy, bank_id, name="Editor", role="editor")
    store.update("agents", outlet_agent, personality_json=json.dumps({"outlet_id": 7}))

    resolver = OrganizationMembershipResolver(store)
    resolver.validate_reference("firm", firm_id)
    resolver.validate_reference("bank", bank_id)
    resolver.validate_reference("government", 1)
    resolver.validate_reference("outlet", 7)
    assert resolver.snapshot("firm", firm_id, 2).member_ids == (first, second)
    assert resolver.snapshot("bank", bank_id, 2).member_ids == (second,)
    assert third in resolver.snapshot("government", 1, 2).member_ids
    outlet = resolver.snapshot("outlet", 7, 2)
    assert outlet.member_ids == (outlet_agent,)
    assert json.loads(outlet.reference_json())["snapshot_hash"] == outlet.snapshot_hash


def test_membership_configuration_and_invalid_references(economy):
    _, first, _, _ = _world(economy)
    store = economy.store
    configured = OrganizationMembershipResolver(store, {
        "government": {"name": "Government"},
        "news": {"outlets": [{"id": "11"}, {}, {"id": "invalid"}, "plain"]},
    })
    configured.validate_reference("government", 1)
    configured.validate_reference("outlet", 11)
    configured.validate_reference("outlet", 2)
    configured.validate_reference("outlet", 4)
    assert configured.snapshot("outlet", 11, 1).member_ids == ()
    fallback = OrganizationMembershipResolver(store, {"outlets": [{"id": 12}]})
    fallback.validate_reference("outlet", 12)

    for kind, organization_id, match in (
        ("unknown", 1, "unsupported organization kind"),
        ("firm", True, "must be positive"),
        ("firm", 0, "must be positive"),
        ("firm", 999999, "unknown firm"),
        ("bank", 999999, "unknown bank"),
        ("government", 2, "unknown government"),
        ("outlet", 999999, "unknown outlet"),
    ):
        with pytest.raises(OrganizationReferenceError, match=match):
            OrganizationMembershipResolver(store).validate_reference(kind, organization_id)

    # The configured-government path remains valid even with no official role.
    store.update("agents", first, role="citizen")
    configured.validate_reference("government", 1)

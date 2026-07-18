"""Stateful semantics-8 communication, privacy, and replay tests."""
from __future__ import annotations

import json

import pytest

from agents.memory import Memory
from agents.policies import scripted_decision
from agents.prompts import ContextBuilder
from communications.delivery import CommunicationDelivery
from communications.handlers import CommunicationRejected, CommunicationService
from communications.policy import (
    AccessBasis,
    CommunicationPolicy,
    MessageField,
    Principal,
)
from communications.projections import AgentKnowledgeProjection
from engine.actions import ActionExecutor
from tests.conftest import make_agent, make_bank


def _semantics8(economy):
    economy.config["engine_semantics_version"] = 8
    economy.config.setdefault("communications", {})
    return ActionExecutor(economy)


def _agents(economy):
    bank_id = make_bank(economy)
    sender, _ = make_agent(
        economy, bank_id, name="Sender", population_tier="core", role="founder")
    recipient, _ = make_agent(
        economy, bank_id, name="Recipient", population_tier="core")
    third, _ = make_agent(
        economy, bank_id, name="Third", population_tier="periphery")
    return bank_id, sender, recipient, third


def _send(executor, tick, sender, recipient, *, subject="Warning", body="Buy only five units"):
    return executor.execute_action(
        tick,
        sender,
        {
            "type": "send_message",
            "audience": {"kind": "direct", "agent_ids": [recipient]},
            "subject": subject,
            "body": body,
        },
    )


def test_direct_message_is_private_until_exactly_once_next_tick_delivery(economy):
    _, sender, recipient, _ = _agents(economy)
    executor = _semantics8(economy)
    result = _send(executor, 1, sender, recipient)
    assert result["ok"] is True
    message_id = result["message_id"]

    proposal = economy.store.query_one(
        "SELECT payload_json FROM action_proposals WHERE action_type='send_message'")
    proposal_payload = json.loads(proposal["payload_json"])
    assert proposal_payload["direct_recipient_count"] == 1
    assert proposal_payload["content_ref"].startswith("sha256:")
    assert "Warning" not in proposal["payload_json"]
    assert "Buy only five units" not in proposal["payload_json"]
    queued_event = economy.store.query_one(
        "SELECT payload_json FROM events WHERE kind='communication_queued'")
    assert "Warning" not in queued_event["payload_json"]
    assert set(json.loads(queued_event["payload_json"])) == {
        "command_type", "audience_kind", "direct_recipient_count", "deliver_at_tick"}

    policy = CommunicationPolicy(economy.store)
    sender_principal = Principal(f"agent:{sender}", agent_id=sender)
    recipient_principal = Principal(f"agent:{recipient}", agent_id=recipient)
    assert policy.can_read_field(
        sender_principal, message_id, MessageField.BODY, 1).basis is AccessBasis.SENDER
    assert not policy.can_read_field(
        recipient_principal, message_id, MessageField.EXISTENCE, 1).allowed

    delivery = CommunicationDelivery(economy.store, economy.config)
    assert delivery.deliver_due(1)["messages"] == 0
    delivered = delivery.deliver_due(2)
    assert delivered == {
        "messages": 1, "delivered": 1, "undeliverable": 0, "published": 0}
    assert delivery.deliver_due(2)["messages"] == 0

    grant = economy.store.query_one(
        "SELECT * FROM comm_deliveries WHERE message_id=? AND recipient_agent_id=?",
        (message_id, recipient),
    )
    assert grant["delivery_status"] == "delivered"
    memory = economy.store.query_one("SELECT * FROM memories WHERE id=?", (grant["memory_id"],))
    assert memory["kind"] == "communication"
    assert "Buy only five units" in memory["text"]
    observed = economy.store.query_one(
        "SELECT * FROM causal_links WHERE source_kind='message' AND source_id=? "
        "AND target_kind='memory' AND target_id=? AND relation='observed'",
        (str(message_id), str(grant["memory_id"])),
    )
    assert observed["authority"] == "engine"
    assert policy.can_read_field(
        recipient_principal, message_id, MessageField.BODY, 2).basis is (
            AccessBasis.DIRECT_DELIVERY)


def test_read_context_is_bounded_persisted_and_resume_stable(economy):
    _, sender, recipient, _ = _agents(economy)
    executor = _semantics8(economy)
    message_id = _send(executor, 1, sender, recipient)["message_id"]
    CommunicationDelivery(economy.store, economy.config).deliver_due(2)
    projection = AgentKnowledgeProjection(economy.store, economy.config)

    first = projection.build(recipient, 2)
    assert [item["message_id"] for item in first["items"]] == [message_id]
    assert first["items"][0]["untrusted_world_data"] is True
    projection.persist_read_context(recipient, 2, first)
    resumed = projection.build(recipient, 2)
    assert resumed == first
    projection.persist_read_context(recipient, 2, resumed)
    assert economy.store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='communication_read_context'") == 1
    assert projection.build(recipient, 3)["items"] == []


def test_agent_directory_is_relationship_bounded_and_reply_safe(economy):
    _, sender, recipient, third = _agents(economy)
    executor = _semantics8(economy)
    original = _send(executor, 1, sender, recipient)
    CommunicationDelivery(economy.store, economy.config).deliver_due(2)
    economy.store.insert(
        "social_ties", agent_a=recipient, agent_b=third, weight=0.9)

    projection = AgentKnowledgeProjection(economy.store, economy.config)
    inbox = projection.build(recipient, 2)
    assert inbox["items"][0]["can_reply"] is True
    directory = projection.contact_directory(recipient, 2, inbox["items"])
    assert [item["agent_id"] for item in directory] == [sender, third]
    assert directory[0]["relationships"] == ["recent_correspondent"]
    assert directory[1]["relationships"] == ["social_tie"]

    reply = executor.execute_action(
        2, recipient,
        {"type": "reply_message", "parent_message_id": original["message_id"],
         "body": "I will consider it"},
    )
    assert reply["ok"] is True
    assert projection.build(recipient, 2)["items"][0]["can_reply"] is False
    economy.store.update("agents", third, alive=0, died_tick=2)
    assert [item["agent_id"] for item in projection.contact_directory(
        recipient, 2, inbox["items"])] == [sender]


def test_scripted_agents_choose_one_goal_driven_reply_without_extra_model_call(economy):
    _, sender, recipient, _ = _agents(economy)
    economy.config["engine_semantics_version"] = 8
    builder = ContextBuilder(economy, Memory(economy.store, economy.config), economy.config)
    context = {
        "purpose": "decision",
        "agent": {"id": recipient, "health": "critical"},
        "state": {},
        "authorized_inbox": [{"message_id": 41, "can_reply": True}],
    }
    action = builder._goal_driven_communication_action(
        context, {"id": recipient}, 2,
        [{"agent_id": sender, "name": "Sender"}],
    )
    assert action == {
        "type": "reply_message",
        "parent_message_id": 41,
        "body": (
            "Thanks for the update. I will consider it alongside my current work "
            "and household priorities."),
    }
    context["scripted_communication_action"] = action
    envelope = scripted_decision("decision", context)
    communication_actions = [
        item for item in envelope["actions"]
        if item["type"] in {"send_message", "reply_message", "forward_message"}
    ]
    assert communication_actions == [action]


@pytest.mark.parametrize(
    ("purpose", "extra", "subject"),
    [
        ("founder", {}, "Operations coordination"),
        ("decision", {"career_day": True}, "Career coordination"),
        ("lawyer", {}, "Role coordination"),
        ("decision", {}, "Household coordination"),
    ],
)
def test_proactive_scripted_messages_follow_agent_goal_and_known_contact(
        economy, purpose, extra, subject):
    _, sender, recipient, _ = _agents(economy)
    economy.config["engine_semantics_version"] = 8
    economy.config["communications"] = {"autonomous_cadence_ticks": 7}
    builder = ContextBuilder(economy, Memory(economy.store, economy.config), economy.config)
    context = {"purpose": purpose, "authorized_inbox": [], **extra}
    tick = recipient % 7
    action = builder._goal_driven_communication_action(
        context, {"id": recipient}, tick,
        [{"agent_id": sender, "name": "Sender"}],
    )
    assert action["type"] == "send_message"
    assert action["audience"] == {"kind": "direct", "agent_ids": [sender]}
    assert action["subject"] == subject


def test_autonomous_communication_can_be_disabled_or_deferred(economy):
    _, sender, recipient, _ = _agents(economy)
    economy.config["engine_semantics_version"] = 8
    economy.config["communications"] = {"autonomous_scripted_enabled": False}
    builder = ContextBuilder(economy, Memory(economy.store, economy.config), economy.config)
    assert builder._goal_driven_communication_action(
        {}, {"id": recipient}, 1, [{"agent_id": sender}]) is None
    builder.config["communications"] = {
        "autonomous_scripted_enabled": True, "autonomous_cadence_ticks": 7}
    assert builder._goal_driven_communication_action(
        {}, {"id": recipient}, recipient % 7, []) is None
    assert builder._goal_driven_communication_action(
        {}, {"id": recipient}, (recipient + 1) % 7,
        [{"agent_id": sender}]) is None


def test_semantics8_prompt_exposes_bounded_recipient_choices(economy):
    _, sender, recipient, _ = _agents(economy)
    economy.config["engine_semantics_version"] = 8
    builder = ContextBuilder(economy, Memory(economy.store, economy.config), economy.config)
    system, user = builder.render_prompt({
        "agent": {"id": recipient, "name": "Recipient"},
        "communication_directory": [{
            "agent_id": sender, "name": "Sender", "role": "founder",
            "occupation": "", "relationships": ["social_tie"],
        }],
        "scripted_communication_action": {
            "type": "send_message",
            "audience": {"kind": "direct", "agent_ids": [sender]},
            "subject": "Coordination", "body": "Any relevant facts?",
        },
    })
    assert "Direct recipient\nIDs must come from the supplied communication directory" in system
    assert '"agent_id":' + str(sender) in user
    assert "OPTIONAL GOAL-DRIVEN COMMUNICATION OPPORTUNITY" in user


def test_reply_is_private_to_parent_sender_and_does_not_grant_old_history(economy):
    _, sender, recipient, third = _agents(economy)
    executor = _semantics8(economy)
    original = _send(executor, 1, sender, recipient)
    CommunicationDelivery(economy.store, economy.config).deliver_due(2)
    reply = executor.execute_action(
        2,
        recipient,
        {"type": "reply_message", "parent_message_id": original["message_id"],
         "body": "Acknowledged"},
    )
    assert reply["ok"] is True
    row = economy.store.query_one("SELECT * FROM comm_messages WHERE id=?", (reply["message_id"],))
    assert row["thread_id"] == original["thread_id"]
    assert row["parent_message_id"] == original["message_id"]
    assert row["visibility"] == "participants"
    audience = economy.store.query_one(
        "SELECT * FROM comm_audiences WHERE message_id=?", (reply["message_id"],))
    assert audience["audience_agent_id"] == sender
    assert not CommunicationPolicy(economy.store).can_read_field(
        Principal(f"agent:{third}", agent_id=third),
        original["message_id"], MessageField.EXISTENCE, 3).allowed


def test_forward_derives_new_thread_and_citation_without_granting_source(economy):
    _, sender, recipient, third = _agents(economy)
    executor = _semantics8(economy)
    original = _send(executor, 1, sender, recipient, subject="Plan", body="Private plan")
    CommunicationDelivery(economy.store, economy.config).deliver_due(2)
    forwarded = executor.execute_action(
        2,
        recipient,
        {
            "type": "forward_message",
            "source_message_id": original["message_id"],
            "audience": {"kind": "direct", "agent_ids": [third]},
            "note": "For your awareness",
        },
    )
    assert forwarded["ok"] is True
    assert forwarded["thread_id"] != original["thread_id"]
    row = economy.store.query_one(
        "SELECT m.*,t.subject FROM comm_messages m JOIN comm_threads t ON t.id=m.thread_id "
        "WHERE m.id=?",
        (forwarded["message_id"],),
    )
    assert row["forwarded_from_id"] == original["message_id"]
    assert row["subject"] == "Fwd: Plan"
    assert "Private plan" in row["body_text"]
    cited = economy.store.query_one(
        "SELECT * FROM causal_links WHERE source_kind='message' AND source_id=? "
        "AND target_kind='message' AND target_id=? AND relation='cited'",
        (str(original["message_id"]), str(forwarded["message_id"])),
    )
    assert cited["authority"] == "actor_claim"
    policy = CommunicationPolicy(economy.store)
    third_principal = Principal(f"agent:{third}", agent_id=third)
    assert not policy.can_read_field(
        third_principal, original["message_id"], MessageField.EXISTENCE, 3).allowed
    CommunicationDelivery(economy.store, economy.config).deliver_due(3)
    assert policy.can_read_field(
        third_principal, forwarded["message_id"], MessageField.BODY, 3).allowed


def test_forward_rejects_canonical_body_over_limit_without_partial_rows(economy):
    _, sender, recipient, third = _agents(economy)
    executor = _semantics8(economy)
    original = _send(executor, 1, sender, recipient, body="x" * 2000)
    CommunicationDelivery(economy.store, economy.config).deliver_due(2)
    before = economy.store.scalar("SELECT COUNT(*) FROM comm_messages")
    result = executor.execute_action(
        2,
        recipient,
        {
            "type": "forward_message",
            "source_message_id": original["message_id"],
            "audience": {"kind": "direct", "agent_ids": [third]},
            "note": "n",
        },
    )
    assert result == {"ok": False, "reason": "forward_body_too_long"}
    assert economy.store.scalar("SELECT COUNT(*) FROM comm_messages") == before


def test_public_statement_publishes_once_without_memory_fanout(economy):
    _, sender, recipient, _ = _agents(economy)
    executor = _semantics8(economy)
    result = executor.execute_action(
        1,
        sender,
        {"type": "send_message", "audience": {"kind": "public"},
         "subject": "Statement", "body": "Public content"},
    )
    assert result["ok"] is True
    outcome = CommunicationDelivery(economy.store, economy.config).deliver_due(2)
    assert outcome["published"] == 1
    assert economy.store.scalar(
        "SELECT COUNT(*) FROM comm_deliveries WHERE message_id=?", (result["message_id"],)) == 0
    assert economy.store.scalar(
        "SELECT COUNT(*) FROM memories WHERE agent_id=? AND kind='communication'", (recipient,)) == 0
    ordinary = Principal("ordinary")
    access = CommunicationPolicy(economy.store).can_read_field(
        ordinary, result["message_id"], MessageField.BODY, 2)
    assert access.basis is AccessBasis.PUBLIC_RELEASE


def test_direct_death_before_delivery_is_one_undeliverable_outcome(economy):
    _, sender, recipient, _ = _agents(economy)
    executor = _semantics8(economy)
    result = _send(executor, 1, sender, recipient)
    economy.store.update("agents", recipient, alive=0, died_tick=2)
    delivery = CommunicationDelivery(economy.store, economy.config)
    outcome = delivery.deliver_due(2)
    assert outcome["undeliverable"] == 1
    row = economy.store.query_one(
        "SELECT * FROM comm_deliveries WHERE message_id=?", (result["message_id"],))
    assert row["delivery_status"] == "undeliverable"
    assert row["memory_id"] is None
    assert delivery.deliver_due(3)["messages"] == 0


def test_firm_membership_is_snapshotted_and_historical_grant_is_immutable(economy):
    _, sender, recipient, third = _agents(economy)
    executor = _semantics8(economy)
    firm_id = economy.store.insert(
        "firms", name="Org", sector="goods", founder_agent_id=sender,
        status="private", product_json="{}", founded_tick=0)
    employment_id = economy.store.insert(
        "employments", firm_id=firm_id, agent_id=recipient, title="staff", wage_cents=100,
        start_tick=0, end_tick=None, status="active", pay_interval_ticks=30,
        next_pay_tick=30)
    message = executor.execute_action(
        1,
        sender,
        {
            "type": "send_message",
            "audience": {"kind": "organization", "organization_kind": "firm",
                         "organization_id": firm_id},
            "subject": "Team", "body": "Internal",
        },
    )
    # Join before delivery is visible; leave after delivery does not revoke.
    economy.store.insert(
        "employments", firm_id=firm_id, agent_id=third, title="new", wage_cents=100,
        start_tick=2, end_tick=None, status="active", pay_interval_ticks=30,
        next_pay_tick=30)
    CommunicationDelivery(economy.store, economy.config).deliver_due(2)
    grant = economy.store.query_one(
        "SELECT * FROM comm_deliveries WHERE message_id=? AND recipient_agent_id=?",
        (message["message_id"], recipient),
    )
    membership = json.loads(grant["membership_ref_json"])
    assert membership["member_ids"] == sorted([sender, recipient, third])
    economy.store.update("employments", employment_id, status="ended", end_tick=2)
    assert CommunicationPolicy(economy.store).can_read_field(
        Principal(f"agent:{recipient}", agent_id=recipient),
        message["message_id"], MessageField.BODY, 3).basis is (
            AccessBasis.ORGANIZATION_AT_DELIVERY)
    with pytest.raises(Exception, match="immutable"):
        economy.store.execute(
            "UPDATE comm_deliveries SET recipient_agent_id=? WHERE id=?", (third, grant["id"]))


def test_periphery_and_core_quotas_are_deterministic(economy):
    _, sender, recipient, periphery = _agents(economy)
    executor = _semantics8(economy)
    for index in range(3):
        assert _send(
            executor, 1, sender, recipient, subject=f"s{index}", body="b")["ok"]
    assert _send(executor, 1, sender, recipient, subject="s4", body="b") == {
        "ok": False, "reason": "communication_quota_exceeded"}
    assert _send(executor, 1, periphery, recipient, subject="p1", body="b")["ok"]
    assert _send(executor, 1, periphery, recipient, subject="p2", body="b") == {
        "ok": False, "reason": "communication_quota_exceeded"}


@pytest.mark.parametrize(
    "boundary",
    ["after_memory", "after_delivery", "after_causal", "after_audience",
     "after_message_resolution"],
)
def test_failure_at_each_delivery_boundary_rolls_back_then_delivers_once(economy, boundary):
    _, sender, recipient, _ = _agents(economy)
    executor = _semantics8(economy)
    result = _send(executor, 1, sender, recipient)
    fired = False

    def fault(name, _context):
        nonlocal fired
        if name == boundary and not fired:
            fired = True
            raise RuntimeError(f"fault:{boundary}")

    with pytest.raises(RuntimeError, match="fault"):
        CommunicationDelivery(
            economy.store, economy.config, fault_hook=fault).deliver_due(2)
    assert economy.store.scalar(
        "SELECT COUNT(*) FROM comm_deliveries WHERE message_id=?", (result["message_id"],)) == 0
    assert economy.store.scalar(
        "SELECT COUNT(*) FROM memories WHERE kind='communication'") == 0
    outcome = CommunicationDelivery(economy.store, economy.config).deliver_due(2)
    assert outcome["delivered"] == 1
    assert economy.store.scalar(
        "SELECT COUNT(*) FROM comm_deliveries WHERE message_id=?", (result["message_id"],)) == 1
    assert economy.store.scalar(
        "SELECT COUNT(*) FROM memories WHERE kind='communication'") == 1


def test_same_case_disclosure_grants_access_and_wrong_case_fails(economy):
    _, sender, recipient, third = _agents(economy)
    executor = _semantics8(economy)
    message = _send(executor, 1, sender, recipient)
    authority_event = economy.store.log_event(2, "court_order", {"case_id": 9})
    service = CommunicationService(economy.store, economy.config)
    with pytest.raises(CommunicationRejected, match="disclosure_case_mismatch"):
        service.grant_disclosure(
            tick=2, message_id=message["message_id"], case_id=9,
            grantee_agent_id=third, authority_kind="court_order",
            authority_record_id="order-1", authority_event_id=authority_event,
            authority_ref={"case_id": 9}, verified_case_id=10)
    grant_id = service.grant_disclosure(
        tick=2, message_id=message["message_id"], case_id=9,
        grantee_agent_id=third, authority_kind="court_order",
        authority_record_id="order-1", authority_event_id=authority_event,
        authority_ref={"case_id": 9}, verified_case_id=9)
    assert grant_id > 0
    access = CommunicationPolicy(economy.store).can_read_field(
        Principal(f"agent:{third}", agent_id=third, disclosure_case_id=9),
        message["message_id"], MessageField.BODY, 2)
    assert access.basis is AccessBasis.LEGAL_DISCLOSURE


def test_operator_truth_requires_successful_sidecar_audit(economy):
    _, sender, recipient, _ = _agents(economy)
    message = _send(_semantics8(economy), 1, sender, recipient)
    principal = Principal("operator", operator_truth=True)
    assert not CommunicationPolicy(economy.store).can_read_field(
        principal, message["message_id"], MessageField.BODY, 1).allowed
    audited = []

    def audit(_principal, message_id, field, tick):
        audited.append((message_id, field.value, tick))
        return True

    access = CommunicationPolicy(economy.store, truth_audit=audit).can_read_field(
        principal, message["message_id"], MessageField.BODY, 1)
    assert access.basis is AccessBasis.OPERATOR_TRUTH
    assert audited == [(message["message_id"], "body", 1)]

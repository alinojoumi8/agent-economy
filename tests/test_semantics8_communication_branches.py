"""Branch-complete communication domain, privacy, and inbox tests."""
from __future__ import annotations

import json

import pytest

from communications.delivery import CommunicationDelivery
from communications.handlers import CommunicationRejected, CommunicationService
from communications.membership import MembershipSnapshot
from communications.policy import (
    AccessBasis,
    AccessDecision,
    CommunicationPolicy,
    MessageField,
    Principal,
)
from communications.privacy import safe_action_for_diagnostic, safe_command_metadata
from communications.projections import AgentKnowledgeProjection, public_communication_summary
from engine.actions import ActionExecutor
from engine.commands.registry import CommandValidationError, default_registry
from tests.conftest import make_agent, make_bank


def _world(economy):
    economy.config["engine_semantics_version"] = 8
    economy.config.setdefault("communications", {})
    bank_id = make_bank(economy)
    sender, _ = make_agent(
        economy, bank_id, name="Sender", role="founder", population_tier="core")
    recipient, _ = make_agent(economy, bank_id, name="Recipient", population_tier="core")
    third, _ = make_agent(economy, bank_id, name="Third", population_tier="core")
    return bank_id, sender, recipient, third


def _send(economy, sender, audience, *, tick=1, subject="Subject", body="Body"):
    return ActionExecutor(economy).execute_action(
        tick, sender,
        {"type": "send_message", "audience": audience, "subject": subject, "body": body})


def _direct(economy, sender, recipient, **kwargs):
    return _send(
        economy, sender, {"kind": "direct", "agent_ids": [recipient]}, **kwargs)


def test_delivery_handles_partial_audience_and_partial_message(economy, monkeypatch):
    _, sender, recipient, third = _world(economy)
    firm_id = economy.store.insert(
        "firms", name="Firm", sector="goods", founder_agent_id=sender,
        status="private", product_json="{}", founded_tick=0)
    organization = _send(
        economy, sender,
        {"kind": "organization", "organization_kind": "firm", "organization_id": firm_id})
    economy.store.update("agents", third, alive=0, died_tick=2)
    delivery = CommunicationDelivery(economy.store, economy.config)
    monkeypatch.setattr(
        delivery.membership,
        "snapshot",
        lambda *_args: MembershipSnapshot("firm", firm_id, 2, (sender, third), "s" * 64),
    )
    outcome = delivery.deliver_due(2)
    assert outcome["delivered"] == 1
    assert outcome["undeliverable"] == 1
    audience = economy.store.query_one(
        "SELECT * FROM comm_audiences WHERE message_id=?", (organization["message_id"],))
    assert audience["resolution_status"] == "partial"
    assert audience["failure_reason"] == "some_recipients_unavailable"

    mixed = _send(
        economy, sender, {"kind": "direct", "agent_ids": [recipient, third]}, tick=3)
    CommunicationDelivery(economy.store, economy.config).deliver_due(4)
    assert economy.store.scalar(
        "SELECT status FROM comm_messages WHERE id=?", (mixed["message_id"],)) == "partial"


def test_delivery_can_resume_message_with_a_late_queued_audience(economy):
    _, sender, recipient, third = _world(economy)
    result = _direct(economy, sender, recipient)
    inserted = False

    def add_late_audience(boundary, context):
        nonlocal inserted
        if boundary == "after_audience" and not inserted:
            inserted = True
            economy.store.insert(
                "comm_audiences", message_id=context["message_id"],
                audience_key=f"agent:{third}", audience_kind="agent",
                audience_agent_id=third, organization_kind=None, organization_id=None,
                resolved_tick=None, resolution_status="queued",
                resolved_recipient_count=0, membership_snapshot_hash=None,
                failure_reason=None)
            economy.store.update("agents", third, alive=0, died_tick=2)

    first = CommunicationDelivery(
        economy.store, economy.config, fault_hook=add_late_audience).deliver_due(2)
    assert first["delivered"] == 1
    assert economy.store.scalar(
        "SELECT status FROM comm_messages WHERE id=?", (result["message_id"],)) == "queued"
    second = CommunicationDelivery(economy.store, economy.config).deliver_due(2)
    assert second["undeliverable"] == 1
    assert economy.store.scalar(
        "SELECT status FROM comm_messages WHERE id=?", (result["message_id"],)) == "partial"


def test_delivery_private_methods_are_idempotent_and_handle_stale_work(economy):
    _, sender, recipient, _ = _world(economy)
    result = _direct(economy, sender, recipient)
    delivery = CommunicationDelivery(economy.store, economy.config)
    assert delivery._deliver_message(999999, 2) == {
        "delivered": 0, "undeliverable": 0, "published": 0}
    delivery.deliver_due(2)
    assert delivery._deliver_message(result["message_id"], 2) == {
        "delivered": 0, "undeliverable": 0, "published": 0}
    message = economy.store.query_one(
        "SELECT m.*,t.subject FROM comm_messages m JOIN comm_threads t ON t.id=m.thread_id "
        "WHERE m.id=?", (result["message_id"],))
    audience = economy.store.query_one(
        "SELECT * FROM comm_audiences WHERE message_id=?", (result["message_id"],))
    assert delivery._deliver_recipient(
        message, audience["id"], recipient, 2, "direct_delivery", None) == "delivered"


@pytest.mark.parametrize("changed", ["message_id", "audience_id", "recipient_agent_id"])
def test_delivery_dedupe_collision_fails_closed(economy, monkeypatch, changed):
    _, sender, recipient, _ = _world(economy)
    result = _direct(economy, sender, recipient)
    delivery = CommunicationDelivery(economy.store, economy.config)
    message = economy.store.query_one(
        "SELECT m.*,t.subject FROM comm_messages m JOIN comm_threads t ON t.id=m.thread_id "
        "WHERE m.id=?", (result["message_id"],))
    audience = economy.store.query_one(
        "SELECT * FROM comm_audiences WHERE message_id=?", (result["message_id"],))
    existing = {
        "message_id": int(result["message_id"]),
        "audience_id": int(audience["id"]),
        "recipient_agent_id": int(recipient),
        "delivery_status": "delivered",
    }
    existing[changed] += 1000
    original = economy.store.query_one

    def query_one(sql, params=()):
        if sql.startswith("SELECT * FROM comm_deliveries WHERE dedupe_key"):
            return existing
        return original(sql, params)

    monkeypatch.setattr(economy.store, "query_one", query_one)
    with pytest.raises(RuntimeError, match="dedupe identity mismatch"):
        delivery._deliver_recipient(
            message, audience["id"], recipient, 2, "direct_delivery", None)


def test_delivery_records_recipient_missing_fail_closed_path(economy, monkeypatch):
    _, sender, recipient, _ = _world(economy)
    result = _direct(economy, sender, recipient)
    delivery = CommunicationDelivery(economy.store, economy.config)
    message = economy.store.query_one(
        "SELECT m.*,t.subject FROM comm_messages m JOIN comm_threads t ON t.id=m.thread_id "
        "WHERE m.id=?", (result["message_id"],))
    audience = economy.store.query_one(
        "SELECT * FROM comm_audiences WHERE message_id=?", (result["message_id"],))
    original = economy.store.query_one

    def query_one(sql, params=()):
        if sql.startswith("SELECT id,name,alive FROM agents"):
            return None
        return original(sql, params)

    monkeypatch.setattr(economy.store, "query_one", query_one)
    assert delivery._deliver_recipient(
        message, audience["id"], recipient, 2, "direct_delivery", None) == "undeliverable"
    assert economy.store.scalar(
        "SELECT failure_reason FROM comm_deliveries WHERE message_id=?",
        (result["message_id"],)) == "recipient_missing"


def test_organization_with_no_members_is_resolved_deterministically(economy):
    _, sender, _, _ = _world(economy)
    firm_id = economy.store.insert(
        "firms", name="Empty", sector="goods", founder_agent_id=sender,
        status="private", product_json="{}", founded_tick=0)
    economy.store.update("agents", sender, alive=0, died_tick=2)
    # Bypass the sender-alive command rule only after the message has been queued.
    economy.store.update("agents", sender, alive=1, died_tick=None)
    result = _send(
        economy, sender,
        {"kind": "organization", "organization_kind": "firm", "organization_id": firm_id})
    economy.store.update("agents", sender, alive=0, died_tick=2)
    outcome = CommunicationDelivery(economy.store, economy.config).deliver_due(2)
    assert outcome["delivered"] == 0
    audience = economy.store.query_one(
        "SELECT * FROM comm_audiences WHERE message_id=?", (result["message_id"],))
    assert audience["failure_reason"] == "organization_has_no_active_members"


def test_service_rejects_actor_audience_reply_forward_and_disclosure_failures(
        economy, monkeypatch):
    _, sender, recipient, third = _world(economy)
    service = CommunicationService(economy.store, economy.config)
    command = {
        "audience": {"kind": "direct", "agent_ids": [recipient]},
        "subject": "s", "body": "b",
    }
    with pytest.raises(CommunicationRejected, match="actor_not_found"):
        service.send(1, 999999, command, phase="EXECUTION")
    economy.store.update("agents", sender, alive=0, died_tick=1)
    with pytest.raises(CommunicationRejected, match="actor_not_alive"):
        service.send(1, sender, command, phase="EXECUTION")
    economy.store.update("agents", sender, alive=1, died_tick=None)

    for audience in (
        {"kind": "direct", "agent_ids": []},
        {"kind": "direct", "agent_ids": [recipient, recipient]},
        {"kind": "direct", "agent_ids": list(range(1, 22))},
        {"kind": "direct", "agent_ids": [999999]},
        {"kind": "unknown"},
    ):
        with pytest.raises(CommunicationRejected):
            service._validate_audience(audience, sender)
    with pytest.raises(CommunicationRejected, match="invalid_audience"):
        service.send(
            1, sender, {"audience": {"kind": "organization"}, "subject": "s", "body": "b"},
            phase="EXECUTION")
    with pytest.raises(CommunicationRejected, match="invalid_audience"):
        service.send(
            1, sender,
            {"audience": {"kind": "organization", "organization_kind": "firm",
                          "organization_id": 999999}, "subject": "s", "body": "b"},
            phase="EXECUTION")

    with pytest.raises(CommunicationRejected, match="message_not_found"):
        service.reply(1, sender, {"parent_message_id": 999999, "body": "b"}, phase="EXECUTION")
    with pytest.raises(CommunicationRejected, match="message_not_found"):
        service.forward(
            1, sender,
            {"source_message_id": 999999,
             "audience": {"kind": "direct", "agent_ids": [recipient]}}, phase="EXECUTION")

    original = _direct(economy, sender, recipient)
    from communications.delivery import CommunicationDelivery
    CommunicationDelivery(economy.store, economy.config).deliver_due(2)
    original_query = economy.store.query_one

    def missing_recipient(sql, params=()):
        if sql.startswith("SELECT id FROM agents WHERE id=") and params == (sender,):
            return None
        return original_query(sql, params)

    monkeypatch.setattr(economy.store, "query_one", missing_recipient)
    with pytest.raises(CommunicationRejected, match="recipient_not_found"):
        service.reply(
            2, recipient, {"parent_message_id": original["message_id"], "body": "b"},
            phase="EXECUTION")
    monkeypatch.setattr(economy.store, "query_one", original_query)

    event_id = economy.store.log_event(2, "court_order", {})
    disclosure = dict(
        tick=2, message_id=original["message_id"], case_id=4,
        grantee_agent_id=third, authority_kind="court_order",
        authority_record_id="order", authority_event_id=event_id,
        authority_ref={"case_id": 4}, verified_case_id=4)
    for changes, match in (
        ({"authority_kind": "invalid"}, "invalid_disclosure_authority"),
        ({"message_id": 999999}, "message_not_found"),
        ({"grantee_agent_id": 999999}, "recipient_not_found"),
        ({"authority_event_id": 999999}, "authority_event_not_found"),
    ):
        with pytest.raises(CommunicationRejected, match=match):
            service.grant_disclosure(**{**disclosure, **changes})
    grant_id = service.grant_disclosure(**disclosure)
    assert service.grant_disclosure(**disclosure) == grant_id

    def mismatched_authority(sql, params=()):
        if sql.startswith("SELECT id,case_id FROM comm_disclosure_authorities"):
            return {"id": 1, "case_id": 99}
        return original_query(sql, params)

    monkeypatch.setattr(economy.store, "query_one", mismatched_authority)
    with pytest.raises(CommunicationRejected, match="disclosure_case_mismatch"):
        service.grant_disclosure(**{**disclosure, "authority_record_id": "other"})


def test_safe_diagnostics_cover_private_and_ordinary_shapes():
    assert safe_command_metadata("buy", {"units": 2}) == {"units": 2}
    reply = safe_command_metadata(
        "reply_message", {"parent_message_id": 3, "body": "secret"})
    assert reply["parent_message_id"] == 3
    assert "secret" not in json.dumps(reply)
    forwarded = safe_command_metadata(
        "forward_message", {"source_message_id": 4, "note": "secret"})
    assert forwarded["source_message_id"] == 4
    organization = safe_command_metadata(
        "send_message",
        {"audience": {"kind": "organization", "organization_kind": "firm",
                      "organization_id": 7}, "subject": None, "body": "secret"})
    assert organization["organization_kind"] == "firm"
    assert safe_command_metadata("send_message", {"audience": "invalid"})[
        "direct_recipient_count"] == 0

    marker = object()
    assert safe_action_for_diagnostic(marker) is marker
    private = safe_action_for_diagnostic({"type": "wait", "body": "secret"})
    assert private["type"] == "wait" and "secret" not in json.dumps(private)
    ordinary = safe_action_for_diagnostic({
        "type": "buy", "units": 2, "model_call_id": 9, "rationale_summary": "private"})
    assert ordinary == {"type": "buy", "units": 2}


def test_policy_deny_by_default_and_audit_failure_paths(economy, monkeypatch):
    _, sender, recipient, third = _world(economy)
    result = _direct(economy, sender, recipient, tick=2)
    policy = CommunicationPolicy(economy.store)
    ordinary = Principal("ordinary")
    assert not policy.can_read_field(ordinary, result["message_id"], "invalid", 2).allowed
    assert not policy.can_read_field(ordinary, result["message_id"], MessageField.BODY, -1).allowed
    assert not policy.can_read_field(ordinary, 999999, MessageField.BODY, 2).allowed
    assert not policy.can_read_field(ordinary, result["message_id"], MessageField.BODY, 1).allowed
    assert policy.can_read_field(
        Principal("sender", agent_id=sender), result["message_id"], MessageField.BODY, 2
    ).basis is AccessBasis.SENDER
    assert not policy.can_read_field(
        Principal("case", agent_id=third, disclosure_case_id=77),
        result["message_id"], MessageField.BODY, 2).allowed
    assert policy.authorized_message(ordinary, result["message_id"], as_of_tick=2) is None

    for audit in (lambda *_args: False, lambda *_args: (_ for _ in ()).throw(RuntimeError("audit"))):
        denied = CommunicationPolicy(economy.store, truth_audit=audit).can_read_field(
            Principal("operator", operator_truth=True), result["message_id"],
            MessageField.BODY, 2)
        assert not denied.allowed

    sender_principal = Principal("sender", agent_id=sender)
    monkeypatch.setattr(policy, "can_read_field", lambda *_args, **_kwargs: AccessDecision(True))
    assert policy.authorized_message(
        sender_principal, result["message_id"], as_of_tick=2)["access_basis"] is None
    monkeypatch.setattr(policy, "can_read_field", lambda *_args, **_kwargs: AccessDecision(True, AccessBasis.SENDER))
    original = economy.store.query_one

    def missing_after_authorization(sql, params=()):
        if sql.startswith("SELECT m.id,m.thread_id"):
            return None
        return original(sql, params)

    monkeypatch.setattr(economy.store, "query_one", missing_after_authorization)
    assert policy.authorized_message(
        sender_principal, result["message_id"], as_of_tick=2) is None


def test_inbox_projection_bounds_authorization_body_and_organization(economy, monkeypatch):
    _, sender, recipient, _ = _world(economy)
    economy.config["communications"] = {
        "prompt_message_limit": 999,
        "prompt_body_char_limit": 1,
        "prompt_unread_age_ticks": 999,
        "prompt_contact_limit": 999,
    }
    projection = AgentKnowledgeProjection(economy.store, economy.config)
    assert (projection.max_messages, projection.max_body_chars, projection.max_unread_age,
            projection.max_contacts) == (20, 500, 365, 20)
    lower = AgentKnowledgeProjection(economy.store, {"communications": {
        "prompt_message_limit": 0, "prompt_body_char_limit": 0,
        "prompt_unread_age_ticks": 0, "prompt_contact_limit": 0}})
    assert (lower.max_messages, lower.max_body_chars, lower.max_unread_age,
            lower.max_contacts) == (1, 500, 1, 1)
    assert lower.build(recipient, 1)["read_context_key"] is None

    _direct(economy, sender, recipient, body="a" * 400)
    _direct(economy, sender, recipient, subject="Second", body="b" * 400)
    CommunicationDelivery(economy.store, economy.config).deliver_due(2)
    bounded = projection.build(recipient, 2)
    assert len(bounded["items"]) == 1

    denied_projection = AgentKnowledgeProjection(economy.store, economy.config)
    monkeypatch.setattr(
        denied_projection.policy, "can_read_field",
        lambda *_args, **_kwargs: AccessDecision(False))
    assert denied_projection.build(recipient, 2)["items"] == []

    firm_id = economy.store.insert(
        "firms", name="Firm", sector="goods", founder_agent_id=sender,
        status="private", product_json="{}", founded_tick=0)
    economy.store.insert(
        "employments", firm_id=firm_id, agent_id=recipient, title="staff", wage_cents=1,
        start_tick=0, end_tick=None, status="active", pay_interval_ticks=30,
        next_pay_tick=30)
    _send(
        economy, sender,
        {"kind": "organization", "organization_kind": "firm", "organization_id": firm_id},
        tick=3)
    CommunicationDelivery(economy.store, economy.config).deliver_due(4)
    item = next(
        candidate for candidate in AgentKnowledgeProjection(
            economy.store, {"communications": {"prompt_unread_age_ticks": 1}}
        ).build(recipient, 4)["items"]
        if candidate["audience"]["kind"] == "organization")
    assert item["audience"] == {
        "kind": "organization", "organization_kind": "firm", "organization_id": firm_id}


def test_contact_directory_relationships_visibility_and_limit(economy):
    _, sender, recipient, third = _world(economy)
    firm_id = economy.store.insert(
        "firms", name="Firm", sector="goods", founder_agent_id=sender,
        status="private", product_json="{}", founded_tick=0)
    economy.store.update("agents", recipient, employer_id=firm_id)
    economy.store.update("agents", third, employer_id=firm_id)
    economy.store.insert("social_ties", agent_a=recipient, agent_b=sender, weight=0.8)
    team_member, _ = make_agent(economy, 1, name="Team", arrived_tick=0)
    economy.store.update("agents", team_member, employer_id=firm_id)
    founded_id = economy.store.insert(
        "firms", name="Founded", sector="goods", founder_agent_id=recipient,
        status="private", product_json="{}", founded_tick=0)
    founded_member, _ = make_agent(economy, 1, name="Founded member", arrived_tick=0)
    economy.store.update("agents", founded_member, employer_id=founded_id)
    future, _ = make_agent(economy, 1, name="Future", arrived_tick=10)
    economy.store.insert("social_ties", agent_a=recipient, agent_b=future, weight=1.0)

    projection = AgentKnowledgeProjection(
        economy.store, {"communications": {"prompt_contact_limit": 3}})
    directory = projection.contact_directory(
        recipient, 2,
        [{"sender_agent_id": recipient}, {"sender_agent_id": sender}])
    assert len(directory) == 3
    by_id = {item["agent_id"]: item for item in directory}
    assert by_id[sender]["relationships"] == [
        "firm_founder", "recent_correspondent", "social_tie"]
    assert future not in by_id
    assert any(
        "colleague" in item["relationships"] or "team_member" in item["relationships"]
        for item in directory)

    isolated, _ = make_agent(economy, 1, name="Isolated")
    economy.store.update("agents", isolated, employer_id=999999)
    assert projection.contact_directory(isolated, 2) == []


def test_read_context_rejects_conflicts_and_partial_persistence(economy):
    _, sender, recipient, third = _world(economy)
    first = _direct(economy, sender, recipient)
    second = _direct(economy, sender, third)
    CommunicationDelivery(economy.store, economy.config).deliver_due(2)
    projection = AgentKnowledgeProjection(economy.store, economy.config)
    projection.persist_read_context(recipient, 2, {"read_context_key": None, "sources": []})
    projection.persist_read_context(recipient, 2, {"read_context_key": "key", "sources": []})

    recipient_delivery = economy.store.query_one(
        "SELECT id FROM comm_deliveries WHERE message_id=?", (first["message_id"],))["id"]
    economy.store.execute(
        "UPDATE comm_deliveries SET read_tick=1,read_context_key='other' WHERE id=?",
        (recipient_delivery,))
    with pytest.raises(RuntimeError, match="identity conflict"):
        projection.persist_read_context(recipient, 2, {
            "read_context_key": "new",
            "sources": [{"delivery_id": recipient_delivery}]})

    other_delivery = economy.store.query_one(
        "SELECT id FROM comm_deliveries WHERE message_id=?", (second["message_id"],))["id"]
    with pytest.raises(RuntimeError, match="did not persist atomically"):
        projection.persist_read_context(recipient, 2, {
            "read_context_key": "new",
            "sources": [{"delivery_id": other_delivery}]})


def test_public_summary_and_blank_command_validators(economy):
    _, sender, recipient, _ = _world(economy)
    assert public_communication_summary(economy.store, as_of_tick=0) == {
        "total": 0, "published": 0, "private_total": 0}
    _direct(economy, sender, recipient)
    public = _send(economy, sender, {"kind": "public"}, subject="Public")
    CommunicationDelivery(economy.store, economy.config).deliver_due(2)
    assert public["ok"]
    assert public_communication_summary(economy.store, as_of_tick=2) == {
        "total": 2, "published": 1, "private_total": 1}

    registry = default_registry({"send_message", "reply_message"})
    invalid_payloads = (
        ("send_message", {"audience": {"kind": "public"}, "subject": " ", "body": "b"}),
        ("send_message", {"audience": {"kind": "public"}, "subject": "s", "body": " "}),
        ("reply_message", {"parent_message_id": 1, "body": " "}),
        ("send_message", {"audience": {"kind": "direct", "agent_ids": "bad"},
                          "subject": "s", "body": "b"}),
        ("send_message", {"audience": {"kind": "direct", "agent_ids": ["bad"]},
                          "subject": "s", "body": "b"}),
        ("send_message", {"audience": {"kind": "direct", "agent_ids": [0]},
                          "subject": "s", "body": "b"}),
    )
    for command_type, payload in invalid_payloads:
        with pytest.raises(CommandValidationError):
            registry.validate(command_type, payload, 8)

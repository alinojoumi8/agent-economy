"""Deny-by-default field authorization for communication data."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable


class AccessBasis(str, Enum):
    SENDER = "sender"
    DIRECT_DELIVERY = "direct_delivery"
    ORGANIZATION_AT_DELIVERY = "organization_at_delivery"
    PUBLIC_RELEASE = "public_release"
    LEGAL_DISCLOSURE = "legal_disclosure"
    OPERATOR_TRUTH = "operator_truth"


class MessageField(str, Enum):
    EXISTENCE = "existence"
    SUBJECT = "subject"
    BODY = "body"
    PARTICIPANTS = "participants"
    THREAD_ENTRY = "thread_entry"
    MESSAGE_URL = "message_url"


@dataclass(frozen=True)
class Principal:
    principal_id: str
    agent_id: int | None = None
    operator_truth: bool = False
    disclosure_case_id: int | None = None


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    basis: AccessBasis | None = None


class CommunicationPolicy:
    """The sole authorization entry point for message-specific fields."""

    def __init__(
        self,
        store,
        *,
        truth_audit: Callable[[Principal, int, MessageField, int], bool] | None = None,
    ):
        self.store = store
        self.truth_audit = truth_audit

    def can_read_field(
        self,
        principal: Principal,
        message_id: int,
        field: MessageField | str,
        as_of_tick: int,
    ) -> AccessDecision:
        try:
            field = MessageField(field)
        except ValueError:
            return AccessDecision(False)
        if as_of_tick < 0:
            return AccessDecision(False)
        message = self.store.query_one(
            "SELECT id,sender_agent_id,created_tick FROM comm_messages WHERE id=?",
            (int(message_id),),
        )
        if message is None or int(message["created_tick"]) > int(as_of_tick):
            return AccessDecision(False)
        agent_id = principal.agent_id
        if agent_id is not None and int(message["sender_agent_id"]) == int(agent_id):
            return AccessDecision(True, AccessBasis.SENDER)
        if agent_id is not None:
            delivery = self.store.query_one(
                "SELECT grant_basis FROM comm_deliveries WHERE message_id=? "
                "AND recipient_agent_id=? AND delivery_status='delivered' "
                "AND delivery_tick<=?",
                (int(message_id), int(agent_id), int(as_of_tick)),
            )
            if delivery is not None:
                return AccessDecision(True, AccessBasis(str(delivery["grant_basis"])))
            if principal.disclosure_case_id is not None:
                disclosed = self.store.query_one(
                    "SELECT d.id FROM comm_disclosures d "
                    "JOIN comm_disclosure_authorities a ON a.id=d.authority_id "
                    "WHERE d.message_id=? AND d.grantee_agent_id=? AND d.case_id=? "
                    "AND a.case_id=d.case_id AND d.granted_tick<=?",
                    (
                        int(message_id), int(agent_id), int(principal.disclosure_case_id),
                        int(as_of_tick),
                    ),
                )
                if disclosed is not None:
                    return AccessDecision(True, AccessBasis.LEGAL_DISCLOSURE)
        published = self.store.query_one(
            "SELECT id FROM comm_audiences WHERE message_id=? "
            "AND audience_kind='public' AND resolution_status='published' "
            "AND resolved_tick<=?",
            (int(message_id), int(as_of_tick)),
        )
        if published is not None:
            return AccessDecision(True, AccessBasis.PUBLIC_RELEASE)
        if principal.operator_truth and self.truth_audit is not None:
            try:
                audited = bool(self.truth_audit(principal, int(message_id), field, int(as_of_tick)))
            except Exception:
                audited = False
            if audited:
                return AccessDecision(True, AccessBasis.OPERATOR_TRUTH)
        return AccessDecision(False)

    def authorized_message(
        self,
        principal: Principal,
        message_id: int,
        *,
        as_of_tick: int,
        include_body: bool = True,
    ) -> dict | None:
        required_field = MessageField.BODY if include_body else MessageField.EXISTENCE
        decision = self.can_read_field(principal, message_id, required_field, as_of_tick)
        if not decision.allowed:
            return None
        row = self.store.query_one(
            "SELECT m.id,m.thread_id,m.parent_message_id,m.forwarded_from_id,"
            "m.sender_agent_id,m.created_tick,m.deliver_at_tick,m.visibility,m.status,"
            "t.subject" + (",m.body_text" if include_body else "") + " "
            "FROM comm_messages m JOIN comm_threads t ON t.id=m.thread_id WHERE m.id=?",
            (int(message_id),),
        )
        if row is None:
            return None
        result = dict(row)
        result["access_basis"] = decision.basis.value if decision.basis else None
        return result

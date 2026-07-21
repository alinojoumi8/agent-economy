"""Exactly-once Semantics 8 inbox delivery.

One due message is one savepoint: audience resolution, immutable outcomes,
authorized memory creation, safe events, and causal provenance either all commit
or all roll back. Retrying therefore selects the same stable work without fan-out.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable

from agents.memory import Memory
from causal import CausalLinkService

from .membership import OrganizationMembershipResolver


def _hash_identity(value: dict) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class CommunicationDelivery:
    def __init__(
        self,
        store,
        config: dict | None = None,
        *,
        fault_hook: Callable[[str, dict], None] | None = None,
    ):
        self.store = store
        self.config = config or {}
        self.membership = OrganizationMembershipResolver(store, self.config)
        self.memory = Memory(store, self.config)
        self.causal = CausalLinkService(store)
        self.fault_hook = fault_hook

    def deliver_due(self, tick: int) -> dict:
        due = self.store.query(
            "SELECT id FROM comm_messages WHERE status='queued' AND deliver_at_tick<=? "
            "ORDER BY deliver_at_tick,created_tick,id",
            (int(tick),),
        )
        summary = {
            "messages": 0,
            "delivered": 0,
            "undeliverable": 0,
            "published": 0,
        }
        for row in due:
            message_id = int(row["id"])
            self._fault("before_message", message_id=message_id, tick=tick)
            with self.store.savepoint(f"comm_delivery_{tick}_{message_id}"):
                outcome = self._deliver_message(message_id, tick)
            self._fault("after_message_commit", message_id=message_id, tick=tick)
            summary["messages"] += 1
            for key in ("delivered", "undeliverable", "published"):
                summary[key] += int(outcome[key])
        domains = json.dumps(["communications", "causal"], separators=(",", ":"))
        self.store.execute(
            "INSERT OR IGNORE INTO projection_commits (tick,phase,domains_json) "
            "VALUES (?,'INBOX_DELIVERY',?)",
            (int(tick), domains),
        )
        return summary

    def _deliver_message(self, message_id: int, tick: int) -> dict:
        message = self.store.query_one(
            "SELECT m.*,t.subject FROM comm_messages m "
            "JOIN comm_threads t ON t.id=m.thread_id WHERE m.id=?",
            (message_id,),
        )
        if message is None or message["status"] != "queued":
            return {"delivered": 0, "undeliverable": 0, "published": 0}
        audiences = self.store.query(
            "SELECT * FROM comm_audiences WHERE message_id=? "
            "AND resolution_status='queued' ORDER BY audience_key,id",
            (message_id,),
        )
        delivered = 0
        undeliverable = 0
        published = 0
        publication_event_id = None
        for audience in audiences:
            audience_id = int(audience["id"])
            kind = str(audience["audience_kind"])
            self._fault(
                "before_audience", message_id=message_id, audience_id=audience_id, tick=tick)
            if kind == "public":
                publication_event_id = self.store.log_event(
                    tick,
                    "communication_published",
                    {
                        "message_id": message_id,
                        "thread_id": int(message["thread_id"]),
                        "sender_agent_id": int(message["sender_agent_id"]),
                    },
                    phase="INBOX_DELIVERY",
                    subject_type="message",
                    subject_id=message_id,
                    importance=1.0,
                )
                self.store.update(
                    "comm_audiences",
                    audience_id,
                    resolved_tick=tick,
                    resolution_status="published",
                    resolved_recipient_count=0,
                    membership_snapshot_hash=None,
                    failure_reason=None,
                )
                published += 1
                self._fault(
                    "after_publication", message_id=message_id,
                    audience_id=audience_id, tick=tick)
                continue
            if kind == "agent":
                recipients = (int(audience["audience_agent_id"]),)
                grant_basis = "direct_delivery"
                membership_json = None
                snapshot_hash = None
            else:
                snapshot = self.membership.snapshot(
                    str(audience["organization_kind"]),
                    int(audience["organization_id"]),
                    tick,
                )
                recipients = snapshot.member_ids
                grant_basis = "organization_at_delivery"
                membership_json = snapshot.reference_json()
                snapshot_hash = snapshot.snapshot_hash
            local_delivered = 0
            local_undeliverable = 0
            for recipient_id in sorted(recipients):
                status = self._deliver_recipient(
                    message,
                    audience_id,
                    recipient_id,
                    tick,
                    grant_basis,
                    membership_json,
                )
                if status == "delivered":
                    local_delivered += 1
                else:
                    local_undeliverable += 1
            delivered += local_delivered
            undeliverable += local_undeliverable
            if local_delivered and local_undeliverable:
                resolution_status = "partial"
                failure_reason = "some_recipients_unavailable"
            elif local_delivered:
                resolution_status = "delivered"
                failure_reason = None
            else:
                resolution_status = "undeliverable"
                failure_reason = (
                    "organization_has_no_active_members" if kind == "organization"
                    and not recipients else "recipient_unavailable")
            self.store.update(
                "comm_audiences",
                audience_id,
                resolved_tick=tick,
                resolution_status=resolution_status,
                resolved_recipient_count=len(recipients),
                membership_snapshot_hash=snapshot_hash,
                failure_reason=failure_reason,
            )
            self._fault(
                "after_audience", message_id=message_id,
                audience_id=audience_id, tick=tick)

        resolved = self.store.query(
            "SELECT resolution_status,resolved_recipient_count FROM comm_audiences "
            "WHERE message_id=? ORDER BY audience_key",
            (message_id,),
        )
        statuses = [str(row["resolution_status"]) for row in resolved]
        if statuses and all(status == "published" for status in statuses):
            message_status = "published"
        elif statuses and all(status == "delivered" for status in statuses):
            message_status = "delivered"
        elif statuses and all(status == "undeliverable" for status in statuses):
            message_status = "undeliverable"
        elif any(status == "queued" for status in statuses):
            message_status = "queued"
        else:
            message_status = "partial"
        self.store.update(
            "comm_messages",
            message_id,
            status=message_status,
            publication_event_id=publication_event_id,
        )
        self.store.log_event(
            tick,
            "communication_delivery_resolved",
            {
                "message_id": message_id,
                "status": message_status,
                "delivered_count": delivered,
                "undeliverable_count": undeliverable,
                "published": bool(published),
            },
            phase="INBOX_DELIVERY",
            subject_type="message",
            subject_id=message_id,
            importance=0.5,
        )
        self._fault("after_message_resolution", message_id=message_id, tick=tick)
        return {
            "delivered": delivered,
            "undeliverable": undeliverable,
            "published": published,
        }

    def _deliver_recipient(
        self,
        message,
        audience_id: int,
        recipient_id: int,
        tick: int,
        grant_basis: str,
        membership_json: str | None,
    ) -> str:
        message_id = int(message["id"])
        dedupe_key = _hash_identity({
            "message_id": message_id,
            "audience_id": int(audience_id),
            "recipient_agent_id": int(recipient_id),
            "delivery_tick": int(tick),
        })
        existing = self.store.query_one(
            "SELECT * FROM comm_deliveries WHERE dedupe_key=?", (dedupe_key,))
        if existing is not None:
            if (
                int(existing["message_id"]) != message_id
                or int(existing["audience_id"]) != int(audience_id)
                or int(existing["recipient_agent_id"]) != int(recipient_id)
            ):
                raise RuntimeError("delivery dedupe identity mismatch")
            return str(existing["delivery_status"])
        recipient = self.store.query_one(
            "SELECT id,name,alive FROM agents WHERE id=?", (recipient_id,))
        if recipient is None or not bool(recipient["alive"]):
            self.store.insert(
                "comm_deliveries",
                dedupe_key=dedupe_key,
                message_id=message_id,
                audience_id=audience_id,
                recipient_agent_id=recipient_id,
                delivery_tick=tick,
                grant_basis=grant_basis,
                membership_ref_json=membership_json,
                memory_id=None,
                read_tick=None,
                read_context_key=None,
                delivery_status="undeliverable",
                failure_reason="recipient_not_alive" if recipient is not None else "recipient_missing",
            )
            return "undeliverable"
        sender_name = self.store.scalar(
            "SELECT name FROM agents WHERE id=?", (int(message["sender_agent_id"]),),
            default=f"Agent {int(message['sender_agent_id'])}",
        )
        memory_text = (
            f"Message from {sender_name} — {message['subject']}:\n"
            f"{message['body_text']}"
        )
        memory_id = self.memory.observe(
            recipient_id,
            tick,
            memory_text,
            importance=2.0,
            entities=[
                f"message:{message_id}",
                f"thread:{int(message['thread_id'])}",
                f"agent:{int(message['sender_agent_id'])}",
            ],
            kind="communication",
        )
        self._fault(
            "after_memory", message_id=message_id,
            audience_id=audience_id, recipient_id=recipient_id, tick=tick)
        self.store.insert(
            "comm_deliveries",
            dedupe_key=dedupe_key,
            message_id=message_id,
            audience_id=audience_id,
            recipient_agent_id=recipient_id,
            delivery_tick=tick,
            grant_basis=grant_basis,
            membership_ref_json=membership_json,
            memory_id=memory_id,
            read_tick=None,
            read_context_key=None,
            delivery_status="delivered",
            failure_reason=None,
        )
        self._fault(
            "after_delivery", message_id=message_id,
            audience_id=audience_id, recipient_id=recipient_id, tick=tick)
        self.causal.create(
            "message",
            message_id,
            "memory",
            memory_id,
            "observed",
            "engine",
            created_tick=tick,
            provenance={
                "delivery_dedupe_key": dedupe_key,
                "grant_basis": grant_basis,
            },
        )
        self._fault(
            "after_causal", message_id=message_id,
            audience_id=audience_id, recipient_id=recipient_id, tick=tick)
        return "delivered"

    def _fault(self, boundary: str, **context) -> None:
        if self.fault_hook is not None:
            self.fault_hook(boundary, dict(context))

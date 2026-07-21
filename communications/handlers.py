"""Transactional domain handlers for send, reply, forward, and disclosure."""
from __future__ import annotations

import hashlib
import json

from causal import CausalLinkService

from .membership import OrganizationMembershipResolver, OrganizationReferenceError
from .policy import CommunicationPolicy, MessageField, Principal


class CommunicationRejected(ValueError):
    """Expected safe-code rejection from a communication domain rule."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _digest(parts: dict) -> str:
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class CommunicationService:
    """Only ordinary mutation path for Semantics 8 communication commands."""

    def __init__(self, store, config: dict | None = None):
        self.store = store
        self.config = config or {}
        self.membership = OrganizationMembershipResolver(store, self.config)
        self.policy = CommunicationPolicy(store)
        self.causal = CausalLinkService(store)

    def send(self, tick: int, sender_agent_id: int, command: dict, *, phase: str) -> dict:
        try:
            self._enforce_quota(tick, sender_agent_id)
            audience = dict(command["audience"])
            audience_rows, visibility, org_ref = self._validate_audience(
                audience, sender_agent_id)
            return self._create_message(
                tick=tick,
                sender_agent_id=sender_agent_id,
                subject=str(command["subject"]),
                body=str(command["body"]),
                visibility=visibility,
                audience_rows=audience_rows,
                organization_ref=org_ref,
                model_call_id=command.get("model_call_id"),
                phase=phase,
                command_type="send_message",
            )
        except (KeyError, TypeError, OrganizationReferenceError) as exc:
            raise CommunicationRejected("invalid_audience") from exc

    def reply(self, tick: int, sender_agent_id: int, command: dict, *, phase: str) -> dict:
        self._enforce_quota(tick, sender_agent_id)
        parent_id = int(command["parent_message_id"])
        parent = self.policy.authorized_message(
            Principal(f"agent:{sender_agent_id}", agent_id=sender_agent_id),
            parent_id,
            as_of_tick=tick,
            include_body=False,
        )
        if parent is None:
            raise CommunicationRejected("message_not_found")
        recipient_id = int(parent["sender_agent_id"])
        recipient = self.store.query_one("SELECT id FROM agents WHERE id=?", (recipient_id,))
        if recipient is None:
            raise CommunicationRejected("recipient_not_found")
        event_id = self._safe_created_event(
            tick, sender_agent_id, "reply_message", "direct", 1, phase)
        message_id = self.store.insert(
            "comm_messages",
            thread_id=int(parent["thread_id"]),
            parent_message_id=parent_id,
            forwarded_from_id=None,
            sender_agent_id=sender_agent_id,
            created_tick=tick,
            deliver_at_tick=tick + 1,
            visibility="participants",
            body_text=str(command["body"]),
            model_call_id=command.get("model_call_id"),
            created_event_id=event_id,
            publication_event_id=None,
            status="queued",
        )
        self._insert_audience(message_id, {
            "audience_kind": "agent",
            "audience_key": f"agent:{recipient_id}",
            "audience_agent_id": recipient_id,
        })
        return {
            "ok": True,
            "thread_id": int(parent["thread_id"]),
            "message_id": message_id,
            "created_event_id": event_id,
            "deliver_at_tick": tick + 1,
        }

    def forward(self, tick: int, sender_agent_id: int, command: dict, *, phase: str) -> dict:
        self._enforce_quota(tick, sender_agent_id)
        source_id = int(command["source_message_id"])
        source = self.policy.authorized_message(
            Principal(f"agent:{sender_agent_id}", agent_id=sender_agent_id),
            source_id,
            as_of_tick=tick,
            include_body=True,
        )
        if source is None:
            raise CommunicationRejected("message_not_found")
        audience_rows, visibility, org_ref = self._validate_audience(
            dict(command["audience"]), sender_agent_id)
        subject = f"Fwd: {source['subject']}"[:160]
        note = str(command.get("note", ""))
        quote = (
            "----- Forwarded message -----\n"
            f"From: agent:{int(source['sender_agent_id'])}\n"
            f"Subject: {source['subject']}\n\n"
            f"{source['body_text']}"
        )
        body = f"{note}\n\n{quote}" if note else quote
        if len(body) > 2000:
            raise CommunicationRejected("forward_body_too_long")
        result = self._create_message(
            tick=tick,
            sender_agent_id=sender_agent_id,
            subject=subject,
            body=body,
            visibility=visibility,
            audience_rows=audience_rows,
            organization_ref=org_ref,
            model_call_id=command.get("model_call_id"),
            phase=phase,
            command_type="forward_message",
            forwarded_from_id=source_id,
        )
        self.causal.create(
            "message",
            source_id,
            "message",
            result["message_id"],
            "cited",
            "actor_claim",
            actor_agent_id=sender_agent_id,
            method="forward_command",
            provenance={"command": "forward_message"},
        )
        return result

    def grant_disclosure(
        self,
        *,
        tick: int,
        message_id: int,
        case_id: int,
        grantee_agent_id: int,
        authority_kind: str,
        authority_record_id: str,
        authority_event_id: int,
        authority_ref: dict,
        verified_case_id: int,
    ) -> int:
        """Create a same-case immutable grant after a legal handler verifies authority."""
        if int(case_id) != int(verified_case_id):
            raise CommunicationRejected("disclosure_case_mismatch")
        if authority_kind not in {"court_order", "agreement"}:
            raise CommunicationRejected("invalid_disclosure_authority")
        if self.store.query_one("SELECT id FROM comm_messages WHERE id=?", (message_id,)) is None:
            raise CommunicationRejected("message_not_found")
        if self.store.query_one("SELECT id FROM agents WHERE id=?", (grantee_agent_id,)) is None:
            raise CommunicationRejected("recipient_not_found")
        if self.store.query_one("SELECT id FROM events WHERE id=?", (authority_event_id,)) is None:
            raise CommunicationRejected("authority_event_not_found")
        authority = self.store.query_one(
            "SELECT id,case_id FROM comm_disclosure_authorities WHERE "
            "case_id=? AND authority_kind=? AND authority_record_id=?",
            (case_id, authority_kind, str(authority_record_id)),
        )
        if authority is None:
            authority_id = self.store.insert(
                "comm_disclosure_authorities",
                case_id=case_id,
                authority_kind=authority_kind,
                authority_record_id=str(authority_record_id),
                authority_event_id=authority_event_id,
                authority_ref_json=json.dumps(authority_ref, sort_keys=True, separators=(",", ":")),
                created_tick=tick,
            )
        else:
            authority_id = int(authority["id"])
            if int(authority["case_id"]) != int(case_id):
                raise CommunicationRejected("disclosure_case_mismatch")
        dedupe_key = _digest({
            "message_id": int(message_id),
            "case_id": int(case_id),
            "grantee_agent_id": int(grantee_agent_id),
            "authority_id": authority_id,
        })
        self.store.execute(
            "INSERT OR IGNORE INTO comm_disclosures "
            "(dedupe_key,message_id,case_id,grantee_agent_id,granted_tick,authority_id) "
            "VALUES (?,?,?,?,?,?)",
            (dedupe_key, message_id, case_id, grantee_agent_id, tick, authority_id),
        )
        row = self.store.query_one(
            "SELECT id FROM comm_disclosures WHERE dedupe_key=?", (dedupe_key,))
        return int(row["id"])

    def _enforce_quota(self, tick: int, sender_agent_id: int) -> None:
        actor = self.store.query_one(
            "SELECT population_tier,alive FROM agents WHERE id=?", (sender_agent_id,))
        if actor is None:
            raise CommunicationRejected("actor_not_found")
        if not bool(actor["alive"]):
            raise CommunicationRejected("actor_not_alive")
        limit = 3 if str(actor["population_tier"] or "core") == "core" else 1
        used = int(self.store.scalar(
            "SELECT COUNT(*) FROM action_proposals WHERE tick=? AND actor_id=? "
            "AND action_type IN ('send_message','reply_message','forward_message') "
            "AND validation_status='accepted'",
            (tick, sender_agent_id),
            default=0,
        ))
        if used >= limit:
            raise CommunicationRejected("communication_quota_exceeded")

    def _validate_audience(self, audience: dict, sender_agent_id: int):
        kind = audience.get("kind")
        if kind == "direct":
            agent_ids = tuple(int(item) for item in audience.get("agent_ids", []))
            if not agent_ids or len(agent_ids) > 20 or len(set(agent_ids)) != len(agent_ids):
                raise CommunicationRejected("invalid_audience")
            placeholders = ",".join("?" for _ in agent_ids)
            existing = {
                int(row["id"]) for row in self.store.query(
                    f"SELECT id FROM agents WHERE id IN ({placeholders})", agent_ids)
            }
            if existing != set(agent_ids):
                raise CommunicationRejected("recipient_not_found")
            rows = [{
                "audience_kind": "agent",
                "audience_key": f"agent:{agent_id}",
                "audience_agent_id": agent_id,
            } for agent_id in sorted(agent_ids)]
            return rows, "participants", None
        if kind == "organization":
            organization_kind = str(audience["organization_kind"])
            organization_id = int(audience["organization_id"])
            self.membership.validate_reference(organization_kind, organization_id)
            row = {
                "audience_kind": "organization",
                "audience_key": f"organization:{organization_kind}:{organization_id}",
                "organization_kind": organization_kind,
                "organization_id": organization_id,
            }
            return [row], "organization", (organization_kind, organization_id)
        if kind == "public":
            return [{"audience_kind": "public", "audience_key": "public"}], "public", None
        raise CommunicationRejected("invalid_audience")

    def _create_message(
        self,
        *,
        tick: int,
        sender_agent_id: int,
        subject: str,
        body: str,
        visibility: str,
        audience_rows: list[dict],
        organization_ref,
        model_call_id: int | None,
        phase: str,
        command_type: str,
        forwarded_from_id: int | None = None,
    ) -> dict:
        event_id = self._safe_created_event(
            tick,
            sender_agent_id,
            command_type,
            audience_rows[0]["audience_kind"],
            len(audience_rows) if visibility == "participants" else 0,
            phase,
        )
        thread_id = self.store.insert(
            "comm_threads",
            created_tick=tick,
            created_by_agent_id=sender_agent_id,
            subject=subject,
            status="open",
            organization_kind=organization_ref[0] if organization_ref else None,
            organization_id=organization_ref[1] if organization_ref else None,
            root_event_id=event_id,
        )
        message_id = self.store.insert(
            "comm_messages",
            thread_id=thread_id,
            parent_message_id=None,
            forwarded_from_id=forwarded_from_id,
            sender_agent_id=sender_agent_id,
            created_tick=tick,
            deliver_at_tick=tick + 1,
            visibility=visibility,
            body_text=body,
            model_call_id=model_call_id,
            created_event_id=event_id,
            publication_event_id=None,
            status="queued",
        )
        for row in audience_rows:
            self._insert_audience(message_id, row)
        return {
            "ok": True,
            "thread_id": thread_id,
            "message_id": message_id,
            "created_event_id": event_id,
            "deliver_at_tick": tick + 1,
        }

    def _insert_audience(self, message_id: int, row: dict) -> int:
        return self.store.insert(
            "comm_audiences",
            message_id=message_id,
            audience_key=row["audience_key"],
            audience_kind=row["audience_kind"],
            audience_agent_id=row.get("audience_agent_id"),
            organization_kind=row.get("organization_kind"),
            organization_id=row.get("organization_id"),
            resolved_tick=None,
            resolution_status="queued",
            resolved_recipient_count=0,
            membership_snapshot_hash=None,
            failure_reason=None,
        )

    def _safe_created_event(
        self,
        tick: int,
        sender_agent_id: int,
        command_type: str,
        audience_kind: str,
        direct_recipient_count: int,
        phase: str,
    ) -> int:
        return self.store.log_event(
            tick,
            "communication_queued",
            {
                "command_type": command_type,
                "audience_kind": audience_kind,
                "direct_recipient_count": direct_recipient_count,
                "deliver_at_tick": tick + 1,
            },
            phase=phase,
            subject_type="agent",
            subject_id=sender_agent_id,
            importance=0.5,
        )

"""Knowledge-safe communication projections shared by prompts and APIs."""
from __future__ import annotations

import hashlib
import json

from .policy import CommunicationPolicy, MessageField, Principal


class AgentKnowledgeProjection:
    """Build and persist a bounded authorized inbox for one scheduled decision."""

    def __init__(self, store, config: dict | None = None):
        self.store = store
        self.config = config or {}
        communication = self.config.get("communications", {})
        self.max_messages = max(1, min(20, int(communication.get("prompt_message_limit", 8))))
        self.max_body_chars = max(
            500, min(20_000, int(communication.get("prompt_body_char_limit", 8_000))))
        self.max_unread_age = max(
            1, min(365, int(communication.get("prompt_unread_age_ticks", 30))))
        self.max_contacts = max(
            1, min(20, int(communication.get("prompt_contact_limit", 20))))
        self.policy = CommunicationPolicy(store)

    def build(self, agent_id: int, tick: int) -> dict:
        read_context_key = hashlib.sha256(
            f"semantics8:scheduled-deliberation:{agent_id}:{tick}".encode("utf-8")
        ).hexdigest()
        rows = self.store.query(
            "SELECT d.id AS delivery_id,d.message_id,d.memory_id,d.delivery_tick,d.grant_basis,"
            "m.thread_id,m.sender_agent_id,m.created_tick,m.visibility,t.subject,m.body_text,"
            "a.audience_kind,a.organization_kind,a.organization_id,"
            "s.name AS sender_name,s.role AS sender_role,"
            "CASE WHEN m.sender_agent_id<>? AND NOT EXISTS("
            "SELECT 1 FROM comm_messages reply WHERE reply.parent_message_id=m.id "
            "AND reply.sender_agent_id=?) THEN 1 ELSE 0 END AS can_reply "
            "FROM comm_deliveries d "
            "JOIN comm_messages m ON m.id=d.message_id "
            "JOIN comm_threads t ON t.id=m.thread_id "
            "JOIN comm_audiences a ON a.id=d.audience_id "
            "JOIN agents s ON s.id=m.sender_agent_id "
            "WHERE d.recipient_agent_id=? AND d.delivery_status='delivered' "
            "AND d.delivery_tick<=? AND d.delivery_tick>=? "
            "AND (d.read_tick IS NULL OR d.read_context_key=?) "
            "ORDER BY (d.read_tick IS NOT NULL),d.delivery_tick,d.id LIMIT ?",
            (
                int(agent_id), int(agent_id),
                int(agent_id), int(tick), int(tick) - self.max_unread_age,
                read_context_key, self.max_messages,
            ),
        )
        principal = Principal(f"agent:{agent_id}", agent_id=int(agent_id))
        items = []
        sources = []
        used_chars = 0
        for row in rows:
            access = self.policy.can_read_field(
                principal, int(row["message_id"]), MessageField.BODY, tick)
            if not access.allowed:
                continue
            body = str(row["body_text"])
            if used_chars + len(body) > self.max_body_chars:
                break
            used_chars += len(body)
            audience = (
                {"kind": "organization", "organization_kind": row["organization_kind"],
                 "organization_id": int(row["organization_id"])}
                if row["audience_kind"] == "organization"
                else {"kind": "direct", "recipient_agent_id": int(agent_id)}
            )
            items.append({
                "message_id": int(row["message_id"]),
                "thread_id": int(row["thread_id"]),
                "sender_agent_id": int(row["sender_agent_id"]),
                "sender_name": str(row["sender_name"]),
                "sender_role": str(row["sender_role"] or "citizen"),
                "subject": str(row["subject"]),
                "body": body,
                "delivered_tick": int(row["delivery_tick"]),
                "delivery_tick": int(row["delivery_tick"]),
                "audience": audience,
                "access_basis": access.basis.value if access.basis else None,
                "can_reply": bool(row["can_reply"]),
                "untrusted_world_data": True,
            })
            sources.append({
                "delivery_id": int(row["delivery_id"]),
                "message_id": int(row["message_id"]),
                "memory_id": int(row["memory_id"]),
            })
        return {
            "items": items,
            "sources": sources,
            "read_context_key": read_context_key if sources else None,
        }

    def contact_directory(
        self, agent_id: int, tick: int, inbox_items: list[dict] | None = None,
    ) -> list[dict]:
        """Return a bounded directory of counterparties the agent already knows.

        The directory is deliberately relationship-derived.  It does not expose the
        whole population or any private state, and dead or not-yet-arrived agents are
        removed as of the deliberation tick.
        """
        agent_id = int(agent_id)
        tick = int(tick)
        candidates: dict[int, dict] = {}

        def remember(other_id: int, score: float, relationship: str) -> None:
            other_id = int(other_id)
            if other_id == agent_id:
                return
            candidate = candidates.setdefault(
                other_id, {"score": float(score), "relationships": set()})
            candidate["score"] = max(float(candidate["score"]), float(score))
            candidate["relationships"].add(str(relationship))

        for position, item in enumerate(inbox_items or []):
            remember(
                int(item["sender_agent_id"]),
                4.0 - min(position, self.max_contacts) / 100.0,
                "recent_correspondent",
            )
        for row in self.store.query(
            "SELECT CASE WHEN agent_a=? THEN agent_b ELSE agent_a END AS other,weight "
            "FROM social_ties WHERE agent_a=? OR agent_b=? "
            "ORDER BY weight DESC,id",
            (agent_id, agent_id, agent_id),
        ):
            remember(int(row["other"]), 3.0 + float(row["weight"]), "social_tie")

        actor = self.store.query_one(
            "SELECT employer_id FROM agents WHERE id=?", (agent_id,))
        employer_id = int(actor["employer_id"]) if actor and actor["employer_id"] else None
        if employer_id is not None:
            for row in self.store.query(
                "SELECT id FROM agents WHERE employer_id=? AND id<>?",
                (employer_id, agent_id),
            ):
                remember(int(row["id"]), 2.5, "colleague")
            founder = self.store.scalar(
                "SELECT founder_agent_id FROM firms WHERE id=?", (employer_id,), default=None)
            if founder is not None:
                remember(int(founder), 2.75, "firm_founder")
        for firm in self.store.query(
            "SELECT id FROM firms WHERE founder_agent_id=? AND status<>'bankrupt' ORDER BY id",
            (agent_id,),
        ):
            for row in self.store.query(
                "SELECT id FROM agents WHERE employer_id=? AND id<>?",
                (int(firm["id"]), agent_id),
            ):
                remember(int(row["id"]), 2.5, "team_member")

        if not candidates:
            return []
        candidate_ids = sorted(candidates)
        placeholders = ",".join("?" for _ in candidate_ids)
        rows = self.store.query(
            f"SELECT id,name,role,occupation FROM agents WHERE id IN ({placeholders}) "
            "AND alive=1 AND arrived_tick<=?",
            (*candidate_ids, tick),
        )
        visible = {int(row["id"]): row for row in rows}
        ranked = sorted(
            (other_id for other_id in candidates if other_id in visible),
            key=lambda other_id: (-float(candidates[other_id]["score"]), other_id),
        )[:self.max_contacts]
        return [
            {
                "agent_id": other_id,
                "name": str(visible[other_id]["name"]),
                "role": str(visible[other_id]["role"] or "citizen"),
                "occupation": str(visible[other_id]["occupation"] or ""),
                "relationships": sorted(candidates[other_id]["relationships"]),
            }
            for other_id in ranked
        ]

    def persist_read_context(self, agent_id: int, tick: int, projection: dict) -> None:
        key = projection.get("read_context_key")
        sources = projection.get("sources", [])
        if not key or not sources:
            return
        delivery_ids = sorted({int(source["delivery_id"]) for source in sources})
        placeholders = ",".join("?" for _ in delivery_ids)
        with self.store.savepoint(f"comm_read_{tick}_{agent_id}"):
            conflict = self.store.scalar(
                f"SELECT COUNT(*) FROM comm_deliveries WHERE id IN ({placeholders}) "
                "AND recipient_agent_id=? AND read_context_key IS NOT NULL "
                "AND read_context_key<>?",
                (*delivery_ids, int(agent_id), str(key)),
                default=0,
            )
            if int(conflict):
                raise RuntimeError("communication read context identity conflict")
            newly_read = int(self.store.scalar(
                f"SELECT COUNT(*) FROM comm_deliveries WHERE id IN ({placeholders}) "
                "AND recipient_agent_id=? AND read_tick IS NULL",
                (*delivery_ids, int(agent_id)),
                default=0,
            ))
            self.store.execute(
                f"UPDATE comm_deliveries SET read_tick=COALESCE(read_tick,?), "
                f"read_context_key=COALESCE(read_context_key,?) WHERE id IN ({placeholders}) "
                "AND recipient_agent_id=? AND delivery_status='delivered'",
                (int(tick), str(key), *delivery_ids, int(agent_id)),
            )
            persisted = int(self.store.scalar(
                f"SELECT COUNT(*) FROM comm_deliveries WHERE id IN ({placeholders}) "
                "AND recipient_agent_id=? AND read_context_key=?",
                (*delivery_ids, int(agent_id), str(key)),
                default=0,
            ))
            if persisted != len(delivery_ids):
                raise RuntimeError("communication read context did not persist atomically")
            if newly_read:
                self.store.log_event(
                    tick,
                    "communication_read_context",
                    {
                        "agent_id": int(agent_id),
                        "message_count": len(delivery_ids),
                        "context_key": str(key),
                    },
                    phase="MORNING",
                    subject_type="agent",
                    subject_id=int(agent_id),
                    importance=0.25,
                )


def public_communication_summary(store, *, as_of_tick: int) -> dict:
    """Existence-safe aggregate for an ordinary dashboard observer."""
    row = store.query_one(
        "SELECT COUNT(*) AS total,"
        "SUM(CASE WHEN EXISTS(SELECT 1 FROM comm_audiences a "
        "WHERE a.message_id=m.id AND a.audience_kind='public' "
        "AND a.resolution_status='published' AND a.resolved_tick<=?) "
        "THEN 1 ELSE 0 END) AS published,"
        "SUM(CASE WHEN m.visibility<>'public' THEN 1 ELSE 0 END) AS private_total "
        "FROM comm_messages m WHERE m.created_tick<=?",
        (int(as_of_tick), int(as_of_tick)),
    )
    return {
        "total": int(row["total"] or 0),
        "published": int(row["published"] or 0),
        "private_total": int(row["private_total"] or 0),
    }

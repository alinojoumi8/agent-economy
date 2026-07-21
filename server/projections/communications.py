"""Field-authorized communication thread and message read models."""
from __future__ import annotations

from communications.policy import AccessBasis, CommunicationPolicy, MessageField, Principal
from engine.store import load_json


def _audience_view(store, message_id: int, basis: AccessBasis) -> list[dict]:
    rows = store.query(
        "SELECT * FROM comm_audiences WHERE message_id=? ORDER BY audience_key",
        (int(message_id),),
    )
    items = []
    for row in rows:
        kind = str(row["audience_kind"])
        if kind == "public":
            items.append({"kind": "public"})
        elif kind == "organization":
            items.append({
                "kind": "organization",
                "organization_kind": str(row["organization_kind"]),
                "organization_id": int(row["organization_id"]),
            })
        elif basis in {
                AccessBasis.SENDER, AccessBasis.DIRECT_DELIVERY,
                AccessBasis.LEGAL_DISCLOSURE, AccessBasis.OPERATOR_TRUTH}:
            items.append({"kind": "direct", "agent_id": int(row["audience_agent_id"])})
    return items


def build_message(
    store,
    principal: Principal,
    message_id: int,
    *,
    as_of_tick: int,
    include_body: bool = True,
    truth_audit=None,
) -> dict | None:
    policy = CommunicationPolicy(store, truth_audit=truth_audit)
    message = policy.authorized_message(
        principal, int(message_id), as_of_tick=int(as_of_tick), include_body=include_body)
    if message is None:
        return None
    basis = AccessBasis(message.pop("access_basis"))
    message["access_basis"] = basis.value
    resolved = store.query_one(
        "SELECT resolution_status,resolved_tick FROM comm_audiences WHERE message_id=? "
        "AND resolved_tick<=? ORDER BY resolved_tick DESC,id DESC LIMIT 1",
        (int(message_id), int(as_of_tick)),
    )
    message["status"] = str(resolved["resolution_status"]) if resolved else "queued"
    message["audience"] = _audience_view(store, int(message_id), basis)
    sender = store.query_one(
        "SELECT id,name,role FROM agents WHERE id=?", (int(message["sender_agent_id"]),))
    if sender is not None:
        message["sender"] = {
            "id": int(sender["id"]), "name": str(sender["name"]),
            "role": str(sender["role"] or "citizen"),
        }
    deliveries = []
    if basis in {AccessBasis.SENDER, AccessBasis.OPERATOR_TRUTH}:
        deliveries = [
            {
                "recipient_agent_id": int(row["recipient_agent_id"]),
                "delivery_tick": int(row["delivery_tick"]),
                "status": str(row["delivery_status"]),
                "grant_basis": str(row["grant_basis"]),
                "read_tick": int(row["read_tick"]) if row["read_tick"] is not None else None,
            }
            for row in store.query(
                "SELECT recipient_agent_id,delivery_tick,delivery_status,grant_basis,read_tick "
                "FROM comm_deliveries WHERE message_id=? ORDER BY recipient_agent_id",
                (int(message_id),),
            )
            if int(row["delivery_tick"]) <= int(as_of_tick)
        ]
    elif principal.agent_id is not None:
        deliveries = [
            {
                "recipient_agent_id": int(row["recipient_agent_id"]),
                "delivery_tick": int(row["delivery_tick"]),
                "status": str(row["delivery_status"]),
                "grant_basis": str(row["grant_basis"]),
                "read_tick": int(row["read_tick"]) if row["read_tick"] is not None else None,
            }
            for row in store.query(
                "SELECT recipient_agent_id,delivery_tick,delivery_status,grant_basis,read_tick "
                "FROM comm_deliveries WHERE message_id=? AND recipient_agent_id=?",
                (int(message_id), int(principal.agent_id)),
            )
            if int(row["delivery_tick"]) <= int(as_of_tick)
        ]
    message["deliveries"] = deliveries
    message["disclosures"] = [
        {
            "case_id": int(row["case_id"]),
            "granted_tick": int(row["granted_tick"]),
            "authority_kind": str(row["authority_kind"]),
        }
        for row in store.query(
            "SELECT d.case_id,d.granted_tick,a.authority_kind FROM comm_disclosures d "
            "JOIN comm_disclosure_authorities a ON a.id=d.authority_id "
            "WHERE d.message_id=? AND d.granted_tick<=? "
            "AND (d.grantee_agent_id=? OR ?=1) ORDER BY d.id",
            (int(message_id), int(as_of_tick), int(principal.agent_id or 0),
             int(basis is AccessBasis.OPERATOR_TRUTH)),
        )
    ]
    return message


def build_threads(
    store,
    principal: Principal,
    *,
    as_of_tick: int,
    after_thread_id: int = 0,
    limit: int = 50,
    truth_audit=None,
) -> dict:
    limit = max(1, min(200, int(limit)))
    policy = CommunicationPolicy(store, truth_audit=truth_audit)
    rows = store.query(
        "SELECT t.id,t.created_tick,t.status FROM comm_threads t "
        "WHERE t.id>? AND t.created_tick<=? ORDER BY t.id",
        (int(after_thread_id), int(as_of_tick)),
    )
    items = []
    has_more = False
    for thread in rows:
        authorized = []
        for message in store.query(
                "SELECT id FROM comm_messages WHERE thread_id=? AND created_tick<=? ORDER BY id",
                (int(thread["id"]), int(as_of_tick))):
            decision = policy.can_read_field(
                principal, int(message["id"]), MessageField.EXISTENCE, int(as_of_tick))
            if decision.allowed:
                authorized.append(int(message["id"]))
        if not authorized:
            continue
        if len(items) >= limit:
            has_more = True
            break
        messages = [
            build_message(
                store, principal, message_id, as_of_tick=as_of_tick,
                include_body=False, truth_audit=truth_audit)
            for message_id in authorized
        ]
        messages = [message for message in messages if message is not None]
        items.append({
            "thread_id": int(thread["id"]),
            "created_tick": int(thread["created_tick"]),
            "status": str(thread["status"]),
            "subject": messages[0]["subject"],
            "authorized_message_count": len(messages),
            "messages": messages,
        })
    return {
        "items": items,
        "next_after_thread_id": items[-1]["thread_id"] if has_more and items else None,
        "truncated": has_more,
    }

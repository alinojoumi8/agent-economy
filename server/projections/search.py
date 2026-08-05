"""Authorization-safe, deterministic observer search projections."""
from __future__ import annotations

from typing import Any, Iterable

from communications.policy import CommunicationPolicy, MessageField, Principal


SEARCH_KINDS = ("agent", "firm", "event", "communication_thread")
_COMMUNICATION_FIELDS = (
    MessageField.EXISTENCE,
    MessageField.SUBJECT,
    MessageField.THREAD_ENTRY,
    MessageField.MESSAGE_URL,
)


def _match_rank(query: str, object_id: int, values: Iterable[object]) -> int | None:
    needle = query.casefold()
    if needle == str(int(object_id)):
        return 0
    normalized = [str(value or "").casefold() for value in values]
    if any(value == needle for value in normalized):
        return 1
    if any(value.startswith(needle) for value in normalized):
        return 2
    if any(needle in value for value in normalized):
        return 3
    return None


def _bounded_group(kind: str, ranked: list[tuple[int, int, dict]], limit: int) -> dict:
    ranked.sort(key=lambda item: (item[0], item[1]))
    return {
        "kind": kind,
        "items": [item[2] for item in ranked[:limit]],
        "truncated": len(ranked) > limit,
    }


def _agent_group(store, query: str, as_of_tick: int, limit: int) -> dict:
    ranked = []
    for row in store.query(
            "SELECT id,name,role,occupation FROM agents "
            "WHERE arrived_tick<=? ORDER BY id", (int(as_of_tick),)):
        object_id = int(row["id"])
        rank = _match_rank(
            query, object_id, (row["name"], row["role"], row["occupation"]))
        if rank is None:
            continue
        descriptor = str(row["role"] or row["occupation"] or "citizen").replace("_", " ")
        ranked.append((rank, object_id, {
            "kind": "agent",
            "id": object_id,
            "label": str(row["name"]),
            "sublabel": f"{descriptor} · Agent #{object_id}",
        }))
    return _bounded_group("agent", ranked, limit)


def _firm_group(store, query: str, as_of_tick: int, limit: int) -> dict:
    ranked = []
    for row in store.query(
            "SELECT id,name,sector FROM firms WHERE founded_tick<=? ORDER BY id",
            (int(as_of_tick),)):
        object_id = int(row["id"])
        rank = _match_rank(query, object_id, (row["name"], row["sector"]))
        if rank is None:
            continue
        sector = str(row["sector"] or "organization").replace("_", " ")
        ranked.append((rank, object_id, {
            "kind": "firm",
            "id": object_id,
            "label": str(row["name"]),
            "sublabel": f"{sector} · Firm #{object_id}",
        }))
    return _bounded_group("firm", ranked, limit)


def _event_group(store, query: str, as_of_tick: int, limit: int) -> dict:
    ranked = []
    for row in store.query(
            "SELECT id,tick,kind,subject_type,subject_id FROM events "
            "WHERE tick<=? ORDER BY id", (int(as_of_tick),)):
        object_id = int(row["id"])
        subject_id = int(row["subject_id"]) if row["subject_id"] is not None else None
        subject_type = str(row["subject_type"] or "")
        place_subject = subject_type.casefold() == "place"
        rank = _match_rank(
            query,
            object_id,
            (row["kind"],) if place_subject else (row["kind"], subject_type, subject_id),
        )
        if rank is None:
            continue
        label = str(row["kind"]).replace("_", " ")
        if place_subject:
            subject = "location withheld"
        elif subject_type and subject_id is not None:
            subject = f"{subject_type} #{subject_id}"
        else:
            subject = "unscoped event"
        ranked.append((rank, object_id, {
            "kind": "event",
            "id": object_id,
            "label": label,
            "sublabel": f"Event #{object_id} · t{int(row['tick'])} · {subject}",
        }))
    return _bounded_group("event", ranked, limit)


def _communication_group(
    store,
    principal: Principal,
    query: str,
    as_of_tick: int,
    limit: int,
    *,
    truth_audit=None,
) -> dict:
    policy = CommunicationPolicy(store, truth_audit=truth_audit)
    ranked = []
    for thread in store.query(
            "SELECT id,created_tick FROM comm_threads "
            "WHERE created_tick<=? ORDER BY id", (int(as_of_tick),)):
        thread_id = int(thread["id"])
        authorized = False
        for message in store.query(
                "SELECT id FROM comm_messages WHERE thread_id=? AND created_tick<=? "
                "ORDER BY id", (thread_id, int(as_of_tick))):
            message_id = int(message["id"])
            if all(policy.can_read_field(
                    principal, message_id, field, int(as_of_tick)).allowed
                   for field in _COMMUNICATION_FIELDS):
                authorized = True
                break
        if not authorized:
            continue
        subject_row = store.query_one(
            "SELECT subject FROM comm_threads WHERE id=?", (thread_id,))
        if subject_row is None:
            continue
        subject = str(subject_row["subject"])
        rank = _match_rank(query, thread_id, (subject,))
        if rank is None:
            continue
        ranked.append((rank, thread_id, {
            "kind": "communication_thread",
            "id": thread_id,
            "label": subject,
            "sublabel": (
                f"Authorized communication · t{int(thread['created_tick'])} · "
                f"Thread #{thread_id}"
            ),
        }))
    return _bounded_group("communication_thread", ranked, limit)


def build_search(
    store,
    principal: Principal,
    *,
    query: str,
    as_of_tick: int,
    kinds: tuple[str, ...] = SEARCH_KINDS,
    limit: int = 8,
    truth_audit=None,
) -> dict[str, Any]:
    """Build a bounded read-only search result using projection authorization."""
    needle = str(query).strip()
    limit = max(1, min(20, int(limit)))
    selected = tuple(kind for kind in SEARCH_KINDS if kind in set(kinds))
    builders = {
        "agent": lambda: _agent_group(store, needle, as_of_tick, limit),
        "firm": lambda: _firm_group(store, needle, as_of_tick, limit),
        "event": lambda: _event_group(store, needle, as_of_tick, limit),
        "communication_thread": lambda: _communication_group(
            store,
            principal,
            needle,
            as_of_tick,
            limit,
            truth_audit=truth_audit,
        ),
    }
    return {"groups": [builders[kind]() for kind in selected]}

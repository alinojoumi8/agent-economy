"""Bounded public small-talk transcripts for one recorded city day.

This reads the legacy conversations/messages records, not the separately
authorized communications or provider cognition stores. Placement and time
within the evening are presentation concerns, never inferred by this query.
"""
from __future__ import annotations

import json


MESSAGE_LIMIT = 64
TEXT_LIMIT = 4000
TOPIC_LIMIT = 512


def build_city_conversations(store, *, as_of_tick: int, limit: int = 60) -> dict:
    if not 1 <= limit <= 200:
        raise ValueError("conversation limit must be between 1 and 200")
    rows = store.query(
        "SELECT c.id,c.tick,c.participant_ids,substr(c.topic,1,?) AS topic,"
        "length(c.topic)>? AS topic_truncated FROM conversations c "
        "WHERE c.tick=? AND json_valid(c.participant_ids) "
        "AND json_type(CASE WHEN json_valid(c.participant_ids) "
        "THEN c.participant_ids ELSE '[]' END)='array' "
        "AND json_array_length(CASE WHEN json_valid(c.participant_ids) "
        "THEN c.participant_ids ELSE '[]' END)>0 "
        "AND NOT EXISTS (SELECT 1 FROM json_each(CASE WHEN json_valid(c.participant_ids) "
        "THEN c.participant_ids ELSE '[]' END) p LEFT JOIN agents a ON a.id=p.value "
        "WHERE p.type!='integer' OR a.id IS NULL OR a.arrived_tick>?) "
        "ORDER BY c.id DESC LIMIT ?",
        (TOPIC_LIMIT, TOPIC_LIMIT, as_of_tick, as_of_tick, limit + 1),
    )
    items = [{
        "id": int(row["id"]), "tick": int(row["tick"]),
        "participants": json.loads(row["participant_ids"]), "topic": row["topic"],
        "topic_truncated": bool(row["topic_truncated"]),
        "messages": [], "messages_truncated": False,
    } for row in rows[:limit]]
    by_id = {item["id"]: item for item in items}
    if by_id:
        placeholders = ",".join("?" for _ in by_id)
        messages = store.query(
            "SELECT * FROM (SELECT m.conv_id,m.agent_id,a.name,m.seq,"
            "substr(m.text,1,?) AS text,length(m.text)>? AS text_truncated,"
            "ROW_NUMBER() OVER (PARTITION BY m.conv_id ORDER BY m.seq,m.id) AS ordinal "
            "FROM messages m JOIN agents a ON a.id=m.agent_id "
            "JOIN conversations c ON c.id=m.conv_id "
            f"WHERE m.conv_id IN ({placeholders}) AND m.tick>=c.tick AND m.tick<=? "
            "AND a.arrived_tick<=? AND EXISTS (SELECT 1 FROM json_each(c.participant_ids) p "
            "WHERE p.type='integer' AND p.value=m.agent_id)) "
            "WHERE ordinal<=? ORDER BY conv_id,ordinal",
            (TEXT_LIMIT, TEXT_LIMIT, *by_id, as_of_tick, as_of_tick, MESSAGE_LIMIT + 1),
        )
        for row in messages:
            item = by_id[row["conv_id"]]
            if row["ordinal"] > MESSAGE_LIMIT:
                item["messages_truncated"] = True
            else:
                item["messages"].append({key: row[key] for key in ("agent_id", "name", "text", "seq")}
                    | {"text_truncated": bool(row["text_truncated"])})
    return {
        "items": items, "tick": as_of_tick, "limit": limit,
        "has_more": len(rows) > limit,
        "content_truncated": any(item["topic_truncated"] or item["messages_truncated"]
                                 or any(message["text_truncated"] for message in item["messages"])
                                 for item in items),
        "source": "recorded_small_talk",
    }

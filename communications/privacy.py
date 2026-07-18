"""Body-free persistence and diagnostics for communication commands."""
from __future__ import annotations

import hashlib
import json


COMMUNICATION_TYPES = {"send_message", "reply_message", "forward_message"}
PRIVATE_KEYS = {"subject", "body", "body_text", "note", "agent_ids"}


def safe_command_metadata(action_type: str, payload: dict) -> dict:
    """Return bounded metadata without prose or recipient identity arrays."""
    if action_type not in COMMUNICATION_TYPES:
        return dict(payload)
    audience = payload.get("audience") if isinstance(payload, dict) else None
    audience = audience if isinstance(audience, dict) else {}
    audience_kind = audience.get("kind")
    direct_count = len(audience.get("agent_ids", [])) if audience_kind == "direct" else 0
    content = {
        key: payload.get(key)
        for key in ("subject", "body", "note")
        if payload.get(key) is not None
    }
    metadata = {
        "content_ref": "sha256:" + hashlib.sha256(
            json.dumps(
                content, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest(),
        "audience_kind": audience_kind,
        "direct_recipient_count": direct_count,
    }
    if audience_kind == "organization":
        metadata["organization_kind"] = audience.get("organization_kind")
        metadata["organization_id"] = audience.get("organization_id")
    for key in ("parent_message_id", "source_message_id"):
        if key in payload:
            metadata[key] = payload[key]
    return metadata


def safe_action_for_diagnostic(action) -> dict | object:
    if not isinstance(action, dict):
        return action
    action_type = str(action.get("type", ""))
    if action_type in COMMUNICATION_TYPES:
        payload = {key: value for key, value in action.items() if key != "type"}
        return {"type": action_type, **safe_command_metadata(action_type, payload)}
    if any(key in action for key in PRIVATE_KEYS):
        return {
            key: value for key, value in action.items()
            if key not in PRIVATE_KEYS | {"model_call_id", "rationale_summary"}
        }
    return {
        key: value for key, value in action.items()
        if key not in {"model_call_id", "rationale_summary"}
    }

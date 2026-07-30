"""Validated value objects consumed by the deterministic engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


class ValidationError(ValueError):
    """Raised when a proposed public value object is not engine-safe."""


@dataclass(frozen=True)
class Clause:
    clause_key: str
    clause_type: str
    terms: dict[str, Any]

    def __post_init__(self) -> None:
        if not self.clause_key.strip():
            raise ValidationError("clause_key is required")
        if not self.clause_type.strip():
            raise ValidationError("clause_type is required")
        if not isinstance(self.terms, dict):
            raise ValidationError("clause terms must be an object")


@dataclass(frozen=True)
class ActionEnvelope:
    actor_id: int
    action_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    evidence_event_ids: tuple[int, ...] = ()
    model_call_id: int | None = None
    rationale_summary: str = ""

    @classmethod
    def from_mapping(
        cls, actor_id: int, value: Mapping[str, Any]
    ) -> "ActionEnvelope":
        if not isinstance(value, Mapping):
            raise ValidationError("action must be an object")
        action_type = str(value.get("type", "")).strip()
        if not action_type:
            raise ValidationError("action type is required")
        raw_payload = value.get("payload")
        if raw_payload is None:
            reserved = {
                "type",
                "evidence_event_ids",
                "model_call_id",
                "rationale_summary",
            }
            payload = {str(k): v for k, v in value.items() if k not in reserved}
        elif isinstance(raw_payload, Mapping):
            payload = dict(raw_payload)
        else:
            raise ValidationError("action payload must be an object")
        evidence = value.get("evidence_event_ids", ())
        if not isinstance(evidence, (list, tuple)):
            raise ValidationError("evidence_event_ids must be a list")
        ids = tuple(int(item) for item in evidence)
        if any(item <= 0 for item in ids):
            raise ValidationError("evidence ids must be positive")
        model_call_id = value.get("model_call_id")
        rationale = str(value.get("rationale_summary", "")).strip()[:500]
        return cls(
            int(actor_id),
            action_type,
            payload,
            ids,
            int(model_call_id) if model_call_id is not None else None,
            rationale,
        )

    def engine_action(self) -> dict[str, Any]:
        action = {"type": self.action_type, **self.payload}
        if self.evidence_event_ids:
            action["evidence_event_ids"] = list(self.evidence_event_ids)
        if self.model_call_id is not None:
            action["model_call_id"] = self.model_call_id
        if self.rationale_summary:
            action["rationale_summary"] = self.rationale_summary
        return action

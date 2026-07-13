"""Validated public value objects for the v2 deterministic engine.

The objects in this module are deliberately small and dependency-free.  They are
the boundary between model-authored JSON and state-changing engine services;
prose and private reasoning are never executable inputs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


class ValidationError(ValueError):
    """Raised when a proposed public value object is not engine-safe."""


def _currency(value: object) -> str:
    code = str(value or "USD").upper().strip()
    if len(code) != 3 or not code.isalpha():
        raise ValidationError("currency must be a three-letter alphabetic code")
    return code


@dataclass(frozen=True)
class Money:
    minor_units: int
    currency: str = "USD"

    def __post_init__(self) -> None:
        if isinstance(self.minor_units, bool) or not isinstance(self.minor_units, int):
            raise ValidationError("money minor_units must be an integer")
        object.__setattr__(self, "currency", _currency(self.currency))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Money":
        return cls(int(value.get("minor_units", value.get("amount_cents", 0))),
                   str(value.get("currency", value.get("currency_code", "USD"))))

    def as_dict(self) -> dict[str, Any]:
        return {"minor_units": self.minor_units, "currency": self.currency}


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
    def from_mapping(cls, actor_id: int, value: Mapping[str, Any]) -> "ActionEnvelope":
        if not isinstance(value, Mapping):
            raise ValidationError("action must be an object")
        action_type = str(value.get("type", "")).strip()
        if not action_type:
            raise ValidationError("action type is required")
        raw_payload = value.get("payload")
        if raw_payload is None:
            reserved = {"type", "evidence_event_ids", "model_call_id", "rationale_summary"}
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
        return cls(int(actor_id), action_type, payload, ids,
                   int(model_call_id) if model_call_id is not None else None,
                   rationale)

    def engine_action(self) -> dict[str, Any]:
        action = {"type": self.action_type, **self.payload}
        if self.evidence_event_ids:
            action["evidence_event_ids"] = list(self.evidence_event_ids)
        if self.model_call_id is not None:
            action["model_call_id"] = self.model_call_id
        if self.rationale_summary:
            action["rationale_summary"] = self.rationale_summary
        return action


def _text(value: object, field_name: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValidationError(f"{field_name} is required")
    return result


@dataclass(frozen=True)
class Contract:
    title: str
    contract_type: str
    ruleset_key: str
    clauses: tuple[Clause, ...]
    status: str = "draft"

    def __post_init__(self) -> None:
        _text(self.title, "title"); _text(self.contract_type, "contract_type")
        _text(self.ruleset_key, "ruleset_key")
        if not isinstance(self.clauses, tuple):
            raise ValidationError("contract clauses must be a tuple")


@dataclass(frozen=True)
class Obligation:
    obligation_type: str
    obligor_type: str
    obligor_id: int
    obligee_type: str
    obligee_id: int
    due_tick: int | None = None

    def __post_init__(self) -> None:
        _text(self.obligation_type, "obligation_type")
        if self.obligor_id <= 0 or self.obligee_id <= 0:
            raise ValidationError("obligation parties must be positive ids")


@dataclass(frozen=True)
class LegalMatter:
    matter_type: str
    venue: str
    claimant_id: int
    respondent_id: int
    claim_type: str

    def __post_init__(self) -> None:
        _text(self.matter_type, "matter_type"); _text(self.venue, "venue")
        _text(self.claim_type, "claim_type")
        if min(self.claimant_id, self.respondent_id) <= 0:
            raise ValidationError("legal matter party ids must be positive")


@dataclass(frozen=True)
class LegalDecision:
    matter_id: int
    findings: tuple[dict[str, Any], ...]
    remedies: tuple[dict[str, Any], ...]
    rationale_summary: str = ""

    def __post_init__(self) -> None:
        if self.matter_id <= 0:
            raise ValidationError("matter_id must be positive")
        object.__setattr__(self, "rationale_summary", self.rationale_summary[:500])


@dataclass(frozen=True)
class Claim:
    subject_type: str
    subject_id: int | None
    predicate: str
    value: Any
    source_event_ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        _text(self.subject_type, "subject_type"); _text(self.predicate, "predicate")
        if any(value <= 0 for value in self.source_event_ids):
            raise ValidationError("claim source event ids must be positive")


@dataclass(frozen=True)
class InformationExposure:
    item_id: int
    agent_id: int
    tick: int
    channel: str
    perceived_claim: dict[str, Any]

    def __post_init__(self) -> None:
        if min(self.item_id, self.agent_id) <= 0 or self.tick < 0:
            raise ValidationError("invalid information exposure identifiers")
        _text(self.channel, "channel")


@dataclass(frozen=True)
class Bill:
    title: str
    origin_chamber: str
    policy_changes: dict[str, Any]

    def __post_init__(self) -> None:
        _text(self.title, "title")
        if self.origin_chamber not in {"house", "senate"}:
            raise ValidationError("origin_chamber must be house or senate")


@dataclass(frozen=True)
class PolicyRuleChange:
    rule_key: str
    value: Any
    effective_tick: int

    def __post_init__(self) -> None:
        _text(self.rule_key, "rule_key")
        if self.effective_tick < 0:
            raise ValidationError("effective_tick must be non-negative")


@dataclass(frozen=True)
class Region:
    key: str
    name: str
    currency: str
    population_target: int

    def __post_init__(self) -> None:
        _text(self.key, "key"); _text(self.name, "name")
        object.__setattr__(self, "currency", _currency(self.currency))
        if self.population_target < 0:
            raise ValidationError("population_target must be non-negative")


@dataclass(frozen=True)
class FxOrder:
    pair: str
    side: str
    qty: int
    limit_rate_ppm: int | None = None

    def __post_init__(self) -> None:
        parts = self.pair.upper().split("/")
        if len(parts) != 2 or any(len(part) != 3 for part in parts) or parts[0] == parts[1]:
            raise ValidationError("FX pair must be distinct ISO-like BASE/QUOTE codes")
        object.__setattr__(self, "pair", self.pair.upper())
        if self.side not in {"buy", "sell"} or self.qty <= 0:
            raise ValidationError("FX side must be buy/sell and qty must be positive")
        if self.limit_rate_ppm is not None and self.limit_rate_ppm <= 0:
            raise ValidationError("limit_rate_ppm must be positive")


@dataclass(frozen=True)
class DatasetManifest:
    key: str
    source_url: str
    vintage_date: str
    checksum_sha256: str
    transform_version: str

    def __post_init__(self) -> None:
        _text(self.key, "key"); _text(self.source_url, "source_url")
        _text(self.vintage_date, "vintage_date"); _text(self.transform_version, "transform_version")
        if len(self.checksum_sha256) != 64:
            raise ValidationError("checksum_sha256 must contain 64 hex characters")
        try:
            int(self.checksum_sha256, 16)
        except ValueError as exc:
            raise ValidationError("checksum_sha256 must be hexadecimal") from exc


@dataclass(frozen=True)
class ScenarioPack:
    key: str
    version: str
    arms: dict[str, dict[str, Any]]
    metrics: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.key, "key"); _text(self.version, "version")
        if len(self.arms) < 2:
            raise ValidationError("scenario pack requires at least two arms")

"""Owned persona boundary for deterministic sampling and governed enrichment.

The vendored module owns only the reproducible census-style base draw.  This
module is the stable application-facing API and constrains the fields an LLM may
enrich for a newly arrived citizen.
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import replace
from typing import Any, Iterable, Mapping

from .vendor.persona_gen import Persona, sample_persona, sample_population


PERSONA_SCHEMA = {
    "occupation": "short occupation",
    "personality": {"trait": 0.0},
    "political_lean": 0.0,
    "media_diet": [1],
    "risk_tolerance": 0.5,
}
PERSONA_SCHEMA_HINT = json.dumps(PERSONA_SCHEMA, separators=(",", ":"))
PERSONA_SYSTEM_PROMPT = (
    "You enrich a deterministic simulation persona. Return one JSON object and "
    "no prose. Include exactly these mutable fields: occupation, personality, "
    "political_lean, media_diet, risk_tolerance. political_lean must be between "
    "-1 and 1; risk_tolerance and every personality score must be between 0 and "
    "1; media_diet may contain only the supplied outlet IDs. Never propose a "
    "name, age, wealth, accounts, region, dependents, health, or lifecycle state."
)


def configured_outlet_ids(outlets: Iterable[Mapping[str, Any]]) -> list[int]:
    """Return stable, unique positive outlet IDs from configuration."""
    result: list[int] = []
    for outlet in outlets:
        try:
            outlet_id = int(outlet["id"])
        except (KeyError, TypeError, ValueError):
            continue
        if outlet_id > 0 and outlet_id not in result:
            result.append(outlet_id)
    return result


def sample_arrival_persona(
        prng: random.Random, outlet_ids: Iterable[int]) -> Persona:
    """Sample a base persona and map the vendor's ordinal diet to real IDs."""
    allowed = [int(value) for value in outlet_ids]
    if not allowed:
        allowed = [1, 2]
    base = sample_persona(prng, n_outlets=len(allowed))
    mapped_diet = [allowed[index - 1] for index in base.media_diet
                   if 1 <= int(index) <= len(allowed)]
    return replace(base, media_diet=mapped_diet or [allowed[0]])


def persona_base(agent: Mapping[str, Any]) -> dict:
    """Extract only mutable enrichment fields from an agent row."""
    return {
        "occupation": str(agent["occupation"] or "resident"),
        "personality": _load_object(agent["personality_json"]),
        "political_lean": float(agent["political_lean"] or 0.0),
        "media_diet": _load_list(agent["media_diet_json"]),
        "risk_tolerance": float(
            0.5 if agent["risk_tolerance"] is None else agent["risk_tolerance"]),
    }


def persona_request(
        agent: Mapping[str, Any], outlet_ids: Iterable[int]) -> tuple[str, str, dict]:
    """Build a stable prompt and structured context for one arrival call."""
    allowed = [int(value) for value in outlet_ids]
    base = persona_base(agent)
    context = {
        "base_persona": base,
        "allowed_outlet_ids": allowed,
        "engine_owned": {
            "name": str(agent["name"]),
            "age": int(agent["age"]),
            "dependents": int(agent["dependents"] or 0),
            "region_id": agent["region_id"],
        },
    }
    user = (
        "Enrich the mutable fields in this bounded input:\n"
        + json.dumps(context, sort_keys=True, separators=(",", ":"))
    )
    return PERSONA_SYSTEM_PROMPT, user, context


def scripted_persona_enrichment(context: dict) -> dict:
    """Deterministic persona policy used by free/offline runs."""
    base = dict(context.get("base_persona") or {})
    return {key: base.get(key) for key in PERSONA_SCHEMA}


def validate_persona_enrichment(
        value: Any, outlet_ids: Iterable[int]) -> tuple[dict | None, str | None]:
    """Validate a complete bounded update; reject the whole object on error."""
    if not isinstance(value, dict):
        return None, "response_not_object"

    occupation = value.get("occupation")
    if not isinstance(occupation, str) or not occupation.strip():
        return None, "invalid_occupation"
    occupation = occupation.strip()
    if len(occupation) > 80 or any(ord(ch) < 32 for ch in occupation):
        return None, "invalid_occupation"

    personality = value.get("personality")
    if not isinstance(personality, dict) or not 1 <= len(personality) <= 8:
        return None, "invalid_personality"
    bounded_personality: dict[str, float] = {}
    for raw_key, raw_score in personality.items():
        key = raw_key.strip() if isinstance(raw_key, str) else ""
        score = _bounded_number(raw_score, 0.0, 1.0)
        if (not key or len(key) > 40 or any(ord(ch) < 32 for ch in key)
                or score is None or key in bounded_personality):
            return None, "invalid_personality"
        bounded_personality[key] = score

    lean = _bounded_number(value.get("political_lean"), -1.0, 1.0)
    if lean is None:
        return None, "invalid_political_lean"
    risk = _bounded_number(value.get("risk_tolerance"), 0.0, 1.0)
    if risk is None:
        return None, "invalid_risk_tolerance"

    media = value.get("media_diet")
    allowed = {int(outlet_id) for outlet_id in outlet_ids}
    if not isinstance(media, list) or not media or not allowed:
        return None, "invalid_media_diet"
    bounded_media: list[int] = []
    for raw_outlet_id in media:
        if isinstance(raw_outlet_id, bool):
            return None, "invalid_media_diet"
        if isinstance(raw_outlet_id, float) and not raw_outlet_id.is_integer():
            return None, "invalid_media_diet"
        try:
            outlet_id = int(raw_outlet_id)
        except (TypeError, ValueError):
            return None, "invalid_media_diet"
        if outlet_id not in allowed:
            return None, "invalid_media_diet"
        if outlet_id not in bounded_media:
            bounded_media.append(outlet_id)

    return {
        "occupation": occupation,
        "personality": bounded_personality,
        "political_lean": lean,
        "media_diet": bounded_media,
        "risk_tolerance": risk,
    }, None


def _bounded_number(value: Any, minimum: float, maximum: float) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < minimum or number > maximum:
        return None
    return round(number, 4)


def _load_object(value: Any) -> dict:
    try:
        loaded = json.loads(value or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _load_list(value: Any) -> list:
    try:
        loaded = json.loads(value or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return loaded if isinstance(loaded, list) else []


__all__ = [
    "PERSONA_SCHEMA_HINT",
    "Persona",
    "configured_outlet_ids",
    "persona_base",
    "persona_request",
    "sample_arrival_persona",
    "sample_persona",
    "sample_population",
    "scripted_persona_enrichment",
    "validate_persona_enrichment",
]

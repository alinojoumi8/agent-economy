"""Deterministic guards for numeric claims in model-authored narrative."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import math
import re
from typing import Any


_NUMBER = re.compile(
    r"(?<![\w,.])(?P<currency>\$)?(?P<sign>[+-])?"
    r"(?P<number>\d+(?:,\d{3})*(?:\.\d+)?(?:[eE][+-]?\d+)?)"
    r"(?P<percent>%?)(?![\w])"
)


def model_grounding_active(config: dict, tick: int) -> bool:
    """Return whether the persisted forward-only grounding boundary is active."""
    boundary = (config or {}).get("beliefs", {}).get(
        "model_grounding_from_tick")
    if boundary is None:
        return False
    try:
        return int(tick) >= max(0, int(boundary))
    except (TypeError, ValueError, OverflowError):
        # A present but malformed safety boundary must fail closed.
        return True


def _canonical_number(match: re.Match[str]) -> str:
    raw = match.group("number").replace(",", "")
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return ""
    canonical = format(value.normalize(), "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    if match.group("sign") == "-" and value:
        canonical = "-" + canonical
    if match.group("currency"):
        canonical = "$" + canonical
    if match.group("percent"):
        canonical += "%"
    return canonical


def numeric_claims(text: str) -> set[str]:
    """Extract canonical, literal money, percentage, and decimal tokens."""
    visible = str(text or "")
    return {
        canonical
        for match in _NUMBER.finditer(visible)
        if not (
            match.end() + 1 < len(visible)
            and visible[match.end()] in {",", "."}
            and visible[match.end() + 1].isdigit()
        )
        if (canonical := _canonical_number(match))
    }


def _source_claims(value: Any) -> set[str]:
    if isinstance(value, bool) or value is None:
        return set()
    if isinstance(value, Decimal):
        return numeric_claims(str(value)) if value.is_finite() else set()
    if isinstance(value, int):
        return numeric_claims(str(value))
    if isinstance(value, float):
        return numeric_claims(str(value)) if math.isfinite(value) else set()
    if isinstance(value, str):
        return numeric_claims(value)
    if isinstance(value, dict):
        claims: set[str] = set()
        for item in value.values():
            claims.update(_source_claims(item))
        return claims
    if isinstance(value, (list, tuple, set)):
        claims = set()
        for item in value:
            claims.update(_source_claims(item))
        return claims
    return set()


def narrative_numbers_are_grounded(text: str, sources: Any) -> bool:
    """Return true only when each literal number occurs in supplied facts."""
    return numeric_claims(text).issubset(_source_claims(sources))


def sanitize_model_numeric_narrative(
    text: str,
    *,
    grounding_enabled: bool,
    fallback: str,
    sources: Any = None,
) -> str:
    """Replace unsupported model numerics while leaving raw call audit intact."""
    visible = str(text or "").strip()
    if (
        grounding_enabled
        and not narrative_numbers_are_grounded(visible, sources)
    ):
        return str(fallback)
    return visible

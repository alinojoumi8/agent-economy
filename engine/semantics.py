"""Compatibility guard for persisted engine behavior contracts."""
from __future__ import annotations

from typing import Any, Mapping


MIN_ENGINE_SEMANTICS_VERSION = 1
CURRENT_ENGINE_SEMANTICS_VERSION = 10


class UnsupportedEngineSemantics(ValueError):
    """Raised when a run asks this binary to interpret unknown semantics."""


def validate_engine_semantics_version(value: Any) -> int:
    """Return one supported integer semantics version, failing closed otherwise.

    Numeric strings remain accepted because historical persisted configuration
    was parsed with ``int(...)``. Booleans and fractional values are rejected
    instead of being silently coerced to a different behavior contract.
    """
    if isinstance(value, bool):
        raise UnsupportedEngineSemantics(
            "engine_semantics_version must be an integer, not a boolean")
    try:
        version = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise UnsupportedEngineSemantics(
            f"invalid engine_semantics_version {value!r}") from exc
    if isinstance(value, float) and value != version:
        raise UnsupportedEngineSemantics(
            f"invalid engine_semantics_version {value!r}")
    if not MIN_ENGINE_SEMANTICS_VERSION <= version <= CURRENT_ENGINE_SEMANTICS_VERSION:
        raise UnsupportedEngineSemantics(
            "unsupported engine_semantics_version "
            f"{version}; this binary supports "
            f"{MIN_ENGINE_SEMANTICS_VERSION}-{CURRENT_ENGINE_SEMANTICS_VERSION}")
    return version


def semantics_version(config: Mapping[str, Any], *, default: int) -> int:
    """Resolve and validate the behavior contract selected by ``config``."""
    return validate_engine_semantics_version(
        config.get("engine_semantics_version", default))

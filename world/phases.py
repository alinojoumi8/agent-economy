"""Immutable phase specifications keyed by engine semantics."""
from __future__ import annotations

from dataclasses import dataclass

from engine.semantics import validate_engine_semantics_version


@dataclass(frozen=True)
class PhaseSpec:
    name: str
    transactional: bool = False
    inference: bool = False


LEGACY_PHASE_SPECS = tuple(PhaseSpec(name) for name in (
    "NIGHT_CLOSE", "MORNING", "EXECUTION", "MARKET",
    "NEWSROOM", "EVENING", "MEMORY",
))

STANDARD_PHASE_SPECS = (
    PhaseSpec("NIGHT_CLOSE", transactional=True),
    PhaseSpec("MORNING", inference=True),
    PhaseSpec("EXECUTION", transactional=True),
    PhaseSpec("MARKET", transactional=True),
    PhaseSpec("NEWSROOM", inference=True),
    PhaseSpec("EVENING", inference=True),
    PhaseSpec("MEMORY", inference=True),
    PhaseSpec("FINALIZE", transactional=True),
)

SEMANTICS_8_PHASE_SPECS = (
    PhaseSpec("NIGHT_CLOSE", transactional=True),
    PhaseSpec("INBOX_DELIVERY", transactional=True),
    *STANDARD_PHASE_SPECS[1:],
)


def phase_specs_for_semantics(version: int) -> tuple[PhaseSpec, ...]:
    version = validate_engine_semantics_version(version)
    if version == 1:
        return LEGACY_PHASE_SPECS
    if version >= 8:
        return SEMANTICS_8_PHASE_SPECS
    return STANDARD_PHASE_SPECS


def phase_names_for_semantics(version: int) -> tuple[str, ...]:
    return tuple(spec.name for spec in phase_specs_for_semantics(version))

"""Validation for machine-checkable Oracle resolution rules.

The prompt advertises a deliberately small resolver language.  New governed
profiles validate that language before a forecast is admitted, so an invented
rule can never age into a scored negative outcome merely because the resolver
does not understand it.
"""
from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from typing import Any


SUPPORTED_RESOLUTION_RULE_TYPES = frozenset({
    "bank_failure",
    "firm_bankruptcy",
    "bank_run",
    "index_drop",
    "unemployment_above",
    "cpi_above",
    "metric_above",
    "metric_below",
})

_METRIC_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,79}$")
_ALLOWED_KEYS = {
    "bank_failure": {"type"},
    "firm_bankruptcy": {"type", "firm_id"},
    "bank_run": {"type", "window", "deposit_drop"},
    "index_drop": {"type", "window", "drop"},
    "unemployment_above": {"type", "threshold", "window"},
    "cpi_above": {"type", "threshold", "window"},
    "metric_above": {"type", "metric", "threshold", "window"},
    "metric_below": {"type", "metric", "threshold", "window"},
}


class ResolutionRuleError(ValueError):
    """Raised when a forecast cannot be resolved by the owned rule engine."""


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ResolutionRuleError(f"{field} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ResolutionRuleError(f"{field} must be a finite number") from exc
    if not math.isfinite(number):
        raise ResolutionRuleError(f"{field} must be a finite number")
    return number


def _positive_int(value: Any, field: str, *, maximum: int = 3650) -> int:
    if isinstance(value, bool):
        raise ResolutionRuleError(f"{field} must be a positive integer")
    try:
        integer = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ResolutionRuleError(f"{field} must be a positive integer") from exc
    if isinstance(value, float) and value != integer:
        raise ResolutionRuleError(f"{field} must be a positive integer")
    if integer < 1 or integer > maximum:
        raise ResolutionRuleError(f"{field} must be between 1 and {maximum}")
    return integer


def validate_resolution_rule(
    rule: Any,
    *,
    metric_exists: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    """Return a shallow copy of one supported, bounded resolver rule.

    ``metric_exists`` lets callers bind generic metric rules to locally
    available persisted series.  Historical profiles can omit strict
    validation entirely; new profiles opt in through Oracle configuration.
    """
    if not isinstance(rule, Mapping):
        raise ResolutionRuleError("resolution_rule must be an object")
    clean = dict(rule)
    rule_type = clean.get("type")
    if not isinstance(rule_type, str) or rule_type not in SUPPORTED_RESOLUTION_RULE_TYPES:
        raise ResolutionRuleError(
            f"unsupported resolution_rule.type {rule_type!r}")
    unknown = set(clean).difference(_ALLOWED_KEYS[rule_type])
    if unknown:
        raise ResolutionRuleError(
            f"unsupported fields for {rule_type}: {sorted(unknown)}")

    if "window" in clean:
        clean["window"] = _positive_int(clean["window"], "window")
    if rule_type == "firm_bankruptcy" and clean.get("firm_id") is not None:
        clean["firm_id"] = _positive_int(
            clean["firm_id"], "firm_id", maximum=2_147_483_647)
    if rule_type == "bank_run":
        drop = _finite_number(clean.get("deposit_drop", 0.30), "deposit_drop")
        if not 0.0 < drop <= 1.0:
            raise ResolutionRuleError("deposit_drop must be in (0, 1]")
        if "deposit_drop" in clean:
            clean["deposit_drop"] = drop
    if rule_type == "index_drop":
        drop = _finite_number(clean.get("drop", 0.20), "drop")
        if not 0.0 < drop <= 1.0:
            raise ResolutionRuleError("drop must be in (0, 1]")
        if "drop" in clean:
            clean["drop"] = drop
    if rule_type == "unemployment_above":
        threshold = _finite_number(clean.get("threshold", 0.08), "threshold")
        if not 0.0 <= threshold <= 1.0:
            raise ResolutionRuleError("unemployment threshold must be in [0, 1]")
        if "threshold" in clean:
            clean["threshold"] = threshold
    if rule_type == "cpi_above":
        threshold = _finite_number(clean.get("threshold", 110), "threshold")
        if threshold <= 0:
            raise ResolutionRuleError("CPI threshold must be positive")
        if "threshold" in clean:
            clean["threshold"] = threshold
    if rule_type in {"metric_above", "metric_below"}:
        metric = clean.get("metric")
        if not isinstance(metric, str) or not _METRIC_NAME.fullmatch(metric):
            raise ResolutionRuleError("metric must be a bounded metric name")
        clean["threshold"] = _finite_number(clean.get("threshold"), "threshold")
        if metric_exists is not None and not metric_exists(metric):
            raise ResolutionRuleError(f"metric {metric!r} has no persisted series")
    return clean

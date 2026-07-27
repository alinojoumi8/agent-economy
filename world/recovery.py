"""Pure, opt-in workforce recovery economics."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


_DEFAULT_ECONOMIC_SETTINGS = {
    "gross_margin_coverage_bps": 12_500,
    "cash_payroll_coverage_periods": 2,
    "max_hires_per_firm_per_period": 1,
    "demand_buffer_ticks": 5,
}


@dataclass(frozen=True)
class RecoveryAssessment:
    unit_margin_cents: int
    gross_margin_per_worker_period_cents: int
    safe_wage_ceiling_cents: int
    demand_limited_headcount: int
    cash_limited_headcount: int
    allowed_new_hires: int
    reason: str


def recovery_settings(config: Mapping[str, Any]) -> dict[str, int | bool]:
    """Return the normalized opt-in recovery profile without mutating config."""
    if not isinstance(config, Mapping):
        raise ValueError("config must be a mapping")
    raw = config.get("supply_recovery", {})
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise ValueError("supply_recovery must be a mapping")

    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("supply_recovery.enabled must be a boolean")

    if not enabled:
        return {"enabled": False, "wage_floor_cents": 0, **_DEFAULT_ECONOMIC_SETTINGS}

    normalized = _normalized_settings(raw)
    wage_floor_cents = _nonnegative_integer(
        "wage_floor_cents", raw.get("wage_floor_cents", 0))
    return {
        "enabled": True,
        "wage_floor_cents": wage_floor_cents,
        **normalized,
    }


def validate_recovery_settings(config: Mapping[str, Any]) -> dict[str, int | bool]:
    """Validate and return the structural, config-only recovery settings."""
    return recovery_settings(config)


def assess_recovery(*, enabled: bool, price_cents: int, input_cost_cents: int,
                    output_per_worker: int, pay_interval_ticks: int,
                    wage_cents: int, cash_cents: int,
                    current_payroll_cents: int, current_headcount: int,
                    target_headcount: int, recent_sales_units: int,
                    settings: Mapping[str, int]) -> RecoveryAssessment:
    """Calculate the new jobs a firm can safely add using integer arithmetic."""
    normalized = _normalized_settings(settings)
    margin = max(0, price_cents - input_cost_cents)
    period_margin = margin * max(0, output_per_worker) * max(1, pay_interval_ticks)
    ceiling = period_margin * 10_000 // normalized["gross_margin_coverage_bps"]
    demand_cap = max(1, (max(0, recent_sales_units) + (
        normalized["demand_buffer_ticks"] * max(0, output_per_worker))
    ) // max(1, output_per_worker))
    cash_cap = max(0, (max(0, cash_cents) - max(0, current_payroll_cents)) // (
        max(1, wage_cents) * normalized["cash_payroll_coverage_periods"]
    ))
    allowed = min(
        normalized["max_hires_per_firm_per_period"],
        max(0, target_headcount - current_headcount),
        max(0, demand_cap - current_headcount),
        cash_cap,
    )
    return _assessment(
        enabled, margin, period_margin, ceiling, demand_cap, cash_cap, allowed, wage_cents
    )


def _normalized_settings(settings: Mapping[str, Any]) -> dict[str, int]:
    if not isinstance(settings, Mapping):
        raise ValueError("recovery settings must be a mapping")
    normalized = dict(_DEFAULT_ECONOMIC_SETTINGS)
    for key, value in settings.items():
        if key in normalized:
            normalized[key] = _nonnegative_integer(key, value)

    if normalized["gross_margin_coverage_bps"] < 10_000:
        raise ValueError("gross_margin_coverage_bps must be at least 10000")
    if normalized["cash_payroll_coverage_periods"] <= 0:
        raise ValueError("cash_payroll_coverage_periods must be positive")
    return normalized


def _nonnegative_integer(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be nonnegative")
    return value


def _assessment(enabled: bool, margin: int, period_margin: int, ceiling: int,
                demand_cap: int, cash_cap: int, allowed: int,
                wage_cents: int) -> RecoveryAssessment:
    if not enabled:
        allowed = 0
        reason = "feature_disabled"
    elif wage_cents > ceiling:
        allowed = 0
        reason = "wage_exceeds_margin_ceiling"
    elif allowed <= 0:
        reason = "no_hire_capacity"
    else:
        reason = "eligible"
    return RecoveryAssessment(
        unit_margin_cents=margin,
        gross_margin_per_worker_period_cents=period_margin,
        safe_wage_ceiling_cents=ceiling,
        demand_limited_headcount=demand_cap,
        cash_limited_headcount=cash_cap,
        allowed_new_hires=allowed,
        reason=reason,
    )

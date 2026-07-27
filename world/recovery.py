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
    "sales_observation_ticks": 30,
}
_ECONOMIC_SETTING_NAMES = frozenset(_DEFAULT_ECONOMIC_SETTINGS)
_PROFILE_METADATA_SETTING_NAMES = frozenset({
    "enabled",
    "wage_floor_cents",
    "policy_version",
    "activation_tick",
})
_PROFILE_SETTING_NAMES = _ECONOMIC_SETTING_NAMES | _PROFILE_METADATA_SETTING_NAMES
_POLICY_VERSION = "supply-recovery-v1"


@dataclass(frozen=True)
class RecoveryAssessment:
    unit_margin_cents: int
    gross_margin_per_worker_period_cents: int
    safe_wage_ceiling_cents: int
    demand_limited_headcount: int
    cash_limited_headcount: int
    allowed_new_hires: int
    reason: str


def recovery_settings(config: Mapping[str, Any]) -> dict[str, int | bool | str]:
    """Return the normalized opt-in recovery profile without mutating config."""
    if not isinstance(config, Mapping):
        raise ValueError("config must be a mapping")
    raw = config.get("supply_recovery", {})
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise ValueError("supply_recovery must be a mapping")
    _reject_unknown_keys(raw, _PROFILE_SETTING_NAMES, "supply_recovery")

    metadata = _normalized_profile_metadata(raw)
    normalized = _normalized_settings({
        key: raw[key] for key in _ECONOMIC_SETTING_NAMES if key in raw
    })
    return {
        **metadata,
        **normalized,
    }


def validate_recovery_settings(config: Mapping[str, Any]) -> dict[str, int | bool | str]:
    """Validate and return the structural, config-only recovery settings."""
    return recovery_settings(config)


def assess_recovery(*, enabled: bool, price_cents: int, input_cost_cents: int,
                    output_per_worker: int, pay_interval_ticks: int,
                    wage_cents: int, cash_cents: int,
                    current_payroll_cents: int, current_headcount: int,
                    target_headcount: int, recent_sales_units: int,
                    settings: Mapping[str, Any]) -> RecoveryAssessment:
    """Calculate the new jobs a firm can safely add using integer arithmetic."""
    normalized = _normalized_settings(settings)
    margin = max(0, price_cents - input_cost_cents)
    period_margin = margin * max(0, output_per_worker) * max(1, pay_interval_ticks)
    ceiling = period_margin * 10_000 // normalized["gross_margin_coverage_bps"]
    sales_units = max(0, recent_sales_units)
    output_units = max(0, output_per_worker)
    demand_cap = 0 if sales_units == 0 else (
        sales_units + normalized["demand_buffer_ticks"] * output_units
    ) // (max(1, output_units) * normalized["sales_observation_ticks"])
    payroll_periods = normalized["cash_payroll_coverage_periods"]
    incumbent_payroll_reserve = max(0, current_payroll_cents) * payroll_periods
    new_hire_payroll_reserve = max(1, wage_cents) * payroll_periods
    cash_cap = max(0, (max(0, cash_cents) - incumbent_payroll_reserve) // (
        new_hire_payroll_reserve
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
    _reject_unknown_keys(settings, _PROFILE_SETTING_NAMES, "recovery settings")
    _normalized_profile_metadata(settings)
    normalized = dict(_DEFAULT_ECONOMIC_SETTINGS)
    for key, value in settings.items():
        if key in normalized:
            normalized[key] = _nonnegative_integer(key, value)

    if normalized["gross_margin_coverage_bps"] < 10_000:
        raise ValueError("gross_margin_coverage_bps must be at least 10000")
    if normalized["cash_payroll_coverage_periods"] <= 0:
        raise ValueError("cash_payroll_coverage_periods must be positive")
    if normalized["sales_observation_ticks"] <= 0:
        raise ValueError("sales_observation_ticks must be positive")
    if normalized["demand_buffer_ticks"] > normalized["sales_observation_ticks"] // 4:
        raise ValueError(
            "demand_buffer_ticks must not exceed one quarter of sales_observation_ticks"
        )
    return normalized


def _normalized_profile_metadata(settings: Mapping[str, Any]) -> dict[str, int | bool | str]:
    enabled = settings.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("supply_recovery.enabled must be a boolean")
    wage_floor_cents = _nonnegative_integer(
        "wage_floor_cents", settings.get("wage_floor_cents", 0))
    policy_version = settings.get("policy_version", _POLICY_VERSION)
    if not isinstance(policy_version, str) or policy_version != _POLICY_VERSION:
        raise ValueError(f"policy_version must be {_POLICY_VERSION}")
    activation_tick = _nonnegative_integer(
        "activation_tick", settings.get("activation_tick", 0))
    return {
        "enabled": enabled,
        "wage_floor_cents": wage_floor_cents,
        "policy_version": policy_version,
        "activation_tick": activation_tick,
    }


def _reject_unknown_keys(settings: Mapping[str, Any], allowed: frozenset[str],
                         context: str) -> None:
    unknown = sorted(repr(key) for key in set(settings) - allowed)
    if unknown:
        raise ValueError(f"{context} contains unknown keys: {', '.join(unknown)}")


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

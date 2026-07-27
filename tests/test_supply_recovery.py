import pytest

from world.recovery import (
    assess_recovery,
    recovery_settings,
    validate_recovery_settings,
)


RECOVERY_SETTINGS = {
    "gross_margin_coverage_bps": 12_500,
    "cash_payroll_coverage_periods": 2,
    "max_hires_per_firm_per_period": 1,
    "demand_buffer_ticks": 5,
}


def _assessment(**overrides):
    inputs = {
        "enabled": True,
        "price_cents": 500,
        "input_cost_cents": 180,
        "output_per_worker": 6,
        "pay_interval_ticks": 30,
        "wage_cents": 15_000,
        "cash_cents": 1_000_000,
        "current_payroll_cents": 0,
        "current_headcount": 0,
        "target_headcount": 3,
        "recent_sales_units": 180,
        "settings": RECOVERY_SETTINGS,
    }
    inputs.update(overrides)
    return assess_recovery(**inputs)


def test_assessment_rejects_wage_above_gross_margin_ceiling():
    assessment = _assessment(wage_cents=250_000)

    assert assessment.safe_wage_ceiling_cents == 46_080
    assert assessment.allowed_new_hires == 0
    assert assessment.reason == "wage_exceeds_margin_ceiling"


def test_profile_validation_rejects_insufficient_margin_coverage():
    with pytest.raises(ValueError, match="gross_margin_coverage_bps"):
        validate_recovery_settings({"supply_recovery": {
            "enabled": True,
            "wage_floor_cents": 15_000,
            **{**RECOVERY_SETTINGS, "gross_margin_coverage_bps": 9_999},
        }})


def test_profile_validation_defers_wage_floor_to_firm_assessment():
    settings = validate_recovery_settings({"supply_recovery": {
        "enabled": True,
        "wage_floor_cents": 50_000,
        **RECOVERY_SETTINGS,
    }})

    assert settings["wage_floor_cents"] == 50_000


def test_profile_validation_rejects_unknown_profile_key():
    with pytest.raises(ValueError, match="wage_floor_cent"):
        validate_recovery_settings({"supply_recovery": {
            "enabled": True,
            "wage_floor_cent": 15_000,
            **RECOVERY_SETTINGS,
        }})


def test_enabled_profile_defaults_documented_metadata():
    settings = validate_recovery_settings({"supply_recovery": {
        "enabled": True,
        **RECOVERY_SETTINGS,
    }})

    assert settings["policy_version"] == "supply-recovery-v1"
    assert settings["activation_tick"] == 0


def test_enabled_profile_retains_valid_metadata():
    settings = validate_recovery_settings({"supply_recovery": {
        "enabled": True,
        "policy_version": "supply-recovery-v1",
        "activation_tick": 17,
        **RECOVERY_SETTINGS,
    }})

    assert settings["policy_version"] == "supply-recovery-v1"
    assert settings["activation_tick"] == 17


def test_profile_validation_rejects_unsupported_policy_version():
    with pytest.raises(ValueError, match="policy_version"):
        validate_recovery_settings({"supply_recovery": {
            "enabled": True,
            "policy_version": "supply-recovery-v2",
            **RECOVERY_SETTINGS,
        }})


def test_profile_validation_rejects_negative_activation_tick():
    with pytest.raises(ValueError, match="activation_tick"):
        validate_recovery_settings({"supply_recovery": {
            "enabled": True,
            "activation_tick": -1,
            **RECOVERY_SETTINGS,
        }})


def test_profile_validation_rejects_nonpositive_sales_observation_ticks():
    with pytest.raises(ValueError, match="sales_observation_ticks must be positive"):
        validate_recovery_settings({"supply_recovery": {
            "enabled": True,
            "sales_observation_ticks": 0,
            **RECOVERY_SETTINGS,
        }})


def test_profile_validation_rejects_excessive_demand_buffer():
    with pytest.raises(ValueError, match="demand_buffer_ticks must not exceed one quarter"):
        validate_recovery_settings({"supply_recovery": {
            "enabled": True,
            **RECOVERY_SETTINGS,
            "sales_observation_ticks": 30,
            "demand_buffer_ticks": 8,
        }})


def test_feature_off_assessment_never_allows_a_hire():
    assessment = _assessment(enabled=False)

    assert assessment.allowed_new_hires == 0
    assert assessment.reason == "feature_disabled"


def test_assessment_allows_only_one_hire_per_period():
    assessment = _assessment()

    assert assessment.allowed_new_hires == 1
    assert assessment.reason == "eligible"


def test_assessment_reserves_incumbent_payroll_for_each_coverage_period():
    assessment = _assessment(
        cash_cents=100_000,
        current_payroll_cents=40_000,
        wage_cents=30_000,
    )

    assert assessment.cash_limited_headcount == 0
    assert assessment.allowed_new_hires == 0


def test_zero_sales_permit_no_new_hires_despite_demand_buffer():
    assessment = _assessment(recent_sales_units=0)

    assert assessment.demand_limited_headcount == 0
    assert assessment.allowed_new_hires == 0


def test_positive_sales_keep_the_bounded_demand_buffer():
    assessment = _assessment(recent_sales_units=150, target_headcount=10)

    assert assessment.demand_limited_headcount == 1
    assert assessment.allowed_new_hires == 1


def test_demand_capacity_counts_default_sales_over_the_observation_window():
    assessment = _assessment(recent_sales_units=180, target_headcount=10)

    assert assessment.demand_limited_headcount == 1
    assert assessment.allowed_new_hires == 1


def test_demand_capacity_scales_with_configured_observation_window():
    assessment = _assessment(
        recent_sales_units=180,
        target_headcount=10,
        settings={
            **RECOVERY_SETTINGS,
            "sales_observation_ticks": 10,
            "demand_buffer_ticks": 2,
        },
    )

    assert assessment.demand_limited_headcount == 3
    assert assessment.allowed_new_hires == 1


def test_assessment_accepts_normalized_profile_settings():
    settings = recovery_settings({"supply_recovery": {
        "enabled": True,
        **RECOVERY_SETTINGS,
    }})

    assessment = _assessment(settings=settings, target_headcount=10)

    assert settings["sales_observation_ticks"] == 30
    assert assessment.demand_limited_headcount == 1
    assert assessment.allowed_new_hires == 1


def test_explicit_enabled_argument_controls_normalized_profile_settings():
    settings = recovery_settings({"supply_recovery": {
        "enabled": True,
        **RECOVERY_SETTINGS,
    }})

    assessment = _assessment(enabled=False, settings=settings)

    assert assessment.allowed_new_hires == 0
    assert assessment.reason == "feature_disabled"


def test_assessment_rejects_unknown_economic_setting():
    with pytest.raises(ValueError, match="gross_margin_covergae_bps"):
        _assessment(settings={
            **RECOVERY_SETTINGS,
            "gross_margin_covergae_bps": 12_500,
        })


def test_missing_profile_defaults_to_feature_off_without_mutating_config():
    config = {"firms": {"pay_interval_ticks": 30}}

    settings = recovery_settings(config)

    assert settings["enabled"] is False
    assert settings["gross_margin_coverage_bps"] == 12_500
    assert config == {"firms": {"pay_interval_ticks": 30}}

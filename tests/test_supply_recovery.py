import random

import pytest

from engine.actions import ActionExecutor
from agents.memory import Memory
from agents.policies import (
    _select_open_job,
    _select_stocked_firm,
    founder_decision,
)
from agents.prompts import ContextBuilder
from tests.conftest import make_agent, make_bank

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


def _recovery_profile(**overrides):
    profile = {
        "enabled": True,
        "wage_floor_cents": 15_000,
        **RECOVERY_SETTINGS,
        "sales_observation_ticks": 30,
        "activation_tick": 0,
    }
    profile.update(overrides)
    return profile


def _recovery_founder_context(*, allowed_new_hires: int, safe_wage_ceiling_cents: int,
                              applications: list[dict] | None = None,
                              counters: list[dict] | None = None,
                              labor_negotiation_enabled: bool = True,
                              cash_cents: int = 1_000_000,
                              payroll_cents: int = 0,
                              employees: int = 0,
                              target_headcount: int = 3,
                              recent_sales_units: int = 180,
                              open_vacancies: int = 0) -> dict:
    return {
        "my_firm": {
            "firm_id": 17,
            "name": "Recovery Works",
            "inventory": 20,
            "price": 288,
            "unit_cost": 180,
            "cash": cash_cents,
            "employees": employees,
            "payroll": payroll_cents,
            "recent_sales": 0,
            "target_headcount": target_headcount,
            "is_private": True,
            "recovery": {
                "active": True,
                "settings": _recovery_profile(),
                "inputs": {
                    "price_cents": 500,
                    "input_cost_cents": 180,
                    "output_per_worker": 6,
                    "pay_interval_ticks": 30,
                    "wage_cents": 15_000,
                    "cash_cents": cash_cents,
                    "current_payroll_cents": payroll_cents,
                    "current_headcount": employees,
                    "target_headcount": target_headcount,
                    "recent_sales_units": recent_sales_units,
                },
                "assessment": {
                    "safe_wage_ceiling_cents": safe_wage_ceiling_cents,
                    "allowed_new_hires": allowed_new_hires,
                    "reason": ("eligible" if allowed_new_hires else "no_hire_capacity"),
                },
                "open_vacancies": open_vacancies,
            },
        },
        "firm_applications": applications or [],
        "firm_job_offers": counters or [],
        "labor_negotiation_enabled": labor_negotiation_enabled,
    }


def _context_firm(economy, profile: dict):
    economy.config["supply_recovery"] = profile
    economy.config["firms"] = {"pay_interval_ticks": 30, "target_headcount": 3}
    bank_id = make_bank(economy, reserves=10_000_000)
    founder_id, _ = make_agent(
        economy, bank_id, name="Recovery Founder", cash=2_000_000,
    )
    firm_id = economy.firms.found_firm(
        0,
        founder_id,
        "Recovery Goods",
        "manufacturing",
        product={
            "product": "recovery goods",
            "unit_price_cents": 500,
            "base_input_cost_cents": 180,
            "output_per_worker": 6,
        },
        opening_capital_cents=1_000_000,
    )
    economy.store.update("firms", firm_id, inventory=20)
    context = ContextBuilder(economy, Memory(economy.store, economy.config), economy.config)
    return firm_id, context


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


def test_profile_defaults_headcount_cap_to_the_legacy_firm_target():
    settings = validate_recovery_settings({
        "firms": {"target_headcount": 4},
        "supply_recovery": {
            "enabled": True,
            **RECOVERY_SETTINGS,
        },
    })

    assert settings["max_headcount_per_firm"] == 4


def test_profile_validation_rejects_negative_headcount_cap():
    with pytest.raises(ValueError, match="max_headcount_per_firm"):
        validate_recovery_settings({"supply_recovery": {
            "enabled": True,
            **RECOVERY_SETTINGS,
            "max_headcount_per_firm": -1,
        }})


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


def test_zero_worker_output_has_no_demand_capacity_even_with_unmet_demand():
    assessment = _assessment(
        output_per_worker=0,
        recent_sales_units=180,
        unmet_demand_units=180,
    )

    assert assessment.demand_limited_headcount == 0
    assert assessment.capacity_limited_headcount == 0
    assert assessment.allowed_new_hires == 0


def test_positive_sales_keep_the_bounded_demand_buffer():
    assessment = _assessment(recent_sales_units=150, target_headcount=10)

    assert assessment.demand_limited_headcount == 1
    assert assessment.allowed_new_hires == 1


def test_demand_capacity_counts_default_sales_over_the_observation_window():
    assessment = _assessment(recent_sales_units=180, target_headcount=10)

    assert assessment.demand_limited_headcount == 1
    assert assessment.allowed_new_hires == 1


def test_stockout_demand_grows_supply_beyond_fulfilled_sales_capacity():
    steady_supply = _assessment(
        output_per_worker=6,
        current_headcount=1,
        target_headcount=5,
        recent_sales_units=180,
        unmet_demand_units=0,
    )
    stockout_demand = _assessment(
        output_per_worker=6,
        current_headcount=1,
        target_headcount=5,
        recent_sales_units=180,
        unmet_demand_units=150,
    )

    assert steady_supply.demand_limited_headcount == 1
    assert steady_supply.capacity_limited_headcount == 1
    assert steady_supply.allowed_new_hires == 0
    assert stockout_demand.demand_limited_headcount == 2
    assert stockout_demand.capacity_limited_headcount == 2
    assert stockout_demand.allowed_new_hires == 1


@pytest.mark.parametrize(
    ("output_per_worker", "recent_sales_units", "unmet_demand_units", "expected_headcount"),
    [
        # 741 / (4 * 30) = 6.175: a persistent stockout needs the seventh worker.
        (4, 720, 21, 7),
        # 1,656 / (8 * 30) = 6.9: do not round the five-tick buffer to worker eight.
        (8, 1600, 56, 7),
    ],
)
def test_stockout_demand_rounds_observed_capacity_without_rounding_the_buffer(
        output_per_worker, recent_sales_units, unmet_demand_units, expected_headcount):
    assessment = _assessment(
        output_per_worker=output_per_worker,
        current_headcount=6,
        target_headcount=10,
        recent_sales_units=recent_sales_units,
        unmet_demand_units=unmet_demand_units,
        settings={**RECOVERY_SETTINGS, "max_headcount_per_firm": 10},
    )

    assert assessment.demand_limited_headcount == expected_headcount
    assert assessment.allowed_new_hires == 1


def test_explicit_headcount_cap_bounds_stockout_driven_growth():
    assessment = _assessment(
        output_per_worker=6,
        current_headcount=1,
        target_headcount=9,
        recent_sales_units=180,
        unmet_demand_units=1_620,
        settings={**RECOVERY_SETTINGS, "max_headcount_per_firm": 5},
    )

    assert assessment.demand_limited_headcount == 10
    assert assessment.headcount_cap == 5
    assert assessment.capacity_limited_headcount == 5
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


def test_context_activates_recovery_only_at_configured_tick(economy):
    firm_id, context = _context_firm(
        economy,
        _recovery_profile(activation_tick=5),
    )
    firm = economy.firms.get(firm_id)

    before = context._firm_view(firm, 4)
    after = context._firm_view(firm, 5)

    assert "recovery" not in before
    assert after["recovery"]["active"] is True


def test_context_uses_only_completed_ticks_for_recovery_sale_units(economy):
    firm_id, context = _context_firm(
        economy,
        _recovery_profile(sales_observation_ticks=3, demand_buffer_ticks=0),
    )
    economy.store.log_event(1, "goods_sale", {"firm_id": firm_id, "qty": 900})
    economy.store.log_event(2, "goods_sale", {"firm_id": firm_id, "qty": 7})
    economy.store.log_event(4, "goods_sale", {"firm_id": firm_id, "qty": 2})
    economy.store.log_event(5, "goods_sale", {"firm_id": firm_id, "qty": 300})
    economy.store.log_event(6, "goods_sale", {"firm_id": firm_id, "qty": 400})

    view = context._firm_view(economy.firms.get(firm_id), 5)

    assert view["recent_sales"] == 4
    assert view["recovery"]["recent_sales_units"] == 9
    assert view["recovery"]["inputs"] == {
        "price_cents": 500,
        "input_cost_cents": 180,
        "output_per_worker": 6,
        "pay_interval_ticks": 30,
        "wage_cents": 15_000,
        "cash_cents": 1_000_000,
        "current_payroll_cents": 0,
        "current_headcount": 0,
        "target_headcount": 3,
        "recent_sales_units": 9,
        "unmet_demand_units": 0,
    }
    assert view["recovery"]["assessment"]["allowed_new_hires"] == 0


def test_context_counts_only_stockout_rejections_as_unmet_recovery_demand(economy):
    firm_id, context = _context_firm(economy, _recovery_profile())
    bank_id = int(economy.store.scalar("SELECT id FROM banks ORDER BY id LIMIT 1"))
    buyer_id, _ = make_agent(economy, bank_id, name="Buyer", cash=0)
    executor = ActionExecutor(economy)

    economy.store.update("firms", firm_id, inventory=0)
    stockout = executor.execute_action(1, buyer_id, {
        "type": "buy_goods", "firm_id": firm_id, "qty": 5,
    })
    economy.store.update("firms", firm_id, inventory=100)
    insufficient_funds = executor.execute_action(1, buyer_id, {
        "type": "buy_goods", "firm_id": firm_id, "qty": 7,
    })

    view = context._firm_view(economy.firms.get(firm_id), 2)

    assert stockout == {"ok": False, "reason": "out of stock"}
    assert insufficient_funds == {"ok": False, "reason": "insufficient funds"}
    assert view["recovery"]["inputs"]["unmet_demand_units"] == 5


def test_active_context_exposes_live_open_vacancies(economy):
    firm_id, context = _context_firm(economy, _recovery_profile())
    economy.labor.post_job(0, firm_id, "worker", 15_000)

    view = context._firm_view(economy.firms.get(firm_id), 1)

    assert view["recovery"]["open_vacancies"] == 1


def test_recovery_founder_does_not_post_without_demand():
    decision = founder_decision(_recovery_founder_context(
        allowed_new_hires=0,
        safe_wage_ceiling_cents=46_080,
        recent_sales_units=0,
    ))

    assert not {
        "post_job", "make_job_offer", "accept_job_offer", "hire",
    } & {action["type"] for action in decision["actions"]}


def test_recovery_founder_uses_floor_only_when_a_hire_is_feasible():
    decision = founder_decision(_recovery_founder_context(
        allowed_new_hires=1,
        safe_wage_ceiling_cents=46_080,
    ))

    jobs = [action for action in decision["actions"] if action["type"] == "post_job"]
    assert jobs == [{
        "type": "post_job", "firm_id": 17, "title": "worker", "wage": 15_000,
    }]


def test_recovery_founder_clamps_a_price_cut_to_the_floor_wage_margin():
    context = _recovery_founder_context(
        allowed_new_hires=1,
        safe_wage_ceiling_cents=46_080,
    )
    firm = context["my_firm"]
    firm["price"] = 300
    firm["unit_cost"] = 120
    firm["recovery"]["inputs"].update({
        "price_cents": 300,
        "input_cost_cents": 120,
        "output_per_worker": 8,
        "pay_interval_ticks": 30,
    })

    decision = founder_decision(context)

    prices = [action for action in decision["actions"] if action["type"] == "set_price"]
    assert prices == [{"type": "set_price", "firm_id": 17, "price": 199}]


def test_recovery_founder_uses_each_incumbent_pay_interval_for_price_margin():
    context = _recovery_founder_context(
        allowed_new_hires=1,
        safe_wage_ceiling_cents=46_080,
    )
    firm = context["my_firm"]
    firm["price"] = 900
    firm["unit_cost"] = 120
    firm["employee_roster"] = [{"wage": 20_000, "pay_interval_ticks": 5}]
    firm["recovery"]["inputs"].update({
        "price_cents": 900,
        "input_cost_cents": 120,
        "output_per_worker": 8,
        "pay_interval_ticks": 30,
    })

    decision = founder_decision(context)

    prices = [action for action in decision["actions"] if action["type"] == "set_price"]
    assert prices == [{"type": "set_price", "firm_id": 17, "price": 745}]


def test_recovery_founder_posts_one_growth_vacancy_but_not_a_duplicate():
    growing = founder_decision(_recovery_founder_context(
        allowed_new_hires=1,
        safe_wage_ceiling_cents=46_080,
        employees=1,
        recent_sales_units=360,
    ))
    already_open = founder_decision(_recovery_founder_context(
        allowed_new_hires=1,
        safe_wage_ceiling_cents=46_080,
        employees=1,
        recent_sales_units=360,
        open_vacancies=1,
    ))

    assert {action["type"] for action in growing["actions"]} >= {"post_job"}
    assert "post_job" not in {action["type"] for action in already_open["actions"]}


def test_recovery_founder_makes_a_floor_wage_offer_only_when_feasible():
    decision = founder_decision(_recovery_founder_context(
        allowed_new_hires=1,
        safe_wage_ceiling_cents=46_080,
        applications=[{"application_id": 9, "posted_wage": 250_000}],
    ))

    offers = [action for action in decision["actions"] if action["type"] == "make_job_offer"]
    assert offers == [{"type": "make_job_offer", "application_id": 9, "wage": 15_000}]


def test_recovery_founder_rejects_existing_high_wage_offer_and_direct_hire():
    negotiated = founder_decision(_recovery_founder_context(
        allowed_new_hires=1,
        safe_wage_ceiling_cents=46_080,
        counters=[{"offer_id": 5, "requested_wage": 250_000}],
    ))
    direct = founder_decision(_recovery_founder_context(
        allowed_new_hires=1,
        safe_wage_ceiling_cents=46_080,
        applications=[{"application_id": 8, "posted_wage": 250_000}],
        labor_negotiation_enabled=False,
    ))

    assert "accept_job_offer" not in {action["type"] for action in negotiated["actions"]}
    assert "hire" not in {action["type"] for action in direct["actions"]}


def test_recovery_founder_selects_first_sustainable_counteroffer():
    decision = founder_decision(_recovery_founder_context(
        allowed_new_hires=1,
        safe_wage_ceiling_cents=46_080,
        counters=[
            {"offer_id": 5, "requested_wage": 250_000},
            {"offer_id": 6, "requested_wage": 25_000},
        ],
    ))

    assert {"type": "accept_job_offer", "offer_id": 6} in decision["actions"]


def test_recovery_founder_rechecks_cash_at_the_counteroffer_wage():
    decision = founder_decision(_recovery_founder_context(
        allowed_new_hires=1,
        safe_wage_ceiling_cents=46_080,
        cash_cents=40_000,
        recent_sales_units=180,
        counters=[{"offer_id": 5, "requested_wage": 25_000}],
    ))

    assert "accept_job_offer" not in {action["type"] for action in decision["actions"]}


def test_recovery_selection_uses_capacity_and_application_load_but_feature_off_is_legacy():
    prices = [
        {"firm_id": 1, "price": 300, "inventory": 1},
        {"firm_id": 2, "price": 900, "inventory": 100},
    ]
    jobs = [
        {"job_id": 1, "wage": 500, "application_count": 20},
        {"job_id": 2, "wage": 400, "application_count": 0},
    ]

    assert _select_stocked_firm({"prices": prices}, random.Random(0))["firm_id"] == 1
    assert _select_open_job({"jobs": jobs}, random.Random(0))["job_id"] == 1
    active_context = {"supply_recovery": {"active": True}, "prices": prices, "jobs": jobs}
    assert _select_stocked_firm(active_context, random.Random(0))["firm_id"] == 2
    assert _select_open_job(active_context, random.Random(0))["job_id"] == 2

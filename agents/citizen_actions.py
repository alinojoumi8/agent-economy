"""Canonical activity registry for native and external citizens.

The registry describes capability families. The participant catalog remains the
authoritative state-valid subset for one citizen and one wake.
"""
from __future__ import annotations

from typing import Any


_WORLD_ACTIONS: tuple[tuple[str, str, int], ...] = (
    ("do_nothing", "economic", 1),
    ("buy_goods", "economic", 1),
    ("apply_job", "employment", 1),
    ("post_job", "employment", 1),
    ("hire", "employment", 1),
    ("fire", "employment", 1),
    ("make_job_offer", "employment", 6),
    ("counter_job_offer", "employment", 6),
    ("accept_job_offer", "employment", 6),
    ("reject_job_offer", "employment", 6),
    ("apply_loan", "finance", 1),
    ("move_deposits", "finance", 1),
    ("transfer", "finance", 1),
    ("place_order", "finance", 1),
    ("cancel_orders", "finance", 1),
    ("place_ipo_bid", "finance", 6),
    ("place_fx_order", "finance", 7),
    ("cancel_fx_orders", "finance", 7),
    ("buy_insurance", "finance", 1),
    ("cancel_insurance", "finance", 1),
    ("withdraw_savings", "finance", 7),
    ("found_company", "company", 1),
    ("set_price", "company", 1),
    ("pitch_vc", "company", 1),
    ("open_ipo", "company", 6),
    ("close_ipo", "company", 6),
    ("propose_term_sheet", "company", 7),
    ("accept_term_sheet", "company", 7),
    ("run_due_diligence", "company", 7),
    ("close_funding_round", "company", 7),
    ("register_ip", "company", 7),
    ("license_ip", "company", 7),
    ("publish_disclosure", "company", 7),
    ("propose_merger", "company", 7),
    ("approve_merger", "company", 7),
    ("close_merger", "company", 7),
    ("create_trade_shipment", "economic", 7),
    ("request_migration", "employment", 7),
    ("say_public", "public", 1),
    ("send_message", "private_message", 8),
    ("reply_message", "private_message", 8),
    ("forward_message", "private_message", 8),
    ("buy_compute_plan", "compute_plan", 11),
    ("cancel_compute_plan", "compute_plan", 11),
    ("set_compute_sponsorship", "compute_plan", 11),
    ("study_skill", "skill_learning", 11),
    ("apply_business_permit", "civic", 12),
    ("attend_civic_appointment", "civic", 12),
)

_COMMONS_ACTIONS: tuple[tuple[str, str, bool], ...] = (
    ("post", "commons", False),
    ("react", "commons", False),
    ("read", "commons", False),
    ("follow", "commons", False),
    ("join_community", "commons", False),
    ("create_community", "commons", False),
    ("appeal", "commons", False),
    ("moderate", "commons_moderation", True),
)


def citizen_world_action_types(semantics_version: int | None = None) -> set[str]:
    maximum = int(semantics_version) if semantics_version is not None else 10_000
    return {
        action_type
        for action_type, _category, minimum in _WORLD_ACTIONS
        if minimum <= maximum
    }


def action_spec(action_type: str) -> dict[str, Any] | None:
    for name, category, minimum in _WORLD_ACTIONS:
        if name == action_type:
            return {
                "type": name,
                "category": category,
                "channel": "world",
                "minimum_semantics_version": minimum,
                "role_restricted": False,
            }
    for name, category, restricted in _COMMONS_ACTIONS:
        if name == action_type:
            return {
                "type": name,
                "category": category,
                "channel": "commons",
                "minimum_semantics_version": 10,
                "role_restricted": restricted,
            }
    return None


def citizen_action_registry(
    semantics_version: int, *, include_moderation: bool = False,
) -> dict[str, Any]:
    world = [
        action_spec(name)
        for name, _category, minimum in _WORLD_ACTIONS
        if minimum <= int(semantics_version)
    ]
    commons = [
        action_spec(name)
        for name, _category, restricted in _COMMONS_ACTIONS
        if int(semantics_version) >= 10 and (include_moderation or not restricted)
    ]
    return {
        "version": "ae.citizen-actions.v1",
        "state_validity": (
            "The per-wake action catalog is the authoritative executable subset."),
        "one_world_action_per_wake": True,
        "activities": [item for item in (*world, *commons) if item is not None],
    }

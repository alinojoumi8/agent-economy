import copy

import pytest

from agents.decision_candidates import compile_candidates
from llm.decision_config import decision_policy
from tests.test_jev_gateway import configuration


def observation():
    return {"tick": 4, "purpose": "decision", "agent": {
        "id": 7, "age": 30, "health": "healthy", "dependents": 0, "risk_tolerance": .4},
        "state": {"checking_balance": 3000, "currency_code": "CAD", "employed": False},
        "prices": [{"firm_id": 2, "price": 200, "inventory": 2, "currency_code": "CAD"},
                   {"firm_id": 3, "price": 100, "inventory": 9, "currency_code": "USD"}],
        "jobs": [{"job_id": 1, "title": "Worker", "wage": 1000, "currency_code": "CAD"}],
        "banks": [{"private_balance_sheet": "must not leave the projection"}],
        "authorized_inbox": [{"other_unneeded_private_content": "not for this task"}]}


def test_optional_household_actions_do_not_disable_every_routine_turn():
    context = observation()
    context["household_decisions"] = {"eligible_actions": [{"type": "separate_household"}]}
    assert compile_candidates(context, 4, decision_policy(configuration())).unsupported_reason is None
    context["household_decisions"]["pending"] = [{"id": 1}]
    assert compile_candidates(context, 4, decision_policy(configuration())).unsupported_reason == "household_decision_due"


def test_candidate_compiler_is_pure_and_actions_are_exact():
    context = observation()
    before = copy.deepcopy(context)
    menu = compile_candidates(context, 4, decision_policy(configuration()))
    assert context == before
    assert menu.unsupported_reason is None
    assert "private_balance_sheet" not in menu.evaluation_json
    assert "other_unneeded_private_content" not in menu.evaluation_json
    assert len({c["id"] for c in menu.candidates}) == len(menu.candidates)
    for candidate in menu.candidates:
        for action in candidate["actions"]:
            if action["type"] == "buy_goods":
                assert action["firm_id"] == 2
                assert 1 <= action["qty"] <= 2
                assert candidate["facts"]["remaining_cash_cents"] >= 2400
    selected = menu.actions_for(menu.baseline_choice)
    assert {action["type"] for action in selected} == {"buy_goods", "apply_job"}
    selected[0]["type"] = "forged"
    assert "forged" not in menu.candidates_json


def test_menu_identity_binds_tick_observation_and_prices():
    policy, context = decision_policy(configuration()), observation()
    first = compile_candidates(context, 4, policy)
    assert compile_candidates(copy.deepcopy(context), 4, policy).menu_hash == first.menu_hash
    context["prices"][0]["price"] += 1
    assert compile_candidates(context, 4, policy).menu_hash != first.menu_hash
    with pytest.raises(ValueError, match="tick"):
        compile_candidates(context, 5, policy)


def test_retired_and_employed_agents_do_not_get_job_actions():
    policy = decision_policy(configuration())
    for flag in ("retired", "employed"):
        context = observation()
        context["agent" if flag == "retired" else "state"][flag] = True
        menu = compile_candidates(context, 4, policy)
        assert not any(a["type"] == "apply_job" for c in menu.candidates for a in c["actions"])


def test_no_cash_or_inventory_has_explicit_wait():
    context = observation()
    context["state"].update(checking_balance=0, employed=True)
    menu = compile_candidates(context, 4, decision_policy(configuration()))
    assert {c["id"] for c in menu.candidates} == {"wait", "escalate"}
    assert menu.baseline_choice == "wait"
    assert menu.actions_for("wait") == [{"type": "do_nothing"}]
    with pytest.raises(ValueError):
        menu.actions_for("escalate")


def test_duplicate_ids_and_noninteger_money_are_rejected():
    context = observation()
    context["prices"].append(copy.deepcopy(context["prices"][0]))
    with pytest.raises(ValueError, match="repeats"):
        compile_candidates(context, 4, decision_policy(configuration()))
    context = observation()
    context["prices"][0]["price"] = 200.5
    with pytest.raises(ValueError, match="integer"):
        compile_candidates(context, 4, decision_policy(configuration()))


def test_required_civic_work_is_not_replaced_by_routine_choices():
    context = observation()
    context["civic_required_action"] = {"type": "attend_civic_appointment", "appointment_id": 3}
    menu = compile_candidates(context, 4, decision_policy(configuration()))
    assert menu.unsupported_reason == "required_civic_action"
    assert {c["id"] for c in menu.candidates} == {"wait", "escalate"}

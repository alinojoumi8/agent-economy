from copy import deepcopy

import pytest

from agents.decision_candidates import compile_candidates
from agents.decision_references import bind_event_references, BINDINGS_KEY
from engine.store import Store
from llm.decision_config import decision_policy
from llm.gateway import Gateway, LLMRequest
from research.decision_studies import frozen_menu
from llm.decisions import decision_hash
from tests.test_jev_candidates import observation
from tests.test_jev_domains import domain_config


def test_v4_event_ids_can_shift_without_weakening_evidence_binding(tmp_path):
    cfg = domain_config("bank_policy")
    policy = decision_policy(cfg)
    policy["strategic_review_interval_ticks"] = 0
    stores, menus, keys, requests = [], [], [], []
    try:
        for index in range(2):
            store = Store(str(tmp_path / f"world-{index}.db"))
            stores.append(store)
            store.init_run_meta(f"world-{index}", 42, cfg)
            if index == 0:
                store.log_event(0, "report_generated", {"operational": True})
            # Duplicate logical events must remain distinct occurrences.
            first = store.log_event(4, "liquidity_support_requested", {"bank_id": 1, "amount_cents": 100})
            second = store.log_event(4, "liquidity_support_requested", {"bank_id": 1, "amount_cents": 100})
            context = observation()
            context.update(purpose="central_banker", policy_rate_bps=500,
                liquidity_support_requests=[{"request_event_id": second, "solvent": True}],
                prepared_decision_options=[{"action": {"type": "decide_liquidity_support",
                    "request_event_id": first, "decision": "deny", "evidence_event_ids": [first]}}])
            context[BINDINGS_KEY] = bind_event_references(store, context)
            assert context[BINDINGS_KEY][0]["identity"] != context[BINDINGS_KEY][1]["identity"]
            menu = compile_candidates(context, 4, policy)
            menus.append(menu)
            gateway = Gateway(store, cfg)
            request = LLMRequest(role="central_banker", purpose="central_banker", agent_id=7,
                tick=4, context=context, evaluation=menu.evaluation)
            keys.append(gateway._cache_key(request, "scripted", "scripted"))
            requests.append(request)
            record = {"contract": policy["version"], "compiler": menu.compiler_version,
                "observation_hash": menu.observation_hash, "menu_hash": menu.menu_hash,
                "candidates": menu.candidates, "evaluation": menu.evaluation,
                "baseline_choice": menu.baseline_choice, "domain_metadata": menu.metadata,
                "question_hash": decision_hash(menu.evaluation["questions"]), "agent_id": 7, "tick": 4}
            assert frozen_menu(record).menu_hash == menu.menu_hash
        assert menus[0].observation_hash == menus[1].observation_hash
        assert menus[0].menu_hash == menus[1].menu_hash
        assert menus[0].evaluation == menus[1].evaluation
        assert keys[0] == keys[1]
        selected = next(c["id"] for c in menus[0].candidates if c["actions"] and c["actions"][0]["type"] == "decide_liquidity_support")
        assert menus[0].actions_for(selected)[0]["request_event_id"] != menus[1].actions_for(selected)[0]["request_event_id"]
        changed = deepcopy(requests[1].context)
        new_event = stores[1].log_event(4, "liquidity_support_requested", {"bank_id": 1, "amount_cents": 101})
        changed["liquidity_support_requests"][0]["request_event_id"] = new_event
        changed.pop(BINDINGS_KEY)
        changed[BINDINGS_KEY] = bind_event_references(stores[1], changed)
        assert compile_candidates(changed, 4, policy).menu_hash != menus[1].menu_hash
        with pytest.raises(ValueError, match="dangling"):
            bind_event_references(stores[1], {"request_event_id": 999999})
    finally:
        for store in stores:
            store.close()

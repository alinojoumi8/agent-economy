import json

from run import activate_llm_output_budgets_for_run
from run_config import load_config


def test_live_minimax_reserves_output_space_for_short_agent_contracts():
    llm = load_config("runs/v2-live-minimax.yaml")["llm"]

    assert llm.get("reporter_max_tokens", 0) >= 1200
    assert llm.get("newsroom_max_tokens", 0) >= 1000
    assert llm.get("conversation_max_tokens", 0) >= 600


def test_output_budget_activation_is_forward_only_persisted_and_idempotent():
    persisted = {
        "llm": {
            "route_contract": {"provider": "minimax", "model": "MiniMax-M3"},
        },
    }
    profile = {
        "llm": {
            "route_contract": {"provider": "minimax", "model": "MiniMax-M3"},
            "reporter_max_tokens": 1600,
            "newsroom_max_tokens": 1200,
            "conversation_max_tokens": 800,
        },
    }

    class FakeStore:
        tick = 206

        def __init__(self):
            self.config_json = json.dumps(persisted)
            self.events = []

        def get_meta(self):
            return {
                "tick": self.tick,
                "active_tick": None,
                "config_json": self.config_json,
            }

        def set_meta(self, **values):
            self.config_json = values["config_json"]

        def log_event(self, tick, kind, payload, **kwargs):
            self.events.append((tick, kind, payload, kwargs))
            return len(self.events)

        def commit(self):
            pass

    store = FakeStore()
    world = type("FakeWorld", (), {"config": persisted, "store": store})()

    first = activate_llm_output_budgets_for_run(world, profile)
    second = activate_llm_output_budgets_for_run(world, profile)
    stored = json.loads(store.config_json)

    assert first == second == {
        "activation_tick": 207,
        "reporter_max_tokens": 1600,
        "newsroom_max_tokens": 1200,
        "conversation_max_tokens": 800,
    }
    assert stored["llm"]["output_budget_activation_tick"] == 207
    assert stored["llm"]["reporter_max_tokens"] == 1600
    assert stored["llm"]["newsroom_max_tokens"] == 1200
    assert stored["llm"]["conversation_max_tokens"] == 800
    assert len(store.events) == 1

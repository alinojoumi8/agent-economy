"""Whole-world execution, ledger reconciliation, and recorded typed replay."""
import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from agents.typed_policy import TypedDecisionPolicy
from agents.decision_candidates import compile_candidates
from llm.decision_config import decision_policy
from llm.gateway import Gateway, LLMRequest
from run import open_run, replay_headless
from run_config import load_config
from world.replay_verify import verify_replay
from tests.test_jev_contract import transport
from tests.test_jev_candidates import observation
from tests.test_jev_gateway import configuration


ROOT = Path(__file__).resolve().parents[1]


def test_execution_revalidates_inventory_after_menu_compilation(tmp_path):
    config = load_config(ROOT / "runs/jev-offline.yaml")
    store, world, _ = open_run(config, None, None, data_dir=tmp_path)
    try:
        actor = store.scalar("SELECT id FROM agents WHERE kind='citizen' ORDER BY id LIMIT 1")
        firm = store.scalar("SELECT id FROM firms ORDER BY id LIMIT 1")
        context = observation()
        context["agent"]["id"] = actor
        context["state"]["currency_code"] = "USD"
        context["prices"] = [{"firm_id": firm, "price": 1, "inventory": 2, "currency_code": "USD"}]
        menu = compile_candidates(context, 4, decision_policy(config))
        choice = next(c for c in menu.candidates if len(c["actions"]) == 1 and c["actions"][0]["type"] == "buy_goods")
        store.update("firms", firm, inventory=0)
        before = store.scalar("SELECT COUNT(*) FROM transactions")
        outcome = world.runtime.executor.execute_actions(4, actor, menu.actions_for(choice["id"]), phase="EXECUTION")
        assert not outcome[0]["ok"]
        assert store.scalar("SELECT COUNT(*) FROM transactions") == before
        assert world.economy.ledger.reconcile()[0]
    finally:
        world.close()


def typed_handler(request):
    body = json.loads(request.content)
    options = body["questions"]["action"]["criteria"]
    selected = next((key for key in options if key not in {"wait", "escalate"}), "wait")
    return httpx.Response(200, json={"model": "typesafe/jev-1.13-20260917", "provider": "TypeSafe",
        "answers": {"action": {"type": "choice", "choice": selected, "confidence": .8}},
        "usage": {"input_tokens": 100, "output_tokens": 20, "cost": .0000042}})


@pytest.mark.parametrize("profile", ["jev-offline.yaml", "jev-live.yaml"])
@pytest.mark.parametrize("version", ["bounded-economic-choice-v1", "bounded-economic-choice-v2"])
def test_world_reconciles_and_replays_exactly(tmp_path, monkeypatch, profile, version):
    monkeypatch.setenv("OPENROUTER_API_KEY", "private-fixture-value")
    transport(monkeypatch, typed_handler)
    config = load_config(ROOT / "runs" / profile)
    config["llm"]["decision_policy"]["version"] = version
    if version.endswith("v2"):
        config["firms"]["listed"] = 0
        config["llm"]["response_contract"] = "required-json-v2"
    config.update(checkpoint_dir=str(tmp_path / "checkpoints"), report_dir=str(tmp_path / "reports"))
    store, world, run_id = open_run(config, None, None, data_dir=tmp_path)
    path = Path(store.path)
    try:
        async def run_days():
            for _ in range(3):
                await world.step()
        asyncio.run(run_days())
        world.economy.ledger.reconcile()
        receipts = [json.loads(row["payload_json"]) for row in store.query(
            "SELECT payload_json FROM events WHERE kind='typed_decision'")]
        assert receipts
        selected = [r for r in receipts if r["status"] == "selected"]
        assert selected
        assert any(any(outcome["ok"] for outcome in r["outcomes"]) for r in selected)
        if profile == "jev-live.yaml":
            assert store.scalar("SELECT COUNT(*) FROM llm_calls WHERE provider='openrouter_jev'") > 0
            assert all(r["calls"] for r in selected)
        else:
            assert all(not r["calls"] for r in selected)
        for receipt in selected:
            assert not store.scalar("SELECT COUNT(*) FROM memories WHERE text LIKE 'I decided:%' "
                                    "AND agent_id=? AND tick=?", (receipt["agent_id"], receipt["tick"]))
    finally:
        world.close()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.delenv("OPENROUTER_API_KEY")
    replay_store, replay_world, _ = open_run({}, None, run_id, data_dir=tmp_path)
    try:
        asyncio.run(replay_headless(replay_world, 3))
        replay_world.economy.ledger.reconcile()
        proof = verify_replay(path, replay_store.path)
        assert proof["exact"], proof["differences"]
        assert replay_world.gateway._live_dispatch_count == 0
    finally:
        replay_world.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_missing_confidence_abstains_without_fabricating_reasoning(store, monkeypatch):
    monkeypatch.setenv("TEST_JEV_KEY", "private-fixture-value")

    def handler(request):
        result = json.loads(typed_handler(request).content)
        result["answers"]["action"].pop("confidence")
        return httpx.Response(200, json=result)

    transport(monkeypatch, handler)
    config = configuration()
    config["llm"]["decision_policy"]["minimum_confidence"] = .7
    gateway = Gateway(store, config)
    policy = TypedDecisionPolicy(gateway, config)
    context = observation()
    menu = policy.prepare(context, 4)
    decision = asyncio.run(policy.complete(LLMRequest(role="citizen", purpose="decision", tick=4), menu))
    assert decision.envelope == {"reasoning": "", "actions": [{"type": "do_nothing"}], "belief_updates": []}
    assert decision.receipt["status"] == "abstained"
    assert decision.receipt["reason"] == "missing_confidence"
    assert decision.receipt["confidence"] is None


def test_cohort_assignment_and_compute_eligibility_are_stable(store, monkeypatch):
    monkeypatch.setenv("TEST_JEV_KEY", "private-fixture-value")
    config = configuration()
    config["llm"]["decision_policy"].update(eligible_tiers=["premium"])
    policy = TypedDecisionPolicy(Gateway(store, config), config)
    context = observation()
    assert policy.prepare(context, 4) is None
    context["compute_plan"] = {"tier": "premium"}
    assert policy.prepare(context, 4) is not None


def test_v2_leaves_staff_personal_turns_on_the_existing_policy(store, monkeypatch):
    monkeypatch.setenv("TEST_JEV_KEY", "private-fixture-value")
    config, context = configuration(), observation()
    context["agent"]["role"] = "reporter"
    original = TypedDecisionPolicy(Gateway(store, config), config)
    assert original.prepare(context, 4) is not None
    config["llm"]["decision_policy"]["version"] = "bounded-economic-choice-v2"
    revised = TypedDecisionPolicy(Gateway(store, config), config)
    assert revised.prepare(context, 4) is None
    context["agent"]["role"] = None
    assert revised.prepare(context, 4) is not None

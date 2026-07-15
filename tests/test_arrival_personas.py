"""Semantics-7 arrival accounts and governed persona enrichment."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from agents.personas.library import (
    PERSONA_SCHEMA_HINT, Persona, configured_outlet_ids, persona_request,
)
from engine.checkpoint_manifest import build_checkpoint_manifest
from engine.ledger import SYS_INFLOW
from engine.store import Store
from llm.gateway import BudgetExceeded, LLMRequest, ProviderUnavailable
from world.loop import World


def _config(tmp_path, *, semantics: int = 7, replay_source=None) -> dict:
    config = {
        "seed": 718,
        "engine_semantics_version": semantics,
        "population": {"size": 6, "baseline_citizens_core": True},
        "banks": {"count": 2},
        "firms": {"count": 1, "listed": 0},
        "outlets": [
            {"id": 10, "name": "North", "slant": "neutral"},
            {"id": 20, "name": "South", "slant": "neutral"},
        ],
        "lifecycle": {"housing_cost_cents": 100},
        "budget": {"cap_usd": 10.0, "oracle_reserve_usd": 1.0,
                   "conversation_pairs": 0},
        "llm": {
            "default_route": {"provider": "scripted", "model": "scripted"},
            "routes": {},
        },
        "checkpoint_every": 0,
        "checkpoint_dir": str(tmp_path / "checkpoints"),
    }
    if replay_source is not None:
        config["replay_source_path"] = str(replay_source)
    return config


def _world(tmp_path, name: str, *, semantics: int = 7, replay_source=None) -> World:
    config = _config(tmp_path, semantics=semantics, replay_source=replay_source)
    store = Store(str(tmp_path / name))
    store.init_run_meta(name, config["seed"], config)
    world = World(store, config, replay=replay_source is not None)
    world.initialize()
    return world


def _spawn_one(world: World, tick: int = 1):
    schedule_event_id = world.economy.lifecycle.schedule_arrival(0, tick)
    world._spawn_due_arrivals(tick)
    arrival = world.store.query_one(
        "SELECT * FROM agents WHERE arrived_tick=? ORDER BY id DESC LIMIT 1", (tick,))
    assert arrival is not None
    event = world.store.query_one(
        "SELECT payload_json FROM events WHERE kind='arrival' "
        "AND subject_id=? ORDER BY id DESC LIMIT 1", (int(arrival["id"]),))
    payload = json.loads(event["payload_json"])
    assert int(payload["schedule_event_id"]) == schedule_event_id
    return arrival, payload


def _opening_delta(store: Store, account_id: int) -> tuple[int, str]:
    row = store.query_one(
        "SELECT positive.delta_cents AS amount, source.label AS source_label "
        "FROM ledger_entries positive "
        "JOIN transactions txn ON txn.id=positive.txn_id "
        "JOIN ledger_entries negative ON negative.txn_id=positive.txn_id "
        "AND negative.delta_cents<0 "
        "JOIN accounts source ON source.id=negative.account_id "
        "WHERE positive.account_id=? AND positive.delta_cents>0 "
        "AND txn.tick=1 AND txn.kind='endowment' ORDER BY txn.id LIMIT 1",
        (account_id,),
    )
    assert row is not None
    return int(row["amount"]), str(row["source_label"])


def test_semantics7_arrival_uses_70_30_inflow_accounts(tmp_path):
    world = _world(tmp_path, "accounts.db")
    arrival, payload = _spawn_one(world)

    checking_id = int(arrival["checking_account_id"])
    savings_id = int(arrival["savings_account_id"])
    checking, checking_source = _opening_delta(world.store, checking_id)
    savings, savings_source = _opening_delta(world.store, savings_id)

    assert checking == int((checking + savings) * 0.7)
    assert checking == int(payload["checking_cents"])
    assert savings == int(payload["savings_cents"])
    assert checking_source == SYS_INFLOW
    assert savings_source == SYS_INFLOW
    assert arrival["population_tier"] == "core"
    assert int(arrival["pinned_core"]) == 1
    assert json.loads(arrival["media_diet_json"])[0] in {10, 20}
    ok, diagnostic = world.economy.ledger.reconcile()
    assert ok, diagnostic
    world.store.close()


def test_persona_enrichment_is_one_persisted_call_and_resume_idempotent(tmp_path):
    world = _world(tmp_path, "resume.db")
    arrival, _ = _spawn_one(world)
    agent_id = int(arrival["id"])
    outlet_ids = configured_outlet_ids(world.config["outlets"])
    system, user, context = persona_request(arrival, outlet_ids)

    # Simulate interruption after the gateway persisted its response but before
    # runtime applied the enrichment or wrote its completion marker.
    asyncio.run(world.gateway.complete(
        LLMRequest(role="persona", purpose="persona", system=system, user=user,
                   context=context, agent_id=agent_id, tick=1,
                   max_tokens=350, temperature=0.4),
        schema_hint=PERSONA_SCHEMA_HINT))
    assert world.store.scalar(
        "SELECT COUNT(*) FROM llm_calls WHERE purpose='persona'", default=0) == 1

    asyncio.run(world.runtime.enrich_pending_arrivals(1))
    asyncio.run(world.runtime.enrich_pending_arrivals(1))

    assert world.store.scalar(
        "SELECT COUNT(*) FROM llm_calls WHERE purpose='persona'", default=0) == 1
    assert world.store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='persona_enriched' "
        "AND subject_id=?", (agent_id,), default=0) == 1
    call = world.store.query_one(
        "SELECT role,purpose,agent_id FROM llm_calls WHERE purpose='persona'")
    assert (call["role"], call["purpose"], int(call["agent_id"])) == (
        "persona", "persona", agent_id)
    marker = world.store.query_one(
        "SELECT payload_json FROM events WHERE kind='persona_enriched' "
        "AND subject_id=?", (agent_id,))
    assert "model_call_id" not in json.loads(marker["payload_json"])
    world.store.close()


@pytest.mark.parametrize("error_type", [BudgetExceeded, ProviderUnavailable])
def test_persona_provider_or_budget_pause_resumes_without_skipping(
        tmp_path, monkeypatch, error_type):
    world = _world(tmp_path, f"resume-{error_type.__name__}.db")
    arrival, _ = _spawn_one(world)
    agent_id = int(arrival["id"])
    original_complete = world.gateway.complete
    attempts = 0

    async def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            if error_type is ProviderUnavailable:
                raise ProviderUnavailable(
                    "scripted", "scripted", "persona", "temporary persona pause")
            raise BudgetExceeded("temporary persona pause")
        return await original_complete(*args, **kwargs)

    monkeypatch.setattr(world.gateway, "complete", fail_once)
    with pytest.raises(error_type, match="temporary persona pause"):
        asyncio.run(world.runtime.enrich_pending_arrivals(1))

    assert world.store.scalar(
        "SELECT COUNT(*) FROM llm_calls WHERE purpose='persona'", default=0) == 0
    assert world.store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind IN "
        "('persona_enriched','persona_enrichment_fallback') AND subject_id=?",
        (agent_id,), default=0) == 0

    asyncio.run(world.runtime.enrich_pending_arrivals(1))
    assert attempts == 2
    assert world.store.scalar(
        "SELECT COUNT(*) FROM llm_calls WHERE purpose='persona'", default=0) == 1
    assert world.store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='persona_enriched' AND subject_id=?",
        (agent_id,), default=0) == 1
    world.store.close()


def test_persona_enrichment_updates_only_bounded_fields(tmp_path):
    world = _world(tmp_path, "bounded.db")
    arrival, _ = _spawn_one(world)
    agent_id = int(arrival["id"])
    immutable = {
        key: arrival[key]
        for key in ("name", "age", "dependents", "region_id",
                    "checking_account_id", "savings_account_id", "retired")
    }

    def enrichment(_context):
        return {
            "occupation": "marine engineer",
            "personality": {"analytical": 0.91, "gregarious": 0.25},
            "political_lean": -0.4,
            "media_diet": [20],
            "risk_tolerance": 0.72,
            # Engine-owned fields are ignored even when a provider proposes them.
            "name": "Provider Chosen",
            "age": 99,
            "wealth_cents": 999_999_999,
            "region_id": 999,
        }

    world.gateway.scripted.register("persona", enrichment)
    asyncio.run(world.runtime.enrich_pending_arrivals(1))
    updated = world.store.query_one("SELECT * FROM agents WHERE id=?", (agent_id,))

    assert updated["occupation"] == "marine engineer"
    assert json.loads(updated["personality_json"]) == {
        "analytical": 0.91, "gregarious": 0.25}
    assert float(updated["political_lean"]) == pytest.approx(-0.4)
    assert json.loads(updated["media_diet_json"]) == [20]
    assert float(updated["risk_tolerance"]) == pytest.approx(0.72)
    for key, expected in immutable.items():
        assert updated[key] == expected
    assert world.store.scalar(
        "SELECT COUNT(*) FROM llm_calls WHERE purpose='persona'", default=0) == 1
    world.store.close()


def test_malformed_persona_output_keeps_base_and_logs_fallback(tmp_path):
    world = _world(tmp_path, "fallback.db")
    arrival, _ = _spawn_one(world)
    agent_id = int(arrival["id"])
    original = {
        key: arrival[key]
        for key in ("occupation", "personality_json", "political_lean",
                    "media_diet_json", "risk_tolerance")
    }

    world.gateway.scripted.register("persona", lambda _context: {
        "occupation": "teacher",
        "personality": {"calm": 0.8},
        "political_lean": 0.1,
        "media_diet": [999],
        "risk_tolerance": 7.5,
    })
    asyncio.run(world.runtime.enrich_pending_arrivals(1))

    updated = world.store.query_one("SELECT * FROM agents WHERE id=?", (agent_id,))
    for key, expected in original.items():
        assert updated[key] == expected
    marker = world.store.query_one(
        "SELECT payload_json FROM events WHERE kind='persona_enrichment_fallback' "
        "AND subject_id=?", (agent_id,))
    payload = json.loads(marker["payload_json"])
    assert payload["reason"] == "invalid_risk_tolerance"
    assert "model_call_id" not in payload
    assert world.store.scalar(
        "SELECT COUNT(*) FROM llm_calls WHERE purpose='persona'", default=0) == 1
    world.store.close()


def test_semantics6_arrival_contract_remains_legacy(tmp_path, monkeypatch):
    world = _world(tmp_path, "legacy.db", semantics=6)
    monkeypatch.setattr("world.loop.sample_persona", lambda *_args, **_kwargs: Persona(
        name="Legacy Arrival", age=35, occupation="teacher",
        income_cents=1_000_000, wealth_cents=10_000,
        personality={"careful": 0.8}, risk_tolerance=0.2,
        political_lean=0.0, media_diet=[1], dependents=0))
    arrival, payload = _spawn_one(world)
    checking, source = _opening_delta(world.store, int(arrival["checking_account_id"]))

    assert arrival["savings_account_id"] is None
    assert "checking_cents" not in payload and "savings_cents" not in payload
    assert source == SYS_INFLOW
    assert arrival["population_tier"] == "periphery"
    assert int(arrival["pinned_core"]) == 0
    assert world.store.scalar(
        "SELECT COUNT(*) FROM llm_calls WHERE purpose='persona'", default=0) == 0
    # Legacy arrivals retain the old 60% checking-only endowment.
    assert checking == 6_000
    world.store.close()


@pytest.mark.parametrize(
    ("semantics", "expected_order"),
    [(6, ["decide"]), (7, ["enrich", "decide"])],
)
def test_world_gates_enrichment_before_morning_decisions(
        tmp_path, monkeypatch, semantics, expected_order):
    world = _world(tmp_path, f"order-{semantics}.db", semantics=semantics)
    order = []

    async def enrich(tick):
        assert tick == 1
        order.append("enrich")

    async def decide(tick):
        assert tick == 1
        order.append("decide")
        return []

    monkeypatch.setattr(world.runtime, "enrich_pending_arrivals", enrich)
    monkeypatch.setattr(world.runtime, "decide_all", decide)
    world.phases = ("MORNING",)
    world.store.set_meta(
        active_tick=1, next_phase="MORNING", phase="MORNING",
        phase_state_json="{}")
    asyncio.run(world.step())

    assert order == expected_order
    world.store.close()


def test_replay_missing_persona_response_fails_closed(tmp_path):
    source = _world(tmp_path, "source.db")
    _spawn_one(source)
    source_path = source.store.path
    source.store.close()

    replay = _world(tmp_path, "replay.db", replay_source=source_path)
    arrival, _ = _spawn_one(replay)
    with pytest.raises(ProviderUnavailable, match="stored response missing"):
        asyncio.run(replay.runtime.enrich_pending_arrivals(1))

    assert replay.store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind IN "
        "('persona_enriched','persona_enrichment_fallback') "
        "AND subject_id=?", (int(arrival["id"]),), default=0) == 0
    assert replay.store.scalar(
        "SELECT COUNT(*) FROM llm_calls WHERE purpose='persona'", default=0) == 0
    replay.gateway.replay_conn.close()
    replay.store.close()


def test_replay_consumes_recorded_persona_response(tmp_path):
    source = _world(tmp_path, "recorded-source.db")
    source_arrival, _ = _spawn_one(source)
    asyncio.run(source.runtime.enrich_pending_arrivals(1))
    source_agent = source.store.query_one(
        "SELECT occupation,personality_json,political_lean,media_diet_json,"
        "risk_tolerance FROM agents WHERE id=?", (int(source_arrival["id"]),))
    source_path = source.store.path
    source.store.close()

    replay = _world(tmp_path, "recorded-replay.db", replay_source=source_path)
    replay_arrival, _ = _spawn_one(replay)
    asyncio.run(replay.runtime.enrich_pending_arrivals(1))
    replay_agent = replay.store.query_one(
        "SELECT occupation,personality_json,political_lean,media_diet_json,"
        "risk_tolerance FROM agents WHERE id=?", (int(replay_arrival["id"]),))

    assert tuple(replay_agent) == tuple(source_agent)
    assert replay.store.scalar(
        "SELECT COUNT(*) FROM llm_calls WHERE role='persona' AND purpose='persona'",
        default=0) == 1
    assert replay.store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='persona_enriched'",
        default=0) == 1
    replay.gateway.replay_conn.close()
    replay.store.close()


def test_resumed_genesis_preserves_arrival_persona_and_exact_replay(tmp_path):
    source = _world(tmp_path, "resumed-source.db")
    config = source.config
    source_path = source.store.path
    persisted_state = json.loads(source.store.get_meta()["prng_state"])
    assert set(persisted_state) == {"engine", "persona"}
    source.close()

    resumed_store = Store(source_path)
    resumed = World(resumed_store, config)
    resumed.restore_prng_state()
    source_arrival, source_payload = _spawn_one(resumed)
    asyncio.run(resumed.runtime.enrich_pending_arrivals(1))
    source_engine_owned = tuple(source_arrival[key] for key in (
        "name", "age", "dependents", "region_id", "checking_account_id",
        "savings_account_id"))
    source_openings = (
        _opening_delta(resumed.store, int(source_arrival["checking_account_id"])),
        _opening_delta(resumed.store, int(source_arrival["savings_account_id"])),
    )
    resumed.store.commit()
    resumed.close()

    replay = _world(tmp_path, "resumed-replay.db", replay_source=source_path)
    replay_arrival, replay_payload = _spawn_one(replay)
    asyncio.run(replay.runtime.enrich_pending_arrivals(1))
    replay_engine_owned = tuple(replay_arrival[key] for key in (
        "name", "age", "dependents", "region_id", "checking_account_id",
        "savings_account_id"))
    replay_openings = (
        _opening_delta(replay.store, int(replay_arrival["checking_account_id"])),
        _opening_delta(replay.store, int(replay_arrival["savings_account_id"])),
    )
    tracker = replay.gateway.replay_execution_stats()

    assert replay_engine_owned == source_engine_owned
    assert replay_payload == source_payload
    assert replay_openings == source_openings
    assert tracker["exact_key_matches"] == 1
    assert tracker["compatibility_fallback_matches"] == 0
    replay.close()


def test_semantics1_through_6_keep_legacy_prng_state_shape(tmp_path):
    for semantics in range(1, 7):
        world = _world(
            tmp_path, f"legacy-prng-{semantics}.db", semantics=semantics)
        world._save_prng_state()
        state = json.loads(world.store.get_meta()["prng_state"])
        assert isinstance(state, list)
        assert len(state) == 3
        world.close()


def test_runtime_checkpoint_is_finalized_before_manifest(tmp_path):
    world = _world(tmp_path, "checkpoint-source.db")
    checkpoint = Path(world.checkpoint(0))

    assert checkpoint.is_file()
    assert not Path(f"{checkpoint}-wal").exists()
    assert not Path(f"{checkpoint}-shm").exists()
    assert Path(f"{checkpoint}.manifest.json").is_file()
    first = build_checkpoint_manifest(checkpoint)
    second = build_checkpoint_manifest(checkpoint)
    assert first == second
    assert not Path(f"{checkpoint}-wal").exists()
    assert not Path(f"{checkpoint}-shm").exists()
    with sqlite3.connect(str(checkpoint)) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    world.close()

"""LLM gateway, runtime, and external-agent gateway regressions from the 2026-09 review."""
from __future__ import annotations

import asyncio

import pytest

from agents.memory import Memory
from llm.gateway import Gateway, PriorityProviderGate, _transient_provider_error
from tests.conftest import make_agent, make_bank
from tests.test_external_agent_gateway import _connection, _world as _external_world


def test_provider_gate_returns_a_slot_granted_to_a_cancelled_waiter():
    async def scenario() -> PriorityProviderGate:
        gate = PriorityProviderGate(1)
        await gate.acquire(0)
        waiter = asyncio.create_task(gate.acquire(0))
        await asyncio.sleep(0)
        assert gate.queued == 1
        await gate.release()  # grants the waiter's future without resuming it
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
        return gate

    gate = asyncio.run(scenario())
    assert gate.active == 0
    assert gate.queued == 0


def test_transient_provider_error_classification():
    assert _transient_provider_error(TimeoutError())
    assert _transient_provider_error(ConnectionResetError())
    assert _transient_provider_error(RuntimeError("temporary provider outage"))
    assert not _transient_provider_error(KeyError("choices"))
    assert not _transient_provider_error(ValueError("bad json"))
    assert not _transient_provider_error(PermissionError("cli denied"))


def test_pricing_lookup_tolerates_missing_cache_rate():
    cached, cost = Gateway._price(None, "m", 1_000_000, 500_000, 250_000, {"in": 1.0, "out": 2.0})
    assert cached is True
    assert cost == pytest.approx(0.75 + 1.0)


def test_belief_updates_skip_malformed_entries(economy):
    bank_id = make_bank(economy)
    agent_id, _ = make_agent(economy, bank_id, name="Believer")
    memory = Memory(economy.store, economy.config)
    memory.apply_belief_updates(
        agent_id, ["optimistic", None, 3, {"key": "trust", "value": 0.4}], tick=1)
    row = economy.store.query_one(
        "SELECT value FROM beliefs WHERE agent_id=? AND key='trust'", (agent_id,))
    assert row is not None and float(row["value"]) == pytest.approx(0.4)


def test_turn_targets_the_next_wake_tick_of_the_connection(tmp_path):
    world = _external_world(tmp_path)
    try:
        service = world.runtime.external
        created = service.create_connection(
            tenant_id="tenant-a", owner_id="owner-a", display_name="Slow Founder",
            biography="Decides every third day.", preferred_occupation="builder",
            tier="actor", wake_interval_ticks=3)
        world._spawn_due_arrivals(1)
        auth = service.authenticate(created["credential"]["token"], rate_limit=False)
        turn = service.turn(auth)
        assert turn["target_tick"] == 3
        queued = service.submit_action(auth, {
            "target_tick": 3, "action": {"type": "do_nothing"},
            "observed_projection_hash": turn["projection_hash"],
            "idempotency_key": "wake-3"})
        assert queued["status"] == "queued"
        controlled, decisions = service.decisions_for_tick(3)
        assert controlled == {auth["actor_id"]}
        assert decisions[0]["purpose"] == "external_agent"
    finally:
        world.close()


def test_turn_skips_the_tick_whose_mailbox_already_closed(tmp_path):
    world = _external_world(tmp_path)
    try:
        service = world.runtime.external
        created = _connection(world)
        auth = service.authenticate(created["credential"]["token"], rate_limit=False)
        completed = world.store.tick
        world.store.set_meta(active_tick=completed + 1, next_phase="MORNING")
        turn = service.turn(auth)
        assert turn["target_tick"] == completed + 2
        world.store.set_meta(active_tick=None, next_phase="NIGHT_CLOSE")
        again = service.turn(auth)
        assert again["target_tick"] == completed + 1
    finally:
        world.close()


def test_morning_reentry_reuses_attendance_and_logs_one_fallback(tmp_path):
    world = _external_world(tmp_path, engine_semantics_version=14)
    try:
        service = world.runtime.external
        created = _connection(world)
        auth = service.authenticate(created["credential"]["token"], rate_limit=False)
        turn = service.turn(auth)
        target = int(turn["target_tick"])
        first_controlled, first = service.decisions_for_tick(target)
        assert first[0]["purpose"] == "external_safe_policy"
        # The lease expires between the two MORNING passes, which would change
        # the wall-clock derived reason and break the immutable attendance row.
        world.store.execute(
            "UPDATE external_agent_connections SET lease_expires_at='2000-01-01T00:00:00+00:00' "
            "WHERE id=?", (auth["id"],))
        second_controlled, second = service.decisions_for_tick(target)
        assert second_controlled == first_controlled
        assert second[0]["envelope"] == first[0]["envelope"]
        fallbacks = world.store.scalar(
            "SELECT COUNT(*) FROM events WHERE tick=? AND kind='external_agent_fallback'",
            (target,), default=0)
        assert fallbacks == 1
    finally:
        world.close()


def test_observe_hides_bank_balance_sheet_metrics_unless_granted(tmp_path):
    world = _external_world(tmp_path)
    try:
        service = world.runtime.external
        created = _connection(world)
        auth = service.authenticate(created["credential"]["token"], rate_limit=False)
        world.store.record_metric(0, "bank_deposits:1", 12345.0)
        world.store.record_metric(0, "bank_reserve_ratio:1", 0.42)
        world.store.record_metric(0, "cpi", 1.01)
        world.store.commit()
        service.config.setdefault("information", {})["citizen_bank_visibility"] = "public_status"
        metrics = service.observe(auth)["metrics"]
        assert "cpi" in metrics
        assert not any(name.startswith("bank_") for name in metrics)
        service.config["information"]["citizen_bank_visibility"] = "full_balance_sheet"
        assert "bank_deposits:1" in service.observe(auth)["metrics"]
    finally:
        world.close()


def test_rate_limit_windows_are_pruned(tmp_path):
    world = _external_world(tmp_path)
    try:
        service = world.runtime.external
        created = _connection(world)
        world.store.execute(
            "INSERT INTO external_rate_windows(connection_id,window_started_at,request_count) "
            "VALUES(?,?,?)", (created["connection"]["id"], "2000-01-01T00:00:00+00:00", 5))
        service.authenticate(created["credential"]["token"])
        stale = world.store.scalar(
            "SELECT COUNT(*) FROM external_rate_windows WHERE window_started_at LIKE '2000-%'",
            default=0)
        assert stale == 0
    finally:
        world.close()

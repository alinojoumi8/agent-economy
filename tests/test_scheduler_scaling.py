"""Bounded scheduler-query regressions for the 1,000-agent population path."""

import json

from agents.scheduler import Scheduler


def test_scheduler_batches_population_wake_state(store):
    for index in range(240):
        store.insert(
            "agents",
            name=f"Scale Agent {index:03d}",
            kind="citizen",
            occupation="worker",
            age=30,
            health="healthy",
            alive=1,
            retired=0,
            population_tier="periphery",
            cadence_json=json.dumps({"act": 997, "portfolio": 991, "career": 983}),
        )
    event_agent = int(store.scalar("SELECT id FROM agents ORDER BY id LIMIT 1"))
    store.insert(
        "memories",
        agent_id=event_agent,
        tick=9,
        kind="observation",
        text="A high-importance event occurred.",
        importance=3.0,
        entities_json="[]",
    )

    scheduler = Scheduler(store, {
        "engine_semantics_version": 7,
        "behavior": {"event_wake_importance": 2.0},
    })
    statements = []
    store.conn.set_trace_callback(statements.append)
    try:
        scheduled = scheduler.scheduled_agents(10)
    finally:
        store.conn.set_trace_callback(None)

    selects = [statement for statement in statements
               if statement.lstrip().upper().startswith("SELECT")]
    assert len(selects) <= 6
    assert event_agent in {int(agent["id"]) for agent in scheduled}
    assert not any("WHERE agent_id=" in statement for statement in selects)


def test_population_indexes_are_installed_after_semantics_columns(store):
    indexes = {row["name"] for row in store.query("PRAGMA index_list(agents)")}
    assert {"ix_agents_alive_tier", "ix_agents_region_alive"} <= indexes

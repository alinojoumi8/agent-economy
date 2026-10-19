"""Versioned, read-only population reconciliation for the stable scale profile."""
from __future__ import annotations

from collections import Counter, deque
from collections.abc import Mapping
import json
import sqlite3
from typing import Any


CONTRACT = "stable-lifecycle-v1"


def _require(condition: bool, error: str) -> None:
    if not condition:
        raise ValueError(error)


def _integer(value: object) -> bool:
    return type(value) is int and value >= 0


def _counts(agents: list[dict[str, Any]], regions: list[str]) -> dict[str, Any]:
    return {
        "agents": len(agents),
        "alive": sum(agent["alive"] == 1 for agent in agents),
        "citizen_kind": sum(agent["kind"] == "citizen" for agent in agents),
        "staff_kind": sum(agent["kind"] == "staff" for agent in agents),
        "core": sum(agent["population_tier"] == "core" for agent in agents),
        "periphery": sum(agent["population_tier"] == "periphery" for agent in agents),
        "regions": {region: sum(agent["region_key"] == region for agent in agents)
                    for region in regions},
    }


def stable_population_evidence(
    connection: sqlite3.Connection, ticks: int, config: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """Reconcile a semantics-7 stable cohort without changing historical v1/v2 gates.

    Dead rows remain scientific history. A replacement must be tied to a unique
    death schedule; only a replacement whose due tick is still future may be absent.
    Region migration is disabled by this contract. Tier journals reconstruct the
    initial cohort and prove subsequent promotions/demotions rather than treating
    final row counts as the original population.
    """
    regions = [str(row[0]) for row in connection.execute(
        "SELECT region_key FROM regions ORDER BY region_key")]
    agents = {row["id"]: dict(row) for row in connection.execute(
        "SELECT a.id,a.kind,a.alive,a.population_tier,a.arrived_tick,a.died_tick,"
        "r.region_key FROM agents a LEFT JOIN regions r ON r.id=a.region_id")}
    evidence: dict[str, Any] = {
        "contract": CONTRACT, "expected_initial": dict(expected),
        "observed": _counts(list(agents.values()), regions),
    }
    try:
        lifecycle = config.get("lifecycle", {})
        living_world = config.get("living_world", {})
        _require(isinstance(lifecycle, Mapping) and isinstance(living_world, Mapping)
                 and type(config.get("engine_semantics_version")) is int
                 and config.get("engine_semantics_version") == 7
                 and lifecycle.get("population_mode") == "stable"
                 and living_world.get("career_migration_enabled") is False,
                 "unsupported_demographic_policy")
        _require(_integer(ticks) and len(regions) == len(set(regions))
                 and set(regions) == set(expected["regions"]),
                 "invalid_horizon_or_regions")
        delay_min = lifecycle.get("arrival_delay_min", 5)
        delay_max = lifecycle.get("arrival_delay_max", 20)
        _require(_integer(delay_min) and _integer(delay_max) and delay_min <= delay_max,
                 "invalid_arrival_delay")
        for agent in agents.values():
            _require(_integer(agent["id"]) and agent["id"] > 0
                     and agent["kind"] in {"citizen", "staff"}
                     and agent["alive"] in {0, 1}
                     and agent["population_tier"] in {"core", "periphery"}
                     and agent["region_key"] in regions
                     and _integer(agent["arrived_tick"])
                     and agent["arrived_tick"] <= ticks, "invalid_agent_row")
            died = agent["died_tick"]
            _require((agent["alive"] == 1 and died is None)
                     or (agent["alive"] == 0 and _integer(died)
                         and agent["arrived_tick"] <= died <= ticks), "invalid_death_row")

        events = [dict(row) for row in connection.execute(
            "SELECT id,tick,kind,phase,subject_type,subject_id,payload_json FROM events "
            "WHERE kind IN ('genesis','death','arrival_scheduled','arrival',"
            "'arrival_cancelled','agent_tier_changed') ORDER BY id")]
        for event in events:
            _require(_integer(event["tick"]) and event["tick"] <= ticks
                     and event["phase"] == "NIGHT_CLOSE", "invalid_lifecycle_event")
            event["payload"] = json.loads(event.pop("payload_json"))
            _require(isinstance(event["payload"], dict), "invalid_lifecycle_payload")
            if event["kind"] in {"death", "arrival", "agent_tier_changed"}:
                agent_id = event["payload"].get("agent_id")
                _require(_integer(agent_id) and agent_id in agents
                         and event["subject_type"] == "agent"
                         and event["subject_id"] == agent_id, "invalid_agent_reference")
            else:
                _require(event["subject_type"] is None and event["subject_id"] is None,
                         "invalid_lifecycle_subject")

        genesis = [event for event in events if event["kind"] == "genesis"]
        _require(len(genesis) == 1 and genesis[0]["tick"] == 0
                 and type(genesis[0]["payload"].get("agents")) is int
                 and genesis[0]["payload"]["agents"] == expected["agents"], "invalid_genesis")

        initial_tiers = {agent_id: agent["population_tier"] for agent_id, agent in agents.items()}
        for event in reversed(events):
            if event["kind"] != "agent_tier_changed" or event["tick"] == 0:
                continue
            payload = event["payload"]
            agent_id = payload["agent_id"]
            old, new = payload.get("old_tier"), payload.get("new_tier")
            agent = agents[agent_id]
            _require(old in {"core", "periphery"} and new in {"core", "periphery"}
                     and old != new and initial_tiers[agent_id] == new
                     and agent["arrived_tick"] <= event["tick"]
                     and (agent["died_tick"] is None or event["tick"] <= agent["died_tick"]),
                     "invalid_tier_history")
            initial_tiers[agent_id] = old
        initial = [{**agent, "alive": 1, "population_tier": initial_tiers[agent_id]}
                   for agent_id, agent in agents.items() if agent["arrived_tick"] == 0]
        evidence["initial"] = _counts(initial, regions)
        _require(evidence["initial"] == expected, "initial_cohort_mismatch")

        deaths: dict[int, dict[str, Any]] = {}
        unscheduled: deque[dict[str, Any]] = deque()
        schedules: dict[int, dict[str, Any]] = {}
        arrivals: dict[int, int] = {}
        used_schedules: set[int] = set()
        for event in events:
            kind, payload, tick = event["kind"], event["payload"], event["tick"]
            if kind == "death":
                agent_id = payload["agent_id"]
                _require(agent_id not in deaths and agents[agent_id]["died_tick"] == tick,
                         "missing_or_duplicate_death")
                deaths[agent_id] = event
                unscheduled.append(event)
            elif kind == "arrival_scheduled":
                due = payload.get("due_tick")
                _require(bool(unscheduled) and unscheduled[0]["tick"] == tick
                         and _integer(due) and tick + delay_min <= due <= tick + delay_max,
                         "unexplained_replacement_schedule")
                schedules[event["id"]] = {"due": due, "death": unscheduled.popleft()}
            elif kind == "arrival":
                agent_id, schedule_id = payload["agent_id"], payload.get("schedule_event_id")
                agent = agents[agent_id]
                _require(_integer(schedule_id) and schedule_id in schedules
                         and schedule_id not in used_schedules and agent_id not in arrivals
                         and tick == agent["arrived_tick"] and tick > 0
                         and schedules[schedule_id]["due"] <= tick
                         and agent["kind"] == "citizen" and initial_tiers[agent_id] == "periphery",
                         "unexplained_or_duplicate_arrival")
                used_schedules.add(schedule_id)
                arrivals[agent_id] = schedule_id
            elif kind == "arrival_cancelled":
                raise ValueError("unexpected_cancelled_replacement")
        _require(not unscheduled, "death_without_replacement_schedule")
        _require(set(deaths) == {agent_id for agent_id, agent in agents.items() if not agent["alive"]},
                 "death_history_mismatch")
        _require(set(arrivals) == {agent_id for agent_id, agent in agents.items() if agent["arrived_tick"] > 0},
                 "arrival_history_mismatch")
        pending = [schedule for event_id, schedule in schedules.items() if event_id not in used_schedules]
        _require(all(schedule["due"] > ticks for schedule in pending), "overdue_replacement")

        living = [agent for agent in agents.values() if agent["alive"]]
        evidence.update(living=_counts(living, regions), deaths=len(deaths), arrivals=len(arrivals),
                        pending_replacements=len(pending))
        expected_regions = Counter(expected["regions"])
        expected_kinds = Counter(citizen=expected["citizen_kind"], staff=expected["staff_kind"])
        for agent_id in deaths:
            expected_regions[agents[agent_id]["region_key"]] -= 1
            expected_kinds[agents[agent_id]["kind"]] -= 1
        for agent_id in arrivals:
            expected_regions[agents[agent_id]["region_key"]] += 1
            expected_kinds["citizen"] += 1
        _require(len(living) == expected["alive"] - len(pending)
                 and evidence["living"]["regions"] == dict(expected_regions)
                 and evidence["living"]["citizen_kind"] == expected_kinds["citizen"]
                 and evidence["living"]["staff_kind"] == expected_kinds["staff"],
                 "living_cohort_mismatch")
    except (ValueError, TypeError, KeyError) as error:
        evidence["error"] = str(error) if isinstance(error, ValueError) else "invalid_population_evidence"
        return False, evidence
    return True, evidence

"""Versioned local activity eligibility; never use this to filter asset owners."""
from .population_history import ResidenceError


def is_local(institution, agent_id: int, *, tick: int | None = None) -> bool:
    if institution.engine_semantics_version < 21:
        return True
    population = getattr(institution, "population", None)
    if population is None:
        raise ResidenceError("local participation requires population history")
    if tick is None:
        return population.is_available(agent_id)
    return population.is_local(agent_id, tick)


def departed_after(institution, agent_id: int, event_frontier: int) -> bool:
    """A prior departure invalidates local consent even after the person returns."""
    if institution.engine_semantics_version < 21:
        return False
    return bool(institution.store.query_one(
        "SELECT 1 FROM person_residence_events WHERE agent_id=? AND cause='departure' "
        "AND event_id>? LIMIT 1", (agent_id, event_frontier)))


def residence_changed_after(institution, agent_id: int, event_frontier: int) -> bool:
    """A return-only or local action window cannot cross a residence change."""
    if institution.engine_semantics_version < 21:
        return False
    return bool(institution.store.query_one(
        "SELECT 1 FROM person_residence_events WHERE agent_id=? AND cause IN ('departure','return') "
        "AND event_id>? LIMIT 1", (agent_id, event_frontier)))

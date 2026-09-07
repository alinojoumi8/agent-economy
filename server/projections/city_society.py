"""Read-only city lenses over recorded household and public bank identities.

The household lens uses core identities only, irrespective of map population
mode. It does not publish accounts, exact residences, or private relationship
payloads. Current mutable age/stage/household region fields are never history.
"""
from __future__ import annotations

from .envelope import semantics_version


def build_city_households(store, *, as_of_tick: int) -> dict:
    tick = int(as_of_tick)
    result = {"available": semantics_version(store) >= 15,
              "source": "recorded_household_membership", "tick": tick,
              "visibility": "core_members_only", "items": []}
    if not result["available"]:
        result["reason"] = "This run predates persistent household identities."
        return result
    rows = store.query(
        "SELECT h.id,h.formed_tick,h.policy,m.agent_id,m.role,m.joined_tick,"
        "a.name,p.birth_tick,p.origin,p.origin_tick,p.legacy_dependents "
        "FROM households h JOIN household_memberships m ON m.household_id=h.id "
        "JOIN person_lifecycle p ON p.agent_id=m.agent_id "
        "JOIN agents a ON a.id=m.agent_id "
        "WHERE h.formed_tick<=? AND (h.dissolved_tick IS NULL OR h.dissolved_tick>?) "
        "AND m.joined_tick<=? AND (m.left_tick IS NULL OR m.left_tick>?) "
        "AND p.origin_tick<=? AND (p.death_tick IS NULL OR p.death_tick>?) "
        "AND a.arrived_tick<=? AND (a.died_tick IS NULL OR a.died_tick>?) "
        "AND (a.population_tier='core' OR COALESCE(a.pinned_core,0)=1) "
        "ORDER BY h.id,m.agent_id", (tick,) * 8)
    groups: dict[int, dict] = {}
    members: dict[int, dict] = {}
    membership: dict[int, int] = {}
    for row in rows:
        household_id, agent_id = int(row["id"]), int(row["agent_id"])
        group = groups.setdefault(household_id, {
            "id": household_id, "name": f"Household #{household_id}",
            "formed_tick": int(row["formed_tick"]), "policy": row["policy"],
            "members": [], "child_needs": [],
        })
        age = (tick - int(row["birth_tick"])) // 365
        member = {"agent_id": agent_id, "name": row["name"], "age_years": age,
                  "age_band": "child" if age < 6 else "school_age" if age < 18 else "adult",
                  "role": row["role"], "joined_tick": int(row["joined_tick"]),
                  "origin": row["origin"], "origin_tick": int(row["origin_tick"]),
                  "legacy_dependents": int(row["legacy_dependents"]),
                  "guardian_agent_id": None}
        group["members"].append(member)
        members[agent_id] = member
        membership[agent_id] = household_id
    # Filter both ends: a visible child cannot reveal a peripheral guardian.
    for row in store.query(
            "SELECT child_agent_id,guardian_agent_id FROM guardianships "
            "WHERE started_tick<=? AND (ended_tick IS NULL OR ended_tick>?) "
            "ORDER BY child_agent_id", (tick, tick)):
        child, guardian = int(row["child_agent_id"]), int(row["guardian_agent_id"])
        if child in members and guardian in members:
            members[child]["guardian_agent_id"] = guardian
    for row in store.query(
            "SELECT household_id,child_agent_id,currency_code,goods_sector,required_units,"
            "purchased_units,spent_cents,care_required_minutes,care_status "
            "FROM child_needs WHERE tick=? ORDER BY household_id,child_agent_id", (tick,)):
        household_id, child = int(row["household_id"]), int(row["child_agent_id"])
        if household_id in groups and membership.get(child) == household_id:
            groups[household_id]["child_needs"].append({
                key: row[key] for key in (
                    "child_agent_id", "currency_code", "goods_sector", "required_units",
                    "purchased_units", "spent_cents", "care_required_minutes", "care_status")})
    result["items"] = list(groups.values())
    return result


def build_city_institutions(store, *, as_of_tick: int) -> dict:
    """Banks are genesis identities; expose their as-of public status only."""
    tick = int(as_of_tick)
    items = []
    for row in store.query(
            "SELECT id,name,failed_tick,currency_code FROM banks ORDER BY id"):
        bank_id = int(row["id"])
        items.append({"id": f"bank:{bank_id}", "bank_id": bank_id, "kind": "bank",
                      "name": row["name"], "currency_code": row["currency_code"],
                      "status": "failed" if row["failed_tick"] is not None
                      and int(row["failed_tick"]) <= tick else "open"})
    return {"available": True, "source": "public_bank_status", "tick": tick,
            "visibility": "public_status_only", "items": items}

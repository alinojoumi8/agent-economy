"""Historical-safe public projections for Semantics-13 construction."""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from engine.business_control import operated_firms_at
from engine.estate_assets import residual_people_at
from engine.project_rights import interests_at, rights_enabled, steward_at


CONSTRUCTION_KINDS = frozenset({
    "private_home", "workplace", "public_facility",
})
CONSTRUCTION_STATUSES = frozenset({
    "proposed", "permitting", "funding", "building", "completed", "cancelled",
})


def _dict(row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _public_person(store, person, tick):
    if person is None:
        return None
    return store.query_one("SELECT a.id,a.name FROM agents a LEFT JOIN person_lifecycle p ON p.agent_id=a.id "
        "WHERE a.id=? AND COALESCE(p.origin_tick,a.arrived_tick,0)<=? AND (a.pinned_core=1 OR COALESCE("
        "(SELECT h.old_tier FROM agent_tier_history h WHERE h.agent_id=a.id AND h.tick>? ORDER BY h.tick,h.id LIMIT 1),"
        "a.population_tier)='core')", (person, tick, tick))


def redact_hidden_home_locations(store, agents, hidden_homes):
    """Keep a withheld home's identity and coordinates out of sibling layers."""
    if not hidden_homes:
        return
    regions = {row["id"]: row for row in store.query("SELECT id,x,y FROM regions")}
    for agent in agents:
        if agent.get("place_id") in hidden_homes:
            region = regions.get(agent.get("region_id"))
            agent.update(place_id=None, place_name=None,
                         x=region["x"] if region else None,
                         y=region["y"] if region else None)


def _ownership(store, project, tick):
    shares = interests_at(store, project["id"], tick, enabled=True)
    steward = steward_at(store, project["id"], tick, enabled=True)
    identities = {project["owner_id"], *(share["agent_id"] for share in shares)}
    for share in shares:
        if share.get("estate_custody"):
            identities.update(residual_people_at(store, share["estate_id"], tick))
    if steward:
        identities.add(steward["steward_agent_id"])
        identities.add(steward["beneficiary_id"])
    public = {person: _public_person(store, person, tick) for person in identities if person is not None}
    if any(person is None for person in public.values()):
        return None
    owners = [{**share, "name": (("Estate of " if share.get("estate_custody") else "") + public[share["agent_id"]]["name"])
               if share["agent_id"] is not None else "System estate custody"} for share in shares]
    operator = None
    if steward and steward["steward_agent_id"] is not None:
        operator = {"agent_id": steward["steward_agent_id"], "name": public[steward["steward_agent_id"]]["name"],
                    "capacity": steward["capacity"], "beneficiary_id": steward["beneficiary_id"], "started_tick": steward["started_tick"],
                    **({"estate_id": steward["estate_id"]} if steward.get("estate_id") is not None else {}),
                    **({"administration_id": steward["administration_id"]} if steward.get("administration_id") is not None else {})}
    return {"policy": "estate_project_interests_v1", "owners": owners, "operator": operator,
        "original_owner": {"type": "agent", "id": project["owner_id"], "name": public[project["owner_id"]]["name"]},
        "updated_tick": max([project["proposed_tick"], *(share["updated_tick"] for share in shares),
                             steward["started_tick"] if steward else 0])}


def _stage(work_units: int, required: int) -> str:
    work = max(0, int(work_units))
    target = max(1, int(required))
    if work >= target:
        return "completed"
    if work >= (2 * target + 2) // 3:
        return "shell"
    if work >= (target + 2) // 3:
        return "frame"
    return "foundation"


def _status_at(row: dict[str, Any], tick: int) -> str:
    if row.get("cancelled_tick") is not None and int(
            row["cancelled_tick"]) <= tick:
        return "cancelled"
    if row.get("completed_tick") is not None and int(
            row["completed_tick"]) <= tick:
        return "completed"
    if row.get("building_tick") is not None and int(
            row["building_tick"]) <= tick:
        return "building"
    if row.get("funding_tick") is not None and int(
            row["funding_tick"]) <= tick:
        return "funding"
    if row.get("permitting_tick") is not None and int(
            row["permitting_tick"]) <= tick:
        return "permitting"
    return "proposed"


def _safe_event_refs(store, ids: list[int], tick: int) -> list[dict[str, Any]]:
    clean = sorted({int(value) for value in ids if int(value) > 0})
    if not clean:
        return []
    placeholders = ",".join("?" for _ in clean)
    return [
        {
            "kind": "event",
            "id": int(row["id"]),
            "tick": int(row["tick"]),
            "event_kind": str(row["kind"]),
        }
        for row in store.query(
            f"SELECT id,tick,kind FROM events WHERE id IN ({placeholders}) "
            "AND tick<=? ORDER BY tick,id",
            (*clean, int(tick)),
        )
    ]


def _milestones(row: dict[str, Any], tick: int) -> list[dict[str, Any]]:
    values = [
        ("proposed", row.get("proposed_tick"), row.get("proposed_event_id")),
        ("permitting", row.get("permitting_tick"), None),
        ("funding", row.get("funding_tick"), row.get("permit_event_id")),
        ("foundation", row.get("foundation_tick"), None),
        ("frame", row.get("frame_tick"), None),
        ("shell", row.get("shell_tick"), None),
        ("completed", row.get("completed_tick"), row.get("completion_event_id")),
        ("cancelled", row.get("cancelled_tick"), row.get("cancellation_event_id")),
    ]
    return [
        {
            "stage": name,
            "tick": int(value),
            "evidence_ref": (
                {"kind": "event", "id": int(event_id), "tick": int(value)}
                if event_id is not None else None
            ),
        }
        for name, value, event_id in values
        if value is not None and int(value) <= int(tick)
    ]


def _raw_projects(store, tick: int) -> list[dict[str, Any]]:
    succession = rights_enabled(store)
    rows = [
        _dict(row) for row in store.query(
            "SELECT p.*,r.name AS region_name,r.x AS region_x,r.y AS region_y,"
            "a.name AS initiator_name,o.name AS agent_owner_name,"
            "COALESCE((SELECT h.old_tier FROM agent_tier_history h "
            " WHERE h.agent_id=o.id AND h.tick>? ORDER BY h.tick,h.id LIMIT 1),"
            " o.population_tier) AS owner_population_tier,"
            "COALESCE(o.pinned_core,0) AS owner_pinned_core,"
            "f.name AS firm_owner_name,ag.name AS agency_owner_name,"
            "pc.status AS permit_current_status,pc.created_tick AS permit_created_tick,"
            "pc.decided_tick AS permit_decided_tick "
            "FROM construction_projects p "
            "JOIN regions r ON r.id=p.region_id "
            "JOIN agents a ON a.id=p.initiator_agent_id "
            "LEFT JOIN agents o ON p.owner_type='agent' AND o.id=p.owner_id "
            "LEFT JOIN firms f ON p.owner_type='firm' AND f.id=p.owner_id "
            "LEFT JOIN agencies ag ON p.owner_type='agency' AND ag.id=p.owner_id "
            "LEFT JOIN construction_permit_cases pc ON pc.id=p.permit_case_id "
            "WHERE p.proposed_tick<=? ORDER BY p.proposed_tick,p.id",
            (int(tick), int(tick)),
        )
    ]
    if not rows:
        return []
    project_ids = [int(row["id"]) for row in rows]
    placeholders = ",".join("?" for _ in project_ids)
    totals = {
        int(row["project_id"]): _dict(row)
        for row in store.query(
            "SELECT project_id,"
            "COALESCE(SUM(CASE WHEN contribution_type='funding' "
            "THEN amount_cents ELSE 0 END),0) AS funding_cents,"
            "COALESCE(SUM(CASE WHEN contribution_type='work' "
            "THEN work_units ELSE 0 END),0) AS work_units,"
            "COALESCE(SUM(CASE WHEN contribution_type='refund' "
            "THEN amount_cents ELSE 0 END),0) AS refund_cents,"
            "COALESCE(SUM(CASE WHEN contribution_type='work' THEN "
            "COALESCE(CAST(json_extract(metadata_json,'$.wage_cents') AS INTEGER),0)"
            "+COALESCE(CAST(json_extract(metadata_json,'$.procurement_cents') "
            "AS INTEGER),0) ELSE 0 END),0) AS spent_cents,"
            "COUNT(CASE WHEN contribution_type='funding' THEN 1 END) "
            "AS funding_contributions,"
            "COUNT(CASE WHEN contribution_type='work' THEN 1 END) "
            "AS work_contributions,"
            "MAX(tick) AS contribution_tick "
            f"FROM construction_contributions WHERE project_id IN ({placeholders}) "
            "AND tick<=? GROUP BY project_id",
            (*project_ids, int(tick)),
        )
    }
    output: list[dict[str, Any]] = []
    for row in rows:
        aggregate = totals.get(int(row["id"]), {})
        funding = int(aggregate.get("funding_cents") or 0)
        work = int(aggregate.get("work_units") or 0)
        refunds = int(aggregate.get("refund_cents") or 0)
        status = _status_at(row, int(tick))
        stage = (
            "completed" if status == "completed"
            else _stage(work, int(row["required_work_units"]))
            if status == "building" or (status == "cancelled" and work > 0)
            else None
        )
        event_ids: list[int] = []
        for field in (
            "proposed_event_id", "permit_event_id",
            "completion_event_id", "cancellation_event_id",
        ):
            if row.get(field) is not None:
                event_ids.append(int(row[field]))
        try:
            event_ids.extend(
                int(value) for value in json.loads(
                    str(row.get("evidence_refs_json") or "[]")))
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
        milestones = _milestones(row, int(tick))
        updated_tick = max([
            int(row["proposed_tick"]),
            *[int(item["tick"]) for item in milestones],
            int(aggregate.get("contribution_tick") or row["proposed_tick"]),
        ])
        is_core_home = (
            str(row["target_place_type"]) == "private_home"
            and (
                str(row.get("owner_population_tier") or "") == "core"
                or bool(row.get("owner_pinned_core"))
            )
        )
        ownership = _ownership(store, row, int(tick)) if succession and row["owner_type"] == "agent" else None
        if succession and row["owner_type"] == "agent":
            is_core_home = is_core_home and ownership is not None
            if ownership is not None:
                updated_tick = max(updated_tick, ownership["updated_tick"])
        exact = (
            str(row["target_place_type"]) != "private_home" or is_core_home)
        owner_name = (
            row.get("agent_owner_name")
            if row["owner_type"] == "agent"
            else row.get("firm_owner_name")
            if row["owner_type"] == "firm"
            else row.get("agency_owner_name")
        )
        owner = {"type": str(row["owner_type"]), "id": int(row["owner_id"]), "name": str(owner_name or "")}
        if ownership is not None:
            owners = ownership["owners"]
            owner = ({"type": "agent", "id": owners[0]["agent_id"], "name": owners[0]["name"]}
                     if len(owners) == 1 and owners[0]["agent_id"] is not None else None)
        permit_status = None
        if (
            row.get("permit_created_tick") is not None
            and int(row["permit_created_tick"]) <= int(tick)
        ):
            permit_status = (
                str(row["permit_current_status"])
                if (
                    row.get("permit_decided_tick") is not None
                    and int(row["permit_decided_tick"]) <= int(tick)
                )
                else "submitted"
            )
        place_id = (
            int(row["place_id"])
            if row.get("place_id") is not None and status == "completed"
            else None
        )
        output.append({
            "project_id": int(row["id"]),
            "project_key": str(row["project_key"]),
            "name": str(row["name"]),
            "target_place_type": str(row["target_place_type"]),
            "status": status,
            "stage": stage,
            "owner": owner if exact else None,
            **({"ownership": ownership} if exact and ownership is not None else {}),
            "initiator_agent_id": (
                int(row["initiator_agent_id"]) if exact else None),
            "region": {
                "id": int(row["region_id"]),
                "name": str(row["region_name"]),
                "x": float(row["region_x"]),
                "y": float(row["region_y"]),
            },
            "site": {
                "site_key": str(row["site_key"]),
                "x": float(row["site_x"]),
                "y": float(row["site_y"]),
            } if exact else None,
            "place_id": place_id if exact else None,
            "permit": {
                "case_id": int(row["permit_case_id"]),
                "status": permit_status,
            } if exact and row.get("permit_case_id") is not None else None,
            "requirements": {
                "funding_cents": int(row["required_funding_cents"]),
                "work_units": int(row["required_work_units"]),
            },
            "contributed": {
                "funding_cents": funding,
                "work_units": work,
                "funding_contributions": int(
                    aggregate.get("funding_contributions") or 0),
                "work_contributions": int(
                    aggregate.get("work_contributions") or 0),
            },
            "settlement": {
                "spent_cents": int(aggregate.get("spent_cents") or 0),
                "refunded_cents": refunds,
            },
            "milestones": milestones,
            "milestone_count": len(milestones),
            "proposed_tick": int(row["proposed_tick"]),
            "updated_tick": updated_tick,
            "completed_tick": (
                int(row["completed_tick"])
                if row.get("completed_tick") is not None
                and int(row["completed_tick"]) <= int(tick) else None),
            "cancelled_tick": (
                int(row["cancelled_tick"])
                if row.get("cancelled_tick") is not None
                and int(row["cancelled_tick"]) <= int(tick) else None),
            "evidence_refs": _safe_event_refs(store, event_ids, int(tick)),
            "privacy": "public" if exact else "peripheral_private",
        })
    return output


def construction_projects_as_of(
    store, *, as_of_tick: int,
) -> list[dict[str, Any]]:
    """Return exact public/core projects plus safe regional home aggregates."""
    raw = _raw_projects(store, int(as_of_tick))
    exact: list[dict[str, Any]] = []
    hidden: dict[tuple[int, str, str | None], list[dict[str, Any]]] = defaultdict(list)
    for item in raw:
        if item["privacy"] != "peripheral_private":
            exact.append(item)
        else:
            key = (
                int(item["region"]["id"]),
                str(item["status"]),
                str(item["stage"]) if item["stage"] is not None else None,
            )
            hidden[key].append(item)
    aggregates: list[dict[str, Any]] = []
    for (region_id, status, stage), items in sorted(hidden.items()):
        region = items[0]["region"]
        count = len(items)
        aggregate_id = (
            f"private-homes:region:{region_id}:{status}:{stage or 'not-building'}")
        aggregates.append({
            "project_id": aggregate_id,
            "project_key": aggregate_id,
            "name": f"Private home construction in {region['name']}",
            "target_place_type": "private_home",
            "status": status,
            "stage": stage,
            "owner": None,
            "initiator_agent_id": None,
            "region": region,
            "site": {
                "site_key": f"region:{region_id}:residential-aggregate",
                "x": float(region["x"]),
                "y": float(region["y"]),
            },
            "place_id": None,
            "permit": None,
            "requirements": {
                "funding_cents": sum(
                    int(item["requirements"]["funding_cents"]) for item in items),
                "work_units": sum(
                    int(item["requirements"]["work_units"]) for item in items),
            },
            "contributed": {
                "funding_cents": sum(
                    int(item["contributed"]["funding_cents"]) for item in items),
                "work_units": sum(
                    int(item["contributed"]["work_units"]) for item in items),
                "funding_contributions": sum(
                    int(item["contributed"]["funding_contributions"])
                    for item in items),
                "work_contributions": sum(
                    int(item["contributed"]["work_contributions"])
                    for item in items),
            },
            "settlement": {
                "spent_cents": sum(
                    int(item["settlement"]["spent_cents"]) for item in items),
                "refunded_cents": sum(
                    int(item["settlement"]["refunded_cents"]) for item in items),
            },
            "milestones": [],
            "milestone_count": sum(
                int(item["milestone_count"]) for item in items),
            "proposed_tick": min(int(item["proposed_tick"]) for item in items),
            "updated_tick": max(int(item["updated_tick"]) for item in items),
            "completed_tick": None,
            "cancelled_tick": None,
            "evidence_refs": [],
            "privacy": "aggregated_private",
            "aggregate_count": count,
        })
    return sorted(
        [*exact, *aggregates],
        key=lambda item: (-int(item["updated_tick"]), str(item["project_id"])),
    )


def build_construction_projects(
    store, *, as_of_tick: int, project_kind: str = "all",
    status: str = "all", after: int = 0, limit: int = 100,
) -> dict[str, Any]:
    projects = construction_projects_as_of(store, as_of_tick=int(as_of_tick))
    filtered = [
        item for item in projects
        if (project_kind == "all" or item["target_place_type"] == project_kind)
        and (status == "all" or item["status"] == status)
    ]
    offset = max(0, int(after))
    page_limit = max(1, min(200, int(limit)))
    page = filtered[offset:offset + page_limit]
    next_cursor = (
        offset + len(page) if offset + len(page) < len(filtered) else None)
    return {
        "summary": {
            "tick": int(as_of_tick),
            "projects_total": len(filtered),
            "active_projects": sum(
                item["status"] not in {"completed", "cancelled"}
                for item in filtered),
            "completed_projects": sum(
                item["status"] == "completed" for item in filtered),
            "cancelled_projects": sum(
                item["status"] == "cancelled" for item in filtered),
            "private_home_aggregates": sum(
                item["privacy"] == "aggregated_private" for item in filtered),
        },
        "projects": {
            "items": page,
            "next_cursor": next_cursor,
            "total": len(filtered),
            "cursor_kind": "offset",
        },
        "stage_contract": {
            "sequence": ["foundation", "frame", "shell", "completed"],
            "measurement": "stored_work_units",
            "percentages_invented": False,
        },
        "privacy": {
            "peripheral_private_homes": "aggregated_by_region_status_and_stage",
            "reversible_private_links_omitted": True,
        },
    }


def build_construction_project_detail(
    store, *, project_id: str, as_of_tick: int,
) -> dict[str, Any] | None:
    project = next(
        (
            item for item in construction_projects_as_of(
                store, as_of_tick=int(as_of_tick))
            if str(item["project_id"]) == str(project_id)
        ),
        None,
    )
    if project is None:
        return None
    contributions = []
    if isinstance(project["project_id"], int):
        contributions = [
            {
                "type": str(row["contribution_type"]),
                "count": int(row["count"]),
                "amount_cents": int(row["amount_cents"] or 0),
                "work_units": int(row["work_units"] or 0),
                "latest_tick": int(row["latest_tick"]),
            }
            for row in store.query(
                "SELECT contribution_type,COUNT(*) AS count,"
                "COALESCE(SUM(amount_cents),0) AS amount_cents,"
                "COALESCE(SUM(work_units),0) AS work_units,"
                "MAX(tick) AS latest_tick FROM construction_contributions "
                "WHERE project_id=? AND tick<=? GROUP BY contribution_type "
                "ORDER BY contribution_type",
                (int(project["project_id"]), int(as_of_tick)),
            )
        ]
    return {
        "project": project,
        "contribution_summary": contributions,
        "stage_contract": {
            "foundation": "building has begun below one third of required work",
            "frame": "at least one third of required work is stored",
            "shell": "at least two thirds of required work is stored",
            "completed": "all required work is stored and the place was created",
        },
        "privacy": {
            "individual_contributors_omitted": True,
            "peripheral_private_homes": "aggregate_only",
        },
    }


def construction_projects_for_agent(
    store, *, agent_id: int, as_of_tick: int, visible_projects=None,
) -> list[dict[str, Any]]:
    """Return projects safely attributable to one selected agent."""
    visible = (construction_projects_as_of(store, as_of_tick=int(as_of_tick))
               if visible_projects is None else visible_projects)
    contributed = {
        int(row["project_id"])
        for row in store.query(
            "SELECT DISTINCT project_id FROM construction_contributions "
            "WHERE actor_agent_id=? AND tick<=?",
            (int(agent_id), int(as_of_tick)),
        )
    }
    founded_firms = {
        int(row["id"]) for row in operated_firms_at(store, int(agent_id), int(as_of_tick))
    }
    staffed_agencies = {
        int(row["agency_id"]) for row in store.query(
            "SELECT agency_id FROM agency_staff WHERE agent_id=? "
            "AND effective_tick<=? AND (ended_tick IS NULL OR ended_tick>?)",
            (int(agent_id), int(as_of_tick), int(as_of_tick)),
        )
    }
    selected = []
    for item in visible:
        if not isinstance(item["project_id"], int):
            continue
        owner = item.get("owner") or {}
        owns = (
            owner.get("type") == "agent"
            and int(owner.get("id") or 0) == int(agent_id)
        ) or (
            owner.get("type") == "firm"
            and int(owner.get("id") or 0) in founded_firms
        ) or (
            owner.get("type") == "agency"
            and int(owner.get("id") or 0) in staffed_agencies
        )
        ownership = item.get("ownership")
        if ownership is not None:
            owns = any(person["agent_id"] == int(agent_id) for person in ownership["owners"]) or (
                ownership["operator"] is not None and ownership["operator"]["agent_id"] == int(agent_id))
        if owns or int(item["project_id"]) in contributed:
            selected.append(item)
    return selected


def hidden_home_place_ids(store, tick, visible_projects=None):
    """A hidden inherited home's site must not leak through its place/lease."""
    if not rights_enabled(store):
        return set()
    visible = construction_projects_as_of(store, as_of_tick=tick) if visible_projects is None else visible_projects
    allowed = {item["place_id"] for item in visible if item.get("place_id") is not None}
    return {row["place_id"] for row in store.query("SELECT place_id FROM construction_projects "
        "WHERE target_place_type='private_home' AND place_id IS NOT NULL AND completed_tick<=?", (tick,))} - allowed

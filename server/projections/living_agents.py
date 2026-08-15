"""Historical-safe Living Agents projections for ordinary observers."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .workspaces import _agent_regions_at, _balances_as_of, _dicts


PROJECT_KINDS = frozenset({
    "employment",
    "skill",
    "firm",
    "civic_case",
    "migration",
    "residence",
    "workplace",
    "public_output",
})
PROJECT_STATUSES = frozenset({"active", "completed", "cancelled"})


def _evidence(kind: str, record_id: int | str, tick: int) -> dict[str, Any]:
    return {"kind": kind, "id": record_id, "tick": int(tick)}


def _project(
    *, project_id: str, kind: str, title: str, owner_agent_id: int | None,
    stage: str, status: str, started_tick: int, updated_tick: int,
    milestone_count: int, evidence_refs: list[dict[str, Any]],
    completed_tick: int | None = None, source: str = "committed",
    organization: dict[str, Any] | None = None,
    place: dict[str, Any] | None = None,
    region: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    privacy: str = "public",
) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "kind": kind,
        "title": title,
        "owner_agent_id": owner_agent_id,
        "stage": stage,
        "status": status,
        "started_tick": int(started_tick),
        "updated_tick": int(updated_tick),
        "completed_tick": int(completed_tick) if completed_tick is not None else None,
        "milestone_count": int(milestone_count),
        "source": source,
        "evidence_refs": evidence_refs,
        "organization": organization,
        "place": place,
        "region": region,
        "metrics": metrics or {},
        "privacy": privacy,
    }


def _activity(
    *, activity_id: str, tick: int, kind: str, stage: str, title: str,
    agent_id: int | None, source: str, evidence_ref: dict[str, Any],
    project_id: str | None = None,
) -> dict[str, Any]:
    return {
        "activity_id": activity_id,
        "tick": int(tick),
        "kind": kind,
        "stage": stage,
        "title": title,
        "agent_id": agent_id,
        "project_id": project_id,
        "source": source,
        "evidence_ref": evidence_ref,
    }


def _runtime_by_agent(runtime: list[dict[str, Any]] | None) -> dict[int, dict[str, Any]]:
    safe: dict[int, dict[str, Any]] = {}
    for item in runtime or []:
        try:
            agent_id = int(item["agent_id"])
        except (KeyError, TypeError, ValueError):
            continue
        # active_agent_status is already bounded by the gateway. Keep a second
        # explicit allowlist here so future telemetry fields cannot drift into
        # this ordinary-observer projection.
        safe[agent_id] = {
            "state": str(item.get("state") or "active"),
            "active_calls": max(0, int(item.get("active_calls") or 0)),
            "tick": int(item["tick"]) if item.get("tick") is not None else None,
            "oldest_elapsed_ms": (
                max(0, int(item["oldest_elapsed_ms"]))
                if item.get("oldest_elapsed_ms") is not None else None
            ),
        }
    return safe


def _living_state(
    store, *, as_of_tick: int, agent_id: int | None,
    runtime: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    tick = int(as_of_tick)
    regions = {
        int(row["id"]): {"id": int(row["id"]), "name": str(row["name"])}
        for row in store.query("SELECT id,name FROM regions ORDER BY id")
    }
    agent_rows = _dicts(store.query(
        "SELECT id,name,kind,role,occupation,population_tier,pinned_core,"
        "arrived_tick,died_tick,checking_account_id,savings_account_id "
        "FROM agents WHERE arrived_tick<=? AND (died_tick IS NULL OR died_tick>?) "
        "ORDER BY id", (tick, tick)))
    if agent_id is not None:
        agent_rows = [row for row in agent_rows if int(row["id"]) == int(agent_id)]
    region_ids = _agent_regions_at(store, agent_rows, tick)
    agent_ids = {int(row["id"]) for row in agent_rows}
    balances = _balances_as_of(
        store,
        (account_id for row in agent_rows for account_id in (
            row.get("checking_account_id"), row.get("savings_account_id"))),
        tick,
    )
    runtime_map = _runtime_by_agent(runtime)

    employment_rows = _dicts(store.query(
        "SELECT e.id,e.agent_id,e.firm_id,e.title,e.wage_cents,e.start_tick,e.end_tick,"
        "f.name AS firm_name FROM employments e JOIN firms f ON f.id=e.firm_id "
        "WHERE e.start_tick<=? ORDER BY e.start_tick,e.id", (tick,)))
    skill_rows = _dicts(store.query(
        "SELECT id,tick,agent_id,skill_key,old_level,new_level,xp_delta,new_xp,source "
        "FROM agent_skill_history WHERE tick<=? ORDER BY tick,id", (tick,)))
    subscription_rows = _dicts(store.query(
        "WITH ranked AS (SELECT id,agent_id,tier,payer_type,payer_id,price_cents,"
        "effective_tick,expiry_tick,reason,ROW_NUMBER() OVER (PARTITION BY agent_id "
        "ORDER BY effective_tick DESC,id DESC) AS rn FROM compute_subscriptions "
        "WHERE created_tick<=? AND effective_tick<=? AND expiry_tick>?) "
        "SELECT id,agent_id,tier,payer_type,payer_id,price_cents,effective_tick,"
        "expiry_tick,reason FROM ranked WHERE rn=1 ORDER BY agent_id",
        (tick, tick, tick)))
    firm_rows = _dicts(store.query(
        "SELECT id,name,sector,founder_agent_id,region_id,founded_tick,bankrupt_tick "
        "FROM firms WHERE founded_tick<=? ORDER BY founded_tick,id", (tick,)))
    migration_rows = _dicts(store.query(
        "SELECT m.id,m.agent_id,m.origin_region_id,m.destination_region_id,"
        "m.requested_tick,m.completed_tick,m.status FROM migrations m "
        "WHERE m.requested_tick<=? ORDER BY m.requested_tick,m.id", (tick,)))
    lease_rows = _dicts(store.query(
        "SELECT l.id,l.agent_id,l.place_id,l.source_type,l.start_tick,l.end_tick,"
        "l.ended_tick,"
        "p.name AS place_name,p.kind AS place_kind,p.region_id "
        "FROM occupancy_leases l JOIN places p ON p.id=l.place_id "
        "WHERE l.created_tick<=? AND l.start_tick<=? "
        "AND l.source_type IN ('routine_home','routine_work') "
        "AND p.created_tick<=? ORDER BY l.start_tick,l.id", (tick, tick, tick)))
    information_rows = _dicts(store.query(
        "SELECT id,tick,author_agent_id,item_type,claim_id,news_article_id "
        "FROM information_items WHERE tick<=? AND status='published' "
        "AND author_agent_id IS NOT NULL ORDER BY tick,id", (tick,)))
    commons_rows = _dicts(store.query(
        "SELECT e.id,e.created_tick AS tick,e.author_agent_id,e.entry_type,e.community_id "
        "FROM commons_entries e LEFT JOIN commons_communities c ON c.id=e.community_id "
        "WHERE e.created_tick<=? AND e.status='published' "
        "AND (e.community_id IS NULL OR c.visibility='public') "
        "ORDER BY e.created_tick,e.id", (tick,)))

    active_employment: dict[int, dict[str, Any]] = {}
    for row in employment_rows:
        aid = int(row["agent_id"])
        if aid not in agent_ids:
            continue
        ended = row["end_tick"]
        if ended is None or int(ended) > tick:
            active_employment[aid] = row

    skills: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
    skill_counts: dict[tuple[int, str], int] = defaultdict(int)
    skill_history: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in skill_rows:
        aid = int(row["agent_id"])
        if aid not in agent_ids:
            continue
        key = str(row["skill_key"])
        skill_counts[(aid, key)] += 1
        skill_history[(aid, key)].append(row)
        skills[aid][key] = row

    subscriptions = {
        int(row["agent_id"]): row for row in subscription_rows
        if int(row["agent_id"]) in agent_ids
    }
    active_leases: dict[tuple[int, str], dict[str, Any]] = {}
    latest_leases: dict[tuple[int, str], dict[str, Any]] = {}
    for row in lease_rows:
        aid = int(row["agent_id"])
        if aid not in agent_ids:
            continue
        key = (aid, str(row["source_type"]))
        latest_leases[key] = row
        if (
            int(row["start_tick"]) <= tick < int(row["end_tick"])
            and (
                row["ended_tick"] is None
                or int(row["ended_tick"]) > tick
            )
        ):
            active_leases[key] = row

    projects: list[dict[str, Any]] = []
    activities: list[dict[str, Any]] = []

    for row in employment_rows:
        aid = int(row["agent_id"])
        if aid not in agent_ids:
            continue
        end_tick = int(row["end_tick"]) if row["end_tick"] is not None else None
        completed = end_tick is not None and end_tick <= tick
        pid = f"employment:{int(row['id'])}"
        refs = [_evidence("employment", int(row["id"]), int(row["start_tick"]))]
        if completed:
            refs.append(_evidence("employment_end", int(row["id"]), end_tick))
        organization = {"id": int(row["firm_id"]), "name": str(row["firm_name"])}
        projects.append(_project(
            project_id=pid, kind="employment",
            title=f"Work at {row['firm_name']}", owner_agent_id=aid,
            stage="ended" if completed else "employed",
            status="completed" if completed else "active",
            started_tick=int(row["start_tick"]),
            updated_tick=end_tick if completed else int(row["start_tick"]),
            completed_tick=end_tick if completed else None,
            milestone_count=2 if completed else 1, evidence_refs=refs,
            organization=organization,
            metrics={"wage_cents": int(row["wage_cents"]), "title": row["title"]},
        ))
        activities.append(_activity(
            activity_id=f"employment:{int(row['id'])}:started",
            tick=int(row["start_tick"]), kind="employment", stage="employed",
            title=f"Started work at {row['firm_name']}", agent_id=aid,
            project_id=pid, source="committed", evidence_ref=refs[0]))
        if completed:
            activities.append(_activity(
                activity_id=f"employment:{int(row['id'])}:ended", tick=end_tick,
                kind="employment", stage="ended",
                title=f"Ended work at {row['firm_name']}", agent_id=aid,
                project_id=pid, source="committed", evidence_ref=refs[-1]))

    for aid, agent_skills in skills.items():
        for key, row in agent_skills.items():
            first = skill_history[(aid, key)][0]
            pid = f"skill:{aid}:{key}"
            refs = [_evidence("agent_skill_history", int(row["id"]), int(row["tick"]))]
            projects.append(_project(
                project_id=pid, kind="skill", title=f"Learning {key.replace('_', ' ')}",
                owner_agent_id=aid, stage=f"level_{int(row['new_level'])}", status="active",
                started_tick=int(first["tick"]), updated_tick=int(row["tick"]),
                milestone_count=skill_counts[(aid, key)], evidence_refs=refs,
                metrics={"level": int(row["new_level"]), "xp": int(row["new_xp"])},
            ))
    for row in skill_rows:
        aid = int(row["agent_id"])
        if aid not in agent_ids:
            continue
        key = str(row["skill_key"])
        ref = _evidence("agent_skill_history", int(row["id"]), int(row["tick"]))
        activities.append(_activity(
            activity_id=f"skill:{int(row['id'])}", tick=int(row["tick"]),
            kind="skill", stage=f"level_{int(row['new_level'])}",
            title=f"Practised {key.replace('_', ' ')} (+{int(row['xp_delta'])} XP)",
            agent_id=aid, project_id=f"skill:{aid}:{key}", source="committed",
            evidence_ref=ref))

    for row in firm_rows:
        founder = int(row["founder_agent_id"]) if row["founder_agent_id"] is not None else None
        if founder not in agent_ids:
            continue
        founded_tick = int(row["founded_tick"])
        ref = _evidence("firm", int(row["id"]), founded_tick)
        pid = f"firm:{int(row['id'])}"
        projects.append(_project(
            project_id=pid, kind="firm", title=f"Founded {row['name']}",
            owner_agent_id=founder, stage="founded", status="completed",
            started_tick=founded_tick, updated_tick=founded_tick,
            completed_tick=founded_tick, milestone_count=1, evidence_refs=[ref],
            organization={"id": int(row["id"]), "name": str(row["name"])},
            region=regions.get(int(row["region_id"])) if row["region_id"] is not None else None,
            metrics={"sector": row["sector"]},
        ))
        activities.append(_activity(
            activity_id=f"firm:{int(row['id'])}:founded", tick=founded_tick,
            kind="firm", stage="founded", title=f"Founded {row['name']}",
            agent_id=founder, project_id=pid, source="committed", evidence_ref=ref))

    for row in migration_rows:
        aid = int(row["agent_id"])
        if aid not in agent_ids:
            continue
        completed_tick = (
            int(row["completed_tick"])
            if row["completed_tick"] is not None and int(row["completed_tick"]) <= tick
            else None
        )
        raw_status = str(row["status"])
        cancelled = completed_tick is None and raw_status in {"cancelled", "rejected", "failed"}
        status = "completed" if completed_tick is not None else "cancelled" if cancelled else "active"
        stage = "arrived" if completed_tick is not None else "cancelled" if cancelled else "requested"
        requested = int(row["requested_tick"])
        destination = regions.get(int(row["destination_region_id"]))
        origin = regions.get(int(row["origin_region_id"]))
        ref = _evidence("migration", int(row["id"]), requested)
        refs = [ref]
        if completed_tick is not None:
            refs.append(_evidence("migration_completion", int(row["id"]), completed_tick))
        pid = f"migration:{int(row['id'])}"
        projects.append(_project(
            project_id=pid, kind="migration",
            title=f"Migration to {destination['name'] if destination else 'another region'}",
            owner_agent_id=aid, stage=stage, status=status, started_tick=requested,
            updated_tick=completed_tick or requested, completed_tick=completed_tick,
            milestone_count=len(refs), evidence_refs=refs, region=destination,
            metrics={"origin_region": origin},
        ))
        activities.append(_activity(
            activity_id=f"migration:{int(row['id'])}:requested", tick=requested,
            kind="migration", stage="requested", title="Requested regional migration",
            agent_id=aid, project_id=pid, source="committed", evidence_ref=ref))
        if completed_tick is not None:
            activities.append(_activity(
                activity_id=f"migration:{int(row['id'])}:completed", tick=completed_tick,
                kind="migration", stage="arrived",
                title=f"Arrived in {destination['name'] if destination else 'destination region'}",
                agent_id=aid, project_id=pid, source="committed", evidence_ref=refs[-1]))

    agents_by_id = {int(row["id"]): row for row in agent_rows}
    peripheral_groups: dict[
        tuple[str, int | None], list[dict[str, Any]]
    ] = defaultdict(list)
    for (aid, source_type), row in latest_leases.items():
        agent = agents_by_id[aid]
        core = (
            str(agent.get("population_tier") or "") == "core"
            or bool(agent.get("pinned_core"))
        )
        kind = "residence" if source_type == "routine_home" else "workplace"
        started = int(row["start_tick"])
        if not core and agent_id is None:
            # The ordinary observer projection aggregates peripheral occupancy
            # by region. A place id would be a reversible private-location link
            # even if the display label omitted the place name.
            region_id = (
                int(row["region_id"])
                if row["region_id"] is not None else None
            )
            peripheral_groups[(kind, region_id)].append(row)
            continue
        ref = _evidence("occupancy_lease", int(row["id"]), started)
        pid = f"{kind}:{aid}:{int(row['id'])}"
        visible_place = (
            {
                "id": int(row["place_id"]),
                "name": str(row["place_name"]),
                "kind": str(row["place_kind"]),
            }
            if core else None
        )
        region = (
            regions.get(int(row["region_id"]))
            if row["region_id"] is not None else None
        )
        projects.append(_project(
            project_id=pid, kind=kind,
            title=(
                f"Established {kind}"
                if not core else f"Established {kind} at {row['place_name']}"
            ),
            owner_agent_id=aid, stage="established", status="completed",
            started_tick=started, updated_tick=started, completed_tick=started,
            milestone_count=1, evidence_refs=[ref], place=visible_place, region=region,
            privacy="public" if core else "region_only",
        ))
        activities.append(_activity(
            activity_id=f"{kind}:{int(row['id'])}:established", tick=started,
            kind=kind, stage="established", title=f"Established {kind}", agent_id=aid,
            project_id=pid, source="committed", evidence_ref=ref))

    for (kind, region_id), rows in peripheral_groups.items():
        latest = max(int(row["start_tick"]) for row in rows)
        region = regions.get(region_id) if region_id is not None else None
        aggregate_key = f"{region_id or 0}:{kind}"
        ref = _evidence("occupancy_aggregate", aggregate_key, latest)
        pid = f"{kind}:district:{region_id or 0}"
        projects.append(_project(
            project_id=pid, kind=kind, title=f"{kind.title()} activity in a district",
            owner_agent_id=None, stage="established", status="completed",
            started_tick=min(int(row["start_tick"]) for row in rows), updated_tick=latest,
            completed_tick=latest, milestone_count=len(rows), evidence_refs=[ref],
            region=region, metrics={"agents": len(rows)}, source="derived",
            privacy="aggregated",
        ))
        activities.append(_activity(
            activity_id=f"{kind}:district:{region_id or 0}:{latest}", tick=latest,
            kind=kind, stage="established", title=f"{len(rows)} agents established {kind}",
            agent_id=None, project_id=pid, source="derived", evidence_ref=ref))

    output_rows = [
        *((item, "information_item") for item in information_rows),
        *((item, "commons_entry") for item in commons_rows),
    ]
    for row, output_kind in output_rows:
        aid = int(row["author_agent_id"])
        if aid not in agent_ids:
            continue
        output_tick = int(row["tick"])
        record_id = int(row["id"])
        label = str(
            row.get("item_type") or row.get("entry_type") or "output"
        ).replace("_", " ")
        ref = _evidence(output_kind, record_id, output_tick)
        pid = f"public_output:{output_kind}:{record_id}"
        projects.append(_project(
            project_id=pid, kind="public_output", title=f"Published {label}",
            owner_agent_id=aid, stage="published", status="completed",
            started_tick=output_tick, updated_tick=output_tick,
            completed_tick=output_tick, milestone_count=1, evidence_refs=[ref],
            metrics={"output_type": label},
        ))
        activities.append(_activity(
            activity_id=f"{output_kind}:{record_id}:published", tick=output_tick,
            kind="public_output", stage="published", title=f"Published {label}",
            agent_id=aid, project_id=pid, source="committed", evidence_ref=ref))

    # Civic case records include confidential application details. Ordinary
    # observers receive only region/stage aggregates and no applicant linkage.
    case_rows = _dicts(store.query(
        "SELECT region_id,created_tick,submitted_tick,decided_tick FROM service_cases "
        "WHERE created_tick<=? ORDER BY created_tick,id", (tick,)))
    case_groups: dict[tuple[int | None, str], list[dict[str, Any]]] = defaultdict(list)
    for row in case_rows:
        decided = row["decided_tick"] is not None and int(row["decided_tick"]) <= tick
        submitted = row["submitted_tick"] is not None and int(row["submitted_tick"]) <= tick
        stage = "decided" if decided else "submitted" if submitted else "applied"
        region_id = int(row["region_id"]) if row["region_id"] is not None else None
        case_groups[(region_id, stage)].append(row)
    for (region_id, stage), rows in case_groups.items():
        stage_tick = max(
            int(
                row["decided_tick"] if stage == "decided"
                else row["submitted_tick"] if stage == "submitted"
                else row["created_tick"]
            )
            for row in rows
        )
        region = regions.get(region_id) if region_id is not None else None
        ref = _evidence("service_case_aggregate", f"{region_id or 0}:{stage}", stage_tick)
        pid = f"civic_case:{region_id or 0}:{stage}"
        projects.append(_project(
            project_id=pid, kind="civic_case", title=f"Business permits: {stage}",
            owner_agent_id=None, stage=stage,
            status="completed" if stage == "decided" else "active",
            started_tick=min(int(row["created_tick"]) for row in rows),
            updated_tick=stage_tick,
            completed_tick=stage_tick if stage == "decided" else None,
            milestone_count=len(rows), evidence_refs=[ref], region=region,
            metrics={"case_count": len(rows)}, source="derived", privacy="aggregated",
        ))
        activities.append(_activity(
            activity_id=f"civic_case:{region_id or 0}:{stage}:{stage_tick}",
            tick=stage_tick, kind="civic_case", stage=stage,
            title=f"{len(rows)} permit cases {stage}",
            agent_id=None, project_id=pid, source="derived", evidence_ref=ref))

    latest_activity: dict[int, int] = defaultdict(int)
    for item in activities:
        if item["agent_id"] is not None:
            aid = int(item["agent_id"])
            latest_activity[aid] = max(latest_activity[aid], int(item["tick"]))

    agents: list[dict[str, Any]] = []
    for row in agent_rows:
        aid = int(row["id"])
        employment = active_employment.get(aid)
        subscription = subscriptions.get(aid)
        core = (
            str(row.get("population_tier") or "") == "core"
            or bool(row.get("pinned_core"))
        )
        residence = active_leases.get((aid, "routine_home"))
        workplace = active_leases.get((aid, "routine_work"))

        def projected_place(lease: dict[str, Any] | None) -> dict[str, Any] | None:
            if lease is None:
                return None
            region = (
                regions.get(int(lease["region_id"]))
                if lease["region_id"] is not None else None
            )
            if not core:
                return {"visibility": "region_only", "region": region}
            return {
                "visibility": "public",
                "id": int(lease["place_id"]),
                "name": str(lease["place_name"]),
                "kind": str(lease["place_kind"]),
                "region": region,
            }

        skill_list = [
            {
                "skill_key": key,
                "level": int(item["new_level"]),
                "xp": int(item["new_xp"]),
                "last_practiced_tick": int(item["tick"]),
                "milestone_count": skill_counts[(aid, key)],
                "source": str(item["source"]),
                "evidence_ref": _evidence(
                    "agent_skill_history", int(item["id"]), int(item["tick"])
                ),
            }
            for key, item in sorted(skills.get(aid, {}).items())
        ]
        checking_id = row.pop("checking_account_id", None)
        savings_id = row.pop("savings_account_id", None)
        row.pop("pinned_core", None)
        if row["died_tick"] is not None and int(row["died_tick"]) > tick:
            row["died_tick"] = None
        row["id"] = aid
        row["alive"] = True
        row["region"] = regions.get(region_ids.get(aid))
        row["balance_cents"] = sum(
            balances.get(int(account_id), 0)
            for account_id in (checking_id, savings_id)
            if account_id is not None
        )
        row["employment"] = (
            {
                "id": int(employment["id"]),
                "firm_id": int(employment["firm_id"]),
                "firm_name": str(employment["firm_name"]),
                "title": employment["title"],
                "wage_cents": int(employment["wage_cents"]),
                "start_tick": int(employment["start_tick"]),
            }
            if employment else None
        )
        row["compute"] = (
            {
                "tier": str(subscription["tier"]),
                "payer_type": str(subscription["payer_type"]),
                "price_cents": int(subscription["price_cents"]),
                "effective_tick": int(subscription["effective_tick"]),
                "expiry_tick": int(subscription["expiry_tick"]),
                "evidence_ref": _evidence(
                    "compute_subscription",
                    int(subscription["id"]),
                    int(subscription["effective_tick"]),
                ),
            }
            if subscription else {
                "tier": "local",
                "payer_type": "free",
                "price_cents": 0,
                "effective_tick": None,
                "expiry_tick": None,
                "evidence_ref": None,
            }
        )
        row["skills"] = skill_list
        row["residence"] = projected_place(residence)
        row["workplace"] = projected_place(workplace)
        row["latest_committed_tick"] = latest_activity.get(
            aid, int(row["arrived_tick"])
        )
        row["runtime"] = runtime_map.get(aid)
        agents.append(row)

    agents.sort(key=lambda row: (
        0 if row["runtime"] else 1,
        -int(row["latest_committed_tick"]),
        int(row["id"]),
    ))
    projects.sort(
        key=lambda row: (-int(row["updated_tick"]), str(row["project_id"]))
    )
    activities.sort(
        key=lambda row: (-int(row["tick"]), str(row["activity_id"]))
    )
    return {"agents": agents, "projects": projects, "activities": activities}


def build_living_agents_workspace(
    store, *, as_of_tick: int, agent_id: int | None = None,
    project_kind: str = "all", status: str = "all", after: int = 0,
    limit: int = 100, runtime: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the combined Living Agents workspace without private bodies."""
    state = _living_state(
        store, as_of_tick=as_of_tick, agent_id=agent_id, runtime=runtime
    )
    projects = [
        item for item in state["projects"]
        if (project_kind == "all" or item["kind"] == project_kind)
        and (status == "all" or item["status"] == status)
    ]
    activities = [
        item for item in state["activities"]
        if project_kind == "all" or item["kind"] == project_kind
    ]
    if status != "all":
        allowed_ids = {item["project_id"] for item in projects}
        activities = [
            item for item in activities if item["project_id"] in allowed_ids
        ]
    offset = max(0, int(after))
    page_limit = max(1, min(200, int(limit)))
    page = activities[offset:offset + page_limit]
    next_cursor = (
        offset + len(page)
        if offset + len(page) < len(activities) else None
    )
    public_outputs = sum(
        item["kind"] == "public_output" for item in state["projects"]
    )
    return {
        "summary": {
            "tick": int(as_of_tick),
            "living_agents": len(state["agents"]),
            "active_employments": sum(
                bool(item["employment"]) for item in state["agents"]
            ),
            "active_projects": sum(
                item["status"] == "active" for item in state["projects"]
            ),
            "completed_projects": sum(
                item["status"] == "completed" for item in state["projects"]
            ),
            "public_outputs": public_outputs,
            "runtime_active": sum(
                item["runtime"] is not None for item in state["agents"]
            ),
            "projects_total": len(projects),
            "projects_shown": min(len(projects), 500),
        },
        "agents": state["agents"],
        "projects": projects[:500],
        "activity": {
            "items": page,
            "next_cursor": next_cursor,
            "total": len(activities),
            "cursor_kind": "offset",
        },
        "source_legend": {
            "committed": (
                "Stored economic or civic evidence at or before the selected tick."
            ),
            "runtime": (
                "Ephemeral live execution status; omitted from historical views."
            ),
            "derived": "A UI summary calculated from committed records.",
        },
        "privacy": {
            "private_bodies_omitted": True,
            "peripheral_locations": "region_only_or_aggregated",
            "civic_cases": "aggregate_only",
        },
    }


def build_agent_journey(
    store, *, agent_id: int, as_of_tick: int, after: int = 0,
    limit: int = 100, runtime: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build one agent's evidence-linked journey as of an explicit tick."""
    runtime_rows = (
        [{"agent_id": int(agent_id), **runtime}] if runtime else None
    )
    workspace = build_living_agents_workspace(
        store, as_of_tick=as_of_tick, agent_id=int(agent_id),
        after=after, limit=limit, runtime=runtime_rows,
    )
    if not workspace["agents"]:
        return None
    agent = workspace["agents"][0]
    projects = workspace["projects"]
    outputs = [item for item in projects if item["kind"] == "public_output"]
    evidence: dict[tuple[str, str], dict[str, Any]] = {}
    for project in projects:
        for ref in project["evidence_refs"]:
            evidence[(str(ref["kind"]), str(ref["id"]))] = ref
    return {
        "profile": {
            "id": agent["id"],
            "name": agent["name"],
            "kind": agent["kind"],
            "role": agent["role"],
            "occupation": agent["occupation"],
            "population_tier": agent["population_tier"],
            "arrived_tick": agent["arrived_tick"],
            "died_tick": agent["died_tick"],
        },
        "current_state": {
            "region": agent["region"],
            "employment": agent["employment"],
            "balance_cents": agent["balance_cents"],
            "compute": agent["compute"],
            "residence": agent["residence"],
            "workplace": agent["workplace"],
        },
        "skills": agent["skills"],
        "projects": projects,
        "milestones": workspace["activity"],
        "public_outputs": outputs,
        "runtime": agent["runtime"],
        "evidence_refs": sorted(
            evidence.values(),
            key=lambda ref: (
                int(ref["tick"]), str(ref["kind"]), str(ref["id"])
            ),
        ),
        "source_legend": workspace["source_legend"],
        "privacy": workspace["privacy"],
    }

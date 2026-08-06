"""Cursor-paginated Legal-Political Economy projections and God-mode actions."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from communications.policy import Principal
from engine.actions import ActionExecutor
from engine.store import load_json
from operator_workspace import OperatorWorkspace, WorkspaceConflict, WorkspaceNotFound
from server.projections import (
    build_causal_projection,
    build_envelope,
    build_events,
    build_message,
    build_search,
    build_snapshot,
    build_threads,
    build_experiments_workspace,
    build_markets_workspace,
    build_organizations_workspace,
    build_politics_law_workspace,
    build_world_workspace,
    resolve_tick,
    SEARCH_KINDS,
)
from server.projections.envelope import ProjectionRequestError, lineage, validate_fork
from server.projections.events import build_backfill


class GodActionBody(BaseModel):
    actor_id: int
    expected_tick: int
    action: dict[str, Any]
    rationale_summary: str = ""


class ForkBody(BaseModel):
    expected_tick: int


class InvestigationCreateBody(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    fork_id: str | None = None
    pinned_tick: int | None = Field(default=None, ge=0)
    query: dict[str, Any] = Field(default_factory=dict)
    layout: dict[str, Any] = Field(default_factory=dict)


class InvestigationUpdateBody(BaseModel):
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    pinned_tick: int | None = Field(default=None, ge=0)
    query: dict[str, Any] | None = None
    layout: dict[str, Any] | None = None


class InvestigationItemBody(BaseModel):
    item_kind: str = Field(min_length=1, max_length=80)
    stable_ref: dict[str, Any]
    note: str = Field(default="", max_length=4000)
    label: str | None = Field(default=None, max_length=160)
    color: str | None = Field(default=None, max_length=40)


class HypothesisBody(BaseModel):
    statement: str = Field(min_length=1, max_length=2000)
    status: str = "open"


def _page(rows, limit: int) -> dict[str, Any]:
    items = [dict(row) for row in rows]
    return {"items": items, "next_cursor": int(items[-1]["id"]) if len(items) == limit else None}


def install_v2_routes(app, world, controller) -> None:
    router = APIRouter(prefix="/api/v2", tags=["legal-political-economy-v2"])
    store = world.store
    workspace_config = world.config.get("operator_workspace", {})
    workspace_path = Path(workspace_config.get(
        "path", Path(store.path).parent / "operator-workspace.db"))
    operator_workspace = OperatorWorkspace(workspace_path, world_path=store.path)
    app.state.operator_workspace = operator_workspace
    csrf_token = str(workspace_config.get("csrf_token", "local-observatory"))

    def projection_principal(
        *, agent_id: int | None = None, disclosure_case_id: int | None = None,
        truth: bool = False, owner_id: str = "local-operator",
    ) -> tuple[Principal, Any]:
        if truth:
            principal = Principal(
                f"operator:{owner_id}", operator_truth=True,
                disclosure_case_id=disclosure_case_id)
            run_lineage = lineage(store)
            audit = operator_workspace.truth_audit(
                owner_id=owner_id, run_id=run_lineage["run_id"],
                fork_id=run_lineage["fork_id"])
            return principal, audit
        if agent_id is not None:
            if not store.query_one("SELECT 1 FROM agents WHERE id=?", (int(agent_id),)):
                raise HTTPException(status_code=404, detail="view not found")
            return Principal(
                f"agent:{int(agent_id)}", agent_id=int(agent_id),
                disclosure_case_id=disclosure_case_id), None
        return Principal("ordinary-dashboard"), None

    def projection_tick(tick: str | int | None, fork_id: str | None) -> int:
        try:
            validate_fork(store, fork_id)
            return resolve_tick(store, tick)
        except ProjectionRequestError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def require_csrf(value: str | None) -> None:
        if not value or value != csrf_token:
            raise HTTPException(status_code=403, detail="valid CSRF token required")

    @router.get("/mode")
    async def local_mode():
        hosted = bool(controller.hosted_safe)
        return {
            "mode": "hosted" if hosted else "local",
            "hosted": hosted,
            "api_base": "/api/v2",
        }

    @router.get("/snapshot")
    async def world_snapshot(
        tick: str = Query("live"), fork_id: str | None = None,
        domains: str = Query("summary,alerts,communications,events"),
        agent_id: int | None = Query(default=None, gt=0),
    ):
        as_of_tick = projection_tick(tick, fork_id)
        principal, _ = projection_principal(agent_id=agent_id)
        selected = tuple(sorted({item.strip() for item in domains.split(",") if item.strip()}))
        data = build_snapshot(store, principal, as_of_tick=as_of_tick, domains=selected)
        return build_envelope(
            store, principal, "world.snapshot", data, as_of_tick=as_of_tick)

    @router.get("/events")
    async def event_projection(
        tick: str = Query("live"), fork_id: str | None = None,
        after: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
        filters: str = Query(""), agent_id: int | None = Query(default=None, gt=0),
    ):
        as_of_tick = projection_tick(tick, fork_id)
        principal, _ = projection_principal(agent_id=agent_id)
        kinds = tuple(sorted({item.strip() for item in filters.split(",") if item.strip()}))
        data = build_events(
            store, as_of_tick=as_of_tick, after_id=after, limit=limit, kinds=kinds)
        return build_envelope(store, principal, "events.page", data, as_of_tick=as_of_tick)

    @router.get("/search")
    async def search_projection(
        q: str = Query(),
        tick: str = Query("live"), fork_id: str | None = None,
        kinds: str = Query(",".join(SEARCH_KINDS)),
        limit: int = Query(8, ge=1, le=20),
    ):
        query = q.strip()
        if not 2 <= len(query) <= 100:
            raise HTTPException(status_code=422, detail="search query must contain 2-100 characters")
        requested = tuple(item.strip() for item in kinds.split(",") if item.strip())
        requested = requested or SEARCH_KINDS
        unknown = sorted(set(requested) - set(SEARCH_KINDS))
        if unknown:
            raise HTTPException(status_code=422, detail="unsupported search kind")
        selected = tuple(kind for kind in SEARCH_KINDS if kind in set(requested))
        as_of_tick = projection_tick(tick, fork_id)
        principal, _ = projection_principal()
        data = build_search(
            store,
            principal,
            query=query,
            as_of_tick=as_of_tick,
            kinds=selected,
            limit=limit,
        )
        return build_envelope(
            store, principal, "search.results", data, as_of_tick=as_of_tick)

    @router.get("/communications/summary")
    async def communication_summary(
        tick: str = Query("live"), fork_id: str | None = None,
    ):
        as_of_tick = projection_tick(tick, fork_id)
        principal = Principal("ordinary-dashboard")
        data = build_snapshot(
            store, principal, as_of_tick=as_of_tick, domains=("communications",))[
                "communications"]
        return build_envelope(
            store, principal, "communications.summary", data, as_of_tick=as_of_tick)

    @router.get("/communications/threads")
    async def communication_threads(
        tick: str = Query("live"), fork_id: str | None = None,
        agent_id: int | None = Query(default=None, gt=0),
        disclosure_case_id: int | None = Query(default=None, gt=0),
        truth: bool = False, after: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=200),
        x_operator_id: str = Header("local-operator"),
    ):
        as_of_tick = projection_tick(tick, fork_id)
        principal, audit = projection_principal(
            agent_id=agent_id, disclosure_case_id=disclosure_case_id,
            truth=truth, owner_id=x_operator_id)
        data = build_threads(
            store, principal, as_of_tick=as_of_tick,
            after_thread_id=after, limit=limit, truth_audit=audit)
        return build_envelope(
            store, principal, "communications.threads", data, as_of_tick=as_of_tick)

    @router.get("/communications/messages/{message_id}")
    async def communication_message(
        message_id: int, tick: str = Query("live"), fork_id: str | None = None,
        agent_id: int | None = Query(default=None, gt=0),
        disclosure_case_id: int | None = Query(default=None, gt=0),
        truth: bool = False, x_operator_id: str = Header("local-operator"),
    ):
        as_of_tick = projection_tick(tick, fork_id)
        principal, audit = projection_principal(
            agent_id=agent_id, disclosure_case_id=disclosure_case_id,
            truth=truth, owner_id=x_operator_id)
        data = build_message(
            store, principal, int(message_id), as_of_tick=as_of_tick,
            include_body=True, truth_audit=audit)
        if data is None:
            raise HTTPException(status_code=404, detail="message not found")
        return build_envelope(
            store, principal, "communications.message", data, as_of_tick=as_of_tick)

    @router.get("/causal/{kind}/{object_id}")
    async def causal_projection_v1(
        kind: str, object_id: int, tick: str = Query("live"),
        fork_id: str | None = None, depth: int = Query(3, ge=0, le=6),
        relations: str = Query(""), authority: str = Query(""),
        agent_id: int | None = Query(default=None, gt=0), truth: bool = False,
        x_operator_id: str = Header("local-operator"),
    ):
        as_of_tick = projection_tick(tick, fork_id)
        principal, audit = projection_principal(
            agent_id=agent_id, truth=truth, owner_id=x_operator_id)
        try:
            data = build_causal_projection(
                store, principal, kind, object_id, as_of_tick=as_of_tick, depth=depth,
                relations=tuple(sorted({item for item in relations.split(",") if item})),
                authorities=tuple(sorted({item for item in authority.split(",") if item})),
                truth_audit=audit)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="causal reference not found") from exc
        if data["root"] is None:
            raise HTTPException(status_code=404, detail="causal reference not found")
        return build_envelope(
            store, principal, "causal.neighborhood", data, as_of_tick=as_of_tick)

    @router.get("/backfill")
    async def projection_backfill(
        after: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
        fork_id: str | None = None, agent_id: int | None = Query(default=None, gt=0),
    ):
        as_of_tick = projection_tick("live", fork_id)
        principal, _ = projection_principal(agent_id=agent_id)
        data = build_backfill(store, after_cursor=after, limit=limit)
        return build_envelope(
            store, principal, "projection.backfill", data, as_of_tick=as_of_tick)

    @router.get("/entities/{kind}/{object_id}")
    async def entity_projection(
        kind: str, object_id: int, tick: str = Query("live"),
        fork_id: str | None = None,
    ):
        as_of_tick = projection_tick(tick, fork_id)
        principal = Principal("ordinary-dashboard")
        if kind == "place":
            data = world.economy.city.place_detail(object_id, as_of_tick)
            if data is None:
                raise HTTPException(status_code=404, detail="entity not found")
            return build_envelope(
                store, principal, "entity.detail",
                {"kind": kind, **data},
                as_of_tick=as_of_tick,
            )
        if kind == "agency":
            data = world.economy.city.agency_detail(object_id, as_of_tick)
            if data is None:
                raise HTTPException(status_code=404, detail="entity not found")
            return build_envelope(
                store, principal, "entity.detail",
                {"kind": kind, **data},
                as_of_tick=as_of_tick,
            )
        table_and_fields = {
            "agent": ("agents", "id,name,role,occupation,population_tier,region_id,alive"),
            "firm": ("firms", "id,name,sector,status,region_id,inventory"),
            "bank": ("banks", "id,name,status,reserve_requirement_bps"),
        }
        definition = table_and_fields.get(kind)
        if definition is None:
            raise HTTPException(status_code=404, detail="entity not found")
        row = store.query_one(
            f"SELECT {definition[1]} FROM {definition[0]} WHERE id=?", (int(object_id),))
        if row is None:
            raise HTTPException(status_code=404, detail="entity not found")
        return build_envelope(
            store, principal, "entity.detail", {"kind": kind, **dict(row)},
            as_of_tick=as_of_tick)

    @router.get("/world-map")
    async def world_map_projection(
        tick: str = Query("live"), fork_id: str | None = None,
        layers: str = Query("regions,agents,organizations,places,presence"),
    ):
        as_of_tick = projection_tick(tick, fork_id)
        principal = Principal("ordinary-dashboard")
        selected = {item.strip() for item in layers.split(",") if item.strip()}
        data: dict[str, Any] = {}
        if "regions" in selected:
            data["regions"] = world.economy.regions.region_state()
        if "agents" in selected:
            data["agents"] = [dict(row) for row in store.query(
                "SELECT a.id,a.name,a.role,a.occupation,a.region_id,"
                "a.population_tier,ep.slot,"
                "CASE WHEN p.kind='licensing_office' THEN NULL ELSE ep.place_id END "
                "AS place_id,"
                "CASE WHEN p.kind='licensing_office' THEN NULL ELSE p.name END "
                "AS place_name,"
                "CASE WHEN p.kind='licensing_office' THEN r.x "
                "ELSE COALESCE(p.x,r.x) END AS x,"
                "CASE WHEN p.kind='licensing_office' THEN r.y "
                "ELSE COALESCE(p.y,r.y) END AS y "
                "FROM agents a LEFT JOIN regions r ON r.id=a.region_id "
                "LEFT JOIN effective_presence ep ON ep.agent_id=a.id "
                "AND ep.tick=? AND ep.slot='business' "
                "LEFT JOIN places p ON p.id=ep.place_id "
                "WHERE a.alive=1 AND "
                "(a.population_tier='core' OR a.pinned_core=1) ORDER BY a.id",
                (as_of_tick,))]
        if "organizations" in selected:
            data["organizations"] = build_world_workspace(
                store, as_of_tick=as_of_tick)["organizations"]
        if "places" in selected:
            data["places"] = world.economy.city.map_places(as_of_tick)
        if "presence" in selected:
            data["presence"] = world.economy.city.map_presence(
                as_of_tick, public=True)
        return build_envelope(
            store, principal, "world.map", data, as_of_tick=as_of_tick)

    def workspace_envelope(slug: str, data: dict[str, Any], as_of_tick: int):
        return build_envelope(
            store, Principal("ordinary-dashboard"), f"workspace.{slug}", data,
            as_of_tick=as_of_tick)

    @router.get("/workspaces/world")
    async def world_workspace(tick: str = Query("live"), fork_id: str | None = None):
        as_of_tick = projection_tick(tick, fork_id)
        return workspace_envelope(
            "world", build_world_workspace(store, as_of_tick=as_of_tick), as_of_tick)

    @router.get("/workspaces/commons")
    async def commons_workspace(
        tick: str = Query("live"), fork_id: str | None = None,
        kind: str = Query("chronological"), limit: int = Query(50, ge=1, le=100),
    ):
        from world.commons import CommonsError
        as_of_tick = projection_tick(tick, fork_id)
        try:
            data = world.commons.public_overview(
                kind=kind, limit=limit, as_of_tick=as_of_tick)
        except CommonsError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        return workspace_envelope("commons", data, as_of_tick)

    @router.get("/workspaces/organizations")
    async def organizations_workspace(
        tick: str = Query("live"), fork_id: str | None = None,
    ):
        as_of_tick = projection_tick(tick, fork_id)
        return workspace_envelope(
            "organizations", build_organizations_workspace(store, as_of_tick=as_of_tick),
            as_of_tick)

    @router.get("/workspaces/markets")
    async def markets_workspace(tick: str = Query("live"), fork_id: str | None = None):
        as_of_tick = projection_tick(tick, fork_id)
        return workspace_envelope(
            "markets", build_markets_workspace(store, as_of_tick=as_of_tick), as_of_tick)

    @router.get("/workspaces/politics-law")
    async def politics_law_workspace(
        tick: str = Query("live"), fork_id: str | None = None,
    ):
        as_of_tick = projection_tick(tick, fork_id)
        return workspace_envelope(
            "politics_law", build_politics_law_workspace(store, as_of_tick=as_of_tick),
            as_of_tick)

    @router.get("/workspaces/experiments")
    async def experiments_workspace(
        tick: str = Query("live"), fork_id: str | None = None,
    ):
        as_of_tick = projection_tick(tick, fork_id)
        return workspace_envelope(
            "experiments", build_experiments_workspace(store, as_of_tick=as_of_tick),
            as_of_tick)

    @router.get("/civic/summary")
    async def civic_summary(
        tick: str = Query("live"), fork_id: str | None = None,
    ):
        as_of_tick = projection_tick(tick, fork_id)
        principal = Principal("ordinary-dashboard")
        return build_envelope(
            store,
            principal,
            "civic.summary",
            world.economy.city.public_summary(as_of_tick),
            as_of_tick=as_of_tick,
        )

    @router.get("/civic/cases")
    async def civic_cases(
        tick: str = Query("live"), fork_id: str | None = None,
        agent_id: int | None = Query(default=None, gt=0),
    ):
        as_of_tick = projection_tick(tick, fork_id)
        principal, _ = projection_principal(agent_id=agent_id)
        data = world.economy.city.cases_for_viewer(
            principal.agent_id, as_of_tick)
        return build_envelope(
            store, principal, "civic.cases", data, as_of_tick=as_of_tick)

    @router.get("/agents/{agent_id}/attention")
    async def agent_attention(
        agent_id: int,
        viewer_agent_id: int = Query(gt=0),
        tick: str = Query("live"),
        fork_id: str | None = None,
    ):
        as_of_tick = projection_tick(tick, fork_id)
        if int(viewer_agent_id) != int(agent_id):
            raise HTTPException(
                status_code=403,
                detail="an agent may view only its own attention lanes",
            )
        principal, _ = projection_principal(agent_id=viewer_agent_id)
        data = world.economy.city.attention_projection(
            int(agent_id), as_of_tick)
        return build_envelope(
            store, principal, "agent.attention", data, as_of_tick=as_of_tick)

    @router.get("/operator/session")
    async def operator_session(x_operator_id: str = Header("local-operator")):
        return {"owner_id": x_operator_id, "csrf_token": csrf_token}

    @router.get("/operator/investigations")
    async def investigations(x_operator_id: str = Header("local-operator")):
        return {"items": operator_workspace.list_investigations(
            owner_id=x_operator_id, run_id=lineage(store)["run_id"])}

    @router.post("/operator/investigations")
    async def create_investigation(
        body: InvestigationCreateBody,
        x_operator_id: str = Header("local-operator"),
        x_csrf_token: str | None = Header(default=None),
    ):
        require_csrf(x_csrf_token)
        return operator_workspace.create_investigation(
            owner_id=x_operator_id, title=body.title, run_id=lineage(store)["run_id"],
            fork_id=body.fork_id, pinned_tick=body.pinned_tick,
            query=body.query, layout=body.layout)

    @router.get("/operator/investigations/{investigation_id}")
    async def investigation_detail(
        investigation_id: str, x_operator_id: str = Header("local-operator"),
    ):
        try:
            return operator_workspace.get_investigation(
                investigation_id, owner_id=x_operator_id)
        except WorkspaceNotFound as exc:
            raise HTTPException(status_code=404, detail="investigation not found") from exc

    @router.patch("/operator/investigations/{investigation_id}")
    async def update_investigation(
        investigation_id: str, body: InvestigationUpdateBody,
        x_operator_id: str = Header("local-operator"),
        x_csrf_token: str | None = Header(default=None),
    ):
        require_csrf(x_csrf_token)
        try:
            return operator_workspace.update_investigation(
                investigation_id, owner_id=x_operator_id,
                expected_version=body.expected_version, title=body.title,
                pinned_tick=body.pinned_tick, query=body.query, layout=body.layout)
        except WorkspaceConflict as exc:
            raise HTTPException(status_code=409, detail="investigation version conflict") from exc
        except WorkspaceNotFound as exc:
            raise HTTPException(status_code=404, detail="investigation not found") from exc

    @router.post("/operator/investigations/{investigation_id}/items")
    async def add_investigation_item(
        investigation_id: str, body: InvestigationItemBody,
        x_operator_id: str = Header("local-operator"),
        x_csrf_token: str | None = Header(default=None),
    ):
        require_csrf(x_csrf_token)
        try:
            return operator_workspace.add_item(
                investigation_id, owner_id=x_operator_id, item_kind=body.item_kind,
                stable_ref=body.stable_ref, note=body.note, label=body.label,
                color=body.color)
        except WorkspaceNotFound as exc:
            raise HTTPException(status_code=404, detail="investigation not found") from exc

    @router.post("/operator/investigations/{investigation_id}/hypotheses")
    async def add_investigation_hypothesis(
        investigation_id: str, body: HypothesisBody,
        x_operator_id: str = Header("local-operator"),
        x_csrf_token: str | None = Header(default=None),
    ):
        require_csrf(x_csrf_token)
        try:
            return operator_workspace.add_hypothesis(
                investigation_id, owner_id=x_operator_id,
                statement=body.statement, status=body.status)
        except WorkspaceNotFound as exc:
            raise HTTPException(status_code=404, detail="investigation not found") from exc

    @router.get("/operator/investigations/{investigation_id}/export")
    async def export_investigation(
        investigation_id: str, x_operator_id: str = Header("local-operator"),
    ):
        try:
            payload, markdown = operator_workspace.export(
                investigation_id, owner_id=x_operator_id)
        except WorkspaceNotFound as exc:
            raise HTTPException(status_code=404, detail="investigation not found") from exc
        return {"json": payload, "markdown": markdown}

    @router.get("/map")
    async def economic_map():
        regions = world.economy.regions.region_state()
        core_agents = [dict(row) for row in store.query(
            "SELECT a.id,a.name,a.role,a.occupation,a.population_tier,a.region_id,"
            "CASE WHEN p.kind='licensing_office' THEN NULL ELSE ep.place_id END "
            "AS place_id,"
            "CASE WHEN p.kind='licensing_office' THEN NULL ELSE p.name END "
            "AS place_name,"
            "CASE WHEN p.kind='licensing_office' THEN r.x "
            "ELSE COALESCE(p.x,r.x) END AS x,"
            "CASE WHEN p.kind='licensing_office' THEN r.y "
            "ELSE COALESCE(p.y,r.y) END AS y "
            "FROM agents a LEFT JOIN regions r ON r.id=a.region_id "
            "LEFT JOIN effective_presence ep ON ep.agent_id=a.id "
            "AND ep.tick=? AND ep.slot='business' "
            "LEFT JOIN places p ON p.id=ep.place_id "
            "WHERE a.alive=1 AND "
            "(a.population_tier='core' OR a.pinned_core=1) ORDER BY a.id",
            (store.tick,))]
        firms = [dict(row) for row in store.query(
            "SELECT f.id,f.name,f.sector,f.status,f.region_id,f.currency_code,"
            "p.id AS place_id,p.name AS place_name,"
            "COALESCE(p.x,r.x) AS x,COALESCE(p.y,r.y) AS y "
            "FROM firms f LEFT JOIN regions r ON r.id=f.region_id "
            "LEFT JOIN places p ON p.owner_type='firm' AND p.owner_id=f.id "
            "AND p.kind='workplace' AND p.active=1 "
            "WHERE f.status<>'bankrupt' ORDER BY f.id")]
        flows = []
        for row in store.query(
            "SELECT id,origin_region_id AS source_region_id,destination_region_id AS target_region_id,"
            "'trade' AS kind,quantity AS magnitude,status FROM trade_shipments ORDER BY id DESC LIMIT 100"):
            flows.append(dict(row))
        for row in store.query(
            "SELECT id,origin_region_id AS source_region_id,destination_region_id AS target_region_id,"
            "'migration' AS kind,1 AS magnitude,status FROM migrations ORDER BY id DESC LIMIT 100"):
            flows.append(dict(row))
        return {
            "enabled": bool(world.economy.regions.enabled),
            "regions": regions,
            "core_agents": core_agents,
            "firms": firms,
            "flows": flows,
            "places": world.economy.city.map_places(store.tick),
            "presence": world.economy.city.map_presence(
                store.tick, public=True),
            "civic": world.economy.city.public_summary(store.tick),
        }

    @router.get("/network")
    async def interaction_network(limit: int = Query(150, ge=1, le=500)):
        nodes = [dict(row) for row in store.query(
            "SELECT id,name,role,occupation,region_id,population_tier FROM agents "
            "WHERE alive=1 AND population_tier='core' ORDER BY id")]
        node_ids = {int(node["id"]) for node in nodes}
        edges = []
        for row in store.query("SELECT agent_a,agent_b,weight FROM social_ties ORDER BY weight DESC LIMIT ?", (limit * 4,)):
            if int(row["agent_a"]) in node_ids and int(row["agent_b"]) in node_ids:
                edges.append({"source": int(row["agent_a"]), "target": int(row["agent_b"]),
                              "kind": "social", "weight": float(row["weight"])})
                if len(edges) >= limit:
                    break
        return {"nodes": nodes, "edges": edges}

    @router.get("/legal")
    async def legal_projection(after_id: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
        matters = store.query(
            "SELECT m.*,c.ruleset_key FROM legal_matters m "
            "LEFT JOIN contracts c ON c.id=m.contract_id "
            "WHERE m.id>? ORDER BY m.id LIMIT ?", (after_id, limit))
        page = _page(matters, limit)
        for item in page["items"]:
            item["requested_remedy"] = load_json(item.pop("requested_remedy_json", None), {})
            item["settlement"] = load_json(item.pop("settlement_json", None), None)
        page["contracts"] = [dict(row) for row in store.query(
            "SELECT id,contract_type,title,status,ruleset_key,jurisdiction,offered_tick,executed_tick FROM contracts "
            "ORDER BY id DESC LIMIT 100")]
        page["obligations"] = [dict(row) for row in store.query(
            "SELECT * FROM obligations WHERE status NOT IN ('performed','expired') ORDER BY due_tick,id LIMIT 100")]
        page["enabled"] = bool(world.economy.legal.enabled)
        return page

    @router.get("/politics")
    async def political_projection(after_id: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
        state = world.economy.politics.state()
        activities = store.query(
            "SELECT * FROM lobbying_activities WHERE id>? ORDER BY id LIMIT ?", (after_id, limit))
        state["lobbying"] = _page(activities, limit)
        state["active_rules"] = [dict(row) for row in store.query(
            "SELECT * FROM policy_rules WHERE effective_tick<=? AND status='active' "
            "ORDER BY rule_key,effective_tick DESC", (store.tick,))]
        state["enabled"] = bool(world.economy.politics.enabled)
        state["institutional_actions_enabled"] = bool(
            world.config.get("llm", {}).get("institutional_role_purposes", False)
        )
        return state

    @router.get("/information")
    async def information_projection(after_id: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
        items = store.query(
            "SELECT i.*,a.name AS author_name FROM information_items i LEFT JOIN agents a ON a.id=i.author_agent_id "
            "WHERE i.id>? ORDER BY i.id LIMIT ?", (after_id, limit))
        page = _page(items, limit)
        page["claims"] = [{**dict(row), "value": load_json(row["value_json"], None)}
                          for row in store.query("SELECT * FROM claims ORDER BY id DESC LIMIT 100")]
        page["exposure_count"] = int(store.scalar("SELECT COUNT(*) FROM information_exposures", default=0))
        return page

    @router.get("/startups")
    async def startup_projection():
        return {
            "term_sheets": [dict(row) for row in store.query("SELECT * FROM term_sheets ORDER BY id DESC LIMIT 100")],
            "funding_rounds": [dict(row) for row in store.query("SELECT * FROM funding_rounds ORDER BY id DESC LIMIT 100")],
            "ip_assets": [dict(row) for row in store.query("SELECT * FROM ip_assets ORDER BY id DESC LIMIT 100")],
            "mergers": [dict(row) for row in store.query("SELECT * FROM mergers ORDER BY id DESC LIMIT 100")],
            "disclosures": [dict(row) for row in store.query("SELECT * FROM firm_disclosures ORDER BY id DESC LIMIT 100")],
        }

    @router.get("/markets")
    async def market_projection():
        return {
            "orders": [dict(row) for row in store.query("SELECT * FROM orders ORDER BY id DESC LIMIT 100")],
            "trades": [dict(row) for row in store.query("SELECT * FROM trades ORDER BY id DESC LIMIT 100")],
            "fx_orders": [dict(row) for row in store.query("SELECT * FROM fx_orders ORDER BY id DESC LIMIT 100")],
            "fx_trades": [dict(row) for row in store.query("SELECT * FROM fx_trades ORDER BY id DESC LIMIT 100")],
            "circuit_breakers": [dict(row) for row in store.query(
                "SELECT * FROM events WHERE kind LIKE '%circuit%' ORDER BY id DESC LIMIT 50")],
        }

    @router.get("/datasets")
    async def dataset_provenance():
        manifests = [dict(row) for row in store.query(
            "SELECT * FROM dataset_manifests ORDER BY dataset_key")]
        for item in manifests:
            item["metadata"] = load_json(item.pop("metadata_json", None), {})
        targets = []
        for row in store.query(
                "SELECT c.id,c.dataset_manifest_id,c.target_key,c.unit,"
                "c.dimensions_json,d.dataset_key,"
                "json_type(c.value_json) AS value_type,"
                "CASE WHEN json_type(c.value_json) IN "
                "('integer','real','text','true','false','null') "
                "THEN json_extract(c.value_json,'$') END AS scalar_value,"
                "json_extract(c.value_json,'$.record_count') AS record_count,"
                "json_extract(c.value_json,'$.class_count') AS class_count,"
                "json_extract(c.value_json,'$.total_firms') AS total_firms "
                "FROM calibration_targets c "
                "JOIN dataset_manifests d ON d.id=c.dataset_manifest_id "
                "ORDER BY d.dataset_key,c.target_key,c.id"):
            item = dict(row)
            value_type = str(item.pop("value_type") or "unknown")
            scalar_value = item.pop("scalar_value")
            summary: dict[str, Any] = {"type": value_type}
            if value_type in {"integer", "real", "text", "true", "false", "null"}:
                summary["value"] = scalar_value
            for key in ("record_count", "class_count", "total_firms"):
                value = item.pop(key)
                if value is not None:
                    summary[key] = int(value)
            item["dimensions"] = load_json(item.pop("dimensions_json", None), {})
            item["value_summary"] = summary
            targets.append(item)
        calibration = store.query_one(
            "SELECT id,tick,payload_json FROM events "
            "WHERE kind='r21_calibration_applied' ORDER BY id DESC LIMIT 1")
        return {"manifests": manifests,
                "targets": targets,
                "scenarios": [dict(row) for row in store.query(
                    "SELECT * FROM scenario_packs ORDER BY id")],
                "r21_calibration": ({"event_id": int(calibration["id"]),
                                     "tick": int(calibration["tick"]),
                                     **load_json(calibration["payload_json"], {})}
                                    if calibration else None)}

    @router.get("/causal/{event_id}")
    async def causal_trace(event_id: int):
        source = store.query_one("SELECT * FROM events WHERE id=?", (event_id,))
        if not source:
            raise HTTPException(status_code=404, detail="event not found")
        claims = []
        for row in store.query("SELECT * FROM claims ORDER BY id"):
            refs = load_json(row["source_event_ids_json"], [])
            if event_id in refs:
                claims.append(dict(row))
        claim_ids = [int(row["id"]) for row in claims]
        exposures = []
        if claim_ids:
            marks = ",".join("?" for _ in claim_ids)
            exposures = [dict(row) for row in store.query(
                f"SELECT e.* FROM information_exposures e JOIN information_items i ON i.id=e.item_id "
                f"WHERE i.claim_id IN ({marks}) ORDER BY e.id", tuple(claim_ids))]
        proposals = []
        for row in store.query("SELECT * FROM action_proposals ORDER BY id"):
            if event_id in load_json(row["evidence_event_ids_json"], []):
                item = dict(row)
                item.pop("payload_json", None)
                proposals.append(item)
        outcomes = [dict(row) for row in store.query(
            "SELECT id,tick,phase,kind,subject_type,subject_id,importance FROM events "
            "WHERE id>? AND tick<=? ORDER BY id LIMIT 100", (event_id, int(source["tick"]) + 30))]
        return {"source_event": {**dict(source), "payload": load_json(source["payload_json"], {})},
                "claims": claims, "exposures": exposures, "actions": proposals, "outcomes": outcomes}

    @router.post("/god/action")
    async def god_action(body: GodActionBody):
        controller._require_mutable("God-mode action")
        if controller.is_running():
            raise HTTPException(status_code=409, detail="pause the run before injecting an action")
        if body.expected_tick != store.tick:
            raise HTTPException(status_code=409, detail=f"tick advanced to {store.tick}")
        action = dict(body.action)
        if body.rationale_summary:
            action["rationale_summary"] = body.rationale_summary[:500]
        result = ActionExecutor(world.economy).execute_action(
            store.tick, body.actor_id, action, phase="GOD_MODE")
        store.commit()
        return {"tick": store.tick, "result": result}

    @router.post("/god/fork")
    async def god_fork(body: ForkBody):
        controller._require_mutable("God-mode fork")
        if controller.is_running() or body.expected_tick != store.tick:
            raise HTTPException(status_code=409, detail="pause at the expected tick before forking")
        checkpoint = world.checkpoint(store.tick, reason="god_mode_fork")
        if not checkpoint:
            raise HTTPException(status_code=500, detail="checkpoint failed")
        from run import fork_run
        run_id = fork_run(str(checkpoint), data_dir=Path(store.path).parent)
        return {"parent_run_id": store.get_meta()["run_id"], "fork_tick": store.tick,
                "run_id": run_id, "checkpoint": checkpoint}

    app.include_router(router)

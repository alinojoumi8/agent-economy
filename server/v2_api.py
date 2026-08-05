"""Cursor-paginated Legal-Political Economy projections and God-mode actions."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from engine.actions import ActionExecutor
from engine.store import load_json


class GodActionBody(BaseModel):
    actor_id: int
    expected_tick: int
    action: dict[str, Any]
    rationale_summary: str = ""


class ForkBody(BaseModel):
    expected_tick: int


def _page(rows, limit: int) -> dict[str, Any]:
    items = [dict(row) for row in rows]
    return {"items": items, "next_cursor": int(items[-1]["id"]) if len(items) == limit else None}


def install_v2_routes(app, world, controller) -> None:
    router = APIRouter(prefix="/api/v2", tags=["legal-political-economy-v2"])
    store = world.store

    @router.get("/map")
    async def economic_map():
        regions = world.economy.regions.region_state()
        core_agents = [dict(row) for row in store.query(
            "SELECT a.id,a.name,a.role,a.occupation,a.population_tier,a.region_id,r.x,r.y "
            "FROM agents a LEFT JOIN regions r ON r.id=a.region_id "
            "WHERE a.alive=1 AND (a.population_tier='core' OR a.pinned_core=1) ORDER BY a.id")]
        firms = [dict(row) for row in store.query(
            "SELECT f.id,f.name,f.sector,f.status,f.region_id,f.currency_code,r.x,r.y "
            "FROM firms f LEFT JOIN regions r ON r.id=f.region_id WHERE f.status<>'bankrupt' ORDER BY f.id")]
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

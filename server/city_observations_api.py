"""Local observer navigation; never copied into canonical simulation storage."""
from __future__ import annotations

import hashlib
import json
import math
import re
from urllib.parse import parse_qsl, urlencode

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from communications.policy import Principal
from operator_workspace import WorkspaceConflict
from server.projections.envelope import build_envelope


class CityObservationContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    run_id: str = Field(min_length=1, max_length=200)
    fork_id: str | None = Field(max_length=200)
    view_key: str = Field(min_length=1, max_length=200)
    policy_version: int = Field(ge=1)
    semantics_version: int = Field(ge=1)
    projection_version: int = Field(ge=1)


class CityObservationsBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    context: CityObservationContext
    expected_version: int = Field(ge=0, le=9007199254740990)
    entries: list[str] = Field(max_length=20)


def validate_observations(entries: list[str], context: dict, current_tick: int) -> list[str]:
    """Admit bounded observer URL fields, never evidence payloads or credentials."""
    allowed = {"tick", "fork", "event", "agent", "firm", "place", "project", "household",
               "institution", "camera", "follow", "layer", "q", "population", "activeOnly", "view"}
    if len(entries) > 20 or len(set(entries)) != len(entries):
        raise ValueError("at most 20 distinct observations are allowed")
    normalized = []
    order = ("fork", "tick", "event", "layer", "q", "activeOnly", "camera", "household", "institution",
             "firm", "agent", "place", "project", "population", "view", "follow")
    for entry in entries:
        if not isinstance(entry, str) or len(entry) > 2048:
            raise ValueError("observation is too long")
        pairs = parse_qsl(entry, keep_blank_values=True, strict_parsing=True, max_num_fields=17)
        values = dict(pairs)
        if len(pairs) != len(values) or not values.keys() <= allowed:
            raise ValueError("unsupported observation fields")
        if not re.fullmatch(r"0|[1-9][0-9]{0,15}", values.get("tick", "")):
            raise ValueError("observation requires a recorded tick")
        if int(values["tick"]) > current_tick or values.get("fork") != context["fork_id"]:
            raise ValueError("observation is outside this run history")
        for key in ("event", "agent", "firm", "place", "household", "follow"):
            if key in values and (not re.fullmatch(r"[1-9][0-9]{0,15}", values[key])
                                  or int(values[key]) > 9007199254740991):
                raise ValueError("invalid observation identifier")
        if "project" in values and not re.fullmatch(r"[a-zA-Z0-9:_-]{1,180}", values["project"]):
            raise ValueError("invalid project identifier")
        if "institution" in values and (not re.fullmatch(r"bank:[1-9][0-9]{0,15}", values["institution"])
                or int(values["institution"].split(":")[1]) > 9007199254740991):
            raise ValueError("invalid bank identifier")
        if sum(key in values for key in ("agent", "firm", "place", "project", "household", "institution")) > 1:
            raise ValueError("observation must have one selected object")
        if "follow" in values and values.get("agent") != values["follow"]:
            raise ValueError("follow must match the selected person")
        choices = {"layer": {"work", "communications", "markets", "institutions", "health"},
                   "population": {"all", "clusters"}, "activeOnly": {"1"},
                   "view": {"diorama", "recorded", "list"}}
        if any(key in values and values[key] not in options for key, options in choices.items()):
            raise ValueError("invalid observation display option")
        if len(values.get("q", "").encode("utf-16-le")) // 2 > 100:
            raise ValueError("observation search is too long")
        if "camera" in values:
            camera = values["camera"]
            if len(camera) > 80 or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?(?:,[0-9]+(?:\.[0-9]+)?){2}", camera):
                raise ValueError("invalid observation camera")
            x, y, zoom = map(float, camera.split(","))
            if not (0 <= x <= 100 and 0 <= y <= 100 and 1.8 <= zoom <= 5.4):
                raise ValueError("invalid observation camera")
            values["camera"] = ",".join(f"{math.floor(value * 1000 + 0.5) / 1000:.3f}".rstrip("0").rstrip(".")
                                        for value in (x, y, zoom))
            if values["camera"] == "50,50,3.05":
                del values["camera"]
        # URLSearchParams encoding and the observer parser's canonical field order.
        normalized.append(urlencode([(key, values[key]) for key in order if values.get(key)], safe="*").replace("~", "%7E"))
    if len(set(normalized)) != len(normalized):
        raise ValueError("observations must identify distinct views")
    return normalized


def install_city_observation_routes(app, world, controller, workspace, *, csrf_token: str) -> None:
    router = APIRouter(prefix="/api/v2/operator/city-observations", tags=["local-city-observations"])

    def admit(context: CityObservationContext) -> tuple[dict, str]:
        if getattr(controller, "hosted_safe", False):
            raise HTTPException(status_code=404, detail="local observation workspace unavailable")
        envelope = build_envelope(world.store, Principal("ordinary-dashboard"), "world.map", {},
                                  as_of_tick=int(world.store.tick))
        expected = {key: envelope[key] for key in CityObservationContext.model_fields}
        if context.model_dump() != expected:
            raise HTTPException(status_code=409, detail="city observation context changed; reload the city")
        digest = hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest()
        return expected, f"city-observations:{digest}"

    def response(context: dict, record: dict) -> JSONResponse:
        return JSONResponse(
            {"context": context, "version": record["version"], "entries": record["state"]["entries"]},
            headers={"Cache-Control": "private, no-store"})

    @router.get("")
    async def observations(
        context: str = Query(max_length=1024),
        x_operator_id: str = Header("local-operator", min_length=1, max_length=200),
    ):
        try:
            parsed = CityObservationContext.model_validate_json(context)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="invalid city observation context") from exc
        expected, route = admit(parsed)
        return response(expected, workspace.get_saved_view(owner_id=x_operator_id, route=route))

    @router.put("")
    async def save_observations(
        body: CityObservationsBody,
        x_operator_id: str = Header("local-operator", min_length=1, max_length=200),
        x_csrf_token: str | None = Header(default=None),
    ):
        expected, route = admit(body.context)
        if not x_csrf_token or x_csrf_token != csrf_token:
            raise HTTPException(status_code=403, detail="valid CSRF token required")
        try:
            entries = validate_observations(body.entries, expected, int(world.store.tick))
            saved = workspace.save_city_view(
                owner_id=x_operator_id, route=route, expected_version=body.expected_version,
                entries=entries, run_id=expected["run_id"], fork_id=expected["fork_id"])
        except WorkspaceConflict as exc:
            raise HTTPException(status_code=409, detail="Saved observations changed in another window. Reload before saving.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return response(expected, saved)

    app.include_router(router)

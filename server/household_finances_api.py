"""Local operator household inspection at committed historical boundaries."""
from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from communications.policy import Principal
from server.projections.envelope import build_envelope, lineage, resolve_tick, validate_fork
from server.projections.household_finances import build_household_finances


def install_household_finance_routes(app, world, controller, *, csrf_token: str) -> None:
    router = APIRouter(prefix="/api/v2/operator/household-finances")

    @router.get("/{agent_id}")
    async def finances(agent_id: int, run_id: str = Query(min_length=1), tick: str = "live",
                       fork_id: str | None = None, x_csrf_token: str | None = Header(default=None)):
        headers = {"Cache-Control": "private, no-store"}
        if getattr(controller, "hosted_safe", False) or not world.config.get("operator_households", {}).get("enabled", True):
            raise HTTPException(403, "Household finances are available to the local operator only.", headers=headers)
        if not x_csrf_token or x_csrf_token != csrf_token:
            raise HTTPException(403, "Valid operator CSRF token required.", headers=headers)
        if run_id != lineage(world.store)["run_id"]:
            raise HTTPException(409, "Household finances require the selected local run.", headers=headers)
        try:
            validate_fork(world.store, fork_id)
            as_of_tick = resolve_tick(world.store, tick)
            data = build_household_finances(world.store, agent_id=agent_id, as_of_tick=as_of_tick)
        except LookupError as exc:
            raise HTTPException(404, "Household view not found at this tick.", headers=headers) from exc
        except ValueError as exc:
            # Reader failures may contain private source identifiers. Do not
            # turn them into error-page disclosures or silently repair a run.
            raise HTTPException(409, "Household finances require a committed Semantics-20 tick with complete position history.",
                                headers=headers) from exc
        data["requested_tick"] = "live" if tick == "live" else str(as_of_tick)
        envelope = build_envelope(world.store, Principal("local-operator:household-finances", operator_truth=True),
                                  "operator.household-finances", data, as_of_tick=as_of_tick)
        return JSONResponse(envelope, headers=headers)

    app.include_router(router)

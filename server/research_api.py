"""Local operator study review; no run controls or public artifact paths."""
from __future__ import annotations

import asyncio
from pathlib import Path
import threading

from fastapi import APIRouter, Header, HTTPException, Query, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from research.study_library import StudyLibrary
from research.study_results import StudyArtifactError, StudyIdentityChanged
from server.projections.envelope import lineage, validate_fork, ProjectionRequestError


class ExportStudyBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    result_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    verification_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


def install_research_routes(app, world, controller, *, csrf_token: str, workspace_path: Path) -> None:
    router = APIRouter(prefix="/api/v2/operator/research", tags=["local-research-evidence"])
    config = world.config.get("operator_research", {})
    root = Path(__file__).resolve().parents[1]
    library = StudyLibrary(data_root=Path(config.get("data_root", root / "data/studies")),
        out_dir=Path(config.get("out_dir", root / "reports/out")),
        export_root=workspace_path.parent / "research-exports")
    app.state.study_library = library
    lock = threading.Lock()

    def authorize(token: str | None, run_id: str, fork_id: str | None, tick: str) -> dict:
        if controller.hosted_safe or not config.get("enabled", True):
            raise HTTPException(status_code=403, detail="Study library is available to the local operator only.")
        if not token or token != csrf_token:
            raise HTTPException(status_code=403, detail="Valid operator CSRF token required.")
        context = lineage(world.store)
        if run_id != context["run_id"] or tick != "live":
            raise HTTPException(status_code=409, detail="Study library requires the current local run context.")
        try:
            validate_fork(world.store, fork_id)
        except ProjectionRequestError as exc:
            raise HTTPException(status_code=409, detail="Run fork changed; refresh the workspace.") from exc
        return {"run_id": context["run_id"], "fork_id": context["fork_id"], "tick": "live"}

    async def read_work(function, *args):
        # The lock remains held by the worker even if its HTTP caller disconnects.
        def work():
            with lock:
                return function(*args)
        try:
            return await asyncio.to_thread(work)
        except StudyIdentityChanged as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Study or export not found.") from exc
        except (StudyArtifactError, OSError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail="Study evidence is unavailable, invalid or exceeds this interface's limits.") from exc

    @router.get("/studies")
    async def studies(run_id: str, response: Response, fork_id: str | None = None, tick: str = "live",
                      x_csrf_token: str | None = Header(default=None)):
        context = authorize(x_csrf_token, run_id, fork_id, tick)
        response.headers["Cache-Control"] = "private, no-store"
        catalog = await read_work(library.public_catalog)
        return {"contract": "operator-study-catalog-v1", "context": context, **catalog,
                "scope": "Saved studies on this local server; independent of the observed world.",
                "capabilities": {"verify": True, "compare": True, "private_export": True,
                                 "launch": False, "checkpoint_fork": False}}

    @router.get("/studies/{study_id}")
    async def study(study_id: str, run_id: str, response: Response,
                    result_sha256: str = Query(pattern=r"^[a-f0-9]{64}$"),
                    fork_id: str | None = None, tick: str = "live",
                    x_csrf_token: str | None = Header(default=None)):
        context = authorize(x_csrf_token, run_id, fork_id, tick)
        response.headers["Cache-Control"] = "private, no-store"
        return {"context": context, **await read_work(library.verify, study_id, result_sha256)}

    @router.post("/studies/{study_id}/export")
    async def export(study_id: str, body: ExportStudyBody, run_id: str, response: Response,
                     fork_id: str | None = None, tick: str = "live",
                     x_csrf_token: str | None = Header(default=None)):
        context = authorize(x_csrf_token, run_id, fork_id, tick)
        response.headers["Cache-Control"] = "private, no-store"
        return {"context": context, **await read_work(library.export, study_id,
            body.result_sha256, body.verification_sha256)}

    @router.get("/exports/{token}")
    async def download(token: str, run_id: str, fork_id: str | None = None, tick: str = "live",
                       x_csrf_token: str | None = Header(default=None)):
        authorize(x_csrf_token, run_id, fork_id, tick)
        path = await read_work(library.download_path, token)
        return FileResponse(path, media_type="application/zip", filename=f"study-{token}.zip",
                            headers={"Cache-Control": "private, no-store"})

    app.include_router(router)

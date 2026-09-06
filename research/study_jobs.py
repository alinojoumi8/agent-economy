"""Local, durable operator launches of bounded fresh-genesis price pilots.

Only the fixed price-lab profile and declared preset parameters are accepted.
A dedicated supervisor owns execution, so an HTTP disconnect or server restart
does not relaunch a study. Operational claims never enter a scientific database.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import Field, model_validator

from research.artifacts import code_identity, digest_json, file_sha256, publish_json
from research.price_catalog import draft_price_study, price_study_catalog
from research.process_lock import process_lock, ProcessLockBusy
from research.studies import Contract, Digest, StudySpec, validate_study_inputs
from research.study_results import StudyArtifactError, StudyIdentityChanged, read_json
from research.study_runner import run_study, validate_execution
from run_config import load_config

ROOT = Path(__file__).resolve().parents[1]
MIB = 1024 * 1024
START_GRACE_SECONDS = 30


class PilotInputError(ValueError):
    """A safe, operator-facing rejection of a bounded pilot request."""


class PilotRequest(Contract):
    preset: Literal["G2", "F2"]
    seeds: Annotated[list[Annotated[int, Field(ge=0, le=2**31 - 1)]], Field(min_length=1, max_length=5)]
    horizon: Annotated[int, Field(ge=3, le=30)]
    intervention_tick: Annotated[int, Field(ge=1, le=30)]
    goods_firm_id: Literal[2, 3] = 2
    equity_firm_id: Literal[1] = 1
    max_wall_seconds: Annotated[int, Field(ge=10, le=300)] = 180
    max_disk_mib: Annotated[int, Field(ge=32, le=128)] = 128

    @model_validator(mode="after")
    def ordered(self):
        if self.intervention_tick > self.horizon or len(set(self.seeds)) != len(self.seeds):
            raise ValueError("intervention must be within the horizon and seeds must be unique")
        return self


class LaunchRequest(Contract):
    draft_sha256: Digest
    idempotency_key: Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]


@contextmanager
def execution_lock(path: Path, *, wait_seconds: float = 0):
    """Process-owned, nonblocking lock; never unlink a lock another process uses."""
    try:
        with process_lock(path, wait_seconds=wait_seconds):
            yield
    except ProcessLockBusy as exc:
        raise StudyIdentityChanged("A study operation is already active; refresh its status.") from exc


class StudyJobs:
    def __init__(self, root: Path, *, data_root: Path, out_dir: Path):
        self.root, self.data_root, self.out_dir = root.resolve(), data_root.resolve(), out_dir.resolve()

    def path(self, kind: str, identity: str) -> Path:
        if kind not in {"drafts", "jobs"} or not re.fullmatch(r"[a-f0-9]{32}", identity):
            raise KeyError("study draft or job not found")
        path = self.root / kind / identity
        if not path.resolve().is_relative_to(self.root) or path.is_symlink():
            raise StudyArtifactError("operator artifact escaped its root")
        return path

    def _read(self, path: Path) -> dict:
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise StudyArtifactError("operator artifact escaped its root")
        if path.stat().st_size > 512 * 1024:
            raise StudyArtifactError("operator artifact exceeds its size limit")
        return read_json(path)

    @staticmethod
    def capabilities() -> dict:
        return {"contract": "operator-study-launch-capabilities-v1", **price_study_catalog(),
            "origin": "fresh_genesis", "profile": "price-lab-pilot", "population": 14,
            "limits": {"max_seeds": 5, "max_horizon": 30, "max_wall_seconds": 300,
                       "max_disk_mib": 128, "concurrency": 1, "provider_calls": 0, "spend_usd": 0},
            "scope": "New independent worlds; the observed world is not a parent checkpoint.",
            "checkpoint_fork": False, "live_models": False, "resume": False}

    @staticmethod
    def _spec(request: PilotRequest, config: dict) -> StudySpec:
        if config.get("population", {}).get("size") != 14 or config.get("firms", {}).get("count") != 3:
            raise PilotInputError("The local interface requires the 14-agent, 3-firm pilot profile.")
        spec = draft_price_study(config, request.preset, seeds=request.seeds,
            horizon=request.horizon, intervention_tick=request.intervention_tick,
            goods_firm_id=request.goods_firm_id, equity_firm_id=request.equity_firm_id)
        values = spec.model_dump(mode="json")
        values["operations"].update(max_wall_seconds=request.max_wall_seconds,
                                    max_disk_bytes=request.max_disk_mib * MIB)
        spec = StudySpec.model_validate(values)
        validate_execution(spec, config)
        return spec

    def validate(self, request: PilotRequest, context: dict) -> dict:
        before = code_identity()
        config = load_config(ROOT / "runs/price-lab-pilot.yaml")
        spec = self._spec(request, config)
        protocol = validate_study_inputs(spec, config, input_root=ROOT)
        # Explicit planning heuristic, including source and replay; not a measured forecast.
        cells = len(request.seeds) * len(spec.arms)
        estimate = cells * (8 * MIB + request.horizon * 256 * 1024)
        if estimate > request.max_disk_mib * MIB:
            raise PilotInputError("The planning storage estimate exceeds the disk budget. Reduce seeds or horizon, or increase the budget.")
        if code_identity() != before:
            raise StudyIdentityChanged("Source changed during validation; validate again.")
        identity = uuid4().hex
        draft = {"contract": "operator-study-draft-v1", "id": identity, "context": context,
            "request": request.model_dump(mode="json"), "code": before, "protocol": protocol,
            "estimate": {"worlds": cells, "source_and_replay_ticks": cells * request.horizon * 2,
                "disk_bytes": estimate, "method": "planning allowance: 8 MiB/world plus 256 KiB/world-tick, including replay; uncalibrated",
                "wall_seconds_limit": request.max_wall_seconds, "disk_bytes_limit": request.max_disk_mib * MIB,
                "provider_calls": 0, "spend_usd": 0}}
        publish_json(self.path("drafts", identity) / "draft.json", draft)
        return self.draft(identity, context)

    def _draft(self, identity: str, context: dict) -> dict:
        path = self.path("drafts", identity) / "draft.json"
        if not path.is_file():
            raise KeyError("study draft not found")
        draft = self._read(path)
        if draft.get("id") != identity or draft.get("context") != context:
            raise StudyIdentityChanged("Study draft belongs to a different run context.")
        return draft

    def draft(self, identity: str, context: dict) -> dict:
        draft = self._draft(identity, context)
        launched = self.path("drafts", identity) / "launch.json"
        job_id = self._read(launched)["job_id"] if launched.is_file() else None
        return {"contract": draft["contract"], "id": identity, "context": context,
            "draft_sha256": digest_json(draft), "origin": "fresh_genesis", "request": draft["request"],
            "estimate": draft["estimate"], "source_identity": draft["code"],
            "spec": draft["protocol"]["study"], "executed": False if job_id is None else None, "job_id": job_id}

    def _clear_active(self, job_id: str) -> None:
        path = self.root / "active.json"
        if path.exists() and self._read(path).get("job_id") == job_id:
            path.unlink()  # Only this disposable scheduler pointer; claims/evidence remain.

    def launch(self, identity: str, body: LaunchRequest, context: dict) -> dict:
        draft = self._draft(identity, context)
        if digest_json(draft) != body.draft_sha256:
            raise StudyIdentityChanged("Validated draft changed; validate again before running.")
        directory = self.path("drafts", identity)
        with execution_lock(self.root / "scheduler.lock"):
            launched = directory / "launch.json"
            if launched.exists():
                claim = self._read(launched)
                if claim["request"] != body.model_dump(mode="json"):
                    raise StudyIdentityChanged("This draft already has a launch; open its job or validate a new draft.")
                return self.status(claim["job_id"], context)
            active = self.root / "active.json"
            if active.exists():
                previous = self._read(active)["job_id"]
                if (self.path("jobs", previous) / "terminal.json").is_file():
                    self._clear_active(previous)
                else:
                    raise StudyIdentityChanged("A local study is active or needs recovery; inspect its job before launching another.")
            if code_identity() != draft["code"]:
                raise StudyIdentityChanged("Source changed after validation; validate a new draft.")
            # A locally edited draft cannot bypass the interface's fixed profile
            # or resource bounds, even if its caller supplies the edited digest.
            request = PilotRequest.model_validate(draft["request"])
            config = load_config(ROOT / "runs/price-lab-pilot.yaml")
            expected = validate_study_inputs(self._spec(request, config), config, input_root=ROOT)
            if draft["protocol"] != expected:
                raise StudyIdentityChanged("Saved protocol no longer matches the bounded pilot request. Validate a new draft.")
            job_id = digest_json({"draft": identity, "key": body.idempotency_key})[:32]
            job = self.path("jobs", job_id)
            claim = {"contract": "operator-study-job-v1", "job_id": job_id, "draft_id": identity,
                "request": body.model_dump(mode="json"), "context": context, "created_at": time.time(),
                "data_root": str(self.data_root), "out_dir": str(self.out_dir)}
            publish_json(job / "claim.json", claim)
            publish_json(launched, claim)
            publish_json(active, {"job_id": job_id})
            try:
                with (job / "supervisor.log").open("xb") as log:
                    process = subprocess.Popen([sys.executable, "-m", "research.study_jobs", "execute",
                        "--root", str(self.root), "--job", job_id], cwd=ROOT,
                        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                # Reap our child without tying execution to the HTTP request's lifetime.
                threading.Thread(target=process.wait, daemon=True, name=f"study-reap-{job_id[:8]}").start()
            except OSError:
                publish_json(job / "terminal.json", {"status": "failed", "reason": "supervisor_start_failed"})
                self._clear_active(job_id)
        return self.status(job_id, context)

    def status(self, identity: str, context: dict) -> dict:
        job = self.path("jobs", identity)
        if not (job / "claim.json").is_file():
            raise KeyError("study job not found")
        claim = self._read(job / "claim.json")
        if claim.get("job_id") != identity or claim.get("context") != context:
            raise StudyIdentityChanged("Study job belongs to a different run context.")
        draft = self._draft(claim["draft_id"], context)
        terminal = job / "terminal.json"
        if terminal.is_file():
            stored = self._read(terminal)
            state = {key: stored[key] for key in ("status", "reason", "eligible_cells", "study_id", "result_sha256", "error_type") if key in stored}
        else:
            try:
                with execution_lock(job / "execution.lock"):
                    interrupted = (job / "started.json").exists() or time.time() - claim["created_at"] > START_GRACE_SECONDS
                    try:
                        with execution_lock(job / "worker.lock"):
                            state = {"status": "interrupted" if interrupted else "starting",
                                     "reason": "supervisor_no_longer_active" if interrupted else None}
                    except StudyIdentityChanged:
                        state = {"status": "interrupted_worker_active", "reason": "supervisor_lost_worker_stopping"}
            except StudyIdentityChanged:
                state = {"status": "running", "reason": None}
        cells = len(draft["protocol"]["study"]["arms"]) * len(draft["request"]["seeds"])
        progress = [self._read(job / f"cell-{index}.json") for index in range(1, cells + 1)
                    if (job / f"cell-{index}.json").is_file()]
        return {"contract": "operator-study-job-status-v1", "id": identity, "context": context,
            "draft_id": claim["draft_id"], "draft_sha256": claim["request"]["draft_sha256"],
            "title": draft["protocol"]["study"]["title"], "origin": "fresh_genesis",
            "created_at": claim["created_at"], "expected_cells": cells, "finished_cells": len(progress),
            "cells": progress, "recoverable": state["status"] == "interrupted" and not terminal.is_file(), **state}

    def active(self, context: dict) -> dict:
        path = self.root / "active.json"
        if not path.is_file():
            return {"active_job": None, "launch_blocked": False}
        try:
            identity = self._read(path)["job_id"]
            state = self.status(identity, context)
            return {"active_job": state, "launch_blocked": state["status"] in {"starting", "running", "interrupted", "interrupted_worker_active"}}
        except StudyIdentityChanged:
            return {"active_job": None, "launch_blocked": True,
                    "reason": "A study from another local run context owns the launch slot. Return to that workspace to inspect it."}

    def recover(self, identity: str, context: dict) -> dict:
        job = self.path("jobs", identity)
        with execution_lock(self.root / "scheduler.lock"), execution_lock(job / "execution.lock"), execution_lock(job / "worker.lock"):
            state = self.status(identity, context) if (job / "terminal.json").exists() else None
            claim = self._read(job / "claim.json")
            if claim.get("context") != context:
                raise StudyIdentityChanged("Study job belongs to a different run context.")
            if not state:
                if not (job / "started.json").exists() and time.time() - claim["created_at"] <= START_GRACE_SECONDS:
                    raise StudyIdentityChanged("The supervisor is still starting; refresh its status.")
                publish_json(job / "terminal.json", {"status": "interrupted", "reason": "operator_released_interrupted_job"})
            self._clear_active(identity)
        return self.status(identity, context)


def execute_job(root: Path, identity: str) -> None:
    # Root/ID are passed by the server, never supplied as executable commands.
    provisional = StudyJobs(root, data_root=root, out_dir=root)
    job = provisional.path("jobs", identity)
    claim = provisional._read(job / "claim.json")
    service = StudyJobs(root, data_root=Path(claim["data_root"]), out_dir=Path(claim["out_dir"]))
    with execution_lock(job / "execution.lock", wait_seconds=5):
        with execution_lock(service.root / "scheduler.lock", wait_seconds=5):
            if (job / "terminal.json").exists() or service._read(service.root / "active.json").get("job_id") != identity:
                return
            publish_json(job / "started.json", {"started_at": time.time()})
        try:
            draft = service._draft(claim["draft_id"], claim["context"])
            if digest_json(draft) != claim["request"]["draft_sha256"]:
                raise StudyIdentityChanged("validated draft changed")
            spec = StudySpec.model_validate(draft["protocol"]["study"])

            def progress(event: dict):
                if event["stage"] == "prepared":
                    publish_json(job / "batch.json", event["batch"])
                else:
                    row = event["row"]
                    publish_json(job / f"cell-{event['index']}.json", {
                        "arm": row["arm"], "seed": row["seed"], "execution_status": row["execution_status"],
                        "eligibility": row["eligibility"], "ticks": row.get("ticks")})

            result = run_study(spec, draft["protocol"]["resolved_config"], input_root=ROOT,
                data_root=service.data_root, out_dir=service.out_dir, expected_code=draft["code"],
                progress=progress, worker_guard_path=job / "worker.lock")
            path = Path(result["artifacts"]["json"])
            eligible = sum(row["eligibility"]["status"] == "eligible" for row in result["results"])
            terminal = {"status": "completed" if eligible == len(result["results"]) else "completed_with_exclusions",
                "eligible_cells": eligible, "study_id": digest_json(path.relative_to(service.out_dir).as_posix())[:32],
                "result_sha256": file_sha256(path), "reason": result["operations"]["stop_reason"]}
        except Exception as exc:
            terminal = {"status": "failed", "reason": "supervisor_failed", "error_type": type(exc).__name__}
        publish_json(job / "terminal.json", terminal)
        # If a simultaneous short API operation holds the scheduler lock, the
        # terminal receipt still lets the next launch retire this pointer safely.
        try:
            with execution_lock(service.root / "scheduler.lock"):
                service._clear_active(identity)
        except StudyIdentityChanged:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["execute"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--job", required=True)
    args = parser.parse_args()
    execute_job(args.root, args.job)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

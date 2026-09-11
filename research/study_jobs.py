"""Local, durable operator launches of bounded fresh or saved-world pilots.

Only the fixed price-lab profile and declared preset parameters are accepted.
A dedicated supervisor owns execution, so an HTTP disconnect or server restart
does not relaunch a study. Operational claims never enter a scientific database.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from itertools import islice
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
from research.price_catalog import draft_checkpoint_price_study, draft_price_study, price_study_catalog
from research.operator_checkpoints import OperatorCheckpoints, study_origin_view
from research.operator_policies import OperatorPolicies, PolicySelection
from research.policy_operator import allowance_view, policy_design_view
from research.policy_studies import draft_checkpoint_policy_comparison, draft_policy_comparison, study_cells
from research.process_lock import process_lock, ProcessLockBusy
from research.studies import Contract, Digest, StudySpec, validate_study_inputs
from research.study_results import StudyArtifactError, StudyIdentityChanged, read_json
from research.study_runner import run_study, validate_execution
from research.working_studies import validate_resume
from research.working_contracts import phase_controls
from world.phases import phase_names_for_semantics
from run_config import load_config

ROOT = Path(__file__).resolve().parents[1]
MIB = 1024 * 1024
START_GRACE_SECONDS = 30


class PilotInputError(ValueError):
    """A safe, operator-facing rejection of a bounded pilot request."""


class CheckpointSelection(Contract):
    id: Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
    database_sha256: Digest
    receipt_sha256: Digest


class PilotRequest(Contract):
    preset: Literal["G2", "F2"]
    origin: Literal["fresh_genesis", "verified_checkpoints"] = "fresh_genesis"
    seeds: Annotated[list[Annotated[int, Field(ge=0, le=2**31 - 1)]], Field(min_length=1, max_length=5)] | None = None
    checkpoints: Annotated[list[CheckpointSelection], Field(min_length=1, max_length=5)] | None = None
    warmup_ticks: Annotated[int, Field(ge=0, le=29)] = 0
    horizon: Annotated[int, Field(ge=3, le=30)]
    intervention_tick: Annotated[int, Field(ge=1, le=30)]
    goods_firm_id: Literal[2, 3] = 2
    equity_firm_id: Literal[1] = 1
    max_wall_seconds: Annotated[int, Field(ge=10, le=300)] = 180
    max_disk_mib: Annotated[int, Field(ge=32, le=128)] = 128
    pause_after_ticks: Annotated[int, Field(ge=1, le=30)] | None = None
    pause_after_phase: Literal["NIGHT_CLOSE", "MORNING", "EXECUTION", "MARKET",
                               "NEWSROOM", "EVENING", "MEMORY", "FINALIZE"] | None = None

    @model_validator(mode="after")
    def ordered(self):
        if self.origin == "fresh_genesis":
            if self.seeds is None or self.checkpoints is not None or self.warmup_ticks:
                raise ValueError("fresh worlds require seeds and cannot declare checkpoints or checkpoint warmup")
        elif self.seeds is not None or not self.checkpoints:
            raise ValueError("saved worlds require checkpoint selections and retain their original seeds")
        if self.checkpoints and len({item.id for item in self.checkpoints}) != len(self.checkpoints):
            raise ValueError("choose each checkpoint only once")
        if self.intervention_tick > self.horizon or (self.seeds and len(set(self.seeds)) != len(self.seeds)):
            raise ValueError("intervention must be within the horizon and seeds must be unique")
        if self.pause_after_ticks is not None and self.pause_after_ticks >= self.horizon:
            raise ValueError("the planned pause must precede the horizon")
        if self.pause_after_phase is not None and self.pause_after_ticks is not None:
            raise ValueError("choose a saved-day limit or a phase pause")
        return self


class LaunchRequest(Contract):
    draft_sha256: Digest
    idempotency_key: Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]


class PolicyLaunchRequest(LaunchRequest):
    approve_live_inference: Literal[True]

    @model_validator(mode="before")
    @classmethod
    def explicit_approval(cls, value):
        if isinstance(value, dict) and value.get("approve_live_inference") is not True:
            raise ValueError("policy launch requires explicit true approval")
        return value


class PolicyPilotRequest(Contract):
    preset: Literal["POLICY"]
    design: PolicySelection
    origin: Literal["fresh_genesis", "verified_checkpoints"] = "fresh_genesis"
    seeds: Annotated[list[Annotated[int, Field(ge=0, le=2**31 - 1)]], Field(min_length=1, max_length=5)] | None = None
    checkpoints: Annotated[list[CheckpointSelection], Field(min_length=1, max_length=5)] | None = None
    model_replicates: Annotated[list[Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,31}$")]], Field(min_length=1, max_length=3)]
    horizon: Annotated[int, Field(ge=3, le=30)]
    max_wall_seconds: Annotated[int, Field(ge=10, le=600)] = 300
    max_disk_mib: Annotated[int, Field(ge=32, le=1024)] = 256
    max_provider_calls: Annotated[int, Field(ge=1, le=5000)]
    max_tokens: Annotated[int, Field(ge=1, le=10_000_000)]
    max_spend_usd: Annotated[float, Field(ge=.000001, le=5)]
    pause_after_ticks: Annotated[int, Field(ge=1, le=30)] | None = None
    pause_after_phase: Literal["NIGHT_CLOSE", "MORNING", "EXECUTION", "MARKET",
                               "NEWSROOM", "EVENING", "MEMORY", "FINALIZE"] | None = None

    @model_validator(mode="after")
    def ordered(self):
        if self.origin == "fresh_genesis":
            if not self.seeds or self.checkpoints is not None or len(set(self.seeds)) != len(self.seeds):
                raise ValueError("fresh policy worlds require distinct seeds and no checkpoints")
        elif self.seeds is not None or not self.checkpoints:
            raise ValueError("saved policy worlds require explicit checkpoints and retain their seeds")
        if self.checkpoints and len({item.id for item in self.checkpoints}) != len(self.checkpoints):
            raise ValueError("choose each checkpoint only once")
        if len(set(self.model_replicates)) != len(self.model_replicates):
            raise ValueError("model draw labels must be distinct")
        if self.pause_after_ticks is not None and self.pause_after_ticks >= self.horizon:
            raise ValueError("the planned pause must precede the horizon")
        if self.pause_after_phase is not None and self.pause_after_ticks is not None:
            raise ValueError("choose a saved-day limit or a phase pause")
        return self


def pilot_request(value: dict) -> PilotRequest | PolicyPilotRequest:
    return (PolicyPilotRequest if value.get("preset") == "POLICY" else PilotRequest).model_validate(value)


class ResumeRequest(Contract):
    progress_sha256: Digest
    resume_check_sha256: Digest
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
    def __init__(self, root: Path, *, data_root: Path, out_dir: Path, checkpoint_root: Path | None = None,
                 policy_root: Path | None = None):
        self.root, self.data_root, self.out_dir = root.resolve(), data_root.resolve(), out_dir.resolve()
        self.checkpoints = OperatorCheckpoints(checkpoint_root or ROOT / "data/checkpoints")
        self.policies = OperatorPolicies(policy_root or ROOT / "data/policies")

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
            "scope": "New worlds or explicitly selected compatible saved worlds; the observed world is never selected automatically.",
            "origins": ["fresh_genesis", "verified_checkpoints"],
            "checkpoint_source_mib": OperatorCheckpoints.MAX_SOURCE_BYTES // MIB,
            "checkpoint_fork": True, "live_models": False, "resume": True,
            "pause_phases": list(phase_names_for_semantics(7))}

    def checkpoint_catalog(self) -> dict:
        return self.checkpoints.catalog(load_config(ROOT / "runs/price-lab-pilot.yaml"))

    def policy_catalog(self) -> dict:
        return self.policies.catalog(load_config(ROOT / "runs/price-lab-pilot.yaml"))

    def launch_capabilities(self) -> dict:
        catalog = self.policy_catalog()
        return {**self.capabilities(), "live_models": bool(catalog["items"]), "policy_designs": catalog}

    def input_root(self, request: PilotRequest | PolicyPilotRequest) -> Path:
        return self.checkpoints.root if request.origin == "verified_checkpoints" else ROOT

    def _spec(self, request: PilotRequest | PolicyPilotRequest, config: dict) -> StudySpec:
        if config.get("population", {}).get("size") != 14 or config.get("firms", {}).get("count") != 3:
            raise PilotInputError("The local interface requires the 14-agent, 3-firm pilot profile.")
        if isinstance(request, PolicyPilotRequest):
            policies, tariffs = self.policies.resolve(request.design)
            options = dict(policies=policies, tariffs=tariffs, model_replicates=request.model_replicates,
                horizon=request.horizon, max_provider_calls=request.max_provider_calls,
                max_tokens=request.max_tokens, max_spend_usd=request.max_spend_usd,
                max_wall_seconds=request.max_wall_seconds, max_disk_bytes=request.max_disk_mib * MIB)
            if request.origin == "verified_checkpoints":
                spec = draft_checkpoint_policy_comparison(config,
                    checkpoints=self.checkpoints.resolve(request.checkpoints, config), input_root=self.checkpoints.root, **options)
            else:
                spec = draft_policy_comparison(config, seeds=request.seeds, **options)
        elif request.origin == "verified_checkpoints":
            paths = self.checkpoints.resolve(request.checkpoints, config)
            spec = draft_checkpoint_price_study(config, request.preset, checkpoints=paths,
                input_root=self.checkpoints.root, horizon=request.horizon,
                intervention_tick=request.intervention_tick, warmup_ticks=request.warmup_ticks,
                goods_firm_id=request.goods_firm_id, equity_firm_id=request.equity_firm_id,
                max_disk_bytes=request.max_disk_mib * MIB, max_wall_seconds=request.max_wall_seconds)
            if request.pause_after_ticks is not None and request.pause_after_ticks >= request.horizon - spec.origin.tick:
                raise PilotInputError("The planned pause must precede the remaining continuation horizon.")
        else:
            spec = draft_price_study(config, request.preset, seeds=request.seeds,
                horizon=request.horizon, intervention_tick=request.intervention_tick,
                goods_firm_id=request.goods_firm_id, equity_firm_id=request.equity_firm_id)
        if request.pause_after_ticks is not None and request.pause_after_ticks >= request.horizon - (spec.origin.tick if spec.origin else 0):
            raise PilotInputError("The planned pause must precede the remaining continuation horizon.")
        values = spec.model_dump(mode="json")
        values["operations"].update(max_wall_seconds=request.max_wall_seconds,
            max_disk_bytes=request.max_disk_mib * MIB,
            pause_policy="preserve_and_resume_phases" if request.pause_after_phase else "preserve_and_resume")
        spec = StudySpec.model_validate(values)
        validate_execution(spec, config)
        phase_controls(spec.operations.pause_policy, spec.model.engine_semantics_version,
                       ticks=request.pause_after_ticks, phase=request.pause_after_phase)
        return spec

    def validate(self, request: PilotRequest | PolicyPilotRequest, context: dict) -> dict:
        before = code_identity()
        config = load_config(ROOT / "runs/price-lab-pilot.yaml")
        spec = self._spec(request, config)
        protocol = validate_study_inputs(spec, config, input_root=self.input_root(request))
        # Explicit planning heuristic, including source and replay; not a measured forecast.
        draws = len(spec.randomness.model_replicates) if spec.policy_design else 1
        cells = len(spec.randomness.seeds) * len(spec.arms) * draws
        remaining = request.horizon - (spec.origin.tick if spec.origin else 0)
        copy_bytes = sum(row["byte_size"] for row in protocol.get("checkpoint_origins", {}).values()) * (1 + 2 * len(spec.arms) * draws)
        estimate = copy_bytes + cells * (8 * MIB + remaining * 256 * 1024)
        if estimate > request.max_disk_mib * MIB:
            raise PilotInputError("The planning storage estimate exceeds the disk budget. Reduce seeds or horizon, or increase the budget.")
        if code_identity() != before:
            raise StudyIdentityChanged("Source changed during validation; validate again.")
        identity = uuid4().hex
        draft = {"contract": "operator-study-draft-v1", "id": identity, "context": context,
            "request": request.model_dump(mode="json"), "code": before, "protocol": protocol,
            "estimate": {"worlds": cells, "source_and_replay_ticks": cells * remaining * 2,
                "disk_bytes": estimate, "origin_copy_bytes": copy_bytes,
                "method": "planning allowance: initial saved-world copies plus 8 MiB/world and 256 KiB/new world-tick, including replay; uncalibrated",
                "wall_seconds_limit": request.max_wall_seconds, "disk_bytes_limit": request.max_disk_mib * MIB,
                "provider_calls": 0, "spend_usd": 0}}
        if spec.policy_design:
            draft["estimate"].update(independent_worlds=len(spec.randomness.seeds), model_draws=draws,
                provider_calls_limit=spec.operations.max_provider_calls, tokens_limit=spec.operations.max_tokens,
                spend_usd_limit=spec.operations.max_spend_usd, preflight_ready=None)
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
        spec = draft["protocol"]["study"]
        policy = spec.get("protocol_version") == "research-study-v3"
        if policy:
            # Public review omits gateways, endpoint references and input paths.
            parsed = StudySpec.model_validate(spec)
            spec = {key: spec[key] for key in ("protocol_version", "title", "hypothesis", "domains",
                "randomness", "time", "analysis", "operations", "limitations")}
            spec["arms"] = [{"key": arm.key, "label": arm.label, "role": arm.role, "policy": arm.policy} for arm in parsed.arms]
        return {"contract": draft["contract"], "id": identity, "context": context,
            "draft_sha256": digest_json(draft), "origin": study_origin_view(draft["protocol"])["kind"],
            "origin_details": study_origin_view(draft["protocol"]), "request": draft["request"],
            "estimate": draft["estimate"], "source_identity": draft["code"],
            "spec": spec, "executed": False if job_id is None else None, "job_id": job_id,
            **({"policy_design": policy_design_view(parsed), "provider_allowance": allowance_view(parsed, None)} if policy else {})}

    def _clear_active(self, job_id: str) -> None:
        path = self.root / "active.json"
        if path.exists() and self._read(path).get("job_id") == job_id:
            path.unlink()  # Only this disposable scheduler pointer; claims/evidence remain.

    def _require_slot(self):
        active = self.root / "active.json"
        if active.exists():
            previous = self._read(active)["job_id"]
            if (self.path("jobs", previous) / "terminal.json").is_file():
                self._clear_active(previous)
            else:
                raise StudyIdentityChanged("A local study is active or needs recovery; inspect its job before launching another.")

    def _start(self, job_id: str):
        job = self.path("jobs", job_id)
        try:
            with (job / "supervisor.log").open("xb") as log:
                process = subprocess.Popen([sys.executable, "-m", "research.study_jobs", "execute",
                    "--root", str(self.root), "--job", job_id], cwd=ROOT,
                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            threading.Thread(target=process.wait, daemon=True, name=f"study-reap-{job_id[:8]}").start()
        except OSError:
            publish_json(job / "terminal.json", {"status": "failed", "reason": "supervisor_start_failed"})
            self._clear_active(job_id)

    def launch(self, identity: str, body: LaunchRequest | PolicyLaunchRequest, context: dict) -> dict:
        draft = self._draft(identity, context)
        if digest_json(draft) != body.draft_sha256:
            raise StudyIdentityChanged("Validated draft changed; validate again before running.")
        request = pilot_request(draft["request"])
        if isinstance(request, PolicyPilotRequest) and not isinstance(body, PolicyLaunchRequest):
            raise PilotInputError("Review the original inference allowance and explicitly approve this policy launch.")
        if not isinstance(request, PolicyPilotRequest) and isinstance(body, PolicyLaunchRequest):
            raise PilotInputError("Inference approval is only accepted for a policy study draft.")
        directory = self.path("drafts", identity)
        with execution_lock(self.root / "scheduler.lock"):
            launched = directory / "launch.json"
            if launched.exists():
                claim = self._read(launched)
                if claim["request"] != body.model_dump(mode="json"):
                    raise StudyIdentityChanged("This draft already has a launch; open its job or validate a new draft.")
                return self.status(claim["job_id"], context)
            self._require_slot()
            if code_identity() != draft["code"]:
                raise StudyIdentityChanged("Source changed after validation; validate a new draft.")
            # A locally edited draft cannot bypass the interface's fixed profile
            # or resource bounds, even if its caller supplies the edited digest.
            config = load_config(ROOT / "runs/price-lab-pilot.yaml")
            expected = validate_study_inputs(self._spec(request, config), config, input_root=self.input_root(request))
            if draft["protocol"] != expected:
                raise StudyIdentityChanged("Saved protocol no longer matches the bounded pilot request. Validate a new draft.")
            job_id = digest_json({"draft": identity, "key": body.idempotency_key})[:32]
            job = self.path("jobs", job_id)
            claim = {"contract": "operator-study-job-v1", "job_id": job_id, "draft_id": identity,
                "request": body.model_dump(mode="json"), "context": context, "created_at": time.time(),
                "data_root": str(self.data_root), "out_dir": str(self.out_dir),
                "checkpoint_root": str(self.checkpoints.root)}
            if isinstance(request, PolicyPilotRequest):
                claim["policy_root"] = str(self.policies.root)
            publish_json(job / "claim.json", claim)
            publish_json(launched, claim)
            publish_json(self.root / "active.json", {"job_id": job_id})
            self._start(job_id)
        return self.status(job_id, context)

    def _resume_state(self, job: Path, draft: dict, context: dict) -> dict:
        batch = self._read(job / "batch.json")
        config = load_config(ROOT / "runs/price-lab-pilot.yaml")
        request = pilot_request(draft["request"])
        spec = self._spec(request, config)
        if draft["protocol"] != validate_study_inputs(spec, config, input_root=self.input_root(request)):
            raise StudyIdentityChanged("The saved pilot no longer matches its original profile.")
        state = validate_resume(batch["data_dir"], spec, config, input_root=self.input_root(request),
                                data_root=self.data_root, out_dir=self.out_dir)
        if state["batch"] != batch:
            raise StudyIdentityChanged("Saved job and working batch identities disagree.")
        last = state["records"][-1]
        progress = Path(batch["report_dir"]) / last["end"]["report"]["path"]
        progress_hash = file_sha256(progress)
        check = digest_json({"manifest_sha256": batch["manifest_sha256"], "batch_id": batch["batch_id"],
                             "progress_sha256": progress_hash, "end_sha256": last["end_sha256"], "context": context})
        return {"resumable": True, "resume_check_sha256": check, "progress_sha256": progress_hash,
                "active_wall_seconds": state["active_wall_seconds"],
                "remaining_wall_seconds": max(0, spec.operations.max_wall_seconds - state["active_wall_seconds"]),
                **({"provider_allowance": allowance_view(spec, {"provider_budget": state["provider_budget"]})} if spec.policy_design else {})}

    def resume(self, identity: str, body: ResumeRequest, context: dict) -> dict:
        job = self.path("jobs", identity)

        def authorized_claim():
            if not (job / "claim.json").is_file():
                raise KeyError("study job not found")
            value = self._read(job / "claim.json")
            if value.get("job_id") != identity or value.get("context") != context:
                raise StudyIdentityChanged("Study job belongs to a different run context.")
            return value

        authorized_claim()  # No new lock/directory for an absent or foreign job.
        if not (job / "terminal.json").is_file() and not (job / "resume.json").is_file():
            raise StudyIdentityChanged("Only a receipted paused study can resume.")
        with execution_lock(self.root / "scheduler.lock"), execution_lock(job / "execution.lock"), execution_lock(job / "worker.lock"):
            claim = authorized_claim()
            continuation = job / "resume.json"
            if continuation.exists():
                saved = self._read(continuation)
                if saved["request"] != body.model_dump(mode="json"):
                    raise StudyIdentityChanged("This pause already has a continuation; open its existing job.")
                return self.status(saved["job_id"], context)
            if self._read(job / "terminal.json").get("status") != "paused":
                raise StudyIdentityChanged("Only a receipted paused study can resume.")
            draft = self._draft(claim["draft_id"], context)
            if digest_json(draft) != claim["request"]["draft_sha256"]:
                raise StudyIdentityChanged("Validated draft changed; the pause cannot resume.")
            try:
                checked = self._resume_state(job, draft, context)
            except (ValueError, OSError, KeyError, TypeError) as exc:
                raise StudyIdentityChanged("Saved study is no longer compatible with this checkout, evidence or remaining budget. Refresh its job status.") from exc
            if body.progress_sha256 != checked["progress_sha256"] or body.resume_check_sha256 != checked["resume_check_sha256"]:
                raise StudyIdentityChanged("Working evidence changed; refresh and check it before resuming.")
            self._require_slot()
            job_id = digest_json({"parent_job": identity, "request": body.model_dump(mode="json")})[:32]
            resumed = {**claim, "job_id": job_id, "created_at": time.time(),
                "resume": {"parent_job_id": identity, "request": body.model_dump(mode="json"),
                           "batch": self._read(job / "batch.json")["data_dir"]}}
            publish_json(self.path("jobs", job_id) / "claim.json", resumed)
            publish_json(continuation, {"request": body.model_dump(mode="json"), "job_id": job_id})
            publish_json(self.root / "active.json", {"job_id": job_id})
            self._start(job_id)
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
        spec = StudySpec.model_validate(draft["protocol"]["study"])
        cells = len(study_cells(spec)) if spec.policy_design else len(spec.arms) * len(spec.randomness.seeds)
        progress = [self._read(job / f"cell-{index}.json") for index in range(1, cells + 1)
                    if (job / f"cell-{index}.json").is_file()]
        resume = {"resumable": False}
        if (job / "resume.json").is_file():
            resume["continuation_job_id"] = self._read(job / "resume.json")["job_id"]
        elif state["status"] == "paused":
            try:
                if digest_json(draft) != claim["request"]["draft_sha256"]:
                    raise StudyIdentityChanged("validated draft changed")
                resume = self._resume_state(job, draft, context)
            except (ValueError, OSError, KeyError, TypeError) as exc:
                # Never expose validation exceptions containing config or paths.
                reason = "working_evidence_changed_or_incompatible"
                for marker, code in (("code changed", "source_checkout_changed"),
                                     ("cumulative budget", "original_budget_exhausted"),
                                     ("original provider allowance", "original_budget_exhausted"),
                                     ("published studies", "study_already_finalized"),
                                     ("unfinished", "interrupted_segment_cannot_resume")):
                    if marker in str(exc):
                        reason = code
                resume["resume_unavailable_reason"] = reason
        return {"contract": "operator-study-job-status-v1", "id": identity, "context": context,
            "draft_id": claim["draft_id"], "draft_sha256": claim["request"]["draft_sha256"],
            "title": draft["protocol"]["study"]["title"], "origin": study_origin_view(draft["protocol"])["kind"],
            "origin_details": study_origin_view(draft["protocol"]),
            "created_at": claim["created_at"], "expected_cells": cells,
            "finished_cells": sum(row.get("eligibility", {}).get("status", "pending") != "pending" for row in progress),
            "cells": progress, "recoverable": state["status"] == "interrupted" and not terminal.is_file(),
            "parent_job_id": claim.get("resume", {}).get("parent_job_id"),
            **({"policy_design": policy_design_view(spec), "provider_allowance": allowance_view(spec, None)} if spec.policy_design else {}),
            **resume, **state}

    def for_study(self, study_id: str, context: dict) -> dict | None:
        """Find this workspace's most recent invocation without adopting CLI runs."""
        if not re.fullmatch(r"[a-f0-9]{32}", study_id):
            raise KeyError("study not found")
        root = self.root / "jobs"
        if not root.is_dir() or root.is_symlink() or not root.resolve().is_relative_to(self.root):
            return None
        matches = []
        for job in islice(root.iterdir(), 500):
            if not re.fullmatch(r"[a-f0-9]{32}", job.name) or job.is_symlink():
                continue
            try:
                claim = self._read(job / "claim.json")
                if claim.get("context") != context or not (job / "batch.json").is_file():
                    continue
                batch = self._read(job / "batch.json")
                relative = (Path(batch["report_dir"]) / "results.json").relative_to(self.out_dir).as_posix()
                if digest_json(relative)[:32] == study_id:
                    matches.append((float(claim["created_at"]), job.name))
            except (ValueError, OSError, KeyError, TypeError):
                continue
        return {**self.status(max(matches)[1], context), "study_id": study_id} if matches else None

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
    service = StudyJobs(root, data_root=Path(claim["data_root"]), out_dir=Path(claim["out_dir"]),
                        checkpoint_root=Path(claim["checkpoint_root"]) if claim.get("checkpoint_root") else None,
                        policy_root=Path(claim["policy_root"]) if claim.get("policy_root") else None)
    with execution_lock(job / "execution.lock", wait_seconds=5):
        with execution_lock(service.root / "scheduler.lock", wait_seconds=5):
            if (job / "terminal.json").exists() or service._read(service.root / "active.json").get("job_id") != identity:
                return
            publish_json(job / "started.json", {"started_at": time.time()})
        try:
            draft = service._draft(claim["draft_id"], claim["context"])
            if digest_json(draft) != claim["request"]["draft_sha256"]:
                raise StudyIdentityChanged("validated draft changed")
            request = pilot_request(draft["request"])
            if isinstance(request, PolicyPilotRequest):
                PolicyLaunchRequest.model_validate(claim["request"])
            config = load_config(ROOT / "runs/price-lab-pilot.yaml")
            spec = service._spec(request, config)
            if validate_study_inputs(spec, config, input_root=service.input_root(request)) != draft["protocol"]:
                raise StudyIdentityChanged("saved protocol differs from the bounded pilot request")

            def progress(event: dict):
                if event["stage"] == "prepared":
                    publish_json(job / "batch.json", event["batch"])
                else:
                    row = event["row"]
                    publish_json(job / f"cell-{event['index']}.json", {
                        "arm": row["arm"], "seed": row["seed"], "execution_status": row["execution_status"],
                        "eligibility": row["eligibility"], "ticks": row.get("ticks"),
                        **({key: row[key] for key in ("cell_key", "policy", "model_replicate")} if spec.policy_design else {}),
                        **({"position": {key: row["position"][key]
                            for key in ("completed_tick", "active_tick", "next_phase")}} if "position" in row else {})})

            result = run_study(spec, config, input_root=service.input_root(request),
                data_root=service.data_root, out_dir=service.out_dir, expected_code=draft["code"],
                progress=progress, worker_guard_path=job / "worker.lock",
                resume_batch=claim.get("resume", {}).get("batch"),
                pause_after_ticks=None if "resume" in claim else draft["request"].get("pause_after_ticks"),
                pause_after_phase=None if "resume" in claim else draft["request"].get("pause_after_phase"),
                **({"approve_live_inference": True} if isinstance(request, PolicyPilotRequest) else {}))
            path = Path(result["artifacts"]["json"])
            for index, row in enumerate(result["results"], 1):
                if not (job / f"cell-{index}.json").exists():
                    progress({"stage": "cell", "index": index, "row": row})
            eligible = sum(row["eligibility"]["status"] == "eligible" for row in result["results"])
            terminal = {"status": "paused" if result.get("status") == "paused" else (
                "completed" if eligible == len(result["results"]) else "completed_with_exclusions"),
                "eligible_cells": eligible, "study_id": digest_json((path.parent / "results.json").relative_to(service.out_dir).as_posix())[:32],
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

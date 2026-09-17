"""Allowlisted operator views of policy evidence, with every model draw intact."""
from __future__ import annotations

import copy
from pathlib import Path

from research.artifacts import digest_json, file_sha256
from research.operator_checkpoints import study_origin_view
from research.policy_evidence import load_policy_evidence
from research.policy_studies import study_cells
from research.process_lock import ProcessLockBusy
from research.studies import StudySpec
from research.study_results import StudyArtifactError, StudyIdentityChanged, verification_identity
from research.working_evidence import working_export_guard

COMPARISON = "operator-policy-study-comparison-v1"
WORKING = "operator-policy-working-study-v1"


def policy_design_view(spec: StudySpec) -> dict:
    """No gateway configuration, endpoint or credential reference crosses here."""
    return {"policies": [{"key": policy.key, "family": policy.behavior.family,
        "provider": policy.behavior.provider_reference, "model": policy.behavior.model_reference,
        "temperature": policy.behavior.temperature, "repair_temperature": policy.repair_temperature,
        "preflight_temperature": policy.preflight_temperature,
        "prompt_sha256": policy.behavior.prompt_sha256} for policy in spec.policy_design.policies],
        "independent_worlds": len(spec.randomness.seeds),
        "model_replicates": list(spec.randomness.model_replicates),
        "tariffs": [{"provider": tariff.provider, "model": tariff.model,
            "max_input_tokens": tariff.max_input_tokens, "max_output_tokens": tariff.max_output_tokens,
            "input_usd_per_million_tokens": tariff.input_nano_usd_per_token / 1000,
            "output_usd_per_million_tokens": tariff.output_nano_usd_per_token / 1000} for tariff in spec.policy_design.tariffs],
        "assigned_cells": len(study_cells(spec)),
        "aggregation": spec.policy_design.replicate_aggregation}


def allowance_view(spec: StudySpec, verification: dict | None) -> dict:
    usage = verification.get("provider_budget") if verification else None
    values = {key: usage.get(key) if usage else None for key in (
        "provider_calls", "reported_tokens", "encumbered_tokens", "unresolved_calls",
        "unknown_usage_calls", "breached_calls", "sealed")}
    values.update({target: usage[source] / 1e9 if usage else None for source, target in (
        ("usage_cost_nano_usd", "reported_cost_usd"), ("encumbered_nano_usd", "encumbered_usd"))})
    return {"limits": {key: getattr(spec.operations, key) for key in (
        "max_provider_calls", "max_tokens", "max_spend_usd", "max_wall_seconds", "max_disk_bytes")},
        "usage": values, "verified": usage is not None,
        "preflight_ready": verification.get("preflight_ready") if verification else None}


def _verification(verification: dict) -> dict:
    result = {key: verification[key] for key in (
        "contract", "status", "publication", "eligibility", "result_sha256", "declared_context",
        "preflight_ready", "stored_summary_matches", "active_wall_seconds") if key in verification}
    result["issues"] = [{key: issue[key] for key in ("cell_key", "reason") if key in issue}
                        for issue in verification.get("issues", [])]
    return result


def _identity(row: dict) -> dict:
    return {key: row[key] for key in ("cell_key", "policy", "model_replicate")}


def decorate_policy_comparison(view: dict, result: dict) -> dict:
    spec = StudySpec.model_validate(result["batch"]["manifest"]["study"])
    view.update(contract=COMPARISON, policy_design=policy_design_view(spec),
        provider_allowance=allowance_view(spec, result["verification"]),
        verification=_verification(result["verification"]))
    for projected, row in zip(view["attempts"], result["results"]):
        projected.update(_identity(row))
        projected.update({key: row.get(key) for key in (
            "provider_calls", "spend_usd", "inherited_provider_calls", "inherited_spend_usd")})
    for measurements in view["measurements"].values():
        for projected, row in zip(measurements, result["results"]):
            projected.update(_identity(row))
    view["arms"] = [{"key": arm.key, "label": arm.label, "role": arm.role, "policy": arm.policy} for arm in spec.arms]
    # Execution coverage comes from real cells, not the synthetic analysis rows
    # used to aggregate a complete block of draws into one world observation.
    view["world_coverage"], view["cell_coverage"] = {}, {}
    for arm in spec.arms:
        rows = [row for row in result["results"] if row["arm"] == arm.key]
        blocks = [block for block in result["summary"]["replication"]["blocks"] if block["arm"] == arm.key]
        view["cell_coverage"][arm.key] = {"assigned": len(rows),
            "started": sum(row["execution_status"] != "planned" for row in rows),
            "completed": sum(row["execution_status"] == "completed" for row in rows),
            "eligible": sum(row["eligibility"]["status"] == "eligible" for row in rows)}
        view["world_coverage"][arm.key] = {"assigned": len(spec.randomness.seeds),
            "started": sum(block["started_replicates"] > 0 for block in blocks),
            "completed": sum(all(row["execution_status"] == "completed" for row in rows if row["seed"] == seed)
                for seed in spec.randomness.seeds),
            "eligible": sum(block["status"] == "complete" for block in blocks)}
    return view


def working_policy_view(study_id: str, path: Path, expected_sha256: str, *, frozen: dict,
                        payload: dict, spec: StudySpec, data_root: Path, out_dir: Path) -> dict:
    cells = study_cells(spec)
    if len(cells) > 512:
        raise StudyArtifactError("working policy study exceeds the interface's assignment limit")
    state, checked = "checkpoint_unavailable", None
    if path.name != "manifest.json":
        try:
            with working_export_guard(path, data_root=data_root, out_dir=out_dir):
                checked = load_policy_evidence(path, data_root=data_root, out_dir=out_dir,
                    expected_sha256=expected_sha256)
            state = "paused"
        except ProcessLockBusy:
            state = "running"
        except (StudyArtifactError, ValueError, OSError):
            state = "needs_attention"
    reported = {row.get("cell_key"): row for row in (checked or payload).get("results", []) if isinstance(row, dict)}
    attempts = []
    for cell in cells:
        row = reported.get(cell["cell_key"], {})
        ticks = row.get("ticks")
        status = row.get("execution_status", "planned")
        attempt = {**cell, "expected_ticks": spec.time.horizon,
            "ticks": ticks if type(ticks) is int and 0 <= ticks <= spec.time.horizon else None,
            "execution_status": status if status in {"planned", "paused", "completed", "failed", "halted"} else "unknown",
            "eligibility": copy.deepcopy(row["eligibility"]) if checked else {
                "status": "pending", "reasons": ["working_evidence_not_verified"]}}
        if checked:
            if "position" in row:
                attempt["position"] = {key: row["position"][key] for key in ("completed_tick", "active_tick", "next_phase")}
            attempt.update({key: row.get(key) for key in (
                "provider_calls", "spend_usd", "inherited_provider_calls", "inherited_spend_usd")})
        attempts.append(attempt)
    verification = _verification(checked["verification"]) if checked else {
        "status": "not_verified", "publication": "working", "eligibility": "pending",
        "result_sha256": expected_sha256, "issues": [{"reason": state}]}
    view = {"contract": WORKING, "id": study_id, "state": state,
        "title": spec.title, "hypothesis": spec.hypothesis, "limitations": spec.limitations,
        "domains": spec.domains,
        "arms": [{"key": arm.key, "label": arm.label, "role": arm.role, "policy": arm.policy} for arm in spec.arms],
        "origin_details": study_origin_view(frozen["manifest"]),
        "measurement_window": [spec.time.measurement_start, spec.time.measurement_end],
        "attempts": attempts, "comparison_available": False, "export_available": bool(checked),
        "verification": verification, "manifest_sha256": frozen["manifest_sha256"],
        "source_identity": {key: frozen["manifest"]["code"].get(key) for key in ("git_commit", "source_tree_sha256")},
        "budget": {"max_wall_seconds": spec.operations.max_wall_seconds,
            "active_wall_seconds": verification.get("active_wall_seconds"), "max_disk_bytes": spec.operations.max_disk_bytes},
        "policy_design": policy_design_view(spec),
        "provider_allowance": allowance_view(spec, checked["verification"] if checked else None),
        "verification_sha256": verification_identity(checked) if checked else digest_json(verification)}
    if file_sha256(path) != expected_sha256:
        raise StudyIdentityChanged("Study progress changed; refresh the catalog before continuing.")
    return view

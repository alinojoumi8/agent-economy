"""Supervised, budgeted policy-study execution with independent replay."""
from __future__ import annotations

import asyncio
from contextlib import ExitStack, nullcontext
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Callable

from engine.store import Store
from llm.gateway import Gateway
from llm.readiness import validate_llm_config
from research.artifacts import code_identity, digest_json, file_sha256, publish_bytes, publish_json
from research.attempts import execute_attempt, verify_attempt
from research.policy_analysis import replicated_summary
from research.policy_studies import policy_configurations, provider_budget_contract, study_cells
from research.process_lock import process_lock
from research.provider_budget import BudgetLedgerError, ProviderBudget, ProviderBudgetContract
from research.studies import StudySpec, prepare_study, validate_study_inputs
from research.working_contracts import working_protocol


def validate_policy_execution(spec: StudySpec, config: dict, *, verify_source: bool = True) -> None:
    if spec.protocol_version != "research-study-v3" or spec.policy_design is None:
        raise ValueError("policy execution requires research-study-v3")
    if spec.model.engine_semantics_version < 7:
        raise ValueError("policy studies require persisted random state")
    if spec.operations.concurrency != 1:
        raise ValueError("policy studies supervise one world at a time")
    if spec.origin is not None:
        raise ValueError("saved-world policy changes require their explicit continuation contract")
    if spec.operations.pause_policy != "preserve_and_stop" and not working_protocol(spec.operations.pause_policy):
        raise ValueError("unsupported policy pause contract")
    if config.get("shocks"):
        raise ValueError("declare policy-study economic shocks in the assigned arms")
    if (len(study_cells(spec)) > 512 or len(spec.analysis.outcomes) > 64
            or spec.time.measurement_end - spec.time.measurement_start > 3660
            or len(spec.arms) * len(spec.randomness.seeds) * len(spec.analysis.outcomes)
                * spec.analysis.bootstrap_samples > 2_000_000):
        raise ValueError("policy study exceeds the bounded evidence verification envelope")
    policy_configurations(spec, config, verify_source=verify_source)


def _budget(batch: dict, *, scope: str, binding: str) -> ProviderBudget:
    contract = ProviderBudgetContract.model_validate_json(
        (Path(batch["data_dir"]) / "provider-budget-contract.json").read_text(encoding="utf-8"))
    expected = provider_budget_contract(StudySpec.model_validate(batch["manifest"]["study"]),
        batch["manifest"]["resolved_config"], manifest_sha256=batch["manifest_sha256"])
    if contract != expected:
        raise ValueError("provider budget differs from the prospective study")
    return ProviderBudget(Path(batch["data_dir"]) / "provider-budget.db", contract,
                          scope=scope, binding_key=binding)


def _preflight(config: dict, budget: ProviderBudget) -> dict:
    store = Store(":memory:")
    gateway = None
    try:
        store.init_run_meta("research-preflight", int(config.get("seed", 0)), config)
        gateway = Gateway(store, config, completion_guard=budget)
        report = asyncio.run(gateway.preflight(live=True, strict_contract=True))
        if report.get("live_checked") is not True:
            raise ValueError("live readiness was not checked")
        return {"ready": report.get("live_ready") is True,
                "checks": [{key: item[key] for key in ("provider", "model", "ok", "contract_ok") if key in item}
                           for item in report.get("checks", [])]}
    finally:
        if gateway is not None:
            gateway.close()
        store.close()


def _worker(batch: dict, cell: dict | None, policy_key: str, input_root: str,
            result_path: str, guard_path: str | None, preflight_scope: str | None = None) -> None:
    parent = multiprocessing.parent_process()
    if parent is not None:
        if not parent.is_alive():
            os._exit(70)

        def stop_if_orphaned():
            parent.join()
            os._exit(70)

        threading.Thread(target=stop_if_orphaned, daemon=True).start()
    with process_lock(Path(guard_path)) if guard_path else nullcontext():
        try:
            spec = StudySpec.model_validate(batch["manifest"]["study"])
            config = batch["manifest"]["resolved_config"]
            if digest_json(batch["manifest"]) != batch["manifest_sha256"] or code_identity() != batch["manifest"]["code"]:
                raise ValueError("prospective study source identity changed")
            declared = validate_study_inputs(spec, config, input_root=input_root)
            if any(digest_json(batch["manifest"].get(key)) != digest_json(value) for key, value in declared.items()):
                raise ValueError("prospective policy study changed")
            configured = declared["policy_configurations"][policy_key]
            scope = (preflight_scope or f"preflight-{policy_key}") if cell is None else cell["cell_key"]
            budget = _budget(batch, scope=scope, binding=policy_key)
            if cell is None:
                packet = {"contract": "policy-preflight-v1", "policy": policy_key,
                          "manifest_sha256": batch["manifest_sha256"],
                          **_preflight(configured, budget), "provider_usage": budget.snapshot(scope=scope)}
            else:
                from research.study_runner import arm_interventions, collect_outcomes

                if cell not in declared["assigned_cells"] or cell["policy"] != policy_key:
                    raise ValueError("worker is outside the prospective policy assignment")
                configured["shocks"] = arm_interventions(spec, cell["arm"])
                row = execute_attempt(run_id=f"policy-{cell['cell_key']}", seed=cell["seed"],
                    arm=cell["arm"], config=configured, ticks=spec.time.horizon,
                    data_dir=Path(batch["data_dir"]) / "cells" / cell["cell_key"],
                    collect=lambda store: collect_outcomes(store, spec), completion_guard=budget)
                packet = {"contract": "policy-cell-v1", "manifest_sha256": batch["manifest_sha256"],
                          "cell": cell, "attempt": row, "provider_usage": budget.snapshot(scope=scope)}
            if code_identity() != batch["manifest"]["code"]:
                raise ValueError("source changed during policy execution")
            validate_study_inputs(spec, config, input_root=input_root)
            publish_json(result_path, packet)
        except Exception as exc:
            # No prompts, provider error bodies or credential values in receipts.
            publish_json(result_path, {"contract": "policy-worker-failure-v1", "error_type": type(exc).__name__,
                "manifest_sha256": batch["manifest_sha256"], "cell": cell, "policy": policy_key})


def _stop(process) -> None:
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join(timeout=5)


def _supervise(batch: dict, cell: dict | None, policy: str, *, input_root: Path,
               guard_path: Path | None, deadline: float, max_disk_bytes: int,
               preflight_scope: str | None = None, receipt_relative: str | None = None) -> tuple[dict | None, Path, str | None]:
    from research.study_runner import _disk_bytes

    key = f"preflight-{policy}" if cell is None else f"cell-{cell['cell_key']}"
    from research.working_attempts import _member
    path = _member(Path(batch["data_dir"]), receipt_relative or f"{key}.json")

    def limit():
        if time.monotonic() >= deadline:
            return "wall_time_budget_exhausted"
        if _disk_bytes(Path(batch["data_dir"])) + _disk_bytes(Path(batch["report_dir"])) >= max_disk_bytes:
            return "disk_budget_exhausted"
        return None

    stopped = limit()
    if stopped:
        return None, path, stopped
    process = multiprocessing.get_context("spawn").Process(target=_worker,
        args=(batch, cell, policy, str(input_root), str(path), str(guard_path) if guard_path else None, preflight_scope),
        name=f"policy-{key[:32]}")
    process.start()
    try:
        while process.is_alive():
            process.join(timeout=.2)
            stopped = limit()
            if stopped:
                _stop(process)
                break
        exit_code = process.exitcode
    except BaseException:
        _stop(process)
        raise
    finally:
        process.close()
    packet = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    return packet, path, stopped or ("worker_failed" if exit_code else None)


def _missing(spec: StudySpec, cell: dict, reason: str) -> dict:
    return {**cell, "execution_status": "planned", "ticks": 0, "expected_ticks": spec.time.horizon,
        "metrics": {item.key: None for item in spec.analysis.outcomes}, "final_boundary": False,
        "reconciled": False, "database_integrity": False, "external_agent_influenced": False,
        "eligibility": {"status": "ineligible", "reasons": [reason]}}


def verify_policy_cell(packet: dict, cell: dict, batch: dict, *,
                       resolve_path: Callable[[str], Path] | None = None,
                       expected_usage: dict | None = None, working_budget: ProviderBudget | None = None) -> list[str]:
    """Bind the independent scientific receipt to the prospective policy cell."""
    from research.study_runner import arm_interventions, collect_outcomes
    from research.study_results import _logical_path, read_json

    spec = StudySpec.model_validate(batch["manifest"]["study"])
    locate = resolve_path or Path
    try:
        if (packet["contract"] != "policy-cell-v1" or packet["cell"] != cell
                or digest_json(packet["cell"]) != digest_json(cell)
                or packet["manifest_sha256"] != batch["manifest_sha256"]):
            raise ValueError("policy cell identity changed")
        row = packet["attempt"]
        original = _logical_path(batch["data_dir"]) / "cells" / cell["cell_key"]
        original /= digest_json({"seed": cell["seed"], "arm": cell["arm"]})[:12]
        directory = locate(str(original)).resolve()

        def confined(value):
            path = locate(value)
            if not path.resolve().is_relative_to(directory):
                raise ValueError("policy evidence leaves its assigned namespace")
            return path

        if confined(row["attempt_claim"]).resolve() != directory / "attempt.json":
            raise ValueError("policy claim leaves its assigned namespace")
        claim = read_json(confined(row["attempt_claim"]))
        expected = json.loads(json.dumps(batch["manifest"]["policy_configurations"][cell["policy"]]))
        expected.update(seed=cell["seed"], shocks=arm_interventions(spec, cell["arm"]),
            checkpoint_every=0, speed_delay_s=0.0,
            checkpoint_dir=str(original / "checkpoints"), report_dir=str(original / "reports"))
        working = bool(working_protocol(spec.operations.pause_policy))
        if (claim["protocol_version"] != (5 if working else 1) or digest_json(claim["config"]) != digest_json(expected)
                or claim["arm"] != cell["arm"] or type(claim["seed"]) is not int or claim["seed"] != cell["seed"]):
            raise ValueError("attempt differs from the assigned policy configuration")
        if working:
            from research.policy_studies import verify_budget_history
            if (working_budget is None or claim["study_manifest"] != batch["manifest"]
                    or claim["study_manifest_sha256"] != batch["manifest_sha256"]
                    or digest_json(claim["policy_cell"]) != digest_json(cell)
                    or claim["provider_budget_contract_sha256"] != digest_json(working_budget.contract.model_dump(mode="json"))):
                raise ValueError("working policy claim differs from its prospective study")
            verify_budget_history(row, working_budget, resolve_path=confined)
        if expected_usage is None:
            expected_usage = _budget(batch, scope=cell["cell_key"], binding=cell["policy"]).snapshot(scope=cell["cell_key"])
        if digest_json(packet["provider_usage"]) != digest_json(expected_usage):
            raise ValueError("policy usage receipt changed")
        reasons = list(row.get("eligibility", {}).get("reasons", []))
        if row.get("execution_status") != "completed":
            return sorted(set(reasons + ["execution_not_completed"]))
        reasons += verify_attempt(row, expected_ticks=spec.time.horizon, resolve_path=confined)
        genesis = read_json(directory / "genesis.json")
        if digest_json({"state": genesis["sha256"], "prng_state": genesis["prng_state"]}) != row["genesis_hash"]:
            reasons.append("genesis_receipt_mismatch")
        if expected_usage["breached_calls"]:
            reasons.append("provider_usage_contract_breached")
        if not reasons:
            store = Store(str(confined(row["source_database"])), create=False, read_only=True)
            try:
                measured = collect_outcomes(store, spec)
            finally:
                store.close()
            if any(digest_json(row.get(key)) != digest_json(value) for key, value in measured.items()):
                reasons.append("independent_measurement_mismatch")
            if measured["provider_calls"] > expected_usage["provider_calls"]:
                reasons.append("recorded_provider_calls_not_accounted")
        return sorted(set(reasons))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, sqlite3.Error, BudgetLedgerError):
        return ["policy_cell_identity_invalid"]


def verify_policy_preflight(packet: dict, policy, batch: dict, usage: dict) -> bool:
    """Verify the bounded smoke and scope before admitting any scientific cell."""
    if (packet.get("contract") != "policy-preflight-v1" or packet.get("policy") != policy.key
            or packet.get("manifest_sha256") != batch["manifest_sha256"]
            or digest_json(packet.get("provider_usage")) != digest_json(usage)
            or type(packet.get("ready")) is not bool):
        raise ValueError("preflight receipt differs from its assigned policy or accounting")
    checks = packet.get("checks")
    if not isinstance(checks, list) or len(checks) != 1:
        raise ValueError("preflight must check the single declared policy target")
    check = checks[0]
    if check.get("provider") != policy.behavior.provider_reference or check.get("model") != policy.behavior.model_reference:
        raise ValueError("preflight checked an undeclared target")
    ready = check.get("ok") is True and check.get("contract_ok") is True
    if packet["ready"] != ready or ready and (usage["provider_calls"] != 1 or usage["breached_calls"]):
        raise ValueError("preflight readiness differs from the smoke evidence")
    return ready


def run_policy_study(spec: StudySpec, config: dict, *, input_root: str | Path,
                     data_root: str | Path, out_dir: str | Path, approve_live_inference: bool,
                     expected_code: dict | None = None, progress: Callable[[dict], None] | None = None,
                     worker_guard_path: Path | None = None) -> dict:
    # Ordinary failures and operator interruptions close the allowance too.
    # Hard process death deliberately leaves unresolved accounting evidence.
    with ExitStack() as lifetime:
        return _run_policy_study(spec, config, input_root=input_root, data_root=data_root,
            out_dir=out_dir, approve_live_inference=approve_live_inference,
            expected_code=expected_code, progress=progress, worker_guard_path=worker_guard_path,
            lifetime=lifetime)


def _run_policy_study(spec: StudySpec, config: dict, *, input_root: str | Path,
                      data_root: str | Path, out_dir: str | Path, approve_live_inference: bool,
                      expected_code: dict | None, progress: Callable[[dict], None] | None,
                      worker_guard_path: Path | None, lifetime: ExitStack) -> dict:
    validate_policy_execution(spec, config)
    if working_protocol(spec.operations.pause_policy):
        raise ValueError("working policy studies require the recovery supervisor")
    if approve_live_inference is not True:
        raise ValueError("live policy studies require explicit approval of their declared provider budget")
    configurations = policy_configurations(spec, config)
    for configured in configurations.values():
        validate_llm_config(configured, require_secrets=True, raise_on_error=True)
    if expected_code is not None and code_identity() != expected_code:
        raise ValueError("source changed after policy study validation")
    started = time.monotonic()
    batch = prepare_study(spec, config, input_root=input_root, data_root=data_root, out_dir=out_dir)
    if expected_code is not None and batch["manifest"]["code"] != expected_code:
        raise ValueError("source changed during policy study preparation")
    root, report = Path(batch["data_dir"]), Path(batch["report_dir"])
    contract = provider_budget_contract(spec, config, manifest_sha256=batch["manifest_sha256"])
    publish_json(root / "provider-budget-contract.json", contract.model_dump(mode="json"))
    budget = ProviderBudget.create(root / "provider-budget.db", contract, scope="supervisor",
                                  binding_key=spec.policy_design.policies[0].key)
    lifetime.callback(budget.seal)
    if progress:
        progress({"stage": "prepared", "batch": batch})
    deadline = started + spec.operations.max_wall_seconds
    preflights, results, stopped = [], [], None
    for policy in spec.policy_design.policies:
        if policy.behavior.family == "scripted":
            continue
        packet, path, stopped = _supervise(batch, None, policy.key, input_root=Path(input_root).resolve(),
            guard_path=worker_guard_path, deadline=deadline, max_disk_bytes=spec.operations.max_disk_bytes)
        ready = False
        if packet and packet.get("contract") == "policy-preflight-v1":
            ready = verify_policy_preflight(packet, policy, batch, budget.snapshot(scope=f"preflight-{policy.key}"))
        entry = {"policy": policy.key, "ready": ready, "stop_reason": stopped}
        if path.exists():
            entry.update(receipt=str(path), sha256=file_sha256(path))
        preflights.append(entry)
        if stopped or not entry["ready"]:
            stopped = stopped or "live_preflight_failed"
            break
    for cell in study_cells(spec):
        if stopped:
            row = _missing(spec, cell, stopped)
        else:
            packet, path, stopped = _supervise(batch, cell, cell["policy"], input_root=Path(input_root).resolve(),
                guard_path=worker_guard_path, deadline=deadline, max_disk_bytes=spec.operations.max_disk_bytes)
            if packet and packet.get("contract") == "policy-cell-v1":
                reasons = verify_policy_cell(packet, cell, batch)
                reasons += [stopped] if stopped else []
                row = {**packet["attempt"], **cell, "provider_usage": packet["provider_usage"],
                       "policy_receipt": str(path), "policy_receipt_sha256": file_sha256(path),
                       "worker_stop_reason": stopped,
                       "eligibility": {"status": "ineligible" if reasons else "eligible", "reasons": sorted(set(reasons))}}
                if row["execution_status"] == "paused":
                    stopped = "study_stopped_after_paused_attempt"
            else:
                row = _missing(spec, cell, stopped or "worker_failed")
                row["execution_status"] = "failed"
                if packet:
                    row.update(policy_receipt=str(path), policy_receipt_sha256=file_sha256(path))
        results.append(row)
        if progress:
            progress({"stage": "cell", "index": len(results), "row": row})
    usage = budget.seal()
    budget_receipt = {"contract": "policy-budget-evidence-v1", "manifest_sha256": batch["manifest_sha256"],
        "database": str(budget.path), "database_sha256": file_sha256(budget.path), "usage": usage,
        "budget_contract": str(root / "provider-budget-contract.json"),
        "budget_contract_sha256": file_sha256(root / "provider-budget-contract.json")}
    publish_json(root / "provider-budget-receipt.json", budget_receipt)
    payload = {"contract": "policy-study-result-v1", "batch": batch, "results": results,
        "summary": replicated_summary(results, spec), "preflight": preflights,
        "provider_budget": budget_receipt,
        "outcomes": [item.model_dump(mode="json") for item in spec.analysis.outcomes],
        "measurement_window": [spec.time.measurement_start, spec.time.measurement_end],
        "operations": {"elapsed_seconds": round(time.monotonic() - started, 3), "stop_reason": stopped,
            "provider_calls": usage["provider_calls"], "usage_cost_usd": usage["usage_cost_nano_usd"] / 1e9,
            "encumbered_usd": usage["encumbered_nano_usd"] / 1e9,
            "disk_guard": "200ms sampling; current writes and final evidence can exceed the threshold"},
        "artifacts": {"json": str(report / "results.json"), "markdown": str(report / "findings.md")}}
    publish_json(report / "results.json", payload)
    publish_bytes(report / "findings.md", policy_findings(payload).encode("utf-8"))
    publish_json(report / "publication.json", {"contract": "policy-study-publication-v1",
        "manifest_sha256": batch["manifest_sha256"],
        "files": {name: file_sha256(report / name) for name in ("results.json", "findings.md")}})
    return payload


def policy_findings(payload: dict) -> str:
    spec = payload["batch"]["manifest"]["study"]
    lines = [f"# {spec['title']}", "", spec["hypothesis"], "",
        "Exploratory, model-conditional policy study. Paired model draws are averaged within each independent world before uncertainty is calculated.",
        "Model draws are not additional economies; these results do not establish empirical realism or confirmatory causality.", "",
        "| Outcome | Policy arm | Mean difference | World pairs | Status |",
        "|---|---|---:|---:|---|"]
    for metric, arms in payload["summary"]["metrics"].items():
        for arm, observation in arms.items():
            if effect := observation.get("paired_effect"):
                lines.append(f"| {metric} | {arm} | {effect['mean_difference']} | {effect['n_pairs']} | {effect['status']} |")
    lines += ["", "## Execution and usage", "", "```json", json.dumps({
        "operations": payload["operations"], "provider_budget": payload["provider_budget"]["usage"],
        "replication": payload["summary"]["replication"]}, indent=2), "```", "",
        "Costs use declared tariffs applied to reported usage. Unresolved reservations remain encumbered; they are not verified provider invoices.",
        "", "## Limitations", "", *[f"- {item}" for item in spec["limitations"]], ""]
    return "\n".join(lines)

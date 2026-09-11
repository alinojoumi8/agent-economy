"""Bounded execution of prospective paired price studies."""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import json
import multiprocessing
import os
from pathlib import Path
import statistics
import threading
import time
from typing import Callable

from pydantic import ValidationError

from engine.store import Store
from research.analysis import paired_summary
from research.artifacts import code_identity, digest_json, file_sha256, publish_bytes, publish_json
from research.attempts import execute_attempt, verify_attempt
from research.metric_registry import metric_definition, read_metric_observation
from research.prices import price_observations
from research.process_lock import process_lock
from research.studies import StudySpec, load_study, prepare_study, validate_study_inputs
from research.working_contracts import PHASE_PROTOCOL, phase_controls, working_protocol
from run_config import load_config


def execution_costs(store: Store, spec: StudySpec, origin: dict | None = None) -> dict:
    """Report newly executed calls separately from a saved world's history."""
    if (origin is None) != (spec.origin is None):
        raise ValueError("checkpoint measurements require their admitted input boundary")
    if origin is None:
        # Preserve the original unfiltered totals for historical genesis data,
        # including imported rows whose primary key was explicitly zero.
        return {"spend_usd": float(store.scalar("SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls", default=0)),
                "provider_calls": int(store.scalar(
                    "SELECT COUNT(*) FROM llm_calls WHERE provider IS NULL OR provider<>'scripted'", default=0))}
    boundary = origin["recorded_inputs"]["last_id"]

    def totals(predicate):
        row = store.conn.execute(
            "SELECT COALESCE(SUM(cost_usd),0), COALESCE(SUM(CASE WHEN "
            "provider IS NULL OR provider<>'scripted' THEN 1 ELSE 0 END),0) "
            f"FROM llm_calls WHERE id{predicate}?", (boundary,)).fetchone()
        return float(row[0]), int(row[1])

    spend, calls = totals(">")
    result = {"spend_usd": spend, "provider_calls": calls}
    if origin:
        inherited_spend, inherited_calls = totals("<=")
        result.update(inherited_spend_usd=inherited_spend, inherited_provider_calls=inherited_calls)
    return result


def collect_outcomes(store: Store, spec: StudySpec, *, origin: dict | None = None) -> dict:
    """Require every declared point; never fill gaps or change currency units."""
    metrics, series, observations = {}, {}, {}
    for outcome in spec.analysis.outcomes:
        ticks = ([spec.time.measurement_end] if outcome.aggregation == "terminal" else
                 range(spec.time.measurement_start, spec.time.measurement_end + 1))
        if outcome.aggregation == "window_vwap":
            domain = "goods" if outcome.metric.startswith("goods_vwap:") else "equities"
            try:
                prices = price_observations(store, int(outcome.metric.split(":")[1]),
                    tick=spec.time.measurement_end, start_tick=spec.time.measurement_start)
                points = [{"tick": spec.time.measurement_end, "start_tick": spec.time.measurement_start,
                           "currency": prices["currency"], "quantity": prices[domain]["quantity"],
                           "notional_cents": prices[domain]["notional_cents"],
                           **prices[domain]["executed_price"]}]
            except ValueError:
                points = [{"tick": spec.time.measurement_end, "start_tick": spec.time.measurement_start,
                           "currency": None, "quantity": None, "notional_cents": None,
                           "value": None, "status": "unavailable",
                           "reason": "instrument_or_committed_window_unavailable"}]
        else:
            points = [read_metric_observation(store, outcome.metric, tick) for tick in ticks]
        for point in points:
            if point["status"] == "available" and outcome.currency is not None and point["currency"] != outcome.currency:
                point.update(value=None, status="unavailable", reason="declared_currency_mismatch")
        values = [point["value"] for point in points]
        complete = all(point["status"] == "available" for point in points)
        if not complete:
            value = None
        elif outcome.aggregation in {"terminal", "window_vwap"}:
            value = values[0]
        elif outcome.aggregation == "window_mean":
            value = statistics.fmean(values)
        else:
            value = sum(values)
        metrics[outcome.key] = value
        series[outcome.key] = [[point["tick"], point["value"]] for point in points]
        observations[outcome.key] = {
            "outcome": outcome.model_dump(mode="json"), "points": points,
            "status": "complete" if complete else "incomplete_window",
            "required_points": len(points),
            "available_points": sum(point["status"] == "available" for point in points)}
    return {"metrics": metrics, "series": series, "outcome_observations": observations,
            **execution_costs(store, spec, origin)}


def validate_execution(spec: StudySpec, config: dict) -> None:
    """Check this runner's capabilities before creating any study artifacts."""
    if spec.protocol_version == "research-study-v3":
        from research.policy_runner import validate_policy_execution
        validate_policy_execution(spec, config)
        return
    if working_protocol(spec.operations.pause_policy) and spec.model.engine_semantics_version < 7:
        raise ValueError("working studies require persisted PRNG semantics")
    if spec.operations.mode != "provider_free" or spec.behavior.family != "scripted":
        raise ValueError("this runner supports explicitly scripted provider-free studies only")
    if spec.operations.concurrency != 1:
        raise ValueError("this runner currently supports one attempt at a time")
    llm = config.get("llm", {})
    if llm.get("providers") or config.get("providers"):
        raise ValueError("provider-free studies must not configure external providers")
    routes = [llm.get("default_route", {}), *llm.get("routes", {}).values()]
    if any(route.get("provider") != "scripted" or route.get("model") != "scripted" for route in routes):
        raise ValueError("every configured route must explicitly use the scripted policy")
    if config.get("shocks") and spec.origin is None:
        raise ValueError("declare all study shocks in arms; the resolved baseline must have none")
    if config.get("dataset_manifest") and not any(item.role == "initialization" for item in spec.inputs):
        raise ValueError("dataset initialization requires pinned input artifacts")


def collect_working_outcomes(store: Store, spec: StudySpec, *, origin: dict | None = None) -> dict:
    """An active day is execution evidence, never a completed price window."""
    if working_protocol(spec.operations.pause_policy) != PHASE_PROTOCOL or store.active_tick is None:
        return collect_outcomes(store, spec, origin=origin)
    observations = {}
    for outcome in spec.analysis.outcomes:
        required = (1 if outcome.aggregation in {"terminal", "window_vwap"} else
                    spec.time.measurement_end - spec.time.measurement_start + 1)
        observations[outcome.key] = {
            "outcome": outcome.model_dump(mode="json"), "points": [],
            "status": "partial_phase", "reason": "unfinished_day_not_measured",
            "required_points": required, "available_points": 0}
    return {"metrics": {item.key: None for item in spec.analysis.outcomes}, "series": {},
            "outcome_observations": observations, **execution_costs(store, spec, origin)}


def arm_interventions(spec: StudySpec, arm_key: str) -> list[dict]:
    arm = next(item for item in spec.arms if item.key == arm_key)
    shocks = []
    for shock in arm.changes.shocks:
        values = shock.model_dump(mode="json")
        kind, tick = values.pop("kind"), values.pop("tick")
        shocks.append({"kind": kind, "trigger": "shock", "trigger_params": {"tick": tick},
                       "duration_ticks": 0, "params": values, "label": f"study:{arm.key}:{kind}"})
    return shocks


def _arm_config(spec: StudySpec, config: dict, arm_key: str, *, verify_policy_source: bool = True) -> dict:
    if spec.policy_design is not None:
        from research.policy_studies import policy_configurations
        policy = next(arm.policy for arm in spec.arms if arm.key == arm_key)
        resolved = policy_configurations(spec, config, verify_source=verify_policy_source)[policy]
    else:
        resolved = json.loads(json.dumps(config))
    inherited = (resolved.get("shocks") or []) if spec.origin else []
    resolved["shocks"] = [*inherited, *arm_interventions(spec, arm_key)]
    return resolved


def _worker(spec_data: dict, config: dict, seed: int, arm: str,
            data_dir: str, result_path: str, input_root: str, expected_code: dict,
            worker_guard_path: str | None = None, working: dict | None = None) -> None:
    parent = multiprocessing.parent_process()
    if parent is not None:
        if not parent.is_alive():
            os._exit(70)

        def stop_if_orphaned():
            parent.join()
            # A hard supervisor crash cannot leave an unbudgeted world worker.
            # No success receipt is fabricated; SQLite/partial artifacts remain.
            os._exit(70)

        threading.Thread(target=stop_if_orphaned, daemon=True, name="study-parent-guard").start()
    with process_lock(Path(worker_guard_path), wait_seconds=5) if worker_guard_path else nullcontext():
        if parent is not None and not parent.is_alive():
            os._exit(70)
        if working is None:
            _execute_worker(spec_data, config, seed, arm, data_dir, result_path, input_root, expected_code)
        else:
            from research.working_attempts import execute_working_attempt
            if working.get("policy_cell") is not None:
                from research.policy_runner import _budget
                cell = working["policy_cell"]
                working["completion_guard"] = _budget(working["batch"], scope=cell["cell_key"], binding=cell["policy"])
            # Keep a clean pause pending. Exceptions leave the segment and
            # missing worker receipt visible to the owning supervisor.
            row = execute_working_attempt(spec=StudySpec.model_validate(spec_data),
                config=config, seed=seed, arm=arm, input_root=input_root, **working)
            publish_json(result_path, row)


def _execute_worker(spec_data: dict, config: dict, seed: int, arm: str,
                    data_dir: str, result_path: str, input_root: str, expected_code: dict) -> None:
    spec = StudySpec.model_validate(spec_data)
    try:
        if code_identity() != expected_code:
            raise ValueError("source changed after manifest publication")
        declared = validate_study_inputs(spec, config, input_root=input_root)
        executor, extra, origin = execute_attempt, {}, None
        if spec.origin:
            from research.attempt_origins import checkpoint_claim_fields, execute_checkpoint_attempt
            manifest = json.loads((Path(data_dir) / "manifest.json").read_text(encoding="utf-8"))["manifest"]
            if any(digest_json(manifest.get(key)) != digest_json(value) for key, value in declared.items()):
                raise ValueError("checkpoint study manifest changed")
            fields = checkpoint_claim_fields(spec, manifest, Path(data_dir), seed, arm)
            executor, extra = execute_checkpoint_attempt, {"origin_fields": fields}
            origin = fields["checkpoint_origin"]["receipt"]
        row = executor(run_id=f"{spec.key}-{arm}-s{seed}", seed=seed, arm=arm,
            config=_arm_config(spec, config, arm), ticks=spec.time.horizon,
            data_dir=Path(data_dir), collect=lambda store: collect_outcomes(store, spec, origin=origin), **extra)
        problems = list(row["eligibility"]["reasons"])
        if code_identity() != expected_code:
            problems.append("source_changed_during_attempt")
        try:
            validate_study_inputs(spec, config, input_root=input_root)
        except (ValueError, OSError):
            problems.append("inputs_changed_during_attempt")
        if row.get("provider_calls", 0) or row.get("spend_usd", 0):
            problems.append("provider_free_contract_violated")
        row["eligibility"] = {"status": "ineligible" if problems else "eligible",
                              "reasons": sorted(set(problems))}
        publish_json(result_path, row)
    except Exception as exc:
        # Validation errors can include private input values; persist type only.
        publish_json(result_path, _incomplete_row(
            spec, seed, arm, "failed", "worker_failed", error_type=type(exc).__name__))


def _incomplete_row(spec: StudySpec, seed: int, arm: str, status: str,
                    reason: str, **details) -> dict:
    return {"run_id": f"{spec.key}-{arm}-s{seed}", "seed": seed, "arm": arm,
            "execution_status": status, "expected_ticks": spec.time.horizon,
            "ticks": 0, "final_boundary": False, "reconciled": False,
            "database_integrity": False, "external_agent_influenced": False,
            "metrics": {item.key: None for item in spec.analysis.outcomes}, "series": {},
            "eligibility": {"status": "ineligible", "reasons": [reason]}, **details}


def _disk_bytes(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        try:
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
        except FileNotFoundError:
            # An atomic publisher can retire its own temporary link during a poll.
            continue
    return total


def run_study(spec: StudySpec, config: dict, *, input_root: str | Path,
              data_root: str | Path = "data/studies", out_dir: str | Path = "reports/out",
              expected_code: dict | None = None,
              progress: Callable[[dict], None] | None = None,
              worker_guard_path: Path | None = None,
              resume_batch: str | Path | None = None,
              pause_after_ticks: int | None = None,
              pause_after_phase: str | None = None,
              approve_live_inference: bool = False) -> dict:
    spec = StudySpec.model_validate(spec.model_dump(mode="json"))
    validate_execution(spec, config)
    if spec.protocol_version == "research-study-v3":
        if working_protocol(spec.operations.pause_policy):
            from research.working_studies import run_working_study
            return run_working_study(spec, config, input_root=input_root, data_root=data_root,
                out_dir=out_dir, expected_code=expected_code, progress=progress, worker_guard_path=worker_guard_path,
                resume_batch=resume_batch, pause_after_ticks=pause_after_ticks, pause_after_phase=pause_after_phase,
                approve_live_inference=approve_live_inference)
        if any(value is not None for value in (resume_batch, pause_after_ticks, pause_after_phase)):
            raise ValueError("live policy recovery requires the recovery executor")
        from research.policy_runner import run_policy_study
        return run_policy_study(spec, config, input_root=input_root, data_root=data_root,
            out_dir=out_dir, expected_code=expected_code, progress=progress,
            worker_guard_path=worker_guard_path, approve_live_inference=approve_live_inference)
    phase_controls(spec.operations.pause_policy, spec.model.engine_semantics_version,
                   ticks=pause_after_ticks, phase=pause_after_phase)
    if working_protocol(spec.operations.pause_policy):
        from research.working_studies import run_working_study
        return run_working_study(spec, config, input_root=input_root, data_root=data_root,
            out_dir=out_dir, expected_code=expected_code, progress=progress,
            worker_guard_path=worker_guard_path, resume_batch=resume_batch,
            pause_after_ticks=pause_after_ticks, pause_after_phase=pause_after_phase)
    if resume_batch is not None or pause_after_ticks is not None:
        raise ValueError("pause and resume controls require the preserve_and_resume policy")
    if expected_code is not None and code_identity() != expected_code:
        raise ValueError("source changed after study validation")
    started = time.monotonic()
    batch = prepare_study(spec, config, input_root=input_root, data_root=data_root, out_dir=out_dir)
    if progress:
        progress({"stage": "prepared", "batch": batch})
    if expected_code is not None and batch["manifest"]["code"] != expected_code:
        raise ValueError("source changed during study preparation")
    data_dir, report_dir = Path(batch["data_dir"]), Path(batch["report_dir"])
    deadline = started + spec.operations.max_wall_seconds
    context = multiprocessing.get_context("spawn")
    results, exhausted = [], None

    def limit_reason():
        if time.monotonic() >= deadline:
            return "wall_time_budget_exhausted"
        if _disk_bytes(data_dir) + _disk_bytes(report_dir) >= spec.operations.max_disk_bytes:
            return "disk_budget_exhausted"
        return None

    for seed in spec.randomness.seeds:
        for arm in spec.arms:
            exhausted = exhausted or limit_reason()
            if exhausted:
                results.append(_incomplete_row(spec, seed, arm.key, "planned", exhausted))
                if progress:
                    progress({"stage": "cell", "index": len(results), "row": results[-1]})
                continue
            cell_id = digest_json({"seed": seed, "arm": arm.key})[:12]
            result_path = data_dir / f"worker-{cell_id}.json"
            process = context.Process(target=_worker, args=(spec.model_dump(mode="json"), config,
                seed, arm.key, str(data_dir), str(result_path), str(Path(input_root).resolve()),
                batch["manifest"]["code"], str(worker_guard_path) if worker_guard_path else None), name=f"study-{cell_id}")
            process.start()
            try:
                while process.is_alive():
                    process.join(timeout=.2)
                    exhausted = limit_reason()
                    if exhausted:
                        process.terminate()
                        process.join(timeout=5)
                        if process.is_alive():
                            process.kill()
                            process.join(timeout=5)
                        break
            except BaseException:
                # Stop only the worker this study owns. Its incomplete database
                # and claim remain inspectable after an interrupted operator run.
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
                    if process.is_alive():
                        process.kill()
                        process.join(timeout=5)
                raise
            exit_code = process.exitcode
            process.close()
            if result_path.is_file():
                row = json.loads(result_path.read_text(encoding="utf-8"))
                if row["eligibility"]["status"] == "eligible":
                    reasons = verify_attempt(row, expected_ticks=spec.time.horizon)
                    if reasons:
                        row["eligibility"] = {"status": "ineligible", "reasons": reasons}
                if exhausted:
                    row["eligibility"] = {"status": "ineligible", "reasons": [exhausted]}
            else:
                row = _incomplete_row(spec, seed, arm.key, "failed", exhausted or "worker_failed",
                    worker_exit_code=exit_code, artifact_directory=str(data_dir / cell_id))
            results.append(row)
            if progress:
                progress({"stage": "cell", "index": len(results), "row": row})
            if row["execution_status"] == "paused":
                exhausted = "study_stopped_after_paused_attempt"

    baseline = next(arm.key for arm in spec.arms if arm.role == "baseline")
    summary = paired_summary(results, baseline, expected_ticks=spec.time.horizon,
        expected_arms=[arm.key for arm in spec.arms], expected_seeds=spec.randomness.seeds,
        expected_metrics=[item.key for item in spec.analysis.outcomes],
        minimum_pairs=spec.analysis.minimum_pairs, bootstrap_samples=spec.analysis.bootstrap_samples,
        initial_state_key="origin_state_hash" if spec.origin else "genesis_hash")
    payload = {"contract": "study-result-v1", "batch": batch, "results": results,
               "summary": summary, "outcomes": [item.model_dump(mode="json") for item in spec.analysis.outcomes],
               "measurement_window": [spec.time.measurement_start, spec.time.measurement_end],
               "operations": {"elapsed_seconds": round(time.monotonic() - started, 3),
                              "stop_reason": exhausted,
                              "provider_spend_usd": sum(row.get("spend_usd", 0) for row in results),
                              "provider_calls": sum(row.get("provider_calls", 0) for row in results),
                              "disk_guard": "200ms sampling; a current write and final diagnostic report can exceed the threshold"},
               "artifacts": {"json": str(report_dir / "results.json"),
                             "markdown": str(report_dir / "findings.md")}}
    publish_json(report_dir / "results.json", payload)
    publish_bytes(report_dir / "findings.md", findings_markdown(payload).encode("utf-8"))
    publish_json(report_dir / "publication.json", {
        "contract": "study-publication-v1", "manifest_sha256": batch["manifest_sha256"],
        "files": {name: file_sha256(report_dir / name) for name in ("results.json", "findings.md")}})
    return payload


def findings_markdown(payload: dict) -> str:
    spec = payload["batch"]["manifest"]["study"]
    lines = [f"# {spec['title']}", "", spec["hypothesis"], "",
             "Exploratory, model-conditional paired study. The manifest was prepared before execution.",
             "This is not empirical validation or a confirmatory causal estimate.", "",
             f"Measurement ticks: {payload['measurement_window']}. Each pair is a whole world/seed.", ""]
    if spec.get("origin"):
        lines += [f"Initial conditions: {len(spec['origin']['sources'])} independent saved worlds at day "
                  f"{spec['origin']['tick']}. Recorded continuation replay covers days "
                  f"{spec['origin']['tick'] + 1}–{spec['time']['horizon']}.",
                  "Admission verifies the saved state; it does not replay the history that produced it. "
                  "Inherited calls and costs are recorded separately and excluded from new execution totals.", ""]
    lines += ["| Outcome | Arm | Mean paired difference | 95% bootstrap interval | Usable pairs | Status |",
              "|---|---|---:|---|---:|---|"]
    for key, arms in payload["summary"]["metrics"].items():
        for arm, observation in arms.items():
            effect = observation.get("paired_effect")
            if effect:
                lines.append(f"| {key} | {arm} | {effect['mean_difference']} | "
                    f"{effect['ci95_bootstrap']} | {effect['n_pairs']} | {effect['status']} |")
    lines += ["", "## Assignment and exclusions", "", "```json",
              json.dumps({"coverage": payload["summary"]["coverage"],
                          "exclusions": payload["summary"]["exclusions"],
                          "operations": payload["operations"]}, indent=2), "```", "",
              "## Measurement contracts", "",
              "| Outcome | Role | Metric/version | Aggregation | Unit | Currency |",
              "|---|---|---|---|---|---|"]
    for outcome in payload["outcomes"]:
        definition = metric_definition(outcome["metric"], semantics_version=spec['model']['engine_semantics_version'])
        lines.append(f"| {outcome['key']} | {outcome['purpose']} | {outcome['metric']} / "
                     f"{outcome['metric_version']} | {outcome['aggregation']} | "
                     f"{definition.unit if definition else 'unavailable'} | {outcome['currency']} |")
    lines += ["", "## Missing observations", "",
              "| Arm | Seed | Outcome | Available / required points | Reason |", "|---|---:|---|---|---|"]
    for row in payload["results"]:
        for key, observation in row.get("outcome_observations", {}).items():
            if observation["status"] != "complete":
                reasons = sorted({point["reason"] for point in observation["points"] if point.get("reason")})
                lines.append(f"| {row['arm']} | {row['seed']} | {key} | "
                    f"{observation['available_points']} / {observation['required_points']} | {', '.join(reasons)} |")
    lines += ["", "## Limitations", "", *[f"- {item}" for item in spec["limitations"]], ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study", type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--input-root", type=Path, default=Path("."))
    parser.add_argument("--data-root", type=Path, default=Path("data/studies"))
    parser.add_argument("--out-dir", type=Path, default=Path("reports/out"))
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--approve-live-inference", action="store_true",
                        help="Authorize only the provider routes and shared caps in the supplied v3 study")
    parser.add_argument("--resume-batch", type=Path,
                        help="Existing working data directory under --data-root")
    parser.add_argument("--pause-after-ticks", type=int,
                        help="Maximum additional days per cell; stop at the first clean pause")
    parser.add_argument("--pause-after-phase",
                        help="Stop after the next named phase; requires preserve_and_resume_phases")
    args = parser.parse_args()
    try:
        spec, config = load_study(args.study), load_config(args.config)
        validate_execution(spec, config)
        if args.pause_after_ticks is not None and args.pause_after_ticks < 1:
            raise ValueError("pause tick limit must be positive")
        phase_controls(spec.operations.pause_policy, spec.model.engine_semantics_version,
                       ticks=args.pause_after_ticks, phase=args.pause_after_phase)
        if (args.resume_batch is not None or args.pause_after_ticks is not None) and not working_protocol(spec.operations.pause_policy):
            raise ValueError("pause and resume controls require the preserve_and_resume policy")
        if args.validate_only:
            validate_study_inputs(spec, config, input_root=args.input_root)
            if args.resume_batch is not None:
                from research.working_studies import validate_resume
                validate_resume(args.resume_batch, spec, config, input_root=args.input_root,
                                data_root=args.data_root, out_dir=args.out_dir)
            print(json.dumps({"status": "valid", "study": spec.key,
                              "input_hashes_verified": True, "executed": False}))
        else:
            result = run_study(spec, config, input_root=args.input_root,
                               data_root=args.data_root, out_dir=args.out_dir,
                               resume_batch=args.resume_batch, pause_after_ticks=args.pause_after_ticks,
                               pause_after_phase=args.pause_after_phase,
                               approve_live_inference=args.approve_live_inference)
            print(json.dumps({"artifacts": result["artifacts"], "coverage": result["summary"]["coverage"],
                              "status": result.get("status", "finalized"), "batch": result["batch"]["data_dir"]}))
            if any(row["execution_status"] != "completed"
                   or spec.protocol_version == "research-study-v3" and row["eligibility"]["status"] != "eligible"
                   for row in result["results"]):
                return 1
        return 0
    except ValidationError as exc:
        print(json.dumps({"status": "invalid", "errors": exc.errors(include_input=False, include_context=False)}))
    except (ValueError, OSError) as exc:
        print(json.dumps({"status": "invalid", "error_type": type(exc).__name__}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Bounded provider-free execution of prospective paired price studies."""
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
from run_config import load_config


def collect_outcomes(store: Store, spec: StudySpec) -> dict:
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
            "spend_usd": float(store.scalar("SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls", default=0)),
            "provider_calls": int(store.scalar(
                "SELECT COUNT(*) FROM llm_calls WHERE provider IS NULL OR provider<>'scripted'", default=0))}


def validate_execution(spec: StudySpec, config: dict) -> None:
    """Check this runner's capabilities before creating any study artifacts."""
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
    if config.get("shocks"):
        raise ValueError("declare all study shocks in arms; the resolved baseline must have none")
    if config.get("dataset_manifest") and not any(item.role == "initialization" for item in spec.inputs):
        raise ValueError("dataset initialization requires pinned input artifacts")


def _arm_config(spec: StudySpec, config: dict, arm_key: str) -> dict:
    arm = next(item for item in spec.arms if item.key == arm_key)
    resolved = json.loads(json.dumps(config))
    shocks = []
    for shock in arm.changes.shocks:
        values = shock.model_dump(mode="json")
        kind, tick = values.pop("kind"), values.pop("tick")
        shocks.append({"kind": kind, "trigger": "shock", "trigger_params": {"tick": tick},
                       "duration_ticks": 0, "params": values, "label": f"study:{arm.key}:{kind}"})
    resolved["shocks"] = shocks
    return resolved


def _worker(spec_data: dict, config: dict, seed: int, arm: str,
            data_dir: str, result_path: str, input_root: str, expected_code: dict,
            worker_guard_path: str | None = None) -> None:
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
        _execute_worker(spec_data, config, seed, arm, data_dir, result_path, input_root, expected_code)


def _execute_worker(spec_data: dict, config: dict, seed: int, arm: str,
                    data_dir: str, result_path: str, input_root: str, expected_code: dict) -> None:
    spec = StudySpec.model_validate(spec_data)
    try:
        if code_identity() != expected_code:
            raise ValueError("source changed after manifest publication")
        validate_study_inputs(spec, config, input_root=input_root)
        row = execute_attempt(run_id=f"{spec.key}-{arm}-s{seed}", seed=seed, arm=arm,
            config=_arm_config(spec, config, arm), ticks=spec.time.horizon,
            data_dir=Path(data_dir), collect=lambda store: collect_outcomes(store, spec))
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
              worker_guard_path: Path | None = None) -> dict:
    spec = StudySpec.model_validate(spec.model_dump(mode="json"))
    validate_execution(spec, config)
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
        minimum_pairs=spec.analysis.minimum_pairs, bootstrap_samples=spec.analysis.bootstrap_samples)
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
             f"Measurement ticks: {payload['measurement_window']}. Each pair is a whole world/seed.", "",
             "| Outcome | Arm | Mean paired difference | 95% bootstrap interval | Usable pairs | Status |",
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
        definition = metric_definition(outcome["metric"])
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
    args = parser.parse_args()
    try:
        spec, config = load_study(args.study), load_config(args.config)
        validate_execution(spec, config)
        if args.validate_only:
            validate_study_inputs(spec, config, input_root=args.input_root)
            print(json.dumps({"status": "valid", "study": spec.key,
                              "input_hashes_verified": True, "executed": False}))
        else:
            result = run_study(spec, config, input_root=args.input_root,
                               data_root=args.data_root, out_dir=args.out_dir)
            print(json.dumps({"artifacts": result["artifacts"], "coverage": result["summary"]["coverage"]}))
            if any(row["execution_status"] != "completed" for row in result["results"]):
                return 1
        return 0
    except ValidationError as exc:
        print(json.dumps({"status": "invalid", "errors": exc.errors(include_input=False, include_context=False)}))
    except (ValueError, OSError) as exc:
        print(json.dumps({"status": "invalid", "error_type": type(exc).__name__}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Supervised, append-only recovery of provider-free research batches."""
from __future__ import annotations

import copy
import multiprocessing
from pathlib import Path
import time
from typing import Callable

from research.analysis import paired_summary
from research.artifacts import code_identity, digest_json, file_sha256, publish_bytes, publish_json
from research.process_lock import process_lock
from research.studies import StudySpec, prepare_study
from research.study_runner import _arm_config, _disk_bytes, _incomplete_row, _worker, findings_markdown
from research.working_attempts import (
    _batch_active_seconds, _check_source, _contract, _duration, _history, _member, _read,
    verify_working_history,
)

CONTRACT = "working-study-supervision-v1"


def _assigned(spec: StudySpec):
    return [(seed, arm.key) for seed in spec.randomness.seeds for arm in spec.arms]


def _planned(spec: StudySpec, seed: int, arm: str) -> dict:
    row = _incomplete_row(spec, seed, arm, "planned", "study_waiting_for_resume")
    row["eligibility"]["status"] = "pending"
    return row


def _journal(data: Path, report: Path, manifest_sha256: str) -> list[dict]:
    """Check all completed invocations without opening a scientific database."""
    directory = _member(data, "supervision")
    starts, ends = sorted(directory.glob("invocation-*-start.json")), sorted(directory.glob("invocation-*-end.json"))
    seals = sorted(directory.glob("invocation-*-seal.json"))
    if not starts or len(starts) != len(ends) or len(starts) != len(seals) or len(starts) > 1024:
        raise ValueError("unfinished or missing supervision cannot resume")
    previous, active, records = None, 0.0, []
    for number, (start_path, end_path) in enumerate(zip(starts, ends), 1):
        prefix = f"invocation-{number:06d}"
        if start_path.name != prefix + "-start.json" or end_path.name != prefix + "-end.json":
            raise ValueError("supervision sequence is incomplete")
        start_path, end_path = _member(directory, start_path.name), _member(directory, end_path.name)
        seal = _read(_member(directory, prefix + "-seal.json"))
        if seal.get("end_sha256") != file_sha256(end_path):
            raise ValueError("supervision timing receipt changed")
        start, end = _read(start_path), _read(end_path)
        if (start.get("contract") != CONTRACT or start.get("manifest_sha256") != manifest_sha256
                or start.get("previous_end_sha256") != previous
                or _duration(start["prior_active_wall_seconds"]) != active
                or end.get("start_sha256") != file_sha256(start_path)
                or _duration(end["active_wall_seconds"]) < active
                or end.get("status") not in {"paused", "finalized"}
                or (number < len(starts) and end["status"] != "paused")):
            raise ValueError("supervision lineage or cumulative timing changed")
        report_name = f"progress-{number:06d}.json" if end["status"] == "paused" else "results.json"
        if end["report"]["path"] != report_name or file_sha256(_member(report, report_name)) != end["report"]["sha256"]:
            raise ValueError("supervision report changed")
        workers = end["workers"]
        if len({item["path"] for item in workers}) != len(workers):
            raise ValueError("duplicate supervised worker receipt")
        for ref in workers:
            if (not ref["path"].startswith(f"supervision/{prefix}-worker-")
                    or file_sha256(_member(data, ref["path"])) != ref["sha256"]):
                raise ValueError("supervised worker receipt changed")
        previous, active = file_sha256(end_path), _duration(end["active_wall_seconds"])
        records.append({"start": start, "end": end, "end_sha256": previous})
    return records


def _checked_rows(batch: dict, spec: StudySpec, config: dict, rows: list[dict], *, location=None) -> None:
    from research.study_results import _logical_path
    data = location.data_dir if location is not None else Path(batch["data_dir"])
    original = _logical_path(batch["data_dir"])

    def owned(value: str) -> Path:
        path = location.locate(value) if location is not None else Path(value)
        return _member(data, str(path.relative_to(data)))

    if [(row["seed"], row["arm"]) for row in rows] != _assigned(spec):
        raise ValueError("working progress changed the assigned cells")
    for row in rows:
        cell = digest_json({"seed": row["seed"], "arm": row["arm"]})[:12]
        directory = _member(data, cell)
        for name in ("source", "replay", "checkpoints", "reports"):
            _member(directory, name)
        if row["execution_status"] == "planned":
            if directory.exists() or row != _planned(spec, row["seed"], row["arm"]):
                raise ValueError("planned cell has unexpected execution evidence")
            continue
        claim_path = _member(directory, "attempt.json")
        claim = _read(claim_path)
        cfg = _arm_config(spec, config, row["arm"])
        cfg.update(seed=row["seed"], checkpoint_every=0, speed_delay_s=0.0,
                   checkpoint_dir=str(original / cell / "checkpoints"), report_dir=str(original / cell / "reports"))
        if (owned(row["attempt_claim"]) != claim_path
                or row["attempt_claim_sha256"] != file_sha256(claim_path)
                or claim["study_manifest"] != batch["manifest"]
                or claim["study_manifest_sha256"] != batch["manifest_sha256"]
                or claim["config"] != cfg or claim["config_sha256"] != digest_json(cfg)
                or any(claim[key] != row[key] for key in ("run_id", "seed", "arm", "expected_ticks", "config_sha256"))):
            raise ValueError("working cell contract changed")
        if row["execution_status"] == "paused":
            if any(_member(directory, name).exists() for name in ("source-receipt.json", "result.json", "finalized.json")):
                raise ValueError("finalized cell cannot resume")
            _, paused = _history(directory, file_sha256(claim_path))
            if paused != row:
                raise ValueError("working pause differs from supervised progress")
            if location is None:
                _check_source(directory, row, claim)
            else:
                _check_source(directory, row, claim, resolve_path=owned,
                              expected_schema_version=spec.model.schema_version)
        else:
            result_path = _member(directory, "result.json")
            seal = _read(_member(directory, "finalized.json"))
            if (seal.get("result_sha256") != file_sha256(result_path) or _read(result_path) != row
                    or _read(_member(data, f"worker-{cell}.json")) != row):
                raise ValueError("finalized working result changed")
            # These bytes were independently verified at finalization. Recheck
            # their seals before any writable open, without creating WAL files.
            for field in ("attempt_claim", "source_database", "source_receipt", "replay_receipt", "genesis_receipt"):
                if field in row and file_sha256(owned(row[field])) != row[field + "_sha256"]:
                    raise ValueError("finalized working evidence changed")
            if "replay_receipt" in row:
                replay = _read(owned(row["replay_receipt"]))
                replay_path = owned(replay["replay_database"])
                if file_sha256(replay_path) != replay["replay_database_sha256"]:
                    raise ValueError("finalized replay changed")
            for ref in row.get("working_history", []):
                if file_sha256(owned(ref["path"])) != ref["sha256"]:
                    raise ValueError("finalized working segment changed")
            if row["execution_status"] == "completed" and verify_working_history(
                    row, claim, resolve_path=owned):
                raise ValueError("finalized working history changed")
            for database in directory.rglob("*.db"):
                for suffix in ("-wal", "-journal"):
                    sidecar = _member(data, str(database.relative_to(data)) + suffix)
                    if sidecar.exists() and sidecar.stat().st_size:
                        raise ValueError("finalized database has unclosed writes")


def validate_resume(directory: str | Path, spec: StudySpec, config: dict, *,
                    input_root: str | Path, data_root: str | Path, out_dir: str | Path) -> dict:
    """Read-only compatibility check; the supervisor repeats it under ownership."""
    try:
        return _validate_resume(directory, spec, config, input_root=input_root, data_root=data_root, out_dir=out_dir)
    except (KeyError, TypeError, OSError) as exc:
        raise ValueError("missing or malformed working-study evidence") from exc


def _validate_resume(directory: str | Path, spec: StudySpec, config: dict, *,
                     input_root: str | Path, data_root: str | Path, out_dir: str | Path) -> dict:
    from research.study_results import _location
    requested = Path(directory).absolute()
    if requested.resolve() != requested or not requested.is_relative_to(Path(data_root).resolve()):
        raise ValueError("working batch is outside its configured data root or aliased")
    batch = _read(_member(requested, "manifest.json"))
    relative = Path(spec.key[:24]) / f"{batch['manifest_sha256'][:12]}-{batch['batch_id'][:12]}"
    report = Path(out_dir).resolve() / "studies" / relative
    batch.update(data_dir=str(requested), report_dir=str(report))
    _location({"batch": batch}, report / "results.json", Path(data_root), Path(out_dir))
    data, report = _contract(batch, spec, config, Path(input_root))
    records = _journal(data, report, batch["manifest_sha256"])
    last = records[-1]["end"]
    if last["status"] != "paused":
        raise ValueError("finalized supervision cannot resume")
    if len(records) >= 1024:
        raise ValueError("working study reached its supervision history limit")
    payload = _read(_member(report, last["report"]["path"]))
    if (payload["contract"] != "working-study-progress-v1" or payload["batch"] != batch
            or payload["operations"]["supervision"] != {"contract": CONTRACT, "invocation": len(records)}):
        raise ValueError("working progress contract changed")
    _checked_rows(batch, spec, config, payload["results"])
    active = _duration(last["active_wall_seconds"])
    if active < _batch_active_seconds(data, spec):
        raise ValueError("supervised time is less than recorded execution time")
    if active >= spec.operations.max_wall_seconds or _disk_bytes(data) + _disk_bytes(report) >= spec.operations.max_disk_bytes:
        raise ValueError("working study has exhausted its cumulative budget")
    return {"batch": batch, "records": records, "results": payload["results"], "active_wall_seconds": active}


def verify_supervised_result(payload: dict, *, data_dir: Path, report_dir: Path) -> None:
    """Verify the enclosing execution lineage after local or portable loading."""
    records = _journal(data_dir, report_dir, payload["batch"]["manifest_sha256"])
    if (records[-1]["end"]["status"] != "finalized"
            or payload["operations"].get("supervision") != {"contract": CONTRACT, "invocation": len(records)}
            or _duration(payload["operations"]["elapsed_seconds"]) > records[-1]["end"]["active_wall_seconds"]):
        raise ValueError("finalized supervision contract changed")


def _stop(process) -> None:
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join(timeout=5)
        if process.is_alive():
            raise RuntimeError("owned study worker did not stop")


def run_working_study(spec: StudySpec, config: dict, *, input_root: str | Path,
                      data_root: str | Path, out_dir: str | Path,
                      expected_code: dict | None = None, progress: Callable[[dict], None] | None = None,
                      worker_guard_path: Path | None = None, resume_batch: str | Path | None = None,
                      pause_after_ticks: int | None = None) -> dict:
    started = time.monotonic()
    if spec.operations.pause_policy != "preserve_and_resume":
        raise ValueError("working studies require the preserve_and_resume policy")
    if pause_after_ticks is not None and (type(pause_after_ticks) is not int or pause_after_ticks < 1):
        raise ValueError("pause tick limit must be a positive integer")
    if expected_code is not None and code_identity() != expected_code:
        raise ValueError("source changed after study validation")
    options = dict(spec=spec, config=config, input_root=input_root, data_root=data_root, out_dir=out_dir)
    if resume_batch is not None:
        state = validate_resume(resume_batch, **options)
        batch = state["batch"]
    else:
        batch = prepare_study(**options)
    data, report = _contract(batch, spec, config, Path(input_root))
    if expected_code is not None and batch["manifest"]["code"] != expected_code:
        raise ValueError("source changed during study preparation")
    with process_lock(_member(data, "supervisor.lock")):
        # Separate from the worker's batch lock: the parent supervises a child,
        # but never holds the child's writer lock while waiting for it.
        if resume_batch is not None:
            state = validate_resume(resume_batch, **options)
            rows, records, prior = copy.deepcopy(state["results"]), state["records"], state["active_wall_seconds"]
        else:
            rows, records, prior = [_planned(spec, seed, arm) for seed, arm in _assigned(spec)], [], 0.0
        _contract(batch, spec, config, Path(input_root))
        number = len(records) + 1
        prefix = f"supervision/invocation-{number:06d}"
        start_path = publish_json(data / (prefix + "-start.json"), {
            "contract": CONTRACT, "manifest_sha256": batch["manifest_sha256"],
            "previous_end_sha256": records[-1]["end_sha256"] if records else None,
            "prior_active_wall_seconds": prior, "pause_after_ticks": pause_after_ticks})
        if progress:
            progress({"stage": "prepared", "batch": batch})
        context = multiprocessing.get_context("spawn")
        exhausted, paused, workers = None, False, []

        def elapsed():
            return prior + time.monotonic() - started

        def limit_reason():
            if elapsed() >= spec.operations.max_wall_seconds:
                return "wall_time_budget_exhausted"
            if _disk_bytes(data) + _disk_bytes(report) >= spec.operations.max_disk_bytes:
                return "disk_budget_exhausted"
            return None

        for index, previous in enumerate(rows):
            if previous["execution_status"] not in {"planned", "paused"}:
                continue
            exhausted = exhausted or limit_reason()
            if exhausted or paused:
                continue
            seed, arm = previous["seed"], previous["arm"]
            cell = digest_json({"seed": seed, "arm": arm})[:12]
            worker_name = prefix + f"-worker-{cell}.json"
            worker_path = _member(data, worker_name)
            process = context.Process(target=_worker, args=(spec.model_dump(mode="json"), config,
                seed, arm, str(data), str(worker_path), str(Path(input_root).resolve()), batch["manifest"]["code"],
                str(worker_guard_path) if worker_guard_path else None,
                {"batch": batch, "resume": previous["execution_status"] == "paused", "max_ticks": pause_after_ticks}),
                name=f"working-study-{cell}")
            process.start()
            try:
                while process.is_alive():
                    process.join(timeout=.2)
                    exhausted = limit_reason()
                    if exhausted:
                        _stop(process)
                        break
                exit_code = process.exitcode
            finally:
                _stop(process)
                process.close()
            if worker_path.is_file():
                row = _read(worker_path)
                workers.append({"path": worker_name, "sha256": file_sha256(worker_path)})
            else:
                row = _incomplete_row(spec, seed, arm, "failed", exhausted or "worker_failed",
                    worker_exit_code=exit_code, artifact_directory=str(data / cell),
                    last_verified_ticks=previous["ticks"])
                # An unmatched start or absent seal has unknown crash accounting.
                # Finalize this batch with exclusions; never spend a reset budget.
                exhausted = exhausted or "worker_failed"
            exhausted = exhausted or limit_reason()
            if exhausted:
                row["eligibility"] = {"status": "ineligible", "reasons": sorted(set([
                    *row.get("eligibility", {}).get("reasons", []), exhausted]))}
            rows[index] = row
            paused = row["execution_status"] == "paused" and row["eligibility"]["status"] == "pending"
            if not paused:
                publish_json(data / f"worker-{cell}.json", row)
            if progress:
                progress({"stage": "cell", "index": index + 1, "row": row})

        try:
            _contract(batch, spec, config, Path(input_root))
        except (ValueError, OSError, RuntimeError):
            exhausted = "study_contract_changed_during_supervision"
            rows = [{**row, "eligibility": {"status": "ineligible", "reasons": [exhausted]}} for row in rows]
        exhausted = exhausted or limit_reason()
        if exhausted:
            paused = False
            for index, row in enumerate(rows):
                if row["eligibility"]["status"] == "pending":
                    rows[index] = {**row, "eligibility": {"status": "ineligible", "reasons": [exhausted]}}
        summary = paired_summary(rows, next(arm.key for arm in spec.arms if arm.role == "baseline"),
            expected_ticks=spec.time.horizon, expected_arms=[arm.key for arm in spec.arms],
            expected_seeds=spec.randomness.seeds, expected_metrics=[item.key for item in spec.analysis.outcomes],
            minimum_pairs=spec.analysis.minimum_pairs, bootstrap_samples=spec.analysis.bootstrap_samples)
        report_name = f"progress-{number:06d}.json" if paused else "results.json"
        payload = {"contract": "working-study-progress-v1" if paused else "study-result-v1",
            "status": "paused" if paused else "finalized", "batch": batch, "results": rows, "summary": summary,
            "outcomes": [item.model_dump(mode="json") for item in spec.analysis.outcomes],
            "measurement_window": [spec.time.measurement_start, spec.time.measurement_end],
            "operations": {"elapsed_seconds": elapsed(), "stop_reason": "working_attempt_paused" if paused else exhausted,
                "provider_spend_usd": sum(row.get("spend_usd", 0) for row in rows),
                "provider_calls": sum(row.get("provider_calls", 0) for row in rows),
                "supervision": {"contract": CONTRACT, "invocation": number},
                "disk_guard": "200ms sampling; a current write and final diagnostic report can exceed the threshold"},
            "artifacts": {"json": str(report / report_name)}}
        if not paused:
            payload["artifacts"]["markdown"] = str(report / "findings.md")
        publish_json(report / report_name, payload)
        if not paused:
            publish_bytes(report / "findings.md", findings_markdown(payload).encode("utf-8"))
            publish_json(report / "publication.json", {"contract": "study-publication-v1",
                "manifest_sha256": batch["manifest_sha256"], "files": {
                    name: file_sha256(report / name) for name in ("results.json", "findings.md")}})
        end_path = publish_json(data / (prefix + "-end.json"), {"start_sha256": file_sha256(start_path),
            "status": payload["status"], "active_wall_seconds": elapsed(), "workers": workers,
            "report": {"path": report_name, "sha256": file_sha256(report / report_name)}})
        publish_json(data / (prefix + "-seal.json"), {"end_sha256": file_sha256(end_path)})
        return payload

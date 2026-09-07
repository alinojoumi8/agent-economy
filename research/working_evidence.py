"""Read and transport paused scientific evidence without authorizing execution."""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
import copy
from pathlib import Path
import sqlite3

from engine.store import Store
from research.analysis import paired_summary
from research.artifacts import digest_json, file_sha256
from research.process_lock import process_lock
from research.studies import StudySpec
from research.study_results import (
    StudyArtifactError, _location, _verify_context, load_study_result, read_json,
)
from research.study_runner import collect_outcomes, validate_execution
from research.working_attempts import _member
from research.working_contracts import working_protocol
from research.working_studies import CONTRACT, _checked_rows, _journal
from world.replay_verify import canonical_state_receipt


def working_location(path: Path, payload: dict, *, data_root: Path, out_dir: Path):
    if not path.resolve().is_relative_to(out_dir.resolve()):
        raise StudyArtifactError("working evidence is outside its configured report root")
    location = _location(payload, path.parent / "results.json", data_root, out_dir)
    number = payload["operations"]["supervision"]["invocation"]
    if (type(number) is not int or not 1 <= number <= 1024
            or path.resolve() != location.report_dir / f"progress-{number:06d}.json"
            or payload["contract"] != "working-study-progress-v1"
            or payload["status"] != "paused"):
        raise StudyArtifactError("unsupported working progress contract")
    return location


@contextmanager
def working_export_guard(path: Path, *, data_root: Path, out_dir: Path):
    """Hold both owners while a mutable checkpoint is copied into an archive."""
    payload = read_json(path)
    if payload.get("contract") != "working-study-progress-v1":
        yield {}
        return
    location = working_location(path, payload, data_root=data_root, out_dir=out_dir)
    with ExitStack() as stack:
        locked_bytes = {}
        for name in ("supervisor.lock", "working.lock"):
            lock = _member(location.data_dir, name)
            if not lock.is_file() or lock.stat().st_size != 1:
                raise StudyArtifactError("working ownership record is missing")
            handle = stack.enter_context(process_lock(lock))
            # Windows byte-range locks reject a second reader, including our
            # archive inventory. Read the exact control byte through its owner.
            handle.seek(0)
            locked_bytes[lock] = handle.read()
        yield locked_bytes


def load_working_progress(result_path: str | Path, *, data_root: str | Path = "data/studies",
                          out_dir: str | Path = "reports/out", expected_sha256: str | None = None) -> dict:
    """Verify a current checkpoint or its frozen copy, independent of current code.

    This neither runs a simulation nor makes an incomplete study eligible.
    Resume compatibility is a separate check against the original live inputs,
    checkout, schema and namespace in working_studies.validate_resume.
    """
    try:
        path = Path(result_path)
        before = file_sha256(path)
        if expected_sha256 is not None and before != expected_sha256:
            raise StudyArtifactError("working progress differs from its bound hash")
        payload = read_json(path)
        location = working_location(path, payload, data_root=Path(data_root), out_dir=Path(out_dir))
        manifest = payload["batch"]["manifest"]
        spec, config = StudySpec.model_validate(manifest["study"]), manifest["resolved_config"]
        validate_execution(spec, config)
        protocol = working_protocol(spec.operations.pause_policy)
        if (not protocol or manifest.get("attempt_protocol") != protocol
                or manifest.get("timing_contract") != "cumulative-active-wall-v1"
                or digest_json(config) != spec.model.resolved_config_sha256):
            raise StudyArtifactError("working study protocol mismatch")
        cells = len(spec.arms) * len(spec.randomness.seeds)
        if (cells > 512 or len(spec.analysis.outcomes) > 64
                or spec.time.measurement_end - spec.time.measurement_start > 3660
                or cells * len(spec.analysis.outcomes) * spec.analysis.bootstrap_samples > 2_000_000):
            raise StudyArtifactError("working study exceeds the verification work limit")
        context_status = _verify_context(manifest, spec, location)
        records = _journal(location.data_dir, location.report_dir, payload["batch"]["manifest_sha256"])
        last = records[-1]["end"]
        if (last["status"] != "paused" or last["report"]["path"] != path.name
                or payload["operations"]["supervision"] != {"contract": CONTRACT, "invocation": len(records)}
                or (location.report_dir / "results.json").exists()
                or (location.report_dir / "publication.json").exists()):
            raise StudyArtifactError("selected progress is not the current working checkpoint")
        _checked_rows(payload["batch"], spec, config, payload["results"], location=location)
        for row in payload["results"]:
            if row["execution_status"] != "completed":
                continue
            source = location.locate(row["source_database"])
            # Ownership and closed, hash-bound files were checked above. Do not
            # create SQLite sidecars just to remeasure a frozen completed cell.
            connection = sqlite3.connect(f"{source.as_uri()}?mode=ro&immutable=1", uri=True,
                                         isolation_level=None, cached_statements=0)
            try:
                connection.execute("PRAGMA query_only = ON")
                store = Store.from_read_only_connection(source, connection)
                observed = collect_outcomes(store, spec)
                if (any(digest_json(row.get(key)) != digest_json(value) for key, value in observed.items())
                        or canonical_state_receipt(connection)["sha256"] != row["source_state_hash"]
                        or observed["provider_calls"] or observed["spend_usd"]):
                    raise StudyArtifactError("completed working source observations changed")
            finally:
                connection.close()
            if file_sha256(source) != row["source_database_sha256"]:
                raise StudyArtifactError("completed working source changed during verification")
        summary = paired_summary(payload["results"], next(arm.key for arm in spec.arms if arm.role == "baseline"),
            expected_ticks=spec.time.horizon, expected_arms=[arm.key for arm in spec.arms],
            expected_seeds=spec.randomness.seeds, expected_metrics=[item.key for item in spec.analysis.outcomes],
            minimum_pairs=spec.analysis.minimum_pairs, bootstrap_samples=spec.analysis.bootstrap_samples)
        if (digest_json(summary) != digest_json(payload["summary"])
                or payload["outcomes"] != [item.model_dump(mode="json") for item in spec.analysis.outcomes]
                or payload["measurement_window"] != [spec.time.measurement_start, spec.time.measurement_end]):
            raise StudyArtifactError("working measurements or aggregate changed")
        if (file_sha256(path) != before
                or _journal(location.data_dir, location.report_dir, payload["batch"]["manifest_sha256"]) != records):
            raise StudyArtifactError("working checkpoint changed during verification")
        known = [row for row in payload["results"] if row["execution_status"] in {"paused", "completed"}]
        partial = any(row["execution_status"] == "failed" for row in payload["results"])
        calls, spend = sum(row.get("provider_calls", 0) for row in known), sum(row.get("spend_usd", 0) for row in known)
        result = copy.deepcopy(payload)
        result.update(summary=summary, verification={
            "contract": "working-study-verification-v1", "status": "verified", "publication": "working",
            "eligibility": "pending", "result_sha256": before, "declared_context": context_status,
            "active_wall_seconds": last["active_wall_seconds"], "supervision_end_sha256": records[-1]["end_sha256"],
            "operations": {"status": "partial" if partial else "working", "provider_calls": None if partial else calls,
                "provider_spend_usd": None if partial else spend,
                "verified_provider_calls_subtotal": calls, "verified_provider_spend_usd_subtotal": spend},
            "stored_summary_matches": True, "issues": [],
            "data_dir": str(location.data_dir), "report_dir": str(location.report_dir)})
        return result
    except StudyArtifactError:
        raise
    except (ValueError, OSError, KeyError, TypeError, AttributeError, sqlite3.Error) as exc:
        raise StudyArtifactError("working evidence is unavailable, changed or incomplete") from exc


def load_study_evidence(result_path: str | Path, **options) -> dict:
    if read_json(Path(result_path)).get("contract") == "working-study-progress-v1":
        return load_working_progress(result_path, **options)
    return load_study_result(result_path, **options)

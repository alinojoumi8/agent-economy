"""Load study evidence through confined paths and independently recomputed outcomes."""
from __future__ import annotations

import argparse
import copy
from contextlib import ExitStack
from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import sqlite3

from engine.store import Store
from research.analysis import paired_summary
from research.artifacts import digest_json, file_sha256, safe_key
from research.attempts import verify_attempt
from research.studies import StudySpec
from research.working_contracts import attempt_version, working_protocol
from research.study_runner import _arm_config, _incomplete_row, collect_outcomes, validate_execution


class StudyArtifactError(ValueError):
    """Malformed or unsupported study artifacts; no raw contents in the error."""


class StudyIdentityChanged(StudyArtifactError):
    """A previously reviewed result no longer has the same verified evidence."""


def verification_identity(result: dict) -> str:
    verification = {k: v for k, v in result["verification"].items() if k not in {"data_dir", "report_dir"}}
    return digest_json({"verification": verification, "summary": result["summary"], "attempts": result["results"]})


def read_json(path: Path) -> dict:
    if path.stat().st_size > 32 * 1024 * 1024:
        raise StudyArtifactError("study JSON exceeds the verification size limit")
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise StudyArtifactError("study artifact must be a JSON object")
    return result


def _logical_path(value: str):
    if not isinstance(value, str) or not value or "\0" in value:
        raise StudyArtifactError("invalid artifact path")
    kind = PureWindowsPath if re.match(r"^[A-Za-z]:[\\/]", value) or value.startswith("\\\\") else PurePosixPath
    path = kind(value)
    if not path.is_absolute() or ".." in path.parts:
        raise StudyArtifactError("artifact paths must be absolute and cannot traverse parents")
    return path


@dataclass(frozen=True)
class StudyLocation:
    data_dir: Path
    report_dir: Path
    original_data_dir: str
    original_report_dir: str

    def data_file(self, relative: str) -> Path:
        return self.locate(str(_logical_path(self.original_data_dir) / relative))

    def report_file(self, relative: str) -> Path:
        return self.locate(str(_logical_path(self.original_report_dir) / relative))

    def locate(self, value: str) -> Path:
        """Map original absolute paths into local or extracted immutable roots."""
        path = _logical_path(value)
        for original, actual in ((self.original_data_dir, self.data_dir),
                                  (self.original_report_dir, self.report_dir)):
            root = _logical_path(original)
            if type(root) is not type(path):
                continue
            try:
                relative = path.relative_to(root)
            except ValueError:
                continue
            candidate = actual.joinpath(*relative.parts).resolve()
            if not candidate.is_relative_to(actual.resolve()):
                raise StudyArtifactError("artifact escapes the declared study namespace")
            return candidate
        raise StudyArtifactError("artifact is outside the declared study namespace")


def _location(payload: dict, result_path: Path, data_root: Path, out_dir: Path) -> StudyLocation:
    batch = payload["batch"]
    manifest = batch["manifest"]
    digest = batch["manifest_sha256"]
    batch_id = batch["batch_id"]
    if (not re.fullmatch(r"[a-f0-9]{64}", digest)
            or not re.fullmatch(r"[a-f0-9]{32}", batch_id) or digest_json(manifest) != digest):
        raise StudyArtifactError("study manifest identity mismatch")
    key = safe_key(manifest["study"]["key"])
    relative = Path(key[:24]) / f"{digest[:12]}-{batch_id[:12]}"
    data_base, report_base = data_root.resolve(), out_dir.resolve()
    data, report = (data_base / relative).resolve(), (report_base / "studies" / relative).resolve()
    if (not data.is_relative_to(data_base) or not report.is_relative_to(report_base)
            or result_path.resolve() != report / "results.json"):
        raise StudyArtifactError("result is outside the assigned study namespace")
    for name in ("data_dir", "report_dir"):
        if _logical_path(batch[name]).parts[-2:] != tuple(relative.parts):
            raise StudyArtifactError("recorded namespace does not match manifest identity")
    location = StudyLocation(data, report, batch["data_dir"], batch["report_dir"])
    expected = {key: batch[key] for key in ("batch_id", "manifest_sha256", "manifest")}
    if any(digest_json(read_json(path)) != digest_json(expected) for path in (
            location.data_file("manifest.json"), location.report_file("manifest.json"))):
        raise StudyArtifactError("data and report manifests disagree")
    return location


def _verify_cell(row: dict, worker: dict | None, spec: StudySpec, config: dict,
                 location: StudyLocation, cell_id: str) -> list[str]:
    reasons = _stored_reasons(row)
    if row.get("eligibility", {}).get("status") != "eligible":
        reasons += reasons or ["stored_attempt_ineligible"]
    if worker is None:
        if row.get("execution_status") in {"planned", "failed"} and reasons:
            return sorted(set(reasons))
        return sorted(set(reasons + ["worker_receipt_missing"]))
    if worker.get("eligibility", {}).get("status") != "eligible":
        reasons += _stored_reasons(worker) or ["worker_excluded_attempt"]
    if digest_json({k: v for k, v in row.items() if k != "eligibility"}) != digest_json(
            {k: v for k, v in worker.items() if k != "eligibility"}):
        reasons.append("worker_result_mismatch")
    if row.get("execution_status") != "completed":
        return sorted(set(reasons or ["execution_not_completed"]))
    reasons += verify_attempt(row, expected_ticks=spec.time.horizon, resolve_path=location.locate)
    try:
        claim_path = location.locate(row["attempt_claim"])
        if claim_path != location.data_dir / cell_id / "attempt.json":
            raise StudyArtifactError("attempt namespace mismatch")
        claim = read_json(claim_path)
        protocol = working_protocol(spec.operations.pause_policy)
        if (protocol or spec.origin) and (claim.get("protocol_version") != attempt_version(spec.model_dump(mode="json"))
                         or claim.get("study_manifest") != read_json(location.data_file("manifest.json"))["manifest"]):
            reasons.append("study_attempt_protocol_mismatch")
        if protocol:
            finished = location.data_file(f"{cell_id}/result.json")
            seal = read_json(location.data_file(f"{cell_id}/finalized.json"))
            stored = read_json(finished)
            if (seal.get("result_sha256") != file_sha256(finished)
                    or digest_json({k: v for k, v in stored.items() if k != "eligibility"})
                    != digest_json({k: v for k, v in row.items() if k != "eligibility"})):
                reasons.append("finalized_working_result_changed")
        expected = _arm_config(spec, config, row["arm"])
        original_attempt = _logical_path(row["attempt_claim"]).parent
        expected.update(seed=row["seed"], checkpoint_every=0, speed_delay_s=0.0,
            checkpoint_dir=str(original_attempt / "checkpoints"), report_dir=str(original_attempt / "reports"))
        if digest_json(expected) != row["config_sha256"] or digest_json(claim["config"]) != digest_json(expected):
            reasons.append("study_arm_configuration_mismatch")
        if spec.origin:
            from research.attempt_origins import verify_origin_identity
            verify_origin_identity(row, claim, resolve_path=location.locate)
        else:
            genesis = read_json(location.data_file(f"{cell_id}/genesis.json"))
            if digest_json({"state": genesis["sha256"], "prng_state": genesis["prng_state"]}) != row["genesis_hash"]:
                reasons.append("genesis_receipt_mismatch")
        if reasons:
            return sorted(set(reasons))
        with ExitStack() as readers:
            if spec.origin:
                from research.checkpoint_origins import closed_checkpoint
                store = readers.enter_context(closed_checkpoint(location.locate(row["source_database"]),
                                                                max_bytes=spec.operations.max_disk_bytes))
            else:
                store = Store(str(location.locate(row["source_database"])), create=False, read_only=True)
                readers.callback(store.close)
            actual = collect_outcomes(store, spec, origin=claim.get("checkpoint_origin", {}).get("receipt"))
        if any(digest_json(row.get(key)) != digest_json(value) for key, value in actual.items()):
            reasons.append("independent_measurement_mismatch")
        if actual["provider_calls"] or actual["spend_usd"]:
            reasons.append("provider_free_contract_violated")
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
        reasons.append("missing_or_invalid_study_evidence")
    return sorted(set(reasons))


def _stored_reasons(row: dict) -> list[str]:
    eligibility = row.get("eligibility", {})
    if not isinstance(eligibility, dict) or eligibility.get("status") not in {"eligible", "ineligible"}:
        raise StudyArtifactError("invalid attempt eligibility record")
    reasons = eligibility.get("reasons")
    if not isinstance(reasons, list) or any(not isinstance(item, str) for item in reasons):
        raise StudyArtifactError("invalid attempt exclusion reasons")
    return reasons.copy()


def _verify_context(manifest: dict, spec: StudySpec, location: StudyLocation) -> str:
    version = manifest.get("evidence_snapshot_version")
    if version is None:
        if spec.origin:
            raise StudyArtifactError("checkpoint studies require their frozen initial conditions")
        return "legacy_missing"
    if version != "declared-inputs-v1":
        raise StudyArtifactError("unsupported declared-input snapshot contract")
    expected = {"model-description.md": manifest["model_description_sha256"],
                **{f"inputs/{item.sha256}.blob": item.sha256 for item in spec.inputs}}
    for name, digest in expected.items():
        path = location.data_file(f"context/{name}")
        if file_sha256(path) != digest:
            raise StudyArtifactError("frozen model description or declared input was modified")
    if spec.origin:
        from research.checkpoint_origins import verify_checkpoint
        if (manifest.get("origin_contract") != "admitted-state-with-recorded-continuation-v1"
                or set(manifest.get("checkpoint_origins", {})) != {str(seed) for seed in spec.randomness.seeds}):
            raise StudyArtifactError("checkpoint initial conditions are missing")
        for declared in spec.origin.sources:
            artifact = next(item for item in spec.inputs if item.key == declared.input_key)
            receipt = manifest["checkpoint_origins"][str(declared.seed)]
            if (digest_json(receipt) != declared.receipt_sha256 or receipt["database_sha256"] != artifact.sha256
                    or receipt["seed"] != declared.seed or receipt["tick"] != spec.origin.tick):
                raise StudyArtifactError("checkpoint initial condition differs from its declaration")
            verify_checkpoint(location.data_file(f"context/inputs/{artifact.sha256}.blob"), receipt,
                max_bytes=spec.operations.max_disk_bytes, config={**manifest["resolved_config"], "seed": declared.seed})
    return "verified"


def load_study_result(result_path: str | Path, *, data_root: str | Path = "data/studies",
                      out_dir: str | Path = "reports/out", expected_sha256: str | None = None) -> dict:
    """Recompute summary from verified cells; never trust a stored aggregate.

    Roots come from the caller/operator, never from an untrusted report. A known
    external result hash can additionally bind identity. Local checksums alone
    establish internal consistency, not authenticity of an unknown publisher.
    """
    path = Path(result_path)
    if not path.resolve().is_relative_to(Path(out_dir).resolve()):
        raise StudyArtifactError("result is outside the configured report root")
    try:
        if expected_sha256 is not None and file_sha256(path) != expected_sha256:
            raise StudyArtifactError("result differs from its externally bound hash")
        payload = read_json(path)
        if payload["contract"] != "study-result-v1" or payload["batch"]["manifest"]["kind"] != "prospective_study":
            raise StudyArtifactError("unsupported study result contract")
        location = _location(payload, path, Path(data_root), Path(out_dir))
        spec = StudySpec.model_validate(payload["batch"]["manifest"]["study"])
        config = payload["batch"]["manifest"]["resolved_config"]
        validate_execution(spec, config)
        if digest_json(config) != spec.model.resolved_config_sha256:
            raise StudyArtifactError("resolved study configuration mismatch")
        if (len(spec.arms) * len(spec.randomness.seeds) > 512
                or spec.time.measurement_end - spec.time.measurement_start > 3660
                or len(spec.analysis.outcomes) > 64
                or len(spec.arms) * len(spec.randomness.seeds) * len(spec.analysis.outcomes)
                   * spec.analysis.bootstrap_samples > 2_000_000):
            raise StudyArtifactError("study exceeds this loader's verification work limit")
        context_status = _verify_context(payload["batch"]["manifest"], spec, location)
        if working_protocol(spec.operations.pause_policy):
            from research.working_studies import verify_supervised_result
            verify_supervised_result(payload, data_dir=location.data_dir, report_dir=location.report_dir)
        publication = location.report_file("publication.json")
        publication_status = "legacy_missing"
        if publication.is_file():
            published = read_json(publication)
            if (published["contract"] != "study-publication-v1"
                    or published["manifest_sha256"] != payload["batch"]["manifest_sha256"]
                    or set(published["files"]) != {"results.json", "findings.md"}
                    or any(file_sha256(location.report_file(name)) != digest for name, digest in published["files"].items())):
                raise StudyArtifactError("published study report was modified")
            publication_status = "verified"
        assigned = {(arm.key, seed) for arm in spec.arms for seed in spec.randomness.seeds}
        reported = {}
        for row in payload["results"]:
            if type(row["seed"]) is not int or not isinstance(row["arm"], str):
                raise StudyArtifactError("invalid assignment identity")
            key = (row["arm"], row["seed"])
            if key not in assigned or key in reported:
                raise StudyArtifactError("duplicate or unexpected study assignment")
            reported[key] = row
        rows, issues = [], []
        for seed in spec.randomness.seeds:
            for arm in spec.arms:
                original = reported.get((arm.key, seed))
                row = copy.deepcopy(original) if original else _incomplete_row(
                    spec, seed, arm.key, "planned", "missing_reported_attempt")
                if not original:
                    issues.append({"arm": arm.key, "seed": seed, "reason": "missing_reported_attempt"})
                cell_id = digest_json({"seed": seed, "arm": arm.key})[:12]
                worker_path = location.data_file(f"worker-{cell_id}.json")
                try:
                    worker = read_json(worker_path) if worker_path.is_file() else None
                    reasons = _verify_cell(row, worker, spec, config, location, cell_id)
                except (OSError, ValueError, KeyError, TypeError, AttributeError):
                    reasons = ["missing_or_invalid_worker_evidence"]
                row["eligibility"] = {"status": "ineligible" if reasons else "eligible", "reasons": reasons}
                if original and row["eligibility"] != original.get("eligibility"):
                    issues.append({"arm": arm.key, "seed": seed, "reason": "eligibility_recomputed", "details": reasons})
                rows.append(row)
        summary = paired_summary(rows, next(arm.key for arm in spec.arms if arm.role == "baseline"),
            expected_ticks=spec.time.horizon, expected_arms=[arm.key for arm in spec.arms],
            expected_seeds=spec.randomness.seeds, expected_metrics=[item.key for item in spec.analysis.outcomes],
            minimum_pairs=spec.analysis.minimum_pairs, bootstrap_samples=spec.analysis.bootstrap_samples,
            initial_state_key="origin_state_hash" if spec.origin else "genesis_hash")
        agrees = digest_json(summary) == digest_json(payload["summary"])
        if not agrees:
            issues.append({"reason": "stored_summary_disagrees_with_verified_evidence"})
        expected_outcomes = [item.model_dump(mode="json") for item in spec.analysis.outcomes]
        if (payload["outcomes"] != expected_outcomes
                or payload["measurement_window"] != [spec.time.measurement_start, spec.time.measurement_end]):
            raise StudyArtifactError("result measurement contract differs from the frozen study")
        result = copy.deepcopy(payload)
        eligible = [row for row in rows if row["eligibility"]["status"] == "eligible"]
        operations_complete = len(eligible) == len(rows)
        calls = sum(row["provider_calls"] for row in eligible)
        spend = sum(row["spend_usd"] for row in eligible)
        if operations_complete and (payload["operations"].get("provider_calls") != calls
                or payload["operations"].get("provider_spend_usd") != spend):
            issues.append({"reason": "stored_provider_totals_disagree_with_verified_evidence"})
        result.update(results=rows, summary=summary, verification={
            "contract": "study-verification-v1", "status": "verified" if not issues else "degraded",
            "publication": publication_status, "result_sha256": file_sha256(path),
            "declared_context": context_status,
            "operations": {"status": "complete" if operations_complete else "partial",
                           "verified_attempts": len(eligible), "assigned_attempts": len(rows),
                           "provider_calls": calls if operations_complete else None,
                           "provider_spend_usd": spend if operations_complete else None,
                           "verified_provider_calls_subtotal": calls,
                           "verified_provider_spend_usd_subtotal": spend},
            "stored_summary_matches": agrees, "issues": issues,
            "data_dir": str(location.data_dir), "report_dir": str(location.report_dir)})
        return result
    except StudyArtifactError:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError, sqlite3.Error) as exc:
        raise StudyArtifactError("missing, malformed or unsupported study evidence") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("--data-root", type=Path, default=Path("data/studies"))
    parser.add_argument("--out-dir", type=Path, default=Path("reports/out"))
    args = parser.parse_args()
    try:
        result = load_study_result(args.result, data_root=args.data_root, out_dir=args.out_dir)
        print(json.dumps({"verification": result["verification"], "coverage": result["summary"]["coverage"]}))
        return int(result["verification"]["status"] != "verified")
    except StudyArtifactError as exc:
        print(json.dumps({"status": "invalid", "reason": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

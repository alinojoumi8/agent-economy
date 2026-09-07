"""Bounded local operator catalog of saved prospective price studies."""
from __future__ import annotations

from pathlib import Path
from itertools import islice
import re

from research.artifacts import digest_json, file_sha256, publish_json
from research.metric_registry import metric_definition
from research.operator_checkpoints import study_origin_view
from research.process_lock import ProcessLockBusy
from research.studies import StudySpec
from research.study_bundle import export_study_bundle
from research.study_results import StudyArtifactError, StudyIdentityChanged, _location, read_json, verification_identity
from research.working_evidence import load_study_evidence, load_working_progress, working_export_guard
from research.working_contracts import working_protocol


class StudyChanged(StudyIdentityChanged):
    """The selected catalog or verification identity is stale."""


class StudyLibrary:
    MAX_CATALOG = 100
    MAX_SCAN = 500
    MAX_EXPORT_BYTES = 128 * 1024 * 1024

    def __init__(self, *, data_root: Path, out_dir: Path, export_root: Path):
        self.data_root, self.out_dir, self.export_root = data_root.resolve(), out_dir.resolve(), export_root.resolve()

    def catalog(self) -> dict:
        root = self.out_dir / "studies"
        items, scanned, omitted = [], 0, 0
        if not root.exists():
            return {"items": [], "truncated": False, "omitted": 0}
        if not root.resolve().is_relative_to(self.out_dir):
            raise StudyArtifactError("study catalog escapes its configured root")
        # Two known namespace levels only. Never recursively discover arbitrary files.
        keys = list(islice(root.iterdir(), self.MAX_SCAN + 1))
        truncated = len(keys) > self.MAX_SCAN
        for key in sorted(keys[:self.MAX_SCAN]):
            if key.is_symlink() or not key.is_dir() or not key.resolve().is_relative_to(root.resolve()):
                continue
            batches = list(islice(key.iterdir(), self.MAX_SCAN + 1))
            truncated = truncated or len(batches) > self.MAX_SCAN
            for batch in sorted(batches[:self.MAX_SCAN], reverse=True):
                if scanned >= self.MAX_SCAN or len(items) >= self.MAX_CATALOG:
                    return {"items": items, "truncated": True, "omitted": omitted}
                scanned += 1
                path = batch / "results.json"
                kind = "finalized"
                if not path.is_file() and batch.is_dir() and not batch.is_symlink():
                    checkpoints = [item for item in islice(batch.iterdir(), 1026)
                                   if re.fullmatch(r"progress-[0-9]{6}\.json", item.name) and item.is_file()]
                    path = max(checkpoints, default=batch / "manifest.json")
                    kind = "working"
                if batch.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
                    continue
                try:
                    payload = read_json(path)
                    frozen = payload if path.name == "manifest.json" else payload.get("batch", {})
                    manifest = frozen.get("manifest", {})
                    if manifest.get("kind") != "prospective_study":
                        continue
                    if kind == "finalized" and payload.get("contract") != "study-result-v1":
                        continue
                    if kind == "working":
                        protocol = working_protocol(manifest["study"]["operations"]["pause_policy"])
                        if not protocol or manifest.get("attempt_protocol") != protocol:
                            continue
                    study = manifest["study"]
                    if not isinstance(study["title"], str) or not isinstance(study["domains"], list):
                        raise StudyArtifactError("invalid catalog metadata")
                    # One identity survives progress publication and finalization.
                    relative = (batch / "results.json").relative_to(self.out_dir).as_posix()
                    items.append({"id": digest_json(relative)[:32], "title": study["title"][:200],
                        "domains": [name for name in study["domains"] if name in {"goods", "equities"}],
                        "result_sha256": file_sha256(path), "verification": "not_checked",
                        "kind": kind,
                        "_path": path})
                except (OSError, ValueError, KeyError, TypeError):
                    omitted += 1
        return {"items": items, "truncated": truncated, "omitted": omitted}

    def public_catalog(self) -> dict:
        catalog = self.catalog()
        return {**catalog, "items": [{k: v for k, v in row.items() if k != "_path"} for row in catalog["items"]]}

    def resolve(self, study_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", study_id):
            raise KeyError("study not found")
        item = next((item for item in self.catalog()["items"] if item["id"] == study_id), None)
        if item is None:
            raise KeyError("study not found")
        return item["_path"]

    def _load(self, study_id: str, expected_sha256: str) -> dict:
        path = self.resolve(study_id)
        if file_sha256(path) != expected_sha256:
            raise StudyChanged("Study result changed; refresh the catalog before continuing.")
        return load_study_evidence(path, data_root=self.data_root, out_dir=self.out_dir,
                                   expected_sha256=expected_sha256)

    @staticmethod
    def _view(study_id: str, result: dict) -> dict:
        spec = result["batch"]["manifest"]["study"]
        if len(result["results"]) * len(result["outcomes"]) > 1024:
            raise StudyArtifactError("study exceeds the interface's observation limit")
        verification = {k: v for k, v in result["verification"].items() if k not in {"data_dir", "report_dir"}}
        outcomes, measurements = [], {}
        for outcome in result["outcomes"]:
            definition = metric_definition(outcome["metric"])
            outcomes.append({**outcome, "domain": definition.domain, "label": definition.label,
                             "unit": definition.unit, "formula": definition.formula,
                             "missingness": definition.missingness})
            records = []
            for row in result["results"]:
                eligible = row["eligibility"]["status"] == "eligible"
                evidence = row.get("outcome_observations", {}).get(outcome["key"], {}) if eligible else {}
                point = (evidence.get("points") or [{}])[-1]
                records.append({"arm": row["arm"], "seed": row["seed"],
                    "value": row.get("metrics", {}).get(outcome["key"]) if eligible else None,
                    "status": evidence.get("status", "ineligible" if not eligible else "unavailable"),
                    "last_execution_tick": point.get("observed_tick"), "age_ticks": point.get("age_ticks"),
                    "required_points": evidence.get("required_points"), "available_points": evidence.get("available_points")})
            measurements[outcome["key"]] = records
        payload = {"contract": "operator-study-comparison-v1", "id": study_id,
            "title": spec["title"], "hypothesis": spec["hypothesis"], "limitations": spec["limitations"],
            "domains": spec["domains"], "analysis": spec["analysis"], "arms": spec["arms"],
            "measurement_window": result["measurement_window"], "outcomes": outcomes,
            "measurements": measurements,
            "summary": result["summary"], "verification": verification,
            "origin_details": study_origin_view(result["batch"]["manifest"]),
            "manifest_sha256": result["batch"]["manifest_sha256"],
            "source_identity": {key: result["batch"]["manifest"]["code"].get(key)
                                for key in ("git_commit", "source_tree_sha256")},
            "attempts": [{"arm": row["arm"], "seed": row["seed"], "execution_status": row["execution_status"],
                          "eligibility": row["eligibility"], "ticks": row.get("ticks"),
                          "expected_ticks": row["expected_ticks"]} for row in result["results"]]}
        payload["verification_sha256"] = verification_identity(result)
        return payload

    def _working_view(self, study_id: str, path: Path, expected_sha256: str) -> dict:
        if file_sha256(path) != expected_sha256:
            raise StudyChanged("Study progress changed; refresh the catalog before continuing.")
        payload = read_json(path)
        if path.name == "manifest.json":
            relative = path.parent.relative_to(self.out_dir / "studies")
            frozen = {**payload, "data_dir": str(self.data_root / relative), "report_dir": str(path.parent)}
        else:
            frozen = payload["batch"]
        _location({"batch": frozen}, path.parent / "results.json", self.data_root, self.out_dir)
        spec = StudySpec.model_validate(frozen["manifest"]["study"])
        if len(spec.arms) * len(spec.randomness.seeds) > 512:
            raise StudyArtifactError("working study exceeds the interface's assignment limit")
        state, checked = "checkpoint_unavailable", None
        if path.name != "manifest.json":
            try:
                with working_export_guard(path, data_root=self.data_root, out_dir=self.out_dir):
                    checked = load_working_progress(path, data_root=self.data_root, out_dir=self.out_dir,
                                                    expected_sha256=expected_sha256)
                state = "paused"
            except ProcessLockBusy:
                state = "running"
            except (StudyArtifactError, ValueError, OSError):
                state = "needs_attention"
        reported = {(row.get("seed"), row.get("arm")): row for row in payload.get("results", []) if isinstance(row, dict)}
        attempts = []
        for seed in spec.randomness.seeds:
            for arm in spec.arms:
                row = reported.get((seed, arm.key), {})
                ticks = row.get("ticks")
                status = row.get("execution_status", "planned")
                attempts.append({"seed": seed, "arm": arm.key, "expected_ticks": spec.time.horizon,
                    "ticks": ticks if type(ticks) is int and 0 <= ticks <= spec.time.horizon else None,
                    "execution_status": status if status in {"planned", "paused", "completed", "failed", "halted"} else "unknown",
                    "eligibility": row.get("eligibility") if checked else {"status": "pending", "reasons": ["working_evidence_not_verified"]}})
                if checked and "position" in row:
                    attempts[-1]["position"] = {key: row["position"][key]
                        for key in ("completed_tick", "active_tick", "next_phase")}
        verification = ({key: value for key, value in checked["verification"].items()
                         if key not in {"data_dir", "report_dir"}} if checked else {
            "status": "not_verified", "publication": "working", "eligibility": "pending",
            "result_sha256": expected_sha256, "issues": [{"reason": state}]})
        view = {"contract": "operator-working-study-v1", "id": study_id, "state": state,
            "title": spec.title, "hypothesis": spec.hypothesis, "limitations": spec.limitations,
            "domains": spec.domains, "arms": [arm.model_dump(mode="json") for arm in spec.arms],
            "origin_details": study_origin_view(frozen["manifest"]),
            "measurement_window": [spec.time.measurement_start, spec.time.measurement_end],
            "attempts": attempts, "comparison_available": False, "export_available": bool(checked),
            "verification": verification, "manifest_sha256": frozen["manifest_sha256"],
            "source_identity": {key: frozen["manifest"]["code"].get(key) for key in ("git_commit", "source_tree_sha256")},
            "budget": {"max_wall_seconds": spec.operations.max_wall_seconds,
                       "active_wall_seconds": verification.get("active_wall_seconds"),
                       "max_disk_bytes": spec.operations.max_disk_bytes},
            "verification_sha256": verification_identity(checked) if checked else digest_json(verification)}
        if file_sha256(path) != expected_sha256:
            raise StudyChanged("Study progress changed; refresh the catalog before continuing.")
        return view

    def verify(self, study_id: str, expected_sha256: str) -> dict:
        path = self.resolve(study_id)
        if path.name != "results.json":
            return self._working_view(study_id, path, expected_sha256)
        return self._view(study_id, self._load(study_id, expected_sha256))

    def export(self, study_id: str, expected_sha256: str, expected_verification: str) -> dict:
        result = self._load(study_id, expected_sha256)
        if verification_identity(result) != expected_verification:
            raise StudyChanged("Study evidence changed; verify it again before exporting.")
        token = f"{study_id}-{expected_verification[:16]}"
        target, receipt_path = self.export_root / f"{token}.zip", self.export_root / f"{token}.json"
        if target.exists():
            return self.download_receipt(token)
        bundle = export_study_bundle(self.resolve(study_id), target, data_root=self.data_root,
            out_dir=self.out_dir, expected_sha256=expected_sha256,
            expected_verification=expected_verification, max_bytes=self.MAX_EXPORT_BYTES)
        receipt = {"token": token, "sha256": bundle["sha256"], "bytes": bundle["bytes"],
                   "classification": bundle["classification"], "verification_status": bundle["verification_status"]}
        publish_json(receipt_path, receipt)
        return receipt

    def download_receipt(self, token: str) -> dict:
        if not re.fullmatch(r"[a-f0-9]{32}-[a-f0-9]{16}", token):
            raise KeyError("export not found")
        path, receipt_path = self.export_root / f"{token}.zip", self.export_root / f"{token}.json"
        if (not path.resolve().is_relative_to(self.export_root) or path.is_symlink()
                or not receipt_path.resolve().is_relative_to(self.export_root)):
            raise StudyArtifactError("export is outside its configured root")
        receipt = read_json(receipt_path)
        if receipt["token"] != token or file_sha256(path) != receipt["sha256"]:
            raise StudyChanged("Saved export changed; its original receipt is retained.")
        return receipt

    def download_path(self, token: str) -> Path:
        self.download_receipt(token)
        return self.export_root / f"{token}.zip"

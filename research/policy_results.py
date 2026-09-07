"""Verify a policy study's assignments, sealed accounting and scientific evidence."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sqlite3

from research.artifacts import digest_json, file_sha256
from research.policy_analysis import replicated_summary
from research.policy_runner import validate_policy_execution, verify_policy_cell, verify_policy_preflight
from research.policy_studies import policy_configurations, provider_budget_contract, study_cells
from research.provider_budget import BudgetLedgerError, ProviderBudget, ProviderBudgetContract
from research.studies import StudySpec
from research.study_results import StudyArtifactError, _location, _verify_context, read_json


def _sealed_budget(payload: dict, spec: StudySpec, location) -> ProviderBudget:
    manifest = payload["batch"]["manifest"]
    receipt = read_json(location.data_file("provider-budget-receipt.json"))
    if digest_json(receipt) != digest_json(payload["provider_budget"]):
        raise StudyArtifactError("provider budget receipt differs from its published result")
    if (receipt["contract"] != "policy-budget-evidence-v1"
            or receipt["manifest_sha256"] != payload["batch"]["manifest_sha256"]):
        raise StudyArtifactError("provider budget evidence belongs to another study")
    for field, filename in (("database", "provider-budget.db"), ("budget_contract", "provider-budget-contract.json")):
        path = location.locate(receipt[field])
        if path != location.data_file(filename) or file_sha256(path) != receipt[field + "_sha256"]:
            raise StudyArtifactError("sealed provider accounting was modified")
    for suffix in ("-wal", "-journal"):
        sidecar = location.data_file("provider-budget.db" + suffix)
        if sidecar.exists() and sidecar.stat().st_size:
            raise StudyArtifactError("provider accounting has an unfinished transaction")
    contract = ProviderBudgetContract.model_validate_json(json.dumps(read_json(location.data_file("provider-budget-contract.json"))))
    expected = provider_budget_contract(spec, manifest["resolved_config"],
        manifest_sha256=payload["batch"]["manifest_sha256"], verify_source=False)
    if contract != expected:
        raise StudyArtifactError("provider budget differs from the prospective assignment")
    budget = ProviderBudget(location.data_file("provider-budget.db"), contract,
        scope="verification", binding_key=spec.policy_design.policies[0].key, read_only=True)
    if not budget.is_sealed() or digest_json({**budget.snapshot(), "sealed": True}) != digest_json(receipt["usage"]):
        raise StudyArtifactError("provider accounting is not sealed at its published totals")
    scopes = {f"preflight-{policy.key}": [policy.key] for policy in spec.policy_design.policies
              if policy.behavior.family == "live_llm"}
    scopes.update({cell["cell_key"]: [cell["policy"]] for cell in study_cells(spec)})
    if any(scopes.get(key) != bindings for key, bindings in budget.scope_bindings().items()):
        raise StudyArtifactError("provider usage leaves the prospective policy assignment")
    return budget


def _preflights(payload: dict, spec: StudySpec, location, budget: ProviderBudget) -> bool:
    policies = [policy for policy in spec.policy_design.policies if policy.behavior.family == "live_llm"]
    entries = payload["preflight"]
    if not isinstance(entries, list) or len(entries) > len(policies):
        raise StudyArtifactError("invalid preflight assignment")
    all_ready = len(entries) == len(policies)
    for index, entry in enumerate(entries):
        policy = policies[index]
        if entry["policy"] != policy.key or type(entry["ready"]) is not bool:
            raise StudyArtifactError("preflight assignment changed")
        ready = False
        path = location.data_file(f"preflight-{policy.key}.json")
        if "receipt" in entry:
            if location.locate(entry["receipt"]) != path or file_sha256(path) != entry["sha256"]:
                raise StudyArtifactError("preflight receipt changed")
            packet = read_json(path)
            if packet.get("contract") == "policy-preflight-v1":
                ready = verify_policy_preflight(packet, policy, payload["batch"],
                    budget.snapshot(scope=f"preflight-{policy.key}"))
            elif (packet.get("contract") != "policy-worker-failure-v1"
                    or packet.get("policy") != policy.key or packet.get("cell") is not None
                    or packet.get("manifest_sha256") != payload["batch"]["manifest_sha256"]):
                raise StudyArtifactError("preflight failure evidence changed")
        elif path.exists():
            raise StudyArtifactError("preflight receipt was omitted")
        if entry["ready"] != ready:
            raise StudyArtifactError("preflight readiness was modified")
        if not ready or entry.get("stop_reason"):
            all_ready = False
            if index != len(entries) - 1:
                raise StudyArtifactError("another preflight was dispatched after the study stopped")
    return all_ready


def _verified_row(row: dict, cell: dict, payload: dict, spec: StudySpec, location,
                  budget: ProviderBudget, preflight_ready: bool) -> dict:
    result = copy.deepcopy(row)
    reasons = list(row["eligibility"]["reasons"])
    if row["eligibility"]["status"] != "eligible":
        reasons += reasons or ["stored_attempt_ineligible"]
    usage = budget.snapshot(scope=cell["cell_key"])
    path = location.data_file(f"cell-{cell['cell_key']}.json")
    if "policy_receipt" in row:
        if location.locate(row["policy_receipt"]) != path or file_sha256(path) != row["policy_receipt_sha256"]:
            raise StudyArtifactError("policy worker receipt changed")
        packet = read_json(path)
        if packet.get("contract") == "policy-cell-v1":
            expected = {**packet["attempt"], **cell, "provider_usage": packet["provider_usage"],
                "policy_receipt": row["policy_receipt"], "policy_receipt_sha256": file_sha256(path),
                "worker_stop_reason": row.get("worker_stop_reason")}
            if digest_json({k: v for k, v in row.items() if k != "eligibility"}) != digest_json(
                    {k: v for k, v in expected.items() if k != "eligibility"}):
                reasons.append("policy_worker_result_mismatch")
            reasons += verify_policy_cell(packet, cell, payload["batch"],
                resolve_path=location.locate, expected_usage=usage)
            if row.get("worker_stop_reason"):
                reasons.append(row["worker_stop_reason"])
            if not preflight_ready:
                reasons.append("policy_preflight_not_verified")
        elif (packet.get("contract") == "policy-worker-failure-v1"
                and packet.get("manifest_sha256") == payload["batch"]["manifest_sha256"]
                and digest_json(packet.get("cell")) == digest_json(cell)
                and packet.get("policy") == cell["policy"]):
            reasons.append("worker_failed")
        else:
            raise StudyArtifactError("policy worker identity changed")
    else:
        if path.exists() or row.get("execution_status") not in {"planned", "failed"} or not reasons:
            reasons.append("missing_or_omitted_policy_receipt")
        if any(value is not None for value in row.get("metrics", {}).values()):
            reasons.append("unverified_policy_measurement")
    result["eligibility"] = {"status": "ineligible" if reasons else "eligible", "reasons": sorted(set(reasons))}
    return result


def load_policy_result(result_path: str | Path, *, data_root: str | Path = "data/studies",
                       out_dir: str | Path = "reports/out", expected_sha256: str | None = None) -> dict:
    """Read only, with caller-owned roots and independently recomputed outcomes.

    Local hashes prove consistency, not authenticity of an unknown publisher.
    An externally supplied result hash can bind a previously reviewed result.
    Loading makes no provider calls and does not require current credentials.
    """
    path = Path(result_path)
    if not path.resolve().is_relative_to(Path(out_dir).resolve()):
        raise StudyArtifactError("policy result is outside the configured report root")
    try:
        if expected_sha256 is not None and file_sha256(path) != expected_sha256:
            raise StudyArtifactError("policy result differs from its externally bound hash")
        payload = read_json(path)
        if payload["contract"] != "policy-study-result-v1" or payload["batch"]["manifest"]["kind"] != "prospective_study":
            raise StudyArtifactError("unsupported policy result contract")
        location = _location(payload, path, Path(data_root), Path(out_dir))
        manifest = payload["batch"]["manifest"]
        spec = StudySpec.model_validate(manifest["study"])
        config = manifest["resolved_config"]
        validate_policy_execution(spec, config, verify_source=False)
        if digest_json(config) != spec.model.resolved_config_sha256 or config.get("engine_semantics_version") != spec.model.engine_semantics_version:
            raise StudyArtifactError("policy study configuration differs from its model")
        cells = study_cells(spec)
        if (digest_json(manifest["assigned_cells"]) != digest_json(cells)
                or digest_json(manifest["policy_configurations"]) != digest_json(policy_configurations(spec, config, verify_source=False))):
            raise StudyArtifactError("resolved policies differ from their prospective assignment")
        context = _verify_context(manifest, spec, location)
        publication = read_json(location.report_file("publication.json"))
        if (publication["contract"] != "policy-study-publication-v1"
                or publication["manifest_sha256"] != payload["batch"]["manifest_sha256"]
                or set(publication["files"]) != {"results.json", "findings.md"}
                or any(file_sha256(location.report_file(name)) != digest for name, digest in publication["files"].items())):
            raise StudyArtifactError("published policy result was modified")
        budget = _sealed_budget(payload, spec, location)
        preflight_ready = _preflights(payload, spec, location, budget)
        reported = {}
        assignments = {cell["cell_key"]: cell for cell in cells}
        for row in payload["results"]:
            key = row["cell_key"]
            cell = assignments.get(key)
            if key in reported or cell is None or digest_json({k: row.get(k) for k in cell}) != digest_json(cell):
                raise StudyArtifactError("duplicate or foreign policy assignment")
            if (row["eligibility"]["status"] not in {"eligible", "ineligible"}
                    or not isinstance(row["eligibility"]["reasons"], list)
                    or any(not isinstance(item, str) for item in row["eligibility"]["reasons"])):
                raise StudyArtifactError("invalid policy exclusion record")
            reported[key] = row
        if len(reported) != len(cells):
            raise StudyArtifactError("assigned policy cells were omitted")
        rows, issues = [], []
        for cell in cells:
            original = reported[cell["cell_key"]]
            row = _verified_row(original, cell, payload, spec, location, budget, preflight_ready)
            if row["eligibility"] != original["eligibility"]:
                issues.append({"cell_key": cell["cell_key"], "reason": "eligibility_recomputed", "details": row["eligibility"]["reasons"]})
            rows.append(row)
        summary = replicated_summary(rows, spec)
        agrees = digest_json(summary) == digest_json(payload["summary"])
        if not agrees:
            issues.append({"reason": "stored_summary_disagrees_with_verified_evidence"})
        if (payload["outcomes"] != [item.model_dump(mode="json") for item in spec.analysis.outcomes]
                or payload["measurement_window"] != [spec.time.measurement_start, spec.time.measurement_end]):
            raise StudyArtifactError("policy result changed its measurement contract")
        usage = {**budget.snapshot(), "sealed": True}
        totals = {"provider_calls": usage["provider_calls"], "usage_cost_usd": usage["usage_cost_nano_usd"] / 1e9,
                  "encumbered_usd": usage["encumbered_nano_usd"] / 1e9}
        if any(payload["operations"].get(key) != value for key, value in totals.items()):
            issues.append({"reason": "stored_provider_totals_disagree_with_sealed_accounting"})
        if file_sha256(budget.path) != payload["provider_budget"]["database_sha256"]:
            raise StudyArtifactError("sealed provider accounting changed during verification")
        result = copy.deepcopy(payload)
        result.update(results=rows, summary=summary, verification={
            "contract": "policy-study-verification-v1", "status": "verified" if not issues else "degraded",
            "publication": "verified", "result_sha256": file_sha256(path), "declared_context": context,
            "provider_budget": usage, "preflight_ready": preflight_ready,
            "stored_summary_matches": agrees, "issues": issues,
            "data_dir": str(location.data_dir), "report_dir": str(location.report_dir)})
        return result
    except StudyArtifactError:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError, sqlite3.Error, BudgetLedgerError) as exc:
        raise StudyArtifactError("missing, malformed or unsupported policy evidence") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("--data-root", type=Path, default=Path("data/studies"))
    parser.add_argument("--out-dir", type=Path, default=Path("reports/out"))
    args = parser.parse_args()
    try:
        result = load_policy_result(args.result, data_root=args.data_root, out_dir=args.out_dir)
        print(json.dumps({"verification": result["verification"], "coverage": result["summary"]["coverage"]}))
        return int(result["verification"]["status"] != "verified")
    except StudyArtifactError as exc:
        print(json.dumps({"status": "invalid", "reason": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

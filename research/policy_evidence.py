"""Private policy evidence may be readable without being resumable or complete."""
from __future__ import annotations

import copy
from pathlib import Path
import sqlite3

from research.artifacts import digest_json, file_sha256
from research.policy_analysis import replicated_summary
from research.policy_recovery import PROGRESS, SUPERVISION, open_allowance, verify_lineage, verify_receipt
from research.policy_results import _policy_declaration, _verified_working_row, load_policy_result
from research.provider_budget import BudgetLedgerError
from research.study_results import StudyArtifactError, _verify_context, read_json
from research.working_contracts import working_protocol


def load_policy_progress(result_path: str | Path, *, data_root: str | Path = "data/studies",
                         out_dir: str | Path = "reports/out", expected_sha256: str | None = None) -> dict:
    """Verify the latest closed pause or a frozen copy, without a writable open.

    The overall publication stays pending, even when individual worlds already
    have eligible final evidence. Runtime resume still requires its original
    namespace, sources, code and allowance; transport never grants that right.
    """
    from research.working_evidence import working_location
    from research.working_studies import _checked_rows, _duration, _journal

    path = Path(result_path)
    if not path.resolve().is_relative_to(Path(out_dir).resolve()):
        raise StudyArtifactError("policy progress is outside the configured report root")
    try:
        before = file_sha256(path)
        if expected_sha256 is not None and before != expected_sha256:
            raise StudyArtifactError("policy progress differs from its externally bound hash")
        payload = read_json(path)
        location = working_location(path, payload, data_root=Path(data_root), out_dir=Path(out_dir),
            progress_contract=PROGRESS)
        manifest = payload["batch"]["manifest"]
        spec, config, cells = _policy_declaration(manifest)
        protocol = working_protocol(spec.operations.pause_policy)
        if (not protocol or manifest.get("attempt_protocol") != protocol
                or manifest.get("timing_contract") != "cumulative-active-wall-v1"):
            raise StudyArtifactError("policy progress differs from its working protocol")
        context = _verify_context(manifest, spec, location)
        records = _journal(location.data_dir, location.report_dir, payload["batch"]["manifest_sha256"], contract=SUPERVISION)
        if not records:
            raise StudyArtifactError("policy progress has no closed supervision")
        last = records[-1]["end"]
        if (last["status"] != "paused" or last["report"]["path"] != path.name
                or payload["operations"]["supervision"] != {"contract": SUPERVISION, "invocation": len(records)}
                or payload["operations"]["stop_reason"] != "working_attempt_paused"
                or _duration(payload["operations"]["elapsed_seconds"]) > last["active_wall_seconds"]
                or location.report_file("results.json").exists() or location.report_file("publication.json").exists()
                or location.data_file("provider-budget-receipt.json").exists()):
            raise StudyArtifactError("selected policy progress is not the current closed pause")
        budget = open_allowance(payload["batch"], location=location, read_only=True, verify_source=False)
        ready = verify_lineage(payload, spec, location, budget, records)
        if not ready:
            raise StudyArtifactError("paused policy worlds have no verified preflight")
        _checked_rows(payload["batch"], spec, config, payload["results"], location=location)
        if (sum(row["execution_status"] == "paused" for row in payload["results"]) != 1
                or any(row["execution_status"] not in {"planned", "paused", "completed"} for row in payload["results"])):
            raise StudyArtifactError("policy progress has no unique cooperative pause")
        rows, issues = [], []
        for cell, row in zip(cells, payload["results"]):
            if row["execution_status"] == "completed":
                checked = _verified_working_row(row, cell, payload, location, budget)
                if checked["eligibility"] != row["eligibility"]:
                    issues.append({"cell_key": cell["cell_key"], "reason": "eligibility_recomputed",
                        "details": checked["eligibility"]["reasons"]})
            else:
                if (row["eligibility"]["status"] != "pending"
                        or not isinstance(row["eligibility"]["reasons"], list)
                        or any(not isinstance(reason, str) for reason in row["eligibility"]["reasons"])):
                    raise StudyArtifactError("unfinished policy evidence was promoted or changed")
                checked = copy.deepcopy(row)
            rows.append(checked)
        summary = replicated_summary(rows, spec)
        agrees = digest_json(summary) == digest_json(payload["summary"])
        if not agrees:
            issues.append({"reason": "stored_summary_disagrees_with_verified_evidence"})
        if (payload["outcomes"] != [item.model_dump(mode="json") for item in spec.analysis.outcomes]
                or payload["measurement_window"] != [spec.time.measurement_start, spec.time.measurement_end]):
            raise StudyArtifactError("policy progress changed its measurement contract")
        usage = budget.snapshot()
        totals = {"provider_calls": usage["provider_calls"], "usage_cost_usd": usage["usage_cost_nano_usd"] / 1e9,
            "encumbered_usd": usage["encumbered_nano_usd"] / 1e9,
            "provider_spend_usd": sum(row.get("spend_usd", 0) for row in rows)}
        if any(payload["operations"].get(key) != value for key, value in totals.items()):
            issues.append({"reason": "stored_provider_totals_disagree_with_original_accounting"})
        # A writer or an unfinished invocation cannot turn an earlier snapshot
        # into the current pause while verification is in progress.
        verify_receipt(payload["provider_budget"], payload["batch"], budget,
            locate=location.locate, at_head=True, sealed=False)
        if (file_sha256(path) != before or _journal(location.data_dir, location.report_dir,
                payload["batch"]["manifest_sha256"], contract=SUPERVISION) != records):
            raise StudyArtifactError("policy progress changed during verification")
        result = copy.deepcopy(payload)
        result.update(results=rows, summary=summary, verification={
            "contract": "policy-working-verification-v1", "status": "verified" if not issues else "degraded",
            "publication": "working", "eligibility": "pending", "result_sha256": before,
            "declared_context": context, "provider_budget": {**usage, "sealed": False}, "preflight_ready": ready,
            "active_wall_seconds": last["active_wall_seconds"], "supervision_end_sha256": records[-1]["end_sha256"],
            "stored_summary_matches": agrees, "issues": issues,
            "data_dir": str(location.data_dir), "report_dir": str(location.report_dir)})
        return result
    except StudyArtifactError:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError, sqlite3.Error, BudgetLedgerError) as exc:
        raise StudyArtifactError("missing, changed or unsupported working policy evidence") from exc


def load_policy_evidence(result_path: str | Path, **options) -> dict:
    try:
        contract = read_json(Path(result_path)).get("contract")
    except StudyArtifactError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise StudyArtifactError("missing or malformed policy evidence") from exc
    if contract == PROGRESS:
        return load_policy_progress(result_path, **options)
    if contract not in ("policy-study-result-v1", "policy-study-result-v2"):
        raise StudyArtifactError("unsupported policy evidence contract")
    return load_policy_result(result_path, **options)

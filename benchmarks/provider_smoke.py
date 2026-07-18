"""Receipt builder for the separate ten-tick MiniMax/Kimi smoke."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


RECEIPT_SCHEMA = "world-os-v8-provider-smoke-receipt-v1"
REQUIRED_KEYS = ("MINIMAX_API_KEY", "KIMI_API_KEY")
REQUIRED_EVIDENCE = (
    "ticks_completed",
    "command_validity_rate",
    "persona_consistent_replies",
    "causal_decision_influence",
    "knowledge_boundary_violations",
    "pause_resume_passed",
    "providers",
)


def missing_provider_keys(environ: Mapping[str, str]) -> list[str]:
    return [key for key in REQUIRED_KEYS if not str(environ.get(key, "")).strip()]


def _evaluate(evidence: Mapping[str, Any]) -> dict[str, bool]:
    missing = [key for key in REQUIRED_EVIDENCE if key not in evidence]
    if missing:
        raise ValueError(f"provider evidence missing fields: {', '.join(missing)}")
    return {
        "ten_ticks_completed": int(evidence["ticks_completed"]) == 10,
        "command_validity": float(evidence["command_validity_rate"]) >= 0.95,
        "persona_consistent_replies": bool(evidence["persona_consistent_replies"]),
        "causal_decision_influence": bool(evidence["causal_decision_influence"]),
        "knowledge_boundary": int(evidence["knowledge_boundary_violations"]) == 0,
        "pause_resume": bool(evidence["pause_resume_passed"]),
        "provider_identity": bool(evidence["providers"]),
    }


def build_provider_receipt(
    *,
    build_identifier: str,
    evidence: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    environment = os.environ if environ is None else environ
    missing_keys = missing_provider_keys(environment)
    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "build_identifier": str(build_identifier),
        "run_config": "runs/live-smoke.yaml",
        "ticks_required": 10,
        "credential_values_recorded": False,
        "missing_environment_keys": missing_keys,
        "provider_evidence": None,
        "criteria": {},
        "status": "unavailable",
        "reason": "",
    }
    if evidence is None:
        receipt["reason"] = (
            "MINIMAX_API_KEY and KIMI_API_KEY are not both configured"
            if missing_keys
            else "provider credentials exist but no completed ten-tick evidence was supplied"
        )
        return receipt

    criteria = _evaluate(evidence)
    receipt["provider_evidence"] = dict(evidence)
    receipt["criteria"] = criteria
    receipt["status"] = "passed" if all(criteria.values()) else "failed"
    receipt["reason"] = "all provider gates passed" if receipt["status"] == "passed" else (
        "one or more provider gates failed")
    return receipt

def write_provider_receipt(
    path: str | Path,
    *,
    build_identifier: str,
    evidence: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    receipt = build_provider_receipt(
        build_identifier=build_identifier,
        evidence=evidence,
        environ=environ,
    )
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt

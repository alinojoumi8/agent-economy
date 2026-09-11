"""Declared decision-policy transitions from immutable admitted worlds."""
from __future__ import annotations

from pathlib import Path

from research.artifacts import digest_json
from research.checkpoint_origins import continuation_config, verify_checkpoint
from research.policy_studies import policy_configurations, study_cells
from research.studies import StudySpec

TRANSITION = "checkpoint-policy-transition-v1"


def policy_transition(manifest: dict, seed: int, arm: str, receipt: dict) -> dict:
    """Derive the entire transition; there is no arbitrary configuration patch."""
    from research.study_runner import _arm_config
    spec = StudySpec.model_validate(manifest["study"])
    common = manifest["resolved_config"]
    if (spec.protocol_version != "research-study-v3" or spec.origin is None
            or manifest.get("kind") != "prospective_study"
            or digest_json(common) != spec.model.resolved_config_sha256
            or manifest.get("origin_contract") != "admitted-state-with-recorded-continuation-v1"
            or digest_json(manifest["assigned_cells"]) != digest_json(study_cells(spec))
            or digest_json(manifest["policy_configurations"]) != digest_json(policy_configurations(spec, common, verify_source=False))):
        raise ValueError("policy origin differs from its prospective study")
    if receipt["seed"] != seed or receipt["tick"] != spec.origin.tick:
        raise ValueError("policy transition differs from its admitted boundary")
    original = continuation_config({**common, "seed": seed})
    if digest_json(original) != receipt["continuation_config_sha256"]:
        raise ValueError("policy transition changed its initial configuration")
    configured = _arm_config(spec, common, arm, verify_policy_source=False)
    configured["seed"] = seed
    key = next(item.policy for item in spec.arms if item.key == arm)
    policy = next(item for item in spec.policy_design.policies if item.key == key)
    return {"contract": TRANSITION, "effective_tick": receipt["tick"] + 1,
        "study_manifest_sha256": digest_json(manifest), "policy": key,
        "policy_definition_sha256": digest_json(policy.model_dump(mode="json")),
        "source_configuration_sha256": digest_json(original),
        "continuation_configuration_sha256": digest_json(continuation_config(configured))}


def validate_policy_continuation(original: dict, configured: dict, receipt: dict,
                                 interventions: list[dict], claim: dict) -> None:
    from research.study_runner import arm_interventions
    manifest = claim["study_manifest"]
    spec = StudySpec.model_validate(manifest["study"])
    expected = policy_transition(manifest, receipt["seed"], claim["arm"], receipt)
    cell = claim["policy_cell"]
    if (claim["protocol_version"] != 6 or claim["study_manifest_sha256"] != digest_json(manifest)
            or not any(digest_json(cell) == digest_json(item) for item in study_cells(spec))
            or cell["seed"] != receipt["seed"] or cell["arm"] != claim["arm"] or cell["policy"] != expected["policy"]
            or claim["checkpoint_origin"]["policy_transition"] != expected
            or continuation_config(original) != continuation_config({**manifest["resolved_config"], "seed": receipt["seed"]})
            or digest_json(continuation_config(configured)) != expected["continuation_configuration_sha256"]
            or claim["seed"] != receipt["seed"] or claim["checkpoint_origin"]["receipt"] != receipt
            or interventions != arm_interventions(spec, claim["arm"])):
        raise ValueError("continuation changes more than its declared decision policy and interventions")


def verify_policy_origin(row: dict, claim: dict, *, resolve_path=Path) -> dict:
    from research.attempt_origins import origin_row_fields
    from research.policy_studies import provider_budget_contract
    from research.study_runner import _arm_config, arm_interventions
    manifest = claim["study_manifest"]
    spec = StudySpec.model_validate(manifest["study"])
    cell = claim["policy_cell"]
    if (claim["protocol_version"] != 6 or spec.origin is None or spec.protocol_version != "research-study-v3"
            or claim["study_manifest_sha256"] != digest_json(manifest)
            or not any(digest_json(cell) == digest_json(item) for item in study_cells(spec))
            or cell["seed"] != claim["seed"] or cell["arm"] != claim["arm"]
            or digest_json(row["policy_cell"]) != digest_json(cell)):
        raise ValueError("policy checkpoint attempt differs from its assigned cell")
    directory = resolve_path(row["attempt_claim"]).parent
    if (directory.name != digest_json({"seed": cell["seed"], "arm": cell["arm"]})[:12]
            or directory.parent.name != cell["cell_key"] or directory.parent.parent.name != "cells"):
        raise ValueError("policy origin leaves its assigned namespace")
    source = next(item for item in spec.origin.sources if item.seed == cell["seed"])
    artifact = next(item for item in spec.inputs if item.key == source.input_key)
    expected_path = directory.parents[2] / "context" / "inputs" / f"{artifact.sha256}.blob"
    binding = claim["checkpoint_origin"]
    receipt = binding["receipt"]
    expected_budget = provider_budget_contract(spec, manifest["resolved_config"],
        manifest_sha256=digest_json(manifest), verify_source=False)
    if (set(binding) != {"database", "receipt", "interventions", "max_bytes", "policy_transition"}
            or resolve_path(binding["database"]) != expected_path
            or binding["max_bytes"] != spec.operations.max_disk_bytes
            or binding["interventions"] != arm_interventions(spec, claim["arm"])
            or digest_json(receipt) != source.receipt_sha256
            or receipt != manifest["checkpoint_origins"][str(cell["seed"])]
            or receipt["database_sha256"] != artifact.sha256
            or binding["policy_transition"] != policy_transition(manifest, cell["seed"], cell["arm"], receipt)
            or claim["provider_budget_contract_sha256"] != digest_json(expected_budget.model_dump(mode="json"))
            or row["provider_budget_contract_sha256"] != claim["provider_budget_contract_sha256"]
            or any(row.get(key) != value for key, value in origin_row_fields(claim).items())
            or row.get("genesis_hash") is not None or "genesis_receipt" in row):
        raise ValueError("policy checkpoint initial condition or transition changed")
    configured = _arm_config(spec, manifest["resolved_config"], claim["arm"], verify_policy_source=False)
    configured["seed"] = cell["seed"]
    if continuation_config(claim["config"]) != continuation_config(configured):
        raise ValueError("policy checkpoint changes undeclared economic configuration")
    return verify_checkpoint(expected_path, receipt, max_bytes=binding["max_bytes"],
        config={**manifest["resolved_config"], "seed": cell["seed"]})


def validate_origin_allowance(claim: dict, budget) -> None:
    """Before constructing the branch, require its original scoped allowance."""
    from research.provider_budget import ProviderBudget
    from research.policy_studies import provider_budget_contract
    manifest = claim["study_manifest"]
    expected = provider_budget_contract(StudySpec.model_validate(manifest["study"]), manifest["resolved_config"],
        manifest_sha256=digest_json(manifest), verify_source=False)
    cell = claim["policy_cell"]
    root = Path(claim["checkpoint_origin"]["database"]).parents[2]
    if (not isinstance(budget, ProviderBudget) or budget.is_sealed() or budget.contract != expected
            or budget.scope != cell["cell_key"] or budget.binding_key != cell["policy"]
            or budget.path != root / "provider-budget.db"
            or digest_json(budget.contract.model_dump(mode="json")) != claim["provider_budget_contract_sha256"]):
        raise ValueError("policy origin requires its original completion allowance")

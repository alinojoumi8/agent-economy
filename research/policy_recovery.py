"""Original-allowance receipts for supervised policy-study recovery."""
from __future__ import annotations

from pathlib import Path

from research.artifacts import digest_json, file_sha256, publish_json
from research.policy_studies import provider_budget_contract, study_cells
from research.provider_budget import ProviderBudget, ProviderBudgetContract
from research.studies import StudySpec
from research.working_attempts import _member, _read

SUPERVISION = "policy-working-study-supervision-v1"
PROGRESS = "policy-working-progress-v1"
RESULT = "policy-study-result-v2"


def open_allowance(batch: dict, *, location=None, read_only: bool = False,
                   verify_source: bool = True) -> ProviderBudget:
    root = location.data_dir if location else Path(batch["data_dir"])
    spec = StudySpec.model_validate(batch["manifest"]["study"])
    contract = ProviderBudgetContract.model_validate_json(
        _member(root, "provider-budget-contract.json").read_text(encoding="utf-8"))
    expected = provider_budget_contract(spec, batch["manifest"]["resolved_config"],
        manifest_sha256=batch["manifest_sha256"], verify_source=verify_source)
    if contract != expected:
        raise ValueError("provider allowance differs from the prospective study")
    return ProviderBudget(_member(root, "provider-budget.db"), contract, scope="supervisor",
        binding_key=spec.policy_design.policies[0].key, read_only=read_only)


def create_allowance(batch: dict, spec: StudySpec, config: dict) -> ProviderBudget:
    root = Path(batch["data_dir"])
    contract = provider_budget_contract(spec, config, manifest_sha256=batch["manifest_sha256"])
    publish_json(root / "provider-budget-contract.json", contract.model_dump(mode="json"))
    return ProviderBudget.create(root / "provider-budget.db", contract, scope="supervisor",
        binding_key=spec.policy_design.policies[0].key)


def budget_receipt(batch: dict, budget: ProviderBudget, *, sealed: bool) -> dict:
    usage = budget.seal() if sealed else budget.snapshot()
    contract_path = Path(batch["data_dir"]) / "provider-budget-contract.json"
    return {"contract": "policy-budget-evidence-v1", "manifest_sha256": batch["manifest_sha256"],
        "database": str(budget.path), "database_sha256": file_sha256(budget.path), "usage": usage,
        "budget_contract": str(contract_path), "budget_contract_sha256": file_sha256(contract_path),
        "checkpoint": budget.checkpoint()}


def verify_receipt(receipt: dict, batch: dict, budget: ProviderBudget, *,
                   locate=Path, at_head: bool = False, sealed: bool = False) -> None:
    if (receipt["contract"] != "policy-budget-evidence-v1"
            or receipt["manifest_sha256"] != batch["manifest_sha256"]
            or locate(receipt["database"]) != budget.path
            or locate(receipt["budget_contract"]) != budget.path.parent / "provider-budget-contract.json"
            or file_sha256(locate(receipt["budget_contract"])) != receipt["budget_contract_sha256"]):
        raise ValueError("working provider allowance identity changed")
    checkpoint = receipt["checkpoint"]
    budget.verify_checkpoint(checkpoint)
    expected = budget.snapshot(through=checkpoint["last_sequence"])
    if sealed:
        expected["sealed"] = True
    if digest_json(receipt["usage"]) != digest_json(expected):
        raise ValueError("working provider totals differ from their reservation history")
    if at_head and (file_sha256(budget.path) != receipt["database_sha256"]
            or digest_json(budget.checkpoint()) != digest_json(checkpoint) or budget.is_sealed() != sealed):
        raise ValueError("original provider allowance changed after supervision closed")


def preflight_scope(policy_key: str, invocation: int) -> str:
    return f"preflight-{policy_key}-i{invocation:06d}"


def run_preflights(batch: dict, spec: StudySpec, budget: ProviderBudget, *, invocation: int,
                   input_root: Path, guard_path: Path | None, deadline: float) -> tuple[list[dict], list[dict], str | None]:
    from research.policy_runner import _supervise, verify_policy_preflight
    entries, workers, stopped = [], [], None
    for policy in spec.policy_design.policies:
        if policy.behavior.family == "scripted":
            continue
        scope = preflight_scope(policy.key, invocation)
        relative = f"supervision/invocation-{invocation:06d}-worker-preflight-{policy.key}.json"
        packet, path, stopped = _supervise(batch, None, policy.key, input_root=input_root,
            guard_path=guard_path, deadline=deadline, max_disk_bytes=spec.operations.max_disk_bytes,
            preflight_scope=scope, receipt_relative=relative)
        ready = False
        if packet and packet.get("contract") == "policy-preflight-v1":
            ready = verify_policy_preflight(packet, policy, batch, budget.snapshot(scope=scope))
        entry = {"policy": policy.key, "scope": scope, "ready": ready, "stop_reason": stopped}
        if path.exists():
            entry.update(receipt=str(path), sha256=file_sha256(path))
            workers.append({"path": relative, "sha256": entry["sha256"]})
        entries.append(entry)
        if stopped or not ready:
            stopped = stopped or "live_preflight_failed"
            break
    return entries, workers, stopped


def verify_lineage(payload: dict, spec: StudySpec, location, budget: ProviderBudget, records: list[dict]) -> bool:
    """Bind every dispatch to that invocation's smoke, allowance and prior rows."""
    from research.policy_runner import verify_policy_preflight
    from research.working_studies import _planned
    cells = study_cells(spec)
    assignments = {cell["cell_key"]: cell for cell in cells}
    prior = {key: _planned(spec, cell["seed"], cell["arm"], policy_cell=cell) for key, cell in assignments.items()}
    scopes = {key: [cell["policy"]] for key, cell in assignments.items()}
    policies = [policy for policy in spec.policy_design.policies if policy.behavior.family == "live_llm"]
    all_ready, previous_sequence = True, 0
    for number, record in enumerate(records, 1):
        end = record["end"]
        current = _read(location.report_file(end["report"]["path"]))
        final = end["status"] == "finalized"
        if (current["contract"] != (RESULT if final else PROGRESS)
                or current["batch"] != payload["batch"] or current["status"] != end["status"]
                or current["operations"]["supervision"] != {"contract": SUPERVISION, "invocation": number}):
            raise ValueError("policy supervision report identity changed")
        verify_receipt(current["provider_budget"], payload["batch"], budget, locate=location.locate,
            at_head=number == len(records), sealed=final)
        entries = current["preflight"]
        if not isinstance(entries, list) or len(entries) > len(policies):
            raise ValueError("invalid invocation preflight assignment")
        ready = len(entries) == len(policies)
        referenced = {}
        for index, entry in enumerate(entries):
            policy = policies[index]
            scope = preflight_scope(policy.key, number)
            scopes[scope] = [policy.key]
            relative = f"supervision/invocation-{number:06d}-worker-preflight-{policy.key}.json"
            path = location.data_file(relative)
            checked = False
            if entry["policy"] != policy.key or entry["scope"] != scope or type(entry["ready"]) is not bool:
                raise ValueError("invocation preflight identity changed")
            if "receipt" in entry:
                if location.locate(entry["receipt"]) != path or file_sha256(path) != entry["sha256"]:
                    raise ValueError("invocation preflight receipt changed")
                packet = _read(path)
                referenced[relative] = entry["sha256"]
                if packet.get("contract") == "policy-preflight-v1":
                    checked = verify_policy_preflight(packet, policy, payload["batch"], budget.snapshot(scope=scope))
                elif (packet.get("contract") != "policy-worker-failure-v1" or packet.get("cell") is not None
                        or packet.get("policy") != policy.key or packet.get("manifest_sha256") != payload["batch"]["manifest_sha256"]):
                    raise ValueError("invocation preflight failure changed")
            elif path.exists():
                raise ValueError("invocation preflight receipt was omitted")
            if checked != entry["ready"]:
                raise ValueError("invocation preflight readiness changed")
            if not checked or entry["stop_reason"]:
                ready = False
                if index != len(entries) - 1:
                    raise ValueError("preflight was dispatched after invocation stopped")
        attempted = end["attempted_cells"]
        remaining = [cell["cell_key"] for cell in cells if prior[cell["cell_key"]]["execution_status"] in {"planned", "paused"}]
        if (not isinstance(attempted, list) or len(set(attempted)) != len(attempted)
                or attempted != remaining[:len(attempted)] or attempted and not ready):
            raise ValueError("policy worlds were dispatched without verified preflight")
        sequence = current["provider_budget"]["checkpoint"]["last_sequence"]
        admitted = {key: [assignments[key]["policy"]] for key in attempted}
        admitted.update({entry["scope"]: [entry["policy"]] for entry in entries})
        if any(admitted.get(key) != bindings for key, bindings in budget.scope_bindings(after=previous_sequence, through=sequence).items()):
            raise ValueError("provider usage occurred outside its supervised invocation")
        previous_sequence = sequence
        if len(current["results"]) != len(cells):
            raise ValueError("policy invocation omitted assigned cells")
        for cell, row in zip(cells, current["results"]):
            key = cell["cell_key"]
            if (digest_json(row.get("policy_cell")) != digest_json(cell)
                    or digest_json({key: row.get(key) for key in cell}) != digest_json(cell)):
                raise ValueError("policy invocation changed cell assignment")
            if key in attempted:
                if prior[key]["execution_status"] not in {"planned", "paused"}:
                    raise ValueError("completed policy cell was dispatched again")
                relative = f"supervision/invocation-{number:06d}-worker-{key}.json"
                path = location.data_file(relative)
                if path.exists():
                    worker = _read(path)
                    referenced[relative] = file_sha256(path)
                    if digest_json({k: v for k, v in worker.items() if k != "eligibility"}) != digest_json(
                            {k: v for k, v in row.items() if k != "eligibility"}):
                        raise ValueError("policy invocation differs from its worker")
                    checkpoint = worker["provider_budget_checkpoint"]
                    if checkpoint["last_sequence"] > current["provider_budget"]["checkpoint"]["last_sequence"]:
                        raise ValueError("policy worker accounting is after its invocation")
                    budget.verify_checkpoint(checkpoint)
                elif row["execution_status"] != "failed" or row["eligibility"]["status"] != "ineligible":
                    raise ValueError("missing policy worker was presented as a valid result")
            elif digest_json({k: v for k, v in prior[key].items() if k != "eligibility"}) != digest_json(
                    {k: v for k, v in row.items() if k != "eligibility"}):
                raise ValueError("policy cell changed without a supervised worker")
            if row["eligibility"] != prior[key]["eligibility"] and key not in attempted and row["eligibility"]["status"] != "ineligible":
                raise ValueError("policy eligibility was promoted without execution")
            prior[key] = row
        if referenced != {ref["path"]: ref["sha256"] for ref in end["workers"]}:
            raise ValueError("policy supervision omitted or added worker evidence")
        all_ready = all_ready and ready
    if any(scopes.get(key) != bindings for key, bindings in budget.scope_bindings().items()):
        raise ValueError("provider usage leaves its supervised assignment")
    return all_ready

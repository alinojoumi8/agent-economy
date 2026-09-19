"""Durable physical-call accounting for the opt-in typed capability."""
from pathlib import Path
import math

from llm.completion_guard import BudgetExceeded
from llm.decisions import decision_hash
from research.provider_budget import (
    GatewayBinding, GatewayTarget, ProviderBudget, ProviderBudgetContract,
    TokenTariff, gateway_config_identity,
)


def typed_targets(config):
    policy = config["llm"]["decision_policy"]
    return sorted({(route["provider"], route["model"])
                   for route in (policy.get("primary"), policy.get("escalation"))
                   if route and route["provider"] not in {"scripted", "mock"}})


def tariffs_for(config, targets, pricing):
    tariffs = []
    for provider, model in targets:
        price = pricing.get(model)
        if not price or any(type(price.get(k)) not in {int, float}
                            or not math.isfinite(price[k]) or price[k] < 0 for k in ("in", "out")):
            raise ValueError("each typed route requires finite declared input/output pricing")
        tariffs.append(TokenTariff(provider=provider, model=model,
            max_input_tokens=32768, max_output_tokens=8192,
            input_nano_usd_per_token=math.ceil(price["in"] * 1000),
            output_nano_usd_per_token=math.ceil(price["out"] * 1000)))
    return tuple(tariffs)


def open_run_budget(store, config, pricing):
    """Open the original allowance; missing evidence never replenishes it."""
    targets = typed_targets(config)
    if not targets:
        return None
    cap = config.get("budget", {}).get("cap_usd", 5)
    if type(cap) not in {int, float} or not math.isfinite(cap) or cap <= 0:
        raise BudgetExceeded("typed calls require a positive finite run budget")
    identity = gateway_config_identity(config)
    meta = store.get_meta()
    contract = ProviderBudgetContract(protocol_version="typed-provider-budget-v1",
        study_manifest_sha256=decision_hash({"run": meta["run_id"] if meta else "uninitialized", "config": identity}),
        gateway_bindings=(GatewayBinding(key="typed", config_sha256=identity,
            targets=tuple(GatewayTarget(provider=p, model=m) for p, m in targets)),),
        max_provider_calls=100000, max_tokens=1000000000,
        max_spend_nano_usd=max(1, math.floor(cap * 1000000000)),
        tariffs=tariffs_for(config, targets, pricing))
    path = Path(store.path).absolute().with_suffix(".jev-budget.db")
    witness = path.with_suffix(".json")
    encoded = contract.model_dump_json()
    if path.exists():
        if not witness.is_file() or witness.read_text(encoding="utf-8") != encoded:
            raise BudgetExceeded("typed budget binding is missing or changed")
        return ProviderBudget(path, contract, scope="run", binding_key="typed")
    if witness.exists() or store.scalar("SELECT COUNT(*) FROM llm_calls WHERE provider NOT IN ('scripted','mock')"):
        raise BudgetExceeded("original typed budget ledger is missing; refusing a new allowance")
    with witness.open("x", encoding="utf-8") as stream:
        stream.write(encoded)
    return ProviderBudget.create(path, contract, scope="run", binding_key="typed")

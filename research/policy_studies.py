"""Executable policy identities and explicit world/model replication axes."""
from __future__ import annotations

import argparse
from decimal import Decimal, ROUND_FLOOR
import json
from pathlib import Path

from llm.readiness import validate_llm_config
from research.artifacts import digest_json, file_sha256, publish_json
from research.provider_budget import (
    GatewayBinding, GatewayTarget, ProviderBudgetContract, TokenTariff,
    gateway_config_identity,
)
from research.studies import BehaviorContract, StudyPolicy, StudySpec, reject_inline_secrets

ROOT = Path(__file__).resolve().parents[1]
WAKE_CONTRACT = "Role/event wake rules from the frozen common runtime and configuration"
COMMUNICATION_CONTRACT = "Conversation and news rules from the frozen common runtime and configuration"
ASSIGNMENT_CONTRACT = "One declared decision policy for all runtime-routed roles"


def prompt_source_identity() -> str:
    # All remaining source, config, persona construction and replay inputs are
    # also bound by the enclosing prospective manifest's code identity.
    return digest_json({name: file_sha256(ROOT / name) for name in (
        "agents/prompts.py", "agents/runtime.py", "agents/policies.py", "llm/gateway.py")})


def declare_policy(key: str, llm: dict, *, temperature: float | None,
                   repair_temperature: float = .2) -> StudyPolicy:
    """Build a declaration from a direct single-model routing configuration."""
    reject_inline_secrets(llm)
    if not isinstance(llm, dict) or not isinstance(llm.get("default_route"), dict) or not isinstance(llm.get("providers", {}), dict):
        raise ValueError("policy requires a route and provider configuration mapping")
    route = llm.get("default_route", {})
    provider, model = route.get("provider"), route.get("model")
    if not isinstance(provider, str) or not isinstance(model, str):
        raise ValueError("policy route requires provider and model identifiers")
    scripted = provider == model == "scripted"
    settings = llm.get("providers", {}).get(provider, {})
    if not isinstance(settings, dict):
        raise ValueError("provider settings must be a mapping")
    endpoint = ("https://api.anthropic.com/v1" if settings.get("kind") == "anthropic"
                else settings.get("base_url"))
    return StudyPolicy(key=key, llm=json.loads(json.dumps(llm)),
        behavior=BehaviorContract(
            family="scripted" if scripted else "live_llm", version="agent-runtime-fixed-primary-v1",
            prompt_sha256=None if scripted else prompt_source_identity(),
            provider_reference=None if scripted else provider, model_reference=None if scripted else model,
            endpoint_reference=None if scripted else endpoint, temperature=temperature,
            wake_cadence=WAKE_CONTRACT, communication_policy=COMMUNICATION_CONTRACT,
            population_assignment=ASSIGNMENT_CONTRACT),
        sampling_contract="fixed-primary-and-repair-v1", repair_temperature=repair_temperature,
        preflight_temperature=0.0, observation_action_contract="shared-runtime-observation-action-v1")


def policy_configurations(spec: StudySpec, config: dict, *, verify_source: bool = True) -> dict[str, dict]:
    """Resolve every declared policy before launch without credentials or calls.

    Policy variants replace only gateway routing/sampling. Economic parameters,
    observations, feasible actions and scheduling remain common and source-bound.
    The common Governor keeps its initial cadence; the shared operational ledger
    stops dispatch instead of silently reducing cognitive effort as money runs low.
    """
    if spec.policy_design is None:
        raise ValueError("policy configuration requires research-study-v3")
    if config.get("providers"):
        raise ValueError("policy providers must be declared inside each policy's llm configuration")
    tariffs = {(item.provider, item.model): item for item in spec.policy_design.tariffs}
    configurations = {}
    for policy in spec.policy_design.policies:
        behavior = policy.behavior
        declared = declare_policy(policy.key, policy.llm, temperature=behavior.temperature,
                                  repair_temperature=policy.repair_temperature)
        if not verify_source:
            # Historical evidence binds its original prompt hash; reading it
            # must not require today's source to be the source that executed it.
            declared = declared.model_copy(update={"behavior": declared.behavior.model_copy(
                update={"prompt_sha256": behavior.prompt_sha256})})
        if declared != policy:
            raise ValueError("decision policy differs from its executable source or declared routing")
        llm = policy.llm
        allowed = {"default_route", "routes", "providers", "provider_retries", "rate_limit_backoff_s",
                   "max_in_flight", "concurrency", "logical_deadline_s"}
        if set(llm) - allowed:
            raise ValueError("policy must declare direct single-model routing without hidden overrides")
        route = llm.get("default_route", {})
        if set(route) != {"provider", "model"}:
            raise ValueError("policy default route must bind its provider and model")
        if not isinstance(llm.get("routes", {}), dict) or any(
                item != route for item in llm.get("routes", {}).values()):
            raise ValueError("every routed role must use the declared policy model")
        scripted = behavior.family == "scripted"
        providers = llm.get("providers", {})
        if (providers if scripted else set(providers) != {behavior.provider_reference}):
            raise ValueError("configure exactly the provider declared by this decision policy")
        if not scripted:
            provider = providers[behavior.provider_reference]
            if provider.get("kind") not in {"openai_compat", "anthropic"}:
                raise ValueError("policy study requires a direct HTTP provider")
            if provider.get("request_defaults") or provider.get("max_tokens_field", "max_tokens") not in {"max_tokens", "max_completion_tokens"}:
                raise ValueError("policy provider must preserve the declared request and token limits")
        resolved = json.loads(json.dumps(config))
        resolved["llm"] = json.loads(json.dumps(llm))
        resolved.setdefault("budget", {})["cap_usd"] = None
        if not scripted:
            tariff = tariffs[(behavior.provider_reference, behavior.model_reference)]
            resolved["llm"]["live_only"] = True
            resolved["llm"]["research_response_contract"] = "required-json-v1"
            resolved["llm"]["research_sampling"] = {
                "primary": behavior.temperature, "repair": policy.repair_temperature,
                "preflight": policy.preflight_temperature}
            resolved["llm"]["pricing"] = {behavior.model_reference: {
                "in": tariff.input_nano_usd_per_token / 1000,
                "out": tariff.output_nano_usd_per_token / 1000,
                "cache": tariff.input_nano_usd_per_token / 1000}}
        report = validate_llm_config(resolved, require_secrets=False, raise_on_error=False)
        if not report["ready"]:
            raise ValueError("declared decision policy configuration is not ready")
        configurations[policy.key] = resolved
    baseline = next(arm for arm in spec.arms if arm.role == "baseline")
    for arm in spec.arms:
        if arm.role == "treatment" and not arm.changes.shocks and configurations[arm.policy] == configurations[baseline.policy]:
            raise ValueError("policy-only treatment must change the executable decision configuration")
    return configurations


def study_cells(spec: StudySpec) -> list[dict]:
    """Labels identify model draws; they never replace or perturb world seeds."""
    if spec.policy_design is None:
        raise ValueError("replicated assignments require a policy study")
    return [{"seed": seed, "model_replicate": replicate, "arm": arm.key,
             "policy": arm.policy, "cell_key": digest_json({
                 "seed": seed, "model_replicate": replicate, "arm": arm.key})[:24]}
            for seed in spec.randomness.seeds
            for replicate in spec.randomness.model_replicates for arm in spec.arms]


def provider_budget_contract(spec: StudySpec, config: dict, *, manifest_sha256: str,
                             verify_source: bool = True) -> ProviderBudgetContract:
    configurations = policy_configurations(spec, config, verify_source=verify_source)
    return ProviderBudgetContract(
        protocol_version="research-provider-budget-v2", study_manifest_sha256=manifest_sha256,
        max_provider_calls=spec.operations.max_provider_calls, max_tokens=spec.operations.max_tokens,
        max_spend_nano_usd=int((Decimal(str(spec.operations.max_spend_usd)) * 1_000_000_000).to_integral_value(rounding=ROUND_FLOOR)),
        tariffs=tuple(spec.policy_design.tariffs),
        gateway_bindings=tuple(GatewayBinding(key=policy.key,
            config_sha256=gateway_config_identity(configurations[policy.key]),
            targets=() if policy.behavior.family == "scripted" else (GatewayTarget(
                provider=policy.behavior.provider_reference, model=policy.behavior.model_reference),))
            for policy in spec.policy_design.policies))


def draft_policy_comparison(config: dict, *, policies: list[StudyPolicy], tariffs: list[TokenTariff],
                            seeds: list[int], model_replicates: list[str], horizon: int,
                            max_provider_calls: int, max_tokens: int, max_spend_usd: float,
                            max_wall_seconds: int = 300, max_disk_bytes: int = 128 * 1024 * 1024) -> StudySpec:
    from research.price_catalog import draft_price_study

    if not 2 <= len(policies) <= 16:
        raise ValueError("a policy comparison requires two to sixteen policies")
    # The template defines economic measurements. Per-policy routing is resolved
    # below; the common world may have originally been used with a live model.
    template = {**config, "llm": {"default_route": {"provider": "scripted", "model": "scripted"}, "routes": {}}}
    base = draft_price_study(template, "G2", seeds=seeds, horizon=horizon, intervention_tick=1)
    raw = base.model_dump(mode="json")
    raw["model"]["resolved_config_sha256"] = digest_json(config)
    raw.update(protocol_version="research-study-v3", key="decision-policy-price-comparison",
        title="Decision policies and goods/equity price discovery",
        hypothesis="Changing the declared decision policy changes executed goods and equity prices and quantities.",
        behavior=policies[0].behavior.model_dump(mode="json"),
        policy_design={"policies": [item.model_dump(mode="json") for item in policies],
            "tariffs": [item.model_dump(mode="json") for item in tariffs],
            "replicate_aggregation": "complete-paired-block-mean-v1",
            "execution_governor": "fixed-cadence-under-shared-budget-v1"},
        arms=[{"key": policy.key, "label": policy.key, "role": "baseline" if index == 0 else "treatment",
               "changes": {}, "policy": policy.key,
               "information_policy": "Common frozen observations, action menus and information access"}
              for index, policy in enumerate(policies)])
    raw["randomness"]["model_replicates"] = model_replicates
    raw["analysis"]["uncertainty"] = "paired_replicated_world_bootstrap"
    raw["analysis"]["multiple_outcome_policy"] = "descriptive_only"
    for outcome in raw["analysis"]["outcomes"]:
        outcome["purpose"] = "primary" if outcome["key"] in {"goods_price", "equity_price"} else "exploratory"
    raw["analysis"]["estimand"] = "Mean policy difference across independent worlds after averaging complete paired model replicates within each world"
    raw["operations"].update(mode="live", max_provider_calls=max_provider_calls, max_tokens=max_tokens,
        max_spend_usd=max_spend_usd, max_wall_seconds=max_wall_seconds, max_disk_bytes=max_disk_bytes)
    raw["limitations"] = [item for item in raw["limitations"] if "existing scripted policy" not in item]
    raw["limitations"] += [
        "Model replicate labels identify fresh stochastic draws; they do not assert deterministic provider seeds.",
        "An incomplete paired replication block excludes that world for the affected outcome; model calls are not independent economies.",
        "The common Governor retains initial cadence; a shared completion ledger stops dispatch instead of degrading the policy."]
    spec = StudySpec.model_validate(raw)
    policy_configurations(spec, config)
    return spec


def main() -> int:
    """Draft an immutable, reviewable study without contacting any provider."""
    from run_config import load_config

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--design", type=Path, required=True,
                        help="JSON object with policies (key, llm, temperature, optional repair_temperature) and tariffs")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", type=int, nargs="+", required=True)
    parser.add_argument("--model-replicates", nargs="+", required=True)
    parser.add_argument("--ticks", type=int, required=True)
    parser.add_argument("--max-provider-calls", type=int, required=True)
    parser.add_argument("--max-tokens", type=int, required=True)
    parser.add_argument("--max-spend-usd", type=float, required=True)
    parser.add_argument("--max-wall-seconds", type=int, default=300)
    parser.add_argument("--max-disk-bytes", type=int, default=128 * 1024 * 1024)
    args = parser.parse_args()
    try:
        if args.design.stat().st_size > 1024 * 1024:
            raise ValueError("policy design exceeds the size limit")
        design = json.loads(args.design.read_text(encoding="utf-8"))
        if not isinstance(design, dict) or set(design) != {"policies", "tariffs"}:
            raise ValueError("design must contain exactly policies and tariffs")
        spec = draft_policy_comparison(load_config(args.config),
            policies=[declare_policy(**policy) for policy in design["policies"]],
            tariffs=[TokenTariff.model_validate(tariff) for tariff in design["tariffs"]],
            seeds=args.seeds, model_replicates=args.model_replicates, horizon=args.ticks,
            max_provider_calls=args.max_provider_calls, max_tokens=args.max_tokens,
            max_spend_usd=args.max_spend_usd, max_wall_seconds=args.max_wall_seconds,
            max_disk_bytes=args.max_disk_bytes)
        from research.policy_runner import validate_policy_execution
        validate_policy_execution(spec, load_config(args.config))
        publish_json(args.output, spec.model_dump(mode="json"))
        print(json.dumps({"draft": str(args.output.resolve()), "assigned_cells": len(study_cells(spec)),
                          "executed": False, "provider_calls": 0}))
        return 0
    except (ValueError, TypeError, KeyError, OSError):
        print(json.dumps({"status": "invalid", "reason": "invalid policy draft or unavailable output"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

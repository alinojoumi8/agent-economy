"""LLM configuration validation and secret-safe readiness reporting."""
from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from .cache_config import normalize_prompt_cache_mode


BUILTIN_PROVIDERS = {"scripted", "mock"}
NETWORK_PROVIDER_KINDS = {"openai_compat", "anthropic"}
KNOWN_PROVIDER_KINDS = NETWORK_PROVIDER_KINDS | {"cli"}
PROMPT_CACHE_MODES = {
    "off", "provider_automatic", "openai_key", "anthropic_ephemeral",
}
PROMPT_CACHE_MODES_BY_KIND = {
    "openai_compat": {"off", "provider_automatic", "openai_key"},
    "anthropic": {"off", "anthropic_ephemeral"},
    "cli": {"off"},
}


class ProviderConfigurationError(RuntimeError):
    """Raised before a run when its provider routing cannot work as configured."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("LLM configuration is not ready: " + "; ".join(errors))


def validate_llm_config(
    config: dict[str, Any], *, environ: Mapping[str, str] | None = None,
    require_secrets: bool = True, raise_on_error: bool = True,
) -> dict[str, Any]:
    """Validate every routed provider without ever returning a credential value.

    Scripted/mock runs stay keyless. Network providers must be declared, carry a
    model on every route, and reference a populated environment variable before
    the world is constructed. This prevents the historical silent fallback from
    a misspelled provider to scripted behavior.
    """
    env = os.environ if environ is None else environ
    llm = config.get("llm", {}) or {}
    providers = llm.get("providers", {}) or {}
    routes = llm.get("routes", {}) or {}
    default_route = llm.get(
        "default_route", {"provider": "scripted", "model": "scripted"}) or {}
    route_contract = llm.get("route_contract")

    route_items = [("default", default_route), *sorted(routes.items())]
    referenced: dict[str, set[str]] = {}
    errors: list[str] = []
    warnings: list[str] = []

    for route_name, route in route_items:
        if not isinstance(route, dict):
            errors.append(f"route '{route_name}' must be a mapping")
            continue
        provider = str(route.get("provider", "")).strip()
        model = str(route.get("model", "")).strip()
        if not provider:
            errors.append(f"route '{route_name}' has no provider")
            continue
        if not model:
            errors.append(f"route '{route_name}' has no model")
        referenced.setdefault(provider, set()).add(model)

    contract_report: dict[str, Any] = {"enforced": False}
    if route_contract is not None:
        if not isinstance(route_contract, dict):
            errors.append("llm.route_contract must be a mapping")
        else:
            raw_contract_provider = route_contract.get("provider")
            raw_contract_model = route_contract.get("model")
            contract_provider = (
                raw_contract_provider.strip()
                if isinstance(raw_contract_provider, str)
                else ""
            )
            contract_model = (
                raw_contract_model.strip()
                if isinstance(raw_contract_model, str)
                else ""
            )
            complete_contract = bool(contract_provider and contract_model)
            contract_report = {
                "enforced": complete_contract,
                "provider": contract_provider or None,
                "model": contract_model or None,
                "scope": "all_gateway_routes",
            }
            if not contract_provider:
                errors.append("llm.route_contract has no provider")
            if not contract_model:
                errors.append("llm.route_contract has no model")
            if complete_contract:
                for route_name, route in route_items:
                    if not isinstance(route, dict):
                        continue
                    actual = (
                        str(route.get("provider", "")).strip(),
                        str(route.get("model", "")).strip(),
                    )
                    if actual != (contract_provider, contract_model):
                        errors.append(
                            f"route '{route_name}' violates llm.route_contract; "
                            f"expected {contract_provider}/{contract_model}")

    provider_rows: list[dict[str, Any]] = []
    for provider in sorted(referenced):
        models = sorted(m for m in referenced[provider] if m)
        if provider in BUILTIN_PROVIDERS:
            provider_rows.append({
                "name": provider, "kind": provider, "models": models,
                "key_required": False, "key_present": True, "configured": True,
            })
            continue

        pcfg = providers.get(provider)
        if not isinstance(pcfg, dict):
            errors.append(f"routed provider '{provider}' is not declared in llm.providers")
            provider_rows.append({
                "name": provider, "kind": None, "models": models,
                "key_required": True, "key_present": False, "configured": False,
            })
            continue

        kind = str(pcfg.get("kind", "")).strip()
        key_env = str(pcfg.get("api_key_env", "")).strip()
        base_url = str(pcfg.get("base_url", "")).strip()
        prompt_cache_mode = normalize_prompt_cache_mode(
            pcfg.get("prompt_cache_mode"),
            legacy_prompt_cache_key=bool(pcfg.get("prompt_cache_key")))
        key_required = kind in NETWORK_PROVIDER_KINDS
        key_value = str(env.get(key_env, "")).strip() if key_env else ""
        key_present = bool(key_value)

        if kind not in KNOWN_PROVIDER_KINDS:
            errors.append(f"provider '{provider}' has unknown kind '{kind or '<empty>'}'")
        if prompt_cache_mode not in PROMPT_CACHE_MODES:
            errors.append(
                f"provider '{provider}' has unknown prompt_cache_mode "
                f"'{prompt_cache_mode or '<empty>'}'")
        elif kind in PROMPT_CACHE_MODES_BY_KIND and prompt_cache_mode not in PROMPT_CACHE_MODES_BY_KIND[kind]:
            allowed = ", ".join(sorted(PROMPT_CACHE_MODES_BY_KIND[kind]))
            errors.append(
                f"provider '{provider}' kind '{kind}' does not support "
                f"prompt_cache_mode '{prompt_cache_mode}' (allowed: {allowed})")
        if kind == "openai_compat" and not base_url:
            errors.append(f"provider '{provider}' requires base_url")
        if key_required and not key_env:
            errors.append(f"provider '{provider}' requires api_key_env")
        elif key_required and require_secrets and not key_present:
            errors.append(f"provider '{provider}' is missing environment variable {key_env}")

        # Kimi Code membership keys and Moonshot pay-as-you-go keys use
        # different services. Catch the otherwise opaque 401 before startup
        # without returning or logging any part of the credential.
        if key_value.lower().startswith("sk-kimi-"):
            expected_base = "https://api.kimi.com/coding/v1"
            if base_url.rstrip("/") != expected_base:
                errors.append(
                    f"provider '{provider}' uses a Kimi Code key and must use "
                    f"base_url {expected_base}")
            invalid_models = [m for m in models
                              if m not in {"kimi-for-coding", "kimi-for-coding-highspeed"}]
            if invalid_models:
                errors.append(
                    f"provider '{provider}' uses a Kimi Code key and must route "
                    "to model kimi-for-coding (or kimi-for-coding-highspeed)")

        if key_value.lower().startswith("sk-cp-"):
            expected_base = "https://api.minimax.io/v1"
            if base_url.rstrip("/") != expected_base:
                errors.append(
                    f"provider '{provider}' uses a MiniMax Token Plan key and "
                    f"must use base_url {expected_base}")

        provider_rows.append({
            "name": provider, "kind": kind or None, "models": models,
            "base_url": base_url or None, "key_env": key_env or None,
            "key_required": key_required, "key_present": key_present,
            "configured": True, "prompt_cache_mode": prompt_cache_mode,
        })

    for provider in sorted(set(providers) - set(referenced)):
        warnings.append(f"provider '{provider}' is configured but not used by any route")

    cli_routes = [name for name, route in route_items
                  if isinstance(route, dict)
                  and providers.get(route.get("provider"), {}).get("kind") == "cli"]
    forbidden_cli = [
        name for name in cli_routes if name not in {"oracle_plan", "oracle", "dev"}]
    if forbidden_cli:
        errors.append(
            "CLI providers may only serve oracle_plan/oracle/dev routes: "
            + ", ".join(forbidden_cli))

    mode = "offline" if set(referenced).issubset(BUILTIN_PROVIDERS) else "network"
    report = {
        "ready": not errors,
        "mode": mode,
        "routed_providers": sorted(referenced),
        "providers": provider_rows,
        "route_contract": contract_report,
        "errors": errors,
        "warnings": warnings,
    }
    if errors and raise_on_error:
        raise ProviderConfigurationError(errors)
    return report

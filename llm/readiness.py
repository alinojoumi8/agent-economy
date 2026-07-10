"""LLM configuration validation and secret-safe readiness reporting."""
from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any


BUILTIN_PROVIDERS = {"scripted", "mock"}
NETWORK_PROVIDER_KINDS = {"openai_compat", "anthropic"}
KNOWN_PROVIDER_KINDS = NETWORK_PROVIDER_KINDS | {"cli"}


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
        key_required = kind in NETWORK_PROVIDER_KINDS
        key_value = str(env.get(key_env, "")).strip() if key_env else ""
        key_present = bool(key_value)

        if kind not in KNOWN_PROVIDER_KINDS:
            errors.append(f"provider '{provider}' has unknown kind '{kind or '<empty>'}'")
        if kind == "openai_compat" and not base_url:
            errors.append(f"provider '{provider}' requires base_url")
        if key_required and not key_env:
            errors.append(f"provider '{provider}' requires api_key_env")
        elif key_required and require_secrets and not key_present:
            errors.append(f"provider '{provider}' is missing environment variable {key_env}")

        normalized_base = base_url.rstrip("/")
        kimi_code_base = "https://api.kimi.com/coding/v1"
        kimi_platform_base = "https://api.moonshot.ai/v1"

        # Service/model compatibility is knowable without inspecting a secret.
        # Kimi Code exposes stable membership aliases; K2.6 is an API Platform
        # model and cannot be selected through the membership endpoint.
        if normalized_base == kimi_code_base:
            invalid_models = [m for m in models
                              if m not in {"kimi-for-coding", "kimi-for-coding-highspeed"}]
            if invalid_models:
                errors.append(
                    f"provider '{provider}' uses the Kimi Code endpoint and must route "
                    "to model kimi-for-coding (or kimi-for-coding-highspeed)")
        if "kimi-k2.6" in models and normalized_base != kimi_platform_base:
            errors.append(
                f"provider '{provider}' routes kimi-k2.6 and must use "
                f"base_url {kimi_platform_base}")

        # Kimi Code membership keys and Moonshot pay-as-you-go keys use
        # different services. Catch the otherwise opaque 401 before startup
        # without returning or logging any part of the credential.
        if key_value.lower().startswith("sk-kimi-"):
            expected_base = kimi_code_base
            if normalized_base != expected_base:
                errors.append(
                    f"provider '{provider}' uses a Kimi Code key and must use "
                    f"base_url {expected_base}")

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
            "configured": True,
        })

    for provider in sorted(set(providers) - set(referenced)):
        warnings.append(f"provider '{provider}' is configured but not used by any route")

    cli_routes = [name for name, route in route_items
                  if isinstance(route, dict)
                  and providers.get(route.get("provider"), {}).get("kind") == "cli"]
    forbidden_cli = [name for name in cli_routes if name not in {"oracle", "dev"}]
    if forbidden_cli:
        errors.append("CLI providers may only serve oracle/dev routes: " + ", ".join(forbidden_cli))

    mode = "offline" if set(referenced).issubset(BUILTIN_PROVIDERS) else "network"
    report = {
        "ready": not errors,
        "mode": mode,
        "routed_providers": sorted(referenced),
        "providers": provider_rows,
        "errors": errors,
        "warnings": warnings,
    }
    if errors and raise_on_error:
        raise ProviderConfigurationError(errors)
    return report

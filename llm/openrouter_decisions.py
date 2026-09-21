"""OpenRouter's Alpha Decisions transport; no chat conversion or internal retries."""
from __future__ import annotations

import json
import os
from urllib.parse import urlsplit

from .adapters import Adapter, AdapterHTTPError, AdapterResult, AdapterTimeoutError, _retry_after_seconds
from .decisions import MAX_RESPONSE_BYTES, canonical_json, finite_number, validate_evaluation


ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
PINNED_MODEL = "typesafe/jev-1.13"
DEFAULT_RESOLVED_MODELS = (PINNED_MODEL, "typesafe/jev-1.13-20260917")


def validate_endpoint(endpoint: str) -> None:
    """Allow the published service or an explicitly configured local test server."""
    parsed = urlsplit(endpoint)
    local = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "::1", "localhost"}
    if (parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path != "/api/alpha/decisions"
            or not (endpoint == ENDPOINT or local)):
        raise ValueError("Decisions endpoint must be OpenRouter or a loopback test service at /api/alpha/decisions")


class OpenRouterDecisionsAdapter(Adapter):
    name = "openrouter_decisions"

    def __init__(self, config: dict):
        self.endpoint = str(config.get("endpoint", ENDPOINT))
        validate_endpoint(self.endpoint)
        self.api_key_env = str(config.get("api_key_env", "OPENROUTER_API_KEY"))
        self.timeout = float(config.get("timeout_s", 30.0))
        configured_models = config.get("resolved_models", DEFAULT_RESOLVED_MODELS)
        if not isinstance(configured_models, (list, tuple)):
            raise ValueError("resolved_models must be an explicit list")
        self.expected_models = tuple(configured_models)
        self.expected_provider = str(config.get("upstream_provider", "TypeSafe"))
        if not self.expected_models or any(not isinstance(item, str) or not item for item in self.expected_models):
            raise ValueError("Decisions requires an explicit resolved-model allowlist")

    async def healthcheck(self, model: str) -> dict:
        # The ordinary chat-model catalog excludes Decisions models. The gateway
        # owns the accounted typed smoke call; a catalog lookup cannot prove this.
        return {"ok": True, "model": model, "live": False,
                "capability": "decisions", "authentication_checked": False,
                "contract_check_required": True}

    async def complete(self, model, messages, *, purpose="", context=None, max_tokens=700,
                       temperature=0.7, cache_key="") -> AdapterResult:
        import httpx

        evaluation = (context or {}).get("_evaluation")
        from agents.decision_domains import TYPED_PURPOSES
        if evaluation is None or purpose not in TYPED_PURPOSES:
            raise ValueError("OpenRouter Decisions requires a typed evaluation purpose")
        evaluation = validate_evaluation(evaluation)
        key = os.environ.get(self.api_key_env, "").strip()
        if not key:
            raise PermissionError(f"missing environment variable {self.api_key_env}")
        body = {"model": model, **evaluation, "provider": {"allow_fallbacks": False}}
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
                response = await client.post(self.endpoint, json=body, headers={
                    "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
                if not 200 <= response.status_code < 300:
                    # Remote messages can echo authorization. Never include the
                    # response body, request headers or a redirect location.
                    raise AdapterHTTPError(response.status_code, self.endpoint,
                        "Decisions request rejected", retry_after_s=_retry_after_seconds(
                            response.headers.get("Retry-After")))
                if len(response.content) > MAX_RESPONSE_BYTES:
                    raise ValueError("Decisions response exceeds the recorded evidence limit")
                data = response.json()
        except httpx.TimeoutException:
            raise AdapterTimeoutError(self.endpoint, self.timeout) from None
        except httpx.RequestError:
            raise OSError("OpenRouter Decisions transport failed") from None
        except json.JSONDecodeError:
            raise ValueError("OpenRouter Decisions returned invalid JSON") from None
        if not isinstance(data, dict):
            raise ValueError("OpenRouter Decisions returned a non-object response")
        # Drop undeclared provider fields before persistence. Keep typed answers
        # in text (bounded above), which replay preserves without log truncation.
        retained = {k: data[k] for k in ("answers", "model", "provider", "id", "usage") if k in data}
        usage = data.get("usage") or {}
        valid_usage = isinstance(usage, dict) and all(
            type(usage.get(k)) is int and 0 <= usage[k] <= 2**31 - 1
            for k in ("input_tokens", "output_tokens"))
        cost = usage.get("cost") if isinstance(usage, dict) else None
        # Answer validation happens after metering, so a billable malformed answer
        # remains accounted and cannot trigger a generative JSON repair.
        return AdapterResult(text=canonical_json(retained).replace(key, "[REDACTED]"),
            in_tokens=usage["input_tokens"] if valid_usage else 0,
            out_tokens=usage["output_tokens"] if valid_usage else 0,
            reported_usage=(usage["input_tokens"], usage["output_tokens"]) if valid_usage else None,
            reported_cost_usd=float(cost) if finite_number(cost, 0, 1_000_000) else None,
            raw={"contract": "openrouter-alpha-decisions-v1",
                 "cost_basis": "provider_reported" if cost is not None else "declared_tariff"})

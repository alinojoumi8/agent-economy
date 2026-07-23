"""Real-provider acceptance probe for Semantics 11 routing.

The probe never installs scripted or mock routes. It performs one live JSON
contract call per provider, drives the configured provider pools concurrently,
and verifies timeout and rate-limit fallback using a real live fallback model.
Use ``--allow-missing`` only for a clearly labelled partial diagnostic.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.store import Store
from llm.gateway import Gateway, LLMRequest
from llm.readiness import validate_llm_config
from run_config import load_config


SCHEMA_HINT = '{"reasoning":"","actions":[]}'
SYSTEM_PROMPT = "Return only valid JSON with top-level reasoning and actions keys."
USER_PROMPT = (
    'Return {"reasoning":"live provider probe",'
    '"actions":[{"type":"do_nothing"}]}.'
)


def _route_targets(route: Any) -> list[dict[str, Any]]:
    if not isinstance(route, dict):
        return []
    if "primary" in route or "fallback" in route:
        return [
            target for target in (route.get("primary"), route.get("fallback"))
            if isinstance(target, dict)
        ]
    return [route]


def _configured_target(config: dict, provider: str) -> dict[str, Any] | None:
    llm = config.get("llm", {})
    routes: list[Any] = [llm.get("default_route")]
    routes.extend((llm.get("routes") or {}).values())
    routes.extend((llm.get("tier_routes") or {}).values())
    routes.extend((llm.get("premium_routes") or {}).values())
    for route in routes:
        for target in _route_targets(route):
            if str(target.get("provider")) == provider:
                return copy.deepcopy(target)
    return None


def _filter_route(route: Any, available: set[str]) -> dict[str, Any] | None:
    if not isinstance(route, dict):
        return None
    if "primary" not in route and "fallback" not in route:
        return copy.deepcopy(route) if str(route.get("provider")) in available else None
    primary = route.get("primary")
    if not isinstance(primary, dict) or str(primary.get("provider")) not in available:
        return None
    filtered: dict[str, Any] = {"primary": copy.deepcopy(primary)}
    fallback = route.get("fallback")
    if isinstance(fallback, dict) and str(fallback.get("provider")) in available:
        filtered["fallback"] = copy.deepcopy(fallback)
    return filtered


def _probe_config(config: dict, available: set[str]) -> dict:
    probe = copy.deepcopy(config)
    llm = probe["llm"]
    llm["providers"] = {
        name: value for name, value in llm.get("providers", {}).items()
        if name in available
    }
    llm["routes"] = {
        name: filtered
        for name, route in (llm.get("routes") or {}).items()
        if (filtered := _filter_route(route, available)) is not None
    }
    llm["tier_routes"] = {
        name: filtered
        for name, route in (llm.get("tier_routes") or {}).items()
        if (filtered := _filter_route(route, available)) is not None
    }
    llm["premium_routes"] = {
        name: filtered
        for name, route in (llm.get("premium_routes") or {}).items()
        if (filtered := _filter_route(route, available)) is not None
    }
    default = _filter_route(llm.get("default_route"), available)
    if default is None:
        candidates = [
            route for group in (llm["tier_routes"], llm["premium_routes"])
            for route in group.values()
        ]
        if not candidates:
            raise RuntimeError("no live route remains after provider filtering")
        default = copy.deepcopy(candidates[0].get("primary", candidates[0]))
    llm["default_route"] = default.get("primary", default)
    llm["live_only"] = True
    llm["provider_retries"] = 0
    probe["budget"]["cap_usd"] = None
    return probe


def _request_specs(config: dict) -> list[tuple[str, str, str, int]]:
    """Return role, purpose, tier, count without duplicating one provider lane."""
    llm = config["llm"]
    candidates = [
        ("citizen", "decision", "local", (llm.get("tier_routes") or {}).get("local")),
        ("citizen", "decision", "flash", (llm.get("tier_routes") or {}).get("flash")),
        ("central_banker", "decision", "premium",
         (llm.get("tier_routes") or {}).get("premium")),
        ("founder", "decision", "premium",
         (llm.get("premium_routes") or {}).get("founder")),
    ]
    specs: list[tuple[str, str, str, int]] = []
    seen_providers: set[str] = set()
    for role, purpose, tier, route in candidates:
        if not isinstance(route, dict):
            continue
        primary = route.get("primary", route)
        provider = str(primary.get("provider", ""))
        if not provider or provider in seen_providers:
            continue
        seen_providers.add(provider)
        capacity = int(llm["providers"][provider].get("concurrency", 1))
        specs.append((role, purpose, tier, max(1, capacity)))
    return specs


def _insert_requests(store: Store, config: dict) -> list[LLMRequest]:
    requests: list[LLMRequest] = []
    sequence = 0
    for role, purpose, tier, count in _request_specs(config):
        for _ in range(count):
            sequence += 1
            agent_id = store.insert(
                "agents", name=f"Live Probe {sequence}",
                kind="staff" if role == "central_banker" else "citizen",
                role=None if role == "citizen" else role,
                occupation=role, age=35, alive=1, model_tier=tier,
            )
            requests.append(LLMRequest(
                role=role, purpose=purpose, agent_id=agent_id, tick=1,
                max_tokens=256, temperature=0.0,
                system=SYSTEM_PROMPT, user=USER_PROMPT,
            ))
    return requests


async def _run_concurrency_probe(config: dict) -> dict[str, Any]:
    store = Store(":memory:")
    store.init_run_meta("live-concurrency-probe", int(config.get("seed", 42)), config)
    gateway = Gateway(store, config)
    try:
        preflight = await gateway.preflight(live=True)
        requests = _insert_requests(store, config)
        results = await asyncio.gather(*(
            gateway.complete(request, schema_hint=SCHEMA_HINT)
            for request in requests
        ), return_exceptions=True)
        failures = [
            {"index": index, "error_type": type(result).__name__, "error": str(result)[:300]}
            for index, result in enumerate(results)
            if isinstance(result, BaseException)
        ]
        successes = [result for result in results if not isinstance(result, BaseException)]
        runtime = gateway.runtime_status()
        return {
            "preflight": {
                "ready": bool(preflight.get("ready")),
                "live_ready": bool(preflight.get("live_ready")),
                "checks": preflight.get("checks", []),
            },
            "requested": len(requests),
            "succeeded": len(successes),
            "failures": failures,
            "calls_by_provider": {
                str(row["provider"]): int(row["n"])
                for row in store.query(
                    "SELECT provider,COUNT(*) n FROM llm_calls GROUP BY provider")
            },
            "attempt_outcomes": {
                str(row["outcome"]): int(row["n"])
                for row in store.query(
                    "SELECT outcome,COUNT(*) n FROM llm_attempts GROUP BY outcome")
            },
            "runtime": runtime,
        }
    finally:
        gateway.close()
        store.close()


async def _fault_server(mode: str):
    handlers: set[asyncio.Task] = set()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            handlers.add(task)
        try:
            await reader.readuntil(b"\r\n\r\n")
            if mode == "timeout":
                await asyncio.sleep(5.0)
            else:
                body = b'{"error":{"message":"injected rate limit"}}'
                writer.write(
                    b"HTTP/1.1 429 Too Many Requests\r\n"
                    b"Content-Type: application/json\r\n"
                    b"Retry-After: 60\r\n"
                    + f"Content-Length: {len(body)}\r\n".encode("ascii")
                    + b"Connection: close\r\n\r\n" + body
                )
                await writer.drain()
        except (asyncio.CancelledError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
            if task is not None:
                handlers.discard(task)

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = int(server.sockets[0].getsockname()[1])
    return server, handlers, port


async def _run_fault_probe(base: dict, available: set[str], mode: str) -> dict[str, Any]:
    preferred = next(
        (name for name in ("deepseek", "ollama", "minimax", "kimi") if name in available),
        None,
    )
    if preferred is None:
        raise RuntimeError("fault probe requires at least one real live provider")
    fallback = _configured_target(base, preferred)
    if fallback is None:
        raise RuntimeError(f"no configured model found for live fallback {preferred}")
    server, handlers, port = await _fault_server(mode)
    fault_name = f"faulted_{mode}"
    config = copy.deepcopy(base)
    llm = config["llm"]
    llm["providers"] = {
        fault_name: {
            "kind": "openai_compat",
            "base_url": f"http://127.0.0.1:{port}/v1",
            "auth": "none",
            "concurrency": 1,
            "timeout_s": 1,
            "healthcheck_path": "/models",
            "prompt_cache_mode": "off",
            "max_tokens_field": "max_tokens",
            "request_defaults": {"stream": False},
        },
        preferred: copy.deepcopy(llm["providers"][preferred]),
    }
    primary = {"provider": fault_name, "model": f"injected-{mode}", "timeout_s": 1}
    llm["default_route"] = primary
    llm["routes"] = {}
    llm["tier_routes"] = {
        "local": {"primary": primary, "fallback": fallback},
    }
    llm["premium_routes"] = {}
    llm["role_tiers"] = {"citizen": "local"}
    llm["live_only"] = True
    llm["provider_retries"] = 0
    config["budget"]["cap_usd"] = None

    store = Store(":memory:")
    store.init_run_meta(f"live-{mode}-fallback-probe", int(config.get("seed", 42)), config)
    agent_id = store.insert(
        "agents", name=f"{mode.title()} Fallback Citizen", kind="citizen",
        occupation="worker", age=35, alive=1, model_tier="local")
    gateway = Gateway(store, config)
    try:
        response = await gateway.complete(LLMRequest(
            role="citizen", purpose="decision", agent_id=agent_id, tick=1,
            max_tokens=256, temperature=0.0,
            system=SYSTEM_PROMPT, user=USER_PROMPT,
        ), schema_hint=SCHEMA_HINT)
        attempts = [dict(row) for row in store.query(
            "SELECT provider,model,outcome,rate_limited,fallback_used,llm_call_id "
            "FROM llm_attempts ORDER BY id")]
        runtime = gateway.runtime_status()
        return {
            "mode": mode,
            "ok": bool(response.ok),
            "final_provider": response.provider,
            "final_model": response.model,
            "attempts": attempts,
            "cooldown_active": any(
                float(row["cooldown_remaining_s"]) > 0
                for row in runtime["providers"] if row["provider"] == fault_name
            ),
        }
    finally:
        gateway.close()
        store.close()
        server.close()
        await server.wait_closed()
        for task in list(handlers):
            task.cancel()
        if handlers:
            await asyncio.gather(*handlers, return_exceptions=True)


async def _execute(config: dict, available: set[str], full_scope: bool) -> dict[str, Any]:
    probe_config = _probe_config(config, available)
    concurrency = await _run_concurrency_probe(probe_config)
    timeout = await _run_fault_probe(config, available, "timeout")
    rate_limit = await _run_fault_probe(config, available, "rate_limit")
    peak = int(concurrency["runtime"]["global"]["peak_in_flight"])
    checks = {
        "provider_preflight": bool(
            concurrency["preflight"]["ready"]
            and concurrency["preflight"]["live_ready"]),
        "all_concurrent_calls_succeeded": (
            concurrency["requested"] == concurrency["succeeded"]
            and not concurrency["failures"]),
        "peak_concurrency_at_least_10": peak >= 10,
        "timeout_used_real_fallback": bool(
            timeout["ok"] and timeout["attempts"]
            and timeout["attempts"][0]["outcome"] == "timeout"
            and timeout["attempts"][-1]["fallback_used"] == 1),
        "rate_limit_used_real_fallback": bool(
            rate_limit["ok"] and rate_limit["attempts"]
            and rate_limit["attempts"][0]["outcome"] == "rate_limited"
            and rate_limit["attempts"][0]["rate_limited"] == 1
            and rate_limit["attempts"][-1]["fallback_used"] == 1
            and rate_limit["cooldown_active"]),
    }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "full" if full_scope else "partial_missing_providers",
        "available_providers": sorted(available),
        "checks": checks,
        "passed": all(checks.values()) and full_scope,
        "partial_checks_passed": all(checks.values()),
        "concurrency": concurrency,
        "timeout_fallback": timeout,
        "rate_limit_fallback": rate_limit,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "runs" / "evolving-live.yaml"))
    parser.add_argument(
        "--allow-missing", action="store_true",
        help="Run a labelled partial diagnostic with currently configured providers.")
    parser.add_argument("--output", help="Optional JSON report path.")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    config = load_config(args.config)
    readiness = validate_llm_config(
        config, require_secrets=True, raise_on_error=False)
    available = {
        str(row["name"]) for row in readiness["providers"]
        if bool(row.get("configured"))
        and (not bool(row.get("key_required")) or bool(row.get("key_present")))
    }
    referenced = set(readiness["routed_providers"])
    missing = sorted(referenced - available)
    if missing and not args.allow_missing:
        raise SystemExit(
            "live cognition probe requires all routed providers; missing: "
            + ", ".join(missing))
    if not available:
        raise SystemExit("no real live provider is configured")

    report = asyncio.run(_execute(
        config, referenced & available, full_scope=not missing))
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if report["passed"]:
        return
    if args.allow_missing and report["partial_checks_passed"]:
        return
    raise SystemExit(1)


if __name__ == "__main__":
    main()

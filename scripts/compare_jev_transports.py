"""Small, isolated transport comparison; never opens a world or launches agents.

Inputs are one to four preserved typed evaluation JSON files. Without --execute,
only a plan is saved. Output directories must be new; interrupted runs cannot be
resumed or retried by this command. Each route receives a separate $0.025 ledger.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
from engine.store import Store
from llm.decisions import validate_evaluation
from llm.gateway import Gateway, LLMRequest
from llm.readiness import validate_llm_config


def config(route):
    direct = route == "direct"
    model = "jev-1.13.0" if direct else "typesafe/jev-1.13"
    return {
        "engine_semantics_version": 16,
        "budget": {"cap_usd": 0.025, "oracle_reserve_usd": 0},
        "llm": {
            "default_route": {"provider": "scripted", "model": "scripted"},
            "provider_retries": 0,
            "max_in_flight": 1,
            "providers": {
                route: {
                    "kind": "typesafe_decisions" if direct else "openrouter_decisions",
                    "api_key_env": "TYPESAFE_API_KEY"
                    if direct
                    else "OPENROUTER_API_KEY",
                    "timeout_s": 20,
                    "concurrency": 1,
                }
            },
            "pricing": {model: {"in": 0.042, "out": 0, "cache": 0.042}},
            "decision_policy": {
                "version": "bounded-economic-choice-v4",
                "primary": {"provider": route, "model": model, "timeout_s": 20},
            },
        },
    }


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)


async def compare(paths, output, *, execute=False):
    paths = [Path(p).resolve() for p in paths]
    if not 1 <= len(paths) <= 4 or len(set(paths)) != len(paths):
        raise ValueError("Supply one to four distinct preserved evaluation files")
    source_bytes = {p: p.read_bytes() for p in paths}
    inputs = [
        validate_evaluation(json.loads(source_bytes[p].decode("utf-8"))) for p in paths
    ]
    hashes = {str(p): hashlib.sha256(source_bytes[p]).hexdigest() for p in paths}
    configurations = {r: config(r) for r in ("direct", "openrouter")}
    for cfg in configurations.values():
        validate_llm_config(cfg, require_secrets=execute)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    schedule = [
        (i, route)
        for i in range(len(inputs))
        for route in (
            ("direct", "openrouter") if i % 2 == 0 else ("openrouter", "direct")
        )
    ]
    save(
        output / "plan.json",
        {
            "input_sha256": hashes,
            "code_sha256": {
                name: digest(Path(__file__).resolve().parents[1] / name)
                for name in (
                    "scripts/compare_jev_transports.py",
                    "llm/typesafe_decisions.py",
                    "llm/openrouter_decisions.py",
                    "llm/gateway.py",
                    "research/provider_budget.py",
                )
            },
            "configurations": configurations,
            "schedule": schedule,
            "max_calls": len(schedule),
            "total_cap_usd": 0.05,
            "automatic_retries": 0,
            "timeout_s": 20,
            "reserved_output_tokens_per_call": 2048,
            "execute": execute,
            "caveat": "Different pinned model identifiers; transport and model revision are confounded.",
        },
    )
    for i, path in enumerate(paths):
        with (output / f"input-{i}.json").open("xb") as stream:
            stream.write(source_bytes[path])
    if not execute:
        return {"status": "prepared_not_run", "calls": 0}
    gateways, stores = {}, {}
    records = []
    status = "complete"
    try:
        for route, cfg in configurations.items():
            store = Store(str(output / f"{route}.db"))
            stores[route] = store
            store.init_run_meta(f"transport-comparison-{route}", 1, cfg)
            gateways[route] = Gateway(store, cfg)
        for sequence, (i, route) in enumerate(schedule):
            if any(digest(p) != hashes[str(p)] for p in paths):
                raise ValueError("Preserved source changed; stopping before dispatch")
            started = datetime.now(timezone.utc).isoformat()
            save(
                output / f"attempt-{sequence}.json",
                {"input_index": i, "route": route, "started_utc": started},
            )
            clock = time.perf_counter()
            record = {
                "sequence": sequence,
                "input_index": i,
                "route": route,
                "started_utc": started,
            }
            try:
                result = await gateways[route].evaluate(
                    LLMRequest(
                        role="citizen", purpose="decision", tick=i + 1, max_tokens=2048
                    ),
                    inputs[i],
                )
                record.update(status="success", response=asdict(result))
            except Exception as exc:
                # Gateway already redacts provider errors. No automatic retry or
                # continuation after a potentially billable ambiguous result.
                record.update(
                    status="stopped_error",
                    error_type=type(exc).__name__,
                    error=str(exc),
                    accounting_requires_inspection=True,
                )
                status = "stopped_error"
            record["elapsed_s"] = time.perf_counter() - clock
            save(output / f"result-{sequence}.json", record)
            records.append(record)
            if status != "complete":
                break
    finally:
        for gateway in gateways.values():
            gateway.close()
        for store in stores.values():
            store.close()
        unchanged = all(digest(p) == hashes[str(p)] for p in paths)
        save(
            output / "preservation.json",
            {
                "source_unchanged": unchanged,
                "before": hashes,
                "after": {str(p): digest(p) for p in paths},
            },
        )
    summary = {
        "status": status,
        "source_unchanged": unchanged,
        "attempted": len(records),
        "planned": len(schedule),
        "records": records,
    }
    save(output / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.env_file:
        if not args.env_file.is_file():
            parser.error("Explicit env file does not exist")
        load_dotenv(args.env_file, override=False)
    result = asyncio.run(compare(args.input, args.out, execute=args.execute))
    print(json.dumps({k: v for k, v in result.items() if k != "records"}))
    return 0 if result["status"] in {"complete", "prepared_not_run"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

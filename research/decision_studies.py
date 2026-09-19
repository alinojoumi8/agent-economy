"""Prospective bounded-choice experiments, separate from historical v3 studies.

Prepare freezes source/config/menu identities without inference. Execute consumes
one exclusive allowance and retains every assigned cell, including exclusions.
Interrupted experiments are intentionally non-resumable; their allowance and
partial records remain evidence and are never reset by this command.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import statistics
import time

from agents.decision_candidates import COMPILER_VERSIONS, DecisionMenu
from agents.typed_policy import TypedDecisionPolicy
from engine.store import Store
from llm.decision_budget import tariffs_for, typed_targets
from llm.decision_config import decision_policy
from llm.decisions import canonical_json, decision_hash, validate_evaluation
from llm.gateway import DEFAULT_PRICING, Gateway, LLMRequest
from llm.readiness import validate_llm_config
from research.artifacts import code_identity, file_sha256, publish_json, safe_key
from research.metric_registry import read_metric_observation
from research.provider_budget import (GatewayBinding, GatewayTarget, ProviderBudget,
    ProviderBudgetContract, gateway_config_identity)
from run import open_run, replay_headless
from run_config import load_config
from world.replay_verify import verify_replay

PROTOCOL = "bounded-decision-study-v1"
METRICS = ("unemployment", "gdp_proxy", "cpi", "gini", "sentiment")


def frozen_menu(record):
    compiler = COMPILER_VERSIONS.get(record.get("contract"))
    if compiler is None or record.get("compiler") != compiler:
        raise ValueError("frozen record uses another compiler or policy")
    menu = DecisionMenu(record["observation_hash"], canonical_json(record["candidates"]),
        canonical_json(validate_evaluation(record["evaluation"])), record["baseline_choice"],
        compiler_version=compiler)
    if menu.menu_hash != record["menu_hash"]:
        raise ValueError("frozen candidate menu identity changed")
    criteria = menu.evaluation["questions"]["action"]["criteria"]
    if criteria != {c["id"]: {"actions": c["actions"], **c["facts"]} for c in menu.candidates}:
        raise ValueError("frozen questions differ from executable candidates")
    menu.actions_for(menu.baseline_choice)
    return menu


def freeze(database: Path, output: Path, limit: int = 2000):
    """Export only closed, committed typed observations; the source stays read-only."""
    if not 1 <= limit <= 100000:
        raise ValueError("snapshot limit must be between 1 and 100000")
    database = database.resolve()
    if any(Path(str(database) + suffix).exists() and Path(str(database) + suffix).stat().st_size
           for suffix in ("-wal", "-journal")):
        raise ValueError("close the source run before freezing observations")
    original = file_sha256(database)
    # Empty WAL files can remain after the existing Windows replay reader.
    # With no frames, immutable reads use only the hash-bound main database.
    conn = sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True, cached_statements=0)
    conn.row_factory = sqlite3.Row
    try:
        meta = dict(conn.execute("SELECT * FROM run_meta LIMIT 1").fetchone())
        records, exclusions = [], Counter()
        for row in conn.execute("SELECT payload_json FROM events WHERE kind='typed_decision' AND tick<=? ORDER BY tick,id", (meta["tick"],)):
            receipt = json.loads(row[0])
            if receipt["status"] == "outside_menu":
                exclusions[receipt["reason"]] += 1
                continue
            frozen_menu(receipt)
            record = {key: receipt[key] for key in ("contract", "compiler", "agent_id", "tick",
                "observation_hash", "menu_hash", "candidates", "evaluation", "baseline_choice")}
            record["id"] = decision_hash({"source": original, "actor": record["agent_id"], "tick": record["tick"]})
            # All observations of one actor in one seed stay in the same split.
            group = decision_hash({"seed": meta["seed"], "actor": record["agent_id"]})
            record["split"] = "calibration" if int(group[:8], 16) % 5 == 0 else "held_out"
            record["label_choice"] = None  # Never treat baseline agreement as truth.
            records.append(record)
    finally:
        conn.close()
    if file_sha256(database) != original:
        raise ValueError("source changed while freezing observations")
    records.sort(key=lambda item: item["id"])
    payload = {"protocol": PROTOCOL, "source_sha256": original,
        "source_seed": meta["seed"], "eligible_records": len(records),
        "exclusions": dict(exclusions), "records": records[:limit]}
    publish_json(output, {**payload, "sha256": decision_hash(payload)})
    return payload


def read_snapshots(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    digest = value.pop("sha256")
    if decision_hash(value) != digest or value.get("protocol") != PROTOCOL:
        raise ValueError("frozen observation seal is invalid")
    ids = set()
    for record in value["records"]:
        menu = frozen_menu(record)
        if record["id"] in ids or record["split"] not in {"calibration", "held_out"}:
            raise ValueError("frozen record IDs/splits must be distinct and valid")
        ids.add(record["id"])
        if record["label_choice"] is not None:
            menu.actions_for(record["label_choice"])
    return value


def label_snapshots(snapshots, labels, output, definition):
    value = read_snapshots(snapshots)
    assignments = json.loads(Path(labels).read_text(encoding="utf-8"))
    ids = {record["id"] for record in value["records"]}
    if not isinstance(assignments, dict) or set(assignments) - ids or not definition.strip():
        raise ValueError("labels require known snapshot IDs and an explicit adjudication definition")
    for record in value["records"]:
        if record["id"] in assignments:
            frozen_menu(record).actions_for(assignments[record["id"]])
            record["label_choice"] = assignments[record["id"]]
    value["label_source_sha256"] = file_sha256(labels)
    value["label_definition"] = definition[:2000]
    publish_json(output, {**value, "sha256": decision_hash(value)})


def _background(config):
    value = deepcopy(config)
    value.pop("extends", None)
    value.pop("seed", None)
    for key in ("primary", "escalation", "on_abstain", "minimum_confidence"):
        value["llm"]["decision_policy"].pop(key, None)
    for key in ("providers", "pricing"):
        value["llm"].pop(key, None)
    # Bind used background providers too; unused experiment targets do not
    # alter world observations or background cognition.
    for route in [config["llm"].get("default_route", {}), *config["llm"].get("routes", {}).values()]:
        provider = route.get("provider")
        if provider not in {None, "scripted", "mock"}:
            raise ValueError("initial typed studies require the same scripted background in every arm")
    if any(config["llm"].get(key) for key in ("tier_routes", "premium_routes", "citizen_model_cohorts")):
        raise ValueError("typed pilot arms require explicitly matched non-cohort background routing")
    return value


def prepare(configs: dict, output: Path, *, seeds=(1, 2), ticks=3,
            snapshots=None, max_calls=10000, max_usd=30.0, wall_seconds=3600):
    if not 2 <= len(configs) <= 4 or any(safe_key(k) != k for k in configs):
        raise ValueError("declare two to four named policy arms")
    if (not seeds or len(seeds) > 100 or len(set(seeds)) != len(seeds)
            or any(type(seed) is not int or not 0 <= seed < 2**31 for seed in seeds)
            or type(ticks) is not int or not 1 <= ticks <= 365
            or type(wall_seconds) is not int or not 1 <= wall_seconds <= 86400
            or type(max_usd) not in {int, float} or not 0 < max_usd <= 10000):
        raise ValueError("study seeds, ticks and budgets must be finite and bounded")
    prepared, tariffs, bindings = {}, {}, []
    background = None
    for key, original in configs.items():
        config = deepcopy(original)
        config.setdefault("budget", {}).update(cap_usd=float(max_usd), oracle_reserve_usd=0.0)
        policy = decision_policy(config)
        if policy is None or policy["population_fraction"] != 1:
            raise ValueError("matched study arms require a complete eligible population declaration")
        validate_llm_config(config, require_secrets=False)
        candidate = _background(config)
        if background is not None and candidate != background:
            raise ValueError("matched arms differ in world, background or candidate-menu configuration")
        background = candidate
        prepared[key] = config
        targets = typed_targets(config)
        for tariff in tariffs_for(config, targets, {**DEFAULT_PRICING, **config["llm"].get("pricing", {})}):
            identity = (tariff.provider, tariff.model)
            if identity in tariffs and tariffs[identity] != tariff:
                raise ValueError("a shared provider/model cannot have conflicting tariffs")
            tariffs[identity] = tariff
        bindings.append(GatewayBinding(key=key, config_sha256=gateway_config_identity(config),
            targets=tuple(GatewayTarget(provider=p, model=m) for p, m in targets)))
    inputs = read_snapshots(snapshots) if snapshots else None
    if inputs and any(r["contract"] != policy["version"] for r in inputs["records"]):
        raise ValueError("frozen observations and study policy versions differ")
    manifest = {"protocol": PROTOCOL, "compiler": COMPILER_VERSIONS[policy["version"]], "policy": policy["version"],
        "source": code_identity(), "configs": prepared, "seeds": list(seeds), "ticks": ticks,
        "wall_seconds": wall_seconds, "snapshots": inputs,
        "metrics": list(METRICS), "limits": {"max_calls": max_calls, "max_usd": max_usd},
        "cells": [{"arm": arm, "seed": seed, "key": f"{arm}-{seed}"}
                  for seed in seeds for arm in prepared],
        "interpretation": "Exploratory paired worlds; actors are not independent replicates"}
    identity = decision_hash(manifest)
    contract = ProviderBudgetContract(protocol_version="typed-provider-budget-v1",
        study_manifest_sha256=identity, gateway_bindings=tuple(bindings),
        max_provider_calls=max_calls, max_tokens=1000000000,
        max_spend_nano_usd=round(max_usd * 1000000000), tariffs=tuple(tariffs.values())) if tariffs else None
    output.mkdir(parents=True, exist_ok=False)
    publish_json(output / "manifest.json", {**manifest, "sha256": identity})
    if contract:
        publish_json(output / "budget-contract.json", contract.model_dump(mode="json"))
    return identity


def read_manifest(root):
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    identity = manifest.pop("sha256")
    if manifest.get("protocol") != PROTOCOL or decision_hash(manifest) != identity:
        raise ValueError("prospective study manifest changed")
    if manifest["source"] != code_identity():
        raise ValueError("source changed since preparation; prepare a new prospective study")
    return manifest, identity


def expected_contract(manifest, identity):
    tariffs, bindings = {}, []
    for arm, config in manifest["configs"].items():
        targets = typed_targets(config)
        for tariff in tariffs_for(config, targets, {**DEFAULT_PRICING, **config["llm"].get("pricing", {})}):
            tariffs[(tariff.provider, tariff.model)] = tariff
        bindings.append(GatewayBinding(key=arm, config_sha256=gateway_config_identity(config),
            targets=tuple(GatewayTarget(provider=p, model=m) for p, m in targets)))
    return ProviderBudgetContract(protocol_version="typed-provider-budget-v1",
        study_manifest_sha256=identity, gateway_bindings=tuple(bindings),
        max_provider_calls=manifest["limits"]["max_calls"], max_tokens=1000000000,
        max_spend_nano_usd=round(manifest["limits"]["max_usd"] * 1000000000),
        tariffs=tuple(tariffs.values())) if tariffs else None


def _guard(root, contract, scope, arm):
    return ProviderBudget(root / "provider-budget.db", contract, scope=scope, binding_key=arm) if contract else None


def _percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))] if ordered else None


def summarize_frozen(rows):
    summaries = {}
    for arm in sorted({row["arm"] for row in rows}):
        for split in ("calibration", "held_out"):
            group = [r for r in rows if r["arm"] == arm and r["split"] == split]
            valid = [r for r in group if r["status"] == "complete"]
            labelled = [r for r in valid if r["label_agreement"] is not None and r["confidence"] is not None]
            bins = []
            for lower in range(10):
                items = [r for r in labelled if min(9, int(r["confidence"] * 10)) == lower]
                if items:
                    bins.append({"lower": lower / 10, "n": len(items),
                        "mean_confidence": statistics.fmean(r["confidence"] for r in items),
                        "label_agreement": statistics.fmean(r["label_agreement"] for r in items)})
            summaries[f"{arm}:{split}"] = {"assigned": len(group), "valid": len(valid),
                "failures": len(group) - len(valid), "labelled_with_confidence": len(labelled),
                "baseline_agreement": statistics.fmean(r["baseline_agreement"] for r in valid) if valid else None,
                "call_cost_usd": sum(r.get("cost_usd", 0) for r in group),
                "latency_p50_ms": _percentile([r["latency_ms"] for r in valid], .5),
                "latency_p95_ms": _percentile([r["latency_ms"] for r in valid], .95),
                "abstentions": sum(r.get("selection_status") == "abstained" for r in valid),
                "escalations": sum(r.get("escalated", False) for r in valid),
                "calibration_bins": bins,
                "ece_against_labels": sum(b["n"] * abs(b["mean_confidence"] - b["label_agreement"])
                    for b in bins) / len(labelled) if labelled else None,
                "brier_against_labels": statistics.fmean((r["confidence"] - r["label_agreement"])**2
                    for r in labelled) if labelled else None}
    return summaries


def paired_summary(cells, manifest):
    baseline = next(iter(manifest["configs"]))
    results = []
    for arm in list(manifest["configs"])[1:]:
        for metric in METRICS:
            differences, excluded = [], []
            for seed in manifest["seeds"]:
                pair = [next((r for r in cells if r["seed"] == seed and r["arm"] == a), {})
                        for a in (baseline, arm)]
                points = [r.get("metrics", {}).get(metric, {}) for r in pair]
                if (all(r.get("status") == "complete" and r.get("replay_exact") for r in pair)
                        and all(p.get("status") == "available" for p in points)
                        and points[0].get("currency") == points[1].get("currency")):
                    differences.append({"seed": seed, "difference": points[1]["value"] - points[0]["value"]})
                else:
                    excluded.append(seed)
            values = [d["difference"] for d in differences]
            results.append({"baseline": baseline, "arm": arm, "metric": metric,
                "paired_differences": differences, "excluded_seeds": excluded,
                "mean_difference": statistics.fmean(values) if values else None,
                "standard_error": statistics.stdev(values) / len(values)**.5 if len(values) > 1 else None})
    return results


async def execute(root: Path, *, approve_live=False):
    root = root.resolve()
    manifest, identity = read_manifest(root)
    contract_path = root / "budget-contract.json"
    contract = ProviderBudgetContract.model_validate_json(contract_path.read_text()) if contract_path.exists() else None
    if contract != expected_contract(manifest, identity):
        raise ValueError("original provider budget contract is missing or changed")
    if contract and (not approve_live or contract.study_manifest_sha256 != identity):
        raise ValueError("live inference requires --approve-live and the original bound allowance")
    for config in manifest["configs"].values():
        validate_llm_config(config, require_secrets=bool(contract))
    # Exclusive ownership; crash/relaunch never grants a second allowance.
    with (root / "execution-started.json").open("x", encoding="utf-8") as stream:
        stream.write(canonical_json({"manifest_sha256": identity}))
    if contract:
        ProviderBudget.create(root / "provider-budget.db", contract, scope="supervisor",
            binding_key=next(iter(manifest["configs"])))
    started = time.monotonic()
    cells, frozen = [], []
    stopped = None
    try:
        for arm, config in manifest["configs"].items():
            records = (manifest["snapshots"] or {}).get("records", [])
            if not records:
                continue
            store = Store(str(root / f"frozen-{arm}.db"))
            store.init_run_meta(f"frozen-{arm}", 0, config)
            gateway = Gateway(store, config, completion_guard=_guard(root, contract, f"frozen-{arm}", arm))
            policy = TypedDecisionPolicy(gateway, config)
            try:
                for record in records:
                    row = {"arm": arm, "id": record["id"], "split": record["split"], "status": "excluded"}
                    frozen.append(row)
                    if stopped or time.monotonic() - started >= manifest["wall_seconds"]:
                        stopped = stopped or "wall_budget"
                        row["reason"] = stopped
                        continue
                    try:
                        result = await asyncio.wait_for(policy.complete(LLMRequest(role="citizen",
                            purpose="decision", tick=record["tick"]), frozen_menu(record)),
                            timeout=max(.01, manifest["wall_seconds"] - (time.monotonic() - started)))
                        receipt = result.receipt
                        choice = receipt["selected_candidate"]
                        row.update(status="complete", choice=choice, confidence=receipt["confidence"],
                            selection_status=receipt["status"], escalated=receipt["escalated"],
                            baseline_agreement=int(choice == record["baseline_choice"]),
                            label_agreement=None if record["label_choice"] is None else int(choice == record["label_choice"]),
                            latency_ms=sum(c["latency_ms"] for c in receipt["calls"]),
                            cost_usd=sum(c["cost_usd"] for c in receipt["calls"]), calls=receipt["calls"])
                    except Exception as exc:
                        row.update(status="failed", reason=type(exc).__name__)
                        stopped = "frozen_evaluation_failed"
                    publish_json(root / f"frozen-{arm}-{record['id']}.json", row)
            finally:
                gateway.close()
                store.close()
        for assignment in manifest["cells"]:
            row = {**assignment, "status": "excluded", "replay_exact": False}
            cells.append(row)
            if stopped or time.monotonic() - started >= manifest["wall_seconds"]:
                stopped = stopped or "wall_budget"
                row["reason"] = stopped
                continue
            directory = root / assignment["key"]
            config = deepcopy(manifest["configs"][assignment["arm"]])
            config.update(seed=assignment["seed"], checkpoint_dir=str(directory / "checkpoints"),
                          report_dir=str(directory / "reports"))
            world = None
            try:
                store, world, run_id = open_run(config, None, None, data_dir=directory,
                    completion_guard=_guard(root, contract, assignment["key"], assignment["arm"]))
                async def advance():
                    for _ in range(manifest["ticks"]):
                        step = await world.step()
                        if step.get("paused") or step.get("interrupted"):
                            raise RuntimeError("world paused before its assigned horizon")
                await asyncio.wait_for(advance(), max(.01, manifest["wall_seconds"] - (time.monotonic() - started)))
                reconciled, diagnostic = world.economy.ledger.reconcile()
                if not reconciled:
                    raise ValueError("world ledger did not reconcile")
                row["metrics"] = {name: read_metric_observation(store, name, manifest["ticks"]) for name in METRICS}
                receipts = [json.loads(r[0]) for r in store.query("SELECT payload_json FROM events WHERE kind='typed_decision'")]
                row["coverage"] = dict(Counter(r["status"] for r in receipts))
                row["action_results"] = dict(Counter("accepted" if o["ok"] else "rejected" for r in receipts for o in r["outcomes"]))
                row["call_cost_usd"] = store.scalar("SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls")
                source_path = Path(store.path)
                world.close()
                world = None
                source_hash = file_sha256(source_path)
                replay_store, replay_world, _ = open_run({}, None, run_id, data_dir=directory)
                try:
                    await replay_headless(replay_world, manifest["ticks"])
                    proof = verify_replay(source_path, replay_store.path)
                    row["replay_exact"] = proof["exact"] and replay_world.gateway._live_dispatch_count == 0
                finally:
                    replay_world.close()
                if source_hash != file_sha256(source_path) or not row["replay_exact"]:
                    raise ValueError("paired world failed exact immutable-source replay")
                row.update(status="complete", source_sha256=source_hash, run_id=run_id)
            except Exception as exc:
                row.update(status="failed", reason=type(exc).__name__)
                stopped = "world_execution_failed"
            finally:
                if world is not None:
                    world.close()
            publish_json(root / f"cell-{assignment['key']}.json", row)
    finally:
        accounting = None
        if contract:
            guard = _guard(root, contract, "supervisor", next(iter(manifest["configs"])))
            accounting = guard.seal()
        # Include all assignments even after interruption, without invented zeroes.
        assigned = {r["key"] for r in cells}
        cells.extend({**a, "status": "excluded", "reason": stopped or "interrupted", "replay_exact": False}
                     for a in manifest["cells"] if a["key"] not in assigned)
        observed = {(r["arm"], r["id"]) for r in frozen}
        frozen.extend({"arm": arm, "id": r["id"], "split": r["split"], "status": "excluded",
                       "reason": stopped or "interrupted"}
                      for arm in manifest["configs"] for r in (manifest["snapshots"] or {}).get("records", [])
                      if (arm, r["id"]) not in observed)
        result = {"protocol": PROTOCOL, "manifest_sha256": identity,
            "status": "complete" if all(r["status"] == "complete" for r in cells + frozen) and not stopped else "incomplete",
            "cells": cells, "frozen": frozen, "frozen_summary": summarize_frozen(frozen),
            "paired_summary": paired_summary(cells, manifest), "provider_accounting": accounting,
            "limitations": ["Exploratory seed-level comparisons, not a production adoption verdict",
                "Confidence calibration requires independently adjudicated labels",
                "Worlds use identical scripted background cognition", "Interrupted studies cannot resume"]}
        publish_json(root / "result.json", {**result, "sha256": decision_hash(result)})
    return result


def main():
    from dotenv import load_dotenv
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    frozen = commands.add_parser("freeze")
    frozen.add_argument("--run", type=Path, required=True)
    frozen.add_argument("--out", type=Path, required=True)
    frozen.add_argument("--limit", type=int, default=2000)
    labelled = commands.add_parser("label")
    labelled.add_argument("--snapshots", type=Path, required=True)
    labelled.add_argument("--labels", type=Path, required=True)
    labelled.add_argument("--definition", required=True)
    labelled.add_argument("--out", type=Path, required=True)
    plan = commands.add_parser("prepare")
    plan.add_argument("--arm", action="append", required=True, help="name=profile.yaml; first is baseline")
    plan.add_argument("--out", type=Path, required=True)
    plan.add_argument("--snapshots", type=Path)
    plan.add_argument("--seeds", default="1,2")
    plan.add_argument("--ticks", type=int, default=3)
    plan.add_argument("--max-calls", type=int, default=10000)
    plan.add_argument("--max-usd", type=float, default=30)
    plan.add_argument("--wall-seconds", type=int, default=3600)
    run = commands.add_parser("execute")
    run.add_argument("study", type=Path)
    run.add_argument("--approve-live", action="store_true")
    args = parser.parse_args()
    if args.command == "freeze":
        value = freeze(args.run, args.out, args.limit)
        print(f"Frozen {len(value['records'])} observations; source unchanged.")
    elif args.command == "label":
        label_snapshots(args.snapshots, args.labels, args.out, args.definition)
        print(f"Saved separately labelled observations: {args.out}")
    elif args.command == "prepare":
        configs = {}
        for item in args.arm:
            key, path = item.split("=", 1)
            if key in configs:
                raise ValueError("duplicate arm name")
            configs[key] = load_config(Path(path))
        print(prepare(configs, args.out, seeds=tuple(int(v) for v in args.seeds.split(",")), ticks=args.ticks,
            snapshots=args.snapshots, max_calls=args.max_calls, max_usd=args.max_usd, wall_seconds=args.wall_seconds))
    else:
        result = asyncio.run(execute(args.study, approve_live=args.approve_live))
        print(f"Study {result['status']}: {args.study / 'result.json'}")
        return 0 if result["status"] == "complete" else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

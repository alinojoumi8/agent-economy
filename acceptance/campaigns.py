"""Resumable production campaigns for the remaining PRD-v1 acceptance gates."""
from __future__ import annotations

import argparse
import asyncio
import html
import json
import shutil
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from acceptance.evidence import (
    calibration_evidence,
    causal_phenomena_evidence,
    long_run_evidence,
    oracle_evidence,
    rumor_pilot_evidence,
)
from engine.store import Store
from experiments.harness import run_experiment
from reports.generate import generate_report
from run import load_config, provider_preflight
from world.loop import World


def load_campaign(path: str | Path) -> dict[str, Any]:
    spec_path = Path(path)
    with spec_path.open("r", encoding="utf-8") as handle:
        spec = yaml.safe_load(handle) or {}
    spec.setdefault("name", "v1-production")
    spec.setdefault("base_config", "runs/production.yaml")
    spec.setdefault("data_root", f"data/acceptance/{spec['name']}")
    spec.setdefault("report_dir", "reports/out")
    spec.setdefault("long_run", {})
    spec.setdefault("rumor", {})
    return spec


def _open_world(db: Path, run_id: str, config: dict, seed: int) -> tuple[Store, World]:
    if db.exists():
        store = Store(str(db))
        meta = store.get_meta()
        if str(meta["run_id"]) != run_id or int(meta["seed"]) != seed:
            store.close()
            raise RuntimeError(f"acceptance database metadata mismatch: {db}")
        if str(meta["status"]) == "running":
            interrupted_tick = int(meta["tick"])
            checkpoint = store.query_one(
                "SELECT tick, path FROM checkpoints ORDER BY tick DESC, id DESC LIMIT 1")
            store.close()
            if not checkpoint or not Path(str(checkpoint["path"])).exists():
                raise RuntimeError(
                    f"interrupted acceptance run at tick {interrupted_tick} has no checkpoint")
            checkpoint_path = Path(str(checkpoint["path"])).resolve()
            shutil.copy2(checkpoint_path, db)
            store = Store(str(db))
            store.set_meta(status="paused")
            store.log_event(
                int(checkpoint["tick"]), "acceptance_recovered", {
                    "interrupted_tick": interrupted_tick,
                    "checkpoint_tick": int(checkpoint["tick"]),
                    "checkpoint_path": str(checkpoint_path),
                }, phase="ACCEPTANCE", importance=2.0)
            store.commit()
            meta = store.get_meta()
        stored_config = json.loads(meta["config_json"])
        world = World(store, stored_config)
        world.restore_prng_state()
        return store, world

    store = Store(str(db))
    store.init_run_meta(run_id, seed, config)
    world = World(store, config)
    world.initialize()
    return store, world


async def _run_to(world: World, target_tick: int) -> None:
    remaining = max(0, target_tick - world.store.tick)
    if not remaining:
        return
    await world.run(max_ticks=remaining)
    if world.last_pause_reason:
        reason = world.last_pause_reason.get("reason", "provider")
        detail = str(world.last_pause_reason.get("detail", ""))[:500]
        raise RuntimeError(
            f"acceptance run paused at tick {world.store.tick}: {reason}: {detail}")
    if world.store.tick < target_tick:
        raise RuntimeError(
            f"acceptance run stopped at tick {world.store.tick}; expected {target_tick}")


def _seed_rate_probe(world: World, tick: int, bank_id: int, amount_cents: int) -> dict:
    existing = world.store.query_one(
        "SELECT payload_json FROM events WHERE kind='acceptance_rate_probe' "
        "ORDER BY id DESC LIMIT 1")
    if existing:
        return json.loads(existing["payload_json"])
    for row in world.store.query(
            "SELECT id FROM agents WHERE alive=1 AND kind='citizen' ORDER BY id"):
        actor_id = int(row["id"])
        result = world.runtime.executor.execute_action(tick, actor_id, {
            "type": "apply_loan", "bank_id": bank_id, "amount": amount_cents,
            "purpose": "acceptance policy-rate transmission probe",
        }, phase="ACCEPTANCE")
        if result.get("ok"):
            payload = {"actor_id": actor_id, "bank_id": bank_id,
                       "amount_cents": amount_cents, **result}
            world.store.log_event(
                tick, "acceptance_rate_probe", payload,
                phase="ACCEPTANCE", importance=1.0)
            world.store.commit()
            return payload
    raise RuntimeError("could not create an acceptance loan application")


async def _run_long_campaign(spec: dict, config: dict, root: Path) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    settings = spec["long_run"]
    seed = int(settings.get("seed", 42))
    target_ticks = int(settings.get("ticks", 365))
    max_spend = float(settings.get("max_spend_usd", 200.0))
    oracle_tick = int(settings.get("oracle_tick", 1))
    rate_probe_tick = int(settings.get("rate_probe_tick", 20))

    cfg = json.loads(json.dumps(config))
    cfg["seed"] = seed
    cfg["checkpoint_every"] = int(settings.get("checkpoint_every", 1))
    cfg["speed_delay_s"] = 0.0
    cfg["shocks"] = list(settings.get("shocks", []))
    run_id = f"{spec['name']}-long"
    db = root / "long_run.db"
    store, world = _open_world(db, run_id, cfg, seed)
    try:
        await _run_to(world, oracle_tick)
        existing_questions = {
            str(row["question"]) for row in store.query("SELECT question FROM predictions")}
        for question in settings.get("oracle_questions", []):
            if question in existing_questions:
                continue
            print(f"[acceptance] Oracle @ t{store.tick}: {question}", flush=True)
            await world.oracle.ask(str(question))
            store.commit()

        await _run_to(world, rate_probe_tick)
        _seed_rate_probe(
            world, rate_probe_tick,
            int(settings.get("rate_probe_bank_id", 1)),
            int(settings.get("rate_probe_amount_cents", 100_000)))
        await _run_to(world, target_ticks)
        report_path = generate_report(store, world, out_dir=spec["report_dir"])
        questions = len(settings.get("oracle_questions", []))
        return {
            "database": str(db),
            "report": report_path,
            "long_run": long_run_evidence(
                store, target_ticks=target_ticks, max_spend_usd=max_spend),
            "oracle": oracle_evidence(
                store, expected_questions=questions,
                max_p90_s=float(settings.get("oracle_max_p90_s", 60.0))),
            "calibration": calibration_evidence(
                store, minimum_predictions=int(
                    settings.get("minimum_resolved_predictions", questions))),
            "causal_phenomena": causal_phenomena_evidence(store),
        }
    finally:
        store.close()


def _run_rumor_campaign(spec: dict, config: dict, root: Path) -> dict:
    settings = spec["rumor"]
    name = f"{spec['name']}-rumor"
    shock_tick = int(settings.get("shock_tick", 4))
    ticks = int(settings.get("ticks", shock_tick + 9))
    experiment_spec = {
        "name": name,
        "config": config,
        "seeds": list(settings.get("seeds", [1, 2, 3, 4, 5])),
        "ticks": ticks,
        "control": True,
        "resume": True,
        "preflight_live": False,
        "shocks": [{
            "kind": "rumor", "trigger": "shock",
            "trigger_params": {"tick": shock_tick},
            "params": {
                "bank_id": int(settings.get("bank_id", 1)),
                "n_agents": int(settings.get("n_agents", 25)),
            },
        }],
        "metrics": ["bank_deposits:1", "bank_reserve_ratio:1", "sentiment", "index"],
        "event_outcomes": ["bank_failure", "deposit_move", "lolr_granted"],
    }
    data_root = root / "experiments"
    output = run_experiment(
        experiment_spec, out_dir=spec["report_dir"],
        data_root=str(data_root), quiet=False)
    evidence = []
    for seed in experiment_spec["seeds"]:
        db = data_root / name / f"{name}_s{seed}_treatment.db"
        store = Store(str(db))
        try:
            item = rumor_pilot_evidence(store)
            item["seed"] = seed
            item["database"] = str(db)
            evidence.append(item)
        finally:
            store.close()
    return {
        "passes": len(evidence) == len(experiment_spec["seeds"])
                  and all(item["passes"] for item in evidence),
        "seeds": evidence,
        "experiment": output["summary"],
    }


def _write_campaign_report(spec: dict, evidence: dict) -> tuple[str, str]:
    out = Path(spec["report_dir"])
    out.mkdir(parents=True, exist_ok=True)
    stem = f"acceptance_{spec['name']}"
    json_path = out / f"{stem}.json"
    md_path = out / f"{stem}.md"
    html_path = out / f"{stem}.html"
    json_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")

    md = [f"# PRD-v1 production acceptance — {spec['name']}", "",
          f"**Overall:** {'PASS' if evidence.get('passes') else 'INCOMPLETE/FAIL'}", ""]
    for name in ("long", "rumor"):
        if name in evidence:
            md += [f"## {name.title()}", "", "```json",
                   json.dumps(evidence[name], indent=2), "```", ""]
    md_path.write_text("\n".join(md), encoding="utf-8")

    rendered = html.escape(json.dumps(evidence, indent=2))
    html_path.write_text(
        "<!doctype html><meta charset='utf-8'><meta name='viewport' "
        "content='width=device-width,initial-scale=1'><title>PRD acceptance</title>"
        "<style>body{font:14px/1.5 system-ui;max-width:1100px;margin:40px auto;"
        "padding:0 18px;color:#17211d}pre{white-space:pre-wrap;background:#f4f6f3;"
        "padding:18px;border-radius:12px;overflow:auto}@media print{body{margin:0}}</style>"
        f"<h1>PRD-v1 production acceptance — {html.escape(spec['name'])}</h1>"
        f"<p><b>{'PASS' if evidence.get('passes') else 'INCOMPLETE/FAIL'}</b></p>"
        f"<pre>{rendered}</pre>", encoding="utf-8")
    return str(md_path), str(html_path)


def run_campaign(spec_path: str | Path, *, phase: str = "all") -> dict:
    load_dotenv()
    spec = load_campaign(spec_path)
    root = Path(spec["data_root"])
    root.mkdir(parents=True, exist_ok=True)
    config = load_config(spec["base_config"])

    if phase == "report":
        json_path = Path(spec["report_dir"]) / f"acceptance_{spec['name']}.json"
        if not json_path.exists():
            raise RuntimeError(f"acceptance evidence does not exist: {json_path}")
        evidence = json.loads(json_path.read_text(encoding="utf-8"))
        md_path, html_path = _write_campaign_report(spec, evidence)
        evidence["markdown_report"] = md_path
        evidence["html_report"] = html_path
        print(json.dumps(evidence, indent=2))
        return evidence

    if phase != "report":
        preflight = asyncio.run(provider_preflight(config, live=True))
        if not preflight.get("ready") or not preflight.get("live_ready"):
            raise RuntimeError("acceptance provider preflight failed: "
                               + json.dumps(preflight.get("errors", preflight)))

    evidence: dict[str, Any] = {"campaign": spec["name"], "preflight": preflight}
    if phase in {"all", "long"}:
        evidence["long"] = asyncio.run(_run_long_campaign(spec, config, root))
    if phase in {"all", "rumor"}:
        evidence["rumor"] = _run_rumor_campaign(spec, config, root)

    selected = [evidence[name] for name in ("long", "rumor") if name in evidence]
    evidence["passes"] = bool(selected) and all(
        item.get("passes", item.get("long_run", {}).get("passes", False)
                 and item.get("oracle", {}).get("passes", False)
                 and item.get("calibration", {}).get("passes", False)
                 and item.get("causal_phenomena", {}).get("passes", False))
        for item in selected)
    md_path, html_path = _write_campaign_report(spec, evidence)
    evidence["markdown_report"] = md_path
    evidence["html_report"] = html_path
    print(json.dumps(evidence, indent=2))
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description="Run resumable PRD-v1 acceptance campaigns")
    parser.add_argument("spec", nargs="?", default="runs/acceptance/v1.yaml")
    parser.add_argument("--phase", choices=("all", "long", "rumor", "report"), default="all")
    args = parser.parse_args()
    evidence = run_campaign(args.spec, phase=args.phase)
    if args.phase != "report" and not evidence["passes"]:
        raise SystemExit(5)


if __name__ == "__main__":
    main()

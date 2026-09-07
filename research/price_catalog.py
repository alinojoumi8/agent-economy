"""Symmetric, provider-free goods and equity study drafts for the price lab."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine.schema import SCHEMA_VERSION
from research.artifacts import digest_json, publish_json
from research.metric_registry import metric_definition
from research.studies import StudySpec, validate_study_inputs
from research.study_runner import validate_execution
from run_config import load_config

PRESETS = (
    {"key": "G2", "domain": "goods", "title": "Input costs and goods price adjustment",
     "hypothesis": "A commodity input-cost increase changes the selected firm's executed goods price and volume.",
     "primary": "goods_price", "treatment": "input_cost", "kind": "oil"},
    {"key": "F2", "domain": "equities", "title": "Public firm information and equity price response",
     "hypothesis": "A public adverse firm event changes its executed share price and liquidity.",
     "primary": "equity_price", "treatment": "firm_information", "kind": "scandal"},
)


def price_study_catalog() -> dict:
    return {"version": "price-study-catalog-v1", "presets": [dict(item) for item in PRESETS],
            "supported_domains": ["goods", "equities"],
            "status": "exploratory_provider_free_pilots",
            "limitations": ["Known-value allocation/auction fixtures are separate benchmarks; these world pilots have no known fair value.",
                            "The current daily engine cannot evaluate intraday latency or high-frequency price discovery."]}


def draft_price_study(config: dict, preset: str, *, seeds: list[int], horizon: int,
                      intervention_tick: int, goods_firm_id: int = 2,
                      equity_firm_id: int = 1, currency: str = "USD") -> StudySpec:
    try:
        selected = next(item for item in PRESETS if item["key"] == preset)
    except StopIteration:
        raise ValueError("unknown price-study preset") from None
    observations = [
        ("goods_price", f"goods_vwap:{goods_firm_id}", "window_vwap"),
        ("goods_volume", f"goods_volume:{goods_firm_id}", "window_sum"),
        ("equity_price", f"equity_price:{equity_firm_id}", "terminal"),
        ("equity_volume", f"equity_volume:{equity_firm_id}", "window_sum")]
    outcomes = []
    for key, metric, aggregation in observations:
        definition = metric_definition(metric)
        if definition is None:
            raise ValueError("firm identity is invalid")
        outcomes.append({"key": key, "metric": metric, "metric_version": definition.version,
                         "aggregation": aggregation, "currency": currency,
                         "purpose": "primary" if key == selected["primary"] else "exploratory"})
    shock = ({"kind": "oil", "tick": intervention_tick, "multiplier": 1.5}
             if selected["kind"] == "oil" else
             {"kind": "scandal", "tick": intervention_tick, "firm_id": equity_firm_id,
              "description": "A public laboratory signal reports an investigation into this firm's accounting."})
    information = "Same configured public-news and communication process in both arms. The declared shock is the treatment."
    keyed = int(config.get("engine_semantics_version", 1)) >= 16
    randomness_limit = (
        "Daily draws use mechanism/day/origin keys. Common keys share draws; changed eligibility, weights, policy branches and unmatched engine-created identities can change outcomes. Genesis retains its configured sequential PRNG."
        if keyed else "Shared mechanism RNG may diverge after treatment; common genesis and seed do not guarantee paired later hazards.")
    spec = StudySpec.model_validate({
        "protocol_version": "research-study-v1", "key": f"{preset.lower()}-price-pilot",
        "title": selected["title"], "hypothesis": selected["hypothesis"],
        "domains": ["goods", "equities"],
        "limitations": [
            "Synthetic exploratory pilot; no empirical-fitness or confirmatory causal claim.",
            randomness_limit,
            "Goods price is volume-weighted over the declared window; a window with no sale yields a missing price.",
            "Equity price carries the last distinct-owner execution with its age; the firm has no known fair value.",
            "Information must pass through the existing scripted policy; a null response is a valid finding.",
            "The input-cost regime uses system-supplied commodities and banks lend from reserves.",
            "Goods and equity firms are separate declared targets; incompatible or missing observations remain null.",
            "Default target choices were informed by exploratory pilot observation and are not a held-out hypothesis."],
        "model": {"engine_semantics_version": config.get("engine_semantics_version"),
                  "schema_version": SCHEMA_VERSION, "resolved_config_sha256": digest_json(config),
                  "model_description_version": "agent-economy-odd-v1",
                  "regimes": ["daily-settlement", "system-commodity-inputs", "reserve-funded-credit"]},
        "inputs": [], "calibration_targets": [],
        "arms": [{"key": "control", "label": "Unchanged baseline", "role": "baseline",
                  "changes": {}, "information_policy": information},
                 {"key": selected["treatment"], "label": selected["title"], "role": "treatment",
                  "changes": {"shocks": [shock]}, "information_policy": information}],
        "behavior": {"family": "scripted", "version": "scripted-policy-frozen-source",
                     "prompt_sha256": None, "provider_reference": None, "model_reference": None,
                     "endpoint_reference": None, "temperature": None,
                     "wake_cadence": f"Configured act_every={config.get('behavior', {}).get('act_every', 'engine default')}; role/event wake rules from frozen source",
                     "communication_policy": "Configured engine conversation and news process from frozen configuration",
                     "population_assignment": "All configured model routes use the scripted provider"},
        "time": {"tick_duration": "one_day", "warmup_ticks": intervention_tick - 1,
                 "intervention_start": intervention_tick, "intervention_end": intervention_tick,
                 "measurement_start": intervention_tick, "measurement_end": horizon,
                 "horizon": horizon, "stop_rule": "fixed_horizon"},
        "randomness": {"seeds": seeds, "seed_role": "initial_world_and_keyed_daily_streams" if keyed else "initial_world_and_engine_stream",
                       "stream_contract": "mechanism_day_identity_v1" if keyed else "legacy_shared_rng_v1", "pairing": "verified_common_genesis",
                       "model_replicates": []},
        "analysis": {"intent": "exploratory", "estimand": "Mean treatment minus control for complete matched world/seed pairs",
                     "treatment_unit": "world_seed_pair", "outcomes": outcomes,
                     "missing_data": "exclude_pair_report_reason", "uncertainty": "paired_world_bootstrap",
                     "minimum_pairs": 2, "bootstrap_samples": 2000,
                     "multiple_outcome_policy": "single_primary"},
        "operations": {"mode": "provider_free", "max_provider_calls": 0, "max_tokens": 0,
                       "max_spend_usd": 0.0, "max_wall_seconds": 300,
                       "max_disk_bytes": 536870912, "concurrency": 1,
                       "failure_policy": "preserve_and_exclude", "pause_policy": "preserve_and_stop"}})
    validate_execution(spec, config)
    return spec


def draft_checkpoint_price_study(config: dict, preset: str, *, checkpoints: list[Path],
                                 input_root: Path, horizon: int, intervention_tick: int,
                                 warmup_ticks: int = 0, goods_firm_id: int = 2,
                                 equity_firm_id: int = 1, currency: str = "USD",
                                 max_disk_bytes: int = 536870912, max_wall_seconds: int = 300,
                                 pause_policy: str = "preserve_and_stop") -> StudySpec:
    """Admit explicit saved-world inputs and draft an unexecuted price study."""
    from research.checkpoint_origins import inspect_checkpoint

    root = input_root.resolve()
    if not checkpoints:
        raise ValueError("declare at least one saved world")
    sources, artifacts, ticks = [], [], set()
    for path in checkpoints:
        path = Path(path).absolute()
        if not path.is_relative_to(root):
            raise ValueError("checkpoint is outside the declared input root")
        receipt = inspect_checkpoint(path, max_bytes=max_disk_bytes)
        seed = receipt["seed"]
        key = f"checkpoint-{seed}"
        ticks.add(receipt["tick"])
        sources.append({"seed": seed, "input_key": key, "receipt_sha256": digest_json(receipt)})
        artifacts.append({"key": key, "path": path.relative_to(root).as_posix(),
            "sha256": receipt["database_sha256"], "role": "checkpoint",
            "vintage": f"Declared saved world at completed day {receipt['tick']}", "transform_version": "identity"})
    if len(ticks) != 1:
        raise ValueError("paired checkpoint studies require one common completed origin day")
    # Use the shared outcome/intervention template, then restore the full
    # original configuration declaration, including inherited schedules.
    template = draft_price_study({**config, "shocks": []}, preset,
        seeds=[item["seed"] for item in sources], horizon=horizon, intervention_tick=intervention_tick,
        goods_firm_id=goods_firm_id, equity_firm_id=equity_firm_id, currency=currency)
    raw = template.model_dump(mode="json")
    raw.update(protocol_version="research-study-v2", inputs=artifacts,
               origin={"kind": "verified_checkpoints", "tick": next(iter(ticks)), "sources": sources})
    raw["model"]["resolved_config_sha256"] = digest_json(config)
    raw["time"]["warmup_ticks"] = warmup_ticks
    raw["randomness"].update(seed_role="checkpoint_origin_seed", pairing="verified_common_checkpoint")
    raw["analysis"].update(treatment_unit="checkpoint_world_pair",
        estimand="Mean treatment minus control for complete matched continuations from independent saved worlds")
    raw["operations"].update(max_disk_bytes=max_disk_bytes, max_wall_seconds=max_wall_seconds, pause_policy=pause_policy)
    raw["limitations"].append("Admission verifies each saved state, not the history that produced it. Replay covers only the declared continuation; inherited calls and costs are excluded from new execution totals.")
    spec = StudySpec.model_validate(raw)
    validate_execution(spec, config)
    validate_study_inputs(spec, config, input_root=root)
    return spec


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("preset", choices=[item["key"] for item in PRESETS])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", type=int, nargs="+")
    parser.add_argument("--checkpoint", type=Path, action="append", help="Explicit closed source; repeat for independent worlds")
    parser.add_argument("--input-root", type=Path, default=Path("."))
    parser.add_argument("--warmup-ticks", type=int, default=0, help="Warmup duration after a checkpoint origin")
    parser.add_argument("--pause-policy", choices=["preserve_and_stop", "preserve_and_resume", "preserve_and_resume_phases"], default="preserve_and_stop")
    parser.add_argument("--ticks", type=int, default=30)
    parser.add_argument("--intervention-tick", type=int, default=5)
    parser.add_argument("--goods-firm-id", type=int, default=2)
    parser.add_argument("--equity-firm-id", type=int, default=1)
    parser.add_argument("--currency", default="USD")
    args = parser.parse_args()
    if not args.checkpoint and (args.warmup_ticks or args.pause_policy != "preserve_and_stop"):
        parser.error("checkpoint warmup/recovery options require --checkpoint")
    if args.checkpoint and args.seeds is not None:
        parser.error("checkpoint studies retain their original seeds; omit --seeds")
    options = {"checkpoints": args.checkpoint, "input_root": args.input_root,
               "warmup_ticks": args.warmup_ticks, "pause_policy": args.pause_policy} if args.checkpoint else {
               "seeds": args.seeds if args.seeds is not None else [1, 2, 3, 4, 5]}
    builder = draft_checkpoint_price_study if args.checkpoint else draft_price_study
    spec = builder(load_config(args.config), args.preset, horizon=args.ticks,
        intervention_tick=args.intervention_tick, goods_firm_id=args.goods_firm_id,
        equity_firm_id=args.equity_firm_id, currency=args.currency, **options)
    publish_json(args.output, spec.model_dump(mode="json"))
    print(json.dumps({"draft": str(args.output.resolve()), "executed": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

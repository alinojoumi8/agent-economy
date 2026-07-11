"""Production acceptance orchestration and evidence receipts.

The evaluator is independent of the live ``World`` object so a reviewer can
regenerate the receipt from persisted run evidence alone.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from engine.ledger import Ledger
from engine.store import Store, load_json

if TYPE_CHECKING:
    from world.loop import World


REQUIRED_SHOCKS = ("policy_rate", "oil", "rumor", "slant", "scandal")
FAILURE_EVENTS = (
    "provider_failure", "provider_pause", "reconciliation_failure",
    "budget_pause", "report_failed",
)


def uses_paid_providers(config: dict) -> bool:
    """Return whether any configured route can call a non-local provider."""
    llm = config.get("llm", {})
    routes = [llm.get("default_route", {}), *llm.get("routes", {}).values()]
    providers = {str(route.get("provider", "scripted")) for route in routes}
    return bool(providers.difference({"scripted", "mock", "replay"}))


def resolve_run_db(run_or_path: str | Path, data_dir: str | Path = "data/runs") -> Path:
    candidate = Path(run_or_path)
    if candidate.exists() or candidate.suffix == ".db":
        return candidate
    return Path(data_dir) / f"{candidate}.db"


def _check(check_id: str, label: str, passed: bool, evidence: Any) -> dict:
    return {"id": check_id, "label": label, "passed": bool(passed), "evidence": evidence}


def _p90(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.90 * len(ordered)) - 1)]


def _event_payloads(store: Store, kind: str) -> list[tuple[int, int, dict]]:
    return [
        (int(row["id"]), int(row["tick"]), load_json(row["payload_json"], {}))
        for row in store.query("SELECT id, tick, payload_json FROM events WHERE kind=? ORDER BY id", (kind,))
    ]


def _outflow(store: Store, bank_id: int, start_tick: int, end_tick: int) -> int:
    rows = store.query(
        "SELECT payload_json FROM events WHERE kind='deposit_move' AND tick BETWEEN ? AND ?",
        (start_tick, end_tick),
    )
    return sum(
        int(payload.get("amount_cents", 0))
        for row in rows
        for payload in [load_json(row["payload_json"], {})]
        if int(payload.get("from_bank", -1)) == bank_id
    )


def _rumor_pilot(store: Store, initial_trust: float) -> tuple[bool, dict]:
    rumors = _event_payloads(store, "rumor")
    if not rumors:
        return False, {"reason": "no rumor event"}
    _, rumor_tick, payload = rumors[0]
    bank_id = int(payload.get("bank_id", 1))
    exposed = [int(value) for value in payload.get("target_agent_ids", [])]
    end_tick = rumor_tick + 9
    participant_conversations: set[int] = set()
    for row in store.query(
        "SELECT c.id, c.participant_ids, m.text FROM conversations c "
        "JOIN messages m ON m.conv_id=c.id WHERE c.tick BETWEEN ? AND ?",
        (rumor_tick, end_tick),
    ):
        participants = {int(value) for value in load_json(row["participant_ids"], [])}
        text = str(row["text"] or "").lower()
        mentions_rumor = "bank" in text and any(
            word in text for word in ("rumor", "hear", "pull", "deposit", "worried", "fail", "under")
        )
        if participants.intersection(exposed) and mentions_rumor:
            participant_conversations.add(int(row["id"]))

    trust_threshold = initial_trust - 0.2
    dropped = 0
    for agent_id in exposed:
        value = store.scalar(
            "SELECT value FROM beliefs WHERE agent_id=? AND key=?",
            (agent_id, f"trust:bank:{bank_id}"), default=None,
        )
        if value is not None and float(value) <= trust_threshold + 1e-9:
            dropped += 1
    drop_share = dropped / len(exposed) if exposed else 0.0
    pre_outflow = _outflow(store, bank_id, max(0, rumor_tick - 10), rumor_tick - 1)
    post_outflow = _outflow(store, bank_id, rumor_tick, end_tick)
    outflow_passed = post_outflow > 2 * pre_outflow if pre_outflow else post_outflow > 0
    evidence = {
        "rumor_tick": rumor_tick, "bank_id": bank_id, "exposed_agents": len(exposed),
        "rumor_conversations_10_ticks": len(participant_conversations),
        "trust_drop_agents": dropped, "trust_drop_share": round(drop_share, 4),
        "initial_trust_assumption": initial_trust,
        "pre_outflow_cents_10_ticks": pre_outflow,
        "post_outflow_cents_10_ticks": post_outflow,
    }
    passed = len(participant_conversations) >= 5 and drop_share >= 0.25 and outflow_passed
    return passed, evidence


def _shock_effects(store: Store) -> tuple[dict[str, bool], dict[str, Any]]:
    fired = {str(payload.get("kind")): tick for _, tick, payload in _event_payloads(store, "shock_fired")}
    policy_events = int(store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='policy_rate_set' AND tick>=?",
        (fired.get("policy_rate", 10**9),), default=0,
    ))
    oil_events = int(store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='commodity_shock' AND tick>=?",
        (fired.get("oil", 10**9),), default=0,
    ))
    slant_articles = 0
    scandal_articles = 0
    scandal_ids = {event_id for event_id, _, _ in _event_payloads(store, "firm_scandal")}
    for row in store.query("SELECT tick, slant_tags, source_event_ids FROM news_articles"):
        if (int(row["tick"]) >= fired.get("slant", 10**9)
                and "directed" in load_json(row["slant_tags"], [])):
            slant_articles += 1
        sources = {int(value) for value in load_json(row["source_event_ids"], [])}
        if scandal_ids.intersection(sources):
            scandal_articles += 1
    effects = {
        "policy_rate": policy_events > 0,
        "oil": oil_events > 0,
        "slant": slant_articles > 0,
        "scandal": scandal_articles > 0,
    }
    evidence = {
        "fired_ticks": fired,
        "policy_rate_events_after_shock": policy_events,
        "commodity_shock_events_after_shock": oil_events,
        "directed_articles": slant_articles,
        "scandal_citing_articles": scandal_articles,
    }
    return effects, evidence


def _experiment_evidence(path: str | Path | None) -> tuple[bool, dict]:
    if not path:
        return False, {"reason": "no experiment JSON supplied"}
    evidence_path = Path(path)
    if not evidence_path.exists():
        return False, {"reason": f"experiment JSON not found: {evidence_path}"}
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    seeds = {int(seed) for seed in payload.get("spec", {}).get("seeds", [])}
    results = payload.get("results", [])
    arms = {str(result.get("arm")) for result in results}
    all_reconciled = bool(payload.get("summary", {}).get("all_reconciled"))
    complete = all(
        any(int(result.get("seed", -1)) == seed and result.get("arm") == arm for result in results)
        for seed in seeds for arm in ("treatment", "control")
    )
    evidence = {
        "path": str(evidence_path), "seeds": sorted(seeds), "arms": sorted(arms),
        "runs": len(results), "all_reconciled": all_reconciled,
    }
    passed = len(seeds) >= 5 and arms >= {"treatment", "control"} and complete and all_reconciled
    return passed, evidence


def _phenomena_evidence(store: Store, path: str | Path | None) -> tuple[bool, dict]:
    if not path:
        return False, {"reason": "no phenomena evidence supplied"}
    evidence_path = Path(path)
    if not evidence_path.exists():
        return False, {"reason": f"phenomena evidence not found: {evidence_path}"}
    payload = yaml.safe_load(evidence_path.read_text(encoding="utf-8")) or {}
    verified = []
    for item in payload.get("phenomena", []):
        metric = str(item.get("metric", ""))
        start_tick = int(item.get("start_tick", -1))
        end_tick = int(item.get("end_tick", -1))
        direction = item.get("direction")
        start = store.scalar(
            "SELECT value FROM metrics WHERE name=? AND tick<=? ORDER BY tick DESC, id DESC LIMIT 1",
            (metric, start_tick), default=None,
        )
        end = store.scalar(
            "SELECT value FROM metrics WHERE name=? AND tick<=? ORDER BY tick DESC, id DESC LIMIT 1",
            (metric, end_tick), default=None,
        )
        delta = None if start is None or end is None else float(end) - float(start)
        direction_ok = delta is not None and (
            (direction == "increase" and delta > 0) or (direction == "decrease" and delta < 0)
        )
        valid = bool(
            item.get("name") and item.get("mechanism") and item.get("status") == "documented"
            and 0 <= start_tick < end_tick and direction_ok
        )
        verified.append({
            "name": item.get("name"), "metric": metric, "start_tick": start_tick,
            "end_tick": end_tick, "direction": direction, "start": start,
            "end": end, "delta": delta, "verified": valid,
        })
    distinct = {
        (item["name"], item["metric"], item["start_tick"], item["end_tick"])
        for item in verified if item["verified"]
    }
    return len(distinct) >= 3, {
        "path": str(evidence_path), "documented": verified,
        "distinct_verified": len(distinct),
    }


def evaluate_acceptance(
    db_path: str | Path,
    *,
    experiment_json: str | Path | None = None,
    phenomena_yaml: str | Path | None = None,
) -> dict:
    """Evaluate all production acceptance gates from persisted evidence."""
    db = Path(db_path)
    if not db.exists():
        raise FileNotFoundError(f"run database not found: {db}")
    store = Store(str(db), create=False)
    try:
        meta = store.get_meta()
        config = load_json(meta["config_json"], {})
        acceptance = config.get("acceptance", {})
        min_ticks = int(acceptance.get("min_ticks", 365))
        min_agents = int(acceptance.get("min_agents", 95))
        max_agents = int(acceptance.get("max_agents", 105))
        max_spend_raw = acceptance.get("max_spend_usd", 200.0)
        max_spend = None if max_spend_raw is None else float(max_spend_raw)
        configured_cap_raw = config.get("budget", {}).get("cap_usd", 200.0)
        configured_cap = None if configured_cap_raw is None else float(configured_cap_raw)
        oracle_p90_limit = int(acceptance.get("oracle_p90_ms", 60_000))
        tick = int(meta["tick"])
        status = str(meta["status"])
        agent_count = int(store.scalar("SELECT COUNT(*) FROM agents", default=0))
        spend = float(store.scalar("SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls", default=0.0))
        providers = {
            str(row["provider"]) for row in store.query("SELECT DISTINCT provider FROM llm_calls")
            if row["provider"]
        }
        real_providers = providers.difference({"scripted", "mock", "replay"})
        forbidden_providers = providers.intersection({"scripted", "mock"})
        reconciled, ledger_diag = Ledger(store).reconcile()
        failures = {
            kind: int(store.scalar("SELECT COUNT(*) FROM events WHERE kind=?", (kind,), default=0))
            for kind in FAILURE_EVENTS
        }
        oracle_latencies = [
            int(row["latency_ms"]) for row in store.query(
                "SELECT latency_ms FROM llm_calls WHERE purpose='oracle' AND latency_ms IS NOT NULL"
            )
        ]
        oracle_p90 = _p90(oracle_latencies)
        resolved_predictions = int(store.scalar(
            "SELECT COUNT(*) FROM predictions WHERE status='resolved' AND brier IS NOT NULL", default=0
        ))
        effects, effect_evidence = _shock_effects(store)
        rumor_ok, rumor_evidence = _rumor_pilot(
            store, float(acceptance.get("rumor_initial_trust", 0.6))
        )
        experiment_ok, experiment_evidence = _experiment_evidence(experiment_json)
        phenomena_ok, phenomena_evidence = _phenomena_evidence(store, phenomena_yaml)

        checks = [
            _check("run_horizon", "365-day run completed cleanly",
                   tick >= min_ticks and status in {"paused", "finished"},
                   {"tick": tick, "minimum": min_ticks, "status": status}),
            _check("population", "Production population is approximately 100 agents",
                   min_agents <= agent_count <= max_agents,
                   {"agents": agent_count, "range": [min_agents, max_agents]}),
            _check("real_providers", "Run used only configured real providers",
                   bool(real_providers) and not forbidden_providers,
                   {"providers": sorted(providers), "real": sorted(real_providers),
                    "forbidden": sorted(forbidden_providers)}),
            _check("budget", "Provider spend policy was satisfied",
                   (max_spend is None or spend <= max_spend)
                   and (configured_cap is None or spend <= configured_cap),
                   {"spend_usd": round(spend, 6), "maximum_usd": max_spend,
                    "configured_cap_usd": configured_cap,
                    "uncapped": max_spend is None and configured_cap is None}),
            _check("ledger", "Double-entry ledger reconciles exactly", reconciled, ledger_diag),
            _check("failure_events", "No provider, budget, report, or reconciliation failure occurred",
                   not any(failures.values()) and status != "halted", failures),
            _check("oracle_latency", "Oracle p90 response latency is below 60 seconds",
                   oracle_p90 is not None and oracle_p90 < oracle_p90_limit,
                   {"samples": len(oracle_latencies), "p90_ms": oracle_p90,
                    "limit_ms": oracle_p90_limit}),
            _check("oracle_scoring", "At least one Oracle prediction resolved automatically",
                   resolved_predictions > 0, {"resolved_predictions": resolved_predictions}),
            _check("required_shocks", "All five required shock types fired",
                   set(effect_evidence["fired_ticks"]) >= set(REQUIRED_SHOCKS), effect_evidence["fired_ticks"]),
            _check("policy_rate_effect", "Policy-rate shock changed the policy-rate channel",
                   effects["policy_rate"], effect_evidence),
            _check("oil_effect", "Oil shock changed the commodity-price channel",
                   effects["oil"], effect_evidence),
            _check("rumor_pilot", "Rumor pilot passed conversation, trust, and outflow thresholds",
                   rumor_ok, rumor_evidence),
            _check("slant_effect", "Slant directive produced a directed article",
                   effects["slant"], effect_evidence),
            _check("scandal_effect", "Firm scandal was cited by a published article",
                   effects["scandal"], effect_evidence),
            _check("experiment_n5", "Five-seed treatment/control experiment completed and reconciled",
                   experiment_ok, experiment_evidence),
            _check("emergent_phenomena", "Three emergent phenomena have verified metric signatures",
                   phenomena_ok, phenomena_evidence),
        ]
        return {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "run": {"run_id": str(meta["run_id"]), "database": str(db), "seed": int(meta["seed"])},
            "passed": all(check["passed"] for check in checks),
            "checks": checks,
        }
    finally:
        store.close()


def write_acceptance_package(
    db_path: str | Path,
    *,
    out_dir: str | Path = "reports/out",
    experiment_json: str | Path | None = None,
    phenomena_yaml: str | Path | None = None,
) -> dict:
    receipt = evaluate_acceptance(
        db_path, experiment_json=experiment_json, phenomena_yaml=phenomena_yaml
    )
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    run_id = receipt["run"]["run_id"]
    json_path = out / f"acceptance_{run_id}.json"
    md_path = out / f"acceptance_{run_id}.md"
    json_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    lines = [
        f"# Production acceptance — {run_id}", "",
        f"Overall: **{'PASS' if receipt['passed'] else 'FAIL'}**", "", "## Gates", "",
    ]
    for check in receipt["checks"]:
        lines.append(f"- [{'x' if check['passed'] else ' '}] **{check['label']}** (`{check['id']}`)")
        lines.append(f"  - Evidence: `{json.dumps(check['evidence'], sort_keys=True)}`")
    lines += ["", "## Reproduction", "", f"Database: `{receipt['run']['database']}`",
              f"Receipt JSON: `{json_path}`"]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {**receipt, "artifacts": {"json": str(json_path), "markdown": str(md_path)}}


async def execute_acceptance_run(world: "World", *, target_tick: int | None = None) -> None:
    """Advance a world to the acceptance horizon and ask scheduled Oracle questions."""
    acceptance = world.config.get("acceptance", {})
    horizon = int(target_tick or acceptance.get("min_ticks", 365))
    questions = sorted(acceptance.get("oracle_questions", []), key=lambda item: int(item["at_tick"]))
    for item in questions:
        at_tick = int(item["at_tick"])
        if at_tick > horizon:
            continue
        if world.store.tick < at_tick:
            await world.run(max_ticks=at_tick - world.store.tick)
            if world.store.tick < at_tick or world.last_pause_reason:
                raise RuntimeError(f"acceptance run paused before Oracle checkpoint at tick {at_tick}")
        existing = world.store.scalar(
            "SELECT COUNT(*) FROM predictions WHERE question=?", (str(item["question"]),), default=0
        )
        if not existing:
            await world.oracle.ask(str(item["question"]))
    if world.store.tick < horizon:
        await world.run(max_ticks=horizon - world.store.tick)
    if world.store.tick < horizon or world.last_pause_reason:
        raise RuntimeError(f"acceptance run paused at tick {world.store.tick}; target was {horizon}")

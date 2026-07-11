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
    dropped_agents: list[int] = []
    for agent_id in exposed:
        value = store.scalar(
            "SELECT value FROM beliefs WHERE agent_id=? AND key=?",
            (agent_id, f"trust:bank:{bank_id}"), default=None,
        )
        if value is not None and float(value) <= trust_threshold + 1e-9:
            dropped_agents.append(agent_id)
    dropped = len(dropped_agents)
    drop_share = dropped / len(exposed) if exposed else 0.0
    pre_outflow = _outflow(store, bank_id, max(0, rumor_tick - 10), rumor_tick - 1)
    post_outflow = _outflow(store, bank_id, rumor_tick, end_tick)
    post_outflow_events = []
    for row in store.query(
        "SELECT id, tick, payload_json FROM events "
        "WHERE kind='deposit_move' AND tick BETWEEN ? AND ? ORDER BY tick, id",
        (rumor_tick, end_tick),
    ):
        move = load_json(row["payload_json"], {})
        if int(move.get("from_bank", -1)) == bank_id:
            post_outflow_events.append({
                "event_id": int(row["id"]), "tick": int(row["tick"]),
                "amount_cents": int(move.get("amount_cents", 0)),
            })
    outflow_passed = post_outflow > 2 * pre_outflow if pre_outflow else post_outflow > 0
    evidence = {
        "rumor_tick": rumor_tick, "bank_id": bank_id, "exposed_agents": len(exposed),
        "rumor_conversations_10_ticks": len(participant_conversations),
        "rumor_conversation_ids": sorted(participant_conversations)[:20],
        "trust_drop_agents": dropped, "trust_drop_share": round(drop_share, 4),
        "trust_drop_agent_ids": sorted(dropped_agents)[:20],
        "initial_trust_assumption": initial_trust,
        "pre_outflow_cents_10_ticks": pre_outflow,
        "post_outflow_cents_10_ticks": post_outflow,
        "post_outflow_events": post_outflow_events[:20],
    }
    passed = len(participant_conversations) >= 5 and drop_share >= 0.25 and outflow_passed
    return passed, evidence


def _shock_effects(store: Store) -> tuple[dict[str, bool], dict[str, Any]]:
    fired_events = {
        str(payload.get("kind")): {
            "event_id": event_id, "tick": tick, "kind": "shock_fired", "payload": payload,
        }
        for event_id, tick, payload in _event_payloads(store, "shock_fired")
    }
    fired = {kind: int(event["tick"]) for kind, event in fired_events.items()}

    def downstream_events(kind: str, shock_kind: str) -> list[dict[str, Any]]:
        return [
            {
                "event_id": int(row["id"]), "tick": int(row["tick"]),
                "kind": str(row["kind"]), "payload": load_json(row["payload_json"], {}),
            }
            for row in store.query(
                "SELECT id, tick, kind, payload_json FROM events "
                "WHERE kind=? AND tick>=? ORDER BY tick, id LIMIT 10",
                (kind, fired.get(shock_kind, 10**9)),
            )
        ]

    policy_trace = downstream_events("policy_rate_set", "policy_rate")
    oil_trace = downstream_events("commodity_shock", "oil")
    policy_events = int(store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='policy_rate_set' AND tick>=?",
        (fired.get("policy_rate", 10**9),), default=0,
    ))
    oil_events = int(store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='commodity_shock' AND tick>=?",
        (fired.get("oil", 10**9),), default=0,
    ))
    directed_articles: list[dict[str, Any]] = []
    scandal_citing_articles: list[dict[str, Any]] = []
    scandal_ids = {event_id for event_id, _, _ in _event_payloads(store, "firm_scandal")}
    for row in store.query(
        "SELECT id, tick, headline, slant_tags, source_event_ids FROM news_articles ORDER BY tick, id"
    ):
        if (int(row["tick"]) >= fired.get("slant", 10**9)
                and "directed" in load_json(row["slant_tags"], [])):
            directed_articles.append({
                "article_id": int(row["id"]), "tick": int(row["tick"]),
                "headline": str(row["headline"]),
                "slant_tags": load_json(row["slant_tags"], []),
            })
        sources = {int(value) for value in load_json(row["source_event_ids"], [])}
        if scandal_ids.intersection(sources):
            scandal_citing_articles.append({
                "article_id": int(row["id"]), "tick": int(row["tick"]),
                "headline": str(row["headline"]), "source_event_ids": sorted(sources),
            })
    effects = {
        "policy_rate": policy_events > 0,
        "oil": oil_events > 0,
        "slant": bool(directed_articles),
        "scandal": bool(scandal_citing_articles),
    }
    traces = {
        "policy_rate": {
            "source": fired_events.get("policy_rate"), "downstream": policy_trace,
            "passed": effects["policy_rate"],
        },
        "oil": {
            "source": fired_events.get("oil"), "downstream": oil_trace,
            "passed": effects["oil"],
        },
        "rumor": {
            "source": fired_events.get("rumor"), "downstream": None, "passed": False,
        },
        "slant": {
            "source": fired_events.get("slant"), "downstream": directed_articles[:10],
            "passed": effects["slant"],
        },
        "scandal": {
            "source": fired_events.get("scandal"), "downstream": scandal_citing_articles[:10],
            "passed": effects["scandal"],
        },
    }
    evidence = {
        "fired_ticks": fired,
        "policy_rate_events_after_shock": policy_events,
        "commodity_shock_events_after_shock": oil_events,
        "directed_articles": len(directed_articles),
        "scandal_citing_articles": len(scandal_citing_articles),
        "traces": traces,
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
        provider_incidents = [
            {
                "event_id": int(row["id"]), "tick": int(row["tick"]),
                "kind": str(row["kind"]),
                "recovered": int(row["tick"]) <= tick,
            }
            for row in store.query(
                "SELECT id, tick, kind FROM events "
                "WHERE kind IN ('provider_failure','provider_pause') ORDER BY id LIMIT 50"
            )
        ]
        unrecovered_provider_incidents = int(store.scalar(
            "SELECT COUNT(*) FROM events "
            "WHERE kind IN ('provider_failure','provider_pause') AND tick>?",
            (tick,), default=0,
        ))
        hard_failures = sum(
            failures[kind] for kind in ("reconciliation_failure", "budget_pause", "report_failed")
        )
        failure_evidence = {
            "counts": failures,
            "provider_incidents": provider_incidents,
            "recovered_provider_incidents": (
                failures["provider_failure"] + failures["provider_pause"]
                - unrecovered_provider_incidents
            ),
            "unrecovered_provider_incidents": unrecovered_provider_incidents,
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
        effect_evidence["traces"]["rumor"].update({
            "downstream": rumor_evidence, "passed": rumor_ok,
        })
        shock_traces_ok = (
            set(effect_evidence["traces"]) == set(REQUIRED_SHOCKS)
            and all(
                trace.get("source") and trace.get("downstream") and trace.get("passed")
                for trace in effect_evidence["traces"].values()
            )
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
            _check("failure_events",
                   "No unrecovered provider, budget, report, or reconciliation failure remains",
                   not hard_failures and not unrecovered_provider_incidents and status != "halted",
                   failure_evidence),
            _check("oracle_latency", "Oracle p90 response latency is below 60 seconds",
                   oracle_p90 is not None and oracle_p90 < oracle_p90_limit,
                   {"samples": len(oracle_latencies), "p90_ms": oracle_p90,
                    "limit_ms": oracle_p90_limit}),
            _check("oracle_scoring", "At least one Oracle prediction resolved automatically",
                   resolved_predictions > 0, {"resolved_predictions": resolved_predictions}),
            _check("required_shocks", "All five required shock types fired",
                   set(effect_evidence["fired_ticks"]) >= set(REQUIRED_SHOCKS), effect_evidence["fired_ticks"]),
            _check("shock_traces", "All five shocks have explicit source-to-downstream traces",
                   shock_traces_ok, effect_evidence["traces"]),
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


def _has_usable_oracle_evidence(store: Store, question: str) -> bool:
    row = store.query_one(
        "SELECT evidence_json FROM predictions WHERE question=? ORDER BY id DESC LIMIT 1",
        (question,))
    evidence = load_json(row["evidence_json"], []) if row else []
    return bool(
        isinstance(evidence, list)
        and any(isinstance(item, dict) and item.get("tool") and "result" in item
                for item in evidence)
    )


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
        question = str(item["question"])
        existing = world.store.scalar(
            "SELECT COUNT(*) FROM predictions WHERE question=?", (question,), default=0)
        if not existing or not _has_usable_oracle_evidence(world.store, question):
            await world.oracle.ask(question)
    if world.store.tick < horizon:
        await world.run(max_ticks=horizon - world.store.tick)
    if world.store.tick < horizon or world.last_pause_reason:
        raise RuntimeError(f"acceptance run paused at tick {world.store.tick}; target was {horizon}")

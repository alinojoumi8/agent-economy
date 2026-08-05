"""Persisted acceptance receipt for the Semantics-11 live cognition profile."""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engine.cognition import COMPLEX_ACTIONS, PLAN_TIERS, level_for_xp
from engine.ledger import Ledger, SYS_COMPUTE, SYS_EDUCATION
from engine.store import Store
from reports.acceptance import resolve_run_db
from world.replay_verify import verify_replay


REQUIRED_TABLES = {
    "agent_skills", "agent_skill_history", "compute_subscriptions",
    "llm_attempts", "runtime_tick_stats",
}
SEED_SKILL_SOURCES = {
    "genesis", "occupation", "founder", "institutional_specialist",
}


def _check(check_id: str, label: str, passed: bool, evidence: Any) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "passed": bool(passed),
        "evidence": evidence,
    }


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return round(ordered[index], 3)


def _expected_distribution(total: int, weights: dict[str, Any]) -> dict[str, int]:
    normalized = {
        tier: max(0.0, float(weights.get(tier, 0.0))) for tier in PLAN_TIERS
    }
    weight_total = sum(normalized.values()) or 1.0
    raw = {tier: total * normalized[tier] / weight_total for tier in PLAN_TIERS}
    counts = {tier: int(raw[tier]) for tier in PLAN_TIERS}
    remaining = total - sum(counts.values())
    order = sorted(
        PLAN_TIERS,
        key=lambda tier: (-(raw[tier] - counts[tier]), PLAN_TIERS.index(tier)),
    )
    for tier in order[:remaining]:
        counts[tier] += 1
    return counts


def _skill_history_audit(store: Store) -> dict[str, Any]:
    proposals = {
        int(row["id"]): row
        for row in store.query(
            "SELECT id,tick,actor_id,action_type,validation_status "
            "FROM action_proposals ORDER BY id")
    }
    current = {
        (int(row["agent_id"]), str(row["skill_key"])): row
        for row in store.query(
            "SELECT agent_id,skill_key,xp,level FROM agent_skills")
    }
    histories: dict[tuple[int, str], list[Any]] = {}
    errors: list[str] = []
    action_awards = 0
    study_awards = 0
    for row in store.query(
            "SELECT * FROM agent_skill_history ORDER BY agent_id,skill_key,tick,id"):
        key = (int(row["agent_id"]), str(row["skill_key"]))
        histories.setdefault(key, []).append(row)
        source = str(row["source"])
        expected_delta: int | None = None
        proposal_id: int | None = None
        expected_type: str | None = None
        if source.startswith("action:"):
            parts = source.split(":")
            if len(parts) == 3 and parts[2].isdigit():
                expected_type = parts[1]
                proposal_id = int(parts[2])
                expected_delta = 4 if expected_type in COMPLEX_ACTIONS else 2
                action_awards += 1
            else:
                errors.append(f"history {row['id']} has unbound action source {source}")
        elif source.startswith("study:"):
            parts = source.split(":")
            if len(parts) == 2 and parts[1].isdigit():
                expected_type = "study_skill"
                proposal_id = int(parts[1])
                expected_delta = 10
                study_awards += 1
            else:
                errors.append(f"history {row['id']} has unbound study source {source}")
        elif source not in SEED_SKILL_SOURCES:
            errors.append(f"history {row['id']} has unknown source {source}")

        if proposal_id is not None:
            proposal = proposals.get(proposal_id)
            if proposal is None:
                errors.append(f"history {row['id']} references missing proposal {proposal_id}")
            elif (
                int(proposal["tick"]) != int(row["tick"])
                or int(proposal["actor_id"]) != int(row["agent_id"])
                or str(proposal["action_type"]) != expected_type
                or str(proposal["validation_status"]) != "accepted"
            ):
                errors.append(f"history {row['id']} is not bound to its accepted proposal")
            if expected_delta is not None and int(row["xp_delta"]) != expected_delta:
                errors.append(
                    f"history {row['id']} awarded {row['xp_delta']} XP, expected {expected_delta}")

    for key, rows in histories.items():
        previous_level = 0
        previous_xp = 0
        for row in rows:
            if int(row["old_level"]) != previous_level:
                errors.append(f"skill {key} history {row['id']} breaks level continuity")
            if int(row["new_xp"]) != previous_xp + int(row["xp_delta"]):
                errors.append(f"skill {key} history {row['id']} breaks XP continuity")
            if int(row["new_level"]) != level_for_xp(int(row["new_xp"])):
                errors.append(f"skill {key} history {row['id']} has the wrong level")
            previous_level = int(row["new_level"])
            previous_xp = int(row["new_xp"])
        final = current.get(key)
        if final is None or (
            int(final["xp"]) != previous_xp or int(final["level"]) != previous_level
        ):
            errors.append(f"skill {key} final state does not match its history")

    missing_history = [key for key, row in current.items() if int(row["xp"]) > 0 and key not in histories]
    errors.extend(f"skill {key} has XP without history" for key in missing_history)
    return {
        "passed": not errors,
        "history_rows": sum(len(rows) for rows in histories.values()),
        "action_awards": action_awards,
        "study_awards": study_awards,
        "errors": errors[:50],
    }


def build_cognition_acceptance_report(
    database: str | Path,
    *,
    live_probe: str | Path | None = None,
    replay_database: str | Path | None = None,
) -> dict[str, Any]:
    db = resolve_run_db(database).resolve()
    if not db.exists():
        raise FileNotFoundError(db)
    store = Store(str(db), create=False, read_only=True)
    try:
        tables = {
            str(row["name"])
            for row in store.query(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        }
        missing_tables = sorted(REQUIRED_TABLES - tables)
        if missing_tables:
            raise ValueError(
                "run is not a schema-15+ cognition run; missing "
                + ", ".join(missing_tables))

        meta = store.get_meta()
        config = json.loads(str(meta["config_json"] or "{}"))
        acceptance = config.get("acceptance", {})
        cognition = config.get("cognition", {})
        target_agents = int(acceptance.get("target_agents", 100))
        target_ticks = int(acceptance.get("rehearsal_ticks", 10))
        min_peak = int(acceptance.get("min_peak_concurrency", 10))
        median_limit_ms = float(acceptance.get("median_day_seconds_max", 180)) * 1000.0
        p95_limit_ms = float(acceptance.get("p95_day_seconds_max", 300)) * 1000.0
        duration = int(cognition.get("duration_ticks", 7))
        checks: list[dict[str, Any]] = []

        checks.append(_check(
            "versions", "Schema 15+ and engine semantics 11",
            int(meta["schema_version"]) >= 15
            and int(config.get("engine_semantics_version", 0)) == 11,
            {
                "schema_version": int(meta["schema_version"]),
                "engine_semantics_version": int(config.get("engine_semantics_version", 0)),
            },
        ))

        living = int(store.scalar("SELECT COUNT(*) FROM agents WHERE alive=1", default=0))
        citizens = int(store.scalar(
            "SELECT COUNT(*) FROM agents WHERE alive=1 AND kind='citizen' AND role IS NULL",
            default=0))
        completed_tick = int(meta["tick"] or 0)
        checks.append(_check(
            "rehearsal_shape", "100-agent, ten-day rehearsal completed",
            living == target_agents and completed_tick >= target_ticks,
            {
                "living_agents": living, "citizens": citizens,
                "completed_tick": completed_tick, "target_agents": target_agents,
                "target_ticks": target_ticks,
            },
        ))

        initial_distribution = {tier: 0 for tier in PLAN_TIERS}
        for row in store.query(
            "SELECT s.tier,COUNT(*) n FROM compute_subscriptions s "
            "JOIN agents a ON a.id=s.agent_id "
            "WHERE s.created_tick=0 AND s.reason='citizen_launch_grant' "
            "AND a.kind='citizen' AND a.role IS NULL GROUP BY s.tier"):
            initial_distribution[str(row["tier"])] = int(row["n"])
        expected_distribution = _expected_distribution(
            citizens, cognition.get(
                "initial_distribution", {"local": 0.5, "flash": 0.4, "premium": 0.1}))
        checks.append(_check(
            "initial_distribution", "Initial citizen compute distribution is exact",
            initial_distribution == expected_distribution,
            {"actual": initial_distribution, "expected": expected_distribution},
        ))

        bad_duration = int(store.scalar(
            "SELECT COUNT(*) FROM compute_subscriptions WHERE expiry_tick-effective_tick<>?",
            (duration,), default=0))
        bad_n_plus_one = int(store.scalar(
            "SELECT COUNT(*) FROM compute_subscriptions WHERE created_tick>0 "
            "AND payer_type IN ('agent','firm') AND effective_tick<>created_tick+1",
            default=0))
        bad_boundaries = int(store.scalar(
            "SELECT COUNT(*) FROM compute_subscriptions s WHERE s.created_tick>0 "
            "AND s.payer_type IN ('agent','firm') AND NOT EXISTS ("
            "SELECT 1 FROM compute_subscriptions prior WHERE prior.agent_id=s.agent_id "
            "AND prior.id<s.id AND prior.expiry_tick=s.effective_tick)",
            default=0))
        reason_counts = {
            str(row["reason"]): int(row["n"])
            for row in store.query(
                "SELECT reason,COUNT(*) n FROM compute_subscriptions GROUP BY reason")
        }
        action_subscriptions = sum(
            reason_counts.get(reason, 0)
            for reason in ("self_purchased", "self_cancelled", "employer_sponsored"))
        scheduled_tier_switches = 0
        for event in store.query(
                "SELECT payload_json FROM events WHERE kind='compute_plan_changed' "
                "ORDER BY tick,id"):
            try:
                payload = json.loads(str(event["payload_json"] or "{}"))
            except (TypeError, json.JSONDecodeError):
                continue
            if (
                payload.get("reason") == "scheduled_activation"
                and payload.get("old_tier") != payload.get("new_tier")
            ):
                scheduled_tier_switches += 1
        exercised = {
            "expired": int(store.scalar(
                "SELECT COUNT(*) FROM compute_subscriptions WHERE status='expired'", default=0)),
            "free_renewals": reason_counts.get("free_local_renewal", 0),
            "institutional_renewals": reason_counts.get("institutional_sponsorship", 0),
            "action_subscriptions": action_subscriptions,
            "employer_sponsorships": reason_counts.get("employer_sponsored", 0),
            "scheduled_tier_switches": scheduled_tier_switches,
        }
        checks.append(_check(
            "subscription_contract", "Seven-tick terms, renewal boundaries, and N+1 switching",
            bad_duration == 0 and bad_n_plus_one == 0 and bad_boundaries == 0
            and all(value > 0 for value in exercised.values()),
            {
                "bad_duration_rows": bad_duration,
                "bad_n_plus_one_rows": bad_n_plus_one,
                "bad_boundary_rows": bad_boundaries,
                **exercised,
            },
        ))

        paid_subscription_cents = int(store.scalar(
            "SELECT COALESCE(SUM(price_cents),0) FROM compute_subscriptions "
            "WHERE created_tick>0", default=0))
        compute_revenue_cents = int(store.scalar(
            "SELECT COALESCE(SUM(le.delta_cents),0) FROM ledger_entries le "
            "JOIN accounts a ON a.id=le.account_id "
            "JOIN transactions t ON t.id=le.txn_id "
            "WHERE a.label=? AND t.kind IN "
            "('compute_subscription','compute_sponsorship','public_compute_sponsorship')",
            (SYS_COMPUTE,), default=0))
        study_rows = int(store.scalar(
            "SELECT COUNT(*) FROM agent_skill_history WHERE source LIKE 'study:%'",
            default=0))
        expected_study_cents = study_rows * int(cognition.get("study_cost_cents", 5000))
        education_revenue_cents = int(store.scalar(
            "SELECT COALESCE(SUM(le.delta_cents),0) FROM ledger_entries le "
            "JOIN accounts a ON a.id=le.account_id "
            "JOIN transactions t ON t.id=le.txn_id "
            "WHERE a.label=? AND t.kind='skill_study'",
            (SYS_EDUCATION,), default=0))
        ledger_ok, ledger_diag = Ledger(store).reconcile()
        checks.append(_check(
            "balanced_services", "Compute and education payments settle in balanced accounts",
            ledger_ok and paid_subscription_cents == compute_revenue_cents
            and expected_study_cents == education_revenue_cents,
            {
                "paid_subscription_cents": paid_subscription_cents,
                "compute_revenue_cents": compute_revenue_cents,
                "expected_study_cents": expected_study_cents,
                "education_revenue_cents": education_revenue_cents,
                "ledger": ledger_diag,
            },
        ))

        living_with_eight = int(store.scalar(
            "SELECT COUNT(*) FROM (SELECT a.id FROM agents a JOIN agent_skills s "
            "ON s.agent_id=a.id WHERE a.alive=1 GROUP BY a.id HAVING COUNT(*)=8)",
            default=0))
        history_audit = _skill_history_audit(store)
        checks.append(_check(
            "skill_history", "Skill XP is complete and bound to accepted proposals",
            living_with_eight == living and bool(history_audit["passed"]),
            {"living_with_eight_skills": living_with_eight, **history_audit},
        ))

        forbidden_calls = int(store.scalar(
            "SELECT COUNT(*) FROM llm_calls WHERE lower(provider) IN "
            "('scripted','mock','replay') OR lower(model) IN ('scripted','mock')",
            default=0))
        call_count = int(store.scalar("SELECT COUNT(*) FROM llm_calls", default=0))
        unlinked_calls = int(store.scalar(
            "SELECT COUNT(*) FROM llm_calls c WHERE NOT EXISTS ("
            "SELECT 1 FROM llm_attempts a WHERE a.llm_call_id=c.id)",
            default=0))
        configured_providers = set((config.get("llm", {}).get("providers", {}) or {}).keys())
        successful_providers = {
            str(row["provider"])
            for row in store.query(
                "SELECT DISTINCT provider FROM llm_attempts WHERE outcome='success'")
        }
        checks.append(_check(
            "live_provenance", "Every routed provider is live with no mock/scripted calls",
            call_count > 0 and forbidden_calls == 0 and unlinked_calls == 0
            and configured_providers <= successful_providers,
            {
                "llm_calls": call_count, "forbidden_calls": forbidden_calls,
                "unlinked_calls": unlinked_calls,
                "configured_providers": sorted(configured_providers),
                "successful_providers": sorted(successful_providers),
            },
        ))

        peak_concurrency = max(
            int(store.scalar(
                "SELECT COALESCE(MAX(global_peak_observed),0) FROM llm_attempts",
                default=0)),
            int(store.scalar(
                "SELECT COALESCE(MAX(peak_live_in_flight),0) FROM runtime_tick_stats",
                default=0)),
        )
        checks.append(_check(
            "parallelism", "At least ten live calls overlapped",
            peak_concurrency >= min_peak,
            {"peak_concurrency": peak_concurrency, "required": min_peak},
        ))

        tick_rows = store.query(
            "SELECT tick,wall_ms FROM runtime_tick_stats ORDER BY tick")
        measured = [float(row["wall_ms"]) for row in tick_rows if int(row["tick"]) <= completed_tick]
        median_ms = _percentile(measured, 0.50)
        p95_ms = _percentile(measured, 0.95)
        checks.append(_check(
            "day_latency", "Median and p95 simulated-day latency meet the target",
            len(measured) >= target_ticks and median_ms is not None and p95_ms is not None
            and median_ms < median_limit_ms and p95_ms < p95_limit_ms,
            {
                "samples": len(measured), "median_ms": median_ms, "p95_ms": p95_ms,
                "median_limit_ms": median_limit_ms, "p95_limit_ms": p95_limit_ms,
            },
        ))

        provider_rows = [dict(row) for row in store.query(
            "SELECT provider,model,COUNT(*) attempts,"
            "SUM(CASE WHEN outcome='success' THEN 1 ELSE 0 END) successes,"
            "SUM(CASE WHEN outcome<>'success' THEN 1 ELSE 0 END) failures,"
            "SUM(rate_limited) rate_limits,SUM(fallback_used) fallbacks,"
            "ROUND(AVG(queue_wait_ms),3) avg_queue_ms,"
            "ROUND(AVG(provider_latency_ms),3) avg_response_ms "
            "FROM llm_attempts GROUP BY provider,model ORDER BY provider,model")]
        spend_rows = [dict(row) for row in store.query(
            "SELECT provider,model,COUNT(*) calls,SUM(in_tokens) in_tokens,"
            "SUM(out_tokens) out_tokens,ROUND(SUM(cost_usd),8) cost_usd "
            "FROM llm_calls GROUP BY provider,model ORDER BY provider,model")]

        probe_payload: dict[str, Any] | None = None
        if live_probe is not None:
            probe_path = Path(live_probe).resolve()
            probe_payload = json.loads(probe_path.read_text(encoding="utf-8"))
            probe_ok = bool(
                probe_payload.get("passed")
                and probe_payload.get("timeout_fallback", {}).get("ok")
                and probe_payload.get("rate_limit_fallback", {}).get("ok"))
            probe_evidence = {
                "path": str(probe_path), "scope": probe_payload.get("scope"),
                "available_providers": probe_payload.get("available_providers", []),
                "checks": probe_payload.get("checks", {}),
            }
        else:
            probe_ok = False
            probe_evidence = {"path": None, "reason": "live probe receipt not supplied"}
        checks.append(_check(
            "fault_probe", "Timeout and rate-limit faults complete through real fallback",
            probe_ok, probe_evidence,
        ))

        replay_proof: dict[str, Any] | None = None
        if replay_database is not None:
            replay_path = resolve_run_db(replay_database).resolve()
            replay_proof = verify_replay(db, replay_path)
            replay_ok = bool(replay_proof.get("exact"))
            replay_evidence = {
                "database": str(replay_path), "exact": replay_proof.get("exact"),
                "differences": replay_proof.get("differences", []),
            }
        else:
            replay_ok = False
            replay_evidence = {"database": None, "reason": "replay database not supplied"}
        checks.append(_check(
            "exact_replay", "Recorded live calls rebuild an exact offline replay",
            replay_ok, replay_evidence,
        ))

        return {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "run": {
                "run_id": str(meta["run_id"]), "database": str(db),
                "status": str(meta["status"]), "tick": completed_tick,
                "seed": int(meta["seed"]),
            },
            "passed": all(check["passed"] for check in checks),
            "checks": checks,
            "provider_attempts": provider_rows,
            "provider_spend": spend_rows,
            "probe": probe_payload,
            "replay": replay_proof,
        }
    finally:
        store.close()


def write_cognition_acceptance_report(
    database: str | Path,
    output: str | Path,
    *,
    live_probe: str | Path | None = None,
    replay_database: str | Path | None = None,
) -> dict[str, Any]:
    report = build_cognition_acceptance_report(
        database, live_probe=live_probe, replay_database=replay_database)
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(destination)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", help="run id or path to the live source database")
    parser.add_argument("--probe", required=True, help="full live cognition probe JSON")
    parser.add_argument("--replay", required=True, help="exact replay run id or database path")
    parser.add_argument("--output", required=True, help="destination JSON receipt")
    args = parser.parse_args()
    report = write_cognition_acceptance_report(
        args.run, args.output, live_probe=args.probe, replay_database=args.replay)
    print(json.dumps({
        "passed": report["passed"], "run": report["run"],
        "output": str(Path(args.output).resolve()),
        "failed_checks": [
            check["id"] for check in report["checks"] if not check["passed"]],
    }, indent=2, sort_keys=True))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from engine.ledger import Leg, Ledger, SYS_GOV
from engine.checkpoint_manifest import write_checkpoint_manifest
from engine.store import Store
import reports.oracle_campaign as oracle_campaign
import run as run_cli
from reports.oracle_campaign import (
    OracleCampaignError,
    RELEASE_CAMPAIGN_ID,
    RELEASE_CAMPAIGN_VERSION,
    RELEASE_COMMITMENT_SHA256,
    RELEASE_MAX_STANDARD_PROMPT_TOKENS,
    RELEASE_ORACLE_ADAPTER,
    RELEASE_ORACLE_MODEL,
    RELEASE_ORACLE_PRICING,
    RELEASE_ORACLE_PROVIDER,
    RELEASE_PROFILES,
    RELEASE_SEEDS,
    _expected_replay_tracker,
    _parse_governed_json_text,
    _openai_metering_evidence,
    effective_config_sha256,
    evaluate_oracle_campaign,
    finalize_sqlite_artifact,
    mark_oracle_campaign_initialized,
    prepare_oracle_campaign_run,
    validate_oracle_campaign_profile,
    write_oracle_campaign_package,
    write_oracle_source_receipt,
    write_replay_execution_receipt,
)
from oracle.analyst import (
    ANSWER_SYSTEM, PLANNER_SYSTEM, MAX_ANSWER_USER_CHARS,
    _answer_user_json, _bound_prompt_evidence,
)
from oracle.tools import (
    MAX_PROMPT_EVIDENCE_CHARS, ORACLE_PREFLIGHT_CONTRACT,
    OracleToolError, bound_oracle_evidence,
    canonical_oracle_json, oracle_tool_definitions,
    validate_bounded_oracle_evidence, validate_oracle_plan,
    validate_oracle_tool_args,
)
from run import (
    _close_run, _initialize_claimed_oracle_genesis, main, open_run,
    replay_headless,
    validate_open_oracle_campaign_source,
)
from run_config import load_config
from world.loop import World
from world.replay_verify import verify_replay


_TEST_REVISION = {"git_commit": "1" * 40, "git_tree": "2" * 40}
_FIRST_SEED = RELEASE_SEEDS[0]
_SECOND_SEED = RELEASE_SEEDS[1]
_FIRST_PROFILE = f"runs/oracle/{RELEASE_PROFILES[_FIRST_SEED]}"
_SECOND_PROFILE = f"runs/oracle/{RELEASE_PROFILES[_SECOND_SEED]}"
_FIRST_RUN_ID = f"{RELEASE_CAMPAIGN_ID}-s{_FIRST_SEED}"


@pytest.fixture(autouse=True)
def _canonical_test_campaign_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(oracle_campaign, "RELEASE_DATA_DIR", tmp_path.resolve())
    monkeypatch.setattr(
        oracle_campaign, "RELEASE_CHECKPOINT_DIR",
        (tmp_path / "data" / "checkpoints").resolve())
    monkeypatch.setattr(
        oracle_campaign, "get_clean_git_revision",
        lambda repo_root=None: dict(_TEST_REVISION))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_checkpoint(
        path: Path, source: Store, run_id: str, seed: int, tick: int,
        config: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    source.commit()
    destination = sqlite3.connect(path)
    try:
        source.conn.backup(destination)
    finally:
        destination.close()
    checkpoint = Store(str(path), create=False)
    checkpoint.execute("DELETE FROM metrics WHERE tick>?", (tick,))
    checkpoint.execute("DELETE FROM events WHERE tick>?", (tick,))
    checkpoint.execute("DELETE FROM llm_calls WHERE tick>?", (tick,))
    checkpoint.execute("DELETE FROM predictions WHERE asked_tick>?", (tick,))
    checkpoint.execute(
        "DELETE FROM acceptance_checkpoints WHERE scheduled_tick>?", (tick,))
    checkpoint.execute("DELETE FROM transactions WHERE tick>?", (tick,))
    checkpoint.execute("DELETE FROM ledger_entries WHERE tick>?", (tick,))
    checkpoint.execute("DELETE FROM agents WHERE arrived_tick>?", (tick,))
    checkpoint.execute(
        "UPDATE agents SET alive=1,died_tick=NULL WHERE died_tick>?", (tick,))
    engine = random.Random(seed).getstate()
    persona = random.Random(seed ^ 0xA11CE).getstate()
    lifecycle = random.Random(seed ^ 0x5F5E5F).getstate()
    engine_state = [engine[0], list(engine[1]), engine[2]]
    persona_state = [persona[0], list(persona[1]), persona[2]]
    checkpoint.set_meta(
        tick=tick, status="running", phase="FINALIZE", active_tick=None,
        next_phase="NIGHT_CLOSE", phase_state_json="{}",
        prng_state=json.dumps({
            "engine": engine_state, "persona": persona_state,
        }),
        lifecycle_prng_state=json.dumps(
            [lifecycle[0], list(lifecycle[1]), lifecycle[2]]),
        governor_json="{}")
    checkpoint.commit()
    checkpoint.close()
    finalize_sqlite_artifact(path)
    write_checkpoint_manifest(path)


def _write_run(
    tmp_path: Path, index: int, *, invalid_provider: bool = False,
    invalid_evidence: bool = False,
    planner_retry: bool = False,
    planner_retry_invalid_args: bool = False,
    planner_retry_shape: str = "empty_queries",
    planner_retry_twice: bool = False,
    planner_retry_same_error: bool = False,
    planner_rejection_state: str = "valid",
    planner_rejection_attempt: int | float | bool = 1,
    lifecycle_replacement: bool = False,
    receipt_dir: Path | None = None,
) -> dict:
    if planner_retry_shape not in {
            "empty_queries", "canonical_noop", "non_list", "invalid_args",
            "long_error", "missing_entity", "future_tick",
            "extra_query_field", "valid"}:
        raise ValueError(f"unsupported planner retry shape: {planner_retry_shape}")
    if planner_rejection_state not in {
            "valid", "missing", "missing_second", "mismatched_error",
            "forged_pair", "misordered_second", "truncated_context"}:
        raise ValueError(f"unsupported planner rejection state: {planner_rejection_state}")
    seed = RELEASE_SEEDS[index]
    run_id = f"{RELEASE_CAMPAIGN_ID}-s{seed}"
    profile_path = (Path("runs/oracle") / RELEASE_PROFILES[seed]).resolve()
    profile = load_config(profile_path)
    claim = prepare_oracle_campaign_run(
        profile, profile_path, data_dir=tmp_path)
    db_path = tmp_path / f"{run_id}.db"
    store = Store(str(db_path))
    store.init_run_meta(run_id, seed, profile)
    store.set_meta(tick=335, status="finished")
    for agent_index in range(65):
        store.insert(
            "agents", name=f"Citizen {agent_index}", kind="citizen", alive=1,
            population_tier="core", pinned_core=1)
    staff_roles = {
        "central_banker": 1, "competition_regulator": 1,
        "credit_officer": 2, "editor": 2, "exchange": 1,
        "executive": 1, "gov_official": 1, "labor_regulator": 1,
        "lawyer": 1, "legislator_house": 12, "legislator_senate": 6,
        "lobbyist": 2, "regulator": 1, "reporter": 2, "vc_partner": 1,
    }
    for role, count in staff_roles.items():
        for role_index in range(count):
            store.insert(
                "agents", name=f"{role}-{role_index}", kind="staff",
                role=role, alive=1, population_tier="core", pinned_core=1)
    ledger = Ledger(store)
    positive = ledger.ensure_system_account("unit:positive")
    negative = ledger.ensure_system_account("unit:negative")
    ledger.post(0, "unit_genesis", [
        Leg(positive, 100, "unit"), Leg(negative, -100, "unit"),
    ])
    for bank_index in (1, 2):
        reserve = ledger.create_account(
            "bank", bank_index, "reserve", label=f"Bank {bank_index} reserve")
        equity = ledger.create_account(
            "bank", bank_index, "equity", label=f"Bank {bank_index} equity")
        store.insert(
            "banks", id=bank_index, name=f"Bank {bank_index}",
            risk_policy_json="{}", reserve_requirement_bps=1000,
            status="open", reserve_account_id=reserve,
            equity_account_id=equity, currency_code="USD")
    for firm_index in range(14):
        store.insert(
            "firms", name=f"Firm {firm_index}", sector="unit",
            status="private", product_json="{}")
    if lifecycle_replacement:
        store.execute(
            "UPDATE agents SET alive=0,died_tick=207 WHERE id=1")
        arrival_id = store.insert(
            "agents", name="Replacement Citizen", kind="citizen", alive=1,
            arrived_tick=221, population_tier="core", pinned_core=1)
        store.log_event(207, "death", {
            "agent_id": 1, "name": "Citizen 0", "cause": "natural",
        }, phase="NIGHT_CLOSE", subject_type="agent", subject_id=1)
        schedule_event_id = store.log_event(
            207, "arrival_scheduled", {"due_tick": 221},
            phase="NIGHT_CLOSE")
        store.log_event(221, "arrival", {
            "agent_id": arrival_id, "name": "Replacement Citizen",
            "schedule_event_id": schedule_event_id,
        }, phase="NIGHT_CLOSE", subject_type="agent", subject_id=arrival_id)
    outcome = index % 2
    question_ticks = {
        int(item["at_tick"])
        for item in profile["acceptance"]["oracle_questions"]
    }
    for metric_tick in range(336):
        store.record_metric(metric_tick, "unit_metric", 1.0)
        deposits = 500.0 if outcome and metric_tick - 1 in question_ticks else 1000.0
        for bank_index in (1, 2):
            store.record_metric(
                metric_tick, f"bank_deposits:{bank_index}", deposits)
    store.log_event(0, "genesis", {"banks": 2, "agents": 100, "firms": 14})
    checkpoint_ticks = sorted({
        *range(10, 335, 10), *question_ticks, 335,
    })
    for tick in checkpoint_ticks:
        checkpoint_path = (
            tmp_path / "data" / "checkpoints" / f"{run_id}_t{tick}.db")
        _write_checkpoint(
            checkpoint_path, store, run_id, seed, tick, profile)
        store.insert("checkpoints", tick=tick, path=str(checkpoint_path.resolve()))
    for shock in profile.get("shocks", []):
        tick = int(shock["trigger_params"]["tick"])
        requested = int(shock["params"]["n_agents"])
        targets = list(range(1, min(requested, 40) + 1))
        shock_id = store.insert(
            "shocks", kind=shock["kind"], trigger_type=shock["trigger"],
            trigger_json=json.dumps(shock["trigger_params"]),
            duration_ticks=0, params_json=json.dumps(shock["params"]),
            label=shock["label"], fired=1, fired_tick=tick)
        resolved_params = {
            **shock["params"], "resolved_bank_id": 1, "bank_id": 1,
            "target_agent_ids": targets,
        }
        store.log_event(tick, "rumor", {
            "bank_id": 1, "n_agents": len(targets),
            "target_agent_ids": targets, "text": "unit precursor",
            "truthful": False, "bank_selector": "largest_by_deposits",
            "audience": shock["params"]["audience"],
        })
        store.log_event(tick, "shock_fired", {
            "shock_id": shock_id, "kind": "rumor", "label": shock["label"],
            "params": resolved_params, "trigger_type": "shock",
            "duration_ticks": 0,
        })
    probability = 0.9 if outcome else 0.1
    for item in profile["acceptance"]["oracle_questions"]:
        tick = int(item["at_tick"])
        provider = (
            "made-up-provider"
            if invalid_provider and tick == 5 else RELEASE_ORACLE_PROVIDER)
        governed_contract = {
            "campaign_id": RELEASE_CAMPAIGN_ID,
            "campaign_version": RELEASE_CAMPAIGN_VERSION,
            "campaign_key": item["campaign_key"],
            "scheduled_tick": tick,
            "resolution_rule": item["expected_rule"],
            "deadline_tick": tick + 30,
        }
        selected_retry_shape = (
            "invalid_args" if planner_retry_invalid_args
            else planner_retry_shape)
        retry_plan_by_shape = {
            "empty_queries": {"queries": []},
            "canonical_noop": {
                "actions": [{"type": "do_nothing"}],
                "reasoning": "unparseable output; no-op",
            },
            "non_list": {"queries": "invalid"},
            "invalid_args": {
                "queries": [{
                    "tool": "get_ledger_summary",
                    "args": {
                        "entity_type": "agent", "entity_id": 1,
                        "from_tick": 0, "to_tick": tick,
                    },
                }],
            },
            "long_error": {
                "queries": [{
                    "tool": "get_ledger_summary",
                    "args": {
                        "entity_type": "agent", "entity_id": 1,
                        **{
                            f"unexpected_argument_{argument:03d}": argument
                            for argument in range(40)
                        },
                    },
                }],
            },
            "missing_entity": {
                "queries": [{
                    "tool": "get_ledger_summary",
                    "args": {"entity_type": "bank", "entity_id": 99999},
                }],
            },
            "future_tick": {
                "queries": [{
                    "tool": "query_metrics",
                    "args": {
                        "names": ["unit_metric"],
                        "from_tick": tick, "to_tick": tick + 1,
                    },
                }],
            },
            "extra_query_field": {
                "queries": [{
                    "tool": "query_metrics",
                    "args": {"names": ["unit_metric"]},
                    "comment": "untrusted planner annotation",
                }],
            },
            "valid": {
                "queries": [{
                    "tool": "query_metrics",
                    "args": {"names": ["unit_metric"]},
                }],
            },
        }
        rejected_plans = [retry_plan_by_shape[selected_retry_shape]]
        if planner_retry_twice:
            rejected_plans.append(
                retry_plan_by_shape[selected_retry_shape]
                if planner_retry_same_error else {"queries": []})
        rejection_errors: list[str] = []
        tool_catalog = oracle_tool_definitions(store, tick=tick)
        for rejected_plan in rejected_plans:
            try:
                validate_oracle_plan(
                    rejected_plan, current_tick=tick,
                    tool_catalog=tool_catalog)
            except OracleToolError as exc:
                rejection_errors.append(str(exc))
            else:
                rejection_errors.append("forged planner rejection error")
        purposes = (
            tuple(["oracle_plan"] * (len(rejected_plans) + 1) + ["oracle"])
            if planner_retry and tick == 5 else ("oracle_plan", "oracle"))
        model_calls = []
        plan_number = 0
        for purpose in purposes:
            base_context = {
                "question": item["question"], "tick": tick,
                "governed_forecast_contract": governed_contract,
            }
            if purpose == "oracle_plan":
                plan_number += 1
            response = (
                (rejected_plans[plan_number - 1]
                 if planner_retry and tick == 5
                 and purpose == "oracle_plan"
                 and plan_number <= len(rejected_plans) else
                 {"queries": [{
                    "tool": "query_metrics",
                    "args": {"names": ["unit_metric"]},
                }]})
                if purpose == "oracle_plan" else {
                    "p": probability,
                    "drivers": ["deposit trust", "reserve ratio"],
                    "confidence": "med",
                    "resolution_rule": item["expected_rule"],
                    "deadline_tick": tick + 30,
                    "reasoning": "bounded forecast",
                })
            evidence = [{
                "tool": "query_metrics", "args": {"names": ["unit_metric"]},
                "result": {"rows": []},
            }]
            if purpose == "oracle_plan":
                context = {
                    **base_context,
                    "preflight_contract": ORACLE_PREFLIGHT_CONTRACT,
                    "available_tools": tool_catalog,
                    "constraints": {
                        "tick_range": {"minimum": 0, "maximum": tick},
                        "maximum_queries": 8, "read_only": True,
                    },
                }
                if (planner_retry and tick == 5 and plan_number > 1
                        and plan_number <= len(rejected_plans) + 1):
                    retry_error = rejection_errors[plan_number - 2]
                    if planner_rejection_state == "forged_pair":
                        retry_error = "jointly forged planner rejection error"
                    elif planner_rejection_state == "truncated_context":
                        retry_error = retry_error[:500]
                    context.update({
                        "previous_plan_error": retry_error,
                        "planner_attempt": plan_number,
                        "instruction": (
                            "Return a corrected plan that satisfies every supplied constraint."),
                    })
                user_payload = context
            else:
                context = {
                    **base_context, "evidence": evidence,
                    "prompt_world": {"unit": True},
                }
                user_payload = {
                    "governed_forecast_contract": governed_contract,
                    "question": item["question"], "tick": tick,
                    "read_only_evidence": evidence,
                    "world": context["prompt_world"],
                }
            user_text = canonical_oracle_json(user_payload)
            system = PLANNER_SYSTEM if purpose == "oracle_plan" else ANSWER_SYSTEM
            cache_key = hashlib.sha1(json.dumps({
                "t": tick, "a": None, "p": purpose,
                "m": RELEASE_ORACLE_MODEL,
                "msgs": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_text},
                ],
            }, sort_keys=True).encode()).hexdigest()
            response_id = f"chatcmpl-{run_id}-{tick}-{purpose}-{plan_number}"

            def provider_payload(suffix: str = "") -> dict:
                return {
                    "id": f"{response_id}{suffix}",
                    "model": RELEASE_ORACLE_MODEL,
                    "object": "chat.completion",
                    "usage": {
                        "prompt_tokens": 10, "completion_tokens": 10,
                        "prompt_tokens_details": {"cached_tokens": 0},
                    },
                }

            is_canonical_noop = response == {
                "actions": [{"type": "do_nothing"}],
                "reasoning": "unparseable output; no-op",
            }
            raw_response = (
                {"provider_calls": 2, "repair": {
                    "initial": provider_payload("-initial"),
                    "final": provider_payload("-final"),
                }}
                if is_canonical_noop else provider_payload())
            token_multiplier = 2 if is_canonical_noop else 1
            prompt_tokens = completion_tokens = 10 * token_multiplier
            store.insert(
                "llm_calls", tick=tick, role="oracle", purpose=purpose,
                provider=provider, model=RELEASE_ORACLE_MODEL,
                cache_key=cache_key,
                request_json=json.dumps({
                    "system": system, "user": user_text,
                    "context": context,
                }),
                response_json=json.dumps({
                    "text": json.dumps(response),
                    "raw": raw_response,
                    "cached_in_tokens": 0,
                }),
                in_tokens=prompt_tokens, out_tokens=completion_tokens,
                cost_usd=(
                    prompt_tokens * RELEASE_ORACLE_PRICING["in"] / 1_000_000
                    + completion_tokens
                    * RELEASE_ORACLE_PRICING["out"] / 1_000_000),
                latency_ms=10)
            model_calls.append({
                "purpose": purpose, "provider": provider,
                "model": RELEASE_ORACLE_MODEL,
                "request_key": cache_key, "call_latency_ms": 10,
            })
            if (planner_retry and tick == 5 and purpose == "oracle_plan"
                    and plan_number <= len(rejected_plans)
                    and planner_rejection_state != "missing"
                    and not (planner_rejection_state == "missing_second"
                             and plan_number == 2)):
                plan_hash = hashlib.sha256(json.dumps(
                    response, sort_keys=True, separators=(",", ":"),
                ).encode("utf-8")).hexdigest()
                event_error = rejection_errors[plan_number - 1]
                if planner_rejection_state == "mismatched_error":
                    event_error = "forged planner rejection error"
                elif planner_rejection_state == "forged_pair":
                    event_error = "jointly forged planner rejection error"
                else:
                    event_error = event_error[:500]
                event_attempt = (
                    1 if planner_rejection_state == "misordered_second"
                    and plan_number == 2
                    else planner_rejection_attempt
                    if plan_number == 1 else plan_number)
                store.log_event(tick, "oracle_tool_plan_rejected", {
                    "question": item["question"],
                    "attempt": event_attempt,
                    "plan_sha256": plan_hash,
                    "error": event_error,
                })
        prediction_id = store.insert(
            "predictions", asked_tick=tick, question=item["question"],
            p=probability, reasoning="bounded forecast",
            drivers_json=json.dumps(
                ["x" * 500 for _ in range(11)]
                if invalid_evidence and tick == 5
                else ["deposit trust", "reserve ratio"]),
            confidence="med",
            resolution_rule_json=json.dumps(item["expected_rule"]),
            deadline_tick=tick + 30, resolved_tick=tick + (1 if outcome else 30),
            outcome=outcome, brier=(probability - outcome) ** 2,
            evidence_json=json.dumps(
                [{"tool": "shell_exec", "args": {}, "result": "unsafe"}]
                if invalid_evidence and tick == 5 else [{
                    "tool": "query_metrics", "args": {"names": ["unit_metric"]},
                    "result": {"rows": []},
                }]), status="resolved")
        store.insert(
            "acceptance_checkpoints", scheduled_tick=tick,
            question=item["question"], status="completed",
            prediction_id=prediction_id)
        store.log_event(tick, "oracle_prediction", {
            "prediction_id": prediction_id, "question": item["question"],
            "p": probability, "deadline_tick": tick + 30,
            "rule": item["expected_rule"],
        })
        store.log_event(tick + (1 if outcome else 30), "prediction_resolved", {
            "prediction_id": prediction_id, "question": item["question"],
            "p": probability, "outcome": outcome,
            "brier": (probability - outcome) ** 2,
        })
        store.log_event(tick, "acceptance_checkpoint_completed", {
            "scheduled_tick": tick,
            "question": item["question"],
            "prediction_id": prediction_id,
            "latency_ms": 100 + index,
            "latency_kind": "scheduled_e2e_v1",
            "campaign_id": RELEASE_CAMPAIGN_ID,
            "campaign_version": RELEASE_CAMPAIGN_VERSION,
            "campaign_key": item["campaign_key"],
            "model_calls": model_calls,
            "latency_measurement": "continuous_monotonic",
        })
    store.commit()
    store.close()
    finalize_sqlite_artifact(db_path)
    mark_oracle_campaign_initialized(claim, db_path)
    replay_path = tmp_path / f"replay-{run_id}.db"
    shutil.copyfile(db_path, replay_path)
    replay = Store(str(replay_path), create=False)
    replay_config = dict(profile)
    replay_config.update({
        "seed": seed,
        "replay_source_path": str(db_path.resolve()),
        "replay_source_run_id": run_id,
        "replay_source_tick": 335,
    })
    replay.set_meta(
        run_id=f"replay-{run_id}", parent_run_id=run_id, fork_tick=0,
        tick=335, status="finished",
        config_json=json.dumps(replay_config))
    replay.close()
    finalize_sqlite_artifact(replay_path)
    expected = _expected_replay_tracker(db_path)
    tracker = {
        "schema_version": 1,
        **expected,
        "consumed_source_calls": expected["source_nonoperational_calls"],
        "consumed_logical_calls_sha256": expected["source_logical_calls_sha256"],
        "consumed_purpose_counts": expected["source_purpose_counts"],
        "oracle_consumed_calls": expected["oracle_source_calls"],
        "oracle_consumed_calls_sha256": expected["oracle_source_calls_sha256"],
        "exact_key_matches": expected["source_nonoperational_calls"],
        "compatibility_fallback_matches": 0,
        "live_dispatch_count": 0,
        "missing_source_calls": 0,
        "unexpected_source_calls": 0,
        "duplicate_source_consumptions": 0,
        "all_nonoperational_calls_consumed_once": True,
        "all_oracle_calls_consumed_once": True,
    }
    replay_receipt = write_replay_execution_receipt(
        db_path, replay_path, profile_path, replay_tracker=tracker,
        campaign_claim=claim,
        out_dir=receipt_dir or (tmp_path / "receipts"))
    source_receipt = write_oracle_source_receipt(
        db_path, replay_path, profile_path,
        replay_execution_receipt=replay_receipt["artifact"],
        campaign_claim=claim,
        out_dir=receipt_dir or (tmp_path / "receipts"))
    return source_receipt["manifest_entry"]


def _manifest(
    tmp_path: Path, *, invalid_provider: bool = False,
    invalid_evidence: bool = False,
    planner_retry: bool = False,
    planner_retry_invalid_args: bool = False,
    planner_rejection_state: str = "valid",
    planner_rejection_attempt: int | float | bool = 1,
) -> Path:
    runs = [
        _write_run(
            tmp_path, index,
            invalid_provider=invalid_provider and index == 0,
            invalid_evidence=invalid_evidence and index == 0,
            planner_retry=planner_retry and index == 0,
            planner_retry_invalid_args=(
                planner_retry_invalid_args and index == 0),
            planner_rejection_state=(
                planner_rejection_state if index == 0 else "valid"),
            planner_rejection_attempt=(
                planner_rejection_attempt if index == 0 else 1))
        for index in range(10)
    ]
    path = tmp_path / "oracle-campaign.yaml"
    path.write_text(yaml.safe_dump({
        "schema_version": 1,
        "campaign_id": RELEASE_CAMPAIGN_ID,
        "campaign_version": RELEASE_CAMPAIGN_VERSION,
        "commitment_sha256": RELEASE_COMMITMENT_SHA256,
        "minimum_runs": 10,
        "minimum_forecasts": 60,
        "p90_limit_ms": 60_000,
        "naive_brier": 0.25,
        "runs": runs,
    }, sort_keys=False), encoding="utf-8")
    return path


def _mutate_manifest_pair(manifest: Path, index: int, mutate) -> dict:
    payload = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    entry = payload["runs"][index]
    for field in ("database", "replay_database"):
        database = manifest.parent / entry[field]
        store = Store(str(database), create=False)
        mutate(store)
        store.commit()
        store.close()
    entry["database_sha256"] = _sha256(manifest.parent / entry["database"])
    entry["replay_database_sha256"] = _sha256(
        manifest.parent / entry["replay_database"])
    manifest.write_text(
        yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return entry


def test_curated_oracle_campaign_passes_and_is_read_only_deterministic(tmp_path):
    manifest = _manifest(tmp_path)
    before = {
        entry["database"]: _sha256(tmp_path / entry["database"])
        for entry in yaml.safe_load(manifest.read_text(encoding="utf-8"))["runs"]
    }

    first = evaluate_oracle_campaign(manifest)
    second = evaluate_oracle_campaign(manifest)

    assert first == second
    assert first["passed"] is True
    assert first["excluded_runs"] == []
    assert first["calibration"]["n"] == 60
    assert first["calibration"]["brier"] == pytest.approx(0.01)
    assert {check["id"]: check["passed"] for check in first["checks"]} == {
        "complete_manifest": True,
        "forecast_count": True,
        "outcome_diversity": True,
        "end_to_end_latency": True,
        "calibration": True,
        "sources_unchanged": True,
    }
    assert before == {
        name: _sha256(tmp_path / name) for name in before
    }

    package_a = write_oracle_campaign_package(
        manifest, out_dir=tmp_path / "out-a")
    package_b = write_oracle_campaign_package(
        manifest, out_dir=tmp_path / "out-b")
    assert Path(package_a["artifacts"]["json"]).read_bytes() == Path(
        package_b["artifacts"]["json"]).read_bytes()
    assert Path(package_a["artifacts"]["markdown"]).read_bytes() == Path(
        package_b["artifacts"]["markdown"]).read_bytes()


def test_curated_oracle_campaign_excludes_non_live_run_with_reasons(tmp_path):
    manifest = _manifest(tmp_path, invalid_provider=True)

    receipt = evaluate_oracle_campaign(manifest)

    assert receipt["passed"] is False
    assert receipt["calibration"]["n"] == 54
    assert receipt["excluded_runs"][0]["run_id"] == _FIRST_RUN_ID
    excluded = next(run for run in receipt["runs"] if not run["eligible"])
    assert any(
        "configured Oracle route" in reason or "model-call route" in reason
        for forecast in excluded["forecasts"]
        for reason in forecast["reasons"])
    checks = {check["id"]: check for check in receipt["checks"]}
    assert checks["complete_manifest"]["passed"] is False
    assert checks["forecast_count"]["passed"] is False
    assert checks["sources_unchanged"]["passed"] is True


def test_oracle_campaign_manifest_cannot_weaken_release_sample_floor(tmp_path):
    manifest = tmp_path / "too-small.yaml"
    manifest.write_text(yaml.safe_dump({
        "schema_version": 1,
        "campaign_id": RELEASE_CAMPAIGN_ID,
        "campaign_version": RELEASE_CAMPAIGN_VERSION,
        "commitment_sha256": RELEASE_COMMITMENT_SHA256,
        "minimum_runs": 1,
        "minimum_forecasts": 1,
        "runs": [],
    }), encoding="utf-8")

    with pytest.raises(OracleCampaignError, match="minimum_runs must be"):
        evaluate_oracle_campaign(manifest)


def test_oracle_campaign_manifest_cannot_weaken_latency_gate(tmp_path):
    manifest = tmp_path / "weak-latency.yaml"
    manifest.write_text(yaml.safe_dump({
        "schema_version": 1,
        "campaign_id": RELEASE_CAMPAIGN_ID,
        "campaign_version": RELEASE_CAMPAIGN_VERSION,
        "commitment_sha256": RELEASE_COMMITMENT_SHA256,
        "minimum_runs": 10,
        "minimum_forecasts": 60,
        "p90_limit_ms": 999_999,
        "runs": [],
    }), encoding="utf-8")

    with pytest.raises(OracleCampaignError, match="hard 60000 ms gate"):
        evaluate_oracle_campaign(manifest)


def test_oracle_campaign_rejects_unknown_tools_and_unbounded_drivers(tmp_path):
    receipt = evaluate_oracle_campaign(
        _manifest(tmp_path, invalid_evidence=True))

    assert receipt["passed"] is False
    excluded = next(run for run in receipt["runs"] if not run["eligible"])
    reasons = {
        reason for forecast in excluded["forecasts"]
        for reason in forecast["reasons"]
    }
    assert "prediction tool evidence is missing, unknown, or unbounded" in reasons
    assert "prediction drivers are invalid" in reasons


def test_oracle_campaign_rejects_post_hoc_seed_substitution(tmp_path):
    manifest = _manifest(tmp_path)
    payload = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    payload["runs"][0]["seed"] = 9999
    manifest.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(OracleCampaignError, match="predeclared corpus"):
        evaluate_oracle_campaign(manifest)


def test_oracle_campaign_requires_exact_companion_replay(tmp_path):
    manifest = _manifest(tmp_path)
    payload = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    entry = payload["runs"][0]
    replay_path = tmp_path / entry["replay_database"]
    replay = Store(str(replay_path), create=False)
    replay.execute("UPDATE predictions SET p=0.55 WHERE id=1")
    replay.commit()
    replay.close()
    entry["replay_database_sha256"] = _sha256(replay_path)
    manifest.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    receipt = evaluate_oracle_campaign(manifest)
    assert receipt["passed"] is False
    excluded = next(run for run in receipt["runs"] if not run["eligible"])
    assert "companion replay is not exact for this source run" in excluded["reasons"]


def test_oracle_campaign_rejects_post_preflight_execution_failure_event(
        tmp_path):
    manifest = _manifest(tmp_path)

    def inject_failure(store):
        store.log_event(5, "oracle_tool_execution_failed", {
            "question": oracle_campaign.RELEASE_QUESTION,
            "error": "forced authenticated execution failure",
            "plan_sha256": "0" * 64,
        })

    entry = _mutate_manifest_pair(manifest, 0, inject_failure)
    receipt = evaluate_oracle_campaign(manifest)
    run = next(
        item for item in receipt["runs"]
        if item["run_id"] == entry["run_id"])

    assert run["eligible"] is False
    assert (
        "run contains provider/budget/reconciliation/execution failures"
        in run["reasons"])


def test_oracle_campaign_requires_replay_source_markers(tmp_path):
    manifest = _manifest(tmp_path)
    payload = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    entry = payload["runs"][0]
    replay_path = tmp_path / entry["replay_database"]
    replay = Store(str(replay_path), create=False)
    config = json.loads(replay.get_meta()["config_json"])
    config.pop("replay_source_run_id")
    replay.set_meta(config_json=json.dumps(config))
    replay.close()
    entry["replay_database_sha256"] = _sha256(replay_path)
    manifest.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    receipt = evaluate_oracle_campaign(manifest)
    excluded = next(run for run in receipt["runs"] if not run["eligible"])
    assert "companion replay source markers are invalid" in excluded["reasons"]


def test_oracle_campaign_rejects_self_asserted_unmetered_provider_calls(tmp_path):
    manifest = _manifest(tmp_path)
    payload = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    entry = payload["runs"][0]
    for field in ("database", "replay_database"):
        database = tmp_path / entry[field]
        store = Store(str(database), create=False)
        store.execute("UPDATE llm_calls SET cost_usd=0 WHERE tick=5")
        store.commit()
        store.close()
    entry["database_sha256"] = _sha256(tmp_path / entry["database"])
    entry["replay_database_sha256"] = _sha256(
        tmp_path / entry["replay_database"])
    manifest.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    receipt = evaluate_oracle_campaign(manifest)
    excluded = next(run for run in receipt["runs"] if not run["eligible"])
    assert any(
        "live metering evidence" in reason
        for forecast in excluded["forecasts"]
        for reason in forecast["reasons"])


def test_oracle_campaign_rejects_positive_metering_with_empty_provider_raw(tmp_path):
    manifest = _manifest(tmp_path)

    def erase_raw(store):
        row = store.query_one(
            "SELECT id,response_json FROM llm_calls WHERE tick=5 ORDER BY id LIMIT 1")
        response = json.loads(row["response_json"])
        response["raw"] = {}
        store.update(
            "llm_calls", int(row["id"]), response_json=json.dumps(response))

    _mutate_manifest_pair(manifest, 0, erase_raw)
    receipt = evaluate_oracle_campaign(manifest)
    first = next(run for run in receipt["runs"] if run["seed"] == _FIRST_SEED)
    assert any(
        "provider response usage is missing" in reason
        for reason in first["forecasts"][0]["reasons"])


def test_oracle_campaign_rejects_provider_usage_mismatch(tmp_path):
    manifest = _manifest(tmp_path)

    def alter_usage(store):
        row = store.query_one(
            "SELECT id,response_json FROM llm_calls WHERE tick=5 ORDER BY id LIMIT 1")
        response = json.loads(row["response_json"])
        response["raw"]["usage"]["prompt_tokens"] = 9
        store.update(
            "llm_calls", int(row["id"]), response_json=json.dumps(response))

    _mutate_manifest_pair(manifest, 0, alter_usage)
    receipt = evaluate_oracle_campaign(manifest)
    first = next(run for run in receipt["runs"] if run["seed"] == _FIRST_SEED)
    assert any(
        "does not reconcile to persisted token totals" in reason
        for reason in first["forecasts"][0]["reasons"])


def test_oracle_campaign_rejects_forged_positive_cost(tmp_path):
    manifest = _manifest(tmp_path)

    def forge_cost(store):
        row = store.query_one(
            "SELECT id FROM llm_calls WHERE tick=5 ORDER BY id LIMIT 1")
        store.update("llm_calls", int(row["id"]), cost_usd=0.12345678)

    _mutate_manifest_pair(manifest, 0, forge_cost)
    receipt = evaluate_oracle_campaign(manifest)
    first = next(run for run in receipt["runs"] if run["seed"] == _FIRST_SEED)
    assert any(
        "pinned release Oracle pricing" in reason
        for reason in first["forecasts"][0]["reasons"])


def test_openai_metering_accepts_valid_direct_and_gateway_repair_shapes():
    direct_cost = round(
        (10 * RELEASE_ORACLE_PRICING["in"]
         + 10 * RELEASE_ORACLE_PRICING["out"]) / 1_000_000,
        8,
    )
    direct_row = {
        "in_tokens": 10, "out_tokens": 10, "cost_usd": direct_cost,
    }
    direct_response = {
        "cached_in_tokens": 0,
        "raw": {"id": "chatcmpl-direct", "model": RELEASE_ORACLE_MODEL,
                "object": "chat.completion", "usage": {
            "prompt_tokens": 10, "completion_tokens": 10,
            "prompt_tokens_details": {"cached_tokens": 0},
        }},
    }
    direct, direct_reasons = _openai_metering_evidence(
        direct_row, direct_response)
    assert direct_reasons == []
    assert direct == {
        "shape": "direct", "response_ids": ["chatcmpl-direct"],
        "prompt_tokens": 10, "completion_tokens": 10,
        "cached_in_tokens": 0, "max_prompt_tokens": 10,
        "expected_cost_usd": direct_cost,
    }

    repair_cost = round(
        (8 * RELEASE_ORACLE_PRICING["in"]
         + 2 * RELEASE_ORACLE_PRICING["cache"]
         + 10 * RELEASE_ORACLE_PRICING["out"]) / 1_000_000,
        8,
    )
    repair_row = {
        "in_tokens": 10, "out_tokens": 10, "cost_usd": repair_cost,
    }
    repair_response = {
        "cached_in_tokens": 2,
        "raw": {"provider_calls": 2, "repair": {
            "initial": {"id": "chatcmpl-initial", "model": RELEASE_ORACLE_MODEL,
                        "object": "chat.completion", "usage": {
                "prompt_tokens": 4, "completion_tokens": 3,
                "prompt_tokens_details": {"cached_tokens": 1},
            }},
            "final": {"id": "chatcmpl-final", "model": RELEASE_ORACLE_MODEL,
                      "object": "chat.completion", "usage": {
                "prompt_tokens": 6, "completion_tokens": 7,
                "prompt_tokens_details": {"cached_tokens": 1},
            }},
        }},
    }
    repair, repair_reasons = _openai_metering_evidence(
        repair_row, repair_response)
    assert repair_reasons == []
    assert repair["shape"] == "repair"
    assert repair["response_ids"] == ["chatcmpl-initial", "chatcmpl-final"]
    assert repair["prompt_tokens"] == 10
    assert repair["completion_tokens"] == 10
    assert repair["cached_in_tokens"] == 2
    assert repair["max_prompt_tokens"] == 6
    assert repair["expected_cost_usd"] == repair_cost


def test_openai_metering_enforces_pinned_standard_pricing_tier_boundary():
    assert RELEASE_MAX_STANDARD_PROMPT_TOKENS == 512_000
    tier_reason = (
        "provider prompt exceeds the pinned release Oracle pricing tier")

    for prompt_tokens, rejected in ((512_000, False), (512_001, True)):
        cost = round(
            (prompt_tokens * RELEASE_ORACLE_PRICING["in"]
             + RELEASE_ORACLE_PRICING["out"]) / 1_000_000,
            8,
        )
        row = {
            "in_tokens": prompt_tokens, "out_tokens": 1,
            "cost_usd": cost,
        }
        response = {
            "cached_in_tokens": 0,
            "raw": {
                "id": f"chatcmpl-tier-{prompt_tokens}",
                "model": RELEASE_ORACLE_MODEL,
                "object": "chat.completion",
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": 1,
                    "prompt_tokens_details": {"cached_tokens": 0},
                },
            },
        }

        evidence, reasons = _openai_metering_evidence(row, response)

        assert evidence["max_prompt_tokens"] == prompt_tokens
        assert (tier_reason in reasons) is rejected


def test_governed_json_parser_accepts_one_json_fence_and_fails_closed():
    payload = {"queries": [{"tool": "read_news", "args": {}}]}
    encoded = json.dumps(payload, separators=(",", ":"))
    assert _parse_governed_json_text(f"```json\n{encoded}\n```") == payload
    assert _parse_governed_json_text(encoded) == payload
    assert _parse_governed_json_text(f"```python\n{encoded}\n```") is None
    assert _parse_governed_json_text(f"```json\n{encoded}\n``` trailing") is None


def test_oracle_campaign_requires_governed_call_request_identity(tmp_path):
    manifest = _manifest(tmp_path)
    payload = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    entry = payload["runs"][0]
    for field in ("database", "replay_database"):
        database = tmp_path / entry[field]
        store = Store(str(database), create=False)
        row = store.query_one(
            "SELECT id,request_json FROM llm_calls WHERE tick=5 "
            "AND purpose='oracle_plan'")
        request = json.loads(row["request_json"])
        request["context"]["question"] = "post-hoc substituted question"
        store.update("llm_calls", int(row["id"]),
                     request_json=json.dumps(request))
        store.commit()
        store.close()
    entry["database_sha256"] = _sha256(tmp_path / entry["database"])
    entry["replay_database_sha256"] = _sha256(
        tmp_path / entry["replay_database"])
    manifest.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    receipt = evaluate_oracle_campaign(manifest)
    excluded = next(run for run in receipt["runs"] if not run["eligible"])
    assert any(
        "request identity" in reason
        for forecast in excluded["forecasts"]
        for reason in forecast["reasons"])


def test_oracle_campaign_requires_predeclared_treatment_to_fire(tmp_path):
    manifest = _manifest(tmp_path)
    payload = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    entry = payload["runs"][1]  # _SECOND_SEED, treatment arm
    for field in ("database", "replay_database"):
        database = tmp_path / entry[field]
        store = Store(str(database), create=False)
        store.execute(
            "DELETE FROM events WHERE kind='shock_fired' AND tick=4")
        store.commit()
        store.close()
    entry["database_sha256"] = _sha256(tmp_path / entry["database"])
    entry["replay_database_sha256"] = _sha256(
        tmp_path / entry["replay_database"])
    manifest.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    receipt = evaluate_oracle_campaign(manifest)
    excluded = next(
        run for run in receipt["runs"] if run["run_id"] == entry["run_id"])
    assert any("shock_fired" in reason for reason in excluded["reasons"])


def test_checked_in_oracle_campaign_profiles_are_predeclared_and_bounded():
    root = Path("runs/oracle")
    profiles = [root / RELEASE_PROFILES[seed] for seed in RELEASE_SEEDS]
    assert len(profiles) == 10
    configs = [load_config(path) for path in profiles]
    assert {config["seed"] for config in configs} == set(RELEASE_SEEDS)
    for config in configs:
        acceptance = config["acceptance"]
        assert acceptance["min_ticks"] == 335
        assert acceptance["oracle_campaign_id"] == RELEASE_CAMPAIGN_ID
        assert acceptance["oracle_campaign_version"] == RELEASE_CAMPAIGN_VERSION
        assert acceptance["oracle_latency_source"] == "scheduled_e2e_v1"
        assert len(acceptance["oracle_questions"]) == 6
        assert config["llm"]["routes"]["oracle"] == {
            "provider": RELEASE_ORACLE_PROVIDER, "model": RELEASE_ORACLE_MODEL,
        }
        assert {
            route["provider"] for role, route in config["llm"]["routes"].items()
            if role != "oracle"
        } == {"scripted"}
        assert config["budget"]["cap_usd"] == 25
        shocks = config.get("shocks", [])
        if config["seed"] % 2:
            assert shocks == []
        else:
            assert len(shocks) == 12
            assert [shock["trigger_params"]["tick"] for shock in shocks] == [
                4, 6, 64, 66, 124, 126, 184, 186, 244, 246, 304, 306,
            ]
            assert [shock["params"]["n_agents"] for shock in shocks] == [
                1, 40, 1, 40, 1, 40, 1, 40, 1, 40, 1, 40,
            ]
        validate_oracle_campaign_profile(config)

    treatment_rehearsal = load_config(root / "calibration-rehearsal.yaml")
    control_rehearsal = load_config(root / "calibration-control-rehearsal.yaml")
    for rehearsal in (treatment_rehearsal, control_rehearsal):
        assert {
            route["provider"] for route in rehearsal["llm"]["routes"].values()
        } == {"scripted"}
    assert treatment_rehearsal["shocks"]
    assert control_rehearsal["shocks"] == []
    manifest = yaml.safe_load(
        (root / "manifest-v9.template.yaml").read_text(encoding="utf-8"))
    assert [entry["seed"] for entry in manifest["runs"]] == list(RELEASE_SEEDS)
    assert {entry["profile"] for entry in manifest["runs"]} == {
        path.name for path in profiles
    }


def test_checked_in_v9_commitment_and_minimax_contract_are_pinned():
    root = Path("runs/oracle")
    expected_hashes = {
        7381: "9bc602916a0b687570d115e00968b26ba29bdc6c787e100db72a864d29763559",
        7382: "d8f2e6cc8b4e8036776c9cd6b9d71c1da816c2bdfca6467b911b42dace981207",
        7383: "be8b3d81040483fe2e174f75a10072edc8475606db963c8e7859c072ae4b6b36",
        7384: "2bd23f5767a389f4771a6ae99750cf546e0ae3bb4b392d9f6125020c5a2a815a",
        7385: "b701004b5e0768e50024ba0346b721735b356761e82cf51cfe4a3650d484e09a",
        7386: "2548082efc81184eff8386311ad7bb932886d4f257fb01a42af92b2ea3d452b0",
        7387: "50ab7f092ba07da4d9ab53bd625743f40626b37b75edbb82393879662cbd5aab",
        7388: "29ce8812646452ead9d222059e24c9a62a6f239956cb3704b055018b57371aa3",
        7389: "869e7e8958b66941f7d57d324edc752c18966315f96cdf6a9ff0559e801e8360",
        7390: "b64642599ad61bc546e6deb25b94eeedaeef20a28781228f0826f95f3519a9a0",
    }
    assert RELEASE_CAMPAIGN_ID == "oracle-calibration-v9"
    assert RELEASE_CAMPAIGN_VERSION == 9
    assert RELEASE_ORACLE_PROVIDER == "minimax"
    assert RELEASE_ORACLE_MODEL == "MiniMax-M3"
    assert RELEASE_ORACLE_ADAPTER == {
        "kind": "openai_compat",
        "base_url": "https://api.minimax.io/v1",
        "api_key_env": "MINIMAX_API_KEY",
        "prompt_cache_mode": "provider_automatic",
        "healthcheck_path": "/models",
        "max_tokens_field": "max_completion_tokens",
        "request_defaults": {
            "max_completion_tokens": 4096,
            "reasoning_split": True,
        },
        "timeout_s": 180,
    }
    assert RELEASE_ORACLE_PRICING == {
        "in": 0.30, "out": 1.20, "cache": 0.06,
    }
    assert RELEASE_COMMITMENT_SHA256 == (
        "8a1845ebe9e916b8618a1c17170dc8a2b439c929ea1e1118670e21683c341a8e")

    commitment_path = root / "commitment-v9.yaml"
    commitment = yaml.safe_load(commitment_path.read_text(encoding="utf-8"))
    assert oracle_campaign._canonical_value_sha256(
        commitment) == RELEASE_COMMITMENT_SHA256
    assert commitment["campaign_id"] == RELEASE_CAMPAIGN_ID
    assert commitment["campaign_version"] == RELEASE_CAMPAIGN_VERSION
    assert [entry["seed"] for entry in commitment["runs"]] == list(
        RELEASE_SEEDS)
    assert {
        entry["seed"]: entry["effective_config_sha256"]
        for entry in commitment["runs"]
    } == expected_hashes

    for entry in commitment["runs"]:
        seed = entry["seed"]
        assert entry["run_id"] == f"{RELEASE_CAMPAIGN_ID}-s{seed}"
        assert entry["profile"] == RELEASE_PROFILES[seed]
        config = load_config(root / entry["profile"])
        assert effective_config_sha256(config) == expected_hashes[seed]
        assert config["llm"]["routes"]["oracle"] == {
            "provider": RELEASE_ORACLE_PROVIDER, "model": RELEASE_ORACLE_MODEL,
        }
        assert config["llm"]["providers"][RELEASE_ORACLE_PROVIDER] == (
            RELEASE_ORACLE_ADAPTER)
        assert config["llm"]["pricing"] == {
            RELEASE_ORACLE_MODEL: RELEASE_ORACLE_PRICING,
        }
        assert config["lifecycle"] == {
            "retirement_age": 65,
            "medical_cost_cents": 5000,
            "housing_cost_cents": 75000,
            "population_mode": "stable",
            "arrival_delay_min": 5,
            "arrival_delay_max": 20,
        }


def test_v8_archive_commitment_and_profiles_remain_pinned():
    root = Path("runs/oracle")
    seeds = tuple(range(7371, 7381))
    expected_hashes = {
        7371: "2ee853cb5242c23f49bc55be90da5521550f9bf4955dd7e968d9c0fa99e1b90f",
        7372: "d03cd3769427e5c589c16dde65572c52fcec0701a444b011e0790a54397afeb6",
        7373: "161d60f3d4bfd27f4ab78534fc7f6c7819e032a78e2a7203aced40f11e953e51",
        7374: "550de2c1de2b547041bb1f87ba13773439231440e6075d04bc5f3d93241642ba",
        7375: "7141c9ed6362bbfc17d169e03c65f606dc525e48c1d4f4672efdb262711ca54a",
        7376: "384003c86e6dad16d29bca3ed129a6fadc9d2837043d6acceb21213aba17c8b2",
        7377: "930005057c6e6fe616b8ac294c55b223640f4ade369fae6ed71e25a1890fe3e2",
        7378: "68773dfee2ae0f54fa317df36c87151347641da91d9648d988878dd766fb4c1a",
        7379: "39fd382334a53a679d2db29d0f8137bc2ba1e94d785ff47679394e9d8d14f95f",
        7380: "ee56fb3bc890a6aec4ac960138b2033b429706e1ce53598e0da295493b3a0db4",
    }
    commitment_hash = (
        "b0ef0afbc6bd39d9584a4db617ffac5943a263e5fbed4b2d7de5a7f7e0032faf")
    commitment = yaml.safe_load(
        (root / "commitment-v8.yaml").read_text(encoding="utf-8"))
    manifest = yaml.safe_load(
        (root / "manifest-v8.template.yaml").read_text(encoding="utf-8"))
    expected_adapter = {
        "kind": "openai_compat",
        "base_url": "https://api.kimi.com/coding/v1",
        "api_key_env": "KIMI_API_KEY",
        "prompt_cache_mode": "off",
        "healthcheck_path": "/models",
        "max_tokens_field": "max_tokens",
        "request_defaults": {
            "max_tokens": 4096,
            "reasoning_effort": "medium",
            "temperature": 1.0,
        },
        "timeout_s": 180,
    }

    assert oracle_campaign._canonical_value_sha256(commitment) == commitment_hash
    assert manifest["commitment_sha256"] == commitment_hash
    for payload in (commitment, manifest):
        assert payload["campaign_id"] == "oracle-calibration-v8"
        assert payload["campaign_version"] == 8
        assert [int(entry["seed"]) for entry in payload["runs"]] == list(seeds)
    assert {
        int(entry["seed"]): entry["effective_config_sha256"]
        for entry in commitment["runs"]
    } == expected_hashes

    manifest_rows = {int(entry["seed"]): entry for entry in manifest["runs"]}
    for entry in commitment["runs"]:
        seed = int(entry["seed"])
        condition = "rumor" if seed % 2 == 0 else "control"
        profile = f"v8-seed-{seed}-{condition}.yaml"
        config = load_config(root / profile)
        assert entry["run_id"] == f"oracle-calibration-v8-s{seed}"
        assert entry["profile"] == profile
        assert effective_config_sha256(config) == expected_hashes[seed]
        assert config["llm"]["routes"]["oracle"] == {
            "provider": "kimi", "model": "kimi-for-coding-highspeed",
        }
        assert config["llm"]["providers"]["kimi"] == expected_adapter
        assert config["llm"]["pricing"] == {
            "kimi-for-coding-highspeed": {
                "in": 2.85, "out": 12.00, "cache": 0.57,
            },
        }
        for key in ("seed", "run_id", "profile", "effective_config_sha256"):
            assert manifest_rows[seed][key] == entry[key]


def test_v7_archive_commitment_and_profiles_remain_pinned():
    root = Path("runs/oracle")
    seeds = tuple(range(7361, 7371))
    expected_hashes = {
        7361: "cb80115b4c4fc13bfccb8a83b8828936a31cbef2e06c35bec794277671937968",
        7362: "956f35356f2764a87c1639460846fe52e5032b6c482c881a385be6cfaebd86d0",
        7363: "a2106b03012c59e72db7c0db617e469927072e972a03b27dc9d040a5d10e5654",
        7364: "2d2c203629b754a5b62401bb6e585b06e5dea232e23e17ec0b7ce9fbcde3f0da",
        7365: "7b8c1c30b5841ff39b4c05d8498a865a23e69443ebf3f2f420c93ce83e1a942e",
        7366: "0fa305bab3b06cff0258800f04b40becd0fc64f464f1f2f43d6e7a8ab3a59030",
        7367: "3a6d5b20b810af0a9b9f9212095762d2144b04da35626ab833433528f32dc65c",
        7368: "08f8593a6049bfa01b1858c0979c5fc0d58253be86cd78873769e5e0f9daea11",
        7369: "853807cf48e4c8bce8cecd6626cce30368368af95fffc7193d6fb20c89750014",
        7370: "21e5b7f86d8e4fa12eacf0178c9c5fb86918b8fa71893a67675be3b4d813cd6e",
    }
    commitment_hash = (
        "99fc30f9777c311bd435c1b2f11290b699cdaf1204c32028f59c6b008bed4b2a")
    commitment = yaml.safe_load(
        (root / "commitment-v7.yaml").read_text(encoding="utf-8"))
    manifest = yaml.safe_load(
        (root / "manifest-v7.template.yaml").read_text(encoding="utf-8"))

    assert oracle_campaign._canonical_value_sha256(commitment) == commitment_hash
    assert manifest["commitment_sha256"] == commitment_hash
    for payload in (commitment, manifest):
        assert payload["campaign_id"] == "oracle-calibration-v7"
        assert payload["campaign_version"] == 7
        assert [int(entry["seed"]) for entry in payload["runs"]] == list(seeds)
    assert {
        int(entry["seed"]): entry["effective_config_sha256"]
        for entry in commitment["runs"]
    } == expected_hashes

    manifest_rows = {
        int(entry["seed"]): entry for entry in manifest["runs"]}
    for entry in commitment["runs"]:
        seed = int(entry["seed"])
        condition = "rumor" if seed % 2 == 0 else "control"
        profile = f"v7-seed-{seed}-{condition}.yaml"
        assert entry["run_id"] == f"oracle-calibration-v7-s{seed}"
        assert entry["profile"] == profile
        assert effective_config_sha256(
            load_config(root / profile)) == expected_hashes[seed]
        for key in ("seed", "run_id", "profile", "effective_config_sha256"):
            assert manifest_rows[seed][key] == entry[key]


def test_v6_archive_commitment_and_profiles_remain_pinned():
    root = Path("runs/oracle")
    expected_hashes = {
        7351: "f31ffb8204b701eb8d724935e36cf6c4bb98b236c8b455df2eeba3fe055df52b",
        7352: "8fe19716cc14df7a34b759cedcbeff4e08a9ebf6cdaf69bccee4fafd2bba2956",
        7353: "0053e39ee2a0539f1f1cdbc2d062cf7a8a1ba0a8ef2a3192ed64b301a1aee96e",
        7354: "c2a76dc708fc0879689b64ae2115e4ace78ef6bd116e2e325a82c5f5f57b0bcc",
        7355: "463c4f48449e9733dc5ed82953f28bb36134b1a41945a1975cae485ebda43371",
        7356: "f1e78a37ae09f4ee9b2d12b9f24c4204504c0496b4b6fd80d3548058104a0a2c",
        7357: "65967b4eb5995a2d0be384eacfb86d7af38b82e6665e379e3f9576fd4407b806",
        7358: "e1724cbe2f02e6773f9564402bbeff28b7867a8f6dfa6e22086b98a062c318f9",
        7359: "347178b98098c6dcd6e495921868fe43d370e622454506f896039a461857dba5",
        7360: "9a3f9a39dc74dd3fd06c63508662379952d6d667434404d97bfce465487051db",
    }
    commitment = yaml.safe_load(
        (root / "commitment-v6.yaml").read_text(encoding="utf-8"))
    manifest = yaml.safe_load(
        (root / "manifest-v6.template.yaml").read_text(encoding="utf-8"))
    commitment_hash = (
        "c34c0cfe000ade888aca937a110afd24e799efe7a030635134212472e4686963")
    assert oracle_campaign._canonical_value_sha256(commitment) == commitment_hash
    assert manifest["commitment_sha256"] == commitment_hash
    for payload in (commitment, manifest):
        assert payload["campaign_id"] == "oracle-calibration-v6"
        assert payload["campaign_version"] == 6
        assert [int(entry["seed"]) for entry in payload["runs"]] == list(
            range(7351, 7361))
    assert {
        int(entry["seed"]): entry["effective_config_sha256"]
        for entry in commitment["runs"]
    } == expected_hashes

    for entry in commitment["runs"]:
        seed = int(entry["seed"])
        condition = "rumor" if seed % 2 == 0 else "control"
        assert entry["run_id"] == f"oracle-calibration-v6-s{seed}"
        assert entry["profile"] == f"v6-seed-{seed}-{condition}.yaml"
        assert effective_config_sha256(
            load_config(root / entry["profile"])) == expected_hashes[seed]


def test_v5_archive_commitment_and_profiles_remain_pinned():
    root = Path("runs/oracle")
    expected_hashes = {
        7341: "39dab7ce006da45c98dcf77c76e954255adc494e6c0ae981ee767e208f069475",
        7342: "79432c3e0aa20c7ab087fecf895ff65b22cbccfb8091f1772b95492d7c63d86a",
        7343: "ec6ab27f6f39b7e32bbd6f4f6959b4d51a75f9a1d0e50435a369999e14e30af1",
        7344: "5ab1b70cc758a754ca8b9049f7153da56faf894f2e7f8e3e42ddbc9b6426842f",
        7345: "86b1d654b29c3ae08a460a9c1dc175376db730e11c743bbb9b9520f4adfc049e",
        7346: "4daf98343b6454e15192f78188545189d826410946c6253aed7cd340d5c16879",
        7347: "61d4112301b3f715dcbe236c5aff4eeb09bde33ad688e51d95ce335d54005cb9",
        7348: "2f3d8296378c8568b56d1660af88e8359be88ec16ab19a257b2e4c266afe5346",
        7349: "ed9044731fea81e0251bc73c4f42ad46ddb1d4bbbbff87ce6ba2aacb6643cc2d",
        7350: "ab17ae80033168f1825974898a7bdec48eb7ac76711dd6c1a172662eaef21ccd",
    }
    commitment = yaml.safe_load(
        (root / "commitment-v5.yaml").read_text(encoding="utf-8"))
    assert oracle_campaign._canonical_value_sha256(commitment) == (
        "00b1b2a9e00168920a89f24f0d914b0d34efe8b232120e412364e29bf7865595")
    assert commitment["campaign_id"] == "oracle-calibration-v5"
    assert commitment["campaign_version"] == 5
    assert {
        int(entry["seed"]): entry["effective_config_sha256"]
        for entry in commitment["runs"]
    } == expected_hashes

    for entry in commitment["runs"]:
        seed = int(entry["seed"])
        condition = "rumor" if seed % 2 == 0 else "control"
        assert entry["run_id"] == f"oracle-calibration-v5-s{seed}"
        assert entry["profile"] == f"v5-seed-{seed}-{condition}.yaml"
        assert effective_config_sha256(
            load_config(root / entry["profile"])) == expected_hashes[seed]


def test_v6_campaign_has_no_v5_profile_or_evidence_ancestry():
    root = Path("runs/oracle")
    v6_seeds = tuple(range(7351, 7361))
    base = yaml.safe_load(
        (root / "calibration-base-v6.yaml").read_text(encoding="utf-8"))
    assert base["extends"] == "../acceptance/rehearsal.yaml"

    for seed in v6_seeds:
        profile_name = (
            f"v6-seed-{seed}-{'rumor' if seed % 2 == 0 else 'control'}.yaml")
        profile = yaml.safe_load(
            (root / profile_name).read_text(encoding="utf-8"))
        assert profile["extends"] == "calibration-base-v6.yaml"

    v5_commitment = yaml.safe_load(
        (root / "commitment-v5.yaml").read_text(encoding="utf-8"))
    assert oracle_campaign._canonical_value_sha256(v5_commitment) == (
        "00b1b2a9e00168920a89f24f0d914b0d34efe8b232120e412364e29bf7865595")

    v6_commitment = yaml.safe_load(
        (root / "commitment-v6.yaml").read_text(encoding="utf-8"))
    v6_manifest = yaml.safe_load(
        (root / "manifest-v6.template.yaml").read_text(encoding="utf-8"))
    previous_seeds = set(range(7301, 7351))
    assert set(v6_seeds).isdisjoint(previous_seeds)
    assert v6_manifest["commitment_sha256"] == (
        "c34c0cfe000ade888aca937a110afd24e799efe7a030635134212472e4686963")
    for payload in (v6_commitment, v6_manifest):
        assert payload["campaign_id"] == "oracle-calibration-v6"
        assert payload["campaign_version"] == 6
        assert [entry["seed"] for entry in payload["runs"]] == list(
            v6_seeds)

    commitment_rows = {
        int(entry["seed"]): entry for entry in v6_commitment["runs"]}
    manifest_rows = {
        int(entry["seed"]): entry for entry in v6_manifest["runs"]}
    assert set(commitment_rows) == set(manifest_rows) == set(v6_seeds)
    for seed in v6_seeds:
        profile_name = (
            f"v6-seed-{seed}-{'rumor' if seed % 2 == 0 else 'control'}.yaml")
        for key in ("seed", "run_id", "profile", "effective_config_sha256"):
            assert manifest_rows[seed][key] == commitment_rows[seed][key]
        assert manifest_rows[seed]["run_id"] == f"oracle-calibration-v6-s{seed}"
        assert manifest_rows[seed]["profile"] == profile_name


def test_v7_campaign_has_no_v6_profile_or_evidence_ancestry():
    root = Path("runs/oracle")
    v7_seeds = tuple(range(7361, 7371))
    base = yaml.safe_load(
        (root / "calibration-base-v7.yaml").read_text(encoding="utf-8"))
    assert base["extends"] == "../acceptance/rehearsal.yaml"

    for seed in v7_seeds:
        profile_name = (
            f"v7-seed-{seed}-{'rumor' if seed % 2 == 0 else 'control'}.yaml")
        profile = yaml.safe_load(
            (root / profile_name).read_text(encoding="utf-8"))
        assert profile["extends"] == "calibration-base-v7.yaml"

    v6_commitment = yaml.safe_load(
        (root / "commitment-v6.yaml").read_text(encoding="utf-8"))
    v7_commitment = yaml.safe_load(
        (root / "commitment-v7.yaml").read_text(encoding="utf-8"))
    v7_manifest = yaml.safe_load(
        (root / "manifest-v7.template.yaml").read_text(encoding="utf-8"))
    v6_rows = {int(entry["seed"]): entry for entry in v6_commitment["runs"]}
    v7_commitment_rows = {
        int(entry["seed"]): entry for entry in v7_commitment["runs"]}
    v7_manifest_rows = {
        int(entry["seed"]): entry for entry in v7_manifest["runs"]}
    v6_config_hashes = {
        row["effective_config_sha256"] for row in v6_rows.values()}
    v7_config_hashes = {
        row["effective_config_sha256"]
        for row in v7_commitment_rows.values()}

    assert set(v7_seeds).isdisjoint(v6_rows)
    assert v7_manifest["commitment_sha256"] == (
        "99fc30f9777c311bd435c1b2f11290b699cdaf1204c32028f59c6b008bed4b2a")
    assert v7_config_hashes.isdisjoint(v6_config_hashes)
    for payload in (v7_commitment, v7_manifest):
        assert payload["campaign_id"] == "oracle-calibration-v7"
        assert payload["campaign_version"] == 7
        assert [int(entry["seed"]) for entry in payload["runs"]] == list(
            v7_seeds)

    assert set(v7_commitment_rows) == set(v7_manifest_rows) == set(
        v7_seeds)
    for seed in v7_seeds:
        committed = v7_commitment_rows[seed]
        manifest = v7_manifest_rows[seed]
        profile_name = (
            f"v7-seed-{seed}-{'rumor' if seed % 2 == 0 else 'control'}.yaml")
        for key in ("seed", "run_id", "profile", "effective_config_sha256"):
            assert manifest[key] == committed[key]
        assert committed["run_id"] == f"oracle-calibration-v7-s{seed}"
        assert committed["profile"] == profile_name
        assert manifest["database"] == (
            f"../../data/runs/oracle-calibration-v7-s{seed}.db")
        assert manifest["replay_database"] == (
            f"../../data/runs/REPLAY_RUN_ID_{seed}.db")
        assert effective_config_sha256(
            load_config(root / committed["profile"])) == (
                committed["effective_config_sha256"])


def test_v8_campaign_has_no_v7_profile_or_evidence_ancestry():
    root = Path("runs/oracle")
    v8_seeds = tuple(range(7371, 7381))
    base = yaml.safe_load(
        (root / "calibration-base-v8.yaml").read_text(encoding="utf-8"))
    assert base["extends"] == "../acceptance/rehearsal.yaml"

    for seed in v8_seeds:
        profile_name = (
            f"v8-seed-{seed}-{'rumor' if seed % 2 == 0 else 'control'}.yaml")
        profile = yaml.safe_load(
            (root / profile_name).read_text(encoding="utf-8"))
        assert profile["extends"] == "calibration-base-v8.yaml"

    v7_commitment = yaml.safe_load(
        (root / "commitment-v7.yaml").read_text(encoding="utf-8"))
    v8_commitment = yaml.safe_load(
        (root / "commitment-v8.yaml").read_text(encoding="utf-8"))
    v8_manifest = yaml.safe_load(
        (root / "manifest-v8.template.yaml").read_text(encoding="utf-8"))
    v7_rows = {int(entry["seed"]): entry for entry in v7_commitment["runs"]}
    v8_commitment_rows = {
        int(entry["seed"]): entry for entry in v8_commitment["runs"]}
    v8_manifest_rows = {
        int(entry["seed"]): entry for entry in v8_manifest["runs"]}
    v7_config_hashes = {
        row["effective_config_sha256"] for row in v7_rows.values()}
    v8_config_hashes = {
        row["effective_config_sha256"]
        for row in v8_commitment_rows.values()}

    assert set(v8_seeds).isdisjoint(v7_rows)
    assert v8_manifest["commitment_sha256"] == (
        "b0ef0afbc6bd39d9584a4db617ffac5943a263e5fbed4b2d7de5a7f7e0032faf")
    assert v8_config_hashes.isdisjoint(v7_config_hashes)
    for payload in (v8_commitment, v8_manifest):
        assert payload["campaign_id"] == "oracle-calibration-v8"
        assert payload["campaign_version"] == 8
        assert [int(entry["seed"]) for entry in payload["runs"]] == list(
            v8_seeds)

    assert set(v8_commitment_rows) == set(v8_manifest_rows) == set(
        v8_seeds)
    for seed in v8_seeds:
        committed = v8_commitment_rows[seed]
        manifest = v8_manifest_rows[seed]
        profile_name = (
            f"v8-seed-{seed}-{'rumor' if seed % 2 == 0 else 'control'}.yaml")
        for key in ("seed", "run_id", "profile", "effective_config_sha256"):
            assert manifest[key] == committed[key]
        assert committed["run_id"] == f"oracle-calibration-v8-s{seed}"
        assert committed["profile"] == profile_name
        assert manifest["database"] == (
            f"../../data/runs/oracle-calibration-v8-s{seed}.db")
        assert manifest["replay_database"] == (
            f"../../data/runs/REPLAY_RUN_ID_{seed}.db")
        assert effective_config_sha256(
            load_config(root / committed["profile"])) == (
                committed["effective_config_sha256"])


def test_v9_campaign_has_no_v8_profile_or_evidence_ancestry():
    root = Path("runs/oracle")
    base = yaml.safe_load(
        (root / "calibration-base-v9.yaml").read_text(encoding="utf-8"))
    assert base["extends"] == "../acceptance/rehearsal.yaml"

    for seed in RELEASE_SEEDS:
        profile = yaml.safe_load(
            (root / RELEASE_PROFILES[seed]).read_text(encoding="utf-8"))
        assert profile["extends"] == "calibration-base-v9.yaml"

    v8_commitment = yaml.safe_load(
        (root / "commitment-v8.yaml").read_text(encoding="utf-8"))
    v9_commitment = yaml.safe_load(
        (root / "commitment-v9.yaml").read_text(encoding="utf-8"))
    v9_manifest = yaml.safe_load(
        (root / "manifest-v9.template.yaml").read_text(encoding="utf-8"))
    v8_rows = {int(entry["seed"]): entry for entry in v8_commitment["runs"]}
    v9_commitment_rows = {
        int(entry["seed"]): entry for entry in v9_commitment["runs"]}
    v9_manifest_rows = {
        int(entry["seed"]): entry for entry in v9_manifest["runs"]}
    v8_config_hashes = {
        row["effective_config_sha256"] for row in v8_rows.values()}
    v9_config_hashes = {
        row["effective_config_sha256"]
        for row in v9_commitment_rows.values()}

    assert set(RELEASE_SEEDS).isdisjoint(v8_rows)
    assert v9_manifest["commitment_sha256"] == RELEASE_COMMITMENT_SHA256
    assert v9_config_hashes.isdisjoint(v8_config_hashes)
    for payload in (v9_commitment, v9_manifest):
        assert payload["campaign_id"] == RELEASE_CAMPAIGN_ID
        assert payload["campaign_version"] == RELEASE_CAMPAIGN_VERSION
        assert [int(entry["seed"]) for entry in payload["runs"]] == list(
            RELEASE_SEEDS)

    assert set(v9_commitment_rows) == set(v9_manifest_rows) == set(
        RELEASE_SEEDS)
    for seed in RELEASE_SEEDS:
        committed = v9_commitment_rows[seed]
        manifest = v9_manifest_rows[seed]
        for key in ("seed", "run_id", "profile", "effective_config_sha256"):
            assert manifest[key] == committed[key]
        assert committed["run_id"] == f"{RELEASE_CAMPAIGN_ID}-s{seed}"
        assert committed["profile"] == RELEASE_PROFILES[seed]
        assert manifest["database"] == (
            f"../../data/runs/{RELEASE_CAMPAIGN_ID}-s{seed}.db")
        assert manifest["replay_database"] == (
            f"../../data/runs/REPLAY_RUN_ID_{seed}.db")
        assert effective_config_sha256(
            load_config(root / committed["profile"])) == (
                committed["effective_config_sha256"])


def test_oracle_campaign_profile_cannot_change_predeclared_arm():
    profile = load_config(_SECOND_PROFILE)
    profile["shocks"][0]["params"]["n_agents"] = 2

    with pytest.raises(OracleCampaignError, match="predeclared campaign arm"):
        validate_oracle_campaign_profile(profile)


def test_oracle_campaign_profile_pins_replacement_arrival_delay():
    profile = load_config(_FIRST_PROFILE)
    profile["lifecycle"]["arrival_delay_min"] = 4

    with pytest.raises(
            OracleCampaignError, match="fixed replacement-arrival schedule"):
        validate_oracle_campaign_profile(profile)


def test_oracle_campaign_profile_requires_official_release_endpoint():
    profile = load_config(_FIRST_PROFILE)
    profile["llm"]["providers"][RELEASE_ORACLE_PROVIDER]["base_url"] = (
        "http://127.0.0.1:9999/v1")

    with pytest.raises(OracleCampaignError, match="official release Oracle API"):
        validate_oracle_campaign_profile(profile)


def test_resumed_oracle_campaign_rejects_wrong_profile_before_dispatch(tmp_path):
    stored = load_config(_FIRST_PROFILE)
    requested = load_config(_SECOND_PROFILE)
    store = Store(str(tmp_path / "wrong-resume.db"))
    store.init_run_meta("wrong-resume", stored["seed"], stored)

    with pytest.raises(OracleCampaignError, match="checked-in predeclared"):
        validate_open_oracle_campaign_source(
            store, requested, _SECOND_PROFILE)
    assert store.scalar("SELECT COUNT(*) FROM llm_calls", default=0) == 0
    store.close()


def test_oracle_campaign_profile_cannot_change_question_or_horizon():
    profile = load_config(_FIRST_PROFILE)
    profile["acceptance"]["oracle_questions"][0]["question"] = "Different?"
    with pytest.raises(OracleCampaignError, match="governed forecast contract"):
        validate_oracle_campaign_profile(profile)

    profile = load_config(_FIRST_PROFILE)
    profile["acceptance"]["min_ticks"] = 334
    with pytest.raises(OracleCampaignError, match="fixed 335-tick horizon"):
        validate_oracle_campaign_profile(profile)


@pytest.mark.parametrize("forbidden", ["model", "messages"])
def test_oracle_campaign_rejects_request_defaults_that_override_wire_identity(
        forbidden):
    profile = load_config(_FIRST_PROFILE)
    profile["llm"]["providers"][RELEASE_ORACLE_PROVIDER][
        "request_defaults"][forbidden] = (
        "attacker-model" if forbidden == "model" else [])

    with pytest.raises(OracleCampaignError, match="official release Oracle API"):
        validate_oracle_campaign_profile(profile)


def test_oracle_campaign_pins_complete_provider_and_pricing_contract():
    profile = load_config(_FIRST_PROFILE)
    profile["llm"]["providers"][RELEASE_ORACLE_PROVIDER]["unexpected"] = True
    with pytest.raises(OracleCampaignError, match="official release Oracle API"):
        validate_oracle_campaign_profile(profile)

    profile = load_config(_FIRST_PROFILE)
    profile["llm"]["pricing"][RELEASE_ORACLE_MODEL]["out"] = 0.0
    with pytest.raises(OracleCampaignError, match="pinned release Oracle pricing"):
        validate_oracle_campaign_profile(profile)


def test_effective_config_hash_includes_inherited_parent_content(tmp_path):
    parent = tmp_path / "parent.yaml"
    leaf = tmp_path / "leaf.yaml"
    parent.write_text("nested:\n  value: 1\n", encoding="utf-8")
    leaf.write_text("extends: parent.yaml\nseed: 7\n", encoding="utf-8")
    leaf_hash = _sha256(leaf)
    first = effective_config_sha256(load_config(leaf))

    parent.write_text("nested:\n  value: 2\n", encoding="utf-8")
    second = effective_config_sha256(load_config(leaf))

    assert _sha256(leaf) == leaf_hash
    assert first != second


def test_manifest_requires_precommitted_resolved_configuration_hash(tmp_path):
    manifest = _manifest(tmp_path)
    payload = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    payload["runs"][0]["effective_config_sha256"] = "0" * 64
    manifest.write_text(
        yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(OracleCampaignError, match="pre-run commitment"):
        evaluate_oracle_campaign(manifest)


def test_pre_run_commitment_allows_resume_but_blocks_resampling(tmp_path):
    profile_path = Path(_FIRST_PROFILE)
    profile = load_config(profile_path)
    first = prepare_oracle_campaign_run(
        profile, profile_path, data_dir=tmp_path)

    assert first["run_id"] == _FIRST_RUN_ID
    assert Path(first["claim_path"]).is_file()
    resumed = prepare_oracle_campaign_run(
        profile, profile_path, data_dir=tmp_path,
        resume_run_id=first["run_id"])
    assert resumed["effective_config_sha256"] == effective_config_sha256(profile)
    with pytest.raises(OracleCampaignError, match="already claimed"):
        prepare_oracle_campaign_run(profile, profile_path, data_dir=tmp_path)


def test_claim_crash_recovery_never_resamples_initialized_or_partial_slot(tmp_path):
    profile_path = Path(_FIRST_PROFILE)
    profile = load_config(profile_path)
    claim = prepare_oracle_campaign_run(
        profile, profile_path, data_dir=tmp_path)
    pending = prepare_oracle_campaign_run(
        profile, profile_path, data_dir=tmp_path,
        resume_run_id=claim["run_id"])
    assert pending["create_pending_database"] is True

    initialized_path = Path(claim["initialized_path"])
    initialized_path.write_text(
        json.dumps(claim["initialized_payload"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    with pytest.raises(OracleCampaignError, match="database is missing"):
        prepare_oracle_campaign_run(
            profile, profile_path, data_dir=tmp_path,
            resume_run_id=claim["run_id"])

    initialized_path.unlink()
    sqlite3.connect(tmp_path / f"{claim['run_id']}.db").close()
    with pytest.raises(OracleCampaignError, match="staging database"):
        prepare_oracle_campaign_run(
            profile, profile_path, data_dir=tmp_path,
            resume_run_id=claim["run_id"])


def test_unique_genesis_staging_quarantines_corrupt_pending_before_publication(
        tmp_path, monkeypatch):
    monkeypatch.setenv(
        RELEASE_ORACLE_ADAPTER["api_key_env"], "unit-test-placeholder"
    )
    profile_path = Path(_FIRST_PROFILE)
    profile = load_config(profile_path)
    claim = prepare_oracle_campaign_run(
        profile, profile_path, data_dir=tmp_path)
    pending = tmp_path / "oracle-pending" / f"{claim['run_id']}.db"
    pending.parent.mkdir(parents=True, exist_ok=True)
    pending.write_bytes(b"partial sqlite publication")

    final = _initialize_claimed_oracle_genesis(
        profile, claim, data_dir=tmp_path)

    assert final == (tmp_path / f"{claim['run_id']}.db").resolve()
    assert final.is_file()
    assert not pending.exists()
    assert list(pending.parent.glob(
        f".{claim['run_id']}.rejected-*.db"))
    assert not list(pending.parent.glob(f".{claim['run_id']}-*"))
    evidence = oracle_campaign.validate_claimed_oracle_genesis(
        final, claim, profile)
    assert evidence["tick"] == 0
    store = Store(str(final), create=False, read_only=True)
    assert store.scalar("SELECT COUNT(*) FROM llm_calls", default=-1) == 0
    store.close()


@pytest.mark.parametrize("missing_column", [
    "prng_state", "lifecycle_prng_state",
])
def test_claimed_genesis_requires_both_prng_streams_before_dispatch(
        tmp_path, monkeypatch, missing_column):
    monkeypatch.setenv(
        RELEASE_ORACLE_ADAPTER["api_key_env"], "unit-test-placeholder"
    )
    profile_path = Path(_FIRST_PROFILE)
    profile = load_config(profile_path)
    claim = prepare_oracle_campaign_run(
        profile, profile_path, data_dir=tmp_path)
    source = _initialize_claimed_oracle_genesis(
        profile, claim, data_dir=tmp_path)

    store = Store(str(source), create=False)
    store.set_meta(**{missing_column: None})
    store.commit()
    store.close()
    finalize_sqlite_artifact(source)

    with pytest.raises(
            OracleCampaignError, match="complete deterministic zero-call genesis"):
        oracle_campaign.validate_claimed_oracle_genesis(
            source, claim, profile)


def test_release_prng_validators_enforce_column_specific_shapes():
    state = random.Random(7311).getstate()
    single = [state[0], list(state[1]), state[2]]
    envelope = {"engine": single, "persona": single}
    single_json = json.dumps(single)
    envelope_json = json.dumps(envelope)

    assert oracle_campaign._valid_single_prng_state(single_json)
    assert not oracle_campaign._valid_single_prng_state(envelope_json)
    assert oracle_campaign._valid_semantics7_prng_state(envelope_json)
    assert not oracle_campaign._valid_semantics7_prng_state(single_json)


def test_checkpoint_population_tracks_living_agents_not_preserved_rows():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE agents (id INTEGER PRIMARY KEY, alive INTEGER)")
    connection.executemany(
        "INSERT INTO agents(alive) VALUES (?)", [(1,)] * 100)

    baseline = oracle_campaign._checkpoint_population_evidence(connection)
    assert baseline == {
        "total": 100, "living": 100, "deceased": 0, "invalid": 0,
    }
    assert oracle_campaign._valid_release_checkpoint_population(baseline)

    connection.execute("UPDATE agents SET alive=0 WHERE id=1")
    before_arrival = oracle_campaign._checkpoint_population_evidence(connection)
    assert before_arrival == {
        "total": 100, "living": 99, "deceased": 1, "invalid": 0,
    }
    assert oracle_campaign._valid_release_checkpoint_population(before_arrival)

    connection.execute("INSERT INTO agents(alive) VALUES (1)")
    after_arrival = oracle_campaign._checkpoint_population_evidence(connection)
    assert after_arrival == {
        "total": 101, "living": 100, "deceased": 1, "invalid": 0,
    }
    assert oracle_campaign._valid_release_checkpoint_population(after_arrival)

    connection.execute("INSERT INTO agents(alive) VALUES (2)")
    invalid = oracle_campaign._checkpoint_population_evidence(connection)
    assert invalid["invalid"] == 1
    assert not oracle_campaign._valid_release_checkpoint_population(invalid)
    connection.execute("UPDATE agents SET alive=NULL WHERE id=2")
    null_alive = oracle_campaign._checkpoint_population_evidence(connection)
    assert null_alive["invalid"] == 2
    assert not oracle_campaign._valid_release_checkpoint_population(null_alive)
    connection.close()


def test_source_receipt_accepts_retained_death_and_linked_replacement(tmp_path):
    entry = _write_run(tmp_path, 0, lifecycle_replacement=True)
    assert entry["run_id"] == _FIRST_RUN_ID

    store = Store(
        str(tmp_path / f"{_FIRST_RUN_ID}.db"), create=False, read_only=True)
    try:
        evidence, reasons = oracle_campaign._source_integrity(
            store, load_config(_FIRST_PROFILE), 335)
    finally:
        store.close()
    assert reasons == []
    assert evidence["population"]["current"] == {
        "total": 101, "living": 100, "deceased": 1, "invalid": 0,
    }
    assert evidence["population"]["baseline_total"] == 100
    assert evidence["population"]["event_links_valid"] is True
    checkpoints = {
        item["tick"]: item for item in evidence["checkpoints"]["files"]
    }
    assert checkpoints[5]["population"] == {
        "total": 100, "living": 100, "deceased": 0, "invalid": 0,
    }
    assert checkpoints[210]["population"] == {
        "total": 100, "living": 99, "deceased": 1, "invalid": 0,
    }
    assert checkpoints[230]["population"] == {
        "total": 101, "living": 100, "deceased": 1, "invalid": 0,
    }
    assert all(
        item["lifecycle"]["event_links_valid"] for item in checkpoints.values())


def test_lifecycle_provenance_rejects_future_or_misattributed_events():
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE agents (id INTEGER PRIMARY KEY, kind TEXT, role TEXT, "
        "alive INTEGER, arrived_tick INTEGER, died_tick INTEGER)")
    connection.execute(
        "CREATE TABLE events (id INTEGER PRIMARY KEY, tick INTEGER, phase TEXT, "
        "kind TEXT, subject_type TEXT, subject_id INTEGER, payload_json TEXT)")
    connection.executemany(
        "INSERT INTO agents(kind,role,alive,arrived_tick,died_tick) "
        "VALUES ('citizen',NULL,1,0,NULL)", [()] * 100)
    connection.execute(
        "UPDATE agents SET alive=0,died_tick=3 WHERE id=1")
    connection.execute(
        "INSERT INTO agents(id,kind,role,alive,arrived_tick,died_tick) "
        "VALUES (101,'citizen',NULL,1,8,NULL)")
    connection.execute(
        "INSERT INTO events(id,tick,phase,kind,subject_type,subject_id,payload_json) "
        "VALUES (1,3,'NIGHT_CLOSE','death','agent',1,?)",
        (json.dumps({"agent_id": 1}),))
    connection.execute(
        "INSERT INTO events(id,tick,phase,kind,subject_type,subject_id,payload_json) "
        "VALUES (2,3,'NIGHT_CLOSE','arrival_scheduled',NULL,NULL,?)",
        (json.dumps({"due_tick": 8}),))
    connection.execute(
        "INSERT INTO events(id,tick,phase,kind,subject_type,subject_id,payload_json) "
        "VALUES (3,8,'NIGHT_CLOSE','arrival','agent',101,?)",
        (json.dumps({"agent_id": 101, "schedule_event_id": 2}),))

    valid = oracle_campaign._source_population_evidence(
        connection, horizon_tick=8)
    assert valid["event_links_valid"] is True

    future = oracle_campaign._source_population_evidence(
        connection, horizon_tick=7)
    assert future["invalid_agent_rows"] > 0
    assert future["invalid_event_envelopes"] > 0
    assert future["event_links_valid"] is False

    connection.execute(
        "UPDATE agents SET arrived_tick=7 WHERE id=101")
    connection.execute(
        "UPDATE events SET payload_json=? WHERE kind='arrival_scheduled'",
        (json.dumps({"due_tick": 7}),))
    connection.execute(
        "UPDATE events SET tick=7 WHERE kind='arrival'")
    too_early = oracle_campaign._source_population_evidence(
        connection, horizon_tick=7)
    assert too_early["invalid_event_envelopes"] == 1
    assert too_early["event_links_valid"] is False

    connection.execute(
        "UPDATE agents SET arrived_tick=23 WHERE id=101")
    connection.execute(
        "UPDATE events SET payload_json=? WHERE kind='arrival_scheduled'",
        (json.dumps({"due_tick": 23}),))
    connection.execute(
        "UPDATE events SET tick=23 WHERE kind='arrival'")
    upper_bound = oracle_campaign._source_population_evidence(
        connection, horizon_tick=23)
    assert upper_bound["event_links_valid"] is True

    connection.execute(
        "UPDATE agents SET arrived_tick=24 WHERE id=101")
    connection.execute(
        "UPDATE events SET payload_json=? WHERE kind='arrival_scheduled'",
        (json.dumps({"due_tick": 24}),))
    connection.execute(
        "UPDATE events SET tick=24 WHERE kind='arrival'")
    too_late = oracle_campaign._source_population_evidence(
        connection, horizon_tick=24)
    assert too_late["invalid_event_envelopes"] == 1
    assert too_late["event_links_valid"] is False

    connection.execute(
        "UPDATE agents SET arrived_tick=8 WHERE id=101")
    connection.execute(
        "UPDATE events SET payload_json=? WHERE kind='arrival_scheduled'",
        (json.dumps({"due_tick": 8}),))
    connection.execute(
        "UPDATE events SET tick=8 WHERE kind='arrival'")

    connection.execute(
        "UPDATE events SET payload_json='{}' WHERE kind='arrival_scheduled'")
    malformed_payload = oracle_campaign._source_population_evidence(
        connection, horizon_tick=8)
    assert malformed_payload["invalid_event_payloads"] == 1
    assert malformed_payload["event_links_valid"] is False
    connection.execute(
        "UPDATE events SET payload_json=? WHERE kind='arrival_scheduled'",
        (json.dumps({"due_tick": 8}),))

    connection.execute(
        "UPDATE agents SET arrived_tick='not-a-tick' WHERE id=101")
    malformed_agent = oracle_campaign._source_population_evidence(
        connection, horizon_tick=8)
    assert malformed_agent["invalid_agent_conversions"] == 1
    assert malformed_agent["event_links_valid"] is False
    connection.execute(
        "UPDATE agents SET arrived_tick=8 WHERE id=101")

    connection.execute(
        "UPDATE agents SET died_tick=3.5 WHERE id=1")
    connection.execute(
        "UPDATE agents SET arrived_tick=8.5 WHERE id=101")
    connection.execute(
        "UPDATE events SET tick=3.5 WHERE kind IN ('death','arrival_scheduled')")
    connection.execute(
        "UPDATE events SET payload_json=? WHERE kind='arrival_scheduled'",
        (json.dumps({"due_tick": 8.5}),))
    connection.execute(
        "UPDATE events SET tick=8.5 WHERE kind='arrival'")
    fractional = oracle_campaign._source_population_evidence(
        connection, horizon_tick=9)
    assert fractional["invalid_agent_conversions"] == 2
    assert fractional["invalid_event_payloads"] == 3
    assert fractional["event_links_valid"] is False
    connection.execute(
        "UPDATE agents SET died_tick=3 WHERE id=1")
    connection.execute(
        "UPDATE agents SET arrived_tick=8 WHERE id=101")
    connection.execute(
        "UPDATE events SET tick=3 WHERE kind IN ('death','arrival_scheduled')")
    connection.execute(
        "UPDATE events SET payload_json=? WHERE kind='arrival_scheduled'",
        (json.dumps({"due_tick": 8}),))
    connection.execute(
        "UPDATE events SET tick=8 WHERE kind='arrival'")

    connection.execute(
        "UPDATE agents SET role=? WHERE id=2", (sqlite3.Binary(b"bad-role"),))
    blob_role = oracle_campaign._source_population_evidence(
        connection, horizon_tick=8)
    assert blob_role["invalid_agent_conversions"] == 1
    assert blob_role["event_links_valid"] is False
    assert all(
        type(kind) is str and (role is None or type(role) is str)
        for kind, role in blob_role["baseline_census"])
    connection.execute("UPDATE agents SET role=NULL WHERE id=2")

    connection.execute(
        "UPDATE events SET subject_id=999 WHERE kind='arrival'")
    misattributed = oracle_campaign._source_population_evidence(
        connection, horizon_tick=8)
    assert misattributed["invalid_event_envelopes"] == 1
    assert misattributed["event_links_valid"] is False
    connection.close()


@pytest.mark.parametrize(
    ("living", "accepted"), ((94, False), (95, True), (105, True), (106, False)))
def test_release_population_living_boundaries(living, accepted):
    total = max(100, living)
    evidence = {
        "total": total, "living": living, "deceased": total - living,
        "invalid": 0,
    }
    assert oracle_campaign._valid_release_checkpoint_population(
        evidence) is accepted


def test_release_population_rejects_negative_or_non_integer_components():
    assert not oracle_campaign._valid_release_checkpoint_population({
        "total": 100, "living": 105, "deceased": -5, "invalid": 0,
    })
    assert not oracle_campaign._valid_release_checkpoint_population({
        "total": 100.0, "living": 100, "deceased": 0, "invalid": 0,
    })
    for value in (True, 1.0, "1"):
        with pytest.raises(ValueError, match="exact integer"):
            oracle_campaign._evidence_integer(value)


def test_claim_and_initialized_marker_publication_never_clobbers_existing_bytes(
        tmp_path, monkeypatch):
    monkeypatch.setenv(
        RELEASE_ORACLE_ADAPTER["api_key_env"], "unit-test-placeholder"
    )
    profile_path = Path(_FIRST_PROFILE)
    profile = load_config(profile_path)
    run_id = _FIRST_RUN_ID
    claim_path = tmp_path / "oracle-commitments" / f"{run_id}.json"
    claim_path.parent.mkdir(parents=True, exist_ok=True)
    real_link = oracle_campaign.os.link

    def fail_claim_publication(source, target):
        if Path(target).resolve() == claim_path.resolve():
            raise OSError("simulated publication crash")
        return real_link(source, target)

    monkeypatch.setattr(oracle_campaign.os, "link", fail_claim_publication)
    with pytest.raises(OracleCampaignError, match="already claimed"):
        prepare_oracle_campaign_run(profile, profile_path, data_dir=tmp_path)
    assert not claim_path.exists()
    assert not list(claim_path.parent.glob(f".{claim_path.name}.*.tmp"))
    monkeypatch.setattr(oracle_campaign.os, "link", real_link)

    claim_path.write_bytes(b"truncated claim")
    with pytest.raises(OracleCampaignError, match="already claimed"):
        prepare_oracle_campaign_run(profile, profile_path, data_dir=tmp_path)
    assert claim_path.read_bytes() == b"truncated claim"
    assert not list(claim_path.parent.glob(f".{claim_path.name}.*.tmp"))

    claim_path.unlink()
    claim = prepare_oracle_campaign_run(
        profile, profile_path, data_dir=tmp_path)
    final = _initialize_claimed_oracle_genesis(
        profile, claim, data_dir=tmp_path)
    initialized = Path(claim["initialized_path"])
    initialized.write_bytes(b"truncated initialized marker")
    with pytest.raises(OracleCampaignError, match="already exists"):
        mark_oracle_campaign_initialized(claim, final)
    assert initialized.read_bytes() == b"truncated initialized marker"
    assert not list(initialized.parent.glob(f".{initialized.name}.*.tmp"))


def test_campaign_execution_lock_rejects_overlap_and_releases_after_process_crash(
        tmp_path):
    claim = {
        "run_id": _FIRST_RUN_ID, "seed": _FIRST_SEED,
    }
    with oracle_campaign.oracle_campaign_execution_lock(
            claim, data_dir=tmp_path):
        with pytest.raises(OracleCampaignError, match="already active"):
            with oracle_campaign.oracle_campaign_execution_lock(
                    claim, data_dir=tmp_path):
                pass
    with oracle_campaign.oracle_campaign_execution_lock(
            claim, data_dir=tmp_path):
        pass

    lock_path = tmp_path / "oracle-locks" / "crash-release.lock"
    ready = tmp_path / "lock-ready"
    script = (
        "import sys,time\n"
        "from pathlib import Path\n"
        "from reports.oracle_campaign import _CampaignExecutionLock\n"
        "lock=_CampaignExecutionLock(Path(sys.argv[1]))\n"
        "lock.__enter__()\n"
        "Path(sys.argv[2]).write_text('ready', encoding='utf-8')\n"
        "time.sleep(60)\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(lock_path), str(ready)],
        cwd=Path.cwd())
    try:
        for _ in range(100):
            if ready.exists():
                break
            if process.poll() is not None:
                raise AssertionError("lock-holder subprocess exited before acquiring")
            time.sleep(0.05)
        assert ready.exists()
        with pytest.raises(OracleCampaignError, match="already active"):
            with oracle_campaign._CampaignExecutionLock(lock_path):
                pass
    finally:
        process.kill()
        process.wait(timeout=10)
    with oracle_campaign._CampaignExecutionLock(lock_path):
        pass


def test_every_checkpoint_hash_schema_and_prng_state_is_receipt_bound(tmp_path):
    entry = _write_run(tmp_path, 0)
    replay_receipt_path = Path(entry["replay_execution_receipt"])
    replay_receipt = json.loads(
        replay_receipt_path.read_text(encoding="utf-8"))
    checkpoint_manifest = replay_receipt["checkpoint_manifest"]
    assert checkpoint_manifest["validated_files"] == 40
    assert len(checkpoint_manifest["files"]) == 40
    assert entry["checkpoint_manifest_sha256"] == (
        checkpoint_manifest["manifest_sha256"])
    assert all(len(item["sha256"]) == 64 for item in checkpoint_manifest["files"])

    checkpoint_path = Path(checkpoint_manifest["files"][0]["path"])
    Path(f"{checkpoint_path}.manifest.json").unlink()
    checkpoint_path.unlink()
    empty = Store(str(checkpoint_path))
    empty.init_run_meta(entry["run_id"], entry["seed"], load_config(entry["profile"]))
    tick = int(checkpoint_manifest["files"][0]["tick"])
    engine = random.Random(entry["seed"]).getstate()
    persona = random.Random(entry["seed"] ^ 0xA11CE).getstate()
    lifecycle = random.Random(entry["seed"] ^ 0x5F5E5F).getstate()
    empty.set_meta(
        tick=tick, status="running", phase="FINALIZE", active_tick=None,
        next_phase="NIGHT_CLOSE", phase_state_json="{}",
        prng_state=json.dumps({
            "engine": [engine[0], list(engine[1]), engine[2]],
            "persona": [persona[0], list(persona[1]), persona[2]],
        }),
        lifecycle_prng_state=json.dumps(
            [lifecycle[0], list(lifecycle[1]), lifecycle[2]]),
        governor_json="{}")
    empty.commit()
    empty.close()
    finalize_sqlite_artifact(checkpoint_path)
    write_checkpoint_manifest(checkpoint_path)

    run, _pairs, _latencies = oracle_campaign._evaluate_run(
        entry, manifest_dir=tmp_path,
        campaign_id=oracle_campaign.RELEASE_CAMPAIGN_ID,
        campaign_version=oracle_campaign.RELEASE_CAMPAIGN_VERSION,
        commitment_sha256=RELEASE_COMMITMENT_SHA256)
    assert run["eligible"] is False
    assert "source checkpoint population census is invalid at tick 5" in run[
        "reasons"]


def test_global_llm_audit_allows_local_background_but_no_other_live_calls(
        tmp_path):
    store = Store(str(tmp_path / "calls.db"))
    for tick in oracle_campaign.RELEASE_QUESTION_TICKS:
        for purpose in ("oracle_plan", "oracle"):
            store.insert(
                "llm_calls", tick=tick, role="oracle", purpose=purpose,
                provider=RELEASE_ORACLE_PROVIDER, model=RELEASE_ORACLE_MODEL,
                cache_key=(
                    f"{tick}-{purpose}"))
    store.insert(
        "llm_calls", tick=1, role="citizen", purpose="decide",
        provider="scripted", model="scripted", cache_key="local")
    evidence, reasons = oracle_campaign._llm_call_integrity(store)
    assert reasons == []
    assert evidence["persisted_calls"] == 13
    assert evidence["live_calls"] == 12

    store.insert(
        "llm_calls", tick=5, role="citizen", purpose="decide",
        provider=RELEASE_ORACLE_PROVIDER, model=RELEASE_ORACLE_MODEL,
        cache_key="smuggled-live")
    evidence, reasons = oracle_campaign._llm_call_integrity(store)
    store.close()
    assert evidence["invalid_live_call_ids"]
    assert "outside governed scheduled Oracle work" in " ".join(reasons)


def test_receipts_are_idempotent_no_clobber_and_replay_path_is_canonical(
        tmp_path):
    entry = _write_run(tmp_path, 0)
    profile_path = Path(entry["profile"])
    profile = load_config(profile_path)
    claim = prepare_oracle_campaign_run(
        profile, profile_path, data_dir=tmp_path,
        resume_run_id=entry["run_id"])
    source = Path(entry["database"])
    replay = Path(entry["replay_database"])
    replay_receipt_path = Path(entry["replay_execution_receipt"])
    original = replay_receipt_path.read_bytes()
    tracker = json.loads(original)["replay_tracker"]

    repeated = write_replay_execution_receipt(
        source, replay, profile_path, replay_tracker=tracker,
        campaign_claim=claim, out_dir=replay_receipt_path.parent)
    assert Path(repeated["artifact"]).read_bytes() == original
    source_repeated = write_oracle_source_receipt(
        source, replay, profile_path,
        replay_execution_receipt=repeated["artifact"],
        campaign_claim=claim, out_dir=replay_receipt_path.parent)
    assert source_repeated["artifact_sha256"] == entry["source_receipt_sha256"]

    for database in (source, replay):
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{database}{suffix}")
            sidecar.write_bytes(b"unexpected sidecar")
            try:
                with pytest.raises(
                        OracleCampaignError,
                        match="finalized standalone SQLite artifact"):
                    write_replay_execution_receipt(
                        source, replay, profile_path, replay_tracker=tracker,
                        campaign_claim=claim,
                        out_dir=replay_receipt_path.parent)
            finally:
                sidecar.unlink()
            assert replay_receipt_path.read_bytes() == original

    alternate = tmp_path / "alternate-replay.db"
    shutil.copyfile(replay, alternate)
    with pytest.raises(OracleCampaignError, match="different contents"):
        write_replay_execution_receipt(
            source, alternate, profile_path, replay_tracker=tracker,
            campaign_claim=claim, out_dir=replay_receipt_path.parent)
    assert replay_receipt_path.read_bytes() == original

    outside = tmp_path / "outside" / "replay.db"
    outside.parent.mkdir()
    shutil.copyfile(replay, outside)
    with pytest.raises(OracleCampaignError, match="canonical campaign paths"):
        write_replay_execution_receipt(
            source, outside, profile_path, replay_tracker=tracker,
            campaign_claim=claim, out_dir=replay_receipt_path.parent)


def test_completed_cli_reuses_validated_receipts_before_read_write_open(
        tmp_path, monkeypatch, capsys):
    receipt_dir = tmp_path / "reports" / "out"
    entry = _write_run(tmp_path, 0, receipt_dir=receipt_dir)
    profile_path = Path(entry["profile"]).resolve()
    profile = load_config(profile_path)
    source = Path(entry["database"])
    replay = Path(entry["replay_database"])
    source_receipt = Path(entry["source_receipt"])
    replay_receipt = Path(entry["replay_execution_receipt"])
    claim = Path(entry["claim"])
    initialized = Path(entry["initialized_claim"])
    checkpoint_paths = [
        Path(item["path"]) for item in json.loads(
            replay_receipt.read_text(encoding="utf-8"))[
                "checkpoint_manifest"]["files"]
    ]
    protected = [
        source, replay, source_receipt, replay_receipt, claim, initialized,
        *checkpoint_paths,
        *(Path(f"{path}.manifest.json") for path in checkpoint_paths),
    ]
    before = {
        str(path): (_sha256(path), path.stat().st_mtime_ns)
        for path in protected
    }
    database_paths = [source, replay, *checkpoint_paths]
    assert not any(
        Path(f"{path}{suffix}").exists()
        for path in database_paths for suffix in ("-wal", "-shm"))

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_cli, "DATA_DIR", tmp_path)

    def forbidden_open(*_args, **_kwargs):
        raise AssertionError("completed campaign reopened a database read-write")

    monkeypatch.setattr(run_cli, "open_run", forbidden_open)
    args = SimpleNamespace(
        config=str(profile_path), resume=entry["run_id"],
        approve_live_inference=True, ticks=None)
    run_cli._execute_oracle_campaign_run(profile, args)

    assert json.loads(capsys.readouterr().out)["reused"] is True
    assert before == {
        str(path): (_sha256(path), path.stat().st_mtime_ns)
        for path in protected
    }
    assert not any(
        Path(f"{path}{suffix}").exists()
        for path in database_paths for suffix in ("-wal", "-shm"))

    source_receipt.write_bytes(source_receipt.read_bytes() + b"conflict")
    with pytest.raises(OracleCampaignError, match="unreadable|canonical|invalid"):
        run_cli._execute_oracle_campaign_run(profile, args)
    assert _sha256(source) == before[str(source)][0]
    assert _sha256(replay) == before[str(replay)][0]


def test_replay_execution_receipt_tamper_is_ineligible(tmp_path):
    manifest = _manifest(tmp_path)
    payload = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    entry = payload["runs"][0]
    receipt_path = Path(entry["replay_execution_receipt"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["replay_tracker"]["live_dispatch_count"] = 1
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    entry["replay_execution_receipt_sha256"] = _sha256(receipt_path)
    manifest.write_text(
        yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    campaign = evaluate_oracle_campaign(manifest)
    run = next(item for item in campaign["runs"] if item["seed"] == _FIRST_SEED)
    assert run["eligible"] is False
    assert "replay receipt tracker does not prove exact consumption" in run["reasons"]


def test_independent_metrics_reject_joint_source_and_replay_outcome_tamper(tmp_path):
    manifest = _manifest(tmp_path)

    def flip_outcome(store):
        prediction = store.query_one(
            "SELECT * FROM predictions WHERE asked_tick=5")
        probability = float(prediction["p"])
        store.update(
            "predictions", int(prediction["id"]), outcome=1,
            brier=(probability - 1) ** 2)
        for event in store.query(
                "SELECT * FROM events WHERE kind='prediction_resolved'"):
            payload = json.loads(event["payload_json"])
            if payload.get("prediction_id") == int(prediction["id"]):
                payload.update({
                    "outcome": 1, "brier": round((probability - 1) ** 2, 4),
                })
                store.update(
                    "events", int(event["id"]),
                    payload_json=json.dumps(payload))

    _mutate_manifest_pair(manifest, 0, flip_outcome)
    receipt = evaluate_oracle_campaign(manifest)
    run = next(item for item in receipt["runs"] if item["seed"] == _FIRST_SEED)
    assert any(
        "independent metric resolution" in reason
        for reason in run["forecasts"][0]["reasons"])


def test_planner_empty_attempt_then_valid_retry_is_bound_and_eligible(tmp_path):
    receipt = evaluate_oracle_campaign(
        _manifest(tmp_path, planner_retry=True))
    first = next(item for item in receipt["runs"] if item["seed"] == _FIRST_SEED)
    assert first["forecasts"][0]["eligible"] is True
    assert receipt["passed"] is True


def test_planner_invalid_args_attempt_then_valid_retry_is_eligible(tmp_path):
    receipt = evaluate_oracle_campaign(_manifest(
        tmp_path, planner_retry=True, planner_retry_invalid_args=True))

    first = next(item for item in receipt["runs"] if item["seed"] == _FIRST_SEED)
    forecast = first["forecasts"][0]
    assert forecast["eligible"] is True
    assert forecast["reasons"] == []
    assert receipt["passed"] is True


def _first_forecast_evidence(entry: dict) -> tuple[dict, list[str]]:
    with oracle_campaign._private_store(Path(entry["database"])) as store:
        config = load_config(entry["profile"])
        item = config["acceptance"]["oracle_questions"][0]
        return oracle_campaign._forecast_evidence(
            store, item=item, acceptance=config["acceptance"],
            expected_provider=oracle_campaign.RELEASE_ORACLE_PROVIDER,
            expected_model=RELEASE_ORACLE_MODEL)


@pytest.mark.parametrize("shape", ["canonical_noop", "non_list"])
def test_normalized_invalid_planner_json_can_retry_and_remain_eligible(
        tmp_path, shape):
    entry = _write_run(
        tmp_path, 0, planner_retry=True, planner_retry_shape=shape)

    forecast, reasons = _first_forecast_evidence(entry)

    assert forecast["eligible"] is True
    assert reasons == []


@pytest.mark.parametrize(
    "shape", ["missing_entity", "future_tick", "extra_query_field"])
def test_shared_preflight_planner_errors_can_retry_and_remain_eligible(
        tmp_path, shape):
    entry = _write_run(
        tmp_path, 0, planner_retry=True, planner_retry_shape=shape)

    forecast, reasons = _first_forecast_evidence(entry)

    assert forecast["eligible"] is True
    assert reasons == []


def test_canonical_noop_planner_response_requires_repair_metering(tmp_path):
    entry = _write_run(
        tmp_path, 0, planner_retry=True,
        planner_retry_shape="canonical_noop")
    store = Store(entry["database"], create=False)
    row = store.query_one(
        "SELECT * FROM llm_calls WHERE tick=5 AND role='oracle' "
        "AND purpose='oracle_plan' ORDER BY id LIMIT 1")
    response = json.loads(row["response_json"])
    response["raw"] = response["raw"]["repair"]["initial"]
    direct_cost = (
        10 * RELEASE_ORACLE_PRICING["in"] / 1_000_000
        + 10 * RELEASE_ORACLE_PRICING["out"] / 1_000_000)
    store.update(
        "llm_calls", int(row["id"]), response_json=json.dumps(response),
        in_tokens=10, out_tokens=10, cost_usd=direct_cost)
    config = load_config(entry["profile"])
    item = config["acceptance"]["oracle_questions"][0]

    forecast, reasons = oracle_campaign._forecast_evidence(
        store, item=item, acceptance=config["acceptance"],
        expected_provider=oracle_campaign.RELEASE_ORACLE_PROVIDER,
        expected_model=RELEASE_ORACLE_MODEL)
    store.close()

    assert forecast["eligible"] is False
    assert (
        "canonical no-op planner response lacks repair-call provenance"
        in reasons)


def test_jointly_forged_rejection_and_retry_context_fail_closed(tmp_path):
    entry = _write_run(
        tmp_path, 0, planner_retry=True,
        planner_retry_invalid_args=True,
        planner_rejection_state="forged_pair")

    forecast, reasons = _first_forecast_evidence(entry)

    assert forecast["eligible"] is False
    assert "planner rejection error is not independently reproducible" in reasons


def test_long_rejection_requires_the_full_retry_error_context(tmp_path):
    entry = _write_run(
        tmp_path, 0, planner_retry=True, planner_retry_shape="long_error",
        planner_rejection_state="truncated_context")

    forecast, reasons = _first_forecast_evidence(entry)

    assert forecast["eligible"] is False
    assert "planner retry context does not bind its rejection error" in reasons


def test_valid_plan_cannot_be_recast_as_a_rejected_attempt(tmp_path):
    entry = _write_run(
        tmp_path, 0, planner_retry=True, planner_retry_shape="valid")

    forecast, reasons = _first_forecast_evidence(entry)

    assert forecast["eligible"] is False
    assert "planner rejection error is not independently reproducible" in reasons


def test_two_bound_rejections_then_third_plan_are_eligible(tmp_path):
    entry = _write_run(
        tmp_path, 0, planner_retry=True,
        planner_retry_invalid_args=True, planner_retry_twice=True)

    forecast, reasons = _first_forecast_evidence(entry)

    assert forecast["eligible"] is True
    assert reasons == []


def test_identical_rejections_have_distinct_bound_retry_attempts(tmp_path):
    entry = _write_run(
        tmp_path, 0, planner_retry=True,
        planner_retry_invalid_args=True, planner_retry_twice=True,
        planner_retry_same_error=True)

    forecast, reasons = _first_forecast_evidence(entry)

    assert forecast["eligible"] is True
    assert reasons == []


@pytest.mark.parametrize(
    "rejection_state", ["missing_second", "misordered_second"])
def test_two_retry_chain_requires_ordered_complete_rejections(
        tmp_path, rejection_state):
    entry = _write_run(
        tmp_path, 0, planner_retry=True,
        planner_retry_invalid_args=True, planner_retry_twice=True,
        planner_rejection_state=rejection_state)

    forecast, reasons = _first_forecast_evidence(entry)

    assert forecast["eligible"] is False
    assert any(
        "planner retry attempts" in reason
        or "planner rejection event" in reason
        for reason in reasons)


@pytest.mark.parametrize("rejection_state", ["missing", "mismatched_error"])
def test_planner_invalid_retry_requires_authenticated_rejection(
        tmp_path, rejection_state):
    receipt = evaluate_oracle_campaign(_manifest(
        tmp_path, planner_retry=True, planner_retry_invalid_args=True,
        planner_rejection_state=rejection_state))

    first = next(item for item in receipt["runs"] if item["seed"] == _FIRST_SEED)
    forecast = first["forecasts"][0]
    assert forecast["eligible"] is False
    assert any(
        "planner retry" in reason or "planner rejection" in reason
        for reason in forecast["reasons"])
    assert receipt["passed"] is False


@pytest.mark.parametrize("attempt", [True, 1.0])
def test_planner_rejection_attempt_requires_exact_integer_type(tmp_path, attempt):
    receipt = evaluate_oracle_campaign(_manifest(
        tmp_path, planner_retry=True, planner_retry_invalid_args=True,
        planner_rejection_attempt=attempt))

    first = next(item for item in receipt["runs"] if item["seed"] == _FIRST_SEED)
    forecast = first["forecasts"][0]
    assert forecast["eligible"] is False
    assert "planner rejection event does not bind its rejected response" in (
        forecast["reasons"])
    assert receipt["passed"] is False


def test_final_planner_attempt_still_requires_valid_tool_arguments(tmp_path):
    entry = _write_run(tmp_path, 0)
    store = Store(entry["database"], create=False)
    row = store.query_one(
        "SELECT * FROM llm_calls WHERE tick=5 AND role='oracle' "
        "AND purpose='oracle_plan' ORDER BY id DESC LIMIT 1")
    response = json.loads(row["response_json"])
    response["text"] = json.dumps({
        "queries": [{
            "tool": "get_ledger_summary",
            "args": {
                "entity_type": "agent", "entity_id": 1,
                "from_tick": 0, "to_tick": 5,
            },
        }],
    })
    store.update(
        "llm_calls", int(row["id"]), response_json=json.dumps(response))
    config = load_config(entry["profile"])
    item = config["acceptance"]["oracle_questions"][0]

    forecast, reasons = oracle_campaign._forecast_evidence(
        store, item=item, acceptance=config["acceptance"],
        expected_provider=oracle_campaign.RELEASE_ORACLE_PROVIDER,
        expected_model=RELEASE_ORACLE_MODEL)

    assert forecast["eligible"] is False
    assert any(
        reason == (
            "scheduled planner query is invalid: invalid arguments for "
            "get_ledger_summary: unexpected from_tick, to_tick")
        for reason in reasons)

    response["text"] = json.dumps({
        "queries": [{
            "tool": "query_metrics",
            "args": {
                "names": ["unit_metric"], "from_tick": 5, "to_tick": 1,
            },
        }],
    })
    store.update(
        "llm_calls", int(row["id"]), response_json=json.dumps(response))
    forecast, reasons = oracle_campaign._forecast_evidence(
        store, item=item, acceptance=config["acceptance"],
        expected_provider=oracle_campaign.RELEASE_ORACLE_PROVIDER,
        expected_model=RELEASE_ORACLE_MODEL)
    store.close()

    assert forecast["eligible"] is False
    assert "scheduled planner query is invalid: invalid tick range" in reasons


def test_answer_prompt_structurally_bounds_maximum_evidence_without_losing_contract():
    contract = {
        "campaign_id": RELEASE_CAMPAIGN_ID,
        "campaign_version": RELEASE_CAMPAIGN_VERSION,
        "campaign_key": "bank_run_t005", "scheduled_tick": 5,
        "resolution_rule": {"type": "bank_run", "window": 5,
                            "deposit_drop": 0.30},
        "deadline_tick": 35,
    }
    raw = [
        {"tool": "query_metrics", "args": {"names": [f"metric_{index}"]},
         "result": {"rows": ["x" * 5_000]}}
        for index in range(8)
    ]
    evidence = _bound_prompt_evidence(raw)
    encoded, prompt_world = _answer_user_json(
        question="What is the probability of a bank run within 30 ticks?",
        tick=5, world={"large": "y" * 20_000}, evidence=evidence,
        governed_contract=contract)
    payload = json.loads(encoded)

    assert len(encoded) <= MAX_ANSWER_USER_CHARS
    assert next(iter(payload)) == "governed_forecast_contract"
    assert payload["governed_forecast_contract"] == contract
    assert payload["question"].startswith("What is the probability")
    assert payload["read_only_evidence"] == evidence
    assert payload["world"] == prompt_world
    assert [
        {"tool": item["tool"], "args": item["args"]} for item in evidence
    ] == [
        {"tool": item["tool"], "args": item["args"]} for item in raw
    ]


def test_oracle_evidence_compact_boundary_and_argument_schemas():
    base = [{"tool": "query_metrics", "args": {"names": ["gdp_proxy"]},
             "result": ""}]
    base_chars = len(canonical_oracle_json(base))
    at_limit = [{**base[0], "result": "x" * (
        MAX_PROMPT_EVIDENCE_CHARS - base_chars)}]
    over_limit = [{**base[0], "result": "x" * (
        MAX_PROMPT_EVIDENCE_CHARS - base_chars + 1)}]

    assert len(canonical_oracle_json(at_limit)) == 8000
    assert validate_bounded_oracle_evidence(
        at_limit, allowed_tools={"query_metrics"}) is True
    assert len(canonical_oracle_json(over_limit)) == 8001
    assert validate_bounded_oracle_evidence(
        over_limit, allowed_tools={"query_metrics"}) is False
    bounded = bound_oracle_evidence(over_limit)
    assert validate_bounded_oracle_evidence(
        bounded, allowed_tools={"query_metrics"}) is True
    assert bounded[0]["result"]["truncated"] is True
    assert set(bounded[0]["result"]) == {
        "truncated", "sha256", "original_chars", "json_prefix"}

    with pytest.raises(ValueError):
        validate_oracle_tool_args("query_metrics", {
            "names": ["gdp_proxy"], "limit": True})
    with pytest.raises(ValueError):
        validate_oracle_tool_args("read_news", {"limit": 2, "sql": "SELECT 1"})


def test_actual_small_open_run_replay_tracks_every_source_call_once(tmp_path):
    config = load_config("runs/oracle/calibration-control-rehearsal.yaml")
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    source_store, source_world, source_id = open_run(
        config, None, None, data_dir=tmp_path)
    try:
        asyncio.run(source_world.run(max_ticks=1))
        source_tick = source_store.tick
        source_path = Path(source_store.path)
    finally:
        _close_run(source_world, source_store)

    replay_store, replay_world, _ = open_run(
        config, None, source_id, data_dir=tmp_path)
    replay_path = Path(replay_store.path)
    try:
        asyncio.run(replay_headless(replay_world, source_tick))
        tracker = replay_world.gateway.replay_execution_stats()
    finally:
        _close_run(replay_world, replay_store)

    proof = verify_replay(source_path, replay_path)
    assert proof["exact"] is True
    assert tracker["source_nonoperational_calls"] > 0
    assert tracker["all_nonoperational_calls_consumed_once"] is True
    assert tracker["source_logical_calls_sha256"] == (
        tracker["consumed_logical_calls_sha256"])
    assert tracker["exact_key_matches"] == tracker["consumed_source_calls"]
    assert tracker["compatibility_fallback_matches"] == 0
    assert tracker["live_dispatch_count"] == 0


def test_replay_headless_fails_if_world_pauses_before_target(tmp_path, monkeypatch):
    config = load_config("runs/oracle/calibration-control-rehearsal.yaml")
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    source_store, source_world, source_id = open_run(
        config, None, None, data_dir=tmp_path)
    try:
        asyncio.run(source_world.run(max_ticks=1))
    finally:
        _close_run(source_world, source_store)

    replay_store, replay_world, _ = open_run(
        config, None, source_id, data_dir=tmp_path)

    async def pause_without_progress(*, max_ticks):
        assert max_ticks == 1

    monkeypatch.setattr(replay_world, "run", pause_without_progress)
    try:
        with pytest.raises(
                RuntimeError, match="replay stopped at tick 0 before target tick 1"):
            asyncio.run(replay_headless(replay_world, 1))
    finally:
        _close_run(replay_world, replay_store)


def test_semantics6_oversized_oracle_transcript_replays_with_recorded_shape(tmp_path):
    config = load_config("runs/oracle/calibration-control-rehearsal.yaml")
    config["engine_semantics_version"] = 6
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    source_store, source_world, source_id = open_run(
        config, None, None, data_dir=tmp_path)
    oversized = [{
        "tool": "query_metrics", "args": {"names": ["gdp_proxy"]},
        "result": {"legacy": "x" * 9000},
    }]
    source_world.oracle.tools.execute_plan_legacy = lambda _queries: oversized
    try:
        asyncio.run(source_world.oracle.ask("Will unemployment rise?"))
        source_path = Path(source_store.path)
    finally:
        _close_run(source_world, source_store)

    replay_store, replay_world, _ = open_run(
        config, None, source_id, data_dir=tmp_path)
    replay_path = Path(replay_store.path)
    replay_world.oracle.tools.execute_plan_legacy = lambda _queries: oversized
    try:
        asyncio.run(replay_headless(replay_world, 0))
        tracker = replay_world.gateway.replay_execution_stats()
    finally:
        _close_run(replay_world, replay_store)

    assert len(canonical_oracle_json(oversized)) > 8000
    assert tracker["compatibility_fallback_matches"] == 0
    assert tracker["exact_key_matches"] == tracker["consumed_source_calls"]
    assert verify_replay(source_path, replay_path)["exact"] is True


@pytest.mark.parametrize(("semantics_version", "hardened_evidence"), [
    (6, False), (7, False), (7, True),
])
def test_pre_state_bound_government_rejection_replays_with_legacy_shape(
        tmp_path, semantics_version, hardened_evidence):
    config = load_config("runs/oracle/calibration-control-rehearsal.yaml")
    config["engine_semantics_version"] = semantics_version
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    source_store, source_world, source_id = open_run(
        config, None, None, data_dir=tmp_path)
    if semantics_version == 7:
        source_world.oracle._state_bound_preflight_at = (
            lambda _tick, _question: False)
        if not hardened_evidence:
            source_world.oracle._hardened_evidence_at = (
                lambda _tick, _question: False)
    else:
        for legacy_args in (
                {"entity_type": "gov", "_treasury_alias": True},
                {"entity_type": "agent", "entity_id": 1,
                 "_treasury_alias": True}):
            with pytest.raises(OracleToolError, match="_treasury_alias"):
                source_world.oracle.tools.execute_plan_legacy([{
                    "tool": "get_ledger_summary", "args": legacy_args,
                }])
    scripted = source_world.gateway.adapters["scripted"]

    def legacy_plan(context):
        if "previous_plan_error" not in context:
            return {"queries": [{
                "tool": "get_ledger_summary",
                "args": {"entity_type": "gov"},
            }]}
        return {"queries": [{
            "tool": "query_metrics",
            "args": {"names": ["unemployment_rate"],
                     "from_tick": 0, "to_tick": 0, "limit": 10},
        }]}

    scripted.register("oracle_plan", legacy_plan)
    question = "Will unemployment rise?"
    try:
        result = asyncio.run(source_world.oracle.ask(question))
        source_path = Path(source_store.path)
        purposes = [str(row["purpose"]) for row in source_store.query(
            "SELECT purpose FROM llm_calls WHERE role='oracle' ORDER BY id")]
        planner_contexts = [
            json.loads(row["request_json"])["context"]
            for row in source_store.query(
                "SELECT request_json FROM llm_calls "
                "WHERE role='oracle' AND purpose='oracle_plan' ORDER BY id")]
        rejections = [json.loads(row["payload_json"])
                      for row in source_store.query(
                          "SELECT payload_json FROM events "
                          "WHERE kind='oracle_tool_plan_rejected' ORDER BY id")]
    finally:
        _close_run(source_world, source_store)

    assert result["evidence"][0]["tool"] == "query_metrics"
    assert purposes == ["oracle_plan", "oracle_plan", "oracle"]
    assert all("preflight_contract" not in item for item in planner_contexts)
    assert [item["error"] for item in rejections] == [
        "entity ledger accounts not found"]
    assert ("attempt" in rejections[0]) is hardened_evidence
    assert ("plan_sha256" in rejections[0]) is hardened_evidence

    replay_store, replay_world, _ = open_run(
        config, None, source_id, data_dir=tmp_path)
    replay_path = Path(replay_store.path)
    try:
        replay_result = asyncio.run(replay_world.oracle.ask(question))
        tracker = replay_world.gateway.replay_execution_stats()
    finally:
        _close_run(replay_world, replay_store)

    assert replay_result == result
    assert tracker["compatibility_fallback_matches"] == 0
    assert tracker["exact_key_matches"] == tracker["consumed_source_calls"]
    assert verify_replay(source_path, replay_path)["exact"] is True


def test_oracle_runtime_records_empty_plan_rejection_before_valid_retry(tmp_path):
    config = load_config("runs/oracle/calibration-control-rehearsal.yaml")
    store = Store(str(tmp_path / "runtime-retry.db"))
    store.init_run_meta("runtime-retry", config["seed"], config)
    world = World(store, config)
    world.initialize()

    class RetryGateway:
        replay = False
        replay_conn = None

        def __init__(self):
            self.requests = []

        async def complete(self, request, **_kwargs):
            self.requests.append(request)
            plans = [item for item in self.requests
                     if item.purpose == "oracle_plan"]
            if request.purpose == "oracle_plan" and len(plans) <= 2:
                return SimpleNamespace(parsed={"queries": []})
            if request.purpose == "oracle_plan":
                return SimpleNamespace(parsed={"queries": [{
                    "tool": "query_metrics",
                    "args": {"names": ["gdp_proxy"], "from_tick": 0,
                             "to_tick": store.tick, "limit": 10},
                }]})
            return SimpleNamespace(parsed={
                "p": 0.2, "drivers": ["stable deposits"],
                "confidence": "med", "resolution_rule": {
                    "type": "bank_run", "window": 5, "deposit_drop": 0.30},
                "deadline_tick": store.tick + 30,
                "reasoning": "bounded evidence",
            })

    gateway = RetryGateway()
    world.oracle.gw = gateway
    contract = {
        "campaign_id": RELEASE_CAMPAIGN_ID,
        "campaign_version": RELEASE_CAMPAIGN_VERSION,
        "campaign_key": "bank_run_t000", "scheduled_tick": store.tick,
        "resolution_rule": {
            "type": "bank_run", "window": 5, "deposit_drop": 0.30},
        "deadline_tick": store.tick + 30,
    }
    result = asyncio.run(world.oracle.ask(
        "What is the probability of a bank run within 30 ticks?",
        governed_contract=contract))

    assert result["p"] == 0.2
    assert [request.purpose for request in gateway.requests] == [
        "oracle_plan", "oracle_plan", "oracle_plan", "oracle"]
    plan_requests = gateway.requests[:3]
    assert "planner_attempt" not in plan_requests[0].context
    assert [request.context["planner_attempt"] for request in plan_requests[1:]] == [
        2, 3]
    assert len({request.user for request in plan_requests}) == 3
    rejections = [json.loads(row["payload_json"]) for row in store.query(
        "SELECT payload_json FROM events "
        "WHERE kind='oracle_tool_plan_rejected' ORDER BY id")]
    assert [rejection["attempt"] for rejection in rejections] == [1, 2]
    assert all(len(rejection["plan_sha256"]) == 64 for rejection in rejections)
    answer_user = json.loads(gateway.requests[-1].user)
    assert answer_user["governed_forecast_contract"] == contract
    assert answer_user["read_only_evidence"] == result["evidence"]
    store.close()


def test_historical_tool_catalog_and_government_treasury_are_executable(tmp_path):
    config = load_config("runs/oracle/calibration-control-rehearsal.yaml")
    store = Store(str(tmp_path / "historical-tool-catalog.db"))
    store.init_run_meta("historical-tool-catalog", config["seed"], config)
    world = World(store, config)
    world.initialize()
    future_agent_id = store.insert(
        "agents", name="Future Arrival", kind="citizen", arrived_tick=10)
    Ledger(store).create_account(
        "agent", future_agent_id, "checking", label="future checking")

    legacy = oracle_tool_definitions(store)
    at_five = oracle_tool_definitions(store, tick=5)
    at_ten = oracle_tool_definitions(store, tick=10)
    ledger_at_five = next(
        item for item in at_five if item["name"] == "get_ledger_summary")
    ledger_at_ten = next(
        item for item in at_ten if item["name"] == "get_ledger_summary")
    government = world.oracle.tools.get_ledger_summary("gov")

    legacy_conversations = next(
        item for item in legacy if item["name"] == "sample_conversations")
    legacy_ledger = next(
        item for item in legacy if item["name"] == "get_ledger_summary")
    assert "available_agent_ids" not in legacy_conversations
    assert set(legacy_ledger["available_entity_ids"]) == {"bank"}
    assert future_agent_id not in ledger_at_five["available_entity_ids"]["agent"]
    assert future_agent_id in ledger_at_ten["available_entity_ids"]["agent"]
    assert "gov" in ledger_at_five["available_entity_types"]
    assert any(account["label"] == SYS_GOV for account in government["accounts"])
    store.close()


def test_semantics7_unknown_entity_retry_is_shared_preflight(tmp_path):
    config = load_config("runs/oracle/calibration-control-rehearsal.yaml")
    store = Store(str(tmp_path / "catalog-retry.db"))
    store.init_run_meta("catalog-retry", config["seed"], config)
    world = World(store, config)
    world.initialize()
    bank_id = int(store.scalar("SELECT MIN(id) FROM banks"))

    class CatalogRetryGateway:
        replay = False
        replay_conn = None

        def __init__(self):
            self.requests = []

        async def complete(self, request, **_kwargs):
            self.requests.append(request)
            plans = [item for item in self.requests
                     if item.purpose == "oracle_plan"]
            if request.purpose == "oracle_plan" and len(plans) == 1:
                return SimpleNamespace(parsed={"queries": [{
                    "tool": "get_ledger_summary",
                    "args": {"entity_type": "bank", "entity_id": 99999},
                }]})
            if request.purpose == "oracle_plan":
                assert request.context["previous_plan_error"] == (
                    "entity ledger accounts not found")
                assert request.context["planner_attempt"] == 2
                return SimpleNamespace(parsed={"queries": [{
                    "tool": "get_ledger_summary",
                    "args": {"entity_type": "bank", "entity_id": bank_id},
                }]})
            return SimpleNamespace(parsed={
                "p": 0.2, "drivers": ["stable deposits"],
                "confidence": "med", "resolution_rule": {
                    "type": "bank_run", "window": 5, "deposit_drop": 0.30},
                "deadline_tick": store.tick + 30,
                "reasoning": "bounded evidence",
            })

    gateway = CatalogRetryGateway()
    world.oracle.gw = gateway
    contract = {
        "campaign_id": RELEASE_CAMPAIGN_ID,
        "campaign_version": RELEASE_CAMPAIGN_VERSION,
        "campaign_key": "bank_run_t000", "scheduled_tick": store.tick,
        "resolution_rule": {
            "type": "bank_run", "window": 5, "deposit_drop": 0.30},
        "deadline_tick": store.tick + 30,
    }

    result = asyncio.run(world.oracle.ask(
        "What is the probability of a bank run within 30 ticks?",
        governed_contract=contract))
    rejections = store.query(
        "SELECT payload_json FROM events "
        "WHERE kind='oracle_tool_plan_rejected' ORDER BY id")

    assert result["evidence"][0]["result"]["entity_id"] == bank_id
    assert [request.purpose for request in gateway.requests] == [
        "oracle_plan", "oracle_plan", "oracle"]
    assert len(rejections) == 1
    assert json.loads(rejections[0]["payload_json"])["error"] == (
        "entity ledger accounts not found")
    store.close()


@pytest.mark.parametrize("failure_type", [OracleToolError, RuntimeError])
def test_semantics7_post_preflight_tool_failure_does_not_retry(
        tmp_path, failure_type):
    config = load_config("runs/oracle/calibration-control-rehearsal.yaml")
    store = Store(str(tmp_path / "execution-failure.db"))
    store.init_run_meta("execution-failure", config["seed"], config)
    world = World(store, config)
    world.initialize()

    class OnePlanGateway:
        replay = False
        replay_conn = None

        def __init__(self):
            self.requests = []

        async def complete(self, request, **_kwargs):
            self.requests.append(request)
            return SimpleNamespace(parsed={"queries": [{
                "tool": "query_metrics",
                "args": {"names": ["gdp_proxy"], "from_tick": 0,
                         "to_tick": store.tick, "limit": 10},
            }]})

    def fail_after_preflight(**_kwargs):
        raise failure_type("forced post-preflight failure")

    gateway = OnePlanGateway()
    world.oracle.gw = gateway
    world.oracle.tools._tools["query_metrics"] = fail_after_preflight
    contract = {
        "campaign_id": RELEASE_CAMPAIGN_ID,
        "campaign_version": RELEASE_CAMPAIGN_VERSION,
        "campaign_key": "bank_run_t000", "scheduled_tick": store.tick,
        "resolution_rule": {
            "type": "bank_run", "window": 5, "deposit_drop": 0.30},
        "deadline_tick": store.tick + 30,
    }

    with pytest.raises(failure_type, match="forced post-preflight failure"):
        asyncio.run(world.oracle.ask(
            "What is the probability of a bank run within 30 ticks?",
            governed_contract=contract))

    assert [request.purpose for request in gateway.requests] == ["oracle_plan"]
    assert store.scalar(
        "SELECT COUNT(*) FROM events "
        "WHERE kind='oracle_tool_plan_rejected'") == 0
    failures = store.query(
        "SELECT payload_json FROM events "
        "WHERE kind='oracle_tool_execution_failed'")
    assert len(failures) == 1
    assert json.loads(failures[0]["payload_json"])["error_type"] == (
        failure_type.__name__)
    store.close()


@pytest.mark.parametrize("oracle_args", [
    ["--oracle-campaign-run"],
    ["--oracle-calibration-report", "manifest.yaml"],
])
@pytest.mark.parametrize("conflict", [
    ["--preflight"], ["--preflight-live"], ["--serve"],
    ["--acceptance-run"], ["--acceptance-report", "run-id"],
    ["--experiment", "experiment.yaml"],
    ["--counterfactual", "scenario.yaml"],
    ["--replay", "run-id"], ["--fork", "run-id@10"],
    ["--verify-datasets", "manifest.yaml"],
    ["--refresh-datasets", "manifest.yaml"],
    ["--report", "run-id"], ["--export-static", "run-id"],
])
def test_oracle_evidence_commands_reject_every_other_primary_mode(
        monkeypatch, capsys, oracle_args, conflict):
    monkeypatch.setattr(sys, "argv", ["run.py", *oracle_args, *conflict])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert "mutually exclusive" in capsys.readouterr().err


def test_oracle_evidence_commands_are_mutually_exclusive(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [
        "run.py", "--oracle-campaign-run",
        "--oracle-calibration-report", "manifest.yaml",
    ])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert "mutually exclusive" in capsys.readouterr().err


def test_oracle_calibration_report_rejects_run_tick_mode(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [
        "run.py", "--oracle-calibration-report", "manifest.yaml",
        "--ticks", "10",
    ])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert "--ticks" in capsys.readouterr().err
    _expected_replay_tracker,
    finalize_sqlite_artifact,
    mark_oracle_campaign_initialized,
    write_oracle_source_receipt,
    write_replay_execution_receipt,

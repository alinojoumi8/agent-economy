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

from engine.ledger import Leg, Ledger
from engine.checkpoint_manifest import write_checkpoint_manifest
from engine.store import Store
import reports.oracle_campaign as oracle_campaign
import run as run_cli
from reports.oracle_campaign import (
    OracleCampaignError,
    RELEASE_COMMITMENT_SHA256,
    _expected_replay_tracker,
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
    MAX_PROMPT_EVIDENCE_CHARS, bound_oracle_evidence,
    canonical_oracle_json, oracle_tool_definitions,
    validate_bounded_oracle_evidence, validate_oracle_tool_args,
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
    engine = random.Random(seed).getstate()
    lifecycle = random.Random(seed ^ 0x5F5E5F).getstate()
    checkpoint.set_meta(
        tick=tick, status="running", phase="FINALIZE", active_tick=None,
        next_phase="NIGHT_CLOSE", phase_state_json="{}",
        prng_state=json.dumps([engine[0], list(engine[1]), engine[2]]),
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
    receipt_dir: Path | None = None,
) -> dict:
    seed = 7301 + index
    run_id = f"oracle-calibration-v1-s{seed}"
    arm = "rumor" if seed % 2 == 0 else "control"
    profile_path = (Path("runs/oracle") / f"seed-{seed}-{arm}.yaml").resolve()
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
        provider = "made-up-provider" if invalid_provider and tick == 5 else "kimi"
        governed_contract = {
            "campaign_id": "oracle-calibration-v1",
            "campaign_version": 1,
            "campaign_key": item["campaign_key"],
            "scheduled_tick": tick,
            "resolution_rule": item["expected_rule"],
            "deadline_tick": tick + 30,
        }
        purposes = (
            ("oracle_plan", "oracle_plan", "oracle")
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
                ({"queries": []} if planner_retry and tick == 5
                 and purpose == "oracle_plan" and plan_number == 1 else
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
                    "available_tools": oracle_tool_definitions(store),
                    "constraints": {
                        "tick_range": {"minimum": 0, "maximum": tick},
                        "maximum_queries": 8, "read_only": True,
                    },
                }
                if planner_retry and tick == 5 and plan_number == 2:
                    context.update({
                        "previous_plan_error": (
                            "at least one evidence query is required"),
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
                "m": "kimi-for-coding",
                "msgs": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_text},
                ],
            }, sort_keys=True).encode()).hexdigest()
            store.insert(
                "llm_calls", tick=tick, role="oracle", purpose=purpose,
                provider=provider, model="kimi-for-coding",
                cache_key=cache_key,
                request_json=json.dumps({
                    "system": system, "user": user_text,
                    "context": context,
                }),
                response_json=json.dumps({
                    "text": json.dumps(response),
                    "raw": {
                        "id": (
                            f"chatcmpl-{run_id}-{tick}-{purpose}-{plan_number}"),
                        "model": "kimi-for-coding",
                        "object": "chat.completion",
                        "usage": {
                            "prompt_tokens": 10, "completion_tokens": 10,
                            "prompt_tokens_details": {"cached_tokens": 0},
                        },
                    },
                    "cached_in_tokens": 0,
                }),
                in_tokens=10, out_tokens=10, cost_usd=0.0000495,
                latency_ms=10)
            model_calls.append({
                "purpose": purpose, "provider": provider,
                "model": "kimi-for-coding",
                "request_key": cache_key, "call_latency_ms": 10,
            })
            if (planner_retry and tick == 5 and purpose == "oracle_plan"
                    and plan_number == 1):
                plan_hash = hashlib.sha256(json.dumps(
                    response, sort_keys=True, separators=(",", ":"),
                ).encode("utf-8")).hexdigest()
                store.log_event(tick, "oracle_tool_plan_rejected", {
                    "question": item["question"], "attempt": 1,
                    "plan_sha256": plan_hash,
                    "error": "at least one evidence query is required",
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
            "campaign_id": "oracle-calibration-v1",
            "campaign_version": 1,
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
) -> Path:
    runs = [
        _write_run(
            tmp_path, index,
            invalid_provider=invalid_provider and index == 0,
            invalid_evidence=invalid_evidence and index == 0,
            planner_retry=planner_retry and index == 0)
        for index in range(10)
    ]
    path = tmp_path / "oracle-campaign.yaml"
    path.write_text(yaml.safe_dump({
        "schema_version": 1,
        "campaign_id": "oracle-calibration-v1",
        "campaign_version": 1,
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
    assert receipt["excluded_runs"][0]["run_id"] == (
        "oracle-calibration-v1-s7301")
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
        "campaign_id": "oracle-calibration-v1",
        "campaign_version": 1,
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
        "campaign_id": "oracle-calibration-v1",
        "campaign_version": 1,
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


def test_oracle_campaign_rejects_self_asserted_unmetered_kimi_calls(tmp_path):
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
    first = next(run for run in receipt["runs"] if run["seed"] == 7301)
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
    first = next(run for run in receipt["runs"] if run["seed"] == 7301)
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
    first = next(run for run in receipt["runs"] if run["seed"] == 7301)
    assert any(
        "pinned Kimi pricing" in reason
        for reason in first["forecasts"][0]["reasons"])


def test_openai_metering_accepts_valid_direct_and_gateway_repair_shapes():
    direct_row = {
        "in_tokens": 10, "out_tokens": 10, "cost_usd": 0.0000495,
    }
    direct_response = {
        "cached_in_tokens": 0,
        "raw": {"id": "chatcmpl-direct", "model": "kimi-for-coding",
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
        "cached_in_tokens": 0, "expected_cost_usd": 0.0000495,
    }

    repair_row = {
        "in_tokens": 10, "out_tokens": 10, "cost_usd": 0.00004798,
    }
    repair_response = {
        "cached_in_tokens": 2,
        "raw": {"provider_calls": 2, "repair": {
            "initial": {"id": "chatcmpl-initial", "model": "kimi-for-coding",
                        "object": "chat.completion", "usage": {
                "prompt_tokens": 4, "completion_tokens": 3,
                "prompt_tokens_details": {"cached_tokens": 1},
            }},
            "final": {"id": "chatcmpl-final", "model": "kimi-for-coding",
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
    entry = payload["runs"][1]  # seed 7302, treatment arm
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
    profiles = sorted(root.glob("seed-*.yaml"))
    assert len(profiles) == 10
    configs = [load_config(path) for path in profiles]
    assert {config["seed"] for config in configs} == set(range(7301, 7311))
    for config in configs:
        acceptance = config["acceptance"]
        assert acceptance["min_ticks"] == 335
        assert acceptance["oracle_campaign_id"] == "oracle-calibration-v1"
        assert acceptance["oracle_campaign_version"] == 1
        assert acceptance["oracle_latency_source"] == "scheduled_e2e_v1"
        assert len(acceptance["oracle_questions"]) == 6
        assert config["llm"]["routes"]["oracle"] == {
            "provider": "kimi", "model": "kimi-for-coding",
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
        (root / "manifest-v1.template.yaml").read_text(encoding="utf-8"))
    assert [entry["seed"] for entry in manifest["runs"]] == list(range(7301, 7311))
    assert {entry["profile"] for entry in manifest["runs"]} == {
        path.name for path in profiles
    }


def test_oracle_campaign_profile_cannot_change_predeclared_arm():
    profile = load_config("runs/oracle/seed-7302-rumor.yaml")
    profile["shocks"][0]["params"]["n_agents"] = 2

    with pytest.raises(OracleCampaignError, match="predeclared campaign arm"):
        validate_oracle_campaign_profile(profile)


def test_oracle_campaign_profile_requires_official_kimi_endpoint():
    profile = load_config("runs/oracle/seed-7301-control.yaml")
    profile["llm"]["providers"]["kimi"]["base_url"] = "http://127.0.0.1:9999/v1"

    with pytest.raises(OracleCampaignError, match="official Kimi API"):
        validate_oracle_campaign_profile(profile)


def test_resumed_oracle_campaign_rejects_wrong_profile_before_dispatch(tmp_path):
    stored = load_config("runs/oracle/seed-7301-control.yaml")
    requested = load_config("runs/oracle/seed-7302-rumor.yaml")
    store = Store(str(tmp_path / "wrong-resume.db"))
    store.init_run_meta("wrong-resume", stored["seed"], stored)

    with pytest.raises(OracleCampaignError, match="checked-in predeclared"):
        validate_open_oracle_campaign_source(
            store, requested, "runs/oracle/seed-7302-rumor.yaml")
    assert store.scalar("SELECT COUNT(*) FROM llm_calls", default=0) == 0
    store.close()


def test_oracle_campaign_profile_cannot_change_question_or_horizon():
    profile = load_config("runs/oracle/seed-7301-control.yaml")
    profile["acceptance"]["oracle_questions"][0]["question"] = "Different?"
    with pytest.raises(OracleCampaignError, match="governed forecast contract"):
        validate_oracle_campaign_profile(profile)

    profile = load_config("runs/oracle/seed-7301-control.yaml")
    profile["acceptance"]["min_ticks"] = 334
    with pytest.raises(OracleCampaignError, match="fixed 335-tick horizon"):
        validate_oracle_campaign_profile(profile)


@pytest.mark.parametrize("forbidden", ["model", "messages"])
def test_oracle_campaign_rejects_request_defaults_that_override_wire_identity(
        forbidden):
    profile = load_config("runs/oracle/seed-7301-control.yaml")
    profile["llm"]["providers"]["kimi"]["request_defaults"][forbidden] = (
        "attacker-model" if forbidden == "model" else [])

    with pytest.raises(OracleCampaignError, match="official Kimi API"):
        validate_oracle_campaign_profile(profile)


def test_oracle_campaign_pins_complete_provider_and_pricing_contract():
    profile = load_config("runs/oracle/seed-7301-control.yaml")
    profile["llm"]["providers"]["kimi"]["unexpected"] = True
    with pytest.raises(OracleCampaignError, match="official Kimi API"):
        validate_oracle_campaign_profile(profile)

    profile = load_config("runs/oracle/seed-7301-control.yaml")
    profile["llm"]["pricing"]["kimi-for-coding"]["out"] = 0.0
    with pytest.raises(OracleCampaignError, match="pinned Kimi pricing"):
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
    profile_path = Path("runs/oracle/seed-7301-control.yaml")
    profile = load_config(profile_path)
    first = prepare_oracle_campaign_run(
        profile, profile_path, data_dir=tmp_path)

    assert first["run_id"] == "oracle-calibration-v1-s7301"
    assert Path(first["claim_path"]).is_file()
    resumed = prepare_oracle_campaign_run(
        profile, profile_path, data_dir=tmp_path,
        resume_run_id=first["run_id"])
    assert resumed["effective_config_sha256"] == effective_config_sha256(profile)
    with pytest.raises(OracleCampaignError, match="already claimed"):
        prepare_oracle_campaign_run(profile, profile_path, data_dir=tmp_path)


def test_claim_crash_recovery_never_resamples_initialized_or_partial_slot(tmp_path):
    profile_path = Path("runs/oracle/seed-7301-control.yaml")
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
    monkeypatch.setenv("KIMI_API_KEY", "unit-test-placeholder")
    profile_path = Path("runs/oracle/seed-7301-control.yaml")
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


def test_claim_and_initialized_marker_publication_never_clobbers_existing_bytes(
        tmp_path, monkeypatch):
    monkeypatch.setenv("KIMI_API_KEY", "unit-test-placeholder")
    profile_path = Path("runs/oracle/seed-7301-control.yaml")
    profile = load_config(profile_path)
    run_id = "oracle-calibration-v1-s7301"
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
        "run_id": "oracle-calibration-v1-s7301", "seed": 7301,
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
    lifecycle = random.Random(entry["seed"] ^ 0x5F5E5F).getstate()
    empty.set_meta(
        tick=tick, status="running", phase="FINALIZE", active_tick=None,
        next_phase="NIGHT_CLOSE", phase_state_json="{}",
        prng_state=json.dumps([engine[0], list(engine[1]), engine[2]]),
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
    assert (
        "source checkpoint schema/state/PRNG/core/ledger binding is invalid"
        in run["reasons"])


def test_global_llm_audit_allows_local_background_but_no_other_live_calls(
        tmp_path):
    store = Store(str(tmp_path / "calls.db"))
    for tick in oracle_campaign.RELEASE_QUESTION_TICKS:
        for purpose in ("oracle_plan", "oracle"):
            store.insert(
                "llm_calls", tick=tick, role="oracle", purpose=purpose,
                provider="kimi", model="kimi-for-coding", cache_key=(
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
        provider="kimi", model="kimi-for-coding", cache_key="smuggled-live")
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
    run = next(item for item in campaign["runs"] if item["seed"] == 7301)
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
    run = next(item for item in receipt["runs"] if item["seed"] == 7301)
    assert any(
        "independent metric resolution" in reason
        for reason in run["forecasts"][0]["reasons"])


def test_planner_empty_attempt_then_valid_retry_is_bound_and_eligible(tmp_path):
    receipt = evaluate_oracle_campaign(
        _manifest(tmp_path, planner_retry=True))
    first = next(item for item in receipt["runs"] if item["seed"] == 7301)
    assert first["forecasts"][0]["eligible"] is True
    assert receipt["passed"] is True


def test_answer_prompt_structurally_bounds_maximum_evidence_without_losing_contract():
    contract = {
        "campaign_id": "oracle-calibration-v1", "campaign_version": 1,
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
            if request.purpose == "oracle_plan" and len(plans) == 1:
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
        "campaign_id": "oracle-calibration-v1", "campaign_version": 1,
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
        "oracle_plan", "oracle_plan", "oracle"]
    rejection = json.loads(store.query_one(
        "SELECT payload_json FROM events WHERE kind='oracle_tool_plan_rejected'"
    )["payload_json"])
    assert rejection["attempt"] == 1
    assert len(rejection["plan_sha256"]) == 64
    answer_user = json.loads(gateway.requests[-1].user)
    assert answer_user["governed_forecast_contract"] == contract
    assert answer_user["read_only_evidence"] == result["evidence"]
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

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import multiprocessing
from pathlib import Path
import shutil
import sqlite3
import threading
import time

import pytest
from pydantic import ValidationError

from llm.adapters import AdapterResult
from llm.gateway import BudgetExceeded
from research.artifacts import digest_json, file_sha256
from research.policy_analysis import replicated_summary
from research.policy_studies import (
    declare_policy, draft_policy_comparison, policy_configurations,
    provider_budget_contract, study_cells,
)
from research.provider_budget import BudgetLedgerError, ProviderBudget, ProviderBudgetContract, TokenTariff
from research.studies import StudySpec, validate_study_inputs
from run_config import load_config

ROOT = Path(__file__).resolve().parents[1]


def base_policy_setup():
    config = load_config(ROOT / "runs/price-lab-pilot.yaml")
    scripted = declare_policy("scripted", {"default_route": {"provider": "scripted", "model": "scripted"}, "routes": {}}, temperature=None)
    live = declare_policy("model_a", {"default_route": {"provider": "fixture", "model": "model-a"},
        "providers": {"fixture": {"kind": "openai_compat", "base_url": "http://127.0.0.1:1/v1", "auth": "none"}}}, temperature=.4)
    tariff = TokenTariff(provider="fixture", model="model-a", max_input_tokens=4096,
        max_output_tokens=1024, input_nano_usd_per_token=10, output_nano_usd_per_token=20)
    spec = draft_policy_comparison(config, policies=[scripted, live], tariffs=[tariff],
        seeds=[1, 2], model_replicates=["draw1", "draw2", "draw3"], horizon=3,
        max_provider_calls=200, max_tokens=1_000_000, max_spend_usd=.1)
    return config, spec


@pytest.fixture
def policy_setup():
    return base_policy_setup()


def test_policy_declarations_bind_source_sampling_and_both_price_domains(policy_setup):
    config, spec = policy_setup
    assert spec.protocol_version == "research-study-v3"
    assert not any(arm.changes.shocks for arm in spec.arms)
    assert {item.key for item in spec.analysis.outcomes if item.purpose == "primary"} == {"goods_price", "equity_price"}
    protocol = validate_study_inputs(spec, config, input_root=ROOT)
    assert len(protocol["assigned_cells"]) == 12
    assert {item["seed"] for item in protocol["assigned_cells"]} == {1, 2}
    assert len({item["cell_key"] for item in protocol["assigned_cells"]}) == 12
    configs = protocol["policy_configurations"]
    assert configs["model_a"]["llm"]["research_sampling"] == {"primary": .4, "repair": .2, "preflight": 0.0}
    assert configs["model_a"]["budget"]["cap_usd"] is None
    assert configs["model_a"]["population"] == configs["scripted"]["population"] == config["population"]
    assert config["budget"]["cap_usd"] == 200.0  # Resolution is immutable.


@pytest.mark.parametrize("mutation", [
    lambda raw: raw["randomness"].update(model_replicates=[]),
    lambda raw: raw["randomness"].update(model_replicates=["same", "same"]),
    lambda raw: raw["analysis"].update(uncertainty="paired_world_bootstrap"),
    lambda raw: raw["arms"][1].update(policy="unknown"),
    lambda raw: raw["time"].update(warmup_ticks=1, intervention_start=2, intervention_end=2, measurement_start=2),
    lambda raw: raw["policy_design"]["tariffs"].clear(),
    lambda raw: raw["operations"].update(mode="provider_free", max_provider_calls=0, max_tokens=0, max_spend_usd=0.0),
])
def test_incomplete_or_confounding_policy_assignment_refuses(policy_setup, mutation):
    _, spec = policy_setup
    raw = spec.model_dump(mode="json")
    mutation(raw)
    with pytest.raises((ValueError, ValidationError)):
        StudySpec.model_validate(raw)


@pytest.mark.parametrize("mutation", [
    lambda raw: raw["policy_design"]["policies"][1]["behavior"].update(prompt_sha256="0" * 64),
    lambda raw: raw["policy_design"]["policies"][1]["llm"].update(routes={"citizen": {"provider": "fixture", "model": "other"}}),
    lambda raw: raw["policy_design"]["policies"][1]["llm"]["providers"]["fixture"].update(request_defaults={"n": 2}),
    lambda raw: raw["policy_design"]["policies"][1]["llm"].update(citizen_model_cohorts=[]),
])
def test_runtime_identity_is_verified_before_preparing_a_study(policy_setup, mutation):
    config, spec = policy_setup
    raw = spec.model_dump(mode="json")
    mutation(raw)
    with pytest.raises(ValueError):
        validate_study_inputs(StudySpec.model_validate(raw), config, input_root=ROOT)


def test_legacy_protocols_do_not_gain_policy_fields_or_replicates(policy_setup):
    from research.price_catalog import draft_price_study
    config, _ = policy_setup
    old = draft_price_study(config, "G2", seeds=[1, 2], horizon=3, intervention_tick=1)
    raw = old.model_dump(mode="json")
    assert "policy_design" not in raw and "origin" not in raw
    assert all("policy" not in arm for arm in raw["arms"])
    assert StudySpec.model_validate_json(json.dumps(raw)).model_dump(mode="json") == raw
    raw["randomness"]["model_replicates"] = ["draw1"]
    with pytest.raises(ValueError, match="model replicate scheduling"):
        StudySpec.model_validate(raw)


def test_named_budget_bindings_share_caps_and_reject_foreign_policy(policy_setup, tmp_path):
    config, spec = policy_setup
    raw = spec.model_dump(mode="json")
    raw["operations"]["max_provider_calls"] = 1
    spec = StudySpec.model_validate(raw)
    budget_contract = provider_budget_contract(spec, config, manifest_sha256="a" * 64)
    assert "gateway_config_sha256" not in budget_contract.model_dump(mode="json")
    budget = ProviderBudget.create(tmp_path / "budget.db", budget_contract, scope="preflight", binding_key="model_a")
    configs = policy_configurations(spec, config)
    budget.validate_config(configs["model_a"])
    with pytest.raises(BudgetLedgerError):
        budget.validate_config(configs["scripted"])

    class Adapter:
        calls = 0

        async def complete(self, *_args, **_kwargs):
            self.calls += 1
            return AdapterResult(text="{}", reported_usage=(10, 5))

    adapter = Adapter()
    message = [{"role": "user", "content": "fixture"}]
    asyncio.run(budget.complete("fixture", adapter, "model-a", message, purpose="preflight", max_tokens=100))
    resumed = ProviderBudget(budget.path, budget_contract, scope="later-cell", binding_key="model_a")
    with pytest.raises(BudgetExceeded):
        asyncio.run(resumed.complete("fixture", adapter, "model-a", message, purpose="decision", max_tokens=100))
    scripted = ProviderBudget(budget.path, budget_contract, scope="scripted-cell", binding_key="scripted")
    with pytest.raises(BudgetExceeded, match="not assigned"):
        asyncio.run(scripted.complete("fixture", adapter, "model-a", message, purpose="decision", max_tokens=100))
    assert adapter.calls == resumed.snapshot()["provider_calls"] == 1
    assert resumed.snapshot(scope="preflight")["provider_calls"] == 1
    assert resumed.snapshot(scope="later-cell")["provider_calls"] == 0
    with pytest.raises(ValueError, match="binding assigned"):
        ProviderBudget(budget.path, budget_contract, scope="unassigned")


def synthetic_results(spec):
    # Pure inference tests use scalar fixtures. Execution receipts are verified
    # by the integration layer, never fabricated by this aggregation function.
    return [{**cell, "ticks": spec.time.horizon, "expected_ticks": spec.time.horizon,
        "execution_status": "completed", "final_boundary": True, "reconciled": True,
        "database_integrity": True, "external_agent_influenced": False,
        "genesis_hash": digest_json({"world": cell["seed"]}),
        "eligibility": {"status": "eligible", "reasons": []},
        "metrics": {item.key: 10 + (2 * cell["seed"] if cell["policy"] == "model_a" else 0)
                    for item in spec.analysis.outcomes}} for cell in study_cells(spec)]


def test_model_draws_do_not_inflate_independent_world_count(policy_setup):
    _, spec = policy_setup
    summary = replicated_summary(synthetic_results(spec), spec)
    assert summary["replication"]["assigned_cells"] == 12
    assert summary["replication"]["independent_worlds"] == 2
    for metric in ["goods_price", "equity_price"]:
        effect = summary["metrics"][metric]["model_a"]["paired_effect"]
        assert effect["n_pairs"] == 2
        assert effect["mean_difference"] == 3
        assert effect["differences"] == [2, 4]


def test_missing_model_draw_excludes_the_paired_world(policy_setup):
    _, spec = policy_setup
    rows = synthetic_results(spec)
    rows = [row for row in rows if not (row["policy"] == "model_a" and row["seed"] == 1 and row["model_replicate"] == "draw2")]
    summary = replicated_summary(rows, spec)
    effect = summary["metrics"]["goods_price"]["model_a"]["paired_effect"]
    assert effect["n_pairs"] == 1 and effect["matched_seeds"] == [2]
    assert effect["status"] == "insufficient_replication"
    assert summary["replication"]["cell_exclusions"] == [{"arm": "model_a", "seed": 1,
        "model_replicate": "draw2", "reasons": ["missing_attempt"]}]


def test_missing_outcome_does_not_discard_other_price_domain(policy_setup):
    _, spec = policy_setup
    rows = synthetic_results(spec)
    next(row for row in rows if row["policy"] == "model_a" and row["seed"] == 1)["metrics"]["goods_price"] = None
    summary = replicated_summary(rows, spec)
    assert summary["metrics"]["goods_price"]["model_a"]["paired_effect"]["n_pairs"] == 1
    assert summary["metrics"]["equity_price"]["model_a"]["paired_effect"]["n_pairs"] == 2


@pytest.mark.parametrize("change", ["duplicate", "foreign_policy", "foreign_world", "boolean_seed"])
def test_foreign_or_duplicate_replicates_are_not_averaged(policy_setup, change):
    _, spec = policy_setup
    rows = synthetic_results(spec)
    if change == "duplicate":
        rows.append(copy.deepcopy(rows[0]))
    else:
        rows[0][{"foreign_policy": "policy", "foreign_world": "seed", "boolean_seed": "seed"}[change]] = {"foreign_policy": "unknown", "foreign_world": 999, "boolean_seed": True}[change]
    with pytest.raises(ValueError):
        replicated_summary(rows, spec)


def test_budgeted_world_executes_and_replays_without_live_replay_calls(policy_setup, tmp_path, monkeypatch):
    from dataclasses import replace
    import research.attempts as attempts
    from research.study_runner import collect_outcomes

    config, initial = policy_setup
    raw = initial.model_dump(mode="json")
    raw["policy_design"]["tariffs"][0].update(max_input_tokens=200_000, max_output_tokens=10_000)
    raw["operations"].update(max_provider_calls=500, max_tokens=100_000_000, max_spend_usd=2.0)
    spec = StudySpec.model_validate(raw)
    policy = provider_budget_contract(spec, config, manifest_sha256="a" * 64)
    budget = ProviderBudget.create(tmp_path / "budget.db", policy, scope="world", binding_key="model_a")
    resolved = policy_configurations(spec, config)["model_a"]
    real_world = attempts.World
    dispatches = []

    class FixtureWorld(real_world):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            scripted = self.gateway.adapters["scripted"]

            class PolicyFixture:
                async def complete(self, model, messages, **request):
                    dispatches.append((model, request["temperature"]))
                    result = await scripted.complete(model, messages, **request)
                    return replace(result, reported_usage=(result.in_tokens, result.out_tokens),
                                   raw={"controlled_policy_fixture": True})

            self.gateway.adapters["fixture"] = PolicyFixture()

    monkeypatch.setattr(attempts, "World", FixtureWorld)
    row = attempts.execute_attempt(run_id="policy-fixture", seed=1, arm="model_a", config=resolved,
        ticks=3, data_dir=tmp_path / "worlds", completion_guard=budget,
        collect=lambda store: collect_outcomes(store, spec))
    assert row["eligibility"] == {"status": "eligible", "reasons": []}
    assert row["ticks"] == 3 and row["provider_calls"] > 0
    assert dispatches and all(temperature == .4 for _, temperature in dispatches)
    assert budget.snapshot()["provider_calls"] == len(dispatches)
    assert budget.snapshot()["unresolved_calls"] == 0
    assert budget.snapshot()["unknown_usage_calls"] == 0
    assert attempts.verify_attempt(row, expected_ticks=3) == []


@contextmanager
def policy_http_fixture(policy_setup, *, smoke_ok=True, max_calls=500, draws=None,
                        invalid_responses=False, hold_response=None):
    """A controlled HTTP no-op policy, never a proxy for real model behavior."""
    posts = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, value):
            data = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self.reply({"data": [{"id": "model-a"}]})

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            posts.append(request)
            if hold_response is not None:
                hold_response[0].set()
                hold_response[1].wait(timeout=20)
            content = {"ok": smoke_ok, "provider": "live", "reasoning": "controlled HTTP fixture",
                       "actions": [{"type": "do_nothing"}], "belief_updates": [], "plan_updates": [],
                       "summary": "controlled HTTP fixture", "text": "controlled HTTP fixture",
                       "importance": 1.0, "memories": [], "rumor_bank": None}
            try:
                self.reply({"choices": [{"message": {"content": "invalid" if invalid_responses and len(posts) > 1 else json.dumps(content)}}],
                            "usage": {"prompt_tokens": 100, "completion_tokens": 20}})
            except (BrokenPipeError, ConnectionResetError):
                pass  # An owned worker was deliberately stopped.

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        config, initial = policy_setup
        llm = copy.deepcopy(initial.policy_design.policies[1].llm)
        llm["providers"]["fixture"]["base_url"] = f"http://127.0.0.1:{server.server_port}/v1"
        live = declare_policy("model_a", llm, temperature=.4)
        tariff = initial.policy_design.tariffs[0].model_copy(update={"max_input_tokens": 200_000, "max_output_tokens": 10_000})
        spec = draft_policy_comparison(config, policies=[initial.policy_design.policies[0], live],
            tariffs=[tariff], seeds=[1, 2], model_replicates=draws or ["draw1"], horizon=3,
            max_provider_calls=max_calls, max_tokens=100_000_000, max_spend_usd=2.0,
            max_wall_seconds=120, max_disk_bytes=128 * 1024 * 1024)
        yield config, spec, posts
    finally:
        if hold_response is not None:
            hold_response[1].set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture(scope="module")
def executed_policy_study(tmp_path_factory):
    from research.study_runner import run_study

    tmp_path = tmp_path_factory.mktemp("policy-execution")
    with policy_http_fixture(base_policy_setup(), draws=["draw1", "draw2"]) as (config, spec, posts):
        result = run_study(spec, config, input_root=ROOT, data_root=tmp_path / "data",
                           out_dir=tmp_path / "reports", approve_live_inference=True)
    return tmp_path, spec, result, posts


def test_supervised_policy_cells_share_preflight_budget_and_replay(executed_policy_study):
    from research.policy_results import load_policy_result

    tmp_path, spec, result, posts = executed_policy_study
    assert len(result["results"]) == 8
    assert result["preflight"][0]["ready"] is True
    assert all(row["eligibility"] == {"status": "eligible", "reasons": []} for row in result["results"]), result["results"]
    assert result["provider_budget"]["usage"]["provider_calls"] == len(posts) > 1
    assert result["provider_budget"]["usage"]["unresolved_calls"] == 0
    assert result["provider_budget"]["usage"]["sealed"] is True
    assert posts[0]["temperature"] == 0.0
    assert all(post["temperature"] == .4 for post in posts[1:])
    for seed in spec.randomness.seeds:
        assert len({row["genesis_hash"] for row in result["results"] if row["seed"] == seed}) == 1
    assert set(result["summary"]["metrics"]) >= {"goods_price", "equity_price"}
    verified = load_policy_result(result["artifacts"]["json"], data_root=tmp_path / "data", out_dir=tmp_path / "reports")
    assert verified["verification"]["status"] == "verified", verified["verification"]
    for domain in ("goods_price", "equity_price"):
        assert verified["summary"]["metrics"][domain]["model_a"]["paired_effect"]["n_pairs"] == 2


def copied_policy_evidence(executed_policy_study, tmp_path):
    original, spec, result, _posts = executed_policy_study
    shutil.copytree(original / "data", tmp_path / "data")
    shutil.copytree(original / "reports", tmp_path / "reports")
    report = tmp_path / Path(result["artifacts"]["json"]).relative_to(original)
    data = tmp_path / Path(result["batch"]["data_dir"]).relative_to(original)
    return spec, report, data


def republish_test_report(path, payload):
    # Explicitly model an editor recomputing the public checksum. Independent
    # evidence must still prevent the edited value entering the estimator.
    path.write_text(json.dumps(payload), encoding="utf-8")
    publication_path = path.parent / "publication.json"
    publication = json.loads(publication_path.read_text())
    publication["files"]["results.json"] = file_sha256(path)
    publication_path.write_text(json.dumps(publication), encoding="utf-8")


def test_policy_evidence_relocation_and_historical_read_are_provider_free(executed_policy_study, tmp_path, monkeypatch):
    from research.policy_results import load_policy_result

    _spec, path, _data = copied_policy_evidence(executed_policy_study, tmp_path)
    monkeypatch.setattr("research.policy_studies.prompt_source_identity", lambda: "f" * 64)
    hashes = {p: file_sha256(p) for p in tmp_path.rglob("*.db")}
    loaded = load_policy_result(path, data_root=tmp_path / "data", out_dir=tmp_path / "reports")
    assert loaded["verification"]["status"] == "verified"
    assert all(file_sha256(p) == digest for p, digest in hashes.items())


@pytest.mark.parametrize("mutation", ["budget", "unsealed", "missing_cell", "preflight", "escaped_budget"])
def test_altered_policy_evidence_is_refused(executed_policy_study, tmp_path, mutation):
    from research.policy_results import load_policy_result
    from research.study_results import StudyArtifactError

    _spec, path, data = copied_policy_evidence(executed_policy_study, tmp_path)
    payload = json.loads(path.read_text())
    if mutation in {"budget", "unsealed"}:
        with sqlite3.connect(data / "provider-budget.db") as conn:
            if mutation == "budget":
                conn.execute("UPDATE reservations SET input_tokens=input_tokens+1")
            else:
                conn.execute("UPDATE budget_status SET sealed=0")
        if mutation == "unsealed":
            receipt_path = data / "provider-budget-receipt.json"
            receipt = json.loads(receipt_path.read_text())
            receipt["database_sha256"] = file_sha256(data / "provider-budget.db")
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            payload["provider_budget"] = receipt
    elif mutation == "missing_cell":
        payload["results"].pop()
    elif mutation == "preflight":
        payload["preflight"][0]["ready"] = False
    else:
        payload["provider_budget"]["database"] = str(tmp_path / "outside.db")
    republish_test_report(path, payload)
    with pytest.raises(StudyArtifactError):
        load_policy_result(path, data_root=tmp_path / "data", out_dir=tmp_path / "reports")


def test_edited_policy_prices_cannot_enter_the_verified_estimator(executed_policy_study, tmp_path):
    from research.policy_results import load_policy_result

    _spec, path, _data = copied_policy_evidence(executed_policy_study, tmp_path)
    payload = json.loads(path.read_text())
    row = next(row for row in payload["results"] if row["policy"] == "model_a" and row["seed"] == 1)
    row["metrics"]["goods_price"] = 1_000_000
    republish_test_report(path, payload)
    loaded = load_policy_result(path, data_root=tmp_path / "data", out_dir=tmp_path / "reports")
    assert loaded["verification"]["status"] == "degraded"
    assert loaded["summary"]["metrics"]["goods_price"]["model_a"]["paired_effect"]["matched_seeds"] == [2]


def test_live_launch_needs_declared_approval_before_artifacts_or_calls(policy_setup, tmp_path):
    from research.study_runner import run_study

    config, spec = policy_setup
    with pytest.raises(ValueError, match="explicit approval"):
        run_study(spec, config, input_root=ROOT, data_root=tmp_path / "data", out_dir=tmp_path / "reports")
    assert list(tmp_path.iterdir()) == []


def test_operator_interruption_seals_the_original_allowance(policy_setup, tmp_path):
    from research.study_runner import run_study

    config, spec = policy_setup
    observed = []

    def interrupt(event):
        observed.append(event["batch"])
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        run_study(spec, config, input_root=ROOT, data_root=tmp_path / "data",
            out_dir=tmp_path / "reports", progress=interrupt, approve_live_inference=True)
    root = Path(observed[0]["data_dir"])
    contract = ProviderBudgetContract.model_validate_json((root / "provider-budget-contract.json").read_text())
    budget = ProviderBudget(root / "provider-budget.db", contract, scope="inspection", binding_key="model_a", read_only=True)
    assert budget.is_sealed() and budget.snapshot()["provider_calls"] == 0
    assert not (Path(observed[0]["report_dir"]) / "publication.json").exists()


def test_failed_live_smoke_preserves_its_cost_without_starting_worlds(policy_setup, tmp_path):
    from research.study_runner import run_study

    with policy_http_fixture(policy_setup, smoke_ok=False) as (config, spec, posts):
        result = run_study(spec, config, input_root=ROOT, data_root=tmp_path / "data",
                           out_dir=tmp_path / "reports", approve_live_inference=True)
    assert result["operations"]["stop_reason"] == "live_preflight_failed"
    assert len(posts) == result["provider_budget"]["usage"]["provider_calls"] == 1
    assert all(row["execution_status"] == "planned" for row in result["results"])
    assert not (Path(result["batch"]["data_dir"]) / "cells").exists()


@pytest.mark.parametrize("failure", ["exhausted", "invalid_response"])
def test_policy_stops_retain_preflight_and_failed_call_costs(policy_setup, tmp_path, failure):
    from research.policy_results import load_policy_result
    from research.study_runner import run_study

    with policy_http_fixture(policy_setup, max_calls=1 if failure == "exhausted" else 100,
                             invalid_responses=failure == "invalid_response") as (config, spec, posts):
        result = run_study(spec, config, input_root=ROOT, data_root=tmp_path / "data",
                           out_dir=tmp_path / "reports", approve_live_inference=True)
    usage = result["provider_budget"]["usage"]
    if failure == "exhausted":
        assert len(posts) == usage["provider_calls"] == 1
    else:
        # Other admitted decisions can be in flight when one repair fails.
        # Cancellation need not reach the HTTP server, but stays encumbered.
        assert 2 < len(posts) <= usage["provider_calls"] <= spec.operations.max_provider_calls
        assert any(post["temperature"] == .2 for post in posts)
    assert result["operations"]["stop_reason"] == "study_stopped_after_paused_attempt"
    assert result["results"][0]["eligibility"]["status"] == "eligible"
    assert result["results"][1]["execution_status"] == "paused"
    assert all(row["execution_status"] == "planned" for row in result["results"][2:])
    assert all(result["summary"]["metrics"][domain]["model_a"]["paired_effect"]["n_pairs"] == 0 for domain in ("goods_price", "equity_price"))
    loaded = load_policy_result(result["artifacts"]["json"], data_root=tmp_path / "data", out_dir=tmp_path / "reports")
    assert loaded["verification"]["status"] == "verified", loaded["verification"]


def _launch_policy_fixture(spec_data, config, data_root, out_dir, guard):
    from research.study_runner import run_study
    run_study(StudySpec.model_validate(spec_data), config, input_root=ROOT,
        data_root=data_root, out_dir=out_dir, worker_guard_path=Path(guard), approve_live_inference=True)


def test_policy_supervisor_death_stops_its_worker_and_retains_pending_charge(policy_setup, tmp_path):
    from research.process_lock import process_lock

    started, release = threading.Event(), threading.Event()
    guard = tmp_path / "owned-worker.lock"
    with policy_http_fixture(policy_setup, hold_response=(started, release)) as (config, spec, posts):
        supervisor = multiprocessing.get_context("spawn").Process(target=_launch_policy_fixture,
            args=(spec.model_dump(mode="json"), config, str(tmp_path / "data"), str(tmp_path / "reports"), str(guard)))
        supervisor.start()
        try:
            assert started.wait(timeout=30), "controlled preflight did not reach the HTTP server"
            supervisor.terminate()
            supervisor.join(timeout=5)
            assert not supervisor.is_alive()
            # A surviving orphan would keep this owned lock. Acquiring it
            # proves the actual nested worker's parent-death guard exited.
            with process_lock(guard, wait_seconds=10):
                contract_path = next((tmp_path / "data").glob("*/*/provider-budget-contract.json"))
                contract = ProviderBudgetContract.model_validate_json(contract_path.read_text())
                budget = ProviderBudget(contract_path.with_name("provider-budget.db"), contract,
                    scope="inspection", binding_key="model_a", read_only=True)
                assert not budget.is_sealed()
                assert budget.snapshot()["provider_calls"] == budget.snapshot()["unresolved_calls"] == len(posts) == 1
                with pytest.raises(FileExistsError):
                    ProviderBudget.create(budget.path, contract, scope="replacement", binding_key="model_a")
        finally:
            release.set()
            if supervisor.is_alive():
                supervisor.terminate()
                supervisor.join(timeout=5)
            supervisor.close()


def test_policy_wall_guard_stops_pending_preflight_without_refunding(policy_setup, tmp_path):
    from research.policy_runner import _supervise
    from research.studies import prepare_study
    from research.artifacts import publish_json

    started, release = threading.Event(), threading.Event()
    with policy_http_fixture(policy_setup, hold_response=(started, release)) as (config, spec, posts):
        batch = prepare_study(spec, config, input_root=ROOT, data_root=tmp_path / "data", out_dir=tmp_path / "reports")
        contract = provider_budget_contract(spec, config, manifest_sha256=batch["manifest_sha256"])
        root = Path(batch["data_dir"])
        publish_json(root / "provider-budget-contract.json", contract.model_dump(mode="json"))
        budget = ProviderBudget.create(root / "provider-budget.db", contract, scope="test-supervisor", binding_key="model_a")
        packet, path, stopped = _supervise(batch, None, "model_a", input_root=ROOT,
            guard_path=None, deadline=time.monotonic() + 5, max_disk_bytes=spec.operations.max_disk_bytes)
        assert started.is_set() and len(posts) == 1
        assert packet is None and not path.exists() and stopped == "wall_time_budget_exhausted"
        usage = budget.seal()
        assert usage["provider_calls"] == usage["unresolved_calls"] == 1
        assert usage["encumbered_tokens"] == contract.tariffs[0].max_input_tokens + 256


def test_sealed_v2_budget_cannot_dispatch_or_settle_through_an_old_connection(policy_setup, tmp_path):
    config, spec = policy_setup
    contract = provider_budget_contract(spec, config, manifest_sha256="a" * 64)
    budget = ProviderBudget.create(tmp_path / "budget.db", contract, scope="cell", binding_key="model_a")
    existing = ProviderBudget(budget.path, contract, scope="cell", binding_key="model_a")
    messages = [{"role": "user", "content": "pending fixture"}]
    reservation = existing._reserve("fixture", "model-a", messages, {"purpose": "decision", "max_tokens": 100})
    frozen = budget.seal()
    sealed_hash = file_sha256(budget.path)
    assert budget.seal() == frozen and file_sha256(budget.path) == sealed_hash
    assert existing.is_sealed() is True
    assert frozen["unresolved_calls"] == 1
    with pytest.raises(BudgetLedgerError, match="sealed"):
        existing._finish(reservation, AdapterResult(text="{}", reported_usage=(10, 5)))
    with pytest.raises(BudgetLedgerError, match="sealed"):
        existing._reserve("fixture", "model-a", messages, {"purpose": "decision", "max_tokens": 100})
    assert {**existing.snapshot(), "sealed": True} == frozen


def test_policy_cli_drafts_and_validates_without_calls_or_overwriting(policy_setup, tmp_path, monkeypatch, capsys):
    from research.policy_studies import main as draft_main
    from research.study_runner import main as runner_main

    _config, spec = policy_setup
    design = {"policies": [{"key": p.key, "llm": p.llm, "temperature": p.behavior.temperature,
                            "repair_temperature": p.repair_temperature} for p in spec.policy_design.policies],
              "tariffs": [tariff.model_dump(mode="json") for tariff in spec.policy_design.tariffs]}
    design_path, study_path = tmp_path / "design.json", tmp_path / "study.json"
    design_path.write_text(json.dumps(design), encoding="utf-8")
    arguments = ["policy_studies", "--config", str(ROOT / "runs/price-lab-pilot.yaml"),
        "--design", str(design_path), "--output", str(study_path), "--seeds", "1", "2",
        "--model-replicates", "draw1", "draw2", "--ticks", "3",
        "--max-provider-calls", "200", "--max-tokens", "1000000", "--max-spend-usd", ".1"]
    monkeypatch.setattr("sys.argv", arguments)
    assert draft_main() == 0
    assert json.loads(capsys.readouterr().out)["provider_calls"] == 0
    before = file_sha256(study_path)
    assert draft_main() == 2 and file_sha256(study_path) == before
    capsys.readouterr()
    monkeypatch.setattr("sys.argv", ["study_runner", str(study_path), "--config",
        str(ROOT / "runs/price-lab-pilot.yaml"), "--validate-only",
        "--data-root", str(tmp_path / "data"), "--out-dir", str(tmp_path / "reports")])
    assert runner_main() == 0
    assert json.loads(capsys.readouterr().out)["executed"] is False
    assert not (tmp_path / "data").exists() and not (tmp_path / "reports").exists()

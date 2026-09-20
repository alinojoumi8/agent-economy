import asyncio
from copy import deepcopy
import json
from pathlib import Path

import httpx
import pytest

from research.decision_studies import execute, freeze, prepare, read_snapshots, summarize_frozen
from run import open_run
from run_config import load_config
from tests.test_jev_contract import transport
from tests.test_jev_runtime import typed_handler

ROOT = Path(__file__).resolve().parents[1]


def profiles():
    return {name: load_config(ROOT / "runs" / filename) for name, filename in (
        ("baseline", "jev-offline.yaml"), ("jev", "jev-live.yaml"))}


@pytest.mark.parametrize("version", ["bounded-economic-choice-v1", "bounded-economic-choice-v2", "bounded-economic-choice-v3", "bounded-economic-choice-v4"])
def test_prospective_pair_and_frozen_roundtrip(tmp_path, monkeypatch, version):
    monkeypatch.setenv("OPENROUTER_API_KEY", "private-fixture-key")
    transport(monkeypatch, typed_handler)
    configs = profiles()
    for config in configs.values():
        config["llm"]["decision_policy"]["version"] = version
        if version != "bounded-economic-choice-v1":
            config["firms"]["listed"] = 0
        if version == "bounded-economic-choice-v4":
            config["llm"]["decision_policy"].update(domains=["consumption", "career", "founder_operations"],
                strategic_review_interval_ticks=0)
    root = tmp_path / "study"
    prepare(configs, root, seeds=(7,), ticks=2)
    result = asyncio.run(execute(root, approve_live=True))
    assert result["status"] == "complete", result["cells"]
    assert all(cell["replay_exact"] for cell in result["cells"])
    assert result["provider_accounting"]["provider_calls"] > 0
    assert result["provider_accounting"]["sealed"]
    baseline = result["cells"][0]
    frozen_path = tmp_path / "observations.json"
    freeze(root / baseline["key"] / (baseline["run_id"] + ".db"), frozen_path)
    snapshots = read_snapshots(frozen_path)
    assert snapshots["records"]
    assert all(r["label_choice"] is None for r in snapshots["records"])
    frozen_root = tmp_path / "frozen-study"
    prepare(configs, frozen_root, seeds=(9,), ticks=1, snapshots=frozen_path)
    frozen_result = asyncio.run(execute(frozen_root, approve_live=True))
    assert frozen_result["status"] == "complete", frozen_result
    assert len(frozen_result["frozen"]) == len(snapshots["records"]) * 2
    assert all(s["probability_brier"] is None for s in frozen_result["frozen_summary"].values())
    with pytest.raises(FileExistsError):
        asyncio.run(execute(root, approve_live=True))


def test_study_refuses_background_drift_and_missing_allowance(tmp_path, monkeypatch):
    configs = profiles()
    configs["jev"]["population"]["size"] += 1
    with pytest.raises(ValueError, match="differ"):
        prepare(configs, tmp_path / "bad")
    assert not (tmp_path / "bad").exists()
    root = tmp_path / "study"
    prepare(profiles(), root, seeds=(1,), ticks=1)
    with pytest.raises(ValueError, match="approve-live"):
        asyncio.run(execute(root))
    assert not (root / "execution-started.json").exists()
    (root / "budget-contract.json").unlink()
    with pytest.raises(ValueError, match="missing or changed"):
        asyncio.run(execute(root, approve_live=True))


def test_failed_provider_keeps_assignments_and_original_charges(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "private-fixture-key")
    transport(monkeypatch, lambda req: httpx.Response(402, json={"error": "quota"}))
    root = tmp_path / "study"
    prepare(profiles(), root, seeds=(1, 2), ticks=1)
    result = asyncio.run(execute(root, approve_live=True))
    assert result["status"] == "incomplete"
    assert len(result["cells"]) == 4
    assert [r["status"] for r in result["cells"]] == ["complete", "failed", "excluded", "excluded"]
    assert result["provider_accounting"]["unknown_usage_calls"] >= 1
    assert result["provider_accounting"]["provider_calls"] == result["provider_accounting"]["unknown_usage_calls"]
    assert result["provider_accounting"]["encumbered_nano_usd"] > 0


def test_calibration_requires_labels_and_reports_each_split():
    base = dict(arm="jev", status="complete", baseline_agreement=1, cost_usd=0,
                latency_ms=2, confidence=.8, label_agreement=1, selection_status="selected")
    summaries = summarize_frozen([{**base, "split": "calibration"},
                                 {**base, "split": "held_out", "label_agreement": None}])
    assert summaries["jev:calibration"]["concentration_agreement_mae"] == pytest.approx(.2)
    assert summaries["jev:held_out"]["concentration_agreement_mae"] is None
    assert summaries["jev:calibration"]["probability_brier"] is None


def test_counterfactual_builder_binds_recorded_context_and_never_joins_future_state(tmp_path):
    from engine.store import Store
    from llm.decisions import canonical_json
    from research.domain_snapshots import build_counterfactual
    from research.artifacts import file_sha256
    from tests.test_jev_candidates import observation
    from tests.test_jev_domains import domain_config
    config = domain_config("consumption", "career")
    context = observation()
    context["decision_resources"] = {"agent:7:CAD": {"available_cents": 600}}
    database = tmp_path / "contexts.db"
    store = Store(str(database))
    store.init_run_meta("counterfactual", 99, config)
    store.execute("UPDATE run_meta SET tick=4")
    for tick, value in ((4, context), (4, {"agent": {"id": 8}}), (99, {**context, "tick": 99})):
        store.insert("llm_calls", tick=tick, agent_id=value["agent"]["id"], role="citizen",
            provider="scripted", model="scripted", purpose="decision", cache_key=str(tick)+str(value["agent"]["id"]),
            request_json=canonical_json({"context": value}), response_json="{}", in_tokens=0, out_tokens=0,
            cached=0, cost_usd=0, latency_ms=0, created_at="fixture")
    store.commit()
    store.close()
    original = file_sha256(database)
    output = tmp_path / "counterfactual.json"
    result = build_counterfactual(database, output, config, "consumption")
    assert len(result["records"]) == 1
    assert result["records"][0]["counterfactual"]
    assert result["exclusions"] == {"incomplete_authorized_context": 1}
    assert read_snapshots(output)["records"] == result["records"]
    assert file_sha256(database) == original
    record = result["records"][0]
    record["domain_metadata"]["ballot_actions"] = {"ballot_forged": {"yes": {"type": "transfer"}}}
    from research.decision_studies import frozen_menu
    with pytest.raises(ValueError, match="ballot mapping"):
        frozen_menu(record)


@pytest.mark.parametrize("exclusion", ["incomplete_founder_observation", "legal_work_not_delegated"])
def test_counterfactual_ineligible_call_does_not_hide_later_eligible_turn(tmp_path, exclusion):
    from copy import deepcopy
    from engine.store import Store
    from llm.decisions import canonical_json
    from research.artifacts import file_sha256
    from research.domain_snapshots import build_counterfactual
    from tests.test_jev_candidates import observation
    from tests.test_jev_domains import domain_config

    config = domain_config("founder_operations")
    valid = observation()
    valid.update(purpose="founder", my_firm={"firm_id": 8, "price": 200, "cash": 6000,
        "currency_code": "CAD", "payroll": 5000, "employees": 1, "target_headcount": 2,
        "open_jobs": 1, "employee_roster": [], "executed_sales_units": 3, "sales_window": 7},
        decision_resources={"firm:8:CAD": {"available_cents": 1000}})
    ineligible = deepcopy(valid)
    if exclusion == "incomplete_founder_observation":
        del ineligible["my_firm"]["currency_code"]
    else:
        ineligible["legal_work"] = {"eligible_actions": [{"type": "issue_legal_decision"}]}
    database = tmp_path / "contexts.db"
    store = Store(str(database))
    try:
        store.init_run_meta("counterfactual", 99, config)
        store.execute("UPDATE run_meta SET tick=4")
        for index, context in enumerate([ineligible, valid, valid]):
            store.insert("llm_calls", tick=4, agent_id=context["agent"]["id"], role="founder",
                provider="scripted", model="scripted", purpose="decision", cache_key=str(index),
                request_json=canonical_json({"context": context}), response_json="{}", in_tokens=0,
                out_tokens=0, cached=0, cost_usd=0, latency_ms=0, created_at="fixture")
        store.commit()
    finally:
        store.close()
    original = file_sha256(database)
    result = build_counterfactual(database, tmp_path / "counterfactual.json", config, "founder_operations")
    assert result["eligible_records"] == 1
    assert result["records"][0]["source_call_id"] == 2
    assert result["exclusions"] == {exclusion: 1, "duplicate_actor_turn": 1}
    assert file_sha256(database) == original


def test_brier_uses_choice_probabilities_only():
    base = dict(arm="jev", split="held_out", status="complete", baseline_agreement=1,
        cost_usd=0, latency_ms=1, confidence=.99, label_agreement=1, selection_status="selected",
        label_choice="buy", probabilities={"buy": .6, "wait": .4})
    result = summarize_frozen([base])["jev:held_out"]
    assert result["probability_brier"] == pytest.approx(.32)
    assert "ece_against_labels" not in result


@pytest.mark.parametrize('failure', ['http', 'malformed'])
def test_failed_frozen_evaluation_reports_known_or_unavailable_cost(tmp_path, monkeypatch, failure):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'private-fixture-key')
    baseline_root = tmp_path / 'baseline'
    store, world, _ = open_run(profiles()['baseline'], None, None, data_dir=baseline_root)
    source = Path(store.path)
    try:
        asyncio.run(world.step())
    finally:
        world.close()
    snapshots = tmp_path / 'frozen.json'
    freeze(source, snapshots, limit=1)

    def fail(request):
        if failure == 'http':
            return httpx.Response(402, json={'error': 'quota'})
        response = typed_handler(request).json()
        response['answers'] = {}
        return httpx.Response(200, json=response)

    transport(monkeypatch, fail)
    study = tmp_path / 'failed'
    prepare(profiles(), study, seeds=(9,), ticks=1, snapshots=snapshots)
    result = asyncio.run(execute(study, approve_live=True))
    row = next(r for r in result['frozen'] if r['arm'] == 'jev')
    summary = result['frozen_summary']['jev:' + row['split']]
    assert row['status'] == 'failed'
    assert result['provider_accounting']['sealed']
    if failure == 'http':
        assert row['cost_usd'] is None and row['cost_status'] == 'unavailable'
        assert summary['call_cost_usd'] is None
        assert summary['cost_unavailable_evaluations'] == 1
        assert result['provider_accounting']['unknown_usage_calls'] >= 1
        assert result['provider_accounting']['encumbered_nano_usd'] > 0
    else:
        assert row['cost_usd'] > 0 and row['cost_status'] == 'recorded'
        assert row['cost_usd'] == sum(c['cost_usd'] for c in row['calls'])
        assert summary['call_cost_usd'] == row['cost_usd']
        assert summary['cost_unavailable_evaluations'] == 0


def test_frozen_summary_preserves_known_subtotal_when_a_call_cost_is_unknown():
    summary = summarize_frozen([
        {'arm': 'jev', 'split': 'held_out', 'status': 'failed',
         'cost_usd': None, 'known_call_cost_usd': .25},
        {'arm': 'jev', 'split': 'held_out', 'status': 'failed', 'cost_usd': .5},
        {'arm': 'jev', 'split': 'held_out', 'status': 'excluded'},
    ])['jev:held_out']
    assert summary['call_cost_usd'] is None
    assert summary['known_call_cost_usd'] == .75
    assert summary['cost_unavailable_evaluations'] == 1

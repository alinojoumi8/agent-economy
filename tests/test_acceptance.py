import asyncio
import json
from pathlib import Path
import sys

import yaml
import pytest
from fastapi.testclient import TestClient

import experiments.harness as experiment_harness
import research.counterfactual as counterfactual_runner
import research.scenarios as scenarios
import run as cli
from engine.store import Store
from reports.acceptance import (
    AcceptanceCheckpointMissed, acceptance_schedule_status, execute_acceptance_run,
    uses_paid_providers, write_acceptance_package,
)
from reports.generate import generate_report
from run_config import load_config
from server.app import create_app
from world.loop import World
from world.replay_verify import verify_replay


def _config(**over):
    config = {
        "seed": 7,
        "population": {"size": 8},
        "banks": {"count": 2},
        "firms": {"count": 3, "listed": 1},
        "budget": {"cap_usd": 200.0, "oracle_reserve_usd": 10.0, "conversation_pairs": 2},
        "llm": {"default_route": {"provider": "scripted", "model": "scripted"}, "routes": {}},
        "checkpoint_every": 0,
        "outlets": [{"id": 1, "name": "A", "slant": "market"},
                    {"id": 2, "name": "B", "slant": "labor"}],
    }
    config.update(over)
    return config


def _passing_evidence(tmp_path):
    db = tmp_path / "acceptance.db"
    config = {
        "seed": 9,
        "budget": {"cap_usd": 200.0},
        "llm": {"default_route": {"provider": "minimax", "model": "MiniMax-M3"}},
        "acceptance": {"min_ticks": 365, "min_agents": 95, "max_agents": 105,
                       "max_spend_usd": 200.0, "oracle_p90_ms": 60_000,
                       "efficiency_target_usd": 200.0,
                       "oracle_min_latency_samples": 5},
    }
    store = Store(str(db))
    store.init_run_meta("acceptance-fixture", 9, config)
    store.set_meta(tick=365, status="paused")
    for agent_id in range(1, 101):
        store.insert("agents", id=agent_id, name=f"A{agent_id}", kind="citizen", age=30)
    for tick in (5, 65, 125, 185, 245):
        store.insert("llm_calls", tick=tick, provider="minimax", model="MiniMax-M3",
                     purpose="oracle", latency_ms=55_000, cost_usd=1.25)
    store.insert("predictions", asked_tick=5, question="bank run?", p=0.5,
                 deadline_tick=35, resolved_tick=35, outcome=1, brier=0.25, status="resolved")

    fired_ticks = {"policy_rate": 15, "oil": 30, "rumor": 60, "slant": 100, "scandal": 150}
    for kind, tick in fired_ticks.items():
        store.log_event(tick, "shock_fired", {"kind": kind})
    store.log_event(15, "policy_rate_set", {"rate_bps": 875})
    store.log_event(30, "commodity_shock", {"multiplier": 1.8})
    targets = [1, 2, 3, 4]
    store.log_event(60, "rumor", {"bank_id": 1, "target_agent_ids": targets})
    for agent_id in targets:
        # 0.50 -> 0.39 is a 22% relative drop but only 0.11 points. This fixture
        # fails if the evaluator regresses to an absolute 0.20-point threshold.
        store.insert("beliefs", agent_id=agent_id, key="trust:bank:1", value=0.39, updated_tick=61)
        store.log_event(
            0, "belief_updated", {
                "agent_id": agent_id, "key": "trust:bank:1", "old_value": None,
                "raw_value": 0.5, "new_value": 0.5, "normalized": False,
                "source": "genesis", "source_llm_call_id": None,
            }, subject_type="agent", subject_id=agent_id)
        store.log_event(
            61, "belief_updated", {
                "agent_id": agent_id, "key": "trust:bank:1", "old_value": 0.5,
                "raw_value": 0.39, "new_value": 0.39, "normalized": False,
                "source": "decision", "source_llm_call_id": None,
            }, subject_type="agent", subject_id=agent_id)
    store.log_event(55, "deposit_move", {"from_bank": 1, "amount_cents": 100})
    store.log_event(62, "deposit_move", {"from_bank": 1, "amount_cents": 300})
    for offset in range(5):
        conversation_id = store.insert(
            "conversations", tick=60 + offset, participant_ids=json.dumps([1, 10 + offset]), topic="bank"
        )
        store.insert("messages", conv_id=conversation_id, tick=60 + offset, agent_id=1,
                     text="Did you hear the bank rumor? I am worried about deposits.", seq=1)
    store.log_event(100, "slant_directive", {"outlet_id": 1})
    store.insert("news_articles", tick=101, outlet_id=1, headline="Directed", body="body",
                 slant_tags=json.dumps(["directed"]), source_event_ids="[]")
    scandal_id = store.log_event(150, "firm_scandal", {"firm_id": 1})
    store.insert("news_articles", tick=151, outlet_id=1, headline="Scandal", body="body",
                 slant_tags="[]", source_event_ids=json.dumps([scandal_id]))

    metric_specs = [
        ("unemployment", 0.05, 0.10, "increase"),
        ("sentiment", 0.4, -0.2, "decrease"),
        ("index", 100.0, 80.0, "decrease"),
    ]
    phenomena = []
    for index, (metric, start, end, direction) in enumerate(metric_specs, 1):
        store.record_metric(10, metric, start)
        store.record_metric(20, metric, end)
        phenomena.append({
            "name": f"phenomenon-{index}", "status": "documented",
            "mechanism": "Observed through agent decisions and transactions.",
            "metric": metric, "start_tick": 10, "end_tick": 20, "direction": direction,
        })
    store.commit()
    store.close()

    experiment = {
        "spec": {"seeds": [1, 2, 3, 4, 5]},
        "results": [
            {"seed": seed, "arm": arm, "reconciled": True}
            for seed in range(1, 6) for arm in ("treatment", "control")
        ],
        "summary": {"all_reconciled": True},
    }
    experiment_path = tmp_path / "experiment.json"
    experiment_path.write_text(json.dumps(experiment), encoding="utf-8")
    phenomena_path = tmp_path / "phenomena.yaml"
    phenomena_path.write_text(yaml.safe_dump({
        "run_id": "acceptance-fixture", "phenomena": phenomena,
    }), encoding="utf-8")
    return db, experiment_path, phenomena_path


def test_acceptance_package_is_machine_checkable_and_standalone(tmp_path):
    db, experiment, phenomena = _passing_evidence(tmp_path)
    receipt = write_acceptance_package(
        db, out_dir=tmp_path / "out", experiment_json=experiment, phenomena_yaml=phenomena
    )

    assert receipt["passed"]
    assert all(check["passed"] for check in receipt["checks"])
    payload = json.loads((tmp_path / "out" / "acceptance_acceptance-fixture.json").read_text())
    assert payload["passed"] and len(payload["checks"]) == 20
    trace_check = next(check for check in payload["checks"] if check["id"] == "shock_traces")
    assert set(trace_check["evidence"]) == {"policy_rate", "oil", "rumor", "slant", "scandal"}
    assert all(
        trace["source"] and trace["downstream"] and trace["passed"]
        for trace in trace_check["evidence"].values()
    )
    rumor_trace = trace_check["evidence"]["rumor"]["downstream"]
    assert len(rumor_trace["rumor_conversation_ids"]) == 5
    assert rumor_trace["trust_drop_agent_ids"] == [1, 2, 3, 4]
    assert rumor_trace["trust_relative_drops"]["1"] == pytest.approx(0.22)
    assert rumor_trace["trust_absolute_drops"]["1"] == pytest.approx(0.11)
    assert rumor_trace["post_outflow_events"][0]["amount_cents"] == 300
    markdown = (tmp_path / "out" / "acceptance_acceptance-fixture.md").read_text()
    assert "Overall: **PASS**" in markdown and "Rumor pilot" in markdown
    assert "## Shock traces" in markdown and "### Policy Rate" in markdown
    assert "## Emergent phenomena" in markdown and "### phenomenon-1" in markdown
    assert "Observed through agent decisions and transactions." in markdown


def test_acceptance_population_gate_counts_living_agents(tmp_path):
    db, experiment, phenomena = _passing_evidence(tmp_path)
    store = Store(str(db))
    store.insert(
        "agents", id=101, name="Historical agent", kind="citizen", age=80,
        alive=0, died_tick=300)
    store.commit()
    store.close()

    receipt = write_acceptance_package(
        db, out_dir=tmp_path / "out", experiment_json=experiment,
        phenomena_yaml=phenomena)
    population = next(
        check for check in receipt["checks"] if check["id"] == "population")

    assert receipt["passed"]
    assert population["passed"]
    assert population["evidence"] == {
        "agents": 100,
        "living_agents": 100,
        "historical_total_agents": 101,
        "range": [95, 105],
    }


def test_acceptance_package_fails_closed_without_reviewed_attachments(tmp_path):
    db, _, _ = _passing_evidence(tmp_path)
    receipt = write_acceptance_package(db, out_dir=tmp_path / "out")
    failed = {check["id"] for check in receipt["checks"] if not check["passed"]}

    assert not receipt["passed"]
    assert failed == {"experiment_n5", "emergent_phenomena"}


def test_rumor_acceptance_fails_closed_without_belief_history(tmp_path):
    db, experiment, phenomena = _passing_evidence(tmp_path)
    store = Store(str(db))
    store.execute("DELETE FROM events WHERE kind='belief_updated'")
    store.commit()
    store.close()

    receipt = write_acceptance_package(
        db, out_dir=tmp_path / "legacy", experiment_json=experiment,
        phenomena_yaml=phenomena,
    )
    rumor = next(check for check in receipt["checks"] if check["id"] == "rumor_pilot")
    assert not rumor["passed"]
    assert not rumor["evidence"]["belief_history_complete"]
    assert rumor["evidence"]["missing_belief_history_agent_ids"] == [1, 2, 3, 4]


def test_acceptance_rejects_duplicate_phenomena_and_pre_shock_effects(tmp_path):
    db, experiment, phenomena = _passing_evidence(tmp_path)
    payload = yaml.safe_load(phenomena.read_text())
    payload["phenomena"] = [payload["phenomena"][0]] * 3
    phenomena.write_text(yaml.safe_dump(payload), encoding="utf-8")
    store = Store(str(db))
    store.execute("UPDATE events SET tick=14 WHERE kind='policy_rate_set'")
    store.commit()
    store.close()

    receipt = write_acceptance_package(
        db, out_dir=tmp_path / "out", experiment_json=experiment, phenomena_yaml=phenomena
    )
    failed = {check["id"] for check in receipt["checks"] if not check["passed"]}

    assert failed == {"policy_rate_effect", "shock_traces", "emergent_phenomena"}


def test_acceptance_rejects_phenomena_reviewed_for_a_different_run(tmp_path):
    db, experiment, phenomena = _passing_evidence(tmp_path)
    payload = yaml.safe_load(phenomena.read_text(encoding="utf-8"))
    payload["run_id"] = "another-run"
    phenomena.write_text(yaml.safe_dump(payload), encoding="utf-8")

    receipt = write_acceptance_package(
        db, out_dir=tmp_path / "out", experiment_json=experiment,
        phenomena_yaml=phenomena,
    )
    check = next(
        check for check in receipt["checks"]
        if check["id"] == "emergent_phenomena")
    assert not check["passed"]
    assert check["evidence"]["reason"] == (
        "phenomena evidence is not bound to this run")
    assert check["evidence"]["expected_run_id"] == "acceptance-fixture"
    assert check["evidence"]["evidence_run_id"] == "another-run"


def test_acceptance_distinguishes_recovered_provider_incidents(tmp_path):
    db, experiment, phenomena = _passing_evidence(tmp_path)
    store = Store(str(db))
    store.log_event(1, "provider_failure", {"provider": "minimax"})
    store.log_event(1, "provider_pause", {"provider": "minimax"})
    store.commit()
    store.close()

    receipt = write_acceptance_package(
        db, out_dir=tmp_path / "recovered", experiment_json=experiment,
        phenomena_yaml=phenomena,
    )
    check = next(check for check in receipt["checks"] if check["id"] == "failure_events")
    assert check["passed"]
    assert check["evidence"]["recovered_provider_incidents"] == 2
    assert check["evidence"]["unrecovered_provider_incidents"] == 0

    store = Store(str(db))
    store.log_event(366, "provider_failure", {"provider": "minimax"})
    store.commit()
    store.close()
    receipt = write_acceptance_package(
        db, out_dir=tmp_path / "unrecovered", experiment_json=experiment,
        phenomena_yaml=phenomena,
    )
    check = next(check for check in receipt["checks"] if check["id"] == "failure_events")
    assert not check["passed"]
    assert check["evidence"]["unrecovered_provider_incidents"] == 1


def test_acceptance_never_waives_reconciliation_failure(tmp_path):
    db, experiment, phenomena = _passing_evidence(tmp_path)
    store = Store(str(db))
    store.log_event(1, "reconciliation_failure", {"grand_sum_cents": 1})
    store.commit()
    store.close()

    receipt = write_acceptance_package(
        db, out_dir=tmp_path / "hard-failure", experiment_json=experiment,
        phenomena_yaml=phenomena,
    )
    check = next(check for check in receipt["checks"] if check["id"] == "failure_events")
    assert not check["passed"]
    assert check["evidence"]["counts"]["reconciliation_failure"] == 1


def test_acceptance_runner_schedules_oracle_once_and_resumes(tmp_path):
    config = _config(acceptance={
        "min_ticks": 3,
        "oracle_questions": [{"at_tick": 1, "question": "Will a bank run happen?"}],
    })
    store = Store(str(tmp_path / "runner.db"))
    store.init_run_meta("runner", config["seed"], config)
    world = World(store, config)
    world.initialize()

    asyncio.run(execute_acceptance_run(world, target_tick=2))
    asyncio.run(execute_acceptance_run(world, target_tick=3))

    assert store.tick == 3
    assert store.scalar("SELECT COUNT(*) FROM predictions") == 1


def test_acceptance_repairs_a_prediction_with_only_rejected_evidence(tmp_path):
    question = "Will a bank run happen?"
    config = _config(acceptance={
        "min_ticks": 2,
        "oracle_questions": [{"at_tick": 1, "question": question}],
    })
    store = Store(str(tmp_path / "runner-repair.db"))
    store.init_run_meta("runner-repair", config["seed"], config)
    world = World(store, config)
    world.initialize()
    store.insert(
        "predictions", asked_tick=0, question=question, p=0.5,
        reasoning="rejected evidence", status="open", deadline_tick=30,
        resolution_rule_json=json.dumps({"type": "bank_failure"}),
        evidence_json=json.dumps([{
            "error": "invalid tick range", "queries_rejected": True,
        }]),
    )
    store.commit()

    asyncio.run(execute_acceptance_run(world, target_tick=2))

    assert store.scalar(
        "SELECT COUNT(*) FROM predictions WHERE question=?", (question,)) == 2
    repaired = store.query_one(
        "SELECT evidence_json FROM predictions WHERE question=? ORDER BY id DESC LIMIT 1",
        (question,))
    evidence = json.loads(repaired["evidence_json"])
    assert evidence and evidence[0]["tool"] == "query_metrics"


def test_acceptance_stops_at_checkpoint_without_usable_oracle_evidence(tmp_path):
    question = "Will a bank run happen?"
    config = _config(acceptance={
        "min_ticks": 2,
        "oracle_questions": [{"at_tick": 1, "question": question}],
    })
    store = Store(str(tmp_path / "runner-invalid-evidence.db"))
    store.init_run_meta("runner-invalid-evidence", config["seed"], config)
    world = World(store, config)
    world.initialize()

    async def rejected_answer(_question):
        store.insert(
            "predictions", asked_tick=store.tick, question=question, p=0.5,
            reasoning="rejected evidence", status="open", deadline_tick=30,
            resolution_rule_json=json.dumps({"type": "bank_failure"}),
            evidence_json=json.dumps([{
                "error": "entity not found", "queries_rejected": True,
            }]),
        )
        return {"prediction_id": 1}

    world.oracle.ask = rejected_answer
    with pytest.raises(RuntimeError, match="no usable read evidence"):
        asyncio.run(execute_acceptance_run(world, target_tick=2))

    assert store.tick == 1


def test_acceptance_fails_closed_after_a_missed_oracle_checkpoint(tmp_path):
    question = "Will a bank run happen?"
    config = _config(acceptance={
        "min_ticks": 3,
        "oracle_questions": [{"at_tick": 1, "question": question}],
    })
    store = Store(str(tmp_path / "runner-missed.db"))
    store.init_run_meta("runner-missed", config["seed"], config)
    world = World(store, config)
    world.initialize()
    store.set_meta(tick=2, status="paused")
    store.commit()

    with pytest.raises(AcceptanceCheckpointMissed, match="passed without usable evidence"):
        asyncio.run(execute_acceptance_run(world, target_tick=3))

    schedule = acceptance_schedule_status(store, config, target_tick=3)
    assert schedule["state"] == "invalid"
    assert schedule["missed"][0]["scheduled_tick"] == 1
    assert store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='acceptance_checkpoint_missed'") == 1


def test_served_acceptance_run_stays_observable_and_asks_at_exact_tick(tmp_path):
    question = "Will a bank run happen?"
    config = _config(
        report_dir=str(tmp_path / "reports"),
        acceptance={
            "min_ticks": 2, "min_agents": 1, "max_agents": 100,
            "oracle_min_latency_samples": 1,
            "oracle_questions": [{"at_tick": 1, "question": question}],
        },
    )
    store = Store(str(tmp_path / "served.db"))
    store.init_run_meta("served", config["seed"], config)
    world = World(store, config)
    world.initialize()
    world.acceptance_authorized = True
    world.acceptance_target_tick = 2

    with TestClient(create_app(world)) as client:
        for _ in range(100):
            status = client.get("/api/run/status").json()
            if not status["running"] and status["tick"] >= 2:
                break
        assert status["tick"] == 2
        assert status["acceptance_orchestration"]["state"] == "completed"
        assert status["acceptance_orchestration"]["authorized"]
        prediction = store.query_one(
            "SELECT asked_tick FROM predictions WHERE question=?", (question,))
        assert prediction and int(prediction["asked_tick"]) == 1
        assert store.scalar(
            "SELECT COUNT(*) FROM acceptance_checkpoints WHERE status='completed'", default=0) == 1


def test_completed_acceptance_orchestration_replays_exactly(tmp_path):
    question = "Will a bank run happen?"
    config = _config(acceptance={
        "min_ticks": 2,
        "oracle_questions": [{"at_tick": 1, "question": question}],
    })
    source_store, source_world, source_id = cli.open_run(
        config, None, None, data_dir=tmp_path)
    source_path = Path(source_store.path)
    replay_world = None
    try:
        asyncio.run(execute_acceptance_run(source_world, target_tick=2))
        assert source_store.scalar(
            "SELECT COUNT(*) FROM events "
            "WHERE kind='acceptance_checkpoint_completed'", default=0) == 1
        source_world.close()

        replay_store, replay_world, _ = cli.open_run(
            {}, None, source_id, data_dir=tmp_path)
        asyncio.run(cli.replay_headless(replay_world, 2))

        checkpoint = replay_store.query_one(
            "SELECT status,prediction_id FROM acceptance_checkpoints "
            "WHERE scheduled_tick=? AND question=?", (1, question))
        assert checkpoint is not None
        assert checkpoint["status"] == "completed"
        assert checkpoint["prediction_id"] is not None
        assert replay_store.scalar(
            "SELECT COUNT(*) FROM events "
            "WHERE kind='acceptance_checkpoint_completed'", default=0) == 1

        proof = verify_replay(source_path, replay_store.path)
        assert proof["exact"] is True
        assert proof["differences"] == []
    finally:
        if replay_world is not None:
            replay_world.close()
        else:
            source_world.close()


def test_missed_acceptance_checkpoint_replays_exactly(tmp_path):
    question = "Will a bank run happen?"
    config = _config(acceptance={
        "min_ticks": 3,
        "oracle_questions": [{"at_tick": 1, "question": question}],
    })
    source_store, source_world, source_id = cli.open_run(
        config, None, None, data_dir=tmp_path)
    source_path = Path(source_store.path)
    replay_world = None
    try:
        asyncio.run(source_world.run(max_ticks=2))
        with pytest.raises(AcceptanceCheckpointMissed):
            asyncio.run(execute_acceptance_run(source_world, target_tick=3))
        source_world.close()

        replay_store, replay_world, _ = cli.open_run(
            {}, None, source_id, data_dir=tmp_path)
        asyncio.run(cli.replay_headless(replay_world, 2))

        checkpoint = replay_store.query_one(
            "SELECT status,detail FROM acceptance_checkpoints "
            "WHERE scheduled_tick=? AND question=?", (1, question))
        assert checkpoint is not None
        assert checkpoint["status"] == "missed"
        assert "passed without usable evidence" in checkpoint["detail"]
        assert replay_store.scalar(
            "SELECT COUNT(*) FROM events WHERE kind='acceptance_checkpoint_missed'",
            default=0) == 1

        proof = verify_replay(source_path, replay_store.path)
        assert proof["exact"] is True
        assert proof["differences"] == []
    finally:
        if replay_world is not None:
            replay_world.close()
        else:
            source_world.close()


def test_resumed_served_acceptance_uses_its_absolute_target(tmp_path):
    config = _config(
        report_dir=str(tmp_path / "reports"),
        acceptance={"min_ticks": 2, "min_agents": 1, "max_agents": 100},
    )
    store = Store(str(tmp_path / "served-resume.db"))
    store.init_run_meta("served-resume", config["seed"], config)
    world = World(store, config)
    world.initialize()
    store.set_meta(tick=1, status="paused")
    store.commit()
    world.acceptance_authorized = True
    world.acceptance_target_tick = 2

    with TestClient(create_app(world, served_ticks=2)) as client:
        for _ in range(100):
            status = client.get("/api/run/status").json()
            if not status["running"]:
                break

        assert status["tick"] == 2
        assert status["target_tick"] == 2
        assert status["remaining_ticks"] == 0
        assert client.post("/api/run/start").json()["status"] == "limit_reached"


def test_paid_acceptance_detection_fails_safe_for_any_real_route():
    assert not uses_paid_providers(_config())
    config = _config()
    config["llm"]["routes"] = {
        "oracle": {"provider": "kimi", "model": "kimi-for-coding"},
    }
    assert uses_paid_providers(config)


def _prepare_cli(monkeypatch, *args):
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(cli, "configure_logging", lambda: None)
    monkeypatch.setattr(sys, "argv", ["run.py", *args])


def test_cli_paid_experiment_requires_approval_before_dispatch(tmp_path, monkeypatch):
    spec_path = tmp_path / "paid-experiment.yaml"
    spec_path.write_text(yaml.safe_dump({
        "name": "paid-approval",
        "config": _config(),
        "overrides": {"llm": {"routes": {
            "oracle": {"provider": "minimax", "model": "MiniMax-M3"},
        }}},
        "seeds": [1],
        "ticks": 1,
        "control": False,
    }), encoding="utf-8")
    dispatched = []
    monkeypatch.setattr(
        experiment_harness, "run_experiment", lambda spec: dispatched.append(spec))

    _prepare_cli(monkeypatch, "--experiment", str(spec_path))
    with pytest.raises(SystemExit, match="--approve-live-inference"):
        cli.main()
    assert not dispatched

    _prepare_cli(
        monkeypatch, "--experiment", str(spec_path), "--approve-live-inference")
    cli.main()
    assert len(dispatched) == 1
    assert uses_paid_providers(dispatched[0]["config"])
    assert "overrides" not in dispatched[0]


def test_cli_scripted_experiment_does_not_require_approval(tmp_path, monkeypatch):
    spec_path = tmp_path / "scripted-experiment.yaml"
    spec_path.write_text(yaml.safe_dump({
        "name": "scripted",
        "config": _config(),
        "seeds": [1],
        "ticks": 1,
        "control": False,
    }), encoding="utf-8")
    dispatched = []
    monkeypatch.setattr(
        experiment_harness, "run_experiment", lambda spec: dispatched.append(spec))

    _prepare_cli(monkeypatch, "--experiment", str(spec_path))
    cli.main()

    assert len(dispatched) == 1
    assert not uses_paid_providers(dispatched[0]["config"])


def test_cli_paid_counterfactual_requires_approval_before_dispatch(monkeypatch):
    paid_config = _config()
    paid_config["llm"]["routes"] = {
        "oracle": {"provider": "minimax", "model": "MiniMax-M3"},
    }
    pack = type("Pack", (), {"config": lambda self: paid_config})()
    monkeypatch.setattr(scenarios, "load_scenario", lambda _path: pack)
    dispatched = []

    def dispatch(loaded_pack, **kwargs):
        dispatched.append((loaded_pack, kwargs))
        return {"scenario": {}, "design": {}, "artifacts": {}}

    monkeypatch.setattr(counterfactual_runner, "run_counterfactual", dispatch)

    _prepare_cli(monkeypatch, "--counterfactual", "paid-scenario.yaml")
    with pytest.raises(SystemExit, match="--approve-live-inference"):
        cli.main()
    assert not dispatched

    _prepare_cli(
        monkeypatch, "--counterfactual", "paid-scenario.yaml",
        "--approve-live-inference")
    cli.main()
    assert dispatched == [(pack, {
        "seeds": 20,
        "ticks": None,
        "effective_config": paid_config,
    })]


def test_cli_scripted_counterfactual_does_not_require_approval(monkeypatch):
    scripted_config = _config()
    pack = type("Pack", (), {"config": lambda self: scripted_config})()
    monkeypatch.setattr(scenarios, "load_scenario", lambda _path: pack)
    dispatched = []

    def dispatch(loaded_pack, **kwargs):
        dispatched.append((loaded_pack, kwargs))
        return {"scenario": {}, "design": {}, "artifacts": {}}

    monkeypatch.setattr(counterfactual_runner, "run_counterfactual", dispatch)

    _prepare_cli(monkeypatch, "--counterfactual", "scripted-scenario.yaml")
    cli.main()

    assert len(dispatched) == 1
    assert dispatched[0][0] is pack
    assert dispatched[0][1]["effective_config"] == scripted_config


def test_counterfactual_runner_reuses_the_authorized_effective_config(
        tmp_path, monkeypatch):
    effective_config = _config()
    effective_config["llm"]["routes"] = {
        "oracle": {"provider": "minimax", "model": "MiniMax-M3"},
    }
    pack = scenarios.ScenarioPack(
        key="authorized-config", version="1", title="Authorized config",
        ticks=1, base_config="unused.yaml", dataset_manifest="manifest.yaml",
        common_shocks=(),
        arms={"control": {}, "treatment": {}}, metrics=(),
        limitations="test only", path="unused.yaml", checksum_sha256="abc",
    )
    observed_configs = []

    def run_arm(_pack, seed, arm, _data_dir, ticks, arm_config):
        observed_configs.append(arm_config)
        return {
            "run_id": f"run-{arm}", "seed": seed, "arm": arm, "ticks": ticks,
            "reconciled": True, "reconciliation": {}, "metrics": {},
            "genesis_hash": "same-genesis", "replay_hash": f"hash-{arm}",
            "causal_trace": [],
        }

    monkeypatch.setattr(counterfactual_runner, "_run_arm", run_arm)

    counterfactual_runner.run_counterfactual(
        pack, seeds=[1], ticks=1, out_dir=tmp_path / "reports",
        data_root=tmp_path / "data", effective_config=effective_config)

    assert observed_configs == [effective_config, effective_config]


def test_rehearsal_initializes_acceptance_population_and_routes_every_role_locally():
    config = load_config("runs/acceptance/rehearsal.yaml")

    assert config["acceptance"]["min_ticks"] == 365
    assert {shock["kind"] for shock in config["shocks"]} == {
        "policy_rate", "oil", "rumor", "slant", "scandal",
    }
    routes = [config["llm"]["default_route"], *config["llm"]["routes"].values()]
    assert {route["provider"] for route in routes} == {"scripted"}
    assert not uses_paid_providers(config)

    store = Store(":memory:")
    store.init_run_meta("acceptance-population", int(config["seed"]), config)
    world = World(store, config)
    try:
        world.initialize()
        living_agents = int(store.scalar(
            "SELECT COUNT(*) FROM agents WHERE alive=1", default=0))
        total_agents = int(store.scalar(
            "SELECT COUNT(*) FROM agents", default=0))
        acceptance = config["acceptance"]

        assert living_agents == 100
        assert total_agents == 100
        assert acceptance["min_agents"] <= living_agents <= acceptance["max_agents"]
    finally:
        world.gateway.close()
        store.close()


def test_live_acceptance_profile_is_explicitly_uncapped():
    config = load_config("runs/acceptance/production.yaml")

    assert config["budget"]["cap_usd"] is None
    assert config["acceptance"]["max_spend_usd"] is None
    assert config["acceptance"]["efficiency_target_usd"] == 200
    assert config["acceptance"]["oracle_min_latency_samples"] == 5
    assert len(config["acceptance"]["oracle_questions"]) == 6
    assert config["information"]["citizen_bank_visibility"] == "public_status"


def test_live_pilot_profile_is_capped_and_rumor_scoped():
    config = load_config("runs/acceptance/pilot.yaml")

    assert config["acceptance"]["min_ticks"] == 30
    assert config["budget"]["cap_usd"] == 25.0
    assert config["acceptance"]["required_shocks"] == ["rumor"]
    assert not config["acceptance"]["require_oracle_scoring"]
    assert not config["acceptance"]["require_experiment"]
    assert not config["acceptance"]["require_phenomena"]


def test_scoped_pilot_receipt_omits_full_acceptance_requirements(tmp_path):
    db, _, _ = _passing_evidence(tmp_path)
    store = Store(str(db))
    meta = store.get_meta()
    config = json.loads(meta["config_json"])
    config["acceptance"].update({
        "required_shocks": ["rumor"],
        "require_oracle_scoring": False,
        "require_experiment": False,
        "require_phenomena": False,
        "oracle_min_latency_samples": 1,
    })
    store.init_run_meta(str(meta["run_id"]), int(meta["seed"]), config)
    store.commit()
    store.close()

    receipt = write_acceptance_package(db, out_dir=tmp_path / "pilot")
    assert receipt["passed"]
    assert receipt["requirements"]["required_shocks"] == ["rumor"]
    assert next(c for c in receipt["checks"] if c["id"] == "policy_rate_effect")[
        "evidence"] == {"required": False}


def test_uncapped_policy_is_preserved_in_receipt_and_end_report(tmp_path):
    db, experiment, phenomena = _passing_evidence(tmp_path)
    store = Store(str(db))
    meta = store.get_meta()
    config = json.loads(meta["config_json"])
    config["budget"]["cap_usd"] = None
    config["acceptance"]["max_spend_usd"] = None
    store.init_run_meta(str(meta["run_id"]), int(meta["seed"]), config)
    store.insert("llm_calls", tick=364, provider="minimax", model="MiniMax-M3",
                 purpose="decision", latency_ms=100, cost_usd=25_000.0)
    store.commit()

    receipt = write_acceptance_package(
        db, out_dir=tmp_path / "out", experiment_json=experiment, phenomena_yaml=phenomena
    )
    budget = next(check for check in receipt["checks"] if check["id"] == "budget")
    report_path = generate_report(store, out_dir=str(tmp_path / "out"))
    report = Path(report_path).read_text(encoding="utf-8")
    store.close()

    assert budget["passed"]
    assert budget["evidence"]["uncapped"]
    assert budget["evidence"]["spend_usd"] > 25_000
    assert "uncapped" in report

import asyncio
import json

import yaml

from engine.store import Store
from reports.acceptance import execute_acceptance_run, uses_paid_providers, write_acceptance_package
from world.loop import World


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
                       "rumor_initial_trust": 0.6},
    }
    store = Store(str(db))
    store.init_run_meta("acceptance-fixture", 9, config)
    store.set_meta(tick=365, status="paused")
    for agent_id in range(1, 101):
        store.insert("agents", id=agent_id, name=f"A{agent_id}", kind="citizen", age=30)
    store.insert("llm_calls", tick=5, provider="minimax", model="MiniMax-M3",
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
        store.insert("beliefs", agent_id=agent_id, key="trust:bank:1", value=0.35, updated_tick=61)
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
    phenomena_path.write_text(yaml.safe_dump({"phenomena": phenomena}), encoding="utf-8")
    return db, experiment_path, phenomena_path


def test_acceptance_package_is_machine_checkable_and_standalone(tmp_path):
    db, experiment, phenomena = _passing_evidence(tmp_path)
    receipt = write_acceptance_package(
        db, out_dir=tmp_path / "out", experiment_json=experiment, phenomena_yaml=phenomena
    )

    assert receipt["passed"]
    assert all(check["passed"] for check in receipt["checks"])
    payload = json.loads((tmp_path / "out" / "acceptance_acceptance-fixture.json").read_text())
    assert payload["passed"] and len(payload["checks"]) == 16
    markdown = (tmp_path / "out" / "acceptance_acceptance-fixture.md").read_text()
    assert "Overall: **PASS**" in markdown and "Rumor pilot" in markdown


def test_acceptance_package_fails_closed_without_reviewed_attachments(tmp_path):
    db, _, _ = _passing_evidence(tmp_path)
    receipt = write_acceptance_package(db, out_dir=tmp_path / "out")
    failed = {check["id"] for check in receipt["checks"] if not check["passed"]}

    assert not receipt["passed"]
    assert failed == {"experiment_n5", "emergent_phenomena"}


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

    assert failed == {"policy_rate_effect", "emergent_phenomena"}


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


def test_paid_acceptance_detection_fails_safe_for_any_real_route():
    assert not uses_paid_providers(_config())
    config = _config()
    config["llm"]["routes"] = {
        "oracle": {"provider": "kimi", "model": "kimi-for-coding"},
    }
    assert uses_paid_providers(config)

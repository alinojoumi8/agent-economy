"""Immutable, persisted scale-economic-health receipt coverage."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pytest

from engine.checkpoint_manifest import (
    checkpoint_manifest_path,
    finalize_sqlite_artifact,
    write_checkpoint_manifest,
)
from engine.store import Store
from reports.scale_economic_health import (
    CHECK_NAMES,
    ECONOMIC_CHECKS,
    _outcome,
    evaluate_scale_ab,
    evaluate_scale_economic_health,
    render_scale_economic_health_markdown,
    write_scale_ab_receipt,
    write_scale_economic_health_receipt,
)
from run_config import load_config
from world.replay_verify import verify_replay


ROOT = Path(__file__).resolve().parents[1]
BASELINE_PROFILE = ROOT / "runs/acceptance/scale-270-baseline-120.yaml"
RECOVERY_PROFILE = ROOT / "runs/acceptance/scale-270-recovery-120.yaml"
EXPECTED_POPULATION = {
    "agents": 308,
    "alive": 308,
    "citizen_kind": 272,
    "staff_kind": 36,
    "core": 100,
    "periphery": 208,
    "regions": {"ironvale": 69, "northstar": 184, "suncoast": 55},
}


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_manifest(root: Path, artifact_root: Path) -> list[dict[str, object]]:
    rows: dict[str, dict[str, object]] = {}
    databases: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        artifact = path.relative_to(artifact_root).as_posix()
        rows[artifact] = {
            "artifact": artifact,
            "kind": (
                "checkpoint_manifest" if path.name.endswith(".db.manifest.json")
                else "checkpoint_database" if path.suffix == ".db" and path.parent != root
                else "source_database" if path.suffix == ".db"
                else "artifact"
            ),
            "present": True,
            "bytes": path.stat().st_size,
            "sha256": _file_hash(path),
        }
        if path.suffix == ".db":
            databases.append(path)
    for database in databases:
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = Path(f"{database}{suffix}")
            artifact = sidecar.relative_to(artifact_root).as_posix()
            rows.setdefault(artifact, {
                "artifact": artifact,
                "kind": "sqlite_sidecar",
                "present": False,
                "bytes": 0,
                "sha256": None,
            })
    return [rows[name] for name in sorted(rows)]


def _write_checkpoint(store: Store, path: Path, tick: int) -> None:
    store.commit()
    source = sqlite3.connect(store.path)
    destination = sqlite3.connect(path)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE run_meta SET tick=?, status='paused', active_tick=NULL WHERE id=1",
            (tick,),
        )
        connection.commit()
    finally:
        connection.close()
    finalize_sqlite_artifact(path)
    write_checkpoint_manifest(path)


def _population(connection: sqlite3.Connection) -> dict[str, object]:
    connection.row_factory = sqlite3.Row
    return {
        "agents": int(connection.execute("SELECT COUNT(*) FROM agents").fetchone()[0]),
        "alive": int(connection.execute(
            "SELECT COUNT(*) FROM agents WHERE alive=1").fetchone()[0]),
        "citizen_kind": int(connection.execute(
            "SELECT COUNT(*) FROM agents WHERE kind='citizen'").fetchone()[0]),
        "staff_kind": int(connection.execute(
            "SELECT COUNT(*) FROM agents WHERE kind='staff'").fetchone()[0]),
        "core": int(connection.execute(
            "SELECT COUNT(*) FROM agents WHERE population_tier='core'").fetchone()[0]),
        "periphery": int(connection.execute(
            "SELECT COUNT(*) FROM agents WHERE population_tier='periphery'").fetchone()[0]),
        "regions": {
            str(row[0]): int(row[1])
            for row in connection.execute(
                "SELECT r.region_key,COUNT(a.id) FROM regions r "
                "LEFT JOIN agents a ON a.region_id=r.id "
                "GROUP BY r.id ORDER BY r.region_key")
        },
    }


def _communications(connection: sqlite3.Connection) -> dict[str, object]:
    conversations = connection.execute(
        "SELECT id,participant_ids FROM conversations ORDER BY id").fetchall()
    members = {
        int(row[0]): {int(value) for value in json.loads(row[1])}
        for row in conversations
    }
    counts: dict[int, int] = {}
    invalid = 0
    empty = 0
    for conversation_id, agent_id, body in connection.execute(
            "SELECT conv_id,agent_id,text FROM messages ORDER BY id"):
        conversation_id = int(conversation_id)
        counts[conversation_id] = counts.get(conversation_id, 0) + 1
        invalid += int(int(agent_id) not in members.get(conversation_id, set()))
        empty += int(not str(body).strip())
    return {
        "conversations": len(conversations),
        "messages": sum(counts.values()),
        "unique_participants": len(set().union(*members.values())),
        "invalid_message_memberships": invalid,
        "empty_messages": empty,
        "message_count_per_conversation": sorted(set(counts.values())),
    }


def _providers(connection: sqlite3.Connection) -> dict[str, object]:
    connection.row_factory = sqlite3.Row
    pairs = [dict(row) for row in connection.execute(
        "SELECT provider,model,COUNT(*) calls,COALESCE(SUM(in_tokens),0) in_tokens,"
        "COALESCE(SUM(out_tokens),0) out_tokens,COALESCE(SUM(cached),0) cached_calls,"
        "COALESCE(SUM(cost_usd),0) cost_usd FROM llm_calls "
        "GROUP BY provider,model ORDER BY provider,model")]
    purposes = {
        str(row[0]): int(row[1])
        for row in connection.execute(
            "SELECT purpose,COUNT(*) FROM llm_calls GROUP BY purpose ORDER BY purpose")
    }
    return {
        "calls": int(connection.execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0]),
        "cost_usd": float(connection.execute(
            "SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls").fetchone()[0]),
        "pairs": pairs,
        "purposes": purposes,
    }


@dataclass
class ScaleFixture:
    root: Path
    source: Path
    replay: Path
    runtime: Path
    profile: Path


def _seed_fixture(tmp_path: Path, *, profile: Path = BASELINE_PROFILE) -> ScaleFixture:
    artifact_root = tmp_path / "artifacts"
    source_root = artifact_root / "runs/source"
    replay_root = artifact_root / "runs/replay"
    output_root = artifact_root / "output"
    checkpoint_root = source_root / "checkpoints"
    source_root.mkdir(parents=True)
    replay_root.mkdir(parents=True)
    output_root.mkdir(parents=True)
    checkpoint_root.mkdir(parents=True)
    source = source_root / "scale-source.db"
    replay = replay_root / "scale-replay.db"
    runtime = output_root / "scale.runtime.json"

    config = load_config(profile)
    config["checkpoint_dir"] = str(checkpoint_root.resolve())
    config["report_dir"] = str((output_root / "reports").resolve())
    store = Store(str(source))
    store.init_run_meta("scale-source", int(config["seed"]), config)
    store.set_meta(status="finished", tick=120, active_tick=None, phase=None)

    regions = [
        ("northstar", "Northstar Federation", "NSD", 184),
        ("ironvale", "Ironvale Union", "IVC", 69),
        ("suncoast", "Suncoast Republic", "SCD", 55),
    ]
    region_ids: list[int] = []
    for key, name, currency, target in regions:
        region_ids.append(store.insert(
            "regions", region_key=key, name=name, currency_code=currency,
            population_target=target, specialization_json="[]", x=0.0, y=0.0,
            legal_ruleset="fixture-1.0",
        ))

    region_assignment = [region_ids[0]] * 184 + [region_ids[1]] * 69 + [region_ids[2]] * 55
    store.conn.execute("BEGIN")
    try:
        store.executemany(
            "INSERT INTO agents (id,name,kind,alive,population_tier,region_id) "
            "VALUES (?,?,?,?,?,?)",
            (
                (
                    index,
                    f"Agent {index}",
                    "citizen" if index <= 272 else "staff",
                    1,
                    "core" if index <= 100 else "periphery",
                    region_assignment[index - 1],
                )
                for index in range(1, 309)
            ),
        )
        store.conn.execute("COMMIT")
    except BaseException:
        store.conn.execute("ROLLBACK")
        raise

    employee_account = store.insert(
        "accounts", owner_type="agent", owner_id=1, bank_id=None,
        kind="checking", label="fixture employee", balance_cents=0,
        is_external=0, currency_code="NSD",
    )
    store.execute(
        "UPDATE agents SET checking_account_id=? WHERE id=1", (employee_account,))
    firm_id = store.insert(
        "firms", name="Healthy Goods Co.", sector="manufacturing", status="private",
        founded_tick=0, inventory=120, region_id=region_ids[0], currency_code="NSD",
        product_json=json.dumps({
            "good": "fixtures", "unit_price_cents": 600,
            "base_input_cost_cents": 180, "output_per_worker": 2,
        }),
    )
    store.insert(
        "employments", agent_id=1, firm_id=firm_id, title="maker",
        wage_cents=15000, start_tick=0, status="active",
        pay_interval_ticks=30, next_pay_tick=150,
    )

    store.conn.execute("BEGIN")
    try:
        store.executemany(
            "INSERT INTO metrics (tick,name,value) VALUES (?,'unemployment',?)",
            ((tick, 0.40) for tick in range(1, 121)),
        )
        store.executemany(
            "INSERT INTO action_proposals "
            "(tick,actor_id,action_type,payload_json,validation_status,result_json) "
            "VALUES (?,1,'buy_goods','{}','accepted',?)",
            ((tick, json.dumps({"ok": True})) for tick in range(60, 121)),
        )
        store.executemany(
            "INSERT INTO events (tick,phase,kind,subject_type,subject_id,payload_json) "
            "VALUES (?,'NIGHT_CLOSE','production','firm',?,?)",
            ((tick, firm_id, json.dumps({
                "firm_id": firm_id, "units": 2, "unit_cost_cents": 180,
            })) for tick in range(61, 121)),
        )
        store.executemany(
            "INSERT INTO events (tick,phase,kind,subject_type,subject_id,payload_json) "
            "VALUES (?,'MARKET','goods_sale','firm',?,?)",
            ((tick, firm_id, json.dumps({
                "firm_id": firm_id, "buyer_id": 2, "qty": 1,
                "unit_price_cents": 600, "total_cents": 600,
            })) for tick in range(61, 121)),
        )
        conversations = []
        messages = []
        conversation_id = 0
        message_id = 0
        for tick in range(1, 121):
            for pair in range(25):
                conversation_id += 1
                left = (pair * 2) % 100 + 1
                right = (pair * 2 + 1) % 100 + 1
                conversations.append((conversation_id, tick, json.dumps([left, right]), "fixture"))
                for sequence, agent_id in enumerate((left, right, left), start=1):
                    message_id += 1
                    messages.append((message_id, conversation_id, tick, agent_id, "hello", sequence))
        store.executemany(
            "INSERT INTO conversations (id,tick,participant_ids,topic) VALUES (?,?,?,?)",
            conversations,
        )
        store.executemany(
            "INSERT INTO messages (id,conv_id,tick,agent_id,text,seq) VALUES (?,?,?,?,?,?)",
            messages,
        )
        store.executemany(
            "INSERT INTO llm_calls "
            "(tick,agent_id,role,provider,model,purpose,in_tokens,out_tokens,cached,cost_usd) "
            "VALUES (?,1,'citizen','scripted','scripted','conversation',10,10,0,0.0)",
            ((tick,) for tick in range(1, 121)),
        )
        store.conn.execute("COMMIT")
    except BaseException:
        store.conn.execute("ROLLBACK")
        raise

    for tick in (105, 112, 119, 120):
        checkpoint = checkpoint_root / f"scale-source_t{tick}.db"
        _write_checkpoint(store, checkpoint, tick)
        store.insert("checkpoints", tick=tick, path=str(checkpoint.resolve()))
    store.close()
    finalize_sqlite_artifact(source)

    shutil.copyfile(source, replay)
    replay_connection = sqlite3.connect(replay)
    try:
        replay_connection.execute(
            "UPDATE run_meta SET run_id='scale-replay' WHERE id=1")
        replay_connection.commit()
    finally:
        replay_connection.close()
    finalize_sqlite_artifact(replay)

    normalized_config = deepcopy(config)
    normalized_config["checkpoint_dir"] = "runs/source/checkpoints"
    normalized_config["report_dir"] = "output/reports"
    profile_config = load_config(profile)
    source_hash = _file_hash(source)
    replay_proof = verify_replay(source, replay)
    source_connection = sqlite3.connect(source)
    replay_connection = sqlite3.connect(replay)
    try:
        population = _population(source_connection)
        communications = _communications(source_connection)
        providers = _providers(source_connection)
    finally:
        source_connection.close()
        replay_connection.close()
    receipt = {
        "schema": "agent-economy-scale-validation-v1",
        "schema_version": 1,
        "generated_at": "2026-08-10T00:00:00+00:00",
        "label": "baseline-120" if profile == BASELINE_PROFILE else "recovery-120",
        "profile_path": profile.relative_to(ROOT).as_posix(),
        "profile_sha256": _file_hash(profile),
        "profile_config_sha256": _canonical_hash(profile_config),
        "effective_config_sha256": _canonical_hash(normalized_config),
        "effective_config": normalized_config,
        "source_commit": "a" * 40,
        "configuration": {
            "ticks": 120,
            "live": False,
            "hard_cap_usd": float(config["budget"]["cap_usd"]),
            "checkpoint_every": int(config["checkpoint_every"]),
            "checkpoint_keep_last": int(config["checkpoint_keep_last"]),
            "conversation_pairs": int(config["budget"]["conversation_pairs"]),
            "conversation_turns": int(config["conversations"]["turns"]),
            "route_contract": config["llm"].get("route_contract"),
            "default_route": config["llm"].get("default_route"),
        },
        "preflight": {
            "ready": True, "mode": "scripted", "routed_providers": ["scripted"],
            "route_contract": None, "live_checked": False, "live_ready": True,
        },
        "artifacts": {"runtime_receipt": "output/scale.runtime.json"},
        "source": {
            "run_id": "scale-source", "database": "runs/source/scale-source.db",
            "status": "finished", "tick": 120, "active_tick": None,
            "sha256_before_replay": source_hash,
            "sha256_after_replay": source_hash,
            "artifact_manifest_before_replay": _artifact_manifest(source_root, artifact_root),
            "artifact_manifest_after_replay": _artifact_manifest(source_root, artifact_root),
        },
        "replay": {
            "run_id": "scale-replay", "database": "runs/replay/scale-replay.db",
            "wall_s": 1.0, "proof": replay_proof,
            "execution": {"live_dispatch_count": 0},
            "artifact_manifest": _artifact_manifest(replay_root, artifact_root),
        },
        "runtime": {
            "genesis_wall_s": 1.0, "source_wall_s": 10.0,
            "ticks": [{"tick": tick, "wall_s": 0.05} for tick in range(1, 121)],
            "checkpoints": [
                {"tick": tick, "reason": "interval", "duration_s": 0.10,
                 "artifact": f"runs/source/checkpoints/scale-source_t{tick}.db",
                 "manifest_artifact": (
                     f"runs/source/checkpoints/scale-source_t{tick}.db.manifest.json")}
                for tick in (105, 112, 119, 120)
            ],
            "memory": {
                "samples": 10, "peak_rss_mb": 512.0,
                "min_available_memory_gb": 32.0,
            },
            "database": {
                "logical_used_growth_bytes": 1024 * 1024,
                "genesis": {"logical_used_bytes": 1024 * 1024},
                "final_open": {"logical_used_bytes": 2 * 1024 * 1024},
            },
        },
        "population": population,
        "communications": communications,
        "providers": providers,
        "governor": {"total_spend_usd": providers["cost_usd"]},
        "integrity": {
            "quick_check": ["ok"], "foreign_key_violations": [],
            "failure_events": {}, "sqlite_sidecars": [], "ledger_ok": True,
            "ledger_diagnostic": {},
        },
        "checks": {"runtime_fixture": True},
        "passed": True,
    }
    runtime.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return ScaleFixture(artifact_root, source, replay, runtime, profile)


def _read_runtime(fixture: ScaleFixture) -> dict:
    return json.loads(fixture.runtime.read_text(encoding="utf-8"))


def _write_runtime(fixture: ScaleFixture, receipt: dict) -> None:
    fixture.runtime.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _refresh_runtime(fixture: ScaleFixture) -> None:
    receipt = _read_runtime(fixture)
    source_hash = _file_hash(fixture.source)
    source_root = fixture.source.parent
    replay_root = fixture.replay.parent
    receipt["source"]["sha256_before_replay"] = source_hash
    receipt["source"]["sha256_after_replay"] = source_hash
    receipt["source"]["artifact_manifest_before_replay"] = _artifact_manifest(
        source_root, fixture.root)
    receipt["source"]["artifact_manifest_after_replay"] = _artifact_manifest(
        source_root, fixture.root)
    receipt["replay"]["artifact_manifest"] = _artifact_manifest(replay_root, fixture.root)
    receipt["replay"]["proof"] = verify_replay(fixture.source, fixture.replay)
    connection = sqlite3.connect(fixture.source)
    try:
        connection.row_factory = sqlite3.Row
        meta = connection.execute(
            "SELECT run_id,status,tick,active_tick FROM run_meta WHERE id=1").fetchone()
        receipt["source"].update({
            "run_id": str(meta["run_id"]), "status": str(meta["status"]),
            "tick": int(meta["tick"]), "active_tick": meta["active_tick"],
        })
        receipt["population"] = _population(connection)
        receipt["communications"] = _communications(connection)
        receipt["providers"] = _providers(connection)
        receipt["governor"]["total_spend_usd"] = receipt["providers"]["cost_usd"]
    finally:
        connection.close()
    _write_runtime(fixture, receipt)


def _mutate_both(fixture: ScaleFixture, mutate: Callable[[sqlite3.Connection], None]) -> None:
    for database in (fixture.source, fixture.replay):
        connection = sqlite3.connect(database)
        try:
            mutate(connection)
            connection.commit()
        finally:
            connection.close()
        finalize_sqlite_artifact(database)
    _refresh_runtime(fixture)


def test_healthy_persisted_fixture_produces_deterministic_all_green_receipt(tmp_path: Path):
    fixture = _seed_fixture(tmp_path)

    first = evaluate_scale_economic_health(fixture.source, fixture.replay, fixture.runtime)
    second = evaluate_scale_economic_health(fixture.source, fixture.replay, fixture.runtime)

    assert first == second
    assert first["schema"] == "agent-economy-scale-economic-health-v1"
    assert first["outcome"] == "passed"
    assert first["passed"] is True
    assert all(first["checks"].values())
    assert first["population"] == EXPECTED_POPULATION
    assert first["run"]["tick"] == 120


@pytest.mark.parametrize(
    ("mutation", "failed_check"),
    (
        ("wrong_profile", "identity_exact"),
        ("wrong_config_hash", "identity_exact"),
        ("wrong_population", "population_exact"),
        ("wrong_tiering", "population_exact"),
        ("wrong_regions", "population_exact"),
        ("tick_119", "horizon_completed"),
        ("active_phase", "horizon_completed"),
        ("unresolved_proposal", "purchase_windows_healthy"),
        ("rejection_over_5pct", "purchase_windows_healthy"),
        ("unemployment_rebound", "unemployment_rebound_bounded"),
        ("worsening_final_mean", "unemployment_final_mean_not_worse"),
        ("missing_production", "production_and_inventory_healthy"),
        ("zero_inventory", "production_and_inventory_healthy"),
        ("labor_backlog", "labor_backlog_bounded"),
        ("invalid_wage", "employment_currency_and_terms_valid"),
        ("invalid_currency", "employment_currency_and_terms_valid"),
        ("insolvency", "managed_insolvency_absent"),
        ("ledger_imbalance", "ledger_reconciles"),
        ("checkpoint_hash", "checkpoints_valid"),
        ("replay_difference", "exact_replay"),
        ("source_mutation", "source_immutable"),
        ("scripted_spend", "provider_and_spend_exact"),
        ("rss_over_cap", "resources_within_caps"),
        ("memory_below_floor", "resources_within_caps"),
        ("database_growth_over_cap", "resources_within_caps"),
        ("checkpoint_p95_over_cap", "resources_within_caps"),
        ("secret_canary", "runtime_receipt_safe"),
    ),
)
def test_evaluator_fails_closed_for_persisted_and_runtime_mutations(
    tmp_path: Path, mutation: str, failed_check: str,
):
    fixture = _seed_fixture(tmp_path)

    if mutation == "wrong_profile":
        receipt = _read_runtime(fixture)
        receipt["profile_path"] = "runs/acceptance/not-the-profile.yaml"
        _write_runtime(fixture, receipt)
    elif mutation == "wrong_config_hash":
        receipt = _read_runtime(fixture)
        receipt["effective_config_sha256"] = "0" * 64
        _write_runtime(fixture, receipt)
    elif mutation == "wrong_population":
        _mutate_both(fixture, lambda connection: connection.execute(
            "UPDATE agents SET alive=0 WHERE id=308"))
    elif mutation == "wrong_tiering":
        _mutate_both(fixture, lambda connection: connection.execute(
            "UPDATE agents SET population_tier='periphery' WHERE id=1"))
    elif mutation == "wrong_regions":
        _mutate_both(fixture, lambda connection: connection.execute(
            "UPDATE agents SET region_id=2 WHERE id=1"))
    elif mutation == "tick_119":
        _mutate_both(fixture, lambda connection: connection.execute(
            "UPDATE run_meta SET tick=119 WHERE id=1"))
    elif mutation == "active_phase":
        _mutate_both(fixture, lambda connection: connection.execute(
            "UPDATE run_meta SET status='running',active_tick=120,phase='MARKET' WHERE id=1"))
    elif mutation == "unresolved_proposal":
        _mutate_both(fixture, lambda connection: connection.execute(
            "UPDATE action_proposals SET validation_status='pending' WHERE tick=120"))
    elif mutation == "rejection_over_5pct":
        _mutate_both(fixture, lambda connection: connection.execute(
            "UPDATE action_proposals SET validation_status='rejected' WHERE tick IN (117,118,119,120)"))
    elif mutation == "unemployment_rebound":
        _mutate_both(fixture, lambda connection: connection.execute(
            "UPDATE metrics SET value=0.55 WHERE name='unemployment' AND tick>=61"))
    elif mutation == "worsening_final_mean":
        _mutate_both(fixture, lambda connection: connection.execute(
            "UPDATE metrics SET value=0.45 WHERE name='unemployment' AND tick>=61"))
    elif mutation == "missing_production":
        _mutate_both(fixture, lambda connection: connection.execute(
            "DELETE FROM events WHERE kind='production' AND tick>=61"))
    elif mutation == "zero_inventory":
        def persistently_zero(connection: sqlite3.Connection) -> None:
            connection.execute("UPDATE firms SET inventory=0 WHERE id=1")
            for row in connection.execute(
                    "SELECT id,payload_json FROM events WHERE kind='production'"):
                payload = json.loads(row[1])
                payload["units"] = 0
                connection.execute(
                    "UPDATE events SET payload_json=? WHERE id=?",
                    (json.dumps(payload), row[0]),
                )
        _mutate_both(fixture, persistently_zero)
    elif mutation == "labor_backlog":
        def add_jobs(connection: sqlite3.Connection) -> None:
            connection.executemany(
                "INSERT INTO jobs (tick,firm_id,title,wage_cents,status) "
                "VALUES (120,1,'fixture',15000,'open')",
                [()] * 21,
            )
        _mutate_both(fixture, add_jobs)
    elif mutation == "invalid_wage":
        _mutate_both(fixture, lambda connection: connection.execute(
            "UPDATE employments SET wage_cents=0 WHERE id=1"))
    elif mutation == "invalid_currency":
        _mutate_both(fixture, lambda connection: connection.execute(
            "UPDATE accounts SET currency_code='IVC' WHERE owner_type='agent' AND owner_id=1"))
    elif mutation == "insolvency":
        def bankrupt(connection: sqlite3.Connection) -> None:
            connection.execute(
                "UPDATE firms SET status='bankrupt',bankrupt_tick=100 WHERE id=1")
            connection.execute(
                "INSERT INTO events (tick,kind,subject_type,subject_id,payload_json) "
                "VALUES (100,'bankruptcy','firm',1,?)",
                (json.dumps({"firm_id": 1, "reason": "insolvency"}),),
            )
        _mutate_both(fixture, bankrupt)
    elif mutation == "ledger_imbalance":
        _mutate_both(fixture, lambda connection: connection.execute(
            "UPDATE accounts SET balance_cents=1 WHERE id=1"))
    elif mutation == "checkpoint_hash":
        manifest = checkpoint_manifest_path(
            fixture.source.parent / "checkpoints/scale-source_t120.db")
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["database_sha256"] = "0" * 64
        manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif mutation == "replay_difference":
        connection = sqlite3.connect(fixture.replay)
        try:
            connection.execute(
                "INSERT INTO metrics (tick,name,value) VALUES (120,'fixture-difference',1.0)")
            connection.commit()
        finally:
            connection.close()
        finalize_sqlite_artifact(fixture.replay)
    elif mutation == "source_mutation":
        connection = sqlite3.connect(fixture.source)
        try:
            connection.execute(
                "UPDATE run_meta SET updated_at='mutated-after-runtime' WHERE id=1")
            connection.commit()
        finally:
            connection.close()
        finalize_sqlite_artifact(fixture.source)
    elif mutation == "scripted_spend":
        _mutate_both(fixture, lambda connection: connection.execute(
            "UPDATE llm_calls SET cost_usd=0.01 WHERE id=1"))
    elif mutation in {
        "rss_over_cap", "memory_below_floor", "database_growth_over_cap",
        "checkpoint_p95_over_cap", "secret_canary",
    }:
        receipt = _read_runtime(fixture)
        if mutation == "rss_over_cap":
            receipt["runtime"]["memory"]["peak_rss_mb"] = 2048.01
        elif mutation == "memory_below_floor":
            receipt["runtime"]["memory"]["min_available_memory_gb"] = 7.99
        elif mutation == "database_growth_over_cap":
            receipt["runtime"]["database"]["logical_used_growth_bytes"] = 120 * 8388608 + 1
        elif mutation == "checkpoint_p95_over_cap":
            receipt["runtime"]["checkpoints"][-1]["duration_s"] = 6.0
        else:
            receipt["api_key"] = "secret-canary-value"
        _write_runtime(fixture, receipt)
    else:  # pragma: no cover - keeps the mutation table exhaustive
        raise AssertionError(mutation)

    evaluated = evaluate_scale_economic_health(
        fixture.source, fixture.replay, fixture.runtime)

    assert evaluated["passed"] is False
    assert evaluated["checks"][failed_check] is False


def test_sqlite_sidecar_is_rejected_without_opening_mutable_state(tmp_path: Path):
    fixture = _seed_fixture(tmp_path)
    Path(f"{fixture.source}-wal").touch()

    receipt = evaluate_scale_economic_health(fixture.source, fixture.replay, fixture.runtime)

    assert receipt["passed"] is False
    assert receipt["checks"]["sqlite_integrity"] is False
    assert receipt["evidence"]["sqlite_integrity"]["source_sidecars"] == ["-wal"]
    assert set(receipt["profile"]) == {
        "path", "required_ticks", "diagnostic", "recovery_enabled",
        "policy_version", "profile_config_sha256", "effective_config_sha256",
        "source_commit",
    }


def test_receipt_writers_emit_deterministic_json_markdown_and_cli_exit_contract(tmp_path: Path):
    fixture = _seed_fixture(tmp_path)
    output = tmp_path / "receipts/scale-health"

    written = write_scale_economic_health_receipt(
        fixture.source, fixture.replay, fixture.runtime, output=output)

    assert written["passed"] is True
    assert json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))["passed"] is True
    assert output.with_suffix(".md").read_text(encoding="utf-8") == (
        render_scale_economic_health_markdown(written))

    completed = subprocess.run(
        [
            sys.executable, "-m", "reports.scale_economic_health",
            "--source", str(fixture.source), "--replay", str(fixture.replay),
            "--runtime-receipt", str(fixture.runtime), "--output", str(tmp_path / "cli"),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_diagnostic_economic_failure_uses_exit_10_but_formal_failure_uses_exit_5(tmp_path: Path):
    fixture = _seed_fixture(tmp_path / "diagnostic")
    _mutate_both(fixture, lambda connection: connection.execute(
        "UPDATE metrics SET value=0.45 WHERE name='unemployment' AND tick>=61"))
    diagnostic = evaluate_scale_economic_health(fixture.source, fixture.replay, fixture.runtime)
    assert diagnostic["outcome"] == "diagnostic_economic_failure"

    completed = subprocess.run(
        [
            sys.executable, "-m", "reports.scale_economic_health",
            "--source", str(fixture.source), "--replay", str(fixture.replay),
            "--runtime-receipt", str(fixture.runtime), "--output", str(tmp_path / "diagnostic-cli"),
        ], cwd=ROOT, check=False, capture_output=True, text=True,
    )
    assert completed.returncode == 10, completed.stderr

    formal_checks = {name: True for name in CHECK_NAMES}
    formal_checks[next(iter(ECONOMIC_CHECKS))] = False
    assert _outcome(formal_checks, diagnostic=True) == "diagnostic_economic_failure"
    assert _outcome(formal_checks, diagnostic=False) == "failed"


def test_ab_allows_only_exact_recovery_policy_difference_and_baseline_diagnostics(tmp_path: Path):
    baseline_fixture = _seed_fixture(tmp_path / "baseline", profile=BASELINE_PROFILE)
    recovery_fixture = _seed_fixture(tmp_path / "recovery", profile=RECOVERY_PROFILE)
    baseline = evaluate_scale_economic_health(
        baseline_fixture.source, baseline_fixture.replay, baseline_fixture.runtime)
    recovery = evaluate_scale_economic_health(
        recovery_fixture.source, recovery_fixture.replay, recovery_fixture.runtime)

    aggregate = evaluate_scale_ab(baseline, recovery)

    assert aggregate["schema"] == "agent-economy-scale-ab-v1"
    assert aggregate["passed"] is True
    assert aggregate["checks"]["configs_differ_only_by_recovery_policy"] is True

    diagnostic = deepcopy(baseline)
    diagnostic["checks"]["unemployment_final_mean_not_worse"] = False
    diagnostic["passed"] = False
    diagnostic["outcome"] = "diagnostic_economic_failure"
    assert evaluate_scale_ab(diagnostic, recovery)["passed"] is True

    drifted = deepcopy(recovery)
    drifted["runtime"]["effective_config"]["seed"] = 99
    drifted["runtime"]["effective_config_sha256"] = _canonical_hash(
        drifted["runtime"]["effective_config"])
    rejected = evaluate_scale_ab(baseline, drifted)
    assert rejected["passed"] is False
    assert rejected["checks"]["configs_differ_only_by_recovery_policy"] is False


def test_ab_writer_emits_atomic_json_and_markdown(tmp_path: Path):
    baseline_fixture = _seed_fixture(tmp_path / "baseline", profile=BASELINE_PROFILE)
    recovery_fixture = _seed_fixture(tmp_path / "recovery", profile=RECOVERY_PROFILE)
    baseline = evaluate_scale_economic_health(
        baseline_fixture.source, baseline_fixture.replay, baseline_fixture.runtime)
    recovery = evaluate_scale_economic_health(
        recovery_fixture.source, recovery_fixture.replay, recovery_fixture.runtime)
    output = tmp_path / "receipts/ab"

    receipt = write_scale_ab_receipt(baseline, recovery, output=output)

    assert receipt["passed"] is True
    assert json.loads(output.with_suffix(".json").read_text(encoding="utf-8")) == receipt
    assert output.with_suffix(".md").read_text(encoding="utf-8").startswith(
        "# Scale-270 economic-health A/B")

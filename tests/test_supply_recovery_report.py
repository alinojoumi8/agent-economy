"""Persisted-evidence acceptance coverage for the supply-recovery profile."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from engine.checkpoint_manifest import (
    canonical_json_bytes,
    checkpoint_manifest_path,
    finalize_sqlite_artifact,
    write_checkpoint_manifest,
)
from engine.store import Store
from reports import supply_recovery as supply_recovery_report
from reports.supply_recovery import (
    evaluate_supply_recovery,
    evaluate_supply_recovery_db,
    render_supply_recovery_markdown,
)
from run_config import load_config


ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "supply-recovery-fixture"


def _config(tmp_path: Path, *, checkpoint_dir: str | None = None) -> dict:
    return {
        "llm": {"default_route": {"provider": "scripted", "model": "scripted"}, "routes": {}},
        "checkpoint_dir": checkpoint_dir or str((tmp_path / "checkpoints").resolve()),
        "checkpoint_every": 100,
        "checkpoint_keep_last": 2,
        "supply_recovery": {
            "enabled": True,
            "policy_version": "supply-recovery-v1",
            "activation_tick": 0,
            "wage_floor_cents": 15000,
            "gross_margin_coverage_bps": 12500,
            "cash_payroll_coverage_periods": 2,
            "max_hires_per_firm_per_period": 1,
            "demand_buffer_ticks": 5,
            "sales_observation_ticks": 30,
        },
        "acceptance": {
            "min_ticks": 1000,
            "supply_recovery": {
                "warmup_ticks": 60,
                "trailing_window_ticks": 60,
                "max_buy_goods_rejection_rate": 0.05,
                "max_unemployment_rebound": 0.10,
                "max_pending_applications": 20,
                "max_pending_job_offers": 20,
                "max_open_jobs": 20,
            },
        },
    }


def _checkpoint_directory_for_fixture(db_path: Path, config: dict) -> Path:
    configured = Path(config["checkpoint_dir"])
    return configured if configured.is_absolute() else db_path.parent / configured


def _write_valid_checkpoint(store: Store, path: Path, tick: int) -> None:
    """Create a finalized persisted checkpoint without starting a World."""
    store.commit()
    source = sqlite3.connect(store.path)
    destination = sqlite3.connect(str(path))
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    checkpoint = sqlite3.connect(str(path))
    try:
        checkpoint.execute(
            "UPDATE run_meta SET tick=?, status='paused', active_tick=NULL WHERE id=1",
            (tick,),
        )
        checkpoint.commit()
    finally:
        checkpoint.close()
    finalize_sqlite_artifact(path)
    write_checkpoint_manifest(path)


def _seed_healthy_store(tmp_path: Path, *, checkpoint_dir: str | None = None) -> Store:
    db_path = tmp_path / "supply-recovery.db"
    store = Store(str(db_path))
    config = _config(tmp_path, checkpoint_dir=checkpoint_dir)
    store.init_run_meta(RUN_ID, 17, config)
    store.set_meta(status="finished", tick=1000)

    firm_id = store.insert(
        "firms",
        name="Fixture Goods Co.",
        sector="manufacturing",
        status="private",
        founded_tick=0,
        inventory=10,
        product_json=json.dumps(
            {
                "good": "fixtures",
                "unit_price_cents": 600,
                "base_input_cost_cents": 180,
                "output_per_worker": 2,
            }
        ),
    )
    store.insert(
        "employments",
        agent_id=1,
        firm_id=firm_id,
        wage_cents=15000,
        start_tick=0,
        status="active",
        pay_interval_ticks=30,
        next_pay_tick=30,
    )
    store.insert(
        "events",
        tick=1000,
        kind="production",
        subject_type=None,
        subject_id=None,
        payload_json=json.dumps(
            {
                "firm_id": firm_id,
                "units": 2,
                "unit_cost_cents": 180,
            }
        ),
    )

    for tick in range(1001):
        store.insert(
            "metrics",
            tick=tick,
            name="unemployment",
            value=0.45 if tick >= 941 else 0.42,
        )
        if tick >= 60:
            store.insert(
                "action_proposals",
                tick=tick,
                actor_id=1,
                action_type="buy_goods",
                payload_json="{}",
                validation_status="accepted",
                result_json=json.dumps({"ok": True}),
            )

    checkpoint_directory = _checkpoint_directory_for_fixture(db_path, config)
    checkpoint_directory.mkdir(parents=True, exist_ok=True)
    for tick in (900, 1000):
        checkpoint_path = checkpoint_directory / f"{RUN_ID}_t{tick}.db"
        _write_valid_checkpoint(store, checkpoint_path, tick)
        store.insert("checkpoints", tick=tick, path=str(checkpoint_path))

    store.commit()
    return store


def _close(store: Store) -> None:
    store.commit()
    store.close()


def _files_under(directory: Path) -> set[Path]:
    return {
        path.relative_to(directory)
        for path in directory.rglob("*")
        if path.is_file()
    }


def _checkpoint_path(tmp_path: Path, tick: int) -> Path:
    return Path(_config(tmp_path)["checkpoint_dir"]) / f"{RUN_ID}_t{tick}.db"


def test_profile_is_provider_free_and_has_explicit_recovery_acceptance_settings():
    config = load_config(ROOT / "runs/acceptance/supply-recovery.yaml")

    assert config["llm"]["default_route"] == {"provider": "scripted", "model": "scripted"}
    assert config["llm"]["routes"] == {}
    assert config["checkpoint_every"] == 100
    assert config["checkpoint_keep_last"] == 2
    assert config["acceptance"]["min_ticks"] == 1000
    assert config["supply_recovery"] == {
        "enabled": True,
        "policy_version": "supply-recovery-v1",
        "activation_tick": 0,
        "wage_floor_cents": 15000,
        "gross_margin_coverage_bps": 12500,
        "cash_payroll_coverage_periods": 2,
        "max_hires_per_firm_per_period": 1,
        "demand_buffer_ticks": 5,
        "sales_observation_ticks": 30,
    }
    assert config["acceptance"]["supply_recovery"] == {
        "warmup_ticks": 60,
        "trailing_window_ticks": 60,
        "max_buy_goods_rejection_rate": 0.05,
        "max_unemployment_rebound": 0.10,
        "max_pending_applications": 20,
        "max_pending_job_offers": 20,
        "max_open_jobs": 20,
    }


def test_persisted_healthy_evidence_produces_a_passing_deterministic_receipt(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        first = evaluate_supply_recovery(store)
        second = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert first == second
    assert first["passed"] is True
    assert all(isinstance(value, bool) for value in first["checks"].values())
    assert first["checks"] == {
        "recovery_profile_persisted": True,
        "horizon_completed": True,
        "buy_goods_rejection_rate_within_5pct": True,
        "unemployment_rebound_within_10pp": True,
        "recovery_managed_insolvency_absent": True,
        "labor_backlog_bounded": True,
        "ledger_reconciled": True,
        "sqlite_integrity": True,
        "checkpoint_retention": True,
        "unit_economics_validated": True,
    }
    assert first["run"] == {
        "run_id": RUN_ID,
        "seed": 17,
        "status": "finished",
        "tick": 1000,
    }
    assert first["evidence"]["buy_goods_rejection"]["windows_evaluated"] == 882
    assert first["evidence"]["buy_goods_rejection"]["latest_window"]["attempts"] == 60
    assert first["evidence"]["buy_goods_rejection"]["latest_window"]["rejected"] == 0
    assert first["evidence"]["sqlite_integrity"]["integrity_check"] == ["ok"]
    assert first["unit_economics"][0]["validated"] is True
    assert first["unit_economics"][0]["employment"][0]["wage_cents"] == 15000


@pytest.mark.parametrize(
    ("path", "bad_value"),
    [
        (("checkpoint_every",), 0),
        (("checkpoint_keep_last",), 3),
        (("checkpoint_every",), True),
        (("supply_recovery", "wage_floor_cents"), "15000"),
        (("acceptance", "supply_recovery", "warmup_ticks"), 60.0),
    ],
)
def test_profile_requires_exact_persisted_types_and_checkpoint_settings(
        tmp_path: Path, path: tuple[str, ...], bad_value: object):
    store = _seed_healthy_store(tmp_path)
    try:
        config = json.loads(store.get_meta()["config_json"])
        target = config
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = bad_value
        store.set_meta(config_json=json.dumps(config))
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["recovery_profile_persisted"] is False


def test_profile_rejects_extra_supply_recovery_acceptance_setting(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        config = json.loads(store.get_meta()["config_json"])
        config["acceptance"]["supply_recovery"]["unreviewed_override"] = 1
        store.set_meta(config_json=json.dumps(config))
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["recovery_profile_persisted"] is False


def test_report_db_rejects_newer_schema_before_evaluation(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    database = Path(store.path)
    try:
        store.set_meta(schema_version=999)
        store.commit()
    finally:
        _close(store)

    report = evaluate_supply_recovery_db(database)

    assert report["passed"] is False
    assert report["evidence"]["error"] == "run database schema is incompatible"


def test_direct_report_rejects_newer_schema_before_evaluation(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        store.set_meta(schema_version=999)
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["evidence"]["error"] == "run database schema is incompatible"


def test_report_db_missing_active_tick_returns_a_failed_receipt(tmp_path: Path):
    database = tmp_path / "missing-active-tick.db"
    connection = sqlite3.connect(str(database))
    try:
        connection.execute(
            "CREATE TABLE run_meta ("
            "id INTEGER PRIMARY KEY,run_id TEXT,seed INTEGER,schema_version INTEGER,"
            "config_json TEXT,status TEXT,tick INTEGER)"
        )
        connection.execute(
            "INSERT INTO run_meta VALUES (1,?,?,?,?,?,?)",
            (RUN_ID, 17, 17, json.dumps({}), "finished", 1000),
        )
        connection.commit()
    finally:
        connection.close()

    report = evaluate_supply_recovery_db(database)

    assert report["passed"] is False
    assert report["evidence"]["error"] == "run metadata is missing required fields: active_tick"


def test_report_db_missing_schema_version_returns_a_failed_receipt(tmp_path: Path):
    database = tmp_path / "missing-schema-version.db"
    connection = sqlite3.connect(str(database))
    try:
        connection.execute(
            "CREATE TABLE run_meta ("
            "id INTEGER PRIMARY KEY,run_id TEXT,seed INTEGER,config_json TEXT,"
            "status TEXT,tick INTEGER,active_tick INTEGER)"
        )
        connection.execute(
            "INSERT INTO run_meta VALUES (1,?,?,?,?,?,?)",
            (RUN_ID, 17, json.dumps({}), "finished", 1000, None),
        )
        connection.commit()
    finally:
        connection.close()

    report = evaluate_supply_recovery_db(database)

    assert report["passed"] is False
    assert report["evidence"]["error"] == "run metadata is missing required fields: schema_version"


def test_report_rejects_non_null_unparseable_active_tick(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        store.set_meta(status="paused", active_tick="garbage")
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["horizon_completed"] is False
    assert report["evidence"]["horizon"]["active_tick"] == "garbage"


def test_active_producer_with_invalid_output_is_retained_as_invalid_evidence(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        product = json.loads(store.query_one("SELECT product_json FROM firms WHERE id=1")["product_json"])
        product["output_per_worker"] = 0
        store.execute("UPDATE firms SET product_json=? WHERE id=1", (json.dumps(product),))
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["unit_economics_validated"] is False
    assert report["unit_economics"][0]["firm_id"] == 1
    assert "missing_or_invalid_output_per_worker" in report["unit_economics"][0]["validation_errors"]


def test_bankrupt_recovery_goods_firm_requires_matching_bankruptcy_event(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        store.execute("UPDATE firms SET status='bankrupt', bankrupt_tick=700 WHERE id=1")
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["recovery_managed_insolvency_absent"] is False
    assert report["evidence"]["recovery_managed_insolvencies"]["state_mismatches"] == [
        {"firm_id": 1, "reason": "missing_matching_bankruptcy_event", "status": "bankrupt", "tick": 700}
    ]


@pytest.mark.parametrize("status", ["mystery", "active"])
def test_recovery_goods_firm_rejects_an_unknown_status(tmp_path: Path, status: str):
    store = _seed_healthy_store(tmp_path)
    try:
        store.execute("UPDATE firms SET status=? WHERE id=1", (status,))
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["recovery_managed_insolvency_absent"] is False
    assert report["evidence"]["recovery_managed_insolvencies"]["state_mismatches"] == [
        {
            "firm_id": 1,
            "reason": "unknown_recovery_goods_firm_status",
            "status": status,
            "tick": None,
        }
    ]


def test_live_recovery_goods_firm_rejects_noninsolvency_bankruptcy_event(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        store.insert(
            "events",
            tick=700,
            kind="bankruptcy",
            subject_type="firm",
            subject_id=1,
            payload_json=json.dumps({"firm_id": 1, "reason": "market_exit"}),
        )
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["recovery_managed_insolvency_absent"] is False
    assert report["evidence"]["recovery_managed_insolvencies"]["state_mismatches"] == [
        {
            "firm_id": 1,
            "reason": "bankruptcy_event_requires_bankrupt_status",
            "status": "private",
            "tick": 700,
        }
    ]


@pytest.mark.parametrize("status", ["private", "listed"])
def test_nonterminal_recovery_goods_firm_rejects_a_bankruptcy_tick(
        tmp_path: Path, status: str):
    store = _seed_healthy_store(tmp_path)
    try:
        store.execute(
            "UPDATE firms SET status=?, bankrupt_tick=700 WHERE id=1", (status,)
        )
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["recovery_managed_insolvency_absent"] is False
    assert report["evidence"]["recovery_managed_insolvencies"]["state_mismatches"] == [
        {
            "firm_id": 1,
            "reason": "nonterminal_status_has_bankrupt_tick",
            "status": status,
            "tick": 700,
        }
    ]


@pytest.mark.parametrize(
    ("kind", "payload"),
    [
        ("production", {"firm_id": 999, "units": 1, "unit_cost_cents": 180}),
        ("goods_sale", {"firm_id": 999, "units": 1}),
    ],
)
def test_report_rejects_orphan_persisted_producer_identity(
        tmp_path: Path, kind: str, payload: dict[str, int]):
    store = _seed_healthy_store(tmp_path)
    try:
        store.insert(
            "events",
            tick=1000,
            kind=kind,
            subject_type="firm",
            subject_id=999,
            payload_json=json.dumps(payload),
        )
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["unit_economics_validated"] is False
    assert report["evidence"]["unit_economics"]["orphan_producer_events"] == [
        {"event_id": 2, "firm_id": 999, "kind": kind, "tick": 1000}
    ]


def test_report_rejects_malformed_explicit_producer_identity(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        store.insert(
            "events",
            tick=1000,
            kind="goods_sale",
            subject_type="firm",
            subject_id=1,
            payload_json=json.dumps({"firm_id": "not-an-id", "units": 1}),
        )
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["unit_economics_validated"] is False
    assert report["evidence"]["unit_economics"]["malformed_producer_events"] == [
        {"event_id": 2, "firm_id": None, "kind": "goods_sale", "tick": 1000}
    ]


@pytest.mark.parametrize(
    ("kind", "payload"),
    [
        ("production", {"firm_id": 1, "units": 1, "unit_cost_cents": 180}),
        (
            "goods_sale",
            {
                "firm_id": 1,
                "buyer_id": 2,
                "qty": 1,
                "unit_price_cents": 600,
                "total_cents": 600,
            },
        ),
    ],
)
def test_report_rejects_conflicting_producer_payload_and_subject_identity(
        tmp_path: Path, kind: str, payload: dict[str, int]):
    store = _seed_healthy_store(tmp_path)
    try:
        store.insert(
            "events",
            tick=1000,
            kind=kind,
            subject_type="firm",
            subject_id=999,
            payload_json=json.dumps(payload),
        )
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["unit_economics_validated"] is False
    assert report["evidence"]["unit_economics"]["producer_identity_mismatches"] == [
        {
            "event_id": 2,
            "kind": kind,
            "payload_firm_id": 1,
            "subject_id": 999,
            "tick": 1000,
        }
    ]


@pytest.mark.parametrize(
    ("event_tick", "reason", "mismatch_reason"),
    [
        (699, "market_exit", "bankruptcy_event_tick_mismatch"),
        (700, "", "missing_or_invalid_bankruptcy_reason"),
    ],
)
def test_bankrupt_recovery_goods_firm_requires_matching_tick_and_reason(
        tmp_path: Path, event_tick: int, reason: str, mismatch_reason: str):
    store = _seed_healthy_store(tmp_path)
    try:
        store.execute("UPDATE firms SET status='bankrupt', bankrupt_tick=700 WHERE id=1")
        store.insert(
            "events",
            tick=event_tick,
            kind="bankruptcy",
            subject_type="firm",
            subject_id=1,
            payload_json=json.dumps({"firm_id": 1, "reason": reason}),
        )
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["recovery_managed_insolvency_absent"] is False
    assert report["evidence"]["recovery_managed_insolvencies"]["state_mismatches"] == [
        {"firm_id": 1, "reason": mismatch_reason, "status": "bankrupt", "tick": 700}
    ]


@pytest.mark.parametrize("bankrupt_tick", [700.5, "not-a-tick"])
def test_bankrupt_recovery_goods_firm_rejects_a_noninteger_bankruptcy_tick(
        tmp_path: Path, bankrupt_tick: float | str):
    store = _seed_healthy_store(tmp_path)
    try:
        store.execute(
            "UPDATE firms SET status='bankrupt', bankrupt_tick=? WHERE id=1",
            (bankrupt_tick,),
        )
        store.insert(
            "events",
            tick=700,
            kind="bankruptcy",
            subject_type="firm",
            subject_id=1,
            payload_json=json.dumps({"firm_id": 1, "reason": "market_exit"}),
        )
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["recovery_managed_insolvency_absent"] is False
    assert report["evidence"]["recovery_managed_insolvencies"]["state_mismatches"] == [
        {
            "firm_id": 1,
            "reason": "missing_or_invalid_bankruptcy_tick",
            "status": "bankrupt",
            "tick": bankrupt_tick,
        }
    ]


@pytest.mark.parametrize(
    ("subject_mode", "mismatch_reason"),
    [
        ("unknown", "unknown_bankruptcy_subject_firm_id"),
        ("different_known", "bankruptcy_subject_identity_mismatch"),
    ],
)
def test_bankruptcy_event_rejects_nonmatching_payload_and_subject_identity(
        tmp_path: Path, subject_mode: str, mismatch_reason: str):
    store = _seed_healthy_store(tmp_path)
    try:
        subject_id = 999
        if subject_mode == "different_known":
            subject_id = store.insert(
                "firms",
                name="Known Different Subject Firm",
                sector="services",
                status="private",
                founded_tick=0,
                inventory=0,
                product_json=json.dumps({}),
            )
        store.execute("UPDATE firms SET status='bankrupt', bankrupt_tick=700 WHERE id=1")
        store.insert(
            "events",
            tick=700,
            kind="bankruptcy",
            subject_type="firm",
            subject_id=subject_id,
            payload_json=json.dumps({"firm_id": 1, "reason": "market_exit"}),
        )
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["recovery_managed_insolvency_absent"] is False
    assert report["evidence"]["recovery_managed_insolvencies"]["bankruptcy_identity_mismatches"] == [
        {
            "event_id": 2,
            "payload_firm_id": 1,
            "reason": mismatch_reason,
            "subject_id": subject_id,
            "tick": 700,
        }
    ]


def test_acquired_recovery_goods_firm_requires_matching_acquisition_event(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        acquired_firm_id = store.insert(
            "firms",
            name="Acquired Fixtures Co.",
            sector="manufacturing",
            status="acquired",
            founded_tick=0,
            inventory=0,
            product_json=json.dumps(
                {
                    "good": "acquired-fixtures",
                    "unit_price_cents": 600,
                    "base_input_cost_cents": 180,
                    "output_per_worker": 2,
                }
            ),
        )
        store.commit()

        without_event = evaluate_supply_recovery(store)
        store.insert(
            "events",
            tick=700,
            kind="merger_closed",
            subject_type="firm",
            subject_id=acquired_firm_id,
            payload_json=json.dumps(
                {"target_firm_id": acquired_firm_id, "acquirer_firm_id": 1}
            ),
        )
        store.commit()
        with_event = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert without_event["passed"] is False
    assert without_event["evidence"]["recovery_managed_insolvencies"]["state_mismatches"] == [
        {
            "firm_id": acquired_firm_id,
            "reason": "missing_matching_acquisition_event",
            "status": "acquired",
            "tick": None,
        }
    ]
    assert with_event["passed"] is True
    assert with_event["evidence"]["recovery_managed_insolvencies"]["permitted_departures"] == [
        {
            "firm_id": acquired_firm_id,
            "kind": "acquisition",
            "status": "acquired",
            "tick": 700,
        }
    ]


@pytest.mark.parametrize(
    ("include_acquirer", "acquirer_value", "invalid_reason"),
    [
        (False, None, "missing_or_invalid_acquirer_firm_id"),
        (True, "not-a-firm-id", "missing_or_invalid_acquirer_firm_id"),
        (True, 999, "unknown_acquirer_firm_id"),
    ],
)
def test_acquired_recovery_goods_firm_requires_a_known_acquirer(
        tmp_path: Path, include_acquirer: bool, acquirer_value: int | str | None,
        invalid_reason: str):
    store = _seed_healthy_store(tmp_path)
    try:
        acquired_firm_id = store.insert(
            "firms",
            name="Acquirer Validation Target",
            sector="manufacturing",
            status="acquired",
            founded_tick=0,
            inventory=0,
            product_json=json.dumps(
                {
                    "good": "acquirer-validation-target",
                    "unit_price_cents": 600,
                    "base_input_cost_cents": 180,
                    "output_per_worker": 2,
                }
            ),
        )
        payload: dict[str, object] = {"target_firm_id": acquired_firm_id}
        if include_acquirer:
            payload["acquirer_firm_id"] = acquirer_value
        store.insert(
            "events",
            tick=700,
            kind="merger_closed",
            subject_type="merger",
            subject_id=1,
            payload_json=json.dumps(payload),
        )
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["recovery_managed_insolvency_absent"] is False
    assert report["evidence"]["recovery_managed_insolvencies"]["invalid_merger_acquirers"] == [
        {
            "acquirer_firm_id": acquirer_value,
            "event_id": 2,
            "reason": invalid_reason,
            "tick": 700,
        }
    ]


@pytest.mark.parametrize("status", ["private", "listed"])
def test_merger_with_a_known_nonrecovery_acquirer_remains_valid(tmp_path: Path, status: str):
    store = _seed_healthy_store(tmp_path)
    try:
        acquirer_firm_id = store.insert(
            "firms",
            name="Known Nonrecovery Acquirer",
            sector="services",
            status=status,
            founded_tick=0,
            inventory=0,
            product_json=json.dumps({}),
        )
        acquired_firm_id = store.insert(
            "firms",
            name="Known Acquired Target",
            sector="manufacturing",
            status="acquired",
            founded_tick=0,
            inventory=0,
            product_json=json.dumps(
                {
                    "good": "known-acquired-target",
                    "unit_price_cents": 600,
                    "base_input_cost_cents": 180,
                    "output_per_worker": 2,
                }
            ),
        )
        store.insert(
            "events",
            tick=700,
            kind="merger_closed",
            subject_type="merger",
            subject_id=999,
            payload_json=json.dumps(
                {"target_firm_id": acquired_firm_id, "acquirer_firm_id": acquirer_firm_id}
            ),
        )
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is True
    assert report["evidence"]["recovery_managed_insolvencies"]["invalid_merger_acquirers"] == []


def _insert_nonrecovery_firm(
        store: Store, *, name: str, status: str, bankrupt_tick: object | None = None) -> int:
    return store.insert(
        "firms",
        name=name,
        sector="services",
        status=status,
        founded_tick=0,
        bankrupt_tick=bankrupt_tick,
        inventory=0,
        product_json=json.dumps({}),
    )


def _insert_merger_closed_event(
        store: Store, *, tick: int, target_firm_id: int, acquirer_firm_id: int) -> int:
    return store.insert(
        "events",
        tick=tick,
        kind="merger_closed",
        subject_type="merger",
        subject_id=999,
        payload_json=json.dumps(
            {"target_firm_id": target_firm_id, "acquirer_firm_id": acquirer_firm_id}
        ),
    )


@pytest.mark.parametrize("status", ["", "unknown"])
def test_merger_acquirer_requires_an_operating_status_at_close(tmp_path: Path, status: str):
    store = _seed_healthy_store(tmp_path)
    try:
        acquirer_firm_id = _insert_nonrecovery_firm(
            store, name="Unproven Acquirer", status=status)
        target_firm_id = _insert_nonrecovery_firm(
            store, name="Unproven Acquirer Target", status="acquired")
        event_id = _insert_merger_closed_event(
            store, tick=700, target_firm_id=target_firm_id, acquirer_firm_id=acquirer_firm_id)
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["recovery_managed_insolvency_absent"] is False
    assert report["evidence"]["recovery_managed_insolvencies"]["invalid_merger_acquirers"] == [
        {
            "acquirer_firm_id": acquirer_firm_id,
            "event_id": event_id,
            "reason": "acquirer_not_operating_at_merger",
            "status": status,
            "tick": 700,
        }
    ]


def test_merger_rejects_acquirer_bankruptcy_after_completed_horizon(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        acquirer_firm_id = _insert_nonrecovery_firm(
            store,
            name="Post-Horizon Bankrupt Acquirer",
            status="bankrupt",
            bankrupt_tick=1001,
        )
        target_firm_id = _insert_nonrecovery_firm(
            store, name="Post-Horizon Target", status="acquired")
        event_id = _insert_merger_closed_event(
            store, tick=700, target_firm_id=target_firm_id, acquirer_firm_id=acquirer_firm_id)
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["recovery_managed_insolvency_absent"] is False
    assert report["evidence"]["recovery_managed_insolvencies"]["invalid_merger_acquirers"] == [
        {
            "acquirer_firm_id": acquirer_firm_id,
            "event_id": event_id,
            "reason": "acquirer_terminal_status_after_completed_horizon",
            "terminal_kind": "bankruptcy",
            "terminal_tick": 1001,
            "tick": 700,
        }
    ]


def test_merger_acquirer_requires_ordered_same_tick_bankruptcy_evidence(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        acquirer_firm_id = _insert_nonrecovery_firm(
            store,
            name="Untimed Bankrupt Acquirer",
            status="bankrupt",
            bankrupt_tick=700,
        )
        target_firm_id = _insert_nonrecovery_firm(
            store, name="Untimed Bankrupt Target", status="acquired")
        event_id = _insert_merger_closed_event(
            store, tick=700, target_firm_id=target_firm_id, acquirer_firm_id=acquirer_firm_id)
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["recovery_managed_insolvency_absent"] is False
    assert report["evidence"]["recovery_managed_insolvencies"]["invalid_merger_acquirers"] == [
        {
            "acquirer_firm_id": acquirer_firm_id,
            "event_id": event_id,
            "reason": "acquirer_terminal_status_has_unprovable_timing",
            "terminal_kind": "bankruptcy",
            "terminal_tick": 700,
            "tick": 700,
        }
    ]


def test_merger_rejects_acquirer_with_non_strict_final_bankruptcy_tick(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        acquirer_firm_id = _insert_nonrecovery_firm(
            store,
            name="Fractional Bankrupt Acquirer",
            status="bankrupt",
            bankrupt_tick=700.5,
        )
        target_firm_id = _insert_nonrecovery_firm(
            store, name="Fractional Bankrupt Target", status="acquired")
        event_id = _insert_merger_closed_event(
            store, tick=700, target_firm_id=target_firm_id, acquirer_firm_id=acquirer_firm_id)
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["recovery_managed_insolvency_absent"] is False
    assert report["evidence"]["recovery_managed_insolvencies"]["invalid_merger_acquirers"] == [
        {
            "acquirer_firm_id": acquirer_firm_id,
            "event_id": event_id,
            "reason": "acquirer_terminal_status_has_invalid_tick",
            "terminal_kind": "bankruptcy",
            "terminal_tick": 700.5,
            "tick": 700,
        }
    ]


def test_same_tick_bankruptcy_before_merger_rejects_the_acquirer(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        acquirer_firm_id = _insert_nonrecovery_firm(
            store,
            name="Same-Tick Prior Bankrupt Acquirer",
            status="bankrupt",
            bankrupt_tick=700,
        )
        target_firm_id = _insert_nonrecovery_firm(
            store, name="Same-Tick Prior Bankrupt Target", status="acquired")
        bankruptcy_event_id = store.insert(
            "events",
            tick=700,
            kind="bankruptcy",
            subject_type="firm",
            subject_id=acquirer_firm_id,
            payload_json=json.dumps({"firm_id": acquirer_firm_id, "reason": "market_exit"}),
        )
        event_id = _insert_merger_closed_event(
            store, tick=700, target_firm_id=target_firm_id, acquirer_firm_id=acquirer_firm_id)
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["recovery_managed_insolvency_absent"] is False
    assert report["evidence"]["recovery_managed_insolvencies"]["invalid_merger_acquirers"] == [
        {
            "acquirer_firm_id": acquirer_firm_id,
            "event_id": event_id,
            "reason": "acquirer_terminal_before_merger",
            "terminal_event_id": bankruptcy_event_id,
            "terminal_kind": "bankruptcy",
            "terminal_tick": 700,
            "tick": 700,
        }
    ]


def test_same_tick_bankruptcy_after_merger_proves_the_acquirer_was_operating(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        acquirer_firm_id = _insert_nonrecovery_firm(
            store,
            name="Same-Tick Later Bankrupt Acquirer",
            status="bankrupt",
            bankrupt_tick=700,
        )
        target_firm_id = _insert_nonrecovery_firm(
            store, name="Same-Tick Later Bankrupt Target", status="acquired")
        _insert_merger_closed_event(
            store, tick=700, target_firm_id=target_firm_id, acquirer_firm_id=acquirer_firm_id)
        store.insert(
            "events",
            tick=700,
            kind="bankruptcy",
            subject_type="firm",
            subject_id=acquirer_firm_id,
            payload_json=json.dumps({"firm_id": acquirer_firm_id, "reason": "market_exit"}),
        )
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is True
    assert report["evidence"]["recovery_managed_insolvencies"]["invalid_merger_acquirers"] == []


@pytest.mark.parametrize("terminal_event_before_merger", [True, False])
def test_same_tick_acquisition_history_uses_persisted_event_order(
        tmp_path: Path, terminal_event_before_merger: bool):
    store = _seed_healthy_store(tmp_path)
    try:
        acquirer_firm_id = _insert_nonrecovery_firm(
            store, name="Same-Tick Acquired Acquirer", status="acquired")
        buyer_firm_id = _insert_nonrecovery_firm(
            store, name="Same-Tick Acquirer Buyer", status="private")
        target_firm_id = _insert_nonrecovery_firm(
            store, name="Same-Tick Acquisition Target", status="acquired")
        if terminal_event_before_merger:
            terminal_event_id = _insert_merger_closed_event(
                store,
                tick=700,
                target_firm_id=acquirer_firm_id,
                acquirer_firm_id=buyer_firm_id,
            )
            merger_event_id = _insert_merger_closed_event(
                store,
                tick=700,
                target_firm_id=target_firm_id,
                acquirer_firm_id=acquirer_firm_id,
            )
        else:
            merger_event_id = _insert_merger_closed_event(
                store,
                tick=700,
                target_firm_id=target_firm_id,
                acquirer_firm_id=acquirer_firm_id,
            )
            terminal_event_id = _insert_merger_closed_event(
                store,
                tick=700,
                target_firm_id=acquirer_firm_id,
                acquirer_firm_id=buyer_firm_id,
            )
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    if terminal_event_before_merger:
        assert report["passed"] is False
        assert report["checks"]["recovery_managed_insolvency_absent"] is False
        assert report["evidence"]["recovery_managed_insolvencies"]["invalid_merger_acquirers"] == [
            {
                "acquirer_firm_id": acquirer_firm_id,
                "event_id": merger_event_id,
                "reason": "acquirer_terminal_before_merger",
                "terminal_event_id": terminal_event_id,
                "terminal_kind": "merger_closed",
                "terminal_tick": 700,
                "tick": 700,
            }
        ]
    else:
        assert report["passed"] is True
        assert report["evidence"]["recovery_managed_insolvencies"]["invalid_merger_acquirers"] == []


@pytest.mark.parametrize(
    ("status", "bankrupt_tick"),
    [
        ("private", 600),
        ("listed", 600),
        ("private", 700.5),
        ("listed", 700.5),
        ("private", 1001),
        ("listed", 1001),
    ],
)
def test_merger_rejects_active_acquirer_with_any_bankruptcy_marker(
        tmp_path: Path, status: str, bankrupt_tick: object):
    store = _seed_healthy_store(tmp_path)
    try:
        acquirer_firm_id = _insert_nonrecovery_firm(
            store,
            name=f"{status.title()} Acquirer With Marker",
            status=status,
            bankrupt_tick=bankrupt_tick,
        )
        target_firm_id = _insert_nonrecovery_firm(
            store, name="Active Marker Target", status="acquired")
        event_id = _insert_merger_closed_event(
            store, tick=700, target_firm_id=target_firm_id, acquirer_firm_id=acquirer_firm_id)
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["recovery_managed_insolvency_absent"] is False
    assert report["evidence"]["recovery_managed_insolvencies"]["invalid_merger_acquirers"] == [
        {
            "acquirer_firm_id": acquirer_firm_id,
            "bankrupt_tick": bankrupt_tick,
            "event_id": event_id,
            "reason": "acquirer_nonbankrupt_status_has_bankrupt_tick",
            "status": status,
            "tick": 700,
        }
    ]


def test_merger_rejects_acquired_acquirer_with_a_bankruptcy_marker(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        acquirer_firm_id = _insert_nonrecovery_firm(
            store,
            name="Acquired Acquirer With Marker",
            status="acquired",
            bankrupt_tick=600,
        )
        buyer_firm_id = _insert_nonrecovery_firm(
            store, name="Acquired Marker Buyer", status="private")
        target_firm_id = _insert_nonrecovery_firm(
            store, name="Acquired Marker Target", status="acquired")
        event_id = _insert_merger_closed_event(
            store, tick=700, target_firm_id=target_firm_id, acquirer_firm_id=acquirer_firm_id)
        _insert_merger_closed_event(
            store, tick=800, target_firm_id=acquirer_firm_id, acquirer_firm_id=buyer_firm_id)
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["recovery_managed_insolvency_absent"] is False
    assert report["evidence"]["recovery_managed_insolvencies"]["invalid_merger_acquirers"] == [
        {
            "acquirer_firm_id": acquirer_firm_id,
            "bankrupt_tick": 600,
            "event_id": event_id,
            "reason": "acquirer_nonbankrupt_status_has_bankrupt_tick",
            "status": "acquired",
            "tick": 700,
        }
    ]


def test_only_invalid_relative_checkpoint_tick_keeps_raw_exclusion_evidence(tmp_path: Path):
    store = _seed_healthy_store(tmp_path, checkpoint_dir="relative-checkpoints")
    try:
        store.execute("DELETE FROM checkpoints WHERE tick=1000")
        store.execute("UPDATE checkpoints SET tick=900.5 WHERE tick=900")
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["checkpoint_retention"] is False
    assert report["evidence"]["checkpoints"]["excluded_rows"] == [
        {"checkpoint_id": 1, "raw_tick": 900.5, "reason": "invalid_tick"}
    ]
    assert report["evidence"]["checkpoints"]["error"] == (
        "checkpoint directory cannot be reconstructed from persisted rows"
    )


def test_acquired_recovery_goods_firm_rejects_a_bankruptcy_tick(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        acquired_firm_id = store.insert(
            "firms",
            name="Contradictory Acquired Fixtures Co.",
            sector="manufacturing",
            status="acquired",
            founded_tick=0,
            bankrupt_tick=700,
            inventory=0,
            product_json=json.dumps(
                {
                    "good": "contradictory-acquired-fixtures",
                    "unit_price_cents": 600,
                    "base_input_cost_cents": 180,
                    "output_per_worker": 2,
                }
            ),
        )
        store.insert(
            "events",
            tick=700,
            kind="merger_closed",
            subject_type="merger",
            subject_id=1,
            payload_json=json.dumps(
                {"target_firm_id": acquired_firm_id, "acquirer_firm_id": 1}
            ),
        )
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["recovery_managed_insolvency_absent"] is False
    assert report["evidence"]["recovery_managed_insolvencies"]["state_mismatches"] == [
        {
            "firm_id": acquired_firm_id,
            "reason": "acquired_status_has_bankrupt_tick",
            "status": "acquired",
            "tick": 700,
        }
    ]


@pytest.mark.parametrize(
    ("kind", "payload"),
    [
        ("bankruptcy", {"firm_id": 999, "reason": "market_exit"}),
        ("merger_closed", {"target_firm_id": 999, "acquirer_firm_id": 1}),
        ("merger_closed", {"target_firm_id": 1, "acquirer_firm_id": 999}),
    ],
)
def test_report_rejects_orphan_terminal_event_identity(
        tmp_path: Path, kind: str, payload: dict[str, int | str]):
    store = _seed_healthy_store(tmp_path)
    try:
        store.insert(
            "events",
            tick=700,
            kind=kind,
            subject_type="firm" if kind == "bankruptcy" else "merger",
            subject_id=999 if kind == "bankruptcy" else 1,
            payload_json=json.dumps(payload),
        )
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["recovery_managed_insolvency_absent"] is False
    assert report["evidence"]["recovery_managed_insolvencies"]["orphan_terminal_events"] == [
        {"event_id": 2, "firm_id": 999, "kind": kind, "tick": 700}
    ]


def test_terminal_event_for_a_known_nonrecovery_firm_remains_valid(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        nonrecovery_firm_id = store.insert(
            "firms",
            name="Known Nonrecovery Firm",
            sector="services",
            status="bankrupt",
            founded_tick=0,
            bankrupt_tick=700,
            inventory=0,
            product_json=json.dumps({}),
        )
        store.insert(
            "events",
            tick=700,
            kind="bankruptcy",
            subject_type="firm",
            subject_id=nonrecovery_firm_id,
            payload_json=json.dumps({"firm_id": nonrecovery_firm_id, "reason": "market_exit"}),
        )
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is True
    assert report["evidence"]["recovery_managed_insolvencies"]["orphan_terminal_events"] == []


def test_checkpoint_artifact_requires_a_canonical_matching_runtime_manifest(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    checkpoint = _checkpoint_path(tmp_path, 900)
    manifest = checkpoint_manifest_path(checkpoint)
    try:
        persisted = json.loads(manifest.read_text(encoding="utf-8"))
        persisted["kind"] = "not_a_runtime_checkpoint"
        manifest.write_bytes(canonical_json_bytes(persisted))
        tampered = evaluate_supply_recovery(store)

        write_checkpoint_manifest(checkpoint)
        persisted = json.loads(manifest.read_text(encoding="utf-8"))
        manifest.write_text(json.dumps(persisted, indent=4) + "\n", encoding="utf-8")
        noncanonical = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert tampered["passed"] is False
    assert tampered["checks"]["checkpoint_retention"] is False
    assert tampered["evidence"]["checkpoints"]["current_rows"][0]["manifest_valid"] is False
    assert noncanonical["passed"] is False
    assert noncanonical["checks"]["checkpoint_retention"] is False


def test_checkpoint_artifact_rejects_arbitrary_bytes_and_empty_manifest(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    checkpoint = _checkpoint_path(tmp_path, 900)
    try:
        checkpoint.write_bytes(b"not a SQLite database")
        checkpoint_manifest_path(checkpoint).write_bytes(canonical_json_bytes({}))
        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["checkpoint_retention"] is False
    assert report["evidence"]["checkpoints"]["current_rows"][0]["manifest_valid"] is False


def test_relative_checkpoint_config_is_db_relative_and_receipts_do_not_leak_absolute_paths(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = _seed_healthy_store(tmp_path, checkpoint_dir="relative-checkpoints")
    other_cwd = tmp_path / "unrelated-cwd"
    other_cwd.mkdir()
    try:
        monkeypatch.chdir(other_cwd)
        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    rendered = render_supply_recovery_markdown(report)
    serialized = json.dumps(report, sort_keys=True)
    assert report["passed"] is True
    assert report["evidence"]["checkpoints"]["configured_checkpoint_dir"] == "relative-checkpoints"
    assert str(tmp_path.resolve()) not in serialized
    assert str(tmp_path.resolve()) not in rendered


def test_report_fails_closed_when_unemployment_rebounds_thirteen_points(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        store.execute(
            "UPDATE metrics SET value = ? WHERE name = ? AND tick BETWEEN ? AND ?",
            (0.55, "unemployment", 300, 359),
        )
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["unemployment_rebound_within_10pp"] is False
    assert report["evidence"]["unemployment"]["worst_window"]["rebound"] == 0.13
    assert report["evidence"]["unemployment"]["latest_window"]["rebound"] == 0.03


def test_report_compares_unrounded_unemployment_rebound_to_the_threshold(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        store.execute(
            "UPDATE metrics SET value = ? WHERE name = ? AND tick BETWEEN ? AND ?",
            (0.5200004, "unemployment", 300, 359),
        )
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    worst_window = report["evidence"]["unemployment"]["worst_window"]
    assert report["passed"] is False
    assert report["checks"]["unemployment_rebound_within_10pp"] is False
    assert worst_window["rebound"] == 0.1
    assert worst_window["raw_rebound"] == pytest.approx(0.1000004)


def test_report_accepts_the_completed_headless_paused_boundary(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        store.set_meta(status="paused", active_tick=None)
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is True
    assert report["checks"]["horizon_completed"] is True
    assert report["evidence"]["horizon"]["headless_horizon_boundary"] is True


def test_report_rejects_a_partial_paused_tick(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        store.set_meta(status="paused", active_tick=1000)
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["horizon_completed"] is False


def test_report_fails_when_a_historical_purchase_window_exceeds_five_percent(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        for proposal_id in range(1, 5):
            store.execute(
                "UPDATE action_proposals SET validation_status = ?, result_json = ? WHERE id = ?",
                ("rejected", json.dumps({"ok": False}), proposal_id),
            )
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["buy_goods_rejection_rate_within_5pct"] is False
    assert report["evidence"]["buy_goods_rejection"]["worst_window"]["rate"] > 0.05
    assert report["evidence"]["buy_goods_rejection"]["latest_window"]["rate"] == 0


def test_purchase_gate_compares_unrounded_rate_to_the_threshold(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = _seed_healthy_store(tmp_path)
    try:
        store.execute("DELETE FROM action_proposals")
        for tick, status in ((60, "accepted"), (61, "accepted"), (62, "rejected")):
            store.insert(
                "action_proposals",
                tick=tick,
                actor_id=1,
                action_type="buy_goods",
                payload_json="{}",
                validation_status=status,
                result_json=json.dumps({"ok": status == "accepted"}),
            )
        store.commit()
        monkeypatch.setitem(
            supply_recovery_report._THRESHOLDS,
            "max_buy_goods_rejection_rate",
            0.3333333,
        )

        passed, evidence = supply_recovery_report._buy_goods_evidence(store, 119)
    finally:
        _close(store)

    assert passed is False
    assert evidence["latest_window"]["rate"] == 0.333333
    assert evidence["latest_window"]["raw_rate"] == pytest.approx(1 / 3)


def test_report_fails_for_recovery_managed_goods_firm_insolvency(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        store.insert(
            "events",
            tick=1000,
            kind="bankruptcy",
            subject_type="firm",
            subject_id=1,
            payload_json=json.dumps({"firm_id": 1, "reason": "insolvency"}),
        )
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["recovery_managed_insolvency_absent"] is False
    assert (report["evidence"]["recovery_managed_insolvencies"]
            ["recovery_managed_insolvencies"][0]["firm_id"] == 1)


def test_historical_noninsolvency_goods_firm_does_not_require_active_wage_evidence(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        retired_firm_id = store.insert(
            "firms",
            name="Historical Goods Co.",
            sector="manufacturing",
            status="bankrupt",
            founded_tick=0,
            bankrupt_tick=700,
            inventory=0,
            product_json=json.dumps(
                {
                    "good": "historical-fixtures",
                    "unit_price_cents": 600,
                    "base_input_cost_cents": 180,
                    "output_per_worker": 2,
                }
            ),
        )
        store.insert(
            "events",
            tick=700,
            kind="bankruptcy",
            subject_type="firm",
            subject_id=retired_firm_id,
            payload_json=json.dumps({"firm_id": retired_firm_id, "reason": "market_exit"}),
        )
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is True
    assert report["checks"]["unit_economics_validated"] is True
    assert report["checks"]["recovery_managed_insolvency_absent"] is True
    assert report["evidence"]["unit_economics"]["excluded_historical_goods_firms"] == [
        {"firm_id": retired_firm_id, "status": "bankrupt"}
    ]


def test_report_fails_for_pending_labor_backlog(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        job_id = store.insert(
            "jobs",
            tick=1000,
            firm_id=1,
            title="Fixture worker",
            wage_cents=15000,
            status="open",
        )
        for agent_id in range(2, 23):
            store.insert(
                "applications",
                tick=1000,
                job_id=job_id,
                agent_id=agent_id,
                state="pending",
            )
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["labor_backlog_bounded"] is False
    assert report["evidence"]["labor_backlog"]["pending_applications"] == 21


def test_report_fails_for_bad_ledger_and_checkpoint_retention(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        store.insert(
            "accounts",
            owner_type="firm",
            owner_id=999,
            kind="checking",
            balance_cents=1,
        )
        checkpoint_dir = Path(_config(tmp_path)["checkpoint_dir"])
        extra = checkpoint_dir / f"{RUN_ID}_t800.db"
        extra.write_bytes(b"extra checkpoint")
        Path(f"{extra}.manifest.json").write_text("{}\n", encoding="utf-8")
        store.insert("checkpoints", tick=800, path=str(extra))
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["ledger_reconciled"] is False
    assert report["checks"]["checkpoint_retention"] is False


def test_report_fails_for_sqlite_foreign_key_integrity_error(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        store.commit()
        store.execute("PRAGMA foreign_keys = OFF")
        store.insert(
            "ledger_entries",
            tick=1000,
            txn_id=999999,
            account_id=999999,
            delta_cents=1,
        )
        store.commit()
        store.execute("PRAGMA foreign_keys = ON")

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["sqlite_integrity"] is False
    assert report["evidence"]["sqlite_integrity"]["foreign_key_check"]


def test_cli_writes_no_receipt_by_default_and_writes_json_and_markdown_on_request(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    db_path = Path(store.path)
    _close(store)
    environment = {
        **os.environ,
        "AGENT_ECONOMY_LOG_FILE": str(tmp_path / "unexpected-operational.jsonl"),
    }
    before_default = _files_under(tmp_path)

    default_result = subprocess.run(
        [sys.executable, str(ROOT / "run.py"), "--supply-recovery-report", str(db_path)],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert default_result.returncode == 0, default_result.stderr
    assert json.loads(default_result.stdout)["passed"] is True
    assert _files_under(tmp_path) == before_default
    assert str(tmp_path.resolve()) not in default_result.stdout

    output = tmp_path / "receipt"
    before_explicit = _files_under(tmp_path)
    explicit_result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "run.py"),
            "--supply-recovery-report",
            str(db_path),
            "--output",
            str(output),
        ],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert explicit_result.returncode == 0, explicit_result.stderr
    assert json.loads(explicit_result.stdout)["passed"] is True
    assert (tmp_path / "receipt.json").is_file()
    assert (tmp_path / "receipt.md").is_file()
    assert _files_under(tmp_path) - before_explicit == {
        Path("receipt.json"),
        Path("receipt.md"),
    }
    assert str(tmp_path.resolve()) not in explicit_result.stdout
    assert str(tmp_path.resolve()) not in (tmp_path / "receipt.json").read_text(encoding="utf-8")
    assert str(tmp_path.resolve()) not in (tmp_path / "receipt.md").read_text(encoding="utf-8")


def test_cli_returns_nonzero_for_a_nonpassing_receipt(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    db_path = Path(store.path)
    store.execute("DELETE FROM metrics WHERE name = ?", ("unemployment",))
    store.commit()
    _close(store)

    result = subprocess.run(
        [sys.executable, "run.py", "--supply-recovery-report", str(db_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert json.loads(result.stdout)["passed"] is False


def test_cli_rejects_run_modifiers_for_a_persisted_evidence_receipt(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    db_path = Path(store.path)
    _close(store)

    result = subprocess.run(
        [
            sys.executable,
            "run.py",
            "--supply-recovery-report",
            str(db_path),
            "--ticks",
            "1",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "only accepts --output" in result.stderr


@pytest.mark.parametrize("completed_tick", [1000.5, "not-a-tick"])
def test_completed_run_tick_requires_a_strict_persisted_integer(
        tmp_path: Path, completed_tick: float | str):
    store = _seed_healthy_store(tmp_path)
    try:
        store.set_meta(tick=completed_tick)
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["horizon_completed"] is False
    assert report["evidence"]["horizon"]["invalid_completed_tick"] == completed_tick


def test_fractional_metric_tick_fails_instead_of_truncating(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        metric_id = store.query_one(
            "SELECT id FROM metrics WHERE name='unemployment' AND tick=700"
        )["id"]
        store.execute("UPDATE metrics SET tick=700.5 WHERE id=?", (metric_id,))
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["unemployment_rebound_within_10pp"] is False
    assert report["evidence"]["unemployment"]["invalid_metric_ticks"] == [
        {"metric_id": metric_id, "tick": 700.5}
    ]


def test_fractional_proposal_tick_fails_instead_of_truncating(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        proposal_id = store.query_one(
            "SELECT id FROM action_proposals WHERE action_type='buy_goods' AND tick=700"
        )["id"]
        store.execute("UPDATE action_proposals SET tick=700.5 WHERE id=?", (proposal_id,))
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["buy_goods_rejection_rate_within_5pct"] is False
    assert report["evidence"]["buy_goods_rejection"]["invalid_proposal_ticks"] == [
        {"proposal_id": proposal_id, "tick": 700.5}
    ]


def test_fractional_producer_event_tick_fails_instead_of_truncating(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        store.execute("UPDATE events SET tick=1000.5 WHERE kind='production'")
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["unit_economics_validated"] is False
    assert report["evidence"]["unit_economics"]["malformed_producer_events"] == [
        {"event_id": 1, "firm_id": 1, "kind": "production", "tick": 1000.5}
    ]


def test_fractional_terminal_event_tick_fails_instead_of_truncating(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        store.execute("UPDATE firms SET status='bankrupt', bankrupt_tick=700 WHERE id=1")
        store.insert(
            "events",
            tick=700.5,
            kind="bankruptcy",
            subject_type="firm",
            subject_id=1,
            payload_json=json.dumps({"firm_id": 1, "reason": "market_exit"}),
        )
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["checks"]["recovery_managed_insolvency_absent"] is False
    assert report["evidence"]["recovery_managed_insolvencies"]["invalid_terminal_event_ticks"] == [
        {"event_id": 2, "kind": "bankruptcy", "tick": 700.5}
    ]


def test_fractional_checkpoint_tick_fails_instead_of_truncating(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        store.execute("UPDATE checkpoints SET tick=900.5 WHERE tick=900")
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["checkpoint_retention"] is False
    assert report["evidence"]["checkpoints"]["excluded_rows"] == [
        {"checkpoint_id": 1, "raw_tick": 900.5, "reason": "invalid_tick"}
    ]


def test_producer_evidence_after_completed_horizon_is_rejected(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        store.execute("UPDATE events SET tick=2000 WHERE kind='production'")
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["unit_economics_validated"] is False
    assert report["evidence"]["unit_economics"]["producer_events_after_completed_horizon"] == [
        {"event_id": 1, "firm_id": 1, "kind": "production", "tick": 2000}
    ]


def test_bankruptcy_state_and_event_after_completed_horizon_are_rejected(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        store.execute("UPDATE firms SET status='bankrupt', bankrupt_tick=2000 WHERE id=1")
        store.insert(
            "events",
            tick=2000,
            kind="bankruptcy",
            subject_type="firm",
            subject_id=1,
            payload_json=json.dumps({"firm_id": 1, "reason": "market_exit"}),
        )
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    insolvency = report["evidence"]["recovery_managed_insolvencies"]
    assert report["checks"]["recovery_managed_insolvency_absent"] is False
    assert insolvency["terminal_events_after_completed_horizon"] == [
        {"event_id": 2, "firm_id": 1, "kind": "bankruptcy", "tick": 2000}
    ]
    assert {
        "firm_id": 1,
        "reason": "bankruptcy_tick_after_completed_horizon",
        "status": "bankrupt",
        "tick": 2000,
    } in insolvency["state_mismatches"]


def test_merger_after_completed_horizon_is_rejected(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        acquired_firm_id = store.insert(
            "firms",
            name="Future Acquired Fixtures Co.",
            sector="manufacturing",
            status="acquired",
            founded_tick=0,
            inventory=0,
            product_json=json.dumps(
                {
                    "good": "future-acquired-fixtures",
                    "unit_price_cents": 600,
                    "base_input_cost_cents": 180,
                    "output_per_worker": 2,
                }
            ),
        )
        store.insert(
            "events",
            tick=2000,
            kind="merger_closed",
            subject_type="merger",
            subject_id=999,
            payload_json=json.dumps(
                {"target_firm_id": acquired_firm_id, "acquirer_firm_id": 1}
            ),
        )
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["recovery_managed_insolvency_absent"] is False
    assert report["evidence"]["recovery_managed_insolvencies"]["terminal_events_after_completed_horizon"] == [
        {"event_id": 2, "firm_id": acquired_firm_id, "kind": "merger_closed", "tick": 2000}
    ]


def test_producer_subject_fallback_requires_a_firm_subject_type(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        store.execute("DELETE FROM events WHERE kind='production'")
        event_id = store.insert(
            "events",
            tick=1000,
            kind="production",
            subject_type="agent",
            subject_id=1,
            payload_json=json.dumps({"units": 2, "unit_cost_cents": 180}),
        )
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["unit_economics_validated"] is False
    assert report["evidence"]["unit_economics"]["invalid_producer_subject_fallbacks"] == [
        {
            "event_id": event_id,
            "kind": "production",
            "reason": "subject_fallback_requires_firm_subject_type",
            "subject_id": 1,
            "subject_type": "agent",
            "tick": 1000,
        }
    ]


def test_bankruptcy_subject_fallback_requires_a_firm_subject_type(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        store.execute("UPDATE firms SET status='bankrupt', bankrupt_tick=700 WHERE id=1")
        store.insert(
            "events",
            tick=700,
            kind="bankruptcy",
            subject_type="agent",
            subject_id=1,
            payload_json=json.dumps({"reason": "market_exit"}),
        )
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["checks"]["recovery_managed_insolvency_absent"] is False
    assert report["evidence"]["recovery_managed_insolvencies"]["invalid_bankruptcy_subject_fallbacks"] == [
        {
            "event_id": 2,
            "reason": "subject_fallback_requires_firm_subject_type",
            "subject_id": 1,
            "subject_type": "agent",
            "tick": 700,
        }
    ]


def test_bankruptcy_payload_identity_remains_valid_without_a_subject(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        store.execute("UPDATE firms SET status='bankrupt', bankrupt_tick=700 WHERE id=1")
        store.insert(
            "events",
            tick=700,
            kind="bankruptcy",
            subject_type=None,
            subject_id=None,
            payload_json=json.dumps({"firm_id": 1, "reason": "market_exit"}),
        )
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["checks"]["recovery_managed_insolvency_absent"] is True
    assert report["evidence"]["recovery_managed_insolvencies"]["invalid_bankruptcy_subject_fallbacks"] == []


def test_merger_rejects_self_acquisition(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        acquired_firm_id = store.insert(
            "firms",
            name="Self Acquired Fixtures Co.",
            sector="manufacturing",
            status="acquired",
            founded_tick=0,
            inventory=0,
            product_json=json.dumps(
                {
                    "good": "self-acquired-fixtures",
                    "unit_price_cents": 600,
                    "base_input_cost_cents": 180,
                    "output_per_worker": 2,
                }
            ),
        )
        store.insert(
            "events",
            tick=700,
            kind="merger_closed",
            subject_type="merger",
            subject_id=999,
            payload_json=json.dumps(
                {"target_firm_id": acquired_firm_id, "acquirer_firm_id": acquired_firm_id}
            ),
        )
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["recovery_managed_insolvency_absent"] is False
    assert report["evidence"]["recovery_managed_insolvencies"]["invalid_merger_acquirers"] == [
        {
            "acquirer_firm_id": acquired_firm_id,
            "event_id": 2,
            "reason": "self_acquisition",
            "target_firm_id": acquired_firm_id,
            "tick": 700,
        }
    ]


def test_merger_rejects_an_acquirer_terminal_before_close(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        acquirer_firm_id = store.insert(
            "firms",
            name="Already Bankrupt Acquirer",
            sector="services",
            status="bankrupt",
            founded_tick=0,
            bankrupt_tick=600,
            inventory=0,
            product_json=json.dumps({}),
        )
        acquired_firm_id = store.insert(
            "firms",
            name="Target of Invalid Acquirer",
            sector="manufacturing",
            status="acquired",
            founded_tick=0,
            inventory=0,
            product_json=json.dumps(
                {
                    "good": "invalid-acquirer-target",
                    "unit_price_cents": 600,
                    "base_input_cost_cents": 180,
                    "output_per_worker": 2,
                }
            ),
        )
        store.insert(
            "events",
            tick=600,
            kind="bankruptcy",
            subject_type="firm",
            subject_id=acquirer_firm_id,
            payload_json=json.dumps({"firm_id": acquirer_firm_id, "reason": "market_exit"}),
        )
        store.insert(
            "events",
            tick=700,
            kind="merger_closed",
            subject_type="merger",
            subject_id=999,
            payload_json=json.dumps(
                {"target_firm_id": acquired_firm_id, "acquirer_firm_id": acquirer_firm_id}
            ),
        )
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["recovery_managed_insolvency_absent"] is False
    assert report["evidence"]["recovery_managed_insolvencies"]["invalid_merger_acquirers"] == [
        {
            "acquirer_firm_id": acquirer_firm_id,
            "event_id": 3,
            "reason": "acquirer_terminal_before_merger",
            "terminal_event_id": 2,
            "terminal_kind": "bankruptcy",
            "terminal_tick": 600,
            "tick": 700,
        }
    ]


def test_merger_acquirer_terminal_after_close_remains_valid(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        acquirer_firm_id = store.insert(
            "firms",
            name="Later Bankrupt Acquirer",
            sector="services",
            status="bankrupt",
            founded_tick=0,
            bankrupt_tick=800,
            inventory=0,
            product_json=json.dumps({}),
        )
        acquired_firm_id = store.insert(
            "firms",
            name="Target of Valid Historical Acquirer",
            sector="manufacturing",
            status="acquired",
            founded_tick=0,
            inventory=0,
            product_json=json.dumps(
                {
                    "good": "valid-acquirer-target",
                    "unit_price_cents": 600,
                    "base_input_cost_cents": 180,
                    "output_per_worker": 2,
                }
            ),
        )
        store.insert(
            "events",
            tick=700,
            kind="merger_closed",
            subject_type="merger",
            subject_id=999,
            payload_json=json.dumps(
                {"target_firm_id": acquired_firm_id, "acquirer_firm_id": acquirer_firm_id}
            ),
        )
        store.insert(
            "events",
            tick=800,
            kind="bankruptcy",
            subject_type="firm",
            subject_id=acquirer_firm_id,
            payload_json=json.dumps({"firm_id": acquirer_firm_id, "reason": "market_exit"}),
        )
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is True
    assert report["evidence"]["recovery_managed_insolvencies"]["invalid_merger_acquirers"] == []


def test_merger_rejects_an_acquired_acquirer_without_terminal_timing(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        acquirer_firm_id = store.insert(
            "firms",
            name="Acquired Acquirer Without Evidence",
            sector="services",
            status="acquired",
            founded_tick=0,
            inventory=0,
            product_json=json.dumps({}),
        )
        acquired_firm_id = store.insert(
            "firms",
            name="Target of Untimed Acquired Acquirer",
            sector="manufacturing",
            status="acquired",
            founded_tick=0,
            inventory=0,
            product_json=json.dumps(
                {
                    "good": "untimed-acquired-acquirer-target",
                    "unit_price_cents": 600,
                    "base_input_cost_cents": 180,
                    "output_per_worker": 2,
                }
            ),
        )
        store.insert(
            "events",
            tick=700,
            kind="merger_closed",
            subject_type="merger",
            subject_id=999,
            payload_json=json.dumps(
                {"target_firm_id": acquired_firm_id, "acquirer_firm_id": acquirer_firm_id}
            ),
        )
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["recovery_managed_insolvency_absent"] is False
    assert report["evidence"]["recovery_managed_insolvencies"]["invalid_merger_acquirers"] == [
        {
            "acquirer_firm_id": acquirer_firm_id,
            "event_id": 2,
            "reason": "acquirer_terminal_status_has_unprovable_timing",
            "terminal_kind": "merger_closed",
            "terminal_tick": None,
            "tick": 700,
        }
    ]


def test_merger_rejects_an_acquirer_acquired_before_close(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        acquirer_firm_id = store.insert(
            "firms",
            name="Previously Acquired Acquirer",
            sector="services",
            status="acquired",
            founded_tick=0,
            inventory=0,
            product_json=json.dumps({}),
        )
        prior_buyer_firm_id = store.insert(
            "firms",
            name="Prior Buyer of Acquirer",
            sector="services",
            status="private",
            founded_tick=0,
            inventory=0,
            product_json=json.dumps({}),
        )
        acquired_firm_id = store.insert(
            "firms",
            name="Target of Previously Acquired Acquirer",
            sector="manufacturing",
            status="acquired",
            founded_tick=0,
            inventory=0,
            product_json=json.dumps(
                {
                    "good": "previously-acquired-acquirer-target",
                    "unit_price_cents": 600,
                    "base_input_cost_cents": 180,
                    "output_per_worker": 2,
                }
            ),
        )
        store.insert(
            "events",
            tick=600,
            kind="merger_closed",
            subject_type="merger",
            subject_id=100,
            payload_json=json.dumps(
                {"target_firm_id": acquirer_firm_id, "acquirer_firm_id": prior_buyer_firm_id}
            ),
        )
        store.insert(
            "events",
            tick=700,
            kind="merger_closed",
            subject_type="merger",
            subject_id=101,
            payload_json=json.dumps(
                {"target_firm_id": acquired_firm_id, "acquirer_firm_id": acquirer_firm_id}
            ),
        )
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is False
    assert report["checks"]["recovery_managed_insolvency_absent"] is False
    assert report["evidence"]["recovery_managed_insolvencies"]["invalid_merger_acquirers"] == [
        {
            "acquirer_firm_id": acquirer_firm_id,
            "event_id": 3,
            "reason": "acquirer_terminal_before_merger",
            "terminal_event_id": 2,
            "terminal_kind": "merger_closed",
            "terminal_tick": 600,
            "tick": 700,
        }
    ]


def test_merger_acquirer_acquired_after_close_remains_valid(tmp_path: Path):
    store = _seed_healthy_store(tmp_path)
    try:
        acquirer_firm_id = store.insert(
            "firms",
            name="Later Acquired Acquirer",
            sector="services",
            status="acquired",
            founded_tick=0,
            inventory=0,
            product_json=json.dumps({}),
        )
        later_buyer_firm_id = store.insert(
            "firms",
            name="Later Buyer of Acquirer",
            sector="services",
            status="private",
            founded_tick=0,
            inventory=0,
            product_json=json.dumps({}),
        )
        acquired_firm_id = store.insert(
            "firms",
            name="Target of Later Acquired Acquirer",
            sector="manufacturing",
            status="acquired",
            founded_tick=0,
            inventory=0,
            product_json=json.dumps(
                {
                    "good": "later-acquired-acquirer-target",
                    "unit_price_cents": 600,
                    "base_input_cost_cents": 180,
                    "output_per_worker": 2,
                }
            ),
        )
        store.insert(
            "events",
            tick=700,
            kind="merger_closed",
            subject_type="merger",
            subject_id=100,
            payload_json=json.dumps(
                {"target_firm_id": acquired_firm_id, "acquirer_firm_id": acquirer_firm_id}
            ),
        )
        store.insert(
            "events",
            tick=800,
            kind="merger_closed",
            subject_type="merger",
            subject_id=101,
            payload_json=json.dumps(
                {"target_firm_id": acquirer_firm_id, "acquirer_firm_id": later_buyer_firm_id}
            ),
        )
        store.commit()

        report = evaluate_supply_recovery(store)
    finally:
        _close(store)

    assert report["passed"] is True
    assert report["evidence"]["recovery_managed_insolvencies"]["invalid_merger_acquirers"] == []

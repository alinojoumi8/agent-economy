"""Persisted-evidence acceptance coverage for the supply-recovery profile."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from engine.store import Store
from reports.supply_recovery import evaluate_supply_recovery
from run_config import load_config


ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "supply-recovery-fixture"


def _config(tmp_path: Path) -> dict:
    return {
        "llm": {"default_route": {"provider": "scripted", "model": "scripted"}, "routes": {}},
        "checkpoint_dir": str((tmp_path / "checkpoints").resolve()),
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


def _seed_healthy_store(tmp_path: Path) -> Store:
    db_path = tmp_path / "supply-recovery.db"
    store = Store(str(db_path))
    config = _config(tmp_path)
    store.init_run_meta(RUN_ID, 17, config)
    store.set_meta(status="finished", tick=1000)

    firm_id = store.insert(
        "firms",
        name="Fixture Goods Co.",
        sector="manufacturing",
        status="active",
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
        subject_type="firm",
        subject_id=firm_id,
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

    checkpoint_dir = Path(config["checkpoint_dir"])
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    for tick in (900, 1000):
        checkpoint_path = checkpoint_dir / f"{RUN_ID}_t{tick}.db"
        checkpoint_path.write_bytes(b"fixture checkpoint")
        Path(f"{checkpoint_path}.manifest.json").write_text("{}\n", encoding="utf-8")
        store.insert("checkpoints", tick=tick, path=str(checkpoint_path))

    store.commit()
    return store


def _close(store: Store) -> None:
    store.commit()
    store.close()


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

    default_result = subprocess.run(
        [sys.executable, "run.py", "--supply-recovery-report", str(db_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert default_result.returncode == 0, default_result.stderr
    assert json.loads(default_result.stdout)["passed"] is True
    assert not list(tmp_path.glob("receipt.*"))

    output = tmp_path / "receipt"
    explicit_result = subprocess.run(
        [
            sys.executable,
            "run.py",
            "--supply-recovery-report",
            str(db_path),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert explicit_result.returncode == 0, explicit_result.stderr
    assert json.loads(explicit_result.stdout)["passed"] is True
    assert (tmp_path / "receipt.json").is_file()
    assert (tmp_path / "receipt.md").is_file()


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


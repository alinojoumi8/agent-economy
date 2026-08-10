from __future__ import annotations

import json
from pathlib import Path

import pytest

from run_config import load_config
from scripts.run_scale_validation import (
    ReceiptSafetyError,
    ValidationInputError,
    prepare_validation_config,
    run_validation,
    validate_receipt_safety,
)


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
REHEARSAL = RUNS / "scale-270-rehearsal.yaml"
MINIMAX = RUNS / "scale-270-minimax-live.yaml"


@pytest.mark.parametrize("ticks", (0, -1, True))
def test_prepare_validation_rejects_non_positive_ticks(tmp_path, ticks):
    with pytest.raises(ValidationInputError, match="ticks must be a positive integer"):
        prepare_validation_config(
            REHEARSAL,
            ticks=ticks,
            output_dir=tmp_path / "output",
            data_dir=tmp_path / "runs",
            approve_live=False,
        )


def test_prepare_validation_rejects_profile_outside_runs(tmp_path):
    outside = tmp_path / "copied-profile.yaml"
    outside.write_text(REHEARSAL.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(ValidationInputError, match="maintained profile beneath runs"):
        prepare_validation_config(
            outside,
            ticks=1,
            output_dir=tmp_path / "output",
            data_dir=tmp_path / "runs",
            approve_live=False,
        )


def test_prepare_validation_enforces_live_approval_matrix(tmp_path):
    with pytest.raises(ValidationInputError, match="requires --approve-live-inference"):
        prepare_validation_config(
            MINIMAX,
            ticks=2,
            output_dir=tmp_path / "output",
            data_dir=tmp_path / "runs",
            approve_live=False,
        )

    with pytest.raises(ValidationInputError, match="invalid for a provider-free profile"):
        prepare_validation_config(
            REHEARSAL,
            ticks=1,
            output_dir=tmp_path / "output",
            data_dir=tmp_path / "runs",
            approve_live=True,
        )


def test_prepare_validation_preserves_profile_contract_and_rehomes_only_paths(
    tmp_path,
):
    source_root = tmp_path / "runs" / "source"
    prepared = prepare_validation_config(
        REHEARSAL,
        ticks=1,
        output_dir=tmp_path / "output",
        data_dir=tmp_path / "runs",
        approve_live=False,
    )
    profile = load_config(REHEARSAL)

    assert prepared["population"] == profile["population"]
    assert prepared["living_world"] == profile["living_world"]
    assert prepared["budget"] == profile["budget"]
    assert prepared["conversations"] == profile["conversations"]
    assert prepared["checkpoint_every"] == profile["checkpoint_every"] == 7
    assert prepared["checkpoint_keep_last"] == profile["checkpoint_keep_last"] == 4
    assert prepared["checkpoint_dir"] == str(source_root / "checkpoints")
    assert prepared["report_dir"] == str(tmp_path / "output" / "reports")


@pytest.mark.parametrize(
    "payload",
    (
        {"api_key": "credential-canary"},
        {"headers": {"Authorization": "Bearer credential-canary"}},
        {"cookies": {"session": "credential-canary"}},
        {"reasoning_content": "private chain"},
        {"raw": {"provider_body": "private response"}},
        {"environment": {"PATH": "/private/bin"}},
        {"payload": "SQLite format 3\x00database-body"},
        {"payload": "U1FMaXRlIGZvcm1hdCAzAGRhdGFiYXNlLWJvZHk="},
        {"innocent_name": "credential-canary"},
    ),
)
def test_receipt_safety_rejects_secrets_private_bodies_and_databases(payload):
    with pytest.raises(ReceiptSafetyError):
        validate_receipt_safety(
            payload, secret_values=("credential-canary",))


@pytest.mark.parametrize(
    "payload",
    (
        {
            "schema": "agent-economy-scale-validation-v1",
            "profile_path": "runs/scale-270-rehearsal.yaml",
            "providers": {"pairs": [{"provider": "scripted", "model": "scripted"}]},
        },
        {
            "schema": "agent-economy-scale-economic-health-v1",
            "checks": {"ledger_reconciles": True},
        },
        {
            "schema": "agent-economy-scale-ab-v1",
            "arms": {"baseline": "receipt-a.json", "recovery": "receipt-b.json"},
        },
        {
            "schema": "agent-economy-scale-browser-v1",
            "browser": {"name": "Google Chrome", "console_errors": []},
        },
    ),
)
def test_receipt_safety_accepts_sanitized_receipt_shapes(payload):
    validate_receipt_safety(payload, secret_values=("credential-canary",))


def test_one_tick_provider_free_validation_is_isolated_and_exact(tmp_path):
    output_dir = tmp_path / "output"
    data_dir = tmp_path / "runs"

    receipt = run_validation(
        REHEARSAL,
        ticks=1,
        label="one-tick-rehearsal",
        output_dir=output_dir,
        data_dir=data_dir,
        approve_live=False,
    )

    receipt_path = tmp_path / receipt["artifacts"]["runtime_receipt"]
    serialized = receipt_path.read_text(encoding="utf-8")
    persisted = json.loads(serialized)
    assert persisted == receipt
    assert receipt["schema"] == "agent-economy-scale-validation-v1"
    assert receipt["passed"] is True
    assert receipt["source"]["tick"] == 1
    assert receipt["source"]["status"] == "finished"
    assert receipt["population"] == {
        "agents": 308,
        "alive": 308,
        "citizen_kind": 272,
        "staff_kind": 36,
        "core": 100,
        "periphery": 208,
        "regions": {"ironvale": 69, "northstar": 184, "suncoast": 55},
    }
    assert receipt["communications"]["conversations"] == 25
    assert receipt["communications"]["messages"] == 75
    assert receipt["communications"]["empty_messages"] == 0
    assert receipt["providers"]["cost_usd"] == 0.0
    assert {
        (row["provider"], row["model"])
        for row in receipt["providers"]["pairs"]
    } == {("scripted", "scripted")}
    assert receipt["runtime"]["checkpoints"]
    assert receipt["replay"]["proof"]["exact"] is True
    assert receipt["replay"]["proof"]["differences"] == []
    assert next(
        row for row in receipt["replay"]["artifact_manifest"]
        if row["artifact"] == receipt["replay"]["database"]
    )["kind"] == "replay_database"
    assert receipt["source"]["artifact_manifest_before_replay"] == (
        receipt["source"]["artifact_manifest_after_replay"])

    assert str(ROOT) not in serialized
    assert str(tmp_path) not in serialized
    validate_receipt_safety(receipt)
    artifact_ids = {
        receipt["artifacts"]["runtime_receipt"],
        receipt["source"]["database"],
        receipt["replay"]["database"],
        *(
            row["artifact"]
            for row in receipt["source"]["artifact_manifest_before_replay"]
            if row["present"]
        ),
        *(
            row["artifact"]
            for row in receipt["replay"]["artifact_manifest"]
            if row["present"]
        ),
    }
    assert all((tmp_path / artifact).is_file() for artifact in artifact_ids)
    assert all((tmp_path / artifact).resolve().is_relative_to(tmp_path) for artifact in artifact_ids)
    assert any(artifact.endswith(".manifest.json") for artifact in artifact_ids)

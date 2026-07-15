from __future__ import annotations

import asyncio
import csv
import io
import json
import random
import zipfile
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from research.datasets import (
    DatasetError,
    _SUSB_ATOMIC_SIZE_CLASSES,
    _scf_household_distributions_v1,
    _susb_firm_size_sector_v1,
    ingest_manifest,
)
from research.r21 import R21Calibration, R21CalibrationError
from run import open_run, replay_headless
from run_config import load_config
from server.app import create_app
from world.replay_verify import verify_replay


def _scf_zip(rows: list[dict], *, omit: str | None = None) -> bytes:
    fields = [
        "YY1", "Y1", "WGT", "AGE", "KIDS", "OCCAT1", "OCCAT2",
        "INCOME", "LIQ", "NETWORTH",
    ]
    if omit:
        fields.remove(omit)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row[key] for key in fields})
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("SCFP2022.csv", stream.getvalue())
    return target.getvalue()


def _scf_rows() -> list[dict]:
    result = []
    for family_id, values in (
        (1, {"AGE": 70, "KIDS": 0, "OCCAT1": 3, "OCCAT2": 4,
             "INCOME": 30_000, "LIQ": 10_000, "NETWORTH": 400_000}),
        (2, {"AGE": 40, "KIDS": 2, "OCCAT1": 1, "OCCAT2": 1,
             "INCOME": 100_000, "LIQ": 50_000, "NETWORTH": 250_000}),
    ):
        for implicate in range(1, 6):
            result.append({
                "YY1": family_id, "Y1": family_id * 10 + implicate,
                "WGT": 10 + family_id, **values,
            })
    return result


def _scf_item() -> dict:
    return {
        "key": "federal-reserve-scf", "vintage_date": "2022-12-31",
        "metadata": {"survey_year": 2022, "archive_member": "SCFP2022.csv",
                     "implicates_per_family": 5, "expected_public_families": 2},
    }


def _susb_body(*, omit_code: str | None = None) -> bytes:
    fields = [
        "STATE", "NAICS", "ENTRSIZE", "FIRM", "EMPL", "EMPLFL_N",
        "ENTRSIZEDSCR",
    ]
    rows = []
    total = 0
    for code, (lower, upper) in _SUSB_ATOMIC_SIZE_CLASSES.items():
        if code == omit_code:
            continue
        representative = lower if upper is None else (lower + upper) // 2
        firms = 2
        total += firms
        rows.append({"STATE": "00", "NAICS": "--", "ENTRSIZE": code,
                     "FIRM": firms, "EMPL": firms * representative,
                     "EMPLFL_N": "G", "ENTRSIZEDSCR": f"{lower}-{upper}"})
    rows.insert(0, {"STATE": "00", "NAICS": "--", "ENTRSIZE": "01",
                    "FIRM": total, "EMPL": total, "EMPLFL_N": "G",
                    "ENTRSIZEDSCR": "total"})
    rows.extend([
        {"STATE": "00", "NAICS": "--", "ENTRSIZE": "33",
         "FIRM": 999_999, "EMPL": 999_999, "ENTRSIZEDSCR": "overlap <20"},
        {"STATE": "00", "NAICS": "--", "ENTRSIZE": "37",
         "FIRM": 999_999, "EMPL": 999_999, "ENTRSIZEDSCR": "overlap <500"},
        {"STATE": "01", "NAICS": "--", "ENTRSIZE": "02",
         "FIRM": 999_999, "EMPL": 999_999, "ENTRSIZEDSCR": "state row"},
    ])
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def test_scf_adapter_collapses_implicates_and_fails_closed():
    payload = json.loads(_scf_household_distributions_v1(
        _scf_item(), _scf_zip(_scf_rows())))
    target = payload["targets"][0]
    assert target["key"] == "household_microdata.records"
    assert target["dimensions"]["implicates_collapsed"] == 5
    assert target["value"] == {
        "record_count": 2,
        "records": [
            {"age": 70, "annual_income_dollars": 30000, "dependents": 0,
             "family_id": 1, "liquid_assets_dollars": 10000,
             "net_worth_dollars": 400000, "occupation_category": 4,
             "weight": 55.0, "work_status": 3},
            {"age": 40, "annual_income_dollars": 100000, "dependents": 2,
             "family_id": 2, "liquid_assets_dollars": 50000,
             "net_worth_dollars": 250000, "occupation_category": 1,
             "weight": 60.0, "work_status": 1},
        ],
    }

    with pytest.raises(DatasetError, match="missing NETWORTH"):
        _scf_household_distributions_v1(
            _scf_item(), _scf_zip(_scf_rows(), omit="NETWORTH"))
    with pytest.raises(DatasetError, match="must have 5 unique implicates"):
        _scf_household_distributions_v1(
            _scf_item(), _scf_zip(_scf_rows()[:-1]))
    bad = _scf_rows()
    bad[0]["WGT"] = -1
    with pytest.raises(DatasetError, match="non-positive weight"):
        _scf_household_distributions_v1(_scf_item(), _scf_zip(bad))


def test_susb_adapter_uses_only_mutually_exclusive_national_classes():
    item = {"key": "census-susb", "vintage_date": "2022-12-31",
            "metadata": {"reference_year": 2022}}
    payload = json.loads(_susb_firm_size_sector_v1(item, _susb_body()))
    value = payload["targets"][0]["value"]
    assert value["class_count"] == len(_SUSB_ATOMIC_SIZE_CLASSES)
    assert value["total_firms"] == 2 * len(_SUSB_ATOMIC_SIZE_CLASSES)
    assert {row["code"] for row in value["classes"]} == set(
        _SUSB_ATOMIC_SIZE_CLASSES)
    assert not {"01", "33", "37"} & {row["code"] for row in value["classes"]}

    with pytest.raises(DatasetError, match="missing SUSB enterprise-size classes"):
        _susb_firm_size_sector_v1(item, _susb_body(omit_code="25"))


def _absolute_manifest(tmp_path: Path) -> Path:
    source = Path("config/data-manifest.yaml").resolve()
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    for item in payload["datasets"]:
        snapshot = str(item.get("snapshot_path", "")).strip()
        if snapshot:
            item["snapshot_path"] = str((source.parent / snapshot).resolve())
    target = tmp_path / "data-manifest.yaml"
    target.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return target


def _r21_config(manifest: Path | None = None) -> dict:
    config = load_config("runs/r21-real-us.yaml")
    if manifest is not None:
        config["dataset_manifest"] = str(manifest)
    return config


def _event_payloads(store, kind: str) -> list[str]:
    return [str(row["payload_json"]) for row in store.query(
        "SELECT payload_json FROM events WHERE kind=? ORDER BY id", (kind,))]


def _unit_r21_config(**overrides) -> dict:
    calibration = {
        "mode": "real_us",
        "household_dataset_key": "unit-scf",
        "firm_dataset_key": "unit-susb",
        "max_initial_firm_employees": 5,
        "minimum_wage_per_interval_cents": 100,
        "maximum_wage_per_interval_cents": 10_000,
    }
    calibration.update(overrides)
    return {
        "engine_semantics_version": 7,
        "lifecycle": {"retirement_age": 70},
        "calibration": calibration,
    }


def _insert_unit_r21_targets(
        store, *, household: dict | None = None,
        firm_class: dict | None = None, duplicate_household: bool = False) -> None:
    household = household or {
        "family_id": 1,
        "weight": 10.0,
        "age": 65,
        "dependents": 0,
        "work_status": 3,
        "occupation_category": 4,
        "annual_income_dollars": 30_000,
        "liquid_assets_dollars": 10_000,
        "net_worth_dollars": 40_000,
    }
    firm_class = firm_class or {
        "code": "unit",
        "firm_count": 10,
        "min_employees": 10,
        "max_employees": 10,
        "representative_employees": 10,
    }

    def _manifest(dataset_key: str, transform: str) -> int:
        return store.insert(
            "dataset_manifests",
            dataset_key=dataset_key,
            source_url=f"https://example.invalid/{dataset_key}",
            retrieval_time="2026-01-01T00:00:00Z",
            release_date="2022-12-31",
            vintage_date="2022-12-31",
            checksum_sha256="a" * 64,
            transform_version=transform,
            usage_terms="public",
            snapshot_path=f"{dataset_key}.json",
            status="verified",
            metadata_json="{}",
        )

    household_manifest = _manifest(
        "unit-scf", R21Calibration.HOUSEHOLD_TRANSFORM)
    firm_manifest = _manifest("unit-susb", R21Calibration.FIRM_TRANSFORM)
    household_value = json.dumps({"record_count": 1, "records": [household]})
    store.insert(
        "calibration_targets", dataset_manifest_id=household_manifest,
        target_key=R21Calibration.HOUSEHOLD_TARGET,
        value_json=household_value, unit="households",
        dimensions_json=json.dumps({"scope": "unit"}, sort_keys=True))
    if duplicate_household:
        store.insert(
            "calibration_targets", dataset_manifest_id=household_manifest,
            target_key=R21Calibration.HOUSEHOLD_TARGET,
            value_json=household_value, unit="households",
            dimensions_json=json.dumps({"scope": "duplicate"}, sort_keys=True))
    store.insert(
        "calibration_targets", dataset_manifest_id=firm_manifest,
        target_key=R21Calibration.FIRM_TARGET,
        value_json=json.dumps({"class_count": 1, "classes": [firm_class]}),
        unit="firms", dimensions_json="{}")


def test_r21_retirement_is_engine_age_owned_and_records_net_worth_state(store):
    _insert_unit_r21_targets(store)
    calibration = R21Calibration(store, _unit_r21_config(), seed=42)
    sample = calibration.sample_households(random.Random(1), 1, 2)[0]

    assert sample.persona.age == 65
    assert sample.persona.occupation == "gig_worker"
    assert sample.persona.extra["r21_retired"] is False
    assert sample.provenance()["non_liquid_net_worth_cents"] == 3_000_000

    older_threshold = _unit_r21_config()
    older_threshold["lifecycle"]["retirement_age"] = 60
    retired = R21Calibration(store, older_threshold, seed=42).sample_households(
        random.Random(1), 1, 2)[0]
    assert retired.persona.occupation == "retiree"
    assert retired.persona.extra["r21_retired"] is True


def test_r21_evidence_uses_realized_firm_sizes_and_fails_incomplete(store):
    _insert_unit_r21_targets(store)
    calibration = R21Calibration(store, _unit_r21_config(), seed=42)
    calibration.sample_households(random.Random(1), 1, 2)
    with pytest.raises(R21CalibrationError, match="at least one initial firm"):
        calibration.sample_firms(0)
    firm = calibration.sample_firms(1)[0]
    assert firm.requested_employees == 5
    with pytest.raises(R21CalibrationError, match="one realized headcount"):
        calibration.evidence()

    calibration.record_realized_firm(firm, 2)
    evidence = calibration.evidence()
    assert evidence["distance"]["real_us"]["firm_size"] == 0.8
    assert "total_net_worth" in evidence["distance"]["real_us"]
    assert "authoritative off-ledger calibration state" in evidence["wealth_definition"]


@pytest.mark.parametrize("overrides,match", [
    ({"max_initial_firm_employees": 0}, "max_initial_firm_employees"),
    ({"max_initial_firm_employees": "5"}, "max_initial_firm_employees"),
    ({"minimum_wage_per_interval_cents": True},
     "minimum_wage_per_interval_cents"),
    ({"maximum_wage_per_interval_cents": 0},
     "maximum_wage_per_interval_cents"),
    ({"minimum_wage_per_interval_cents": 20_000,
      "maximum_wage_per_interval_cents": 10_000}, "must not exceed"),
])
def test_r21_rejects_invalid_configured_bounds(store, overrides, match):
    _insert_unit_r21_targets(store)
    with pytest.raises(R21CalibrationError, match=match):
        R21Calibration(store, _unit_r21_config(**overrides), seed=42)


@pytest.mark.parametrize("field,bad_value", [
    ("family_id", True),
    ("age", "65"),
    ("weight", "10.0"),
    ("annual_income_dollars", float("nan")),
])
def test_r21_rejects_coerced_or_nonfinite_household_numbers(
        store, field, bad_value):
    household = {
        "family_id": 1, "weight": 10.0, "age": 65, "dependents": 0,
        "work_status": 3, "occupation_category": 4,
        "annual_income_dollars": 30_000,
        "liquid_assets_dollars": 10_000, "net_worth_dollars": 40_000,
    }
    household[field] = bad_value
    _insert_unit_r21_targets(store, household=household)
    with pytest.raises(R21CalibrationError, match="record is malformed"):
        R21Calibration(store, _unit_r21_config(), seed=42)


def test_r21_requires_one_logical_target_per_dataset(store):
    _insert_unit_r21_targets(store, duplicate_household=True)
    with pytest.raises(R21CalibrationError, match="exactly one target; found 2"):
        R21Calibration(store, _unit_r21_config(), seed=42)


def test_real_us_genesis_is_deterministic_calibrated_and_reconciled(tmp_path: Path):
    first_dir, second_dir = tmp_path / "first", tmp_path / "second"
    first, first_world, _ = open_run(_r21_config(), None, None, data_dir=first_dir)
    second, second_world, _ = open_run(_r21_config(), None, None, data_dir=second_dir)
    first_households = _event_payloads(first, "r21_household_sampled")
    try:
        assert first_households == _event_payloads(
            second, "r21_household_sampled")
        assert _event_payloads(first, "r21_firm_size_sampled") == _event_payloads(
            second, "r21_firm_size_sampled")
        assert _event_payloads(first, "r21_calibration_applied") == _event_payloads(
            second, "r21_calibration_applied")
        evidence = json.loads(_event_payloads(first, "r21_calibration_applied")[0])
        assert evidence["distance"]["real_us"]["composite"] \
            < evidence["distance"]["synthetic_baseline"]["composite"]
        assert evidence["households_sampled"] == 70
        assert evidence["firms_sampled"] == 12

        for row in first.query(
                "SELECT e.payload_json,a.checking_account_id,a.savings_account_id "
                "FROM events e JOIN agents a ON a.id=e.subject_id "
                "WHERE e.kind='r21_household_sampled' ORDER BY e.id"):
            payload = json.loads(row["payload_json"])
            checking = first_world.economy.ledger.balance(int(row["checking_account_id"]))
            savings = (first_world.economy.ledger.balance(
                int(row["savings_account_id"])) if row["savings_account_id"] is not None else 0)
            assert checking + savings == payload["liquid_wealth_cents"]
            assert checking == int(payload["liquid_wealth_cents"] * 0.7)
            assert payload["non_liquid_net_worth_cents"] == (
                payload["net_worth_cents"] - payload["liquid_wealth_cents"])

        firm_payloads = [json.loads(payload) for payload in _event_payloads(
            first, "r21_firm_size_sampled")]
        assert firm_payloads
        assert all({"requested_employees", "source_representative_employees",
                    "source_firm_count", "realized_employees"} <= set(payload)
                   for payload in firm_payloads)

        wages = first.query(
            "SELECT m.payload_json,e.wage_cents FROM employments e "
            "JOIN events m ON m.subject_id=e.agent_id "
            "AND m.kind='r21_household_sampled' "
            "JOIN events f ON f.subject_id=e.firm_id "
            "AND f.kind='r21_firm_size_sampled' ORDER BY e.id")
        assert wages
        for row in wages:
            income = json.loads(row["payload_json"])["annual_income_cents"]
            assert int(row["wage_cents"]) == max(50_000, min(5_000_000,
                                                            round(income / 12)))
        assert first_world.economy.ledger.reconcile()[0]

        with TestClient(create_app(first_world)) as client:
            response = client.get("/api/v2/datasets")
            assert response.status_code == 200
            assert response.json()["r21_calibration"]["mode"] == "real_us"
    finally:
        first_world.close()
        second_world.close()

    different_config = _r21_config()
    different_config["seed"] = 43
    third, third_world, _ = open_run(
        different_config, None, None, data_dir=tmp_path / "third")
    try:
        assert _event_payloads(third, "r21_household_sampled") != first_households
    finally:
        third_world.close()


def test_real_us_replay_uses_recorded_targets_without_manifest(tmp_path: Path):
    manifest = _absolute_manifest(tmp_path)
    data_dir = tmp_path / "runs"
    source, source_world, source_id = open_run(
        _r21_config(manifest), None, None, data_dir=data_dir)
    try:
        asyncio.run(source_world.run(max_ticks=1))
        assert source.tick == 1
        source_path = Path(source.path)
        source_world.close()
        manifest.unlink()
        replay, replay_world, _ = open_run({}, None, source_id, data_dir=data_dir)
        try:
            asyncio.run(replay_headless(replay_world, 1))
            proof = verify_replay(source_path, replay.path)
            assert proof["exact"] is True
            assert proof["differences"] == []
            assert replay.scalar(
                "SELECT COUNT(*) FROM events WHERE kind='r21_calibration_applied'") == 1
        finally:
            replay_world.close()
    finally:
        source_world.close()


def test_real_us_requires_verified_supports(tmp_path: Path):
    config = _r21_config()
    config.pop("dataset_manifest")
    with pytest.raises(R21CalibrationError, match="missing required calibration target"):
        store, world, _ = open_run(config, None, None, data_dir=tmp_path)
        world.close()


def test_manifest_reingest_replaces_targets_without_orphans(tmp_path: Path):
    manifest = _absolute_manifest(tmp_path)
    config = load_config("runs/base.yaml")
    store, world, _ = open_run(config, None, None, data_dir=tmp_path / "world")
    try:
        ingest_manifest(store, manifest)
        first_count = int(store.scalar("SELECT COUNT(*) FROM calibration_targets"))
        ingest_manifest(store, manifest)
        assert int(store.scalar("SELECT COUNT(*) FROM calibration_targets")) == first_count
        assert int(store.scalar(
            "SELECT COUNT(*) FROM calibration_targets c LEFT JOIN dataset_manifests d "
            "ON d.id=c.dataset_manifest_id WHERE d.id IS NULL")) == 0
    finally:
        world.close()

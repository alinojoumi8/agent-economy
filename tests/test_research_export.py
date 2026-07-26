"""Hash-contract-v1 and deterministic Parquet export tests."""
from __future__ import annotations

import json

import duckdb
import pytest

from communications.delivery import CommunicationDelivery
from engine.actions import ActionExecutor
from engine.store import Store
from research.export_bundle import ExportBundleError, export_bundle, validate_bundle
from research.hashing import (
    HashContractError,
    canonical_hashes,
    canonical_projection_hash,
    canonical_value,
    verify_hash_contract,
)
from research.supplier_warning_experiment import create_common_checkpoint
from tests.conftest import make_agent, make_bank


def test_hash_contract_is_typed_stable_and_excludes_wall_time(tmp_path):
    first, _ = create_common_checkpoint(tmp_path / "first.db")
    second, _ = create_common_checkpoint(tmp_path / "second.db")
    try:
        first_hashes = canonical_hashes(first)
        second_hashes = canonical_hashes(second)
        assert first_hashes["authoritative_sha256"] == second_hashes[
            "authoritative_sha256"]
        first.execute(
            "UPDATE schema_migrations SET applied_at='different-wall-time'")
        first.execute(
            "UPDATE events SET created_at='different-wall-time'")
        first.execute(
            "UPDATE run_meta SET updated_at='different-wall-time'")
        assert canonical_hashes(first)["authoritative_sha256"] == first_hashes[
            "authoritative_sha256"]
        first.insert("metrics", tick=4, name="derived-only", value=1.5)
        changed = canonical_hashes(first)
        assert changed["authoritative_sha256"] == first_hashes["authoritative_sha256"]
        assert changed["derived_sha256"] != first_hashes["derived_sha256"]
    finally:
        first.close()
        second.close()

    assert canonical_value("e\u0301") == canonical_value("é")
    assert canonical_value(1) != canonical_value(1.0)
    assert canonical_projection_hash({"a": 1, "b": [2.0]}) == (
        canonical_projection_hash({"b": [2.0], "a": 1}))


def test_hash_contract_rejects_every_unclassified_schema_or_value(tmp_path):
    store = Store(str(tmp_path / "world.db"))
    store.init_run_meta("hash-test", 1, {})
    try:
        store.execute("CREATE TABLE surprise_table(id INTEGER PRIMARY KEY)")
        with pytest.raises(HashContractError, match="unclassified storage tables"):
            verify_hash_contract(store)
        store.execute("DROP TABLE surprise_table")
        store.execute("ALTER TABLE agents ADD COLUMN surprise_column TEXT")
        with pytest.raises(HashContractError, match="unclassified storage column"):
            verify_hash_contract(store)
    finally:
        store.close()

    invalid = Store(str(tmp_path / "invalid-json.db"))
    invalid.init_run_meta("invalid-json", 1, {})
    try:
        invalid.execute("UPDATE run_meta SET config_json='{' WHERE id=1")
        with pytest.raises(HashContractError, match="invalid JSON"):
            canonical_hashes(invalid)
    finally:
        invalid.close()


def test_hash_contract_v1_is_frozen_and_v2_covers_gateway_commons(tmp_path):
    historical = Store(str(tmp_path / "semantics-8.db"))
    current = Store(str(tmp_path / "semantics-10.db"))
    try:
        historical.init_run_meta(
            "semantics-8", 8, {"engine_semantics_version": 8})
        historical_hashes = canonical_hashes(historical)
        assert historical_hashes["contract_id"] == "hash-contract-v1"
        assert historical_hashes["schema_inventory_sha256"] == (
            "0df8926132314e91b603c6cb2b56c0743fb690347680dd0a3b62b3fbc356c8d0")

        current.init_run_meta(
            "semantics-10", 10, {"engine_semantics_version": 10})
        agent_id = current.insert(
            "agents", name="Commons Citizen", kind="citizen", age=30)
        before = canonical_hashes(current)
        assert before["contract_id"] == "hash-contract-v2"
        assert before["schema_inventory_sha256"] == (
            "495657150cd398601e4dab9532e09275e5ec054b90834e85a8525021afad7865")
        current.insert(
            "commons_profiles", agent_id=agent_id,
            display_name="Commons Citizen", created_tick=0, updated_tick=0)
        after = canonical_hashes(current)
        assert after["authoritative_sha256"] != before["authoritative_sha256"]
        assert after["tables"]["commons_profiles"]["row_count"] == 1
        assert after["tables"]["commons_profiles"]["sha256"] != before[
            "tables"]["commons_profiles"]["sha256"]
    finally:
        historical.close()
        current.close()


def test_default_export_is_deterministic_queryable_and_private(economy, tmp_path):
    economy.config["engine_semantics_version"] = 8
    economy.config["communications"] = {}
    bank_id = make_bank(economy)
    sender, _ = make_agent(
        economy, bank_id, name="Private Sender", population_tier="core")
    recipient, _ = make_agent(
        economy, bank_id, name="Private Recipient", population_tier="core")
    secret_subject = "Secret supplier warning"
    secret_body = "Do not reveal batch private-413"
    result = ActionExecutor(economy).execute_action(1, sender, {
        "type": "send_message",
        "audience": {"kind": "direct", "agent_ids": [recipient]},
        "subject": secret_subject,
        "body": secret_body,
    })
    assert result["ok"] is True
    CommunicationDelivery(economy.store, economy.config).deliver_due(2)

    first = export_bundle(economy.store, tmp_path / "exports")
    second = export_bundle(economy.store, tmp_path / "exports")
    assert first == second
    manifest = validate_bundle(first)
    assert manifest["privacy_profile"] == "default-redacted-pseudonymous-v1"
    assert manifest["tables"]["comm_messages"]["redactions"]["body_text"] == 1
    assert manifest["tables"]["comm_threads"]["redactions"]["subject"] == 1
    assert manifest["tables"]["comm_messages"]["pseudonyms"][
        "sender_agent_id"] == 1

    connection = duckdb.connect(database=":memory:")
    try:
        message = connection.execute(
            "SELECT body_text,sender_agent_id FROM read_parquet(?)",
            [str(first / "comm_messages.parquet")],
        ).fetchone()
        thread = connection.execute(
            "SELECT subject FROM read_parquet(?)",
            [str(first / "comm_threads.parquet")],
        ).fetchone()
    finally:
        connection.close()
    assert message[0] is None
    assert message[1] != sender
    assert thread[0] is None
    for path in first.iterdir():
        raw = path.read_bytes()
        assert secret_subject.encode() not in raw
        assert secret_body.encode() not in raw


def test_interrupted_or_modified_export_is_rejected(economy, tmp_path):
    root = tmp_path / "exports"

    def fail_before(name, _context):
        if name == "before_publish":
            raise RuntimeError("stop-before-publish")

    with pytest.raises(RuntimeError, match="stop-before-publish"):
        export_bundle(economy.store, root, fault_hook=fail_before)
    assert list(root.iterdir()) == []

    def fail_after(name, _context):
        if name == "after_publish_before_manifest":
            raise RuntimeError("stop-after-publish")

    with pytest.raises(RuntimeError, match="stop-after-publish"):
        export_bundle(economy.store, root, fault_hook=fail_after)
    incomplete = next(root.iterdir())
    with pytest.raises(ExportBundleError, match="manifest is absent"):
        validate_bundle(incomplete)

    clean_root = tmp_path / "clean"
    bundle = export_bundle(economy.store, clean_root)
    events = bundle / "events.parquet"
    events.write_bytes(events.read_bytes() + b"tamper")
    with pytest.raises(ExportBundleError, match="file hash mismatch"):
        validate_bundle(bundle)


def test_manifest_hash_rejects_rewritten_metadata(economy, tmp_path):
    bundle = export_bundle(economy.store, tmp_path / "exports")
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["privacy_profile"] = "unsafe"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ExportBundleError, match="manifest hash mismatch"):
        validate_bundle(bundle)


def test_hash_contract_v2_redacts_external_action_canaries(tmp_path):
    from pathlib import Path

    from research.hashing import load_hash_contract
    from run_config import load_config
    from world.loop import World

    canary = "CANARY-EA-EXPORT-7d2a9f31"
    v1 = load_hash_contract(Path("research/hash-contract-v1.json"))
    v2 = load_hash_contract(Path("research/hash-contract-v2.json"))
    assert "external_action_submissions" not in v1.get("default_export_redactions", {})
    assert set(v2["default_export_redactions"]["external_action_submissions"]) == {
        "action_json", "rationale_summary", "result_json", "validator_results_json",
    }

    config = load_config("runs/world-os-external.yaml")
    config["population"]["size"] = 4
    config["firms"]["count"] = 2
    config["firms"]["listed"] = 1
    config["banks"]["count"] = 1
    config["checkpoint_every"] = 0
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    store = Store(str(tmp_path / "export-external.db"))
    store.init_run_meta("export-external", 42, config)
    world = World(store, config)
    try:
        world.initialize()
        created = world.runtime.external.create_connection(
            tenant_id="tenant-a", owner_id="owner-export",
            display_name="Export Citizen", biography="Public bio.",
            preferred_occupation="builder", tier="actor")
        world._spawn_due_arrivals(1)
        auth = world.runtime.external.authenticate(
            created["credential"]["token"], rate_limit=False)
        turn = world.runtime.external.turn(auth)
        submission_id = "exportcanary" + ("0" * 20)
        store.execute(
            "INSERT INTO external_action_submissions("
            "id,connection_id,actor_id,turn_id,target_tick,observed_projection_hash,"
            "idempotency_key,action_json,rationale_summary,status,validator_results_json,"
            "result_json,event_ids_json,resulting_state_hash,source_submission_id,"
            "created_at,completed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                submission_id, auth["id"], auth["actor_id"], turn["turn_id"],
                turn["target_tick"], turn["projection_hash"], "export-canary-key",
                json.dumps({"type": "do_nothing", "secret": canary}),
                canary,
                "executed",
                json.dumps([{"validator": "participant_catalog", "ok": True,
                             "message": canary}]),
                json.dumps([{"ok": True, "private": canary}]),
                json.dumps([11]),
                "e" * 64,
                None,
                "2026-07-24T00:00:00+00:00",
                "2026-07-24T00:00:01+00:00",
            ),
        )
        store.commit()
        # External-action redactions are a hash-contract-v2 default-export policy.
        bundle = export_bundle(
            store, tmp_path / "exports",
            contract_path=Path("research/hash-contract-v2.json"),
        )
        manifest = validate_bundle(bundle)
        assert manifest["contract_id"] == "hash-contract-v2"
        redactions = manifest["tables"]["external_action_submissions"]["redactions"]
        for field in (
            "action_json", "rationale_summary", "result_json", "validator_results_json",
        ):
            assert redactions[field] == 1, field
        # Non-sensitive integrity fields remain.
        connection = duckdb.connect(database=":memory:")
        try:
            row = connection.execute(
                "SELECT status,event_ids_json,resulting_state_hash,"
                "action_json,rationale_summary,result_json,validator_results_json "
                "FROM read_parquet(?)",
                [str(bundle / "external_action_submissions.parquet")],
            ).fetchone()
        finally:
            connection.close()
        assert row[0] == "executed"
        assert row[1] is not None
        assert row[2] == "e" * 64
        assert row[3] is None
        assert row[4] is None
        assert row[5] is None
        assert row[6] is None
        for path in bundle.iterdir():
            assert canary.encode() not in path.read_bytes()
    finally:
        world.close()

"""Compatibility foundations for the opt-in Semantics 8 release."""
from __future__ import annotations

import sqlite3

import pytest

from engine.commands.registry import (
    CommandDefinition,
    CommandRegistry,
    CommandValidationError,
    default_registry,
)
from engine.commands.models import LegacyCommand
from engine.migrations import registry as migration_registry
from engine.migrations.registry import Migration, MigrationError
from engine.schema import SCHEMA_VERSION
from engine.semantics import UnsupportedEngineSemantics
from engine.store import Store
from world.phases import (
    LEGACY_PHASE_SPECS,
    SEMANTICS_8_PHASE_SPECS,
    STANDARD_PHASE_SPECS,
    phase_names_for_semantics,
    phase_specs_for_semantics,
)


LEGACY_PHASES = (
    "NIGHT_CLOSE", "MORNING", "EXECUTION", "MARKET",
    "NEWSROOM", "EVENING", "MEMORY",
)
STANDARD_PHASES = (*LEGACY_PHASES, "FINALIZE")


def test_phase_spec_preserves_semantics_one_through_seven() -> None:
    assert phase_names_for_semantics(1) == LEGACY_PHASES
    for version in range(2, 8):
        assert phase_names_for_semantics(version) == STANDARD_PHASES
        assert phase_specs_for_semantics(version) is STANDARD_PHASE_SPECS
    assert phase_specs_for_semantics(1) is LEGACY_PHASE_SPECS


def test_semantics_eight_adds_one_transactional_inbox_boundary() -> None:
    assert phase_names_for_semantics(8) == (
        "NIGHT_CLOSE", "INBOX_DELIVERY", *STANDARD_PHASES[1:])
    inbox = SEMANTICS_8_PHASE_SPECS[1]
    assert inbox.name == "INBOX_DELIVERY"
    assert inbox.transactional is True
    assert inbox.inference is False


@pytest.mark.parametrize("version", [0, 13])
def test_phase_lookup_rejects_unsupported_semantics(version: int) -> None:
    with pytest.raises(UnsupportedEngineSemantics):
        phase_specs_for_semantics(version)


def test_fresh_store_applies_current_migration_history(tmp_path) -> None:
    store = Store(str(tmp_path / "fresh.db"))
    try:
        assert SCHEMA_VERSION == 17
        communication_tables = {
            row["name"] for row in store.query(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
                "('comm_threads','comm_messages','comm_audiences','comm_deliveries',"
                "'comm_disclosure_authorities','comm_disclosures')")
        }
        assert communication_tables == {
            "comm_threads", "comm_messages", "comm_audiences", "comm_deliveries",
            "comm_disclosure_authorities", "comm_disclosures",
        }
        history = store.query(
            "SELECT version,name,status,source_schema,checksum_sha256 "
            "FROM schema_migrations ORDER BY version")
        assert [(row["version"], row["name"], row["status"]) for row in history] == [
            (11, "legacy_schema_v11", "adopted_legacy"),
            (12, "communications_and_causal_links", "applied"),
            (13, "external_agent_gateway", "applied"),
            (14, "agent_commons", "applied"),
            (15, "cognition_economy", "applied"),
            (16, "passport_bindings", "applied"),
            (17, "civic_city", "applied"),
        ]
        assert history[1]["source_schema"] == 11
        assert history[1]["checksum_sha256"] == (
            migration_registry.registered_migrations()[0].checksum_sha256)
        assert history[-1]["source_schema"] == 16
        assert history[-1]["checksum_sha256"] == (
            migration_registry.registered_migrations()[-1].checksum_sha256)
    finally:
        store.close()


def test_reopen_is_idempotent_and_does_not_reapply_migration(tmp_path) -> None:
    path = tmp_path / "reopen.db"
    Store(str(path)).close()
    reopened = Store(str(path))
    try:
        assert reopened.scalar("SELECT COUNT(*) FROM schema_migrations") == 7
    finally:
        reopened.close()


def test_migration_history_fails_closed_on_checksum_tampering(tmp_path) -> None:
    path = tmp_path / "tampered.db"
    Store(str(path)).close()
    conn = sqlite3.connect(path)
    conn.execute("UPDATE schema_migrations SET checksum_sha256=? WHERE version=12", ("0" * 64,))
    conn.commit()
    conn.close()

    with pytest.raises(MigrationError, match="checksum mismatch"):
        Store(str(path))


def test_migration_history_fails_closed_on_unknown_future_row(tmp_path) -> None:
    path = tmp_path / "future-history.db"
    Store(str(path)).close()
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO schema_migrations "
        "(version,name,checksum_sha256,source_schema,status) "
        "VALUES (99,'future',?,14,'applied')",
        ("f" * 64,),
    )
    conn.commit()
    conn.close()

    with pytest.raises(MigrationError, match="future migration history"):
        Store(str(path))


def test_failed_migration_rolls_back_schema_and_history(tmp_path, monkeypatch) -> None:
    store = Store(str(tmp_path / "rollback.db"))
    broken = Migration.create(
        18,
        "broken_probe",
        "CREATE TABLE migration_probe(id INTEGER);\n"
        "INSERT INTO missing_table(id) VALUES (1);",
    )
    monkeypatch.setattr(
        migration_registry,
        "_MIGRATIONS",
        (*migration_registry.registered_migrations(), broken),
    )
    try:
        with pytest.raises(MigrationError, match="failed applying migration v18"):
            migration_registry.apply_migrations(
                store.conn, source_schema=17, target_schema=18)
        assert store.scalar(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='migration_probe'") == 0
        assert store.scalar(
            "SELECT COUNT(*) FROM schema_migrations WHERE version=18") == 0
    finally:
        store.close()


def test_communication_command_registry_is_opt_in_and_strict() -> None:
    registry = default_registry({"buy", "send_message", "reply_message", "forward_message"})
    legacy, legacy_payload = registry.validate("buy", {"units": 10, "ticker": "ACME"}, 1)
    assert legacy.handler_name == "_do_buy"
    assert legacy_payload == {"units": 10, "ticker": "ACME"}

    with pytest.raises(CommandValidationError, match="unknown action type"):
        registry.validate(
            "send_message",
            {"audience": {"kind": "public"}, "subject": "Hi", "body": "News"},
            7,
        )

    definition, payload = registry.validate(
        "send_message",
        {
            "audience": {"kind": "direct", "agent_ids": [2, 3]},
            "subject": "A bounded subject",
            "body": "A bounded body",
        },
        8,
    )
    assert definition.handler_name == "_do_send_message"
    assert payload["audience"] == {"kind": "direct", "agent_ids": [2, 3]}


@pytest.mark.parametrize(
    "payload,match",
    [
        ({"audience": {"kind": "direct", "agent_ids": [2, 2]},
          "subject": "s", "body": "b"}, "must be unique"),
        ({"audience": {"kind": "direct", "agent_ids": [True]},
          "subject": "s", "body": "b"}, "positive integers"),
        ({"audience": {"kind": "direct", "agent_ids": list(range(1, 22))},
          "subject": "s", "body": "b"}, "at most 20"),
        ({"audience": {"kind": "public"}, "subject": "x" * 161, "body": "b"},
         "at most 160"),
        ({"audience": {"kind": "public"}, "subject": "s", "body": "x" * 2001},
         "at most 2000"),
        ({"audience": {"kind": "public"}, "subject": "s", "body": "b", "extra": 1},
         "Extra inputs"),
    ],
)
def test_send_command_rejects_every_bounded_validation_branch(payload, match) -> None:
    registry = default_registry({"send_message"})
    with pytest.raises(CommandValidationError, match=match):
        registry.validate("send_message", payload, 8)


def test_reply_forward_and_all_audience_models_round_trip() -> None:
    registry = default_registry({"reply_message", "forward_message", "send_message"})
    _, reply = registry.validate(
        "reply_message", {"parent_message_id": 4, "body": "Acknowledged"}, 8)
    assert reply == {"parent_message_id": 4, "body": "Acknowledged"}

    _, forwarded = registry.validate(
        "forward_message",
        {
            "source_message_id": 4,
            "audience": {
                "kind": "organization", "organization_kind": "firm", "organization_id": 7},
        },
        8,
    )
    assert forwarded["note"] == ""

    _, public = registry.validate(
        "send_message",
        {"audience": {"kind": "public"}, "subject": "Public", "body": "Statement"},
        8,
    )
    assert public["audience"] == {"kind": "public"}


def test_registry_rejects_unknown_and_duplicate_definitions() -> None:
    registry = CommandRegistry()
    definition = CommandDefinition("legacy", LegacyCommand, "_do_legacy", 1)
    registry.register(definition)
    assert registry.definitions() == (definition,)
    with pytest.raises(CommandValidationError, match="duplicate command type"):
        registry.register(definition)
    with pytest.raises(CommandValidationError, match="unknown action type"):
        registry.resolve("missing", 8)

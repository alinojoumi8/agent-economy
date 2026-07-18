"""Defensive/refutation branch tests for the frozen 30-tick protocol."""
from __future__ import annotations

import copy
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

import research.supplier_warning_experiment as protocol
from agents.policies import SUPPLIER_WARNING_POLICY_CONTRACT_HASH, SUPPLIER_WARNING_POLICY_ID
from communications.policy import AccessDecision
from engine.actions import ActionExecutor
from engine.store import Store


def _valid_receipts():
    receipts = {}
    for arm, qty, observation, chain in (
        ("control-none", 10, 0, 0),
        ("control-neutral", 10, 1, 0),
        ("treatment-warning", 5, 1, 5),
    ):
        receipts[arm] = {
            "quantity": {
                "qty": qty,
                "unit_price_cents": 100,
                "total_cents": qty * 100,
                "inventory": 100 - qty,
                "entry_sum_cents": 0,
                "entry_ids": [1, 2],
                "policy_contract_hash": SUPPLIER_WARNING_POLICY_CONTRACT_HASH,
            },
            "privacy": {"outside_access": False},
            "causal": {
                "message_observation_edges": observation,
                "warning_chain_edges": chain,
            },
            "table_hashes": {"events": "same"},
        }
    return receipts


def _valid_edges():
    shapes = (
        ("message", "1", "memory", "2", "observed", "engine", None, {}),
        ("memory", "2", "belief", "3", "triggered", "engine", None, {}),
        ("belief", "3", "action_proposal", "4", "motivated", "actor_claim",
         SUPPLIER_WARNING_POLICY_ID, {}),
        ("action_proposal", "4", "event", "5", "triggered", "engine", None, {}),
        ("event", "5", "ledger_transaction", "6", "settled", "engine", None,
         {"entry_ids": [1, 2]}),
    )
    return [
        {
            "id": index,
            "source_kind": source_kind,
            "source_id": source_id,
            "target_kind": target_kind,
            "target_id": target_id,
            "relation": relation,
            "authority": authority,
            "method": method,
            "evidence_json": json.dumps(evidence),
        }
        for index, (
            source_kind, source_id, target_kind, target_id, relation, authority, method,
            evidence,
        ) in enumerate(shapes, start=1)
    ]


class _CausalStore:
    def __init__(self, rows, message=None):
        self.rows = rows
        self.message = message

    def query(self, _sql, _params=()):
        return self.rows

    def query_one(self, _sql, _params=()):
        return self.message


def test_checkpoint_creation_rejects_nonpositive_checkpoint_id(tmp_path, monkeypatch):
    original = Store.insert

    def insert(store, table, **columns):
        result = original(store, table, **columns)
        return 0 if table == "checkpoints" else result

    monkeypatch.setattr(Store, "insert", insert)
    with pytest.raises(AssertionError, match="checkpoint row"):
        protocol.create_common_checkpoint(tmp_path / "bad-checkpoint.db")


def test_fixture_verifier_rejects_every_frozen_precondition(tmp_path, monkeypatch):
    store, identity = protocol.create_common_checkpoint(tmp_path / "common.db")
    try:
        store.execute("UPDATE run_meta SET tick=3 WHERE id=1")
        with pytest.raises(AssertionError, match="tick 4"):
            protocol.verify_fixture(store, identity)
        store.execute("UPDATE run_meta SET tick=4 WHERE id=1")

        config = json.loads(store.get_meta()["config_json"])
        config["engine_semantics_version"] = 7
        store.execute(
            "UPDATE run_meta SET config_json=? WHERE id=1", (json.dumps(config),))
        with pytest.raises(AssertionError, match="semantics 8"):
            protocol.verify_fixture(store, identity)
        config["engine_semantics_version"] = 8
        store.execute(
            "UPDATE run_meta SET config_json=? WHERE id=1", (json.dumps(config),))

        store.execute("UPDATE run_meta SET schema_version=11 WHERE id=1")
        with pytest.raises(AssertionError, match="schema 12"):
            protocol.verify_fixture(store, identity)
        store.execute("UPDATE run_meta SET schema_version=12 WHERE id=1")
        monkeypatch.setattr(protocol, "SCHEMA_VERSION", 13)
        store.execute("UPDATE run_meta SET schema_version=13 WHERE id=1")
        with pytest.raises(AssertionError, match="schema 12"):
            protocol.verify_fixture(store, identity)
        monkeypatch.setattr(protocol, "SCHEMA_VERSION", 12)
        store.execute("UPDATE run_meta SET schema_version=12 WHERE id=1")

        with pytest.raises(AssertionError, match="all three"):
            protocol.verify_fixture(store, replace(identity, outside_agent_id=999999))
        store.update("agents", identity.outside_agent_id, alive=0, died_tick=4)
        with pytest.raises(AssertionError, match="all three"):
            protocol.verify_fixture(store, identity)
        store.update("agents", identity.outside_agent_id, alive=1, died_tick=None)

        store.update("agents", identity.sender_agent_id, role="citizen")
        with pytest.raises(AssertionError, match="supplier_officer"):
            protocol.verify_fixture(store, identity)
        store.update("agents", identity.sender_agent_id, role="supplier_officer")

        with pytest.raises(AssertionError, match="inventory/price/status"):
            protocol.verify_fixture(store, replace(identity, supplier_firm_id=999999))
        store.update("firms", identity.supplier_firm_id, status="bankrupt")
        with pytest.raises(AssertionError, match="inventory/price/status"):
            protocol.verify_fixture(store, identity)
        store.update("firms", identity.supplier_firm_id, status="private", inventory=99)
        with pytest.raises(AssertionError, match="inventory/price/status"):
            protocol.verify_fixture(store, identity)
        store.update("firms", identity.supplier_firm_id, inventory=100,
                     product_json=json.dumps({"unit_price_cents": 99}))
        with pytest.raises(AssertionError, match="inventory/price/status"):
            protocol.verify_fixture(store, identity)
        store.update("firms", identity.supplier_firm_id,
                     product_json=json.dumps({"unit_price_cents": 100}))

        store.execute(
            "UPDATE accounts SET balance_cents=999 WHERE id=?",
            (identity.retailer_account_id,))
        with pytest.raises(AssertionError, match="cannot fund"):
            protocol.verify_fixture(store, identity)
        store.execute(
            "UPDATE accounts SET balance_cents=10000 WHERE id=?",
            (identity.retailer_account_id,))

        economy = protocol._economy(store, json.loads(store.get_meta()["config_json"]))
        result = ActionExecutor(economy).execute_action(5, identity.sender_agent_id, {
            "type": "send_message",
            "audience": {"kind": "direct", "agent_ids": [identity.retailer_agent_id]},
            "subject": "probe", "body": "probe",
        })
        assert result["ok"]
        with pytest.raises(AssertionError, match="no threaded messages"):
            protocol.verify_fixture(store, identity)
    finally:
        store.close()


def test_phase_effect_rejects_send_failure_and_builds_missing_projection(monkeypatch):
    identity = protocol.FixtureIdentity(1, 2, 3, 4, 5, 6)

    class RejectingExecutor:
        def execute_action(self, *_args, **_kwargs):
            return {"ok": False, "reason": "rejected"}

    with pytest.raises(AssertionError, match="communication failed"):
        protocol._phase_effect(
            "EXECUTION", tick=5, arm="control-neutral", economy=SimpleNamespace(),
            config={}, identity=identity, executor=RejectingExecutor(), state={})

    projection = {"items": [], "sources": [], "read_context_key": None}

    class Projection:
        def __init__(self, *_args):
            pass

        def build(self, agent_id, tick):
            assert (agent_id, tick) == (2, 6)
            return projection

    observed = []
    monkeypatch.setattr(protocol, "AgentKnowledgeProjection", Projection)
    monkeypatch.setattr(
        protocol, "_execute_purchase",
        lambda economy, config, actual_identity, actual_projection, executor: observed.append(
            (actual_identity, actual_projection)))
    protocol._phase_effect(
        "EXECUTION", tick=6, arm="control-none",
        economy=SimpleNamespace(store=object()), config={}, identity=identity,
        executor=object(), state={})
    assert observed == [(identity, projection)]


def test_run_branch_unknown_arm_and_repeated_phase_failure(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="unknown protocol arm"):
        protocol.run_branch(tmp_path / "missing.db", arm="unknown",
                            identity=protocol.FixtureIdentity(1, 2, 3, 4, 5, 6))

    common, identity = protocol.create_common_checkpoint(tmp_path / "common.db")
    branch = tmp_path / "branch.db"
    try:
        protocol._prepare_branch(common, branch, "control-none")
    finally:
        common.close()

    monkeypatch.setattr(
        protocol, "_phase_effect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(protocol.ScenarioFault("repeat")))
    with pytest.raises(protocol.ScenarioFault, match="repeat"):
        protocol.run_branch(
            branch, arm="control-none", identity=identity, start_tick=5, end_tick=5)


def test_quantity_and_causal_receipts_fail_closed():
    class EmptyQuantity:
        def query(self, *_args, **_kwargs):
            return []

    with pytest.raises(AssertionError, match="exactly one"):
        protocol._quantity_receipt(EmptyQuantity(), protocol.FixtureIdentity(1, 2, 3, 4, 5, 6))

    class MissingTransaction:
        def query(self, *_args, **_kwargs):
            return [{"id": 1, "payload_json": "{}", "result_json": "{}"}]

        def query_one(self, *_args, **_kwargs):
            return None

    with pytest.raises(AssertionError, match="transaction is absent"):
        protocol._quantity_receipt(
            MissingTransaction(), protocol.FixtureIdentity(1, 2, 3, 4, 5, 6))

    identity = protocol.FixtureIdentity(1, 2, 3, 4, 5, 6)
    with pytest.raises(AssertionError, match="message is absent"):
        protocol._causal_receipt(_CausalStore([], None), identity, "treatment-warning")
    with pytest.raises(AssertionError, match="expected exactly one"):
        protocol._causal_receipt(
            _CausalStore([], {"id": 1}), identity, "treatment-warning")

    rows = _valid_edges()
    receipt = protocol._causal_receipt(
        _CausalStore(rows, {"id": 1}), identity, "treatment-warning")
    assert receipt["warning_chain_edges"] == 5
    wrong_start = copy.deepcopy(rows)
    wrong_start[0]["source_id"] = "99"
    with pytest.raises(AssertionError, match="wrong message"):
        protocol._causal_receipt(
            _CausalStore(wrong_start, {"id": 1}), identity, "treatment-warning")
    wrong_method = copy.deepcopy(rows)
    wrong_method[2]["method"] = "other"
    with pytest.raises(AssertionError, match="frozen policy method"):
        protocol._causal_receipt(
            _CausalStore(wrong_method, {"id": 1}), identity, "treatment-warning")
    wrong_evidence = copy.deepcopy(rows)
    wrong_evidence[-1]["evidence_json"] = "{}"
    with pytest.raises(AssertionError, match="two ledger entries"):
        protocol._causal_receipt(
            _CausalStore(wrong_evidence, {"id": 1}), identity, "treatment-warning")


def test_privacy_receipt_handles_missing_access_bases(monkeypatch):
    class Store:
        def query_one(self, *_args, **_kwargs):
            return {"id": 1}

    class Policy:
        def __init__(self, _store):
            pass

        def can_read_field(self, *_args, **_kwargs):
            return AccessDecision(False)

    monkeypatch.setattr(protocol, "CommunicationPolicy", Policy)
    receipt = protocol._privacy_receipt(
        Store(), protocol.FixtureIdentity(1, 2, 3, 4, 5, 6), "control-neutral")
    assert receipt["sender_access_basis"] is None
    assert receipt["recipient_access_basis"] is None


@pytest.mark.parametrize("field,value", [
    ("unit_price_cents", 99),
    ("total_cents", 999),
    ("inventory", 0),
    ("entry_sum_cents", 1),
    ("entry_ids", [1]),
    ("policy_contract_hash", "wrong"),
])
def test_protocol_validator_rejects_each_economic_invariant(field, value):
    receipts = _valid_receipts()
    receipts["control-none"]["quantity"][field] = value
    with pytest.raises(AssertionError, match="economic/privacy"):
        protocol._validate_protocol_results("same", "same", receipts)


def test_protocol_validator_rejects_every_global_and_causal_refutation():
    receipts = _valid_receipts()
    assert protocol._validate_protocol_results("same", "same", receipts) == (
        {"control-none": 10, "control-neutral": 10, "treatment-warning": 5}, [])
    with pytest.raises(AssertionError, match="source checkpoint changed"):
        protocol._validate_protocol_results("before", "after", receipts)

    changed = _valid_receipts()
    changed["control-none"]["quantity"]["qty"] = 9
    with pytest.raises(AssertionError, match="quantities refuted"):
        protocol._validate_protocol_results("same", "same", changed)
    outside = _valid_receipts()
    outside["control-none"]["privacy"]["outside_access"] = True
    with pytest.raises(AssertionError, match="economic/privacy"):
        protocol._validate_protocol_results("same", "same", outside)

    for arm, field, value, match in (
        ("control-none", "message_observation_edges", 1, "unexpectedly"),
        ("control-neutral", "message_observation_edges", 0, "lacks"),
        ("treatment-warning", "warning_chain_edges", 4, "five-edge"),
    ):
        altered = _valid_receipts()
        altered[arm]["causal"][field] = value
        with pytest.raises(AssertionError, match=match):
            protocol._validate_protocol_results("same", "same", altered)

    unrelated = _valid_receipts()
    for index, arm in enumerate(unrelated):
        unrelated[arm]["table_hashes"]["unexpected_table"] = str(index)
    with pytest.raises(AssertionError, match="cross-branch isolation"):
        protocol._validate_protocol_results("same", "same", unrelated)


def test_variant_validator_checks_each_hash_family():
    base = {
        "one": {"authoritative_sha256": "a", "derived_sha256": "d",
                "projection_sha256": "p"},
        "two": {"authoritative_sha256": "a", "derived_sha256": "d",
                "projection_sha256": "p"},
    }
    protocol._validate_variant_hashes("arm", base)
    for field in ("authoritative_sha256", "derived_sha256", "projection_sha256"):
        changed = copy.deepcopy(base)
        changed["two"][field] = "different"
        with pytest.raises(AssertionError, match="identical hashes"):
            protocol._validate_variant_hashes("arm", changed)

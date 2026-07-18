"""Executable frozen 30-tick supplier-warning causal protocol."""
from __future__ import annotations

import json
import random
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from agents.memory import Memory
from agents.policies import (
    SUPPLIER_WARNING_BODY,
    SUPPLIER_WARNING_POLICY_CONTRACT_HASH,
    SUPPLIER_WARNING_POLICY_ID,
    SUPPLIER_WARNING_SUBJECT,
    supplier_warning_decision,
)
from agents.prompts import ContextBuilder
from agents.runtime import AgentRuntime
from causal import CausalLinkService
from communications.delivery import CommunicationDelivery
from communications.policy import CommunicationPolicy, MessageField, Principal
from communications.projections import AgentKnowledgeProjection
from engine.actions import ActionExecutor
from engine.core import Economy
from engine.schema import SCHEMA_VERSION
from engine.store import Store, load_json
from server.projections.snapshot import build_snapshot
from world.phases import phase_names_for_semantics

from .hashing import canonical_hashes, canonical_projection_hash


PROTOCOL_ID = "world-os-v8-supplier-warning-v1"
SEED = 20_260_718
NEUTRAL_BODY = "Batch 2026-07 is cleared. Continue the scheduled 10-unit purchase."
ARMS = {
    "control-none": None,
    "control-neutral": NEUTRAL_BODY,
    "treatment-warning": SUPPLIER_WARNING_BODY,
}
ALLOWED_DIFFERENCE_TABLES = {
    "account_ledger_totals", "accounts", "action_proposals", "agent_decisions",
    "beliefs", "causal_links", "comm_audiences", "comm_deliveries",
    "comm_disclosure_authorities", "comm_disclosures", "comm_messages", "comm_threads",
    "events", "firms", "ledger_entries", "memories", "run_meta", "transactions",
}


@dataclass(frozen=True)
class FixtureIdentity:
    sender_agent_id: int
    retailer_agent_id: int
    outside_agent_id: int
    retailer_account_id: int
    supplier_firm_id: int
    supplier_account_id: int

    def as_dict(self) -> dict:
        return {
            "sender_agent_id": self.sender_agent_id,
            "retailer_agent_id": self.retailer_agent_id,
            "outside_agent_id": self.outside_agent_id,
            "retailer_account_id": self.retailer_account_id,
            "supplier_firm_id": self.supplier_firm_id,
            "supplier_account_id": self.supplier_account_id,
        }


class ScenarioFault(RuntimeError):
    pass


def _config() -> dict:
    return {
        "engine_semantics_version": 8,
        "central_bank": {"max_step_bps": 50, "min_rate_bps": 0, "max_rate_bps": 2_000},
        "communications": {
            "autonomous_scripted_enabled": False,
        },
    }


def _economy(store: Store, config: dict) -> Economy:
    economy = Economy(store, config, random.Random(SEED), random.Random(SEED + 1))
    economy.ensure_system_accounts()
    return economy


def _create_bank(economy: Economy) -> int:
    reserve = economy.ledger.create_account(
        "bank", None, "reserve", label="Protocol Bank:reserve", opening_cents=1_000_000)
    equity = economy.ledger.create_account(
        "bank", None, "equity", label="Protocol Bank:equity")
    bank_id = economy.store.insert(
        "banks", name="Protocol Bank", reserve_account_id=reserve,
        equity_account_id=equity, risk_policy_json="{}",
        reserve_requirement_bps=1_000, status="open")
    economy.store.execute(
        "UPDATE accounts SET owner_id=? WHERE id IN (?,?)", (bank_id, reserve, equity))
    return int(bank_id)


def _create_agent(
    economy: Economy, bank_id: int, *, name: str, role: str, cash: int,
    population_tier: str,
) -> tuple[int, int]:
    agent_id = economy.store.insert(
        "agents", name=name, kind="citizen", occupation=role.replace("_", " "),
        role=role, age=35, health="healthy", alive=1, arrived_tick=0,
        population_tier=population_tier,
    )
    account_id = economy.ledger.create_account(
        "agent", agent_id, "checking", bank_id=bank_id,
        label=f"{name}:checking", opening_cents=cash)
    economy.store.update("agents", agent_id, checking_account_id=account_id)
    return int(agent_id), int(account_id)


def create_common_checkpoint(path: str | Path) -> tuple[Store, FixtureIdentity]:
    path = Path(path)
    config = _config()
    store = Store(str(path))
    store.init_run_meta("world-os-v8-common", SEED, config)
    economy = _economy(store, config)
    bank_id = _create_bank(economy)
    sender, _ = _create_agent(
        economy, bank_id, name="Supplier Officer", role="supplier_officer",
        cash=10_000, population_tier="core")
    retailer, retailer_account = _create_agent(
        economy, bank_id, name="Retailer Manager", role="retailer_manager",
        cash=10_000, population_tier="periphery")
    outside, _ = _create_agent(
        economy, bank_id, name="Outside Agent", role="citizen",
        cash=10_000, population_tier="periphery")
    supplier_account = economy.ledger.create_account(
        "firm", None, "checking", bank_id=bank_id, label="Supplier Firm:operating")
    firm_id = store.insert(
        "firms", name="Supplier Firm", sector="goods", founder_agent_id=sender,
        status="private", product_json=json.dumps({
            "product": "fixture good", "unit_price_cents": 100,
        }, sort_keys=True), account_id=supplier_account, founded_tick=0,
        inventory=100, currency_code="USD")
    store.execute(
        "UPDATE accounts SET owner_id=? WHERE id=?", (firm_id, supplier_account))
    config["communications"]["supplier_warning_policy"] = {
        "retailer_agent_id": retailer,
        "supplier_firm_id": firm_id,
    }
    store.execute(
        "UPDATE run_meta SET config_json=?,tick=4,status='paused',phase=NULL,"
        "active_tick=NULL,next_phase='NIGHT_CLOSE',phase_state_json='{}' WHERE id=1",
        (json.dumps(config, sort_keys=True),),
    )
    checkpoint_id = store.insert(
        "checkpoints", tick=4, path=str(path.resolve()), created_at="frozen-logical-tick-4")
    identity = FixtureIdentity(
        sender_agent_id=sender,
        retailer_agent_id=retailer,
        outside_agent_id=outside,
        retailer_account_id=retailer_account,
        supplier_firm_id=int(firm_id),
        supplier_account_id=int(supplier_account),
    )
    verify_fixture(store, identity)
    if checkpoint_id <= 0:
        raise AssertionError("common checkpoint row was not created")
    return store, identity


def verify_fixture(store: Store, identity: FixtureIdentity) -> None:
    meta = store.get_meta()
    config = load_json(meta["config_json"], {}) or {}
    if int(meta["tick"]) != 4 or int(config.get("engine_semantics_version", 0)) != 8:
        raise AssertionError("fixture must be frozen at tick 4 under semantics 8")
    if int(meta["schema_version"]) != SCHEMA_VERSION or SCHEMA_VERSION != 12:
        raise AssertionError("fixture requires schema 12")
    agents = store.query(
        "SELECT id,role,alive FROM agents WHERE id IN (?,?,?) ORDER BY id",
        (identity.sender_agent_id, identity.retailer_agent_id, identity.outside_agent_id),
    )
    if len(agents) != 3 or not all(bool(row["alive"]) for row in agents):
        raise AssertionError("all three protocol agents must be alive")
    roles = {int(row["id"]): str(row["role"]) for row in agents}
    if roles[identity.sender_agent_id] != "supplier_officer":
        raise AssertionError("sender must have supplier_officer role")
    firm = store.query_one(
        "SELECT inventory,product_json,status FROM firms WHERE id=?",
        (identity.supplier_firm_id,),
    )
    product = load_json(firm["product_json"], {}) if firm else {}
    if (firm is None or firm["status"] == "bankrupt" or int(firm["inventory"]) < 100
            or int(product.get("unit_price_cents", 0)) != 100):
        raise AssertionError("supplier fixture inventory/price/status precondition failed")
    cash = int(store.scalar(
        "SELECT balance_cents FROM accounts WHERE id=?",
        (identity.retailer_account_id,), default=0))
    if cash < 1_000:
        raise AssertionError("retailer cannot fund the scheduled ten-unit purchase")
    if int(store.scalar("SELECT COUNT(*) FROM comm_messages", default=0)) != 0:
        raise AssertionError("common checkpoint must contain no threaded messages")


def _backup(source: Store, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    target = sqlite3.connect(destination)
    try:
        source.conn.backup(target)
    finally:
        target.close()


def _runtime(economy: Economy, config: dict, executor: ActionExecutor) -> AgentRuntime:
    runtime = object.__new__(AgentRuntime)
    runtime.e = economy
    runtime.store = economy.store
    runtime.config = config
    runtime.mem = Memory(economy.store, config)
    runtime.executor = executor
    runtime.causal = CausalLinkService(economy.store)
    runtime.participant = SimpleNamespace(complete=lambda *_args: None)
    return runtime


def _execute_purchase(
    economy: Economy, config: dict, identity: FixtureIdentity, projection: dict,
    executor: ActionExecutor,
) -> None:
    context = {
        "authorized_inbox": projection["items"],
        "state": {
            "checking_balance": economy.ledger.balance(identity.retailer_account_id),
        },
    }
    builder = object.__new__(ContextBuilder)
    builder.config = config
    builder.store = economy.store
    retailer = economy.store.query_one(
        "SELECT * FROM agents WHERE id=?", (identity.retailer_agent_id,))
    builder._add_supplier_warning_policy_input(context, retailer, 6)
    envelope = supplier_warning_decision(context["supplier_warning_policy_input"])
    _runtime(economy, config, executor).execute_decisions(6, [{
        "agent_id": identity.retailer_agent_id,
        "purpose": "decision",
        "envelope": envelope,
        "reasoning": envelope["reasoning"],
        "llm_call_id": None,
        "communication_sources": projection["sources"],
        "communication_read_context_key": projection["read_context_key"],
    }])


def _phase_effect(
    phase: str,
    *,
    tick: int,
    arm: str,
    economy: Economy,
    config: dict,
    identity: FixtureIdentity,
    executor: ActionExecutor,
    state: dict,
) -> None:
    if phase == "INBOX_DELIVERY":
        CommunicationDelivery(economy.store, config).deliver_due(tick)
    elif phase == "MORNING" and tick == 6:
        projection_builder = AgentKnowledgeProjection(economy.store, config)
        projection = projection_builder.build(identity.retailer_agent_id, tick)
        projection_builder.persist_read_context(identity.retailer_agent_id, tick, projection)
        state["projection"] = projection
    elif phase == "EXECUTION" and tick == 5 and ARMS[arm] is not None:
        result = executor.execute_action(tick, identity.sender_agent_id, {
            "type": "send_message",
            "audience": {"kind": "direct", "agent_ids": [identity.retailer_agent_id]},
            "subject": SUPPLIER_WARNING_SUBJECT,
            "body": ARMS[arm],
        })
        if not result.get("ok"):
            raise AssertionError(f"tick-5 communication failed: {result}")
        state["message_id"] = int(result["message_id"])
    elif phase == "EXECUTION" and tick == 6:
        projection = state.get("projection")
        if projection is None:
            projection = AgentKnowledgeProjection(economy.store, config).build(
                identity.retailer_agent_id, tick)
        _execute_purchase(economy, config, identity, projection, executor)
    elif phase == "FINALIZE":
        economy.store.insert(
            "projection_commits", tick=tick, phase="FINALIZE",
            domains_json='["causal","communications","events","snapshot"]',
            created_event_id=None,
        )
        economy.store.execute(
            "UPDATE run_meta SET tick=?,phase=NULL,active_tick=NULL,next_phase='NIGHT_CLOSE' "
            "WHERE id=1",
            (tick,),
        )


def run_branch(
    path: str | Path,
    *,
    arm: str,
    identity: FixtureIdentity,
    start_tick: int = 5,
    end_tick: int = 30,
    faults: set[tuple[int, str, str]] | None = None,
) -> None:
    if arm not in ARMS:
        raise ValueError(f"unknown protocol arm: {arm}")
    store = Store(str(path), create=False)
    try:
        meta = store.get_meta()
        config = load_json(meta["config_json"], {}) or {}
        economy = _economy(store, config)
        executor = ActionExecutor(economy)
        state: dict[str, Any] = {}
        pending_faults = set(faults or set())
        fired_faults: set[tuple[int, str, str]] = set()
        phases = phase_names_for_semantics(8)
        for tick in range(int(start_tick), int(end_tick) + 1):
            for index, phase in enumerate(phases):
                attempts = 0
                while True:
                    attempts += 1
                    store.execute(
                        "UPDATE run_meta SET status='running',active_tick=?,phase=?,next_phase=? "
                        "WHERE id=1",
                        (tick, phase, phase),
                    )
                    before = (tick, phase, "before")
                    after = (tick, phase, "after")
                    try:
                        if before in pending_faults and before not in fired_faults:
                            fired_faults.add(before)
                            raise ScenarioFault(f"fault before tick {tick} {phase}")
                        with store.savepoint(f"protocol_{tick}_{index}_{attempts}"):
                            _phase_effect(
                                phase, tick=tick, arm=arm, economy=economy,
                                config=config, identity=identity, executor=executor,
                                state=state,
                            )
                            if after in pending_faults and after not in fired_faults:
                                fired_faults.add(after)
                                raise ScenarioFault(f"fault after tick {tick} {phase}")
                        break
                    except ScenarioFault:
                        if attempts >= 2:
                            raise
                next_phase = phases[index + 1] if index + 1 < len(phases) else "NIGHT_CLOSE"
                store.execute(
                    "UPDATE run_meta SET next_phase=? WHERE id=1", (next_phase,))
        store.execute(
            "UPDATE run_meta SET status='finished',tick=?,phase=NULL,active_tick=NULL,"
            "next_phase='NIGHT_CLOSE' WHERE id=1",
            (int(end_tick),),
        )
    finally:
        store.close()


def _branch_identity(store: Store, arm: str) -> None:
    store.execute(
        "UPDATE run_meta SET run_id=?,parent_run_id='world-os-v8-common',fork_tick=4,"
        "status='paused' WHERE id=1",
        (f"world-os-v8-{arm}",),
    )


def _quantity_receipt(store: Store, identity: FixtureIdentity) -> dict:
    proposals = store.query(
        "SELECT id,payload_json,result_json FROM action_proposals "
        "WHERE tick=6 AND actor_id=? AND action_type='buy_goods' "
        "AND validation_status='accepted' ORDER BY id",
        (identity.retailer_agent_id,),
    )
    if len(proposals) != 1:
        raise AssertionError("branch must contain exactly one accepted tick-6 purchase")
    proposal = proposals[0]
    payload = load_json(proposal["payload_json"], {}) or {}
    result = load_json(proposal["result_json"], {}) or {}
    transaction = store.query_one(
        "SELECT id FROM transactions WHERE tick=6 AND kind='goods_purchase'")
    if transaction is None:
        raise AssertionError("goods purchase transaction is absent")
    entries = store.query(
        "SELECT id,delta_cents FROM ledger_entries WHERE txn_id=? ORDER BY id",
        (int(transaction["id"]),),
    )
    return {
        "proposal_id": int(proposal["id"]),
        "qty": int(result["qty"]),
        "unit_price_cents": int(result["unit_price_cents"]),
        "total_cents": int(result["total_cents"]),
        "inventory": int(store.scalar(
            "SELECT inventory FROM firms WHERE id=?", (identity.supplier_firm_id,))),
        "transaction_id": int(transaction["id"]),
        "entry_ids": [int(row["id"]) for row in entries],
        "entry_sum_cents": sum(int(row["delta_cents"]) for row in entries),
        "policy_contract_hash": payload.get("policy_contract_hash"),
        "policy_input_hash": payload.get("policy_input_hash"),
    }


def _causal_receipt(store: Store, identity: FixtureIdentity, arm: str) -> dict:
    rows = [dict(row) for row in store.query("SELECT * FROM causal_links ORDER BY id")]
    message = store.query_one(
        "SELECT id FROM comm_messages WHERE sender_agent_id=? ORDER BY id LIMIT 1",
        (identity.sender_agent_id,),
    )
    if arm != "treatment-warning":
        return {
            "message_observation_edges": sum(
                1 for row in rows if row["source_kind"] == "message"
                and row["target_kind"] == "memory" and row["relation"] == "observed"),
            "warning_chain_edges": 0,
        }
    if message is None:
        raise AssertionError("treatment warning message is absent")
    expected = [
        ("message", "memory", "observed", "engine"),
        ("memory", "belief", "triggered", "engine"),
        ("belief", "action_proposal", "motivated", "actor_claim"),
        ("action_proposal", "event", "triggered", "engine"),
        ("event", "ledger_transaction", "settled", "engine"),
    ]
    matched = []
    previous_target = None
    for source_kind, target_kind, relation, authority in expected:
        candidates = [
            row for row in rows
            if row["source_kind"] == source_kind
            and row["target_kind"] == target_kind
            and row["relation"] == relation
            and row["authority"] == authority
            and (previous_target is None or row["source_id"] == previous_target)
        ]
        if len(candidates) != 1:
            raise AssertionError(
                f"expected exactly one {source_kind}->{target_kind} {relation} edge")
        matched.append(candidates[0])
        previous_target = str(candidates[0]["target_id"])
    if matched[0]["source_id"] != str(message["id"]):
        raise AssertionError("causal chain begins at the wrong message")
    if matched[2]["method"] != SUPPLIER_WARNING_POLICY_ID:
        raise AssertionError("motivated edge lacks frozen policy method")
    evidence = load_json(matched[-1]["evidence_json"], {}) or {}
    if len(evidence.get("entry_ids", [])) != 2:
        raise AssertionError("settled edge must cite exactly two ledger entries")
    return {
        "message_observation_edges": 1,
        "warning_chain_edges": len(matched),
        "edges": [
            {
                "id": int(row["id"]), "source_kind": row["source_kind"],
                "source_id": row["source_id"], "target_kind": row["target_kind"],
                "target_id": row["target_id"], "relation": row["relation"],
                "authority": row["authority"], "method": row["method"],
            }
            for row in matched
        ],
    }


def _privacy_receipt(store: Store, identity: FixtureIdentity, arm: str) -> dict:
    message = store.query_one("SELECT id FROM comm_messages ORDER BY id LIMIT 1")
    if message is None:
        return {"message_created": False, "outside_access": False}
    message_id = int(message["id"])
    policy = CommunicationPolicy(store)
    sender = policy.can_read_field(
        Principal(f"agent:{identity.sender_agent_id}", agent_id=identity.sender_agent_id),
        message_id, MessageField.BODY, 30,
    )
    recipient = policy.can_read_field(
        Principal(
            f"agent:{identity.retailer_agent_id}", agent_id=identity.retailer_agent_id),
        message_id, MessageField.BODY, 30,
    )
    outside = policy.can_read_field(
        Principal(f"agent:{identity.outside_agent_id}", agent_id=identity.outside_agent_id),
        message_id, MessageField.EXISTENCE, 30,
    )
    return {
        "message_created": True,
        "arm": arm,
        "sender_access_basis": sender.basis.value if sender.basis else None,
        "recipient_access_basis": recipient.basis.value if recipient.basis else None,
        "outside_access": bool(outside.allowed),
    }


def _receipt(path: Path, identity: FixtureIdentity, arm: str) -> dict:
    store = Store(str(path), create=False)
    try:
        hashes = canonical_hashes(store)
        projection = build_snapshot(
            store, Principal("ordinary"), as_of_tick=30,
            domains=("summary", "events", "communications"),
        )
        return {
            "arm": arm,
            "quantity": _quantity_receipt(store, identity),
            "causal": _causal_receipt(store, identity, arm),
            "privacy": _privacy_receipt(store, identity, arm),
            "authoritative_sha256": hashes["authoritative_sha256"],
            "derived_sha256": hashes["derived_sha256"],
            "projection_sha256": canonical_projection_hash(projection),
            "table_hashes": {
                table: result["sha256"] for table, result in hashes["tables"].items()
            },
        }
    finally:
        store.close()


def _prepare_branch(common: Store, path: Path, arm: str) -> None:
    _backup(common, path)
    branch = Store(str(path), create=False)
    try:
        _branch_identity(branch, arm)
    finally:
        branch.close()


def _unrelated_differences(receipts: dict[str, dict]) -> list[str]:
    arms = sorted(receipts)
    all_tables = sorted(receipts[arms[0]]["table_hashes"])
    differences = []
    for table in all_tables:
        values = {receipts[arm]["table_hashes"][table] for arm in arms}
        if len(values) > 1 and table not in ALLOWED_DIFFERENCE_TABLES:
            differences.append(table)
    return differences


def _validate_variant_hashes(arm: str, arm_variants: dict[str, dict]) -> None:
    authoritative = {
        value["authoritative_sha256"] for value in arm_variants.values()}
    derived = {value["derived_sha256"] for value in arm_variants.values()}
    projections = {value["projection_sha256"] for value in arm_variants.values()}
    if len(authoritative) != 1 or len(derived) != 1 or len(projections) != 1:
        raise AssertionError(f"{arm} variants do not reproduce identical hashes")


def _validate_protocol_results(
    common_before: str,
    common_after: str,
    receipts: dict[str, dict],
) -> tuple[dict[str, int], list[str]]:
    if common_before != common_after:
        raise AssertionError("source checkpoint changed while branches ran")
    expected_quantities = {
        "control-none": 10, "control-neutral": 10, "treatment-warning": 5}
    actual_quantities = {
        arm: int(receipt["quantity"]["qty"]) for arm, receipt in receipts.items()}
    if actual_quantities != expected_quantities:
        raise AssertionError(f"protocol quantities refuted: {actual_quantities}")
    for arm, receipt in receipts.items():
        quantity = receipt["quantity"]
        if (quantity["unit_price_cents"] != 100
                or quantity["total_cents"] != quantity["qty"] * 100
                or quantity["inventory"] != 100 - quantity["qty"]
                or quantity["entry_sum_cents"] != 0
                or len(quantity["entry_ids"]) != 2
                or quantity["policy_contract_hash"] != SUPPLIER_WARNING_POLICY_CONTRACT_HASH
                or receipt["privacy"]["outside_access"]):
            raise AssertionError(f"{arm} failed economic/privacy invariants")
    if receipts["control-none"]["causal"]["message_observation_edges"] != 0:
        raise AssertionError("no-message control unexpectedly has a message edge")
    if receipts["control-neutral"]["causal"]["message_observation_edges"] != 1:
        raise AssertionError("neutral control lacks its observation edge")
    if receipts["treatment-warning"]["causal"]["warning_chain_edges"] != 5:
        raise AssertionError("treatment lacks the exact five-edge chain")
    unrelated = _unrelated_differences(receipts)
    if unrelated:
        raise AssertionError("cross-branch isolation failed: " + ",".join(unrelated))
    return actual_quantities, unrelated


def run_protocol(output_root: str | Path) -> dict:
    """Run all arms/variants to tick 30 and write machine/human receipts."""
    output_root = Path(output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    common_path = output_root / "common-tick-4.db"
    common, identity = create_common_checkpoint(common_path)
    try:
        common_before = canonical_hashes(common)["authoritative_sha256"]
        receipts: dict[str, dict] = {}
        variants: dict[str, dict] = {}
        for arm in ARMS:
            arm_variants = {}
            uninterrupted = output_root / f"{arm}-uninterrupted.db"
            _prepare_branch(common, uninterrupted, arm)
            run_branch(uninterrupted, arm=arm, identity=identity)
            arm_variants["uninterrupted"] = _receipt(uninterrupted, identity, arm)

            replayed = output_root / f"{arm}-replayed.db"
            _prepare_branch(common, replayed, arm)
            run_branch(replayed, arm=arm, identity=identity)
            arm_variants["replayed"] = _receipt(replayed, identity, arm)

            resumed = output_root / f"{arm}-resumed.db"
            _prepare_branch(common, resumed, arm)
            run_branch(resumed, arm=arm, identity=identity, end_tick=15)
            run_branch(resumed, arm=arm, identity=identity, start_tick=16, end_tick=30)
            arm_variants["resumed"] = _receipt(resumed, identity, arm)

            faulted = output_root / f"{arm}-phase-fault-resumed.db"
            _prepare_branch(common, faulted, arm)
            run_branch(
                faulted, arm=arm, identity=identity,
                faults={(6, "INBOX_DELIVERY", "after")},
            )
            arm_variants["phase_fault_resumed"] = _receipt(faulted, identity, arm)

            _validate_variant_hashes(arm, arm_variants)
            receipts[arm] = arm_variants["uninterrupted"]
            variants[arm] = {
                name: {
                    "authoritative_sha256": value["authoritative_sha256"],
                    "derived_sha256": value["derived_sha256"],
                    "projection_sha256": value["projection_sha256"],
                }
                for name, value in arm_variants.items()
            }
        common_after = canonical_hashes(common)["authoritative_sha256"]
    finally:
        common.close()

    actual_quantities, unrelated = _validate_protocol_results(
        common_before, common_after, receipts)

    result = {
        "protocol_id": PROTOCOL_ID,
        "seed": SEED,
        "semantics_version": 8,
        "schema_version": 12,
        "policy_contract_sha256": SUPPLIER_WARNING_POLICY_CONTRACT_HASH,
        "common_checkpoint_authoritative_sha256": common_before,
        "source_checkpoint_unchanged": common_before == common_after,
        "fixture": identity.as_dict(),
        "quantities": actual_quantities,
        "treatment_effect_units": -5,
        "unrelated_difference_tables": unrelated,
        "branches": receipts,
        "variants": variants,
        "status": "passed",
    }
    receipt_path = output_root / "protocol-receipt.json"
    receipt_path.write_text(
        json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    summary = [
        f"# {PROTOCOL_ID} receipt",
        "",
        "Status: **passed**",
        "",
        f"- Common checkpoint hash: `{common_before}`",
        "- Control (no message): 10 units",
        "- Control (neutral message): 10 units",
        "- Treatment (warning): 5 units",
        "- Treatment effect: -5 units",
        "- Treatment causal chain: 5/5 exact qualified edges",
        "- Source checkpoint unchanged: yes",
        "- Uninterrupted, resumed, phase-fault-resumed, and replayed hashes: identical",
        "- Unrelated cross-branch differences: none",
    ]
    (output_root / "SUMMARY.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    return result

"""Three-branch Agent Commons supplier-warning acceptance protocol."""
from __future__ import annotations

import json
from pathlib import Path
import random
import sqlite3

from agents.memory import Memory
from causal import CausalLinkService
from engine.actions import ActionExecutor
from engine.core import Economy
from engine.store import Store, load_json
from world.commons import CommonsService

from .supplier_warning_experiment import (
    FixtureIdentity,
    NEUTRAL_BODY,
    SUPPLIER_WARNING_BODY,
    create_common_checkpoint,
)


PROTOCOL_ID = "world-os-v10-commons-supplier-warning-v1"
POLICY_ID = "commons-supplier-warning-policy-v1"
ARMS = ("control-none", "control-neutral", "treatment-warning")


def _backup(source: Store, destination: Path) -> None:
    target = sqlite3.connect(destination)
    try:
        source.conn.backup(target)
    finally:
        target.close()


def _economy(store: Store, config: dict) -> Economy:
    return Economy(store, config, random.Random(20_260_718), random.Random(20_260_719))


def _exposure_policy_input(store: Store, identity: FixtureIdentity) -> dict:
    rows = store.query(
        "SELECT x.id AS exposure_id,i.body,c.id AS claim_id,c.predicate,c.value_json,"
        "c.truth_status,p.id AS impression_id,p.read_tick,e.id AS entry_id "
        "FROM information_exposures x JOIN information_items i ON i.id=x.item_id "
        "JOIN claims c ON c.id=i.claim_id JOIN commons_entries e "
        "ON e.information_item_id=i.id JOIN commons_feed_impressions p "
        "ON p.entry_id=e.id AND p.viewer_agent_id=x.agent_id AND p.exposure_id=x.id "
        "WHERE x.agent_id=? AND x.channel='commons' AND p.read_tick IS NOT NULL "
        "ORDER BY x.id", (identity.retailer_agent_id,))
    exposures = [{
        "exposure_id": int(row["exposure_id"]),
        "impression_id": int(row["impression_id"]),
        "entry_id": int(row["entry_id"]),
        "claim_id": int(row["claim_id"]),
        "predicate": str(row["predicate"]),
        "value": load_json(row["value_json"], None),
        "truth_status": str(row["truth_status"]),
        "body": str(row["body"]),
        "read_tick": int(row["read_tick"]),
    } for row in rows]
    firm = store.query_one(
        "SELECT inventory,product_json FROM firms WHERE id=?",
        (identity.supplier_firm_id,))
    product = load_json(firm["product_json"], {}) or {}
    return {
        "read_commons_exposures": exposures,
        "firm_id": identity.supplier_firm_id,
        "firm_inventory": int(firm["inventory"]),
        "unit_price_cents": int(product["unit_price_cents"]),
        "cash_cents": int(store.scalar(
            "SELECT balance_cents FROM accounts WHERE id=?",
            (identity.retailer_account_id,), default=0)),
    }


def _quantity(policy_input: dict) -> int:
    required = {"read_commons_exposures", "firm_id", "firm_inventory",
                "unit_price_cents", "cash_cents"}
    if set(policy_input) != required:
        raise AssertionError("Commons policy input is not branch-blind and closed")
    warning = any(
        item["predicate"] == "contaminated"
        and item["value"] is True
        and item["truth_status"] == "verified"
        and item["body"] == SUPPLIER_WARNING_BODY
        and item["read_tick"] == 6
        for item in policy_input["read_commons_exposures"])
    return 5 if warning else 10


def _run_branch(path: Path, arm: str, identity: FixtureIdentity) -> dict:
    store = Store(str(path), create=False)
    try:
        config = load_json(store.get_meta()["config_json"], {}) or {}
        economy = _economy(store, config)
        commons = CommonsService(economy, Memory(store, config))
        store.set_meta(run_id=f"world-os-v10-commons-{arm}", tick=5)
        entry = None
        feed = {"candidate_set_hash": None, "entries": []}
        read = None
        if arm != "control-none":
            is_warning = arm == "treatment-warning"
            source_event = store.log_event(
                5, "supplier_batch_tested", {"contaminated": is_warning},
                phase="COMMONS", subject_type="firm",
                subject_id=identity.supplier_firm_id, importance=1.0)
            claim = economy.information.create_claim(5, identity.sender_agent_id, {
                "claim_key": f"commons-supplier:{arm}", "subject_type": "firm",
                "subject_id": identity.supplier_firm_id,
                "predicate": "contaminated", "value": is_warning,
                "truth_status": "verified", "source_event_ids": [source_event],
            })
            body = SUPPLIER_WARNING_BODY if is_warning else NEUTRAL_BODY
            entry = commons.publish(
                identity.sender_agent_id, body=body, claim_id=claim["claim_id"])
        store.set_meta(tick=6)
        feed = commons.feed(identity.retailer_agent_id)
        if entry is not None:
            impression = next(item for item in feed["entries"] if item["id"] == entry["id"])
            read = commons.read(identity.retailer_agent_id, impression["impression_id"])
        policy_input = _exposure_policy_input(store, identity)
        qty = _quantity(policy_input)
        result = ActionExecutor(economy).execute_action(6, identity.retailer_agent_id, {
            "type": "buy_goods", "firm_id": identity.supplier_firm_id, "qty": qty,
        })
        if not result.get("ok"):
            raise AssertionError(f"Commons branch purchase failed: {result}")
        proposal_id = int(store.scalar(
            "SELECT MAX(id) FROM action_proposals WHERE actor_id=? AND tick=6",
            (identity.retailer_agent_id,), default=0))
        if policy_input["read_commons_exposures"]:
            claim_id = policy_input["read_commons_exposures"][-1]["claim_id"]
            belief = store.query_one(
                "SELECT id FROM beliefs WHERE agent_id=? AND key=?",
                (identity.retailer_agent_id, f"claim:{claim_id}"))
            CausalLinkService(store).create(
                "belief", int(belief["id"]), "action_proposal", proposal_id,
                "motivated", "actor_claim", created_tick=6,
                actor_agent_id=identity.retailer_agent_id, method=POLICY_ID,
                provenance={"closed_policy_input": True, "qty": qty})
        store.commit()
        return {
            "arm": arm, "qty": qty, "post_count": 1 if entry else 0,
            "impression_count": len(feed["entries"]),
            "read_count": 1 if read else 0,
            "exposure_count": len(policy_input["read_commons_exposures"]),
            "candidate_set_hash": feed["candidate_set_hash"],
            "causal_relations": [str(row["relation"]) for row in store.query(
                "SELECT relation FROM causal_links ORDER BY id")],
        }
    finally:
        store.close()


def run_protocol(output_root: str | Path) -> dict:
    output = Path(output_root).resolve()
    output.mkdir(parents=True, exist_ok=True)
    common, identity = create_common_checkpoint(output / "common-tick-4.db")
    try:
        config = load_json(common.get_meta()["config_json"], {}) or {}
        config["engine_semantics_version"] = 10
        config["information_economy"] = {
            "enabled": True, "base_reach": 0.15, "diffusion_window_ticks": 30}
        common.execute(
            "UPDATE run_meta SET config_json=? WHERE id=1",
            (json.dumps(config, sort_keys=True),))
        common.commit()
        receipts = {}
        for arm in ARMS:
            path = output / f"{arm}.db"
            _backup(common, path)
            receipts[arm] = _run_branch(path, arm, identity)
    finally:
        common.close()
    quantities = {arm: receipts[arm]["qty"] for arm in ARMS}
    if quantities != {
            "control-none": 10, "control-neutral": 10, "treatment-warning": 5}:
        raise AssertionError(f"Commons supplier-warning quantities refuted: {quantities}")
    result = {"protocol_id": PROTOCOL_ID, "quantities": quantities,
              "receipts": receipts}
    (output / "commons-supplier-warning-receipt.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result

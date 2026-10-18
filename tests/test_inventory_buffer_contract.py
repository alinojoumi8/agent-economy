"""Prospective buffer/demand contract; historical receipts stay on v1."""
from copy import deepcopy
import asyncio
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from agents.policies import probe_consumption_demand, scripted_decision
from engine.actions import ActionExecutor
from engine.inventory_audit import InventoryAudit
from engine.checkpoint_manifest import finalize_sqlite_artifact
from reports.inventory_buffer import buffer_inventory_evidence, demand_evidence
from reports.scale_economic_health import (
    _thresholds, evaluate_scale_ab, evaluate_scale_economic_health,
    render_scale_economic_health_markdown,
)
from run import open_run, replay_headless
from run_config import load_config
from tests.conftest import make_agent, make_bank
from world.replay_verify import verify_replay


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "runs/acceptance/scale-270-recovery-buffer-120.yaml"
THRESHOLDS = {"warmup_ticks": 1, "trailing_window_ticks": 60,
              "inventory_response_ticks": 5, "inventory_observation_ticks": 30}


def _inventory_fixture(closes, *, production=10):
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript("""
        CREATE TABLE firms(id INTEGER, name TEXT, status TEXT, region_id INTEGER,
                           currency_code TEXT, inventory INTEGER, product_json TEXT);
        CREATE TABLE events(id INTEGER PRIMARY KEY, tick INTEGER, kind TEXT, payload_json TEXT);
        CREATE TABLE scale_inventory_audit(tick INTEGER PRIMARY KEY, opening_json TEXT,
                                          closing_json TEXT, decision_agent_ids_json TEXT);
        CREATE TABLE scale_demand_audit(tick INTEGER, agent_id INTEGER, region_id INTEGER,
                                       currency_code TEXT, observation_json TEXT);
        CREATE TABLE scale_purchase_audit(proposal_id INTEGER PRIMARY KEY, tick INTEGER,
            buyer_id INTEGER, firm_id INTEGER, requested_units INTEGER, stock_units INTEGER,
            unit_price_cents INTEGER, cash_cents INTEGER, unavailable_reason TEXT, result_json TEXT,
            preceding_goods_event_id INTEGER, following_goods_event_id INTEGER);
        CREATE TABLE action_proposals(id INTEGER PRIMARY KEY, tick INTEGER, actor_id INTEGER,
                    action_type TEXT, payload_json TEXT, validation_status TEXT, result_json TEXT);
        CREATE TABLE agents(id INTEGER PRIMARY KEY, region_id INTEGER, checking_account_id INTEGER);
        CREATE TABLE accounts(id INTEGER PRIMARY KEY, currency_code TEXT);
        INSERT INTO agents VALUES (1,1,1);
        INSERT INTO accounts VALUES (1,'USD');
    """)
    firm = {"firm_id": 1, "region_id": 1, "currency_code": "USD", "inventory": closes[0]}
    for tick, closing in enumerate(closes[1:], 1):
        opening = dict(firm)
        sales = opening["inventory"] + production - closing
        assert sales >= 0
        firm["inventory"] = closing
        connection.execute("INSERT INTO scale_inventory_audit VALUES (?,?,?,?)",
                           (tick, json.dumps([opening]), json.dumps([firm]), "[]"))
        for kind, units, key in (("production", production, "units"), ("goods_sale", sales, "qty")):
            if units:
                connection.execute("INSERT INTO events(tick,kind,payload_json) VALUES (?,?,?)",
                                   (tick, kind, json.dumps({"firm_id": 1, key: units, "buyer_id": 1})))
    connection.execute("INSERT INTO firms VALUES (1,'Fixture','private',1,'USD',?,?)",
                       (closes[-1], json.dumps({"output_per_worker": 10})))
    return connection


def test_temporary_buffer_drawdown_is_valid_even_when_closing_below_opening():
    connection = _inventory_fixture([20] + [10, 13, 8, 12, 6, 15] * 10)
    ok, evidence = buffer_inventory_evidence(connection, 60, THRESHOLDS)
    assert ok, evidence
    firm = evidence["active_goods_firms"][0]
    assert firm["opening_inventory"] == 20
    assert firm["terminal_inventory"] == 15
    assert firm["accepted_sale_units"] > firm["production_units"]


@pytest.mark.parametrize("closes,reason", [
    ([30] + [max(0, 30 - tick) for tick in range(1, 61)], "sustained_depletion"),
    ([10] + [0] * 60, "persistent_empty_stock"),
])
def test_persistent_depletion_and_empty_stock_fail(closes, reason):
    ok, evidence = buffer_inventory_evidence(_inventory_fixture(closes), 60, THRESHOLDS)
    assert not ok
    assert reason in evidence["active_goods_firms"][0]["failures"]


def test_large_buffer_may_drain_while_it_covers_response_horizon():
    ok, evidence = buffer_inventory_evidence(
        _inventory_fixture([200 - tick for tick in range(61)]), 60, THRESHOLDS)
    assert ok, evidence


def test_oscillating_slow_depletion_is_reported_without_claiming_imminent_failure():
    changes = [-1, -1, -1, -1, -1, 1, 1, 1, 1, 0] * 6
    closes = [20]
    for change in changes:
        closes.append(closes[-1] + change)
    ok, evidence = buffer_inventory_evidence(_inventory_fixture(closes), 60, THRESHOLDS)
    assert ok, evidence
    trends = evidence["active_goods_firms"][0]["declining_windows"]
    assert trends
    assert all(trend["net_draw_units"] > 0 for trend in trends)
    assert all(trend["linear_ticks_to_empty"] > 5 for trend in trends)


def test_an_isolated_sellout_can_recover_within_response_horizon():
    closes = [20] * 30 + [0, 10, 20] + [20] * 28
    ok, evidence = buffer_inventory_evidence(_inventory_fixture(closes, production=20), 60, THRESHOLDS)
    assert ok, evidence
    assert evidence["active_goods_firms"][0]["maximum_unsafe_depletion_ticks"] == 1


@pytest.mark.parametrize("damage", ["missing_tick", "negative", "wrong_close", "wrong_terminal", "wrong_region"])
def test_inventory_measurement_fails_closed(damage):
    connection = _inventory_fixture([20] * 61)
    if damage == "missing_tick":
        connection.execute("DELETE FROM scale_inventory_audit WHERE tick=24")
    elif damage == "wrong_terminal":
        connection.execute("UPDATE firms SET inventory=99")
    else:
        row = json.loads(connection.execute(
            "SELECT closing_json FROM scale_inventory_audit WHERE tick=24").fetchone()[0])
        row[0]["region_id" if damage == "wrong_region" else "inventory"] = (
            2 if damage == "wrong_region" else -1 if damage == "negative" else 21)
        connection.execute("UPDATE scale_inventory_audit SET closing_json=? WHERE tick=24", (json.dumps(row),))
    assert not buffer_inventory_evidence(connection, 60, THRESHOLDS)[0]


def test_other_region_surplus_does_not_hide_a_firms_shortage():
    connection = _inventory_fixture([10] + [0] * 60)
    connection.execute("INSERT INTO firms VALUES (2,'Surplus','private',2,'EUR',10000,?)",
                       (json.dumps({"output_per_worker": 10}),))
    for tick in range(1, 61):
        for column in ("opening_json", "closing_json"):
            rows = json.loads(connection.execute(f"SELECT {column} FROM scale_inventory_audit WHERE tick=?", (tick,)).fetchone()[0])
            rows.append({"firm_id": 2, "region_id": 2, "currency_code": "EUR", "inventory": 10000})
            connection.execute(f"UPDATE scale_inventory_audit SET {column}=? WHERE tick=?", (json.dumps(rows), tick))
        for kind, key in (("production", "units"), ("goods_sale", "qty")):
            connection.execute("INSERT INTO events(tick,kind,payload_json) VALUES (?,?,?)", (tick, kind, json.dumps({"firm_id": 2, key: 10, "buyer_id": 2})))
    ok, evidence = buffer_inventory_evidence(connection, 60, THRESHOLDS)
    assert not ok
    assert evidence["active_goods_firms"][1]["passed"]


def _context(*, cash=100000, cap=2):
    return {"purpose": "decision", "tick": 60, "rng_seed": 7,
            "agent": {"id": 1, "health": "healthy", "dependents": 0},
            "state": {"checking_balance": cash, "currency_code": "USD"},
            "prices": [], "inventory_aware_shopping_enabled": True,
            "shopping_qty_cap": cap, "supply_recovery": {"active": True}}


CATALOG = [{"firm_id": 1, "product": "goods", "price": 500, "inventory": 0, "currency_code": "USD"}]


@pytest.mark.parametrize("cash,affordable", [(100000, 8), (10000, 2), (1000, 0)])
def test_demand_is_independent_of_zero_stock_and_shopping_guidance(cash, affordable):
    context = _context(cash=cash)
    original = deepcopy(context)
    probe = probe_consumption_demand("decision", context, CATALOG)
    assert probe["desired_units"] == 8
    assert probe["affordable_units"] == affordable
    assert probe["guidance_limited_units"] == max(0, affordable - 2)
    assert probe["affordability_limited_units"] == 8 - affordable
    assert context == original
    assert not any(action["type"] == "buy_goods" for action in scripted_decision("decision", context)["actions"])


def test_probe_does_not_invent_consumption_when_another_action_preempts_it():
    context = _context()
    context["civic_required_action"] = {"type": "attend_civic_appointment", "appointment_id": 1}
    probe = probe_consumption_demand("decision", context, CATALOG)
    assert probe["desired_units"] == probe["affordable_units"] == 0
    assert probe["eligibility"] == "policy_preempted"


def test_missing_catalog_retains_unpriced_desired_demand():
    probe = probe_consumption_demand("decision", _context(), [])
    assert probe["desired_units"] == probe["unpriced_units"] == 8
    assert probe["affordability_limited_units"] == 0


def _demand_fixture(*, requested=8, stock=3, cash=100000, pre_rejected=False):
    filled = 0 if pre_rejected else min(requested, stock, cash // 500)
    connection = _inventory_fixture([stock, stock - filled], production=0)
    connection.execute("DELETE FROM events")
    connection.execute("UPDATE scale_inventory_audit SET decision_agent_ids_json='[1]'")
    probe = probe_consumption_demand("decision", _context(), CATALOG)
    connection.execute("INSERT INTO scale_demand_audit VALUES (1,1,1,'USD',?)", (json.dumps(probe),))
    result = ({"ok": True, "qty": filled, "total_cents": filled * 500, "unit_price_cents": 500}
              if filled else {"ok": False, "reason": "actor not alive" if pre_rejected else "out of stock" if stock == 0 else "insufficient funds"})
    connection.execute("INSERT INTO action_proposals VALUES (1,1,1,'buy_goods',?,?,?)", (
        json.dumps({"firm_id": 1, "qty": requested}), "accepted" if filled else "rejected", json.dumps(result)))
    if not pre_rejected:
        connection.execute("INSERT INTO scale_purchase_audit VALUES (1,1,1,1,?,?,500,?,NULL,?,0,?)", (requested, stock, cash, json.dumps(result), 1 if filled else 0))
    if filled:
        connection.execute("INSERT INTO events(tick,kind,payload_json) VALUES (1,'goods_sale',?)", (json.dumps({"firm_id": 1, "buyer_id": 1, "qty": filled, "unit_price_cents": 500, "total_cents": filled * 500}),))
    return connection


@pytest.mark.parametrize("stock,cash,filled,stock_loss,cash_loss", [
    (3, 100000, 3, 5, 0), (20, 1000, 2, 0, 6), (3, 500, 1, 5, 2),
    (0, 100000, 0, 8, 0), (20, 0, 0, 0, 8), (20, 100000, 8, 0, 0),
])
def test_demand_reconciles_partial_fills_rejections_and_ordered_limits(stock, cash, filled, stock_loss, cash_loss):
    ok, evidence = demand_evidence(_demand_fixture(stock=stock, cash=cash), 1, THRESHOLDS)
    assert ok, evidence
    totals = evidence["totals"]
    assert totals["desired_units"] == totals["affordable_units"] == 8
    assert totals["submitted_units"] == 8
    assert totals["fulfilled_units"] == filled
    assert totals["stock_limited_units"] == stock_loss
    assert totals["cash_limited_units"] == cash_loss
    assert totals["guidance_limited_units"] == 6
    assert evidence["demand_adequacy_certified"] is False


def test_rejected_before_dispatch_is_separate_from_stock_and_cash():
    ok, evidence = demand_evidence(_demand_fixture(pre_rejected=True), 1, THRESHOLDS)
    assert ok, evidence
    assert evidence["totals"]["pre_execution_rejected_units"] == 8


def test_rejected_purchase_cannot_rewind_before_an_earlier_settlement():
    connection = _demand_fixture(requested=6, stock=9)
    result = json.dumps({"ok": False, "reason": "insufficient funds"})
    connection.execute("INSERT INTO action_proposals VALUES (2,1,1,'buy_goods',?,'rejected',?)",
                       (json.dumps({"firm_id": 1, "qty": 8}), result))
    connection.execute("INSERT INTO scale_purchase_audit VALUES (2,1,1,1,8,3,500,0,NULL,?,1,1)", (result,))
    ok, evidence = demand_evidence(connection, 1, THRESHOLDS)
    assert ok, evidence
    assert evidence["totals"]["stock_limited_units"] == 5
    assert evidence["totals"]["cash_limited_units"] == 3
    connection.execute("UPDATE scale_purchase_audit SET stock_units=9,preceding_goods_event_id=0,following_goods_event_id=0 WHERE proposal_id=2")
    assert not demand_evidence(connection, 1, THRESHOLDS)[0]


def test_empty_goods_boundary_replays_as_a_valid_explicit_sentinel(tmp_path, economy):
    bank = make_bank(economy)
    owner, _ = make_agent(economy, bank, cash=100000)
    buyer, _ = make_agent(economy, bank, cash=500)
    firm = economy.firms.found_firm(0, owner, "Empty shop", "retail", opening_capital_cents=1000)
    economy.store.update("firms", firm, inventory=0)
    economy.firms.inventory_audit = InventoryAudit(economy.store)
    result = ActionExecutor(economy).execute_action(1, buyer, {"type": "buy_goods", "firm_id": firm, "qty": 8})
    assert result == {"ok": False, "reason": "out of stock"}
    audit = economy.store.query_one("SELECT * FROM scale_purchase_audit")
    assert audit["preceding_goods_event_id"] == audit["following_goods_event_id"] == 0
    connection = economy.store.conn
    connection.commit()
    paths = [tmp_path / name for name in ("source.db", "replay.db")]
    for path in paths:
        with sqlite3.connect(path) as target:
            connection.backup(target)
    proof = verify_replay(*paths)
    assert proof["exact"], proof["differences"]
    with sqlite3.connect(paths[1]) as damaged:
        damaged.execute("UPDATE scale_purchase_audit SET following_goods_event_id=999999")
    assert not verify_replay(*paths)["exact"]


@pytest.mark.parametrize("damage", ["missing_probe", "missing_cohort", "missing_execution", "missing_rejected_execution", "wrong_sale", "wrong_result", "negative_probe"])
def test_demand_audit_fails_closed_for_missing_or_inconsistent_evidence(damage):
    connection = _demand_fixture(stock=0 if damage == "missing_rejected_execution" else 3)
    if damage == "missing_probe":
        connection.execute("DELETE FROM scale_demand_audit")
    elif damage == "missing_cohort":
        connection.execute("UPDATE scale_inventory_audit SET decision_agent_ids_json='[]'")
    elif damage.startswith("missing_"):
        connection.execute("DELETE FROM scale_purchase_audit")
    elif damage == "wrong_sale":
        connection.execute("DELETE FROM events")
    elif damage == "wrong_result":
        connection.execute("UPDATE scale_purchase_audit SET result_json='{}'")
    else:
        probe = probe_consumption_demand("decision", _context(), CATALOG)
        probe["desired_units"] = -1
        connection.execute("UPDATE scale_demand_audit SET observation_json=?", (json.dumps(probe),))
    assert not demand_evidence(connection, 1, THRESHOLDS)[0]


@pytest.mark.parametrize("damage", ["wrong_region", "wrong_currency", "unknown_reference", "mixed_unpriced",
                                    "altered_price_and_stock", "unknown_unavailable_reason", "zero_cap",
                                    "wrong_price", "wrong_total", "wrong_event_price", "wrong_boundary",
                                    "wrong_rejection", "null_cash", "wrong_reference_currency"])
def test_demand_does_not_certify_inconsistent_identity_or_loss_attribution(damage):
    connection = _demand_fixture(stock=0 if damage in {"unknown_unavailable_reason", "wrong_rejection"} else 3)
    if damage == "wrong_region":
        connection.execute("UPDATE scale_demand_audit SET region_id=999")
    elif damage == "wrong_currency":
        connection.execute("UPDATE scale_demand_audit SET currency_code='BOGUS'")
    elif damage == "altered_price_and_stock":
        connection.execute("UPDATE scale_purchase_audit SET stock_units=8,unit_price_cents=30000")
    elif damage == "unknown_unavailable_reason":
        connection.execute("UPDATE scale_purchase_audit SET unavailable_reason='invented'")
    elif damage == "wrong_reference_currency":
        connection.execute("UPDATE firms SET currency_code='EUR'")
    elif damage == "wrong_price":
        connection.execute("UPDATE scale_purchase_audit SET unit_price_cents=400")
    elif damage == "wrong_total":
        for table in ("scale_purchase_audit", "action_proposals"):
            connection.execute(f"UPDATE {table} SET result_json=json_set(result_json,'$.total_cents',1)")
    elif damage == "wrong_event_price":
        connection.execute("UPDATE events SET payload_json=json_set(payload_json,'$.unit_price_cents',1)")
    elif damage == "wrong_boundary":
        connection.execute("UPDATE scale_purchase_audit SET preceding_goods_event_id=following_goods_event_id")
    elif damage == "wrong_rejection":
        for table in ("scale_purchase_audit", "action_proposals"):
            connection.execute(f"UPDATE {table} SET result_json=json_set(result_json,'$.reason','insufficient funds')")
    elif damage == "null_cash":
        connection.execute("UPDATE scale_purchase_audit SET cash_cents=NULL")
    else:
        probe = probe_consumption_demand("decision", _context(), CATALOG)
        if damage == "unknown_reference":
            probe["reference_firm_id"] = 999
        elif damage == "zero_cap":
            probe.update(shopping_qty_cap=0, guidance_limited_units=8)
        else:
            probe.update(affordable_units=4, unpriced_units=4, guidance_limited_units=2,
                         reference_firm_id=None, reference_price_cents=None)
        connection.execute("UPDATE scale_demand_audit SET observation_json=?", (json.dumps(probe),))
    assert not demand_evidence(connection, 1, THRESHOLDS)[0]


def test_partial_purchase_audit_captures_authoritative_pre_transfer_limits(economy):
    bank = make_bank(economy)
    owner, _ = make_agent(economy, bank, cash=100000)
    buyer, _ = make_agent(economy, bank, cash=500)
    firm = economy.firms.found_firm(0, owner, "Shop", "retail", opening_capital_cents=1000)
    economy.store.update("firms", firm, inventory=3)
    economy.firms.inventory_audit = InventoryAudit(economy.store)
    result = ActionExecutor(economy).execute_action(1, buyer, {"type": "buy_goods", "firm_id": firm, "qty": 8})
    assert result["ok"] and result["qty"] == 1
    audit = economy.store.query_one("SELECT * FROM scale_purchase_audit")
    assert audit["requested_units"] == 8
    assert audit["stock_units"] == 3
    assert audit["cash_cents"] == 500
    assert json.loads(audit["result_json"]) == result
    assert economy.store.scalar("SELECT validation_status FROM action_proposals WHERE id=?", (audit["proposal_id"],)) == "accepted"
    assert economy.ledger.reconcile()[0]


def test_audit_retry_is_idempotent_only_for_identical_payload(economy):
    bank = make_bank(economy)
    actor, _ = make_agent(economy, bank, cash=100000)
    economy.firms.found_firm(0, actor, "Shop", "retail", opening_capital_cents=1000)
    audit = InventoryAudit(economy.store)
    agent = economy.store.query_one("SELECT * FROM agents WHERE id=?", (actor,))
    audit.open_tick(1)
    audit.open_tick(1)
    audit.record_cohort(1, [agent])
    audit.record_cohort(1, [agent])
    observation = probe_consumption_demand("decision", _context(), CATALOG)
    audit.record_demand(1, agent, "USD", observation)
    audit.record_demand(1, agent, "USD", observation)
    assert economy.store.scalar("SELECT COUNT(*) FROM scale_demand_audit") == 1
    with pytest.raises(ValueError, match="identity mismatch"):
        audit.record_demand(1, agent, "USD", {**observation, "desired_units": 7})
    with pytest.raises(ValueError, match="identity mismatch"):
        audit.record_cohort(1, [])


@pytest.mark.parametrize("ticks", [120, 1000])
def test_v2_profile_preserves_all_unrelated_policy_and_threshold_values(ticks):
    original = load_config(ROOT / f"runs/acceptance/scale-270-recovery-inventory-{ticks}.yaml")
    config = load_config(ROOT / f"runs/acceptance/scale-270-recovery-buffer-{ticks}.yaml")
    expected = deepcopy(original)
    expected["observability"] = {**expected.get("observability", {}), "scale_inventory_contract": "buffer-demand-v2"}
    expected["acceptance"]["scale_economic_health"].update(
        schema_version=2, inventory_response_ticks=5, inventory_observation_ticks=30)
    assert config == expected
    assert _thresholds(config)["schema_version"] == 2
    assert _thresholds(original)["schema_version"] == 1


def test_formal_buffer_receipt_rejects_a_short_run(tmp_path):
    from tests.test_scale_economic_health import _seed_fixture

    profile = ROOT / "runs/acceptance/scale-270-recovery-buffer-1000.yaml"
    fixture = _seed_fixture(tmp_path, profile=profile)
    receipt = evaluate_scale_economic_health(fixture.source, fixture.replay, fixture.runtime)

    assert receipt["schema"] == "agent-economy-scale-economic-health-v2"
    assert receipt["profile"]["required_ticks"] == 1000
    assert receipt["profile"]["diagnostic"] is False
    assert receipt["evidence"]["identity"]["checks"]["known_profile"] is True
    assert receipt["evidence"]["identity"]["checks"]["threshold_contract"] is True
    assert receipt["run"]["tick"] == 120
    assert receipt["checks"]["horizon_completed"] is False
    assert receipt["outcome"] == "failed"
    assert receipt["passed"] is False


def test_canonical_v2_receipt_requires_demand_and_does_not_promote_v1_comparisons(tmp_path):
    from types import SimpleNamespace
    from tests.test_scale_economic_health import _seed_fixture, _mutate_both
    fixture = _seed_fixture(tmp_path, profile=PROFILE)

    def populate(connection):
        InventoryAudit(SimpleNamespace(execute=connection.execute))
        connection.execute("DELETE FROM action_proposals")
        connection.execute("DELETE FROM events WHERE kind IN ('production','goods_sale')")
        catalog = [{**CATALOG[0], "price": 600, "currency_code": "NSD"}]
        probe = probe_consumption_demand("decision", _context(), catalog)
        result = json.dumps({"ok": True, "qty": 1, "unit_price_cents": 600, "total_cents": 600})
        for tick in range(1, 121):
            identity = {"firm_id": 1, "region_id": 1, "currency_code": "NSD"}
            connection.execute("INSERT INTO scale_inventory_audit VALUES (?,?,?,'[1]')", (
                tick, json.dumps([{**identity, "inventory": tick - 1}]), json.dumps([{**identity, "inventory": tick}])) )
            connection.execute("INSERT INTO scale_demand_audit VALUES (?,1,1,'NSD',?)", (tick, json.dumps(probe)))
            connection.execute("INSERT INTO action_proposals(id,tick,actor_id,action_type,payload_json,validation_status,result_json) VALUES (?,?,1,'buy_goods',?,'accepted',?)", (tick, tick, json.dumps({"firm_id": 1, "qty": 1}), result))
            boundaries = []
            for kind, payload in (("production", {"firm_id": 1, "units": 2, "unit_cost_cents": 180}),
                                  ("goods_sale", {"firm_id": 1, "buyer_id": 1, "qty": 1, "unit_price_cents": 600, "total_cents": 600})):
                boundaries.append(connection.execute("INSERT INTO events(tick,kind,payload_json) VALUES (?,?,?)", (tick, kind, json.dumps(payload))).lastrowid)
            connection.execute("INSERT INTO scale_purchase_audit VALUES (?,?,1,1,1,?,600,100000,NULL,?,?,?)", (tick, tick, tick + 1, result, *boundaries))

    _mutate_both(fixture, populate)
    receipt = evaluate_scale_economic_health(fixture.source, fixture.replay, fixture.runtime)
    assert receipt["schema"] == "agent-economy-scale-economic-health-v2"
    assert receipt["schema_version"] == 2
    assert receipt["passed"], {key: value for key, value in receipt["checks"].items() if not value}
    assert receipt == evaluate_scale_economic_health(fixture.source, fixture.replay, fixture.runtime)
    assert "demand_measurement_complete" in receipt["check_groups"]["operational"]
    markdown = render_scale_economic_health_markdown(receipt)
    assert "Household demand adequacy is not certified" in markdown
    assert "Limited by guidance" in markdown
    assert evaluate_scale_ab(receipt, receipt)["checks"]["receipt_schemas_valid"] is False
    _mutate_both(fixture, lambda connection: connection.execute(
        "UPDATE scale_inventory_audit SET closing_json=json_set(closing_json,'$[0].inventory',999) WHERE tick=75"))
    corrupt = evaluate_scale_economic_health(fixture.source, fixture.replay, fixture.runtime)
    assert corrupt["outcome"] == "failed"
    assert corrupt["checks"]["inventory_accounting_valid"] is False
    _mutate_both(fixture, lambda connection: connection.execute(
        "UPDATE scale_inventory_audit SET closing_json=json_set(closing_json,'$[0].inventory',75) WHERE tick=75"))
    _mutate_both(fixture, lambda connection: connection.execute("DELETE FROM scale_demand_audit WHERE tick=75"))
    missing = evaluate_scale_economic_health(fixture.source, fixture.replay, fixture.runtime)
    assert missing["outcome"] == "failed"
    assert missing["checks"]["demand_measurement_complete"] is False


@pytest.mark.parametrize("version", [1, 2, 6, 8, 21])
def test_audit_is_restricted_to_explicit_semantics7_lane(store, version):
    config = {"engine_semantics_version": version,
              "observability": {"scale_inventory_contract": "buffer-demand-v2"}}
    with pytest.raises(ValueError, match="semantics 7"):
        InventoryAudit.from_config(store, config)


def test_default_off_audit_creates_nothing(store):
    before = list(store.query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"))
    assert InventoryAudit.from_config(store, {}) is None
    assert before == list(store.query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"))


def test_opt_in_audit_replays_exactly_and_does_not_change_economic_actions(tmp_path):
    config = load_config(PROFILE)
    config["population"]["size"] = 12
    config["living_world"]["core_agents"] = 20
    config["behavior"].update(act_every=1, inventory_aware_shopping_activation_tick=2)
    config["budget"]["conversation_pairs"] = 0
    sources = []
    for enabled in (False, True):
        arm = deepcopy(config)
        if not enabled:
            arm["observability"].pop("scale_inventory_contract")
        root = tmp_path / ("observed" if enabled else "control")
        arm["checkpoint_dir"], arm["report_dir"] = str(root / "checkpoints"), str(root / "reports")
        store, world, run_id = open_run(arm, None, None, data_dir=root)
        path = Path(store.path)
        try:
            for _ in range(3):
                asyncio.run(world.step())
            assert world.economy.ledger.reconcile()[0]
            if enabled:
                assert store.scalar("SELECT COUNT(*) FROM scale_inventory_audit WHERE closing_json IS NOT NULL") == 3
                assert store.scalar("SELECT COUNT(*) FROM scale_demand_audit") > 0
                observed, evidence = demand_evidence(store.conn, 3, {"warmup_ticks": 1})
                assert observed, evidence
                _, inventory = buffer_inventory_evidence(store.conn, 3, {
                    "warmup_ticks": 1, "inventory_response_ticks": 1, "inventory_observation_ticks": 1})
                assert inventory["daily_conservation_exact"], inventory
        finally:
            world.close()
        finalize_sqlite_artifact(path)
        sources.append(path)
    # Compare the complete world state, apart from the deliberately added audit.
    proof = verify_replay(*sources)
    assert set(proof["differences"]) <= {"scale_inventory_audit", "scale_demand_audit", "scale_purchase_audit"}, proof
    before = hashlib.sha256(sources[1].read_bytes()).hexdigest()
    replay_store, replay_world, _ = open_run({}, None, run_id, data_dir=tmp_path / "replay", replay_source_dir=tmp_path / "observed")
    try:
        asyncio.run(replay_headless(replay_world, 3))
        proof = verify_replay(sources[1], replay_store.path)
        assert proof["exact"], proof["differences"]
    finally:
        replay_world.close()
    assert hashlib.sha256(sources[1].read_bytes()).hexdigest() == before

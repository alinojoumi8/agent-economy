from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from agents.policies import citizen_decision, founder_decision
from engine.ledger import LedgerError, SYS_EXTERNAL
from run import open_run
from run_config import load_config


@pytest.fixture()
def v2_world(tmp_path: Path):
    config = load_config("runs/v2.yaml")
    store, world, _ = open_run(config, None, None, data_dir=tmp_path)
    try:
        yield store, world
    finally:
        store.close()


def _trade_parties(store):
    row = store.query_one(
        "SELECT e.id AS exporter_firm_id,e.founder_agent_id AS actor_id,"
        "e.inventory AS exporter_inventory,e.currency_code AS exporter_currency,"
        "i.id AS importer_firm_id,i.inventory AS importer_inventory,"
        "i.currency_code AS importer_currency,i.account_id AS importer_account_id "
        "FROM firms e JOIN firms i ON i.region_id<>e.region_id "
        "WHERE e.status NOT IN ('bankrupt','acquired') AND e.inventory>=5 "
        "AND i.status NOT IN ('bankrupt','acquired') "
        "ORDER BY e.id,i.id LIMIT 1")
    assert row is not None
    return row


def _active_trade_contract(
        store, parties, *, status: str = "active", effective_tick: int = 0,
        expiry_tick: int | None = None) -> int:
    contract_id = store.insert(
        "contracts", contract_type="cross_border_supply", title="Regional supply",
        status=status, jurisdiction="interregional", ruleset_key="external-lite-1.0",
        drafter_agent_id=int(parties["actor_id"]), offered_tick=0,
        executed_tick=0, effective_tick=effective_tick, expiry_tick=expiry_tick,
        prose="regional supply",
        metadata_json="{}")
    store.insert(
        "contract_parties", contract_id=contract_id, party_type="firm",
        party_id=int(parties["exporter_firm_id"]), role="exporter")
    store.insert(
        "contract_parties", contract_id=contract_id, party_type="firm",
        party_id=int(parties["importer_firm_id"]), role="importer")
    return contract_id


def _qualified_migration_destination(store, actor) -> tuple[int, int]:
    """Create one destination that clears the bounded Semantics-7 wage gate."""
    destination_firm = store.query_one(
        "SELECT id,region_id FROM firms WHERE region_id<>? "
        "AND status NOT IN ('bankrupt','acquired') ORDER BY id LIMIT 1",
        (actor["region_id"],))
    assert destination_firm is not None
    store.insert(
        "jobs", tick=0, firm_id=int(destination_firm["id"]),
        title="qualified migration role", wage_cents=100_000_000, status="open")
    cadence = json.loads(actor["cadence_json"] or "{}")
    career_every = max(1, int(cadence.get("career", 30)))
    career_tick = int(actor["id"]) % career_every
    return int(destination_firm["region_id"]), career_tick


def test_flagship_population_regions_tiers_and_currency_reconciliation(v2_world):
    store, world = v2_world
    rows = store.query(
        "SELECT r.region_key,COUNT(a.id) AS n FROM regions r "
        "LEFT JOIN agents a ON a.region_id=r.id GROUP BY r.id ORDER BY r.id")
    assert {row["region_key"]: int(row["n"]) for row in rows} == {
        "northstar": 600, "ironvale": 220, "suncoast": 180,
    }
    assert store.scalar("SELECT COUNT(*) FROM agents") == 1000
    assert store.scalar("SELECT COUNT(*) FROM agents WHERE population_tier='core'") == 100
    ok, diagnostic = world.economy.ledger.reconcile()
    assert ok, diagnostic
    assert diagnostic["currency_sums"] == {"IVC": 0, "NSD": 0, "SCD": 0, "USD": 0}


def test_fx_is_inventory_backed_and_migration_changes_primary_currency(v2_world):
    store, world = v2_world
    economy = world.economy
    actor = store.query_one(
        "SELECT a.* FROM agents a JOIN regions r ON r.id=a.region_id "
        "WHERE r.region_key='northstar' AND a.kind='citizen' AND a.alive=1 "
        "AND a.health='healthy' AND a.retired=0 AND a.role IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM employments e WHERE e.agent_id=a.id "
        "AND e.status='active') "
        "AND (SELECT balance_cents FROM accounts WHERE id=a.checking_account_id)>10000 "
        "ORDER BY a.id LIMIT 1")
    actor_id = int(actor["id"])
    source_balance = economy.ledger.balance(int(actor["checking_account_id"]))
    placed = economy.regions.place_fx_order(1, actor_id, {
        "pair": "IVC/NSD", "side": "buy", "qty": 1000,
    })
    assert placed["ok"]
    trades = economy.regions.match_fx(1)
    assert len(trades) == 1
    ivc = store.query_one(
        "SELECT id,balance_cents FROM accounts WHERE owner_type='agent' AND owner_id=? "
        "AND currency_code='IVC'", (actor_id,))
    assert int(ivc["balance_cents"]) == 1000
    assert economy.ledger.balance(int(actor["checking_account_id"])) < source_balance
    assert store.scalar("SELECT MIN(balance_cents) FROM fx_reserves r JOIN accounts a ON a.id=r.account_id") >= 0

    destination, career_tick = _qualified_migration_destination(store, actor)
    requested = economy.regions.request_migration(
        career_tick, actor_id, destination, "new job")
    assert requested["ok"]
    assert store.scalar("SELECT status FROM migrations WHERE id=?",
                        (requested["migration_id"],)) == "pending"
    economy.regions.run_nightly(career_tick + 1)
    moved = store.query_one("SELECT region_id,checking_account_id FROM agents WHERE id=?", (actor_id,))
    assert int(moved["region_id"]) == destination
    assert store.scalar("SELECT currency_code FROM accounts WHERE id=?", (moved["checking_account_id"],)) == (
        store.scalar("SELECT currency_code FROM regions WHERE id=?", (destination,)))
    assert store.scalar("SELECT status FROM migrations WHERE id=?",
                        (requested["migration_id"],)) == "completed"
    assert store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='agent_migrated' AND subject_id=?",
        (actor_id,)) == 1
    assert economy.ledger.reconcile()[0]


def test_direct_cross_currency_transfer_is_rejected(v2_world):
    store, world = v2_world
    accounts = {row["currency_code"]: int(row["id"]) for row in store.query(
        "SELECT currency_code,id FROM accounts WHERE owner_type='system' AND label='sys:external'")}
    with pytest.raises(LedgerError, match="same currency"):
        world.economy.ledger.transfer(1, accounts["NSD"], accounts["IVC"], 1)


def test_contract_backed_trade_shipment_creates_and_delivers(v2_world):
    store, world = v2_world
    economy = world.economy
    parties = _trade_parties(store)
    contract_id = _active_trade_contract(store, parties)
    context = economy.regions.decision_context(
        int(parties["actor_id"]), tick=1,
        exporter_firm_id=int(parties["exporter_firm_id"]))
    opportunity = context["trade_opportunities"][0]
    action = dict(opportunity["action"])
    assert action["contract_id"] == contract_id
    assert action["invoice_currency"] == parties["importer_currency"]

    created = economy.regions.create_shipment(1, int(parties["actor_id"]), action)
    assert created["ok"]
    assert store.scalar("SELECT status FROM trade_shipments WHERE id=?",
                        (created["shipment_id"],)) == "in_transit"
    assert store.scalar("SELECT inventory FROM firms WHERE id=?",
                        (parties["exporter_firm_id"],)) == (
                            int(parties["exporter_inventory"]) - action["quantity"])

    economy.regions.run_nightly(int(created["arrival_tick"]))
    assert store.scalar("SELECT status FROM trade_shipments WHERE id=?",
                        (created["shipment_id"],)) == "delivered"
    assert store.scalar("SELECT inventory FROM firms WHERE id=?",
                        (parties["importer_firm_id"],)) == (
                            int(parties["importer_inventory"]) + action["quantity"])
    assert store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='trade_shipment_created' "
        "AND subject_id=?", (created["shipment_id"],)) == 1
    assert store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='trade_shipment_delivered' "
        "AND subject_id=?", (created["shipment_id"],)) == 1
    assert economy.ledger.reconcile()[0]


def test_trade_rejects_unauthorized_uncontracted_inactive_and_wrong_currency(v2_world):
    store, world = v2_world
    economy = world.economy
    parties = _trade_parties(store)
    contract_id = _active_trade_contract(store, parties)
    context = economy.regions.decision_context(
        int(parties["actor_id"]), tick=1,
        exporter_firm_id=int(parties["exporter_firm_id"]))
    action = dict(context["trade_opportunities"][0]["action"])
    outsider = int(store.scalar(
        "SELECT id FROM agents WHERE alive=1 AND id<>? AND "
        "COALESCE(employer_id,0)<>? ORDER BY id LIMIT 1",
        (parties["actor_id"], parties["exporter_firm_id"])))

    unauthorized = economy.regions.create_shipment(1, outsider, action)
    assert not unauthorized["ok"]
    assert "authorization" in unauthorized["reason"]

    uncontracted_action = {**action, "contract_id": contract_id + 1_000_000}
    uncontracted = economy.regions.create_shipment(
        1, int(parties["actor_id"]), uncontracted_action)
    assert not uncontracted["ok"]
    assert "contract" in uncontracted["reason"]

    future_contract = _active_trade_contract(
        store, parties, effective_tick=2)
    future = economy.regions.create_shipment(
        1, int(parties["actor_id"]), {**action, "contract_id": future_contract})
    assert not future["ok"]
    assert "effective" in future["reason"]

    expired_contract = _active_trade_contract(
        store, parties, expiry_tick=1)
    expired = economy.regions.create_shipment(
        1, int(parties["actor_id"]), {**action, "contract_id": expired_contract})
    assert not expired["ok"]
    assert "effective" in expired["reason"]

    # Even a funded foreign wallet cannot override the v7 importer-currency
    # settlement invariant by mutating an engine-qualified action.
    wrong_currency = str(parties["exporter_currency"])
    wrong_wallet = economy.regions._wallet(
        "firm", int(parties["importer_firm_id"]), wrong_currency, create=True)
    external = economy.ledger.system_account(
        SYS_EXTERNAL, currency_code=wrong_currency)
    economy.ledger.transfer(
        0, external, wrong_wallet,
        int(action["invoice_cents"]) + int(action["tariff_cents"])
        + int(action["transport_cents"]),
        kind="test_foreign_working_capital")
    wrong_currency_action = {**action, "invoice_currency": wrong_currency}
    wrong = economy.regions.create_shipment(
        1, int(parties["actor_id"]), wrong_currency_action)
    assert not wrong["ok"]
    assert "importer's currency" in wrong["reason"]
    assert store.scalar("SELECT COUNT(*) FROM trade_shipments") == 0
    assert store.scalar("SELECT inventory FROM firms WHERE id=?",
                        (parties["exporter_firm_id"],)) == parties["exporter_inventory"]
    assert economy.ledger.reconcile()[0]

    # The enforcement is deliberately semantics-7-only. Historical runs keep
    # the prior direct-action result for exact recorded replay.
    economy.regions.engine_semantics_version = 6
    legacy = economy.regions.create_shipment(
        1, int(parties["actor_id"]), {
            **wrong_currency_action, "contract_id": future_contract})
    assert legacy["ok"]
    assert store.scalar(
        "SELECT invoice_currency FROM trade_shipments WHERE id=?",
        (legacy["shipment_id"],)) == wrong_currency
    assert economy.ledger.reconcile()[0]


def test_semantics_7_trade_binds_exactly_to_advertised_opportunity(v2_world):
    store, world = v2_world
    economy = world.economy
    parties = _trade_parties(store)
    exporter_id = int(parties["exporter_firm_id"])
    importer_id = int(parties["importer_firm_id"])
    actor_id = int(parties["actor_id"])
    store.update(
        "firms", exporter_id,
        inventory=max(
            int(parties["exporter_inventory"]),
            economy.regions.max_trade_quantity + 10,
        ))
    contract_id = _active_trade_contract(store, parties)
    context = economy.regions.decision_context(
        actor_id, tick=1, exporter_firm_id=exporter_id)
    action = dict(context["trade_opportunities"][0]["action"])
    assert action["contract_id"] == contract_id
    assert int(store.scalar(
        "SELECT inventory FROM firms WHERE id=?", (exporter_id,))) > action["quantity"]
    assert action["invoice_cents"] > 1
    assert parties["exporter_currency"] != parties["importer_currency"]

    tampered_actions = {
        "quantity": {**action, "quantity": action["quantity"] + 1},
        "quantity_type": {**action, "quantity": str(action["quantity"])},
        "invoice": {**action, "invoice_cents": action["invoice_cents"] - 1},
        "currency": {**action, "invoice_currency": parties["exporter_currency"]},
        "exporter": {**action, "exporter_firm_id": importer_id},
        "importer": {**action, "importer_firm_id": exporter_id},
        "contract": {**action, "contract_id": contract_id + 1_000_000},
        "tariff": {**action, "tariff_cents": action["tariff_cents"] + 1},
        "transport": {**action, "transport_cents": action["transport_cents"] + 1},
        "transit": {**action, "transit_ticks": action["transit_ticks"] + 1},
        "action_type": {**action, "type": "unadvertised_shipment"},
        "extra_term": {**action, "discount_cents": 1},
    }
    inventory_before = int(store.scalar(
        "SELECT inventory FROM firms WHERE id=?", (exporter_id,)))
    accounts_before = int(store.scalar("SELECT COUNT(*) FROM accounts"))
    for field, tampered in tampered_actions.items():
        result = economy.regions.create_shipment(1, actor_id, tampered)
        assert not result["ok"], (field, result)

    assert store.scalar("SELECT COUNT(*) FROM trade_shipments") == 0
    assert store.scalar(
        "SELECT inventory FROM firms WHERE id=?", (exporter_id,)) == inventory_before
    assert store.scalar("SELECT COUNT(*) FROM accounts") == accounts_before
    assert economy.ledger.reconcile()[0]

    # An LLM action binds to the morning request context, but mutable execution
    # facts still fail closed if either firm or the actor becomes ineligible.
    model_call_id = store.insert(
        "llm_calls", tick=1, agent_id=actor_id, role="founder",
        provider="test", model="test", purpose="decision",
        request_json=json.dumps({"context": context}), response_json="{}")
    attributed_action = {**action, "model_call_id": model_call_id}
    for firm_id, inactive_status in (
            (exporter_id, "acquired"), (importer_id, "bankrupt")):
        prior_status = str(store.scalar(
            "SELECT status FROM firms WHERE id=?", (firm_id,)))
        store.update("firms", firm_id, status=inactive_status)
        inactive = economy.regions.create_shipment(
            1, actor_id, attributed_action)
        assert not inactive["ok"] and "active firms" in inactive["reason"]
        store.update("firms", firm_id, status=prior_status)

    store.update("agents", actor_id, alive=0)
    dead_actor = economy.regions.create_shipment(1, actor_id, attributed_action)
    assert not dead_actor["ok"] and "living authorized exporter" in dead_actor["reason"]
    store.update("agents", actor_id, alive=1)
    assert store.scalar("SELECT COUNT(*) FROM trade_shipments") == 0
    assert store.scalar(
        "SELECT inventory FROM firms WHERE id=?", (exporter_id,)) == inventory_before
    assert economy.ledger.reconcile()[0]

    # The exact binding is deliberately Semantics-7-only. Historical runs
    # preserve the prior direct domain behavior for recorded replay.
    economy.regions.engine_semantics_version = 6
    legacy = economy.regions.create_shipment(1, actor_id, {
        **action,
        "quantity": action["quantity"] + 1,
        "invoice_cents": 1,
    })
    assert legacy["ok"]
    assert store.scalar(
        "SELECT quantity FROM trade_shipments WHERE id=?",
        (legacy["shipment_id"],)) == action["quantity"] + 1
    assert economy.ledger.reconcile()[0]


def test_migration_rejects_credit_exposure_under_semantics_7(v2_world):
    store, world = v2_world
    economy = world.economy
    actor = store.query_one(
        "SELECT a.* FROM agents a WHERE a.alive=1 AND a.kind='citizen' "
        "AND a.health='healthy' AND a.retired=0 AND a.role IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM employments e WHERE e.agent_id=a.id "
        "AND e.status='active') ORDER BY a.id LIMIT 1")
    destination, career_tick = _qualified_migration_destination(store, actor)
    bank_id = int(store.scalar("SELECT id FROM banks ORDER BY id LIMIT 1"))
    store.insert(
        "loan_applications", tick=1, bank_id=bank_id, borrower_type="agent",
        borrower_id=int(actor["id"]), amount_cents=10_000,
        purpose="pre-migration credit", status="pending")

    result = economy.regions.request_migration(
        career_tick, int(actor["id"]), destination, "career")
    assert not result["ok"]
    assert "pending loan application" in result["reason"]
    assert store.scalar("SELECT COUNT(*) FROM migrations WHERE agent_id=?",
                        (actor["id"],)) == 0


def test_semantics_7_migration_action_and_settlement_revalidate_eligibility(v2_world):
    store, world = v2_world
    economy = world.economy
    actor = store.query_one(
        "SELECT a.* FROM agents a WHERE a.kind='citizen' AND a.alive=1 "
        "AND a.health='healthy' AND a.retired=0 AND a.role IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM employments e WHERE e.agent_id=a.id "
        "AND e.status='active') ORDER BY a.id LIMIT 1")
    destination, career_tick = _qualified_migration_destination(store, actor)
    actor_id = int(actor["id"])
    origin = int(actor["region_id"])

    store.update("agents", actor_id, retired=1)
    retired = economy.regions.request_migration(
        career_tick, actor_id, destination, "retired bypass")
    assert not retired["ok"] and "retired" in retired["reason"]

    store.update("agents", actor_id, retired=0)
    off_cadence = economy.regions.request_migration(
        career_tick + 1, actor_id, destination, "off-cadence bypass")
    assert not off_cadence["ok"] and "career cadence" in off_cadence["reason"]

    requested = economy.regions.request_migration(
        career_tick, actor_id, destination, "qualified career move")
    assert requested["ok"]

    # Settlement is the following NIGHT_CLOSE. Current eligibility is checked
    # again, while cadence remains tied to the persisted request tick.
    store.update("agents", actor_id, alive=0)
    economy.regions.run_nightly(career_tick + 1)
    assert store.scalar(
        "SELECT status FROM migrations WHERE id=?", (requested["migration_id"],)) == "rejected"
    assert store.scalar("SELECT region_id FROM agents WHERE id=?", (actor_id,)) == origin
    assert store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='migration_rejected_ineligible' "
        "AND subject_id=?", (actor_id,)) == 1
    assert store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='agent_migrated' AND subject_id=?",
        (actor_id,)) == 0


def test_semantics_7_context_bounds_trade_and_scripted_founder_uses_one(v2_world):
    store, world = v2_world
    parties = _trade_parties(store)
    contract_ids = [_active_trade_contract(store, parties) for _ in range(6)]
    founder = store.query_one("SELECT * FROM agents WHERE id=?", (parties["actor_id"],))
    context = world.runtime.ctx.build(founder, 1)

    opportunities = context["trade_opportunities"]
    assert len(opportunities) == 5
    assert [item["contract_id"] for item in opportunities] == contract_ids[:5]
    assert all(item["invoice_currency"] == parties["importer_currency"]
               for item in opportunities)
    decision = founder_decision(context)
    shipments = [action for action in decision["actions"]
                 if action["type"] == "create_trade_shipment"]
    assert shipments == [opportunities[0]["action"]]

    system, prompt = world.runtime.ctx.render_prompt(context)
    assert "create_trade_shipment" in system
    assert "QUALIFIED CROSS-BORDER SHIPMENTS" in prompt


def test_semantics_7_migration_options_are_career_gated_and_wage_qualified(v2_world):
    store, world = v2_world
    actor = store.query_one(
        "SELECT a.* FROM agents a WHERE a.kind='citizen' AND a.alive=1 "
        "AND a.health='healthy' AND a.retired=0 AND a.role IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM firms f WHERE f.founder_agent_id=a.id) "
        "AND NOT EXISTS (SELECT 1 FROM employments e WHERE e.agent_id=a.id "
        "AND e.status='active') AND EXISTS (SELECT 1 FROM firms f WHERE f.region_id=a.region_id) "
        "ORDER BY a.id LIMIT 1")
    home_firm = store.query_one(
        "SELECT id FROM firms WHERE region_id=? AND status NOT IN ('bankrupt','acquired') "
        "ORDER BY id LIMIT 1", (actor["region_id"],))
    destination_firm = store.query_one(
        "SELECT id,region_id FROM firms WHERE region_id<>? "
        "AND status NOT IN ('bankrupt','acquired') ORDER BY id LIMIT 1",
        (actor["region_id"],))
    store.insert("jobs", tick=1, firm_id=int(home_firm["id"]), title="local",
                 wage_cents=10_000, status="open")
    store.insert("jobs", tick=1, firm_id=int(destination_firm["id"]), title="better",
                 wage_cents=40_000, status="open")
    cadence = json.loads(actor["cadence_json"] or "{}")
    career_every = max(1, int(cadence.get("career", 30)))
    assert career_every > 1
    career_tick = int(actor["id"]) % career_every

    context = world.runtime.ctx.build(actor, career_tick)
    assert context["career_day"]
    assert context["migration_options"]
    best = context["migration_options"][0]
    assert best["destination_region_id"] == int(destination_firm["region_id"])
    assert best["wage_gain_bps"] >= context["migration_wage_gain_bps"]
    decision = citizen_decision(context)
    migrations = [action for action in decision["actions"]
                  if action["type"] == "request_migration"]
    assert migrations == [best["action"]]
    assert not any(action["type"] == "apply_job" for action in decision["actions"])

    off_cadence = world.runtime.ctx.build(actor, career_tick + 1)
    assert not off_cadence["career_day"]
    assert off_cadence["migration_options"] == []
    assert not any(action["type"] == "request_migration"
                   for action in citizen_decision(off_cadence)["actions"])


def test_semantics_6_prompt_surface_has_no_regional_activation(v2_world):
    store, world = v2_world
    founder = store.query_one(
        "SELECT a.* FROM agents a JOIN firms f ON f.founder_agent_id=a.id "
        "ORDER BY f.id LIMIT 1")
    world.runtime.ctx.engine_semantics_version = 6
    context = world.runtime.ctx.build(founder, 1)
    assert "regional_actions_enabled" not in context
    assert "trade_opportunities" not in context
    assert "migration_options" not in context
    system, prompt = world.runtime.ctx.render_prompt(context)
    assert "place_fx_order" not in system
    assert "create_trade_shipment" not in system
    assert "REGIONAL WALLETS" not in prompt

    institutional = {
        "agent": {"id": int(founder["id"]), "name": "Institution", "role": "central_banker"},
        "state": {}, "purpose": "central_banker",
        "institutional_work": {"eligible_actions": []},
        "regional_actions_enabled": True, "fx_quotes": [],
    }
    legacy_system, _ = world.runtime.ctx.render_prompt(institutional)
    assert "place_fx_order" in legacy_system
    world.runtime.ctx.engine_semantics_version = 7
    bounded_system, _ = world.runtime.ctx.render_prompt(institutional)
    assert "place_fx_order" not in bounded_system


def test_peripheral_agents_never_create_model_call_records(v2_world):
    store, world = v2_world
    asyncio.run(world.step())
    assert store.scalar(
        "SELECT COUNT(*) FROM llm_calls l JOIN agents a ON a.id=l.agent_id "
        "WHERE a.population_tier='periphery'"
    ) == 0
    assert store.scalar(
        "SELECT COUNT(*) FROM memories m JOIN agents a ON a.id=m.agent_id "
        "WHERE a.population_tier='periphery' AND m.kind='summary'"
    ) > 0


def test_vc_opportunity_set_requires_matching_currency(v2_world):
    store, world = v2_world
    partner = store.query_one("SELECT * FROM agents WHERE role='vc_partner' ORDER BY id LIMIT 1")
    partner_currency = store.scalar(
        "SELECT currency_code FROM accounts WHERE id=?", (partner["checking_account_id"],))
    foreign = store.query_one(
        "SELECT * FROM firms WHERE status='private' AND currency_code<>? "
        "AND id NOT IN (SELECT firm_id FROM pitches WHERE status='pending') ORDER BY id LIMIT 1",
        (partner_currency,))
    local = store.query_one(
        "SELECT * FROM firms WHERE status='private' AND currency_code=? "
        "AND id NOT IN (SELECT firm_id FROM pitches WHERE status='pending') ORDER BY id LIMIT 1",
        (partner_currency,))
    foreign_pitch = world.economy.vc.pitch(
        1, int(foreign["founder_agent_id"]), int(foreign["id"]), 10_000, "foreign")
    local_pitch = world.economy.vc.pitch(
        1, int(local["founder_agent_id"]), int(local["id"]), 10_000, "local")
    context = world.runtime.ctx._vc_partner_context(partner, 1)
    offered = {item["pitch_id"] for item in context["pending_pitches"]}
    assert local_pitch in offered
    assert foreign_pitch not in offered
    assert context["fund_currency"] == partner_currency


def test_v2_memory_is_mechanistic_daily_and_core_reflects_weekly(v2_world):
    store, world = v2_world
    core_id = int(store.scalar(
        "SELECT id FROM agents WHERE population_tier='core' ORDER BY id LIMIT 1"))
    peripheral_id = int(store.scalar(
        "SELECT id FROM agents WHERE population_tier='periphery' ORDER BY id LIMIT 1"))
    world.runtime.mem.observe(core_id, 7, "Core observation", importance=2.0)
    world.runtime.mem.observe(peripheral_id, 7, "Peripheral observation", importance=1.0)
    asyncio.run(world.runtime.compress_memories(7))
    assert store.scalar(
        "SELECT COUNT(*) FROM llm_calls WHERE agent_id=? AND purpose='memory'",
        (core_id,)) == 1
    assert store.scalar(
        "SELECT COUNT(*) FROM llm_calls WHERE agent_id=? AND purpose='memory'",
        (peripheral_id,)) == 0
    assert store.scalar(
        "SELECT COUNT(*) FROM memories WHERE agent_id IN (?,?) "
        "AND kind='weekly_summary'", (core_id, peripheral_id)) == 2

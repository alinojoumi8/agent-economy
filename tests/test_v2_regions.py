from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from engine.ledger import LedgerError
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
        "SELECT a.id,a.checking_account_id FROM agents a JOIN regions r ON r.id=a.region_id "
        "WHERE r.region_key='northstar' AND a.kind='citizen' "
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

    ironvale = int(store.scalar("SELECT id FROM regions WHERE region_key='ironvale'"))
    requested = economy.regions.request_migration(1, actor_id, ironvale, "new job")
    assert requested["ok"]
    economy.regions.run_nightly(1)
    moved = store.query_one("SELECT region_id,checking_account_id FROM agents WHERE id=?", (actor_id,))
    assert int(moved["region_id"]) == ironvale
    assert store.scalar("SELECT currency_code FROM accounts WHERE id=?", (moved["checking_account_id"],)) == "IVC"
    assert economy.ledger.reconcile()[0]


def test_direct_cross_currency_transfer_is_rejected(v2_world):
    store, world = v2_world
    accounts = {row["currency_code"]: int(row["id"]) for row in store.query(
        "SELECT currency_code,id FROM accounts WHERE owner_type='system' AND label='sys:external'")}
    with pytest.raises(LedgerError, match="same currency"):
        world.economy.ledger.transfer(1, accounts["NSD"], accounts["IVC"], 1)


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

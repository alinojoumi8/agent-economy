"""Known disputes retain actual cash until a recorded disposition resolves them."""
import asyncio
import copy
import hashlib

import pytest

from engine.lifecycle import Lifecycle
from research.export_bundle import export_bundle, validate_bundle
from research.hashing import canonical_hashes
from world.replay_verify import verify_replay

from .test_semantics20_legal_awards import award_case, claim, decide, receive, check
from .test_semantics13_construction import _config, _owner
from .test_semantics17_household_decisions import _world


def reserve(case, matter):
    return case.e.store.query_one("SELECT * FROM estate_legal_reserves WHERE matter_id=?", (matter,))


def dismiss(case, matter, tick):
    result = case.e.legal.issue_decision(tick, case.judge, {"matter_id": matter, "outcome": "dismissed",
        "findings": [{"key": "supported_claim", "value": False}], "remedy": {"type": "dismissal"}})
    assert result["ok"], result
    return result


def test_contested_contract_cash_is_held_then_pays_the_judgment_and_releases_only_the_excess(award_case):
    c = award_case
    matter, event = claim(c, 150)
    c.e.lifecycle.settle_death(2, c.person)
    held = reserve(c, matter)
    assert c.e.ledger.balance(held["escrow_account_id"]) == 100
    assert c.e.ledger.balance(c.creditor_wallet) == c.e.ledger.balance(c.heir_wallet) == 0
    receive(c, 60, tick=3)
    assert c.e.ledger.balance(held["escrow_account_id"]) == 150
    assert c.e.ledger.balance(c.heir_wallet) == 10
    result = decide(c, matter, event, 120, tick=4)
    assert result["ok"], result
    assert c.e.ledger.balance(held["escrow_account_id"]) == 0
    assert c.e.ledger.balance(c.creditor_wallet) == 120
    assert c.e.ledger.balance(c.heir_wallet) == 40
    assert c.e.store.scalar("SELECT released_cents FROM estate_reserve_resolutions") == 150
    check(c)


def test_dismissed_independent_claim_releases_reserved_cash_to_recorded_heirs(award_case):
    c = award_case
    matter, _ = claim(c, 80, contract=False)
    c.e.lifecycle.settle_death(2, c.person)
    assert c.e.ledger.balance(reserve(c, matter)["escrow_account_id"]) == 80
    assert c.e.ledger.balance(c.heir_wallet) == 20
    dismiss(c, matter, 3)
    assert c.e.ledger.balance(c.heir_wallet) == 100
    assert c.e.ledger.balance(c.creditor_wallet) == 0
    assert c.e.store.scalar("SELECT COUNT(*) FROM legal_awards") == 0
    check(c)


def test_resolving_one_dispute_funds_another_known_dispute_before_residual_inheritance(award_case):
    c = award_case
    first, _ = claim(c, 60, contract=False)
    second, event = claim(c, 60, contract=False)
    c.e.lifecycle.settle_death(2, c.person)
    assert c.e.ledger.balance(reserve(c, first)["escrow_account_id"]) == 60
    assert c.e.ledger.balance(reserve(c, second)["escrow_account_id"]) == 40
    dismiss(c, first, 3)
    assert c.e.ledger.balance(reserve(c, second)["escrow_account_id"]) == 60
    assert c.e.ledger.balance(c.heir_wallet) == 40
    assert decide(c, second, event, 50, tick=4)["ok"]
    assert c.e.ledger.balance(c.creditor_wallet) == 50
    assert c.e.ledger.balance(c.heir_wallet) == 50
    check(c)


def test_a_new_case_after_distribution_can_reserve_only_future_estate_receipts(award_case):
    c = award_case
    c.e.lifecycle.settle_death(2, c.person)
    assert c.e.ledger.balance(c.heir_wallet) == 100
    matter, event = claim(c, 80, contract=False, tick=3)
    assert c.e.ledger.balance(c.heir_wallet) == 100
    assert c.e.ledger.balance(reserve(c, matter)["escrow_account_id"]) == 0
    receive(c, 90, tick=4)
    assert c.e.ledger.balance(c.heir_wallet) == 110
    assert c.e.ledger.balance(reserve(c, matter)["escrow_account_id"]) == 80
    assert decide(c, matter, event, 60, tick=5)["ok"]
    assert c.e.ledger.balance(c.creditor_wallet) == 60
    assert c.e.ledger.balance(c.heir_wallet) == 130
    check(c)


def test_dispute_resolution_failure_rolls_back_judgment_replacement_and_escrow_release(award_case, monkeypatch):
    c = award_case
    matter, event = claim(c, 150)
    c.e.lifecycle.settle_death(2, c.person)
    before = canonical_hashes(c.e.store)["authoritative_sha256"]
    original = c.e.estate_disputes.resolve
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected after escrow release")
    monkeypatch.setattr(c.e.estate_disputes, "resolve", fail)
    with pytest.raises(RuntimeError, match="injected"):
        decide(c, matter, event, 120, tick=3)
    assert canonical_hashes(c.e.store)["authoritative_sha256"] == before
    check(c)
    monkeypatch.setattr(c.e.estate_disputes, "resolve", original)
    assert decide(c, matter, event, 120, tick=3)["ok"]
    check(c)


def test_dispute_award_and_actual_reserve_collection_survive_restart_and_recorded_replay(tmp_path, monkeypatch, caplog):
    config = _config(semantics=20)
    config.setdefault("households", {})["scheduled_births"] = []
    config.setdefault("lifecycle", {}).update(population_mode="drift", birth_annual_prob=0)
    config.setdefault("legal", {})["response_ticks"] = 2
    config.setdefault("llm", {})["institutional_role_purposes"] = True
    config["checkpoint_dir"] = str(tmp_path / "checkpoints")
    owner_id = None
    original_draw = Lifecycle._draw

    def draw(self, tick, agent_id, mechanism):
        if tick == 1 and agent_id == owner_id and mechanism == "mortality":
            return 0.0
        return original_draw(self, tick, agent_id, mechanism)

    monkeypatch.setattr(Lifecycle, "_draw", draw)

    def open_seeded(path, settings, *, replay=False):
        nonlocal owner_id
        world = _world(path, settings, replay=replay)
        if world.store.tick != 0:
            return world
        e = world.economy
        owner = _owner(world)
        owner_id = owner["id"]
        creditor = e.store.scalar("SELECT id FROM agents WHERE alive=1 AND age>=18 AND region_id=? AND id<>? AND kind='citizen' ORDER BY id LIMIT 1", (owner["region_id"], owner_id))
        regulator = e.store.scalar("SELECT id FROM agents WHERE role='labor_regulator' AND alive=1")
        assert regulator is not None
        # The small civic profile leaves this role peripheral. This declared
        # court scenario requires an active, scheduled regulator in both runs.
        e.store.update("agents", regulator, population_tier="core", pinned_core=1)
        currency = e.store.scalar("SELECT currency_code FROM accounts WHERE id=?", (owner["checking_account_id"],))
        proposal = e.legal.propose_contract(0, creditor, {"contract_type": "supplier", "title": "Stipulated replay debt",
            "parties": [{"type": "agent", "id": creditor, "role": "supplier"}, {"type": "agent", "id": owner_id, "role": "buyer"}],
            "clauses": [{"clause_key": "price", "clause_type": "payment", "terms": {"obligor_role": "buyer", "obligee_role": "supplier",
                        "amount_cents": 170, "due_tick": 0, "currency_code": currency}}]})
        assert proposal["ok"], proposal
        contract = proposal["contract_id"]
        assert e.legal.accept_contract(0, creditor, contract, "agent", creditor)["ok"]
        assert e.legal.accept_contract(0, owner_id, contract, "agent", owner_id)["ok"]
        obligation = e.store.scalar("SELECT id FROM obligations WHERE contract_id=?", (contract,))
        evidence = e.store.scalar("SELECT id FROM events WHERE kind='contract_executed' AND subject_id=? ORDER BY id DESC LIMIT 1", (contract,))
        assert evidence is not None
        filed = e.legal.file_claim(0, creditor, {"contract_id": contract, "matter_type": "labor",
            "claimant": {"type": "agent", "id": creditor}, "respondent": {"type": "agent", "id": owner_id},
            "claim_type": "stipulated_payment", "requested_remedy": {"type": "damages", "amount_cents": 170,
                "currency_code": currency, "obligation_ids": [obligation]}})
        assert filed["ok"], filed
        admitted = e.legal.submit_filing(0, creditor, {"matter_id": filed["matter_id"], "filer_type": "agent", "filer_id": creditor,
            "filing_type": "stipulation", "evidence_event_ids": [evidence], "body": "A declared pending monetary dispute at genesis."})
        assert admitted["ok"], admitted
        return world

    path = tmp_path / "source.db"
    for day in (1, 2):
        source = open_seeded(path, config)
        try:
            asyncio.run(source.step())
            assert source.store.scalar("SELECT COUNT(*) FROM estate_legal_reserves") >= 1
            if day == 1:
                assert source.store.scalar("SELECT SUM(a.balance_cents) FROM estate_legal_reserves r JOIN accounts a ON a.id=r.escrow_account_id") == 170
            else:
                assert source.store.scalar("SELECT COUNT(*) FROM legal_awards") >= 1
                assert source.store.scalar("SELECT SUM(amount_cents) FROM legal_award_payments") == 170
                assert source.store.scalar("SELECT SUM(released_cents) FROM estate_reserve_resolutions") == 170
                manifest = validate_bundle(export_bundle(source.store, tmp_path / "replay-source-export"))
                assert manifest["tables"]["estate_reserve_resolutions"]["row_count"] >= 1
            source.economy.estate_cases.check_invariants()
            source.economy.legal_awards.check_invariants()
        finally:
            source.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    replay_config = copy.deepcopy(config)
    replay_config["replay_source_path"] = str(path)
    replay = open_seeded(tmp_path / "replay.db", replay_config, replay=True)
    try:
        for _ in range(2):
            asyncio.run(replay.step())
        proof = verify_replay(path, replay.store.path)
        assert proof["exact"], proof["differences"]
        replay.economy.estate_cases.check_invariants()
        replay.economy.legal_awards.check_invariants()
        assert not any("action.execution.failed" in record.message for record in caplog.records)
    finally:
        replay.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before

from __future__ import annotations

import asyncio
import json

import pytest

from engine.store import Store, load_json
from world.loop import World
from world.replay_verify import verify_replay


def _config(tmp_path, *, replay_source=None) -> dict:
    config = {
        "seed": 42,
        "engine_semantics_version": 6,
        "population": {"size": 12},
        "banks": {"count": 2},
        "firms": {"count": 3, "listed": 1},
        "behavior": {"act_every": 999},
        "budget": {"cap_usd": None, "conversation_pairs": 0},
        "llm": {
            "provider_retries": 0,
            "institutional_role_purposes": True,
            "default_route": {"provider": "scripted", "model": "scripted"},
            "routes": {},
        },
        "central_bank": {"meeting_interval_ticks": 999},
        "checkpoint_every": 0,
        "checkpoint_dir": str(tmp_path / "checkpoints"),
        "report_dir": str(tmp_path / "reports"),
        "outlets": [
            {"id": 1, "name": "A", "slant": "pro-market-sensational"},
            {"id": 2, "name": "B", "slant": "cautious-pro-labor"},
        ],
    }
    if replay_source is not None:
        config.update({"replay": True, "replay_source_path": str(replay_source)})
    return config


def _world(tmp_path, name: str, *, replay_source=None) -> World:
    config = _config(tmp_path, replay_source=replay_source)
    store = Store(str(tmp_path / name))
    store.init_run_meta(name.removesuffix(".db"), config["seed"], config)
    world = World(store, config, replay=replay_source is not None)
    world.initialize()
    return world


def _multicurrency_world(tmp_path, name: str) -> World:
    config = _config(tmp_path)
    config["banks"]["count"] = 3
    config["living_world"] = {"enabled": True}
    store = Store(str(tmp_path / name))
    store.init_run_meta(name.removesuffix(".db"), config["seed"], config)
    world = World(store, config)
    world.initialize()
    return world


def _central_banker(world: World):
    return world.store.query_one(
        "SELECT * FROM agents WHERE role='central_banker' AND alive=1 LIMIT 1")


def _model_call(world: World, tick: int, agent_id: int, *,
                role: str = "central_banker", purpose: str = "central_banker") -> int:
    return world.store.insert(
        "llm_calls", tick=tick, agent_id=agent_id, role=role,
        provider="scripted", model="scripted", purpose=purpose,
        cache_key=f"test:{tick}:{agent_id}:{role}:{purpose}",
        request_json="{}", response_json="{}",
        in_tokens=0, out_tokens=0, cached=0, cost_usd=0.0)


def _drain_reserves(world: World, bank_id: int, target_cents: int = 0) -> None:
    bank = world.economy.bank.get(bank_id)
    reserve_account = int(bank["reserve_account_id"])
    central_bank_account = world.economy.central_bank_reserve_acct(
        str(bank["currency_code"] or "USD"))
    assert central_bank_account is not None
    current = world.economy.ledger.balance(reserve_account)
    amount = max(0, current - max(0, int(target_cents)))
    if amount:
        world.economy.ledger.transfer(
            0, reserve_account, int(central_bank_account), amount,
            kind="test_reserve_drain", memo=f"create bank {bank_id} distress")


def _make_solvent_on_books(world: World, bank_id: int) -> None:
    deposits = world.economy.bank.deposits(bank_id)
    borrower_id = int(world.store.scalar(
        "SELECT id FROM agents WHERE alive=1 ORDER BY id LIMIT 1"))
    world.store.insert(
        "loans", bank_id=bank_id, borrower_type="agent", borrower_id=borrower_id,
        principal_cents=deposits, outstanding_cents=deposits,
        rate_bps=500, term_ticks=365, origin_tick=0,
        payment_cents=1, payment_interval_ticks=365, next_due_tick=365,
        missed_payments=0, collateral_json="{}", purpose="test solvency",
        status="active")


def _night_close_distress(world: World) -> tuple[int, int]:
    banks = world.store.query("SELECT * FROM banks WHERE status='open' ORDER BY id")
    weak_id = int(banks[0]["id"])
    strong_id = int(banks[1]["id"])
    _make_solvent_on_books(world, weak_id)
    _drain_reserves(world, weak_id, 0)
    # Interbank support only lends reserves above 10% of deposits. Keep the
    # second bank sound but without lendable surplus so the central-bank path is exercised.
    _drain_reserves(world, strong_id, world.economy.bank.deposits(strong_id) // 10)
    world._bank_liquidity_sweep(1)
    request = world.economy.bank.pending_liquidity_requests(bank_id=weak_id, limit=1)[0]
    return weak_id, int(request["request_event_id"])


def test_transfer_distress_waits_for_actor_correct_approval(tmp_path):
    world = _world(tmp_path, "transfer-lolr.db")
    banks = world.store.query("SELECT id FROM banks WHERE status='open' ORDER BY id")
    weak_id, destination_id = int(banks[0]["id"]), int(banks[1]["id"])
    depositor = world.store.query_one(
        "SELECT a.id,ac.balance_cents FROM agents a JOIN accounts ac "
        "ON ac.id=a.checking_account_id WHERE ac.bank_id=? AND ac.balance_cents>0 "
        "ORDER BY a.id LIMIT 1", (weak_id,))
    assert depositor is not None
    _drain_reserves(world, weak_id, 0)
    _drain_reserves(world, destination_id, 0)

    move = {"type": "move_deposits", "to_bank_id": destination_id}
    first = world.runtime.executor.execute_action(1, int(depositor["id"]), move)
    assert first["reason"] == "liquidity_support_pending"
    request_event_id = int(first["request_event_id"])
    assert world.store.scalar("SELECT status FROM banks WHERE id=?", (weak_id,)) == "open"

    # Repeated transfers reuse the same durable request rather than inflating support.
    second = world.runtime.executor.execute_action(1, int(depositor["id"]), move)
    assert second["request_event_id"] == request_event_id
    assert world.store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='liquidity_support_requested' "
        "AND subject_id=?", (weak_id,)) == 1

    # Pending distress is database state, not an in-memory callback: reopening
    # the world preserves both the request and the emergency scheduler wakeup.
    path = world.store.path
    config = world.config
    world.store.commit()
    world.store.close()
    reopened = Store(path)
    world = World(reopened, config)
    world.initialize()
    assert world.economy.bank.pending_liquidity_requests(
        bank_id=weak_id, limit=1)[0]["request_event_id"] == request_event_id
    governor = _central_banker(world)
    assert int(governor["id"]) in {
        int(agent["id"]) for agent in world.runtime.scheduler.scheduled_agents(1)}

    governor_id = int(governor["id"])
    evidence = [request_event_id]
    citizen_call = _model_call(
        world, 1, int(depositor["id"]), role="citizen", purpose="decision")
    wrong_actor = world.runtime.executor.execute_action(1, int(depositor["id"]), {
        "type": "decide_liquidity_support", "request_event_id": request_event_id,
        "decision": "approve", "evidence_event_ids": evidence,
        "model_call_id": citizen_call,
    })
    assert not wrong_actor["ok"] and "central banker" in wrong_actor["reason"]

    dangling = world.runtime.executor.execute_action(1, governor_id, {
        "type": "decide_liquidity_support", "request_event_id": request_event_id,
        "decision": "approve", "evidence_event_ids": evidence,
        "model_call_id": 999_999,
    })
    assert not dangling["ok"] and "dangling" in dangling["reason"]

    other_actor_call = _model_call(world, 1, int(depositor["id"]))
    wrong_provenance = world.runtime.executor.execute_action(1, governor_id, {
        "type": "decide_liquidity_support", "request_event_id": request_event_id,
        "decision": "approve", "evidence_event_ids": evidence,
        "model_call_id": other_actor_call,
    })
    assert not wrong_provenance["ok"] and "different actor" in wrong_provenance["reason"]
    assert world.economy.bank.pending_liquidity_requests(bank_id=weak_id, limit=1)
    assert world.store.query_one(
        "SELECT id,importance FROM events WHERE id=? AND kind='liquidity_support_requested'",
        (request_event_id,))["importance"] >= 4.0

    call_id = _model_call(world, 1, governor_id)
    approved = world.runtime.executor.execute_action(1, governor_id, {
        "type": "decide_liquidity_support", "request_event_id": request_event_id,
        "decision": "approve", "evidence_event_ids": evidence,
        "model_call_id": call_id,
    })
    assert approved["ok"] and approved["decision"] == "approve"
    assert not world.economy.bank.pending_liquidity_requests(bank_id=weak_id, limit=1)

    grant = world.store.query_one(
        "SELECT payload_json FROM events WHERE kind='lolr_granted' "
        "AND subject_id=? ORDER BY id DESC LIMIT 1", (weak_id,))
    provenance = load_json(grant["payload_json"], {})
    assert provenance["request_event_id"] == request_event_id
    assert provenance["decision_actor_id"] == governor_id
    assert provenance["model_call_id"] == call_id

    retried = world.runtime.executor.execute_action(1, int(depositor["id"]), move)
    assert retried["ok"]
    assert world.economy.ledger.reconcile()[0]


def test_central_banker_denial_fails_bank_and_applies_haircut(tmp_path):
    world = _world(tmp_path, "deny-lolr.db")
    bank_id = int(world.store.scalar("SELECT id FROM banks WHERE status='open' ORDER BY id LIMIT 1"))
    _drain_reserves(world, bank_id, 0)
    request_event_id = world.economy.bank.request_liquidity_support(
        1, bank_id, 50_000, phase="NIGHT_CLOSE", source="night_close")
    governor_id = int(_central_banker(world)["id"])
    call_id = _model_call(world, 1, governor_id)

    denied = world.runtime.executor.execute_action(1, governor_id, {
        "type": "decide_liquidity_support", "request_event_id": request_event_id,
        "decision": "deny", "evidence_event_ids": [request_event_id],
        "model_call_id": call_id,
    })

    assert denied["ok"] and denied["decision"] == "deny"
    assert world.store.scalar("SELECT status FROM banks WHERE id=?", (bank_id,)) == "failed"
    failure = world.store.query_one(
        "SELECT payload_json,phase FROM events WHERE kind='bank_failure' "
        "AND subject_id=?", (bank_id,))
    failure_payload = load_json(failure["payload_json"], {})
    assert failure["phase"] == "EXECUTION"
    assert failure_payload["haircut_rate"] > 0
    denial = load_json(world.store.scalar(
        "SELECT payload_json FROM events WHERE kind='lolr_denied' AND subject_id=?",
        (bank_id,)), {})
    assert denial["request_event_id"] == request_event_id
    assert denial["model_call_id"] == call_id
    assert world.economy.ledger.reconcile()[0]


def test_multicurrency_interbank_and_lolr_use_matching_reserve_accounts(tmp_path):
    world = _multicurrency_world(tmp_path, "multicurrency-lolr.db")
    central_accounts = world.store.query(
        "SELECT id,currency_code FROM accounts WHERE owner_type='central_bank' "
        "AND kind='reserve' ORDER BY currency_code")
    assert {str(row["currency_code"]) for row in central_accounts} == {
        "NSD", "IVC", "SCD",
    }
    governor_id = int(_central_banker(world)["id"])

    for tick, currency in enumerate(("IVC", "SCD"), start=1):
        bank = world.store.query_one(
            "SELECT * FROM banks WHERE currency_code=? AND status='open'",
            (currency,))
        assert bank is not None
        bank_id = int(bank["id"])
        _make_solvent_on_books(world, bank_id)
        _drain_reserves(world, bank_id, 0)
        central_account = world.economy.central_bank_reserve_acct(currency)
        assert central_account is not None

        supported = world.economy.bank.attempt_liquidity_support(
            tick, bank_id, 50_000, int(central_account),
            require_authorized_decision=True, phase="NIGHT_CLOSE",
            source="multicurrency_test")
        assert supported is None
        request = world.economy.bank.pending_liquidity_requests(
            bank_id=bank_id, limit=1)[0]
        call_id = _model_call(world, tick, governor_id)
        approved = world.runtime.executor.execute_action(tick, governor_id, {
            "type": "decide_liquidity_support",
            "request_event_id": int(request["request_event_id"]),
            "decision": "approve",
            "evidence_event_ids": [int(request["request_event_id"])],
            "model_call_id": call_id,
        })
        assert approved["ok"], approved
        assert world.economy.bank.reserves(bank_id) == 50_000
        txn_currency = world.store.scalar(
            "SELECT currency_code FROM transactions WHERE kind='lolr' "
            "ORDER BY id DESC LIMIT 1")
        assert txn_currency == currency

    # Other-currency banks retained lendable balances, but none was treated as
    # liquidity for either IVC or SCD settlement.
    assert world.store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='interbank_loan'", default=0) == 0
    assert world.economy.ledger.reconcile()[0]


def test_missing_living_central_banker_denies_request_and_fails_bank(tmp_path):
    world = _world(tmp_path, "unstaffed-lolr.db")
    banks = world.store.query("SELECT id FROM banks WHERE status='open' ORDER BY id")
    weak_id, strong_id = int(banks[0]["id"]), int(banks[1]["id"])
    _make_solvent_on_books(world, weak_id)
    _drain_reserves(world, weak_id, 0)
    _drain_reserves(world, strong_id, world.economy.bank.deposits(strong_id) // 10)
    world.store.execute("UPDATE agents SET alive=0 WHERE role='central_banker'")

    world._bank_liquidity_sweep(1)

    assert world.store.scalar(
        "SELECT status FROM banks WHERE id=?", (weak_id,)) == "failed"
    assert not world.economy.bank.pending_liquidity_requests(
        bank_id=weak_id, limit=1)
    request_state = world.store.query_one(
        "SELECT status,decided_tick FROM liquidity_support_requests WHERE bank_id=?",
        (weak_id,))
    assert dict(request_state) == {"status": "denied", "decided_tick": 1}
    denial = load_json(world.store.scalar(
        "SELECT payload_json FROM events WHERE kind='lolr_denied' "
        "AND subject_id=? ORDER BY id DESC LIMIT 1", (weak_id,)), {})
    assert denial["reason"] == "no_living_central_banker"
    assert denial["decision_actor_id"] is None
    assert world.economy.ledger.reconcile()[0]


def test_pending_liquidity_queries_use_indexed_workflow_state(tmp_path):
    world = _world(tmp_path, "indexed-lolr.db")
    bank_id = int(world.store.scalar(
        "SELECT id FROM banks WHERE status='open' ORDER BY id LIMIT 1"))
    request_event_id = world.economy.bank.request_liquidity_support(
        1, bank_id, 25_000, phase="NIGHT_CLOSE", source="index_test")
    for index in range(250):
        world.store.insert(
            "action_proposals", tick=0, actor_id=1,
            action_type="decide_liquidity_support", payload_json=f"not-json-{index}",
            evidence_event_ids_json="[]", model_call_id=None,
            rationale_summary="historical noise", validation_status="accepted",
            result_json="{}")

    pending = world.economy.bank.pending_liquidity_requests(
        bank_id=bank_id, limit=1)
    assert pending[0]["request_event_id"] == request_event_id
    assert world.runtime.scheduler._has_pending_liquidity_request()
    plan = world.store.query(
        "EXPLAIN QUERY PLAN SELECT 1 FROM liquidity_support_requests r "
        "JOIN banks b ON b.id=r.bank_id "
        "WHERE r.status='pending' AND b.status='open' "
        "ORDER BY r.request_event_id LIMIT 1")
    assert any("ix_liquidity_support_status" in str(row["detail"]) for row in plan)


def test_off_cycle_scripted_lolr_decision_replays_without_provider(tmp_path):
    source = _world(tmp_path, "source-lolr.db")
    bank_id, request_event_id = _night_close_distress(source)
    governor = _central_banker(source)

    scheduled = source.runtime.scheduler.scheduled_agents(1)
    assert int(governor["id"]) in {int(agent["id"]) for agent in scheduled}
    assert 1 % 999 != 0  # the distress request, not the rate calendar, caused the wakeup
    source_decision = asyncio.run(source.runtime._decide_one(1, governor))
    source.runtime.execute_decisions(1, [source_decision])
    source.store.commit()

    source_proposal = source.store.query_one(
        "SELECT * FROM action_proposals WHERE action_type='decide_liquidity_support'")
    assert source_proposal["validation_status"] == "accepted"
    assert source_proposal["model_call_id"] is not None
    source_call = source.store.query_one(
        "SELECT agent_id,role,purpose FROM llm_calls WHERE id=?",
        (int(source_proposal["model_call_id"]),))
    assert dict(source_call) == {
        "agent_id": int(governor["id"]),
        "role": "central_banker",
        "purpose": "central_banker",
    }
    assert source.store.scalar("SELECT status FROM banks WHERE id=?", (bank_id,)) == "open"
    assert not source.economy.bank.pending_liquidity_requests(bank_id=bank_id, limit=1)

    replay = _world(tmp_path, "replay-lolr.db", replay_source=source.store.path)
    # Operational participant rows are intentionally ignored by exact replay,
    # but they still shift every later SQLite event ID. The recorded response
    # must therefore bind to the local logical request rather than its source ID.
    replay.store.log_event(
        0, "participant_idle", {"agent_id": 1}, phase="MORNING",
        subject_type="agent", subject_id=1, importance=0.1)
    replay_bank_id, replay_request_id = _night_close_distress(replay)
    assert replay_bank_id == bank_id
    assert replay_request_id != request_event_id
    replay_governor = _central_banker(replay)
    assert replay.gateway.replay
    assert replay.gateway.replay_conn is not None

    class NoProvider:
        async def complete(self, *args, **kwargs):
            raise AssertionError("replay attempted to contact a provider")

    replay.gateway.adapters = {
        name: NoProvider() for name in replay.gateway.adapters
    }
    replay_decision = asyncio.run(replay.runtime._decide_one(1, replay_governor))
    replay_action = replay_decision["envelope"]["actions"][0]
    assert replay_action["request_event_id"] == replay_request_id
    assert replay_action["evidence_event_ids"] == [replay_request_id]
    replay.runtime.execute_decisions(1, [replay_decision])
    replay.store.commit()

    proof = verify_replay(source.store.path, replay.store.path)
    assert proof["exact"], proof["differences"]
    assert replay.store.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='lolr_granted' AND subject_id=?",
        (bank_id,)) == 1
    assert replay.economy.ledger.reconcile()[0]

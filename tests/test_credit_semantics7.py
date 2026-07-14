"""Semantics-7 loan-loss recognition without changing historical defaults."""

import json
import random

from engine.core import Economy
from engine.credit import LoanTerms
from engine.ledger import SYS_LOSS


def _economy(store, semantics: int) -> Economy:
    economy = Economy(
        store,
        {"engine_semantics_version": semantics},
        random.Random(1),
        random.Random(2),
    )
    economy.ensure_system_accounts()
    return economy


def _make_bank(economy: Economy, currency: str = "USD") -> tuple[int, int, int]:
    reserve = economy.ledger.create_account(
        "bank", None, "reserve", label=f"bank:{currency}:reserve",
        opening_cents=50_000_00, currency_code=currency)
    equity = economy.ledger.create_account(
        "bank", None, "equity", label=f"bank:{currency}:equity",
        currency_code=currency)
    bank_id = economy.store.insert(
        "banks", name=f"{currency} Bank", reserve_account_id=reserve,
        equity_account_id=equity, risk_policy_json="{}",
        reserve_requirement_bps=1000, status="open", currency_code=currency)
    economy.store.execute(
        "UPDATE accounts SET owner_id=? WHERE id IN (?,?)",
        (bank_id, reserve, equity),
    )
    return bank_id, reserve, equity


def _make_agent(economy: Economy, bank_id: int, currency: str, name: str) -> tuple[int, int]:
    agent_id = economy.store.insert(
        "agents", name=name, kind="citizen", occupation="worker", age=35, alive=1)
    checking = economy.ledger.create_account(
        "agent", agent_id, "checking", bank_id=bank_id,
        label=f"{name}:checking", currency_code=currency)
    economy.store.update("agents", agent_id, checking_account_id=checking)
    return agent_id, checking


def _force_default(economy: Economy, loan_id: int) -> None:
    for tick in (30, 60, 90):
        economy.bank.process_due_loans(tick)
    assert economy.store.scalar(
        "SELECT status FROM loans WHERE id=?", (loan_id,)) == "default"


def test_semantics7_default_recognizes_only_unrecovered_principal(store):
    economy = _economy(store, 7)
    bank_id, reserve, equity = _make_bank(economy, "EUR")
    borrower_id, borrower_account = _make_agent(economy, bank_id, "EUR", "Borrower")
    _, sink_account = _make_agent(economy, bank_id, "EUR", "Sink")
    loan_id = economy.bank.disburse_loan(
        0, bank_id, "agent", borrower_id,
        LoanTerms(10_000_00, 1000, 360, 30),
        collateral={"cash": 500_00},
    )
    assert loan_id is not None

    # Leave cash collateral below one scheduled payment so the loan reaches
    # default; seizure then reduces the recognized loss dollar-for-dollar.
    economy.ledger.transfer(1, borrower_account, sink_account, 9_500_00)
    equity_before = economy.ledger.balance(equity)
    reserve_before = economy.ledger.balance(reserve)
    eur_loss = economy.ledger.system_account(SYS_LOSS, currency_code="EUR")
    loss_before = economy.ledger.balance(eur_loss)

    _force_default(economy, loan_id)

    recovered = 500_00
    net_chargeoff = 9_500_00
    assert economy.ledger.balance(reserve) == reserve_before + recovered
    assert economy.ledger.balance(equity) == equity_before - net_chargeoff
    assert economy.ledger.balance(eur_loss) == loss_before + net_chargeoff

    transaction = economy.store.query_one(
        "SELECT id, currency_code FROM transactions "
        "WHERE kind='loan_loss_chargeoff'")
    assert transaction is not None
    assert transaction["currency_code"] == "EUR"
    entries = economy.store.query(
        "SELECT account_id, delta_cents FROM ledger_entries "
        "WHERE txn_id=? ORDER BY account_id", (int(transaction["id"]),))
    assert {int(row["account_id"]): int(row["delta_cents"]) for row in entries} == {
        equity: -net_chargeoff,
        eur_loss: net_chargeoff,
    }

    event = economy.store.query_one(
        "SELECT payload_json FROM events WHERE kind='loan_default'")
    payload = json.loads(event["payload_json"])
    assert payload["recovered_cents"] == recovered
    assert payload["charged_off_cents"] == net_chargeoff
    assert payload["net_charged_off_cents"] == net_chargeoff

    ok, diagnostics = economy.ledger.reconcile()
    assert ok, diagnostics
    assert diagnostics["currency_sums"]["EUR"] == 0


def test_semantics6_default_keeps_historical_off_ledger_writeoff(store):
    economy = _economy(store, 6)
    bank_id, _, equity = _make_bank(economy)
    borrower_id, borrower_account = _make_agent(economy, bank_id, "USD", "Borrower")
    _, sink_account = _make_agent(economy, bank_id, "USD", "Sink")
    loan_id = economy.bank.disburse_loan(
        0, bank_id, "agent", borrower_id,
        LoanTerms(10_000_00, 1000, 360, 30),
    )
    assert loan_id is not None
    economy.ledger.transfer(1, borrower_account, sink_account, 10_000_00)
    equity_before = economy.ledger.balance(equity)

    _force_default(economy, loan_id)

    assert economy.ledger.balance(equity) == equity_before
    assert economy.store.scalar(
        "SELECT COUNT(*) FROM transactions WHERE kind='loan_loss_chargeoff'",
        default=0,
    ) == 0
    event = economy.store.query_one(
        "SELECT payload_json FROM events WHERE kind='loan_default'")
    payload = json.loads(event["payload_json"])
    assert payload["charged_off_cents"] == 10_000_00
    assert "net_charged_off_cents" not in payload

    ok, diagnostics = economy.ledger.reconcile()
    assert ok, diagnostics

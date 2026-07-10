"""Ledger invariants (PRD R1): balance, conservation, reconciliation, rejection."""
import pytest

from engine.ledger import Ledger, Leg, LedgerError
from tests.conftest import make_bank, make_agent


def test_unbalanced_transaction_rejected(economy):
    a = economy.ledger.create_account("agent", 1, "checking", opening_cents=100)
    b = economy.ledger.create_account("agent", 2, "checking")
    with pytest.raises(LedgerError):
        economy.ledger.post(0, "bad", [Leg(a, -50), Leg(b, 49)])


def test_missing_account_rejected(economy):
    a = economy.ledger.create_account("agent", 1, "checking", opening_cents=100)
    with pytest.raises(LedgerError):
        economy.ledger.post(0, "bad", [Leg(a, -50), Leg(99999, 50)])


def test_grand_sum_always_zero(economy):
    bank = make_bank(economy)
    a1, acct1 = make_agent(economy, bank, "A", 5_000_00)
    a2, acct2 = make_agent(economy, bank, "B", 1_000_00)
    economy.ledger.transfer(1, acct1, acct2, 123_45)
    ok, diag = economy.ledger.reconcile()
    assert ok and diag["grand_sum_cents"] == 0


def test_reconcile_detects_tampering(economy):
    bank = make_bank(economy)
    _, acct = make_agent(economy, bank, "A", 100_00)
    # Simulate a bug writing a balance without a ledger entry.
    economy.store.execute("UPDATE accounts SET balance_cents = balance_cents + 1 WHERE id=?", (acct,))
    ok, diag = economy.ledger.reconcile()
    assert not ok
    assert diag["grand_sum_cents"] == 1 or diag["account_mismatches"]


def test_cross_bank_transfer_settles_reserves(economy):
    b1 = make_bank(economy, "B1", 10_000_00)
    b2 = make_bank(economy, "B2", 10_000_00)
    _, acct1 = make_agent(economy, b1, "A", 1_000_00)
    _, acct2 = make_agent(economy, b2, "B", 0)
    r1_before = economy.bank.reserves(b1)
    r2_before = economy.bank.reserves(b2)
    economy.ledger.transfer(1, acct1, acct2, 500_00)
    assert economy.bank.reserves(b1) == r1_before - 500_00
    assert economy.bank.reserves(b2) == r2_before + 500_00
    ok, _ = economy.ledger.reconcile()
    assert ok

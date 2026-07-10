"""Loan schedules, default, bankruptcy waterfall, scripted bank run (PRD R3, §14)."""
from engine.credit import LoanTerms
from tests.conftest import make_bank, make_agent


def test_loan_lifecycle_and_payoff(economy):
    bank = make_bank(economy, reserves=50_000_00)
    borrower, acct = make_agent(economy, bank, "B", 100_000_00)
    loan_id = economy.bank.disburse_loan(0, bank, "agent", borrower,
                                         LoanTerms(12_000_00, 1200, 360, 30))
    assert loan_id is not None
    assert economy.ledger.balance(acct) == 112_000_00
    for tick in range(30, 400, 30):
        economy.bank.process_due_loans(tick)
    loan = economy.store.query_one("SELECT * FROM loans WHERE id=?", (loan_id,))
    assert loan["status"] == "paid"
    assert int(loan["outstanding_cents"]) == 0
    # Bank earned interest into equity.
    eq = economy.store.query_one("SELECT equity_account_id FROM banks WHERE id=?", (bank,))
    assert economy.ledger.balance(int(eq["equity_account_id"])) > 0
    ok, _ = economy.ledger.reconcile()
    assert ok


def test_default_after_three_missed_payments(economy):
    bank = make_bank(economy, reserves=50_000_00)
    borrower, acct = make_agent(economy, bank, "B", 0)
    loan_id = economy.bank.disburse_loan(0, bank, "agent", borrower, LoanTerms(10_000_00, 1000, 360, 30))
    # Drain the borrower so payments fail.
    other, oacct = make_agent(economy, bank, "O", 0)
    economy.ledger.transfer(1, acct, oacct, 10_000_00)
    for tick in (30, 60, 90):
        economy.bank.process_due_loans(tick)
    loan = economy.store.query_one("SELECT * FROM loans WHERE id=?", (loan_id,))
    assert loan["status"] == "default"
    ok, _ = economy.ledger.reconcile()
    assert ok


def test_bankruptcy_waterfall(economy):
    bank = make_bank(economy, reserves=100_000_00)
    founder, _ = make_agent(economy, bank, "F", 10_000_00)
    firm_id = economy.firms.found_firm(0, founder, "DoomedCo", "retail", opening_capital_cents=0)
    firm_acct = int(economy.firms.get(firm_id)["account_id"])
    # Firm borrows 50, holds only 20 in cash by the time it dies.
    economy.bank.disburse_loan(0, bank, "firm", firm_id, LoanTerms(50_000_00, 1000, 360, 30))
    from engine.ledger import Leg, SYS_EXTERNAL
    ext = economy.ledger.system_account(SYS_EXTERNAL)
    economy.ledger.post(1, "burn", [Leg(firm_acct, -30_000_00), Leg(ext, 30_000_00)], memo="losses")
    reserves_before = economy.bank.reserves(bank)
    economy.firms.bankrupt_firm(2, firm_id, reason="test")
    firm = economy.firms.get(firm_id)
    assert firm["status"] == "bankrupt"
    # Remaining 20 flowed to the creditor bank; equity wiped.
    assert economy.bank.reserves(bank) == reserves_before + 20_000_00
    assert economy.ledger.balance(firm_acct) == 0
    assert economy.store.query("SELECT * FROM shares WHERE firm_id=?", (firm_id,)) == []
    ok, _ = economy.ledger.reconcile()
    assert ok


def test_scripted_bank_run_produces_failure(economy):
    """A scripted run must break a bank through real mechanics (§14) —
    withdrawals drain reserves; without support the bank fails with a haircut."""
    weak = make_bank(economy, "Weak", reserves=3_000_00)     # thin reserves
    strong = make_bank(economy, "Strong", reserves=100_000_00)
    depositors = [make_agent(economy, weak, f"D{i}", 5_000_00) for i in range(5)]
    from engine.actions import ActionExecutor
    ex = ActionExecutor(economy)
    failed = False
    for agent_id, _ in depositors:
        res = ex.execute_action(1, agent_id, {"type": "move_deposits", "to_bank_id": strong})
        if not res["ok"] and res["reason"] == "bank_failed_during_run":
            failed = True
            break
    assert failed, "bank should fail once reserves are exhausted (no interbank/LOLR here)"
    bank_row = economy.store.query_one("SELECT status FROM banks WHERE id=?", (weak,))
    assert bank_row["status"] == "failed"
    haircuts = economy.store.query("SELECT * FROM events WHERE kind='bank_failure'")
    assert len(haircuts) == 1
    ok, diag = economy.ledger.reconcile()
    assert ok, diag

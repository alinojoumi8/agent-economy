"""Lifecycle (PRD R11): estate settlement conserves money; identical seed ⇒
identical lifecycle schedule; sickness costs are visible."""
import random

from engine.credit import LoanTerms
from tests.conftest import make_bank, make_agent


def test_estate_settlement_with_debts_and_heir(economy):
    bank = make_bank(economy, reserves=50_000_00)
    deceased, dacct = make_agent(economy, bank, "Elder", 20_000_00, age=80)
    heir, hacct = make_agent(economy, bank, "Heir", 1_000_00, age=40)
    economy.store.insert("social_ties", agent_a=min(deceased, heir), agent_b=max(deceased, heir),
                         weight=0.9)
    economy.bank.disburse_loan(0, bank, "agent", deceased, LoanTerms(5_000_00, 1000, 360, 30))
    # Deceased holds shares too.
    firm = economy.firms.found_firm(0, deceased, "FamilyCo", "food", opening_capital_cents=0)
    heir_before = economy.ledger.balance(hacct)

    economy.lifecycle.settle_death(10, deceased, cause="test")

    a = economy.store.query_one("SELECT alive FROM agents WHERE id=?", (deceased,))
    assert not a["alive"]
    # Loan settled from estate cash (25k cash covers the 5k debt), remainder to heir.
    loan = economy.store.query_one("SELECT status, outstanding_cents FROM loans")
    assert loan["status"] == "paid"
    assert economy.ledger.balance(dacct) == 0
    assert economy.ledger.balance(hacct) == heir_before + 20_000_00  # 25k - 5k debt
    # Shares moved to heir.
    sh = economy.store.query_one(
        "SELECT qty FROM shares WHERE firm_id=? AND holder_id=?", (firm, heir))
    assert sh and int(sh["qty"]) == 1000
    ok, diag = economy.ledger.reconcile()
    assert ok, diag


def test_escheat_without_heir(economy):
    bank = make_bank(economy)
    loner, lacct = make_agent(economy, bank, "Loner", 7_000_00, age=90)
    economy.lifecycle.settle_death(5, loner)
    from engine.ledger import SYS_GOV
    gov = economy.ledger.system_account(SYS_GOV)
    assert economy.ledger.balance(gov) == 7_000_00
    ok, _ = economy.ledger.reconcile()
    assert ok


def test_identical_seed_identical_lifecycle_schedule(tmp_path):
    """Same seed ⇒ same sequence of lifecycle events (R11 acceptance d)."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from engine.store import Store
    from engine.core import Economy

    def run_events(dbname):
        s = Store(str(tmp_path / dbname))
        s.init_run_meta("t", 99, {})
        e = Economy(s, {}, random.Random(5), random.Random(99))
        e.ensure_system_accounts()
        bank = None
        from tests.conftest import make_bank as mb, make_agent as ma
        bank = mb(e)
        for i in range(20):
            ma(e, bank, f"P{i}", 1_000_00, age=60 + i)
        for tick in range(1, 200):
            e.lifecycle.run_nightly(tick)
        events = [(r["tick"], r["kind"]) for r in s.query(
            "SELECT tick, kind FROM events WHERE kind IN "
            "('illness_onset','illness_critical','recovery','death','birthday','retirement') "
            "ORDER BY id")]
        s.close()
        return events

    assert run_events("a.db") == run_events("b.db")


def test_sick_agent_pays_medical_and_skips_wages(economy):
    bank = make_bank(economy)
    worker, wacct = make_agent(economy, bank, "W", 10_000_00)
    firm_owner, _ = make_agent(economy, bank, "Own", 10_000_00)
    firm_id = economy.firms.found_firm(0, firm_owner, "ShopCo", "retail")
    from engine.ledger import Leg, SYS_EXTERNAL
    facct = int(economy.firms.get(firm_id)["account_id"])
    economy.ledger.post(0, "seed", [Leg(facct, 100_000_00), Leg(economy.ledger.system_account(SYS_EXTERNAL), -100_000_00)])
    economy.store.insert("employments", firm_id=firm_id, agent_id=worker, title="w",
                         wage_cents=3_000_00, start_tick=0, status="active",
                         pay_interval_ticks=30, next_pay_tick=30)
    # Mark sick and process a payday + a medical charge.
    economy.store.update("agents", worker, health="sick", sick_since_tick=25)
    bal_before = economy.ledger.balance(wacct)
    economy.lifecycle._charge_medical(30, worker)
    economy.firms.process_payroll(30)
    assert economy.ledger.balance(wacct) == bal_before - 5000  # medical, no wage
    skipped = economy.store.query("SELECT * FROM events WHERE kind='wage_skipped_illness'")
    assert len(skipped) == 1
    ok, _ = economy.ledger.reconcile()
    assert ok

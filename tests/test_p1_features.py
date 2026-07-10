"""P1 features: government fiscal layer + elections (R12), VC track (R13),
health economy (R17). Engine-level units + one world integration run."""
import asyncio

from engine.government import Government
from engine.ledger import Leg, SYS_EXTERNAL, SYS_GOV
from engine.store import Store
from world.loop import World
from tests.conftest import make_bank, make_agent


def _fund_firm(economy, firm_id, cents):
    acct = int(economy.firms.get(firm_id)["account_id"])
    ext = economy.ledger.system_account(SYS_EXTERNAL)
    economy.ledger.post(0, "firm_endowment", [Leg(acct, cents), Leg(ext, -cents)])
    return acct


# ── R12: taxes, benefits, elections ──────────────────────────────────────────
def test_payroll_withholds_income_tax(economy):
    bank = make_bank(economy)
    founder, _ = make_agent(economy, bank, "Founder", 50_000)
    worker, wacct = make_agent(economy, bank, "Worker", 0)
    firm_id = economy.firms.found_firm(0, founder, "TaxCo", "services")
    _fund_firm(economy, firm_id, 1_000_000)
    economy.store.insert("employments", firm_id=firm_id, agent_id=worker, title="worker",
                         wage_cents=100_000, start_tick=0, status="active",
                         pay_interval_ticks=30, next_pay_tick=30)
    economy.store.record_metric(0, "tax_rate_bps", 2000)   # 20%

    economy.firms.process_payroll(30)

    gov_acct = economy.ledger.system_account(SYS_GOV)
    assert economy.ledger.balance(wacct) == 80_000          # net of tax
    assert economy.ledger.balance(gov_acct) == 20_000       # withheld
    ev = economy.store.query_one(
        "SELECT payload_json FROM events WHERE kind='wage_paid'")
    assert '"tax_cents": 20000' in ev["payload_json"]
    ok, diag = economy.ledger.reconcile()
    assert ok, diag


def test_unemployment_benefits_flow_to_jobless_only(economy):
    bank = make_bank(economy)
    jobless, jacct = make_agent(economy, bank, "Jobless", 0)
    employed, eacct = make_agent(economy, bank, "Employed", 0)
    founder, _ = make_agent(economy, bank, "Founder", 10_000)
    firm_id = economy.firms.found_firm(0, founder, "JobCo", "services")
    economy.store.insert("employments", firm_id=firm_id, agent_id=employed, title="w",
                         wage_cents=1000, start_tick=0, status="active",
                         pay_interval_ticks=30, next_pay_tick=999)
    gov = Government(economy.store, economy.ledger,
                     {"unemployment_benefit_cents": 90_000, "benefit_interval_ticks": 30,
                      "election_interval_ticks": 0})
    gov.initialize(0)

    gov.run_nightly(29)   # not a benefit tick
    assert economy.ledger.balance(jacct) == 0
    gov.run_nightly(30)
    assert economy.ledger.balance(jacct) == 90_000
    assert economy.ledger.balance(eacct) == 0               # employed: nothing
    assert gov.treasury_balance() == -90_000                # deficit is visible
    ok, diag = economy.ledger.reconcile()
    assert ok, diag


def test_election_shifts_fiscal_policy_within_bounds(economy):
    bank = make_bank(economy)
    for i in range(5):   # five miserable unemployed voters → EXPAND wins
        aid, _ = make_agent(economy, bank, f"V{i}", 1000)
        economy.store.insert("beliefs", agent_id=aid, key="sentiment", value=-0.9,
                             updated_tick=0)
    gov = Government(economy.store, economy.ledger,
                     {"tax_rate_bps": 1500, "unemployment_benefit_cents": 120_000,
                      "tax_step_bps": 300, "benefit_step_cents": 40_000,
                      "max_tax_bps": 2000, "max_benefit_cents": 170_000})
    gov.initialize(0)

    r1 = gov.hold_election(180)
    assert r1["direction"] == "expand"
    assert r1["new_tax_bps"] == 1800 and r1["new_benefit_cents"] == 160_000
    r2 = gov.hold_election(360)   # clamped at the guardrails
    assert r2["new_tax_bps"] == 2000 and r2["new_benefit_cents"] == 170_000
    assert economy.store.query("SELECT * FROM events WHERE kind='election_held'")

    # Happy, right-leaning employed voters → AUSTERITY wins and steps back down.
    economy.store.execute("UPDATE beliefs SET value=0.8 WHERE key='sentiment'")
    economy.store.execute("UPDATE agents SET political_lean=0.9")
    for r in economy.store.query("SELECT id FROM agents"):
        economy.store.insert("employments", firm_id=1, agent_id=int(r["id"]), title="w",
                             wage_cents=1000, start_tick=0, status="active",
                             pay_interval_ticks=30, next_pay_tick=999)
    r3 = gov.hold_election(540)
    assert r3["direction"] == "austerity"
    assert r3["new_tax_bps"] == 1700 and r3["new_benefit_cents"] == 130_000


# ── R13: pitch → term sheet → cap table → write-off ─────────────────────────
def test_vc_pitch_fund_and_cap_table(economy):
    from engine.actions import ActionExecutor
    ex = ActionExecutor(economy)
    bank = make_bank(economy)
    founder, _ = make_agent(economy, bank, "Founder", 20_000)
    vc, vc_acct = make_agent(economy, bank, "Partner", 2_000_000,
                             kind="staff", role="vc_partner")
    firm_id = economy.firms.found_firm(0, founder, "SeedCo", "tech")   # 1000 shares
    firm_acct = _fund_firm(economy, firm_id, 10_000)

    r = ex.execute_action(1, founder, {"type": "pitch_vc", "firm_id": firm_id,
                                       "ask": 500_000, "summary": "expand"})
    assert r["ok"], r
    pitch_id = r["pitch_id"]
    # Only the partner can fund; a citizen is rejected.
    assert not ex.execute_action(1, founder, {"type": "fund_pitch", "pitch_id": pitch_id,
                                              "amount": 500_000, "equity_bps": 2000})["ok"]
    r2 = ex.execute_action(2, vc, {"type": "fund_pitch", "pitch_id": pitch_id,
                                   "amount": 500_000, "equity_bps": 2000})
    assert r2["ok"], r2
    assert r2["shares_issued"] == 250                      # 1000 × 0.20 / 0.80
    firm = economy.firms.get(firm_id)
    assert int(firm["shares_outstanding"]) == 1250
    held = economy.store.query_one(
        "SELECT qty FROM shares WHERE firm_id=? AND holder_id=?", (firm_id, vc))
    assert int(held["qty"]) == 250
    assert economy.ledger.balance(firm_acct) == 510_000
    assert economy.ledger.balance(vc_acct) == 1_500_000
    assert economy.store.query_one(
        "SELECT status FROM pitches WHERE id=?", (pitch_id,))["status"] == "funded"
    ok, diag = economy.ledger.reconcile()
    assert ok, diag


def test_vc_decline_followon_and_writeoff(economy):
    from engine.actions import ActionExecutor
    ex = ActionExecutor(economy)
    bank = make_bank(economy)
    founder, _ = make_agent(economy, bank, "F2", 20_000)
    vc, _ = make_agent(economy, bank, "P2", 2_000_000, kind="staff", role="vc_partner")
    firm_id = economy.firms.found_firm(0, founder, "RiskyCo", "tech")
    _fund_firm(economy, firm_id, 5_000)

    p1 = ex.execute_action(1, founder, {"type": "pitch_vc", "firm_id": firm_id, "ask": 100_000})
    assert ex.execute_action(1, vc, {"type": "decline_pitch", "pitch_id": p1["pitch_id"],
                                     "reason": "too early"})["ok"]
    p2 = ex.execute_action(2, founder, {"type": "pitch_vc", "firm_id": firm_id, "ask": 100_000})
    assert ex.execute_action(2, vc, {"type": "fund_pitch", "pitch_id": p2["pitch_id"],
                                     "amount": 100_000, "equity_bps": 2500})["ok"]
    p3 = ex.execute_action(3, founder, {"type": "pitch_vc", "firm_id": firm_id, "ask": 50_000})
    assert economy.store.query_one(
        "SELECT follow_on FROM pitches WHERE id=?", (p3["pitch_id"],))["follow_on"] == 1

    economy.firms.bankrupt_firm(4, firm_id, reason="test")
    economy.vc.run_nightly(4)
    assert economy.store.query_one(
        "SELECT status FROM pitches WHERE id=?", (p2["pitch_id"],))["status"] == "written_off"
    assert economy.store.query("SELECT * FROM events WHERE kind='vc_writeoff'")
    ok, diag = economy.ledger.reconcile()
    assert ok, diag


# ── R17: hospital revenue, insurance claims, premiums, epidemic ──────────────
def test_medical_bill_pays_hospital_with_insurance_split(economy):
    bank = make_bank(economy)
    patient, pacct = make_agent(economy, bank, "Patient", 100_000)
    hosp_founder, _ = make_agent(economy, bank, "Doc", 10_000)
    ins_founder, _ = make_agent(economy, bank, "Broker", 10_000)
    hospital = economy.firms.found_firm(0, hosp_founder, "Hosp", "health",
                                        product={"product": "care", "unit_price_cents": 5000,
                                                 "base_input_cost_cents": 0, "output_per_worker": 0})
    hosp_acct = int(economy.firms.get(hospital)["account_id"])
    insurer = economy.firms.found_firm(0, ins_founder, "Mutual", "insurance")
    ins_acct = _fund_firm(economy, insurer, 50_000)
    economy.store.insert("insurance_policies", agent_id=patient, insurer_firm_id=insurer,
                         premium_cents=3000, coverage_bps=8000, start_tick=0,
                         next_premium_tick=999, premium_interval_ticks=30, status="active")

    economy.lifecycle._charge_medical(1, patient)   # bill = 5000 (default)

    assert economy.ledger.balance(hosp_acct) == 5000        # full fee is hospital revenue
    assert economy.ledger.balance(ins_acct) == 50_000 - 4000  # insurer paid 80%
    assert economy.ledger.balance(pacct) == 100_000 - 1000    # patient paid 20%
    assert economy.store.query("SELECT * FROM events WHERE kind='insurance_claim'")
    ok, diag = economy.ledger.reconcile()
    assert ok, diag


def test_premium_collection_and_lapse(economy):
    bank = make_bank(economy)
    rich, racct = make_agent(economy, bank, "Rich", 50_000)
    poor, _ = make_agent(economy, bank, "Poor", 100)
    ins_founder, _ = make_agent(economy, bank, "Broker", 10_000)
    insurer = economy.firms.found_firm(0, ins_founder, "Mutual", "insurance")
    ins_acct = _fund_firm(economy, insurer, 10_000)
    for agent in (rich, poor):
        economy.store.insert("insurance_policies", agent_id=agent, insurer_firm_id=insurer,
                             premium_cents=3000, coverage_bps=8000, start_tick=0,
                             next_premium_tick=5, premium_interval_ticks=30, status="active")

    economy.lifecycle._collect_premiums(5)

    rich_pol = economy.store.query_one(
        "SELECT * FROM insurance_policies WHERE agent_id=?", (rich,))
    poor_pol = economy.store.query_one(
        "SELECT * FROM insurance_policies WHERE agent_id=?", (poor,))
    assert rich_pol["status"] == "active" and int(rich_pol["next_premium_tick"]) == 35
    assert economy.ledger.balance(racct) == 47_000
    assert poor_pol["status"] == "lapsed"
    assert economy.ledger.balance(ins_acct) == 13_000
    ok, diag = economy.ledger.reconcile()
    assert ok, diag


def test_epidemic_multiplier_scales_illness_onset(economy):
    bank = make_bank(economy)
    for i in range(10):
        make_agent(economy, bank, f"A{i}", 10_000, age=30)
    economy.store.record_metric(0, "epidemic_multiplier", 10_000.0)  # hazard → 0.9 cap
    economy.lifecycle.run_nightly(1)
    sick = economy.store.scalar(
        "SELECT COUNT(*) FROM agents WHERE health IN ('sick','critical')", default=0)
    assert sick >= 5   # ~90% of 10 under the capped hazard


# ── world integration: all three features live in one deterministic run ─────
def _p1_cfg(**over):
    cfg = {
        "seed": 42,
        "population": {"size": 24},
        "banks": {"count": 2},
        "firms": {"count": 5, "listed": 2},
        "budget": {"cap_usd": 200.0, "oracle_reserve_usd": 10.0, "conversation_pairs": 15,
                   "thresholds": [0.60, 0.80, 0.95]},
        "llm": {"default_route": {"provider": "scripted", "model": "scripted"}, "routes": {}},
        "checkpoint_every": 0,
        "outlets": [{"id": 1, "name": "A", "slant": "pro-market-sensational"},
                    {"id": 2, "name": "B", "slant": "cautious-pro-labor"}],
        "government": {"tax_rate_bps": 1500, "unemployment_benefit_cents": 60_000,
                       "benefit_interval_ticks": 10, "election_interval_ticks": 15},
        "vc": {"fund_cents": 5_000_000},
        "health": {"hospital": True, "insurer": True, "premium_cents": 3000,
                   "coverage_bps": 8000, "premium_interval_ticks": 10},
        "shocks": [{"kind": "epidemic", "trigger": "trend", "trigger_params": {"start": 5},
                    "duration_ticks": 8, "params": {"multiplier": 400.0}}],
    }
    cfg.update(over)
    return cfg


def test_world_p1_integration(tmp_path):
    s = Store(str(tmp_path / "p1.db"))
    cfg = _p1_cfg()
    s.init_run_meta("p1", cfg["seed"], cfg)
    w = World(s, cfg)
    w.initialize()

    async def go():
        for _ in range(32):
            await w.step()
    asyncio.run(go())

    # R12: taxes withheld, benefits paid, elections held.
    assert s.scalar("SELECT COUNT(*) FROM events WHERE kind='wage_paid' "
                    "AND json_extract(payload_json,'$.tax_cents') > 0") > 0
    assert s.scalar("SELECT COUNT(*) FROM events WHERE kind='benefits_paid'") > 0
    assert s.scalar("SELECT COUNT(*) FROM events WHERE kind='election_held'") >= 2
    # R17: hospital + insurer exist; sickness spiked during the epidemic window.
    assert s.query_one("SELECT id FROM firms WHERE sector='health'")
    assert s.query_one("SELECT id FROM firms WHERE sector='insurance'")
    assert s.scalar("SELECT COUNT(*) FROM events WHERE kind='epidemic_started'") == 1
    assert s.scalar("SELECT COUNT(*) FROM events WHERE kind='epidemic_ended'") == 1
    epidemic_onsets = s.scalar(
        "SELECT COUNT(*) FROM events WHERE kind='illness_onset' AND tick BETWEEN 5 AND 13")
    assert epidemic_onsets > 0
    assert s.scalar("SELECT COUNT(*) FROM insurance_policies WHERE status='active'") > 0
    # Medical money flowed to the hospital, not the sink.
    hospital_cash = s.scalar(
        "SELECT COALESCE(SUM(le.delta_cents),0) FROM ledger_entries le "
        "JOIN transactions t ON t.id=le.txn_id "
        "JOIN accounts a ON a.id=le.account_id "
        "JOIN firms f ON f.account_id=a.id AND f.sector='health' "
        "WHERE t.kind IN ('medical_cost','insurance_claim') AND le.delta_cents>0", default=0)
    assert hospital_cash > 0
    # The books still close after all of it.
    ok, diag = w.economy.ledger.reconcile()
    assert ok, diag


def test_world_p1_determinism(tmp_path):
    def event_log(name):
        s = Store(str(tmp_path / name))
        cfg = _p1_cfg()
        s.init_run_meta(name, cfg["seed"], cfg)
        w = World(s, cfg)
        w.initialize()

        async def go():
            for _ in range(18):
                await w.step()
        asyncio.run(go())
        rows = w.store.query("SELECT tick, kind, payload_json FROM events ORDER BY id")
        out = [(r["tick"], r["kind"], r["payload_json"]) for r in rows]
        w.store.close()
        return out

    assert event_log("pd1.db") == event_log("pd2.db")

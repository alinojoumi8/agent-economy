"""Genesis: build a fresh world from config (population, institutions, firms).

Everything here is deterministic given the seed: the population comes from the
attributed synthetic-heuristic persona generator (its own PRNG), and structural choices (bank
assignment, social ties, initial employment) come from the engine PRNG. Money is
minted from the visible external endowment account so the books reconcile to zero
from tick 0.
"""
from __future__ import annotations

import json
import random
from typing import Optional, TYPE_CHECKING

from engine.core import Economy
from engine.ledger import SYS_EXTERNAL, SYS_INFLOW
from agents.memory import Memory
from agents.personas.library import Persona, sample_persona, sample_population

if TYPE_CHECKING:
    from research.r21 import R21Calibration


class Genesis:
    def __init__(self, economy: Economy, config: dict, persona_prng: random.Random,
                 *, calibration: "R21Calibration | None" = None):
        self.e = economy
        self.store = economy.store
        self.config = config
        self.prng = economy.prng
        self.persona_prng = persona_prng
        self.calibration = calibration
        self.r21_income_by_agent: dict[int, int] = {}
        self.memory = Memory(self.store, config)
        self.bank_ids: list[int] = []
        self.outlets = config.get("outlets", [
            {"id": 1, "name": "The Ledger", "slant": "pro-market-sensational"},
            {"id": 2, "name": "Commons Dispatch", "slant": "cautious-pro-labor"},
        ])

    def _citizen_tier(self) -> tuple[str, int]:
        """Keep the optional R19 core/periphery throttle out of baseline v7.

        Semantics 5 and 6 historically classified genesis citizens as
        peripheral even when no regional living-world configuration was
        present, so their persisted behavior must not move.  Maintained
        semantics 7 treats citizens as core unless the optional regional
        economy is explicitly enabled; otherwise a v1-style acceptance run
        would schedule only institutional agents and rumors could never affect
        household decisions.
        """
        if (int(self.config.get("engine_semantics_version", 1)) >= 7
                and bool(self.config.get("population", {}).get(
                    "baseline_citizens_core", False))
                and not self.e.regions.enabled):
            return "core", 1
        return "periphery", 0

    # ── top-level ────────────────────────────────────────────────────────────
    def build(self) -> None:
        self.e.ensure_system_accounts()
        self.e.regions.initialize(0)
        self._central_bank()
        self._banks()
        self._institutions()
        self.e.politics.initialize(0)
        self._population()
        self._firms()
        self._health_institutions()
        self._social_graph()
        self.e.startups.initialize_trader_profiles(0)
        self.e.regions.rebalance_tiers(0)
        self._initial_metrics()
        self.store.log_event(0, "genesis", {
            "banks": len(self.bank_ids),
            "agents": int(self.store.scalar("SELECT COUNT(*) FROM agents", default=0)),
            "firms": int(self.store.scalar("SELECT COUNT(*) FROM firms", default=0))},
            phase="NIGHT_CLOSE", importance=3.0)
        self.store.commit()

    # ── central bank ─────────────────────────────────────────────────────────
    def _central_bank(self) -> None:
        region_id = self.e.regions.primary_region_id() if self.e.regions.enabled else None
        currency = self.e.regions.currency_for_region(region_id)
        currencies = [currency]
        if int(self.config.get("engine_semantics_version", 1)) >= 6:
            configured_currencies = [
                str(row["code"]) for row in self.store.query(
                    "SELECT code FROM currencies ORDER BY code")
            ]
            currencies = ([currency] + [
                code for code in configured_currencies if code != currency
            ]) if configured_currencies else currencies
        for code in currencies:
            self.e.ledger.create_account(
                "central_bank", 1, "reserve",
                label=("central_bank_reserve" if code == currency
                       else f"central_bank_reserve:{code}"),
                currency_code=code)
        gov_agent = self.store.insert(
            "agents", name="Governor Vale", kind="staff", occupation="central banker",
            role="central_banker", age=58, model_tier="strong", alive=1, arrived_tick=0,
            region_id=region_id, population_tier="core", pinned_core=1,
            personality_json=json.dumps({"prudent": 0.9}), cadence_json=json.dumps({"act": 1}))
        self.central_bank_agent = gov_agent
        self.store.log_event(0, "institution_created", {"kind": "central_bank", "agent_id": gov_agent},
                             phase="NIGHT_CLOSE")

    # ── commercial banks ─────────────────────────────────────────────────────
    def _banks(self) -> None:
        bank_cfg = self.config.get("banks", {})
        names = bank_cfg.get("names", ["First Bank", "Union Bank", "Meridian Trust"])
        n = int(bank_cfg.get("count", 2))
        for i in range(n):
            name = names[i % len(names)]
            region_id = self.e.regions.region_for_bank_index(i) if self.e.regions.enabled else None
            currency = self.e.regions.currency_for_region(region_id)
            res = self.e.ledger.create_account("bank", None, "reserve", label=f"{name}_reserve",
                                               currency_code=currency)
            eq = self.e.ledger.create_account("bank", None, "equity", label=f"{name}_equity",
                                              currency_code=currency)
            bid = self.store.insert(
                "banks", name=name, reserve_account_id=res, equity_account_id=eq,
                risk_policy_json=json.dumps(bank_cfg.get("risk_policy",
                    {"min_rate_bps": 300, "max_rate_bps": 3000, "default_rate_bps": 900})),
                reserve_requirement_bps=int(bank_cfg.get("reserve_requirement_bps", 1000)),
                status="open", region_id=region_id, currency_code=currency)
            self.store.execute("UPDATE accounts SET owner_id=? WHERE id=?", (bid, res))
            self.store.execute("UPDATE accounts SET owner_id=? WHERE id=?", (bid, eq))
            self.bank_ids.append(bid)

    def _fund_bank_reserves(self) -> None:
        """After deposits exist, fund each bank's reserves to the configured ratio."""
        ratio = float(self.config.get("banks", {}).get("initial_reserve_ratio", 0.6))
        for bid in self.bank_ids:
            deposits = self.e.bank.deposits(bid)
            target = int(deposits * ratio)
            b = self.e.bank.get(bid)
            ext = self.e.ledger.system_account(SYS_EXTERNAL, currency_code=b["currency_code"])
            from engine.ledger import Leg
            self.e.ledger.post(0, "reserve_endowment", [
                Leg(int(b["reserve_account_id"]), target, "initial reserves"),
                Leg(ext, -target, "reserve endowment"),
            ], memo=f"endow reserves bank {bid}")

    # ── institutional staff ──────────────────────────────────────────────────
    def _institutions(self) -> None:
        # Credit officers (one per bank).
        for i, bid in enumerate(self.bank_ids):
            self._spawn_staff(f"Officer {i+1}", "credit officer", "credit_officer", employer_id=bid,
                              opening_cents=200_000)
        # News outlets: an editor + reporter each.
        for outlet in self.outlets:
            self._spawn_staff(f"Editor {outlet['name']}", "editor", "editor",
                              extra={"outlet_id": outlet["id"]}, opening_cents=150_000)
            self._spawn_staff(f"Reporter {outlet['name']}", "reporter", "reporter",
                              extra={"outlet_id": outlet["id"]}, opening_cents=120_000)
        # VC partner + exchange operator. The partner's checking IS the fund (R13).
        vc_fund = int(self.config.get("vc", {}).get("fund_cents", 10_000_000))
        self._spawn_staff("VC Partner", "venture capitalist", "vc_partner", opening_cents=vc_fund)
        self._spawn_staff("Exchange Operator", "exchange operator", "exchange", opening_cents=150_000)
        # At least one lawyer (required to incorporate).
        self._spawn_staff("Counsel Reyes", "lawyer", "lawyer", opening_cents=300_000)
        # Government official (R12) — the fiscal layer speaks through this seat.
        if self.config.get("government"):
            self._spawn_staff("Secretary Lin", "treasury secretary", "gov_official",
                              opening_cents=200_000)

    def _spawn_staff(self, name: str, occupation: str, role: str, *, employer_id: Optional[int] = None,
                     extra: Optional[dict] = None, opening_cents: int = 150_000) -> int:
        if self.e.regions.enabled:
            region_id = self.e.regions.primary_region_id()
            bank_id = self.e.regions.bank_for_region(self.bank_ids, region_id)
        else:
            region_id = None
            bank_id = self.prng.choice(self.bank_ids)
        agent_id = self.store.insert(
            "agents", name=name, kind="staff", occupation=occupation, role=role,
            employer_id=employer_id, age=self.prng.randint(30, 60), model_tier="strong",
            alive=1, arrived_tick=0, risk_tolerance=0.5, political_lean=0.0,
            personality_json=json.dumps(extra or {}),
            media_diet_json=json.dumps([o["id"] for o in self.outlets]),
            cadence_json=json.dumps({"act": 1}), region_id=region_id,
            population_tier="core", pinned_core=1)
        self._open_accounts(agent_id, bank_id, opening_cents, savings_cents=0)
        self._seed_beliefs(agent_id, bank_id)
        return agent_id

    # ── population ───────────────────────────────────────────────────────────
    def _population(self) -> None:
        pop_cfg = self.config.get("population", {})
        if pop_cfg.get("target_total") is not None:
            reserved_health = 2 if self.config.get("health") else 0
            size = max(0, int(pop_cfg["target_total"]) - int(self.store.scalar(
                "SELECT COUNT(*) FROM agents", default=0)) - reserved_health)
        else:
            reserved_health = 0
            size = int(pop_cfg.get("size", 70))
        calibrated = bool(self.calibration and self.calibration.enabled)
        household_samples = (self.calibration.sample_households(
            self.persona_prng, size, len(self.outlets)) if calibrated else [])
        personas = ([sample.persona for sample in household_samples] if calibrated
                    else sample_population(
                        self.persona_prng, size, n_outlets=len(self.outlets)))
        population_tier, pinned_core = self._citizen_tier()
        # Guarantee at least one lawyer occupation exists among citizens too.
        for index, p in enumerate(personas):
            if self.e.regions.enabled:
                region_id = self.e.regions.region_for_new_citizen(
                    reserved_northstar=reserved_health)
                bank_id = self.e.regions.bank_for_region(self.bank_ids, region_id)
            else:
                region_id = None
                bank_id = self.prng.choice(self.bank_ids)
            checking = int(p.wealth_cents * 0.7)
            savings = p.wealth_cents - checking
            agent_id = self.store.insert(
                "agents", name=p.name, kind="citizen", occupation=p.occupation,
                age=p.age, health="healthy", dependents=p.dependents,
                personality_json=json.dumps(p.personality), political_lean=p.political_lean,
                media_diet_json=json.dumps(p.media_diet), risk_tolerance=p.risk_tolerance,
                cadence_json=json.dumps(self._cadence_for(p)), model_tier="citizen",
                alive=1, retired=int(self._is_retired(p)), arrived_tick=0,
                region_id=region_id, population_tier=population_tier,
                pinned_core=pinned_core)
            self._open_accounts(agent_id, bank_id, checking, savings)
            self._seed_beliefs(agent_id, bank_id)
            if calibrated:
                sample = household_samples[index]
                self.r21_income_by_agent[agent_id] = sample.annual_income_cents
                self.store.log_event(
                    0, "r21_household_sampled",
                    {"agent_id": agent_id, **sample.provenance()},
                    phase="NIGHT_CLOSE", subject_type="agent",
                    subject_id=agent_id, importance=0.5)

    def _cadence_for(self, p: Persona) -> dict:
        if (int(self.config.get("engine_semantics_version", 1)) >= 7
                and self._is_retired(p)):
            lifecycle = self.config.get("lifecycle", {})
            return {
                "act": max(1, int(lifecycle.get("retired_act_every", 2))),
                "portfolio": max(1, int(lifecycle.get("retired_portfolio_every", 5))),
                "career": 30,
                "news": max(1, int(lifecycle.get("retired_news_every", 1))),
            }
        return {"act": 3, "portfolio": 7, "career": 30}

    def _is_retired(self, p: Persona) -> bool:
        calibration = getattr(self, "calibration", None)
        if calibration and calibration.enabled \
                and "r21_retired" in p.extra:
            return bool(p.extra["r21_retired"])
        retirement_age = 65
        if int(self.config.get("engine_semantics_version", 1)) >= 7:
            retirement_age = int(
                self.config.get("lifecycle", {}).get("retirement_age", 65))
        return int(p.age) >= retirement_age

    # ── firms ────────────────────────────────────────────────────────────────
    def _firms(self) -> None:
        firm_cfg = self.config.get("firms", {})
        count = int(firm_cfg.get("count", 12))
        sectors = firm_cfg.get("sectors", ["food", "retail", "manufacturing", "services", "tech", "energy"])
        # Founders: pick suitable citizens.
        candidates = self.store.query(
            "SELECT id FROM agents WHERE kind='citizen' AND age BETWEEN 28 AND 60 ORDER BY id")
        founders = [int(r["id"]) for r in candidates]
        self.prng.shuffle(founders)
        n_listed = int(firm_cfg.get("listed", 3))
        actual_count = min(count, len(founders))
        calibrated = bool(self.calibration and self.calibration.enabled)
        firm_samples = (self.calibration.sample_firms(actual_count)
                        if calibrated else [])
        for i in range(actual_count):
            founder = founders[i]
            sector = sectors[i % len(sectors)]
            price = self.prng.randint(300, 900)
            product = {"product": f"{sector}_good", "unit_price_cents": price,
                       "base_input_cost_cents": int(price * 0.4),
                       "output_per_worker": self.prng.randint(4, 8)}
            capital = self.prng.randint(500_000, 3_000_000)
            firm_id = self.e.firms.found_firm(0, founder, f"{sector.title()} Co {i+1}", sector,
                                              product=product, opening_capital_cents=0)
            # Endow firm operating capital from external so it can pay wages/inputs.
            from engine.ledger import Leg
            firm = self.e.firms.get(firm_id)
            acct = int(firm["account_id"])
            ext = self.e.ledger.system_account(
                SYS_EXTERNAL, currency_code=str(firm["currency_code"] or "USD"))
            self.e.ledger.post(0, "firm_endowment", [
                Leg(acct, capital, "seed capital"), Leg(ext, -capital, "endowment")],
                memo=f"seed firm {firm_id}")
            self.store.update("firms", firm_id, inventory=self.prng.randint(10, 40))
            # Initial employees.
            target_headcount = firm_samples[i].requested_employees if calibrated else None
            realized_headcount = self._staff_firm(
                firm_id, product["unit_price_cents"],
                target_headcount=target_headcount)
            if calibrated:
                self.calibration.record_realized_firm(
                    firm_samples[i], realized_headcount)
                self.store.log_event(
                    0, "r21_firm_size_sampled",
                    {"firm_id": firm_id, "realized_employees": realized_headcount,
                     **firm_samples[i].provenance()},
                    phase="NIGHT_CLOSE", subject_type="firm",
                    subject_id=firm_id, importance=0.5)
            if i < n_listed:
                self._list_firm(firm_id, price)
        if calibrated:
            self.store.log_event(
                0, "r21_calibration_applied", self.calibration.evidence(),
                phase="NIGHT_CLOSE", importance=3.0)

    def _staff_firm(self, firm_id: int, price: int, *,
                    target_headcount: int | None = None) -> int:
        wage = max(250_000, price * 400)
        firm = self.e.firms.get(firm_id)
        if target_headcount is None:
            pool = self.store.query(
                "SELECT id FROM agents WHERE kind='citizen' AND retired=0 AND employer_id IS NULL "
                "AND age BETWEEN 20 AND 64 AND (? IS NULL OR region_id=?) ORDER BY id LIMIT 3",
                (firm["region_id"], firm["region_id"]))
        else:
            pool = self.store.query(
                "SELECT id FROM agents WHERE kind='citizen' AND retired=0 AND employer_id IS NULL "
                "AND age BETWEEN 20 AND 64 AND (? IS NULL OR region_id=?) ORDER BY id LIMIT ?",
                (firm["region_id"], firm["region_id"], max(0, int(target_headcount))))
        pay_interval = int(self.config.get("firms", {}).get("pay_interval_ticks", 30))
        for r in pool:
            aid = int(r["id"])
            employee_wage = wage
            if target_headcount is not None:
                employee_wage = max(
                    self.calibration.minimum_wage_per_interval_cents,
                    min(self.calibration.maximum_wage_per_interval_cents,
                        int(round(self.r21_income_by_agent.get(aid, wage) / 12))))
            self.store.insert("employments", firm_id=firm_id, agent_id=aid, title="worker",
                              wage_cents=employee_wage, start_tick=0, status="active",
                              pay_interval_ticks=pay_interval, next_pay_tick=pay_interval)
            self.store.execute("UPDATE agents SET employer_id=? WHERE id=?", (firm_id, aid))
        return len(pool)

    def _list_firm(self, firm_id: int, price: int) -> None:
        firm = self.e.firms.get(firm_id)
        so = int(firm["shares_outstanding"])
        founder = int(firm["founder_agent_id"])
        # Distribute a float to a handful of citizens so the book has participants.
        float_shares = so // 2
        holders = self.store.query(
            "SELECT id FROM agents WHERE kind='citizen' AND (? IS NULL OR region_id=?) ORDER BY id LIMIT 6",
            (firm["region_id"], firm["region_id"]))
        per = max(1, float_shares // max(1, len(holders)))
        # Move shares from founder to holders.
        self.store.execute("UPDATE shares SET qty=qty-? WHERE firm_id=? AND holder_id=? AND holder_type='agent'",
                           (per * len(holders), firm_id, founder))
        for h in holders:
            holder_id = int(h["id"])
            self.e.exchange._adjust_shares(firm_id, "agent", holder_id, per)
            if int(self.config.get("engine_semantics_version", 2)) >= 6:
                self.store.insert(
                    "share_movements", tick=0, firm_id=firm_id,
                    from_holder_type="agent", from_holder_id=founder,
                    to_holder_type="agent", to_holder_id=holder_id, qty=per,
                    movement_type="bootstrap_distribution", reference_type="genesis",
                    reference_id=firm_id, price_cents=None, amount_cents=0,
                    transaction_id=None)
        reference = price * 100 if price < 100 else price
        if int(self.config.get("engine_semantics_version", 2)) >= 6:
            # The opening cap table supplies sellers, but there is deliberately
            # no stock metric until agents express crossing prices.
            self.e.firms.list_firm(0, firm_id, None, float_shares)
        else:
            self.e.firms.list_firm(
                0, firm_id, reference, float_shares, legacy_reference_price=True)
            # Preserve the duplicate genesis metric written by semantics 1-5;
            # recorded runs depend on its physical row identity for exact replay.
            self.store.record_metric(0, f"stock:{firm_id}", reference)

    # ── health economy: hospital + insurer firms (P1 R17) ───────────────────
    def _health_institutions(self) -> None:
        hcfg = self.config.get("health")
        if not hcfg:
            return
        from engine.ledger import Leg
        med_cost = int(self.config.get("lifecycle", {}).get("medical_cost_cents", 5000))

        def _found(founder_name: str, occupation: str, firm_name: str, sector: str,
                   product_name: str, unit_price: int, capital: int, staff: list[tuple[str, int]]):
            region_id = self.e.regions.primary_region_id() if self.e.regions.enabled else None
            bank_id = self.e.regions.bank_for_region(self.bank_ids, region_id) \
                if self.e.regions.enabled else self.prng.choice(self.bank_ids)
            population_tier, pinned_core = self._citizen_tier()
            founder = self.store.insert(
                "agents", name=founder_name, kind="citizen", occupation=occupation,
                age=self.prng.randint(35, 55), health="healthy", dependents=1,
                personality_json=json.dumps({"diligent": 0.8}), political_lean=0.0,
                media_diet_json=json.dumps([o["id"] for o in self.outlets]),
                risk_tolerance=0.4, cadence_json=json.dumps({"act": 2, "portfolio": 7, "career": 30}),
                model_tier="citizen", population_tier=population_tier,
                pinned_core=pinned_core, region_id=region_id,
                alive=1, retired=0, arrived_tick=0)
            self._open_accounts(founder, bank_id, 500_000, 0)
            self._seed_beliefs(founder, bank_id)
            # Service firms: no inventory production — revenue is fees/premiums.
            product = {"product": product_name, "unit_price_cents": unit_price,
                       "base_input_cost_cents": 0, "output_per_worker": 0}
            firm_id = self.e.firms.found_firm(0, founder, firm_name, sector,
                                              product=product, opening_capital_cents=0)
            firm = self.e.firms.get(firm_id)
            acct = int(firm["account_id"])
            ext = self.e.ledger.system_account(
                SYS_EXTERNAL, currency_code=str(firm["currency_code"] or "USD"))
            self.e.ledger.post(0, "firm_endowment", [
                Leg(acct, capital, "seed capital"), Leg(ext, -capital, "endowment")],
                memo=f"seed {firm_name}")
            pay_interval = int(self.config.get("firms", {}).get("pay_interval_ticks", 30))
            for title, wage in staff:
                pool = self.store.query_one(
                    "SELECT id FROM agents WHERE kind='citizen' AND retired=0 AND alive=1 "
                    "AND employer_id IS NULL AND age BETWEEN 20 AND 64 "
                    "AND id NOT IN (SELECT founder_agent_id FROM firms WHERE founder_agent_id "
                    "IS NOT NULL) ORDER BY id LIMIT 1")
                if not pool:
                    break
                aid = int(pool["id"])
                self.store.insert("employments", firm_id=firm_id, agent_id=aid, title=title,
                                  wage_cents=wage, start_tick=0, status="active",
                                  pay_interval_ticks=pay_interval, next_pay_tick=pay_interval)
                self.store.execute("UPDATE agents SET employer_id=? WHERE id=?", (firm_id, aid))
            return firm_id

        if hcfg.get("hospital", True):
            _found("Dr. Amara Osei", "doctor", "General Hospital", "health", "care",
                   med_cost, int(hcfg.get("hospital_capital_cents", 3_000_000)),
                   [("nurse", 320_000), ("orderly", 260_000)])
        if hcfg.get("insurer", True):
            _found("Ines Aldana", "insurance broker", "Aegis Mutual", "insurance", "coverage",
                   int(hcfg.get("premium_cents", 3000)),
                   int(hcfg.get("insurer_capital_cents", 5_000_000)),
                   [("claims adjuster", 280_000)])

    # ── accounts + beliefs helpers ───────────────────────────────────────────
    def _open_accounts(self, agent_id: int, bank_id: int, checking_cents: int, savings_cents: int,
                       funding_label: str = SYS_EXTERNAL) -> None:
        region_id = self.store.scalar("SELECT region_id FROM agents WHERE id=?", (agent_id,))
        currency = self.e.regions.currency_for_region(
            int(region_id) if region_id is not None else None) if self.e.regions.enabled else "USD"
        chk = self.e.ledger.create_account("agent", agent_id, "checking", bank_id=bank_id,
                                           label=f"agent:{agent_id}:checking",
                                           opening_cents=max(0, checking_cents), funding_label=funding_label,
                                           currency_code=currency)
        sav = None
        if savings_cents > 0:
            sav = self.e.ledger.create_account("agent", agent_id, "savings", bank_id=bank_id,
                                               label=f"agent:{agent_id}:savings",
                                               opening_cents=savings_cents, funding_label=funding_label,
                                               currency_code=currency)
        self.store.update("agents", agent_id, checking_account_id=chk, savings_account_id=sav)

    def _seed_beliefs(self, agent_id: int, bank_id: int) -> None:
        tick = 0
        for bid in self.bank_ids:
            self.memory.set_belief(
                agent_id, f"trust:bank:{bid}", 0.6, tick, source="genesis")
        self.memory.set_belief(agent_id, "sentiment", 0.0, tick, source="genesis")
        self.memory.set_belief(
            agent_id, "inflation_expectation", 0.02, tick, source="genesis")

    def _social_graph(self) -> None:
        agents = [int(r["id"]) for r in self.store.query("SELECT id FROM agents WHERE alive=1")]
        for a in agents:
            n_ties = self.prng.randint(2, 6)
            partners = self.prng.sample([x for x in agents if x != a], min(n_ties, len(agents) - 1))
            for b in partners:
                lo, hi = min(a, b), max(a, b)
                existing = self.store.query_one(
                    "SELECT id FROM social_ties WHERE agent_a=? AND agent_b=?", (lo, hi))
                if not existing:
                    self.store.insert("social_ties", agent_a=lo, agent_b=hi,
                                      weight=round(self.prng.uniform(0.2, 1.0), 3))

    def _initial_metrics(self) -> None:
        self._fund_bank_reserves()
        cb = self.config.get("central_bank", {})
        self.store.record_metric(0, "policy_rate", int(cb.get("neutral_rate_bps", 500)))
        self.store.record_metric(0, "commodity_index", 1.0)
        self.store.record_metric(0, "epidemic_multiplier", 1.0)
        if int(self.config.get("engine_semantics_version", 2)) >= 3:
            from world.metrics import Metrics
            self.store.record_metric(
                0, "cpi", Metrics(self.e, semantics_version=3)._cpi())
        self.e.gov.initialize(0)   # records opening tax rate + benefit level (R12)

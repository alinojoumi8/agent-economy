"""Deterministic Semantics-7 starting conditions for the specification closure gate.

The fixture is deliberately a state *preparation* layer.  It uses the domain
services and balanced ledger operations to create action-ready conditions, but
leaves the retirement draw, shipment, migration, default, arrival, and persona
enrichment to the normal five-tick world loop.  A single event is the durable
idempotence marker and contains every entity needed for an evidence audit.
"""
from __future__ import annotations

import json
from typing import Any, Iterable

from engine.credit import LoanTerms
from engine.ledger import SYS_EXTERNAL


class SpecClosureFixtureError(RuntimeError):
    """Raised when the requested closure fixture cannot be prepared safely."""


class SpecClosureFixtureSeeder:
    """Prepare the bounded Semantics-7 closure scenario exactly once."""

    EVENT_KIND = "spec_closure_fixture_seeded"

    def __init__(self, economy, config: dict[str, Any]):
        self.e = economy
        self.store = economy.store
        self.config = config
        self.cfg = dict(config.get("spec_closure_fixture", {}) or {})
        self.semantics = int(config.get("engine_semantics_version", 1))

    def seed(self) -> dict[str, Any] | None:
        """Seed the fixture atomically, or return its existing durable payload."""
        if not self.cfg.get("enabled"):
            return None
        if self.semantics < 7:
            raise SpecClosureFixtureError(
                "spec_closure_fixture requires engine_semantics_version >= 7"
            )

        fixture_key = str(self.cfg.get("key", "semantics-7-spec-closure-v1"))[:80]
        existing = self.store.query_one(
            "SELECT payload_json FROM events WHERE kind=? "
            "AND json_extract(payload_json,'$.fixture_key')=? ORDER BY id LIMIT 1",
            (self.EVENT_KIND, fixture_key),
        )
        if existing:
            return json.loads(str(existing["payload_json"] or "{}"))

        with self.store.savepoint("spec_closure_fixture_seed"):
            payload = self._seed(fixture_key)
            ok, diagnostic = self.e.ledger.reconcile()
            if not ok:
                raise SpecClosureFixtureError(
                    f"spec closure fixture does not reconcile: {diagnostic}"
                )
            self.store.log_event(
                0,
                self.EVENT_KIND,
                payload,
                phase="NIGHT_CLOSE",
                subject_type="world",
                subject_id=1,
                importance=4.0,
            )
        return payload

    def _seed(self, fixture_key: str) -> dict[str, Any]:
        origin = self.store.query_one(
            "SELECT * FROM regions WHERE region_key=?",
            (str(self.cfg.get("origin_region", "northstar")),),
        )
        if not origin:
            raise SpecClosureFixtureError("fixture origin region is unavailable")
        destination = self.store.query_one(
            "SELECT * FROM regions WHERE id<>? ORDER BY id LIMIT 1",
            (int(origin["id"]),),
        )
        if not destination:
            raise SpecClosureFixtureError("fixture requires two distinct regions")

        origin_id = int(origin["id"])
        destination_id = int(destination["id"])
        used: set[int] = set()

        exporter_founder = self._pick_citizen(
            origin_id, used, not_founder=True, unemployed=False)
        used.add(int(exporter_founder["id"]))
        importer_founder = self._pick_citizen(
            destination_id, used, not_founder=True, unemployed=False)
        used.add(int(importer_founder["id"]))
        retiree = self._pick_citizen(
            origin_id, used, not_founder=True, unemployed=True)
        used.add(int(retiree["id"]))
        debtor = self._pick_citizen(
            origin_id, used, not_founder=True, unemployed=True)
        used.add(int(debtor["id"]))
        migrant = self._pick_citizen(
            origin_id, used, not_founder=True, unemployed=True,
            no_credit_exposure=True)
        used.add(int(migrant["id"]))

        retiree_ids = self._prepare_retiree(int(retiree["id"]))
        loan_ids = self._prepare_default(int(debtor["id"]))
        trade_ids = self._prepare_trade(
            int(exporter_founder["id"]), int(importer_founder["id"]),
            origin_id, destination_id,
        )
        migration_ids = self._prepare_migration(
            int(migrant["id"]), destination_id, int(trade_ids["importer_firm_id"])
        )
        schedule_event_id = self.e.lifecycle.schedule_arrival(
            0, int(self.cfg.get("arrival_due_tick", 1)))

        return {
            "fixture_key": fixture_key,
            "engine_semantics_version": self.semantics,
            "origin_region_id": origin_id,
            "destination_region_id": destination_id,
            "arrival_schedule_event_id": int(schedule_event_id),
            **retiree_ids,
            **loan_ids,
            **trade_ids,
            **migration_ids,
        }

    def _prepare_retiree(self, agent_id: int) -> dict[str, int]:
        checking_id, savings_id = self._ensure_declared_accounts(agent_id)
        checking_target = max(
            0, int(self.cfg.get("retiree_checking_cents", 20_000)))
        liquidity_target = max(
            checking_target + 1,
            int(self.config.get("lifecycle", {}).get(
                "retirement_liquidity_target_cents", 100_000)),
        )
        savings_target = max(
            liquidity_target,
            int(self.cfg.get("retiree_savings_cents", liquidity_target * 2)),
        )

        self._set_exact_balance(
            checking_id, checking_target, overflow_account_id=savings_id,
            kind="spec_fixture_retiree_liquidity")
        self._ensure_minimum_balance(
            savings_id, savings_target, kind="spec_fixture_retiree_savings")
        self.store.execute(
            "UPDATE employments SET status='ended',end_tick=0 "
            "WHERE agent_id=? AND status='active'", (agent_id,))
        retirement_age = int(self.config.get("lifecycle", {}).get(
            "retirement_age", 65))
        self.store.update(
            "agents", agent_id,
            age=max(retirement_age, int(self.store.scalar(
                "SELECT age FROM agents WHERE id=?", (agent_id,), default=retirement_age))),
            retired=1, health="healthy", employer_id=None,
            cadence_json=json.dumps({
                "act": max(1, int(self.config.get("lifecycle", {}).get(
                    "retired_act_every", 1))),
                "portfolio": max(1, int(self.config.get("lifecycle", {}).get(
                    "retired_portfolio_every", 2))),
                "career": 30,
                "news": max(1, int(self.config.get("lifecycle", {}).get(
                    "retired_news_every", 1))),
            }, sort_keys=True),
            population_tier="core", pinned_core=1,
        )
        return {
            "retiree_agent_id": agent_id,
            "retiree_checking_account_id": checking_id,
            "retiree_savings_account_id": savings_id,
            "retirement_liquidity_target_cents": liquidity_target,
        }

    def _prepare_default(self, borrower_id: int) -> dict[str, int]:
        checking_id, savings_id = self._ensure_declared_accounts(borrower_id)
        account = self.store.query_one(
            "SELECT bank_id,currency_code FROM accounts WHERE id=?", (checking_id,))
        if not account or account["bank_id"] is None:
            raise SpecClosureFixtureError("fixture debtor lacks a commercial-bank checking account")
        bank_id = int(account["bank_id"])
        bank = self.e.bank.get(bank_id)
        if not bank or str(bank["status"]) != "open":
            raise SpecClosureFixtureError("fixture debtor's bank is unavailable")

        amount = max(10_000, int(self.cfg.get("loan_amount_cents", 120_000)))
        recovery = max(1, min(
            amount - 1, int(self.cfg.get("collateral_recovery_cents", 5_000))))
        reserve_id = int(bank["reserve_account_id"])
        # Neutralise the loan's reserve outflow so the closure scenario does not
        # accidentally become a bank-liquidity/failure scenario.
        self._ensure_minimum_balance(
            reserve_id, self.e.ledger.balance(reserve_id) + amount,
            kind="spec_fixture_loan_reserve_buffer")
        loan_id = self.e.bank.disburse_loan(
            0, bank_id, "agent", borrower_id,
            LoanTerms(
                amount_cents=amount,
                rate_bps=max(1, int(self.cfg.get("loan_rate_bps", 900))),
                term_ticks=max(3, int(self.cfg.get("loan_term_ticks", 12))),
                payment_interval_ticks=1,
            ),
            purpose="semantics-7 charge-off fixture",
            collateral={"cash": recovery},
        )
        if loan_id is None:
            raise SpecClosureFixtureError("fixture loan could not be disbursed")

        self._set_exact_balance(
            checking_id, recovery, overflow_account_id=savings_id,
            kind="spec_fixture_default_liquidity")
        self.store.update(
            "agents", borrower_id, retired=0, health="healthy",
            population_tier="periphery", pinned_core=0)
        self.store.update(
            "loans", int(loan_id), missed_payments=2, next_due_tick=1)
        return {
            "default_borrower_agent_id": borrower_id,
            "default_loan_id": int(loan_id),
            "default_bank_id": bank_id,
            "default_bank_equity_account_id": int(bank["equity_account_id"]),
            "collateral_recovery_cents": recovery,
            "expected_net_chargeoff_cents": amount - recovery,
        }

    def _prepare_trade(
        self,
        exporter_founder_id: int,
        importer_founder_id: int,
        origin_region_id: int,
        destination_region_id: int,
    ) -> dict[str, int]:
        unit_price = max(
            1, int(self.cfg.get("trade_unit_price_cents", 1_000)))
        exporter_id = self.e.firms.found_firm(
            0, exporter_founder_id,
            str(self.cfg.get("exporter_name", "Closure Export Cooperative")),
            "manufacturing",
            product={
                "product": "closure_fixture_component",
                "unit_price_cents": unit_price,
                # Preserve the deliberately high bounded invoice even when the
                # scripted founder reprices from cost before creating shipment.
                "base_input_cost_cents": max(1, unit_price * 4 // 5),
                "output_per_worker": 0,
            },
        )
        importer_id = self.e.firms.found_firm(
            0, importer_founder_id,
            str(self.cfg.get("importer_name", "Closure Import Cooperative")),
            "logistics",
            product={
                "product": "closure_fixture_distribution",
                "unit_price_cents": 1_200,
                "base_input_cost_cents": 0,
                "output_per_worker": 0,
            },
        )
        exporter = self.e.firms.get(exporter_id)
        importer = self.e.firms.get(importer_id)
        if (int(exporter["region_id"] or 0) != origin_region_id
                or int(importer["region_id"] or 0) != destination_region_id):
            raise SpecClosureFixtureError("fixture firms were not created in distinct regions")

        inventory = max(1, int(self.cfg.get("exporter_inventory", 8)))
        self.store.update("firms", exporter_id, inventory=inventory)
        importer_funds = max(
            100_000, int(self.cfg.get("importer_funds_cents", 500_000)))
        self._ensure_minimum_balance(
            int(importer["account_id"]), importer_funds,
            kind="spec_fixture_importer_working_capital")
        self.store.update(
            "agents", exporter_founder_id,
            cadence_json=json.dumps({"act": 1, "portfolio": 7, "career": 30},
                                    sort_keys=True),
            population_tier="core", pinned_core=1)

        lawyer = self.store.query_one(
            "SELECT id FROM agents WHERE role='lawyer' AND alive=1 ORDER BY id LIMIT 1")
        if not lawyer:
            raise SpecClosureFixtureError("fixture requires an available lawyer")
        proposed = self.e.legal.propose_contract(0, int(lawyer["id"]), {
            "title": "Closure cross-border supply framework",
            "contract_type": "cross-border-supply",
            "parties": [
                {"type": "firm", "id": exporter_id, "role": "exporter"},
                {"type": "firm", "id": importer_id, "role": "importer"},
            ],
            # A non-obligation clause keeps the framework active while the
            # shipment service remains the sole owner of invoice settlement.
            "clauses": [{
                "clause_key": "shipment-confidentiality",
                "clause_type": "confidentiality",
                "terms": {"scope": "fixture shipment details"},
            }],
            "prose": "Fictional simulation fixture; typed state controls execution.",
            "metadata": {"fixture": "semantics-7-spec-closure"},
        })
        if not proposed.get("ok"):
            raise SpecClosureFixtureError(
                f"fixture trade contract proposal failed: {proposed.get('reason')}")
        contract_id = int(proposed["contract_id"])
        for actor_id, party_id in (
            (exporter_founder_id, exporter_id),
            (importer_founder_id, importer_id),
        ):
            accepted = self.e.legal.accept_contract(
                0, actor_id, contract_id, "firm", party_id)
            if not accepted.get("ok"):
                raise SpecClosureFixtureError(
                    f"fixture trade contract acceptance failed: {accepted.get('reason')}")

        context = self.e.regions.decision_context(
            exporter_founder_id, tick=1, exporter_firm_id=exporter_id,
            career_day=False)
        opportunities = context.get("trade_opportunities", [])
        if not opportunities:
            raise SpecClosureFixtureError(
                "fixture failed to produce an executable trade opportunity")
        opportunity = opportunities[0]
        return {
            "exporter_founder_agent_id": exporter_founder_id,
            "importer_founder_agent_id": importer_founder_id,
            "exporter_firm_id": exporter_id,
            "importer_firm_id": importer_id,
            "trade_contract_id": contract_id,
            "qualified_trade_quantity": int(opportunity["quantity"]),
            "qualified_trade_invoice_cents": int(opportunity["invoice_cents"]),
        }

    def _prepare_migration(
        self, agent_id: int, destination_region_id: int, destination_firm_id: int,
    ) -> dict[str, int]:
        self.store.execute(
            "UPDATE employments SET status='ended',end_tick=0 "
            "WHERE agent_id=? AND status='active'", (agent_id,))
        self.store.update(
            "agents", agent_id,
            age=min(55, int(self.store.scalar(
                "SELECT age FROM agents WHERE id=?", (agent_id,), default=35))),
            health="healthy", retired=0, employer_id=None,
            cadence_json=json.dumps({"act": 1, "portfolio": 7, "career": 1},
                                    sort_keys=True),
            population_tier="core", pinned_core=1,
        )
        wage = max(1_000_000, int(self.cfg.get(
            "migration_destination_wage_cents", 10_000_000)))
        job_id = self.e.labor.post_job(
            0, destination_firm_id, "cross-border operations lead", wage)
        context = self.e.regions.decision_context(
            agent_id, tick=1, career_day=True)
        options = [
            option for option in context.get("migration_options", [])
            if int(option["destination_region_id"]) == destination_region_id
        ]
        if not options:
            raise SpecClosureFixtureError(
                "fixture failed to produce an eligible migration opportunity")
        return {
            "migration_candidate_agent_id": agent_id,
            "migration_destination_job_id": int(job_id),
            "migration_destination_region_id": destination_region_id,
            "qualified_migration_wage_gain_bps": int(options[0]["wage_gain_bps"]),
        }

    def _pick_citizen(
        self,
        region_id: int,
        excluded: Iterable[int],
        *,
        not_founder: bool,
        unemployed: bool,
        no_credit_exposure: bool = False,
    ):
        params: list[Any] = [region_id]
        clauses = [
            "a.kind='citizen'", "a.alive=1", "a.region_id=?",
            "a.checking_account_id IS NOT NULL",
        ]
        excluded_ids = sorted({int(value) for value in excluded})
        if excluded_ids:
            clauses.append(
                "a.id NOT IN (" + ",".join("?" for _ in excluded_ids) + ")")
            params.extend(excluded_ids)
        if not_founder:
            clauses.append(
                "NOT EXISTS (SELECT 1 FROM firms f WHERE f.founder_agent_id=a.id "
                "AND f.status<>'bankrupt')")
        if unemployed:
            clauses.append(
                "NOT EXISTS (SELECT 1 FROM employments e WHERE e.agent_id=a.id "
                "AND e.status='active')")
        if no_credit_exposure:
            clauses.extend([
                "NOT EXISTS (SELECT 1 FROM loans l WHERE l.borrower_type='agent' "
                "AND l.borrower_id=a.id AND l.status='active')",
                "NOT EXISTS (SELECT 1 FROM loan_applications la "
                "WHERE la.borrower_type='agent' AND la.borrower_id=a.id "
                "AND la.status='pending')",
            ])
        row = self.store.query_one(
            "SELECT a.* FROM agents a WHERE " + " AND ".join(clauses)
            + " ORDER BY a.id LIMIT 1",
            tuple(params),
        )
        if not row:
            raise SpecClosureFixtureError(
                f"fixture lacks a suitable citizen in region {region_id}")
        return row

    def _ensure_declared_accounts(self, agent_id: int) -> tuple[int, int]:
        agent = self.store.query_one("SELECT * FROM agents WHERE id=?", (agent_id,))
        if not agent:
            raise SpecClosureFixtureError(f"fixture agent {agent_id} is missing")
        checking_id = int(agent["checking_account_id"] or 0)
        checking = self.store.query_one(
            "SELECT * FROM accounts WHERE id=? AND owner_type='agent' "
            "AND owner_id=? AND kind='checking'", (checking_id, agent_id))
        if not checking:
            raise SpecClosureFixtureError(
                f"fixture agent {agent_id} lacks its declared checking account")

        savings_id = int(agent["savings_account_id"] or 0)
        savings = self.store.query_one(
            "SELECT * FROM accounts WHERE id=? AND owner_type='agent' "
            "AND owner_id=? AND kind='savings'", (savings_id, agent_id))
        if not savings:
            savings_id = self.e.ledger.create_account(
                "agent", agent_id, "savings", bank_id=checking["bank_id"],
                label=f"agent:{agent_id}:savings:spec-closure",
                currency_code=str(checking["currency_code"] or "USD"))
            self.store.update("agents", agent_id, savings_account_id=savings_id)
        else:
            if (str(savings["currency_code"] or "USD")
                    != str(checking["currency_code"] or "USD")):
                raise SpecClosureFixtureError(
                    f"fixture agent {agent_id} accounts use different currencies")
        return checking_id, savings_id

    def _set_exact_balance(
        self,
        account_id: int,
        target_cents: int,
        *,
        overflow_account_id: int,
        kind: str,
    ) -> None:
        balance = self.e.ledger.balance(account_id)
        if balance > target_cents:
            self.e.ledger.transfer(
                0, account_id, overflow_account_id, balance - target_cents,
                kind=kind, memo="fixture balance preparation")
        elif balance < target_cents:
            self._fund_from_external(
                account_id, target_cents - balance, kind=kind)

    def _ensure_minimum_balance(
        self, account_id: int, minimum_cents: int, *, kind: str,
    ) -> None:
        missing = max(0, minimum_cents - self.e.ledger.balance(account_id))
        if missing:
            self._fund_from_external(account_id, missing, kind=kind)

    def _fund_from_external(self, account_id: int, amount_cents: int, *, kind: str) -> None:
        currency = str(self.store.scalar(
            "SELECT currency_code FROM accounts WHERE id=?", (account_id,),
            default="USD") or "USD")
        external = self.e.ledger.system_account(
            SYS_EXTERNAL, currency_code=currency)
        self.e.ledger.transfer(
            0, external, account_id, amount_cents,
            kind=kind, memo="spec closure fixture funding")


__all__ = ["SpecClosureFixtureError", "SpecClosureFixtureSeeder"]

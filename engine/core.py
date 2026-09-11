"""Economy facade — wires the deterministic engine modules over one Store.

This is the object the world loop and the executor talk to. It owns the engine
PRNG and a separate lifecycle PRNG for historical runs. Semantics 15 isolates
demographic draws; Semantics 16 isolates daily mechanisms and policy calls by
seed, day and semantic identity. Every version retains its replay contract.
"""
from __future__ import annotations

import random
from typing import Optional

from .credit import Bank
from .business_control import BusinessControl
from .city import City
from .civic_authority import CivicAuthority
from .cognition import CognitionEconomy
from .construction import ConstructionEconomy
from .daily_time import DailyTime
from .earned_wages import EarnedWages
from .estate_cases import EstateCases
from .estate_securities import EstateSecurities
from .estate_property import EstateProperty
from .estate_property_sales import EstatePropertySales
from .estate_unlisted_sales import EstateUnlistedSales
from .estate_administration import EstateAdministration
from .legal_awards import LegalAwards
from .legal_authority import LegalDecisionAuthority
from .legal_representation import LegalRepresentation
from .estate_legal_work import EstateLegalWork
from .wage_awards import WageAwards
from .estate_disputes import EstateDisputes
from .estates import CashEstates
from .exchange import Exchange
from .firms import Firms
from .families import HouseholdDecisions
from .government import Government
from .households import Households
from .information import InformationEconomy
from .labor import Labor
from .legal import LegalInstitution
from .ledger import (Ledger, SYS_COMMODITY, SYS_COMPUTE, SYS_CONSTRUCTION, SYS_EDUCATION,
                     SYS_EXTERNAL, SYS_GOV, SYS_INFLOW, SYS_HOUSING, SYS_LOSS,
                     SYS_MEDICAL)
from .lifecycle import Lifecycle
from .store import Store
from .startups import StartupLifecycle
from .politics import PoliticalEconomy
from .population import PopulationBoundary
from .project_rights import ProjectRights
from .regions import RegionalEconomy
from .semantics import semantics_version
from .vc import VentureCapital


class Economy:
    def __init__(self, store: Store, config: dict, engine_prng: random.Random,
                 lifecycle_prng: random.Random):
        self.store = store
        self.config = config
        self.prng = engine_prng
        self.engine_semantics_version = semantics_version(config, default=2)
        self.business_control = BusinessControl(self)
        local_currency_action_surfaces = bool(
            config.get("llm", {}).get("local_currency_action_surfaces", False))
        self.ledger = Ledger(store)
        cb = config.get("exchange", {}).get("circuit_breaker_drop")
        self.exchange = Exchange(store, self.ledger,
                                 circuit_breaker_drop=float(cb) if cb else None)
        self.bank = Bank(
            store, self.ledger,
            local_currency_action_surfaces=local_currency_action_surfaces,
            engine_semantics_version=self.engine_semantics_version)
        city_enabled = (
            self.engine_semantics_version >= 12
            and bool(config.get("city", {}).get("enabled", False))
        )
        self.firms = Firms(
            store,
            self.ledger,
            engine_semantics_version=self.engine_semantics_version,
            city_enabled=city_enabled,
        )
        self.labor = Labor(
            store,
            engine_semantics_version=self.engine_semantics_version,
        )
        self.households = Households(self, config.get("households"))
        self.families = HouseholdDecisions(self, config.get("family_decisions"))
        self.lifecycle = Lifecycle(store, self.ledger, self.bank, self.firms,
                                   lifecycle_prng, config.get("lifecycle", {}),
                                   health_cfg=config.get("health", {}),
                                   engine_semantics_version=self.engine_semantics_version,
                                   households=self.households, seed=int(config.get("seed", 42)))
        self.gov = Government(store, self.ledger, config.get("government"),
                              engine_semantics_version=self.engine_semantics_version)
        self.vc = VentureCapital(store, self.ledger)
        self.legal = LegalInstitution(store, self.ledger, config.get("legal"))
        self.regions = RegionalEconomy(store, self.ledger, self.legal, engine_prng,
                                       config.get("living_world"),
                                       local_currency_action_surfaces=local_currency_action_surfaces,
                                       engine_semantics_version=self.engine_semantics_version)
        self.startups = StartupLifecycle(store, self.ledger, self.legal, config.get("startup"))
        self.information = InformationEconomy(store, config.get("information_economy"),
                                              engine_semantics_version=self.engine_semantics_version)
        self.politics = PoliticalEconomy(store, self.ledger, self.legal, config.get("political_model"),
                                        engine_semantics_version=self.engine_semantics_version)
        self.cognition = CognitionEconomy(
            store, self.ledger, config.get("cognition"),
            engine_semantics_version=self.engine_semantics_version,
            seed=int(config.get("seed", 42)),
        )
        self.city = City(self, config.get("city"))
        self.construction = ConstructionEconomy(self, config.get("construction"))
        self.daily_time = DailyTime(self, config.get("daily_time"))
        self.earned_wages = EarnedWages(self, self.daily_time.p["normal_workday_minutes"])
        self.firms.daily_time = self.daily_time
        self.firms.earned_wages = self.earned_wages
        self.lifecycle.earned_wages = self.earned_wages
        self.cash_estates = CashEstates(self)
        self.lifecycle.cash_estates = self.cash_estates
        self.project_rights = ProjectRights(self)
        self.lifecycle.project_rights = self.project_rights
        self.estate_cases = EstateCases(self)
        self.lifecycle.estate_cases = self.estate_cases
        self.civic_authority = CivicAuthority(self)
        self.legal_awards = LegalAwards(self)
        self.wage_awards = WageAwards(self)
        self.legal.awards = self.legal_awards
        self.estate_disputes = EstateDisputes(self)
        self.estate_securities = EstateSecurities(self)
        self.estate_property = EstateProperty(self)
        self.estate_property_sales = EstatePropertySales(self)
        self.estate_unlisted_sales = EstateUnlistedSales(self)
        self.estate_administration = EstateAdministration(self)
        self.legal_representation = LegalRepresentation(self)
        self.estate_legal_work = EstateLegalWork(self)
        self.legal.representation = self.legal_representation
        self.legal_authority = LegalDecisionAuthority(self)
        self.legal.authority = self.legal_authority
        self.exchange.estate_securities = self.estate_securities
        if self.estate_cases.enabled:
            self.ledger.cash_receipt_hook = self.estate_cases.cash_received
        for institution in (self.firms, self.labor, self.legal, self.cognition, self.gov, self.regions):
            institution.business_control = self.business_control
        self.lifecycle.business_control = self.business_control
        self.cognition.daily_time = self.daily_time
        self.population = PopulationBoundary(self)
        self.labor.population = self.population
        self.gov.population = self.population
        for institution in (self.bank, self.politics, self.cognition, self.information, self.regions):
            institution.population = self.population

    # ── system accounts (created once at genesis) ────────────────────────────
    def ensure_system_accounts(self) -> None:
        labels = (
            SYS_EXTERNAL, SYS_COMMODITY, SYS_INFLOW, SYS_LOSS,
            SYS_MEDICAL, SYS_GOV, SYS_HOUSING,
        )
        if self.engine_semantics_version >= 11:
            labels += (SYS_COMPUTE, SYS_EDUCATION)
        if self.engine_semantics_version >= 13:
            labels += (SYS_CONSTRUCTION,)
        for label in labels:
            self.ledger.ensure_system_account(label)

    # ── convenient references ────────────────────────────────────────────────
    def central_bank_reserve_acct(self, currency_code: Optional[str] = None) -> Optional[int]:
        """Return the central-bank reserve account for one settlement currency.

        Omitting ``currency_code`` preserves the legacy primary-account lookup.
        Semantics-6 callers always supply the distressed bank's currency.
        """
        params: tuple = ()
        currency_clause = ""
        if currency_code is not None:
            currency_clause = " AND currency_code=?"
            params = (str(currency_code or "USD").upper(),)
        v = self.store.scalar(
            "SELECT id FROM accounts WHERE owner_type='central_bank' "
            f"AND kind='reserve'{currency_clause} ORDER BY id LIMIT 1", params)
        return int(v) if v is not None else None

    def policy_rate_bps(self) -> int:
        return int(self.store.metric_latest("policy_rate", 500.0))

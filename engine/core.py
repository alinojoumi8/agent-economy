"""Economy facade — wires the deterministic engine modules over one Store.

This is the object the world loop and the executor talk to. It owns the engine
PRNG (all engine randomness) and a *separate* lifecycle PRNG (so the lifecycle
schedule is stable under replay, PRD R11).
"""
from __future__ import annotations

import random
from typing import Optional

from .credit import Bank
from .exchange import Exchange
from .firms import Firms
from .government import Government
from .information import InformationEconomy
from .labor import Labor
from .legal import LegalInstitution
from .ledger import (Ledger, SYS_COMMODITY, SYS_EXTERNAL, SYS_GOV, SYS_INFLOW,
                     SYS_HOUSING, SYS_LOSS, SYS_MEDICAL)
from .lifecycle import Lifecycle
from .store import Store
from .startups import StartupLifecycle
from .politics import PoliticalEconomy
from .regions import RegionalEconomy
from .vc import VentureCapital


class Economy:
    def __init__(self, store: Store, config: dict, engine_prng: random.Random,
                 lifecycle_prng: random.Random):
        self.store = store
        self.config = config
        self.prng = engine_prng
        local_currency_action_surfaces = bool(
            config.get("llm", {}).get("local_currency_action_surfaces", False))
        self.ledger = Ledger(store)
        cb = config.get("exchange", {}).get("circuit_breaker_drop")
        self.exchange = Exchange(store, self.ledger,
                                 circuit_breaker_drop=float(cb) if cb else None)
        self.bank = Bank(
            store, self.ledger,
            local_currency_action_surfaces=local_currency_action_surfaces)
        self.firms = Firms(store, self.ledger)
        self.labor = Labor(store)
        self.lifecycle = Lifecycle(store, self.ledger, self.bank, self.firms,
                                   lifecycle_prng, config.get("lifecycle", {}),
                                   health_cfg=config.get("health", {}))
        self.gov = Government(store, self.ledger, config.get("government"))
        self.vc = VentureCapital(store, self.ledger)
        self.legal = LegalInstitution(store, self.ledger, config.get("legal"))
        self.regions = RegionalEconomy(store, self.ledger, self.legal, engine_prng,
                                      config.get("living_world"),
                                      local_currency_action_surfaces=local_currency_action_surfaces)
        self.startups = StartupLifecycle(store, self.ledger, self.legal, config.get("startup"))
        self.information = InformationEconomy(store, config.get("information_economy"))
        self.politics = PoliticalEconomy(store, self.ledger, self.legal, config.get("political_model"))

    # ── system accounts (created once at genesis) ────────────────────────────
    def ensure_system_accounts(self) -> None:
        for label in (SYS_EXTERNAL, SYS_COMMODITY, SYS_INFLOW, SYS_LOSS,
                      SYS_MEDICAL, SYS_GOV, SYS_HOUSING):
            self.ledger.ensure_system_account(label)

    # ── convenient references ────────────────────────────────────────────────
    def central_bank_reserve_acct(self) -> Optional[int]:
        v = self.store.scalar(
            "SELECT id FROM accounts WHERE owner_type='central_bank' AND kind='reserve' LIMIT 1")
        return int(v) if v is not None else None

    def policy_rate_bps(self) -> int:
        return int(self.store.metric_latest("policy_rate", 500.0))

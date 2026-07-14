"""Regional population tiers, multicurrency accounting, FX, trade, and migration."""
from __future__ import annotations

import json
import random
from typing import Any

from .ledger import (Leg, Ledger, SYS_COMMODITY, SYS_EXTERNAL, SYS_GOV,
                     SYS_HOUSING, SYS_INFLOW, SYS_LOSS, SYS_MEDICAL)
from .legal import LegalInstitution
from .store import Store


DEFAULT_REGIONS = [
    {"key": "northstar", "name": "Northstar Federation", "currency": "NSD",
     "population": 600, "specialization": ["technology", "services", "finance"],
     "x": 0.25, "y": 0.35, "legal_ruleset": "northstar-us-inspired-1.0",
     "rate_ppm": 1_000_000},
    {"key": "ironvale", "name": "Ironvale Union", "currency": "IVC",
     "population": 220, "specialization": ["manufacturing", "energy"],
     "x": 0.72, "y": 0.28, "legal_ruleset": "external-lite-1.0",
     "rate_ppm": 750_000},
    {"key": "suncoast", "name": "Suncoast Republic", "currency": "SCD",
     "population": 180, "specialization": ["agriculture", "logistics", "tourism"],
     "x": 0.55, "y": 0.78, "legal_ruleset": "external-lite-1.0",
     "rate_ppm": 1_200_000},
]


class RegionalEconomy:
    def __init__(self, store: Store, ledger: Ledger, legal: LegalInstitution,
                 prng: random.Random, config: dict | None = None, *,
                 local_currency_action_surfaces: bool = False,
                 engine_semantics_version: int | None = None):
        self.store = store
        self.ledger = ledger
        self.legal = legal
        self.prng = prng
        self.config = config or {}
        self.local_currency_action_surfaces = bool(local_currency_action_surfaces)
        self.enabled = config is not None and bool(self.config.get("enabled", True))
        self.specs = list(self.config.get("regions", DEFAULT_REGIONS))
        self.core_target = int(self.config.get("core_agents", 100))
        self.promotion_interval = int(self.config.get("promotion_interval_ticks", 30))
        self.require_trade_contract = bool(self.config.get("require_trade_contract", True))
        self.fx_inventory = int(self.config.get("fx_market_maker_inventory", 100_000_000))
        self.migration_wage_gain_bps = max(
            0, int(self.config.get("migration_wage_gain_bps", 1_000)))
        self.max_trade_opportunities = max(
            1, min(5, int(self.config.get("max_trade_opportunities", 5))))
        self.max_trade_quantity = max(
            1, int(self.config.get("max_trade_quantity", 5)))
        self.trade_transit_ticks = max(
            1, int(self.config.get("trade_transit_ticks", 3)))
        try:
            stored_config = json.loads(str(self.store.get_meta()["config_json"]))
        except (TypeError, ValueError, KeyError):
            stored_config = {}
        self.engine_semantics_version = int(
            stored_config.get("engine_semantics_version", 2)
            if engine_semantics_version is None else engine_semantics_version)

    def initialize(self, tick: int = 0) -> None:
        if not self.enabled or self.store.query_one("SELECT 1 FROM regions LIMIT 1"):
            return
        system_labels = (SYS_EXTERNAL, SYS_COMMODITY, SYS_INFLOW, SYS_LOSS,
                         SYS_MEDICAL, SYS_GOV, SYS_HOUSING)
        for spec in self.specs:
            region_id = self.store.insert(
                "regions", region_key=spec["key"], name=spec["name"],
                currency_code=spec["currency"], population_target=int(spec["population"]),
                specialization_json=json.dumps(spec.get("specialization", [])),
                x=float(spec.get("x", 0.5)), y=float(spec.get("y", 0.5)),
                legal_ruleset=str(spec.get("legal_ruleset", "external-lite-1.0")))
            code = str(spec["currency"]).upper()
            self.store.insert(
                "currencies", code=code, name=f"{spec['name']} currency", minor_unit=2,
                numeraire_rate_ppm=int(spec.get("rate_ppm", 1_000_000)), issuer_region_id=region_id)
            for label in system_labels:
                self.ledger.ensure_system_account(label, currency_code=code)
            reserve = self.ledger.create_account(
                "fx_market", region_id, "reserve", label=f"fx:{code}",
                opening_cents=self.fx_inventory, currency_code=code)
            self.store.insert("fx_reserves", currency_code=code, account_id=reserve,
                              target_inventory=self.fx_inventory)
        self.store.log_event(tick, "regions_initialized", {
            "regions": [{"key": spec["key"], "currency": spec["currency"],
                         "population_target": int(spec["population"])} for spec in self.specs]},
            phase="NIGHT_CLOSE", subject_type="world", subject_id=1, importance=3.0)

    def primary_region_id(self) -> int | None:
        value = self.store.scalar("SELECT id FROM regions WHERE region_key='northstar' LIMIT 1")
        return int(value) if value is not None else None

    def region_for_bank_index(self, index: int) -> int | None:
        rows = self.store.query("SELECT id FROM regions ORDER BY id")
        return int(rows[index % len(rows)]["id"]) if rows else None

    def currency_for_region(self, region_id: int | None) -> str:
        if region_id is None:
            return "USD"
        return str(self.store.scalar("SELECT currency_code FROM regions WHERE id=?", (region_id,), default="USD"))

    def bank_for_region(self, bank_ids: list[int], region_id: int | None) -> int:
        value = self.store.scalar(
            "SELECT id FROM banks WHERE region_id=? AND status='open' ORDER BY id LIMIT 1", (region_id,))
        return int(value) if value is not None else self.prng.choice(bank_ids)

    def region_for_new_citizen(self, *, reserved_northstar: int = 0) -> int | None:
        regions = self.store.query("SELECT id, region_key, population_target FROM regions ORDER BY id")
        if not regions:
            return None
        choices = []
        for region in regions:
            count = int(self.store.scalar("SELECT COUNT(*) FROM agents WHERE region_id=?", (region["id"],), default=0))
            reserve = reserved_northstar if region["region_key"] == "northstar" else 0
            remaining = int(region["population_target"]) - count - reserve
            choices.append((remaining, -int(region["id"]), int(region["id"])))
        return max(choices)[2]

    # ------------------------------------------------------------------ FX
    def place_fx_order(self, tick: int, actor_id: int, data: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "reason": "regional economy disabled"}
        pair = str(data.get("pair", "")).upper()
        parts = pair.split("/")
        if len(parts) != 2 or parts[0] == parts[1]:
            return {"ok": False, "reason": "pair must be BASE/QUOTE"}
        base, quote = parts
        known = {str(row["code"]) for row in self.store.query("SELECT code FROM currencies")}
        side = str(data.get("side", "")).lower()
        qty = int(data.get("qty", 0))
        limit_rate = data.get("limit_rate_ppm")
        if base not in known or quote not in known or side not in {"buy", "sell"} or qty <= 0:
            return {"ok": False, "reason": "invalid FX order"}
        if limit_rate is not None and int(limit_rate) <= 0:
            return {"ok": False, "reason": "limit rate must be positive"}
        seq = int(self.store.scalar("SELECT COALESCE(MAX(seq),0)+1 FROM fx_orders WHERE tick=?", (tick,), default=1))
        order_id = self.store.insert(
            "fx_orders", tick=tick, actor_id=actor_id, pair=pair, base_currency=base,
            quote_currency=quote, side=side, qty=qty, qty_remaining=qty,
            limit_rate_ppm=int(limit_rate) if limit_rate is not None else None,
            seq=seq, status="open")
        self.store.log_event(tick, "fx_order_placed", {"order_id": order_id, "actor_id": actor_id,
            "pair": pair, "side": side, "qty": qty, "limit_rate_ppm": limit_rate},
            phase="EXECUTION", subject_type="agent", subject_id=actor_id, importance=1.2)
        return {"ok": True, "order_id": order_id}

    def cancel_fx_orders(self, tick: int, actor_id: int, pair: str | None = None) -> dict[str, Any]:
        if pair:
            cursor = self.store.execute(
                "UPDATE fx_orders SET status='cancelled' WHERE actor_id=? AND pair=? AND status='open'",
                (actor_id, pair.upper()))
        else:
            cursor = self.store.execute(
                "UPDATE fx_orders SET status='cancelled' WHERE actor_id=? AND status='open'", (actor_id,))
        return {"ok": True, "cancelled": max(0, int(cursor.rowcount))}

    def match_fx(self, tick: int) -> list[dict[str, Any]]:
        trades = []
        for order in self.store.query(
                "SELECT * FROM fx_orders WHERE status='open' ORDER BY tick,seq,id"):
            rate = self.current_rate(str(order["base_currency"]), str(order["quote_currency"]))
            limit_rate = order["limit_rate_ppm"]
            if limit_rate is not None:
                if order["side"] == "buy" and rate > int(limit_rate):
                    continue
                if order["side"] == "sell" and rate < int(limit_rate):
                    continue
            qty = int(order["qty_remaining"])
            quote_qty = max(1, round(qty * rate / 1_000_000))
            base_agent = self._wallet("agent", int(order["actor_id"]), str(order["base_currency"]), create=True)
            quote_agent = self._wallet("agent", int(order["actor_id"]), str(order["quote_currency"]), create=True)
            base_mm = int(self.store.scalar(
                "SELECT account_id FROM fx_reserves WHERE currency_code=?", (order["base_currency"],)))
            quote_mm = int(self.store.scalar(
                "SELECT account_id FROM fx_reserves WHERE currency_code=?", (order["quote_currency"],)))
            if order["side"] == "buy":
                if self.ledger.balance(quote_agent) < quote_qty or self.ledger.balance(base_mm) < qty:
                    continue
                legs = [Leg(quote_agent, -quote_qty, "FX quote sold"), Leg(quote_mm, quote_qty, "FX quote reserve"),
                        Leg(base_mm, -qty, "FX base reserve"), Leg(base_agent, qty, "FX base bought")]
            else:
                if self.ledger.balance(base_agent) < qty or self.ledger.balance(quote_mm) < quote_qty:
                    continue
                legs = [Leg(base_agent, -qty, "FX base sold"), Leg(base_mm, qty, "FX base reserve"),
                        Leg(quote_mm, -quote_qty, "FX quote reserve"), Leg(quote_agent, quote_qty, "FX quote bought")]
            self.ledger.post(tick, "fx_trade", legs, memo=f"FX order {order['id']}")
            trade_id = self.store.insert(
                "fx_trades", tick=tick, order_id=int(order["id"]), actor_id=int(order["actor_id"]),
                pair=order["pair"], side=order["side"], base_qty=qty, quote_qty=quote_qty,
                rate_ppm=rate, base_account_id=base_agent, quote_account_id=quote_agent)
            self.store.update("fx_orders", int(order["id"]), qty_remaining=0, status="filled")
            impact = max(1, min(10_000, round(qty * 1000 / max(1, self.fx_inventory))))
            new_rate = max(1, rate + impact if order["side"] == "buy" else rate - impact)
            self.store.record_metric(tick, f"fx:{order['pair']}", new_rate)
            event_id = self.store.log_event(tick, "fx_trade", {"fx_trade_id": trade_id,
                "order_id": int(order["id"]), "pair": order["pair"], "side": order["side"],
                "base_qty": qty, "quote_qty": quote_qty, "rate_ppm": rate,
                "new_rate_ppm": new_rate}, phase="MARKET", subject_type="agent",
                subject_id=int(order["actor_id"]), importance=1.5)
            trades.append({"trade_id": trade_id, "event_id": event_id, "rate_ppm": rate})
        return trades

    def current_rate(self, base: str, quote: str) -> int:
        pair = f"{base}/{quote}"
        metric = self.store.metric_latest(f"fx:{pair}", None)
        if metric is not None:
            return int(metric)
        base_rate = int(self.store.scalar("SELECT numeraire_rate_ppm FROM currencies WHERE code=?",
                                          (base,), default=1_000_000))
        quote_rate = int(self.store.scalar("SELECT numeraire_rate_ppm FROM currencies WHERE code=?",
                                           (quote,), default=1_000_000))
        return max(1, round(base_rate * 1_000_000 / max(1, quote_rate)))

    def _wallet(self, owner_type: str, owner_id: int, currency: str, *, create: bool) -> int:
        row = self.store.query_one(
            "SELECT id FROM accounts WHERE owner_type=? AND owner_id=? AND currency_code=? "
            "AND kind IN ('checking','savings','fx') ORDER BY CASE kind WHEN 'checking' THEN 0 ELSE 1 END,id LIMIT 1",
            (owner_type, owner_id, currency))
        if row:
            return int(row["id"])
        if not create:
            raise ValueError(f"{owner_type}:{owner_id} lacks a {currency} wallet")
        return self.ledger.create_account(owner_type, owner_id, "fx",
                                          label=f"{owner_type}:{owner_id}:{currency}",
                                          currency_code=currency)

    # ------------------------------------------------------------------ bounded agent context
    def decision_context(
        self,
        actor_id: int,
        *,
        tick: int,
        exporter_firm_id: int | None = None,
        career_day: bool = False,
    ) -> dict[str, Any]:
        """Return deterministic, action-ready regional facts for Semantics 7.

        The context is deliberately more restrictive than the public action
        endpoints: an action is advertised only when the current snapshot makes
        it executable.  This keeps scripted and model-driven agents on the same
        bounded opportunity set without changing historical prompt surfaces.
        """
        if not self.enabled or self.engine_semantics_version < 7:
            return {}
        agent = self.store.query_one(
            "SELECT a.id,a.kind,a.alive,a.retired,a.health,a.region_id,"
            "r.name AS region_name,r.currency_code,ac.id AS primary_account_id "
            "FROM agents a JOIN regions r ON r.id=a.region_id "
            "LEFT JOIN accounts ac ON ac.id=a.checking_account_id WHERE a.id=?",
            (actor_id,))
        if not agent or not agent["alive"] or agent["region_id"] is None:
            return {}

        primary_currency = str(agent["currency_code"] or "USD")
        wallets = [{
            "account_id": int(row["id"]),
            "kind": str(row["kind"]),
            "currency_code": str(row["currency_code"] or "USD"),
            "balance_cents": int(row["balance_cents"]),
            "primary": int(row["id"]) == int(agent["primary_account_id"] or 0),
        } for row in self.store.query(
            "SELECT id,kind,currency_code,balance_cents FROM accounts "
            "WHERE owner_type='agent' AND owner_id=? "
            "ORDER BY CASE kind WHEN 'checking' THEN 0 WHEN 'savings' THEN 1 ELSE 2 END,id "
            "LIMIT 8", (actor_id,))]
        settlement_wallets: dict[str, dict[str, Any]] = {}
        for wallet in wallets:
            settlement_wallets.setdefault(str(wallet["currency_code"]), wallet)

        quote_wallet = settlement_wallets.get(primary_currency)
        quote_balance = int(quote_wallet["balance_cents"]) if quote_wallet else 0
        fx_quotes = []
        for currency in self.store.query(
                "SELECT code,name FROM currencies WHERE code<>? ORDER BY code LIMIT 5",
                (primary_currency,)):
            base = str(currency["code"])
            pair = f"{base}/{primary_currency}"
            rate = self.current_rate(base, primary_currency)
            max_buy = max(0, (quote_balance * 1_000_000) // max(1, rate))
            base_wallet = settlement_wallets.get(base)
            max_sell = int(base_wallet["balance_cents"]) if base_wallet else 0
            quote: dict[str, Any] = {
                "pair": pair,
                "base_currency": base,
                "quote_currency": primary_currency,
                "rate_ppm": rate,
                "max_buy_qty": max_buy,
                "max_sell_qty": max_sell,
            }
            if max_buy > 0:
                qty = min(1_000, max_buy)
                quote["buy_action"] = {
                    "type": "place_fx_order", "pair": pair, "side": "buy",
                    "qty": qty, "limit_rate_ppm": rate,
                }
            if max_sell > 0:
                qty = min(1_000, max_sell)
                quote["sell_action"] = {
                    "type": "place_fx_order", "pair": pair, "side": "sell",
                    "qty": qty, "limit_rate_ppm": rate,
                }
            fx_quotes.append(quote)

        open_fx_orders = [{
            "order_id": int(row["id"]), "pair": str(row["pair"]),
            "side": str(row["side"]), "qty_remaining": int(row["qty_remaining"]),
            "limit_rate_ppm": (int(row["limit_rate_ppm"])
                               if row["limit_rate_ppm"] is not None else None),
            "cancel_action": {"type": "cancel_fx_orders", "pair": str(row["pair"])},
        } for row in self.store.query(
            "SELECT id,pair,side,qty_remaining,limit_rate_ppm FROM fx_orders "
            "WHERE actor_id=? AND status='open' ORDER BY tick,seq,id LIMIT 5", (actor_id,))]

        return {
            "regional_actions_enabled": True,
            "regional_state": {
                "region_id": int(agent["region_id"]),
                "region_name": str(agent["region_name"]),
                "currency_code": primary_currency,
            },
            "regional_wallets": wallets,
            "fx_quotes": fx_quotes,
            "open_fx_orders": open_fx_orders,
            "migration_wage_gain_bps": self.migration_wage_gain_bps,
            "migration_options": self._migration_options(
                agent, actor_id=actor_id, career_day=career_day),
            "trade_opportunities": self._trade_opportunities(
                tick, actor_id=actor_id, exporter_firm_id=exporter_firm_id),
        }

    def _migration_options(
        self,
        agent,
        *,
        actor_id: int,
        career_day: bool,
        ignore_pending_migration_id: int | None = None,
    ) -> list[dict[str, Any]]:
        if (not career_day or str(agent["kind"]) != "citizen"
                or str(agent["health"] or "healthy") != "healthy"
                or bool(agent["retired"])):
            return []
        if self.store.query_one(
                "SELECT 1 FROM employments WHERE agent_id=? AND status='active'", (actor_id,)):
            return []
        pending = self.store.query_one(
            "SELECT id FROM migrations WHERE agent_id=? AND status='pending' "
            "ORDER BY id LIMIT 1", (actor_id,))
        if (pending is not None
                and int(pending["id"]) != int(ignore_pending_migration_id or 0)):
            return []
        if self._agent_credit_exposure(actor_id):
            return []

        best_by_region: dict[int, dict[str, Any]] = {}
        for row in self.store.query(
                "SELECT j.id AS job_id,j.wage_cents,f.region_id,f.currency_code,"
                "r.name AS region_name,c.numeraire_rate_ppm "
                "FROM jobs j JOIN firms f ON f.id=j.firm_id "
                "JOIN regions r ON r.id=f.region_id "
                "JOIN currencies c ON c.code=f.currency_code "
                "WHERE j.status='open' AND f.status NOT IN ('bankrupt','acquired') "
                "ORDER BY f.region_id,j.wage_cents DESC,j.id"):
            region_id = int(row["region_id"])
            if region_id in best_by_region:
                continue
            wage = int(row["wage_cents"])
            rate = int(row["numeraire_rate_ppm"])
            best_by_region[region_id] = {
                "job_id": int(row["job_id"]), "wage_cents": wage,
                "wage_numeraire_cents": max(0, round(wage * rate / 1_000_000)),
                "currency_code": str(row["currency_code"] or "USD"),
                "region_name": str(row["region_name"]),
            }

        origin_id = int(agent["region_id"])
        home_wage = int(best_by_region.get(origin_id, {}).get("wage_numeraire_cents", 0))
        options = []
        for destination_id, job in sorted(best_by_region.items()):
            if destination_id == origin_id:
                continue
            destination_wage = int(job["wage_numeraire_cents"])
            gain_bps = min(
                1_000_000,
                ((destination_wage - home_wage) * 10_000) // max(1, home_wage),
            )
            if gain_bps < self.migration_wage_gain_bps:
                continue
            options.append({
                "destination_region_id": destination_id,
                "destination_region_name": job["region_name"],
                "destination_currency": job["currency_code"],
                "best_job_id": job["job_id"],
                "best_wage_cents": job["wage_cents"],
                "best_wage_numeraire_cents": destination_wage,
                "home_best_wage_numeraire_cents": home_wage,
                "wage_gain_bps": gain_bps,
                "action": {
                    "type": "request_migration",
                    "destination_region_id": destination_id,
                    "reason": f"career opportunity job {job['job_id']}",
                },
            })
        return sorted(
            options,
            key=lambda item: (-int(item["wage_gain_bps"]),
                              int(item["destination_region_id"])),
        )[:5]

    @staticmethod
    def _is_career_day(agent, tick: int) -> bool:
        try:
            cadence = json.loads(str(agent["cadence_json"] or "{}"))
        except (TypeError, ValueError):
            cadence = {}
        try:
            every = max(1, int(cadence.get("career", 30)))
        except (TypeError, ValueError):
            every = 30
        return tick % every == int(agent["id"]) % every

    def _qualified_migration_option(
            self, tick: int, actor_id: int, destination_region_id: int, *,
            ignore_pending_migration_id: int | None = None) -> tuple[dict[str, Any] | None, str]:
        """Return the exact advertised Semantics-7 migration opportunity.

        The action boundary and nightly settlement both call this method so a
        model cannot bypass the bounded prompt facts and an agent that becomes
        ineligible before settlement cannot move.
        """
        agent = self.store.query_one("SELECT * FROM agents WHERE id=?", (actor_id,))
        if not agent or not bool(agent["alive"]):
            return None, "migration requires a living citizen"
        if agent["region_id"] is None or int(agent["region_id"]) == destination_region_id:
            return None, "valid distinct destination required"
        if not self.store.query_one("SELECT 1 FROM regions WHERE id=?", (destination_region_id,)):
            return None, "valid distinct destination required"
        if str(agent["kind"]) != "citizen":
            return None, "migration requires a citizen"
        if str(agent["health"] or "healthy") != "healthy":
            return None, "migration requires a healthy citizen"
        if bool(agent["retired"]):
            return None, "retired citizens cannot migrate for work"
        if self.store.query_one(
                "SELECT 1 FROM employments WHERE agent_id=? AND status='active'",
                (actor_id,)):
            return None, "migration requires an unemployed citizen"
        pending = self.store.query_one(
            "SELECT id FROM migrations WHERE agent_id=? AND status='pending' "
            "ORDER BY id LIMIT 1", (actor_id,))
        if (pending is not None
                and int(pending["id"]) != int(ignore_pending_migration_id or 0)):
            return None, "migration already pending"
        credit_exposure = self._agent_credit_exposure(actor_id)
        if credit_exposure:
            return None, f"resolve {credit_exposure} before migration"
        if not self._is_career_day(agent, tick):
            return None, "migration is available only on career cadence"
        options = self._migration_options(
            agent,
            actor_id=actor_id,
            career_day=self._is_career_day(agent, tick),
            ignore_pending_migration_id=ignore_pending_migration_id,
        )
        for option in options:
            if int(option["destination_region_id"]) == int(destination_region_id):
                return option, ""
        return None, (
            "migration requires career cadence, a healthy unemployed non-retired "
            "citizen, no credit exposure, and a qualified wage-gain destination"
        )

    def _trade_opportunities(
        self,
        tick: int,
        *,
        actor_id: int,
        exporter_firm_id: int | None,
    ) -> list[dict[str, Any]]:
        if not exporter_firm_id or not self.legal.controls(
                actor_id, "firm", int(exporter_firm_id)):
            return []
        exporter = self.store.query_one(
            "SELECT id,name,inventory,product_json,region_id,currency_code FROM firms "
            "WHERE id=? AND status NOT IN ('bankrupt','acquired')", (int(exporter_firm_id),))
        if not exporter or int(exporter["inventory"]) <= 0 or exporter["region_id"] is None:
            return []
        try:
            product = json.loads(str(exporter["product_json"] or "{}"))
        except (TypeError, ValueError):
            product = {}
        exporter_unit_price = max(1, int(product.get("unit_price_cents", 500)))
        exporter_currency = str(exporter["currency_code"] or "USD")

        opportunities = []
        rows = self.store.query(
            "SELECT c.id AS contract_id,i.id AS importer_firm_id,i.name AS importer_name,"
            "i.region_id AS importer_region_id,i.currency_code AS importer_currency,"
            "i.account_id AS importer_account_id,ia.currency_code AS account_currency,"
            "ia.balance_cents AS importer_balance "
            "FROM contracts c "
            "JOIN contract_parties ep ON ep.contract_id=c.id "
            "AND ep.party_type='firm' AND ep.party_id=? "
            "JOIN contract_parties ip ON ip.contract_id=c.id "
            "AND ip.party_type='firm' AND ip.party_id<>? "
            "JOIN firms i ON i.id=ip.party_id "
            "JOIN accounts ia ON ia.id=i.account_id "
            "WHERE c.status IN ('active','performed') "
            "AND (c.effective_tick IS NULL OR c.effective_tick<=?) "
            "AND (c.expiry_tick IS NULL OR c.expiry_tick>?) "
            "AND i.status NOT IN ('bankrupt','acquired') AND i.region_id<>? "
            "ORDER BY c.id,i.id",
            (int(exporter_firm_id), int(exporter_firm_id), tick, tick,
             int(exporter["region_id"])))
        for row in rows:
            importer_currency = str(row["importer_currency"] or "USD")
            if str(row["account_currency"] or "USD") != importer_currency:
                continue
            rate = self.current_rate(exporter_currency, importer_currency)
            unit_invoice = max(1, round(exporter_unit_price * rate / 1_000_000))
            importer_balance = int(row["importer_balance"])
            affordable = importer_balance // unit_invoice
            quantity = min(
                int(exporter["inventory"]), self.max_trade_quantity, affordable)
            if quantity <= 0:
                continue
            invoice = quantity * unit_invoice
            action = {
                "type": "create_trade_shipment",
                "exporter_firm_id": int(exporter_firm_id),
                "importer_firm_id": int(row["importer_firm_id"]),
                "contract_id": int(row["contract_id"]),
                "quantity": quantity,
                "invoice_cents": invoice,
                "invoice_currency": importer_currency,
                "tariff_cents": 0,
                "transport_cents": 0,
                "transit_ticks": self.trade_transit_ticks,
            }
            opportunities.append({
                "exporter_firm_id": int(exporter_firm_id),
                "exporter_name": str(exporter["name"]),
                "importer_firm_id": int(row["importer_firm_id"]),
                "importer_name": str(row["importer_name"]),
                "contract_id": int(row["contract_id"]),
                "quantity": quantity,
                "unit_invoice_cents": unit_invoice,
                "invoice_cents": invoice,
                "invoice_currency": importer_currency,
                "importer_available_cents": importer_balance,
                "action": action,
            })
            if len(opportunities) >= self.max_trade_opportunities:
                break
        return opportunities

    @staticmethod
    def _matches_trade_opportunity(
            data: dict[str, Any], expected: dict[str, Any]) -> bool:
        """Require exact model-visible settlement terms for Semantics 7.

        Gateway provenance belongs to the action envelope rather than the
        economic offer, so those fields may accompany an otherwise exact
        action. Every model-controlled settlement field must retain both the
        value and JSON scalar type emitted by the deterministic opportunity.
        """
        provenance_fields = {
            "evidence_event_ids", "model_call_id", "rationale_summary",
        }
        candidate = {
            key: value for key, value in data.items()
            if key not in provenance_fields
        }
        if set(candidate) != set(expected):
            return False
        return all(
            type(candidate[key]) is type(expected[key])
            and candidate[key] == expected[key]
            for key in expected
        )

    def _advertised_trade_actions(
            self, tick: int, actor_id: int, exporter_firm_id: int,
            data: dict[str, Any]) -> list[dict[str, Any]]:
        """Return the opportunity set actually shown to this action's author.

        Earlier actions from the same decision can legitimately change a
        firm's mutable pricing state before its shipment executes. LLM-backed
        actions therefore bind to the persisted request context that produced
        them. Direct domain callers have no call record, so they bind to the
        currently executable context instead.
        """
        model_call_id = data.get("model_call_id")
        if model_call_id is None:
            return [
                opportunity["action"] for opportunity in self._trade_opportunities(
                    tick, actor_id=actor_id,
                    exporter_firm_id=exporter_firm_id)
            ]
        if isinstance(model_call_id, bool) or not isinstance(model_call_id, int):
            return []
        call = self.store.query_one(
            "SELECT tick,agent_id,request_json FROM llm_calls WHERE id=?",
            (model_call_id,))
        if (call is None or call["agent_id"] is None
                or int(call["tick"]) != int(tick)
                or int(call["agent_id"]) != int(actor_id)):
            return []
        try:
            request = json.loads(str(call["request_json"] or "{}"))
        except (json.JSONDecodeError, TypeError, ValueError):
            return []
        context = request.get("context") if isinstance(request, dict) else None
        opportunities = (
            context.get("trade_opportunities")
            if isinstance(context, dict) else None)
        if not isinstance(opportunities, list):
            return []
        return [
            dict(opportunity["action"])
            for opportunity in opportunities
            if isinstance(opportunity, dict)
            and isinstance(opportunity.get("action"), dict)
        ]

    # ------------------------------------------------------------------ trade and migration
    def create_shipment(self, tick: int, actor_id: int, data: dict[str, Any]) -> dict[str, Any]:
        exporter_id = int(data.get("exporter_firm_id", 0))
        importer_id = int(data.get("importer_firm_id", 0))
        exporter = self.store.query_one("SELECT * FROM firms WHERE id=?", (exporter_id,))
        importer = self.store.query_one("SELECT * FROM firms WHERE id=?", (importer_id,))
        if not exporter or not importer or not self.legal.controls(actor_id, "firm", exporter_id):
            return {"ok": False, "reason": "exporter authorization and two firms required"}
        if self.engine_semantics_version >= 7:
            actor_alive = self.store.scalar(
                "SELECT alive FROM agents WHERE id=?", (actor_id,), default=0)
            if not bool(actor_alive):
                return {"ok": False, "reason": "a living authorized exporter is required"}
            if (str(exporter["status"]) in {"bankrupt", "acquired"}
                    or str(importer["status"]) in {"bankrupt", "acquired"}):
                return {"ok": False, "reason": "shipment requires two active firms"}
        if exporter["region_id"] == importer["region_id"]:
            return {"ok": False, "reason": "regional trade requires distinct regions"}
        contract_id = data.get("contract_id")
        if self.require_trade_contract:
            if contract_id is None or not self._contract_covers_firms(
                    int(contract_id), exporter_id, importer_id, tick=tick):
                return {"ok": False, "reason": "effective cross-border contract required"}
        quantity = int(data.get("quantity", 0))
        invoice = int(data.get("invoice_cents", 0))
        tariff = max(0, int(data.get("tariff_cents", 0)))
        transport = max(0, int(data.get("transport_cents", 0)))
        currency = str(data.get("invoice_currency", exporter["currency_code"])).upper()
        if (self.engine_semantics_version >= 7
                and currency != str(importer["currency_code"] or "USD").upper()):
            return {"ok": False, "reason": "invoice must use the importer's currency"}
        if quantity <= 0 or invoice <= 0 or int(exporter["inventory"]) < quantity:
            return {"ok": False, "reason": "positive available goods and invoice required"}
        if self.engine_semantics_version >= 7:
            advertised_actions = self._advertised_trade_actions(
                tick, actor_id, exporter_id, data)
            if not any(
                    self._matches_trade_opportunity(data, expected)
                    for expected in advertised_actions):
                return {
                    "ok": False,
                    "reason": (
                        "shipment must exactly match an advertised engine-qualified "
                        "trade opportunity"
                    ),
                }
        importer_wallet = self._wallet("firm", importer_id, currency, create=True)
        exporter_wallet = self._wallet("firm", exporter_id, currency, create=True)
        total = invoice + tariff + transport
        if self.ledger.balance(importer_wallet) < total:
            return {"ok": False, "reason": "importer lacks invoice currency; acquire it through FX"}
        legs = [Leg(importer_wallet, -total, "import payment"), Leg(exporter_wallet, invoice, "export revenue")]
        if tariff:
            legs.append(Leg(self.ledger.system_account(SYS_GOV, currency_code=currency), tariff, "tariff"))
        if transport:
            legs.append(Leg(self.ledger.system_account(SYS_EXTERNAL, currency_code=currency), transport, "transport"))
        txn_id = self.ledger.post(tick, "cross_border_trade", legs, memo=f"{exporter_id}->{importer_id}")
        self.store.update("firms", exporter_id, inventory=int(exporter["inventory"]) - quantity)
        arrival = tick + max(1, int(data.get("transit_ticks", 3)))
        shipment_id = self.store.insert(
            "trade_shipments", created_tick=tick, exporter_firm_id=exporter_id,
            importer_firm_id=importer_id, origin_region_id=int(exporter["region_id"]),
            destination_region_id=int(importer["region_id"]),
            contract_id=int(contract_id) if contract_id is not None else None,
            quantity=quantity, invoice_cents=invoice, invoice_currency=currency,
            tariff_cents=tariff, transport_cents=transport, arrival_tick=arrival,
            status="in_transit", payment_transaction_id=txn_id)
        self.store.log_event(tick, "trade_shipment_created", {"shipment_id": shipment_id,
            "exporter_firm_id": exporter_id, "importer_firm_id": importer_id,
            "quantity": quantity, "invoice_cents": invoice, "invoice_currency": currency,
            "arrival_tick": arrival}, phase="EXECUTION", subject_type="trade_shipment",
            subject_id=shipment_id, importance=2.2)
        return {"ok": True, "shipment_id": shipment_id, "arrival_tick": arrival,
                "transaction_id": txn_id}

    def _contract_covers_firms(
            self, contract_id: int, firm_a: int, firm_b: int, *, tick: int) -> bool:
        if self.engine_semantics_version >= 7:
            contract = self.store.query_one(
                "SELECT 1 FROM contracts WHERE id=? AND status IN ('active','performed') "
                "AND (effective_tick IS NULL OR effective_tick<=?) "
                "AND (expiry_tick IS NULL OR expiry_tick>?)",
                (contract_id, tick, tick))
        else:
            contract = self.store.query_one(
                "SELECT 1 FROM contracts WHERE id=? AND status IN ('active','performed')",
                (contract_id,))
        if not contract:
            return False
        parties = {int(row["party_id"]) for row in self.store.query(
            "SELECT party_id FROM contract_parties WHERE contract_id=? AND party_type='firm'",
            (contract_id,))}
        return {firm_a, firm_b}.issubset(parties)

    def request_migration(self, tick: int, actor_id: int, destination_region_id: int,
                          reason: str = "") -> dict[str, Any]:
        agent = self.store.query_one("SELECT region_id FROM agents WHERE id=? AND alive=1", (actor_id,))
        destination = self.store.query_one("SELECT 1 FROM regions WHERE id=?", (destination_region_id,))
        if not agent or not destination or agent["region_id"] is None or int(agent["region_id"]) == destination_region_id:
            return {"ok": False, "reason": "valid distinct destination required"}
        if self.store.query_one("SELECT 1 FROM migrations WHERE agent_id=? AND status='pending'", (actor_id,)):
            return {"ok": False, "reason": "migration already pending"}
        if self.engine_semantics_version >= 7:
            _, ineligible_reason = self._qualified_migration_option(
                tick, actor_id, destination_region_id)
            if ineligible_reason:
                return {"ok": False, "reason": ineligible_reason}
        if self.local_currency_action_surfaces or self.engine_semantics_version >= 7:
            credit_exposure = self._agent_credit_exposure(actor_id)
            if credit_exposure:
                return {"ok": False, "reason": f"resolve {credit_exposure} before migration"}
        migration_id = self.store.insert(
            "migrations", agent_id=actor_id, origin_region_id=int(agent["region_id"]),
            destination_region_id=destination_region_id, requested_tick=tick,
            reason=str(reason)[:300], status="pending")
        return {"ok": True, "migration_id": migration_id, "status": "pending"}

    def _agent_credit_exposure(self, agent_id: int) -> str | None:
        if self.store.query_one(
                "SELECT 1 FROM loans WHERE borrower_type='agent' AND borrower_id=? "
                "AND status='active'", (agent_id,)):
            return "active loan debt"
        if self.store.query_one(
                "SELECT 1 FROM loan_applications WHERE borrower_type='agent' AND borrower_id=? "
                "AND status='pending'", (agent_id,)):
            return "the pending loan application"
        return None

    def run_nightly(self, tick: int) -> None:
        if not self.enabled:
            return
        for shipment in self.store.query(
                "SELECT * FROM trade_shipments WHERE status='in_transit' AND arrival_tick<=? ORDER BY id", (tick,)):
            importer = self.store.query_one("SELECT inventory FROM firms WHERE id=?", (shipment["importer_firm_id"],))
            self.store.update("firms", int(shipment["importer_firm_id"]),
                              inventory=int(importer["inventory"]) + int(shipment["quantity"]))
            self.store.update("trade_shipments", int(shipment["id"]), status="delivered")
            self.store.log_event(tick, "trade_shipment_delivered", {"shipment_id": int(shipment["id"]),
                "importer_firm_id": int(shipment["importer_firm_id"]),
                "quantity": int(shipment["quantity"])}, phase="NIGHT_CLOSE",
                subject_type="trade_shipment", subject_id=int(shipment["id"]), importance=1.8)
        for migration in self.store.query("SELECT * FROM migrations WHERE status='pending' ORDER BY id"):
            agent_id = int(migration["agent_id"])
            credit_exposure = (
                self._agent_credit_exposure(agent_id)
                if (self.local_currency_action_surfaces
                    or self.engine_semantics_version >= 7) else None)
            if credit_exposure:
                self.store.update(
                    "migrations", int(migration["id"]), status="rejected", completed_tick=tick)
                self.store.log_event(
                    tick, "migration_rejected_credit_exposure", {
                        "migration_id": int(migration["id"]), "agent_id": agent_id,
                        "reason": credit_exposure,
                    }, phase="NIGHT_CLOSE", subject_type="agent", subject_id=agent_id,
                    importance=1.5)
                continue
            if self.engine_semantics_version >= 7:
                _, ineligible_reason = self._qualified_migration_option(
                    int(migration["requested_tick"]), agent_id,
                    int(migration["destination_region_id"]),
                    ignore_pending_migration_id=int(migration["id"]),
                )
                if ineligible_reason:
                    self.store.update(
                        "migrations", int(migration["id"]), status="rejected",
                        completed_tick=tick)
                    self.store.log_event(
                        tick, "migration_rejected_ineligible", {
                            "migration_id": int(migration["id"]), "agent_id": agent_id,
                            "reason": ineligible_reason,
                        }, phase="NIGHT_CLOSE", subject_type="agent", subject_id=agent_id,
                        importance=1.5)
                    continue
            destination = int(migration["destination_region_id"])
            currency = self.currency_for_region(destination)
            wallet = self._wallet("agent", agent_id, currency, create=True)
            self.store.execute(
                "UPDATE employments SET status='ended',end_tick=? WHERE agent_id=? AND status='active'",
                (tick, agent_id))
            self.store.update("agents", agent_id, region_id=destination, checking_account_id=wallet,
                              employer_id=None)
            self.store.update("migrations", int(migration["id"]), status="completed", completed_tick=tick)
            self.store.log_event(tick, "agent_migrated", {"migration_id": int(migration["id"]),
                "agent_id": agent_id, "origin_region_id": int(migration["origin_region_id"]),
                "destination_region_id": destination, "currency_code": currency}, phase="NIGHT_CLOSE",
                subject_type="agent", subject_id=agent_id, importance=1.5)
        if self.promotion_interval > 0 and tick % self.promotion_interval == 0:
            self.rebalance_tiers(tick)

    def rebalance_tiers(self, tick: int) -> None:
        if not self.enabled:
            return
        rows = self.store.query(
            "WITH cash AS ("
            " SELECT owner_id AS agent_id,SUM(balance_cents) AS total FROM accounts"
            " WHERE owner_type='agent' GROUP BY owner_id"
            "), firm_counts AS ("
            " SELECT founder_agent_id AS agent_id,COUNT(*) AS total FROM firms"
            " WHERE status<>'bankrupt' GROUP BY founder_agent_id"
            "), matter_agents AS ("
            " SELECT id,claimant_id AS agent_id FROM legal_matters WHERE claimant_type='agent'"
            " UNION SELECT id,respondent_id AS agent_id FROM legal_matters WHERE respondent_type='agent'"
            "), matter_counts AS ("
            " SELECT agent_id,COUNT(*) AS total FROM matter_agents GROUP BY agent_id"
            "), activity_counts AS ("
            " SELECT subject_id AS agent_id,COUNT(*) AS total FROM events"
            " WHERE subject_type='agent' AND tick>? GROUP BY subject_id"
            ") SELECT a.id,a.role,a.population_tier,a.pinned_core,"
            "COALESCE(cash.total,0) cash,COALESCE(firm_counts.total,0) firms,"
            "COALESCE(matter_counts.total,0) matters,COALESCE(activity_counts.total,0) activity "
            "FROM agents a LEFT JOIN cash ON cash.agent_id=a.id "
            "LEFT JOIN firm_counts ON firm_counts.agent_id=a.id "
            "LEFT JOIN matter_counts ON matter_counts.agent_id=a.id "
            "LEFT JOIN activity_counts ON activity_counts.agent_id=a.id "
            "WHERE a.alive=1 ORDER BY a.id", (max(0, tick - self.promotion_interval),))
        scored = []
        for row in rows:
            institutional = 1 if row["role"] else 0
            score = institutional * 1_000_000 + int(row["firms"]) * 100_000 + int(row["matters"]) * 10_000
            score += int(row["activity"]) * 100 + max(0, int(row["cash"])) / 100_000
            if row["pinned_core"]:
                score += 10_000_000
            scored.append((float(score), -int(row["id"]), row))
        core_ids = {int(item[2]["id"]) for item in sorted(scored, reverse=True)[:self.core_target]}
        for score, _, row in scored:
            old = str(row["population_tier"] or "periphery")
            new = "core" if int(row["id"]) in core_ids else "periphery"
            if old == new:
                continue
            self.store.update("agents", int(row["id"]), population_tier=new,
                              model_tier="strong" if new == "core" else "citizen")
            self.store.insert(
                "agent_tier_history", tick=tick, agent_id=int(row["id"]), old_tier=old,
                new_tier=new, score=score,
                reason_json=json.dumps({"role": row["role"], "firms": int(row["firms"]),
                                        "matters": int(row["matters"]), "activity": int(row["activity"])},
                                       sort_keys=True))
            self.store.log_event(tick, "agent_tier_changed", {"agent_id": int(row["id"]),
                "old_tier": old, "new_tier": new, "score": score}, phase="NIGHT_CLOSE",
                subject_type="agent", subject_id=int(row["id"]), importance=1.0)

    def region_state(self) -> list[dict[str, Any]]:
        out = []
        for region in self.store.query("SELECT * FROM regions ORDER BY id"):
            region_id = int(region["id"])
            out.append({**dict(region),
                        "specialization": json.loads(region["specialization_json"] or "[]"),
                        "population": int(self.store.scalar(
                            "SELECT COUNT(*) FROM agents WHERE alive=1 AND region_id=?", (region_id,), default=0)),
                        "firms": int(self.store.scalar(
                            "SELECT COUNT(*) FROM firms WHERE status NOT IN ('bankrupt','acquired') AND region_id=?",
                            (region_id,), default=0))})
        return out

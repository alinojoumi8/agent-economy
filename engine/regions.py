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
                 prng: random.Random, config: dict | None = None):
        self.store = store
        self.ledger = ledger
        self.legal = legal
        self.prng = prng
        self.config = config or {}
        self.enabled = config is not None and bool(self.config.get("enabled", True))
        self.specs = list(self.config.get("regions", DEFAULT_REGIONS))
        self.core_target = int(self.config.get("core_agents", 100))
        self.promotion_interval = int(self.config.get("promotion_interval_ticks", 30))
        self.require_trade_contract = bool(self.config.get("require_trade_contract", True))
        self.fx_inventory = int(self.config.get("fx_market_maker_inventory", 100_000_000))

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

    # ------------------------------------------------------------------ trade and migration
    def create_shipment(self, tick: int, actor_id: int, data: dict[str, Any]) -> dict[str, Any]:
        exporter_id = int(data.get("exporter_firm_id", 0))
        importer_id = int(data.get("importer_firm_id", 0))
        exporter = self.store.query_one("SELECT * FROM firms WHERE id=?", (exporter_id,))
        importer = self.store.query_one("SELECT * FROM firms WHERE id=?", (importer_id,))
        if not exporter or not importer or not self.legal.controls(actor_id, "firm", exporter_id):
            return {"ok": False, "reason": "exporter authorization and two firms required"}
        if exporter["region_id"] == importer["region_id"]:
            return {"ok": False, "reason": "regional trade requires distinct regions"}
        contract_id = data.get("contract_id")
        if self.require_trade_contract:
            if contract_id is None or not self._contract_covers_firms(int(contract_id), exporter_id, importer_id):
                return {"ok": False, "reason": "effective cross-border contract required"}
        quantity = int(data.get("quantity", 0))
        invoice = int(data.get("invoice_cents", 0))
        tariff = max(0, int(data.get("tariff_cents", 0)))
        transport = max(0, int(data.get("transport_cents", 0)))
        currency = str(data.get("invoice_currency", exporter["currency_code"])).upper()
        if quantity <= 0 or invoice <= 0 or int(exporter["inventory"]) < quantity:
            return {"ok": False, "reason": "positive available goods and invoice required"}
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

    def _contract_covers_firms(self, contract_id: int, firm_a: int, firm_b: int) -> bool:
        if not self.store.query_one(
                "SELECT 1 FROM contracts WHERE id=? AND status IN ('active','performed')", (contract_id,)):
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
        migration_id = self.store.insert(
            "migrations", agent_id=actor_id, origin_region_id=int(agent["region_id"]),
            destination_region_id=destination_region_id, requested_tick=tick,
            reason=str(reason)[:300], status="pending")
        return {"ok": True, "migration_id": migration_id, "status": "pending"}

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

"""Securities held for estate creditors; representatives never receive sale cash."""
from __future__ import annotations

import json

from .estates import EstateError
from .estate_assets import EstateAssetCustody


class EstateSecurities(EstateAssetCustody):

    def remaining(self, lot):
        return lot["qty"] - self.store.scalar(
            "SELECT COALESCE(SUM(qty),0) FROM estate_security_sale_lots WHERE lot_id=?", (lot["id"],)) - self.store.scalar(
            "SELECT COALESCE(SUM(qty),0) FROM estate_unlisted_sales WHERE lot_id=?", (lot["id"],))

    def lots(self, estate_id, firm_id=None):
        return self.store.query("SELECT l.* FROM estate_security_lots l WHERE l.estate_id=? "
            "AND (? IS NULL OR l.firm_id=?) AND NOT EXISTS "
            "(SELECT 1 FROM estate_security_releases r WHERE r.lot_id=l.id) ORDER BY l.id",
            (estate_id, firm_id, firm_id))


    def open(self, tick, estate_id, person, beneficiaries):
        for share in self.store.query("SELECT s.*,f.currency_code FROM shares s JOIN firms f ON f.id=s.firm_id "
                "WHERE s.holder_type='agent' AND s.holder_id=? AND s.qty<>0 ORDER BY s.firm_id", (person,)):
            if share["qty"] < 0:
                raise EstateError("a short security position needs an explicit estate liability")
            if self.needs_custody(tick, estate_id, share["currency_code"]):
                item = self.store.scalar("SELECT id FROM estate_items WHERE estate_id=? AND kind='security' AND source_id=?",
                                         (estate_id, share["id"]))
                if item is None:
                    raise EstateError("retained security has no opening inventory")
                self.store.insert("estate_security_lots", estate_id=estate_id, firm_id=share["firm_id"],
                    started_tick=tick, qty=share["qty"], source_item_id=item,
                    policy="known_claims_then_residual_v1")
            else:
                self.e.business_control.distribute_shares(tick, person, beneficiaries, firm_id=share["firm_id"])

    def accept_transfer(self, tick, transfer_id):
        transfer = self.store.query_one("SELECT * FROM estate_share_transfers WHERE id=?", (transfer_id,))
        case = self.store.query_one("SELECT * FROM estate_cases WHERE deceased_agent_id=?", (transfer["beneficiary_id"],))
        if case is None:
            raise EstateError("deceased security beneficiary lacks an estate")
        self.store.insert("estate_security_lots", estate_id=case["id"], firm_id=transfer["firm_id"],
            started_tick=tick, qty=transfer["qty"], source_transfer_id=transfer_id,
            policy="known_claims_then_residual_v1")
        self.release_ready(tick, case["id"])


    def operator_for(self, firm_id):
        for row in self.store.query("SELECT l.estate_id,SUM(l.qty-COALESCE((SELECT SUM(p.qty) "
                "FROM estate_security_sale_lots p WHERE p.lot_id=l.id),0)-COALESCE((SELECT SUM(u.qty) "
                "FROM estate_unlisted_sales u WHERE u.lot_id=l.id),0)) qty FROM estate_security_lots l "
                "WHERE l.firm_id=? AND NOT EXISTS (SELECT 1 FROM estate_security_releases r WHERE r.lot_id=l.id) "
                "GROUP BY l.estate_id HAVING qty>0 ORDER BY qty DESC,l.estate_id", (firm_id,)):
            representatives = self.representatives(row["estate_id"])
            if representatives:
                return representatives[0]["actor_id"]
        return None

    def context_for(self, actor_id, tick):
        """Private current-decision scope, with no invented security valuation."""
        if not self.enabled:
            return []
        result = []
        for case in self.store.query("SELECT DISTINCT c.* FROM estate_cases c JOIN estate_security_lots l "
                "ON l.estate_id=c.id WHERE c.opened_tick<=? AND l.started_tick<=? AND NOT EXISTS "
                "(SELECT 1 FROM estate_security_releases r WHERE r.lot_id=l.id) ORDER BY c.id", (tick, tick)):
            proof = self.authority(case["id"], actor_id)
            if proof is None:
                continue
            quantities = {}
            for lot in self.lots(case["id"]):
                if lot["started_tick"] <= tick:
                    quantities[lot["firm_id"]] = quantities.get(lot["firm_id"], 0) + self.remaining(lot)
            positions = []
            for firm, quantity in sorted(quantities.items()):
                if quantity <= 0:
                    continue
                issuer = self.store.query_one("SELECT currency_code,status FROM firms WHERE id=?", (firm,))
                history = self.store.query_one("SELECT COALESCE(SUM(CASE WHEN o.status IN ('open','partial') "
                    "THEN o.qty_remaining ELSE 0 END),0) pending_sale_qty, "
                    "MAX(CASE WHEN o.tick<=? THEN o.tick END) last_offer_tick FROM orders o "
                    "JOIN estate_security_orders a ON a.order_id=o.id WHERE a.estate_id=? AND o.firm_id=?",
                    (tick, case["id"], firm))
                pending = history["pending_sale_qty"]
                positions.append({"firm_id": firm, "currency_code": issuer["currency_code"], "custody_qty": quantity,
                    "tradeable": issuer["status"] == "listed", "pending_sale_qty": pending,
                    "last_offer_tick": history["last_offer_tick"],
                    "orderable_qty": max(0, quantity - pending),
                    "order_scope": {"type": "place_order", "estate_id": case["id"], "firm_id": firm, "side": "sell"}})
            if positions:
                result.append({"estate_id": case["id"], "deceased_agent_id": case["deceased_agent_id"],
                    "authority": proof.get("authority", "guardian" if proof["guardian_id"] is not None else "beneficiary"),
                    **({"administration_id": proof["administration_id"]} if proof.get("administration_id") is not None else {}),
                    "beneficiary_id": proof["beneficiary_id"], "securities": positions,
                    "proceeds_destination": "estate_creditors_then_recorded_beneficiaries"})
        return result

    def place_order(self, tick, actor_id, estate_id, firm_id, side, qty, limit_cents, order_type):
        case = self.store.query_one("SELECT * FROM estate_cases WHERE id=?", (estate_id,))
        proof = self.authority(estate_id, actor_id) if case is not None else None
        if proof is None:
            return {"ok": False, "reason": "estate securities require a living adult beneficiary, current guardian, or appointed public administrator"}
        if tick < case["opened_tick"] or any(lot["started_tick"] > tick for lot in self.lots(estate_id, firm_id)):
            return {"ok": False, "reason": "estate security order cannot precede its custody"}
        if side != "sell":
            return {"ok": False, "reason": "estate security authority permits sales only"}
        available = sum(self.remaining(lot) for lot in self.lots(estate_id, firm_id))
        if qty > available or qty <= 0:
            return {"ok": False, "reason": "insufficient securities in estate custody"}
        currency = self.store.scalar("SELECT currency_code FROM firms WHERE id=?", (firm_id,))
        with self.store.savepoint("estate_security_order"):
            account = self.e.estate_cases._wallet(case["deceased_agent_id"], currency)
            order = self.e.exchange.place_order(tick, case["deceased_agent_id"], firm_id, side, qty, limit_cents, order_type)
            self.store.insert("estate_security_orders", order_id=order, estate_id=estate_id,
                actor_id=actor_id, beneficiary_id=proof["beneficiary_id"], guardian_id=proof["guardian_id"],
                administration_id=proof.get("administration_id"),
                administration_end_frontier=(self.store.scalar("SELECT COALESCE(MAX(id),0) FROM estate_administration_ends")
                    if proof.get("administration_id") is not None else 0),
                actor_age=proof["actor_age"], beneficiary_age=proof["beneficiary_age"],
                estate_frontier_id=self.store.scalar("SELECT MAX(id) FROM estate_cases"),
                path_json=json.dumps(proof["path"], separators=(",", ":")), account_id=account)
            self.store.log_event(tick, "estate_security_order_placed", {
                "estate_id": estate_id, "order_id": order, "actor_id": actor_id, "firm_id": firm_id,
                "qty": qty, "limit_price_cents": limit_cents}, phase="EXECUTION",
                subject_type="agent", subject_id=actor_id)
        return {"ok": True, "order_id": order}

    def authorization(self, order_id):
        return self.store.query_one("SELECT * FROM estate_security_orders WHERE order_id=?", (order_id,))

    def valid_order(self, order, tick=None):
        auth = self.authorization(order["id"])
        if auth is None:
            return not self.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (order["agent_id"],))
        case = self.store.query_one("SELECT * FROM estate_cases WHERE id=?", (auth["estate_id"],))
        proof = self.authority(auth["estate_id"], auth["actor_id"])
        return bool((tick is None or order["tick"] <= tick) and case is not None
            and order["agent_id"] == case["deceased_agent_id"] and order["side"] == "sell"
            and proof is not None and proof["beneficiary_id"] == auth["beneficiary_id"]
            and proof.get("administration_id") == auth["administration_id"]
            and proof["guardian_id"] == auth["guardian_id"] and proof["path"] == json.loads(auth["path_json"])
            and sum(self.remaining(lot) for lot in self.lots(auth["estate_id"], order["firm_id"])) > 0)

    def sale_account(self, order):
        auth = self.authorization(order["id"])
        return auth["account_id"] if auth else self.e.ledger.agent_checking_id(order["agent_id"])

    def record_sale(self, tick, trade_id, order, transaction_id, buyer_account):
        auth = self.authorization(order["id"])
        if auth is None:
            return
        if not self.valid_order(order, tick):
            raise EstateError("estate sale lacks current representative authority")
        trade = self.store.query_one("SELECT * FROM trades WHERE id=?", (trade_id,))
        sale = self.store.insert("estate_security_sales", trade_id=trade_id, authorization_id=auth["id"],
                                 transaction_id=transaction_id, buyer_account_id=buyer_account)
        remaining = trade["qty"]
        for lot in self.lots(auth["estate_id"], trade["firm_id"]):
            amount = min(remaining, self.remaining(lot))
            if amount:
                self.store.insert("estate_security_sale_lots", sale_id=sale, lot_id=lot["id"], qty=amount)
                remaining -= amount
        if remaining:
            raise EstateError("estate sale exceeds retained security quantities")

    def release_ready(self, tick, estate_id):
        case = self.store.query_one("SELECT * FROM estate_cases WHERE id=?", (estate_id,))
        if case is None:
            return
        firms = sorted({lot["firm_id"] for lot in self.lots(estate_id)})
        for firm in firms:
            lots = self.lots(estate_id, firm)
            quantities = [(lot, self.remaining(lot)) for lot in lots]
            for lot, amount in quantities:
                if amount == 0:
                    self.store.insert("estate_security_releases", lot_id=lot["id"], tick=tick, qty=0, **self._frontier())
            pending = [(lot, amount) for lot, amount in quantities if amount > 0]
            currency = self.store.scalar("SELECT currency_code FROM firms WHERE id=?", (firm,))
            if not pending or self.needs_custody(tick, estate_id, currency):
                continue
            key = f"estate_security_release:{max(lot['id'] for lot, _ in pending)}"
            with self.store.savepoint("estate_security_release"):
                held = self.e.exchange.shares_held(firm, "agent", case["deceased_agent_id"])
                if held != sum(amount for _, amount in pending):
                    raise EstateError("estate security custody and nominee holdings disagree")
                for lot, amount in pending:
                    self.store.insert("estate_security_releases", lot_id=lot["id"], tick=tick, qty=amount,
                                      distribution_key=key, **self._frontier())
                members = [(r["agent_id"], r["weight"]) for r in self.store.query(
                    "SELECT * FROM estate_beneficiaries WHERE estate_id=? ORDER BY id", (estate_id,))]
                self.e.business_control.distribute_shares(tick, case["deceased_agent_id"], members,
                                                         distribution_key=key, firm_id=firm, allow_deceased=True)
                self.store.execute("UPDATE orders SET status='cancelled' WHERE agent_id=? AND firm_id=? "
                    "AND status IN ('open','partial')", (case["deceased_agent_id"], firm))

    def refresh(self, tick):
        if not self.enabled:
            return
        for row in self.store.query("SELECT DISTINCT estate_id FROM estate_security_lots ORDER BY estate_id"):
            self.release_ready(tick, row["estate_id"])
        self.e.estate_administration.reconcile(tick)
        self.revoke_invalid_orders(tick)
        self.e.estate_unlisted_sales.reconcile(tick)

    def revoke_invalid_orders(self, tick, estate_id=None):
        for order in self.store.query("SELECT o.* FROM orders o JOIN estate_security_orders a ON a.order_id=o.id "
                "WHERE o.status IN ('open','partial') AND (? IS NULL OR a.estate_id=?) ORDER BY o.id", (estate_id, estate_id)):
            if not self.valid_order(order, tick):
                self.e.exchange._cancel_order(order["id"])

    def check_invariants(self):
        if not self.enabled:
            return
        for table, column, parent in (
                ("estate_security_releases", "lot_id", "estate_security_lots"),
                ("estate_security_sale_lots", "lot_id", "estate_security_lots"),
                ("estate_security_sale_lots", "sale_id", "estate_security_sales")):
            if self.store.scalar(f"SELECT c.id FROM {table} c LEFT JOIN {parent} p ON p.id=c.{column} WHERE p.id IS NULL LIMIT 1"):
                raise EstateError("orphaned estate security evidence")
        expected, releases = {}, {}
        for lot in self.store.query("SELECT l.*,c.deceased_agent_id FROM estate_security_lots l "
                                   "LEFT JOIN estate_cases c ON c.id=l.estate_id ORDER BY l.id"):
            if lot["deceased_agent_id"] is None:
                raise EstateError("security custody lacks an estate")
            if lot["source_item_id"] is not None:
                item = self.store.query_one("SELECT * FROM estate_items WHERE id=?", (lot["source_item_id"],))
                evidence = json.loads(item["snapshot_json"]) if item else {}
                valid = item and item["estate_id"] == lot["estate_id"] and item["kind"] == "security" and evidence.get("firm_id") == lot["firm_id"] and evidence.get("qty") == lot["qty"]
            else:
                transfer = self.store.query_one("SELECT * FROM estate_share_transfers WHERE id=?", (lot["source_transfer_id"],))
                valid = transfer and transfer["beneficiary_id"] == lot["deceased_agent_id"] and transfer["firm_id"] == lot["firm_id"] and transfer["qty"] == lot["qty"]
            if not valid:
                raise EstateError("estate security lot disagrees with its source")
            left = self.remaining(lot)
            release = self.store.query_one("SELECT * FROM estate_security_releases WHERE lot_id=?", (lot["id"],))
            if left < 0 or (release and (release["qty"] != left or release["tick"] < lot["started_tick"])):
                raise EstateError("estate security units do not reconcile")
            if release and release["qty"]:
                currency = self.store.scalar("SELECT currency_code FROM firms WHERE id=?", (lot["firm_id"],))
                self.check_release_frontier(release["tick"], lot["estate_id"], currency, release)
                key = (lot["deceased_agent_id"], lot["firm_id"], release["distribution_key"])
                releases[key] = releases.get(key, 0) + release["qty"]
            if not release:
                key = (lot["deceased_agent_id"], lot["firm_id"])
                expected[key] = expected.get(key, 0) + left
        for holding in self.store.query("SELECT s.* FROM shares s JOIN estate_cases c ON c.deceased_agent_id=s.holder_id "
                                       "WHERE s.holder_type='agent' AND s.qty<>0"):
            if expected.pop((holding["holder_id"], holding["firm_id"]), 0) != holding["qty"]:
                raise EstateError("estate security custody and nominee holdings disagree")
        if any(expected.values()):
            raise EstateError("retained estate securities are missing")
        for key, quantity in releases.items():
            moved = self.store.scalar("SELECT COALESCE(SUM(qty),0) FROM estate_share_transfers "
                "WHERE deceased_agent_id=? AND firm_id=? AND distribution_key=?", key)
            if moved != quantity:
                raise EstateError("estate security release lacks its exact in-kind distribution")
        for auth in self.store.query("SELECT * FROM estate_security_orders ORDER BY id"):
            self._check_authorization(auth)
        for sale in self.store.query("SELECT * FROM estate_security_sales ORDER BY id"):
            auth = self.store.query_one("SELECT * FROM estate_security_orders WHERE id=?", (sale["authorization_id"],))
            trade = self.store.query_one("SELECT * FROM trades WHERE id=?", (sale["trade_id"],))
            if auth is None or trade is None or trade["sell_order_id"] != auth["order_id"]:
                raise EstateError("estate sale lacks its authorized order and trade")
            owner = self.store.scalar("SELECT deceased_agent_id FROM estate_cases WHERE id=?", (auth["estate_id"],))
            if trade["seller_id"] != owner or self.store.scalar("SELECT kind FROM transactions WHERE id=?",
                    (sale["transaction_id"],)) != "equity_trade":
                raise EstateError("estate sale has the wrong seller or payment provenance")
            lots = self.store.query("SELECT p.*,l.estate_id,l.firm_id,l.started_tick FROM estate_security_sale_lots p "
                                   "JOIN estate_security_lots l ON l.id=p.lot_id WHERE p.sale_id=? ORDER BY p.id", (sale["id"],))
            if sum(lot["qty"] for lot in lots) != trade["qty"] or any(lot["estate_id"] != auth["estate_id"] or lot["firm_id"] != trade["firm_id"] or lot["started_tick"] > trade["tick"] for lot in lots):
                raise EstateError("estate sale and retained units disagree")
            source = self.store.query_one("SELECT * FROM accounts WHERE id=?", (sale["buyer_account_id"],))
            target = self.store.query_one("SELECT * FROM accounts WHERE id=?", (auth["account_id"],))
            if source is None or source["owner_type"] != "agent" or source["owner_id"] != trade["buyer_id"]:
                raise EstateError("estate sale has the wrong buyer account")
            expected_legs = self.e.estate_cases._transfer_legs(source, target, trade["qty"] * trade["price_cents"])
            if self.e.cash_estates._transaction_legs(sale["transaction_id"], trade["tick"], target["currency_code"]) != expected_legs:
                raise EstateError("estate sale and funded cash disagree")
            if not self.store.scalar("SELECT id FROM estate_receipts WHERE estate_id=? AND source_account_id=? "
                                    "AND origin_transaction_id=?", (auth["estate_id"], auth["account_id"], sale["transaction_id"])):
                raise EstateError("estate sale proceeds lack an estate receipt")

    def _check_authorization(self, auth):
        order = self.store.query_one("SELECT * FROM orders WHERE id=?", (auth["order_id"],))
        case = self.store.query_one("SELECT * FROM estate_cases WHERE id=?", (auth["estate_id"],))
        account = self.store.query_one("SELECT * FROM accounts WHERE id=?", (auth["account_id"],))
        if not order or not case or not account or order["side"] != "sell" or order["agent_id"] != case["deceased_agent_id"] or account["owner_type"] != "agent" or account["owner_id"] != case["deceased_agent_id"]:
            raise EstateError("estate security authorization has the wrong owner or account")
        actor_age = self.store.scalar("SELECT age FROM agents WHERE id=?", (auth["actor_id"],), default=-1)
        beneficiary_age = self.store.scalar("SELECT age FROM agents WHERE id=?", (auth["beneficiary_id"],), default=-1)
        if order["tick"] < case["opened_tick"] or actor_age < auth["actor_age"]:
            raise EstateError("estate security authority has invalid age or time evidence")
        frontier = self.store.query_one("SELECT * FROM estate_cases WHERE id=?", (auth["estate_frontier_id"],))
        if frontier is None or frontier["id"] < case["id"] or frontier["opened_tick"] > order["tick"]:
            raise EstateError("estate security authority has an invalid estate frontier")
        currency = self.store.scalar("SELECT currency_code FROM firms WHERE id=?", (order["firm_id"],))
        if account["currency_code"] != currency or account["kind"] not in self.e.estate_cases.CASH_KINDS:
            raise EstateError("estate security authorization has the wrong settlement currency")
        if auth["administration_id"] is not None:
            self.e.estate_administration.check_order_authority(auth, order["tick"])
            if self.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=? AND id<=?",
                                 (auth["actor_id"], auth["estate_frontier_id"])):
                raise EstateError("estate public administrator was already deceased")
            return
        if beneficiary_age < auth["beneficiary_age"]:
            raise EstateError("estate security authority has invalid age or time evidence")
        route = json.loads(auth["path_json"])
        case_id, beneficiary = case["id"], None
        if not isinstance(route, list) or not route:
            raise EstateError("estate security authority lacks a beneficial path")
        for index, member_id in enumerate(route):
            member = self.store.query_one("SELECT * FROM estate_beneficiaries WHERE id=?", (member_id,))
            if member is None or member["estate_id"] != case_id or member["agent_id"] is None:
                raise EstateError("estate security authority has a false beneficial path")
            beneficiary = member["agent_id"]
            descendant = self.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=? AND id<=?",
                                            (beneficiary, auth["estate_frontier_id"]))
            if index < len(route) - 1:
                if descendant is None:
                    raise EstateError("estate security authority predates its beneficial path")
                case_id = descendant
            elif descendant is not None:
                raise EstateError("estate security representative claimed a deceased beneficiary")
        if beneficiary != auth["beneficiary_id"] or self.store.scalar(
                "SELECT id FROM estate_cases WHERE deceased_agent_id=? AND id<=?", (auth["actor_id"], auth["estate_frontier_id"])):
            raise EstateError("estate security representative was not eligible")
        if auth["guardian_id"] is not None:
            guardian = self.store.query_one("SELECT * FROM guardianships WHERE id=?", (auth["guardian_id"],))
            if guardian is None or guardian["guardian_agent_id"] != auth["actor_id"] or guardian["child_agent_id"] != beneficiary or guardian["started_tick"] > order["tick"] or (guardian["ended_tick"] is not None and guardian["ended_tick"] < order["tick"]):
                raise EstateError("estate security guardian lacked the recorded authority")

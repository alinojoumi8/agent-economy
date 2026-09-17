"""Explicit cash bids for entire retained lots of private-company shares."""
from __future__ import annotations

import json

from .estate_assets import EstateAssetCustody
from .estates import EstateError


class EstateUnlistedSales(EstateAssetCustody):
    POLICY = "funded_whole_unlisted_lot_bids_v1"
    TERMS = ("lot_id", "qty", "buyer_account_id", "amount_cents", "currency_code", "expires_tick")

    def _lot(self, lot_id):
        return self.store.query_one("SELECT l.*,c.deceased_agent_id,f.currency_code,f.status,f.region_id "
            "FROM estate_security_lots l JOIN estate_cases c ON c.id=l.estate_id "
            "JOIN firms f ON f.id=l.firm_id WHERE l.id=?", (lot_id,))

    def _listed_frontier(self):
        return self.store.scalar("SELECT COALESCE(MAX(id),0) FROM estate_security_sales")

    def _quantity_at(self, lot, frontier, tick):
        if frontier:
            latest = self.store.query_one("SELECT t.tick FROM estate_security_sales s JOIN trades t ON t.id=s.trade_id WHERE s.id=?", (frontier,))
            if latest is None or latest["tick"] > tick:
                raise EstateError("private share sale has an invalid listed-sale frontier")
        return lot["qty"] - self.store.scalar("SELECT COALESCE(SUM(qty),0) FROM estate_security_sale_lots WHERE lot_id=? AND sale_id<=?",
                                             (lot["id"], frontier))

    def _terminal_reason(self, bid, tick):
        if tick >= bid["expires_tick"]:
            return "expired"
        if self._adult(bid["buyer_agent_id"]) is None:
            return "buyer_unavailable"
        lot = self._lot(bid["lot_id"])
        if lot is None or self.store.scalar("SELECT id FROM estate_security_releases WHERE lot_id=?", (bid["lot_id"],)):
            return "lot_disposed"
        remaining = self.e.estate_securities.remaining(lot)
        if remaining <= 0:
            return "lot_disposed"
        if lot["status"] != "private":
            return "issuer_status_changed"
        if remaining != bid["qty"]:
            return "lot_quantity_changed"
        return None

    def _available(self, bid, tick):
        return bool(bid is not None and bid["created_tick"] <= tick and not self.store.scalar(
            "SELECT id FROM estate_unlisted_bid_ends WHERE bid_id=?", (bid["id"],)) and self._terminal_reason(bid, tick) is None)

    def _end(self, tick, bid, reason, phase="NIGHT_CLOSE"):
        status = self._lot(bid["lot_id"])["status"]
        frontier = self._listed_frontier()
        event = self.store.log_event(tick, "estate_unlisted_bid_ended",
            {"bid_id": bid["id"], "reason": reason, "issuer_status": status, "listed_sale_frontier": frontier},
            phase=phase, subject_type="agent", subject_id=bid["buyer_agent_id"])
        self.store.insert("estate_unlisted_bid_ends", bid_id=bid["id"], tick=tick,
            reason=reason, issuer_status=status, listed_sale_frontier=frontier, event_id=event)

    def _bid_payload(self, bid):
        return {key: bid[key] for key in (*self.TERMS, "buyer_agent_id", "request_key", "listed_sale_frontier")} | {"issuer_status": "private"}

    def place_bid(self, tick, actor, action):
        if not self.enabled:
            return {"ok": False, "reason": "private estate share sales require semantics 20"}
        previous = self.store.query_one("SELECT * FROM estate_unlisted_bids WHERE buyer_agent_id=? AND request_key=?", (actor, action["request_key"]))
        if previous is not None:
            if tick < previous["created_tick"] or any(previous[key] != action[key] for key in self.TERMS):
                return {"ok": False, "reason": "private share bid request key has different terms or time"}
            return {"ok": True, "bid_id": previous["id"], "existing": True}
        person, lot = self._adult(actor), self._lot(action["lot_id"])
        if person is None or lot is None or lot["started_tick"] > tick:
            return {"ok": False, "reason": "private share bid requires a living adult and recorded custody"}
        bid = {key: action[key] for key in self.TERMS} | {"buyer_agent_id": actor,
            "request_key": action["request_key"], "listed_sale_frontier": self._listed_frontier()}
        if self._terminal_reason(bid, tick) or not tick < bid["expires_tick"] <= tick+30:
            return {"ok": False, "reason": "private share lot, quantity, issuer or expiry is unavailable"}
        if self.authority(lot["estate_id"], actor) is not None:
            return {"ok": False, "reason": "share buyer cannot represent the selling estate"}
        if bid["currency_code"] != lot["currency_code"] or not self._funded(bid):
            return {"ok": False, "reason": "private share bid needs actual same-currency buyer funds"}
        with self.store.savepoint("estate_unlisted_bid"):
            event = self.store.log_event(tick, "estate_unlisted_bid_placed", self._bid_payload(bid),
                phase="EXECUTION", subject_type="agent", subject_id=actor)
            identifier = self.store.insert("estate_unlisted_bids", **bid,
                buyer_age=person["age"], created_tick=tick, event_id=event)
        return {"ok": True, "bid_id": identifier}

    def withdraw(self, tick, actor, bid_id):
        bid = self.store.query_one("SELECT * FROM estate_unlisted_bids WHERE id=?", (bid_id,))
        if not self.enabled or not self._available(bid, tick) or bid["buyer_agent_id"] != actor:
            return {"ok": False, "reason": "only the buyer can withdraw a current private share bid"}
        with self.store.savepoint("estate_unlisted_withdrawal"):
            self._end(tick, bid, "withdrawn", "EXECUTION")
        return {"ok": True, "bid_id": bid_id}

    def acceptance_error(self, tick, actor, bid):
        if not self.enabled or not self._available(bid, tick):
            return "private share bid is no longer available"
        lot = self._lot(bid["lot_id"])
        if actor == bid["buyer_agent_id"] or self.authority(lot["estate_id"], bid["buyer_agent_id"]) is not None:
            return "share buyer cannot represent the selling estate"
        if self.authority(lot["estate_id"], actor) is None:
            return "private share sale requires current estate representative authority"
        held = self.e.exchange.shares_held(lot["firm_id"], "agent", lot["deceased_agent_id"])
        reserved = self.store.scalar("SELECT COALESCE(SUM(qty_remaining),0) FROM orders WHERE agent_id=? AND firm_id=? "
            "AND side='sell' AND status IN ('open','partial')", (lot["deceased_agent_id"], lot["firm_id"]))
        if held-reserved < bid["qty"]:
            return "private share sale exceeds uncommitted nominee holdings"
        if bid["currency_code"] != lot["currency_code"] or not self._funded(bid):
            return "private share buyer no longer has the required same-currency funds"
        return None

    def accept(self, tick, actor, bid_id):
        bid = self.store.query_one("SELECT * FROM estate_unlisted_bids WHERE id=?", (bid_id,))
        reason = self.acceptance_error(tick, actor, bid)
        if reason:
            return {"ok": False, "reason": reason}
        lot = self._lot(bid["lot_id"])
        proof = self.capture_authority(lot["estate_id"], actor)
        with self.store.savepoint("estate_unlisted_settlement"):
            with self.e.estate_cases._batch():
                account = self.e.estate_cases._wallet(lot["deceased_agent_id"], bid["currency_code"])
                transaction = self.e.ledger.transfer(tick, bid["buyer_account_id"], account, bid["amount_cents"],
                    kind="estate_unlisted_sale", memo=f"private share bid {bid_id}")
                self.e.exchange._adjust_shares(lot["firm_id"], "agent", lot["deceased_agent_id"], -bid["qty"])
                self.e.exchange._adjust_shares(lot["firm_id"], "agent", bid["buyer_agent_id"], bid["qty"])
                movement = self.store.insert("share_movements", tick=tick, firm_id=lot["firm_id"],
                    from_holder_type="agent", from_holder_id=lot["deceased_agent_id"], to_holder_type="agent",
                    to_holder_id=bid["buyer_agent_id"], qty=bid["qty"], movement_type="estate_unlisted_sale",
                    reference_type="estate_unlisted_bid", reference_id=bid_id,
                    amount_cents=bid["amount_cents"], transaction_id=transaction)
                payload = dict(bid_id=bid_id, lot_id=lot["id"], actor_id=actor, buyer_agent_id=bid["buyer_agent_id"],
                    firm_id=lot["firm_id"], qty=bid["qty"], amount_cents=bid["amount_cents"],
                    currency_code=bid["currency_code"], transaction_id=transaction, movement_id=movement)
                event = self.store.log_event(tick, "estate_unlisted_sold", payload,
                    phase="EXECUTION", subject_type="agent", subject_id=actor)
                sale = self.store.insert("estate_unlisted_sales", bid_id=bid_id, lot_id=lot["id"], tick=tick,
                    qty=bid["qty"], actor_id=actor, account_id=account, transaction_id=transaction,
                    movement_id=movement, listed_sale_frontier=self._listed_frontier(),
                    authority_json=json.dumps(proof, sort_keys=True, separators=(",", ":")), event_id=event)
                self._end(tick, bid, "accepted", "EXECUTION")
            self.e.business_control.refresh_custody(tick)
        return {"ok": True, "bid_id": bid_id, "sale_id": sale, "transaction_id": transaction, "movement_id": movement}

    def reconcile(self, tick):
        if not self.enabled:
            return
        with self.store.savepoint("estate_unlisted_bid_endings"):
            for bid in self.store.query("SELECT b.* FROM estate_unlisted_bids b WHERE b.created_tick<=? AND NOT EXISTS "
                    "(SELECT 1 FROM estate_unlisted_bid_ends e WHERE e.bid_id=b.id) ORDER BY b.id", (tick,)):
                reason = self._terminal_reason(bid, tick)
                if reason:
                    self._end(tick, bid, reason)

    def context_for(self, actor, tick):
        result = {"policy": self.POLICY, "represented_lots": [], "available_lots": [],
                  "own_bids": [], "selected_bid": None, "eligible_actions": []}
        person = self._adult(actor)
        if not self.enabled or person is None:
            return result
        for row in self.store.query("SELECT l.*,f.name,f.region_id,f.currency_code FROM estate_security_lots l "
                "JOIN firms f ON f.id=l.firm_id WHERE l.started_tick<=? AND f.status='private' AND NOT EXISTS "
                "(SELECT 1 FROM estate_security_releases r WHERE r.lot_id=l.id) ORDER BY l.id", (tick,)):
            qty = self.e.estate_securities.remaining(row)
            if qty <= 0:
                continue
            item = dict(lot_id=row["id"], firm_id=row["firm_id"], firm_name=row["name"], qty=qty, currency_code=row["currency_code"])
            if self.authority(row["estate_id"], actor) is not None:
                offers = []
                for bid in self.store.query("SELECT * FROM estate_unlisted_bids WHERE lot_id=? AND created_tick<=? "
                        "ORDER BY amount_cents DESC,id", (row["id"], tick)):
                    if not self._available(bid, tick):
                        continue
                    error = self.acceptance_error(tick, actor, bid)
                    terms = {key: bid[key] for key in ("id", "buyer_agent_id", "qty", "amount_cents", "currency_code", "expires_tick")}
                    if len(offers) < 5:
                        offers.append(dict(terms, blocked_reason=error))
                    if error is None and not result["eligible_actions"]:
                        result["eligible_actions"] = [{"type": "accept_estate_unlisted_bid", "bid_id": bid["id"]}]
                        result["selected_bid"] = dict(item, estate_id=row["estate_id"], bid=terms)
                if len(result["represented_lots"]) < 5:
                    result["represented_lots"].append(dict(item, estate_id=row["estate_id"], bids=offers))
            elif len(result["available_lots"]) < 5 and person["region_id"] == row["region_id"]:
                wallets = [dict(w) for w in self.store.query("SELECT id,balance_cents FROM accounts WHERE owner_type='agent' "
                    "AND owner_id=? AND kind IN ('checking','savings','fx') AND currency_code=? AND balance_cents>0 ORDER BY id LIMIT 5",
                    (actor, row["currency_code"]))]
                if wallets and self.representatives(row["estate_id"]):
                    result["available_lots"].append(dict(item, buyer_wallets=wallets, latest_expiry_tick=tick+30))
        for bid in self.store.query("SELECT * FROM estate_unlisted_bids WHERE buyer_agent_id=? AND created_tick<=? ORDER BY id DESC", (actor, tick)):
            if self._available(bid, tick):
                result["own_bids"].append({key: bid[key] for key in ("id", "lot_id", "qty", "amount_cents", "currency_code", "expires_tick")}
                    | {"funded_now": self._funded(bid), "withdraw_action": {"type": "withdraw_estate_unlisted_bid", "bid_id": bid["id"]}})
            if len(result["own_bids"]) == 5:
                break
        return result

    def check_sale(self, sale):
        bid = self.store.query_one("SELECT * FROM estate_unlisted_bids WHERE id=?", (sale["bid_id"],))
        lot = self._lot(sale["lot_id"])
        end = self.store.query_one("SELECT * FROM estate_unlisted_bid_ends WHERE bid_id=?", (sale["bid_id"],))
        release = self.store.query_one("SELECT * FROM estate_security_releases WHERE lot_id=?", (sale["lot_id"],))
        if (bid is None or lot is None or bid["lot_id"] != lot["id"] or sale["qty"] != bid["qty"]
                or not bid["created_tick"] <= sale["tick"] < bid["expires_tick"] or sale["actor_id"] == bid["buyer_agent_id"]
                or sale["listed_sale_frontier"] < bid["listed_sale_frontier"]
                or sale["qty"] != self._quantity_at(lot, sale["listed_sale_frontier"], sale["tick"])
                or end is None or end["reason"] != "accepted" or end["tick"] != sale["tick"] or end["issuer_status"] != "private"
                or release is None or release["qty"] != 0 or release["tick"] != sale["tick"]):
            raise EstateError("private share sale lacks its exact retained quantity or disposition")
        source = self.store.query_one("SELECT * FROM accounts WHERE id=?", (bid["buyer_account_id"],))
        target = self.store.query_one("SELECT * FROM accounts WHERE id=?", (sale["account_id"],))
        transaction = self.store.query_one("SELECT * FROM transactions WHERE id=?", (sale["transaction_id"],))
        if (source is None or target is None or source["owner_type"] != "agent" or source["owner_id"] != bid["buyer_agent_id"]
                or target["owner_type"] != "agent" or target["owner_id"] != lot["deceased_agent_id"]
                or source["kind"] not in self.e.estate_cases.CASH_KINDS or target["kind"] not in self.e.estate_cases.CASH_KINDS
                or source["currency_code"] != bid["currency_code"] or target["currency_code"] != bid["currency_code"]
                or lot["currency_code"] != bid["currency_code"] or transaction is None or transaction["kind"] != "estate_unlisted_sale"):
            raise EstateError("private share sale has the wrong funded wallets or payment")
        expected = self.e.estate_cases._transfer_legs(source, target, bid["amount_cents"])
        before = self.store.scalar("SELECT COALESCE(SUM(delta_cents),0) FROM ledger_entries WHERE account_id=? AND txn_id<?",
                                  (source["id"], transaction["id"]))
        if (before < bid["amount_cents"] or self.e.cash_estates._transaction_legs(transaction["id"], sale["tick"], bid["currency_code"]) != expected
                or not self.store.scalar("SELECT id FROM estate_receipts WHERE estate_id=? AND source_account_id=? AND origin_transaction_id=?",
                    (lot["estate_id"], target["id"], transaction["id"]))):
            raise EstateError("private share sale lacks its actual funded estate receipt")
        movement = self.store.query_one("SELECT * FROM share_movements WHERE id=?", (sale["movement_id"],))
        expected_movement = dict(tick=sale["tick"], firm_id=lot["firm_id"], from_holder_type="agent", from_holder_id=lot["deceased_agent_id"],
            to_holder_type="agent", to_holder_id=bid["buyer_agent_id"], qty=bid["qty"], movement_type="estate_unlisted_sale",
            reference_type="estate_unlisted_bid", reference_id=bid["id"], price_cents=None,
            amount_cents=bid["amount_cents"], transaction_id=transaction["id"])
        if movement is None or any(movement[key] != value for key, value in expected_movement.items()):
            raise EstateError("private share sale lacks its exact paid share movement")
        proof = json.loads(sale["authority_json"])
        if proof["estate_id"] != lot["estate_id"] or proof["actor_id"] != sale["actor_id"]:
            raise EstateError("private share sale has the wrong representative")
        self.check_authority_history(proof, sale["tick"])
        if self.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=? AND id<=?",
                             (bid["buyer_agent_id"], proof["estate_frontier_id"])):
            raise EstateError("private share buyer was already deceased")
        event = self.store.query_one("SELECT * FROM events WHERE id=?", (sale["event_id"],))
        payload = dict(bid_id=bid["id"], lot_id=lot["id"], actor_id=sale["actor_id"], buyer_agent_id=bid["buyer_agent_id"], firm_id=lot["firm_id"],
            qty=bid["qty"], amount_cents=bid["amount_cents"], currency_code=bid["currency_code"], transaction_id=transaction["id"], movement_id=movement["id"])
        if event is None or event["kind"] != "estate_unlisted_sold" or event["tick"] != sale["tick"] or json.loads(event["payload_json"]) != payload:
            raise EstateError("private share sale event disagrees with its settlement")

    def check_invariants(self):
        if not self.enabled:
            return
        for bid in self.store.query("SELECT * FROM estate_unlisted_bids ORDER BY id"):
            lot = self._lot(bid["lot_id"])
            wallet = self.store.query_one("SELECT * FROM accounts WHERE id=?", (bid["buyer_account_id"],))
            event = self.store.query_one("SELECT * FROM events WHERE id=?", (bid["event_id"],))
            if (lot is None or lot["started_tick"] > bid["created_tick"] or wallet is None
                    or wallet["owner_type"] != "agent" or wallet["owner_id"] != bid["buyer_agent_id"]
                    or wallet["kind"] not in self.e.estate_cases.CASH_KINDS or wallet["currency_code"] != bid["currency_code"]
                    or lot["currency_code"] != bid["currency_code"] or bid["qty"] != self._quantity_at(lot, bid["listed_sale_frontier"], bid["created_tick"])
                    or event is None or event["kind"] != "estate_unlisted_bid_placed" or event["tick"] != bid["created_tick"]
                    or event["subject_type"] != "agent" or event["subject_id"] != bid["buyer_agent_id"]
                    or json.loads(event["payload_json"]) != self._bid_payload(bid)):
                raise EstateError("private share bid lacks its custody, buyer or recorded terms")
        for end in self.store.query("SELECT * FROM estate_unlisted_bid_ends ORDER BY id"):
            bid = self.store.query_one("SELECT * FROM estate_unlisted_bids WHERE id=?", (end["bid_id"],))
            event = self.store.query_one("SELECT * FROM events WHERE id=?", (end["event_id"],))
            payload = dict(bid_id=end["bid_id"], reason=end["reason"], issuer_status=end["issuer_status"], listed_sale_frontier=end["listed_sale_frontier"])
            if (bid is None or end["tick"] < bid["created_tick"] or end["listed_sale_frontier"] < bid["listed_sale_frontier"]
                    or event is None or event["kind"] != "estate_unlisted_bid_ended" or event["tick"] != end["tick"]
                    or event["subject_type"] != "agent" or event["subject_id"] != bid["buyer_agent_id"] or json.loads(event["payload_json"]) != payload):
                raise EstateError("private share bid ending lacks its recorded evidence")
            qty = self._quantity_at(self._lot(bid["lot_id"]), end["listed_sale_frontier"], end["tick"])
            if end["reason"] == "accepted" and not self.store.scalar("SELECT id FROM estate_unlisted_sales WHERE bid_id=?", (bid["id"],)):
                raise EstateError("accepted private share bid has no sale")
            if end["reason"] == "expired" and end["tick"] < bid["expires_tick"]:
                raise EstateError("private share bid expired before its deadline")
            if end["reason"] == "buyer_unavailable" and not self.buyer_unavailable_at(
                    bid["buyer_agent_id"], end["tick"], end["event_id"]):
                raise EstateError("private share bid lacks its buyer unavailability")
            if end["reason"] == "lot_quantity_changed" and qty == bid["qty"]:
                raise EstateError("private share bid lacks its changed lot quantity")
            if end["reason"] == "lot_disposed" and not self.store.scalar(
                    "SELECT id FROM estate_security_releases WHERE lot_id=? AND tick<=?", (bid["lot_id"], end["tick"])):
                raise EstateError("private share bid lacks its lot disposition")
        for sale in self.store.query("SELECT * FROM estate_unlisted_sales ORDER BY id"):
            self.check_sale(sale)
        if self.store.scalar("SELECT m.id FROM share_movements m WHERE m.movement_type='estate_unlisted_sale' AND NOT EXISTS "
                "(SELECT 1 FROM estate_unlisted_sales s WHERE s.movement_id=m.id) LIMIT 1"):
            raise EstateError("private estate share movement lacks its sale")

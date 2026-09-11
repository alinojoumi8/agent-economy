"""Explicit bids and atomic cash/title settlement for retained personal property."""
from __future__ import annotations

import json

from .estate_assets import EstateAssetCustody
from .estates import EstateError


class EstatePropertySales(EstateAssetCustody):
    POLICY = "funded_whole_interest_bids_v1"

    def _custody(self, custody):
        return self.store.query_one("SELECT c.*,l.project_id,l.agent_id,l.ended_tick,p.status,p.cancelled_tick,"
            "a.currency_code FROM estate_project_custody c JOIN project_interest_lots l ON l.id=c.interest_lot_id "
            "JOIN construction_projects p ON p.id=l.project_id JOIN accounts a ON a.id=p.escrow_account_id WHERE c.id=?", (custody,))

    def _end(self, tick, bid, reason, phase="NIGHT_CLOSE"):
        event = self.store.log_event(tick, "estate_property_bid_ended", {"bid_id": bid["id"], "reason": reason},
            phase=phase, subject_type="agent", subject_id=bid["buyer_agent_id"])
        self.store.insert("estate_property_bid_ends", bid_id=bid["id"], tick=tick, reason=reason, event_id=event)

    def _terminal_reason(self, bid, tick):
        if tick >= bid["expires_tick"]:
            return "expired"
        if self._adult(bid["buyer_agent_id"]) is None:
            return "buyer_unavailable"
        custody = self._custody(bid["custody_id"])
        if custody is None or custody["ended_tick"] is not None or self.store.scalar(
                "SELECT id FROM estate_project_releases WHERE custody_id=?", (bid["custody_id"],)):
            return "custody_disposed"
        if custody["status"] == "cancelled":
            return "project_cancelled"
        return None

    def _available(self, bid, tick):
        return bool(bid is not None and bid["created_tick"] <= tick and not self.store.scalar(
            "SELECT id FROM estate_property_bid_ends WHERE bid_id=?", (bid["id"],)) and self._terminal_reason(bid, tick) is None)

    def place_bid(self, tick, actor, action):
        if not self.enabled:
            return {"ok": False, "reason": "estate property sales require semantics 20"}
        previous = self.store.query_one("SELECT * FROM estate_property_bids WHERE buyer_agent_id=? AND request_key=?",
            (actor, action["request_key"]))
        terms = ("custody_id", "buyer_account_id", "amount_cents", "currency_code", "expires_tick")
        if previous is not None:
            if tick < previous["created_tick"] or any(previous[key] != action[key] for key in terms):
                return {"ok": False, "reason": "property bid request key has different terms or time"}
            return {"ok": True, "bid_id": previous["id"], "existing": True}
        person, custody = self._adult(actor), self._custody(action["custody_id"])
        if person is None or custody is None or custody["opened_tick"] > tick:
            return {"ok": False, "reason": "property bid requires an adult buyer and recorded custody"}
        bid = {**{key: action[key] for key in terms}, "buyer_agent_id": actor}
        if self._terminal_reason(bid, tick) or not tick < action["expires_tick"] <= tick+30:
            return {"ok": False, "reason": "property custody or bid expiry is unavailable"}
        if self.authority(custody["estate_id"], actor) is not None:
            return {"ok": False, "reason": "property buyer cannot represent the selling estate"}
        if action["currency_code"] != custody["currency_code"] or not self._funded(bid):
            return {"ok": False, "reason": "property bid needs actual same-currency buyer funds"}
        with self.store.savepoint("estate_property_bid"):
            event = self.store.log_event(tick, "estate_property_bid_placed", dict(bid, request_key=action["request_key"]),
                phase="EXECUTION", subject_type="agent", subject_id=actor)
            identifier = self.store.insert("estate_property_bids", **bid, buyer_age=person["age"], created_tick=tick,
                request_key=action["request_key"], event_id=event)
        return {"ok": True, "bid_id": identifier}

    def withdraw(self, tick, actor, bid_id):
        bid = self.store.query_one("SELECT * FROM estate_property_bids WHERE id=?", (bid_id,))
        if not self.enabled or not self._available(bid, tick) or bid["buyer_agent_id"] != actor:
            return {"ok": False, "reason": "only the buyer can withdraw a current property bid"}
        with self.store.savepoint("estate_property_bid_withdrawal"):
            self._end(tick, bid, "withdrawn", "EXECUTION")
        return {"ok": True, "bid_id": bid_id}

    def acceptance_error(self, tick, actor, bid):
        if not self.enabled or not self._available(bid, tick):
            return "property bid is no longer available"
        custody = self._custody(bid["custody_id"])
        if actor == bid["buyer_agent_id"] or self.authority(custody["estate_id"], bid["buyer_agent_id"]) is not None:
            return "property buyer cannot represent the selling estate"
        if self.authority(custody["estate_id"], actor) is None:
            return "property sale requires current estate representative authority"
        if bid["currency_code"] != custody["currency_code"] or not self._funded(bid):
            return "property buyer no longer has the required same-currency funds"
        return None

    def accept(self, tick, actor, bid_id):
        bid = self.store.query_one("SELECT * FROM estate_property_bids WHERE id=?", (bid_id,))
        reason = self.acceptance_error(tick, actor, bid)
        if reason:
            return {"ok": False, "reason": reason}
        custody = self._custody(bid["custody_id"])
        parent = self.store.query_one("SELECT * FROM project_interest_lots WHERE id=?", (custody["interest_lot_id"],))
        proof = self.capture_authority(custody["estate_id"], actor)
        with self.e.estate_cases._batch():
            account = self.e.estate_cases._wallet(custody["agent_id"], bid["currency_code"])
            transaction = self.e.ledger.transfer(tick, bid["buyer_account_id"], account,
                bid["amount_cents"], kind="estate_property_sale", memo=f"estate property bid {bid_id}")
            self.store.update("project_interest_lots", parent["id"], ended_tick=tick)
            successor = self.store.insert("project_interest_lots", project_id=parent["project_id"],
                agent_id=bid["buyer_agent_id"], numerator=parent["numerator"], denominator=parent["denominator"],
                started_tick=tick, prior_lot_id=parent["id"], estate_id=custody["estate_id"])
            self.store.insert("estate_project_releases", custody_id=custody["id"], tick=tick,
                disposition="sold", **self._frontier())
            event = self.store.log_event(tick, "estate_property_sold", {"bid_id": bid_id, "custody_id": custody["id"],
                "actor_id": actor, "buyer_agent_id": bid["buyer_agent_id"], "successor_lot_id": successor,
                "transaction_id": transaction, "amount_cents": bid["amount_cents"], "currency_code": bid["currency_code"]},
                phase="EXECUTION", subject_type="agent", subject_id=actor)
            sale = self.store.insert("estate_property_sales", bid_id=bid_id, custody_id=custody["id"], tick=tick,
                actor_id=actor, account_id=account, successor_lot_id=successor, transaction_id=transaction,
                authority_json=json.dumps(proof, sort_keys=True, separators=(",", ":")), event_id=event)
            self._end(tick, bid, "accepted", "EXECUTION")
            self.e.project_rights.refresh(tick)
        return {"ok": True, "bid_id": bid_id, "sale_id": sale, "transaction_id": transaction, "successor_lot_id": successor}

    def reconcile(self, tick):
        if not self.enabled:
            return
        for bid in self.store.query("SELECT b.* FROM estate_property_bids b WHERE b.created_tick<=? AND NOT EXISTS "
                "(SELECT 1 FROM estate_property_bid_ends e WHERE e.bid_id=b.id) ORDER BY b.id", (tick,)):
            reason = self._terminal_reason(bid, tick)
            if reason:
                self._end(tick, bid, reason)

    def check_sale(self, sale):
        bid = self.store.query_one("SELECT * FROM estate_property_bids WHERE id=?", (sale["bid_id"],))
        custody = self._custody(sale["custody_id"])
        child = self.store.query_one("SELECT * FROM project_interest_lots WHERE id=?", (sale["successor_lot_id"],))
        parent = self.store.query_one("SELECT * FROM project_interest_lots WHERE id=?", (custody["interest_lot_id"],)) if custody else None
        end = self.store.query_one("SELECT * FROM estate_property_bid_ends WHERE bid_id=?", (sale["bid_id"],))
        release = self.store.query_one("SELECT * FROM estate_project_releases WHERE custody_id=?", (sale["custody_id"],))
        if (bid is None or custody is None or child is None or parent is None or bid["custody_id"] != custody["id"]
                or not bid["created_tick"] <= sale["tick"] < bid["expires_tick"] or bid["buyer_agent_id"] == sale["actor_id"]
                or end is None or end["reason"] != "accepted" or end["tick"] != sale["tick"]
                or release is None or release["disposition"] != "sold" or release["tick"] != sale["tick"]
                or child["prior_lot_id"] != parent["id"] or parent["ended_tick"] != sale["tick"]
                or child["started_tick"] != sale["tick"] or child["estate_id"] != custody["estate_id"]
                or child["project_id"] != parent["project_id"] or child["agent_id"] != bid["buyer_agent_id"]
                or (child["numerator"], child["denominator"]) != (parent["numerator"], parent["denominator"])):
            raise EstateError("estate property sale lacks exact funded title/disposition evidence")
        account = self.store.query_one("SELECT * FROM accounts WHERE id=?", (sale["account_id"],))
        if (account is None or account["owner_type"] != "agent" or account["owner_id"] != parent["agent_id"]
                or account["kind"] not in self.e.estate_cases.CASH_KINDS or account["currency_code"] != bid["currency_code"]
                or custody["currency_code"] != bid["currency_code"]):
            raise EstateError("estate property sale has the wrong nominee wallet or currency")
        transaction = self.store.query_one("SELECT * FROM transactions WHERE id=?", (sale["transaction_id"],))
        legs = {row["account_id"]: row["amount"] for row in self.store.query("SELECT account_id,SUM(delta_cents) amount "
            "FROM ledger_entries WHERE txn_id=? GROUP BY account_id", (sale["transaction_id"],))}
        expected_legs = {bid["buyer_account_id"]: -bid["amount_cents"], sale["account_id"]: bid["amount_cents"]}
        buyer_wallet = self.store.query_one("SELECT * FROM accounts WHERE id=?", (bid["buyer_account_id"],))
        if (buyer_wallet["bank_id"] and account["bank_id"] and buyer_wallet["bank_id"] != account["bank_id"]
                and buyer_wallet["kind"] in ("checking", "savings") and account["kind"] in ("checking", "savings")):
            source_reserve = self.e.ledger._bank_reserve(buyer_wallet["bank_id"])
            target_reserve = self.e.ledger._bank_reserve(account["bank_id"])
            if source_reserve and target_reserve:
                expected_legs[source_reserve] = -bid["amount_cents"]
                expected_legs[target_reserve] = bid["amount_cents"]
        before = self.store.scalar("SELECT COALESCE(SUM(delta_cents),0) FROM ledger_entries WHERE account_id=? AND txn_id<?",
                                  (bid["buyer_account_id"], sale["transaction_id"]))
        if (transaction is None or transaction["tick"] != sale["tick"] or transaction["kind"] != "estate_property_sale"
                or legs != expected_legs
                or before < bid["amount_cents"] or not self.store.scalar("SELECT id FROM estate_receipts WHERE estate_id=? "
                    "AND source_account_id=? AND origin_transaction_id=?", (custody["estate_id"], sale["account_id"], sale["transaction_id"]))):
            raise EstateError("estate property sale lacks actual funded estate receipt")
        proof = json.loads(sale["authority_json"])
        if proof["estate_id"] != custody["estate_id"] or proof["actor_id"] != sale["actor_id"]:
            raise EstateError("estate property sale has the wrong representative")
        self.check_authority_history(proof, sale["tick"])
        if self.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=? AND id<=?",
                             (bid["buyer_agent_id"], proof["estate_frontier_id"])):
            raise EstateError("estate property buyer was already deceased")
        event = self.store.query_one("SELECT * FROM events WHERE id=?", (sale["event_id"],))
        expected = dict(bid_id=bid["id"], custody_id=custody["id"], actor_id=sale["actor_id"],
            buyer_agent_id=bid["buyer_agent_id"], successor_lot_id=child["id"], transaction_id=sale["transaction_id"],
            amount_cents=bid["amount_cents"], currency_code=bid["currency_code"])
        if event is None or event["kind"] != "estate_property_sold" or event["tick"] != sale["tick"] or json.loads(event["payload_json"]) != expected:
            raise EstateError("estate property sale event does not match its settlement")

    def context_for(self, actor, tick):
        result = {"policy": self.POLICY, "represented_interests": [], "available_interests": [],
                  "own_bids": [], "selected_bid": None, "eligible_actions": []}
        person = self._adult(actor)
        if not self.enabled or person is None:
            return result
        for row in self.store.query("SELECT c.*,l.project_id,l.numerator,l.denominator,p.status,p.region_id,a.currency_code "
                "FROM estate_project_custody c JOIN project_interest_lots l ON l.id=c.interest_lot_id "
                "JOIN construction_projects p ON p.id=l.project_id JOIN accounts a ON a.id=p.escrow_account_id "
                "WHERE c.opened_tick<=? AND l.ended_tick IS NULL AND p.status<>'cancelled' AND NOT EXISTS "
                "(SELECT 1 FROM estate_project_releases r WHERE r.custody_id=c.id) ORDER BY c.id", (tick,)):
            item = {key: row[key] for key in ("project_id", "numerator", "denominator", "status", "currency_code")}
            item["custody_id"] = row["id"]
            if self.authority(row["estate_id"], actor) is not None:
                offers = []
                for bid in self.store.query("SELECT * FROM estate_property_bids WHERE custody_id=? AND created_tick<=? "
                        "ORDER BY amount_cents DESC,id", (row["id"], tick)):
                    if self._available(bid, tick):
                        error = self.acceptance_error(tick, actor, bid)
                        if len(offers) < 5:
                            offers.append({key: bid[key] for key in ("id", "buyer_agent_id", "amount_cents", "currency_code", "expires_tick")}
                                | {"blocked_reason": error})
                        if error is None and not result["eligible_actions"]:
                            result["eligible_actions"] = [{"type": "accept_estate_property_bid", "bid_id": bid["id"]}]
                            result["selected_bid"] = dict(item, estate_id=row["estate_id"], bid={
                                key: bid[key] for key in ("id", "buyer_agent_id", "amount_cents", "currency_code", "expires_tick")})
                if len(result["represented_interests"]) < 5:
                    result["represented_interests"].append(dict(item, estate_id=row["estate_id"], bids=offers))
            elif len(result["available_interests"]) < 5 and row["region_id"] == person["region_id"]:
                wallets = [dict(wallet) for wallet in self.store.query("SELECT id,balance_cents FROM accounts WHERE owner_type='agent' "
                    "AND owner_id=? AND kind IN ('checking','savings','fx') AND currency_code=? AND balance_cents>0 ORDER BY id LIMIT 5",
                    (actor, row["currency_code"]))]
                if wallets and self.representatives(row["estate_id"]):
                    result["available_interests"].append(dict(item, buyer_wallets=wallets, latest_expiry_tick=tick+30))
        for bid in self.store.query("SELECT * FROM estate_property_bids WHERE buyer_agent_id=? AND created_tick<=? ORDER BY id DESC", (actor, tick)):
            if self._available(bid, tick):
                result["own_bids"].append({key: bid[key] for key in ("id", "custody_id", "amount_cents", "currency_code", "expires_tick")}
                    | {"funded_now": self._funded(bid), "withdraw_action": {"type": "withdraw_estate_property_bid", "bid_id": bid["id"]}})
            if len(result["own_bids"]) == 5:
                break
        return result

    def check_invariants(self):
        if not self.enabled:
            return
        for bid in self.store.query("SELECT * FROM estate_property_bids ORDER BY id"):
            custody = self._custody(bid["custody_id"])
            wallet = self.store.query_one("SELECT * FROM accounts WHERE id=?", (bid["buyer_account_id"],))
            event = self.store.query_one("SELECT * FROM events WHERE id=?", (bid["event_id"],))
            if (custody is None or custody["opened_tick"] > bid["created_tick"] or wallet is None
                    or wallet["owner_type"] != "agent" or wallet["owner_id"] != bid["buyer_agent_id"]
                    or wallet["kind"] not in self.e.estate_cases.CASH_KINDS or wallet["currency_code"] != bid["currency_code"]
                    or custody["currency_code"] != bid["currency_code"] or event is None
                    or event["kind"] != "estate_property_bid_placed" or event["tick"] != bid["created_tick"]):
                raise EstateError("estate property bid has invalid custody, buyer or evidence")
            expected = {key: bid[key] for key in ("custody_id", "buyer_account_id", "amount_cents", "currency_code", "expires_tick", "buyer_agent_id", "request_key")}
            if json.loads(event["payload_json"]) != expected:
                raise EstateError("estate property bid event changed its terms")
        for end in self.store.query("SELECT * FROM estate_property_bid_ends ORDER BY id"):
            bid = self.store.query_one("SELECT * FROM estate_property_bids WHERE id=?", (end["bid_id"],))
            event = self.store.query_one("SELECT * FROM events WHERE id=?", (end["event_id"],))
            if (bid is None or end["tick"] < bid["created_tick"] or event is None or event["tick"] != end["tick"]
                    or event["kind"] != "estate_property_bid_ended" or json.loads(event["payload_json"]) != {"bid_id": end["bid_id"], "reason": end["reason"]}):
                raise EstateError("estate property bid ending lacks its recorded evidence")
            if end["reason"] == "accepted" and not self.store.scalar("SELECT id FROM estate_property_sales WHERE bid_id=?", (bid["id"],)):
                raise EstateError("accepted property bid has no sale")
            custody = self._custody(bid["custody_id"])
            if end["reason"] == "expired" and end["tick"] < bid["expires_tick"]:
                raise EstateError("estate property bid expired before its deadline")
            if end["reason"] == "buyer_unavailable" and not self.buyer_unavailable_at(
                    bid["buyer_agent_id"], end["tick"], end["event_id"]):
                raise EstateError("estate property bid lacks its buyer unavailability")
            if end["reason"] == "custody_disposed" and not self.store.scalar(
                    "SELECT id FROM estate_project_releases WHERE custody_id=? AND tick<=?", (bid["custody_id"], end["tick"])):
                raise EstateError("estate property bid lacks its custody disposition")
            if end["reason"] == "project_cancelled" and (custody["cancelled_tick"] is None or custody["cancelled_tick"] > end["tick"]):
                raise EstateError("estate property bid lacks its project cancellation")
            if event["subject_type"] != "agent" or event["subject_id"] != bid["buyer_agent_id"]:
                raise EstateError("estate property bid ending has the wrong buyer")
        for sale in self.store.query("SELECT * FROM estate_property_sales ORDER BY id"):
            self.check_sale(sale)

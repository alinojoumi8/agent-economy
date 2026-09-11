"""Shared creditor and representative rules for retained estate assets."""
from __future__ import annotations

from fractions import Fraction
import json

from .estates import EstateError


def residual_people_at(store, estate_id, tick=None):
    """Resolve recorded residual paths at a selected day without future deaths."""
    people, pending = set(), [(estate_id, frozenset())]
    while pending:
        case_id, seen = pending.pop(0)
        if case_id in seen:
            raise EstateError("cyclic estate beneficial interests")
        for row in store.query("SELECT a.* FROM estate_beneficiaries b JOIN agents a ON a.id=b.agent_id "
                               "WHERE b.estate_id=? ORDER BY b.id", (case_id,)):
            clause = "" if tick is None else " AND opened_tick<=?"
            params = (row["id"],) if tick is None else (row["id"], tick)
            child = store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?" + clause, params)
            if child is not None:
                pending.append((child, seen | {case_id}))
            elif tick is None and not row["alive"]:
                raise EstateError("deceased beneficiary lacks an estate")
            else:
                people.add(row["id"])
    return people


class EstateAssetCustody:
    def beneficial_people(self, estate_id):
        """Living residual beneficiaries, including minors without a guardian."""
        return residual_people_at(self.store, estate_id)

    def check_release_frontier(self, tick, estate_id, currency, frontier):
        opening_count = self.store.scalar("SELECT claim_count FROM estate_cases WHERE id=?", (estate_id,))
        opening_claim = self.store.scalar("SELECT COALESCE(MAX(id),0) FROM "
            "(SELECT id FROM estate_claims WHERE estate_id=? ORDER BY id LIMIT ?)", (estate_id, opening_count))
        for key, table, tick_field in (
                ("transaction_frontier", "transactions", "tick"), ("receipt_frontier", "estate_receipts", "tick"),
                ("claim_frontier", "estate_claims", "registered_tick"), ("claim_release_frontier", "estate_claim_releases", "tick"),
                ("reserve_frontier", "estate_legal_reserves", "registered_tick"), ("resolution_frontier", "estate_reserve_resolutions", "tick")):
            recorded_tick = self.store.scalar(f"SELECT {tick_field} FROM {table} WHERE id=?", (frontier[key],))
            if frontier[key] and (recorded_tick is None or recorded_tick > tick):
                raise EstateError("estate asset release has an invalid settlement frontier")
        if frontier["claim_frontier"] < opening_claim or self._unsettled(tick, estate_id, currency, frontier):
            raise EstateError("estate asset was released before creditor settlement")

    def __init__(self, economy):
        self.e = economy
        self.store = economy.store
        self.enabled = economy.estate_cases.enabled

    def _adult(self, actor):
        if self.e.engine_semantics_version >= 21 and self.store.scalar("SELECT alive FROM agents WHERE id=?", (actor,)):
            if not self.e.population.is_available(actor):
                return None
        return self.store.query_one("SELECT * FROM agents WHERE id=? AND alive=1 AND age>=18", (actor,))

    def buyer_unavailable_at(self, agent_id, tick, event_id):
        if self.e.engine_semantics_version >= 21:
            if not self.e.population.history.is_living_resident(agent_id, tick, event_frontier=event_id-1):
                return True
            # The atomic death transition closes bids after opening the estate
            # but before appending the final death event. Only an opening that
            # already existed at this bid's ending can support that ordering.
            return bool(self.store.scalar("SELECT c.id FROM estate_cases c JOIN events e ON e.id=c.completed_event_id "
                "WHERE c.deceased_agent_id=? AND c.opened_tick<=? AND e.id<? "
                "AND e.tick=c.opened_tick AND e.kind='estate_case_opened' AND e.phase='NIGHT_CLOSE' "
                "AND e.subject_type='agent' AND e.subject_id=c.deceased_agent_id "
                "AND json_extract(e.payload_json,'$.estate_id')=c.id "
                "AND json_extract(e.payload_json,'$.agent_id')=c.deceased_agent_id", (agent_id, tick, event_id)))
        return bool(self.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=? AND opened_tick<=?", (agent_id, tick)))

    def _funded(self, bid):
        account = self.store.query_one("SELECT * FROM accounts WHERE id=?", (bid["buyer_account_id"],))
        return bool(account is not None and account["owner_type"] == "agent" and account["owner_id"] == bid["buyer_agent_id"]
            and account["kind"] in self.e.estate_cases.CASH_KINDS and account["currency_code"] == bid["currency_code"]
            and account["balance_cents"] >= bid["amount_cents"])

    def needs_custody(self, tick, estate_id, currency):
        return self._unsettled(tick, estate_id, currency, self._frontier())

    def _frontier(self):
        return {name: self.store.scalar(f"SELECT COALESCE(MAX(id),0) FROM {table}") for name, table in (
            ("transaction_frontier", "transactions"), ("receipt_frontier", "estate_receipts"),
            ("claim_frontier", "estate_claims"), ("claim_release_frontier", "estate_claim_releases"),
            ("reserve_frontier", "estate_legal_reserves"), ("resolution_frontier", "estate_reserve_resolutions"))}

    def _unsettled(self, tick, estate_id, currency, frontier):
        case = self.store.query_one("SELECT * FROM estate_cases WHERE id=?", (estate_id,))
        if case is None:
            raise EstateError("asset custody needs a recorded estate")
        if self.store.scalar("SELECT a.id FROM accounts a LEFT JOIN ledger_entries le "
                "ON le.account_id=a.id AND le.txn_id<=? WHERE a.owner_type='agent' AND a.owner_id=? "
                "AND a.currency_code=? AND a.kind IN ('checking','savings','fx') "
                "GROUP BY a.id HAVING COALESCE(SUM(le.delta_cents),0)<0 LIMIT 1",
                (frontier["transaction_frontier"], case["deceased_agent_id"], currency)):
            return True
        reserves = self.store.query("SELECT r.* FROM estate_legal_reserves r WHERE r.estate_id=? "
            "AND r.currency_code=? AND r.id<=? AND r.registered_tick<=? AND NOT EXISTS "
            "(SELECT 1 FROM estate_reserve_resolutions s WHERE s.reserve_id=r.id AND s.id<=?) ORDER BY r.id",
            (estate_id, currency, frontier["reserve_frontier"], tick, frontier["resolution_frontier"]))
        claims = self.store.query("SELECT * FROM estate_claims WHERE estate_id=? AND currency_code=? "
                                  "AND id<=? AND registered_tick<=? ORDER BY id", (estate_id, currency, frontier["claim_frontier"], tick))
        for claim in claims:
            paid = self.store.scalar("SELECT COALESCE(SUM(amount_cents),0) FROM estate_disbursements "
                "WHERE claim_id=? AND receipt_id<=? AND transaction_id<=?",
                (claim["id"], frontier["receipt_frontier"], frontier["transaction_frontier"]))
            released = self.store.scalar("SELECT COALESCE(SUM(amount_cents),0) FROM estate_claim_releases "
                                         "WHERE claim_id=? AND id<=?", (claim["id"], frontier["claim_release_frontier"]))
            protected = (sum(self.store.scalar("SELECT COALESCE(SUM(protected_cents),0) FROM estate_reserve_obligations "
                "WHERE reserve_id=? AND obligation_id=?", (reserve["id"], claim["source_id"])) for reserve in reserves)
                if claim["kind"] == "contract_payment" else 0)
            if claim["principal_cents"] - paid - released > protected:
                return True
        return any(self.store.scalar("SELECT COALESCE(SUM(delta_cents),0) FROM ledger_entries "
            "WHERE account_id=? AND txn_id<=?", (reserve["escrow_account_id"], frontier["transaction_frontier"]))
            < reserve["reserve_limit_cents"] for reserve in reserves)

    def representatives(self, estate_id):
        private = self.beneficiary_representatives(estate_id)
        if private:
            return private
        public = self.e.estate_administration.proof(estate_id)
        return [public] if public is not None else []

    def beneficiary_representatives(self, estate_id):
        """Frozen beneficial paths; live adults or current guardians can administer."""
        result, pending = [], [(estate_id, [], Fraction(1), frozenset())]
        beneficial_weights = {}
        while pending:
            case_id, path, weight, seen = pending.pop(0)
            if case_id in seen:
                raise EstateError("cyclic estate beneficial interests")
            members = self.store.query("SELECT * FROM estate_beneficiaries WHERE estate_id=? ORDER BY id", (case_id,))
            denominator = sum(row["weight"] for row in members)
            for member in members:
                if member["agent_id"] is None:
                    continue
                person = self.store.query_one("SELECT * FROM agents WHERE id=?", (member["agent_id"],))
                if person is None:
                    raise EstateError("estate beneficiary identity is missing")
                route = [*path, member["id"]]
                part = weight * Fraction(member["weight"], denominator)
                if not person["alive"]:
                    child = self.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (person["id"],))
                    if child is None:
                        raise EstateError("deceased beneficiary lacks an estate")
                    pending.append((child, route, part, seen | {case_id}))
                    continue
                beneficial_weights[person["id"]] = beneficial_weights.get(person["id"], Fraction()) + part
                if person["age"] >= 18:
                    result.append(dict(actor_id=person["id"], beneficiary_id=person["id"], guardian_id=None,
                        actor_age=person["age"], beneficiary_age=person["age"], path=route, weight=part))
                else:
                    for guardian in self.store.query("SELECT g.id,a.id actor_id,a.age FROM guardianships g "
                            "JOIN agents a ON a.id=g.guardian_agent_id WHERE g.child_agent_id=? "
                            "AND g.ended_tick IS NULL AND a.alive=1 AND a.age>=18 ORDER BY a.id", (person["id"],)):
                        result.append(dict(actor_id=guardian["actor_id"], beneficiary_id=person["id"],
                            guardian_id=guardian["id"], actor_age=guardian["age"], beneficiary_age=person["age"],
                            path=route, weight=part))
        # A descendant can inherit through several branches. Rank their total
        # beneficial interest once, without multiplying it by their guardians.
        # Each authority still preserves its own exact recorded path and weight.
        if self.e.engine_semantics_version >= 21:
            result = [entry for entry in result if self.e.population.is_available(entry["actor_id"])]
        return sorted(result, key=lambda r: (r["guardian_id"] is not None,
            -beneficial_weights[r["beneficiary_id"]], r["beneficiary_id"], r["actor_id"], r["path"]))

    def authority(self, estate_id, actor_id):
        return next((row for row in self.representatives(estate_id) if row["actor_id"] == actor_id), None)

    def capture_authority(self, estate_id, actor_id):
        proof = self.authority(estate_id, actor_id)
        if proof is None:
            return None
        return dict(estate_id=estate_id, actor_id=actor_id,
            beneficiary_id=proof["beneficiary_id"], guardian_id=proof["guardian_id"],
            administration_id=proof.get("administration_id"), actor_age=proof["actor_age"],
            beneficiary_age=proof["beneficiary_age"], path_json=json.dumps(proof["path"], separators=(",", ":")),
            estate_frontier_id=self.store.scalar("SELECT COALESCE(MAX(id),0) FROM estate_cases"),
            administration_end_frontier=self.store.scalar("SELECT COALESCE(MAX(id),0) FROM estate_administration_ends"))

    def check_authority_history(self, auth, tick):
        """Check a recorded asset mandate after later succession or revocation."""
        case = self.store.query_one("SELECT * FROM estate_cases WHERE id=?", (auth["estate_id"],))
        actor_age = self.store.scalar("SELECT age FROM agents WHERE id=?", (auth["actor_id"],), default=-1)
        frontier = self.store.query_one("SELECT * FROM estate_cases WHERE id=?", (auth["estate_frontier_id"],))
        if (case is None or tick < case["opened_tick"] or not 18 <= auth["actor_age"] <= actor_age
                or frontier is None or frontier["id"] < case["id"] or frontier["opened_tick"] > tick):
            raise EstateError("estate asset authority has invalid age, time or frontier evidence")
        if self.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=? AND id<=?",
                             (auth["actor_id"], auth["estate_frontier_id"])):
            raise EstateError("estate asset representative was already deceased")
        if auth["administration_id"] is not None:
            self.e.estate_administration.check_order_authority(auth, tick)
            return
        route = json.loads(auth["path_json"])
        case_id, beneficiary = case["id"], None
        if not isinstance(route, list) or not route:
            raise EstateError("estate asset authority lacks a beneficial path")
        for index, member_id in enumerate(route):
            member = self.store.query_one("SELECT * FROM estate_beneficiaries WHERE id=?", (member_id,))
            if member is None or member["estate_id"] != case_id or member["agent_id"] is None:
                raise EstateError("estate asset authority has a false beneficial path")
            beneficiary = member["agent_id"]
            descendant = self.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=? AND id<=?",
                                           (beneficiary, auth["estate_frontier_id"]))
            if index < len(route)-1:
                if descendant is None:
                    raise EstateError("estate asset authority predates its beneficial path")
                case_id = descendant
            elif descendant is not None:
                raise EstateError("estate asset authority claimed a deceased beneficiary")
        age = self.store.scalar("SELECT age FROM agents WHERE id=?", (beneficiary,), default=-1)
        if beneficiary != auth["beneficiary_id"] or auth["beneficiary_age"] is None or age < auth["beneficiary_age"]:
            raise EstateError("estate asset beneficiary identity or age is invalid")
        if auth["guardian_id"] is None:
            if auth["actor_id"] != beneficiary or auth["beneficiary_age"] < 18:
                raise EstateError("estate asset mandate is not an adult beneficial owner")
        else:
            guardian = self.store.query_one("SELECT * FROM guardianships WHERE id=?", (auth["guardian_id"],))
            if (guardian is None or guardian["guardian_agent_id"] != auth["actor_id"]
                    or guardian["child_agent_id"] != beneficiary or auth["beneficiary_age"] >= 18
                    or guardian["started_tick"] > tick or (guardian["ended_tick"] is not None and guardian["ended_tick"] < tick)):
                raise EstateError("estate asset guardian lacked the recorded authority")

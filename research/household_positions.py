"""Private, read-only household instruments and contingent estate interests.

Each underlying financial claim appears once in ``instruments``. Household
and estate views reference its key; face claims, cash and execution marks have
separate subtotals. Residual estate rights are conditional paths through every
estate's creditor/reserve boundary, never extra copies of a nominee's assets.
There is deliberately no net-wealth scalar for an incompletely priced world.
"""
from __future__ import annotations

from collections import defaultdict
from fractions import Fraction

from engine.position_history import CASH_KINDS, account_balances_at, cash_distribution_at, people_at
from engine.project_rights import interests_at
from engine.store import load_json


POSITION_CONTRACT = "household-instruments-v1"


def _fraction(value: Fraction) -> dict:
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def household_positions(store, *, tick: int) -> dict:
    """Inventory recorded instruments at a committed Semantics-20 boundary.

    This is an operator/research reader, not a public or agent-authorized API.
    It must not be exposed through an unauthenticated city projection.
    """
    if type(tick) is not int or tick < 0:
        raise ValueError("tick must be a nonnegative integer")
    meta = store.get_meta()
    if int(load_json(meta["config_json"], {}).get("engine_semantics_version", 1)) < 20:
        raise ValueError("household positions require Semantics 20")
    if tick > meta["tick"] or (meta["active_tick"] is not None and tick >= meta["active_tick"]):
        raise ValueError("positions require a committed tick")
    return _Inventory(store, tick).read()


class _Inventory:
    def __init__(self, store, tick):
        self.store, self.tick = store, tick
        self.people = {r["agent_id"]: r for r in people_at(store, tick)}
        self.cases = {r["id"]: dict(r) for r in store.query(
            "SELECT * FROM estate_cases WHERE opened_tick<=? ORDER BY id", (tick,))}
        self.nominees = {r["deceased_agent_id"]: r["id"] for r in self.cases.values()}
        self.instruments = {}
        self.claims = {(r["kind"], r["source_id"]): dict(r) for r in store.query(
            "SELECT * FROM estate_claims WHERE registered_tick<=? ORDER BY id", (tick,))}

    def holder(self, kind, identifier):
        if kind == "agent" and identifier in self.nominees:
            return {"type": "estate", "id": self.nominees[identifier], "nominee_agent_id": identifier}
        return {"type": kind, "id": identifier}

    def add(self, key, kind, holder, currency, *, original_holder=None, debtor=None,
            cash_cents=None, face_cents=None, quantity=None, unit="currency_minor_units",
            mark=None, evidence=(), replaces=(), reason=None):
        if key in self.instruments:
            raise ValueError("duplicate instrument source: " + key)
        if face_cents is not None and face_cents < 0:
            raise ValueError("negative outstanding claim: " + key)
        self.instruments[key] = {
            "key": key, "kind": kind, "holder": holder,
            "original_holder": original_holder or holder, "debtor": debtor,
            "currency": currency, "unit": unit, "quantity": quantity,
            "cash_cents": cash_cents, "face_cents": face_cents, "mark": mark,
            "evidence": list(evidence), "replaces": list(replaces), "reason": reason,
        }

    def sum(self, sql, params):
        return int(self.store.scalar(sql, params, default=0) or 0)

    def claim_remaining(self, claim):
        paid = self.sum("SELECT SUM(d.amount_cents) FROM estate_disbursements d "
            "JOIN estate_receipts r ON r.id=d.receipt_id WHERE d.claim_id=? AND r.tick<=?",
            (claim["id"], self.tick))
        released = self.sum("SELECT SUM(amount_cents) FROM estate_claim_releases WHERE claim_id=? AND tick<=?",
                            (claim["id"], self.tick))
        # A bank's accounting loss is not discharge of this estate claim.
        return claim["principal_cents"] - paid - released

    def cash(self):
        for row in account_balances_at(self.store, self.tick):
            if row["owner_type"] != "agent" or row["owner_id"] not in self.people:
                continue
            if row["kind"] not in (*CASH_KINDS, "legal_escrow"):
                continue  # Claim bookkeeping is inventoried by its instrument below.
            if row["amount_cents"] == 0:
                continue
            self.add(f"account:{row['id']}", "wallet_cash" if row["kind"] in CASH_KINDS else "restricted_cash",
                self.holder("agent", row["owner_id"]), row["currency_code"],
                original_holder={"type": "agent", "id": row["owner_id"]},
                cash_cents=row["amount_cents"], evidence=[f"accounts:{row['id']}", "ledger_entries:tick<=" + str(self.tick)])

    def wages(self):
        for claim in self.store.query("SELECT * FROM wage_claims WHERE opened_tick<=? ORDER BY id", (self.tick,)):
            holder = self.store.query_one("SELECT * FROM wage_claim_holders WHERE claim_id=? AND started_tick<=? "
                "AND (ended_tick IS NULL OR ended_tick>?) ORDER BY id", (claim["id"], self.tick, self.tick))
            if holder is None:
                raise ValueError("wage claim lacks historical holder")
            amount = self.sum("SELECT SUM(earned_cents) FROM wage_accruals WHERE claim_id=? AND tick<=?", (claim["id"], self.tick))
            amount -= self.sum("SELECT SUM(gross_cents) FROM wage_settlements WHERE claim_id=? AND tick<=?", (claim["id"], self.tick))
            amount -= self.sum("SELECT SUM(n.removed_cents) FROM wage_claim_novations n JOIN legal_awards a ON a.id=n.award_id "
                               "WHERE n.claim_id=? AND a.tick<=?", (claim["id"], self.tick))
            ledger_amount = self.sum("SELECT SUM(delta_cents) FROM ledger_entries WHERE account_id=? AND tick<=?",
                                     (holder["receivable_account_id"], self.tick))
            if amount != ledger_amount:
                raise ValueError("wage position does not reconcile to its recorded holder")
            self.add(f"wage:{claim['id']}", "wage_receivable", self.holder(holder["owner_type"], holder["owner_id"]),
                claim["currency_code"], original_holder={"type": "agent", "id": claim["employee_id"]},
                debtor=self.holder("firm", claim["firm_id"]), face_cents=amount,
                evidence=[f"wage_claims:{claim['id']}", f"wage_claim_holders:{holder['id']}",
                          "wage_accruals", "wage_settlements", "wage_claim_novations"],
                reason="gross_earned_face_amount_not_expected_net_collection")

    def awards(self):
        for award in self.store.query("SELECT * FROM legal_awards WHERE tick<=? ORDER BY id", (self.tick,)):
            amount = award["awarded_cents"] - award["credited_cents"] - award["credited_loss_cents"]
            amount -= self.sum("SELECT SUM(amount_cents) FROM legal_award_payments WHERE award_id=? AND tick<=?", (award["id"], self.tick))
            amount -= self.sum("SELECT SUM(amount_cents) FROM legal_award_losses WHERE award_id=? AND tick<=?", (award["id"], self.tick))
            replaces = [f"obligation:{r[0]}" for r in self.store.query(
                "SELECT obligation_id FROM legal_award_obligations WHERE award_id=? ORDER BY obligation_id", (award["id"],))]
            replaces += [f"wage:{r[0]}" for r in self.store.query(
                "SELECT DISTINCT claim_id FROM wage_claim_novations WHERE award_id=? ORDER BY claim_id", (award["id"],))]
            self.add(f"award:{award['id']}", "legal_award", self.holder(award["claimant_type"], award["claimant_id"]),
                award["currency_code"], original_holder={"type": award["claimant_type"], "id": award["claimant_id"]},
                debtor=self.holder(award["respondent_type"], award["respondent_id"]), face_cents=amount,
                evidence=[f"legal_awards:{award['id']}", "legal_award_payments", "legal_award_losses"],
                replaces=replaces, reason="adjudicated_face_amount_not_expected_collection")

    def loans(self):
        # Personal loan payment principal has an existing exact transaction memo
        # containing loan_id. Its reserve leg excludes interest (paid to equity).
        # Firm bankruptcy recoveries have a different contract and are not
        # personal household debts; no firm debt is charged to its shareholders.
        for loan in self.store.query("SELECT l.*,b.reserve_account_id,b.currency_code FROM loans l "
                "JOIN banks b ON b.id=l.bank_id WHERE borrower_type='agent' AND origin_tick<=? ORDER BY l.id", (self.tick,)):
            claim = self.claims.get(("bank_principal", loan["id"]))
            evidence = [f"loans:{loan['id']}"]
            if claim:
                amount = self.claim_remaining(claim)
                evidence += [f"estate_claims:{claim['id']}", "estate_disbursements", "estate_claim_releases"]
            elif self.store.scalar("SELECT 1 FROM events WHERE kind='loan_default' AND tick<=? "
                    "AND json_extract(payload_json,'$.loan_id')=? LIMIT 1", (self.tick, loan["id"])):
                amount = 0
                evidence += ["events:loan_default"]
            else:
                paid = self.sum("SELECT SUM(l.delta_cents) FROM transactions t JOIN ledger_entries l ON l.txn_id=t.id "
                    "WHERE t.kind='loan_payment' AND t.memo=? AND t.tick<=? AND l.account_id=?",
                    (f"loan {loan['id']} payment", self.tick, loan["reserve_account_id"]))
                amount = loan["principal_cents"] - paid
                evidence += [f"transactions:loan {loan['id']} payment", f"accounts:{loan['reserve_account_id']}"]
            self.add(f"loan:{loan['id']}", "bank_principal", self.holder("bank", loan["bank_id"]), loan["currency_code"],
                debtor=self.holder("agent", loan["borrower_id"]), face_cents=amount, evidence=evidence,
                reason="remaining_principal_excludes_future_interest")

    def obligations(self):
        for row in self.store.query("SELECT o.*,c.executed_tick,c.terminated_tick FROM obligations o JOIN contracts c ON c.id=o.contract_id "
                "WHERE c.executed_tick<=? AND o.obligation_type IN ('payment','indemnity') AND o.amount_cents>0 "
                "AND (o.obligor_type='agent' OR o.obligee_type='agent') ORDER BY o.id", (self.tick,)):
            replacement = self.store.scalar("SELECT a.id FROM legal_award_obligations x JOIN legal_awards a ON a.id=x.award_id "
                "WHERE x.obligation_id=? AND a.tick<=?", (row["id"], self.tick))
            claim = self.claims.get(("contract_payment", row["id"]))
            reason = "contractual_face_amount_not_expected_collection"
            if replacement:
                amount, reason = 0, f"replaced_by_award:{replacement}"
            elif claim:
                amount = self.claim_remaining(claim)
            elif row["performed_tick"] is not None and row["performed_tick"] <= self.tick:
                amount = 0
            elif row["status"] == "cancelled" and row["terminated_tick"] is not None:
                amount = 0 if row["terminated_tick"] <= self.tick else row["amount_cents"]
            elif self.store.scalar("SELECT 1 FROM estate_items i JOIN estate_cases e ON e.id=i.estate_id "
                    "WHERE i.kind='personal_obligation' AND i.source_id=? AND i.disposition='extinguished' "
                    "AND e.opened_tick<=?", (row["id"], self.tick)):
                amount = 0
            elif row["status"] not in ("pending", "breached", "performed", "adjudicated"):
                # Do not back-project an undated cancellation/other mutable status.
                amount, reason = None, "unrecorded_obligation_disposition_boundary"
            else:
                amount = row["amount_cents"]
            self.add(f"obligation:{row['id']}", "contract_receivable", self.holder(row["obligee_type"], row["obligee_id"]),
                row["currency_code"], original_holder={"type": row["obligee_type"], "id": row["obligee_id"]},
                debtor=self.holder(row["obligor_type"], row["obligor_id"]), face_cents=amount,
                evidence=[f"obligations:{row['id']}", f"contracts:{row['contract_id']}",
                          *([f"estate_claims:{claim['id']}"] if claim else [])], reason=reason)

    def assets(self):
        holdings = defaultdict(int)
        movements = defaultdict(list)
        for row in self.store.query("SELECT f.id FROM firms f WHERE f.founded_tick<=? AND NOT EXISTS "
                "(SELECT 1 FROM share_movements m WHERE m.firm_id=f.id AND m.movement_type='founder_issuance')", (self.tick,)):
            raise ValueError(f"firm {row['id']} lacks recorded founder issuance")
        for row in self.store.query("SELECT * FROM share_movements WHERE tick<=? ORDER BY id", (self.tick,)):
            for prefix, sign in (("from", -1), ("to", 1)):
                if row[prefix + "_holder_type"] == "agent":
                    key = (row["firm_id"], row[prefix + "_holder_id"])
                    holdings[key] += sign * row["qty"]
                    movements[key].append(f"share_movements:{row['id']}")
        # Exchange executions use the trades journal, not share_movements.
        for row in self.store.query("SELECT id,firm_id,buyer_id,seller_id,qty FROM trades WHERE tick<=? ORDER BY id", (self.tick,)):
            for field, sign in (("buyer_id", 1), ("seller_id", -1)):
                key = (row["firm_id"], row[field])
                holdings[key] += sign * row["qty"]
                movements[key].append(f"trades:{row['id']}")
        for row in self.store.query("SELECT id,firm_id,investor_agent_id,shares_issued FROM funding_rounds WHERE tick<=? ORDER BY id", (self.tick,)):
            key = (row["firm_id"], row["investor_agent_id"])
            holdings[key] += row["shares_issued"]
            movements[key].append(f"funding_rounds:{row['id']}")
        for row in self.store.query("SELECT id,payload_json FROM events WHERE kind='vc_funded' AND tick<=? ORDER BY id", (self.tick,)):
            payload = load_json(row["payload_json"], {})
            key = (payload["firm_id"], payload["vc_agent_id"])
            holdings[key] += payload["shares_issued"]
            movements[key].append(f"events:{row['id']}")
        for (firm_id, agent_id), qty in sorted(holdings.items()):
            if qty < 0:
                raise ValueError("historical share movements do not reconcile")
            if qty == 0:
                continue
            if self.store.scalar("SELECT 1 FROM firms WHERE id=? AND bankrupt_tick<=?", (firm_id, self.tick)):
                continue  # Extinguished shares have no remaining quantity, not a zero price.
            currency = self.store.scalar("SELECT currency_code FROM firms WHERE id=?", (firm_id,))
            trade = self.store.query_one("SELECT id,tick,price_cents FROM trades WHERE firm_id=? AND tick<=? "
                "AND buyer_id<>seller_id AND price_cents>0 AND qty>0 ORDER BY tick DESC,id DESC LIMIT 1", (firm_id, self.tick))
            mark = {"amount_cents": qty * trade["price_cents"], "unit_price_cents": trade["price_cents"],
                    "observed_tick": trade["tick"], "age_ticks": self.tick - trade["tick"],
                    "evidence": f"trades:{trade['id']}", "kind": "last_distinct_owner_execution"} if trade else None
            self.add(f"shares:{firm_id}:agent:{agent_id}", "equity", self.holder("agent", agent_id), currency,
                original_holder={"type": "agent", "id": agent_id}, quantity=str(qty), unit="shares", mark=mark,
                evidence=movements[(firm_id, agent_id)], reason="observed_mark_is_not_guaranteed_sale_proceeds" if mark else "no_observed_execution")
        if self.tick == self.store.get_meta()["tick"]:
            observed = {(r["firm_id"], r["holder_id"]): r["qty"] for r in self.store.query(
                "SELECT firm_id,holder_id,qty FROM shares WHERE holder_type='agent' AND qty<>0")}
            reconstructed = {(int(r["key"].split(":")[1]), r["original_holder"]["id"]): int(r["quantity"])
                             for r in self.instruments.values() if r["kind"] == "equity"}
            if reconstructed != observed:
                raise ValueError("share history does not reconcile to the committed cap table")
        for project in self.store.query("SELECT p.*,a.currency_code FROM construction_projects p JOIN accounts a ON a.id=p.escrow_account_id "
                "WHERE p.owner_type='agent' AND p.proposed_tick<=? AND (p.cancelled_tick IS NULL OR p.cancelled_tick>?) ORDER BY p.id", (self.tick, self.tick)):
            interests = interests_at(self.store, project["id"], self.tick, enabled=True)
            if sum((Fraction(int(i["numerator"]), int(i["denominator"])) for i in interests), Fraction()) != 1:
                raise ValueError("project interests do not reconcile to one title")
            for interest in interests:
                agent_id = interest["agent_id"]
                self.add(f"property:{project['id']}:agent:{agent_id}", "property", self.holder("agent", agent_id), project["currency_code"],
                    original_holder={"type": "agent", "id": project["owner_id"]},
                    quantity={"numerator": interest["numerator"], "denominator": interest["denominator"]}, unit="project_interest",
                    evidence=[f"construction_projects:{project['id']}", "project_interest_lots", "estate_project_custody"],
                    reason="no_observed_market_valuation; construction_cost_is_not_a_price")

    def estate_views(self):
        result = {}
        for identifier, case in self.cases.items():
            claims = [c for c in self.claims.values() if c["estate_id"] == identifier]
            priority = {"bank_principal": 0, "contract_payment": 1, "legal_award": 2}
            creditors = [{"claim_id": c["id"], "instrument_key":
                         {"bank_principal": "loan", "contract_payment": "obligation", "legal_award": "award"}[c["kind"]] + f":{c['source_id']}",
                         "currency": c["currency_code"], "remaining_cents": self.claim_remaining(c),
                         "priority": c["kind"]} for c in sorted(claims, key=lambda c: (priority[c["kind"]], c["id"]))
                         if self.claim_remaining(c) > 0]
            beneficiaries = self.store.query("SELECT id,agent_id,weight FROM estate_beneficiaries WHERE estate_id=? ORDER BY id", (identifier,))
            weight = sum(b["weight"] for b in beneficiaries)
            reserves = [dict(r) for r in self.store.query("SELECT r.id,r.matter_id,r.currency_code,r.reserve_limit_cents,r.escrow_account_id "
                "FROM estate_legal_reserves r WHERE r.estate_id=? AND r.registered_tick<=? AND NOT EXISTS "
                "(SELECT 1 FROM estate_reserve_resolutions x WHERE x.reserve_id=r.id AND x.tick<=?) ORDER BY r.id", (identifier, self.tick, self.tick))]
            for reserve in reserves:
                reserve["protected_obligations"] = [dict(r) for r in self.store.query(
                    "SELECT obligation_id,protected_cents FROM estate_reserve_obligations WHERE reserve_id=? ORDER BY obligation_id", (reserve["id"],))]
            result[identifier] = {"estate_id": identifier, "nominee_agent_id": case["deceased_agent_id"],
                "finality_policy": case["distribution_finality_policy"], "creditors_in_priority_order": creditors,
                "unresolved_reserves": reserves, "reserves_are_admitted_debts": False,
                "beneficiaries": [{"beneficiary_id": b["id"], "holder": self.holder("agent", b["agent_id"]),
                                   "fraction_of_residual": _fraction(Fraction(b["weight"], weight))} for b in beneficiaries],
                "asset_keys": [], "debt_keys": [], "residual_value_cents": None}
        return result

    def read(self):
        self.cash()
        self.wages()
        self.awards()
        self.loans()
        self.obligations()
        self.assets()
        estates = self.estate_views()
        memberships = {r["agent_id"]: r["household_id"] for r in self.store.query(
            "SELECT household_id,agent_id FROM household_memberships WHERE joined_tick<=? "
            "AND (left_tick IS NULL OR left_tick>?) ORDER BY id", (self.tick, self.tick))}
        households = {}
        for person in people_at(self.store, self.tick, living_only=True):
            household_id = memberships.get(person["agent_id"])
            if household_id is None:
                raise ValueError("living person lacks a recorded household membership")
            view = households.setdefault(household_id, {"household_id": household_id, "members": [],
                "asset_keys": [], "debt_keys": [], "contingent_interests": [], "by_currency": {}})
            view["members"].append(person["agent_id"])

        def view_for(holder):
            if not holder:
                return None
            if holder["type"] == "estate":
                return estates[holder["id"]]
            if holder["type"] == "agent":
                return households.get(memberships.get(holder["id"]))
            return None

        for instrument in self.instruments.values():
            for field, destination in (("holder", "asset_keys"), ("debtor", "debt_keys")):
                view = view_for(instrument[field])
                if view is not None:
                    view[destination].append(instrument["key"])

        def residual_paths(origin, current, path, fraction):
            if current in path:
                raise ValueError("cyclic estate residual path")
            path = [*path, current]
            for beneficiary in estates[current]["beneficiaries"]:
                portion = beneficiary["fraction_of_residual"]
                value = fraction * Fraction(int(portion["numerator"]), int(portion["denominator"]))
                holder = beneficiary["holder"]
                if holder["type"] == "estate":
                    residual_paths(origin, holder["id"], path, value)
                else:
                    view = view_for(holder)
                    if view is not None:
                        view["contingent_interests"].append({"origin_estate_id": origin, "beneficiary_agent_id": holder["id"],
                            "estate_path": path, "fraction_if_intervening_claims_settled": _fraction(value),
                            "amount_cents": None, "condition": "each_estate_creditors_and_reserves_precede_its_residual"})

        for identifier in estates:
            residual_paths(identifier, identifier, [], Fraction(1))
        for view in [*households.values(), *estates.values()]:
            subtotals = {}
            for side in ("asset_keys", "debt_keys"):
                for key in view[side]:
                    instrument = self.instruments[key]
                    totals = subtotals.setdefault(instrument["currency"], {"wallet_cash_cents": 0, "restricted_cash_cents": 0,
                        "receivable_face_cents": 0, "debt_face_cents": 0, "observed_equity_marks_cents": 0, "unpriced_keys": []})
                    if side == "debt_keys":
                        if instrument["face_cents"] is not None:
                            totals["debt_face_cents"] += instrument["face_cents"]
                        else:
                            totals["unpriced_keys"].append(key)
                    elif instrument["cash_cents"] is not None:
                        totals[instrument["kind"] + "_cents"] += instrument["cash_cents"]
                    elif instrument["face_cents"] is not None:
                        totals["receivable_face_cents"] += instrument["face_cents"]
                    elif instrument["mark"] is not None:
                        totals["observed_equity_marks_cents"] += instrument["mark"]["amount_cents"]
                    else:
                        totals["unpriced_keys"].append(key)
            view["by_currency"] = subtotals
        return {"contract_version": POSITION_CONTRACT, "tick": self.tick,
            "instruments": list(self.instruments.values()), "households": list(households.values()),
            "estates": list(estates.values()), "cash_distribution": cash_distribution_at(self.store, self.tick),
            "net_wealth_cents": None, "net_wealth_reason": "face_claims_and_contingent_or_unpriced_rights_are_not_market_values",
            "currency_conversion": None, "scope": "private_personal_cash_claims_debts_equities_and_project_interests"}

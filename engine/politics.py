"""Federal-lite Northstar legislature, lobbying, elections, and typed policy rules."""
from __future__ import annotations

import json
import math
from typing import Any

from .ledger import Ledger, SYS_GOV
from .legal import LegalInstitution
from .store import Store


ALLOWED_POLICY_RULES = {
    "tax_rate_bps", "unemployment_benefit_cents",
    "competition.hhi_threshold", "competition.delta_threshold",
    "competition.agency_capacity", "ai.mandatory_acquisition_disclosure",
    "ai.interoperability_remedy",
}


class PoliticalEconomy:
    def __init__(self, store: Store, ledger: Ledger, legal: LegalInstitution,
                 config: dict | None = None):
        self.store = store
        self.ledger = ledger
        self.legal = legal
        self.config = config or {}
        self.enabled = config is not None and bool(self.config.get("enabled", True))
        self.house_seats = int(self.config.get("house_seats", 12))
        self.senate_seats = int(self.config.get("senate_seats", 6))
        self.house_interval = int(self.config.get("house_election_interval_ticks", 180))
        self.executive_interval = int(self.config.get("executive_election_interval_ticks", 360))
        self.disclosure_delay = int(self.config.get("lobbying_disclosure_delay_ticks", 5))

    def initialize(self, tick: int = 0) -> None:
        if not self.enabled or self.store.query_one("SELECT 1 FROM political_parties LIMIT 1"):
            return
        parties = [
            ("Civic Coalition", {"economic": -0.45, "competition": 0.75, "labor": 0.65}),
            ("Enterprise Alliance", {"economic": 0.45, "competition": 0.35, "labor": 0.25}),
        ]
        party_ids = []
        for name, platform in parties:
            account = self.ledger.create_account("party", None, "treasury", label=f"party:{name}")
            party_id = self.store.insert(
                "political_parties", name=name, platform_json=json.dumps(platform, sort_keys=True),
                treasury_account_id=account)
            self.store.execute("UPDATE accounts SET owner_id=? WHERE id=?", (party_id, account))
            party_ids.append(party_id)
        for chamber, seats, term in (("house", self.house_seats, self.house_interval),
                                     ("senate", self.senate_seats, self.house_interval * 3)):
            for seat in range(1, seats + 1):
                party_id = party_ids[(seat + (0 if chamber == "house" else 1)) % 2]
                agent_id = self._spawn_official(
                    f"{chamber.title()} Member {seat}", "legislator", f"legislator_{chamber}", tick)
                self.store.insert(
                    "legislators", agent_id=agent_id, chamber=chamber, seat_number=seat,
                    party_id=party_id, term_start_tick=tick, term_end_tick=tick + term, active=1)
        committee_specs = [
            ("Judiciary and Competition", "competition,corporate,legal"),
            ("Finance", "tax,spending,securities"),
            ("Commerce and Technology", "technology,trade,ai"),
            ("Labor", "employment,wages,benefits"),
        ]
        for chamber in ("house", "senate"):
            legislators = self.store.query(
                "SELECT id FROM legislators WHERE chamber=? AND active=1 ORDER BY seat_number", (chamber,))
            for index, (name, jurisdiction) in enumerate(committee_specs):
                committee_id = self.store.insert(
                    "committees", name=f"{chamber.title()} {name}", chamber=chamber,
                    jurisdiction=jurisdiction)
                members = [legislators[(index + offset) % len(legislators)] for offset in range(
                    min(3 if chamber == "house" else 2, len(legislators)))]
                for offset, member in enumerate(members):
                    self.store.insert("committee_members", committee_id=committee_id,
                                      legislator_id=int(member["id"]), is_chair=1 if offset == 0 else 0)
        agency_specs = [
            ("Northstar Markets Commission", "markets,securities,disclosure", "regulator"),
            ("Northstar Competition Commission", "competition,mergers", "competition_regulator"),
            ("Northstar Labor and AI Standards Agency", "labor,ai,compliance", "labor_regulator"),
        ]
        for name, mandate, role in agency_specs:
            leader = self._spawn_official(f"Director {name}", "regulator", role, tick)
            self.store.insert("agencies", name=name, mandate=mandate, capacity=1.0,
                              leader_agent_id=leader)
        if not self.store.query_one("SELECT 1 FROM agents WHERE role='executive' AND alive=1"):
            self._spawn_official("President Arden", "executive", "executive", tick)
        for index in range(2):
            self._spawn_official(f"Registered Lobbyist {index + 1}", "lobbyist", "lobbyist", tick)
        self.store.log_event(tick, "political_institutions_created", {
            "parties": 2, "house_seats": self.house_seats, "senate_seats": self.senate_seats,
            "committees": 8, "agencies": 3}, phase="NIGHT_CLOSE",
            subject_type="government", subject_id=1, importance=3.0)

    def _spawn_official(self, name: str, occupation: str, role: str, tick: int) -> int:
        region = self.store.query_one(
            "SELECT id,currency_code FROM regions WHERE region_key='northstar' LIMIT 1")
        region_id = int(region["id"]) if region else None
        currency = str(region["currency_code"]) if region else "USD"
        agent_id = self.store.insert(
            "agents", name=name, kind="staff", occupation=occupation, role=role,
            age=45, health="healthy", dependents=0, personality_json="{}", political_lean=0.0,
            media_diet_json="[1,2]", risk_tolerance=0.4, cadence_json="{\"act\":1}",
            model_tier="strong", population_tier="core", pinned_core=1,
            region_id=region_id, alive=1, retired=0, arrived_tick=tick)
        bank = self.store.scalar(
            "SELECT id FROM banks WHERE status='open' AND (? IS NULL OR region_id=?) ORDER BY id LIMIT 1",
            (region_id, region_id))
        account = self.ledger.create_account(
            "agent", agent_id, "checking", bank_id=int(bank) if bank is not None else None,
            label=f"official:{agent_id}", opening_cents=100_000, currency_code=currency)
        self.store.update("agents", agent_id, checking_account_id=account)
        return agent_id

    # ------------------------------------------------------------------ bills
    def sponsor_bill(self, tick: int, actor_id: int, data: dict[str, Any]) -> dict[str, Any]:
        legislator = self._legislator_for_agent(actor_id)
        if not legislator:
            return {"ok": False, "reason": "only an active legislator may sponsor a bill"}
        changes = dict(data.get("policy_changes", {}))
        error = self._validate_policy_changes(changes)
        if error:
            return {"ok": False, "reason": error}
        topic = str(data.get("topic", "technology"))
        committee = self._committee_for(str(legislator["chamber"]), topic)
        sequence = int(self.store.scalar("SELECT COALESCE(MAX(id),0)+1 FROM bills", default=1))
        bill_key = str(data.get("bill_key", f"NS-{tick}-{sequence}"))[:80]
        title = str(data.get("title", "Untitled Bill")).strip()[:200]
        bill_id = self.store.insert(
            "bills", bill_key=bill_key, title=title, sponsor_legislator_id=int(legislator["id"]),
            origin_chamber=legislator["chamber"], committee_id=int(committee["id"]),
            status="committee", current_version=1, introduced_tick=tick,
            policy_changes_json=json.dumps(changes, sort_keys=True),
            metadata_json=json.dumps(data.get("metadata", {}), sort_keys=True))
        self.store.insert(
            "bill_versions", bill_id=bill_id, version=1, tick=tick,
            author_legislator_id=int(legislator["id"]),
            summary=str(data.get("summary", title))[:1000], text_json=json.dumps({
                "title": title, "policy_changes": changes}, sort_keys=True))
        self._bill_action(bill_id, tick, "introduced", actor_id, {"committee_id": int(committee["id"])})
        self.store.log_event(tick, "bill_introduced", {"bill_id": bill_id, "bill_key": bill_key,
            "title": title, "origin_chamber": legislator["chamber"], "policy_changes": changes},
            phase="EXECUTION", subject_type="bill", subject_id=bill_id, importance=3.0)
        return {"ok": True, "bill_id": bill_id, "status": "committee"}

    def amend_bill(self, tick: int, actor_id: int, bill_id: int,
                   amendment: dict[str, Any]) -> dict[str, Any]:
        bill = self.store.query_one("SELECT * FROM bills WHERE id=?", (bill_id,))
        legislator = self._legislator_for_agent(actor_id)
        if not bill or bill["status"] not in {"committee", "floor_house", "floor_senate"}:
            return {"ok": False, "reason": "bill is not amendable"}
        if not legislator:
            return {"ok": False, "reason": "active legislator required"}
        changes = json.loads(bill["policy_changes_json"] or "{}")
        changes.update(dict(amendment.get("policy_changes", {})))
        error = self._validate_policy_changes(changes)
        if error:
            return {"ok": False, "reason": error}
        version = int(bill["current_version"]) + 1
        self.store.update("bills", bill_id, current_version=version,
                          policy_changes_json=json.dumps(changes, sort_keys=True), status="committee")
        self.store.execute("DELETE FROM legislative_votes WHERE bill_id=?", (bill_id,))
        self.store.insert(
            "bill_versions", bill_id=bill_id, version=version, tick=tick,
            author_legislator_id=int(legislator["id"]),
            summary=str(amendment.get("summary", "Amendment"))[:1000],
            text_json=json.dumps({"policy_changes": changes}, sort_keys=True))
        self._bill_action(bill_id, tick, "amended", actor_id, {"version": version})
        self.store.log_event(tick, "bill_amended", {"bill_id": bill_id, "version": version,
            "policy_changes": changes}, phase="EXECUTION", subject_type="bill",
            subject_id=bill_id, importance=2.2)
        return {"ok": True, "bill_id": bill_id, "version": version, "status": "committee"}

    def committee_vote(self, tick: int, actor_id: int, bill_id: int, vote: str) -> dict[str, Any]:
        bill = self.store.query_one("SELECT * FROM bills WHERE id=?", (bill_id,))
        legislator = self._legislator_for_agent(actor_id)
        if not bill or bill["status"] != "committee" or not legislator:
            return {"ok": False, "reason": "bill is not in committee or actor is ineligible"}
        member = self.store.query_one(
            "SELECT 1 FROM committee_members WHERE committee_id=? AND legislator_id=?",
            (bill["committee_id"], legislator["id"]))
        if not member or vote not in {"yes", "no", "abstain"}:
            return {"ok": False, "reason": "committee membership and valid vote required"}
        self._record_vote(bill, legislator, "committee", vote, tick)
        yes = int(self.store.scalar(
            "SELECT COUNT(*) FROM legislative_votes WHERE bill_id=? AND version=? "
            "AND stage='committee' AND vote='yes'", (bill_id, bill["current_version"]), default=0))
        members = int(self.store.scalar(
            "SELECT COUNT(*) FROM committee_members WHERE committee_id=?", (bill["committee_id"],), default=0))
        status = "committee"
        if yes > members / 2:
            status = f"floor_{bill['origin_chamber']}"
            self.store.update("bills", bill_id, status=status)
            self._bill_action(bill_id, tick, "committee_reported", actor_id, {"yes": yes, "members": members})
        return {"ok": True, "bill_id": bill_id, "status": status, "yes": yes, "members": members}

    def cast_vote(self, tick: int, actor_id: int, bill_id: int, vote: str) -> dict[str, Any]:
        bill = self.store.query_one("SELECT * FROM bills WHERE id=?", (bill_id,))
        legislator = self._legislator_for_agent(actor_id)
        if not bill or bill["status"] not in {"floor_house", "floor_senate"} or not legislator:
            return {"ok": False, "reason": "bill is not on an eligible floor"}
        chamber = bill["status"].removeprefix("floor_")
        if legislator["chamber"] != chamber or vote not in {"yes", "no", "abstain"}:
            return {"ok": False, "reason": "legislator cannot vote in this chamber"}
        self._record_vote(bill, legislator, chamber, vote, tick)
        yes = int(self.store.scalar(
            "SELECT COUNT(*) FROM legislative_votes WHERE bill_id=? AND version=? AND stage=? AND vote='yes'",
            (bill_id, bill["current_version"], chamber), default=0))
        seats = self.house_seats if chamber == "house" else self.senate_seats
        status = bill["status"]
        if yes > seats / 2:
            if not self.store.query_one(
                    "SELECT 1 FROM bill_actions WHERE bill_id=? AND action_type=?",
                    (bill_id, f"{chamber}_passed")):
                self._bill_action(bill_id, tick, f"{chamber}_passed", actor_id, {"yes": yes, "seats": seats})
            other = "senate" if chamber == "house" else "house"
            other_passed = self.store.query_one(
                "SELECT 1 FROM bill_actions WHERE bill_id=? AND action_type=?", (bill_id, f"{other}_passed"))
            status = "executive" if other_passed else f"floor_{other}"
            self.store.update("bills", bill_id, status=status)
        return {"ok": True, "bill_id": bill_id, "status": status, "yes": yes, "seats": seats}

    def executive_action(self, tick: int, actor_id: int, bill_id: int,
                         action: str, effective_delay_ticks: int = 1) -> dict[str, Any]:
        actor = self.store.query_one("SELECT role FROM agents WHERE id=? AND alive=1", (actor_id,))
        bill = self.store.query_one("SELECT * FROM bills WHERE id=?", (bill_id,))
        if not actor or (actor["role"] or "") not in {"executive", "gov_official"}:
            return {"ok": False, "reason": "executive authority required"}
        if not bill or bill["status"] != "executive" or action not in {"sign", "veto"}:
            return {"ok": False, "reason": "bill is not awaiting valid executive action"}
        if action == "veto":
            self.store.update("bills", bill_id, status="vetoed", executive_action_tick=tick)
            self._bill_action(bill_id, tick, "vetoed", actor_id, {})
            self.store.log_event(tick, "bill_vetoed", {"bill_id": bill_id}, phase="EXECUTION",
                                 subject_type="bill", subject_id=bill_id, importance=3.5)
            return {"ok": True, "bill_id": bill_id, "status": "vetoed"}
        effective_tick = tick + max(1, int(effective_delay_ticks))
        self._enact_bill(tick, bill, actor_id, effective_tick, action_type="signed")
        return {"ok": True, "bill_id": bill_id, "status": "enacted", "effective_tick": effective_tick}

    def override_veto(self, tick: int, actor_id: int, bill_id: int, vote: str = "yes") -> dict[str, Any]:
        bill = self.store.query_one("SELECT * FROM bills WHERE id=?", (bill_id,))
        legislator = self._legislator_for_agent(actor_id)
        if not bill or bill["status"] != "vetoed" or not legislator or vote not in {"yes", "no"}:
            return {"ok": False, "reason": "veto override vote unavailable"}
        chamber = str(legislator["chamber"])
        stage = f"override_{chamber}"
        self._record_vote(bill, legislator, stage, vote, tick)
        seats = self.house_seats if chamber == "house" else self.senate_seats
        yes = int(self.store.scalar(
            "SELECT COUNT(*) FROM legislative_votes WHERE bill_id=? AND version=? AND stage=? AND vote='yes'",
            (bill_id, bill["current_version"], stage), default=0))
        if yes >= math.ceil(seats * 2 / 3):
            self._bill_action(bill_id, tick, f"{stage}_passed", actor_id, {"yes": yes, "seats": seats})
        both = all(self.store.query_one(
            "SELECT 1 FROM bill_actions WHERE bill_id=? AND action_type=?",
            (bill_id, f"override_{candidate}_passed")) for candidate in ("house", "senate"))
        if both:
            self._enact_bill(tick, bill, actor_id, tick + 1, action_type="veto_overridden")
            return {"ok": True, "bill_id": bill_id, "status": "enacted"}
        return {"ok": True, "bill_id": bill_id, "status": "vetoed", "chamber_yes": yes}

    def _enact_bill(self, tick: int, bill, actor_id: int, effective_tick: int,
                    *, action_type: str) -> None:
        changes = json.loads(bill["policy_changes_json"] or "{}")
        for key, value in sorted(changes.items()):
            self.store.insert(
                "policy_rules", bill_id=int(bill["id"]), rule_key=key,
                value_json=json.dumps(value, sort_keys=True), enacted_tick=tick,
                effective_tick=effective_tick, status="pending")
        self.store.update("bills", int(bill["id"]), status="enacted",
                          executive_action_tick=tick, effective_tick=effective_tick)
        self._bill_action(int(bill["id"]), tick, action_type, actor_id,
                          {"effective_tick": effective_tick, "policy_changes": changes})
        self.store.log_event(tick, "bill_enacted", {"bill_id": int(bill["id"]),
            "effective_tick": effective_tick, "policy_changes": changes,
            "action_type": action_type}, phase="EXECUTION", subject_type="bill",
            subject_id=int(bill["id"]), importance=4.5)

    def _record_vote(self, bill, legislator, stage: str, vote: str, tick: int) -> None:
        self.store.execute(
            "INSERT INTO legislative_votes (bill_id,version,legislator_id,stage,vote,tick) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(bill_id,version,legislator_id,stage) DO UPDATE SET "
            "vote=excluded.vote,tick=excluded.tick",
            (bill["id"], bill["current_version"], legislator["id"], stage, vote, tick))

    def _bill_action(self, bill_id: int, tick: int, action_type: str,
                     actor_id: int | None, detail: dict[str, Any]) -> None:
        self.store.insert("bill_actions", bill_id=bill_id, tick=tick, action_type=action_type,
                          actor_agent_id=actor_id, detail_json=json.dumps(detail, sort_keys=True))

    def _legislator_for_agent(self, agent_id: int):
        return self.store.query_one(
            "SELECT * FROM legislators WHERE agent_id=? AND active=1", (agent_id,))

    def _committee_for(self, chamber: str, topic: str):
        keyword = ("Competition" if topic in {"competition", "antitrust", "merger"} else
                   "Finance" if topic in {"tax", "finance", "securities"} else
                   "Labor" if topic in {"labor", "employment"} else "Commerce")
        return self.store.query_one(
            "SELECT * FROM committees WHERE chamber=? AND name LIKE ? ORDER BY id LIMIT 1",
            (chamber, f"%{keyword}%"))

    @staticmethod
    def _validate_policy_changes(changes: dict[str, Any]) -> str | None:
        unknown = sorted(set(changes) - ALLOWED_POLICY_RULES)
        if unknown:
            return f"unsupported policy rules: {', '.join(unknown)}"
        for key, value in changes.items():
            if key in {"ai.mandatory_acquisition_disclosure", "ai.interoperability_remedy"}:
                if not isinstance(value, bool):
                    return f"{key} must be boolean"
            elif isinstance(value, bool) or not isinstance(value, (int, float)):
                return f"{key} must be numeric"
        return None

    # ------------------------------------------------------------------ lobbying
    def lobby(self, tick: int, actor_id: int, data: dict[str, Any]) -> dict[str, Any]:
        actor = self.store.query_one("SELECT role FROM agents WHERE id=? AND alive=1", (actor_id,))
        if not actor or (actor["role"] or "") not in {"lobbyist", "lawyer"}:
            return {"ok": False, "reason": "registered lobbyist or lawyer required"}
        sponsor_type = str(data.get("sponsor_type", "firm"))
        sponsor_id = int(data.get("sponsor_id", 0))
        authorizer = int(data.get("authorized_by_agent_id", 0))
        if sponsor_type == "firm" and not self.legal.controls(authorizer, "firm", sponsor_id):
            return {"ok": False, "reason": "firm authorization required"}
        if sponsor_type == "agent" and authorizer != sponsor_id:
            return {"ok": False, "reason": "agent authorization required"}
        source = self._sponsor_account(sponsor_type, sponsor_id)
        amount = int(data.get("amount_cents", 0))
        if source is None or amount <= 0 or self.ledger.balance(source) < amount:
            return {"ok": False, "reason": "sponsor cannot fund lobbying activity"}
        currency = str(self.store.scalar(
            "SELECT currency_code FROM accounts WHERE id=?", (source,), default="USD") or "USD")
        sink = self.ledger.system_account(SYS_GOV, currency_code=currency)
        txn_id = self.ledger.transfer(tick, source, sink, amount, kind="lobbying_spend",
                                      memo=f"lobbying by {sponsor_type}:{sponsor_id}")
        salience = min(0.25, math.log10(max(10, amount)) / 40.0)
        activity_id = self.store.insert(
            "lobbying_activities", tick=tick, sponsor_type=sponsor_type, sponsor_id=sponsor_id,
            lobbyist_agent_id=actor_id, target_agent_id=data.get("target_agent_id"),
            bill_id=data.get("bill_id"), activity_type=str(data.get("activity_type", "meeting"))[:60],
            position=str(data.get("position", "support"))[:30], amount_cents=amount,
            transaction_id=txn_id, salience_effect=salience,
            disclosure_tick=tick + self.disclosure_delay, disclosed=0)
        self.store.log_event(tick, "lobbying_activity", {"activity_id": activity_id,
            "bill_id": data.get("bill_id"), "position": data.get("position", "support"),
            "amount_cents": amount, "salience_effect": salience,
            "disclosure_tick": tick + self.disclosure_delay}, phase="EXECUTION",
            subject_type="bill", subject_id=data.get("bill_id"), importance=2.0)
        return {"ok": True, "activity_id": activity_id, "transaction_id": txn_id,
                "salience_effect": salience}

    def _sponsor_account(self, sponsor_type: str, sponsor_id: int) -> int | None:
        if sponsor_type == "agent":
            return self.ledger.agent_checking_id(sponsor_id)
        if sponsor_type == "firm":
            value = self.store.scalar("SELECT account_id FROM firms WHERE id=?", (sponsor_id,))
            return int(value) if value is not None else None
        return None

    # ------------------------------------------------------------------ elections and effective rules
    def hold_election(self, tick: int, election_type: str = "legislative") -> dict[str, Any]:
        voters = self.store.query(
            "SELECT a.id, a.political_lean, COALESCE(b.value,0) AS sentiment FROM agents a "
            "LEFT JOIN beliefs b ON b.agent_id=a.id AND b.key='sentiment' "
            "WHERE a.alive=1 AND a.age>=18 AND a.kind='citizen' ORDER BY a.id")
        civic = enterprise = 0
        for voter in voters:
            score = -float(voter["political_lean"] or 0.0) - max(0.0, -float(voter["sentiment"])) * 0.25
            if score >= 0:
                civic += 1
            else:
                enterprise += 1
        parties = self.store.query("SELECT id, name FROM political_parties ORDER BY id")
        winner = int(parties[0]["id"] if civic >= enterprise else parties[1]["id"])
        if election_type == "legislative":
            total = max(1, civic + enterprise)
            civic_house = round(self.house_seats * civic / total)
            civic_senate = round(self.senate_seats * civic / total)
            for chamber, civic_seats in (("house", civic_house), ("senate", civic_senate)):
                legislators = self.store.query(
                    "SELECT id, seat_number FROM legislators WHERE chamber=? AND active=1 ORDER BY seat_number",
                    (chamber,))
                for index, legislator in enumerate(legislators):
                    party_id = int(parties[0]["id"] if index < civic_seats else parties[1]["id"])
                    self.store.update("legislators", int(legislator["id"]), party_id=party_id,
                                      term_start_tick=tick,
                                      term_end_tick=tick + (self.house_interval if chamber == "house"
                                                            else self.house_interval * 3))
        else:
            self.store.record_metric(tick, "executive_party_id", winner)
        result = {"election_type": election_type, "civic_votes": civic,
                  "enterprise_votes": enterprise, "winner_party_id": winner,
                  "turnout": len(voters)}
        election_id = self.store.insert("elections", tick=tick, election_type=election_type,
                                        results_json=json.dumps(result, sort_keys=True), turnout=len(voters))
        self.store.log_event(tick, "federal_election_held", {"election_id": election_id, **result},
                             phase="NIGHT_CLOSE", subject_type="government", subject_id=1,
                             importance=4.0)
        return result

    def run_nightly(self, tick: int) -> None:
        if not self.enabled:
            return
        for row in self.store.query(
                "SELECT id FROM lobbying_activities WHERE disclosed=0 AND disclosure_tick<=? ORDER BY id",
                (tick,)):
            activity_id = int(row["id"])
            self.store.update("lobbying_activities", activity_id, disclosed=1)
            self.store.log_event(tick, "lobbying_disclosed", {"activity_id": activity_id},
                                 phase="NIGHT_CLOSE", subject_type="lobbying_activity",
                                 subject_id=activity_id, importance=1.5)
        for rule in self.store.query(
                "SELECT * FROM policy_rules WHERE status='pending' AND effective_tick<=? ORDER BY id", (tick,)):
            self.store.update("policy_rules", int(rule["id"]), status="active")
            value = json.loads(rule["value_json"])
            if rule["rule_key"] in {"tax_rate_bps", "unemployment_benefit_cents"}:
                self.store.record_metric(tick, rule["rule_key"], float(value))
            if rule["rule_key"] == "competition.agency_capacity":
                self.store.execute(
                    "UPDATE agencies SET capacity=? WHERE name='Northstar Competition Commission'",
                    (float(value),))
            self.store.log_event(tick, "policy_rule_effective", {"policy_rule_id": int(rule["id"]),
                "rule_key": rule["rule_key"], "value": value, "bill_id": rule["bill_id"]},
                phase="NIGHT_CLOSE", subject_type="bill", subject_id=rule["bill_id"], importance=3.5)
        if self.house_interval > 0 and tick > 0 and tick % self.house_interval == 0:
            if not self.store.query_one(
                    "SELECT 1 FROM elections WHERE tick=? AND election_type='legislative'", (tick,)):
                self.hold_election(tick, "legislative")
        if self.executive_interval > 0 and tick > 0 and tick % self.executive_interval == 0:
            if not self.store.query_one(
                    "SELECT 1 FROM elections WHERE tick=? AND election_type='executive'", (tick,)):
                self.hold_election(tick, "executive")

    def active_policy(self, rule_key: str, default: Any = None) -> Any:
        row = self.store.query_one(
            "SELECT value_json FROM policy_rules WHERE rule_key=? AND status='active' "
            "ORDER BY effective_tick DESC, id DESC LIMIT 1", (rule_key,))
        return json.loads(row["value_json"]) if row else default

    @staticmethod
    def ai_policy_changes(variant: str) -> dict[str, Any]:
        variants = {
            "control": {"competition.hhi_threshold": 1800.0,
                        "competition.delta_threshold": 100.0,
                        "competition.agency_capacity": 1.0,
                        "ai.mandatory_acquisition_disclosure": False,
                        "ai.interoperability_remedy": False},
            "light": {"competition.hhi_threshold": 1800.0,
                      "competition.delta_threshold": 100.0,
                      "competition.agency_capacity": 1.25,
                      "ai.mandatory_acquisition_disclosure": True,
                      "ai.interoperability_remedy": False},
            "strict": {"competition.hhi_threshold": 1500.0,
                       "competition.delta_threshold": 75.0,
                       "competition.agency_capacity": 1.5,
                       "ai.mandatory_acquisition_disclosure": True,
                       "ai.interoperability_remedy": True},
        }
        if variant not in variants:
            raise ValueError(f"unknown AI competition policy variant: {variant}")
        return variants[variant]

    def state(self) -> dict[str, Any]:
        return {
            "parties": [dict(row) for row in self.store.query("SELECT * FROM political_parties ORDER BY id")],
            "legislators": [dict(row) for row in self.store.query(
                "SELECT l.*, a.name, p.name AS party_name FROM legislators l "
                "JOIN agents a ON a.id=l.agent_id JOIN political_parties p ON p.id=l.party_id "
                "WHERE l.active=1 ORDER BY l.chamber,l.seat_number")],
            "bills": [{**dict(row), "policy_changes": json.loads(row["policy_changes_json"] or "{}")}
                      for row in self.store.query("SELECT * FROM bills ORDER BY id DESC")],
            "agencies": [dict(row) for row in self.store.query("SELECT * FROM agencies ORDER BY id")],
        }

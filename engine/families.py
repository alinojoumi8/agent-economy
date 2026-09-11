"""Semantics 17: proposals and recorded assent precede shared residence changes."""
from __future__ import annotations

import json

from .households import HouseholdError, _integer


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class HouseholdDecisions:
    def __init__(self, economy, config=None):
        self.e = economy
        self.store = economy.store
        self.enabled = economy.engine_semantics_version >= 17
        self.p = {"proposal_ttl_days": 30, "formation_interval_days": 30,
                  "scripted_matching": True}
        if self.enabled:
            if config is not None and (not isinstance(config, dict) or set(config) - set(self.p)):
                raise HouseholdError("unknown household decision settings")
            self.p.update(config or {})
            for key in ("proposal_ttl_days", "formation_interval_days"):
                _integer(self.p[key], key, low=1, high=365)
            if not isinstance(self.p["scripted_matching"], bool):
                raise HouseholdError("scripted_matching must be a boolean")

    def _adult(self, actor_id: int):
        if not self.enabled:
            raise HouseholdError("household decisions require semantics 17")
        _integer(actor_id, "actor_id", low=1, high=2**63 - 1)
        actor = self.store.query_one("SELECT * FROM agents WHERE id=?", (actor_id,))
        if (not actor or not actor["alive"] or actor["age"] < 18
                or actor["kind"] != "citizen" or not self.e.households.membership(actor_id)):
            raise HouseholdError("household decision requires a living adult citizen member")
        if self.e.engine_semantics_version >= 21 and not self.e.population.is_available(actor_id):
            raise HouseholdError("household decision requires a local resident")
        return actor

    def partnership(self, actor_id: int):
        return self.store.query_one(
            "SELECT * FROM partnerships WHERE ended_tick IS NULL AND (agent_a=? OR agent_b=?)",
            (actor_id, actor_id))

    def _partner_check(self, actor_id: int, partner_id: int) -> None:
        actor, partner = self._adult(actor_id), self._adult(partner_id)
        if actor_id == partner_id or self.partnership(actor_id) or self.partnership(partner_id):
            raise HouseholdError("partnership needs two distinct unpartnered adults")
        if actor["region_id"] is None or actor["region_id"] != partner["region_id"]:
            raise HouseholdError("partners must currently share a region")
        if not self.store.query_one(
                "SELECT 1 FROM social_ties WHERE weight>0 AND "
                "((agent_a=? AND agent_b=?) OR (agent_a=? AND agent_b=?))",
                (actor_id, partner_id, partner_id, actor_id)):
            raise HouseholdError("partnership requires an existing social contact")
        # UNION deduplicates and terminates even on a corrupt historical cycle.
        related = self.store.query_one(
            "WITH RECURSIVE lineage(root,id) AS (VALUES (?,?),(?,?) UNION "
            "SELECT l.root,p.parent_agent_id FROM lineage l JOIN parent_child_relations p "
            "ON p.child_agent_id=l.id) SELECT 1 FROM lineage a JOIN lineage b ON a.id=b.id "
            "WHERE a.root=? AND b.root=? LIMIT 1",
            (actor_id, actor_id, partner_id, partner_id, actor_id, partner_id))
        if related:
            raise HouseholdError("partners cannot share recorded ancestry")

    def _snapshot(self, actor_id: int, kind: str, partner_id=None) -> dict:
        household_ids = {int(self.e.households.membership(actor_id)["household_id"])}
        if partner_id is not None:
            household_ids.add(int(self.e.households.membership(partner_id)["household_id"]))
        homes, adults = [], []
        for household_id in sorted(household_ids):
            home = self.store.query_one("SELECT * FROM households WHERE id=?", (household_id,))
            members = []
            for row in self.store.query(
                    "SELECT m.*,a.alive,a.age,a.region_id FROM household_memberships m "
                    "JOIN agents a ON a.id=m.agent_id WHERE m.household_id=? AND m.left_tick IS NULL ORDER BY m.agent_id",
                    (household_id,)):
                if not row["alive"] or row["region_id"] != home["region_id"]:
                    raise HouseholdError("household residence is awaiting reconciliation")
                person = int(row["agent_id"])
                if self.e.engine_semantics_version >= 21 and not self.e.population.is_available(person):
                    raise HouseholdError("household decisions require all members to be local residents")
                adult = row["age"] >= 18
                if adult:
                    if kind != "separation":
                        self._adult(person)
                    adults.append(person)
                item = {"membership_id": row["id"], "agent_id": person, "role": row["role"],
                        "adult": adult, "guardian_id": self.e.households.guardian_id(person)}
                if kind == "joint_move":
                    item["employment"] = [dict(job) for job in self.store.query(
                        "SELECT id,firm_id,wage_cents FROM employments WHERE agent_id=? AND status='active' ORDER BY id",
                        (person,))]
                members.append(item)
            homes.append({"household_id": household_id, "region_id": home["region_id"], "members": members})
        if kind != "separation" and sum(len(home["members"]) for home in homes) > 128:
            raise HouseholdError("household decision exceeds 128 members")
        return {"households": homes, "adult_ids": sorted(adults)}

    def _move_check(self, tick, actor_id, destination, snapshot) -> None:
        _integer(destination, "destination_region_id", low=1, high=2**63 - 1)
        _, reason = self.e.regions._qualified_migration_option(tick, actor_id, destination)
        if reason:
            raise HouseholdError(reason)
        for home in snapshot["households"]:
            for member in home["members"]:
                person = member["agent_id"]
                if self.e.regions._agent_credit_exposure(person):
                    raise HouseholdError("all household members must resolve credit exposure before moving")
                if self.store.query_one("SELECT 1 FROM migrations WHERE agent_id=? AND status='pending'", (person,)):
                    raise HouseholdError("a household member already has an individual move pending")

    def _result(self, row, *, ok=True):
        return {"ok": ok, "household_decision_id": int(row["id"]),
                "status": row["status"], "reason": row["reason"]}

    def _event(self, tick, kind, actor_id, decision_id, *, phase="EXECUTION", **payload):
        self.store.log_event(tick, kind, {"agent_id": actor_id, "household_decision_id": decision_id, **payload},
                             phase=phase, subject_type="agent", subject_id=actor_id, importance=1.5)

    def _finish(self, tick, row, status, reason="", *, phase="EXECUTION"):
        self.store.update("household_decisions", row["id"], status=status, reason=reason, settled_tick=tick)
        self._event(tick, "household_decision_" + status, row["actor_id"], row["id"], phase=phase)
        return self._result(self.store.query_one("SELECT * FROM household_decisions WHERE id=?", (row["id"],)))

    def propose(self, tick, actor_id, kind, request_key, *, partner_id=None, destination_region_id=None):
        self._adult(actor_id)
        _integer(tick, "tick", low=0, high=2**63 - 1)
        if not isinstance(request_key, str) or not request_key.strip() or len(request_key) > 96:
            raise HouseholdError("request_key must be nonblank and at most 96 characters")
        if kind not in {"partnership", "joint_move", "separation"}:
            raise HouseholdError("unknown household decision kind")
        with self.store.savepoint("household_proposal"):
            existing = self.store.query_one("SELECT * FROM household_decisions WHERE actor_id=? AND request_key=?",
                                            (actor_id, request_key))
            if existing:
                if (existing["kind"], existing["partner_id"], existing["destination_region_id"]) != (kind, partner_id, destination_region_id):
                    raise HouseholdError("request key already binds different household terms")
                return self._result(existing)
            if kind == "partnership":
                if destination_region_id is not None:
                    raise HouseholdError("partnership cannot include a destination")
                self._partner_check(actor_id, partner_id)
            elif partner_id is not None or (kind == "separation" and destination_region_id is not None):
                raise HouseholdError("unexpected household proposal terms")
            snapshot = self._snapshot(actor_id, kind, partner_id)
            if kind == "joint_move":
                self._move_check(tick, actor_id, destination_region_id, snapshot)
            # A household cannot silently participate in competing decisions.
            self.reconcile(tick, phase="EXECUTION")
            if kind != "separation":
                for pending in self.store.query("SELECT snapshot_json FROM household_decisions WHERE status IN ('pending','agreed')"):
                    if set(json.loads(pending["snapshot_json"])["adult_ids"]) & set(snapshot["adult_ids"]):
                        raise HouseholdError("an affected adult already has a household decision pending")
            decision_id = self.store.insert("household_decisions", actor_id=actor_id, request_key=request_key,
                kind=kind, partner_id=partner_id, destination_region_id=destination_region_id,
                created_tick=tick, expires_tick=tick + self.p["proposal_ttl_days"],
                snapshot_json=_json(snapshot), status="pending")
            self.store.insert("household_assents", decision_id=decision_id, actor_id=actor_id, decision="accept", tick=tick)
            row = self.store.query_one("SELECT * FROM household_decisions WHERE id=?", (decision_id,))
            self._event(tick, "household_decision_proposed", actor_id, decision_id, decision_kind=kind)
            if kind == "separation":
                self._separate(tick, row, snapshot)
                return self._finish(tick, row, "applied")
            if snapshot["adult_ids"] == [actor_id]:
                return self._finish(tick, row, "agreed")
            return self._result(row)

    def _current(self, row, tick) -> str:
        if tick < row["created_tick"]:
            return "decision cannot precede its proposal"
        if tick >= row["expires_tick"]:
            return "proposal expired"
        try:
            self._adult(row["actor_id"])
            if row["kind"] == "partnership":
                self._partner_check(row["actor_id"], row["partner_id"])
            if _json(self._snapshot(row["actor_id"], row["kind"], row["partner_id"])) != row["snapshot_json"]:
                return "household terms changed; a new proposal is required"
            if row["kind"] == "joint_move":
                self._move_check(row["created_tick"], row["actor_id"], row["destination_region_id"], json.loads(row["snapshot_json"]))
        except HouseholdError as exc:
            return str(exc)
        return ""

    def respond(self, tick, actor_id, decision_id, decision):
        self._adult(actor_id)
        _integer(tick, "tick", low=0, high=2**63 - 1)
        _integer(decision_id, "household_decision_id", low=1, high=2**63 - 1)
        if decision not in {"accept", "reject"}:
            raise HouseholdError("household response must accept or reject")
        with self.store.savepoint("household_response"):
            row = self.store.query_one("SELECT * FROM household_decisions WHERE id=?", (decision_id,))
            if not row or actor_id not in json.loads(row["snapshot_json"])["adult_ids"]:
                raise HouseholdError("actor is not an affected adult in this proposal")
            if tick < row["created_tick"]:
                raise HouseholdError("response cannot precede proposal")
            prior = self.store.query_one("SELECT decision FROM household_assents WHERE decision_id=? AND actor_id=?", (decision_id, actor_id))
            if prior:
                if prior["decision"] != decision:
                    raise HouseholdError("recorded assent cannot be rewritten; separate or cancel instead")
                return self._result(row)
            if row["status"] != "pending":
                raise HouseholdError("household decision is no longer pending")
            reason = self._current(row, tick)
            if reason:
                return self._finish(tick, row, "expired" if tick >= row["expires_tick"] else "cancelled", reason)
            self.store.insert("household_assents", decision_id=decision_id, actor_id=actor_id, decision=decision, tick=tick)
            self._event(tick, "household_assent_recorded", actor_id, decision_id, decision=decision)
            if decision == "reject":
                return self._finish(tick, row, "rejected", "an affected adult declined")
            snapshot = json.loads(row["snapshot_json"])
            count = self.store.scalar("SELECT COUNT(*) FROM household_assents WHERE decision_id=? AND decision='accept'", (decision_id,))
            if count == len(snapshot["adult_ids"]):
                if row["kind"] == "partnership":
                    self._merge(tick, row, snapshot)
                    return self._finish(tick, row, "applied")
                return self._finish(tick, row, "agreed")
            return self._result(row)

    def cancel(self, tick, actor_id, decision_id):
        self._adult(actor_id)
        _integer(tick, "tick", low=0, high=2**63 - 1)
        _integer(decision_id, "household_decision_id", low=1, high=2**63 - 1)
        with self.store.savepoint("household_cancel"):
            row = self.store.query_one("SELECT * FROM household_decisions WHERE id=?", (decision_id,))
            if not row or actor_id not in json.loads(row["snapshot_json"])["adult_ids"]:
                raise HouseholdError("actor is not an affected adult")
            if tick < row["created_tick"]:
                raise HouseholdError("cancellation cannot precede proposal")
            if row["status"] not in {"pending", "agreed"}:
                return self._result(row)
            return self._finish(tick, row, "cancelled", "an affected adult withdrew")

    def _move_members(self, tick, members, destination, reason):
        for member in members:
            current = self.e.households.membership(member["agent_id"])
            if current["household_id"] == destination:
                continue
            if tick < current["joined_tick"]:
                raise HouseholdError("residence change cannot precede membership")
            self.store.update("household_memberships", current["id"], left_tick=tick, end_reason=reason)
            self.store.insert("household_memberships", household_id=destination,
                              agent_id=member["agent_id"], role=current["role"], joined_tick=tick)
            self.e.households._dissolve_empty(tick, current["household_id"])

    def _refresh_city(self, tick):
        if self.e.city.enabled:
            self.e.city._sync_routine_leases(tick)
            self.e.city.establish_effective_presence(tick)

    def _merge(self, tick, row, snapshot):
        destination = min(home["household_id"] for home in snapshot["households"])
        for home in snapshot["households"]:
            self._move_members(tick, home["members"], destination, "partnership_formation")
        a, b = sorted((row["actor_id"], row["partner_id"]))
        self.store.insert("partnerships", agent_a=a, agent_b=b,
                          decision_id=row["id"], started_tick=tick)
        self.e.households.reconcile_custody(tick)
        self._refresh_city(tick)
        self._event(tick, "partnership_formed", a, row["id"],
                    partner_id=b, household_id=destination)

    def _end_partnership(self, tick, partnership, reason, *, phase="EXECUTION"):
        if tick < partnership["started_tick"]:
            raise HouseholdError("partnership cannot end before formation")
        self.store.update("partnerships", partnership["id"], ended_tick=tick, end_reason=reason)
        self._event(tick, "partnership_ended", partnership["agent_a"], partnership["decision_id"],
                    partner_id=partnership["agent_b"], reason=reason, phase=phase)

    def _separate(self, tick, row, snapshot):
        actor_id = row["actor_id"]
        relationship = self.partnership(actor_id)
        if relationship:
            self._end_partnership(tick, relationship, "adult_separation")
        home = snapshot["households"][0]
        departing = [m for m in home["members"] if m["agent_id"] == actor_id
                     or (not m["adult"] and m["guardian_id"] == actor_id)]
        destination = home["household_id"]
        if len(departing) < len(home["members"]):
            destination = self.store.insert("households", region_id=home["region_id"], formed_tick=tick,
                                            policy="guardian_basic_needs_v1")
            self._move_members(tick, departing, destination, "adult_separation_with_wards")
        self.e.households.reconcile_custody(tick)
        for pending in self.store.query("SELECT * FROM household_decisions WHERE status IN ('pending','agreed') AND id<>?", (row["id"],)):
            if actor_id in json.loads(pending["snapshot_json"])["adult_ids"]:
                self._finish(tick, pending, "cancelled", "an affected adult separated")
        self.reconcile(tick, phase="EXECUTION")
        self._refresh_city(tick)
        self._event(tick, "household_separated", actor_id, row["id"],
                    household_id=destination, previous_household_id=home["household_id"],
                    policy="primary_minor_wards_accompany_v1")

    def pending_interests(self, agent_id):
        """Unsettled consent snapshots that name this person or their custody."""
        return self.store.query(
            "SELECT d.* FROM household_decisions d WHERE d.status IN ('pending','agreed') "
            "AND (d.actor_id=? OR d.partner_id=? OR EXISTS ("
            "SELECT 1 FROM json_each(d.snapshot_json,'$.households') h, "
            "json_each(h.value,'$.members') m WHERE json_extract(m.value,'$.agent_id')=? "
            "OR json_extract(m.value,'$.guardian_id')=?)) ORDER BY d.id",
            (agent_id, agent_id, agent_id, agent_id))

    def end_for_death(self, tick, row):
        if tick < row["created_tick"]:
            raise HouseholdError("death cannot precede the inventoried family proposal")
        return self._finish(tick, row, "cancelled", "person_died", phase="NIGHT_CLOSE")

    def pending_deceased_participant(self):
        """Check active requests once, even after many generations of estates."""
        if self.e.engine_semantics_version < 20:
            return None
        return self.store.scalar(
            "WITH pending AS (SELECT * FROM household_decisions WHERE status IN ('pending','agreed')), "
            "people AS (SELECT actor_id AS person FROM pending UNION ALL SELECT partner_id FROM pending "
            "UNION ALL SELECT json_extract(m.value,'$.agent_id') FROM pending d, "
            "json_each(d.snapshot_json,'$.households') h,json_each(h.value,'$.members') m "
            "UNION ALL SELECT json_extract(m.value,'$.guardian_id') FROM pending d, "
            "json_each(d.snapshot_json,'$.households') h,json_each(h.value,'$.members') m) "
            "SELECT c.deceased_agent_id FROM people p JOIN estate_cases c ON c.deceased_agent_id=p.person LIMIT 1")

    def invalidate_for_population_movement(self, tick, adult_ids, movement_id):
        """End stale local agreements without ending the underlying kinship."""
        if self.e.engine_semantics_version < 21:
            raise HouseholdError("population movement requires semantics 21")
        pending = {}
        for adult in adult_ids:
            pending.update({row["id"]: row for row in self.pending_interests(adult)})
        for identity in sorted(pending):
            self._finish(tick, pending[identity], "cancelled",
                         f"population_movement:{movement_id}", phase="NIGHT_CLOSE")

    def reconcile(self, tick, *, phase="NIGHT_CLOSE"):
        """Close obsolete agreements without inferring fresh consent."""
        if not self.enabled:
            return
        with self.store.savepoint("household_decision_reconcile"):
            for partnership in self.store.query("SELECT * FROM partnerships WHERE ended_tick IS NULL ORDER BY id"):
                a, b = partnership["agent_a"], partnership["agent_b"]
                alive = self.store.scalar("SELECT COUNT(*) FROM agents WHERE id IN (?,?) AND alive=1", (a, b))
                ma, mb = self.e.households.membership(a), self.e.households.membership(b)
                if alive != 2:
                    self._end_partnership(tick, partnership, "death", phase=phase)
                elif not ma or not mb or ma["household_id"] != mb["household_id"]:
                    self._end_partnership(tick, partnership, "residence_separation", phase=phase)
            for row in self.store.query("SELECT * FROM household_decisions WHERE status IN ('pending','agreed') ORDER BY id"):
                # A separation is applied inside its creating transaction.
                if row["kind"] == "separation":
                    continue
                reason = self._current(row, tick)
                if reason:
                    self._finish(tick, row, "expired" if tick >= row["expires_tick"] else "cancelled", reason, phase=phase)

    def run_nightly(self, tick):
        if not self.enabled:
            return
        self.reconcile(tick)
        for row in self.store.query("SELECT * FROM household_decisions WHERE kind='joint_move' AND status='agreed' ORDER BY id"):
            last_assent = self.store.scalar("SELECT MAX(tick) FROM household_assents WHERE decision_id=?", (row["id"],))
            if tick <= last_assent:
                continue
            with self.store.savepoint("joint_household_move"):
                snapshot = json.loads(row["snapshot_json"])
                destination = row["destination_region_id"]
                currency = self.e.regions.currency_for_region(destination)
                for home in snapshot["households"]:
                    for member in home["members"]:
                        actor = member["agent_id"]
                        wallet = self.e.regions._wallet("agent", actor, currency, create=True)
                        self.store.execute("UPDATE employments SET status='ended',end_tick=? WHERE agent_id=? AND status='active'", (tick, actor))
                        self.store.update("agents", actor, region_id=destination, checking_account_id=wallet, employer_id=None)
                        migration = self.store.insert("migrations", agent_id=actor,
                            origin_region_id=home["region_id"], destination_region_id=destination,
                            requested_tick=row["created_tick"], completed_tick=tick, status="completed",
                            reason=f"household_decision:{row['id']}")
                        self._event(tick, "agent_migrated", actor, row["id"],
                                    migration_id=migration, destination_region_id=destination,
                                    origin_region_id=home["region_id"], currency_code=currency, phase="NIGHT_CLOSE")
                    self.store.update("households", home["household_id"], region_id=destination)
                self._refresh_city(tick)
                self._finish(tick, row, "applied", phase="NIGHT_CLOSE")

    def decision_context(self, actor_id, tick, migration_options=()):
        """Bounded private facts and actions shared by native and external citizens."""
        if not self.enabled:
            return None
        try:
            self._adult(actor_id)
        except HouseholdError:
            return None
        pending, actions, blocked = [], [], False
        for row in self.store.query("SELECT * FROM household_decisions WHERE status IN ('pending','agreed') AND created_tick<=? ORDER BY id", (tick,)):
            snapshot = json.loads(row["snapshot_json"])
            if actor_id not in snapshot["adult_ids"] or self._current(row, tick):
                continue
            blocked = True
            assent = self.store.query_one("SELECT decision FROM household_assents WHERE decision_id=? AND actor_id=?", (row["id"], actor_id))
            item = {"household_decision_id": row["id"], "kind": row["kind"], "proposer_id": row["actor_id"],
                    "partner_id": row["partner_id"], "destination_region_id": row["destination_region_id"],
                    "adult_count": len(snapshot["adult_ids"]),
                    "member_count": sum(len(h["members"]) for h in snapshot["households"]),
                    "prospective_members": [{key: m[key] for key in ("agent_id", "role", "guardian_id")}
                                             for h in snapshot["households"] for m in h["members"]],
                    "expires_tick": row["expires_tick"], "status": row["status"], "own_assent": assent["decision"] if assent else None}
            if row["kind"] == "joint_move":
                item["own_employment_ending"] = next(m["employment"] for h in snapshot["households"] for m in h["members"] if m["agent_id"] == actor_id)
            pending.append(item)
            if not assent and row["status"] == "pending":
                for response in ("accept", "reject"):
                    actions.append({"type": "respond_household", "household_decision_id": row["id"], "decision": response})
            actions.append({"type": "cancel_household_proposal", "household_decision_id": row["id"]})
        candidates = []
        if not blocked and not self.partnership(actor_id):
            ties = self.store.query(
                "SELECT CASE WHEN agent_a=? THEN agent_b ELSE agent_a END AS contact,MAX(weight) AS weight "
                "FROM social_ties WHERE (agent_a=? OR agent_b=?) AND weight>0 GROUP BY contact ORDER BY weight DESC,contact LIMIT 32",
                (actor_id, actor_id, actor_id))
            for tie in ties:
                contact = int(tie["contact"])
                try:
                    self._partner_check(actor_id, contact)
                    prospective = self._snapshot(actor_id, "partnership", contact)
                    other_home = self.e.households.membership(contact)["household_id"]
                    if any(other_home == h["household_id"] for p in self.store.query(
                            "SELECT snapshot_json FROM household_decisions WHERE status IN ('pending','agreed')")
                           for h in json.loads(p["snapshot_json"])["households"]):
                        continue
                except HouseholdError:
                    continue
                action = {"type": "propose_partnership", "partner_id": contact,
                          "request_key": f"partnership:{tick}:{contact}"}
                candidates.append({"agent_id": contact, "action": action,
                    "adult_count": len(prospective["adult_ids"]),
                    "member_count": sum(len(h["members"]) for h in prospective["households"])})
                actions.append(action)
                if len(candidates) == 4:
                    break
        if not blocked:
            for option in list(migration_options)[:4]:
                destination = option["destination_region_id"]
                try:
                    self._move_check(tick, actor_id, destination, self._snapshot(actor_id, "joint_move"))
                except HouseholdError:
                    continue
                actions.append({"type": "propose_household_move", "destination_region_id": destination,
                                "request_key": f"household_move:{tick}:{destination}"})
        relationship = self.partnership(actor_id)
        actions.append({"type": "separate_household", "request_key": f"separation:{tick}"})
        return {"policy": "mutual_household_decisions_v1", "pending": pending,
                "partner_id": next((relationship[key] for key in ("agent_a", "agent_b") if relationship[key] != actor_id), None) if relationship else None,
                "member_count": sum(len(h["members"]) for h in self._snapshot(actor_id, "separation")["households"]),
                "partnership_id": relationship["id"] if relationship else None,
                "candidates": candidates, "eligible_actions": actions,
                "scripted_matching": self.p["scripted_matching"],
                "formation_day": tick > 0 and (tick - actor_id) % self.p["formation_interval_days"] == 0,
                "terms": "Personal ownership is unchanged. Every affected adult must assent. "
                         "A joint move ends your listed employment; balances stay in their existing currencies. "
                         "Separation takes your primary minor wards with you. Care time and full estates remain unimplemented."}

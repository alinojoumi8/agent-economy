"""Effective business stewardship, separate from founder and share ownership."""
from __future__ import annotations

import json


def operating_surface(institution):
    control = getattr(institution, "business_control", None)
    return (control.table, control.column) if control is not None else ("firms", "founder_agent_id")


def operator_at(store, firm_id, tick=None, *, enabled=None):
    """Pure selected-tick lookup for both engine and read-only projections."""
    if enabled is None:
        config = json.loads(store.scalar("SELECT config_json FROM run_meta WHERE id=1", default="{}") or "{}")
        enabled = int(config.get("engine_semantics_version", 1)) >= 20
    firm = store.query_one("SELECT * FROM firms WHERE id=?", (firm_id,))
    if firm is None or (tick is not None and tick < firm["founded_tick"]):
        return None
    if enabled:
        if firm["bankrupt_tick"] is not None and (tick is None or tick >= firm["bankrupt_tick"]):
            return None
        clause = "ended_tick IS NULL" if tick is None else "started_tick<=? AND (ended_tick IS NULL OR ended_tick>?)"
        params = (firm_id,) if tick is None else (firm_id, tick, tick)
        row = store.query_one("SELECT steward_agent_id FROM firm_stewardships WHERE firm_id=? AND " + clause
                              + " ORDER BY started_tick DESC,id DESC LIMIT 1", params)
        if row is not None:
            return row["steward_agent_id"]
    return firm["founder_agent_id"]


def operated_firms_at(store, agent_id, tick):
    config = json.loads(store.scalar("SELECT config_json FROM run_meta WHERE id=1", default="{}") or "{}")
    if int(config.get("engine_semantics_version", 1)) < 20:
        return store.query("SELECT id FROM firms WHERE founder_agent_id=? AND founded_tick<=?", (agent_id, tick))
    return store.query(
        "SELECT f.id FROM firms f LEFT JOIN firm_stewardships s ON s.firm_id=f.id AND s.started_tick<=? "
        "AND (s.ended_tick IS NULL OR s.ended_tick>?) WHERE f.founded_tick<=? "
        "AND (f.bankrupt_tick IS NULL OR f.bankrupt_tick>?) "
        "AND CASE WHEN s.id IS NULL THEN f.founder_agent_id ELSE s.steward_agent_id END=? ORDER BY f.id",
        (tick, tick, tick, tick, agent_id))


class BusinessControlError(RuntimeError):
    """A stewardship transition would lose or invent operating authority."""


class BusinessControl:
    def __init__(self, economy):
        self.e = economy
        self.store = economy.store
        self.enabled = economy.engine_semantics_version >= 20
        self.table = "firm_operations" if self.enabled else "firms"
        self.column = "operator_agent_id" if self.enabled else "founder_agent_id"

    def operated_firms(self, agent_id):
        return self.store.query(
            f"SELECT * FROM {self.table} WHERE {self.column}=? "
            "AND status IN ('private','listed') ORDER BY id", (agent_id,))

    def operator_at(self, firm_id, tick=None):
        return operator_at(self.store, firm_id, tick, enabled=self.enabled)

    def controls(self, actor_id, firm_id):
        firm = self.store.query_one("SELECT status FROM firms WHERE id=?", (firm_id,))
        actor = self.store.query_one("SELECT * FROM agents WHERE id=?", (actor_id,))
        if firm is None or firm["status"] == "bankrupt" or actor is None or not actor["alive"]:
            return False
        if self.enabled and int(actor["age"]) < 18:
            return False
        if not self._local_candidate(actor_id):
            return False
        if self.operator_at(firm_id) == actor_id:
            capacity = (self.store.scalar("SELECT capacity FROM firm_stewardships WHERE firm_id=? AND ended_tick IS NULL", (firm_id,))
                        if self.enabled else None)
            if capacity != "estate" or self.successor(firm_id)[0] == actor_id:
                return True
        return bool(actor["employer_id"] == firm_id and actor["role"] in ("manager", "founder")
                    and self.store.scalar("SELECT 1 FROM employments WHERE agent_id=? AND firm_id=? "
                                          "AND status='active' LIMIT 1", (actor_id, firm_id)))

    def _record_interval(self, tick, firm_id, steward_id, capacity, *, started_tick=None,
                         beneficiary_id=None, death_event_id=None):
        values = dict(firm_id=firm_id, steward_agent_id=steward_id, capacity=capacity,
                      started_tick=tick if started_tick is None else started_tick,
                      beneficiary_id=beneficiary_id, death_event_id=death_event_id)
        event = self.store.log_event(tick, "business_stewardship_recorded", values,
            phase="NIGHT_CLOSE", subject_type="firm", subject_id=firm_id)
        return self.store.insert("firm_stewardships", **values, recorded_event_id=event)

    def _local_candidate(self, actor_id):
        return self.e.engine_semantics_version < 21 or self.e.population.is_available(actor_id)

    def release_unavailable(self, tick, movement_id):
        """Replace unavailable operators after every group member has departed."""
        if self.e.engine_semantics_version < 21:
            raise BusinessControlError("population succession requires Semantics 21")
        for firm in self.store.query("SELECT id,operator_agent_id FROM firm_operations "
                "WHERE status IN ('private','listed') AND operator_agent_id IS NOT NULL ORDER BY id"):
            previous = firm["operator_agent_id"]
            if self._local_candidate(previous):
                continue
            successor, capacity, beneficiary = self.successor(firm["id"])
            self.replace(tick, firm["id"], successor, capacity=capacity, beneficiary_id=beneficiary)
            self.store.log_event(tick, "business_steward_changed", {
                "firm_id": firm["id"], "previous_agent_id": previous, "steward_agent_id": successor,
                "capacity": capacity, "beneficiary_id": beneficiary, "reason": "population_departure",
                "movement_id": movement_id}, phase="NIGHT_CLOSE", subject_type="firm", subject_id=firm["id"])

    def replace(self, tick, firm_id, steward_id, *, capacity, beneficiary_id=None, death_event_id=None):
        if not self.enabled:
            raise BusinessControlError("business succession requires Semantics 20")
        firm = self.store.query_one("SELECT * FROM firms WHERE id=?", (firm_id,))
        if firm is None or firm["status"] == "bankrupt":
            raise BusinessControlError("business is unavailable for stewardship")
        if steward_id is not None:
            actor = self.store.query_one("SELECT * FROM agents WHERE id=?", (steward_id,))
            if actor is None or not actor["alive"] or actor["age"] < 18:
                raise BusinessControlError("business steward must be a living adult")
            if not self._local_candidate(steward_id):
                raise BusinessControlError("business steward must be locally available")
        with self.store.savepoint("business_stewardship"):
            previous = self.store.query_one(
                "SELECT * FROM firm_stewardships WHERE firm_id=? AND ended_tick IS NULL", (firm_id,))
            if previous is None:
                prior_id = self._record_interval(tick, firm_id, firm["founder_agent_id"], "founder",
                                                 started_tick=firm["founded_tick"])
                previous = self.store.query_one("SELECT * FROM firm_stewardships WHERE id=?", (prior_id,))
            if tick < previous["started_tick"]:
                raise BusinessControlError("stewardship cannot travel backwards in time")
            if (previous["steward_agent_id"] == steward_id and previous["capacity"] == capacity
                    and previous["beneficiary_id"] == beneficiary_id):
                return previous["id"]
            self.store.update("firm_stewardships", previous["id"], ended_tick=tick)
            return self._record_interval(tick, firm_id, steward_id, capacity,
                                         beneficiary_id=beneficiary_id, death_event_id=death_event_id)

    def successor(self, firm_id):
        """Prefer an adult shareholder, then a minor's guardian, then a manager.

        Share quantities select a steward; this never transfers beneficial assets
        to that steward or treats a guardian as the child's economic owner.
        """
        holders = self.store.query(
            "SELECT s.holder_id,s.qty,a.age FROM shares s JOIN agents a ON a.id=s.holder_id "
            "WHERE s.firm_id=? AND s.holder_type='agent' AND s.qty>0 AND a.alive=1 "
            "ORDER BY s.qty DESC,s.holder_id", (firm_id,))
        for holder in holders:
            if holder["age"] >= 18 and self._local_candidate(holder["holder_id"]):
                return holder["holder_id"], "shareholder", None
        representative = self.e.estate_securities.operator_for(firm_id)
        if representative is not None and self._local_candidate(representative):
            return representative, "estate", None
        for holder in holders:
            if holder["age"] >= 18:
                continue
            guardian = self.store.query_one(
                "SELECT a.id FROM guardianships g JOIN agents a ON a.id=g.guardian_agent_id "
                "WHERE g.child_agent_id=? AND g.ended_tick IS NULL AND a.alive=1 AND a.age>=18 "
                "ORDER BY a.id LIMIT 1", (holder["holder_id"],))
            if guardian and self._local_candidate(guardian["id"]):
                return guardian["id"], "guardian", holder["holder_id"]
        if self.e.engine_semantics_version >= 21:
            for manager in self.store.query(
                    "SELECT a.id FROM agents a JOIN employments e ON e.agent_id=a.id "
                    "WHERE e.firm_id=? AND e.status='active' AND a.alive=1 AND a.age>=18 "
                    "AND a.employer_id=? AND a.role IN ('manager','founder') ORDER BY a.id", (firm_id, firm_id)):
                if self._local_candidate(manager["id"]):
                    return manager["id"], "employee", None
            return None, "vacant", None
        manager = self.store.query_one(
            "SELECT a.id FROM agents a JOIN employments e ON e.agent_id=a.id "
            "WHERE e.firm_id=? AND e.status='active' AND a.alive=1 AND a.age>=18 "
            "AND a.employer_id=? AND a.role IN ('manager','founder') ORDER BY a.id LIMIT 1", (firm_id, firm_id))
        return (manager["id"], "employee", None) if manager else (None, "vacant", None)

    def on_death(self, tick, agent_id, death_event_id):
        """Run after share disposition, death and custody reconciliation."""
        if not self.enabled:
            return
        for firm in self.operated_firms(agent_id):
            successor, capacity, beneficiary = self.successor(firm["id"])
            self.replace(tick, firm["id"], successor, capacity=capacity,
                         beneficiary_id=beneficiary, death_event_id=death_event_id)
            self.store.log_event(tick, "business_steward_changed", {
                "firm_id": firm["id"], "previous_agent_id": agent_id,
                "steward_agent_id": successor, "capacity": capacity,
                "beneficiary_id": beneficiary, "death_event_id": death_event_id,
            }, phase="NIGHT_CLOSE", subject_type="firm", subject_id=firm["id"])

    def distribute_shares(self, tick, agent_id, beneficiaries, *, distribution_key="death", firm_id=None, allow_deceased=False):
        """Distribute whole securities by declared positive integer weights."""
        if not self.enabled:
            raise BusinessControlError("share succession requires Semantics 20")
        beneficiaries = sorted(beneficiaries, key=lambda pair: (pair[0] is None, pair[0] or 0))
        if (not beneficiaries or len({person for person, _ in beneficiaries}) != len(beneficiaries)
                or any(isinstance(weight, bool) or not isinstance(weight, int) or weight<=0
                       for _, weight in beneficiaries)):
            raise BusinessControlError("inheritance weights must be distinct and positive")
        for person, _ in beneficiaries:
            if person is not None and (person == agent_id or (not self.store.scalar(
                    "SELECT alive FROM agents WHERE id=?", (person,)) and not (allow_deceased and self.store.scalar(
                    "SELECT id FROM estate_cases WHERE deceased_agent_id=?", (person,))))):
                raise BusinessControlError("share beneficiary must be a different living person")
        denominator = sum(weight for _, weight in beneficiaries)
        with self.store.savepoint("estate_share_distribution"):
            self.store.execute("UPDATE orders SET status='cancelled' WHERE agent_id=? "
                               "AND (? IS NULL OR firm_id=?) AND status IN ('open','partial')", (agent_id, firm_id, firm_id))
            if firm_id is None:
                self.e.regions.cancel_fx_orders(tick, agent_id)
                self.store.execute("UPDATE ipo_bids SET status='cancelled' WHERE bidder_agent_id=? AND status='open'", (agent_id,))
            for holding in self.store.query("SELECT * FROM shares WHERE holder_type='agent' AND holder_id=? "
                    "AND (? IS NULL OR firm_id=?) ORDER BY firm_id", (agent_id, firm_id, firm_id)):
                total = int(holding["qty"])
                if total < 0:
                    raise BusinessControlError("a short security position needs an explicit estate liability")
                if not total:
                    continue
                allocations = [total * weight // denominator for _, weight in beneficiaries]
                priority = sorted(range(len(beneficiaries)), key=lambda i: (-(total * beneficiaries[i][1] % denominator), i))
                for i in priority[:total-sum(allocations)]:
                    allocations[i] += 1
                self.e.exchange._adjust_shares(holding["firm_id"], "agent", agent_id, -total)
                for (person, _), qty in zip(beneficiaries, allocations):
                    if not qty:
                        continue
                    owner_type = "system" if person is None else "agent"
                    self.e.exchange._adjust_shares(holding["firm_id"], owner_type, person or 0, qty)
                    movement = self.store.insert("share_movements", tick=tick, firm_id=holding["firm_id"],
                        from_holder_type="agent", from_holder_id=agent_id, to_holder_type=owner_type,
                        to_holder_id=person or 0, qty=qty, movement_type="estate_inheritance",
                        reference_type="deceased_agent", reference_id=agent_id, amount_cents=0)
                    transfer = self.store.insert("estate_share_transfers", deceased_agent_id=agent_id, tick=tick,
                        firm_id=holding["firm_id"], beneficiary_type=owner_type, beneficiary_id=person,
                        distribution_key=distribution_key, movement_id=movement, former_qty=total, qty=qty)
                    if person is not None and not self.store.scalar("SELECT alive FROM agents WHERE id=?", (person,)):
                        self.e.estate_securities.accept_transfer(tick, transfer)

    def refresh_custody(self, tick):
        if not self.enabled:
            return
        self.e.estate_administration.reconcile(tick)
        self.e.estate_securities.refresh(tick)
        for row in self.store.query("SELECT s.* FROM firm_stewardships s JOIN firms f ON f.id=s.firm_id "
                                    "WHERE s.ended_tick IS NULL AND s.capacity IN ('guardian','estate','vacant') "
                                    "AND f.status IN ('private','listed') ORDER BY s.firm_id"):
            valid_guardian = row["capacity"] == "guardian" and self.store.scalar(
                "SELECT 1 FROM guardianships g JOIN agents a ON a.id=g.child_agent_id "
                "JOIN agents caretaker ON caretaker.id=g.guardian_agent_id "
                "JOIN shares s ON s.holder_type='agent' AND s.holder_id=a.id AND s.firm_id=? AND s.qty>0 "
                "WHERE g.child_agent_id=? AND g.guardian_agent_id=? AND g.ended_tick IS NULL "
                "AND a.alive=1 AND a.age<18 AND caretaker.alive=1 AND caretaker.age>=18 LIMIT 1",
                (row["firm_id"], row["beneficiary_id"], row["steward_agent_id"]))
            if valid_guardian and self._local_candidate(row["steward_agent_id"]):
                continue
            successor, capacity, beneficiary = self.successor(row["firm_id"])
            if (successor, capacity, beneficiary) == (row["steward_agent_id"], row["capacity"], row["beneficiary_id"]):
                continue
            self.replace(tick, row["firm_id"], successor, capacity=capacity, beneficiary_id=beneficiary)
            self.store.log_event(tick, "business_steward_changed", {
                "firm_id": row["firm_id"], "previous_agent_id": row["steward_agent_id"],
                "steward_agent_id": successor, "capacity": capacity, "beneficiary_id": beneficiary,
                "reason": "custody_or_adult_eligibility",
            }, phase="NIGHT_CLOSE", subject_type="firm", subject_id=row["firm_id"])

    def check_invariants(self):
        if not self.enabled:
            return
        for row in self.store.query("SELECT deceased_agent_id,firm_id,SUM(qty) total,MIN(former_qty) lo,MAX(former_qty) hi "
                                    "FROM estate_share_transfers GROUP BY deceased_agent_id,firm_id,distribution_key"):
            if row["total"] != row["lo"] or row["lo"] != row["hi"]:
                raise BusinessControlError("inherited security quantities do not reconcile")
        for row in self.store.query("SELECT t.*,m.tick AS movement_tick,m.firm_id AS movement_firm,"
                "m.from_holder_type,m.from_holder_id,m.to_holder_type,m.to_holder_id,m.qty AS movement_qty,"
                "m.movement_type,m.price_cents,m.amount_cents,m.transaction_id FROM estate_share_transfers t "
                "JOIN share_movements m ON m.id=t.movement_id"):
            if (row["tick"] != row["movement_tick"] or row["firm_id"] != row["movement_firm"]
                    or row["from_holder_type"] != "agent" or row["from_holder_id"] != row["deceased_agent_id"]
                    or row["to_holder_type"] != row["beneficiary_type"]
                    or row["to_holder_id"] != (row["beneficiary_id"] or 0)
                    or row["movement_qty"] != row["qty"] or row["movement_type"] != "estate_inheritance"
                    or row["price_cents"] is not None or row["amount_cents"] != 0 or row["transaction_id"] is not None):
                raise BusinessControlError("estate share receipt and cap-table movement disagree")
        previous = {}
        for row in self.store.query("SELECT * FROM firm_stewardships ORDER BY firm_id,started_tick,id"):
            event = self.store.query_one("SELECT * FROM events WHERE id=?", (row["recorded_event_id"],))
            payload = {key: row[key] for key in ("firm_id", "steward_agent_id", "capacity", "started_tick",
                                                "beneficiary_id", "death_event_id")}
            if event is None or event["kind"] != "business_stewardship_recorded" or event["tick"] < row["started_tick"] or (
                    event["subject_type"] != "firm" or event["subject_id"] != row["firm_id"]
                    or json.loads(event["payload_json"]) != payload):
                raise BusinessControlError("business stewardship lacks its recording event")
            prior = previous.get(row["firm_id"])
            if prior is not None and prior["ended_tick"] != row["started_tick"]:
                raise BusinessControlError("business stewardship history has a gap or overlap")
            previous[row["firm_id"]] = row
        if any(row["ended_tick"] is not None for row in previous.values()):
            raise BusinessControlError("business stewardship has no current disposition")

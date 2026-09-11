"""Finite person-days, delivered care, and physical labor for Semantics 18."""
from __future__ import annotations

import json

from .households import _integer
from .ledger import Leg, SYS_COMMODITY


class TimeBudgetError(ValueError):
    pass


class _FailedActivity(Exception):
    def __init__(self, result):
        self.result = result


class DailyTime:
    def __init__(self, economy, config=None):
        self.e = economy
        self.store = economy.store
        self.enabled = economy.engine_semantics_version >= 18
        self.p = {"available_minutes": 960, "normal_workday_minutes": 480,
                  "journey_minutes": 60, "relocation_minutes": 480,
                  "study_minutes": 120, "construction_minutes_per_unit": 60,
                  "appointment_minutes": 480}
        if not self.enabled:
            return
        if config is not None and not isinstance(config, dict):
            raise TimeBudgetError("daily_time must be a mapping")
        if set(config or {}) - set(self.p):
            raise TimeBudgetError("unknown daily_time setting")
        self.p.update(config or {})
        for key, value in self.p.items():
            _integer(value, key, 1, 1440)
        if self.p["relocation_minutes"] > self.p["available_minutes"]:
            raise TimeBudgetError("a relocation must fit the daily budget")

    def _adult(self, agent_id, *, working=False):
        row = self.store.query_one("SELECT * FROM agents WHERE id=?", (agent_id,))
        if not row or not row["alive"] or row["age"] < 18:
            raise TimeBudgetError("a time plan requires a living adult")
        if working and (row["health"] == "critical" or row["retired"]):
            raise TimeBudgetError("this adult cannot work today")
        return row

    def plan_at(self, agent_id, tick):
        return self.store.query_one(
            "SELECT * FROM time_plans WHERE agent_id=? AND effective_tick<=? "
            "ORDER BY effective_tick DESC,id DESC LIMIT 1", (agent_id, tick))

    def eligible_work(self, agent_id):
        employment = [dict(row) for row in self.store.query(
            "SELECT e.id,e.firm_id,'employment' kind FROM employments e JOIN firms f ON f.id=e.firm_id "
            "WHERE e.agent_id=? AND e.status='active' AND f.status IN ('private','listed') ORDER BY e.id", (agent_id,))]
        employed = {row["firm_id"] for row in employment}
        owners = [{"id": row["id"], "firm_id": row["id"], "kind": "owner_work"} for row in self.store.query(
            f"SELECT id FROM {self.e.business_control.table} WHERE {self.e.business_control.column}=? "
            "AND status IN ('private','listed') ORDER BY id", (agent_id,))
            if row["id"] not in employed]
        return employment + owners

    def selected_work(self, agent_id, tick):
        choices = self.eligible_work(agent_id)
        plan = self.plan_at(agent_id, tick)
        if plan and plan["work_firm_id"] is not None:
            return next((row for row in choices if row["firm_id"] == plan["work_firm_id"]), None)
        return choices[0] if choices else None

    def care_targets(self, agent_id, named=None):
        member = self.e.households.membership(agent_id)
        if member is None:
            return []
        rows = self.store.query(
            "SELECT a.id,g.guardian_agent_id FROM agents a JOIN household_memberships m "
            "ON m.agent_id=a.id AND m.left_tick IS NULL LEFT JOIN guardianships g "
            "ON g.child_agent_id=a.id AND g.ended_tick IS NULL "
            "WHERE m.household_id=? AND a.alive=1 AND a.age<18 ORDER BY a.id", (member["household_id"],))
        if self.e.engine_semantics_version >= 21:
            rows = [row for row in rows if self.e.population.is_available(int(row['id']))]
        return [int(row["id"]) for row in rows if
                (row["guardian_agent_id"] == agent_id if named is None else row["id"] in named)]

    def submit_plan(self, tick, agent_id, action):
        if not self.enabled:
            raise TimeBudgetError("time plans require semantics 18")
        self._adult(agent_id)
        if self.e.engine_semantics_version >= 21 and not self.e.population.is_local(agent_id, tick):
            raise TimeBudgetError("outside people cannot submit a local time plan")
        key = action["request_key"]
        if not isinstance(key, str) or not key.strip() or len(key) > 96:
            raise TimeBudgetError("request_key must contain 1 to 96 characters")
        work = _integer(action["work_minutes"], "work_minutes", 0, self.p["available_minutes"])
        care = _integer(action["care_minutes"], "care_minutes", 0, self.p["available_minutes"])
        if work + care > self.p["available_minutes"]:
            raise TimeBudgetError("planned work and care exceed available time")
        named = action.get("care_child_ids")
        if named is not None:
            if not isinstance(named, list) or len(named) > 32 or any(type(x) is not int or x <= 0 for x in named):
                raise TimeBudgetError("care_child_ids must name at most 32 distinct children")
            if len(set(named)) != len(named):
                raise TimeBudgetError("care_child_ids cannot contain duplicates")
            named = sorted(named)
        encoded = json.dumps(named, separators=(",", ":")) if named is not None else None
        firm_id = action.get("work_firm_id")
        if firm_id is not None and (type(firm_id) is not int or firm_id <= 0):
            raise TimeBudgetError("work_firm_id must be a positive integer")
        previous = self.store.query_one("SELECT * FROM time_plans WHERE agent_id=? AND request_key=?", (agent_id, key))
        terms = (work, firm_id, care, encoded)
        if previous:
            if tuple(previous[field] for field in ("work_minutes", "work_firm_id", "care_minutes", "care_targets_json")) != terms:
                raise TimeBudgetError("request_key was already used for different time terms")
            return {"ok": True, "plan_id": previous["id"], "effective_tick": previous["effective_tick"], "idempotent": True}
        if named is not None and set(self.care_targets(agent_id, named)) != set(named):
            raise TimeBudgetError("care targets must be current minor household members")
        if firm_id is not None and not any(row["firm_id"] == firm_id for row in self.eligible_work(agent_id)):
            raise TimeBudgetError("work plan must name an active employment or managed firm")
        with self.store.savepoint("daily_time_plan"):
            plan_id = self.store.insert("time_plans", agent_id=agent_id, request_key=key,
                created_tick=tick, effective_tick=tick + 1, work_minutes=work, work_firm_id=firm_id,
                care_minutes=care, care_targets_json=encoded)
            self.store.log_event(tick, "time_plan_submitted", {"agent_id": agent_id, "plan_id": plan_id,
                "effective_tick": tick + 1, "work_minutes": work, "care_minutes": care},
                phase="EXECUTION", subject_type="agent", subject_id=agent_id)
            return {"ok": True, "plan_id": plan_id, "effective_tick": tick + 1}

    def remaining(self, tick, agent_id):
        day = self.store.query_one("SELECT * FROM time_days WHERE tick=? AND agent_id=?", (tick, agent_id))
        if day is None:
            raise TimeBudgetError("daily time has not been prepared for this person")
        return int(day["available_minutes"] - day["allocated_minutes"])

    def _allocate(self, tick, agent_id, key, kind, minutes, ref_type, ref_id=None, *, delivered=True, request=None):
        if minutes <= 0 or minutes > self.remaining(tick, agent_id):
            raise TimeBudgetError("insufficient daily time")
        return self.store.insert("time_allocations", tick=tick, agent_id=agent_id,
            allocation_key=key, kind=kind, minutes=minutes, delivered_minutes=minutes if delivered else 0,
            reference_type=ref_type, reference_id=ref_id,
            request_json=json.dumps(request or {}, sort_keys=True, separators=(",", ":")))

    def _deliver_care(self, tick, actor_id, targets, offer):
        for child_id in targets:
            need = self.store.query_one("SELECT * FROM child_care_days WHERE tick=? AND child_id=?", (tick, child_id))
            if need is None:
                continue
            minutes = min(offer, need["required_minutes"] - need["delivered_minutes"],
                          self.remaining(tick, actor_id), self.remaining(tick, child_id))
            if minutes <= 0:
                continue
            self._allocate(tick, actor_id, f"care:{child_id}", "care", minutes, "child", child_id)
            self._allocate(tick, child_id, f"care_received:{actor_id}", "care_received", minutes, "caregiver", actor_id)
            self.store.execute("UPDATE child_care_days SET delivered_minutes=delivered_minutes+? WHERE tick=? AND child_id=?",
                               (minutes, tick, child_id))
            self.store.log_event(tick, "child_care_delivered", {"agent_id": actor_id, "child_id": child_id,
                "minutes": minutes, "household_id": need["household_id"]}, phase="NIGHT_CLOSE",
                subject_type="agent", subject_id=actor_id)
            offer -= minutes

    def prepare_day(self, tick):
        if not self.enabled or self.store.query_one("SELECT 1 FROM time_days WHERE tick=? LIMIT 1", (tick,)):
            return
        with self.store.savepoint("prepare_person_day"):
            people = self.store.query("SELECT * FROM agents WHERE alive=1 ORDER BY id")
            if self.e.engine_semantics_version >= 21:
                people = [person for person in people if self.e.population.is_local(person["id"], tick)]
            for person in people:
                plan = self.plan_at(person["id"], tick)
                self.store.insert("time_days", tick=tick, agent_id=person["id"],
                    available_minutes=self.p["available_minutes"], plan_id=plan["id"] if plan else None)
            for child in self.store.query(
                    "SELECT a.id,m.household_id FROM agents a JOIN household_memberships m ON m.agent_id=a.id "
                    "AND m.left_tick IS NULL WHERE a.alive=1 AND a.age<18 ORDER BY a.id"):
                if self.e.engine_semantics_version >= 21 and not self.e.population.is_local(child["id"], tick):
                    continue
                self.store.insert("child_care_days", tick=tick, child_id=child["id"],
                    household_id=child["household_id"], required_minutes=self.e.households.p["care_minutes_per_child"])
            for move in self.store.query("SELECT * FROM migrations WHERE status='completed' AND completed_tick=? ORDER BY id", (tick,)):
                if self.store.query_one("SELECT 1 FROM time_days WHERE tick=? AND agent_id=?", (tick, move["agent_id"])):
                    self._allocate(tick, move["agent_id"], f"relocation:{move['id']}", "travel",
                                   self.p["relocation_minutes"], "migration", move["id"])
            for person in people:
                actor = int(person["id"])
                if person["age"] < 18 or person["health"] == "critical":
                    continue
                if self.e.city.enabled:
                    for appointment in self.store.query("SELECT * FROM service_appointments WHERE applicant_agent_id=? "
                            "AND scheduled_tick=? AND status='scheduled' ORDER BY id", (actor, tick)):
                        need = self.p["appointment_minutes"] + self.p["journey_minutes"]
                        if self.remaining(tick, actor) >= need:
                            self._allocate(tick, actor, f"civic:{appointment['id']}", "civic",
                                self.p["appointment_minutes"], "appointment", appointment["id"], delivered=False)
                            self._allocate(tick, actor, f"civic_journey:{appointment['id']}", "travel",
                                self.p["journey_minutes"], "appointment", appointment["id"], delivered=False)
                    staff = self.store.query_one("SELECT * FROM agency_staff WHERE agent_id=? AND active=1 ORDER BY id LIMIT 1", (actor,))
                    if staff and not person["retired"]:
                        plan = self.plan_at(actor, tick)
                        target = plan["work_minutes"] if plan else self.p["normal_workday_minutes"]
                        minutes = min(target, max(0, self.remaining(tick, actor) - self.p["journey_minutes"]))
                        if minutes:
                            self._allocate(tick, actor, "institution_journey", "travel", self.p["journey_minutes"], "agency", staff["agency_id"])
                            self._allocate(tick, actor, "institution", "institution", minutes, "agency", staff["agency_id"])
            adults = [row for row in people if row["age"] >= 18 and row["health"] != "critical"]
            for explicit in (True, False):
                for person in adults:
                    actor = int(person["id"])
                    plan = self.plan_at(actor, tick)
                    if bool(plan) != explicit:
                        continue
                    named = json.loads(plan["care_targets_json"]) if plan and plan["care_targets_json"] is not None else None
                    offer = plan["care_minutes"] if plan else self.remaining(tick, actor)
                    self._deliver_care(tick, actor, self.care_targets(actor, named), offer)
            for person in adults:
                actor = int(person["id"])
                if person["retired"] or self.store.query_one("SELECT 1 FROM time_allocations WHERE tick=? AND agent_id=? AND kind='institution'", (tick, actor)):
                    continue
                work = self.selected_work(actor, tick)
                if not work or not self.e.firms.founder_present(actor, work["firm_id"], tick):
                    continue
                plan = self.plan_at(actor, tick)
                target = plan["work_minutes"] if plan else self.p["normal_workday_minutes"]
                minutes = min(target, max(0, self.remaining(tick, actor) - self.p["journey_minutes"]))
                if minutes <= 0:
                    continue
                self._allocate(tick, actor, "work_journey", "travel", self.p["journey_minutes"], "firm", work["firm_id"])
                allocation = self._allocate(tick, actor, "work", work["kind"], minutes,
                    "employment" if work["kind"] == "employment" else "firm", work["id"])
                if work["kind"] == "employment":
                    self.e.earned_wages.accrue(tick, allocation)

    def perform(self, tick, agent_id, key, kind, minutes, request, callback):
        """A rejected action cannot retain either its time charge or its effects."""
        try:
            actor = self._adult(agent_id, working=(kind == "construction"))
            if actor["health"] == "critical":
                raise TimeBudgetError("this adult cannot perform the activity today")
            request = {key: value for key, value in request.items()
                       if key not in {"evidence_event_ids", "model_call_id", "rationale_summary"}}
            encoded = json.dumps(request, sort_keys=True, separators=(",", ":"))
            prior = self.store.query_one("SELECT * FROM time_allocations WHERE agent_id=? AND allocation_key=? ORDER BY id LIMIT 1", (agent_id, key))
            if prior:
                if prior["kind"] != kind or prior["request_json"] != encoded:
                    raise TimeBudgetError("activity key was already used for different terms")
                return json.loads(prior["result_json"])
            with self.store.savepoint("perform_timed_activity"):
                allocation = self._allocate(tick, agent_id, key, kind, minutes, kind, request=request)
                result = callback()
                if not result.get("ok"):
                    raise _FailedActivity(result)
                self.store.update("time_allocations", allocation, result_json=json.dumps(result, sort_keys=True, separators=(",", ":")))
                return result
        except _FailedActivity as error:
            return error.result
        except TimeBudgetError as error:
            return {"ok": False, "reason": str(error)}

    def attend(self, tick, agent_id, appointment_id, callback):
        try:
            actor = self._adult(agent_id)
            if actor["health"] == "critical":
                raise TimeBudgetError("this adult cannot attend today")
            with self.store.savepoint("attend_timed_appointment"):
                reservation = self.store.query_one("SELECT * FROM time_allocations WHERE tick=? AND agent_id=? "
                    "AND kind='civic' AND reference_id=?", (tick, agent_id, appointment_id))
                if not reservation:
                    raise TimeBudgetError("appointment has no feasible time reservation today")
                if reservation["result_json"] is not None:
                    return json.loads(reservation["result_json"])
                result = callback()
                if not result.get("ok"):
                    raise _FailedActivity(result)
                self.store.execute("UPDATE time_allocations SET delivered_minutes=minutes WHERE tick=? AND agent_id=? "
                    "AND reference_type='appointment' AND reference_id=?", (tick, agent_id, appointment_id))
                self.store.update("time_allocations", reservation["id"], result_json=json.dumps(result, sort_keys=True, separators=(",", ":")))
                return result
        except _FailedActivity as error:
            return error.result
        except TimeBudgetError as error:
            return {"ok": False, "reason": str(error)}

    def produce(self, tick, firm):
        firm_id = int(firm["id"])
        if self.store.query_one("SELECT 1 FROM firm_labor_days WHERE tick=? AND firm_id=?", (tick, firm_id)):
            return
        with self.store.savepoint("produce_from_delivered_work"):
            employed = int(self.store.scalar("SELECT COALESCE(SUM(a.delivered_minutes),0) FROM time_allocations a "
                "JOIN employments e ON e.id=a.reference_id WHERE a.tick=? AND a.kind='employment' AND e.firm_id=?", (tick, firm_id)))
            owner = int(self.store.scalar("SELECT COALESCE(SUM(delivered_minutes),0) FROM time_allocations "
                "WHERE tick=? AND kind='owner_work' AND reference_id=?", (tick, firm_id)))
            productive = employed or owner
            management = owner if employed else 0
            prod = self.e.firms.product(firm)
            prior = self.store.scalar("SELECT carry_numerator FROM firm_labor_days WHERE firm_id=? AND tick<? ORDER BY tick DESC LIMIT 1", (firm_id, tick), default=0)
            desired, carry = divmod(productive * int(prod["output_per_worker"]) + int(prior), self.p["normal_workday_minutes"])
            unit_cost = max(1, int(prod["base_input_cost_cents"] * self.e.firms.commodity_index()))
            produced = max(0, min(desired, self.e.ledger.balance(firm["account_id"]) // unit_cost))
            self.store.insert("firm_labor_days", tick=tick, firm_id=firm_id, productive_minutes=productive,
                management_minutes=management, desired_units=desired, produced_units=produced, carry_numerator=carry)
            if produced:
                commodity = self.e.ledger.system_account(SYS_COMMODITY, currency_code=str(firm["currency_code"] or "USD"))
                self.e.ledger.post(tick, "production_input", [Leg(firm["account_id"], -produced * unit_cost, "input cost"),
                    Leg(commodity, produced * unit_cost, "commodity purchase")], memo=f"firm {firm_id} produce {produced}")
                self.store.update("firms", firm_id, inventory=int(firm["inventory"]) + produced)
                self.store.log_event(tick, "production", {"firm_id": firm_id, "units": produced,
                    "unit_cost_cents": unit_cost, "productive_minutes": productive}, phase="NIGHT_CLOSE")

    def decision_context(self, agent_id, tick):
        if not self.enabled:
            return None
        day = self.store.query_one("SELECT * FROM time_days WHERE tick=? AND agent_id=?", (tick, agent_id))
        plan = self.plan_at(agent_id, tick + 1)
        member = self.e.households.membership(agent_id)
        care = [dict(row) for row in self.store.query("SELECT *,required_minutes-delivered_minutes unmet_minutes "
            "FROM child_care_days WHERE tick=? AND household_id=? ORDER BY child_id LIMIT 32", (tick, member["household_id"]))] if member else []
        care_needed = len(self.care_targets(agent_id)) * self.e.households.p["care_minutes_per_child"]
        care_offer = min(care_needed, self.p["available_minutes"])
        work_offer = min(self.p["normal_workday_minutes"], max(0, self.p["available_minutes"] - care_offer - self.p["journey_minutes"]))
        offers = [(work_offer, care_offer), (max(0, work_offer - self.p["study_minutes"]), care_offer),
                  (self.p["normal_workday_minutes"], 0)]
        actions = [{"type": "set_time_plan", "request_key": f"time:{tick}:{work}:{care_minutes}",
                    "work_minutes": work, "care_minutes": care_minutes} for work, care_minutes in dict.fromkeys(offers)
                   if work + care_minutes <= self.p["available_minutes"]]
        actor = self.store.query_one("SELECT alive,age FROM agents WHERE id=?", (agent_id,))
        if not actor or not actor["alive"] or actor["age"] < 18:
            actions = []
        result = {"available_minutes": day["available_minutes"] if day else None,
                "remaining_minutes": self.remaining(tick, agent_id) if day else None,
                "allocations": [dict(row) for row in self.store.query("SELECT kind,minutes,delivered_minutes,reference_type,reference_id "
                    "FROM time_allocations WHERE tick=? AND agent_id=? ORDER BY id", (tick, agent_id))],
                "tomorrow_plan": dict(plan) if plan else None, "primary_ward_ids": self.care_targets(agent_id),
                "household_care": care, "eligible_work": self.eligible_work(agent_id)[:32],
                "assumptions": dict(self.p), "plan_effective_tick": tick + 1,
                "eligible_actions": actions,
                "wage_claims": [dict(row) for row in self.store.query("SELECT c.id,c.currency_code,"
                    "c.accrued_cents-c.paid_cents-c.written_off_cents outstanding_cents FROM wage_claims c "
                    "JOIN wage_claim_holders h ON h.claim_id=c.id AND h.ended_tick IS NULL "
                    "WHERE h.owner_type='agent' AND h.owner_id=? AND c.closed_tick IS NULL ORDER BY c.id LIMIT 32", (agent_id,))],
                "wage_claims_are_spendable_cash": False}
        if self.e.engine_semantics_version >= 20:
            for claim in result["wage_claims"]:
                claim["outstanding_cents"] -= self.e.wage_awards.novated(claim["id"])
            result["wage_awards"] = [{"award_id": row["id"], "currency_code": row["currency_code"],
                "outstanding_gross_cents": self.e.legal_awards.remaining(row)} for row in self.store.query(
                    "SELECT a.* FROM legal_awards a JOIN legal_wage_awards w ON w.award_id=a.id "
                    "WHERE a.claimant_type='agent' AND a.claimant_id=? ORDER BY a.id", (agent_id,))]
        return result

    def check_invariants(self):
        bad = self.store.query_one("SELECT d.tick,d.agent_id FROM time_days d LEFT JOIN time_allocations a "
            "ON a.tick=d.tick AND a.agent_id=d.agent_id GROUP BY d.tick,d.agent_id "
            "HAVING d.allocated_minutes<>COALESCE(SUM(a.minutes),0) OR d.allocated_minutes>d.available_minutes LIMIT 1")
        if bad:
            raise TimeBudgetError("daily allocations do not reconcile to available time")
        bad = self.store.query_one("SELECT c.tick,c.child_id FROM child_care_days c WHERE c.delivered_minutes<>"
            "(SELECT COALESCE(SUM(a.delivered_minutes),0) FROM time_allocations a WHERE a.tick=c.tick "
            "AND a.kind='care' AND a.reference_id=c.child_id) OR c.delivered_minutes<>"
            "(SELECT COALESCE(SUM(a.delivered_minutes),0) FROM time_allocations a WHERE a.tick=c.tick "
            "AND a.kind='care_received' AND a.agent_id=c.child_id) LIMIT 1")
        if bad:
            raise TimeBudgetError("delivered child care does not reconcile")

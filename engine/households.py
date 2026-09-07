"""Semantics 15 persistent people and an explicit guardian basic-needs policy.

These records extend agents; they never replace identities or reify legacy
dependent counts. Child care time is a requirement, not an invented delivery.
"""
from __future__ import annotations

import json

from .keyed_random import person_key, stable_key


ADULT_AGE = 18
DAYS_PER_YEAR = 365


class HouseholdError(ValueError):
    """A demographic transition would break canonical identity or membership."""


def _integer(value, name: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise HouseholdError(f"{name} must be an integer between {low} and {high}")
    return value


class Households:
    def __init__(self, economy, config: dict | None = None):
        self.e = economy
        self.store = economy.store
        self.ledger = economy.ledger
        self.enabled = economy.engine_semantics_version >= 15
        self.retirement_age = 65
        self.p = {"child_goods_units": 1, "goods_sector": "food",
                  "care_minutes_per_child": 120, "scheduled_births": []}
        if not self.enabled:
            return
        self.retirement_age = _integer(economy.config.get("lifecycle", {}).get("retirement_age", 65),
                                       "retirement_age", ADULT_AGE, 150)
        for name in ("behavioral_fixture", "spec_closure_fixture"):
            if economy.config.get(name, {}).get("enabled"):
                raise HouseholdError(f"{name} mutates historical genesis; use its recorded pre-15 semantics")
        if config is not None and not isinstance(config, dict):
            raise HouseholdError("households must be a mapping")
        if set(config or {}) - set(self.p):
            raise HouseholdError("unknown households setting")
        self.p.update(config or {})
        _integer(self.p["child_goods_units"], "child_goods_units", 0, 100)
        _integer(self.p["care_minutes_per_child"], "care_minutes_per_child", 0, 1440)
        sector = self.p["goods_sector"]
        if not isinstance(sector, str) or not sector.strip() or sector != sector.strip() or len(sector) > 40:
            raise HouseholdError("goods_sector must be a nonempty sector name of at most 40 characters")
        scheduled = self.p["scheduled_births"]
        if not isinstance(scheduled, list) or len(scheduled) > 1000:
            raise HouseholdError("scheduled_births must be a list with at most 1000 entries")
        seen = set()
        for item in scheduled:
            if not isinstance(item, dict) or set(item) != {"tick", "parent_agent_id"}:
                raise HouseholdError("scheduled birth requires tick and parent_agent_id")
            tick = _integer(item["tick"], "birth tick", 1, 2_147_483_647)
            parent = _integer(item["parent_agent_id"], "parent_agent_id", 1, 2_147_483_647)
            if (tick, parent) in seen:
                raise HouseholdError("duplicate scheduled birth")
            seen.add((tick, parent))

    @staticmethod
    def age_at(birth_tick: int, tick: int) -> int:
        return (int(tick) - int(birth_tick)) // DAYS_PER_YEAR

    def _stage(self, age: int, retired: bool = False) -> str:
        if retired:
            return "retired"
        if age < 6:
            return "child"
        return "school_age" if age < ADULT_AGE else "adult"

    def membership(self, agent_id: int):
        return self.store.query_one(
            "SELECT * FROM household_memberships WHERE agent_id=? AND left_tick IS NULL",
            (agent_id,))

    def register_person(self, tick: int, agent_id: int, origin: str, *, random_key: str | None = None) -> int:
        """Adopt a newly created adult's age basis, without inventing relatives."""
        if not self.enabled:
            return 0
        with self.store.savepoint("register_person"):
            existing = self.store.query_one(
                "SELECT * FROM person_lifecycle WHERE agent_id=?", (agent_id,))
            if existing:
                if existing["origin"] != origin or int(existing["origin_tick"]) != tick:
                    raise HouseholdError("person already has a different origin")
                if (self.e.engine_semantics_version >= 16 and random_key is not None
                        and person_key(self.store, agent_id) != random_key):
                    raise HouseholdError("person already has a different random identity")
                member = self.membership(agent_id)
                return int(member["household_id"]) if member else 0
            agent = self.store.query_one("SELECT * FROM agents WHERE id=?", (agent_id,))
            if not agent or not agent["alive"] or origin not in {"genesis", "arrival", "engine_created"}:
                raise HouseholdError("registration needs a living, newly created person")
            if int(agent["arrived_tick"]) != tick:
                raise HouseholdError("cannot infer an unrecorded historical person origin")
            # A disclosed synthetic within-year age basis. Newborns instead use
            # the exact birth tick and get their first birthday 365 days later.
            day_in_year = (DAYS_PER_YEAR - (int(agent_id) % DAYS_PER_YEAR)) % DAYS_PER_YEAR
            keyed_age = self.e.engine_semantics_version >= 16 and random_key is not None
            if keyed_age:
                day_in_year = int(stable_key("age_offset", random_key).rsplit(":", 1)[1], 16) % DAYS_PER_YEAR
            birth_tick = tick - int(agent["age"]) * DAYS_PER_YEAR - day_in_year
            self.store.insert(
                "person_lifecycle", agent_id=agent_id, origin=origin, origin_tick=tick,
                birth_tick=birth_tick, life_stage=self._stage(int(agent["age"]), bool(agent["retired"])),
                legacy_dependents=int(agent["dependents"]))
            household = self.store.insert(
                "households", region_id=agent["region_id"], formed_tick=tick,
                policy="guardian_basic_needs_v1")
            self.store.insert(
                "household_memberships", household_id=household, agent_id=agent_id,
                role="adult" if int(agent["age"]) >= ADULT_AGE else "dependent", joined_tick=tick)
            payload = {"origin": origin, "birth_tick": birth_tick, "household_id": household,
                       "legacy_dependents": int(agent["dependents"]),
                       "age_basis": "synthetic_origin_offset_v1" if keyed_age else "synthetic_id_offset_v1"}
            if self.e.engine_semantics_version >= 16:
                payload["random_key"] = random_key or f"agent:{agent_id}"
            self._event(tick, "person_registered", agent_id, payload)
            return household

    def register_new_people(self, tick: int, *, genesis: bool = False) -> None:
        if not self.enabled:
            return
        for row in self.store.query(
                "SELECT a.id FROM agents a LEFT JOIN person_lifecycle p ON p.agent_id=a.id "
                "WHERE p.agent_id IS NULL ORDER BY a.id"):
            self.register_person(tick, int(row["id"]), "genesis" if genesis else "engine_created")

    def initialize(self) -> None:
        if self.enabled:
            with self.store.savepoint("households_genesis"):
                self.register_new_people(0, genesis=True)
                self.record_census(0)

    def birth(self, tick: int, parent_id: int, *, source: str = "birth_hazard") -> int:
        """Exactly one child per parent/day, including a retried scheduled hazard."""
        if not self.enabled:
            raise HouseholdError("persistent birth requires semantics 15")
        _integer(tick, "birth tick", 1, 2_147_483_647)
        _integer(parent_id, "parent_agent_id", 1, 2_147_483_647)
        if source not in {"birth_hazard", "scheduled_birth"}:
            raise HouseholdError("unknown birth provenance")
        key = f"birth:{tick}:{parent_id}"
        with self.store.savepoint("household_birth"):
            child = self.store.scalar("SELECT agent_id FROM person_lifecycle WHERE birth_key=?", (key,))
            if child is not None:
                return int(child)
            parent = self.store.query_one("SELECT * FROM agents WHERE id=?", (parent_id,))
            member = self.membership(parent_id)
            if not parent or not parent["alive"] or int(parent["age"]) < ADULT_AGE or not member:
                raise HouseholdError("birth needs a living adult in an active household")
            child_id = self.store.insert(
                "agents", name="New person", kind="citizen",
                occupation="child", age=0, health="healthy", dependents=0,
                personality_json="{}", media_diet_json="[]", risk_tolerance=0.5,
                cadence_json='{"act":3,"portfolio":7,"career":30}', model_tier="local",
                alive=1, retired=0, arrived_tick=tick, region_id=parent["region_id"],
                population_tier="periphery", pinned_core=0)
            self.store.insert(
                "person_lifecycle", agent_id=child_id, origin="birth", origin_tick=tick,
                birth_tick=tick, birth_key=key, life_stage="child", legacy_dependents=0)
            self.store.insert(
                "household_memberships", household_id=int(member["household_id"]),
                agent_id=child_id, role="dependent", joined_tick=tick)
            self.store.insert(
                "parent_child_relations", parent_agent_id=parent_id, child_agent_id=child_id,
                formed_tick=tick, provenance=source)
            self.store.insert(
                "guardianships", child_agent_id=child_id, guardian_agent_id=parent_id,
                started_tick=tick, reason=source)
            account = self.store.query_one("SELECT * FROM accounts WHERE id=?",
                                           (parent["checking_account_id"],))
            currency = account["currency_code"] if account else self.e.regions.currency_for_region(parent["region_id"])
            checking = self.ledger.create_account(
                "agent", child_id, "checking", bank_id=account["bank_id"] if account else None,
                label=f"agent:{child_id}:checking", currency_code=currency)
            self.store.update("agents", child_id, name=f"Person {child_id}",
                              checking_account_id=checking)
            # Do not increment agents.dependents: those are uninstantiated legacy
            # dependents and continue to affect only the legacy policy path.
            payload = {"agent_id": child_id, "parent_agent_id": parent_id,
                       "household_id": int(member["household_id"]), "birth_key": key,
                       "provenance": source, "endowment_cents": 0}
            if self.e.engine_semantics_version >= 16:
                payload["random_key"] = stable_key("birth", tick, person_key(self.store, parent_id))
            self._event(tick, "birth", child_id, payload)
            self._event(tick, "parenthood", parent_id,
                        {"child_agent_id": child_id, "household_id": int(member["household_id"])})
            return child_id

    def scheduled_births(self, tick: int) -> None:
        if not self.enabled:
            return
        for item in sorted(self.p["scheduled_births"], key=lambda x: (x["tick"], x["parent_agent_id"])):
            if item["tick"] != tick:
                continue
            parent_id = item["parent_agent_id"]
            try:
                self.birth(tick, parent_id, source="scheduled_birth")
            except HouseholdError as exc:
                self._event(tick, "scheduled_birth_rejected", parent_id, {"reason": str(exc)})

    def advance_age(self, tick: int, agent) -> int:
        person = self.store.query_one("SELECT * FROM person_lifecycle WHERE agent_id=?", (agent["id"],))
        if not person:
            raise HouseholdError("age requires a recorded person origin")
        age = self.age_at(int(person["birth_tick"]), tick)
        if age < int(agent["age"]):
            raise HouseholdError("person age cannot move backwards")
        if age != int(agent["age"]):
            agent_id = int(agent["id"])
            self.store.update("agents", agent_id, age=age)
            self._event(tick, "birthday", agent_id, {"age": age})
            if int(agent["age"]) < ADULT_AGE <= age:
                member = self.membership(agent_id)
                self.store.update("household_memberships", int(member["id"]), left_tick=tick, end_reason="adulthood")
                self.store.insert("household_memberships", household_id=int(member["household_id"]),
                                  agent_id=agent_id, role="adult", joined_tick=tick)
                self.store.execute("UPDATE guardianships SET ended_tick=?,end_reason='adulthood' "
                                   "WHERE child_agent_id=? AND ended_tick IS NULL", (tick, agent_id))
                if agent["occupation"] == "child":
                    self.store.update("agents", agent_id, occupation="job seeker")
                self._event(tick, "adulthood", agent_id,
                            {"household_id": int(member["household_id"]), "endowment_cents": 0})
        stage = self._stage(age, bool(agent["retired"]) or age >= self.retirement_age)
        self.store.execute("UPDATE person_lifecycle SET life_stage=? WHERE agent_id=?", (stage, agent["id"]))
        return age

    def _dissolve_empty(self, tick: int, household_id: int) -> None:
        if not self.store.query_one("SELECT 1 FROM household_memberships WHERE household_id=? AND left_tick IS NULL",
                                    (household_id,)):
            self.store.update("households", household_id, dissolved_tick=tick)

    def split_household(self, tick: int, agent_id: int, *, reason: str = "adult_separation") -> int:
        """A deterministic adult departure; property and children do not silently move."""
        if not self.enabled:
            raise HouseholdError("household separation requires semantics 15")
        if reason not in {"adult_separation", "regional_migration"}:
            raise HouseholdError("unknown household separation reason")
        with self.store.savepoint("household_separation"):
            agent = self.store.query_one("SELECT * FROM agents WHERE id=?", (agent_id,))
            member = self.membership(agent_id)
            if not agent or not agent["alive"] or int(agent["age"]) < ADULT_AGE or not member:
                raise HouseholdError("separation needs a living adult member")
            previous = int(member["household_id"])
            household = self.store.query_one("SELECT * FROM households WHERE id=?", (previous,))
            count = int(self.store.scalar("SELECT COUNT(*) FROM household_memberships WHERE household_id=? AND left_tick IS NULL", (previous,)))
            if count == 1 and household["region_id"] == agent["region_id"]:
                return previous
            if tick < int(member["joined_tick"]):
                raise HouseholdError("household separation cannot precede membership")
            self.store.update("household_memberships", int(member["id"]), left_tick=tick, end_reason=reason)
            new_id = self.store.insert("households", region_id=agent["region_id"], formed_tick=tick, policy="guardian_basic_needs_v1")
            self.store.insert("household_memberships", household_id=new_id, agent_id=agent_id, role="adult", joined_tick=tick)
            self._dissolve_empty(tick, previous)
            self.reconcile_custody(tick)
            self._event(tick, "household_separated", agent_id,
                        {"previous_household_id": previous, "household_id": new_id, "reason": reason})
            return new_id

    def reconcile_residence(self, tick: int) -> None:
        """Existing individual migration creates a new household in its destination."""
        if not self.enabled:
            return
        for row in self.store.query(
                "SELECT a.id FROM agents a JOIN household_memberships m ON m.agent_id=a.id AND m.left_tick IS NULL "
                "JOIN households h ON h.id=m.household_id WHERE a.alive=1 AND a.region_id IS NOT h.region_id ORDER BY a.id"):
            self.split_household(tick, int(row["id"]), reason="regional_migration")

    def close_person(self, tick: int, agent_id: int) -> None:
        """Preserve the dead identity and record care gaps; custody transfers no assets."""
        if not self.enabled:
            return
        member = self.membership(agent_id)
        self.store.execute("UPDATE person_lifecycle SET life_stage='dead',death_tick=? WHERE agent_id=?", (tick, agent_id))
        self.store.execute("UPDATE guardianships SET ended_tick=?,end_reason='death' "
                           "WHERE ended_tick IS NULL AND (guardian_agent_id=? OR child_agent_id=?)",
                           (tick, agent_id, agent_id))
        if member:
            self.store.update("household_memberships", int(member["id"]), left_tick=tick, end_reason="death")
            self._dissolve_empty(tick, int(member["household_id"]))
        self.reconcile_custody(tick)

    def reconcile_custody(self, tick: int) -> None:
        if not self.enabled:
            return
        # End invalid assignments before choosing from the child's own household.
        self.store.execute(
            "UPDATE guardianships SET ended_tick=?,end_reason='household_change' "
            "WHERE ended_tick IS NULL AND NOT EXISTS ("
            "SELECT 1 FROM household_memberships c JOIN household_memberships g ON g.household_id=c.household_id "
            "JOIN agents a ON a.id=g.agent_id AND a.alive=1 AND a.age>=18 "
            "WHERE c.agent_id=guardianships.child_agent_id AND g.agent_id=guardianships.guardian_agent_id "
            "AND c.left_tick IS NULL AND g.left_tick IS NULL)", (tick,))
        for child in self.store.query(
                "SELECT a.id,m.household_id FROM agents a JOIN household_memberships m ON m.agent_id=a.id "
                "WHERE a.alive=1 AND a.age<18 AND m.left_tick IS NULL AND NOT EXISTS "
                "(SELECT 1 FROM guardianships g WHERE g.child_agent_id=a.id AND g.ended_tick IS NULL) ORDER BY a.id"):
            guardian = self.store.scalar(
                "SELECT a.id FROM agents a JOIN household_memberships m ON m.agent_id=a.id "
                "WHERE m.household_id=? AND m.left_tick IS NULL AND a.alive=1 AND a.age>=18 ORDER BY a.id LIMIT 1",
                (child["household_id"],))
            if guardian is not None:
                self.store.insert("guardianships", child_agent_id=child["id"], guardian_agent_id=guardian,
                                  started_tick=tick, reason="same_household_adult_v1")
                self._event(tick, "guardian_assigned", int(child["id"]),
                            {"guardian_agent_id": int(guardian), "policy": "same_household_adult_v1"})

    def guardian_id(self, child_id: int) -> int | None:
        value = self.store.scalar("SELECT guardian_agent_id FROM guardianships WHERE child_agent_id=? AND ended_tick IS NULL",
                                  (child_id,))
        return int(value) if value is not None else None

    def decision_context(self, agent_id: int, tick: int) -> dict | None:
        """An actor sees their own membership and care costs, not other families."""
        if not self.enabled:
            return None
        member = self.membership(agent_id)
        if member is None or int(member["joined_tick"]) > tick:
            return None
        children = self.store.query(
            "SELECT a.id,a.age FROM agents a JOIN guardianships g ON g.child_agent_id=a.id "
            "WHERE g.guardian_agent_id=? AND g.ended_tick IS NULL AND g.started_tick<=? "
            "AND a.alive=1 AND a.age<18 ORDER BY a.id", (agent_id, tick))
        spending = [dict(row) for row in self.store.query(
            "SELECT currency_code,SUM(spent_cents) spent_cents,SUM(purchased_units) purchased_units,"
            "SUM(required_units-purchased_units) unmet_units FROM child_needs "
            "WHERE guardian_agent_id=? AND tick=? GROUP BY currency_code ORDER BY currency_code", (agent_id, tick - 1))]
        return {
            "household_id": int(member["household_id"]), "role": str(member["role"]),
            "policy": "guardian_basic_needs_v1", "responsible_children": [dict(row) for row in children[:32]],
            "responsible_child_count": len(children), "children_truncated": len(children) > 32,
            "child_goods_units_per_day": len(children) * self.p["child_goods_units"],
            "goods_sector": self.p["goods_sector"],
            "care_required_minutes_per_day": len(children) * self.p["care_minutes_per_child"],
            "care_time_allocation": "pending", "previous_day_spending": spending,
            "settlement_rule": "Automatic child food purchases follow adult actions; do not add these children to legacy dependents.",
        }

    def provision_children(self, tick: int) -> None:
        """MARKET: disclosed deterministic purchases, with unmet quantities retained."""
        if not self.enabled:
            return
        with self.store.savepoint("household_needs"):
            self.reconcile_custody(tick)
            for child in self.store.query(
                    "SELECT a.id,a.region_id,m.household_id FROM agents a "
                    "JOIN household_memberships m ON m.agent_id=a.id AND m.left_tick IS NULL "
                    "WHERE a.alive=1 AND a.age<18 ORDER BY a.id"):
                child_id = int(child["id"])
                if self.store.query_one("SELECT 1 FROM child_needs WHERE tick=? AND child_agent_id=?", (tick, child_id)):
                    continue
                guardian = self.guardian_id(child_id)
                account_id = self.ledger.agent_checking_id(guardian) if guardian is not None else None
                currency = self.store.scalar("SELECT currency_code FROM accounts WHERE id=?", (account_id,))
                required = self.p["child_goods_units"]
                units = spent = 0
                purchases = []
                if account_id is not None:
                    firms = self.store.query(
                        "SELECT * FROM firms WHERE status<>'bankrupt' AND sector=? AND currency_code=? "
                        "AND (region_id=? OR (region_id IS NULL AND ? IS NULL)) AND inventory>0 ORDER BY id",
                        (self.p["goods_sector"], currency, child["region_id"], child["region_id"]))
                    firms.sort(key=lambda f: (int(self.e.firms.product(f)["unit_price_cents"]), int(f["id"])))
                    for firm in firms:
                        if units >= required:
                            break
                        result = self.e.firms.buy_goods(tick, guardian, int(firm["id"]), required - units)
                        if result.get("ok"):
                            units += int(result["qty"])
                            spent += int(result["total_cents"])
                            purchases.append({"firm_id": int(firm["id"]), "qty": int(result["qty"]),
                                              "total_cents": int(result["total_cents"])})
                need_id = self.store.insert(
                    "child_needs", tick=tick, child_agent_id=child_id, household_id=child["household_id"],
                    guardian_agent_id=guardian, currency_code=currency, goods_sector=self.p["goods_sector"],
                    required_units=required, purchased_units=units, spent_cents=spent,
                    care_required_minutes=self.p["care_minutes_per_child"],
                    care_status=("not_required" if not self.p["care_minutes_per_child"] else
                                 "unassigned" if guardian is None else "time_allocation_pending"),
                    purchases_json=json.dumps(purchases, sort_keys=True, separators=(",", ":")))
                self._event(tick, "child_needs_recorded", child_id,
                            {"need_id": need_id, "guardian_agent_id": guardian,
                             "required_units": required, "purchased_units": units,
                             "unmet_units": required - units, "spent_cents": spent,
                             "currency_code": currency}, phase="MARKET")
                if guardian is not None:
                    self._event(tick, "household_child_support", guardian,
                                {"child_agent_id": child_id, "spent_cents": spent,
                                 "currency_code": currency, "purchased_units": units,
                                 "unmet_units": required - units}, phase="MARKET")

    def check_invariants(self, tick: int) -> None:
        if not self.enabled:
            return
        invalid = self.store.query_one(
            "SELECT a.id FROM agents a LEFT JOIN person_lifecycle p ON p.agent_id=a.id "
            "LEFT JOIN household_memberships m ON m.agent_id=a.id AND m.left_tick IS NULL "
            "LEFT JOIN households h ON h.id=m.household_id "
            "WHERE p.agent_id IS NULL OR (a.alive=1 AND (m.id IS NULL OR h.dissolved_tick IS NOT NULL "
            "OR a.region_id IS NOT h.region_id "
            "OR p.origin_tick<>a.arrived_tick "
            "OR a.age<>CAST((?-p.birth_tick)/365 AS INTEGER) OR p.death_tick IS NOT NULL "
            "OR (a.age<18)<>(m.role='dependent') OR p.life_stage<>CASE "
            "WHEN a.retired=1 THEN 'retired' WHEN a.age<6 THEN 'child' "
            "WHEN a.age<18 THEN 'school_age' ELSE 'adult' END)) "
            "OR (a.alive=0 AND (m.id IS NOT NULL OR p.death_tick IS NOT a.died_tick OR p.life_stage<>'dead')) LIMIT 1",
            (tick,))
        if invalid:
            raise HouseholdError(f"person/membership reconciliation failed for agent {invalid['id']}")
        invalid = self.store.query_one(
            "SELECT g.id FROM guardianships g JOIN agents c ON c.id=g.child_agent_id "
            "JOIN agents a ON a.id=g.guardian_agent_id "
            "LEFT JOIN household_memberships cm ON cm.agent_id=c.id AND cm.left_tick IS NULL "
            "LEFT JOIN household_memberships am ON am.agent_id=a.id AND am.left_tick IS NULL "
            "WHERE g.ended_tick IS NULL AND (c.alive=0 OR c.age>=18 OR a.alive=0 OR a.age<18 "
            "OR cm.household_id IS NOT am.household_id) LIMIT 1")
        if invalid:
            raise HouseholdError(f"guardianship reconciliation failed for relation {invalid['id']}")

    def record_census(self, tick: int) -> None:
        if not self.enabled:
            return
        self.check_invariants(tick)
        previous = self.store.query_one("SELECT * FROM population_census WHERE tick<? ORDER BY tick DESC LIMIT 1", (tick,))
        if tick > 0 and (previous is None or int(previous["tick"]) != tick - 1):
            raise HouseholdError("census requires the preceding committed day")
        population = int(self.store.scalar("SELECT COUNT(*) FROM agents WHERE alive=1", default=0))
        counts = {r["origin"]: int(r["n"]) for r in self.store.query(
            "SELECT origin,COUNT(*) n FROM person_lifecycle WHERE origin_tick=? GROUP BY origin", (tick,))}
        deaths = int(self.store.scalar("SELECT COUNT(*) FROM person_lifecycle WHERE death_tick=?", (tick,), default=0))
        opening = int(previous["closing_population"]) if previous else population
        births, arrivals, other = (counts.get(k, 0) for k in ("birth", "arrival", "engine_created"))
        if population != opening + births + arrivals + other - deaths:
            raise HouseholdError("birth/death/arrival census identity does not reconcile")
        values = dict(
            tick=tick, opening_population=opening, births=births, arrivals=arrivals, other_entries=other,
            deaths=deaths, closing_population=population,
            active_households=int(self.store.scalar("SELECT COUNT(*) FROM households WHERE dissolved_tick IS NULL", default=0)),
            unassigned_minors=int(self.store.scalar(
                "SELECT COUNT(*) FROM agents a WHERE a.alive=1 AND a.age<18 AND NOT EXISTS "
                "(SELECT 1 FROM guardianships g WHERE g.child_agent_id=a.id AND g.ended_tick IS NULL)", default=0)),
            legacy_dependents=int(self.store.scalar(
                "SELECT COALESCE(SUM(p.legacy_dependents),0) FROM person_lifecycle p JOIN agents a ON a.id=p.agent_id WHERE a.alive=1", default=0)))
        existing = self.store.query_one("SELECT * FROM population_census WHERE tick=?", (tick,))
        if existing is not None:
            if dict(existing) != values:
                raise HouseholdError("cannot rewrite a recorded census")
            return
        self.store.insert("population_census", **values)

    def _event(self, tick: int, kind: str, agent_id: int, payload: dict, *, phase="NIGHT_CLOSE") -> None:
        self.store.log_event(tick, kind, {"agent_id": agent_id, **payload}, phase=phase,
                             subject_type="agent", subject_id=agent_id, importance=1.5)

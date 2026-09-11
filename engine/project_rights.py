"""Exact beneficial fractions and effective control of inherited home projects.

Construction and funding history retain their original identities. Fractions
use canonical decimal strings so generations of division never round away a
property right or overflow SQLite's integer representation.
"""
from __future__ import annotations

from fractions import Fraction
import json

from .estates import EstateError


def rights_enabled(store):
    config = json.loads(store.scalar("SELECT config_json FROM run_meta WHERE id=1", default="{}") or "{}")
    return int(config.get("engine_semantics_version", 1)) >= 20


def interests_at(store, project_id, tick=None, *, enabled=None):
    """Read title shares and estate custody at the selected tick, without mutation."""
    enabled = rights_enabled(store) if enabled is None else enabled
    project = store.query_one("SELECT * FROM construction_projects WHERE id=?", (project_id,))
    if project is None or project["owner_type"] != "agent" or (tick is not None and tick < project["proposed_tick"]):
        return []
    rows = []
    if enabled:
        clause = "ended_tick IS NULL" if tick is None else "started_tick<=? AND (ended_tick IS NULL OR ended_tick>?)"
        params = (project_id,) if tick is None else (project_id, tick, tick)
        rows = store.query("SELECT * FROM project_interest_lots WHERE project_id=? AND " + clause + " ORDER BY id", params)
    if not rows:
        return [{"agent_id": project["owner_id"], "numerator": "1", "denominator": "1",
                 "started_tick": project["proposed_tick"], "updated_tick": project["proposed_tick"]}]
    portions, starts, updates, custody = {}, {}, {}, {}
    for row in rows:
        person = row["agent_id"]
        portions[person] = portions.get(person, Fraction()) + Fraction(int(row["numerator"]), int(row["denominator"]))
        starts[person] = min(starts.get(person, row["started_tick"]), row["started_tick"])
        updates[person] = max(updates.get(person, 0), row["started_tick"])
        if enabled:
            boundary = "" if tick is None else " AND c.opened_tick<=?"
            active = "r.id IS NULL" if tick is None else "(r.id IS NULL OR r.tick>?)"
            params = (row["id"],) if tick is None else (row["id"], tick, tick)
            estate = store.scalar("SELECT c.estate_id FROM estate_project_custody c LEFT JOIN estate_project_releases r "
                "ON r.custody_id=c.id WHERE c.interest_lot_id=?" + boundary + " AND " + active, params)
            if estate is not None:
                custody[person] = estate
    return [{"agent_id": person, "numerator": str(portion.numerator), "denominator": str(portion.denominator),
             "started_tick": starts[person], "updated_tick": updates[person],
             **({"estate_id": custody[person], "estate_custody": True} if person in custody else {})}
            for person, portion in sorted(portions.items(), key=lambda pair: pair[0] or 0)]


def steward_at(store, project_id, tick=None, *, enabled=None):
    enabled = rights_enabled(store) if enabled is None else enabled
    project = store.query_one("SELECT * FROM construction_projects WHERE id=?", (project_id,))
    if project is None or project["owner_type"] != "agent" or (tick is not None and tick < project["proposed_tick"]):
        return None
    if enabled:
        clause = "ended_tick IS NULL" if tick is None else "started_tick<=? AND (ended_tick IS NULL OR ended_tick>?)"
        params = (project_id,) if tick is None else (project_id, tick, tick)
        row = store.query_one("SELECT * FROM project_stewardships WHERE project_id=? AND " + clause
                              + " ORDER BY started_tick DESC,id DESC LIMIT 1", params)
        if row is not None:
            return dict(row)
    return {"project_id": project_id, "steward_agent_id": project["owner_id"], "capacity": "owner",
            "beneficiary_id": None, "started_tick": project["proposed_tick"]}


class ProjectRights:
    def __init__(self, economy):
        self.e = economy
        self.store = economy.store
        self.enabled = economy.engine_semantics_version >= 20

    def owned_projects(self, agent_id):
        rows = self.store.query("SELECT p.* FROM construction_projects p WHERE p.owner_type='agent' AND p.status<>'cancelled' "
            "AND ((p.owner_id=? AND NOT EXISTS (SELECT 1 FROM project_interest_lots l WHERE l.project_id=p.id)) "
            "OR EXISTS (SELECT 1 FROM project_interest_lots l WHERE l.project_id=p.id AND l.agent_id=? AND l.ended_tick IS NULL)) "
            "ORDER BY p.id", (agent_id, agent_id))
        result = []
        for row in rows:
            portion = next(share for share in interests_at(self.store, row["id"], enabled=True) if share["agent_id"] == agent_id)
            result.append({**dict(row), "beneficial_numerator": portion["numerator"], "beneficial_denominator": portion["denominator"]})
        return result

    def operated_projects(self, agent_id, *, active_only=True):
        terminal = "AND p.status NOT IN ('completed','cancelled') " if active_only else "AND p.status<>'cancelled' "
        return self.store.query("SELECT p.* FROM construction_projects p LEFT JOIN project_stewardships s "
            "ON s.project_id=p.id AND s.ended_tick IS NULL WHERE p.owner_type='agent' " + terminal
            + "AND CASE WHEN s.id IS NULL THEN p.owner_id ELSE s.steward_agent_id END=? "
            "AND p.region_id=(SELECT region_id FROM agents WHERE id=?) ORDER BY p.proposed_tick,p.id", (agent_id, agent_id))

    def controls(self, agent_id, project):
        actor = self.store.query_one("SELECT * FROM agents WHERE id=?", (agent_id,))
        if actor is None or not actor["alive"]:
            return False
        if self.e.engine_semantics_version >= 21 and not self.e.population.is_available(agent_id):
            return False
        steward = steward_at(self.store, project["id"], enabled=True)
        current = self._successor(project["id"])
        return bool(actor and actor["alive"] and actor["age"] >= 18 and actor["region_id"] == project["region_id"]
                    and steward and steward["steward_agent_id"] == agent_id
                    and current == (steward["steward_agent_id"], steward["capacity"], steward["beneficiary_id"],
                                    steward.get("estate_id"), steward.get("administration_id")))

    def _seed(self, project):
        if self.store.scalar("SELECT id FROM project_interest_lots WHERE project_id=? LIMIT 1", (project["id"],)) is None:
            self.store.insert("project_interest_lots", project_id=project["id"], agent_id=project["owner_id"],
                              numerator="1", denominator="1", started_tick=project["proposed_tick"])
        if self.store.scalar("SELECT id FROM project_stewardships WHERE project_id=? LIMIT 1", (project["id"],)) is None:
            self.store.insert("project_stewardships", project_id=project["id"], steward_agent_id=project["owner_id"],
                              capacity="owner", started_tick=project["proposed_tick"])

    def distribute(self, tick, estate_id, agent_id):
        if not self.enabled:
            raise EstateError("project succession requires Semantics 20")
        case = self.store.query_one("SELECT * FROM estate_cases WHERE id=?", (estate_id,))
        if case is None or case["deceased_agent_id"] != agent_id or case["opened_tick"] != tick:
            raise EstateError("project succession must match the recorded estate opening")
        with self.store.savepoint("project_estate_distribution"):
            self.e.estate_property.open(tick, estate_id, agent_id)

    def _distribute_lot(self, tick, estate_id, lot):
        case = self.store.query_one("SELECT * FROM estate_cases WHERE id=?", (estate_id,))
        if case is None or case["deceased_agent_id"] != lot["agent_id"] or case["opened_tick"] > tick or (
                lot["ended_tick"] is not None or lot["started_tick"] > tick):
            raise EstateError("project inheritance has an invalid predecessor or time")
        beneficiaries = self.store.query("SELECT * FROM estate_beneficiaries WHERE estate_id=? ORDER BY COALESCE(agent_id,0),id", (estate_id,))
        if not beneficiaries or any(b["agent_id"] == lot["agent_id"] for b in beneficiaries):
            raise EstateError("project beneficiary must be a different recorded person")
        denominator = sum(b["weight"] for b in beneficiaries)
        original = Fraction(int(lot["numerator"]), int(lot["denominator"]))
        with self.store.savepoint("project_interest_distribution"):
            self.store.update("project_interest_lots", lot["id"], ended_tick=tick)
            descendants = []
            for beneficiary in beneficiaries:
                share = original * Fraction(beneficiary["weight"], denominator)
                child = self.store.insert("project_interest_lots", project_id=lot["project_id"], agent_id=beneficiary["agent_id"],
                    numerator=str(share.numerator), denominator=str(share.denominator), started_tick=tick,
                    prior_lot_id=lot["id"], estate_id=estate_id)
                if beneficiary["agent_id"] is not None and not self.store.scalar("SELECT alive FROM agents WHERE id=?", (beneficiary["agent_id"],)):
                    inherited_estate = self.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (beneficiary["agent_id"],))
                    if inherited_estate is None:
                        raise EstateError("deceased property beneficiary lacks an estate")
                    descendants.append((inherited_estate, child))
            for inherited_estate, child in descendants:
                self.e.estate_property.accept_lot(tick, inherited_estate, child)

    def has_personal_residual(self, project_id):
        for share in interests_at(self.store, project_id, enabled=True):
            if share["agent_id"] is None:
                continue
            case = share.get("estate_id") or self.store.scalar("SELECT id FROM estate_cases WHERE deceased_agent_id=?", (share["agent_id"],))
            if case is not None:
                if self.e.estate_property.beneficial_people(case):
                    return True
            elif self.store.scalar("SELECT alive FROM agents WHERE id=?", (share["agent_id"],)):
                return True
        return False

    def cancel_if_unclaimed(self, tick, project_id):
        if not self.has_personal_residual(project_id):
            self.e.construction.cancel_unclaimed(tick, project_id)

    def _successor(self, project_id):
        if self.store.scalar("SELECT status FROM construction_projects WHERE id=?", (project_id,)) == "cancelled":
            return None, "vacant", None, None, None
        shares = interests_at(self.store, project_id, enabled=True)
        shares.sort(key=lambda share: (-Fraction(int(share["numerator"]), int(share["denominator"])), share["agent_id"] or 0))
        minors = []
        for share in shares:
            if share["agent_id"] is None or share.get("estate_custody"):
                continue
            actor = self.store.query_one("SELECT * FROM agents WHERE id=?", (share["agent_id"],))
            if actor is None or not actor["alive"]:
                continue
            if actor["age"] >= 18 and (self.e.engine_semantics_version < 21 or self.e.population.is_available(actor["id"])):
                return actor["id"], "owner", None, None, None
            if actor["age"] < 18:
                minors.append(actor["id"])
        estate = self.e.estate_property.operator_for(project_id)
        if estate is not None and (self.e.engine_semantics_version < 21 or self.e.population.is_available(estate[0])):
            return estate
        for child in minors:
            guardian = self.store.scalar("SELECT g.guardian_agent_id FROM guardianships g JOIN agents a ON a.id=g.guardian_agent_id "
                "WHERE g.child_agent_id=? AND g.ended_tick IS NULL AND a.alive=1 AND a.age>=18 ORDER BY g.id LIMIT 1", (child,))
            if guardian is not None and (self.e.engine_semantics_version < 21 or self.e.population.is_available(guardian)):
                return guardian, "guardian", child, None, None
        return None, "vacant", None, None, None

    def refresh(self, tick):
        """After death/custody, then each day: reassess actual current rights."""
        if not self.enabled:
            return
        with self.store.savepoint("project_custody_refresh"):
            self.e.estate_administration.reconcile(tick)
            if self.e.engine_semantics_version >= 21:
                # An original owner's departure also needs a historical control
                # interval, even when the property has never been inherited.
                for project in self.store.query("SELECT p.* FROM construction_projects p "
                        "WHERE p.owner_type='agent' AND p.status<>'cancelled' AND NOT EXISTS "
                        "(SELECT 1 FROM project_stewardships s WHERE s.project_id=p.id) ORDER BY p.id"):
                    self._seed(project)
            for previous in self.store.query("SELECT * FROM project_stewardships WHERE ended_tick IS NULL ORDER BY project_id"):
                successor = self._successor(previous["project_id"])
                if successor == (previous["steward_agent_id"], previous["capacity"], previous["beneficiary_id"], previous["estate_id"], previous["administration_id"]):
                    continue
                if tick < previous["started_tick"]:
                    raise EstateError("project stewardship cannot move backwards in time")
                self.store.update("project_stewardships", previous["id"], ended_tick=tick)
                self.store.insert("project_stewardships", project_id=previous["project_id"], steward_agent_id=successor[0],
                                  capacity=successor[1], beneficiary_id=successor[2], estate_id=successor[3],
                                  administration_id=successor[4], started_tick=tick)
            self.e.estate_property_sales.reconcile(tick)

    def household_home(self, region_id, agent_id):
        members = self.store.query("SELECT other.agent_id FROM household_memberships mine JOIN household_memberships other "
            "ON other.household_id=mine.household_id JOIN agents a ON a.id=other.agent_id "
            "WHERE mine.agent_id=? AND mine.left_tick IS NULL AND other.left_tick IS NULL AND a.alive=1 ORDER BY a.id", (agent_id,))
        people = [row["agent_id"] for row in members] or [agent_id]
        marks = ",".join("?" for _ in people)
        candidates = self.store.query("SELECT p.* FROM construction_projects p WHERE p.region_id=? "
            "AND p.owner_type='agent' AND p.target_place_type='private_home' AND p.status='completed' "
            "AND p.place_id IS NOT NULL AND ((p.owner_id IN (" + marks + ") AND NOT EXISTS "
            "(SELECT 1 FROM project_interest_lots l WHERE l.project_id=p.id)) OR EXISTS "
            "(SELECT 1 FROM project_interest_lots l WHERE l.project_id=p.id AND l.ended_tick IS NULL AND l.agent_id IN (" + marks + ")) OR EXISTS "
            "(SELECT 1 FROM estate_project_custody c JOIN project_interest_lots l ON l.id=c.interest_lot_id "
            "WHERE l.project_id=p.id AND NOT EXISTS (SELECT 1 FROM estate_project_releases r WHERE r.custody_id=c.id))) "
            "ORDER BY p.completed_tick DESC,p.id DESC", (region_id, *people, *people))
        for project in candidates:
            for share in interests_at(self.store, project["id"], enabled=True):
                if share.get("estate_custody"):
                    if self.e.estate_property.beneficial_people(share["estate_id"]).intersection(people):
                        return project["place_id"]
                elif share["agent_id"] in people:
                    return project["place_id"]
        return None

    def check_invariants(self):
        if not self.enabled:
            return
        lots = {row["id"]: row for row in self.store.query("SELECT * FROM project_interest_lots ORDER BY id")}
        children, boundaries = {}, {}
        for lot in lots.values():
            share = Fraction(int(lot["numerator"]), int(lot["denominator"]))
            if not 0 < share <= 1 or (str(share.numerator), str(share.denominator)) != (lot["numerator"], lot["denominator"]):
                raise EstateError("project beneficial fraction is not canonical")
            project = self.store.query_one("SELECT * FROM construction_projects WHERE id=?", (lot["project_id"],))
            if project is None or project["owner_type"] != "agent" or lot["started_tick"] < project["proposed_tick"]:
                raise EstateError("project interest has no matching personal property")
            if lot["prior_lot_id"] is None:
                if share != 1 or lot["agent_id"] != project["owner_id"] or lot["started_tick"] != project["proposed_tick"]:
                    raise EstateError("project original owner history changed")
            else:
                parent = lots.get(lot["prior_lot_id"])
                case = self.store.query_one("SELECT * FROM estate_cases WHERE id=?", (lot["estate_id"],))
                if parent is None or case is None or parent["project_id"] != lot["project_id"] or parent["ended_tick"] != lot["started_tick"] or (
                        case["deceased_agent_id"] != parent["agent_id"] or case["opened_tick"] > lot["started_tick"]):
                    raise EstateError("project inheritance has no matching predecessor estate")
                sale = self.store.query_one("SELECT * FROM estate_property_sales WHERE successor_lot_id=?", (lot["id"],))
                if sale is not None:
                    self.e.estate_property_sales.check_sale(sale)
                    children[parent["id"]] = children.get(parent["id"], Fraction()) + share
                    changes = boundaries.setdefault(lot["project_id"], {})
                    changes[lot["started_tick"]] = changes.get(lot["started_tick"], Fraction()) + share
                    if lot["ended_tick"] is not None:
                        changes[lot["ended_tick"]] = changes.get(lot["ended_tick"], Fraction()) - share
                    continue
                if case["opened_tick"] != lot["started_tick"] and not self.store.scalar(
                        "SELECT r.id FROM estate_project_releases r JOIN estate_project_custody c ON c.id=r.custody_id "
                        "WHERE c.interest_lot_id=? AND c.estate_id=? AND r.tick=? AND r.disposition='distributed'",
                        (parent["id"], case["id"], lot["started_tick"])):
                    raise EstateError("late project inheritance lacks a recorded estate release")
                beneficiary = self.store.query_one("SELECT * FROM estate_beneficiaries WHERE estate_id=? AND agent_id IS ?", (case["id"], lot["agent_id"]))
                total_weight = self.store.scalar("SELECT SUM(weight) FROM estate_beneficiaries WHERE estate_id=?", (case["id"],))
                if beneficiary is None or share != Fraction(int(parent["numerator"]), int(parent["denominator"])) * Fraction(beneficiary["weight"], total_weight):
                    raise EstateError("project inheritance violates recorded beneficial weights")
                children[parent["id"]] = children.get(parent["id"], Fraction()) + share
            changes = boundaries.setdefault(lot["project_id"], {})
            changes[lot["started_tick"]] = changes.get(lot["started_tick"], Fraction()) + share
            if lot["ended_tick"] is not None:
                changes[lot["ended_tick"]] = changes.get(lot["ended_tick"], Fraction()) - share
        for lot in lots.values():
            if lot["ended_tick"] is not None and children.get(lot["id"], Fraction()) != Fraction(int(lot["numerator"]), int(lot["denominator"])):
                raise EstateError("project inheritance lost or created a beneficial share")
        for changes in boundaries.values():
            total = Fraction()
            for tick in sorted(changes):
                total += changes[tick]
                if total != 1:
                    raise EstateError("project ownership does not sum to one at every boundary")
        previous = {}
        for row in self.store.query("SELECT * FROM project_stewardships ORDER BY project_id,started_tick,id"):
            prior = previous.get(row["project_id"])
            if prior is not None and prior["ended_tick"] != row["started_tick"]:
                raise EstateError("project stewardship has a gap or overlap")
            previous[row["project_id"]] = row
        if set(previous) != set(boundaries) or any(row["ended_tick"] is not None for row in previous.values()):
            raise EstateError("project rights have no current stewardship disposition")
        for row in previous.values():
            if (row["steward_agent_id"], row["capacity"], row["beneficiary_id"], row["estate_id"], row["administration_id"]) != self._successor(row["project_id"]):
                raise EstateError("project stewardship does not follow current ownership and custody")

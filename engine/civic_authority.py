"""End personal authority at death or departure while retaining institutional acts."""
from __future__ import annotations

import json

from .estates import EstateError


def agency_leaders_before_death(store, tick):
    """Public identity before a later death; callers gate to Semantics 20."""
    # Undo only death, without exposing private estate snapshots. Prospective
    # appointments require their own history rather than reusing these records.
    return {
        int(row["source_id"]): row["leader_agent_id"]
        for row in store.query(
            "SELECT source_id,leader_agent_id FROM ("
            "SELECT i.source_id,json_extract(i.snapshot_json,'$.leader_agent_id') AS leader_agent_id,"
            "ROW_NUMBER() OVER (PARTITION BY i.source_id ORDER BY c.opened_tick,i.id) AS position "
            "FROM estate_items i JOIN estate_cases c ON c.id=i.estate_id "
            "WHERE i.kind='agency_leadership' AND c.opened_tick>?) WHERE position=1", (int(tick),))
    }


class CivicAuthority:
    def __init__(self, economy):
        self.e = economy
        self.store = economy.store
        self.enabled = economy.engine_semantics_version >= 20

    def close_person(self, tick, estate_id, agent_id):
        if not self.enabled:
            return
        inventory = self.e.estate_cases._item
        actor = self.store.query_one("SELECT id,role,occupation FROM agents WHERE id=?", (agent_id,))
        if actor["role"] or actor["occupation"] == "lawyer":
            inventory(estate_id, "personal_role", actor, "extinguished")
        for member in self.store.query("SELECT * FROM legislators WHERE agent_id=? AND active=1 ORDER BY id", (agent_id,)):
            if tick < member["term_start_tick"]:
                raise EstateError("death cannot precede the current legislative term")
            original = {**dict(member), "committee_memberships": [dict(row) for row in self.store.query(
                "SELECT * FROM committee_members WHERE legislator_id=? ORDER BY committee_id", (member["id"],))]}
            inventory(estate_id, "legislative_office", original, "extinguished")
            self.store.update("legislators", member["id"], active=0,
                              term_end_tick=min(tick, member["term_end_tick"]))
        for agency in self.store.query("SELECT * FROM agencies WHERE leader_agent_id=? ORDER BY id", (agent_id,)):
            inventory(estate_id, "agency_leadership", agency, "extinguished")
            self.store.update("agencies", agency["id"], leader_agent_id=None)
        for matter in self.store.query("SELECT * FROM legal_matters WHERE counsel_agent_id=? "
                "AND status NOT IN ('decided','dismissed','settled') ORDER BY id", (agent_id,)):
            inventory(estate_id, "legal_representation", matter, "extinguished")
            self.store.update("legal_matters", matter["id"], counsel_agent_id=None)
        self._close_city_roles(tick, estate_id, agent_id)
        self.e.legal_representation.close_person(tick, estate_id, agent_id)

    def _close_city_roles(self, tick, estate_id, agent_id):
        self._release_city_roles(tick, agent_id,
            lambda kind, row: self.e.estate_cases._item(estate_id, kind, row, "extinguished"),
            applicant_reason="applicant_deceased", lawyer_reason="lawyer_deceased", for_death=True)

    def record_departure_binding(self, tick, movement_id, agent_id, kind, row):
        self.store.log_event(tick, "population_authority_released", {
            "movement_id": movement_id, "agent_id": agent_id, "binding_kind": kind,
            "source_id": row["id"], "snapshot": dict(row), "policy": "local_personal_authority_v1"},
            phase="NIGHT_CLOSE", subject_type="agent", subject_id=agent_id, importance=2.0)

    def release_for_departure(self, tick, movement_id, agent_id):
        """Release personal authority without opening or settling an estate."""
        if self.e.engine_semantics_version < 21:
            raise EstateError("population authority ending requires Semantics 21")
        state = self.e.population.history.state_at(agent_id, tick)
        if state is None or state["cause"] != "departure" or state["request_key"] != f"population:{movement_id}":
            raise EstateError("authority ending needs this movement's recorded departure")
        record = lambda kind, row: self.record_departure_binding(tick, movement_id, agent_id, kind, row)
        actor = self.store.query_one("SELECT id,role,occupation FROM agents WHERE id=?", (agent_id,))
        if actor["role"] or actor["occupation"] == "lawyer":
            record("personal_role", actor)
        # Professional history remains. A return does not restore a lost office.
        self.store.update("agents", agent_id, role=None)
        for member in self.store.query("SELECT * FROM legislators WHERE agent_id=? AND active=1 ORDER BY id", (agent_id,)):
            if tick < member["term_start_tick"]:
                raise EstateError("departure cannot precede the current legislative term")
            record("legislative_office", {**dict(member), "committee_memberships": [dict(row) for row in self.store.query(
                "SELECT * FROM committee_members WHERE legislator_id=? ORDER BY committee_id", (member["id"],))]})
            self.store.update("legislators", member["id"], active=0, term_end_tick=min(tick, member["term_end_tick"]))
        for agency in self.store.query("SELECT * FROM agencies WHERE leader_agent_id=? ORDER BY id", (agent_id,)):
            record("agency_leadership", agency)
            self.store.update("agencies", agency["id"], leader_agent_id=None)
        for matter in self.store.query("SELECT * FROM legal_matters WHERE counsel_agent_id=? "
                "AND status NOT IN ('decided','dismissed','settled') ORDER BY id", (agent_id,)):
            record("legal_representation", matter)
            self.store.update("legal_matters", matter["id"], counsel_agent_id=None)
        self._release_city_roles(tick, agent_id, record,
                                applicant_reason="applicant_departed", lawyer_reason="lawyer_departed")
        self.e.legal_representation.release_for_departure(tick, movement_id, agent_id)

    def _release_city_roles(self, tick, agent_id, record, *, applicant_reason, lawyer_reason, for_death=False):
        # Snapshot all personal bindings before cancelling any case or releasing
        # an assignment. The task and the institution remain independent of the
        # former worker's authority; neither passes to their beneficiaries.
        sources = (
            ("agency_staff", "agency_staff", "agent_id=? AND active=1"),
            ("institutional_assignment", "institution_tasks", "assigned_agent_id=? AND status='assigned'"),
            ("civic_application", "service_cases", "applicant_agent_id=? AND status IN ('applied','appointment_scheduled','submitted','under_review')"),
            ("civic_counsel", "service_cases", "lawyer_agent_id=? AND applicant_agent_id<>lawyer_agent_id AND status IN ('applied','appointment_scheduled','submitted','under_review')"),
            ("civic_appointment", "service_appointments", "applicant_agent_id=? AND status='scheduled'"),
            ("civic_authorization", "civic_authorizations", "holder_agent_id=? AND status='active'"),
        )
        records = {}
        for kind, table, predicate in sources:
            records[kind] = self.store.query(f"SELECT * FROM {table} WHERE {predicate} ORDER BY id", (agent_id,))
            for row in records[kind]:
                record(kind, row)
        represented_permits = self.store.query(
            "SELECT a.*,c.lawyer_agent_id FROM civic_authorizations a JOIN service_cases c ON c.id=a.case_id "
            "WHERE c.lawyer_agent_id=? AND a.holder_agent_id<>c.lawyer_agent_id AND a.status='active' ORDER BY a.id", (agent_id,))
        for authorization in represented_permits:
            record("civic_counsel_authorization", authorization)
        city = self.e.city
        abandon = city._abandon_case_after_death if for_death else city._abandon_personal_case
        revoke = city._revoke_authorization_after_death if for_death else city._revoke_personal_authorization
        for case in records["civic_application"]:
            if for_death:
                # Retain the legacy death closure and its failure-injection seam.
                abandon(tick, case)
            else:
                abandon(tick, case, reason=applicant_reason)
        for case in records["civic_counsel"]:
            abandon(tick, case, reason=lawyer_reason)
        for appointment in records["civic_appointment"]:
            city._cancel_case_appointments(appointment["case_id"], tick)
        for staff in records["agency_staff"]:
            city._end_staff_assignment(tick, staff)
        city._release_task_assignments(agent_id)
        for authorization in records["civic_authorization"]:
            revoke(tick, authorization, reason=applicant_reason)
        for authorization in represented_permits:
            revoke(tick, authorization, reason=lawyer_reason)

    def check_invariants(self):
        if not self.enabled:
            return
        if self.store.scalar("SELECT l.id FROM legislators l JOIN estate_cases c ON c.deceased_agent_id=l.agent_id "
                             "WHERE l.active=1 LIMIT 1"):
            raise EstateError("a deceased legislator retains active authority")
        if self.store.scalar("SELECT a.id FROM agencies a JOIN estate_cases c ON c.deceased_agent_id=a.leader_agent_id LIMIT 1"):
            raise EstateError("a deceased agent retains agency leadership")
        if self.store.scalar("SELECT m.id FROM legal_matters m JOIN estate_cases c ON c.deceased_agent_id=m.counsel_agent_id "
                             "WHERE m.status NOT IN ('decided','dismissed','settled') LIMIT 1"):
            raise EstateError("a deceased counsel retains a pending representation")
        for table, field, predicate in (
            ("agency_staff", "agent_id", "r.active=1"),
            ("institution_tasks", "assigned_agent_id", "r.status='assigned'"),
            ("service_cases", "applicant_agent_id", "r.status IN ('applied','appointment_scheduled','submitted','under_review')"),
            ("service_cases", "lawyer_agent_id", "r.status IN ('applied','appointment_scheduled','submitted','under_review')"),
            ("service_appointments", "applicant_agent_id", "r.status='scheduled'"),
            ("civic_authorizations", "holder_agent_id", "r.status='active'"),
        ):
            if self.store.scalar(f"SELECT r.id FROM {table} r JOIN estate_cases c ON c.deceased_agent_id=r.{field} "
                                 f"WHERE {predicate} LIMIT 1"):
                raise EstateError(f"a deceased person retains active city rights in {table}")
        if self.store.scalar("SELECT a.id FROM civic_authorizations a JOIN service_cases m ON m.id=a.case_id "
                             "JOIN estate_cases c ON c.deceased_agent_id=m.lawyer_agent_id WHERE a.status='active' LIMIT 1"):
            raise EstateError("an active permit retains a deceased lawyer")
        identities = {
            "personal_role": "id", "legislative_office": "agent_id",
            "agency_leadership": "leader_agent_id", "legal_representation": "counsel_agent_id",
            "agency_staff": "agent_id", "institutional_assignment": "assigned_agent_id",
            "civic_application": "applicant_agent_id", "civic_appointment": "applicant_agent_id",
            "civic_authorization": "holder_agent_id",
            "civic_counsel": "lawyer_agent_id", "civic_counsel_authorization": "lawyer_agent_id",
        }
        placeholders = ",".join("?" for _ in identities)
        for item in self.store.query("SELECT i.*,c.deceased_agent_id FROM estate_items i JOIN estate_cases c ON c.id=i.estate_id "
                f"WHERE i.kind IN ({placeholders}) ORDER BY i.id", tuple(identities)):
            person = item["deceased_agent_id"]
            source = json.loads(item["snapshot_json"])
            field = identities[item["kind"]]
            if source[field] != person or source["id"] != item["source_id"] or item["disposition"] != "extinguished":
                raise EstateError("estate authority ending has a different person or disposition")
            if item["kind"] == "legislative_office":
                member = self.store.query_one("SELECT * FROM legislators WHERE id=?", (item["source_id"],))
                if not member or member["active"] != 0 or member["agent_id"] != person:
                    raise EstateError("a former legislative identity was removed or reassigned")
            if item["kind"] == "agency_staff":
                staff = self.store.query_one("SELECT agent_id,active FROM agency_staff WHERE id=?", (item["source_id"],))
                if not staff or staff["active"] != 0 or staff["agent_id"] != person:
                    raise EstateError("a former city staff identity was removed or reassigned")

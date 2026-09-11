"""Recorded ending of local requests and services on external departure."""
from __future__ import annotations

import json

from .population_history import ResidenceError


POLICY = "end_local_commitments_retain_assets_v1"
# The predicate identifies a person's own request or service, never a company's
# obligation or an already disbursed loan. Terminal rows retain their identity.
ENDINGS = {
    "insurance": ("insurance_policies", "agent_id", "status='active'", "cancelled", "end_tick"),
    "compute_access": ("compute_subscriptions", "agent_id", "status IN ('pending','active')", "cancelled", None),
    "loan_application": ("loan_applications", "borrower_id", "borrower_type='agent' AND status='pending'", "expired", "decided_tick"),
    "migration": ("migrations", "agent_id", "status='pending'", "cancelled", "completed_tick"),
    "stock_order": ("orders", "agent_id", "status IN ('open','partial')", "cancelled", None),
    "fx_order": ("fx_orders", "actor_id", "status='open'", "cancelled", None),
    "ipo_bid": ("ipo_bids", "bidder_agent_id", "status='open'", "cancelled", None),
    "local_occupancy": ("occupancy_leases", "agent_id", "status='active'", "cancelled", "ended_tick"),
}
OPEN_STATES = {
    "insurance": {"active"}, "compute_access": {"pending", "active"},
    "loan_application": {"pending"}, "migration": {"pending"},
    "stock_order": {"open", "partial"}, "fx_order": {"open"}, "ipo_bid": {"open"},
    "local_occupancy": {"active"},
}


class PopulationCommitments:
    def __init__(self, population):
        self.population = population
        self.e = population.e
        self.store = population.store

    @staticmethod
    def changes(kind, tick):
        _, _, _, status, tick_field = ENDINGS[kind]
        return {"status": status, **({tick_field: tick} if tick_field else {})}

    def _rows(self, kind, agent_id):
        table, owner, predicate, _, _ = ENDINGS[kind]
        return self.store.query(f"SELECT * FROM {table} WHERE {owner}=? AND {predicate} ORDER BY id", (agent_id,))

    def end_person(self, tick, movement_id, agent_id):
        self.population._require_enabled()
        movement = self.population._read(movement_id)
        terms = json.loads(movement["terms_json"])
        state = self.population.history.state_at(agent_id, tick)
        if (movement["due_tick"] != tick or terms["cause"] != "departure" or agent_id not in terms["member_ids"]
                or state is None or state["cause"] != "departure" or state["request_key"] != f"population:{movement_id}"):
            raise ResidenceError("commitment ending needs the person's recorded group departure")
        with self.store.savepoint("population_commitments"):
            recorded = {kind: self._rows(kind, agent_id) for kind in ENDINGS}
            self.e.lifecycle.cancel_personal_insurance(tick, agent_id)
            self.e.cognition.end_local_access(agent_id)
            self.e.bank.expire_personal_applications(tick, agent_id)
            self.e.regions.cancel_pending_migrations(tick, agent_id)
            for order in recorded["stock_order"]:
                self.e.exchange._cancel_order(order["id"])
            self.e.regions.cancel_fx_orders(tick, agent_id)
            self.e.firms.cancel_ipo_bids(agent_id)
            self.e.city.cancel_local_occupancy(tick, agent_id)
            for kind, rows in recorded.items():
                for row in rows:
                    event_id = self.store.log_event(tick, "population_commitment_ended", {
                        "movement_id": movement_id, "agent_id": agent_id, "kind": kind,
                        "source_id": row["id"], "snapshot": dict(row),
                        "changes": self.changes(kind, tick), "policy": POLICY},
                        phase="NIGHT_CLOSE", subject_type="agent", subject_id=agent_id, importance=1.5)
                    self.store.insert("population_commitment_endings", movement_id=movement_id, agent_id=agent_id,
                        tick=tick, kind=kind, source_id=row["id"], event_id=event_id,
                        evidence_json=self.store.scalar("SELECT payload_json FROM events WHERE id=?", (event_id,)))
            # These markets own immutable bid endings and their source audit.
            # A bidder leaving does not sell or redistribute the estate's asset.
            self.e.estate_property_sales.reconcile(tick)
            self.e.estate_unlisted_sales.reconcile(tick)

    def check_invariants(self):
        self.population._require_enabled()
        movements, seen = {}, set()
        if self.store.scalar("SELECT e.id FROM events e WHERE e.kind='population_commitment_ended' AND NOT EXISTS "
                "(SELECT 1 FROM population_commitment_endings c WHERE c.event_id=e.id) LIMIT 1"):
            raise ResidenceError("commitment ending event lacks its immutable record")
        for ending in self.store.query("SELECT * FROM population_commitment_endings ORDER BY id"):
            event = self.store.query_one("SELECT * FROM events WHERE id=?", (ending["event_id"],))
            if event is None or event["kind"] != "population_commitment_ended" or (
                    event["payload_json"] != ending["evidence_json"] or event["tick"] != ending["tick"]):
                raise ResidenceError("commitment ending lost or changed its event")
            try:
                payload = json.loads(event["payload_json"])
                if set(payload) != {"movement_id", "agent_id", "kind", "source_id", "snapshot", "changes", "policy"}:
                    raise ValueError("unexpected fields")
                kind, person, movement_id = payload["kind"], payload["agent_id"], payload["movement_id"]
                if (kind not in ENDINGS or payload["policy"] != POLICY or type(person) is not int
                        or type(movement_id) is not int or type(payload["source_id"]) is not int
                        or not isinstance(payload["snapshot"], dict) or not isinstance(payload["changes"], dict)):
                    raise ValueError("invalid identity or policy")
            except (ValueError, TypeError, KeyError) as exc:
                raise ResidenceError("commitment ending has invalid recorded evidence") from exc
            table, owner, _, _, _ = ENDINGS[kind]
            if any(payload[key] != ending[key] for key in ("movement_id", "agent_id", "kind", "source_id")):
                raise ResidenceError("commitment ending disagrees with its immutable identity")
            if movement_id not in movements:
                movements[movement_id] = self.population._read(movement_id)
            movement = movements[movement_id]
            terms = json.loads(movement["terms_json"])
            residence = self.population.history.state_at(person, event["tick"], event_frontier=event["id"]-1)
            source, changes = payload["snapshot"], self.changes(kind, event["tick"])
            if (event["phase"] != "NIGHT_CLOSE" or event["subject_type"] != "agent" or event["subject_id"] != person
                    or movement["status"] != "applied" or movement["due_tick"] != event["tick"]
                    or movement["outcome_event_id"] <= event["id"] or terms["cause"] != "departure"
                    or person not in terms["member_ids"] or residence is None or residence["cause"] != "departure"
                    or residence["request_key"] != f"population:{movement_id}" or source.get(owner) != person
                    or source.get("id") != payload["source_id"] or type(source.get("id")) is not int
                    or type(source.get(owner)) is not int
                    or type(source.get("status")) is not str or source["status"] not in OPEN_STATES[kind]
                    or json.dumps(payload["changes"], sort_keys=True) != json.dumps(changes, sort_keys=True)
                    or (kind == "loan_application" and source.get("borrower_type") != "agent")):
                raise ResidenceError("commitment ending disagrees with its source or departure")
            identity = (kind, source["id"])
            if identity in seen:
                raise ResidenceError("one commitment was ended by multiple departures")
            seen.add(identity)
            actual = self.store.query_one(f"SELECT * FROM {table} WHERE id=?", (source["id"],))
            expected = {**source, **changes}
            if actual is None or any(key not in actual.keys() or actual[key] != value or type(actual[key]) is not type(value)
                                     for key, value in expected.items()):
                raise ResidenceError("an ended commitment was changed or reactivated")
        # Detect a missing ending record as well as a forged terminal snapshot.
        for kind, (table, owner, predicate, _, _) in ENDINGS.items():
            for person in self.store.query(f"SELECT DISTINCT {owner} AS agent_id FROM {table} WHERE {predicate}"):
                if (self.store.scalar("SELECT alive FROM agents WHERE id=?", (person["agent_id"],))
                        and not self.population.is_available(person["agent_id"])):
                    raise ResidenceError(f"an outside person retains local {kind}")

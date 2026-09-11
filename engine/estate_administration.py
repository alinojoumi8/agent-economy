"""Recorded regional public trustees for estates without private representation."""
from __future__ import annotations

from fractions import Fraction
import json

from .estates import EstateError


class EstateAdministration:
    POLICY = "regional_public_trustee_v1"

    def __init__(self, economy):
        self.e = economy
        self.store = economy.store
        self.enabled = economy.estate_cases.enabled

    def current(self, estate_id):
        return self.store.query_one("SELECT a.* FROM estate_administrations a WHERE a.estate_id=? "
            "AND NOT EXISTS (SELECT 1 FROM estate_administration_ends x WHERE x.administration_id=a.id)", (estate_id,))

    def _has_assets(self, estate_id):
        if self.e.estate_property.pending(estate_id):
            return True
        return any(self.e.estate_securities.remaining(lot) > 0 for lot in self.e.estate_securities.lots(estate_id))

    def _has_work(self, estate_id):
        return self._has_assets(estate_id) or self.e.estate_legal_work.has_rights(estate_id) or bool(self.store.scalar(
            "SELECT m.id FROM legal_matters m JOIN estate_cases c ON c.id=? WHERE "
            "m.status IN ('filed','pleading','hearing','settlement_offered') AND "
            "((m.claimant_type='agent' AND m.claimant_id=c.deceased_agent_id) OR "
            "(m.respondent_type='agent' AND m.respondent_id=c.deceased_agent_id)) LIMIT 1", (estate_id,)))

    def _region(self, case):
        return self.store.scalar("SELECT r.id FROM agents a JOIN regions r ON r.id=a.region_id WHERE a.id=?",
                                 (case["deceased_agent_id"],))

    def _eligible(self, actor_id, region_id):
        if actor_id is None or region_id is None:
            return None
        if self.e.engine_semantics_version >= 21 and not self.e.population.is_available(actor_id):
            return None
        return self.store.query_one("SELECT a.* FROM agents a WHERE a.id=? AND a.region_id=? "
            "AND a.alive=1 AND a.age>=18 AND a.role='gov_official' AND NOT EXISTS "
            "(SELECT 1 FROM estate_cases c WHERE c.deceased_agent_id=a.id)", (actor_id, region_id))

    def _candidate(self, region_id, previous):
        if previous is not None:
            incumbent = self._eligible(previous["administrator_agent_id"], region_id)
            if incumbent is not None:
                return incumbent
        if region_id is None:
            return None
        if self.e.engine_semantics_version >= 21:
            return next((row for row in self.store.query("SELECT a.* FROM agents a WHERE a.region_id=? AND a.alive=1 "
                "AND a.age>=18 AND a.role='gov_official' AND NOT EXISTS "
                "(SELECT 1 FROM estate_cases c WHERE c.deceased_agent_id=a.id) ORDER BY a.id", (region_id,))
                if self.e.population.is_available(row["id"])), None)
        return self.store.query_one("SELECT a.* FROM agents a WHERE a.region_id=? AND a.alive=1 "
            "AND a.age>=18 AND a.role='gov_official' AND NOT EXISTS "
            "(SELECT 1 FROM estate_cases c WHERE c.deceased_agent_id=a.id) ORDER BY a.id LIMIT 1", (region_id,))

    def reconcile(self, tick):
        """Keep an eligible incumbent; otherwise appoint by stable person ID."""
        if not self.enabled:
            return
        with self.store.savepoint("estate_administration_refresh"):
            for case in self.store.query("SELECT c.* FROM estate_cases c JOIN agents a ON a.id=c.deceased_agent_id "
                    "WHERE a.alive=0 AND c.completed_event_id IS NOT NULL AND ("
                    "EXISTS (SELECT 1 FROM estate_security_lots l WHERE l.estate_id=c.id AND NOT EXISTS "
                    "(SELECT 1 FROM estate_security_releases r WHERE r.lot_id=l.id)) OR "
                    "EXISTS (SELECT 1 FROM estate_project_custody p WHERE p.estate_id=c.id AND NOT EXISTS "
                    "(SELECT 1 FROM estate_project_releases r WHERE r.custody_id=p.id)) OR "
                    "EXISTS (SELECT 1 FROM legal_matters m WHERE m.status IN ('filed','pleading','hearing','settlement_offered') AND "
                    "((m.claimant_type='agent' AND m.claimant_id=c.deceased_agent_id) OR "
                    "(m.respondent_type='agent' AND m.respondent_id=c.deceased_agent_id))) OR "
                    "EXISTS (SELECT 1 FROM obligations o WHERE o.obligee_type='agent' AND o.obligee_id=c.deceased_agent_id "
                    "AND o.obligation_type IN ('payment','indemnity') AND o.status IN ('pending','breached')) OR "
                    "EXISTS (SELECT 1 FROM wage_claim_holders h JOIN wage_claims w ON w.id=h.claim_id WHERE "
                    "h.owner_type='agent' AND h.owner_id=c.deceased_agent_id AND h.ended_tick IS NULL AND w.closed_tick IS NULL) OR "
                    "EXISTS (SELECT 1 FROM estate_administrations d WHERE d.estate_id=c.id AND NOT EXISTS "
                    "(SELECT 1 FROM estate_administration_ends x WHERE x.administration_id=d.id))) ORDER BY c.id"):
                previous = self.current(case["id"])
                has_assets = self._has_work(case["id"])
                private = self.e.estate_securities.beneficiary_representatives(case["id"])
                region = self._region(case)
                candidate = self._candidate(region, previous) if has_assets and not private else None
                administrator = candidate["id"] if candidate is not None else None
                needs_disposition = has_assets and not private
                if previous is not None:
                    if needs_disposition and previous["administrator_agent_id"] == administrator and previous["region_id"] == region:
                        continue
                    if tick < previous["started_tick"]:
                        raise EstateError("estate administration cannot move backwards in time")
                    reason = ("assets_disposed" if not has_assets else "private_representative" if private else
                              "candidate_available" if previous["administrator_agent_id"] is None else "authority_lost")
                    event = self.store.log_event(tick, "estate_administration_ended", {
                        "estate_id": case["id"], "administration_id": previous["id"], "reason": reason},
                        phase="NIGHT_CLOSE", subject_type="agent", subject_id=case["deceased_agent_id"])
                    self.store.insert("estate_administration_ends", administration_id=previous["id"],
                                      tick=tick, reason=reason, event_id=event)
                if not needs_disposition:
                    continue
                payload = {"estate_id": case["id"], "administrator_agent_id": administrator, "region_id": region,
                    "authority_role": "gov_official" if candidate is not None else None,
                    "actor_age": candidate["age"] if candidate is not None else None, "policy": self.POLICY}
                event = self.store.log_event(tick, "estate_administration_started", payload,
                    phase="NIGHT_CLOSE", subject_type="agent", subject_id=case["deceased_agent_id"])
                self.store.insert("estate_administrations", **payload, started_tick=tick, event_id=event)

    def proof(self, estate_id):
        """Current appointment confers authority, never a beneficial interest."""
        if not self.enabled:
            return None
        row = self.current(estate_id)
        if row is None or not self._has_work(estate_id):
            return None
        actor = self._eligible(row["administrator_agent_id"], row["region_id"])
        if actor is None or self.e.estate_securities.beneficiary_representatives(estate_id):
            return None
        return dict(actor_id=actor["id"], beneficiary_id=None, guardian_id=None,
            administration_id=row["id"], actor_age=actor["age"], beneficiary_age=None,
            path=[], weight=Fraction(), authority="public_administrator")

    def check_order_authority(self, auth, tick):
        row = self.store.query_one("SELECT * FROM estate_administrations WHERE id=?", (auth["administration_id"],))
        if row is None or row["estate_id"] != auth["estate_id"] or row["administrator_agent_id"] != auth["actor_id"] or (
                row["started_tick"] > tick or row["authority_role"] != "gov_official" or auth["actor_age"] < row["actor_age"]):
            raise EstateError("estate order lacks its public administration appointment")
        frontier = auth["administration_end_frontier"]
        ended_tick = self.store.scalar("SELECT tick FROM estate_administration_ends WHERE id=?", (frontier,))
        if frontier and (ended_tick is None or ended_tick > tick):
            raise EstateError("estate order has an invalid administration frontier")
        if self.store.scalar("SELECT id FROM estate_administration_ends WHERE administration_id=? AND id<=?",
                             (row["id"], frontier)):
            raise EstateError("estate order uses an ended public administration appointment")
        if auth["beneficiary_id"] is not None or auth["guardian_id"] is not None or auth["beneficiary_age"] is not None or json.loads(auth["path_json"]) != []:
            raise EstateError("public administrator cannot claim a beneficial path")

    def _check_event(self, event_id, tick, kind, case, payload):
        event = self.store.query_one("SELECT * FROM events WHERE id=?", (event_id,))
        if event is None or event["tick"] != tick or event["kind"] != kind or (
                event["subject_type"] != "agent" or event["subject_id"] != case["deceased_agent_id"]
                or json.loads(event["payload_json"]) != payload):
            raise EstateError("estate administration lacks its recorded authority event")

    def check_invariants(self):
        if not self.enabled:
            return
        if self.store.scalar("SELECT x.id FROM estate_administration_ends x LEFT JOIN estate_administrations a "
                             "ON a.id=x.administration_id WHERE a.id IS NULL LIMIT 1"):
            raise EstateError("orphaned estate administration ending")
        previous = {}
        for row in self.store.query("SELECT * FROM estate_administrations ORDER BY id"):
            case = self.store.query_one("SELECT * FROM estate_cases WHERE id=?", (row["estate_id"],))
            if case is None or row["started_tick"] < case["opened_tick"] or row["region_id"] != self._region(case):
                raise EstateError("estate administration has the wrong estate, region or time")
            earlier = previous.get(case["id"])
            if earlier is not None:
                end = self.store.query_one("SELECT * FROM estate_administration_ends WHERE administration_id=?", (earlier["id"],))
                if end is None or end["tick"] > row["started_tick"]:
                    raise EstateError("estate administration intervals overlap")
            actor = self.store.query_one("SELECT * FROM agents WHERE id=?", (row["administrator_agent_id"],))
            if row["administrator_agent_id"] is not None and (actor is None or actor["age"] < row["actor_age"] or (
                    actor["died_tick"] is not None and actor["died_tick"] < row["started_tick"])):
                raise EstateError("estate public trustee has invalid identity or age evidence")
            self._check_event(row["event_id"], row["started_tick"], "estate_administration_started", case,
                {key: row[key] for key in ("estate_id", "administrator_agent_id", "region_id", "authority_role", "actor_age", "policy")})
            end = self.store.query_one("SELECT * FROM estate_administration_ends WHERE administration_id=?", (row["id"],))
            if end is not None:
                if end["tick"] < row["started_tick"]:
                    raise EstateError("estate administration ending predates appointment")
                self._check_event(end["event_id"], end["tick"], "estate_administration_ended", case,
                    {"estate_id": case["id"], "administration_id": row["id"], "reason": end["reason"]})
            previous[case["id"]] = row
        for case in self.store.query("SELECT c.* FROM estate_cases c JOIN agents a ON a.id=c.deceased_agent_id "
                "WHERE a.alive=0 AND c.completed_event_id IS NOT NULL ORDER BY c.id"):
            current = self.current(case["id"])
            needed = self._has_work(case["id"]) and not self.e.estate_securities.beneficiary_representatives(case["id"])
            if bool(current is not None) != bool(needed):
                raise EstateError("estate lacks its current public administration disposition")
            if current is not None:
                candidate = self._candidate(self._region(case), current)
                if current["administrator_agent_id"] != (candidate["id"] if candidate is not None else None):
                    raise EstateError("estate public administration does not follow current authority")

"""Unpriced project interests retained for estate creditors and later residuals."""
from __future__ import annotations

from fractions import Fraction
import json

from .estate_assets import EstateAssetCustody
from .estates import EstateError


class EstateProperty(EstateAssetCustody):
    def currency_for(self, project):
        currency = self.store.scalar("SELECT currency_code FROM accounts WHERE id=?", (project["escrow_account_id"],))
        if not currency:
            raise EstateError("estate property lacks its settlement-currency account")
        return currency

    def pending(self, estate_id=None, project_id=None):
        return self.store.query("SELECT c.*,l.project_id FROM estate_project_custody c "
            "JOIN project_interest_lots l ON l.id=c.interest_lot_id WHERE (? IS NULL OR c.estate_id=?) "
            "AND (? IS NULL OR l.project_id=?) AND NOT EXISTS "
            "(SELECT 1 FROM estate_project_releases r WHERE r.custody_id=c.id) ORDER BY c.id",
            (estate_id, estate_id, project_id, project_id))

    def _retain(self, tick, estate_id, interest_id, *, origin):
        return self.store.insert("estate_project_custody", estate_id=estate_id,
            interest_lot_id=interest_id, opened_tick=tick, origin=origin, policy="known_claims_then_residual_v1")

    def open(self, tick, estate_id, agent_id):
        for project in self.e.project_rights.owned_projects(agent_id):
            self.e.project_rights._seed(project)
            retain = self.needs_custody(tick, estate_id, self.currency_for(project))
            for lot in self.store.query("SELECT * FROM project_interest_lots WHERE project_id=? "
                    "AND agent_id=? AND ended_tick IS NULL ORDER BY id", (project["id"], agent_id)):
                if retain:
                    self._retain(tick, estate_id, lot["id"], origin="opening")
                else:
                    self.e.project_rights._distribute_lot(tick, estate_id, lot)
            self.e.project_rights.cancel_if_unclaimed(tick, project["id"])

    def accept_lot(self, tick, estate_id, interest_id):
        # Late title can pass through another deceased beneficiary. Even an
        # immediately released receipt keeps its own custody/disposition proof.
        self._retain(tick, estate_id, interest_id, origin="inheritance")
        self.release_ready(tick, estate_id)

    def release_ready(self, tick, estate_id):
        with self.e.estate_cases._batch():
            self._release_ready(tick, estate_id)

    def _release_ready(self, tick, estate_id):
        for custody in self.pending(estate_id):
            project = self.store.query_one("SELECT * FROM construction_projects WHERE id=?", (custody["project_id"],))
            if project["status"] == "cancelled":
                self.store.insert("estate_project_releases", custody_id=custody["id"], tick=tick,
                    disposition="cancelled", cancellation_event_id=project["cancellation_event_id"], **self._frontier())
                continue
            if self.needs_custody(tick, estate_id, self.currency_for(project)):
                continue
            with self.store.savepoint("estate_project_release"):
                self.store.insert("estate_project_releases", custody_id=custody["id"], tick=tick,
                                  disposition="distributed", **self._frontier())
                lot = self.store.query_one("SELECT * FROM project_interest_lots WHERE id=?", (custody["interest_lot_id"],))
                self.e.project_rights._distribute_lot(tick, estate_id, lot)
                self.e.project_rights.cancel_if_unclaimed(tick, project["id"])

    def close_cancelled(self, tick, project_id):
        if not self.enabled:
            return
        for estate_id in sorted({row["estate_id"] for row in self.pending(project_id=project_id)}):
            self.release_ready(tick, estate_id)
        self.e.project_rights.refresh(tick)

    def operator_for(self, project_id):
        portions = {}
        for custody in self.pending(project_id=project_id):
            lot = self.store.query_one("SELECT * FROM project_interest_lots WHERE id=?", (custody["interest_lot_id"],))
            portions[custody["estate_id"]] = portions.get(custody["estate_id"], Fraction()) + Fraction(
                int(lot["numerator"]), int(lot["denominator"]))
        for estate_id in sorted(portions, key=lambda case: (-portions[case], case)):
            representatives = self.representatives(estate_id)
            if representatives:
                actor = representatives[0]
                administration = actor.get("administration_id")
                return (actor["actor_id"], "administrator" if administration is not None else "estate",
                        actor["beneficiary_id"], estate_id, administration)
        return None

    def check_invariants(self):
        if not self.enabled:
            return
        if self.store.scalar("SELECT r.id FROM estate_project_releases r LEFT JOIN estate_project_custody c "
                             "ON c.id=r.custody_id WHERE c.id IS NULL LIMIT 1"):
            raise EstateError("orphaned estate project release")
        for custody in self.store.query("SELECT * FROM estate_project_custody ORDER BY id"):
            case = self.store.query_one("SELECT * FROM estate_cases WHERE id=?", (custody["estate_id"],))
            lot = self.store.query_one("SELECT * FROM project_interest_lots WHERE id=?", (custody["interest_lot_id"],))
            if case is None or lot is None or lot["agent_id"] != case["deceased_agent_id"] or (
                    custody["opened_tick"] < case["opened_tick"] or lot["started_tick"] > custody["opened_tick"]):
                raise EstateError("estate property custody has the wrong owner or time")
            project = self.store.query_one("SELECT * FROM construction_projects WHERE id=?", (lot["project_id"],))
            if project is None or project["owner_type"] != "agent":
                raise EstateError("estate property custody lacks a personal project")
            if custody["origin"] == "opening":
                item = self.store.query_one("SELECT * FROM estate_items WHERE estate_id=? "
                    "AND kind='personal_project' AND source_id=?", (case["id"], project["id"]))
                if custody["opened_tick"] != case["opened_tick"] or item is None or json.loads(item["snapshot_json"]).get("id") != project["id"]:
                    raise EstateError("estate property custody lacks its opening inventory")
            elif lot["started_tick"] != custody["opened_tick"] or lot["prior_lot_id"] is None or lot["estate_id"] == case["id"]:
                raise EstateError("late estate property custody lacks its inherited source")
            release = self.store.query_one("SELECT * FROM estate_project_releases WHERE custody_id=?", (custody["id"],))
            if release is None:
                if lot["ended_tick"] is not None or project["status"] == "cancelled":
                    raise EstateError("retained estate property lacks a disposition")
                continue
            if release["tick"] < custody["opened_tick"]:
                raise EstateError("estate property release predates custody")
            if release["disposition"] == "distributed":
                if lot["ended_tick"] != release["tick"] or not self.store.scalar(
                        "SELECT id FROM project_interest_lots WHERE prior_lot_id=? AND estate_id=? LIMIT 1", (lot["id"], case["id"])):
                    raise EstateError("estate property release lacks its in-kind distribution")
                self.check_release_frontier(release["tick"], case["id"], self.currency_for(project), release)
            elif release["disposition"] == "sold":
                sale = self.store.query_one("SELECT * FROM estate_property_sales WHERE custody_id=?", (custody["id"],))
                if sale is None:
                    raise EstateError("estate property sale lacks its funded disposition")
                self.e.estate_property_sales.check_sale(sale)
            else:
                event = self.store.query_one("SELECT * FROM events WHERE id=?", (release["cancellation_event_id"],))
                if (project["status"] != "cancelled" or project["cancelled_tick"] != release["tick"]
                        or project["cancellation_event_id"] != release["cancellation_event_id"] or event is None
                        or event["kind"] != "construction_project_cancelled" or event["subject_id"] != project["id"]
                        or event["tick"] != release["tick"] or lot["ended_tick"] is not None):
                    raise EstateError("estate property extinguishment lacks an actual cancellation")

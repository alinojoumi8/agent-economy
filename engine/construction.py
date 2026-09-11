"""Deterministic Semantics-13 construction lifecycle."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .ledger import SYS_CONSTRUCTION


TERMINAL_STATUSES = {"completed", "cancelled"}
_PROVENANCE_FIELDS = {"evidence_event_ids", "model_call_id", "rationale_summary"}
DEFAULT_CONSTRUCTION_CONFIG = {
    "enabled": False,
    "agent_initiation": True,
    "private_home_funding_cents": 20_000,
    "workplace_funding_cents": 60_000,
    "public_facility_funding_cents": 80_000,
    "private_home_work_units": 4,
    "workplace_work_units": 8,
    "public_facility_work_units": 10,
    "funding_contribution_cents": 10_000,
    "work_units_per_action": 2,
}


def _json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _evidence(action: Mapping[str, Any]) -> list[int]:
    values = action.get("evidence_event_ids", [])
    if not isinstance(values, list):
        return []
    return sorted({
        int(value) for value in values
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
    })


class ConstructionEconomy:
    """Action-driven projects that become places only when completed."""

    def __init__(self, economy, config: dict | None = None):
        self.e = economy
        self.store = economy.store
        self.ledger = economy.ledger
        self.engine_semantics_version = int(economy.engine_semantics_version)
        self.config = {**DEFAULT_CONSTRUCTION_CONFIG, **dict(config or {})}
        requested = bool(self.config.get("enabled", False))
        if requested and self.engine_semantics_version < 13:
            raise ValueError(
                "construction.enabled requires engine_semantics_version 13")
        if requested and not bool(economy.city.enabled):
            raise ValueError("construction.enabled requires city.enabled")
        self.enabled = requested and self.engine_semantics_version >= 13

    # Receipts make all construction commands safely repeatable.
    def _payload_hash(self, action: Mapping[str, Any]) -> str:
        return _hash({
            key: value for key, value in action.items()
            if key not in _PROVENANCE_FIELDS
        })

    def _cached(
        self, actor_id: int, action_type: str, action: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        row = self.store.query_one(
            "SELECT action_type,payload_hash,result_json "
            "FROM construction_action_receipts "
            "WHERE actor_agent_id=? AND dedupe_key=?",
            (int(actor_id), str(action["dedupe_key"])),
        )
        if row is None:
            return None
        if (
            str(row["action_type"]) != action_type
            or str(row["payload_hash"]) != self._payload_hash(action)
        ):
            return {
                "ok": False,
                "reason": "construction dedupe_key was already used for another payload",
                "idempotency_conflict": True,
            }
        result = json.loads(str(row["result_json"]))
        result["idempotent"] = True
        return result

    def _finish(
        self, tick: int, actor_id: int, action_type: str,
        action: Mapping[str, Any], result: dict[str, Any],
        project_id: int | None = None,
    ) -> dict[str, Any]:
        self.store.insert(
            "construction_action_receipts",
            actor_agent_id=int(actor_id),
            dedupe_key=str(action["dedupe_key"]),
            action_type=action_type,
            payload_hash=self._payload_hash(action),
            project_id=int(project_id) if project_id is not None else None,
            tick=int(tick),
            ok=1 if result.get("ok") else 0,
            result_json=_json(result),
        )
        return result

    def _start(
        self, actor_id: int, action_type: str, action: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        cached = self._cached(actor_id, action_type, action)
        if cached is not None:
            return cached
        if not self.enabled:
            return {"ok": False, "reason": "construction economy is not enabled"}
        if (self.e.engine_semantics_version >= 21
                and not self.e.population.is_available(actor_id)):
            return {"ok": False, "reason": "construction requires a local actor"}
        return None

    def _project(self, project_id: int):
        return self.store.query_one(
            "SELECT * FROM construction_projects WHERE id=?",
            (int(project_id),),
        )

    def _controls_firm(self, actor_id: int, firm_id: int) -> bool:
        if self.e.business_control.enabled:
            return self.e.business_control.controls(actor_id, firm_id)
        firm = self.store.query_one(
            "SELECT founder_agent_id,status FROM firms WHERE id=?",
            (int(firm_id),),
        )
        if firm is None or str(firm["status"]) == "bankrupt":
            return False
        if int(firm["founder_agent_id"] or 0) == int(actor_id):
            return True
        agent = self.store.query_one(
            "SELECT employer_id,role FROM agents WHERE id=?", (int(actor_id),))
        return bool(
            agent is not None
            and int(agent["employer_id"] or 0) == int(firm_id)
            and str(agent["role"] or "") in {"manager", "founder"}
        )

    def _staffs_agency(
        self, actor_id: int, agency_id: int, region_id: int | None = None,
    ) -> bool:
        clause = ""
        params: list[Any] = [int(actor_id), int(agency_id)]
        if region_id is not None:
            clause = " AND region_id=?"
            params.append(int(region_id))
        return self.store.query_one(
            "SELECT 1 FROM agency_staff WHERE agent_id=? AND agency_id=? "
            "AND role_key='permit_clerk' AND active=1" + clause + " LIMIT 1",
            tuple(params),
        ) is not None

    def _authorized_owner(
        self, actor_id: int, owner_type: str, owner_id: int, region_id: int,
    ) -> bool:
        if owner_type == "agent":
            current = self.store.scalar(
                "SELECT region_id FROM agents WHERE id=?",
                (int(actor_id),), default=None)
            return (
                int(owner_id) == int(actor_id)
                and current is not None
                and int(current) == int(region_id)
            )
        if owner_type == "firm":
            firm_region = self.store.scalar(
                "SELECT region_id FROM firms WHERE id=?",
                (int(owner_id),), default=None)
            return (
                firm_region is not None
                and int(firm_region) == int(region_id)
                and self._controls_firm(actor_id, owner_id)
            )
        return (
            owner_type == "agency"
            and self._staffs_agency(actor_id, owner_id, region_id)
        )

    def _authorized_project(self, actor_id: int, project) -> bool:
        if self.engine_semantics_version >= 20 and project["owner_type"] == "agent":
            return self.e.project_rights.controls(actor_id, project)
        return self._authorized_owner(
            actor_id, str(project["owner_type"]), int(project["owner_id"]),
            int(project["region_id"]))

    def _merge_evidence(self, project, action: Mapping[str, Any]) -> str:
        try:
            current = json.loads(str(project["evidence_refs_json"] or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            current = []
        return _json(sorted({
            int(item) for item in [*current, *_evidence(action)]
            if isinstance(item, int) and not isinstance(item, bool) and item > 0
        }))

    @staticmethod
    def stage_for(work_units: int, required_work_units: int) -> str:
        work = max(0, int(work_units))
        required = max(1, int(required_work_units))
        if work >= required:
            return "completed"
        if work >= (2 * required + 2) // 3:
            return "shell"
        if work >= (required + 2) // 3:
            return "frame"
        return "foundation"

    def propose(
        self, tick: int, actor_id: int, action: Mapping[str, Any],
    ) -> dict[str, Any]:
        action_type = "propose_construction"
        cached = self._start(actor_id, action_type, action)
        if cached is not None:
            return cached if cached.get("idempotent") or cached.get(
                "idempotency_conflict") else self._finish(
                    tick, actor_id, action_type, action, cached)
        owner_type = str(action["owner_type"])
        owner_id = int(action["owner_id"])
        region_id = int(action["region_id"])
        target = str(action["target_place_type"])
        expected = {
            "private_home": "agent",
            "workplace": "firm",
            "public_facility": "agency",
        }
        if expected.get(target) != owner_type:
            return self._finish(tick, actor_id, action_type, action, {
                "ok": False,
                "reason": f"{target} projects must be owned by {expected.get(target)}",
            })
        region = self.store.query_one(
            "SELECT * FROM regions WHERE id=?", (region_id,))
        if region is None:
            return self._finish(tick, actor_id, action_type, action, {
                "ok": False, "reason": "construction region does not exist"})
        if not self._authorized_owner(
                actor_id, owner_type, owner_id, region_id):
            return self._finish(tick, actor_id, action_type, action, {
                "ok": False,
                "reason": "actor is not authorized for the construction owner",
            })
        existing = self.store.query_one(
            "SELECT id FROM construction_projects "
            "WHERE owner_type=? AND owner_id=? AND target_place_type=? "
            "AND status IN ('proposed','permitting','funding','building') "
            "ORDER BY id LIMIT 1",
            (owner_type, owner_id, target),
        )
        if self.engine_semantics_version >= 20 and owner_type == "agent":
            inherited = [p for p in self.e.project_rights.owned_projects(owner_id)
                         if p["target_place_type"] == target and p["status"] not in TERMINAL_STATUSES]
            if inherited:
                existing = min(inherited, key=lambda p: p["id"])
        if existing is not None:
            project_id = int(existing["id"])
            return self._finish(tick, actor_id, action_type, action, {
                "ok": False,
                "reason": "owner already has an active project of this kind",
                "project_id": project_id,
            }, project_id)
        if target == "workplace" and self.store.query_one(
                "SELECT 1 FROM places WHERE owner_type='firm' AND owner_id=? "
                "AND kind='firm_workplace' AND active=1 LIMIT 1", (owner_id,)):
            return self._finish(tick, actor_id, action_type, action, {
                "ok": False, "reason": "firm already has an operational workplace"})
        checking_id = self.ledger.agent_checking_id(int(actor_id))
        if checking_id is None:
            return self._finish(tick, actor_id, action_type, action, {
                "ok": False, "reason": "initiator has no checking account"})
        currency = str(self.store.scalar(
            "SELECT currency_code FROM accounts WHERE id=?",
            (checking_id,), default="USD") or "USD")
        site_key = str(action["site_key"])
        occupied_site = self.store.query_one(
            "SELECT id FROM construction_projects WHERE region_id=? "
            "AND site_key=? AND status<>'cancelled' ORDER BY id LIMIT 1",
            (region_id, site_key),
        )
        if occupied_site is not None:
            return self._finish(tick, actor_id, action_type, action, {
                "ok": False,
                "reason": "construction site already has a non-cancelled project",
                "project_id": int(occupied_site["id"]),
            }, int(occupied_site["id"]))
        project_key = "construction:" + _hash({
            "actor_id": int(actor_id),
            "dedupe_key": str(action["dedupe_key"]),
        })[:32]
        place_key = f"construction-site:{site_key}"
        site_x, site_y = self.e.city._coordinates(region, place_key)
        escrow_id = self.ledger.create_account(
            "construction_project", None, "escrow",
            label=f"{project_key}:escrow", currency_code=currency)
        project_id = self.store.insert(
            "construction_projects",
            project_key=project_key,
            name=str(action["name"]),
            owner_type=owner_type,
            owner_id=owner_id,
            initiator_agent_id=int(actor_id),
            region_id=region_id,
            site_key=site_key,
            site_x=site_x,
            site_y=site_y,
            target_place_type=target,
            status="proposed",
            required_funding_cents=int(action["required_funding_cents"]),
            required_work_units=int(action["required_work_units"]),
            escrow_account_id=escrow_id,
            proposed_tick=int(tick),
            evidence_refs_json=_json(_evidence(action)),
        )
        self.store.execute(
            "UPDATE accounts SET owner_id=? WHERE id=?", (project_id, escrow_id))
        event_id = self.store.log_event(
            tick, "construction_project_proposed", {
                "project_id": project_id,
                "project_key": project_key,
                "owner_type": owner_type,
                "owner_id": owner_id,
                "region_id": region_id,
                "target_place_type": target,
                "required_funding_cents": int(action["required_funding_cents"]),
                "required_work_units": int(action["required_work_units"]),
                "evidence_event_ids": _evidence(action),
            }, phase="EXECUTION", subject_type="construction_project",
            subject_id=project_id, importance=2.5)
        self.store.update(
            "construction_projects", project_id, proposed_event_id=event_id)
        return self._finish(tick, actor_id, action_type, action, {
            "ok": True,
            "project_id": project_id,
            "project_key": project_key,
            "status": "proposed",
        }, project_id)

    def apply_permit(
        self, tick: int, actor_id: int, action: Mapping[str, Any],
    ) -> dict[str, Any]:
        action_type = "apply_construction_permit"
        cached = self._start(actor_id, action_type, action)
        if cached is not None:
            return cached if cached.get("idempotent") or cached.get(
                "idempotency_conflict") else self._finish(
                    tick, actor_id, action_type, action, cached)
        project_id = int(action["project_id"])
        project = self._project(project_id)
        if project is None:
            return self._finish(tick, actor_id, action_type, action, {
                "ok": False, "reason": "construction project does not exist"})
        if not self._authorized_project(actor_id, project):
            return self._finish(tick, actor_id, action_type, action, {
                "ok": False, "reason": "actor cannot apply for this project permit",
            }, project_id)
        if str(project["status"]) != "proposed":
            return self._finish(tick, actor_id, action_type, action, {
                "ok": False,
                "reason": "construction permit requires a proposed project",
            }, project_id)
        agency_id = int(self.e.city._agency_for_region(int(project["region_id"])))
        case_id = self.store.insert(
            "construction_permit_cases",
            project_id=project_id,
            agency_id=agency_id,
            applicant_agent_id=int(actor_id),
            region_id=int(project["region_id"]),
            status="submitted",
            created_tick=int(tick),
        )
        self.store.update(
            "construction_projects", project_id, status="permitting",
            permit_case_id=case_id, permitting_tick=int(tick),
            evidence_refs_json=self._merge_evidence(project, action))
        event_id = self.store.log_event(
            tick, "construction_permit_submitted", {
                "project_id": project_id,
                "permit_case_id": case_id,
                "agency_id": agency_id,
                "applicant_agent_id": int(actor_id),
                "evidence_event_ids": _evidence(action),
            }, phase="EXECUTION", subject_type="construction_project",
            subject_id=project_id, importance=2.0)
        self.store.update(
            "construction_permit_cases", case_id, created_event_id=event_id)
        return self._finish(tick, actor_id, action_type, action, {
            "ok": True,
            "project_id": project_id,
            "permit_case_id": case_id,
            "status": "permitting",
        }, project_id)

    def decide_permit(
        self, tick: int, actor_id: int, action: Mapping[str, Any],
    ) -> dict[str, Any]:
        action_type = "decide_construction_permit"
        cached = self._start(actor_id, action_type, action)
        if cached is not None:
            return cached if cached.get("idempotent") or cached.get(
                "idempotency_conflict") else self._finish(
                    tick, actor_id, action_type, action, cached)
        case_id = int(action["case_id"])
        case = self.store.query_one(
            "SELECT c.*,p.status AS project_status "
            "FROM construction_permit_cases c "
            "JOIN construction_projects p ON p.id=c.project_id WHERE c.id=?",
            (case_id,),
        )
        if case is None:
            return self._finish(tick, actor_id, action_type, action, {
                "ok": False, "reason": "construction permit case does not exist"})
        project_id = int(case["project_id"])
        if not self._staffs_agency(
                actor_id, int(case["agency_id"]), int(case["region_id"])):
            return self._finish(tick, actor_id, action_type, action, {
                "ok": False,
                "reason": "construction permit is not assigned to this agency staff",
            }, project_id)
        if (
            str(case["status"]) != "submitted"
            or str(case["project_status"]) != "permitting"
        ):
            return self._finish(tick, actor_id, action_type, action, {
                "ok": False, "reason": "construction permit is no longer pending",
            }, project_id)
        decision = str(action["decision"])
        approved = decision == "approve"
        case_status = "approved" if approved else "denied"
        project_status = "funding" if approved else "cancelled"
        event_id = self.store.log_event(
            tick, f"construction_permit_{case_status}", {
                "project_id": project_id,
                "permit_case_id": case_id,
                "decision_actor_id": int(actor_id),
                "decision": decision,
                "reason_code": str(action["reason_code"]),
                "evidence_event_ids": _evidence(action),
            }, phase="EXECUTION", subject_type="construction_project",
            subject_id=project_id, importance=2.5)
        self.store.update(
            "construction_permit_cases", case_id, status=case_status,
            decided_tick=int(tick), decision_actor_id=int(actor_id),
            reason_code=str(action["reason_code"]), outcome_event_id=event_id)
        project = self._project(project_id)
        updates: dict[str, Any] = {
            "status": project_status,
            "permit_event_id": event_id,
            "evidence_refs_json": self._merge_evidence(project, action),
        }
        if approved:
            updates["funding_tick"] = int(tick)
        else:
            updates.update({
                "cancelled_tick": int(tick),
                "cancellation_event_id": event_id,
            })
        self.store.update("construction_projects", project_id, **updates)
        return self._finish(tick, actor_id, action_type, action, {
            "ok": True,
            "project_id": project_id,
            "permit_case_id": case_id,
            "decision": decision,
            "status": project_status,
        }, project_id)

    def contribute_funding(
        self, tick: int, actor_id: int, action: Mapping[str, Any],
    ) -> dict[str, Any]:
        action_type = "contribute_construction_funding"
        cached = self._start(actor_id, action_type, action)
        if cached is not None:
            return cached if cached.get("idempotent") or cached.get(
                "idempotency_conflict") else self._finish(
                    tick, actor_id, action_type, action, cached)
        project_id = int(action["project_id"])
        project = self._project(project_id)
        if project is None:
            return self._finish(tick, actor_id, action_type, action, {
                "ok": False, "reason": "construction project does not exist"})
        if str(project["status"]) != "funding":
            return self._finish(tick, actor_id, action_type, action, {
                "ok": False,
                "reason": "construction funding requires an approved permit",
            }, project_id)
        remaining = (
            int(project["required_funding_cents"])
            - int(project["contributed_funding_cents"])
        )
        amount = int(action["amount_cents"])
        if amount > remaining:
            return self._finish(tick, actor_id, action_type, action, {
                "ok": False,
                "reason": f"funding exceeds remaining requirement of {remaining} cents",
            }, project_id)
        checking_id = self.ledger.agent_checking_id(int(actor_id))
        if checking_id is None:
            return self._finish(tick, actor_id, action_type, action, {
                "ok": False, "reason": "contributor has no checking account",
            }, project_id)
        if self.ledger.balance(checking_id) < amount:
            return self._finish(tick, actor_id, action_type, action, {
                "ok": False,
                "reason": "insufficient funds for construction contribution",
            }, project_id)
        source_currency = str(self.store.scalar(
            "SELECT currency_code FROM accounts WHERE id=?",
            (checking_id,), default="USD") or "USD")
        escrow_id = int(project["escrow_account_id"])
        escrow_currency = str(self.store.scalar(
            "SELECT currency_code FROM accounts WHERE id=?",
            (escrow_id,), default="USD") or "USD")
        if source_currency != escrow_currency:
            return self._finish(tick, actor_id, action_type, action, {
                "ok": False,
                "reason": "construction contribution currency does not match escrow",
            }, project_id)
        transaction_id = self.ledger.transfer(
            tick, checking_id, escrow_id, amount, kind="construction_funding",
            memo=f"agent {actor_id} funds construction project {project_id}")
        contribution_id = self.store.insert(
            "construction_contributions",
            dedupe_key=_hash({
                "actor_id": int(actor_id),
                "dedupe_key": str(action["dedupe_key"]),
                "kind": "funding",
            }),
            project_id=project_id,
            actor_agent_id=int(actor_id),
            contribution_type="funding",
            amount_cents=amount,
            work_units=0,
            source_account_id=checking_id,
            transaction_id=transaction_id,
            tick=int(tick),
            evidence_refs_json=_json(_evidence(action)),
            metadata_json="{}",
        )
        total = int(project["contributed_funding_cents"]) + amount
        fully_funded = total == int(project["required_funding_cents"])
        updates: dict[str, Any] = {
            "contributed_funding_cents": total,
            "evidence_refs_json": self._merge_evidence(project, action),
        }
        if fully_funded:
            updates.update({
                "status": "building",
                "building_tick": int(tick),
                "foundation_tick": int(tick),
            })
        self.store.update("construction_projects", project_id, **updates)
        event_id = self.store.log_event(
            tick, "construction_funding_contributed", {
                "project_id": project_id,
                "contribution_id": contribution_id,
                "contributor_agent_id": int(actor_id),
                "amount_cents": amount,
                "transaction_id": transaction_id,
                "contributed_funding_cents": total,
                "required_funding_cents": int(project["required_funding_cents"]),
                "status": "building" if fully_funded else "funding",
                "stage": "foundation" if fully_funded else None,
                "evidence_event_ids": _evidence(action),
            }, phase="EXECUTION", subject_type="construction_project",
            subject_id=project_id, importance=2.0)
        self.store.update(
            "construction_contributions", contribution_id,
            evidence_event_id=event_id)
        return self._finish(tick, actor_id, action_type, action, {
            "ok": True,
            "project_id": project_id,
            "contribution_id": contribution_id,
            "transaction_id": transaction_id,
            "contributed_funding_cents": total,
            "required_funding_cents": int(project["required_funding_cents"]),
            "status": "building" if fully_funded else "funding",
            "stage": "foundation" if fully_funded else None,
        }, project_id)

    def perform_work(
        self, tick: int, actor_id: int, action: Mapping[str, Any],
    ) -> dict[str, Any]:
        if self.e.engine_semantics_version >= 18:
            cached = self._start(actor_id, "perform_construction_work", action)
            if cached is not None:
                return self._perform_work(tick, actor_id, action)
            return self.e.daily_time.perform(tick, actor_id, f"construction:{action['dedupe_key']}",
                "construction", int(action["work_units"]) * self.e.daily_time.p["construction_minutes_per_unit"],
                dict(action), lambda: self._perform_work(tick, actor_id, action))
        return self._perform_work(tick, actor_id, action)

    def _perform_work(
        self, tick: int, actor_id: int, action: Mapping[str, Any],
    ) -> dict[str, Any]:
        action_type = "perform_construction_work"
        cached = self._start(actor_id, action_type, action)
        if cached is not None:
            return cached if cached.get("idempotent") or cached.get(
                "idempotency_conflict") else self._finish(
                    tick, actor_id, action_type, action, cached)
        project_id = int(action["project_id"])
        project = self._project(project_id)
        if project is None:
            return self._finish(tick, actor_id, action_type, action, {
                "ok": False, "reason": "construction project does not exist"})
        if str(project["status"]) != "building":
            return self._finish(tick, actor_id, action_type, action, {
                "ok": False,
                "reason": "construction work requires a fully funded project",
            }, project_id)
        if (
            int(project["contributed_funding_cents"])
            < int(project["required_funding_cents"])
        ):
            return self._finish(tick, actor_id, action_type, action, {
                "ok": False, "reason": "construction funding requirement is unmet",
            }, project_id)
        remaining_work = (
            int(project["required_work_units"])
            - int(project["contributed_work_units"])
        )
        work_units = int(action["work_units"])
        if work_units > remaining_work:
            return self._finish(tick, actor_id, action_type, action, {
                "ok": False,
                "reason": f"work exceeds remaining requirement of {remaining_work} units",
            }, project_id)
        wage_cents = int(action["wage_cents"])
        procurement_cents = int(action["procurement_cents"])
        cost = wage_cents + procurement_cents
        maximum_cost = (
            int(project["required_funding_cents"]) * work_units
            + int(project["required_work_units"]) - 1
        ) // int(project["required_work_units"])
        if cost > maximum_cost:
            return self._finish(tick, actor_id, action_type, action, {
                "ok": False,
                "reason": (
                    "construction work costs exceed the deterministic "
                    f"{maximum_cost}-cent budget for {work_units} work units"),
            }, project_id)
        escrow_id = int(project["escrow_account_id"])
        if self.ledger.balance(escrow_id) < cost:
            return self._finish(tick, actor_id, action_type, action, {
                "ok": False, "reason": "construction escrow cannot cover work costs",
            }, project_id)
        wage_transaction_id = None
        if wage_cents:
            checking_id = self.ledger.agent_checking_id(int(actor_id))
            if checking_id is None:
                return self._finish(tick, actor_id, action_type, action, {
                    "ok": False, "reason": "worker has no checking account",
                }, project_id)
            escrow_currency = str(self.store.scalar(
                "SELECT currency_code FROM accounts WHERE id=?",
                (escrow_id,), default="USD") or "USD")
            worker_currency = str(self.store.scalar(
                "SELECT currency_code FROM accounts WHERE id=?",
                (checking_id,), default="USD") or "USD")
            if worker_currency != escrow_currency:
                return self._finish(tick, actor_id, action_type, action, {
                    "ok": False,
                    "reason": "construction wage currency does not match escrow",
                }, project_id)
            wage_transaction_id = self.ledger.transfer(
                tick, escrow_id, checking_id, wage_cents,
                kind="construction_wage",
                memo=f"project {project_id} wage to agent {actor_id}")
        procurement_transaction_id = None
        if procurement_cents:
            currency = str(self.store.scalar(
                "SELECT currency_code FROM accounts WHERE id=?",
                (escrow_id,), default="USD") or "USD")
            materials = self.ledger.system_account(
                SYS_CONSTRUCTION, currency_code=currency)
            procurement_transaction_id = self.ledger.transfer(
                tick, escrow_id, materials, procurement_cents,
                kind="construction_procurement",
                memo=f"materials for construction project {project_id}")
        contribution_id = self.store.insert(
            "construction_contributions",
            dedupe_key=_hash({
                "actor_id": int(actor_id),
                "dedupe_key": str(action["dedupe_key"]),
                "kind": "work",
            }),
            project_id=project_id,
            actor_agent_id=int(actor_id),
            contribution_type="work",
            amount_cents=0,
            work_units=work_units,
            wage_transaction_id=wage_transaction_id,
            procurement_transaction_id=procurement_transaction_id,
            tick=int(tick),
            evidence_refs_json=_json(_evidence(action)),
            metadata_json=_json({
                "wage_cents": wage_cents,
                "procurement_cents": procurement_cents,
            }),
        )
        total_work = int(project["contributed_work_units"]) + work_units
        stage = self.stage_for(total_work, int(project["required_work_units"]))
        updates: dict[str, Any] = {
            "contributed_work_units": total_work,
            "spent_funding_cents": int(project["spent_funding_cents"]) + cost,
            "evidence_refs_json": self._merge_evidence(project, action),
        }
        if (
            stage in {"frame", "shell", "completed"}
            and project["frame_tick"] is None
        ):
            updates["frame_tick"] = int(tick)
        if stage in {"shell", "completed"} and project["shell_tick"] is None:
            updates["shell_tick"] = int(tick)
        self.store.update("construction_projects", project_id, **updates)
        event_id = self.store.log_event(
            tick, "construction_work_contributed", {
                "project_id": project_id,
                "contribution_id": contribution_id,
                "worker_agent_id": int(actor_id),
                "work_units": work_units,
                "contributed_work_units": total_work,
                "required_work_units": int(project["required_work_units"]),
                "stage": stage,
                "wage_cents": wage_cents,
                "procurement_cents": procurement_cents,
                "wage_transaction_id": wage_transaction_id,
                "procurement_transaction_id": procurement_transaction_id,
                "evidence_event_ids": _evidence(action),
            }, phase="EXECUTION", subject_type="construction_project",
            subject_id=project_id, importance=2.0)
        self.store.update(
            "construction_contributions", contribution_id,
            evidence_event_id=event_id)
        completion: dict[str, Any] = {}
        if stage == "completed":
            completion = self._complete(tick, project_id)
        return self._finish(tick, actor_id, action_type, action, {
            "ok": True,
            "project_id": project_id,
            "contribution_id": contribution_id,
            "contributed_work_units": total_work,
            "required_work_units": int(project["required_work_units"]),
            "stage": stage,
            "status": "completed" if stage == "completed" else "building",
            **completion,
        }, project_id)

    def cancel(
        self, tick: int, actor_id: int, action: Mapping[str, Any],
    ) -> dict[str, Any]:
        action_type = "cancel_construction"
        cached = self._start(actor_id, action_type, action)
        if cached is not None:
            return cached if cached.get("idempotent") or cached.get(
                "idempotency_conflict") else self._finish(
                    tick, actor_id, action_type, action, cached)
        project_id = int(action["project_id"])
        project = self._project(project_id)
        if project is None:
            return self._finish(tick, actor_id, action_type, action, {
                "ok": False, "reason": "construction project does not exist"})
        if not self._authorized_project(actor_id, project):
            return self._finish(tick, actor_id, action_type, action, {
                "ok": False, "reason": "actor cannot cancel this construction project",
            }, project_id)
        if str(project["status"]) in TERMINAL_STATUSES:
            return self._finish(tick, actor_id, action_type, action, {
                "ok": False, "reason": "construction project is already terminal",
            }, project_id)
        result = self._cancel_project(tick, project, actor_id, str(action["reason_code"]), action)
        return self._finish(tick, actor_id, action_type, action, result, project_id)

    def cancel_unclaimed(self, tick: int, project_id: int):
        """Engine disposition of unclaimed property, never an impersonated owner."""
        from .project_rights import interests_at
        from .estates import EstateError
        project = self._project(project_id)
        if self.engine_semantics_version < 20 or project is None or project["owner_type"] != "agent":
            raise EstateError("unclaimed construction requires a personal estate project")
        shares = interests_at(self.store, project_id, enabled=True)
        if not shares or self.e.project_rights.has_personal_residual(project_id):
            raise EstateError("cannot cancel a project with a personal beneficial owner")
        if project["status"] in TERMINAL_STATUSES:
            return {"ok": True, "project_id": project_id, "status": project["status"], "refund_cents": 0}
        with self.store.savepoint("unclaimed_project_cancellation"):
            return self._cancel_project(tick, project, None, "no_estate_beneficiary", {}, phase="NIGHT_CLOSE")

    def _cancel_project(self, tick, project, actor_id, reason, action, *, phase="EXECUTION"):
        project_id = int(project["id"])
        refund_cents, refund_transaction_ids = self._refund_remaining(
            tick, project_id, terminal_reason="cancelled")
        if project["permit_case_id"] is not None:
            self.store.execute(
                "UPDATE construction_permit_cases SET status='withdrawn',"
                "decided_tick=?,decision_actor_id=?,reason_code=? "
                "WHERE id=? AND status='submitted'",
                (
                    int(tick), int(actor_id) if actor_id is not None else None, reason,
                    int(project["permit_case_id"]),
                ),
            )
        event_id = self.store.log_event(
            tick, "construction_project_cancelled", {
                "project_id": project_id,
                "actor_agent_id": int(actor_id) if actor_id is not None else None,
                "reason_code": reason,
                "refund_cents": refund_cents,
                "refund_transaction_ids": refund_transaction_ids,
                "evidence_event_ids": _evidence(action),
            }, phase=phase, subject_type="construction_project",
            subject_id=project_id, importance=2.5)
        current = self._project(project_id)
        self.store.update(
            "construction_projects", project_id, status="cancelled",
            cancelled_tick=int(tick),
            refunded_funding_cents=(
                int(current["refunded_funding_cents"]) + refund_cents),
            cancellation_event_id=event_id,
            evidence_refs_json=self._merge_evidence(current, action))
        if self.engine_semantics_version >= 20:
            self.e.estate_property.close_cancelled(tick, project_id)
        return {
            "ok": True,
            "project_id": project_id,
            "status": "cancelled",
            "refund_cents": refund_cents,
            "refund_transaction_ids": refund_transaction_ids,
        }

    def _refund_remaining(
        self, tick: int, project_id: int, terminal_reason: str,
    ) -> tuple[int, list[int]]:
        project = self._project(project_id)
        escrow_id = int(project["escrow_account_id"])
        remaining = self.ledger.balance(escrow_id)
        if remaining <= 0:
            return 0, []
        sources = self.store.query(
            "SELECT actor_agent_id,source_account_id,SUM(amount_cents) AS amount "
            "FROM construction_contributions "
            "WHERE project_id=? AND contribution_type='funding' "
            "GROUP BY actor_agent_id,source_account_id "
            "ORDER BY actor_agent_id,source_account_id",
            (int(project_id),),
        )
        total = sum(int(row["amount"]) for row in sources)
        if total <= 0:
            raise RuntimeError(
                "funded construction escrow has no source contributions")
        allocations = [
            (row, remaining * int(row["amount"]) // total)
            for row in sources
        ]
        remainder = remaining - sum(amount for _row, amount in allocations)
        transaction_ids: list[int] = []
        refunded = 0
        for index, (row, base_amount) in enumerate(allocations):
            amount = base_amount + (1 if index < remainder else 0)
            if amount <= 0:
                continue
            account_id = int(row["source_account_id"])
            contributor_id = int(row["actor_agent_id"])
            transaction_id = self.ledger.transfer(
                tick, escrow_id, account_id, amount,
                kind="construction_refund",
                memo=(
                    f"project {project_id} {terminal_reason} refund "
                    f"to agent {contributor_id}"))
            self.store.insert(
                "construction_contributions",
                dedupe_key=_hash({
                    "project_id": int(project_id),
                    "terminal_reason": terminal_reason,
                    "account_id": account_id,
                }),
                project_id=int(project_id),
                actor_agent_id=contributor_id,
                contribution_type="refund",
                amount_cents=amount,
                work_units=0,
                source_account_id=account_id,
                transaction_id=transaction_id,
                tick=int(tick),
                evidence_refs_json="[]",
                metadata_json=_json({"reason": terminal_reason}),
            )
            transaction_ids.append(transaction_id)
            refunded += amount
        return refunded, transaction_ids

    def _complete(self, tick: int, project_id: int) -> dict[str, Any]:
        project = self._project(project_id)
        if project["place_id"] is not None:
            return {
                "place_id": int(project["place_id"]),
                "refund_cents": 0,
                "refund_transaction_ids": [],
            }
        region = self.store.query_one(
            "SELECT * FROM regions WHERE id=?", (int(project["region_id"]),))
        target = str(project["target_place_type"])
        inherited_title = self.engine_semantics_version >= 20 and project["owner_type"] == "agent"
        place_kind = {
            "private_home": "residential_district",
            "workplace": "firm_workplace",
            "public_facility": "public_commons",
        }[target]
        if target == "private_home":
            place_owner_type = "region"
            place_owner_id = int(project["region_id"])
        else:
            place_owner_type = str(project["owner_type"])
            place_owner_id = int(project["owner_id"])
        place_id = self.e.city._ensure_place(
            place_key=f"construction:{project['project_key']}",
            region=region,
            name=str(project["name"]),
            kind=place_kind,
            owner_type=place_owner_type,
            owner_id=place_owner_id,
            capacity=None,
            tick=int(tick),
            metadata={
                "construction_project_id": int(project_id),
                "target_place_type": target,
                **({"original_owner_type": str(project["owner_type"]), "original_owner_id": int(project["owner_id"])}
                   if inherited_title else {"canonical_owner_type": str(project["owner_type"]), "canonical_owner_id": int(project["owner_id"])}),
                "site_key": str(project["site_key"]),
            },
        )
        refund_cents, refund_transaction_ids = self._refund_remaining(
            tick, project_id, terminal_reason="completed")
        self.store.update(
            "construction_projects", project_id, status="completed",
            completed_tick=int(tick), place_id=place_id,
            refunded_funding_cents=(
                int(project["refunded_funding_cents"]) + refund_cents))
        event_id = self.store.log_event(
            tick, "construction_project_completed", {
                "project_id": int(project_id),
                "place_id": place_id,
                "target_place_type": target,
                **({"original_owner_type": str(project["owner_type"]), "original_owner_id": int(project["owner_id"])}
                   if inherited_title else {"owner_type": str(project["owner_type"]), "owner_id": int(project["owner_id"])}),
                "region_id": int(project["region_id"]),
                "required_funding_cents": int(project["required_funding_cents"]),
                "required_work_units": int(project["required_work_units"]),
                "spent_funding_cents": (
                    int(project["spent_funding_cents"])),
                "refund_cents": refund_cents,
                "refund_transaction_ids": refund_transaction_ids,
            }, phase="EXECUTION", subject_type="construction_project",
            subject_id=int(project_id), importance=3.5)
        self.store.update(
            "construction_projects", project_id, completion_event_id=event_id)
        self.e.city._sync_routine_leases(int(tick))
        return {
            "place_id": place_id,
            "completion_event_id": event_id,
            "refund_cents": refund_cents,
            "refund_transaction_ids": refund_transaction_ids,
        }

    def _funding_action(
        self, agent_id: int, tick: int, project,
    ) -> dict[str, Any] | None:
        remaining = (
            int(project["required_funding_cents"])
            - int(project["contributed_funding_cents"])
        )
        checking = self.ledger.agent_checking_id(int(agent_id))
        available = self.ledger.balance(checking) if checking is not None else 0
        amount = min(
            remaining,
            max(1, int(self.config["funding_contribution_cents"])),
            max(0, available),
        )
        if amount <= 0:
            return None
        return {
            "type": "contribute_construction_funding",
            "project_id": int(project["id"]),
            "amount_cents": amount,
            "dedupe_key": (
                f"construction-project-{int(project['id'])}-fund-"
                f"{int(agent_id)}-{int(tick)}"),
        }

    def _work_action(
        self, agent_id: int, tick: int, project,
    ) -> dict[str, Any] | None:
        remaining = (
            int(project["required_work_units"])
            - int(project["contributed_work_units"])
        )
        units = min(
            remaining, max(1, int(self.config["work_units_per_action"])))
        if units <= 0:
            return None
        return {
            "type": "perform_construction_work",
            "project_id": int(project["id"]),
            "work_units": units,
            "wage_cents": 0,
            "procurement_cents": 0,
            "dedupe_key": (
                f"construction-project-{int(project['id'])}-work-"
                f"{int(agent_id)}-{int(tick)}"),
        }

    def decision_context(
        self, agent_id: int, tick: int,
    ) -> dict[str, Any] | None:
        """Return bounded, exact actions authored by the deciding agent."""
        if not self.enabled or not bool(self.config.get("agent_initiation", True)):
            return None
        if (self.e.engine_semantics_version >= 21
                and not self.e.population.is_available(agent_id)):
            return None
        agent = self.store.query_one(
            "SELECT id,name,region_id FROM agents WHERE id=? AND alive=1",
            (int(agent_id),),
        )
        if agent is None or agent["region_id"] is None:
            return None
        action = None

        permit = self.store.query_one(
            "SELECT c.id FROM construction_permit_cases c "
            "JOIN agency_staff s ON s.agency_id=c.agency_id "
            "WHERE s.agent_id=? AND s.active=1 AND s.role_key='permit_clerk' "
            "AND s.region_id=c.region_id "
            "AND c.status='submitted' ORDER BY c.created_tick,c.id LIMIT 1",
            (int(agent_id),),
        )
        if permit is not None:
            action = {
                "type": "decide_construction_permit",
                "case_id": int(permit["id"]),
                "decision": "approve",
                "reason_code": "requirements_verified",
                "dedupe_key": (
                    f"construction-permit-{int(permit['id'])}-approve"),
            }

        owned = self.store.query_one(
            "SELECT p.* FROM construction_projects p "
            "WHERE p.status IN ('proposed','permitting','funding','building') "
            "AND ((p.owner_type='agent' AND p.owner_id=?) OR "
            "(p.owner_type='firm' AND p.owner_id IN "
            f" (SELECT id FROM {self.e.business_control.table} WHERE {self.e.business_control.column}=? "
            "  AND status<>'bankrupt')) OR "
            "(p.owner_type='agency' AND p.owner_id IN "
            " (SELECT agency_id FROM agency_staff WHERE agent_id=? AND active=1 "
            "  AND role_key='permit_clerk' AND region_id=p.region_id))) "
            "ORDER BY p.proposed_tick,p.id LIMIT 1",
            (int(agent_id), int(agent_id), int(agent_id)),
        )
        if self.engine_semantics_version >= 20:
            candidates = self.e.project_rights.operated_projects(agent_id)
            if owned is not None:
                candidates.append(owned)
            owned = min(candidates, key=lambda p: (p["proposed_tick"], p["id"])) if candidates else None
        if action is None and owned is not None:
            status = str(owned["status"])
            if status == "proposed":
                action = {
                    "type": "apply_construction_permit",
                    "project_id": int(owned["id"]),
                    "dedupe_key": (
                        f"construction-project-{int(owned['id'])}-permit"),
                }
            elif status == "funding":
                action = self._funding_action(agent_id, tick, owned)
            elif status == "building":
                action = self._work_action(agent_id, tick, owned)

        if action is None and owned is None:
            founder = self.store.query_one(
                f"SELECT f.id,f.name,f.region_id FROM {self.e.business_control.table} f "
                f"WHERE f.{self.e.business_control.column}=? AND f.status<>'bankrupt' "
                "AND NOT EXISTS (SELECT 1 FROM places p WHERE "
                " p.owner_type='firm' AND p.owner_id=f.id "
                " AND p.kind='firm_workplace' AND p.active=1) "
                "AND NOT EXISTS (SELECT 1 FROM construction_projects cp WHERE "
                " cp.owner_type='firm' AND cp.owner_id=f.id "
                " AND cp.target_place_type='workplace' "
                " AND cp.status<>'cancelled') ORDER BY f.id LIMIT 1",
                (int(agent_id),),
            )
            if founder is not None:
                action = {
                    "type": "propose_construction",
                    "owner_type": "firm",
                    "owner_id": int(founder["id"]),
                    "region_id": int(founder["region_id"]),
                    "site_key": f"firm-{int(founder['id'])}-workplace",
                    "target_place_type": "workplace",
                    "name": f"{founder['name']} Workplace",
                    "required_funding_cents": int(
                        self.config["workplace_funding_cents"]),
                    "required_work_units": int(
                        self.config["workplace_work_units"]),
                    "dedupe_key": (
                        f"construction-firm-{int(founder['id'])}-workplace"),
                }

        if action is None and owned is None:
            staff = self.store.query_one(
                "SELECT agency_id,region_id FROM agency_staff s "
                "WHERE s.agent_id=? AND s.active=1 AND s.role_key='permit_clerk' "
                "AND NOT EXISTS (SELECT 1 FROM construction_projects cp WHERE "
                " cp.owner_type='agency' AND cp.owner_id=s.agency_id "
                " AND cp.target_place_type='public_facility' "
                " AND cp.status<>'cancelled') ORDER BY s.id LIMIT 1",
                (int(agent_id),),
            )
            if staff is not None:
                action = {
                    "type": "propose_construction",
                    "owner_type": "agency",
                    "owner_id": int(staff["agency_id"]),
                    "region_id": int(staff["region_id"]),
                    "site_key": (
                        f"agency-{int(staff['agency_id'])}-public-facility"),
                    "target_place_type": "public_facility",
                    "name": (
                        f"Agency {int(staff['agency_id'])} Public Hall"),
                    "required_funding_cents": int(
                        self.config["public_facility_funding_cents"]),
                    "required_work_units": int(
                        self.config["public_facility_work_units"]),
                    "dedupe_key": (
                        f"construction-agency-{int(staff['agency_id'])}-hall"),
                }

        if action is None and owned is None:
            shared = self.store.query_one(
                "SELECT * FROM construction_projects "
                "WHERE status IN ('funding','building') "
                "AND target_place_type IN ('public_facility','workplace') "
                "ORDER BY CASE target_place_type "
                "WHEN 'public_facility' THEN 0 ELSE 1 END,proposed_tick,id LIMIT 1"
            )
            if shared is not None:
                action = (
                    self._funding_action(agent_id, tick, shared)
                    if str(shared["status"]) == "funding"
                    else self._work_action(agent_id, tick, shared)
                )

        if action is None and owned is None:
            home = self.store.query_one(
                "SELECT 1 FROM construction_projects WHERE owner_type='agent' "
                "AND owner_id=? AND target_place_type='private_home' "
                "AND status<>'cancelled' LIMIT 1",
                (int(agent_id),),
            )
            if self.engine_semantics_version >= 20:
                home = self.e.project_rights.household_home(agent["region_id"], agent_id) or any(
                    p["region_id"] == agent["region_id"] for p in self.e.project_rights.owned_projects(agent_id)) or None
            if home is None:
                action = {
                    "type": "propose_construction",
                    "owner_type": "agent",
                    "owner_id": int(agent_id),
                    "region_id": int(agent["region_id"]),
                    "site_key": f"agent-{int(agent_id)}-home",
                    "target_place_type": "private_home",
                    "name": f"{agent['name']} Home",
                    "required_funding_cents": int(
                        self.config["private_home_funding_cents"]),
                    "required_work_units": int(
                        self.config["private_home_work_units"]),
                    "dedupe_key": f"construction-agent-{int(agent_id)}-home",
                }

        if action is None:
            return None
        return {
            "rule": "copy one eligible action exactly or deliberately do nothing",
            "eligible_actions": [action],
        }

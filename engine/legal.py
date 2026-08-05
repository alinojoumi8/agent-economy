"""Deterministic legal-institutional kernel.

LLMs may author prose and propose findings, but this service owns every legal
state transition and every enforceable effect.  The fictional Northstar ruleset
is intentionally bounded and is not a representation of real legal advice.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from .ledger import Ledger
from .store import Store
from .types import Clause, ValidationError


RULESET_KEY = "northstar-us-inspired"
RULESET_VERSION = "1.0"
JURISDICTION = "Northstar Federation"
LEGAL_DISCLAIMER = (
    "Fictional rules for an economic simulation. Not legal advice and not a "
    "prediction of any real court, regulator, or legal system."
)

ALLOWED_CLAUSE_TYPES = {
    "payment", "delivery", "vesting", "equity_issuance", "ip_assignment",
    "ip_license", "confidentiality", "employment", "representations",
    "covenant", "termination", "indemnity", "liquidation_preference",
    "pro_rata", "closing_condition", "dispute_resolution",
}
OBLIGATION_CLAUSE_TYPES = {
    "payment", "delivery", "equity_issuance", "ip_assignment", "employment",
    "covenant", "closing_condition", "indemnity",
}
AVAILABLE_REMEDIES = {"none", "dismissal", "damages", "terminate_contract", "injunction"}
DECISION_ROLES = {
    "judge", "regulator", "competition_regulator", "labor_regulator",
    "gov_official",
}


@dataclass(frozen=True)
class Party:
    party_type: str
    party_id: int
    role: str

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> "Party":
        party_type = str(raw.get("party_type", raw.get("type", ""))).strip().lower()
        party_id = int(raw.get("party_id", raw.get("id", 0)))
        role = str(raw.get("role", "party")).strip()[:60]
        if party_type not in {"agent", "firm", "government", "agency"} or party_id <= 0:
            raise ValidationError("party must identify an agent, firm, government, or agency")
        if not role:
            raise ValidationError("party role is required")
        return cls(party_type, party_id, role)


class LegalInstitution:
    def __init__(self, store: Store, ledger: Ledger, config: dict | None = None):
        self.store = store
        self.ledger = ledger
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", True))
        self.ruleset_key = str(self.config.get("ruleset", f"{RULESET_KEY}-{RULESET_VERSION}"))
        self.max_damages_cents = int(self.config.get("max_damages_cents", 100_000_000_00))
        self.default_response_ticks = int(self.config.get("response_ticks", 14))
        self._ensure_ruleset()

    def _ensure_ruleset(self) -> None:
        if not self.enabled:
            return
        if self.store.query_one(
                "SELECT id FROM legal_rulesets WHERE ruleset_key=? AND version=?",
                (RULESET_KEY, RULESET_VERSION)):
            return
        rules = {
            "contract": {"mutual_acceptance_required": True, "breach_requires_due_obligation": True},
            "procedure": {"response_ticks": self.default_response_ticks,
                          "claimant_bears_burden": True},
            "remedies": sorted(AVAILABLE_REMEDIES),
            "max_damages_cents": self.max_damages_cents,
        }
        sources = [
            {"title": "Northstar simulation rules", "kind": "fictional-model",
             "note": "US-inspired structure; no real-law effect"}
        ]
        self.store.insert(
            "legal_rulesets", ruleset_key=RULESET_KEY, version=RULESET_VERSION,
            jurisdiction=JURISDICTION, effective_tick=0, status="active",
            rules_json=json.dumps(rules, sort_keys=True),
            sources_json=json.dumps(sources, sort_keys=True), disclaimer=LEGAL_DISCLAIMER)

    # ------------------------------------------------------------------
    # Parties and authorization
    def _entity_exists(self, party: Party) -> bool:
        if party.party_type == "agent":
            return bool(self.store.query_one("SELECT 1 FROM agents WHERE id=? AND alive=1", (party.party_id,)))
        if party.party_type == "firm":
            return bool(self.store.query_one("SELECT 1 FROM firms WHERE id=? AND status<>'bankrupt'", (party.party_id,)))
        return party.party_id > 0

    def controls(self, actor_id: int, party_type: str, party_id: int) -> bool:
        if party_type == "agent":
            return actor_id == party_id
        if party_type == "firm":
            firm = self.store.query_one(
                "SELECT founder_agent_id, status FROM firms WHERE id=?", (party_id,))
            if not firm or firm["status"] == "bankrupt":
                return False
            if int(firm["founder_agent_id"] or 0) == actor_id:
                return True
            agent = self.store.query_one("SELECT employer_id, role FROM agents WHERE id=?", (actor_id,))
            return bool(agent and int(agent["employer_id"] or 0) == party_id
                        and (agent["role"] or "") in {"manager", "founder"})
        agent = self.store.query_one("SELECT role FROM agents WHERE id=? AND alive=1", (actor_id,))
        return bool(agent and (agent["role"] or "") in {"gov_official", "regulator"})

    def _is_lawyer(self, actor_id: int) -> bool:
        row = self.store.query_one("SELECT occupation, role, alive FROM agents WHERE id=?", (actor_id,))
        return bool(row and row["alive"] and ((row["occupation"] or "").lower() == "lawyer"
                    or (row["role"] or "") in {"lawyer", "counsel"}))

    # ------------------------------------------------------------------
    # Contracts
    def propose_contract(self, tick: int, actor_id: int, proposal: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "reason": "legal system disabled"}
        try:
            parties = [Party.parse(item) for item in proposal.get("parties", [])]
            clauses = [Clause(str(item.get("clause_key", f"clause-{i + 1}")),
                              str(item.get("clause_type", "")), dict(item.get("terms", {})))
                       for i, item in enumerate(proposal.get("clauses", []))]
        except (TypeError, ValueError, ValidationError) as exc:
            return {"ok": False, "reason": str(exc)}
        if len(parties) < 2 or len({(p.party_type, p.party_id) for p in parties}) != len(parties):
            return {"ok": False, "reason": "contract requires at least two unique parties"}
        if not clauses:
            return {"ok": False, "reason": "contract requires at least one typed clause"}
        bad = sorted({c.clause_type for c in clauses} - ALLOWED_CLAUSE_TYPES)
        if bad:
            return {"ok": False, "reason": f"unsupported clause types: {', '.join(bad)}"}
        if not all(self._entity_exists(p) for p in parties):
            return {"ok": False, "reason": "contract party missing or unavailable"}
        if not self._is_lawyer(actor_id) and not any(
                self.controls(actor_id, p.party_type, p.party_id) for p in parties):
            return {"ok": False, "reason": "drafter is neither counsel nor an authorized party"}

        title = str(proposal.get("title", proposal.get("contract_type", "Agreement"))).strip()[:160]
        contract_type = str(proposal.get("contract_type", "commercial")).strip()[:60]
        expiry = proposal.get("expiry_tick")
        contract_id = self.store.insert(
            "contracts", contract_type=contract_type, title=title or "Agreement", status="offered",
            jurisdiction=JURISDICTION, ruleset_key=self.ruleset_key, version=1,
            parent_contract_id=None, drafter_agent_id=actor_id, offered_tick=tick,
            expiry_tick=int(expiry) if expiry is not None else None,
            prose=str(proposal.get("prose", ""))[:5000],
            metadata_json=json.dumps(proposal.get("metadata", {}), sort_keys=True))
        for party in parties:
            self.store.insert("contract_parties", contract_id=contract_id,
                              party_type=party.party_type, party_id=party.party_id, role=party.role)
        for ordinal, clause in enumerate(clauses, 1):
            self.store.insert("contract_clauses", contract_id=contract_id,
                              clause_key=clause.clause_key[:80], clause_type=clause.clause_type,
                              ordinal=ordinal, terms_json=json.dumps(clause.terms, sort_keys=True),
                              status="active")
        self.store.log_event(
            tick, "contract_offered", {"contract_id": contract_id, "title": title,
            "contract_type": contract_type, "party_count": len(parties),
            "clause_types": [c.clause_type for c in clauses], "ruleset": self.ruleset_key},
            phase="EXECUTION", subject_type="contract", subject_id=contract_id, importance=2.0)
        return {"ok": True, "contract_id": contract_id, "status": "offered"}

    def counter_contract(self, tick: int, actor_id: int, contract_id: int,
                         changes: dict[str, Any]) -> dict[str, Any]:
        original = self.store.query_one("SELECT * FROM contracts WHERE id=?", (contract_id,))
        if not original or original["status"] not in {"offered", "negotiating"}:
            return {"ok": False, "reason": "contract is not negotiable"}
        if not self._authorized_contract_party(actor_id, contract_id):
            return {"ok": False, "reason": "actor is not an authorized contract party"}
        parties = [dict(row) for row in self.store.query(
            "SELECT party_type, party_id, role FROM contract_parties WHERE contract_id=? ORDER BY id",
            (contract_id,))]
        existing_clauses = [{"clause_key": row["clause_key"], "clause_type": row["clause_type"],
                             "terms": json.loads(row["terms_json"] or "{}")}
                            for row in self.store.query(
                                "SELECT * FROM contract_clauses WHERE contract_id=? ORDER BY ordinal",
                                (contract_id,))]
        proposal = {
            "contract_type": original["contract_type"], "title": original["title"],
            "parties": parties, "clauses": changes.get("clauses", existing_clauses),
            "prose": changes.get("prose", original["prose"]),
            "expiry_tick": changes.get("expiry_tick", original["expiry_tick"]),
            "metadata": {**json.loads(original["metadata_json"] or "{}"),
                         **dict(changes.get("metadata", {}))},
        }
        result = self.propose_contract(tick, actor_id, proposal)
        if not result.get("ok"):
            return result
        replacement = int(result["contract_id"])
        self.store.update("contracts", replacement, status="negotiating",
                          parent_contract_id=contract_id, version=int(original["version"]) + 1)
        self.store.update("contracts", contract_id, status="superseded", terminated_tick=tick)
        self.store.log_event(tick, "contract_countered", {
            "contract_id": contract_id, "replacement_contract_id": replacement,
            "actor_id": actor_id}, phase="EXECUTION", subject_type="contract",
            subject_id=replacement, importance=1.8)
        return {"ok": True, "contract_id": replacement, "supersedes": contract_id,
                "status": "negotiating"}

    def accept_contract(self, tick: int, actor_id: int, contract_id: int,
                        party_type: str, party_id: int) -> dict[str, Any]:
        contract = self.store.query_one("SELECT * FROM contracts WHERE id=?", (contract_id,))
        if not contract or contract["status"] not in {"offered", "negotiating"}:
            return {"ok": False, "reason": "contract is not open for acceptance"}
        party = self.store.query_one(
            "SELECT 1 FROM contract_parties WHERE contract_id=? AND party_type=? AND party_id=?",
            (contract_id, party_type, party_id))
        if not party or not self.controls(actor_id, party_type, party_id):
            return {"ok": False, "reason": "actor cannot accept for that party"}
        self.store.execute(
            "INSERT INTO contract_acceptances (contract_id, party_type, party_id, accepted_tick, actor_id) "
            "VALUES (?,?,?,?,?) ON CONFLICT(contract_id,party_type,party_id) DO UPDATE SET "
            "accepted_tick=excluded.accepted_tick, actor_id=excluded.actor_id",
            (contract_id, party_type, party_id, tick, actor_id))
        required = int(self.store.scalar(
            "SELECT COUNT(*) FROM contract_parties WHERE contract_id=?", (contract_id,), default=0))
        accepted = int(self.store.scalar(
            "SELECT COUNT(*) FROM contract_acceptances WHERE contract_id=?", (contract_id,), default=0))
        status = contract["status"]
        if accepted == required:
            effective_tick = max(tick, int(contract["effective_tick"] or tick))
            status = "active" if effective_tick <= tick else "executed"
            self.store.update("contracts", contract_id, status=status, executed_tick=tick,
                              effective_tick=effective_tick)
            self._compile_obligations(contract_id, effective_tick)
            self.store.log_event(tick, "contract_executed", {
                "contract_id": contract_id, "effective_tick": effective_tick,
                "obligations": int(self.store.scalar(
                    "SELECT COUNT(*) FROM obligations WHERE contract_id=?",
                    (contract_id,), default=0))}, phase="EXECUTION", subject_type="contract",
                subject_id=contract_id, importance=3.0)
        return {"ok": True, "contract_id": contract_id, "accepted": accepted,
                "required": required, "status": status}

    def reject_contract(self, tick: int, actor_id: int, contract_id: int) -> dict[str, Any]:
        contract = self.store.query_one("SELECT status FROM contracts WHERE id=?", (contract_id,))
        if not contract or contract["status"] not in {"offered", "negotiating"}:
            return {"ok": False, "reason": "contract is not open"}
        if not self._authorized_contract_party(actor_id, contract_id):
            return {"ok": False, "reason": "actor is not an authorized contract party"}
        self.store.update("contracts", contract_id, status="rejected", terminated_tick=tick)
        self.store.log_event(tick, "contract_rejected", {"contract_id": contract_id,
            "actor_id": actor_id}, phase="EXECUTION", subject_type="contract",
            subject_id=contract_id, importance=1.2)
        return {"ok": True, "contract_id": contract_id, "status": "rejected"}

    def _authorized_contract_party(self, actor_id: int, contract_id: int) -> bool:
        return any(self.controls(actor_id, row["party_type"], int(row["party_id"]))
                   for row in self.store.query(
                       "SELECT party_type, party_id FROM contract_parties WHERE contract_id=?",
                       (contract_id,)))

    def _compile_obligations(self, contract_id: int, effective_tick: int) -> None:
        if self.store.query_one("SELECT 1 FROM obligations WHERE contract_id=?", (contract_id,)):
            return
        parties = [Party(row["party_type"], int(row["party_id"]), row["role"])
                   for row in self.store.query(
                       "SELECT party_type, party_id, role FROM contract_parties WHERE contract_id=? ORDER BY id",
                       (contract_id,))]
        by_role = {party.role: party for party in parties}
        for row in self.store.query(
                "SELECT * FROM contract_clauses WHERE contract_id=? ORDER BY ordinal", (contract_id,)):
            if row["clause_type"] not in OBLIGATION_CLAUSE_TYPES:
                continue
            terms = json.loads(row["terms_json"] or "{}")
            obligor = self._term_party(terms.get("obligor"), terms.get("obligor_role"), by_role,
                                       parties[0])
            obligee = self._term_party(terms.get("obligee"), terms.get("obligee_role"), by_role,
                                       parties[1])
            due_tick = int(terms.get("due_tick", effective_tick + int(terms.get("due_in_ticks", 0))))
            self.store.insert(
                "obligations", contract_id=contract_id, clause_id=int(row["id"]),
                obligation_type=row["clause_type"], obligor_type=obligor.party_type,
                obligor_id=obligor.party_id, obligee_type=obligee.party_type,
                obligee_id=obligee.party_id, due_tick=max(effective_tick, due_tick),
                grace_ticks=max(0, int(terms.get("grace_ticks", 0))),
                amount_cents=(int(terms["amount_cents"]) if terms.get("amount_cents") is not None else None),
                currency_code=str(terms.get("currency_code", "USD")).upper(),
                terms_json=json.dumps(terms, sort_keys=True), status="pending")

    @staticmethod
    def _term_party(raw: Any, role: Any, by_role: dict[str, Party], fallback: Party) -> Party:
        if isinstance(raw, dict):
            return Party.parse(raw)
        if role is not None and str(role) in by_role:
            return by_role[str(role)]
        return fallback

    def perform_obligation(self, tick: int, actor_id: int, obligation_id: int) -> dict[str, Any]:
        obligation = self.store.query_one("SELECT * FROM obligations WHERE id=?", (obligation_id,))
        if not obligation or obligation["status"] != "pending":
            return {"ok": False, "reason": "obligation is not pending"}
        if not self.controls(actor_id, obligation["obligor_type"], int(obligation["obligor_id"])):
            return {"ok": False, "reason": "actor does not control the obligor"}
        txn_id = None
        amount = obligation["amount_cents"]
        if obligation["obligation_type"] in {"payment", "indemnity"}:
            if amount is None or int(amount) <= 0:
                return {"ok": False, "reason": "financial obligation lacks a positive amount"}
            source = self._entity_account(obligation["obligor_type"], int(obligation["obligor_id"]))
            target = self._entity_account(obligation["obligee_type"], int(obligation["obligee_id"]))
            if source is None or target is None:
                return {"ok": False, "reason": "party account missing"}
            if self.ledger.balance(source) < int(amount):
                return {"ok": False, "reason": "obligor has insufficient funds"}
            txn_id = self.ledger.transfer(tick, source, target, int(amount), kind="contract_performance",
                                          memo=f"obligation {obligation_id}")
        self.store.update("obligations", obligation_id, status="performed", performed_tick=tick,
                          transaction_id=txn_id)
        self.store.log_event(tick, "obligation_performed", {
            "obligation_id": obligation_id, "contract_id": int(obligation["contract_id"]),
            "obligation_type": obligation["obligation_type"], "transaction_id": txn_id},
            phase="EXECUTION", subject_type="contract", subject_id=int(obligation["contract_id"]),
            importance=1.5)
        self._mark_contract_performed_if_complete(int(obligation["contract_id"]), tick)
        return {"ok": True, "obligation_id": obligation_id, "transaction_id": txn_id}

    def _mark_contract_performed_if_complete(self, contract_id: int, tick: int) -> None:
        pending = int(self.store.scalar(
            "SELECT COUNT(*) FROM obligations WHERE contract_id=? AND status='pending'",
            (contract_id,), default=0))
        if pending == 0:
            self.store.update("contracts", contract_id, status="performed", terminated_tick=tick)
            self.store.log_event(tick, "contract_performed", {"contract_id": contract_id},
                                 phase="EXECUTION", subject_type="contract",
                                 subject_id=contract_id, importance=2.0)

    # ------------------------------------------------------------------
    # Notice, litigation, settlement, and adjudication
    def issue_notice(self, tick: int, actor_id: int, notice: dict[str, Any]) -> dict[str, Any]:
        sender = Party.parse(dict(notice.get("sender", {"type": "agent", "id": actor_id})))
        recipient = Party.parse(dict(notice.get("recipient", {})))
        if not self.controls(actor_id, sender.party_type, sender.party_id):
            return {"ok": False, "reason": "actor cannot issue notice for sender"}
        notice_id = self.store.insert(
            "legal_notices", contract_id=notice.get("contract_id"), matter_id=notice.get("matter_id"),
            sender_type=sender.party_type, sender_id=sender.party_id,
            recipient_type=recipient.party_type, recipient_id=recipient.party_id,
            notice_type=str(notice.get("notice_type", "general"))[:60], tick=tick,
            detail=str(notice.get("detail", ""))[:1000])
        self.store.log_event(tick, "legal_notice_issued", {"notice_id": notice_id,
            "contract_id": notice.get("contract_id"), "notice_type": notice.get("notice_type", "general")},
            phase="EXECUTION", subject_type="contract", subject_id=notice.get("contract_id"), importance=1.2)
        return {"ok": True, "notice_id": notice_id}

    def file_claim(self, tick: int, actor_id: int, claim: dict[str, Any]) -> dict[str, Any]:
        try:
            claimant = Party.parse(dict(claim.get("claimant", {})))
            respondent = Party.parse(dict(claim.get("respondent", {})))
        except (TypeError, ValueError, ValidationError) as exc:
            return {"ok": False, "reason": str(exc)}
        counsel = claim.get("counsel_agent_id")
        represented = self.controls(actor_id, claimant.party_type, claimant.party_id)
        if counsel is not None and int(counsel) == actor_id and self._is_lawyer(actor_id):
            represented = True
        if not represented:
            return {"ok": False, "reason": "actor cannot file for claimant"}
        contract_id = claim.get("contract_id")
        if contract_id is not None and not self.store.query_one(
                "SELECT 1 FROM contracts WHERE id=?", (int(contract_id),)):
            return {"ok": False, "reason": "contract missing"}
        matter_id = self.store.insert(
            "legal_matters", matter_type=str(claim.get("matter_type", "civil"))[:60],
            venue=str(claim.get("venue", "Northstar Civil Tribunal"))[:100], status="filed",
            contract_id=int(contract_id) if contract_id is not None else None,
            claimant_type=claimant.party_type, claimant_id=claimant.party_id,
            respondent_type=respondent.party_type, respondent_id=respondent.party_id,
            claim_type=str(claim.get("claim_type", "breach"))[:80], filed_tick=tick,
            response_due_tick=tick + self.default_response_ticks,
            counsel_agent_id=int(counsel) if counsel is not None else (actor_id if self._is_lawyer(actor_id) else None),
            requested_remedy_json=json.dumps(claim.get("requested_remedy", {}), sort_keys=True),
            metadata_json=json.dumps(claim.get("metadata", {}), sort_keys=True))
        self.store.log_event(tick, "legal_matter_filed", {"matter_id": matter_id,
            "claim_type": claim.get("claim_type", "breach"), "contract_id": contract_id},
            phase="EXECUTION", subject_type="legal_matter", subject_id=matter_id, importance=2.5)
        return {"ok": True, "matter_id": matter_id, "status": "filed"}

    def submit_filing(self, tick: int, actor_id: int, filing: dict[str, Any]) -> dict[str, Any]:
        matter_id = int(filing.get("matter_id", 0))
        matter = self.store.query_one("SELECT * FROM legal_matters WHERE id=?", (matter_id,))
        if not matter or matter["status"] not in {"filed", "pleading", "hearing", "settlement_offered"}:
            return {"ok": False, "reason": "matter is not open"}
        filer_type = str(filing.get("filer_type", "agent"))
        filer_id = int(filing.get("filer_id", actor_id))
        authorized = self.controls(actor_id, filer_type, filer_id)
        if int(matter["counsel_agent_id"] or 0) == actor_id and self._is_lawyer(actor_id):
            authorized = True
        if not authorized:
            return {"ok": False, "reason": "actor is not authorized to file"}
        evidence = filing.get("evidence_event_ids", [])
        if not isinstance(evidence, list) or any(int(item) <= 0 for item in evidence):
            return {"ok": False, "reason": "evidence_event_ids must contain positive ids"}
        existing = {int(row["id"]) for row in self.store.query(
            f"SELECT id FROM events WHERE id IN ({','.join('?' for _ in evidence)})", evidence)} if evidence else set()
        if existing != {int(item) for item in evidence}:
            return {"ok": False, "reason": "filing references missing evidence events"}
        filing_type = str(filing.get("filing_type", "brief"))[:60]
        admitted = 1 if filing_type in {"evidence", "stipulation"} else 0
        filing_id = self.store.insert(
            "legal_filings", matter_id=matter_id, tick=tick, filer_type=filer_type,
            filer_id=filer_id, filing_type=filing_type, body=str(filing.get("body", ""))[:5000],
            evidence_event_ids_json=json.dumps([int(item) for item in evidence]), admitted=admitted,
            model_call_id=filing.get("model_call_id"),
            rationale_summary=str(filing.get("rationale_summary", ""))[:500])
        self.store.update("legal_matters", matter_id, status="hearing" if admitted else "pleading")
        self.store.log_event(tick, "legal_filing_submitted", {"matter_id": matter_id,
            "filing_id": filing_id, "filing_type": filing_type, "admitted": bool(admitted)},
            phase="EXECUTION", subject_type="legal_matter", subject_id=matter_id, importance=1.2)
        return {"ok": True, "filing_id": filing_id, "admitted": bool(admitted)}

    def propose_settlement(self, tick: int, actor_id: int, matter_id: int,
                           terms: dict[str, Any]) -> dict[str, Any]:
        matter = self.store.query_one("SELECT * FROM legal_matters WHERE id=?", (matter_id,))
        if not matter or matter["status"] in {"decided", "dismissed", "settled"}:
            return {"ok": False, "reason": "matter is not settleable"}
        side = self._matter_side(actor_id, matter)
        if side is None and int(matter["counsel_agent_id"] or 0) != actor_id:
            return {"ok": False, "reason": "actor is not authorized to settle"}
        remedy = dict(terms.get("remedy", terms))
        error = self._validate_remedy(matter, remedy)
        if error:
            return {"ok": False, "reason": error}
        offer = {"status": "offered", "proposer_actor_id": actor_id, "proposer_side": side or "claimant",
                 "offered_tick": tick, "remedy": remedy}
        self.store.update("legal_matters", matter_id, status="settlement_offered",
                          settlement_json=json.dumps(offer, sort_keys=True))
        self.store.log_event(tick, "settlement_offered", {"matter_id": matter_id,
            "remedy_type": remedy.get("type", "none")}, phase="EXECUTION",
            subject_type="legal_matter", subject_id=matter_id, importance=1.8)
        return {"ok": True, "matter_id": matter_id, "status": "settlement_offered"}

    def accept_settlement(self, tick: int, actor_id: int, matter_id: int) -> dict[str, Any]:
        matter = self.store.query_one("SELECT * FROM legal_matters WHERE id=?", (matter_id,))
        if not matter or matter["status"] != "settlement_offered":
            return {"ok": False, "reason": "no settlement is open"}
        offer = json.loads(matter["settlement_json"] or "{}")
        side = self._matter_side(actor_id, matter)
        if side is None or side == offer.get("proposer_side"):
            return {"ok": False, "reason": "opposing party must accept settlement"}
        result = self._enforce_remedy(tick, matter, dict(offer.get("remedy", {})), matter_id)
        offer.update({"status": "accepted", "accepted_tick": tick, "accepted_by": actor_id,
                      "enforcement": result})
        self.store.update("legal_matters", matter_id, status="settled", resolved_tick=tick,
                          settlement_json=json.dumps(offer, sort_keys=True))
        event_id = self.store.log_event(tick, "matter_settled", {"matter_id": matter_id,
            "enforcement": result}, phase="EXECUTION", subject_type="legal_matter",
            subject_id=matter_id, importance=3.0)
        return {"ok": True, "matter_id": matter_id, "event_id": event_id, "enforcement": result}

    def issue_decision(self, tick: int, actor_id: int, decision: dict[str, Any]) -> dict[str, Any]:
        actor = self.store.query_one("SELECT role FROM agents WHERE id=? AND alive=1", (actor_id,))
        if not actor or (actor["role"] or "") not in DECISION_ROLES:
            return {"ok": False, "reason": "only a judge or authorized regulator may decide"}
        matter_id = int(decision.get("matter_id", 0))
        matter = self.store.query_one("SELECT * FROM legal_matters WHERE id=?", (matter_id,))
        response_due_tick = (
            matter["response_due_tick"]
            if matter is not None
            else None
        )
        ready_status = bool(matter and (
            matter["status"] in {"filed", "pleading", "hearing"}
            or (matter["status"] == "settlement_offered"
                and response_due_tick is not None
                and tick >= int(response_due_tick))))
        if not ready_status:
            return {"ok": False, "reason": "matter is not ready for decision"}
        if self.store.query_one("SELECT 1 FROM legal_decisions WHERE matter_id=?", (matter_id,)):
            return {"ok": False, "reason": "matter already has a decision"}
        outcome = str(decision.get("outcome", "")).lower()
        if outcome not in {"claimant", "respondent", "dismissed"}:
            return {"ok": False, "reason": "invalid outcome"}
        findings = decision.get("findings", [])
        if not isinstance(findings, list) or not findings:
            return {"ok": False, "reason": "structured findings are required"}
        evidence = [int(item) for item in decision.get("evidence_event_ids", [])]
        admitted = self._admitted_evidence(matter_id)
        errors: list[str] = []
        if not set(evidence).issubset(admitted):
            errors.append("decision relies on evidence that was not admitted")
        if outcome == "claimant" and not evidence:
            errors.append("claimant outcome requires admitted evidence")
        remedy = dict(decision.get("remedy", {"type": "none"}))
        remedy_error = self._validate_remedy(matter, remedy)
        if remedy_error:
            errors.append(remedy_error)
        if outcome != "claimant" and remedy.get("type") not in {"none", "dismissal"}:
            errors.append("non-claimant outcome cannot award claimant relief")
        if errors:
            self.store.log_event(tick, "legal_decision_validation_failed", {
                "matter_id": matter_id, "actor_id": actor_id, "errors": errors}, phase="EXECUTION",
                subject_type="legal_matter", subject_id=matter_id, importance=2.0)
            return {"ok": False, "reason": "; ".join(errors), "repairable": True, "errors": errors}
        enforcement = self._enforce_remedy(tick, matter, remedy, matter_id)
        event_id = self.store.log_event(tick, "legal_decision_enforced", {
            "matter_id": matter_id, "outcome": outcome, "remedy": remedy,
            "enforcement": enforcement}, phase="EXECUTION", subject_type="legal_matter",
            subject_id=matter_id, importance=4.0)
        decision_id = self.store.insert(
            "legal_decisions", matter_id=matter_id, tick=tick, decision_maker_id=actor_id,
            outcome=outcome, findings_json=json.dumps(findings, sort_keys=True),
            evidence_event_ids_json=json.dumps(evidence), remedy_json=json.dumps(remedy, sort_keys=True),
            validation_status="valid", validation_errors_json="[]",
            model_call_id=decision.get("model_call_id"),
            rationale_summary=str(decision.get("rationale_summary", ""))[:500],
            enforcement_event_id=event_id)
        self.store.update("legal_matters", matter_id,
                          status="dismissed" if outcome in {"respondent", "dismissed"} else "decided",
                          resolved_tick=tick)
        return {"ok": True, "decision_id": decision_id, "matter_id": matter_id,
                "enforcement": enforcement, "event_id": event_id}

    def _admitted_evidence(self, matter_id: int) -> set[int]:
        out: set[int] = set()
        for row in self.store.query(
                "SELECT evidence_event_ids_json FROM legal_filings WHERE matter_id=? AND admitted=1",
                (matter_id,)):
            out.update(int(item) for item in json.loads(row["evidence_event_ids_json"] or "[]"))
        return out

    def _matter_side(self, actor_id: int, matter) -> str | None:
        if self.controls(actor_id, matter["claimant_type"], int(matter["claimant_id"])):
            return "claimant"
        if self.controls(actor_id, matter["respondent_type"], int(matter["respondent_id"])):
            return "respondent"
        return None

    def _validate_remedy(self, matter, remedy: dict[str, Any]) -> str | None:
        remedy_type = str(remedy.get("type", "none"))
        if remedy_type not in AVAILABLE_REMEDIES:
            return "unsupported remedy"
        if remedy_type == "damages":
            amount = int(remedy.get("amount_cents", 0))
            requested = json.loads(matter["requested_remedy_json"] or "{}")
            requested_amount = int(requested.get("amount_cents", self.max_damages_cents))
            if amount <= 0 or amount > min(self.max_damages_cents, requested_amount):
                return "damages exceed requested or ruleset limit"
        if remedy_type == "terminate_contract" and not matter["contract_id"]:
            return "termination remedy requires a contract"
        return None

    def _enforce_remedy(self, tick: int, matter, remedy: dict[str, Any], matter_id: int) -> dict[str, Any]:
        remedy_type = str(remedy.get("type", "none"))
        if remedy_type in {"none", "dismissal"}:
            return {"type": remedy_type}
        if remedy_type == "damages":
            source = self._entity_account(matter["respondent_type"], int(matter["respondent_id"]))
            target = self._entity_account(matter["claimant_type"], int(matter["claimant_id"]))
            if source is None or target is None:
                return {"type": "damages", "awarded_cents": int(remedy["amount_cents"]),
                        "paid_cents": 0, "reason": "party account missing"}
            award = int(remedy["amount_cents"])
            paid = max(0, min(award, self.ledger.balance(source)))
            txn_id = None
            if paid:
                txn_id = self.ledger.transfer(tick, source, target, paid, kind="legal_damages",
                                              memo=f"matter {matter_id} damages")
            return {"type": "damages", "awarded_cents": award, "paid_cents": paid,
                    "unpaid_cents": award - paid, "transaction_id": txn_id}
        if remedy_type == "terminate_contract":
            contract_id = int(matter["contract_id"])
            self.store.update("contracts", contract_id, status="terminated", terminated_tick=tick)
            self.store.execute(
                "UPDATE obligations SET status='cancelled' WHERE contract_id=? AND status='pending'",
                (contract_id,))
            return {"type": "terminate_contract", "contract_id": contract_id}
        restriction_id = self.store.insert(
            "legal_restrictions", matter_id=matter_id,
            subject_type=matter["respondent_type"], subject_id=int(matter["respondent_id"]),
            restriction_type=str(remedy.get("restriction_type", "conduct"))[:60],
            params_json=json.dumps(remedy.get("params", {}), sort_keys=True),
            effective_tick=tick,
            expiry_tick=(int(remedy["expiry_tick"]) if remedy.get("expiry_tick") is not None else None),
            status="active")
        return {"type": "injunction", "restriction_id": restriction_id}

    def _entity_account(self, entity_type: str, entity_id: int) -> int | None:
        if entity_type == "agent":
            return self.ledger.agent_checking_id(entity_id)
        if entity_type == "firm":
            value = self.store.scalar("SELECT account_id FROM firms WHERE id=?", (entity_id,))
            return int(value) if value is not None else None
        value = self.store.scalar(
            "SELECT id FROM accounts WHERE owner_type=? AND owner_id=? ORDER BY id LIMIT 1",
            ("gov" if entity_type == "government" else entity_type, entity_id))
        return int(value) if value is not None else None

    def is_restricted(self, subject_type: str, subject_id: int, restriction_type: str,
                      tick: int) -> bool:
        return bool(self.store.query_one(
            "SELECT 1 FROM legal_restrictions WHERE subject_type=? AND subject_id=? "
            "AND restriction_type=? AND status='active' AND effective_tick<=? "
            "AND (expiry_tick IS NULL OR expiry_tick>=?) LIMIT 1",
            (subject_type, subject_id, restriction_type, tick, tick)))

    # ------------------------------------------------------------------
    # Nightly state transitions and projections
    def run_nightly(self, tick: int) -> None:
        if not self.enabled:
            return
        self.store.execute(
            "UPDATE contracts SET status='active' WHERE status='executed' AND effective_tick<=?", (tick,))
        for obligation in self.store.query(
                "SELECT * FROM obligations WHERE status='pending' AND due_tick + grace_ticks < ? "
                "ORDER BY id", (tick,)):
            oid = int(obligation["id"])
            contract_id = int(obligation["contract_id"])
            self.store.update("obligations", oid, status="breached", breached_tick=tick)
            self.store.execute(
                "UPDATE contracts SET status='breached' WHERE id=? AND status IN ('active','executed')",
                (contract_id,))
            self.store.log_event(tick, "obligation_breached", {
                "obligation_id": oid, "contract_id": contract_id,
                "obligation_type": obligation["obligation_type"],
                "due_tick": int(obligation["due_tick"])}, phase="NIGHT_CLOSE",
                subject_type="contract", subject_id=contract_id, importance=2.5)
        expiring = self.store.query(
            "SELECT id FROM contracts WHERE expiry_tick IS NOT NULL AND expiry_tick<? "
            "AND status IN ('offered','negotiating','executed','active') ORDER BY id", (tick,))
        for row in expiring:
            contract_id = int(row["id"])
            self.store.update("contracts", contract_id, status="expired", terminated_tick=tick)
            self.store.execute(
                "UPDATE obligations SET status='cancelled' WHERE contract_id=? AND status='pending'",
                (contract_id,))
            self.store.log_event(tick, "contract_expired", {"contract_id": contract_id},
                                 phase="NIGHT_CLOSE", subject_type="contract",
                                 subject_id=contract_id, importance=1.0)
        self.store.execute(
            "UPDATE legal_restrictions SET status='expired' WHERE status='active' "
            "AND expiry_tick IS NOT NULL AND expiry_tick<?", (tick,))

    def contract_view(self, contract_id: int) -> dict[str, Any] | None:
        contract = self.store.query_one("SELECT * FROM contracts WHERE id=?", (contract_id,))
        if not contract:
            return None
        return {
            "contract": dict(contract),
            "parties": [dict(row) for row in self.store.query(
                "SELECT * FROM contract_parties WHERE contract_id=? ORDER BY id", (contract_id,))],
            "clauses": [{**dict(row), "terms": json.loads(row["terms_json"] or "{}")}
                        for row in self.store.query(
                            "SELECT * FROM contract_clauses WHERE contract_id=? ORDER BY ordinal",
                            (contract_id,))],
            "obligations": [dict(row) for row in self.store.query(
                "SELECT * FROM obligations WHERE contract_id=? ORDER BY id", (contract_id,))],
        }

    def docket(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return [{**dict(row),
                 "requested_remedy": json.loads(row["requested_remedy_json"] or "{}"),
                 "settlement": json.loads(row["settlement_json"] or "null")}
                for row in self.store.query(
                    "SELECT * FROM legal_matters ORDER BY id DESC LIMIT ?", (max(1, min(limit, 500)),))]

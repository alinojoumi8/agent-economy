"""Deterministic starting conditions for bounded behavioral provider gates.

The fixture creates work for the strategic agents without granting configuration
files or free text a state-mutation shortcut. Every proposal is submitted through
``ActionExecutor``; the legal close remains the authoritative breach detector.
"""
from __future__ import annotations

import json
from typing import Any

from engine.actions import ActionExecutor


class BehavioralFixtureError(RuntimeError):
    """Raised when a requested behavioral fixture cannot be seeded atomically."""


class BehavioralFixtureSeeder:
    def __init__(self, economy, config: dict[str, Any]):
        self.e = economy
        self.store = economy.store
        self.config = config
        self.cfg = dict(config.get("behavioral_fixture", {}) or {})
        self.executor = ActionExecutor(economy)

    def seed(self) -> dict[str, int] | None:
        if not self.cfg.get("enabled"):
            return None
        fixture_key = str(self.cfg.get("key", "seeded-startup-behavior-v1"))[:80]
        existing = self.store.query_one(
            "SELECT payload_json FROM events WHERE kind='behavioral_fixture_seeded' "
            "AND json_extract(payload_json,'$.fixture_key')=? ORDER BY id LIMIT 1",
            (fixture_key,),
        )
        if existing:
            return {key: int(value) for key, value in json.loads(existing["payload_json"]).items()
                    if key.endswith("_id")}

        with self.store.savepoint("behavioral_fixture_seed"):
            result = self._seed_startup_gate(fixture_key)
        return result

    def _seed_startup_gate(self, fixture_key: str) -> dict[str, int]:
        region = self.store.query_one(
            "SELECT * FROM regions WHERE region_key=?",
            (str(self.cfg.get("region", "northstar")),),
        )
        if not region:
            raise BehavioralFixtureError("behavioral fixture region is unavailable")
        region_id = int(region["id"])
        currency = str(region["currency_code"])

        lawyer = self._required_agent("lawyer")
        vc_partner = self._required_agent("vc_partner")
        officer = self.store.query_one(
            "SELECT a.* FROM agents a JOIN banks b ON b.id=a.employer_id "
            "WHERE a.role='credit_officer' AND a.alive=1 AND a.population_tier='core' "
            "AND b.region_id=? ORDER BY a.id LIMIT 1",
            (region_id,),
        )
        if not officer:
            raise BehavioralFixtureError("fixture needs a core credit officer in its region")
        bank_id = int(officer["employer_id"])

        founder = self.store.query_one(
            "SELECT a.* FROM agents a LEFT JOIN firms f ON f.founder_agent_id=a.id "
            "WHERE a.kind='citizen' AND a.alive=1 AND a.region_id=? "
            "GROUP BY a.id ORDER BY COUNT(f.id),a.id LIMIT 1",
            (region_id,),
        )
        if not founder:
            raise BehavioralFixtureError("fixture needs a living regional founder")
        founder_id = int(founder["id"])

        incorporation = self._must(-1, founder_id, {
            "type": "found_company",
            "name": str(self.cfg.get("startup_name", "Northstar Interface Labs")),
            "sector": "technology",
            "lawyer_agent_id": int(lawyer["id"]),
            "opening_capital": 0,
            "product": {
                "product": "interoperability_api_unit",
                "unit_price_cents": 1_000,
                "base_input_cost_cents": 400,
                "output_per_worker": 5,
            },
        })
        startup_id = int(incorporation["firm_id"])

        worker = self.store.query_one(
            "SELECT a.* FROM agents a WHERE a.kind='citizen' AND a.alive=1 "
            "AND a.retired=0 AND a.region_id=? AND a.id<>? "
            "AND NOT EXISTS (SELECT 1 FROM employments e WHERE e.agent_id=a.id AND e.status='active') "
            "ORDER BY a.id LIMIT 1",
            (region_id, founder_id),
        )
        if not worker:
            raise BehavioralFixtureError("fixture needs an available regional worker")
        job = self._must(-1, founder_id, {
            "type": "post_job", "firm_id": startup_id,
            "title": "interoperability engineer", "wage": 240_000,
        })
        application = self._must(-1, int(worker["id"]), {
            "type": "apply_job", "job_id": int(job["job_id"]),
        })
        self._must(-1, founder_id, {
            "type": "hire", "application_id": int(application["application_id"]),
        })

        respondent = self.store.query_one(
            "SELECT f.* FROM firms f WHERE f.id<>? AND f.region_id=? "
            "AND f.status<>'bankrupt' AND f.founder_agent_id IS NOT NULL ORDER BY f.id LIMIT 1",
            (startup_id, region_id),
        )
        if not respondent:
            raise BehavioralFixtureError("fixture needs a regional contract counterparty")
        respondent_id = int(respondent["id"])
        respondent_founder = int(respondent["founder_agent_id"])
        damages = int(self.cfg.get("damages_cents", 75_000))

        offered = self._must(-1, int(lawyer["id"]), {
            "type": "propose_contract",
            "title": "Interoperability delivery agreement",
            "contract_type": "supplier",
            "parties": [
                {"type": "firm", "id": startup_id, "role": "vendor"},
                {"type": "firm", "id": respondent_id, "role": "customer"},
            ],
            "clauses": [{
                "clause_key": "launch-payment",
                "clause_type": "payment",
                "terms": {
                    "obligor_role": "customer", "obligee_role": "vendor",
                    "amount_cents": damages, "currency_code": currency,
                    "due_tick": -1, "grace_ticks": 0,
                },
            }],
            "prose": "Fictional simulation fixture; typed clauses alone control state.",
        })
        contract_id = int(offered["contract_id"])
        for actor_id, party_id in ((founder_id, startup_id), (respondent_founder, respondent_id)):
            self._must(-1, actor_id, {
                "type": "accept_contract", "contract_id": contract_id,
                "party_type": "firm", "party_id": party_id,
            })

        # The agreement belongs to pre-simulation history (tick -1). The normal
        # deterministic close at tick 0 detects the overdue obligation.
        self.e.legal.run_nightly(0)
        breach_event_id = int(self.store.scalar(
            "SELECT id FROM events WHERE kind='obligation_breached' "
            "AND subject_type='contract' AND subject_id=? ORDER BY id DESC LIMIT 1",
            (contract_id,), default=0,
        ))
        if not breach_event_id:
            raise BehavioralFixtureError("fixture contract did not produce a breach event")

        claim = self._must(0, int(lawyer["id"]), {
            "type": "file_claim", "contract_id": contract_id,
            "claimant": {"type": "firm", "id": startup_id},
            "respondent": {"type": "firm", "id": respondent_id},
            "claim_type": "breach",
            "counsel_agent_id": int(lawyer["id"]),
            "requested_remedy": {"type": "damages", "amount_cents": damages},
            "metadata": {"fixture_key": fixture_key},
        })
        matter_id = int(claim["matter_id"])

        disclosure = self._must(0, founder_id, {
            "type": "publish_disclosure", "firm_id": startup_id,
            "disclosure_type": "material-litigation", "lookback_ticks": 30,
        })
        loan = self._must(0, founder_id, {
            "type": "apply_loan", "bank_id": bank_id,
            "amount": int(self.cfg.get("loan_amount_cents", 250_000)),
            "purpose": "interoperability launch working capital",
            "as_firm": True, "firm_id": startup_id,
        })
        pitch = self._must(0, founder_id, {
            "type": "pitch_vc", "firm_id": startup_id,
            "ask": int(self.cfg.get("pitch_amount_cents", 500_000)),
            "summary": "Scale an audited interoperability product while resolving disclosed litigation.",
        })

        payload = {
            "fixture_key": fixture_key,
            "startup_id": startup_id,
            "founder_id": founder_id,
            "worker_id": int(worker["id"]),
            "bank_id": bank_id,
            "credit_officer_id": int(officer["id"]),
            "vc_partner_id": int(vc_partner["id"]),
            "lawyer_id": int(lawyer["id"]),
            "contract_id": contract_id,
            "breach_event_id": breach_event_id,
            "matter_id": matter_id,
            "disclosure_id": int(disclosure["disclosure_id"]),
            "loan_application_id": int(loan["application_id"]),
            "pitch_id": int(pitch["pitch_id"]),
        }
        self.store.log_event(
            0, "behavioral_fixture_seeded", payload, phase="NIGHT_CLOSE",
            subject_type="firm", subject_id=startup_id, importance=3.0,
        )
        return {key: int(value) for key, value in payload.items() if key.endswith("_id")}

    def _required_agent(self, role: str):
        row = self.store.query_one(
            "SELECT * FROM agents WHERE role=? AND alive=1 AND population_tier='core' "
            "ORDER BY id LIMIT 1",
            (role,),
        )
        if not row:
            raise BehavioralFixtureError(f"fixture needs a core {role}")
        return row

    def _must(self, tick: int, actor_id: int, action: dict[str, Any]) -> dict[str, Any]:
        result = self.executor.execute_action(tick, actor_id, action, phase="FIXTURE")
        if not result.get("ok"):
            raise BehavioralFixtureError(
                f"fixture action {action.get('type')} failed: {result.get('reason', 'rejected')}"
            )
        return result

"""Typed startup, financing, intellectual-property, disclosure, and M&A services."""
from __future__ import annotations

import json
from typing import Any

from .ledger import Leg, Ledger
from .legal import LegalInstitution
from .store import Store


INSTRUMENTS = {"convertible", "preferred_equity", "common_equity"}
IP_TYPES = {"patent_like", "copyright", "trade_secret", "trademark"}
TRADER_ARCHETYPES = ("retail", "fundamental", "momentum", "institutional", "market_maker")


class StartupLifecycle:
    def __init__(self, store: Store, ledger: Ledger, legal: LegalInstitution,
                 config: dict | None = None):
        self.store = store
        self.ledger = ledger
        self.legal = legal
        self.config = config or {}
        competition = self.config.get("competition", {})
        self.hhi_threshold = float(competition.get("hhi_threshold", 1800.0))
        self.delta_threshold = float(competition.get("delta_threshold", 100.0))

    # ------------------------------------------------------------------ funding
    def propose_term_sheet(self, tick: int, actor_id: int, proposal: dict[str, Any]) -> dict[str, Any]:
        firm_id = int(proposal.get("firm_id", 0))
        firm = self.store.query_one("SELECT * FROM firms WHERE id=?", (firm_id,))
        investor = int(proposal.get("investor_agent_id", actor_id))
        metadata = proposal.get("metadata", {})
        metadata = dict(metadata) if isinstance(metadata, dict) else {}
        actor = self.store.query_one("SELECT role, alive FROM agents WHERE id=?", (actor_id,))
        if not firm or firm["status"] != "private":
            return {"ok": False, "reason": "term sheets require a private firm"}
        if investor != actor_id or not actor or not actor["alive"]:
            return {"ok": False, "reason": "investor must propose its own term sheet"}
        if (actor["role"] or "") not in {"vc_partner", "investor"}:
            return {"ok": False, "reason": "only an investor may propose a term sheet"}
        instrument = str(proposal.get("instrument_type", "preferred_equity"))
        amount = int(proposal.get("amount_cents", 0))
        equity_bps = proposal.get("equity_bps")
        if instrument not in INSTRUMENTS or amount <= 0:
            return {"ok": False, "reason": "invalid instrument or amount"}
        if instrument != "convertible" and not (0 < int(equity_bps or 0) < 10000):
            return {"ok": False, "reason": "equity financing requires equity_bps between 1 and 9999"}
        if instrument == "convertible" and int(proposal.get("valuation_cap_cents", 0)) <= 0:
            return {"ok": False, "reason": "convertible financing requires a valuation cap"}
        sheet_id = self.store.insert(
            "term_sheets", tick=tick, firm_id=firm_id, proposer_agent_id=actor_id,
            investor_agent_id=investor, instrument_type=instrument, amount_cents=amount,
            currency_code=str(proposal.get("currency_code", "USD")).upper(),
            pre_money_cents=proposal.get("pre_money_cents"),
            valuation_cap_cents=proposal.get("valuation_cap_cents"),
            discount_bps=proposal.get("discount_bps"), equity_bps=equity_bps,
            liquidation_preference_bps=int(proposal.get("liquidation_preference_bps", 10000)),
            pro_rata=1 if proposal.get("pro_rata") else 0,
            board_seat=1 if proposal.get("board_seat") else 0, status="offered",
            investor_accepted_tick=tick, contract_id=proposal.get("contract_id"),
            metadata_json=json.dumps(metadata, sort_keys=True))
        pitch_id = int(metadata.get("pitch_id", 0) or 0)
        if pitch_id:
            pitch = self.store.query_one(
                "SELECT id FROM pitches WHERE id=? AND firm_id=? AND status='pending'",
                (pitch_id, firm_id))
            if pitch:
                self.store.update(
                    "pitches", pitch_id, status="term_sheeted", decided_tick=tick,
                    vc_agent_id=actor_id, equity_bps=equity_bps)
        self.store.log_event(tick, "term_sheet_offered", {
            "term_sheet_id": sheet_id, "firm_id": firm_id, "investor_agent_id": investor,
            "instrument_type": instrument, "amount_cents": amount, "equity_bps": equity_bps},
            phase="EXECUTION", subject_type="firm", subject_id=firm_id, importance=2.2)
        return {"ok": True, "term_sheet_id": sheet_id, "status": "offered"}

    def accept_term_sheet(self, tick: int, actor_id: int, term_sheet_id: int) -> dict[str, Any]:
        sheet = self.store.query_one("SELECT * FROM term_sheets WHERE id=?", (term_sheet_id,))
        if not sheet or sheet["status"] != "offered":
            return {"ok": False, "reason": "term sheet is not open"}
        if actor_id == int(sheet["investor_agent_id"]):
            self.store.update("term_sheets", term_sheet_id, investor_accepted_tick=tick)
        elif self.legal.controls(actor_id, "firm", int(sheet["firm_id"])):
            self.store.update("term_sheets", term_sheet_id, founder_accepted_tick=tick)
        else:
            return {"ok": False, "reason": "actor cannot accept this term sheet"}
        sheet = self.store.query_one("SELECT * FROM term_sheets WHERE id=?", (term_sheet_id,))
        status = "accepted" if sheet["founder_accepted_tick"] is not None and sheet["investor_accepted_tick"] is not None else "offered"
        if status == "accepted":
            self.store.update("term_sheets", term_sheet_id, status=status)
            self.store.log_event(tick, "term_sheet_accepted", {
                "term_sheet_id": term_sheet_id, "firm_id": int(sheet["firm_id"])},
                phase="EXECUTION", subject_type="firm", subject_id=int(sheet["firm_id"]), importance=2.5)
        return {"ok": True, "term_sheet_id": term_sheet_id, "status": status}

    def run_due_diligence(self, tick: int, actor_id: int, term_sheet_id: int) -> dict[str, Any]:
        actor = self.store.query_one("SELECT role, occupation, alive FROM agents WHERE id=?", (actor_id,))
        sheet = self.store.query_one("SELECT * FROM term_sheets WHERE id=?", (term_sheet_id,))
        if not actor or not actor["alive"] or ((actor["role"] or "") not in {"lawyer", "counsel"}
                and (actor["occupation"] or "").lower() != "lawyer"):
            return {"ok": False, "reason": "due diligence requires a living lawyer"}
        if not sheet or sheet["status"] not in {"offered", "accepted"}:
            return {"ok": False, "reason": "term sheet unavailable"}
        firm_id = int(sheet["firm_id"])
        active_contracts = int(self.store.scalar(
            "SELECT COUNT(*) FROM contract_parties cp JOIN contracts c ON c.id=cp.contract_id "
            "WHERE cp.party_type='firm' AND cp.party_id=? AND c.status IN ('active','performed')",
            (firm_id,), default=0))
        breached_contracts = int(self.store.scalar(
            "SELECT COUNT(*) FROM contract_parties cp JOIN contracts c ON c.id=cp.contract_id "
            "WHERE cp.party_type='firm' AND cp.party_id=? AND c.status='breached'",
            (firm_id,), default=0))
        open_matters = int(self.store.scalar(
            "SELECT COUNT(*) FROM legal_matters WHERE status NOT IN ('decided','dismissed','settled') "
            "AND ((claimant_type='firm' AND claimant_id=?) OR (respondent_type='firm' AND respondent_id=?))",
            (firm_id, firm_id), default=0))
        ip_count = int(self.store.scalar(
            "SELECT COUNT(*) FROM ip_assets WHERE firm_id=? AND status='registered'", (firm_id,), default=0))
        cap_total = int(self.store.scalar("SELECT COALESCE(SUM(qty),0) FROM shares WHERE firm_id=?",
                                         (firm_id,), default=0))
        outstanding = int(self.store.scalar("SELECT shares_outstanding FROM firms WHERE id=?",
                                            (firm_id,), default=0))
        issues = []
        if cap_total != outstanding:
            issues.append("cap_table_mismatch")
        if breached_contracts:
            issues.append("breached_contracts")
        if open_matters:
            issues.append("open_legal_matters")
        findings = {"active_contracts": active_contracts, "breached_contracts": breached_contracts,
                    "open_legal_matters": open_matters, "registered_ip": ip_count,
                    "shares_outstanding": outstanding, "shares_held": cap_total, "issues": issues}
        status = "pass" if not issues else "qualified"
        check_id = self.store.insert(
            "due_diligence_checks", tick=tick, firm_id=firm_id, term_sheet_id=term_sheet_id,
            reviewer_agent_id=actor_id, scope="corporate,contract,ip,employment,financial,litigation",
            status=status, findings_json=json.dumps(findings, sort_keys=True), source_ids_json="[]")
        self.store.log_event(tick, "due_diligence_completed", {"check_id": check_id,
            "term_sheet_id": term_sheet_id, "firm_id": firm_id, "status": status,
            "issues": issues}, phase="EXECUTION", subject_type="firm", subject_id=firm_id,
            importance=2.0)
        return {"ok": True, "check_id": check_id, "status": status, "findings": findings}

    def close_funding_round(self, tick: int, actor_id: int, term_sheet_id: int) -> dict[str, Any]:
        sheet = self.store.query_one("SELECT * FROM term_sheets WHERE id=?", (term_sheet_id,))
        if not sheet or sheet["status"] != "accepted":
            return {"ok": False, "reason": "accepted term sheet required"}
        if actor_id != int(sheet["investor_agent_id"]):
            return {"ok": False, "reason": "only the named investor may close"}
        diligence = self.store.query_one(
            "SELECT status FROM due_diligence_checks WHERE term_sheet_id=? ORDER BY id DESC LIMIT 1",
            (term_sheet_id,))
        if not diligence or diligence["status"] not in {"pass", "qualified"}:
            return {"ok": False, "reason": "completed due diligence required"}
        firm = self.store.query_one("SELECT * FROM firms WHERE id=?", (sheet["firm_id"],))
        investor_acct = self.ledger.agent_checking_id(actor_id)
        amount = int(sheet["amount_cents"])
        if investor_acct is None or self.ledger.balance(investor_acct) < amount:
            return {"ok": False, "reason": "investor has insufficient funds"}
        outstanding = int(firm["shares_outstanding"])
        equity_bps = int(sheet["equity_bps"] or 0)
        if sheet["instrument_type"] == "convertible":
            cap = max(1, int(sheet["valuation_cap_cents"] or amount))
            equity_bps = min(9000, max(1, round(amount * 10000 / (cap + amount))))
        new_shares = max(1, round(outstanding * equity_bps / (10000 - equity_bps)))
        txn_id = self.ledger.transfer(tick, investor_acct, int(firm["account_id"]), amount,
                                      kind="startup_funding", memo=f"term sheet {term_sheet_id}")
        self._adjust_shares(int(firm["id"]), actor_id, new_shares)
        self.store.update("firms", int(firm["id"]), shares_outstanding=outstanding + new_shares)
        pre_money = sheet["pre_money_cents"] or sheet["valuation_cap_cents"]
        round_id = self.store.insert(
            "funding_rounds", tick=tick, firm_id=int(firm["id"]), term_sheet_id=term_sheet_id,
            investor_agent_id=actor_id, round_type=sheet["instrument_type"], amount_cents=amount,
            currency_code=sheet["currency_code"], shares_issued=new_shares,
            pre_money_cents=pre_money,
            post_money_cents=(int(pre_money) + amount if pre_money is not None else None),
            transaction_id=txn_id, status="closed")
        self.store.update("term_sheets", term_sheet_id, status="closed")
        metadata = json.loads(sheet["metadata_json"] or "{}")
        pitch_id = int(metadata.get("pitch_id", 0) or 0) if isinstance(metadata, dict) else 0
        if pitch_id:
            pitch = self.store.query_one(
                "SELECT id FROM pitches WHERE id=? AND firm_id=? "
                "AND status IN ('pending','term_sheeted')",
                (pitch_id, int(firm["id"])))
            if pitch:
                term_sheet = {
                    "term_sheet_id": term_sheet_id,
                    "instrument_type": sheet["instrument_type"],
                    "amount_cents": amount,
                    "currency_code": sheet["currency_code"],
                    "pre_money_cents": pre_money,
                    "equity_bps": equity_bps,
                }
                self.store.update(
                    "pitches", pitch_id, status="funded", decided_tick=tick,
                    vc_agent_id=actor_id, invested_cents=amount,
                    equity_bps=equity_bps, shares_issued=new_shares,
                    term_sheet_json=json.dumps(term_sheet, sort_keys=True))
        self.store.log_event(tick, "funding_round_closed", {
            "funding_round_id": round_id, "term_sheet_id": term_sheet_id,
            "firm_id": int(firm["id"]), "amount_cents": amount,
            "shares_issued": new_shares, "instrument_type": sheet["instrument_type"]},
            phase="EXECUTION", subject_type="firm", subject_id=int(firm["id"]), importance=3.5)
        return {"ok": True, "funding_round_id": round_id, "shares_issued": new_shares,
                "transaction_id": txn_id}

    def _adjust_shares(self, firm_id: int, agent_id: int, qty: int) -> None:
        row = self.store.query_one(
            "SELECT id, qty FROM shares WHERE firm_id=? AND holder_type='agent' AND holder_id=?",
            (firm_id, agent_id))
        if row:
            self.store.update("shares", int(row["id"]), qty=int(row["qty"]) + qty)
        else:
            self.store.insert("shares", firm_id=firm_id, holder_type="agent", holder_id=agent_id, qty=qty)

    # ------------------------------------------------------------------ IP and disclosures
    def register_ip(self, tick: int, actor_id: int, registration: dict[str, Any]) -> dict[str, Any]:
        firm_id = int(registration.get("firm_id", 0))
        actor = self.store.query_one("SELECT role, occupation FROM agents WHERE id=? AND alive=1", (actor_id,))
        is_counsel = bool(actor and ((actor["role"] or "") in {"lawyer", "counsel"}
                          or (actor["occupation"] or "").lower() == "lawyer"))
        if not self.legal.controls(actor_id, "firm", firm_id) and not is_counsel:
            return {"ok": False, "reason": "firm controller or counsel required"}
        asset_type = str(registration.get("asset_type", "patent_like"))
        title = str(registration.get("title", "")).strip()[:180]
        if asset_type not in IP_TYPES or not title:
            return {"ok": False, "reason": "valid IP type and title required"}
        asset_id = self.store.insert(
            "ip_assets", firm_id=firm_id, creator_agent_id=registration.get("creator_agent_id"),
            counsel_agent_id=actor_id if is_counsel else registration.get("counsel_agent_id"),
            asset_type=asset_type, title=title, scope=str(registration.get("scope", ""))[:1000],
            status="registered", registered_tick=tick,
            valuation_cents=max(0, int(registration.get("valuation_cents", 0))),
            metadata_json=json.dumps(registration.get("metadata", {}), sort_keys=True))
        self.store.log_event(tick, "ip_registered", {"ip_asset_id": asset_id,
            "firm_id": firm_id, "asset_type": asset_type, "title": title}, phase="EXECUTION",
            subject_type="firm", subject_id=firm_id, importance=2.0)
        return {"ok": True, "ip_asset_id": asset_id}

    def publish_disclosure(self, tick: int, actor_id: int, firm_id: int,
                           disclosure_type: str = "earnings", lookback_ticks: int = 30) -> dict[str, Any]:
        if not self.legal.controls(actor_id, "firm", firm_id):
            return {"ok": False, "reason": "actor does not control firm"}
        firm = self.store.query_one("SELECT * FROM firms WHERE id=?", (firm_id,))
        start = max(0, tick - max(1, lookback_ticks) + 1)
        sales = self.store.query(
            "SELECT id, json_extract(payload_json,'$.total_cents') AS total FROM events "
            "WHERE kind='goods_sale' AND tick BETWEEN ? AND ? "
            "AND json_extract(payload_json,'$.firm_id')=? ORDER BY id", (start, tick, firm_id))
        revenue = sum(int(row["total"] or 0) for row in sales)
        facts = {
            "cash_cents": self.ledger.balance(int(firm["account_id"])),
            "revenue_cents": revenue,
            "employees": int(self.store.scalar(
                "SELECT COUNT(*) FROM employments WHERE firm_id=? AND status='active'", (firm_id,), default=0)),
            "shares_outstanding": int(firm["shares_outstanding"]),
            "registered_ip": int(self.store.scalar(
                "SELECT COUNT(*) FROM ip_assets WHERE firm_id=? AND status='registered'", (firm_id,), default=0)),
            "active_contracts": int(self.store.scalar(
                "SELECT COUNT(DISTINCT c.id) FROM contracts c JOIN contract_parties cp ON cp.contract_id=c.id "
                "WHERE cp.party_type='firm' AND cp.party_id=? AND c.status='active'", (firm_id,), default=0)),
            "open_legal_matters": int(self.store.scalar(
                "SELECT COUNT(*) FROM legal_matters WHERE status NOT IN ('decided','dismissed','settled') "
                "AND ((claimant_type='firm' AND claimant_id=?) OR (respondent_type='firm' AND respondent_id=?))",
                (firm_id, firm_id), default=0)),
        }
        disclosure_id = self.store.insert(
            "firm_disclosures", tick=tick, firm_id=firm_id,
            disclosure_type=str(disclosure_type)[:60], period_start_tick=start, period_end_tick=tick,
            facts_json=json.dumps(facts, sort_keys=True),
            source_event_ids_json=json.dumps([int(row["id"]) for row in sales]),
            published_by_agent_id=actor_id)
        self.store.log_event(tick, "firm_disclosure_published", {
            "disclosure_id": disclosure_id, "firm_id": firm_id,
            "disclosure_type": disclosure_type, "facts": facts,
            "source_event_ids": [int(row["id"]) for row in sales]}, phase="EXECUTION",
            subject_type="firm", subject_id=firm_id, importance=2.5)
        return {"ok": True, "disclosure_id": disclosure_id, "facts": facts}

    def license_ip(self, tick: int, actor_id: int, license_data: dict[str, Any]) -> dict[str, Any]:
        asset_id = int(license_data.get("ip_asset_id", 0))
        asset = self.store.query_one("SELECT * FROM ip_assets WHERE id=? AND status='registered'", (asset_id,))
        if not asset or not self.legal.controls(actor_id, "firm", int(asset["firm_id"])):
            return {"ok": False, "reason": "IP owner authorization required"}
        licensee = int(license_data.get("licensee_firm_id", 0))
        if not self.store.query_one("SELECT 1 FROM firms WHERE id=? AND status<>'bankrupt'", (licensee,)):
            return {"ok": False, "reason": "licensee firm missing"}
        royalty = int(license_data.get("royalty_bps", 0))
        if not 0 <= royalty <= 10000:
            return {"ok": False, "reason": "royalty_bps must be between 0 and 10000"}
        contract_id = license_data.get("contract_id")
        if contract_id is not None and not self.store.query_one(
                "SELECT 1 FROM contracts WHERE id=? AND status IN ('active','performed')", (int(contract_id),)):
            return {"ok": False, "reason": "license contract is not effective"}
        license_id = self.store.insert(
            "ip_licenses", ip_asset_id=asset_id, licensor_firm_id=int(asset["firm_id"]),
            licensee_firm_id=licensee, contract_id=int(contract_id) if contract_id is not None else None,
            start_tick=tick,
            expiry_tick=(int(license_data["expiry_tick"]) if license_data.get("expiry_tick") is not None else None),
            royalty_bps=royalty, status="active")
        self.store.log_event(tick, "ip_licensed", {"ip_license_id": license_id,
            "ip_asset_id": asset_id, "licensor_firm_id": int(asset["firm_id"]),
            "licensee_firm_id": licensee, "royalty_bps": royalty}, phase="EXECUTION",
            subject_type="firm", subject_id=int(asset["firm_id"]), importance=1.8)
        return {"ok": True, "ip_license_id": license_id}

    # ------------------------------------------------------------------ M&A
    def propose_merger(self, tick: int, actor_id: int, proposal: dict[str, Any]) -> dict[str, Any]:
        acquirer = int(proposal.get("acquirer_firm_id", 0))
        target = int(proposal.get("target_firm_id", 0))
        price = int(proposal.get("price_cents", 0))
        if acquirer == target or price <= 0:
            return {"ok": False, "reason": "distinct firms and positive price required"}
        if not self.legal.controls(actor_id, "firm", acquirer):
            return {"ok": False, "reason": "actor does not control acquirer"}
        if self.legal.is_restricted("firm", acquirer, "merger", tick):
            return {"ok": False, "reason": "acquirer is enjoined from mergers"}
        firms = self.store.query(
            "SELECT id, status FROM firms WHERE id IN (?,?) ORDER BY id", (acquirer, target))
        if len(firms) != 2 or any(row["status"] in {"bankrupt", "acquired"} for row in firms):
            return {"ok": False, "reason": "both firms must be operating"}
        merger_id = self.store.insert(
            "mergers", proposed_tick=tick, acquirer_firm_id=acquirer, target_firm_id=target,
            proposer_agent_id=actor_id, consideration_type="cash", price_cents=price,
            currency_code=str(proposal.get("currency_code", "USD")).upper(), status="proposed",
            agreement_contract_id=proposal.get("agreement_contract_id"),
            metadata_json=json.dumps(proposal.get("metadata", {}), sort_keys=True))
        self.store.log_event(tick, "merger_proposed", {"merger_id": merger_id,
            "acquirer_firm_id": acquirer, "target_firm_id": target, "price_cents": price},
            phase="EXECUTION", subject_type="merger", subject_id=merger_id, importance=3.0)
        return {"ok": True, "merger_id": merger_id, "status": "proposed"}

    def approve_merger(self, tick: int, actor_id: int, merger_id: int) -> dict[str, Any]:
        merger = self.store.query_one("SELECT * FROM mergers WHERE id=?", (merger_id,))
        if not merger or merger["status"] != "proposed":
            return {"ok": False, "reason": "merger is not awaiting target approval"}
        if not self.legal.controls(actor_id, "firm", int(merger["target_firm_id"])):
            return {"ok": False, "reason": "target controller approval required"}
        self.store.update("mergers", merger_id, status="pending_review", target_approved_tick=tick,
                          regulator_notified_tick=tick)
        self.store.log_event(tick, "merger_notified", {"merger_id": merger_id}, phase="EXECUTION",
                             subject_type="merger", subject_id=merger_id, importance=2.8)
        return {"ok": True, "merger_id": merger_id, "status": "pending_review"}

    def review_merger(self, tick: int, actor_id: int, merger_id: int,
                      remedy: dict[str, Any] | None = None) -> dict[str, Any]:
        actor = self.store.query_one("SELECT role FROM agents WHERE id=? AND alive=1", (actor_id,))
        merger = self.store.query_one("SELECT * FROM mergers WHERE id=?", (merger_id,))
        if not actor or (actor["role"] or "") not in {"regulator", "competition_regulator"}:
            return {"ok": False, "reason": "competition regulator required"}
        if not merger or merger["status"] != "pending_review":
            return {"ok": False, "reason": "merger is not pending review"}
        pre_hhi, post_hhi = self._merger_hhi(tick, int(merger["acquirer_firm_id"]),
                                             int(merger["target_firm_id"]), lookback=30)
        delta = post_hhi - pre_hhi
        hhi_threshold = float(self.store.scalar(
            "SELECT CAST(json_extract(value_json,'$') AS REAL) FROM policy_rules "
            "WHERE rule_key='competition.hhi_threshold' AND status='active' "
            "ORDER BY effective_tick DESC,id DESC LIMIT 1", default=self.hhi_threshold))
        delta_threshold = float(self.store.scalar(
            "SELECT CAST(json_extract(value_json,'$') AS REAL) FROM policy_rules "
            "WHERE rule_key='competition.delta_threshold' AND status='active' "
            "ORDER BY effective_tick DESC,id DESC LIMIT 1", default=self.delta_threshold))
        presumptive = post_hhi >= hhi_threshold and delta >= delta_threshold
        remedy = dict(remedy or {})
        if presumptive and remedy.get("type") in {"divestiture", "interoperability"}:
            outcome = "approved_with_remedy"
        elif presumptive:
            outcome = "challenged"
        else:
            outcome = "approved"
        review_id = self.store.insert(
            "merger_reviews", merger_id=merger_id, tick=tick, regulator_agent_id=actor_id,
            lookback_ticks=30, pre_hhi=pre_hhi, post_hhi=post_hhi, delta_hhi=delta,
            threshold_hhi=hhi_threshold, threshold_delta=delta_threshold,
            outcome=outcome, remedy_json=json.dumps(remedy, sort_keys=True),
            rationale_summary=("Presumptive concentration screen triggered."
                               if presumptive else "Concentration screen not triggered."))
        self.store.update("mergers", merger_id, status=outcome)
        self.store.log_event(tick, "merger_reviewed", {"merger_id": merger_id,
            "review_id": review_id, "pre_hhi": pre_hhi, "post_hhi": post_hhi,
            "delta_hhi": delta, "outcome": outcome, "remedy": remedy}, phase="EXECUTION",
            subject_type="merger", subject_id=merger_id, importance=4.0)
        return {"ok": True, "review_id": review_id, "outcome": outcome,
                "pre_hhi": pre_hhi, "post_hhi": post_hhi, "delta_hhi": delta}

    def _merger_hhi(self, tick: int, acquirer: int, target: int, *, lookback: int) -> tuple[float, float]:
        sector = self.store.scalar("SELECT sector FROM firms WHERE id=?", (target,), default="")
        firms = [int(row["id"]) for row in self.store.query(
            "SELECT id FROM firms WHERE sector=? AND status NOT IN ('bankrupt','acquired') ORDER BY id", (sector,))]
        start = max(0, tick - lookback + 1)
        revenues = {firm_id: int(self.store.scalar(
            "SELECT COALESCE(SUM(json_extract(payload_json,'$.total_cents')),0) FROM events "
            "WHERE kind='goods_sale' AND tick BETWEEN ? AND ? "
            "AND json_extract(payload_json,'$.firm_id')=?", (start, tick, firm_id), default=0))
                    for firm_id in firms}
        total = sum(revenues.values())
        if total <= 0:
            revenues = {firm_id: 1 for firm_id in firms}
            total = len(firms)
        shares = {firm_id: value * 100.0 / total for firm_id, value in revenues.items()}
        pre_hhi = sum(value * value for value in shares.values())
        combined = shares.get(acquirer, 0.0) + shares.get(target, 0.0)
        post_hhi = sum(value * value for firm_id, value in shares.items()
                       if firm_id not in {acquirer, target}) + combined * combined
        return round(pre_hhi, 4), round(post_hhi, 4)

    def close_merger(self, tick: int, actor_id: int, merger_id: int) -> dict[str, Any]:
        merger = self.store.query_one("SELECT * FROM mergers WHERE id=?", (merger_id,))
        if not merger or merger["status"] not in {"approved", "approved_with_remedy"}:
            return {"ok": False, "reason": "approved merger required"}
        acquirer_id = int(merger["acquirer_firm_id"])
        target_id = int(merger["target_firm_id"])
        if not self.legal.controls(actor_id, "firm", acquirer_id):
            return {"ok": False, "reason": "actor does not control acquirer"}
        acquirer = self.store.query_one("SELECT * FROM firms WHERE id=?", (acquirer_id,))
        target = self.store.query_one("SELECT * FROM firms WHERE id=?", (target_id,))
        price = int(merger["price_cents"])
        source = int(acquirer["account_id"])
        if self.ledger.balance(source) < price:
            return {"ok": False, "reason": "acquirer cannot fund consideration"}
        holders = self.store.query("SELECT * FROM shares WHERE firm_id=? AND qty>0 ORDER BY id", (target_id,))
        total_shares = sum(int(row["qty"]) for row in holders)
        target_account = int(target["account_id"])
        legs = [Leg(source, -price, "cash merger consideration")]
        allocated = 0
        for index, holder in enumerate(holders):
            amount = price - allocated if index == len(holders) - 1 else price * int(holder["qty"]) // max(1, total_shares)
            account = self._holder_account(holder) or target_account
            legs.append(Leg(account, amount, f"target shares {holder['qty']}"))
            allocated += amount
        if not holders:
            legs.append(Leg(target_account, price, "target consideration"))
        txn_id = self.ledger.post(tick, "merger_close", legs, memo=f"merger {merger_id}")
        self.store.update("firms", target_id, status="acquired", bankrupt_tick=None)
        self.store.execute("UPDATE ip_assets SET firm_id=? WHERE firm_id=?", (acquirer_id, target_id))
        self.store.update("mergers", merger_id, status="closed", closed_tick=tick)
        self.store.log_event(tick, "merger_closed", {"merger_id": merger_id,
            "acquirer_firm_id": acquirer_id, "target_firm_id": target_id,
            "price_cents": price, "transaction_id": txn_id}, phase="EXECUTION",
            subject_type="merger", subject_id=merger_id, importance=4.5)
        return {"ok": True, "merger_id": merger_id, "transaction_id": txn_id, "status": "closed"}

    def _holder_account(self, holder) -> int | None:
        if holder["holder_type"] == "agent":
            return self.ledger.agent_checking_id(int(holder["holder_id"]))
        if holder["holder_type"] == "firm":
            value = self.store.scalar("SELECT account_id FROM firms WHERE id=?", (holder["holder_id"],))
            return int(value) if value is not None else None
        return None

    # ------------------------------------------------------------------ market participants
    def initialize_trader_profiles(self, tick: int = 0) -> None:
        agents = self.store.query("SELECT id, role, risk_tolerance FROM agents WHERE alive=1 ORDER BY id")
        for row in agents:
            agent_id = int(row["id"])
            if self.store.query_one("SELECT 1 FROM trader_profiles WHERE agent_id=?", (agent_id,)):
                continue
            role = row["role"] or ""
            archetype = ("market_maker" if role == "exchange" else
                         "institutional" if role in {"vc_partner", "investor"} else
                         TRADER_ARCHETYPES[agent_id % 3])
            weights = {
                "retail": (0.5, 0.2, 0.3), "fundamental": (0.1, 0.8, 0.1),
                "momentum": (0.2, 0.1, 0.7), "institutional": (0.1, 0.75, 0.15),
                "market_maker": (0.05, 0.45, 0.5),
            }[archetype]
            self.store.insert(
                "trader_profiles", agent_id=agent_id, archetype=archetype,
                horizon_ticks={"retail": 7, "fundamental": 30, "momentum": 5,
                               "institutional": 60, "market_maker": 1}[archetype],
                risk_budget_bps=max(100, round(float(row["risk_tolerance"] or 0.5) * 5000)),
                sentiment_weight=weights[0], fundamentals_weight=weights[1],
                momentum_weight=weights[2], updated_tick=tick)

    def cap_table_reconciles(self, firm_id: int) -> bool:
        held = int(self.store.scalar("SELECT COALESCE(SUM(qty),0) FROM shares WHERE firm_id=?",
                                     (firm_id,), default=0))
        outstanding = int(self.store.scalar("SELECT shares_outstanding FROM firms WHERE id=?",
                                            (firm_id,), default=0))
        return held == outstanding

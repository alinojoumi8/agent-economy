"""Context + prompt assembly (TECH-SPEC §6).

`ContextBuilder` gathers everything an agent needs to decide — persona, state,
beliefs, retrieved memories, today's news, things heard — into one structured
`context` dict. That dict is consumed two ways:
  • scripted policies read it directly (offline runs);
  • `render_prompt` turns it into the cached system prefix + a per-wakeup user
    message for real LLMs.
Both paths therefore see identical information, so switching providers can't change
what an agent knew.
"""
from __future__ import annotations

import hashlib
import json
from typing import Optional

from engine.core import Economy
from engine.store import load_json
from .memory import Memory


INSTITUTIONAL_DECISION_ROLES = {
    "exchange", "gov_official", "legislator_house", "legislator_senate",
    "regulator", "competition_regulator", "labor_regulator", "executive",
    "lobbyist",
}

# Shared system prefix — identical for all citizens, so it caches well (§8, §12).
SYSTEM_PREFIX = """You are a person living inside a simulated US-style economy. You reason in character
and act in your own self-interest given your persona, finances, beliefs, and what you have read and heard.

Respond with ONLY a JSON object of this exact shape:
{
  "reasoning": "one or two sentences, in character",
  "actions": [ {"type": "...", ...} ],
  "belief_updates": [ {"key": "trust:bank:2", "value": 0.31} ]
}
Valid action types: buy_goods{firm_id,qty}, place_order{firm_id,side,qty,limit_price},
apply_loan{bank_id,amount,purpose}, apply_job{job_id}, post_job{firm_id,title,wage},
set_price{firm_id,price}, hire{application_id}, fire{employment_id},
found_company{name,sector,lawyer_agent_id}, transfer{to_account,amount,memo},
move_deposits{to_bank_id}, pitch_vc{firm_id,ask,summary}, buy_insurance{},
cancel_insurance{}, publish_disclosure{firm_id,disclosure_type,lookback_ticks},
say_public{text}, do_nothing.
Role actions: approve_loan{application_id,rate_bps,term_ticks},
  deny_loan{application_id,reason}, set_policy_rate{rate_bps},
  decide_liquidity_support{request_event_id,decision,evidence_event_ids},
fund_pitch{pitch_id,amount,equity_bps}, decline_pitch{pitch_id,reason}.
Legal role actions: submit_filing{matter_id,filer_type,filer_id,filing_type,
evidence_event_ids,body}, propose_settlement{matter_id,terms:{remedy:{type,
amount_cents}}}.
Every field ending in _id, plus to_account, MUST be a JSON integer copied exactly from the
provided context. Never emit labels such as "firm7", "job2", names, titles, or composite strings
where an integer ID is required.
You are never obligated to act. Money is in cents. Stay in character."""

INSTITUTIONAL_ACTIONS_SUFFIX = """
Institutional actions: sponsor_bill{title,topic,summary,policy_changes},
committee_vote{bill_id,vote}, cast_legislative_vote{bill_id,vote},
executive_bill_action{bill_id,action,effective_delay_ticks},
lobby{sponsor_type,sponsor_id,authorized_by_agent_id,target_agent_id,bill_id,
activity_type,position,amount_cents}, review_merger{merger_id,remedy},
place_fx_order{pair,side,qty,limit_rate_ppm}."""

LABOR_IPO_ACTIONS_SUFFIX = """
Semantics 6 labor actions replace direct hire: make_job_offer{application_id,wage},
counter_job_offer{offer_id,wage}, accept_job_offer{offer_id},
reject_job_offer{offer_id}. Only the receiving side may respond to a pending offer.
IPO actions: open_ipo{firm_id,shares_offered,reserve_price,minimum_subscription_bps},
place_ipo_bid{offering_id,qty,max_price}, close_ipo{offering_id}. Prices must be
chosen by agents from supplied facts; never invent an offering or entity ID."""


def _seed(agent_id: int, tick: int, salt: str = "") -> int:
    return int(hashlib.sha1(f"{agent_id}:{tick}:{salt}".encode()).hexdigest()[:12], 16)


class ContextBuilder:
    def __init__(self, economy: Economy, memory: Memory, config: dict):
        self.e = economy
        self.store = economy.store
        self.mem = memory
        self.config = config
        self.institutional_role_purposes = bool(
            config.get("llm", {}).get("institutional_role_purposes", False))
        self.local_currency_action_surfaces = bool(
            config.get("llm", {}).get("local_currency_action_surfaces", False))
        self.engine_semantics_version = int(config.get("engine_semantics_version", 2))
        self.citizen_bank_visibility = str(
            config.get("information", {}).get(
                "citizen_bank_visibility", "full_balance_sheet"))
        if self.citizen_bank_visibility not in {
                "public_status", "full_balance_sheet"}:
            raise ValueError(
                "information.citizen_bank_visibility must be public_status or "
                "full_balance_sheet")

    # ── public: assemble per-role context ────────────────────────────────────
    def build(self, agent_row, tick: int) -> dict:
        role = agent_row["role"]
        if role == "central_banker":
            return self._central_banker_context(agent_row, tick)
        if role == "credit_officer":
            return self._credit_officer_context(agent_row, tick)
        if role == "vc_partner":
            return self._vc_partner_context(agent_row, tick)
        if role == "lawyer":
            return self._lawyer_context(agent_row, tick)
        ctx = self._citizen_context(agent_row, tick)
        firm = self.store.query_one(
            "SELECT * FROM firms WHERE founder_agent_id=? AND status<>'bankrupt' LIMIT 1",
            (agent_row["id"],))
        if firm:
            ctx["my_firm"] = self._firm_view(firm, tick)
            ctx["firm_applications"] = self._firm_applications(int(firm["id"]))
            if self.engine_semantics_version >= 6:
                ctx["firm_job_offers"] = self._firm_job_offers(int(firm["id"]))
            ctx["purpose"] = "founder"
        elif self.institutional_role_purposes and role in INSTITUTIONAL_DECISION_ROLES:
            ctx["purpose"] = role
            ctx["institutional_work"] = self._institutional_work(agent_row, tick)
        return ctx

    def purpose_for(self, agent_row) -> str:
        role = agent_row["role"]
        if role in ("central_banker", "credit_officer", "vc_partner", "lawyer"):
            return role
        if self.store.query_one("SELECT 1 FROM firms WHERE founder_agent_id=? AND status<>'bankrupt'",
                                (agent_row["id"],)):
            return "founder"
        if self.institutional_role_purposes and role in INSTITUTIONAL_DECISION_ROLES:
            return str(role)
        return "decision"

    # ── citizen ──────────────────────────────────────────────────────────────
    def _citizen_context(self, a, tick: int) -> dict:
        agent_id = int(a["id"])
        if self.local_currency_action_surfaces:
            checking = self.store.query_one(
                "SELECT ac.* FROM agents ag JOIN accounts ac ON ac.id=ag.checking_account_id "
                "WHERE ag.id=? AND ac.owner_type='agent' AND ac.owner_id=?",
                (agent_id, agent_id))
            if checking is None:
                checking = self.store.query_one(
                    "SELECT * FROM accounts WHERE owner_type='agent' AND owner_id=? "
                    "AND kind='checking' ORDER BY id LIMIT 1", (agent_id,))
        else:
            checking = self.store.query_one(
                "SELECT * FROM accounts WHERE owner_type='agent' AND owner_id=? AND kind='checking' "
                "ORDER BY balance_cents DESC LIMIT 1", (agent_id,))
        cash = int(checking["balance_cents"]) if checking else 0
        bank_id = int(checking["bank_id"]) if checking and checking["bank_id"] is not None else None
        currency_code = str(checking["currency_code"] or "USD") if checking else "USD"
        debt = int(self.store.scalar(
            "SELECT COALESCE(SUM(outstanding_cents),0) FROM loans "
            "WHERE borrower_type='agent' AND borrower_id=? AND status='active'", (agent_id,), default=0))
        emp = self.store.query_one(
            "SELECT * FROM employments WHERE agent_id=? AND status='active' LIMIT 1", (agent_id,))
        shares = {str(r["firm_id"]): int(r["qty"]) for r in self.store.query(
            "SELECT firm_id, qty FROM shares WHERE holder_type='agent' AND holder_id=?", (agent_id,))}
        beliefs = self.mem.get_beliefs(agent_id)

        cadence = load_json(a["cadence_json"], {}) or {}
        portfolio_every = int(cadence.get("portfolio", 7))
        portfolio_day = (tick % max(1, portfolio_every)) == (agent_id % max(1, portfolio_every))
        career_every = int(cadence.get("career", 30))
        career_day = (tick % max(1, career_every)) == (agent_id % max(1, career_every))

        heard = self._heard(agent_id, tick)
        memories = self.mem.retrieve(agent_id, tick, k=6, query_entities=self._query_entities(bank_id))

        insured = self.store.query_one(
            "SELECT 1 FROM insurance_policies WHERE agent_id=? AND status='active'",
            (agent_id,)) is not None
        state = {"checking_balance": cash, "bank_id": bank_id, "debt": debt,
                 "employed": emp is not None, "wage": int(emp["wage_cents"]) if emp else 0,
                 "net_worth": self.e.ledger.net_worth_agent(agent_id), "shares": shares}
        if self.local_currency_action_surfaces:
            state["currency_code"] = currency_code
        context = {
            "tick": tick,
            "purpose": "decision",
            "rng_seed": _seed(agent_id, tick),
            "run_threshold": float(self.config.get("behavior", {}).get("run_threshold", 0.35)),
            "insured": insured,
            "insurance_offer": self._insurance_offer(
                currency_code if self.local_currency_action_surfaces else None),
            "agent": {"id": agent_id, "name": a["name"], "age": int(a["age"]),
                      "occupation": a["occupation"], "role": a["role"], "health": a["health"],
                      "retired": bool(a["retired"]), "dependents": int(a["dependents"]),
                      "risk_tolerance": float(a["risk_tolerance"] or 0.5),
                      "political_lean": float(a["political_lean"] or 0.0)},
            "state": state,
            "beliefs": beliefs,
            "prices": self._goods_offers(
                currency_code if self.local_currency_action_surfaces else None),
            "jobs": self._open_jobs(
                currency_code if self.local_currency_action_surfaces else None),
            "listed_firms": self._listed_firms(
                tick, currency_code if self.local_currency_action_surfaces else None),
            "banks": self._bank_views(
                self.citizen_bank_visibility,
                currency_code=currency_code if self.local_currency_action_surfaces else None),
            "news": self._news_for(a, tick),
            "heard": heard,
            "memories": [m["text"] for m in memories],
            "policy_rate_bps": self.e.policy_rate_bps(),
            "metrics": self._metrics_snapshot(tick),
            "portfolio_day": portfolio_day,
            "career_day": career_day,
        }
        if self.engine_semantics_version >= 6:
            context["labor_negotiation_enabled"] = True
            context["incoming_job_offers"] = self._incoming_job_offers(agent_id)
            context["ipo_offerings"] = self._ipo_offerings(
                currency_code if self.local_currency_action_surfaces else None)
        return context

    def _insurance_offer(self, currency_code: str | None = None) -> Optional[dict]:
        currency_clause = " AND currency_code=?" if currency_code is not None else ""
        params = (currency_code,) if currency_code is not None else ()
        insurer = self.store.query_one(
            "SELECT id, name FROM firms WHERE sector='insurance' AND status<>'bankrupt' "
            f"{currency_clause} ORDER BY id LIMIT 1", params)
        if not insurer:
            return None
        h = self.e.lifecycle.h
        return {"insurer_firm_id": int(insurer["id"]), "insurer": insurer["name"],
                "premium": int(h["premium_cents"]), "coverage_bps": int(h["coverage_bps"]),
                "interval_ticks": int(h["premium_interval_ticks"])}

    def _query_entities(self, bank_id: Optional[int]) -> list[str]:
        ents = ["economy"]
        if bank_id is not None:
            ents.append(f"bank:{bank_id}")
        return ents

    def _heard(self, agent_id: int, tick: int) -> list[dict]:
        rows = self.store.query(
            "SELECT text, entities_json FROM memories WHERE agent_id=? AND tick>=? AND kind='observation'",
            (agent_id, tick - 1))
        heard = []
        for r in rows:
            ents = load_json(r["entities_json"], []) or []
            rumor_bank = None
            for e in ents:
                if isinstance(e, str) and e.startswith("rumor_bank:"):
                    rumor_bank = int(e.split(":")[1])
            if rumor_bank is not None:
                heard.append({"text": r["text"], "rumor_bank": rumor_bank})
        return heard

    def _goods_offers(self, currency_code: str | None = None) -> list[dict]:
        inventory_clause = "inventory>0" if self.engine_semantics_version >= 2 else "inventory>=0"
        currency_clause = " AND currency_code=?" if currency_code is not None else ""
        params = (currency_code,) if currency_code is not None else ()
        firms = self.store.query(
            "SELECT id, product_json, inventory, currency_code FROM firms "
            f"WHERE status IN ('private','listed') AND {inventory_clause} "
            f"{currency_clause} ORDER BY inventory DESC, id", params)
        out = []
        for f in firms:
            prod = load_json(f["product_json"], {}) or {}
            offer = {"firm_id": int(f["id"]), "product": prod.get("product", "goods"),
                     "price": int(prod.get("unit_price_cents", 500)),
                     "inventory": int(f["inventory"])}
            if currency_code is not None:
                offer["currency_code"] = str(f["currency_code"] or "USD")
            out.append(offer)
        return out

    def _open_jobs(self, currency_code: str | None = None) -> list[dict]:
        currency_clause = " AND f.currency_code=?" if currency_code is not None else ""
        params = (currency_code,) if currency_code is not None else ()
        order_clause = (
            " ORDER BY j.wage_cents DESC,j.id LIMIT 20" if currency_code is not None
            else " ORDER BY j.wage_cents DESC LIMIT 20")
        out = []
        for j in self.store.query(
                "SELECT j.*,f.currency_code AS firm_currency FROM jobs j "
                "JOIN firms f ON f.id=j.firm_id "
                f"WHERE j.status='open'{currency_clause} "
                f"{order_clause}", params):
            item = {"job_id": int(j["id"]), "firm_id": int(j["firm_id"]),
                    "title": j["title"], "wage": int(j["wage_cents"])}
            if currency_code is not None:
                item["currency_code"] = str(j["firm_currency"] or "USD")
            out.append(item)
        return out

    def _incoming_job_offers(self, agent_id: int) -> list[dict]:
        rows = self.store.query(
            "SELECT jo.id AS offer_id,jo.application_id,jo.wage_cents,"
            "jo.proposer_agent_id,ap.job_id,j.firm_id,j.title,j.wage_cents AS posted_wage,"
            "f.name AS firm_name,f.currency_code FROM job_offers jo "
            "JOIN applications ap ON ap.id=jo.application_id "
            "JOIN jobs j ON j.id=ap.job_id JOIN firms f ON f.id=j.firm_id "
            "WHERE jo.status='pending' AND ap.state='negotiating' "
            "AND ap.agent_id=? AND jo.proposer_agent_id<>ap.agent_id ORDER BY jo.id",
            (agent_id,))
        return [{
            "offer_id": int(row["offer_id"]),
            "application_id": int(row["application_id"]),
            "job_id": int(row["job_id"]), "firm_id": int(row["firm_id"]),
            "firm_name": row["firm_name"], "title": row["title"],
            "posted_wage": int(row["posted_wage"]),
            "offered_wage": int(row["wage_cents"]),
            "proposer_agent_id": int(row["proposer_agent_id"]),
            "currency_code": str(row["currency_code"] or "USD"),
        } for row in rows]

    def _ipo_offerings(self, currency_code: str | None = None) -> list[dict]:
        currency_clause = " AND f.currency_code=?" if currency_code is not None else ""
        params = (currency_code,) if currency_code is not None else ()
        rows = self.store.query(
            "SELECT io.id AS offering_id,io.firm_id,io.shares_offered,"
            "io.reserve_price_cents,io.minimum_subscription_bps,f.name,f.currency_code,"
            "COALESCE(SUM(CASE WHEN b.status='open' THEN b.qty ELSE 0 END),0) AS demand "
            "FROM ipo_offerings io JOIN firms f ON f.id=io.firm_id "
            "LEFT JOIN ipo_bids b ON b.offering_id=io.id "
            f"WHERE io.status='building'{currency_clause} "
            "GROUP BY io.id ORDER BY io.id", params)
        return [{
            "offering_id": int(row["offering_id"]), "firm_id": int(row["firm_id"]),
            "firm_name": row["name"], "shares_offered": int(row["shares_offered"]),
            "reserve_price": int(row["reserve_price_cents"]),
            "minimum_subscription_bps": int(row["minimum_subscription_bps"]),
            "book_demand": int(row["demand"]),
            "currency_code": str(row["currency_code"] or "USD"),
        } for row in rows]

    def _listed_firms(self, tick: int, currency_code: str | None = None) -> list[dict]:
        out = []
        currency_clause = " AND currency_code=?" if currency_code is not None else ""
        params = (currency_code,) if currency_code is not None else ()
        for f in self.store.query(
                "SELECT id,name,account_id,inventory,product_json,currency_code FROM firms "
                f"WHERE status='listed'{currency_clause} ORDER BY id", params):
            firm_id = int(f["id"])
            product = load_json(f["product_json"], {}) or {}
            shares = int(self.store.scalar(
                "SELECT COALESCE(SUM(qty),0) FROM shares WHERE firm_id=?",
                (firm_id,), default=0))
            cash = self.e.ledger.balance(int(f["account_id"]))
            revenue_7 = int(self.store.scalar(
                "SELECT COALESCE(SUM(json_extract(payload_json,'$.total_cents')),0) "
                "FROM events WHERE kind='goods_sale' AND tick>? "
                "AND json_extract(payload_json,'$.firm_id')=?",
                (tick - 7, firm_id), default=0))
            item = {
                "firm_id": firm_id, "name": f["name"],
                "last_price": self.e.exchange.last_price(firm_id),
                "book_value_per_share": round(cash / shares) if shares else None,
                "cash": cash, "inventory": int(f["inventory"]),
                "goods_price": int(product.get("unit_price_cents", 500)),
                "recent_revenue_7": revenue_7,
            }
            if currency_code is not None:
                item["currency_code"] = str(f["currency_code"] or "USD")
            out.append(item)
        return out

    def _bank_views(
        self,
        visibility: str = "full_balance_sheet",
        *,
        own_bank_id: Optional[int] = None,
        currency_code: str | None = None,
    ) -> list[dict]:
        out = []
        currency_clause = " WHERE currency_code=?" if currency_code is not None else ""
        params = (currency_code,) if currency_code is not None else ()
        order_clause = " ORDER BY id" if currency_code is not None else ""
        for b in self.store.query(
                f"SELECT * FROM banks{currency_clause}{order_clause}", params):
            bank_id = int(b["id"])
            view = {"id": bank_id, "name": b["name"], "status": b["status"]}
            if currency_code is not None:
                view["currency_code"] = str(b["currency_code"] or "USD")
            if visibility == "full_balance_sheet" or bank_id == own_bank_id:
                view["reserve_ratio"] = round(self.e.bank.reserve_ratio(bank_id), 4)
            out.append(view)
        return out

    def _institutional_work(self, a, tick: int) -> dict:
        """Return a bounded queue of actions that are valid in the current state.

        Concurrent decisions receive the same morning snapshot. Legislative
        queues therefore expose only the smallest quorum-needed set of unvoted
        members so the final same-tick vote advances the bill without making
        later proposals stale.
        """
        agent_id = int(a["id"])
        role = str(a["role"] or "")
        work: dict = {"role": role, "eligible_actions": []}
        primary = self.store.query_one(
            "SELECT ac.id,ac.balance_cents,ac.currency_code,ac.bank_id FROM agents ag "
            "JOIN accounts ac ON ac.id=ag.checking_account_id WHERE ag.id=?", (agent_id,))
        if primary:
            work["wallet"] = {
                "account_id": int(primary["id"]),
                "balance_cents": int(primary["balance_cents"]),
                "currency_code": str(primary["currency_code"] or "USD"),
                "bank_id": int(primary["bank_id"]) if primary["bank_id"] is not None else None,
            }

        if role in {"legislator_house", "legislator_senate"}:
            self._legislative_work(agent_id, work)
        elif role == "executive":
            bill = self.store.query_one(
                "SELECT id,title,status FROM bills WHERE status='executive' ORDER BY id LIMIT 1")
            if bill:
                work["bills"] = [dict(bill)]
                work["eligible_actions"].append({
                    "type": "executive_bill_action", "bill_id": int(bill["id"]),
                    "action": "sign", "effective_delay_ticks": 1,
                })
        elif role == "lobbyist":
            bill = self.store.query_one(
                "SELECT b.id,b.title,b.status,l.agent_id AS sponsor_agent_id FROM bills b "
                "JOIN legislators l ON l.id=b.sponsor_legislator_id "
                "WHERE b.status NOT IN ('failed','enacted') ORDER BY b.id LIMIT 1")
            first_lobbyist = self.store.scalar(
                "SELECT MIN(id) FROM agents WHERE role='lobbyist' AND alive=1")
            already = self.store.query_one(
                "SELECT 1 FROM lobbying_activities WHERE lobbyist_agent_id=? AND bill_id=?",
                (agent_id, int(bill["id"]))) if bill else None
            if bill:
                work["bills"] = [{"id": int(bill["id"]), "title": bill["title"],
                                  "status": bill["status"]}]
            if bill and agent_id == int(first_lobbyist or 0) and not already:
                work["eligible_actions"].append({
                    "type": "lobby", "sponsor_type": "agent", "sponsor_id": agent_id,
                    "authorized_by_agent_id": agent_id,
                    "target_agent_id": int(bill["sponsor_agent_id"]),
                    "bill_id": int(bill["id"]), "activity_type": "meeting",
                    "position": "support", "amount_cents": 1000,
                })
        elif role in {"regulator", "competition_regulator", "labor_regulator"}:
            agency = self.store.query_one(
                "SELECT id,name,mandate,capacity FROM agencies WHERE leader_agent_id=?",
                (agent_id,))
            if agency:
                work["agency"] = dict(agency)
            if role == "competition_regulator":
                merger = self.store.query_one(
                    "SELECT id,acquirer_firm_id,target_firm_id,price_cents,currency_code,status "
                    "FROM mergers WHERE status='pending_review' ORDER BY id LIMIT 1")
                if merger:
                    work["pending_mergers"] = [dict(merger)]
                    work["eligible_actions"].append({
                        "type": "review_merger", "merger_id": int(merger["id"]),
                        "remedy": {"type": "interoperability", "duration_ticks": 180},
                    })
        elif role == "exchange" and primary:
            prior = self.store.query_one(
                "SELECT 1 FROM fx_orders WHERE actor_id=? LIMIT 1", (agent_id,))
            foreign = self.store.query_one(
                "SELECT code FROM currencies WHERE code<>? ORDER BY code LIMIT 1",
                (str(primary["currency_code"] or "USD"),))
            if not prior and foreign and int(primary["balance_cents"]) >= 1000:
                base = str(foreign["code"])
                quote = str(primary["currency_code"] or "USD")
                rate = int(self.e.regions.current_rate(base, quote))
                work["fx_market"] = {"pair": f"{base}/{quote}", "current_rate_ppm": rate}
                work["eligible_actions"].append({
                    "type": "place_fx_order", "pair": f"{base}/{quote}",
                    "side": "buy", "qty": 1000, "limit_rate_ppm": rate,
                })
        return work

    def _legislative_work(self, agent_id: int, work: dict) -> None:
        legislator = self.store.query_one(
            "SELECT l.id,l.chamber,l.seat_number,l.party_id FROM legislators l "
            "WHERE l.agent_id=? AND l.active=1", (agent_id,))
        if not legislator:
            return
        committee_ids = [int(row["committee_id"]) for row in self.store.query(
            "SELECT committee_id FROM committee_members WHERE legislator_id=? ORDER BY committee_id",
            (int(legislator["id"]),))]
        work["legislator"] = {**dict(legislator), "committee_ids": committee_ids}
        bills = self.store.query(
            "SELECT id,title,status,current_version,committee_id,origin_chamber "
            "FROM bills ORDER BY id DESC LIMIT 8")
        work["bills"] = [dict(row) for row in bills]

        if not bills:
            first = int(self.store.scalar(
                "SELECT MIN(agent_id) FROM legislators WHERE active=1", default=0) or 0)
            if agent_id == first:
                work["eligible_actions"].append({
                    "type": "sponsor_bill", "title": "AI Market Interoperability Act",
                    "topic": "competition",
                    "summary": "Require acquisition disclosure and strengthen competition review.",
                    "policy_changes": {
                        "competition.agency_capacity": 1.25,
                        "ai.mandatory_acquisition_disclosure": True,
                    },
                })
            return

        bill = next((row for row in reversed(bills)
                     if row["status"] in {"committee", "floor_house", "floor_senate"}), None)
        if bill is None:
            return
        status = str(bill["status"])
        if status == "committee":
            members = self.store.query(
                "SELECT l.id,l.agent_id FROM committee_members cm JOIN legislators l "
                "ON l.id=cm.legislator_id WHERE cm.committee_id=? AND l.active=1 ORDER BY l.id",
                (int(bill["committee_id"]),))
            stage = "committee"
            threshold = len(members) // 2 + 1
        else:
            chamber = status.removeprefix("floor_")
            members = self.store.query(
                "SELECT id,agent_id FROM legislators WHERE chamber=? AND active=1 ORDER BY id",
                (chamber,))
            stage = chamber
            threshold = len(members) // 2 + 1
        voted = {int(row["legislator_id"]): str(row["vote"]) for row in self.store.query(
            "SELECT legislator_id,vote FROM legislative_votes WHERE bill_id=? AND version=? "
            "AND stage=?", (int(bill["id"]), int(bill["current_version"]), stage))}
        yes = sum(1 for vote in voted.values() if vote == "yes")
        needed = max(0, threshold - yes)
        eligible = [int(row["agent_id"]) for row in members
                    if int(row["id"]) not in voted][:needed]
        if agent_id in eligible:
            action_type = "committee_vote" if stage == "committee" else "cast_legislative_vote"
            work["eligible_actions"].append({
                "type": action_type, "bill_id": int(bill["id"]), "vote": "yes",
            })

    def _news_for(self, a, tick: int) -> list[dict]:
        diet = set(load_json(a["media_diet_json"], []) or [])
        if self.engine_semantics_version >= 4:
            # In v2 an article is visible only after a persisted exposure.  This
            # is the information-asymmetry boundary: querying the newsroom is
            # not equivalent to an agent having observed every publication.
            rows = self.store.query(
                "SELECT n.* FROM information_exposures e "
                "JOIN information_items i ON i.id=e.item_id "
                "JOIN news_articles n ON n.id=i.news_article_id "
                "WHERE e.agent_id=? AND e.tick>=? ORDER BY e.tick DESC, e.id DESC LIMIT 12",
                (int(a["id"]), tick - 1))
        else:
            rows = self.store.query(
                "SELECT * FROM news_articles WHERE tick>=? ORDER BY tick DESC LIMIT 12", (tick - 1,))
        out = []
        for r in rows:
            if diet and int(r["outlet_id"]) not in diet:
                continue
            head = (r["headline"] or "")
            out.append({"headline": head, "outlet": r["outlet_name"], "tone": float(r["tone"]),
                        "mentions_inflation": ("rate" in head.lower() or "inflation" in head.lower())})
        return out

    def _metrics_snapshot(self, tick: int) -> dict:
        names = [
            "cpi", "cpi_yoy", "inflation_30d", "unemployment", "index",
            "index_change_10", "gdp_proxy", "gdp_proxy_30d", "labor_income",
            "money_supply", "gini", "sentiment", "policy_rate",
        ]
        if self.engine_semantics_version < 3:
            return {n: self.store.metric_latest(n, 0.0) for n in names}
        out = {}
        for name in names:
            value = self.store.metric_latest(name, None)
            if value is not None:
                out[name] = value
        out["inflation_signal"] = self.inflation_signal()
        return out

    def inflation_signal(self) -> float:
        """Bounded annual policy signal without pretending short runs are YoY."""
        target = float(
            self.config.get("central_bank", {}).get("target_inflation", 0.02))
        if self.engine_semantics_version < 3:
            return self.store.metric_latest("cpi_yoy", target)
        year_over_year = self.store.metric_latest("cpi_yoy", None)
        if year_over_year is not None:
            return max(-0.5, min(0.5, year_over_year))
        change_30d = self.store.metric_latest("inflation_30d", None)
        if change_30d is not None:
            return max(-0.5, min(0.5, 12.0 * change_30d))
        return target

    # ── founder firm view ────────────────────────────────────────────────────
    def _firm_view(self, firm, tick: int) -> dict:
        firm_id = int(firm["id"])
        prod = load_json(firm["product_json"], {}) or {}
        employee_summary = self.store.query(
            "SELECT COALESCE(SUM(wage_cents),0) AS pay, COUNT(*) AS n FROM employments "
            "WHERE firm_id=? AND status='active'", (firm_id,))[0]
        employee_roster = [{
            "employment_id": int(row["employment_id"]),
            "agent_id": int(row["agent_id"]), "occupation": row["occupation"],
            "wage": int(row["wage_cents"]),
        } for row in self.store.query(
            "SELECT e.id AS employment_id,e.agent_id,e.wage_cents,a.occupation "
            "FROM employments e JOIN agents a ON a.id=e.agent_id "
            "WHERE e.firm_id=? AND e.status='active' ORDER BY e.id", (firm_id,))]
        sales = int(self.store.scalar(
            "SELECT COUNT(*) FROM events WHERE kind='goods_sale' AND tick>=? "
            "AND json_extract(payload_json,'$.firm_id')=?", (tick - 3, firm_id), default=0))
        pending_loan = self.store.query_one(
            "SELECT 1 FROM loan_applications WHERE borrower_type='firm' AND borrower_id=? AND status='pending'",
            (firm_id,))
        pending_pitch = self.store.query_one(
            "SELECT 1 FROM pitches WHERE firm_id=? AND status='pending'", (firm_id,))
        view = {
            "firm_id": firm_id, "name": firm["name"], "sector": firm["sector"],
            "inventory": int(firm["inventory"]),
            "price": int(prod.get("unit_price_cents", 500)),
            "unit_cost": int(prod.get("base_input_cost_cents", 180) * self.e.firms.commodity_index()),
            "cash": self.e.ledger.balance(int(firm["account_id"])),
            "employees": int(employee_summary["n"]),
            "employee_roster": employee_roster,
            "payroll": int(employee_summary["pay"]),
            "recent_sales": sales, "target_headcount": int(self.config.get("firms", {}).get("target_headcount", 3)),
            "has_pending_loan": pending_loan is not None,
            "has_pending_pitch": pending_pitch is not None,
            "is_private": firm["status"] == "private",
        }
        if self.engine_semantics_version >= 6:
            qualification = self.e.firms.ipo_qualification(tick, firm_id)
            active_offering = self.store.query_one(
                "SELECT id,shares_offered,reserve_price_cents,minimum_subscription_bps "
                "FROM ipo_offerings WHERE firm_id=? AND status='building'", (firm_id,))
            view["ipo_qualification"] = qualification
            view["active_ipo"] = ({
                "offering_id": int(active_offering["id"]),
                "shares_offered": int(active_offering["shares_offered"]),
                "reserve_price": int(active_offering["reserve_price_cents"]),
                "minimum_subscription_bps": int(active_offering["minimum_subscription_bps"]),
                "book_demand": int(self.store.scalar(
                    "SELECT COALESCE(SUM(qty),0) FROM ipo_bids "
                    "WHERE offering_id=? AND status='open'", (int(active_offering["id"]),),
                    default=0)),
            } if active_offering else None)
        return view

    def _firm_applications(self, firm_id: int) -> list[dict]:
        if self.engine_semantics_version >= 6:
            rows = self.store.query(
                "SELECT ap.id AS application_id,ap.agent_id,ap.job_id,ap.state,"
                "a.occupation,a.age,j.wage_cents AS posted_wage,jo.id AS current_offer_id,"
                "jo.proposer_agent_id,jo.wage_cents AS current_offer_wage "
                "FROM applications ap JOIN jobs j ON j.id=ap.job_id "
                "JOIN agents a ON a.id=ap.agent_id "
                "LEFT JOIN job_offers jo ON jo.application_id=ap.id AND jo.status='pending' "
                "WHERE j.firm_id=? AND ap.state IN ('pending','negotiating') ORDER BY ap.id",
                (firm_id,))
            return [{
                "application_id": int(r["application_id"]), "agent_id": int(r["agent_id"]),
                "job_id": int(r["job_id"]), "occupation": r["occupation"],
                "age": int(r["age"]), "state": r["state"],
                "posted_wage": int(r["posted_wage"]),
                "current_offer_id": (int(r["current_offer_id"])
                                     if r["current_offer_id"] is not None else None),
                "current_offer_wage": (int(r["current_offer_wage"])
                                       if r["current_offer_wage"] is not None else None),
                "current_proposer_agent_id": (int(r["proposer_agent_id"])
                                               if r["proposer_agent_id"] is not None else None),
            } for r in rows]
        rows = self.store.query(
            "SELECT ap.id AS application_id, ap.agent_id AS agent_id, ap.job_id AS job_id, "
            "a.occupation AS occupation, a.age AS age FROM applications ap "
            "JOIN jobs j ON j.id=ap.job_id JOIN agents a ON a.id=ap.agent_id "
            "WHERE j.firm_id=? AND ap.state='pending' ORDER BY ap.id",
            (firm_id,))
        return [{"application_id": int(r["application_id"]),
                 "agent_id": int(r["agent_id"]), "job_id": int(r["job_id"]),
                 "occupation": r["occupation"], "age": int(r["age"])}
                for r in rows]

    def _firm_job_offers(self, firm_id: int) -> list[dict]:
        rows = self.store.query(
            "SELECT jo.id AS offer_id,jo.application_id,jo.proposer_agent_id,"
            "jo.wage_cents,ap.agent_id,ap.job_id,j.title,j.wage_cents AS posted_wage "
            "FROM job_offers jo JOIN applications ap ON ap.id=jo.application_id "
            "JOIN jobs j ON j.id=ap.job_id WHERE j.firm_id=? "
            "AND jo.status='pending' AND ap.state='negotiating' "
            "AND jo.proposer_agent_id=ap.agent_id ORDER BY jo.id", (firm_id,))
        return [{
            "offer_id": int(row["offer_id"]),
            "application_id": int(row["application_id"]),
            "candidate_agent_id": int(row["agent_id"]),
            "job_id": int(row["job_id"]), "title": row["title"],
            "posted_wage": int(row["posted_wage"]),
            "requested_wage": int(row["wage_cents"]),
            "proposer_agent_id": int(row["proposer_agent_id"]),
        } for row in rows]

    # ── institutional contexts ───────────────────────────────────────────────
    def _credit_officer_context(self, a, tick: int) -> dict:
        bank_id = int(a["employer_id"]) if a["employer_id"] else self._officer_bank(int(a["id"]))
        if bank_id:
            apps = self.store.query(
                "SELECT * FROM loan_applications WHERE status='pending' AND bank_id=? ORDER BY id",
                (bank_id,))
        else:
            apps = self.store.query(
                "SELECT * FROM loan_applications WHERE status='pending' ORDER BY id")
        pending = []
        for ap in apps:
            income, net_worth = self._borrower_financials(ap["borrower_type"], int(ap["borrower_id"]))
            pending.append({"id": int(ap["id"]), "amount_cents": int(ap["amount_cents"]),
                            "purpose": ap["purpose"], "borrower_income_cents": income,
                            "borrower_net_worth_cents": net_worth})
        return {"tick": tick, "purpose": "credit_officer", "rng_seed": _seed(int(a["id"]), tick),
                "agent": {"id": int(a["id"]), "name": a["name"], "role": "credit_officer"},
                "policy_rate_bps": self.e.policy_rate_bps(), "pending_loan_apps": pending,
                "banks": self._bank_views("public_status", own_bank_id=bank_id)}

    def _officer_bank(self, agent_id: int) -> Optional[int]:
        v = self.store.scalar(
            "SELECT b.id FROM agents a JOIN banks b ON b.id=a.employer_id "
            "WHERE a.id=? AND a.role='credit_officer' AND b.status='open'",
            (agent_id,), default=None)
        if v is None:
            # Legacy/custom databases may not retain the institutional employer
            # link. Preserve their historical first-open-bank behavior.
            v = self.store.scalar(
                "SELECT id FROM banks WHERE status='open' ORDER BY id LIMIT 1")
        return int(v) if v is not None else None

    def _borrower_financials(self, borrower_type: str, borrower_id: int) -> tuple[int, int]:
        if borrower_type == "agent":
            a = self.store.query_one("SELECT * FROM agents WHERE id=?", (borrower_id,))
            income = 0
            emp = self.store.query_one(
                "SELECT wage_cents, pay_interval_ticks FROM employments WHERE agent_id=? AND status='active'",
                (borrower_id,))
            if emp:
                income = int(emp["wage_cents"]) * (365 // max(1, int(emp["pay_interval_ticks"])))
            return income, self.e.ledger.net_worth_agent(borrower_id)
        firm = self.store.query_one("SELECT account_id FROM firms WHERE id=?", (borrower_id,))
        cash = self.e.ledger.balance(int(firm["account_id"])) if firm else 0
        # Income for underwriting = recent revenue annualised (a broke-but-selling
        # firm can still borrow), floored at cash so idle-rich firms qualify too.
        tick = self.store.tick
        revenue_30 = int(self.store.scalar(
            "SELECT COALESCE(SUM(json_extract(payload_json,'$.total_cents')),0) FROM events "
            "WHERE kind='goods_sale' AND tick>? AND json_extract(payload_json,'$.firm_id')=?",
            (tick - 30, borrower_id), default=0))
        income = max(revenue_30 * 12, cash)
        return income, cash

    def _vc_partner_context(self, a, tick: int) -> dict:
        agent_id = int(a["id"])
        acct = self.e.ledger.agent_checking_id(agent_id)
        fund_cash = self.e.ledger.balance(acct) if acct else 0
        fund_currency = self.store.scalar(
            "SELECT currency_code FROM accounts WHERE id=?", (acct,), default="USD")
        pending = []
        for p in self.store.query(
                "SELECT p.*, f.name AS firm_name, f.sector AS sector, f.account_id AS firm_acct, "
                "f.founded_tick AS founded_tick, fa.currency_code AS firm_currency "
                "FROM pitches p JOIN firms f ON f.id=p.firm_id "
                "JOIN accounts fa ON fa.id=f.account_id "
                "WHERE p.status='pending' AND fa.currency_code=? ORDER BY p.id",
                (fund_currency,)):
            firm_id = int(p["firm_id"])
            revenue_30 = int(self.store.scalar(
                "SELECT COALESCE(SUM(json_extract(payload_json,'$.total_cents')),0) FROM events "
                "WHERE kind='goods_sale' AND tick>? AND json_extract(payload_json,'$.firm_id')=?",
                (tick - 30, firm_id), default=0))
            employees = int(self.store.scalar(
                "SELECT COUNT(*) FROM employments WHERE firm_id=? AND status='active'",
                (firm_id,), default=0))
            pending.append({
                "pitch_id": int(p["id"]), "firm_id": firm_id, "firm_name": p["firm_name"],
                "sector": p["sector"], "ask_cents": int(p["ask_cents"]),
                "summary": p["summary"], "follow_on": bool(p["follow_on"]),
                "currency": p["firm_currency"],
                "firm_cash": self.e.ledger.balance(int(p["firm_acct"])) if p["firm_acct"] else 0,
                "revenue_30": revenue_30, "employees": employees,
                "firm_age_ticks": tick - int(p["founded_tick"] or 0)})
        return {"tick": tick, "purpose": "vc_partner", "rng_seed": _seed(agent_id, tick),
                "agent": {"id": agent_id, "name": a["name"], "role": "vc_partner"},
                "fund_cash": fund_cash, "fund_currency": fund_currency,
                "pending_pitches": pending,
                "portfolio": self.e.vc.portfolio(agent_id),
                "metrics": self._metrics_snapshot(tick)}

    def _lawyer_context(self, a, tick: int) -> dict:
        agent_id = int(a["id"])
        ctx = self._citizen_context(a, tick)
        matters = []
        for matter in self.store.query(
                "SELECT * FROM legal_matters WHERE counsel_agent_id=? "
                "AND status NOT IN ('decided','dismissed','settled') ORDER BY id",
                (agent_id,)):
            matter_id = int(matter["id"])
            contract_id = int(matter["contract_id"] or 0)
            evidence = []
            for event in self.store.query(
                    "SELECT id,tick,kind,payload_json FROM events WHERE "
                    "(subject_type='legal_matter' AND subject_id=?) OR "
                    "(subject_type='contract' AND subject_id=?) ORDER BY id",
                    (matter_id, contract_id)):
                evidence.append({
                    "event_id": int(event["id"]), "tick": int(event["tick"]),
                    "kind": event["kind"],
                    "facts": load_json(event["payload_json"], {}) or {},
                })
            filings = [{
                "filing_id": int(filing["id"]),
                "filing_type": filing["filing_type"],
                "admitted": bool(filing["admitted"]),
                "evidence_event_ids": load_json(filing["evidence_event_ids_json"], []) or [],
            } for filing in self.store.query(
                "SELECT id,filing_type,admitted,evidence_event_ids_json FROM legal_filings "
                "WHERE matter_id=? ORDER BY id", (matter_id,))]
            matters.append({
                "matter_id": matter_id,
                "status": matter["status"],
                "matter_type": matter["matter_type"],
                "claim_type": matter["claim_type"],
                "contract_id": contract_id or None,
                "claimant": {"type": matter["claimant_type"], "id": int(matter["claimant_id"])},
                "respondent": {"type": matter["respondent_type"], "id": int(matter["respondent_id"])},
                "response_due_tick": int(matter["response_due_tick"]),
                "requested_remedy": load_json(matter["requested_remedy_json"], {}) or {},
                "settlement": load_json(matter["settlement_json"], {}) or {},
                "evidence_events": evidence[-12:],
                "filings": filings,
            })
        ctx["purpose"] = "lawyer"
        ctx["assigned_legal_matters"] = matters
        return ctx

    def _central_banker_context(self, a, tick: int) -> dict:
        cb = self.config.get("central_bank", {})
        m = self._metrics_snapshot(tick)
        return {"tick": tick, "purpose": "central_banker", "rng_seed": _seed(int(a["id"]), tick),
                "agent": {"id": int(a["id"]), "name": a["name"], "role": "central_banker"},
                "policy_rate_bps": self.e.policy_rate_bps(), "metrics": m,
                "banks": self._bank_views("full_balance_sheet"),
                "liquidity_support_requests": (
                    self.e.bank.pending_liquidity_requests(limit=8)
                    if self.engine_semantics_version >= 6 else []),
                "neutral_rate_bps": int(cb.get("neutral_rate_bps", 500)),
                "target_inflation": float(cb.get("target_inflation", 0.02)),
                "natural_unemployment": float(cb.get("natural_unemployment", 0.05))}

    # ── render LLM messages from a context ───────────────────────────────────
    def render_prompt(self, context: dict) -> tuple[str, str]:
        a = context.get("agent", {})
        s = context.get("state", {})
        lines = [f"[PERSONA] agent_id {a.get('id')}, {a.get('name')}, "
                 f"age {a.get('age')}, {a.get('occupation')}, "
                 f"risk_tolerance {a.get('risk_tolerance')}, health {a.get('health')}."]
        if s:
            if "currency_code" in s:
                lines.append(f"[STATE] cash {s.get('checking_balance',0)}c at bank {s.get('bank_id')}, "
                             f"currency {s.get('currency_code','USD')}, debt {s.get('debt',0)}c, "
                             f"employed={s.get('employed')}, "
                             f"net_worth {s.get('net_worth',0)}c, shares {s.get('shares',{})}.")
            else:
                lines.append(f"[STATE] cash {s.get('checking_balance',0)}c at bank {s.get('bank_id')}, "
                             f"debt {s.get('debt',0)}c, employed={s.get('employed')}, "
                             f"net_worth {s.get('net_worth',0)}c, shares {s.get('shares',{})}.")
        beliefs = context.get("beliefs", {})
        if beliefs:
            lines.append("[BELIEFS] " + ", ".join(f"{k}={v}" for k, v in list(beliefs.items())[:8]))
        mems = context.get("memories", [])
        if mems:
            lines.append("[MEMORIES]\n- " + "\n- ".join(mems[:6]))
        news = context.get("news", [])
        if news:
            lines.append("[TODAY — NEWS]\n- " + "\n- ".join(n["headline"] for n in news[:5]))
        heard = context.get("heard", [])
        if heard:
            lines.append("[HEARD]\n- " + "\n- ".join(h["text"] for h in heard[:5]))
        metrics = context.get("metrics", {})
        if metrics:
            lines.append("[MACRO — MOST RECENT COMPLETED DAY] "
                         + json.dumps(metrics, separators=(",", ":")))
        banks = context.get("banks", [])
        if banks:
            lines.append("[BANKS — COPY id AS bank_id/to_bank_id] "
                         + json.dumps(banks, separators=(",", ":")))
        prices = context.get("prices", [])
        if prices:
            lines.append("[GOODS — inventory IS CURRENT STOCK; COPY firm_id; "
                         "NEVER REQUEST qty ABOVE inventory] "
                         + json.dumps(prices[:16], separators=(",", ":")))
        jobs = context.get("jobs", [])
        if jobs:
            lines.append("[JOBS — COPY job_id AS AN INTEGER] "
                         + json.dumps(jobs[:6], separators=(",", ":")))
        if context.get("incoming_job_offers"):
            lines.append("[WAGE OFFERS TO YOU — COPY offer_id; ACCEPT, COUNTER, OR REJECT] "
                         + json.dumps(context["incoming_job_offers"][:8],
                                      separators=(",", ":")))
        if context.get("ipo_offerings"):
            lines.append("[OPEN IPO BOOKS — COPY offering_id; reserve_price IS ISSUER-SET] "
                         + json.dumps(context["ipo_offerings"][:10],
                                      separators=(",", ":")))
        listed = context.get("listed_firms", [])
        if listed:
            lines.append("[LISTED FIRMS — COPY firm_id; last_price IS HISTORICAL; "
                         "VALUE YOUR limit_price FROM FUNDAMENTALS] "
                         + json.dumps(listed[:12], separators=(",", ":")))
        if context.get("portfolio_day"):
            lines.append("[PORTFOLIO REVIEW DUE] If you hold listed shares, consider a "
                         "sell limit; if you have cash, consider a buy limit. Choose your "
                         "own valuation from fundamentals, or deliberately do nothing.")
        if context.get("career_day"):
            lines.append("[CAREER REVIEW DUE] Reassess employment and the available jobs; "
                         "apply with a supplied job_id or deliberately stay put.")
        if context.get("my_firm"):
            f = context["my_firm"]
            lines.append("[YOUR FIRM — COPY firm_id] "
                         + json.dumps(f, separators=(",", ":")))
        if context.get("firm_applications"):
            target = "make_job_offer" if getattr(self, "engine_semantics_version", 2) >= 6 else "hire"
            lines.append(f"[APPLICANTS — COPY application_id TO {target}] "
                         + json.dumps(context["firm_applications"][:20],
                                      separators=(",", ":")))
        if context.get("firm_job_offers"):
            lines.append("[CANDIDATE COUNTEROFFERS — COPY offer_id; ACCEPT, COUNTER, OR REJECT] "
                         + json.dumps(context["firm_job_offers"][:10],
                                      separators=(",", ":")))
        if context.get("pending_loan_apps"):
            lines.append("[LOAN APPLICATIONS — COPY id AS application_id] "
                         + json.dumps(context["pending_loan_apps"], separators=(",", ":")))
        if context.get("pending_pitches"):
            lines.append(f"[FUND] cash {context.get('fund_cash',0)}c · "
                         f"portfolio {json.dumps(context.get('portfolio', []))[:400]}")
            lines.append("[PITCHES] " + json.dumps(context["pending_pitches"])[:1200] +
                         "\nRespond with fund_pitch{pitch_id,amount,equity_bps} or "
                         "decline_pitch{pitch_id,reason} per pitch.")
        if context.get("assigned_legal_matters"):
            lines.append("[ASSIGNED LEGAL MATTERS — COPY matter_id, contract_id, party IDs, "
                         "AND evidence event_id VALUES EXACTLY] "
                         + json.dumps(context["assigned_legal_matters"], separators=(",", ":"))[:4000])
        if context.get("institutional_work"):
            lines.append(
                "[INSTITUTIONAL WORK — ONLY eligible_actions MAY BE USED; COPY EVERY "
                "FIELD, ID, AND VALUE EXACTLY] "
                + json.dumps(context["institutional_work"], separators=(",", ":"))[:6000])
        if context.get("insurance_offer") and not context.get("insured"):
            o = context["insurance_offer"]
            lines.append(f"[INSURANCE] {o['insurer']} offers health coverage: "
                         f"{o['premium']}c per {o['interval_ticks']} ticks, covers "
                         f"{o['coverage_bps']/100:.0f}% of medical bills (buy_insurance).")
        purpose = context.get("purpose", "decision")
        if purpose == "central_banker":
            lines.append("[CENTRAL BANK] current_rate_bps="
                         f"{context.get('policy_rate_bps')} neutral_rate_bps="
                         f"{context.get('neutral_rate_bps')} target_inflation="
                         f"{context.get('target_inflation')} natural_unemployment="
                         f"{context.get('natural_unemployment')}")
            requests = context.get("liquidity_support_requests", [])
            if requests:
                lines.append(
                    "[LENDER OF LAST RESORT — RESOLVE EVERY REQUEST; COPY request_event_id "
                    "AND CITE IT AS THE ONLY evidence_event_ids VALUE] "
                    + json.dumps(requests, separators=(",", ":"))[:5000])
                lines.append(
                    "[TASK] Act as a prudent central-bank governor. For every pending request "
                    "use decide_liquidity_support{request_event_id,decision,evidence_event_ids} "
                    "with decision='approve' or 'deny' and evidence_event_ids=[request_event_id]. "
                    "Weigh recorded solvency and systemic liquidity; do not invent an amount. "
                    "You may also use set_policy_rate{rate_bps} if the macro data warrants it.")
            else:
                lines.append("[TASK] Assess the macro data and use set_policy_rate{rate_bps} "
                             "only if a change is warranted; otherwise do_nothing.")
        elif purpose == "credit_officer":
            lines.append("[TASK] Underwrite every pending application from its real income, "
                         "net worth, requested amount, bank risk, and policy rate. Use "
                         "approve_loan{application_id,rate_bps,term_ticks} or "
                         "deny_loan{application_id,reason}; otherwise do_nothing.")
        elif purpose == "founder":
            lines.append("[TASK] Manage your firm from cash, unit cost, inventory, recent "
                         "sales, payroll, employee_roster, target headcount, and applicants. "
                         "Consider pricing, "
                         "hiring, funding, an IPO when qualified, or a deliberate do_nothing; "
                         "copy every supplied ID. "
                         "Normally change price by at most 10% per review and avoid pricing "
                         "below unit cost unless you are deliberately liquidating inventory.")
        elif purpose == "vc_partner":
            lines.append("[TASK] Evaluate pending pitches or deliberately do_nothing. "
                         "Reply with the JSON envelope only.")
        elif purpose == "lawyer":
            lines.append("[TASK] Act only for an assigned matter and only from its bounded record. "
                         "If a breach evidence event is supplied and not yet filed, use "
                         "submit_filing with filing_type='evidence', filer_type='agent', your "
                         "integer agent id as filer_id, and supplied event_id values. If the "
                         "record is already in hearing, you may propose a settlement no larger "
                         "than the requested remedy. If an assigned matter has no supported "
                         "next step, deliberately do_nothing. Only when there are no assigned "
                         "matters may you make an ordinary household decision.")
        elif purpose in INSTITUTIONAL_DECISION_ROLES:
            lines.append(
                "[TASK] Perform at most one supplied institutional_work.eligible_actions "
                "object, copying it exactly. If the list is empty or you prefer not to act, "
                "use do_nothing. Never invent an institutional ID, target, amount, vote, "
                "remedy, policy field, currency pair, or alternative action.")
        else:
            lines.append("[TASK] Decide what you do today from the available goods, jobs, "
                         "banks, and—when due—listed securities. Reply with the JSON envelope only.")
        system = SYSTEM_PREFIX
        if context.get("institutional_work"):
            system += INSTITUTIONAL_ACTIONS_SUFFIX
        if getattr(self, "engine_semantics_version", 2) >= 6:
            system += LABOR_IPO_ACTIONS_SUFFIX
        return system, "\n\n".join(lines)

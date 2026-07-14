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
fund_pitch{pitch_id,amount,equity_bps}, decline_pitch{pitch_id,reason}.
Legal role actions: submit_filing{matter_id,filer_type,filer_id,filing_type,
evidence_event_ids,body}, propose_settlement{matter_id,terms:{remedy:{type,
amount_cents}}}.
Every field ending in _id, plus to_account, MUST be a JSON integer copied exactly from the
provided context. Never emit labels such as "firm7", "job2", names, titles, or composite strings
where an integer ID is required.
You are never obligated to act. Money is in cents. Stay in character."""


def _seed(agent_id: int, tick: int, salt: str = "") -> int:
    return int(hashlib.sha1(f"{agent_id}:{tick}:{salt}".encode()).hexdigest()[:12], 16)


class ContextBuilder:
    def __init__(self, economy: Economy, memory: Memory, config: dict):
        self.e = economy
        self.store = economy.store
        self.mem = memory
        self.config = config
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
            ctx["purpose"] = "founder"
        return ctx

    def purpose_for(self, agent_row) -> str:
        role = agent_row["role"]
        if role in ("central_banker", "credit_officer", "vc_partner", "lawyer"):
            return role
        if self.store.query_one("SELECT 1 FROM firms WHERE founder_agent_id=? AND status<>'bankrupt'",
                                (agent_row["id"],)):
            return "founder"
        return "decision"

    # ── citizen ──────────────────────────────────────────────────────────────
    def _citizen_context(self, a, tick: int) -> dict:
        agent_id = int(a["id"])
        checking = self.store.query_one(
            "SELECT * FROM accounts WHERE owner_type='agent' AND owner_id=? AND kind='checking' "
            "ORDER BY balance_cents DESC LIMIT 1", (agent_id,))
        cash = int(checking["balance_cents"]) if checking else 0
        bank_id = int(checking["bank_id"]) if checking and checking["bank_id"] is not None else None
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
        return {
            "tick": tick,
            "purpose": "decision",
            "rng_seed": _seed(agent_id, tick),
            "run_threshold": float(self.config.get("behavior", {}).get("run_threshold", 0.35)),
            "insured": insured,
            "insurance_offer": self._insurance_offer(),
            "agent": {"id": agent_id, "name": a["name"], "age": int(a["age"]),
                      "occupation": a["occupation"], "role": a["role"], "health": a["health"],
                      "retired": bool(a["retired"]), "dependents": int(a["dependents"]),
                      "risk_tolerance": float(a["risk_tolerance"] or 0.5),
                      "political_lean": float(a["political_lean"] or 0.0)},
            "state": {"checking_balance": cash, "bank_id": bank_id, "debt": debt,
                      "employed": emp is not None, "wage": int(emp["wage_cents"]) if emp else 0,
                      "net_worth": self.e.ledger.net_worth_agent(agent_id), "shares": shares},
            "beliefs": beliefs,
            "prices": self._goods_offers(),
            "jobs": self._open_jobs(),
            "listed_firms": self._listed_firms(tick),
            "banks": self._bank_views(self.citizen_bank_visibility),
            "news": self._news_for(a, tick),
            "heard": heard,
            "memories": [m["text"] for m in memories],
            "policy_rate_bps": self.e.policy_rate_bps(),
            "metrics": self._metrics_snapshot(tick),
            "portfolio_day": portfolio_day,
            "career_day": career_day,
        }

    def _insurance_offer(self) -> Optional[dict]:
        insurer = self.store.query_one(
            "SELECT id, name FROM firms WHERE sector='insurance' AND status<>'bankrupt' "
            "ORDER BY id LIMIT 1")
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

    def _goods_offers(self) -> list[dict]:
        inventory_clause = "inventory>0" if self.engine_semantics_version >= 2 else "inventory>=0"
        firms = self.store.query(
            "SELECT id, product_json, inventory FROM firms "
            f"WHERE status IN ('private','listed') AND {inventory_clause} "
            "ORDER BY inventory DESC, id")
        out = []
        for f in firms:
            prod = load_json(f["product_json"], {}) or {}
            out.append({"firm_id": int(f["id"]), "product": prod.get("product", "goods"),
                        "price": int(prod.get("unit_price_cents", 500)),
                        "inventory": int(f["inventory"])})
        return out

    def _open_jobs(self) -> list[dict]:
        return [{"job_id": int(j["id"]), "firm_id": int(j["firm_id"]), "title": j["title"],
                 "wage": int(j["wage_cents"])}
                for j in self.store.query("SELECT * FROM jobs WHERE status='open' ORDER BY wage_cents DESC LIMIT 20")]

    def _listed_firms(self, tick: int) -> list[dict]:
        out = []
        for f in self.store.query(
                "SELECT id,name,account_id,inventory,product_json FROM firms "
                "WHERE status='listed' ORDER BY id"):
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
            out.append({
                "firm_id": firm_id, "name": f["name"],
                "last_price": self.e.exchange.last_price(firm_id),
                "book_value_per_share": round(cash / shares) if shares else None,
                "cash": cash, "inventory": int(f["inventory"]),
                "goods_price": int(product.get("unit_price_cents", 500)),
                "recent_revenue_7": revenue_7,
            })
        return out

    def _bank_views(
        self,
        visibility: str = "full_balance_sheet",
        *,
        own_bank_id: Optional[int] = None,
    ) -> list[dict]:
        out = []
        for b in self.store.query("SELECT * FROM banks"):
            bank_id = int(b["id"])
            view = {"id": bank_id, "name": b["name"], "status": b["status"]}
            if visibility == "full_balance_sheet" or bank_id == own_bank_id:
                view["reserve_ratio"] = round(self.e.bank.reserve_ratio(bank_id), 4)
            out.append(view)
        return out

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
        return {
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

    def _firm_applications(self, firm_id: int) -> list[dict]:
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
            lines.append("[APPLICANTS — COPY application_id TO hire] "
                         + json.dumps(context["firm_applications"][:20],
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
                         "hiring, funding, or a deliberate do_nothing; copy every supplied ID. "
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
        else:
            lines.append("[TASK] Decide what you do today from the available goods, jobs, "
                         "banks, and—when due—listed securities. Reply with the JSON envelope only.")
        return SYSTEM_PREFIX, "\n\n".join(lines)

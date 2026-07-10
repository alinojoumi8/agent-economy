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
cancel_insurance{}, say_public{text}, do_nothing.
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

    # ── public: assemble per-role context ────────────────────────────────────
    def build(self, agent_row, tick: int) -> dict:
        role = agent_row["role"]
        if role == "central_banker":
            return self._central_banker_context(agent_row, tick)
        if role == "credit_officer":
            return self._credit_officer_context(agent_row, tick)
        if role == "vc_partner":
            return self._vc_partner_context(agent_row, tick)
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
        if role in ("central_banker", "credit_officer", "vc_partner"):
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
            "listed_firms": self._listed_firms(),
            "banks": self._bank_views(),
            "news": self._news_for(a, tick),
            "heard": heard,
            "memories": [m["text"] for m in memories],
            "policy_rate_bps": self.e.policy_rate_bps(),
            "metrics": self._metrics_snapshot(tick),
            "portfolio_day": portfolio_day,
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
        firms = self.store.query(
            "SELECT id, product_json, inventory FROM firms WHERE status IN ('private','listed') AND inventory>=0")
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

    def _listed_firms(self) -> list[dict]:
        out = []
        for f in self.store.query("SELECT id, name FROM firms WHERE status='listed'"):
            out.append({"firm_id": int(f["id"]), "name": f["name"],
                        "last_price": self.e.exchange.last_price(int(f["id"]))})
        return out

    def _bank_views(self) -> list[dict]:
        out = []
        for b in self.store.query("SELECT * FROM banks"):
            out.append({"id": int(b["id"]), "name": b["name"], "status": b["status"],
                        "reserve_ratio": round(self.e.bank.reserve_ratio(int(b["id"])), 4)})
        return out

    def _news_for(self, a, tick: int) -> list[dict]:
        diet = set(load_json(a["media_diet_json"], []) or [])
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
        names = ["cpi", "cpi_yoy", "unemployment", "index", "index_change_10", "gdp_proxy",
                 "money_supply", "gini", "sentiment", "policy_rate"]
        return {n: self.store.metric_latest(n, 0.0) for n in names}

    # ── founder firm view ────────────────────────────────────────────────────
    def _firm_view(self, firm, tick: int) -> dict:
        firm_id = int(firm["id"])
        prod = load_json(firm["product_json"], {}) or {}
        employees = self.store.query(
            "SELECT COALESCE(SUM(wage_cents),0) AS pay, COUNT(*) AS n FROM employments "
            "WHERE firm_id=? AND status='active'", (firm_id,))[0]
        sales = int(self.store.scalar(
            "SELECT COUNT(*) FROM events WHERE kind='goods_sale' AND tick>=? "
            "AND json_extract(payload_json,'$.firm_id')=?", (tick - 3, firm_id), default=0))
        pending_loan = self.store.query_one(
            "SELECT 1 FROM loan_applications WHERE borrower_type='firm' AND borrower_id=? AND status='pending'",
            (firm_id,))
        pending_pitch = self.store.query_one(
            "SELECT 1 FROM pitches WHERE firm_id=? AND status='pending'", (firm_id,))
        return {
            "firm_id": firm_id, "name": firm["name"],
            "inventory": int(firm["inventory"]),
            "price": int(prod.get("unit_price_cents", 500)),
            "unit_cost": int(prod.get("base_input_cost_cents", 180) * self.e.firms.commodity_index()),
            "cash": self.e.ledger.balance(int(firm["account_id"])),
            "employees": int(employees["n"]), "payroll": int(employees["pay"]),
            "recent_sales": sales, "target_headcount": int(self.config.get("firms", {}).get("target_headcount", 3)),
            "has_pending_loan": pending_loan is not None,
            "has_pending_pitch": pending_pitch is not None,
            "is_private": firm["status"] == "private",
        }

    def _firm_applications(self, firm_id: int) -> list[dict]:
        rows = self.store.query(
            "SELECT ap.id AS application_id, ap.agent_id AS agent_id FROM applications ap "
            "JOIN jobs j ON j.id=ap.job_id WHERE j.firm_id=? AND ap.state='pending' ORDER BY ap.id",
            (firm_id,))
        return [{"application_id": int(r["application_id"]), "agent_id": int(r["agent_id"])} for r in rows]

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
                "banks": self._bank_views()}

    def _officer_bank(self, agent_id: int) -> Optional[int]:
        v = self.store.scalar("SELECT id FROM banks WHERE status='open' ORDER BY id LIMIT 1")
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
        pending = []
        for p in self.store.query(
                "SELECT p.*, f.name AS firm_name, f.sector AS sector, f.account_id AS firm_acct, "
                "f.founded_tick AS founded_tick FROM pitches p JOIN firms f ON f.id=p.firm_id "
                "WHERE p.status='pending' ORDER BY p.id"):
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
                "firm_cash": self.e.ledger.balance(int(p["firm_acct"])) if p["firm_acct"] else 0,
                "revenue_30": revenue_30, "employees": employees,
                "firm_age_ticks": tick - int(p["founded_tick"] or 0)})
        return {"tick": tick, "purpose": "vc_partner", "rng_seed": _seed(agent_id, tick),
                "agent": {"id": agent_id, "name": a["name"], "role": "vc_partner"},
                "fund_cash": fund_cash, "pending_pitches": pending,
                "portfolio": self.e.vc.portfolio(agent_id),
                "metrics": self._metrics_snapshot(tick)}

    def _central_banker_context(self, a, tick: int) -> dict:
        cb = self.config.get("central_bank", {})
        m = self._metrics_snapshot(tick)
        return {"tick": tick, "purpose": "central_banker", "rng_seed": _seed(int(a["id"]), tick),
                "agent": {"id": int(a["id"]), "name": a["name"], "role": "central_banker"},
                "policy_rate_bps": self.e.policy_rate_bps(), "metrics": m,
                "neutral_rate_bps": int(cb.get("neutral_rate_bps", 500)),
                "target_inflation": float(cb.get("target_inflation", 0.02)),
                "natural_unemployment": float(cb.get("natural_unemployment", 0.05))}

    # ── render LLM messages from a context ───────────────────────────────────
    def render_prompt(self, context: dict) -> tuple[str, str]:
        a = context.get("agent", {})
        s = context.get("state", {})
        lines = [f"[PERSONA] {a.get('name')}, age {a.get('age')}, {a.get('occupation')}, "
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
        prices = context.get("prices", [])
        if prices:
            lines.append("[PRICES — COPY firm_id AS AN INTEGER] "
                         + json.dumps(prices[:8], separators=(",", ":")))
        jobs = context.get("jobs", [])
        if jobs:
            lines.append("[JOBS — COPY job_id AS AN INTEGER] "
                         + json.dumps(jobs[:6], separators=(",", ":")))
        if context.get("my_firm"):
            f = context["my_firm"]
            lines.append(f"[YOUR FIRM] {f['name']} cash {f['cash']}c inv {f['inventory']} "
                         f"price {f['price']}c employees {f['employees']}")
        if context.get("pending_loan_apps"):
            lines.append("[LOAN APPLICATIONS] " + json.dumps(context["pending_loan_apps"]))
        if context.get("pending_pitches"):
            lines.append(f"[FUND] cash {context.get('fund_cash',0)}c · "
                         f"portfolio {json.dumps(context.get('portfolio', []))[:400]}")
            lines.append("[PITCHES] " + json.dumps(context["pending_pitches"])[:1200] +
                         "\nRespond with fund_pitch{pitch_id,amount,equity_bps} or "
                         "decline_pitch{pitch_id,reason} per pitch.")
        if context.get("insurance_offer") and not context.get("insured"):
            o = context["insurance_offer"]
            lines.append(f"[INSURANCE] {o['insurer']} offers health coverage: "
                         f"{o['premium']}c per {o['interval_ticks']} ticks, covers "
                         f"{o['coverage_bps']/100:.0f}% of medical bills (buy_insurance).")
        lines.append("[TASK] Decide what you do today. Reply with the JSON envelope only.")
        return SYSTEM_PREFIX, "\n\n".join(lines)

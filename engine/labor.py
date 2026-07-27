"""Labour market: postings, applications, hiring, firing, employment records.

Firms post jobs with wages; agents apply; the firm side decides who to hire (an
LLM decision for founder-run firms). Employment writes payroll obligations the
engine then enforces (PRD R3, TECH-SPEC §9).
"""
from __future__ import annotations

from typing import Optional

from .store import Store

DEFAULT_PAY_INTERVAL = 30  # ticks (~monthly)


class Labor:
    def __init__(self, store: Store, *, engine_semantics_version: int = 2):
        self.store = store
        self.engine_semantics_version = int(engine_semantics_version)

    def _agent_can_work(self, agent_id: int) -> bool:
        if self.engine_semantics_version < 7:
            return True
        actor = self.store.query_one(
            "SELECT alive,retired FROM agents WHERE id=?", (agent_id,))
        return bool(actor and actor["alive"] and not actor["retired"])

    def post_job(self, tick: int, firm_id: int, title: str, wage_cents: int) -> int:
        job_id = self.store.insert("jobs", tick=tick, firm_id=firm_id, title=title,
                                   wage_cents=max(0, int(wage_cents)), status="open")
        self.store.log_event(tick, "job_posted", {
            "job_id": job_id, "firm_id": firm_id, "title": title, "wage_cents": wage_cents},
            phase="EXECUTION")
        return job_id

    def apply_job(self, tick: int, agent_id: int, job_id: int) -> Optional[int]:
        if not self._agent_can_work(agent_id):
            return None
        job = self.store.query_one("SELECT * FROM jobs WHERE id=?", (job_id,))
        if not job or job["status"] != "open":
            return None
        dup = self.store.query_one(
            "SELECT id FROM applications WHERE job_id=? AND agent_id=? "
            "AND state IN ('pending','negotiating')",
            (job_id, agent_id))
        if dup:
            return int(dup["id"])
        app_id = self.store.insert("applications", tick=tick, job_id=job_id, agent_id=agent_id,
                                   state="pending")
        self.store.log_event(tick, "job_application", {
            "application_id": app_id, "job_id": job_id, "agent_id": agent_id}, phase="EXECUTION")
        return app_id

    def make_offer(self, tick: int, application_id: int, proposer_agent_id: int,
                   wage_cents: int, parent_offer_id: Optional[int] = None) -> Optional[int]:
        """Persist one side's wage proposal without mutating employment.

        The caller is responsible for actor/firm authorization.  This method
        enforces the replay-critical state transition: exactly one pending
        offer may exist for an application and every counter links to the offer
        it superseded.
        """
        app = self.store.query_one("SELECT * FROM applications WHERE id=?", (application_id,))
        if not app or app["state"] not in ("pending", "negotiating"):
            return None
        if not self._agent_can_work(int(app["agent_id"])):
            return None
        job = self.store.query_one("SELECT * FROM jobs WHERE id=?", (app["job_id"],))
        if not job or job["status"] != "open" or int(wage_cents) < 0:
            return None
        pending = self.store.query_one(
            "SELECT * FROM job_offers WHERE application_id=? AND status='pending'",
            (application_id,))
        if parent_offer_id is None:
            if pending is not None:
                return None
        else:
            if not pending or int(pending["id"]) != int(parent_offer_id):
                return None
            self.store.update("job_offers", int(parent_offer_id), status="superseded",
                              decided_tick=tick)
        offer_id = self.store.insert(
            "job_offers", application_id=application_id, tick=tick,
            proposer_agent_id=proposer_agent_id, wage_cents=int(wage_cents),
            parent_offer_id=parent_offer_id, status="pending")
        self.store.update("applications", application_id, state="negotiating")
        self.store.log_event(tick, "job_offer_countered" if parent_offer_id else "job_offer_made", {
            "offer_id": offer_id, "parent_offer_id": parent_offer_id,
            "application_id": application_id, "job_id": int(app["job_id"]),
            "firm_id": int(job["firm_id"]), "candidate_agent_id": int(app["agent_id"]),
            "proposer_agent_id": proposer_agent_id, "wage_cents": int(wage_cents),
        }, phase="EXECUTION", subject_type="job_offer", subject_id=offer_id,
            importance=1.5)
        return offer_id

    def reject_offer(self, tick: int, offer_id: int, rejecting_agent_id: int) -> bool:
        offer = self.store.query_one(
            "SELECT jo.*,ap.job_id,ap.agent_id,j.firm_id FROM job_offers jo "
            "JOIN applications ap ON ap.id=jo.application_id "
            "JOIN jobs j ON j.id=ap.job_id WHERE jo.id=?", (offer_id,))
        if not offer or offer["status"] != "pending":
            return False
        self.store.update("job_offers", offer_id, status="rejected", decided_tick=tick)
        self.store.update("applications", int(offer["application_id"]), state="rejected")
        self.store.log_event(tick, "job_offer_rejected", {
            "offer_id": offer_id, "application_id": int(offer["application_id"]),
            "firm_id": int(offer["firm_id"]), "candidate_agent_id": int(offer["agent_id"]),
            "rejecting_agent_id": rejecting_agent_id,
        }, phase="EXECUTION", subject_type="job_offer", subject_id=offer_id,
            importance=1.2)
        return True

    def hire(self, tick: int, application_id: int, pay_interval: int = DEFAULT_PAY_INTERVAL,
             *, wage_cents: Optional[int] = None, job_offer_id: Optional[int] = None) -> Optional[int]:
        app = self.store.query_one("SELECT * FROM applications WHERE id=?", (application_id,))
        allowed_states = ("pending", "negotiating") if job_offer_id is not None else ("pending",)
        if not app or app["state"] not in allowed_states:
            return None
        if not self._agent_can_work(int(app["agent_id"])):
            return None
        job = self.store.query_one("SELECT * FROM jobs WHERE id=?", (app["job_id"],))
        if not job or job["status"] != "open":
            return None
        agent_id = int(app["agent_id"])
        # One active job per agent: end any prior employment.
        self.store.execute(
            "UPDATE employments SET status='ended', end_tick=? WHERE agent_id=? AND status='active'",
            (tick, agent_id))
        agreed_wage = int(job["wage_cents"]) if wage_cents is None else int(wage_cents)
        if agreed_wage < 0:
            return None
        emp_id = self.store.insert(
            "employments", firm_id=int(job["firm_id"]), agent_id=agent_id, title=job["title"],
            wage_cents=agreed_wage, start_tick=tick, status="active",
            pay_interval_ticks=pay_interval, next_pay_tick=tick + pay_interval)
        self.store.update("applications", application_id, state="hired")
        self.store.update("jobs", int(job["id"]), status="filled")
        self.store.execute("UPDATE agents SET employer_id=? WHERE id=?", (int(job["firm_id"]), agent_id))
        # Reject sibling applications for this job.
        self.store.execute(
            "UPDATE applications SET state='rejected' WHERE job_id=? "
            "AND state IN ('pending','negotiating')",
            (int(job["id"]),))
        if job_offer_id is not None:
            self.store.execute(
                "UPDATE job_offers SET status='rejected', decided_tick=? "
                "WHERE status='pending' AND application_id IN "
                "(SELECT id FROM applications WHERE job_id=?)",
                (tick, int(job["id"])))
        payload = {
            "employment_id": emp_id, "firm_id": int(job["firm_id"]), "agent_id": agent_id,
            "wage_cents": agreed_wage}
        if job_offer_id is not None:
            payload.update({"application_id": application_id, "job_offer_id": job_offer_id,
                            "negotiated": True})
        self.store.log_event(tick, "hired", payload, phase="EXECUTION",
            subject_type="agent", subject_id=agent_id, importance=2.0)
        return emp_id

    def accept_offer(self, tick: int, offer_id: int, accepting_agent_id: int,
                     pay_interval: int = DEFAULT_PAY_INTERVAL) -> Optional[int]:
        offer = self.store.query_one(
            "SELECT jo.*,ap.job_id,ap.agent_id,j.firm_id FROM job_offers jo "
            "JOIN applications ap ON ap.id=jo.application_id "
            "JOIN jobs j ON j.id=ap.job_id WHERE jo.id=?", (offer_id,))
        if not offer or offer["status"] != "pending":
            return None
        emp_id = self.hire(
            tick, int(offer["application_id"]), pay_interval,
            wage_cents=int(offer["wage_cents"]), job_offer_id=offer_id)
        if emp_id is None:
            return None
        self.store.update("job_offers", offer_id, status="accepted", decided_tick=tick)
        self.store.log_event(tick, "job_offer_accepted", {
            "offer_id": offer_id, "application_id": int(offer["application_id"]),
            "employment_id": emp_id, "firm_id": int(offer["firm_id"]),
            "candidate_agent_id": int(offer["agent_id"]),
            "accepting_agent_id": accepting_agent_id,
            "wage_cents": int(offer["wage_cents"]),
        }, phase="EXECUTION", subject_type="job_offer", subject_id=offer_id,
            importance=2.0)
        return emp_id

    def fire(self, tick: int, employment_id: int) -> bool:
        emp = self.store.query_one("SELECT * FROM employments WHERE id=?", (employment_id,))
        if not emp or emp["status"] != "active":
            return False
        self.store.update("employments", employment_id, status="ended", end_tick=tick)
        self.store.execute("UPDATE agents SET employer_id=NULL WHERE id=?", (emp["agent_id"],))
        self.store.log_event(tick, "fired", {
            "employment_id": employment_id, "firm_id": int(emp["firm_id"]),
            "agent_id": int(emp["agent_id"])}, phase="EXECUTION",
            subject_type="agent", subject_id=int(emp["agent_id"]), importance=2.5)
        return True

    def is_employed(self, agent_id: int) -> bool:
        return self.store.query_one(
            "SELECT 1 FROM employments WHERE agent_id=? AND status='active'", (agent_id,)) is not None

    def open_jobs(self) -> list:
        return self.store.query("SELECT * FROM jobs WHERE status='open' ORDER BY id")

    def expire_incompatible_offers(
            self, tick: int, *, phase: str = "NIGHT_CLOSE") -> int:
        """Retire offers whose payroll currency can never be settled.

        Modern action validation prevents new cross-currency offers, but a
        resumed run may contain offers written under older semantics. Leaving
        one pending reserves its job until the generic age limit, even though
        accepting it is correctly impossible.
        """
        rows = self.store.query(
            "SELECT jo.id AS offer_id,jo.application_id,ap.agent_id AS candidate_agent_id,"
            "j.id AS job_id,j.firm_id,f.currency_code AS firm_currency,"
            "candidate_wallet.currency_code AS candidate_currency "
            "FROM job_offers jo "
            "JOIN applications ap ON ap.id=jo.application_id "
            "JOIN jobs j ON j.id=ap.job_id "
            "JOIN firms f ON f.id=j.firm_id "
            "JOIN agents a ON a.id=ap.agent_id "
            "LEFT JOIN accounts candidate_wallet "
            "ON candidate_wallet.id=a.checking_account_id "
            "WHERE jo.status='pending' "
            "AND (candidate_wallet.id IS NULL "
            "OR candidate_wallet.currency_code IS NULL "
            "OR candidate_wallet.currency_code<>COALESCE(f.currency_code,'USD')) "
            "ORDER BY jo.id")
        for row in rows:
            offer_id = int(row["offer_id"])
            application_id = int(row["application_id"])
            self.store.update(
                "job_offers", offer_id, status="expired", decided_tick=tick)
            self.store.execute(
                "UPDATE applications SET state='rejected' "
                "WHERE id=? AND state IN ('pending','negotiating')",
                (application_id,),
            )
            self.store.log_event(
                tick,
                "job_offer_expired_incompatible_currency",
                {
                    "offer_id": offer_id,
                    "application_id": application_id,
                    "job_id": int(row["job_id"]),
                    "firm_id": int(row["firm_id"]),
                    "candidate_agent_id": int(row["candidate_agent_id"]),
                    "firm_currency": str(row["firm_currency"]),
                    "candidate_currency": str(row["candidate_currency"]),
                },
                phase=phase,
                subject_type="job_offer",
                subject_id=offer_id,
                importance=1.5,
            )
        return len(rows)

    def expire_stale_jobs(
            self, tick: int, max_age: int = 20, *,
            terminalize_stale_applications: bool = False,
            phase: str = "NIGHT_CLOSE") -> None:
        # Only negotiations use job_offers, so this remains a no-op for legacy
        # semantics while making modern capabilities explicitly non-dangling.
        self.expire_incompatible_offers(tick, phase=phase)
        self.store.execute(
            "UPDATE job_offers SET status='expired', decided_tick=? WHERE status='pending' "
            "AND application_id IN (SELECT ap.id FROM applications ap "
            "JOIN jobs j ON j.id=ap.job_id WHERE j.status='open' AND j.tick < ?)",
            (tick, tick - max_age))
        self.store.execute(
            "UPDATE applications SET state='rejected' WHERE state='negotiating' "
            "AND id IN (SELECT application_id FROM job_offers WHERE status='expired')")
        if terminalize_stale_applications:
            # The opt-in recovery profile closes out applicants that never
            # reached negotiation after their vacancy expires.
            self.store.execute(
                "UPDATE applications SET state='rejected' "
                "WHERE state IN ('pending','negotiating') AND job_id IN "
                "(SELECT id FROM jobs WHERE status='open' AND tick < ?)",
                (tick - max_age,))
        self.store.execute(
            "UPDATE jobs SET status='closed' WHERE status='open' AND tick < ?", (tick - max_age,))

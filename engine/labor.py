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
    def __init__(self, store: Store):
        self.store = store

    def post_job(self, tick: int, firm_id: int, title: str, wage_cents: int) -> int:
        job_id = self.store.insert("jobs", tick=tick, firm_id=firm_id, title=title,
                                   wage_cents=max(0, int(wage_cents)), status="open")
        self.store.log_event(tick, "job_posted", {
            "job_id": job_id, "firm_id": firm_id, "title": title, "wage_cents": wage_cents},
            phase="EXECUTION")
        return job_id

    def apply_job(self, tick: int, agent_id: int, job_id: int) -> Optional[int]:
        job = self.store.query_one("SELECT * FROM jobs WHERE id=?", (job_id,))
        if not job or job["status"] != "open":
            return None
        dup = self.store.query_one(
            "SELECT id FROM applications WHERE job_id=? AND agent_id=? AND state='pending'",
            (job_id, agent_id))
        if dup:
            return int(dup["id"])
        app_id = self.store.insert("applications", tick=tick, job_id=job_id, agent_id=agent_id,
                                   state="pending")
        self.store.log_event(tick, "job_application", {
            "application_id": app_id, "job_id": job_id, "agent_id": agent_id}, phase="EXECUTION")
        return app_id

    def hire(self, tick: int, application_id: int, pay_interval: int = DEFAULT_PAY_INTERVAL) -> Optional[int]:
        app = self.store.query_one("SELECT * FROM applications WHERE id=?", (application_id,))
        if not app or app["state"] != "pending":
            return None
        job = self.store.query_one("SELECT * FROM jobs WHERE id=?", (app["job_id"],))
        if not job or job["status"] != "open":
            return None
        agent_id = int(app["agent_id"])
        # One active job per agent: end any prior employment.
        self.store.execute(
            "UPDATE employments SET status='ended', end_tick=? WHERE agent_id=? AND status='active'",
            (tick, agent_id))
        emp_id = self.store.insert(
            "employments", firm_id=int(job["firm_id"]), agent_id=agent_id, title=job["title"],
            wage_cents=int(job["wage_cents"]), start_tick=tick, status="active",
            pay_interval_ticks=pay_interval, next_pay_tick=tick + pay_interval)
        self.store.update("applications", application_id, state="hired")
        self.store.update("jobs", int(job["id"]), status="filled")
        self.store.execute("UPDATE agents SET employer_id=? WHERE id=?", (int(job["firm_id"]), agent_id))
        # Reject sibling applications for this job.
        self.store.execute(
            "UPDATE applications SET state='rejected' WHERE job_id=? AND state='pending'",
            (int(job["id"]),))
        self.store.log_event(tick, "hired", {
            "employment_id": emp_id, "firm_id": int(job["firm_id"]), "agent_id": agent_id,
            "wage_cents": int(job["wage_cents"])}, phase="EXECUTION",
            subject_type="agent", subject_id=agent_id, importance=2.0)
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

    def expire_stale_jobs(self, tick: int, max_age: int = 20) -> None:
        self.store.execute(
            "UPDATE jobs SET status='closed' WHERE status='open' AND tick < ?", (tick - max_age,))

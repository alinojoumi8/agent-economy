"""Overview snapshot built from the same read model used by transport."""
from __future__ import annotations

from communications.projections import public_communication_summary
from communications.policy import Principal

from .events import build_events


def build_snapshot(store, principal: Principal, *, as_of_tick: int, domains: tuple[str, ...]) -> dict:
    requested = set(domains or ("summary", "alerts", "communications", "events"))
    data: dict = {}
    meta = store.get_meta()
    if "summary" in requested:
        data["summary"] = {
            "status": str(meta["status"]),
            "phase": str(meta["phase"] or ""),
            "active_tick": int(meta["active_tick"]) if meta["active_tick"] is not None else None,
            "agents_alive": int(store.scalar(
                "SELECT COUNT(*) FROM agents WHERE alive=1", default=0)),
            "active_firms": int(store.scalar(
                "SELECT COUNT(*) FROM firms WHERE status<>'bankrupt'", default=0)),
            "ledger_balance": int(store.scalar(
                "SELECT COALESCE(SUM(delta_cents),0) FROM ledger_entries WHERE tick<=?",
                (int(as_of_tick),), default=0)),
        }
    if "alerts" in requested:
        data["alerts"] = [
            item for item in build_events(
                store, as_of_tick=as_of_tick, after_id=0, limit=100)["items"]
            if item["importance"] >= 1.5
        ][-20:]
    if "communications" in requested:
        data["communications"] = public_communication_summary(
            store, as_of_tick=int(as_of_tick))
    if "events" in requested:
        data["events"] = build_events(
            store, as_of_tick=as_of_tick, after_id=max(0, int(store.scalar(
                "SELECT COALESCE(MAX(id),0)-50 FROM events WHERE tick<=?",
                (int(as_of_tick),), default=0))), limit=50)
    return data

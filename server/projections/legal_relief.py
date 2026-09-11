"""Selected-day monetary relief, derived from recorded payments and reserves.

Court and settlement events describe admission. They are not the current cash
balance. This projection exposes no wallets, heirs, private filings or bodies.
"""
from __future__ import annotations

from engine.store import load_json
from .construction import _public_person


def monetary_relief_as_of(store, matter_id: int, tick: int):
    config = load_json(store.get_meta()["config_json"], {}) or {}
    if int(config.get("engine_semantics_version", 2)) < 20:
        return None
    matter = store.query_one("SELECT * FROM legal_matters WHERE id=? AND filed_tick<=?", (matter_id, tick))
    if matter is None:
        return None
    for party in ("claimant", "respondent"):
        if matter[f"{party}_type"] == "agent" and _public_person(store, matter[f"{party}_id"], tick) is None:
            return {"visibility": "withheld", "as_of_tick": tick}
    result = {"visibility": "public", "as_of_tick": tick, "award": None, "estate_reserve": None}
    award = store.query_one("SELECT id,tick,basis,currency_code,awarded_cents,credited_cents,credited_loss_cents "
        "FROM legal_awards WHERE matter_id=? AND tick<=?", (matter_id, tick))
    if award:
        payment = store.query_one("SELECT COALESCE(SUM(amount_cents),0) AS paid_cents,COALESCE(SUM(tax_cents),0) AS tax_cents,COUNT(*) AS payment_count,"
            "MAX(tick) AS last_paid_tick FROM legal_award_payments WHERE award_id=? AND tick<=?", (award["id"], tick))
        loss = store.scalar("SELECT COALESCE(SUM(amount_cents),0) FROM legal_award_losses WHERE award_id=? AND tick<=?", (award["id"], tick))
        wage = store.scalar("SELECT id FROM legal_wage_awards WHERE award_id=?", (award["id"],))
        result["award"] = {**dict(award), **dict(payment), "written_off_cents": loss,
            "payment_basis": "gross_wages" if wage else "cash", "net_received_cents": payment["paid_cents"] - payment["tax_cents"],
            "outstanding_cents": award["awarded_cents"] - award["credited_cents"] - award["credited_loss_cents"] - payment["paid_cents"] - loss}
    reserve = store.query_one("SELECT id,registered_tick,currency_code,requested_cents,reserve_limit_cents "
        "FROM estate_legal_reserves WHERE matter_id=? AND registered_tick<=?", (matter_id, tick))
    if reserve:
        funded = store.scalar("SELECT COALESCE(SUM(d.amount_cents),0) FROM estate_disbursements d "
            "JOIN estate_receipts r ON r.id=d.receipt_id WHERE d.reserve_id=? AND r.tick<=?", (reserve["id"], tick))
        resolution = store.query_one("SELECT tick,released_cents FROM estate_reserve_resolutions WHERE reserve_id=? AND tick<=?",
                                     (reserve["id"], tick))
        released = resolution["released_cents"] if resolution else 0
        result["estate_reserve"] = {**dict(reserve), "funded_cents": funded, "held_cents": funded - released,
            "released_cents": released, "resolved_tick": resolution["tick"] if resolution else None,
            "status": "resolved" if resolution else "pending"}
    return result

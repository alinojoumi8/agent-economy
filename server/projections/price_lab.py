"""Public, cursor-scoped goods and equity measurements for the price inspector."""
from __future__ import annotations

from research.prices import price_observations


def build_price_lab(store, *, as_of_tick: int, firm_id: int | None = None, window: int = 30) -> dict:
    if type(window) is not int or not 1 <= window <= 90:
        raise ValueError("price window must be 1..90 daily ticks")
    if firm_id is not None and (type(firm_id) is not int or firm_id <= 0):
        raise ValueError("invalid firm identity")
    # Listing/exit status and current private balances are unnecessary to select
    # a price instrument. Firms that exited remain in the historical cohort.
    firms = [dict(row) for row in store.query(
        "SELECT id,name,sector,currency_code FROM firms WHERE founded_tick<=? ORDER BY id LIMIT 501",
        (as_of_tick,))]
    truncated = len(firms) > 500
    firms = firms[:500]
    selected_id = firm_id if firm_id is not None else firms[0]["id"] if firms else None
    selected = next((row for row in firms if row["id"] == selected_id), None)
    if selected_id is not None and selected is None:
        row = store.query_one("SELECT id,name,sector,currency_code FROM firms WHERE id=? AND founded_tick<=?",
                              (selected_id, as_of_tick))
        if row is None:
            raise LookupError("firm not found at the selected tick")
        selected = dict(row)
        firms.append(selected)
    start = max(0, as_of_tick - window + 1)
    return {"contract": "price-lab-projection-v1", "firms": firms, "firms_truncated": truncated,
            "selected_firm": selected, "window_ticks": window, "start_tick": start, "tick": as_of_tick,
            "observation": price_observations(store, selected_id, tick=as_of_tick,
                start_tick=start, include_series=True) if selected_id is not None else None,
            "empty_reason": "no_firms_at_selected_tick" if selected_id is None else None}

"""Read-only end-of-tick cash evidence shared by metrics and research readers."""
from __future__ import annotations

from fractions import Fraction

from .person_kind_history import person_kinds_at


CASH_KINDS = ("checking", "savings", "fx")


def account_balances_at(store, tick: int) -> list[dict]:
    """Accounts with recorded entries, including accounts now empty or closed.

    Account identity and currency are fixed attributes. Their mutable cached
    balance is deliberately not selected. Zero-entry accounts have no amount
    to inventory and no recorded creation date from which to expose identity.
    """
    if type(tick) is not int or tick < 0:
        raise ValueError("tick must be a nonnegative integer")
    return [dict(row) for row in store.query(
        "SELECT a.id,a.owner_type,a.owner_id,a.bank_id,a.kind,a.currency_code,"
        "SUM(l.delta_cents) AS amount_cents,MIN(l.tick) AS first_entry_tick,"
        "MAX(l.tick) AS last_entry_tick FROM ledger_entries l "
        "JOIN accounts a ON a.id=l.account_id WHERE l.tick<=? "
        "GROUP BY a.id ORDER BY a.id", (tick,))]


def people_at(store, tick: int, *, living_only: bool = False) -> list[dict]:
    kinds = person_kinds_at(store, tick)
    boundary = " AND (p.death_tick IS NULL OR p.death_tick>?)" if living_only else ""
    params = (tick, tick) if living_only else (tick,)
    return [{**dict(row), "kind": kinds[row["agent_id"]]} for row in store.query(
        "SELECT p.agent_id,p.origin_tick,p.death_tick FROM person_lifecycle p "
        "JOIN agents a ON a.id=p.agent_id WHERE p.origin_tick<=?" + boundary +
        " ORDER BY p.agent_id", params)]


def cash_distribution_at(store, tick: int) -> dict[str, dict]:
    """Cash-only Gini in each historically observed currency, over all citizens.

    Each living registered citizen, including minors and people without a
    wallet in that currency, contributes one observation. Wallet balances are
    netted within that person/currency, then clipped at zero for this measure.
    Empty/zero-total cohorts have Gini zero by explicit convention. This is
    neither household inequality nor net wealth; negative balances remain
    visible in the returned reconciliation totals.
    """
    people = [r["agent_id"] for r in people_at(store, tick, living_only=True)
              if r["kind"] == "citizen"]
    balances = account_balances_at(store, tick)
    currencies = sorted({r["currency_code"] for r in balances})
    result = {}
    for currency in currencies:
        amounts = dict.fromkeys(people, 0)
        for row in balances:
            if (row["currency_code"] == currency and row["owner_type"] == "agent"
                    and row["owner_id"] in amounts and row["kind"] in CASH_KINDS):
                amounts[row["owner_id"]] += row["amount_cents"]
        result[currency] = summarize_person_cash(amounts)
    return result


def summarize_person_cash(amounts: dict[int, int]) -> dict:
    """Apply the same exact cash convention to an explicitly selected cohort."""
    ordered = sorted(max(0, value) for value in amounts.values())
    count, total = len(ordered), sum(ordered)
    numerator = 2 * sum(rank * value for rank, value in enumerate(ordered, 1))
    gini = float(Fraction(numerator, count * total) - Fraction(count + 1, count)) if total else 0.0
    return {
        "gini": gini, "population_count": count, "nonnegative_cash_cents": total,
        "signed_cash_cents": sum(amounts.values()),
        "negative_cash_cents": sum(min(0, value) for value in amounts.values()),
        "person_cash_cents": amounts,
    }

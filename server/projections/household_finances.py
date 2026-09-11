"""Scoped financial detail for the local operator; never a public city layer."""
from __future__ import annotations

from functools import lru_cache

from research.household_positions import household_positions
from server.projections.construction import _public_person


def build_household_finances(store, *, agent_id: int, as_of_tick: int) -> dict:
    """Retain financial amounts but disclose only core/pinned identity links.

    The caller must enforce local operator access. A selected household's
    finances are private even when all of its members are public identities.
    Raw account references, filings and unrelated households never leave here.
    """
    if _public_person(store, agent_id, as_of_tick) is None:
        raise LookupError("Household view not found at this tick.")
    report = household_positions(store, tick=as_of_tick)
    household = next((h for h in report["households"] if agent_id in h["members"]), None)
    if household is None:
        raise LookupError("Household view not found at this tick.")

    @lru_cache(maxsize=None)
    def person(identifier):
        row = _public_person(store, identifier, as_of_tick)
        return {"type": "agent", "id": row["id"], "name": row["name"]} if row else {
            "type": "private", "id": None, "name": "Private person"}

    def holder(value):
        if value is None:
            return None
        kind, identifier = value["type"], value["id"]
        if kind == "agent":
            return person(identifier)
        if kind == "estate":
            nominee = person(value["nominee_agent_id"])
            return {"type": "estate", "id": None, "name":
                    "Estate of " + nominee["name"] if nominee["id"] is not None else "Private estate"}
        table = {"firm": "firms", "bank": "banks"}.get(kind)
        row = store.query_one(f"SELECT name FROM {table} WHERE id=?", (identifier,)) if table else None
        return {"type": kind, "id": None, "name": row["name"] if row else kind.replace("_", " ").capitalize()}

    keys = set(household["asset_keys"]) | set(household["debt_keys"])
    references = {key: f"position-{i}" for i, key in enumerate(sorted(keys), 1)}

    def totals(by_currency):
        return {currency: {**{k: values[k] for k in ("wallet_cash_cents", "restricted_cash_cents", "receivable_face_cents",
                                                   "debt_face_cents", "observed_equity_marks_cents")},
                           "unpriced_count": len(set(values["unpriced_keys"]))}
                for currency, values in by_currency.items()}

    instruments = []
    for row in report["instruments"]:
        if row["key"] not in keys:
            continue
        instruments.append({
            "id": references[row["key"]], "kind": row["kind"],
            "asset": row["key"] in household["asset_keys"], "debt": row["key"] in household["debt_keys"],
            "holder": holder(row["holder"]), "original_holder": holder(row["original_holder"]),
            "debtor": holder(row["debtor"]), "currency": row["currency"], "unit": row["unit"],
            "quantity": row["quantity"], "cash_cents": row["cash_cents"], "face_cents": row["face_cents"],
            "mark": {k: v for k, v in row["mark"].items() if k != "evidence"} if row["mark"] else None,
            "replaces": [references[k] for k in row["replaces"] if k in references],
            "reason": row["reason"],
        })

    # Only estates on this household's residual paths, without other heirs,
    # raw claim references or protected obligation/account identifiers.
    estate_ids = sorted({identifier for interest in household["contingent_interests"] for identifier in interest["estate_path"]})
    estate_refs = {identifier: f"boundary-{i}" for i, identifier in enumerate(estate_ids, 1)}
    boundaries = []
    for estate in report["estates"]:
        if estate["estate_id"] not in estate_refs:
            continue
        nominee = person(estate["nominee_agent_id"])
        creditors, reserves = {}, {}
        for claim in estate["creditors_in_priority_order"]:
            key = (claim["currency"], claim["priority"])
            creditors[key] = creditors.get(key, 0) + claim["remaining_cents"]
        for reserve in estate["unresolved_reserves"]:
            currency = reserve["currency_code"]
            reserves[currency] = reserves.get(currency, 0) + reserve["reserve_limit_cents"]
        boundaries.append({"id": estate_refs[estate["estate_id"]],
            "name": "Estate of " + nominee["name"] if nominee["id"] is not None else "Private estate",
            "by_currency": totals(estate["by_currency"]),
            "creditors": [{"currency": key[0], "priority": key[1], "remaining_cents": amount}
                          for key, amount in creditors.items()],
            "reserve_limits": [{"currency": currency, "limit_cents": amount} for currency, amount in reserves.items()],
            "finality_policy": estate["finality_policy"]})

    return {"contract_version": "household-finances-v1", "visibility": "local_operator",
        "selected_agent_id": agent_id, "household_id": household["household_id"],
        "members": [person(identifier) for identifier in household["members"]],
        "by_currency": totals(household["by_currency"]), "instruments": instruments,
        "contingent_interests": [{"beneficiary": person(row["beneficiary_agent_id"]),
            "estate_path": [estate_refs[identifier] for identifier in row["estate_path"]],
            "fraction": row["fraction_if_intervening_claims_settled"], "amount_cents": None}
            for row in household["contingent_interests"]],
        "estate_boundaries": boundaries,
        "cash_inequality": {currency: {k: distribution[k] for k in ("gini", "population_count", "nonnegative_cash_cents",
                                                                 "signed_cash_cents", "negative_cash_cents")}
                            for currency, distribution in report["cash_distribution"].items()},
        "net_wealth_cents": None, "currency_conversion": None,
        "identity_policy": "core_or_pinned_at_selected_tick; other_people_anonymous",
        "scope": "selected_household_and_its_conditional_estate_paths"}

"""Versioned definitions and strict read-only observations for research metrics.

These contracts describe existing output; they never rewrite historical values.
Unregistered or incompatible series are unavailable to a strict research reader.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import re

from engine.store import Store, load_json

REGISTRY_VERSION = "research-metrics-v1"


@dataclass(frozen=True)
class MetricDefinition:
    key: str
    version: str
    domain: str
    label: str
    unit: str
    currency_policy: str
    population: str
    time_basis: str
    formula: str
    evidence: tuple[str, ...]
    missingness: str
    min_semantics: int = 1
    price_kind: str = "not_price"


DEFINITIONS = (
    MetricDefinition(
        "cpi", "legacy-genesis-posted-v2", "goods", "Legacy posted goods price index",
        "index_points_genesis_100", "single_currency_required",
        "founded_tick=0 firms excluding sectors health and insurance, including exits",
        "state_at_tick", "100 * mean(positive posted unit prices) / genesis mean",
        ("world/metrics.py:Metrics._cpi", "firms.product_json", "metrics.cpi_base"),
        "Historical engine returns 100 for an empty basket; this is a default, not a transaction price. Missing posted items are omitted by the legacy formula.",
        min_semantics=2, price_kind="posted_index"),
    MetricDefinition(
        "gdp_proxy", "final-goods-flow-v3", "goods", "Final goods sales flow",
        "currency_major_units", "single_currency_required", "successful goods_sale events",
        "one_tick", "sum(total_cents) / 100",
        ("world/metrics.py:Metrics._gdp_proxy", "events.goods_sale"),
        "Zero means no recorded sales in a finalized tick; missing tick is unavailable. Semantics 1–2 include wages and do not satisfy this contract.", min_semantics=3),
    MetricDefinition(
        "gdp_proxy_30d", "final-goods-flow-30-v3", "goods", "Trailing goods sales",
        "currency_major_units", "single_currency_required", "successful goods_sale events",
        "max(1,tick-29)..tick", "sum(total_cents in window) / 100",
        ("world/metrics.py:Metrics._gdp_proxy_30d", "events.goods_sale"),
        "Before tick 30 this is a shorter observed window, not a complete month.", min_semantics=3),
    MetricDefinition(
        "labor_income", "wage-flow-v3", "labor", "Gross wage payments",
        "currency_major_units", "single_currency_required", "wage_paid events",
        "one_tick", "sum(wage_cents) / 100",
        ("world/metrics.py:Metrics._labor_income", "events.wage_paid"),
        "Zero between payroll dates is not zero contracted wages; missing tick is unavailable.", min_semantics=3),
    MetricDefinition(
        "unemployment", "unique-worker-share-v7", "labor", "Unemployed working-age citizens",
        "fraction", "currency_neutral", "living non-retired citizens aged 18–64",
        "state_at_tick", "1 - count(unique employed citizens or active founders) / labor_force",
        ("world/metrics.py:Metrics._unemployment", "agents", "employments", "firms"),
        "Legacy engine returns zero with an empty labor force; older semantics count workers differently.", min_semantics=7),
    MetricDefinition(
        "gini", "nonnegative-cash-gini-v1", "households", "Citizen cash inequality",
        "fraction", "single_currency_required", "living citizens; account sums clipped at zero",
        "state_at_tick", "2*sum(rank*cash)/(n*sum(cash)) - (n+1)/n",
        ("world/metrics.py:Metrics._gini", "accounts", "agents"),
        "Returns zero for empty or zero-cash cohorts. Excludes shares, loans and real assets; not net-wealth Gini."),
    MetricDefinition(
        "money_supply", "checking-savings-total-v1", "banking", "Checking and savings balances",
        "currency_major_units", "single_currency_required", "all checking and savings accounts",
        "state_at_tick", "sum(balance_cents) / 100",
        ("engine/ledger.py:Ledger.total_deposits_cents", "accounts"),
        "This aggregate is not a calibrated M1/M2 definition; a missing tick is unavailable."),
    MetricDefinition(
        "index", "share-count-weighted-index-v1", "equities", "Legacy equity index",
        "index_points", "single_currency_required", "currently listed firms with a last price",
        "state_at_tick", "sum(last_price_cents * shares_outstanding) / sum(shares_outstanding) / initial_divisor",
        ("engine/exchange.py:Exchange.compute_index", "metrics.stock:<firm_id>", "firms"),
        "Missing before first eligible price. Last prices can be stale; changing listings/float changes the basket. This is not a total-return or market-cap-weighted-price index.",
        price_kind="execution_based_legacy_index"),
    MetricDefinition(
        "stock:{firm_id}", "last-execution-v1", "equities", "Last executed share price",
        "currency_minor_units_per_share", "instrument_currency", "one firm's actual trades",
        "last execution at or before selected tick", "price_cents of last trade ordered by tick,id",
        ("engine/exchange.py:Exchange._settle", "trades"),
        "Null before the first trade. Carries last execution with observed tick and age; never treats a quote, book value or empty book as a transaction.",
        price_kind="execution"),
    MetricDefinition(
        "goods_posted:{firm_id}", "observed-posted-price-v1", "goods", "Observed posted product price",
        "currency_minor_units_per_firm_product_unit", "instrument_currency", "one firm's product",
        "state_at_tick", "last recorded price_set at or before tick; current firm state only at current committed tick",
        ("research/prices.py:price_observations", "events.price_set", "firms.product_json"),
        "Null when no historical quote was recorded. Carries observation age; never uses a future firm quote.", price_kind="posted"),
    MetricDefinition(
        "goods_vwap:{firm_id}", "goods-sales-vwap-v1", "goods", "Executed product price",
        "currency_minor_units_per_firm_product_unit", "instrument_currency", "one firm's valid successful goods_sale events",
        "one_tick", "sum(total_cents) / sum(qty)",
        ("research/prices.py:price_observations", "events.goods_sale"),
        "Null with no execution or invalid sale evidence. Does not measure intended or unmet demand.", price_kind="volume_weighted_execution"),
    MetricDefinition(
        "goods_volume:{firm_id}", "goods-sales-volume-v1", "goods", "Product units sold",
        "firm_product_units", "instrument_currency", "one firm's valid successful goods_sale events",
        "one_tick", "sum(qty)",
        ("research/prices.py:price_observations", "events.goods_sale"),
        "Zero with no sales; null when sale evidence is invalid. Unit is only comparable within the declared firm product."),
    MetricDefinition(
        "equity_price:{firm_id}", "qualified-last-execution-v1", "equities", "Last distinct-owner share execution",
        "currency_minor_units_per_share", "instrument_currency", "one firm's trades where buyer_id differs from seller_id",
        "last execution at or before selected tick", "price_cents of last qualified trade ordered by tick,id",
        ("research/prices.py:price_observations", "trades"),
        "Null before a qualified trade; carries age. Broader beneficial ownership is not recorded.", price_kind="qualified_execution"),
    MetricDefinition(
        "equity_vwap:{firm_id}", "qualified-equity-vwap-v1", "equities", "Executed share price",
        "currency_minor_units_per_share", "instrument_currency", "one firm's trades where buyer_id differs from seller_id",
        "one_tick", "sum(price_cents * qty) / sum(qty)",
        ("research/prices.py:price_observations", "trades"),
        "Null with no qualified execution or invalid trade evidence.", price_kind="volume_weighted_execution"),
    MetricDefinition(
        "equity_volume:{firm_id}", "qualified-equity-volume-v1", "equities", "Shares traded between distinct owners",
        "shares", "instrument_currency", "one firm's trades where buyer_id differs from seller_id",
        "one_tick", "sum(qty)",
        ("research/prices.py:price_observations", "trades"),
        "Zero with no qualified trades; null with invalid trade evidence. Outstanding float is a separate stock."),
    MetricDefinition(
        "policy_rate", "policy-rate-bps-v1", "banking", "Policy rate",
        "basis_points_per_year", "currency_neutral", "configured central policy rate",
        "state_at_tick", "engine policy_rate_bps",
        ("world/metrics.py:Metrics.snapshot", "engine/economy.py"),
        "Administrative policy instrument; not a discovered loan APR."),
    MetricDefinition(
        "bank_deposits:{bank_id}", "bank-deposit-total-v1", "banking", "Bank deposit balances",
        "currency_major_units", "bank_currency", "one bank's checking and savings accounts",
        "state_at_tick", "bank.deposits(bank_id) / 100",
        ("world/metrics.py:Metrics.snapshot", "engine/credit.py", "accounts"),
        "Missing record is unavailable; balances are not a measurement of new loan-created money."),
    MetricDefinition(
        "bank_reserve_ratio:{bank_id}", "reserve-deposit-ratio-v1", "banking", "Bank reserve ratio",
        "ratio", "bank_currency", "one bank's reserves and deposits",
        "state_at_tick", "bank.reserve_ratio(bank_id)",
        ("world/metrics.py:Metrics.snapshot", "engine/credit.py"),
        "Uses the engine's zero-deposit convention; not a regulatory capital ratio."),
    MetricDefinition(
        "hhi", "sales-concentration-30-v4", "goods", "Seller sales concentration",
        "hhi_points_0_to_10000", "single_currency_required", "sellers with goods_sale events in the window",
        "max(0,tick-29)..tick", "sum((100 * seller_sales / all_sales)^2)",
        ("world/metrics.py:Metrics._market_hhi", "events.goods_sale"),
        "Zero means no positive sales denominator, not a competitive market; heterogeneous products are combined.", min_semantics=4),
)


def metric_definition(name: str) -> MetricDefinition | None:
    for definition in DEFINITIONS:
        pattern = re.escape(definition.key)
        pattern = pattern.replace(re.escape("{firm_id}"), r"[1-9]\d*")
        pattern = pattern.replace(re.escape("{bank_id}"), r"[1-9]\d*")
        if re.fullmatch(pattern, name):
            return definition
    return None


def metric_catalog() -> dict:
    return {"registry_version": REGISTRY_VERSION,
            "definitions": [asdict(definition) for definition in DEFINITIONS]}


def read_metric_observation(store: Store, name: str, tick: int) -> dict:
    """Read a declared series without filling absent points or mixing currency."""
    if type(tick) is not int or tick < 0:
        raise ValueError("tick must be a nonnegative integer")
    definition = metric_definition(name)
    result = {"name": name, "tick": tick, "value": None, "observed_tick": None,
              "age_ticks": None, "currency": None, "status": "unavailable",
              "reason": None, "registry_version": REGISTRY_VERSION,
              "definition": asdict(definition) if definition else None}

    def unavailable(reason: str) -> dict:
        return {**result, "reason": reason}

    if definition is None:
        return unavailable("unregistered_metric")
    meta = store.get_meta()
    if tick > int(meta["tick"]):
        return unavailable("future_tick")
    config = load_json(meta["config_json"], {})
    if int(config.get("engine_semantics_version", 1)) < definition.min_semantics:
        return unavailable("incompatible_metric_semantics")
    if definition.currency_policy == "single_currency_required":
        currencies = [str(row[0]) for row in store.query(
            "SELECT DISTINCT currency_code FROM accounts ORDER BY currency_code")]
        if len(currencies) != 1 or not currencies[0]:
            return unavailable("multiple_or_unknown_currencies_without_conversion")
        result["currency"] = currencies[0]
    elif definition.currency_policy in {"instrument_currency", "bank_currency"}:
        table = "firms" if definition.currency_policy == "instrument_currency" else "banks"
        currency = store.scalar(f"SELECT currency_code FROM {table} WHERE id=?", (int(name.split(":")[1]),))
        if not currency:
            return unavailable("unknown_instrument_currency")
        result["currency"] = str(currency)
    price_measures = {
        "goods_posted": ("goods", "posted_price"), "goods_vwap": ("goods", "executed_price"),
        "goods_volume": ("goods", "quantity"), "equity_price": ("equities", "last_execution"),
        "equity_vwap": ("equities", "executed_price"), "equity_volume": ("equities", "quantity"),
    }
    prefix = name.split(":")[0]
    if prefix in price_measures:
        from research.prices import price_observations
        try:
            prices = price_observations(store, int(name.split(":")[1]), tick=tick)
        except ValueError:
            return unavailable("instrument_or_committed_window_unavailable")
        domain, measure = price_measures[prefix]
        observation = prices[domain][measure]
        if isinstance(observation, dict):
            if observation["value"] is None:
                return {**result, **observation}
            return {**result, **observation,
                    "observed_tick": observation["observed_tick"] if observation["observed_tick"] is not None else tick,
                    "age_ticks": observation["age_ticks"] if observation["observed_tick"] is not None else 0}
        return {**result, "value": observation,
                "status": "available" if observation is not None else "unavailable",
                "reason": "invalid_execution_evidence" if observation is None else None,
                "observed_tick": tick, "age_ticks": 0}
    if definition.price_kind == "execution":
        row = store.query_one(
            "SELECT tick,price_cents AS value FROM trades WHERE firm_id=? AND tick<=? "
            "ORDER BY tick DESC,id DESC LIMIT 1", (int(name.split(":")[1]), tick))
    else:
        row = store.query_one(
            "SELECT tick,value FROM metrics WHERE name=? AND tick=? ORDER BY id DESC LIMIT 1",
            (name, tick))
    if row is None:
        return unavailable("no_execution" if definition.price_kind == "execution" else "not_recorded_at_tick")
    value = row["value"]
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return unavailable("nonfinite_value")
    return {**result, "status": "available", "value": value,
            "observed_tick": int(row["tick"]), "age_ticks": tick - int(row["tick"])}

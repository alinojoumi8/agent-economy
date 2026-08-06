const ORDER_FIELDS = [
  "id", "tick", "agent_id", "actor_id", "firm_id", "side", "order_type", "qty",
  "qty_remaining", "limit_price_cents", "pair", "base_currency", "quote_currency",
  "limit_rate_ppm", "status",
];
const TRADE_FIELDS = [
  "id", "tick", "firm_id", "firm_name", "buy_order_id", "sell_order_id", "buyer_id",
  "seller_id", "qty", "price_cents", "order_id", "actor_id", "pair", "side",
  "base_qty", "quote_qty", "rate_ppm",
];
const EVENT_FIELDS = ["id", "tick", "phase", "kind", "subject_type", "subject_id", "importance"];
const CURRENCY_FIELDS = ["code", "name", "minor_unit", "numeraire_rate_ppm"];
const NUMERIC_FIELDS = new Set([
  "id", "tick", "agent_id", "actor_id", "firm_id", "qty", "qty_remaining",
  "limit_price_cents", "limit_rate_ppm", "price_cents", "buy_order_id", "sell_order_id",
  "buyer_id", "seller_id", "order_id", "base_qty", "quote_qty", "rate_ppm", "importance",
  "subject_id", "minor_unit", "numeraire_rate_ppm",
]);

function records(value) {
  return Array.isArray(value) ? value.filter(row => row && typeof row === "object") : [];
}

function sanitize(row, fields) {
  const result = {};
  for (const field of fields) {
    if (row[field] === undefined) continue;
    if (NUMERIC_FIELDS.has(field) && !Number.isFinite(row[field])) continue;
    result[field] = row[field];
  }
  return result;
}

function compareTickId(left, right) {
  return Number(left.tick ?? 0) - Number(right.tick ?? 0)
    || Number(left.id ?? 0) - Number(right.id ?? 0)
    || String(left.id ?? "").localeCompare(String(right.id ?? ""));
}

function fxDirection(row) {
  const [pairBase = "", pairQuote = ""] = String(row.pair ?? "").split("/");
  return {
    ...row,
    baseCurrency: row.base_currency || pairBase || null,
    quoteCurrency: row.quote_currency || pairQuote || null,
  };
}

function normalizedRows(value, fields) {
  return records(value)
    .map(row => sanitize(row, fields))
    .filter(row => row.id !== undefined)
    .sort(compareTickId);
}

export function normalizeMarketsWorkspace(data = {}) {
  const source = data && typeof data === "object" ? data : {};
  const orders = normalizedRows(source.orders, ORDER_FIELDS);
  const trades = normalizedRows(source.trades, TRADE_FIELDS);
  const fxOrders = normalizedRows(source.fx_orders, ORDER_FIELDS).map(fxDirection);
  const fxTrades = normalizedRows(source.fx_trades, TRADE_FIELDS).map(fxDirection);
  const volumes = trades.map(row => row.qty).filter(Number.isFinite);
  return {
    orders,
    trades,
    fxOrders,
    fxTrades,
    circuitBreakers: normalizedRows(source.circuit_breakers, EVENT_FIELDS),
    totals: {
      tradeCount: trades.length,
      tradeVolume: volumes.length ? volumes.reduce((sum, value) => sum + Number(value), 0) : null,
      fxTradeCount: fxTrades.length,
    },
    currencies: records(source.currencies).map(row => sanitize(row, CURRENCY_FIELDS))
      .filter(row => row.code)
      .sort((left, right) => String(left.code ?? "").localeCompare(String(right.code ?? ""))),
  };
}

export function filterMarketRows(rows, filters = {}) {
  return records(rows).filter(row => (
    (!filters.side || String(row.side ?? "").toLowerCase() === String(filters.side).toLowerCase())
    && (!filters.status || String(row.status ?? "").toLowerCase() === String(filters.status).toLowerCase())
  )).sort(compareTickId);
}

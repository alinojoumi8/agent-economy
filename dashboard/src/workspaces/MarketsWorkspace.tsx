import { Link, useSearchParams } from "react-router";
import { filterMarketRows, normalizeMarketsWorkspace } from "./marketsWorkspaceModel.js";
import {
  WorkspaceHeader,
  WorkspaceState,
  WorkspaceTable,
  workspaceUrl,
  useWorkspaceProjection,
} from "./workspaceShared";

type MarketRow = {
  id: number; tick?: number; firm_id?: number; firm_name?: string; side?: string;
  status?: string; qty?: number; qty_remaining?: number; limit_price_cents?: number;
  price_cents?: number; pair?: string; baseCurrency?: string; quoteCurrency?: string;
  base_qty?: number; quote_qty?: number; rate_ppm?: number; limit_rate_ppm?: number; kind?: string;
  importance?: number;
};
type MarketsProjection = {
  orders?: MarketRow[]; trades?: MarketRow[]; fx_orders?: MarketRow[]; fx_trades?: MarketRow[];
  circuit_breakers?: MarketRow[]; currencies?: Array<Record<string, unknown>>;
};
type MarketView = "orders" | "trades" | "fx" | "circuits";

function text(value: unknown, fallback = "—") {
  return value === null || value === undefined || value === "" ? fallback : String(value).replaceAll("_", " ");
}

function measured(value: unknown, unit: string) {
  return Number.isFinite(value) ? `${Number(value).toLocaleString()} ${unit}` : "—";
}

export function MarketsWorkspace() {
  const projection = useWorkspaceProjection<MarketsProjection>("workspace.markets", "/api/v2/workspaces/markets");
  const [searchParams, setSearchParams] = useSearchParams();
  const model = normalizeMarketsWorkspace(projection.data || {});
  const requestedView = searchParams.get("view");
  const view: MarketView = ["orders", "trades", "fx", "circuits"].includes(String(requestedView))
    ? requestedView as MarketView : "orders";
  const filters = { side: searchParams.get("side") || "", status: searchParams.get("status") || "" };
  const patch = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams);
    if (!value || (key === "view" && value === "orders")) next.delete(key);
    else next.set(key, value);
    if (key === "view") {
      next.delete("side");
      next.delete("status");
    }
    setSearchParams(next, { replace: true });
  };
  const organizationUrl = (id: number) => workspaceUrl(projection.runId, `organizations/${id}`, projection.observerState);
  const investigationUrl = (id: number) => workspaceUrl(projection.runId, "investigations", projection.observerState, { event: id });
  const orders = filterMarketRows(model.orders, filters) as MarketRow[];
  const fxOrders = filterMarketRows(model.fxOrders, filters) as MarketRow[];

  return <section className="world-os-markets-workspace">
    <WorkspaceHeader title="Markets" kicker="As-of order and execution evidence"
      sourceLabel="Markets workspace committed projection" envelope={projection.envelope} />
    <WorkspaceState loading={projection.loading} error={projection.error}>
      <dl className="world-os-summary-strip" aria-label="Market summary">
        <div><dt>Trades</dt><dd>{model.totals.tradeCount}</dd></div>
        <div><dt>Trade volume</dt><dd>{model.totals.tradeVolume == null ? "—" : measured(model.totals.tradeVolume, "shares")}</dd></div>
        <div><dt>FX trades</dt><dd>{model.totals.fxTradeCount}</dd></div>
        <div><dt>Currencies</dt><dd>{(model.currencies as Array<{ code?: string }>).map(item => item.code).filter(Boolean).join(", ") || "—"}</dd></div>
      </dl>
      <div className="world-os-market-toolbar">
        <div className="world-os-view-switch" role="group" aria-label="Market evidence view">
          {(["orders", "trades", "fx", "circuits"] as MarketView[]).map(item => <button key={item} type="button" aria-pressed={view === item} onClick={() => patch("view", item)}>{item === "circuits" ? "Circuit breakers" : text(item)}</button>)}
        </div>
        {(view === "orders" || view === "fx") && <div className="world-os-filters">
          <label>Side <select value={filters.side} onChange={event => patch("side", event.target.value)}><option value="">All</option><option value="buy">Buy</option><option value="sell">Sell</option></select></label>
          <label>Status <select value={filters.status} onChange={event => patch("status", event.target.value)}><option value="">All</option><option value="open">Open</option><option value="partial">Partial</option><option value="filled">Filled</option><option value="cancelled">Cancelled</option></select></label>
        </div>}
      </div>

      {view === "orders" && <article className="world-os-workspace-card">
        <header><div><p className="world-os-kicker">Equity order book</p><h3>Orders</h3></div></header>
        <WorkspaceTable caption="Equity orders" rows={orders} empty="The order book is empty at this tick; no activity is inferred."
          columns={[
            { key: "tick", label: "Tick", render: row => text(row.tick) },
            { key: "side", label: "Side", render: row => text(row.side) },
            { key: "firm", label: "Organization", render: row => row.firm_id ? <Link to={organizationUrl(row.firm_id)}>{text(row.firm_name, `Organization ${row.firm_id}`)}</Link> : "—" },
            { key: "qty", label: "Quantity (shares)", render: row => measured(row.qty, "shares") },
            { key: "remaining", label: "Remaining (shares)", render: row => measured(row.qty_remaining, "shares") },
            { key: "price", label: "Limit (cents, firm currency)", render: row => measured(row.limit_price_cents, "cents") },
            { key: "status", label: "Status", render: row => text(row.status) },
          ]} />
      </article>}

      {view === "trades" && <article className="world-os-workspace-card">
        <header><div><p className="world-os-kicker">Executed equity records</p><h3>Trades</h3></div></header>
        <WorkspaceTable caption="Equity trades" rows={model.trades as MarketRow[]} empty="No equity executions are committed at this tick."
          columns={[
            { key: "tick", label: "Tick", render: row => text(row.tick) },
            { key: "firm", label: "Organization", render: row => row.firm_id ? <Link to={organizationUrl(row.firm_id)}>{text(row.firm_name, `Organization ${row.firm_id}`)}</Link> : "—" },
            { key: "qty", label: "Quantity (shares)", render: row => measured(row.qty, "shares") },
            { key: "price", label: "Price (cents, firm currency)", render: row => measured(row.price_cents, "cents") },
          ]} />
      </article>}

      {view === "fx" && <div className="world-os-market-stack">
        <article className="world-os-workspace-card"><header><div><p className="world-os-kicker">FX order book</p><h3>FX orders</h3></div></header>
          <WorkspaceTable caption="FX orders" rows={fxOrders} empty="The FX order book is empty at this tick."
            columns={[
              { key: "tick", label: "Tick", render: row => text(row.tick) },
              { key: "pair", label: "Base / quote", render: row => `${text(row.baseCurrency)} / ${text(row.quoteCurrency)}` },
              { key: "side", label: "Side", render: row => text(row.side) },
              { key: "qty", label: "Base quantity", render: row => measured(row.qty, text(row.baseCurrency, "base units")) },
              { key: "rate", label: "Limit (ppm)", render: row => measured(row.limit_rate_ppm, "ppm") },
              { key: "status", label: "Status", render: row => text(row.status) },
            ]} />
        </article>
        <article className="world-os-workspace-card"><header><div><p className="world-os-kicker">FX executions</p><h3>FX trades</h3></div></header>
          <WorkspaceTable caption="FX trades" rows={model.fxTrades as MarketRow[]} empty="No FX executions are committed at this tick."
            columns={[
              { key: "tick", label: "Tick", render: row => text(row.tick) },
              { key: "pair", label: "Base / quote", render: row => `${text(row.baseCurrency)} / ${text(row.quoteCurrency)}` },
              { key: "base", label: "Base quantity", render: row => measured(row.base_qty, text(row.baseCurrency, "base units")) },
              { key: "quote", label: "Quote quantity", render: row => measured(row.quote_qty, text(row.quoteCurrency, "quote units")) },
              { key: "rate", label: "Rate (ppm)", render: row => measured(row.rate_ppm, "ppm") },
            ]} />
        </article>
      </div>}

      {view === "circuits" && <article className="world-os-workspace-card">
        <header><div><p className="world-os-kicker">Committed safety events</p><h3>Circuit breakers</h3></div></header>
        <WorkspaceTable caption="Circuit breaker events" rows={model.circuitBreakers as MarketRow[]} empty="No circuit-breaker event is committed at this tick."
          columns={[
            { key: "tick", label: "Tick", render: row => text(row.tick) },
            { key: "kind", label: "Event", render: row => <Link to={investigationUrl(row.id)}>{text(row.kind, `Event ${row.id}`)}</Link> },
            { key: "importance", label: "Importance", render: row => text(row.importance) },
          ]} />
      </article>}
    </WorkspaceState>
  </section>;
}

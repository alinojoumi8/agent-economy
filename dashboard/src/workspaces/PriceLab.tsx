import { Link, useSearchParams } from "react-router";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { priceLabFrameMatches, priceLabSelection, priceNumber } from "./priceLabModel.js";
import { organizationWorkspaceUrl } from "./workspaceRouteState.js";
import { WorkspaceState, WorkspaceTable, useWorkspaceProjection, workspaceUrl } from "./workspaceShared";
import "./price-lab.css";

type Observation = { value: number | null; reason: string | null; age_ticks?: number | null;
  observed_tick?: number | null; evidence?: Array<{ type: string; id: number }> };
type Point = { tick: number; goods_vwap: number | null; goods_volume: number | null;
  equity_vwap: number | null; equity_volume: number | null; goods_reason?: string; equity_reason?: string };
type Firm = { id: number; name: string; sector: string; currency_code: string };
type PriceData = {
  contract: string; firms: Firm[]; firms_truncated: boolean; selected_firm: Firm | null;
  tick: number; start_tick: number; window_ticks: number;
  observation: { firm_id: number; tick: number; currency: string; limitations: string[];
    goods: { posted_price: Observation; executed_price: Observation; last_execution: Observation;
      quantity: number | null; sale_count: number; demand: { reason: string } };
    equities: { last_execution: Observation; executed_price: Observation; quantity: number | null;
      trade_count: number; excluded_self_trade_ids: number[];
      book: { status: string; reason: string | null; best_bid_cents: number | null; best_ask_cents: number | null;
        spread_cents: number | null; bid_quantity: number | null; ask_quantity: number | null } };
    series: { points: Point[] };
  } | null;
};

function reason(value?: string | null) {
  const labels: Record<string, string> = {
    no_execution: "No execution is recorded.", no_qualified_execution: "No qualifying execution is recorded.",
    no_execution_in_window: "No execution in this window.", posted_price_not_recorded: "This historical posted price was not recorded.",
    invalid_sale_evidence: "The window contains inconsistent sale evidence.", invalid_trade_evidence: "The window contains inconsistent trade evidence.",
  };
  return value ? labels[value] || value.replaceAll("_", " ") : "";
}

function PriceValue({ observation, currency, unit }: { observation: Observation; currency: string; unit: string }) {
  return <><strong>{priceNumber(observation.value)}</strong>
    {observation.value !== null && <span>{currency} cents / {unit}</span>}
    {observation.age_ticks != null && <small>Observed tick {observation.observed_tick} · {observation.age_ticks} ticks old</small>}
    {observation.reason && <small>{reason(observation.reason)}</small>}</>;
}

function ExecutionChart({ points, domain, currency }: { points: Point[]; domain: "goods" | "equity"; currency: string }) {
  const key = domain === "goods" ? "goods_vwap" : "equity_vwap";
  const label = domain === "goods" ? "Goods" : "Equity";
  if (!points.some(point => point[key] !== null)) return <p className="price-lab__no-trades">No {label.toLowerCase()} executions to plot in this window.</p>;
  return <figure className="price-lab__chart">
    <figcaption>{label} daily execution VWAP · {currency} cents / {domain === "goods" ? "product unit" : "share"}</figcaption>
    <div className="price-lab__plot" aria-label={`${label} daily execution prices`}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points} margin={{ top: 12, right: 16, left: 6, bottom: 6 }} accessibilityLayer>
          <CartesianGrid stroke="var(--ae-border-soft)" strokeDasharray="3 3" />
          <XAxis dataKey="tick" name="Tick" tick={{ fill: "var(--ae-text-2)", fontSize: 11 }} />
          <YAxis width={55} tick={{ fill: "var(--ae-text-2)", fontSize: 11 }} domain={[0, "auto"]} />
          <Tooltip labelFormatter={tick => `Tick ${tick}`} formatter={value => [priceNumber(value), `${currency} cents`]} />
          <Line dataKey={key} name={`${label} VWAP`} stroke="var(--ae-accent)" strokeWidth={2}
            dot={{ r: 3 }} connectNulls={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  </figure>;
}

export function PriceLab() {
  const [params, setParams] = useSearchParams();
  const selection = priceLabSelection(params);
  const query = new URLSearchParams({ window: String(selection.window) });
  if (selection.firmId !== undefined) query.set("firm_id", String(selection.firmId));
  const projection = useWorkspaceProjection<PriceData>("workspace.price_lab", `/api/v2/workspaces/price-lab?${query}`);
  const matches = priceLabFrameMatches(projection.envelope, {
    runId: projection.runId, fork: projection.observerState.fork, tick: projection.observerState.tick, ...selection,
  });
  const data = matches ? projection.data : undefined;
  const observation = data?.observation;
  const error = selection.invalid ? new Error("Invalid price selection. Clear it to choose a business.")
    : projection.error || (projection.envelope && !matches ? new Error("Price data does not match the selected run, fork, tick or instrument.") : null);
  const patch = (name: string, value: string) => setParams(previous => {
    const next = new URLSearchParams(previous);
    if (value) next.set(name, value); else next.delete(name);
    return next;
  });
  const clear = () => setParams(previous => {
    const next = new URLSearchParams(previous);
    next.delete("price_firm"); next.delete("price_window"); return next;
  });
  const evidence = observation?.goods.executed_price.evidence || [];

  return <section className="price-lab" aria-label="Price Discovery Lab">
    <header className="price-lab__intro"><div><p className="world-os-kicker">Price Discovery Lab</p>
      <h3>Follow a business from goods to shares</h3>
      <p>Inspect posted offers and settled transactions at the same world tick.</p></div>
      <Link to={workspaceUrl(projection.runId, "world", projection.observerState)}>Explore the city ↗</Link>
    </header>
    <div className="price-lab__controls">
      <label>Business <select aria-label="Business" value={data?.selected_firm?.id ?? ""} onChange={event => patch("price_firm", event.target.value)}>
        {!data?.firms.length && <option value="">No business selected</option>}
        {data?.firms.map(firm => <option key={firm.id} value={firm.id}>{firm.name} · {firm.currency_code}</option>)}
      </select></label>
      <label>Measurement window <select aria-label="Measurement window" value={selection.window} onChange={event => patch("price_window", event.target.value)}>
        <option value={7}>7 daily ticks</option><option value={30}>30 daily ticks</option><option value={90}>90 daily ticks</option>
      </select></label>
      {(selection.firmId !== undefined || selection.invalid || error) && <button type="button" onClick={clear}>Clear price selection</button>}
    </div>
    <WorkspaceState loading={projection.loading} error={error}>
      {!observation && !error && <div className="world-os-empty"><h3>No firms at this tick</h3><p>Choose a world with businesses or move to a later recorded tick.</p></div>}
      {observation && data && <>
        <p className="price-lab__scope">{data.selected_firm?.name} · {observation.currency} · ticks {data.start_tick}–{data.tick} · {projection.observerState.tick === "live" ? "latest committed boundary" : "historical view"}.
          {data.selected_firm && <> <Link to={organizationWorkspaceUrl(projection.runId, "firm", data.selected_firm.id, projection.observerState) || "#"}>Inspect business ↗</Link></>}
        </p>
        {data.firms_truncated && <p>Business choices are limited to the first 500 IDs; a directly selected business remains available.</p>}
        <div className="price-lab__domains">
          <article className="world-os-workspace-card" aria-label="Goods price evidence">
            <header><div><p className="world-os-kicker">Real economy</p><h3>Goods</h3></div></header>
            <dl className="price-lab__measurements">
              <div><dt>Posted price at selected tick</dt><dd><PriceValue observation={observation.goods.posted_price} currency={observation.currency} unit="product unit" /></dd></div>
              <div><dt>Execution VWAP in window</dt><dd><PriceValue observation={observation.goods.executed_price} currency={observation.currency} unit="product unit" /></dd></div>
              <div><dt>Executed quantity</dt><dd>{priceNumber(observation.goods.quantity)} product units</dd></div>
              <div><dt>Last purchase</dt><dd><PriceValue observation={observation.goods.last_execution} currency={observation.currency} unit="product unit" /></dd></div>
            </dl>
            <ExecutionChart points={observation.series.points} domain="goods" currency={observation.currency} />
            <p className="price-lab__note">Sales alone cannot measure unmet demand. The current run does not record intended purchases.</p>
            {evidence.length > 0 && <details className="price-lab__evidence"><summary>{evidence.length} sale evidence records</summary>
              <ul>{evidence.map(item => <li key={item.id}><Link to={workspaceUrl(projection.runId, "investigations", projection.observerState, { event: item.id })}>Sale event #{item.id}</Link></li>)}</ul>
            </details>}
          </article>
          <article className="world-os-workspace-card" aria-label="Equity price evidence">
            <header><div><p className="world-os-kicker">Financial market</p><h3>Equities</h3></div></header>
            <dl className="price-lab__measurements">
              <div><dt>Last qualifying execution</dt><dd><PriceValue observation={observation.equities.last_execution} currency={observation.currency} unit="share" /></dd></div>
              <div><dt>Execution VWAP in window</dt><dd><PriceValue observation={observation.equities.executed_price} currency={observation.currency} unit="share" /></dd></div>
              <div><dt>Executed quantity</dt><dd>{priceNumber(observation.equities.quantity)} shares</dd></div>
              <div><dt>Displayed bid / ask</dt><dd>{priceNumber(observation.equities.book.best_bid_cents)} / {priceNumber(observation.equities.book.best_ask_cents)}<small>{observation.currency} cents / share</small></dd></div>
            </dl>
            <ExecutionChart points={observation.series.points} domain="equity" currency={observation.currency} />
            <p className="price-lab__note">{observation.equities.book.status === "unavailable"
              ? "Historical order-book state is unavailable. Current quotes are not shown here."
              : "Displayed orders are not reserved or guaranteed executable depth."}</p>
            <p className="price-lab__note">{observation.equities.excluded_self_trade_ids.length} same-ID self trades excluded from this window.</p>
            <details className="price-lab__evidence"><summary>{observation.equities.trade_count} qualifying trade evidence records</summary>
              <p>Trade IDs: {(observation.equities.executed_price.evidence || []).map(item => `#${item.id}`).join(", ") || "None"}</p>
            </details>
          </article>
        </div>
        <details className="price-lab__daily-table"><summary>Daily execution data and missing observations</summary>
          <p>Each price is that day’s volume-weighted execution price. Missing days remain gaps.</p>
          <WorkspaceTable caption="Daily price observations" rows={observation.series.points.map(point => ({ ...point, id: point.tick }))} columns={[
            { key: "tick", label: "Tick", render: row => row.tick },
            { key: "goods", label: `Goods (${observation.currency} cents/unit)`, render: row => <>{priceNumber(row.goods_vwap)}{row.goods_reason && <small> · {reason(row.goods_reason)}</small>}</> },
            { key: "goodsQty", label: "Product units", render: row => priceNumber(row.goods_volume) },
            { key: "equity", label: `Equity (${observation.currency} cents/share)`, render: row => <>{priceNumber(row.equity_vwap)}{row.equity_reason && <small> · {reason(row.equity_reason)}</small>}</> },
            { key: "shares", label: "Shares", render: row => priceNumber(row.equity_volume) },
          ]} />
        </details>
        <details className="price-lab__method"><summary>Measurement definitions and limitations</summary>
          <p>VWAP = executed notional divided by executed quantity. Quotes never create a transaction price. No-trade days are not carried forward.</p>
          <ul>{observation.limitations.map(item => <li key={item}>{item}</li>)}</ul>
        </details>
      </>}
    </WorkspaceState>
  </section>;
}

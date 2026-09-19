import { useQuery } from "@tanstack/react-query";
import { useId, useState } from "react";
import type { ProjectionEnvelope } from "../generated/worldOs";
import { workspaceApi } from "../app/api";
import { cashGiniLabel, financeMoney, householdFinanceFrameMatches } from "./householdFinancesModel";

type Identity = { type: string; id: number | null; name: string };
type Fraction = { numerator: string; denominator: string };
type Totals = { wallet_cash_cents: number; restricted_cash_cents: number; receivable_face_cents: number;
  debt_face_cents: number; observed_equity_marks_cents: number; unpriced_count: number };
type Instrument = { id: string; kind: string; asset: boolean; debt: boolean; holder: Identity; original_holder: Identity;
  debtor: Identity | null; currency: string; unit: string; quantity: number | Fraction | null;
  cash_cents: number | null; face_cents: number | null;
  mark: { amount_cents: number; unit_price_cents: number; observed_tick: number; age_ticks: number } | null;
  replaces: string[]; reason: string | null };
type Boundary = { id: string; name: string; by_currency: Record<string, Totals>;
  creditors: { currency: string; priority: string; remaining_cents: number }[];
  reserve_limits: { currency: string; limit_cents: number }[]; finality_policy: string };
type Finances = { household_id: number; members: Identity[]; by_currency: Record<string, Totals>;
  instruments: Instrument[]; estate_boundaries: Boundary[];
  contingent_interests: { beneficiary: Identity; estate_path: string[]; fraction: Fraction; amount_cents: null }[];
  cash_inequality: Record<string, { gini: number; population_count: number; nonnegative_cash_cents: number;
    signed_cash_cents: number; negative_cash_cents: number }> };

const titles: Record<string, string> = { wallet_cash: "Wallet cash", restricted_cash: "Restricted cash",
  wage_claim: "Earned wages", wage: "Earned wages", legal_award: "Judgment", award: "Judgment",
  bank_principal: "Bank principal", loan: "Bank principal", obligation: "Contract claim", shares: "Shares", property: "Property interest" };
const words = (value: string) => titles[value] || value.replaceAll("_", " ");
const fraction = (value: Fraction) => `${value.numerator}/${value.denominator}`;

function Position({ row }: { row: Instrument }) {
  const amount = row.cash_cents ?? row.face_cents ?? row.mark?.amount_cents;
  const quantity = typeof row.quantity === "object" && row.quantity ? fraction(row.quantity) : row.quantity;
  return <li>
    <div><strong>{words(row.kind)}</strong><span>{row.asset && row.debt ? "Within-household claim" : row.debt ? "Debt" : "Asset"}</span></div>
    <dl>
      <div><dt>Recorded holder</dt><dd>{row.holder.name}</dd></div>
      {row.debtor && <div><dt>Debtor</dt><dd>{row.debtor.name}</dd></div>}
      {row.original_holder.name !== row.holder.name && <div><dt>Original holder</dt><dd>{row.original_holder.name}</dd></div>}
      {quantity != null && <div><dt>{row.unit === "project_interest" ? "Exact title share" : "Quantity"}</dt><dd>{quantity}</dd></div>}
      <div><dt>{row.cash_cents != null ? "Cash" : row.face_cents != null ? "Remaining face amount" : row.mark ? "Observed execution mark" : "Market value"}</dt>
        <dd>{amount == null ? "Unpriced" : financeMoney(amount, row.currency)}</dd></div>
    </dl>
    {row.mark && <p>Last distinct-owner execution: tick {row.mark.observed_tick}, {row.mark.age_ticks} ticks old.
      {" "}Unit price {financeMoney(row.mark.unit_price_cents, row.currency)}. Sale proceeds may differ.</p>}
    {row.face_cents != null && <p>A face amount records the claim; collection is uncertain.</p>}
    {row.replaces.length > 0 && <p>Replaces {row.replaces.length} earlier claim{row.replaces.length === 1 ? "" : "s"} in this inventory.</p>}
    {row.reason && <p>{row.reason.replaceAll("_", " ").replaceAll(";", ". ")}</p>}
  </li>;
}

export function HouseholdFinances({ runId, fork, agentId, asOfTick }: {
  runId: string; fork: string | null; agentId: number; asOfTick: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const [chosenCurrency, setCurrency] = useState("");
  const [pageState, setPage] = useState({ identity: "", index: 0 });
  const panelId = useId();
  const scope = { runId, fork, tick: asOfTick, agentId };
  const session = useQuery({ queryKey: ["world-os", runId, "household-operator-session"],
    queryFn: ({ signal }) => workspaceApi<{ csrf_token: string }>("/api/v2/operator/session", { signal }),
    enabled: expanded, retry: false, refetchOnWindowFocus: false });
  const token = session.data?.csrf_token;
  const params = new URLSearchParams({ run_id: runId, tick: String(asOfTick) });
  if (fork) params.set("fork_id", fork);
  const query = useQuery({ queryKey: ["household-finances", runId, fork, asOfTick, agentId],
    queryFn: ({ signal }) => workspaceApi<ProjectionEnvelope<Finances>>(
      `/api/v2/operator/household-finances/${agentId}?${params}`, { signal, headers: { "X-CSRF-Token": token || "" } }),
    enabled: expanded && Boolean(token) && !session.error, retry: false, refetchOnWindowFocus: false, gcTime: 0 });
  const data = expanded && token && !session.error && !query.error && !query.isFetching
    && householdFinanceFrameMatches(query.data, scope) ? query.data?.data : undefined;
  const currencies = data ? [...new Set([...Object.keys(data.by_currency), ...Object.keys(data.cash_inequality),
    ...data.estate_boundaries.flatMap(boundary => [...Object.keys(boundary.by_currency),
      ...boundary.creditors.map(row => row.currency), ...boundary.reserve_limits.map(row => row.currency)])])].sort() : [];
  const currency = currencies.includes(chosenCurrency) ? chosenCurrency : currencies[0] || "";
  const totals = data?.by_currency[currency];
  const inequality = data?.cash_inequality[currency];
  const rows = data?.instruments.filter(row => row.currency === currency) || [];
  const identity = `${runId}:${fork}:${asOfTick}:${agentId}:${currency}`;
  const lastPage = Math.max(0, Math.ceil(rows.length / 20) - 1);
  const page = pageState.identity === identity ? Math.min(lastPage, pageState.index) : 0;
  const error = session.error || query.error;
  return <article className="world-os-panel world-os-household-finances" aria-label="Household finances">
    <header><div><p className="world-os-kicker">Local operator · tick {asOfTick}</p><h3>Household finances</h3></div>
      <button type="button" aria-expanded={expanded} aria-controls={panelId} onClick={() => setExpanded(value => !value)}>
        {expanded ? "Close finances" : "Inspect finances"}</button></header>
    {expanded && <div id={panelId}>
      {error && <p role="alert">{error.message}</p>}
      {!error && !data && <p role="status">{session.isFetching || query.isFetching ? "Loading committed household records…" : "No matching financial view is available."}</p>}
      {data && <>
        <p>Household {data.household_id} · {data.members.map(person => person.name).join(", ")}</p>
        <p>Private financial records. Other people retain their identity visibility at this tick.</p>
        <div className="world-os-finance-controls">
          <label htmlFor={`${panelId}-currency`}>Currency</label>
          <select id={`${panelId}-currency`} value={currency} disabled={!currencies.length} onChange={event => setCurrency(event.target.value)}>
            {currencies.map(code => <option key={code} value={code}>{code}</option>)}
          </select>
          <button type="button" onClick={() => void query.refetch()}>Reload selected tick</button>
        </div>
        {currency ? <>
          {totals ? <dl className="world-os-finance-totals">
            <div><dt>Wallet cash</dt><dd>{financeMoney(totals.wallet_cash_cents, currency)}</dd></div>
            <div><dt>Restricted cash</dt><dd>{financeMoney(totals.restricted_cash_cents, currency)}</dd></div>
            <div><dt>Receivable face amounts</dt><dd>{financeMoney(totals.receivable_face_cents, currency)}</dd></div>
            <div><dt>Debt face amounts</dt><dd>{financeMoney(totals.debt_face_cents, currency)}</dd></div>
            <div><dt>Observed equity marks</dt><dd>{financeMoney(totals.observed_equity_marks_cents, currency)}</dd></div>
            <div><dt>Unpriced instruments</dt><dd>{totals.unpriced_count}</dd></div>
          </dl> : <p>No household positions recorded in {currency} at this tick.</p>}
          <p>These amounts have different meanings and are not added into net wealth. Currencies are not converted.</p>
          <section className="world-os-cash-inequality" aria-label={`${currency} cash inequality`}>
            <h4>{currency} citizen cash Gini</h4><strong>{cashGiniLabel(inequality)}</strong>
            <p>{inequality ? `${inequality.population_count} living registered citizens, including minors and citizens with no ${currency} wallet.` : "No currency observation at this tick."}</p>
            <p>Checking, savings and FX cash, netted per person in this currency. Negative balances are clipped to zero for Gini.
              {" "}Claims, escrow, shares and property are excluded.</p>
            {inequality && <p>Signed cash: {financeMoney(inequality.signed_cash_cents, currency)}.
              {" "}Negative cash: {financeMoney(inequality.negative_cash_cents, currency)}.</p>}
          </section>
          <h4>Instruments · {currency}</h4>
          <ul className="world-os-finance-instruments">{rows.slice(page * 20, (page + 1) * 20).map(row => <Position row={row} key={row.id} />)}</ul>
          {!rows.length && <p>No recorded instruments in this currency.</p>}
          {rows.length > 20 && <nav aria-label="Financial instrument pages">
            <button type="button" disabled={page === 0} onClick={() => setPage({ identity, index: page - 1 })}>Previous instruments</button>
            <span>Page {page + 1} of {lastPage + 1}</span>
            <button type="button" disabled={page === lastPage} onClick={() => setPage({ identity, index: page + 1 })}>Next instruments</button>
          </nav>}
        </> : <p>No currency has a recorded financial observation at this tick.</p>}
        <details><summary>Conditional inheritance rights · {data.contingent_interests.length} paths</summary>
          <p>Each estate must settle its own creditors and reserves before passing any residual onward. These rights have no unconditional cash value.</p>
          {data.contingent_interests.map((row, index) => <p key={index}>{row.beneficiary.name}: {fraction(row.fraction)} of the residual,
            {" "}conditional through {row.estate_path.map(id => data.estate_boundaries.find(boundary => boundary.id === id)?.name || "Estate boundary").join(" → ")}.</p>)}
          {data.estate_boundaries.map(boundary => <section key={boundary.id}>
            <h4>{boundary.name} · {currency}</h4>
            {boundary.by_currency[currency] && <p>Retained wallet cash: {financeMoney(boundary.by_currency[currency].wallet_cash_cents, currency)};
              {" "}restricted cash: {financeMoney(boundary.by_currency[currency].restricted_cash_cents, currency)};
              {" "}receivable face amounts: {financeMoney(boundary.by_currency[currency].receivable_face_cents, currency)};
              {" "}observed equity marks: {financeMoney(boundary.by_currency[currency].observed_equity_marks_cents, currency)};
              {" "}{boundary.by_currency[currency].unpriced_count} unpriced instruments.</p>}
            <ol>{boundary.creditors.filter(row => row.currency === currency).map(row => <li key={row.priority}>{words(row.priority)}: {financeMoney(row.remaining_cents, currency)}</li>)}</ol>
            {boundary.reserve_limits.filter(row => row.currency === currency).map(row => <p key={row.currency}>Unresolved reserve limits: {financeMoney(row.limit_cents, currency)}. These limits are not additional admitted debts or held cash.</p>)}
            <p>Completed distributions stay final. Later claims reach retained assets and future receipts.</p>
          </section>)}
        </details>
      </>}
    </div>}
  </article>;
}

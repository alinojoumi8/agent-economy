import { formatTrust, money, number, percent } from "../api";
import { Badge, Empty, Panel } from "./ui";

export function BanksPanel({ banks }) {
  return (
    <Panel title="Banks" eyebrow="Trust beside fundamentals" className="col-span-full lg:col-span-4">
      <div className="scrollbar max-h-[350px] overflow-auto">
        {banks.length ? <table className="data-table">
          <thead><tr><th>Bank</th><th>Deposits</th><th>Reserves</th><th>Trust</th><th>Status</th></tr></thead>
          <tbody>{banks.map(bank => <tr key={bank.id}>
            <td className="font-semibold text-slate-200">{bank.name}</td>
            <td className="tabular">{money(bank.deposits_cents)}</td>
            <td><div className="tabular">{money(bank.reserves_cents)}</div><div className="text-[10px] text-slate-500">{percent(bank.reserve_ratio)}</div></td>
            <td><div className="mb-1 flex justify-between gap-2 tabular"><span>{formatTrust(bank.avg_trust)}</span></div><div className="h-1 w-16 overflow-hidden rounded bg-ink-700"><div className="h-full bg-mint-300" style={{ width: `${Math.max(0, Math.min(100, Number(bank.avg_trust || 0) * 100))}%` }} /></div></td>
            <td><Badge tone={bank.status === "open" ? "good" : "bad"}>{bank.status}</Badge></td>
          </tr>)}</tbody>
        </table> : <Empty>Banks appear after genesis.</Empty>}
      </div>
      <p className="border-t border-mint-300/10 px-4 py-3 text-[11px] leading-relaxed text-slate-500">Reserve pressure follows actual deposit movement. Trust is the average belief agents hold, so narrative and balance-sheet risk stay visibly separate.</p>
    </Panel>
  );
}

export function FirmsPanel({ firms }) {
  const ticker = firms.filter(firm => firm.status === "listed" && firm.last_stock_price != null);
  return (
    <Panel title="Firms & exchange" eyebrow="Production · payroll · price discovery" className="col-span-full lg:col-span-5">
      <div className="flex min-h-10 items-center gap-2 overflow-x-auto border-b border-mint-300/10 bg-ink-950/35 px-4 py-2" aria-label="Live stock ticker">
        <span className="shrink-0 text-[10px] uppercase tracking-widest text-slate-500">Ticker</span>
        {ticker.length ? ticker.map(firm => <span key={firm.id} className="shrink-0 rounded-full border border-mint-300/10 px-2.5 py-1 text-[10px]"><strong className="mr-1.5 text-slate-300">{firm.name}</strong><span className="tabular text-mint-300">{money(firm.last_stock_price, false)}</span></span>) : <span className="text-[10px] text-slate-600">Awaiting the first agent-priced trade</span>}
      </div>
      <div className="scrollbar max-h-[430px] overflow-auto">
        {firms.length ? <table className="data-table">
          <thead><tr><th>Firm</th><th>Status</th><th>Team</th><th>Goods</th><th>Stock</th><th>Cash</th></tr></thead>
          <tbody>{firms.map(firm => <tr key={firm.id}>
            <td><div className="font-semibold text-slate-200">{firm.name}</div><div className="text-[10px] text-slate-500">{firm.sector || firm.product || "—"}</div></td>
            <td><Badge tone={firm.status === "bankrupt" ? "bad" : firm.status === "listed" ? "good" : "neutral"}>{firm.status}</Badge></td>
            <td className="tabular">{firm.employees}</td>
            <td className="tabular">{money(firm.price_cents, false)}</td>
            <td className="tabular text-mint-300">{money(firm.last_stock_price, false)}</td>
            <td className="tabular">{money(firm.cash_cents)}</td>
          </tr>)}</tbody>
        </table> : <Empty>Firms appear after genesis.</Empty>}
      </div>
    </Panel>
  );
}

export function InstitutionsPanel({ institutions }) {
  const gov = institutions?.government;
  const vc = institutions?.vc;
  const health = institutions?.health;
  return (
    <Panel title="Public & private institutions" eyebrow="Fiscal · VC · healthcare" className="col-span-full lg:col-span-3">
      {!institutions ? <Empty>Loading institutions…</Empty> : <div className="divide-y divide-mint-300/10">
        <article className="p-4">
          <div className="mb-2 flex justify-between"><strong className="text-xs uppercase tracking-wider text-slate-300">Government</strong><Badge tone={gov?.enabled ? "good" : "neutral"}>{gov?.enabled ? "active" : "disabled"}</Badge></div>
          {gov?.enabled && <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs"><dt className="text-slate-500">Tax rate</dt><dd className="text-right tabular">{number(gov.tax_rate_bps / 100, 1)}%</dd><dt className="text-slate-500">Benefit</dt><dd className="text-right tabular">{money(gov.unemployment_benefit_cents)}</dd><dt className="text-slate-500">Treasury</dt><dd className="text-right tabular">{money(gov.treasury_cents)}</dd></dl>}
        </article>
        <article className="p-4">
          <div className="mb-2 flex justify-between"><strong className="text-xs uppercase tracking-wider text-slate-300">Venture capital</strong><Badge tone={vc?.exists ? "good" : "neutral"}>{vc?.exists ? "funded" : "none"}</Badge></div>
          {vc?.exists && <div className="text-xs"><span className="text-slate-500">Dry powder </span><span className="tabular">{money(vc.fund_cents)}</span><div className="mt-1 text-slate-500">{vc.portfolio?.length || 0} portfolio positions</div></div>}
        </article>
        <article className="p-4">
          <div className="mb-2 flex justify-between"><strong className="text-xs uppercase tracking-wider text-slate-300">Health economy</strong><Badge tone={Number(health?.epidemic_multiplier || 1) > 1 ? "bad" : "good"}>×{number(health?.epidemic_multiplier || 1, 1)}</Badge></div>
          <div className="space-y-1 text-xs text-slate-400"><div>{health?.hospital?.name || "No hospital"}</div><div>{health?.insurer?.name || "No insurer"}</div><div className="tabular text-slate-500">{health?.insured_count || 0} insured agents</div></div>
        </article>
      </div>}
    </Panel>
  );
}

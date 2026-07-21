import { money, number, percent } from "../api";
import { firmIdsForRegion } from "../observatoryInteraction";
import { inspectionButtonProps, useObservatoryInteraction } from "./ObservatoryInteraction";
import { Badge, Empty, Panel } from "./ui";

export function BanksPanel({ banks }) {
  const { inspect } = useObservatoryInteraction();
  return (
    <Panel title="Banks" eyebrow="Trust beside fundamentals" className="col-span-full lg:col-span-4">
      <div className="scrollbar max-h-[350px] overflow-auto">
        {banks.length ? <table className="data-table">
          <thead><tr><th>Bank</th><th>Deposits</th><th>Reserves</th><th>Trust</th><th>Status</th></tr></thead>
          <tbody>{banks.map(bank => <tr key={bank.id}>
            <td><button className="inspectable-card !inline-flex !w-auto !px-2 !py-1 text-left" {...inspectionButtonProps(
              inspect,
              { kind: "bank", id: bank.id, title: bank.name },
              bank,
              `Inspect bank ${bank.name}`,
            )}><span className="font-semibold text-slate-200">{bank.name}</span></button></td>
            <td className="tabular">{money(bank.deposits_cents)}</td>
            <td><div className="tabular">{money(bank.reserves_cents)}</div><div className="text-[10px] text-slate-500">{percent(bank.reserve_ratio)}</div></td>
            <td><div className="mb-1 flex justify-between gap-2 tabular"><span>{number(bank.avg_trust, 2)}</span></div><div className="h-1 w-16 overflow-hidden rounded bg-ink-700"><div className="h-full bg-mint-300" style={{ width: `${Math.max(0, Math.min(100, Number(bank.avg_trust || 0) * 100))}%` }} /></div></td>
            <td><Badge tone={bank.status === "open" ? "good" : "bad"}>{bank.status}</Badge></td>
          </tr>)}</tbody>
        </table> : <Empty>Banks appear after genesis.</Empty>}
      </div>
      <p className="border-t border-mint-300/10 px-4 py-3 text-[11px] leading-relaxed text-slate-500">Reserve pressure follows actual deposit movement. Trust is the average belief agents hold, so narrative and balance-sheet risk stay visibly separate.</p>
    </Panel>
  );
}

export function FirmsPanel({ firms, map }) {
  const { regionFocus, inspect } = useObservatoryInteraction();
  return <FirmsPanelView firms={firms} map={map} regionFocus={regionFocus} inspect={inspect} />;
}

export function FirmsPanelView({ firms, map, regionFocus, inspect }) {
  const mappedIds = firmIdsForRegion(map, regionFocus?.regionId);
  const visibleFirms = regionFocus ? firms.filter(firm => mappedIds.has(Number(firm.id))) : firms;
  const firmHeading = regionFocus
    ? `${visibleFirms.length} firms in ${regionFocus.regionName}`
    : "Production · payroll · price discovery";
  const ticker = visibleFirms.filter(firm => firm.status === "listed" && firm.last_stock_price != null);
  return (
    <Panel title="Firms & exchange" eyebrow={firmHeading} className="col-span-full lg:col-span-5">
      <div className="flex min-h-10 items-center gap-2 overflow-x-auto border-b border-mint-300/10 bg-ink-950/35 px-4 py-2" aria-label="Live stock ticker">
        <span className="shrink-0 text-[10px] uppercase tracking-widest text-slate-500">Ticker</span>
        {ticker.length ? ticker.map(firm => <button key={firm.id} className="inspectable-card !w-auto shrink-0 rounded-full !px-2.5 !py-1 text-[10px]" {...inspectionButtonProps(
          inspect,
          { kind: "firm", id: firm.id, title: firm.name },
          firm,
          `Inspect firm ${firm.name}`,
        )}>
          <strong className="mr-1.5 text-slate-300">{firm.name}</strong>
          <span className="tabular text-mint-300">{money(firm.last_stock_price, false)}</span>
        </button>) : <span className="text-[10px] text-slate-600">Awaiting the first agent-priced trade</span>}
      </div>
      <div className="scrollbar max-h-[430px] overflow-auto">
        {visibleFirms.length ? <table className="data-table">
          <thead><tr><th>Firm</th><th>Status</th><th>Team</th><th>Goods</th><th>Stock</th><th>Cash</th></tr></thead>
          <tbody>{visibleFirms.map(firm => <tr key={firm.id}>
            <td><button className="inspectable-card !block !w-auto !px-2 !py-1 text-left" {...inspectionButtonProps(
              inspect,
              { kind: "firm", id: firm.id, title: firm.name },
              firm,
              `Inspect firm ${firm.name}`,
            )}><span className="block font-semibold text-slate-200">{firm.name}</span><span className="block text-[10px] text-slate-500">{firm.sector || firm.product || "—"}</span></button></td>
            <td><Badge tone={firm.status === "bankrupt" ? "bad" : firm.status === "listed" ? "good" : "neutral"}>{firm.status}</Badge></td>
            <td className="tabular">{firm.employees}</td>
            <td className="tabular">{money(firm.price_cents, false)}</td>
            <td className="tabular text-mint-300">{money(firm.last_stock_price, false)}</td>
            <td className="tabular">{money(firm.cash_cents)}</td>
          </tr>)}</tbody>
        </table> : regionFocus
          ? <Empty>No active mapped firms are present in {regionFocus.regionName}.</Empty>
          : <Empty>Firms appear after genesis.</Empty>}
      </div>
    </Panel>
  );
}

export function InstitutionsPanel({ institutions }) {
  const { inspect } = useObservatoryInteraction();
  const gov = institutions?.government;
  const vc = institutions?.vc;
  const health = institutions?.health;
  return (
    <Panel title="Public & private institutions" eyebrow="Fiscal · VC · healthcare" className="col-span-full lg:col-span-3">
      {!institutions ? <Empty>Loading institutions…</Empty> : <div className="divide-y divide-mint-300/10">
        <article className="p-4">
          <div className="mb-2 flex justify-between"><button className="inspectable-card !w-auto !px-2 !py-1 text-left" {...inspectionButtonProps(
            inspect,
            { kind: "institution", id: "government", title: "Government" },
            gov,
            "Inspect institution Government",
          )}><strong className="text-xs uppercase tracking-wider text-slate-300">Government</strong></button><Badge tone={gov?.enabled ? "good" : "neutral"}>{gov?.enabled ? "active" : "disabled"}</Badge></div>
          {gov?.enabled && <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs"><dt className="text-slate-500">Tax rate</dt><dd className="text-right tabular">{number(gov.tax_rate_bps / 100, 1)}%</dd><dt className="text-slate-500">Benefit</dt><dd className="text-right tabular">{money(gov.unemployment_benefit_cents)}</dd><dt className="text-slate-500">Treasury</dt><dd className="text-right tabular">{money(gov.treasury_cents)}</dd></dl>}
        </article>
        <article className="p-4">
          <div className="mb-2 flex justify-between"><button className="inspectable-card !w-auto !px-2 !py-1 text-left" {...inspectionButtonProps(
            inspect,
            { kind: "institution", id: "vc", title: "Venture capital" },
            vc,
            "Inspect institution Venture capital",
          )}><strong className="text-xs uppercase tracking-wider text-slate-300">Venture capital</strong></button><Badge tone={vc?.exists ? "good" : "neutral"}>{vc?.exists ? "funded" : "none"}</Badge></div>
          {vc?.exists && <div className="text-xs"><span className="text-slate-500">Dry powder </span><span className="tabular">{money(vc.fund_cents)}</span><div className="mt-1 text-slate-500">{vc.portfolio?.length || 0} portfolio positions</div></div>}
        </article>
        <article className="p-4">
          <div className="mb-2 flex justify-between"><button className="inspectable-card !w-auto !px-2 !py-1 text-left" {...inspectionButtonProps(
            inspect,
            { kind: "institution", id: "health", title: "Health economy" },
            health,
            "Inspect institution Health economy",
          )}><strong className="text-xs uppercase tracking-wider text-slate-300">Health economy</strong></button><Badge tone={Number(health?.epidemic_multiplier || 1) > 1 ? "bad" : "good"}>×{number(health?.epidemic_multiplier || 1, 1)}</Badge></div>
          <div className="space-y-1 text-xs text-slate-400"><div>{health?.hospital?.name || "No hospital"}</div><div>{health?.insurer?.name || "No insurer"}</div><div className="tabular text-slate-500">{health?.insured_count || 0} insured agents</div></div>
        </article>
      </div>}
    </Panel>
  );
}

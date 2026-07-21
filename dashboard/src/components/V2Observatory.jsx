import { number, shortKind } from "../api";
import { Badge, Empty, Panel } from "./ui";
import { inspectionButtonProps, useObservatoryInteraction } from "./ObservatoryInteraction";

export { EconomicMap } from "./LivingEconomyMap";

function Stat({ label, value, onInspect = null }) {
  if (onInspect) return <button type="button" className="inspectable-card !block rounded-lg border border-mint-300/10 bg-ink-950/40 p-3"
    aria-label={`Inspect startup summary ${label}`} onClick={onInspect}>
    <span className="block text-[10px] uppercase tracking-widest text-slate-600">{label}</span>
    <span className="mt-1 block text-xl font-semibold tabular text-slate-200">{value}</span>
  </button>;
  return <div className="rounded-lg border border-mint-300/10 bg-ink-950/40 p-3"><div className="text-[10px] uppercase tracking-widest text-slate-600">{label}</div><div className="mt-1 text-xl font-semibold tabular text-slate-200">{value}</div></div>;
}

export function InstitutionalPulse({ legal, politics, information, datasets }) {
  const { inspect } = useObservatoryInteraction();
  const bills = politics?.bills || [];
  return <Panel className="col-span-full xl:col-span-4" title="Institutional pulse" eyebrow="LAW · POLICY · NARRATIVE">
    <div className="grid grid-cols-3 gap-2 p-3">
      <Stat label="Contracts" value={legal?.contracts?.length || 0} />
      <Stat label="Matters" value={legal?.items?.length || 0} />
      <Stat label="Bills" value={bills.length} />
    </div>
    <div className="border-t border-mint-300/10 p-3 text-xs">
      <div className="eyebrow mb-2">Active legal docket</div>
      {(legal?.items || []).slice(0, 4).map(item => <div key={item.id} className="mb-2 rounded-lg bg-ink-950/40 p-2">
        <button className="inspectable-card !p-0" {...inspectionButtonProps(
          inspect,
          { kind: "legal_matter", id: item.id, title: item.title || `Matter ${item.id}` },
          item,
          `Inspect legal matter ${item.title || item.id}`,
        )}>
          <span className="min-w-0">
            <strong className="block truncate">{item.title || `Matter ${item.id}`}</strong>
            <span className="mt-1 block text-slate-500">{shortKind(item.matter_type)} · {item.ruleset}</span>
          </span>
          <span className="text-gold-300">{item.status}</span>
        </button>
      </div>)}
      {!legal?.items?.length && <Empty text="No disputes filed." />}
      <div className="eyebrow mb-2 mt-4">Information diffusion</div>
      <p className="text-slate-400">{number(information?.exposure_count || 0, 0)} recorded exposures. Claims retain source-event provenance and agents update beliefs only after exposure.</p>
      <div className="eyebrow mb-2 mt-4">Pinned research grounding</div>
      <p className="text-slate-400">
        {datasets?.manifests?.length || 0} verified dataset snapshots · {datasets?.targets?.length || 0} calibration targets.
        {datasets?.r21_calibration
          ? ` R21 ${datasets.r21_calibration.mode} initialization sampled ${datasets.r21_calibration.households_sampled} households and ${datasets.r21_calibration.firms_sampled} firms from pinned statistical supports; identities remain fictional.`
          : " This run uses fictional synthetic people and firms."}
      </p>
    </div>
  </Panel>;
}

export function LegalPoliticalPanels({ legal, politics, information, startups, markets }) {
  const { inspect } = useObservatoryInteraction();
  const contractStatuses = (legal?.contracts || []).reduce((out, contract) => ({ ...out, [contract.status]: (out[contract.status] || 0) + 1 }), {});
  const startupSummaries = [
    ["Term sheets", startups?.term_sheets?.length || 0],
    ["Funding rounds", startups?.funding_rounds?.length || 0],
    ["IP assets", startups?.ip_assets?.length || 0],
    ["M&A reviews", startups?.mergers?.length || 0],
  ];
  return <>
    <Panel className="col-span-full lg:col-span-4" title="Contracts & obligations" eyebrow="ENFORCEABLE OBJECTS">
      <div className="p-3 text-xs text-slate-400">
        <div className="mb-3 flex flex-wrap gap-2">{Object.entries(contractStatuses).map(([status, count]) => <span key={status} className="rounded-full border border-mint-300/15 px-2 py-1">{status} <b className="text-slate-200">{count}</b></span>)}</div>
        {(legal?.obligations || []).slice(0, 6).map(item => <div key={item.id} className="border-t border-mint-300/10 py-2">
          <button className="inspectable-card !p-0" {...inspectionButtonProps(
            inspect,
            { kind: "legal_obligation", id: item.id, title: shortKind(item.obligation_type) },
            item,
            `Inspect legal obligation ${item.id}`,
          )}>
            <span>{shortKind(item.obligation_type)}</span><span className="text-gold-300">{item.status}</span>
          </button>
        </div>)}
        {!legal?.obligations?.length && <Empty text="No open obligations." />}
      </div>
    </Panel>
    <Panel className="col-span-full lg:col-span-4" title="Bills, votes & lobbying" eyebrow="ENDOGENOUS POLITICS">
      <div className="p-3 text-xs">
        {(politics?.bills || []).slice(0, 6).map(bill => <div key={bill.id} className="mb-2 rounded-lg bg-ink-950/40 p-2">
          <button className="inspectable-card !p-0" {...inspectionButtonProps(
            inspect,
            { kind: "bill", id: bill.id, title: bill.title },
            bill,
            `Inspect bill ${bill.title}`,
          )}>
            <span className="min-w-0">
              <strong className="block truncate">{bill.title}</strong>
              <span className="mt-1 block text-slate-500">{bill.origin_chamber}</span>
            </span>
            <span className="text-mint-300">{shortKind(bill.status)}</span>
          </button>
        </div>)}
        {!politics?.bills?.length && <Empty text="No legislation introduced." />}
        <p className="mt-3 text-slate-500">{politics?.lobbying?.items?.length || 0} disclosed or pending lobbying records in this page. Spending affects salience, never votes directly.</p>
      </div>
    </Panel>
    <Panel className="col-span-full lg:col-span-4" title="Startup lifecycle" eyebrow="FORMATION → EXIT">
      <div className="grid grid-cols-2 gap-2 p-3">{startupSummaries.map(([label, value]) => <Stat key={label} label={label} value={value}
        onInspect={() => inspect(
          { kind: "startup_summary", id: null, title: label },
          { title: label, count: value, description: "Summary from the current startup lifecycle payload." },
        )} />)}</div>
      <div className="space-y-2 px-3 pb-3">{[
        ["term_sheets", startups?.term_sheets],
        ["funding_rounds", startups?.funding_rounds],
        ["ip_assets", startups?.ip_assets],
        ["mergers", startups?.mergers],
      ].flatMap(([collection, records]) => (records || []).slice(0, 2).map(record => {
        const title = record.title || record.name || `${shortKind(collection)} ${record.id}`;
        return <button key={`${collection}-${record.id}`} className="inspectable-card bg-ink-950/40 text-xs"
          {...inspectionButtonProps(
            inspect,
            { kind: "startup_record", id: record.id, collection, title },
            record,
            `Inspect startup record ${title}`,
          )}>
          <span>{title}</span><Badge>{shortKind(record.status || collection)}</Badge>
        </button>;
      }))}</div>
      <div className="px-3 pb-3 text-xs text-slate-500">{markets?.fx_trades?.length || 0} FX trades · {markets?.trades?.length || 0} stock trades · {information?.items?.length || 0} narrative items</div>
    </Panel>
  </>;
}

import { number, shortKind } from "../api";
import { Empty, Panel } from "./ui";

const REGION_COLORS = ["#79e6bd", "#f7d783", "#ff9788"];

export function EconomicMap({ map }) {
  const regions = map?.regions || [];
  const byId = Object.fromEntries(regions.map(region => [region.id, region]));
  return <Panel className="col-span-full xl:col-span-8" title="Living economy map" eyebrow="TRADE · CAPITAL · MIGRATION">
    {!regions.length ? <Empty text={map?.enabled === false
      ? "Regional economy disabled for this run profile. Use the institutional Observatory rehearsal to activate it."
      : "No regional economy data has been recorded yet."} /> :
      <div className="p-3">
        <svg viewBox="0 0 1000 430" role="img" aria-label="Regional economy map with trade and migration flows" className="h-auto w-full rounded-xl bg-ink-950/55">
          <defs><marker id="flow-arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" fill="#9aefcf" /></marker></defs>
          {(map.flows || []).map((flow, index) => {
            const source = byId[flow.source_region_id], target = byId[flow.target_region_id];
            if (!source || !target) return null;
            return <line key={`${flow.kind}-${flow.id}-${index}`} x1={source.x * 1000} y1={source.y * 430} x2={target.x * 1000} y2={target.y * 430}
              stroke={flow.kind === "trade" ? "#79e6bd" : "#f7d783"} strokeOpacity=".45" strokeWidth={Math.min(7, 1 + Number(flow.magnitude || 1) / 20)} markerEnd="url(#flow-arrow)" />;
          })}
          {regions.map((region, index) => <g key={region.id} transform={`translate(${region.x * 1000} ${region.y * 430})`}>
            <circle r={54 + Math.sqrt(Number(region.population || 0))} fill={REGION_COLORS[index % 3]} fillOpacity=".12" stroke={REGION_COLORS[index % 3]} strokeWidth="2" />
            <text textAnchor="middle" y="-8" fill="#e7f1ed" fontSize="17" fontWeight="700">{region.name}</text>
            <text textAnchor="middle" y="16" fill="#9fb8af" fontSize="13">{number(region.population, 0)} agents · {region.currency_code}</text>
            <text textAnchor="middle" y="36" fill="#78938a" fontSize="11">{region.firms} firms</text>
          </g>)}
          {(map.core_agents || []).slice(0, 100).map(agent => <circle key={agent.id}
            cx={agent.x * 1000 + ((agent.id * 17) % 70 - 35)} cy={agent.y * 430 + ((agent.id * 29) % 70 - 35)} r="2.4" fill="#fff" fillOpacity=".62"><title>{agent.name} · {agent.role || agent.occupation}</title></circle>)}
        </svg>
        <div className="mt-3 flex flex-wrap gap-4 text-[11px] text-slate-500"><span><b className="text-mint-300">●</b> trade</span><span><b className="text-gold-300">●</b> migration</span><span><b className="text-white">●</b> core strategic agent</span><span>{map.firms?.length || 0} active firms plotted</span></div>
      </div>}
  </Panel>;
}

function Stat({ label, value }) {
  return <div className="rounded-lg border border-mint-300/10 bg-ink-950/40 p-3"><div className="text-[10px] uppercase tracking-widest text-slate-600">{label}</div><div className="mt-1 text-xl font-semibold tabular text-slate-200">{value}</div></div>;
}

export function InstitutionalPulse({ legal, politics, information, datasets }) {
  const bills = politics?.bills || [];
  const billsEnabled = politics?.enabled !== false && politics?.institutional_actions_enabled !== false;
  const legalItems = legal?.enabled === false ? [] : legal?.items || [];
  return <Panel className="col-span-full xl:col-span-4" title="Institutional pulse" eyebrow="LAW · POLICY · NARRATIVE">
    <div className="grid grid-cols-3 gap-2 p-3">
      <Stat label="Contracts" value={legal?.enabled === false ? "Off" : legal?.contracts?.length || 0} />
      <Stat label="Matters" value={legal?.enabled === false ? "Off" : legal?.items?.length || 0} />
      <Stat label="Bills" value={billsEnabled ? bills.length : "Off"} />
    </div>
    <div className="border-t border-mint-300/10 p-3 text-xs">
      <div className="eyebrow mb-2">Active legal docket</div>
      {legalItems.slice(0, 4).map(item => <div key={item.id} className="mb-2 rounded-lg bg-ink-950/40 p-2">
        <div className="flex justify-between gap-2"><b>{item.title || `Matter ${item.id}`}</b><span className="text-gold-300">{shortKind(item.status)}</span></div>
        <div className="mt-1 text-slate-500">{shortKind(item.matter_type)} · {item.ruleset_key || item.venue}</div>
      </div>)}
      {!legalItems.length && <Empty text={legal?.enabled === false
        ? "Legal institution disabled for this run profile."
        : "No disputes filed."} />}
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
  const contractStatuses = (legal?.contracts || []).reduce((out, contract) => ({ ...out, [contract.status]: (out[contract.status] || 0) + 1 }), {});
  const billsEnabled = politics?.enabled !== false && politics?.institutional_actions_enabled !== false;
  const bills = billsEnabled ? politics?.bills || [] : [];
  return <>
    <Panel className="col-span-full lg:col-span-4" title="Contracts & obligations" eyebrow="ENFORCEABLE OBJECTS">
      <div className="p-3 text-xs text-slate-400">
        <div className="mb-3 flex flex-wrap gap-2">{Object.entries(contractStatuses).map(([status, count]) => <span key={status} className="rounded-full border border-mint-300/15 px-2 py-1">{status} <b className="text-slate-200">{count}</b></span>)}</div>
        {(legal?.obligations || []).slice(0, 6).map(item => <div key={item.id} className="flex justify-between border-t border-mint-300/10 py-2"><span>{shortKind(item.obligation_type)}</span><span className="text-gold-300">{item.status}</span></div>)}
        {!legal?.obligations?.length && <Empty text="No open obligations." />}
      </div>
    </Panel>
    <Panel className="col-span-full lg:col-span-4" title="Bills, votes & lobbying" eyebrow="ENDOGENOUS POLITICS">
      <div className="p-3 text-xs">
        {bills.slice(0, 6).map(bill => <div key={bill.id} className="mb-2 rounded-lg bg-ink-950/40 p-2"><b>{bill.title}</b><div className="mt-1 flex justify-between text-slate-500"><span>{bill.origin_chamber}</span><span className="text-mint-300">{shortKind(bill.status)}</span></div></div>)}
        {!bills.length && <Empty text={billsEnabled
          ? "No legislation introduced."
          : "Institutional role actions are disabled for this run profile."} />}
        <p className="mt-3 text-slate-500">{politics?.lobbying?.items?.length || 0} disclosed or pending lobbying records in this page. Spending affects salience, never votes directly.</p>
      </div>
    </Panel>
    <Panel className="col-span-full lg:col-span-4" title="Startup lifecycle" eyebrow="FORMATION → EXIT">
      <div className="grid grid-cols-2 gap-2 p-3"><Stat label="Term sheets" value={startups?.term_sheets?.length || 0} /><Stat label="Funding rounds" value={startups?.funding_rounds?.length || 0} /><Stat label="IP assets" value={startups?.ip_assets?.length || 0} /><Stat label="M&A reviews" value={startups?.mergers?.length || 0} /></div>
      <div className="px-3 pb-3 text-xs text-slate-500">{markets?.fx_trades?.length || 0} FX trades · {markets?.trades?.length || 0} stock trades · {information?.items?.length || 0} narrative items</div>
    </Panel>
  </>;
}

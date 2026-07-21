import { number } from "../api";
import { Badge, Empty, Panel } from "./ui";
import { inspectionButtonProps, useObservatoryInteraction } from "./ObservatoryInteraction";

export function AcceptancePanel({ acceptance }) {
  const { inspect } = useObservatoryInteraction();
  if (!acceptance?.configured) return null;
  const checks = acceptance.checks || [];
  const passed = checks.filter(check => check.passed).length;
  const progress = acceptance.progress || {};
  const fraction = Math.max(0, Math.min(1, Number(progress.fraction || 0)));
  const rumor = checks.find(check => check.id === "rumor_pilot")?.evidence || {};
  const shockTraces = checks.find(check => check.id === "shock_traces")?.evidence || {};
  const orchestration = acceptance.orchestration || {};
  const dollars = value => value === null || value === undefined ? "—" : `$${number(value, 2)}`;
  return (
    <Panel title="Acceptance evidence" eyebrow="Live progress · fail closed" className="col-span-full"
      action={<Badge tone={acceptance.passed ? "good" : "warn"}>{passed}/{checks.length} gates</Badge>}>
      <div className="grid gap-4 xl:grid-cols-[1fr_1.4fr_1.4fr]">
        <section>
          <div className="mb-2 flex justify-between text-xs"><span className="text-slate-500">Run horizon</span><span className="tabular">{progress.completed_ticks || 0}/{progress.required_ticks || 0} days</span></div>
          <div className="h-2 overflow-hidden rounded-full bg-ink-950" role="progressbar" aria-label="Acceptance run horizon" aria-valuemin="0" aria-valuemax="100" aria-valuenow={Math.round(fraction * 100)}><div className="h-full bg-mint-300" style={{ width: `${fraction * 100}%` }} /></div>
          <dl className="mt-4 grid grid-cols-2 gap-2 text-xs">
            <dt className="text-slate-500">Actual spend</dt><dd className="tabular">{dollars(progress.actual_spend_usd)}</dd>
            <dt className="text-slate-500">Projected spend</dt><dd className="tabular">{dollars(progress.projected_spend_usd)}</dd>
            <dt className="text-slate-500">Efficiency target</dt><dd className="tabular">{dollars(progress.efficiency_target_usd)}</dd>
            <dt className="text-slate-500">Oracle samples</dt><dd className="tabular">{progress.oracle_latency_samples || 0}/{progress.oracle_min_latency_samples || 0}</dd>
            <dt className="text-slate-500">Orchestrator</dt><dd><Badge tone={orchestration.state === "invalid" ? "bad" : orchestration.authorized ? "good" : "warn"}>{orchestration.state || "not authorized"}</Badge></dd>
            <dt className="text-slate-500">Next checkpoint</dt><dd className="tabular">{orchestration.next_checkpoint ? `day ${orchestration.next_checkpoint.scheduled_tick}` : "—"}</dd>
          </dl>
          {orchestration.missed?.length > 0 && <div className="mt-3 rounded-lg border border-coral-300/20 bg-coral-300/[.05] p-2 text-xs text-coral-300">Missed Oracle checkpoint at day {orchestration.missed[0].scheduled_tick}. This run cannot produce a clean receipt.</div>}
          {rumor.exposed_agents > 0 && <dl className="mt-4 grid grid-cols-2 gap-2 border-t border-mint-300/10 pt-3 text-xs">
            <dt className="text-slate-500">Rumor exposed</dt><dd className="tabular">{rumor.exposed_agents}</dd>
            <dt className="text-slate-500">Relative trust drops</dt><dd className="tabular">{rumor.trust_drop_agents || 0} · {number(Number(rumor.trust_drop_share || 0) * 100, 1)}%</dd>
            <dt className="text-slate-500">Conversations</dt><dd className="tabular">{rumor.rumor_conversations_10_ticks || 0}</dd>
            <dt className="text-slate-500">Post-rumor outflow</dt><dd className="tabular">{dollars(Number(rumor.post_outflow_cents_10_ticks || 0) / 100)}</dd>
          </dl>}
        </section>
        <section className="scrollbar max-h-56 overflow-y-auto pr-2">
          {checks.length ? checks.map(check => <article key={check.id} className="border-t border-mint-300/10 py-2 first:border-0"><div className="flex items-start justify-between gap-3 text-xs">
            <button className="inspectable-card !w-auto !p-0" {...inspectionButtonProps(
              inspect,
              { kind: "acceptance_check", id: check.id, title: check.label },
              check,
              `Inspect acceptance check ${check.label}`,
            )}><span>{check.label}</span></button>
            <Badge tone={check.passed ? "good" : "warn"}>{check.passed ? "passed" : "pending"}</Badge>
          </div><div className="mt-1 text-[10px] text-slate-600">{check.id}</div></article>) : <Empty>No acceptance checks are configured.</Empty>}
        </section>
        <section className="scrollbar max-h-56 overflow-y-auto pr-2">
          <div className="eyebrow mb-2">Shock traces</div>
          {Object.keys(shockTraces).length ? Object.entries(shockTraces).map(([kind, trace]) => <article key={kind} className="border-t border-mint-300/10 py-2 first:border-0">
            <button className="inspectable-card !p-0" {...inspectionButtonProps(
              inspect,
              { kind: "shock_trace", id: kind, title: `${kind.replaceAll("_", " ")} shock trace` },
              { id: kind, kind, ...trace },
              `Inspect ${kind.replaceAll("_", " ")} shock trace`,
            )}>
              <span><span className="block text-xs capitalize">{kind.replaceAll("_", " ")}</span><span className="mt-1 block text-[10px] text-slate-600">day {trace?.source?.tick ?? "—"} · {(trace?.downstream || []).length || (trace?.downstream ? 1 : 0)} downstream</span></span>
              <Badge tone={trace?.passed ? "good" : "warn"}>{trace?.passed ? "traced" : "pending"}</Badge>
            </button>
          </article>) : <Empty>Shock evidence appears after configured shocks fire.</Empty>}
        </section>
      </div>
    </Panel>
  );
}

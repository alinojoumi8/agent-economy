import { Area, AreaChart, ResponsiveContainer, Tooltip } from "recharts";
import { formatMetricDelta, formatMetricValue } from "../api";
import { rollingSumSeries } from "../metrics";
import { Panel } from "./ui";

const DEFINITIONS = [
  ["gdp_proxy_30d", "30-day output", "Rolling final-goods sales; wages are reported separately", "#79e6bd"],
  ["labor_income", "30-day labor income", "Rolling gross wages paid during this day and the preceding 29 days", "#fbbf24"],
  ["cpi", "Price level", "Goods-price index", "#f7d783"],
  ["unemployment", "Unemployment", "Living, non-retired working-age citizens without active employment or an operating firm", "#ff9788"],
  ["index", "Market index", "Listed-firm prices", "#93c5fd"],
  ["policy_rate", "Policy rate", "Central-bank rate", "#c4b5fd"],
  ["money_supply", "Money supply", "Deposits in circulation", "#67e8f9"],
  ["gini", "Gini", "Balance inequality", "#f0abfc"],
  ["sentiment", "Sentiment", "Average belief", "#86efac"],
];

export function MacroOverview({ metrics }) {
  return (
    <Panel title="Macro pulse" eyebrow="Engine-measured · never narrated" className="col-span-full">
      <div className="grid grid-cols-2 gap-px bg-mint-300/10 sm:grid-cols-3 xl:grid-cols-9">
        {DEFINITIONS.map(([key, label, help, color]) => {
          const sourceSeries = metrics[key] || [];
          const series = key === "labor_income" ? rollingSumSeries(sourceSeries, 30) : sourceSeries;
          const latest = series.at(-1)?.value;
          const previous = series.at(-2)?.value;
          const delta = previous === undefined ? null : Number(latest) - Number(previous);
          return (
            <article key={key} className="min-w-0 bg-ink-900/95 px-3 py-3" title={help}>
              <div className="truncate text-[10px] font-semibold uppercase tracking-[.12em] text-slate-500">{label}</div>
              <div className="mt-1 flex items-baseline gap-2">
                <strong className="tabular truncate text-lg font-semibold text-slate-100">{formatMetricValue(key, latest)}</strong>
                {delta !== null && <span className={`tabular text-[10px] ${delta > 0 ? "text-mint-300" : delta < 0 ? "text-coral-300" : "text-slate-600"}`}>{formatMetricDelta(key, delta)}</span>}
              </div>
              <div className="mt-2 h-10" aria-hidden="true">
                {series.length > 1 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={series} accessibilityLayer={false} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
                      <defs><linearGradient id={`fill-${key}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={color} stopOpacity={.35}/><stop offset="100%" stopColor={color} stopOpacity={0}/></linearGradient></defs>
                      <Tooltip content={() => null} />
                      <Area type="monotone" dataKey="value" stroke={color} strokeWidth={1.5} fill={`url(#fill-${key})`} isAnimationActive={false} />
                    </AreaChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="pt-3 text-[9px] leading-tight text-slate-600">
                    {key === "index"
                      ? (series.length ? "Awaiting another market close" : "Awaiting first listed firm")
                      : "Awaiting metric history"}
                  </div>
                )}
              </div>
            </article>
          );
        })}
      </div>
    </Panel>
  );
}

export default MacroOverview;

import { Area, AreaChart, ResponsiveContainer, Tooltip } from "recharts";
import { number, percent } from "../api";
import { Panel } from "./ui";

const DEFINITIONS = [
  ["gdp_proxy_30d", "30-day output", "Rolling final-goods sales; wages are reported separately", "#79e6bd"],
  ["labor_income", "Labor income", "Gross wages paid during this day", "#fbbf24"],
  ["cpi", "Price level", "Goods-price index", "#f7d783"],
  ["unemployment", "Unemployment", "Share seeking work", "#ff9788"],
  ["index", "Market index", "Listed-firm prices", "#93c5fd"],
  ["policy_rate", "Policy rate", "Central-bank rate", "#c4b5fd"],
  ["money_supply", "Money supply", "Deposits in circulation", "#67e8f9"],
  ["gini", "Gini", "Balance inequality", "#f0abfc"],
  ["sentiment", "Sentiment", "Average belief", "#86efac"],
];

function display(name, value) {
  if (name === "unemployment") return percent(value);
  if (name === "policy_rate") return `${number(value, 0)} bps`;
  if (name === "money_supply" || name === "gdp_proxy" || name === "gdp_proxy_30d" || name === "labor_income") return new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(Number(value || 0));
  return number(value, name === "cpi" || name === "gini" || name === "sentiment" ? 3 : 2);
}

export function MacroOverview({ metrics }) {
  return (
    <Panel title="Macro pulse" eyebrow="Engine-measured · never narrated" className="col-span-full">
      <div className="grid grid-cols-2 gap-px bg-mint-300/10 sm:grid-cols-3 xl:grid-cols-9">
        {DEFINITIONS.map(([key, label, help, color]) => {
          const series = metrics[key] || [];
          const latest = series.at(-1)?.value;
          const previous = series.at(-2)?.value;
          const delta = previous === undefined ? null : Number(latest) - Number(previous);
          return (
            <article key={key} className="min-w-0 bg-ink-900/95 px-3 py-3" title={help}>
              <div className="truncate text-[10px] font-semibold uppercase tracking-[.12em] text-slate-500">{label}</div>
              <div className="mt-1 flex items-baseline gap-2">
                <strong className="tabular truncate text-lg font-semibold text-slate-100">{display(key, latest)}</strong>
                {delta !== null && <span className={`tabular text-[10px] ${delta > 0 ? "text-mint-300" : delta < 0 ? "text-coral-300" : "text-slate-600"}`}>{delta > 0 ? "+" : ""}{number(delta, 2)}</span>}
              </div>
              <div className="mt-2 h-10" aria-label={`${label} history`}>
                {series.length > 1 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={series} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
                      <defs><linearGradient id={`fill-${key}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={color} stopOpacity={.35}/><stop offset="100%" stopColor={color} stopOpacity={0}/></linearGradient></defs>
                      <Tooltip content={() => null} />
                      <Area type="monotone" dataKey="value" stroke={color} strokeWidth={1.5} fill={`url(#fill-${key})`} isAnimationActive={false} />
                    </AreaChart>
                  </ResponsiveContainer>
                ) : <div className="mt-4 h-px bg-mint-300/10" />}
              </div>
            </article>
          );
        })}
      </div>
    </Panel>
  );
}

export default MacroOverview;

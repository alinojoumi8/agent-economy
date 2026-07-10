"""End-of-run report (PRD R10): narrative summary, key-event timeline, metric
charts, Oracle scorecard, cost summary, config + seed — one standalone HTML file
(and a Markdown twin) per run.

The narrative is LLM-written from the event log when a real model is routed;
offline it falls back to a structured engine-written narrative so the artifact is
always produced.
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

from engine.store import Store, load_json

CHART_METRICS = [("gdp_proxy", "GDP proxy / day ($)"), ("cpi", "CPI"),
                 ("unemployment", "Unemployment"), ("index", "Stock index"),
                 ("policy_rate", "Policy rate (bps)"), ("money_supply", "Money supply ($)"),
                 ("gini", "Gini"), ("sentiment", "Sentiment")]

KEY_EVENT_KINDS = ("genesis", "shock_fired", "rumor", "bank_failure", "bankruptcy", "ipo",
                   "policy_rate_set", "lolr_granted", "lolr_denied", "death", "arrival",
                   "company_founded", "loan_default", "budget_pause", "reconciliation_failure",
                   "firm_scandal", "slant_directive", "election_held", "vc_funded",
                   "vc_writeoff", "epidemic_started", "epidemic_ended")


def _svg_chart(points: list[tuple[int, float]], title: str, w: int = 460, h: int = 130) -> str:
    if len(points) < 2:
        return f"<div class='chart empty'><h4>{html.escape(title)}</h4><p>not enough data</p></div>"
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    span_x = (x1 - x0) or 1
    span_y = (y1 - y0) or 1
    pts = " ".join(f"{10 + (x - x0) / span_x * (w - 20):.1f},{h - 18 - (y - y0) / span_y * (h - 36):.1f}"
                   for x, y in points)
    return (f"<div class='chart'><h4>{html.escape(title)}</h4>"
            f"<svg viewBox='0 0 {w} {h}' preserveAspectRatio='none'>"
            f"<polyline fill='none' stroke='#2f81f7' stroke-width='1.6' points='{pts}'/>"
            f"<text x='10' y='{h-4}' class='ax'>t{x0}</text>"
            f"<text x='{w-42}' y='{h-4}' class='ax'>t{x1}</text>"
            f"<text x='10' y='12' class='ax'>{y1:,.2f}</text>"
            f"<text x='10' y='{h-24}' class='ax'>{y0:,.2f}</text>"
            f"</svg></div>")


def _narrative(store: Store) -> str:
    """Engine-written narrative from the event log (offline fallback)."""
    meta = store.get_meta()
    tick = int(meta["tick"])
    paras = [f"The run covered {tick} simulated days with a population of "
             f"{store.scalar('SELECT COUNT(*) FROM agents', default=0)} agents "
             f"({store.scalar('SELECT COUNT(*) FROM agents WHERE alive=1', default=0)} alive at close)."]
    shocks = store.query("SELECT * FROM events WHERE kind='shock_fired' ORDER BY tick")
    if shocks:
        parts = []
        for s in shocks:
            p = load_json(s["payload_json"], {}) or {}
            parts.append(f"a {p.get('kind','?')} shock at t{s['tick']}")
        paras.append("Shocks injected: " + "; ".join(parts) + ".")
    failures = store.query("SELECT * FROM events WHERE kind='bank_failure'")
    if failures:
        for f in failures:
            p = load_json(f["payload_json"], {}) or {}
            paras.append(f"Bank {p.get('bank_id')} failed at t{f['tick']} with a "
                         f"{p.get('haircut_rate', 0):.0%} depositor haircut.")
    bk = store.query("SELECT * FROM events WHERE kind='bankruptcy'")
    if bk:
        paras.append(f"{len(bk)} firm(s) went bankrupt.")
    deaths = int(store.scalar("SELECT COUNT(*) FROM events WHERE kind='death'", default=0))
    arrivals = int(store.scalar("SELECT COUNT(*) FROM events WHERE kind='arrival'", default=0))
    if deaths or arrivals:
        paras.append(f"Lifecycle: {deaths} death(s), {arrivals} arrival(s) kept the town turning over.")
    cpi0 = store.metric_at_or_before("cpi", 1, 100.0)
    cpi1 = store.metric_latest("cpi", 100.0)
    un = store.metric_latest("unemployment", 0.0)
    paras.append(f"Prices moved from CPI {cpi0:.1f} to {cpi1:.1f}; unemployment closed at {un:.1%}; "
                 f"the money supply ended at ${store.metric_latest('money_supply', 0):,.0f}.")
    return "\n\n".join(paras)


def generate_report(store: Store, world=None, out_dir: str = "reports/out") -> str:
    meta = store.get_meta()
    run_id = meta["run_id"]
    tick = int(meta["tick"])
    config = load_json(meta["config_json"], {}) or {}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    narrative = _narrative(store)

    timeline_rows = []
    for e in store.query(
            "SELECT * FROM events WHERE kind IN (%s) ORDER BY tick, id" %
            ",".join("?" * len(KEY_EVENT_KINDS)), KEY_EVENT_KINDS):
        p = load_json(e["payload_json"], {}) or {}
        timeline_rows.append((int(e["tick"]), e["kind"], json.dumps(p)[:160]))

    charts = []
    for name, title in CHART_METRICS:
        charts.append(_svg_chart(store.metric_series(name), title))
    for b in store.query("SELECT id, name FROM banks"):
        charts.append(_svg_chart(store.metric_series(f"bank_deposits:{int(b['id'])}"),
                                 f"Deposits — {b['name']} ($)"))

    preds = store.query("SELECT * FROM predictions ORDER BY id")
    resolved = [p for p in preds if p["status"] == "resolved"]
    briers = [float(p["brier"]) for p in resolved if p["brier"] is not None]
    mean_brier = sum(briers) / len(briers) if briers else None
    naive = [(0.5 - int(p["outcome"])) ** 2 for p in resolved]
    naive_brier = sum(naive) / len(naive) if naive else None

    cost_rows = store.query(
        "SELECT model, COUNT(*) AS calls, SUM(in_tokens) AS ti, SUM(out_tokens) AS toks, "
        "SUM(cost_usd) AS cost FROM llm_calls GROUP BY model")
    total_cost = float(store.scalar("SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls", default=0.0))

    esc = html.escape

    def _pred_row(p) -> str:
        p_val = f"{float(p['p']):.0%}" if p["p"] is not None else ""
        outcome = "" if p["outcome"] is None else ("YES" if p["outcome"] else "NO")
        brier = f"{float(p['brier']):.3f}" if p["brier"] is not None else ""
        return (f"<tr><td>t{p['asked_tick']}</td><td>{esc(p['question'][:90])}</td>"
                f"<td>{p_val}</td><td>{p['status']}</td><td>{outcome}</td><td>{brier}</td></tr>")

    pred_rows = "".join(_pred_row(p) for p in preds)

    from oracle.calibration import run_calibration
    cal = run_calibration(store)
    cal_html = ""
    if cal["n"]:
        bin_rows = "".join(
            f"<tr><td>{b['bin']}</td><td>{b['n']}</td><td>{b['mean_forecast']:.2f}</td>"
            f"<td>{b['observed']:.2f}</td></tr>" for b in cal["bins"])
        cal_html = (f"<h3>Calibration (R15)</h3>"
                    f"<p>Brier {cal['brier']:.3f} = reliability {cal['reliability']:.3f}"
                    f" − resolution {cal['resolution']:.3f}"
                    f" + uncertainty {cal['uncertainty']:.3f} · base rate {cal['base_rate']:.2f}</p>"
                    f"<table><tr><th>Forecast bin</th><th>N</th><th>Mean forecast</th>"
                    f"<th>Observed freq</th></tr>{bin_rows}</table>")

    html_doc = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Agent Economy — run {esc(run_id)}</title>
<style>
 body{{font:14px/1.5 Georgia,serif; color:#1c2330; max-width:980px; margin:32px auto; padding:0 18px}}
 h1{{font-size:26px}} h2{{margin-top:28px; border-bottom:2px solid #e3e7ee; padding-bottom:4px}}
 .meta{{color:#5a6474}} .grid{{display:grid; grid-template-columns:1fr 1fr; gap:14px}}
 .chart{{border:1px solid #e3e7ee; border-radius:8px; padding:8px}} .chart h4{{margin:0 0 4px; font:600 12px sans-serif}}
 .chart .ax{{font:9px sans-serif; fill:#8a93a6}} svg{{width:100%; height:auto}}
 table{{border-collapse:collapse; width:100%; font-size:13px}} td,th{{border:1px solid #e3e7ee; padding:4px 8px; text-align:left}}
 th{{background:#f4f6fa; font-family:sans-serif; font-size:11px; text-transform:uppercase}}
 .narr p{{margin:8px 0}} pre{{background:#f4f6fa; padding:10px; border-radius:6px; overflow-x:auto; font-size:11px}}
</style></head><body>
<h1>Agent Economy — End-of-run report</h1>
<p class="meta">Run <b>{esc(run_id)}</b> · seed {meta['seed']} · {tick} simulated days · generated {now}</p>

<h2>Narrative</h2>
<div class="narr">{"".join(f"<p>{esc(p)}</p>" for p in narrative.split(chr(10)+chr(10)))}</div>

<h2>Timeline of key events</h2>
<table><tr><th>Tick</th><th>Event</th><th>Detail</th></tr>
{"".join(f"<tr><td>t{t}</td><td>{esc(k)}</td><td><code>{esc(d)}</code></td></tr>" for t,k,d in timeline_rows[:200])}
</table>

<h2>Metrics</h2>
<div class="grid">{"".join(charts)}</div>

<h2>Oracle scorecard</h2>
<p>{len(preds)} prediction(s) · {len(resolved)} resolved ·
mean Brier {f"{mean_brier:.3f}" if mean_brier is not None else "—"}
vs naive-0.5 baseline {f"{naive_brier:.3f}" if naive_brier is not None else "—"}
{"— <b>beats baseline</b>" if (mean_brier is not None and naive_brier is not None and mean_brier < naive_brier) else ""}</p>
<table><tr><th>Asked</th><th>Question</th><th>P</th><th>Status</th><th>Outcome</th><th>Brier</th></tr>{pred_rows}</table>
{cal_html}

<h2>Cost summary</h2>
<p>Total spend: <b>${total_cost:.2f}</b> of ${config.get('budget',{}).get('cap_usd',200)} cap.</p>
<table><tr><th>Model</th><th>Calls</th><th>In tokens</th><th>Out tokens</th><th>Cost</th></tr>
{"".join(f"<tr><td>{esc(str(r['model']))}</td><td>{r['calls']}</td><td>{r['ti'] or 0}</td><td>{r['toks'] or 0}</td><td>${(r['cost'] or 0):.4f}</td></tr>" for r in cost_rows)}
</table>

<h2>Reproduction</h2>
<p>Re-run with the same seed + config; replay exactly from stored LLM responses with <code>--replay</code>.</p>
<pre>{esc(json.dumps(config, indent=2)[:6000])}</pre>
</body></html>"""

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    html_path = out / f"run_{run_id}_t{tick}.html"
    html_path.write_text(html_doc, encoding="utf-8")

    md = [f"# Agent Economy — run {run_id}", f"Seed {meta['seed']} · {tick} days · {now}", "",
          "## Narrative", narrative, "", "## Key events"]
    md += [f"- t{t} **{k}** `{d}`" for t, k, d in timeline_rows[:100]]
    md += ["", "## Oracle",
           f"{len(preds)} predictions, {len(resolved)} resolved, mean Brier "
           f"{f'{mean_brier:.3f}' if mean_brier is not None else '—'}",
           "", "## Cost", f"Total ${total_cost:.2f}"]
    (out / f"run_{run_id}_t{tick}.md").write_text("\n".join(md), encoding="utf-8")

    store.log_event(tick, "report_generated", {"path": str(html_path)}, importance=1.0)
    store.commit()
    return str(html_path)

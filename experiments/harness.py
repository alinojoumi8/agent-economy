"""Experiment harness (P1 R14).

An experiment = {config, seed set, shock schedule, metrics of interest}. The
harness runs every seed through a TREATMENT arm (with the experiment's shocks)
and, when `control: true`, a CONTROL arm (same seed, no shocks), then writes a
comparison report with outcome distributions — so a robust effect separates from
one-off noise exactly as PRD Goal 4 asks.

Spec (YAML file or dict):

    name: rumor_bank_run
    base_config: runs/base.yaml        # optional; `config:` inlines one instead
    overrides: {population: {size: 24}}  # deep-merged over the base config
    seeds: [1, 2, 3]                   # or n_seeds: 5 → seeds 1..5
    ticks: 40
    control: true                      # run a no-shock twin per seed
    shocks:
      - {kind: rumor, trigger: shock, trigger_params: {tick: 10},
         params: {bank_id: 1, n_agents: 14}}
    metrics: [unemployment, cpi, index, bank_deposits:1]
    event_outcomes: [bank_failure, bankruptcy, death]

Run: `python run.py --experiment spec.yaml` or `python -m experiments.harness spec.yaml`.
Run databases land in data/experiments/<name>/ (kept out of data/runs so the
replay catalogue stays a catalogue of real runs).
"""
from __future__ import annotations

import asyncio
import html as _html
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

import yaml

from engine.store import Store
from world.loop import World


# ── config plumbing ──────────────────────────────────────────────────────────
def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_spec(path_or_dict) -> dict:
    if isinstance(path_or_dict, dict):
        spec = dict(path_or_dict)
    else:
        with open(path_or_dict, "r", encoding="utf-8") as f:
            spec = yaml.safe_load(f) or {}
    if "config" not in spec:
        base = spec.get("base_config", "runs/base.yaml")
        with open(base, "r", encoding="utf-8") as f:
            spec["config"] = yaml.safe_load(f) or {}
    spec["config"] = _deep_merge(spec["config"], spec.get("overrides", {}))
    if not spec.get("seeds"):
        spec["seeds"] = list(range(1, int(spec.get("n_seeds", 3)) + 1))
    spec.setdefault("name", "experiment")
    spec.setdefault("ticks", 30)
    spec.setdefault("control", True)
    spec.setdefault("metrics", ["unemployment", "cpi", "index", "gdp_proxy"])
    spec.setdefault("event_outcomes", ["bank_failure", "bankruptcy", "death"])
    return spec


# ── one run of one arm ───────────────────────────────────────────────────────
def _run_arm(spec: dict, seed: int, arm: str, data_dir: Path) -> dict:
    cfg = json.loads(json.dumps(spec["config"]))   # deep copy
    cfg["seed"] = seed
    cfg["checkpoint_every"] = 0
    cfg["speed_delay_s"] = 0.0
    cfg["shocks"] = spec.get("shocks", []) if arm == "treatment" else []
    run_id = f"{spec['name']}_s{seed}_{arm}"
    db = data_dir / f"{run_id}.db"
    if db.exists():
        db.unlink()   # experiments are derived artifacts; a re-run replaces them
    store = Store(str(db))
    store.init_run_meta(run_id, seed, cfg)
    world = World(store, cfg)
    world.initialize()

    async def go():
        await world.run(max_ticks=int(spec["ticks"]))
    asyncio.run(go())

    ok, diag = world.economy.ledger.reconcile()
    result = {"run_id": run_id, "seed": seed, "arm": arm, "ticks": store.tick,
              "reconciled": ok, "metrics": {}, "series": {}, "events": {}}
    for name in spec["metrics"]:
        series = store.metric_series(name)
        result["series"][name] = series
        result["metrics"][name] = float(series[-1][1]) if series else None
    for kind in spec["event_outcomes"]:
        result["events"][kind] = int(store.scalar(
            "SELECT COUNT(*) FROM events WHERE kind=?", (kind,), default=0))
    spend = float(store.scalar("SELECT COALESCE(SUM(cost_usd),0) FROM llm_calls", default=0.0))
    result["spend_usd"] = round(spend, 4)
    store.close()
    return result


# ── the experiment ───────────────────────────────────────────────────────────
def run_experiment(spec_path_or_dict, out_dir: str = "reports/out",
                   data_root: str = "data/experiments", quiet: bool = False) -> dict:
    spec = load_spec(spec_path_or_dict)
    data_dir = Path(data_root) / spec["name"]
    data_dir.mkdir(parents=True, exist_ok=True)
    arms = ["treatment"] + (["control"] if spec["control"] else [])

    results: list[dict] = []
    for seed in spec["seeds"]:
        for arm in arms:
            if not quiet:
                print(f"[experiment {spec['name']}] seed {seed} · {arm} · {spec['ticks']} ticks")
            results.append(_run_arm(spec, seed, arm, data_dir))

    summary = _summarize(spec, results)
    report_path = _write_report(spec, results, summary, out_dir)
    summary["report_path"] = report_path
    if not quiet:
        print(f"[experiment {spec['name']}] report: {report_path}")
    return {"spec": {k: spec[k] for k in ("name", "seeds", "ticks", "control",
                                          "metrics", "event_outcomes")},
            "results": results, "summary": summary}


def _stats(values: list[float]) -> dict:
    vals = [v for v in values if v is not None]
    if not vals:
        return {"n": 0, "mean": None, "std": None, "min": None, "max": None}
    return {"n": len(vals), "mean": round(statistics.fmean(vals), 4),
            "std": round(statistics.pstdev(vals), 4) if len(vals) > 1 else 0.0,
            "min": round(min(vals), 4), "max": round(max(vals), 4)}


def _summarize(spec: dict, results: list[dict]) -> dict:
    by_arm = {arm: [r for r in results if r["arm"] == arm]
              for arm in {r["arm"] for r in results}}
    metrics = {}
    for name in spec["metrics"]:
        metrics[name] = {arm: _stats([r["metrics"].get(name) for r in rs])
                         for arm, rs in by_arm.items()}
        t, c = metrics[name].get("treatment"), metrics[name].get("control")
        if t and c and t["mean"] is not None and c["mean"] is not None:
            metrics[name]["effect_mean"] = round(t["mean"] - c["mean"], 4)
    events = {}
    for kind in spec["event_outcomes"]:
        events[kind] = {arm: _stats([float(r["events"].get(kind, 0)) for r in rs])
                        for arm, rs in by_arm.items()}
        t, c = events[kind].get("treatment"), events[kind].get("control")
        if t and c and t["mean"] is not None and c["mean"] is not None:
            events[kind]["effect_mean"] = round(t["mean"] - c["mean"], 4)
    return {"metrics": metrics, "events": events,
            "all_reconciled": all(r["reconciled"] for r in results),
            "total_spend_usd": round(sum(r["spend_usd"] for r in results), 4)}


# ── report ───────────────────────────────────────────────────────────────────
def _overlay_svg(series_by_run: list[tuple[str, str, list[tuple[int, float]]]],
                 title: str, w: int = 460, h: int = 150) -> str:
    """One polyline per run: treatment solid, control dashed."""
    esc = _html.escape
    pts_all = [p for _, _, s in series_by_run for p in s]
    if len(pts_all) < 2:
        return f"<div class='chart empty'><h4>{esc(title)}</h4><p>not enough data</p></div>"
    xs = [p[0] for p in pts_all]; ys = [p[1] for p in pts_all]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    sx, sy = (x1 - x0) or 1, (y1 - y0) or 1
    colors = ["#2f81f7", "#3fb950", "#d29922", "#bc8cff", "#f85149", "#5ac8fa"]
    lines = []
    seed_color: dict[str, str] = {}
    for label, arm, series in series_by_run:
        if len(series) < 2:
            continue
        seed = label.split("·")[0]
        color = seed_color.setdefault(seed, colors[len(seed_color) % len(colors)])
        pts = " ".join(f"{10 + (x - x0) / sx * (w - 20):.1f},{h - 18 - (y - y0) / sy * (h - 36):.1f}"
                       for x, y in series)
        dash = "" if arm == "treatment" else " stroke-dasharray='4 3' opacity='0.55'"
        lines.append(f"<polyline fill='none' stroke='{color}' stroke-width='1.5'{dash} points='{pts}'/>")
    return (f"<div class='chart'><h4>{esc(title)} <span class='ax'>(solid=treatment, "
            f"dashed=control; one color per seed)</span></h4>"
            f"<svg viewBox='0 0 {w} {h}' preserveAspectRatio='none'>{''.join(lines)}"
            f"<text x='10' y='12' class='ax'>{y1:,.2f}</text>"
            f"<text x='10' y='{h-24}' class='ax'>{y0:,.2f}</text>"
            f"<text x='10' y='{h-4}' class='ax'>t{x0}</text>"
            f"<text x='{w-42}' y='{h-4}' class='ax'>t{x1}</text></svg></div>")


def _write_report(spec: dict, results: list[dict], summary: dict, out_dir: str) -> str:
    esc = _html.escape
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def stat_row(name, per_arm):
        cells = []
        for arm in ("treatment", "control"):
            s = per_arm.get(arm)
            cells.append(f"<td>{s['mean']} ± {s['std']} [{s['min']}, {s['max']}]</td>"
                         if s and s["mean"] is not None else "<td>—</td>")
        eff = per_arm.get("effect_mean")
        cells.append(f"<td><b>{eff:+}</b></td>" if eff is not None else "<td>—</td>")
        return f"<tr><td>{esc(name)}</td>{''.join(cells)}</tr>"

    metric_rows = "".join(stat_row(n, per) for n, per in summary["metrics"].items())
    event_rows = "".join(stat_row(n, per) for n, per in summary["events"].items())

    charts = []
    for name in spec["metrics"]:
        series_by_run = [(f"s{r['seed']}·{r['arm']}", r["arm"], r["series"].get(name, []))
                         for r in results]
        charts.append(_overlay_svg(series_by_run, name))

    per_run_rows = "".join(
        f"<tr><td>{esc(r['run_id'])}</td><td>{r['seed']}</td><td>{r['arm']}</td>"
        f"<td>{r['ticks']}</td>"
        f"<td>{'✓' if r['reconciled'] else 'FAIL'}</td>"
        + "".join(f"<td>{r['metrics'].get(n) if r['metrics'].get(n) is not None else '—'}</td>"
                  for n in spec["metrics"])
        + "".join(f"<td>{r['events'].get(k, 0)}</td>" for k in spec["event_outcomes"])
        + "</tr>" for r in results)

    doc = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Experiment — {esc(spec['name'])}</title>
<style>
 body{{font:14px/1.5 Georgia,serif; color:#1c2330; max-width:1020px; margin:32px auto; padding:0 18px}}
 h1{{font-size:24px}} h2{{margin-top:26px; border-bottom:2px solid #e3e7ee; padding-bottom:4px}}
 .meta{{color:#5a6474}} .grid{{display:grid; grid-template-columns:1fr 1fr; gap:14px}}
 .chart{{border:1px solid #e3e7ee; border-radius:8px; padding:8px}} .chart h4{{margin:0 0 4px; font:600 12px sans-serif}}
 .chart .ax{{font:9px sans-serif; fill:#8a93a6; color:#8a93a6; font-weight:400}} svg{{width:100%; height:auto}}
 table{{border-collapse:collapse; width:100%; font-size:12.5px}} td,th{{border:1px solid #e3e7ee; padding:4px 8px; text-align:left}}
 th{{background:#f4f6fa; font-family:sans-serif; font-size:11px; text-transform:uppercase}}
 pre{{background:#f4f6fa; padding:10px; border-radius:6px; overflow-x:auto; font-size:11px}}
</style></head><body>
<h1>Experiment — {esc(spec['name'])}</h1>
<p class="meta">{len(spec['seeds'])} seed(s) × {"2 arms (treatment vs control)" if spec['control'] else "1 arm"}
 · {spec['ticks']} ticks each · generated {now}
 · {"all runs reconciled" if summary['all_reconciled'] else "<b>RECONCILIATION FAILURES</b>"}
 · total LLM spend ${summary['total_spend_usd']}</p>

<h2>Outcome distributions — final metric values across seeds</h2>
<table><tr><th>Metric</th><th>Treatment mean ± std [min, max]</th><th>Control</th><th>Effect (T−C)</th></tr>
{metric_rows}</table>

<h2>Event-count outcomes</h2>
<table><tr><th>Event</th><th>Treatment</th><th>Control</th><th>Effect (T−C)</th></tr>
{event_rows}</table>

<h2>Metric trajectories</h2>
<div class="grid">{''.join(charts)}</div>

<h2>Per-run detail</h2>
<table><tr><th>Run</th><th>Seed</th><th>Arm</th><th>Ticks</th><th>Books</th>
{''.join(f"<th>{esc(n)}</th>" for n in spec['metrics'])}
{''.join(f"<th>{esc(k)}</th>" for k in spec['event_outcomes'])}</tr>
{per_run_rows}</table>

<h2>Reproduction</h2>
<pre>{esc(json.dumps({k: spec[k] for k in ('name','seeds','ticks','control','shocks','metrics','event_outcomes') if k in spec}, indent=2))}</pre>
</body></html>"""

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"experiment_{spec['name']}.html"
    path.write_text(doc, encoding="utf-8")

    md = [f"# Experiment — {spec['name']}",
          f"{len(spec['seeds'])} seeds × {'T+C' if spec['control'] else 'T'} × {spec['ticks']} ticks · {now}",
          "", "## Final-value distributions"]
    for name, per in summary["metrics"].items():
        t = per.get("treatment"); c = per.get("control"); eff = per.get("effect_mean")
        md.append(f"- **{name}**: T {t['mean'] if t else '—'} ± {t['std'] if t else '—'}"
                  f" · C {c['mean'] if c else '—'}"
                  f" · effect {eff:+} " if eff is not None else f"- **{name}**: T {t['mean'] if t else '—'}")
    md += ["", "## Event counts (mean per run)"]
    for kind, per in summary["events"].items():
        t = per.get("treatment"); c = per.get("control")
        md.append(f"- **{kind}**: T {t['mean'] if t else '—'} · C {c['mean'] if c else '—'}")
    (out / f"experiment_{spec['name']}.md").write_text("\n".join(md), encoding="utf-8")
    return str(path)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        sys.exit("usage: python -m experiments.harness <spec.yaml>")
    run_experiment(sys.argv[1])

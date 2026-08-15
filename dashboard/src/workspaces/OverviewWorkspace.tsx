import { useState } from "react";
import { Link, useParams } from "react-router";
import { post } from "../api.js";
import {
  commonObserverParamsFromState, projectionScopeParams, useObserverViewState,
} from "../app/observerViewState";
/* Lineage provenance is the shell topbar's global FreshnessBadge; a second copy
   here is what made the chrome double-decked, so this surface does not repeat it. */
import { useWorkspaceOutletContext } from "../components/FreshnessBadge";
import {
  Button, Cap, DataTable, EmptyState, Figure, KindCode, LatencyMeter, Num, Panel,
  Pending, Skeleton, Stat, StatusText, count, decimal, fromCents, humanize, numberOr,
  percentFromFraction, received, splitDecimal, titleCase, useAfter, useSource,
  type Column, type Delta, type FigureTone, type LatencySample, type RowTone,
} from "../ui";
import { useTheme } from "../ui/useTheme";

/* ============================================================== payloads == */

type Governor = {
  cap_usd: number | null; total_spend_usd: number; world_spend_usd: number;
  level: number; citizens_enabled?: boolean;
};
type RunStatus = {
  run_id: string; status: string; tick: number; seed?: number;
  active_tick: number | null; next_phase: string | null;
  semantics_version: number; speed_delay_s: number; running: boolean;
  pause_reason: string | null;
  governor: Governor;
  provider_readiness?: { mode?: string; routed_providers?: string[] };
};
type MetricPoint = { tick: number; value: number };
type Metrics = Record<string, MetricPoint[]>;
type AgentRow = {
  id: number; name: string; kind?: string; role?: string | null; occupation?: string | null;
  age?: number | null; health?: string; alive?: number; retired?: number;
  employer_id?: number | null; model_tier?: string;
  population_tier?: "core" | "periphery"; region_id?: number | null; region_key?: string | null;
};
type AgentPage = {
  items: AgentRow[]; total: number; population_total?: number;
  limit: number; next_after_id: number | null;
};
type FirmRow = { id: number; name: string; sector?: string; status?: string; employees?: number };
type BankRow = { id: number; name: string; status?: string; deposits_cents?: number; reserves_cents?: number };
type Institutions = {
  government?: {
    enabled: boolean; tax_rate_bps?: number; unemployment_benefit_cents?: number;
    treasury_cents?: number;
    last_election?: { tick: number; direction?: string; turnout?: number; new_tax_bps?: number } | null;
  };
  vc?: { exists: boolean; fund_cents?: number; portfolio?: Array<{ status?: string }> };
  health?: { insured_count?: number; epidemic_multiplier?: number };
  outlets?: Array<{ id: number; name?: string }>;
};
type EventRow = {
  id: number; tick: number; phase: string; kind: string; importance: number;
  payload: Record<string, unknown>;
};
type RegionRow = {
  id: number; region_key: string; name: string; currency_code?: string;
  population?: number; firms?: number;
};
type RegionEnvelope = { data: { regions?: RegionRow[] } };

/* ============================================================= constants == */

/** world/loop.py, semantics 8+. An unrecognised phase renders as a name only. */
const PHASES = [
  "NIGHT_CLOSE", "INBOX_DELIVERY", "MORNING", "EXECUTION", "MARKET",
  "NEWSROOM", "EVENING", "MEMORY", "FINALIZE",
];
const TERMINAL_STATUSES = new Set(["completed", "failed", "finished", "halted", "stopped"]);
const AGENT_PAGE = 40;
const EVENT_PAGE = 40;
/** Kinds whose name states a failure. Salience tracks exceptionality, not frequency. */
const EXCEPTIONAL = /reject|fail|denie|denied|bankrupt|default|halt|breach|violat/i;
const IDENTITY_KEYS = [
  "agent_id", "actor_id", "firm_id", "outlet_id", "bank_id", "buyer_id", "seller_id",
  "article_id", "item_id", "conv_id", "claim_id", "pitch_id", "order_id",
];

/* =============================================================== helpers == */

function seriesOf(metrics: Metrics | undefined, key: string): MetricPoint[] {
  const points = metrics?.[key];
  return Array.isArray(points) ? points : [];
}

function latestOf(points: MetricPoint[]): MetricPoint | null {
  return points.length ? points[points.length - 1] : null;
}

/**
 * A delta only exists when we hold two real observations. Everything else returns
 * null and the stat renders without a delta line rather than inventing a zero.
 */
function deltaOf(
  points: MetricPoint[],
  options: { digits: number; unit: string; scale?: number; rising: "pos" | "neg" | "caution" | "neutral" },
): Delta | null {
  if (points.length < 2) return null;
  const current = points[points.length - 1];
  const previous = points[points.length - 2];
  if (!received(current?.value) || !received(previous?.value)) return null;
  const scale = options.scale ?? 1;
  const change = (current.value - previous.value) * scale;
  const magnitude = Math.abs(change);
  const direction = change > 0 ? "up" : change < 0 ? "down" : "flat";
  const judgement = direction === "flat"
    ? "hold"
    : direction === "up"
      ? options.rising
      : options.rising === "pos" ? "neg" : options.rising === "neg" ? "pos" : options.rising;
  return {
    direction,
    judgement,
    value: decimal(magnitude, options.digits),
    unit: options.unit,
    note: `vs t${previous.tick}`,
    sinceTick: previous.tick,
  };
}

/**
 * Defect 4: three deltas that all read "– 0.00 … vs t333" spend a row of height
 * saying nothing. A delta line is for movement; a series that did not move is
 * reported once, in words, for all of them together. This returns the delta only
 * when there is movement to draw.
 */
function moved(delta: Delta | null): Delta | null {
  return delta && delta.direction !== "flat" ? delta : null;
}

/**
 * Defect 2: the exceptionality test for a balance, and the whole of it. A
 * balance below zero means the holder owes more than it holds, which is the one
 * thing about a treasury a reader must not walk past. Size is not a test — a
 * large positive balance is ordinary — so ink follows the sign and magnitude
 * stays where it belongs, in the digits.
 */
function deficit(cents: unknown): FigureTone {
  const value = numberOr(cents);
  return value !== null && value < 0 ? "neg" : "neutral";
}

function sentenceList(items: string[]): string {
  if (items.length < 2) return items[0] ?? "";
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

function eventSubject(payload: Record<string, unknown>): string {
  const entries = Object.entries(payload || {}).filter(
    ([, value]) => typeof value === "string" || typeof value === "number",
  );
  const identity = entries.filter(([key]) => IDENTITY_KEYS.includes(key)).slice(0, 1);
  const rest = entries.filter(([key]) => !IDENTITY_KEYS.includes(key)).slice(0, 2);
  const shown = [...identity, ...rest];
  if (!shown.length) return "—";
  /* Payload keys and enum-ish values are protocol tokens; the stream reads them
     out as words. The event's own kind is on the row's title.

     The trailing `_id` is dropped from a key name. "case 434" says exactly what
     "case id 434" said, and across the three fields a row can hold that is six
     to nine characters of scaffolding reclaimed for the subject itself — the
     other half of defect 5, which is fixed by lowering the demand as well as by
     raising the supply. */
  return shown
    .map(([key, value]) => `${key.replace(/_id$/, "").replaceAll("_", " ")} ${String(value).replaceAll("_", " ")}`)
    .join(" · ");
}

/**
 * Defect 5: the series used to run out at x = width, so the fill met the frame
 * instead of ending, the terminal dot was sliced in half by the viewBox, and the
 * figure was bounded on three sides only.
 *
 * The plot now stops one INSET short of the frame. That single change closes the
 * figure: the fill gains its own right edge (the last observation's vertical drop
 * to the baseline), and the terminal marker has room to be a whole dot rather
 * than a half one clipped by the wall. The baseline is drawn rather than implied,
 * so the bottom edge is an axis and not a crop.
 */
function Sparkline({ points, label }: { points: MetricPoint[]; label: string }) {
  if (points.length < 2) return null;
  const width = 268;
  const height = 54;
  /* Terminal dot radius plus its own breathing room; nothing may be drawn past it. */
  const inset = 9;
  const baseline = height - 1;
  const values = points.map(point => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = (width - inset) / (points.length - 1);
  const coords = points.map((point, index) => [
    index * step,
    height - 7 - ((point.value - min) / span) * (height - 15),
  ] as const);
  const line = coords
    .map(([x, y], index) => `${index ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`)
    .join(" ");
  const [tailX, tailY] = coords[coords.length - 1];
  return <div className="ae-spark">
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label={label}>
      <path
        d={`${line} L${tailX.toFixed(1)},${baseline} L0,${baseline} Z`}
        fill="var(--ae-spark-fill)"
      />
      {/* The two edges the figure was missing: a floor it sits on, and a right
          wall of its own at the last observation rather than at the frame. */}
      <path d={`M0,${baseline} L${tailX.toFixed(1)},${baseline}`} stroke="var(--ae-divider)" strokeWidth="1" fill="none" />
      <path
        d={`M${tailX.toFixed(1)},${tailY.toFixed(1)} L${tailX.toFixed(1)},${baseline}`}
        stroke="var(--ae-border-soft)" strokeWidth="1" fill="none"
      />
      <path d={line} fill="none" stroke="var(--ae-text-2)" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={tailX} cy={tailY} r="2.6" fill="var(--ae-text-hi)" />
    </svg>
    {/* The caption is inset by the same amount, so "t334" sits over the point it
        names instead of over the frame's corner. */}
    <div className="ae-sparkcap">
      <span>t{points[0].tick}</span>
      <span>{points.length} closes</span>
      <span>t{points[points.length - 1].tick}</span>
    </div>
  </div>;
}

function RailRow({ k, v }: { k: string; v: string | null }) {
  return <div className="ae-railrow">
    <span className="k">{k}</span>
    <span className="v">{v === null ? <Pending /> : <Num>{v}</Num>}</span>
  </div>;
}

/**
 * A rail row whose value is a verdict rather than a quantity, so it is not set
 * in the tabular-numeral track the counts use. `note` carries the magnitude for
 * the reader who needs it, without making the magnitude the headline.
 */
function RailVerdict({ k, verdict, tone, note }: {
  k: string; verdict: string | null; tone: "normal" | "bad"; note?: string;
}) {
  return <div className="ae-railrow">
    <span className="k">{k}</span>
    <span className="v">{verdict === null
      ? <Pending />
      : <StatusText tone={tone}>{verdict}{note ? <small> {note}</small> : null}</StatusText>}</span>
  </div>;
}

/**
 * Defect 6: a count column and a currency column are not the same column.
 *
 * "27,893,861.39" was dropped into the same right-aligned track as 305, 101 and
 * 3, so the one figure on the rail that is money read as a count of twenty-eight
 * million things. Counting and settling are different questions and they now sit
 * in different sections, told apart three ways at once:
 *   · the figure has its own group, so it is not in the counts' list at all;
 *   · that group's heading DECLARES THE UNIT, which is how a ledger has always
 *     distinguished a money column from a tally — the counts need no unit and
 *     therefore carry none;
 *   · the cents are set in the quiet tier, so a two-decimal figure cannot be
 *     mistaken for a whole count at a glance.
 */
function RailMoney({ k, v }: { k: string; v: string | null }) {
  const parts = v === null ? null : splitDecimal(v);
  return <div className="ae-railrow is-money">
    <span className="k">{k}</span>
    <span className="v">
      {parts === null
        ? <Pending />
        : <Num>{parts.whole}<span className="ae-railfrac">{parts.fraction}</span></Num>}
    </span>
  </div>;
}

/**
 * Defect 1 — the worst one. The regional split used to be the last section
 * inside the rail's scrolling ledger, and it lost that race: the header printed,
 * one region row was sliced through its x-height by the scroll boundary, and
 * nothing legible followed. A heading that advertises data and then amputates it
 * is worse than no heading.
 *
 * Three structural changes make a half-row impossible here rather than unlikely:
 *   1. the section is lifted OUT of the rail's scroller and pinned as its own
 *      block, so the outer boundary can never fall inside it;
 *   2. every region is one fixed-height row and the list's own max-height is an
 *      exact integer multiple of that height, so its boundary can only ever land
 *      between rows — at rest and, with scroll snapping, after any scroll too;
 *   3. the header states the total, so a list longer than the window says so in
 *      words instead of leaving the reader to infer it from a clipped glyph.
 */
const REGION_WINDOW = 3;

function RegionRow({ region }: { region: RegionRow }) {
  return <div
    className="ae-regionrow"
    title={`${region.name} · settles in ${region.currency_code || "an unstated currency"}`}
  >
    <span className="ae-regionrow-k">
      {region.region_key}
      {region.currency_code ? <u className="mono">{region.currency_code}</u> : null}
    </span>
    <span className="ae-regionrow-n"><Num>{count(region.population) ?? "—"}</Num></span>
    <span className="ae-regionrow-n"><Num>{count(region.firms) ?? "—"}</Num></span>
  </div>;
}

/* ============================================================= workspace == */

export function OverviewWorkspace() {
  const { runId = "run" } = useParams();
  const [observerState] = useObserverViewState();
  const { transport } = useWorkspaceOutletContext();
  const { theme, toggleTheme } = useTheme();
  const tick = observerState.tick;
  const live = tick === "live";
  const [agentCursor, setAgentCursor] = useState<number[]>([]);
  const [eventLimit, setEventLimit] = useState(EVENT_PAGE);
  const [controlError, setControlError] = useState<string | null>(null);
  /* Defect 6: the ledgers report what the reader can see, not what was fetched. */
  const [agentsInView, setAgentsInView] = useState(0);
  const [eventsInView, setEventsInView] = useState(0);

  /* -- every panel owns its query. Nothing waits on the slowest call. -- */
  const run = useSource<RunStatus>({
    key: ["run-status", runId],
    path: "/api/run/status",
    refetchInterval: live ? 2000 : false,
  });
  const terminal = TERMINAL_STATUSES.has(String(run.data?.status || "").toLowerCase());
  const polling = live && !terminal;

  const metrics = useSource<Metrics>({
    key: ["metrics", runId],
    path: "/api/metrics",
    refetchInterval: polling ? 5000 : false,
  });
  const after = agentCursor[agentCursor.length - 1];
  const agents = useSource<AgentPage>({
    key: ["agents", runId, after ?? 0],
    path: `/api/agents?limit=${AGENT_PAGE}${after ? `&after_id=${after}` : ""}`,
    label: "/api/agents",
    refetchInterval: polling ? 6000 : false,
  });
  const coreAgents = useSource<AgentPage>({
    key: ["agents-core", runId],
    path: "/api/agents?limit=1&population_tier=core",
    label: "/api/agents?population_tier",
    refetchInterval: polling ? 15000 : false,
  });
  const firms = useSource<FirmRow[]>({
    key: ["firms", runId],
    path: "/api/firms",
    refetchInterval: polling ? 10000 : false,
  });
  const banks = useSource<BankRow[]>({
    key: ["banks", runId],
    path: "/api/banks",
    refetchInterval: polling ? 10000 : false,
  });
  const institutions = useSource<Institutions>({
    key: ["institutions", runId],
    path: "/api/institutions",
    refetchInterval: polling ? 8000 : false,
  });
  /*
   * The API is a single asyncio process sharing an event loop with the tick loop,
   * so one slow query stalls every other request behind it: firing all nine at
   * once made /api/institutions (3 ms on its own) take eleven seconds. The two
   * known-slow sources are therefore released only once the fast tier has
   * settled — or after a 4 s valve, so a stuck fast source cannot strand them.
   */
  const valveOpen = useAfter(4000);
  const fastSettled = ![run, metrics, agents, coreAgents, firms, banks, institutions]
    .some(source => source.pending);
  const slowReleased = fastSettled || valveOpen;

  const events = useSource<EventRow[]>({
    key: ["events", runId, eventLimit],
    path: `/api/events?limit=${eventLimit}`,
    label: "/api/events",
    enabled: slowReleased,
    refetchInterval: polling ? 20000 : false,
  });
  /*
   * THE INVARIANT, NOT A STATISTIC.
   *
   * `ledger_balance` is SUM(delta_cents) over every ledger entry to this tick.
   * Double entry means it must be exactly zero; any other number says the world
   * created or destroyed money, which invalidates everything else on this page.
   *
   * It had no reader anywhere on this surface — the one figure that says whether
   * the economy is sound was the one figure nobody could see. It belongs beside
   * the balances, because that is what it is measured against.
   */
  const summaryParams = projectionScopeParams(observerState);
  summaryParams.set("domains", "summary");
  const ledger = useSource<{ data: { summary?: { ledger_balance?: number } } }>({
    key: ["overview-summary", runId, summaryParams.toString()],
    path: `/api/v2/snapshot?${summaryParams}`,
    label: "/api/v2/snapshot",
    refetchInterval: polling ? 20000 : false,
  });
  const regionParams = projectionScopeParams(observerState);
  regionParams.set("layers", "regions");
  const regions = useSource<RegionEnvelope>({
    key: ["regions", runId, regionParams.toString()],
    path: `/api/v2/world-map?${regionParams}`,
    label: "/api/v2/world-map",
    enabled: slowReleased,
    refetchInterval: polling ? 30000 : false,
  });

  const control = async (path: string, body?: unknown) => {
    setControlError(null);
    try {
      await post(path, body);
    } catch (reason) {
      setControlError(reason instanceof Error ? reason.message : String(reason));
    }
    run.refetch();
  };

  /* -------------------------------------------------------- derived -- */
  const status = run.data;
  const phaseIndex = status?.next_phase ? PHASES.indexOf(status.next_phase) : -1;
  const cap = numberOr(status?.governor?.cap_usd);
  const spend = numberOr(status?.governor?.total_spend_usd);
  const capped = cap !== null && cap > 0 && spend !== null;
  const capFraction = cap !== null && cap > 0 && spend !== null
    ? Math.min(100, (spend / cap) * 100)
    : 0;
  const providerMode = status?.provider_readiness?.mode;
  const routed = status?.provider_readiness?.routed_providers?.join(", ");

  /*
   * The link has three conditions and they are not three shades of one thing.
   * DELIVERING is routine and takes no hue; the dot beats because updates are
   * arriving. DEGRADED — stale, reconnecting, still connecting — is exceptional,
   * so it takes the caution ink and the dot stops. HISTORICAL is a view the
   * reader chose, not a fault: no hue, and the beat stops because a pinned tick
   * is not receiving anything either.
   */
  const linkDegraded = live && transport.status !== "live";
  const linkBeating = live && transport.status === "live";
  const linkNote = !live
    ? `Pinned to tick ${tick}. Live updates are not being applied while a tick is pinned.`
    : transport.status === "live"
      ? `Updates are arriving; the projection is at cursor ${transport.cursor}.`
      : `Live updates are ${transport.status}, so every figure on this screen is the last one delivered — at cursor ${transport.cursor}. The provenance disclosure in the top bar explains why.`;

  const gdp = seriesOf(metrics.data, "gdp_proxy");
  const gdpLatest = latestOf(gdp);
  const cpi = seriesOf(metrics.data, "cpi");
  const unemployment = seriesOf(metrics.data, "unemployment");
  const policyRate = seriesOf(metrics.data, "policy_rate");
  const gdpWindow = gdp.slice(-24);

  /*
   * Defect 4: a delta line is a claim about movement. Four of them reading
   * "– 0.00 vs t333" is a full row of height spent on a placeholder repeated
   * four times. Series that held are named once, quietly, in a single line under
   * the band; only series that actually moved keep a delta.
   */
  const series = [
    { name: "GDP proxy", delta: deltaOf(gdp, { digits: 2, unit: "", rising: "pos" }) },
    { name: "CPI", delta: deltaOf(cpi, { digits: 2, unit: "index", rising: "caution" }) },
    { name: "unemployment", delta: deltaOf(unemployment, { digits: 2, unit: "pp", scale: 100, rising: "neg" }) },
    { name: "the policy rate", delta: deltaOf(policyRate, { digits: 0, unit: "bps", rising: "neutral" }) },
  ];
  const [gdpDelta, cpiDelta, unemploymentDelta, policyRateDelta] = series.map(entry => entry.delta);
  const held = series.filter(entry => entry.delta?.direction === "flat");
  const heldSince = held[0]?.delta?.sinceTick;
  const heldNote = held.length && received(heldSince)
    ? `${sentenceList(held.map(entry => entry.name))} unchanged since t${heldSince}`
      .replace(/^./, first => first.toUpperCase())
    : null;

  const firmRows = firms.data ?? [];
  const bankRows = banks.data ?? [];
  const government = institutions.data?.government;
  const election = government?.last_election ?? null;
  const vc = institutions.data?.vc;
  const health = institutions.data?.health;
  const ledgerBalance = numberOr(ledger.data?.data.summary?.ledger_balance) ?? null;
  /* The investigations workspace opens on the event it was sent, at the same
     fork and tick the reader is already looking at. */
  const traceUrl = (eventId: number) => {
    const params = commonObserverParamsFromState(observerState);
    params.set("event", String(eventId));
    return `/runs/${encodeURIComponent(runId)}/investigations?${params}`;
  };
  const regionRows = [...(regions.data?.data.regions ?? [])]
    .sort((a, b) => (numberOr(b.population) ?? 0) - (numberOr(a.population) ?? 0));
  const totalAgents = numberOr(agents.data?.total);
  const coreCount = numberOr(coreAgents.data?.total);
  const peripheryCount = totalAgents !== null && coreCount !== null ? totalAgents - coreCount : null;
  const deposits = banks.data
    ? bankRows.reduce((sum, bank) => sum + (numberOr(bank.deposits_cents) ?? 0), 0)
    : null;

  const latency: LatencySample[] = [
    { label: "/api/run/status", ms: run.latencyMs, pending: run.pending },
    { label: "/api/metrics", ms: metrics.latencyMs, pending: metrics.pending },
    { label: "/api/institutions", ms: institutions.latencyMs, pending: institutions.pending },
    { label: "/api/agents", ms: agents.latencyMs, pending: agents.pending },
    { label: "/api/firms", ms: firms.latencyMs, pending: firms.pending },
    { label: "/api/v2/world-map", ms: regions.latencyMs, pending: regions.pending, queued: regions.queued },
    { label: "/api/events", ms: events.latencyMs, pending: events.pending, queued: events.queued },
  ];

  /*
   * Every column declares the narrowest it may be drawn, and the sum of those
   * floors is what the table reserves. Six columns at 425px of floor sit inside a
   * 466px panel, so nothing is squeezed even before the growth shares are paid.
   *
   * The employer column is gone: it printed a bare foreign key ("3", "none") with
   * nothing on the surface to resolve it against, which is the same raw-protocol
   * problem as an unglossed enum. The roster answers who exists, what they do,
   * where they are, and whether they are alright.
   */
  /*
   * Defect 2 — the column budget. Measured against this run's roster, the widest
   * ID is 13px, the widest AGE 13px, the widest STATE 54px and the widest ROLE
   * 100px ("Venture capitalist"), while NAME wants 288px and never gets it. The
   * old split handed ROLE 109px and NAME 101px, so ROLE carried ~40% dead gutter
   * on every row while "Editor The Ledg…" and "Exchange Oper…" were cut.
   *
   * Every floor is now that column's own measured ceiling rather than a round
   * number, and NAME is the only column with a growth share, so it collects the
   * entire remainder instead of a proportional slice of it. ROLE lands at exactly
   * the width of "Venture capitalist" — full, with no gutter left to waste — and
   * NAME rises from 101px to 134px, which seats both names the critics quoted.
   */
  const agentColumns: Column<AgentRow>[] = [
    { key: "id", label: "ID", min: 28, align: "right", skeleton: "60%", render: row => <Num className="ae-tcell-dim">{row.id}</Num> },
    { key: "name", label: "Name", min: 92, grow: 1, skeleton: "78%", render: row => <span className="ae-tcell-hi" title={row.name}>{row.name}</span> },
    /* `occupation` is the prose the engine already holds ("treasury secretary");
       `role` is the routing enum behind it ("gov_official"). The page says the
       prose and keeps the enum on hover, rather than the other way round. */
    { key: "role", label: "Role", min: 101, skeleton: "84%", render: row => {
      const said = row.occupation || row.role || "";
      if (!said) return <span className="ae-tcell-dim">—</span>;
      const both = [row.occupation, row.role].filter(Boolean).join(" · ");
      return <span className="ae-tcell-2" title={both}>{humanize(said)}</span>;
    } },
    /* Salience tracks exceptionality: the core population is the individually
       simulated third of the roster, so it is the tier that gets named. Every
       row carries its full tier on hover either way. */
    { key: "region", label: "Region", min: 74, skeleton: "70%", render: row => <span
      title={`${row.region_key || "no region"}${row.population_tier ? ` · ${row.population_tier} population` : ""}`}
    >{row.region_key || "—"}{row.population_tier === "core" ? <em className="ae-tcell-tier"> core</em> : null}</span> },
    { key: "age", label: "Age", min: 28, align: "right", skeleton: "60%", render: row => received(row.age) ? <Num>{row.age}</Num> : <span className="ae-tcell-dim">—</span> },
    { key: "state", label: "State", min: 56, skeleton: "66%", render: row => {
      if (row.alive === 0) return <StatusText tone="bad">Deceased</StatusText>;
      if (row.retired === 1) return <StatusText tone="quiet">Retired</StatusText>;
      if (row.health && row.health !== "healthy") return <StatusText tone="caution">{titleCase(row.health)}</StatusText>;
      return <StatusText tone="normal">Alive</StatusText>;
    } },
  ];

  const agentTone = (row: AgentRow): RowTone => {
    if (row.alive === 0) return "exception";
    if (row.health && row.health !== "healthy") return "caution";
    return undefined;
  };

  /*
   * Defect 5 — the same column-budget failure the roster had, in the other
   * ledger. SUBJECT is the only column on this table carrying anything a reader
   * cannot reconstruct, and it was the only one starved: it held 174px and cut
   * eight rows of twelve, while TICK sat at 42px to draw three digits, IMP at
   * 32px to draw "2.5" and KIND at 36px to draw four monospace characters.
   *
   * Every floor below is now that column's own MEASURED ceiling in this
   * surface's own type, not a round number:
   *   TICK  27  header "TICK" measures 24.4px and four digits measure 25.9px
   *   KIND  28  header 27.5px, a four-character code 26.0px
   *   IMP   21  header 20.7px, the widest reading ("4.0") 15.5px
   *   PHASE 87  "INBOX DELIVERY", the widest of the loop's nine phase names —
   *             the ceiling over the whole vocabulary, not over today's sample,
   *             so a rare phase is never the one that gets cut
   * That releases 33px, and SUBJECT is the only column with a growth share, so
   * it collects all of it and every pixel the panel has spare besides: 174px
   * becomes 207px at the reference width. Its own floor is set so that the five
   * floors plus four gutters still total the 352px the stream panel's minimum
   * width is derived from, which keeps that derivation true.
   */
  const eventColumns: Column<EventRow>[] = [
    { key: "tick", label: "Tick", min: 27, align: "right", skeleton: "60%", render: row => <Num className="ae-tcell-dim">{row.tick}</Num> },
    { key: "kind", label: "Kind", min: 28, skeleton: "80%", render: row => <KindCode kind={row.kind} /> },
    { key: "subject", label: "Subject", min: 153, grow: 1, skeleton: "88%", render: row => {
      const subject = eventSubject(row.payload);
      return <span title={`${humanize(row.kind)} — ${subject}`}>{subject}</span>;
    } },
    { key: "importance", label: "Imp", min: 21, align: "right", skeleton: "55%", render: row => <Num>{decimal(row.importance, 1) ?? "—"}</Num> },
    { key: "phase", label: "Phase", min: 87, skeleton: "70%", render: row => <StatusText
      tone={EXCEPTIONAL.test(row.kind) ? "bad" : "quiet"}
    >{String(row.phase || "").replaceAll("_", " ")}</StatusText> },
    /*
     * The way out of "something happened" and into "here is the proof". Without
     * it the stream is a list a reader can only look at: every event on this
     * page has a causal chain behind it, and this is the door to it.
     */
    { key: "trace", label: "Trace", min: 44, align: "right", skeleton: "40%", render: row =>
      <Link className="ae-tracelink" aria-label={`Investigate event ${row.id}`} to={traceUrl(row.id)}>
        Trace <span aria-hidden="true">→</span>
      </Link> },
  ];

  const eventTone = (row: EventRow): RowTone => {
    if (EXCEPTIONAL.test(row.kind)) return "exception";
    if (row.importance >= 2) return "caution";
    return undefined;
  };

  const agentsShown = agents.data?.items.length ?? 0;
  const agentsVisible = agentsInView || agentsShown;
  const eventsShown = events.data?.length ?? 0;
  const eventsVisible = eventsInView || eventsShown;
  const pageStart = agentCursor.length * AGENT_PAGE + 1;

  return <section className="ae-overview">

    {/*
      ===== ONE row of chrome, and now with a rank inside it. =====
      Defect 8: the strip read as one undifferentiated run because a fact wearing
      a control's box (the S12 chip), a run command, and a theme switch were all
      drawn the same way. Three vocabularies, stated once and kept apart:
        · FACTS are a small-caps label over a value — TICK, NEXT PHASE, LLM
          SPEND and LINK all take that one shape, and each is ruled off from its
          neighbour so five fields do not read as one sentence;
        · RUN COMMANDS are the only boxed, headline-ink controls on the strip;
        · VIEW PREFERENCE (the theme switch) is a quiet control with no box, so
          it cannot be mistaken for a transport command.
      The semantics version, which is a fact and not a control, has lost its box
      and joined the link field's meta line where the other cursor figures live.
    */}
    <div className="ae-chrome">
      <div className="ae-chrome-block">
        <Cap>Tick</Cap>
        {status
          ? <><span className="ae-tickval ae-num">{count(status.tick) ?? "—"}</span>
            <span className="ae-tickmeta">
              {titleCase(status.status)}
              {received(status.speed_delay_s) ? ` · ${status.speed_delay_s} s delay` : ""}
            </span></>
          : <Pending />}
      </div>

      <div className="ae-chrome-block">
        <Cap>Next phase</Cap>
        {status?.next_phase
          ? <>
            {phaseIndex >= 0 && <span className="ae-phasebar" aria-hidden="true">
              {PHASES.map((phase, index) => <i
                key={phase}
                className={`ae-seg${index < phaseIndex ? " is-done" : index === phaseIndex ? " is-now" : ""}`}
              />)}
            </span>}
            <span
              className="ae-phase"
              title={phaseIndex >= 0 ? `${status.next_phase} — phase ${phaseIndex + 1} of ${PHASES.length}` : status.next_phase}
            >
              <em>{status.next_phase.replaceAll("_", " ")}</em>
            </span>
          </>
          : <Pending />}
      </div>

      <div className="ae-ctl" role="group" aria-label="Run transport">
        <Button pressed={status?.running === true} disabled={run.pending || terminal || status?.running === true} onClick={() => control("/api/run/start")}>Run</Button>
        <Button disabled={run.pending || terminal || status?.running !== true} onClick={() => control("/api/run/pause")}>Pause</Button>
        <Button disabled={run.pending || terminal || status?.running === true} onClick={() => control("/api/run/step")}>Step</Button>
        <Button disabled={run.pending || terminal} onClick={() => control("/api/run/speed", { delay_s: status?.speed_delay_s === 0 ? 0.5 : 0 })}>
          {status?.speed_delay_s === 0 ? "Slow" : "Fast"}
        </Button>
      </div>

      {/* Defect 4: a 0.00-of-0.00 meter measures nothing. Say the condition instead. */}
      <div className="ae-spend">
        <Cap>LLM spend</Cap>
        {run.pending
          ? <Pending />
          : capped
            ? <>
              <span className="ae-spend-val">{decimal(spend, 2)} USD <u>of cap</u> {decimal(cap, 2)} USD</span>
              <span className="ae-meter" role="img" aria-label={`${decimal(spend, 2)} of ${decimal(cap, 2)} USD spent`}>
                <i style={{ width: `${capFraction.toFixed(1)}%` }} />
              </span>
            </>
            : <span
              className="ae-spend-plain"
              title={`No budget cap is set, so there is no meter to fill. This run is ${providerMode || "offline"}${routed ? ` and routes to ${routed}` : ""}; provider calls cannot be made.`}
            >
              No cap · run is <b>{providerMode || "offline"}</b>
            </span>}
      </div>

      {/*
        Defect 2, second half. STALE was set in the same plain white as LIVE with
        an uncoloured dot, so the one field on the strip that tells a reader the
        numbers beside it have stopped arriving was drawn as though nothing had
        happened. Salience tracks exceptionality: a delivering link is routine and
        stays uncoloured, a link that has stopped is exceptional and takes the
        caution ink in both channels — the word and the dot — with the beat
        stopped, because a still dot is itself the statement that nothing is
        arriving. The plain-English reason lives in the shell's provenance
        disclosure; this field says the condition and the cursor it stopped at.
      */}
      <div className="ae-chrome-block">
        <Cap>Link</Cap>
        <span className={`ae-conn${linkDegraded ? " is-degraded" : ""}`}>
          <i className={`ae-dot${linkBeating ? "" : " is-off"}`} />
          <span className="ae-conn-text">
            <b title={linkNote}>{live ? transport.status.toUpperCase() : "HISTORICAL"}</b>
            <em>
              {live ? `cursor ${transport.cursor}` : `tick ${tick}`}
              {status ? ` · semantics ${count(status.semantics_version) ?? "?"}` : ""}
            </em>
          </span>
        </span>
      </div>

      <div className="ae-chrome-end">
        <Button
          variant="quiet"
          onClick={toggleTheme}
          ariaLabel={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
        >{theme === "dark" ? "Light" : "Dark"}</Button>
      </div>
      {controlError && <p className="world-os-error" role="alert">{controlError}</p>}
    </div>

    <div className="ae-stage">

      {/* ================= rail: counted entities, regions, latency ================= */}
      {/* The note names both kinds of figure the rail now holds. It said "counts"
          while a settled amount sat in the list, which is the same conflation
          defect 6 is about, one line higher up. The source count it used to carry
          is not lost — SOURCE LATENCY names every source, three blocks below. */}
      <Panel as="aside" title="Entities" label="Counted entities" className="ae-rail" note="counts and one balance">
        {/*
          The counted-entities ledger is sized to stand whole at the reference
          height. The venture figures that used to sit here are gone, not lost:
          PUBLIC INSTITUTIONS carries the identical VC fund and VC positions two
          panels over, and one screen should state a number once. What is left is
          only what no other panel holds, which is also what buys the regional
          split below the room to complete.
        */}
        <div className="ae-raillist">
          <div className="world-os-metrics" role="group" aria-label="World summary">
            <div className="ae-railgrp">Population</div>
            <RailRow k="Agents" v={count(totalAgents)} />
            <RailRow k="Core" v={count(coreCount)} />
            <RailRow k="Periphery" v={count(peripheryCount)} />
            <RailRow k="Insured" v={count(health?.insured_count)} />

            <div className="ae-railgrp">Organizations</div>
            <RailRow k="Firms" v={firms.data ? count(firmRows.length) : null} />
            <RailRow k="Listed" v={firms.data ? count(firmRows.filter(firm => firm.status === "listed").length) : null} />
            <RailRow k="Banks" v={banks.data ? count(bankRows.length) : null} />
            <RailRow k="News outlets" v={institutions.data ? count(institutions.data.outlets?.length ?? 0) : null} />

            {/* The only settled amount on the rail, out of the tally and into a
                section whose heading states what it is measured in. */}
            <div className="ae-railgrp">
              Balances
              <span className="ae-railunit">major units</span>
            </div>
            <RailMoney k="Bank deposits" v={fromCents(deposits)} />
            {/*
              Stated as the verdict, not the number, because the number is only
              ever interesting when it is wrong. The cents sit underneath so a
              reader who needs the magnitude has it without reading the ledger.
            */}
            <RailVerdict
              k="Ledger invariant"
              verdict={ledgerBalance === null ? null : ledgerBalance === 0 ? "Balanced" : "Review"}
              tone={ledgerBalance === 0 ? "normal" : "bad"}
              note={ledgerBalance === null ? undefined : `${count(ledgerBalance)} cents net`}
            />
          </div>
        </div>

        {/*
          Defect 1: pinned outside the scroller above, so the rail's boundary can
          never fall inside this section. /api/v2/world-map is a projection whose
          latency swings from 60 ms to 35 s against the tick loop, so it does not
          hold a top-level slot on the page — but wherever it resolves, it
          resolves whole.
        */}
        <div className="ae-regions">
          <div className="ae-railgrp">
            Regions
            <span className="ae-region-src">
              {regionRows.length > REGION_WINDOW
                ? <>{count(REGION_WINDOW)} of {count(regionRows.length)}, scroll</>
                : null}
              <span className="mono">/api/v2/world-map</span>
            </span>
          </div>
          {regions.pending
            ? <div className="ae-regionlist">
              {[0, 1, 2].map(index => <div className="ae-regionrow" key={index} aria-hidden="true">
                <span className="ae-regionrow-k"><Skeleton dim={index % 2 === 1} width="72%" /></span>
                <span className="ae-regionrow-n"><Skeleton dim width="80%" /></span>
                <span className="ae-regionrow-n"><Skeleton dim width="80%" /></span>
              </div>)}
            </div>
            : regions.error
              ? <EmptyState title="Regions unavailable" compact>
                The regional projection did not answer: {regions.error.message}
              </EmptyState>
              : regionRows.length
                ? <>
                  <div className="ae-regionrow is-head" aria-hidden="true">
                    <span className="ae-regionrow-k">Region</span>
                    <span className="ae-regionrow-n">Agents</span>
                    <span className="ae-regionrow-n">Firms</span>
                  </div>
                  {/* The window is an exact multiple of the row height, so this
                      boundary lands between rows and never through one. */}
                  <div className="ae-regionlist" tabIndex={0} role="group" aria-label="Regions by population">
                    {regionRows.map(region => <RegionRow region={region} key={region.id} />)}
                  </div>
                </>
                : <EmptyState title="Regions" compact>
                  This projection returned no regions, so there is nothing to split.
                </EmptyState>}
        </div>

        {/*
          Defect 5: bar length is base-10 logarithmic over a fixed 1 ms – 30 s
          domain, and the meter says so. Drawing 2 ms and 19 s at comparable
          lengths is not decoration, it is a false claim about the data.
        */}
        <LatencyMeter samples={latency} />

        <EmptyState title="Halts & overrides">
          {run.pending
            ? "No run status has arrived yet."
            : status?.pause_reason
              ? `Paused: ${humanize(status.pause_reason).toLowerCase()}.`
              : `None recorded. The run is ${String(status?.status || "in an unknown state").toLowerCase()} at tick ${status?.tick ?? "?"}.`}
        </EmptyState>
      </Panel>

      <div className="ae-content">

        {/* ================= economy state: the hero ================= */}
        <Panel
          title="Economy state"
          source={metrics}
          note={gdpLatest ? `published at t${gdpLatest.tick}` : undefined}
          label="Economy state"
        >
          <div className="ae-macro">
            <div className="ae-macro-top">
              <div>
                {/* One line: a name and a gloss. The tick this was published at
                    is stated once, in the panel header, not repeated here. */}
                <div className="ae-herolbl">
                  <b>GDP proxy</b>
                  <span className="ae-herodef">final-goods sales in one tick</span>
                </div>
                <Stat
                  size="hero"
                  label=""
                  value={decimal(gdpLatest?.value, 2)}
                  delta={moved(gdpDelta)}
                />
              </div>
              {metrics.pending
                ? <div className="ae-spark"><Skeleton height={54} /></div>
                : <Sparkline points={gdpWindow} label={`GDP proxy, t${gdpWindow[0]?.tick ?? "?"} to t${gdpLatest?.tick ?? "?"}`} />}
            </div>

            <div className="ae-macro-row">
              <Stat
                label="CPI"
                value={decimal(latestOf(cpi)?.value, 2)}
                unit="index"
                delta={moved(cpiDelta)}
              />
              <Stat
                label="Unemployment"
                value={percentFromFraction(latestOf(unemployment)?.value, 2)}
                unit="%"
                delta={moved(unemploymentDelta)}
              />
              <Stat
                label="Policy rate"
                value={decimal(latestOf(policyRate)?.value, 0)}
                unit="bps"
                delta={moved(policyRateDelta)}
              />
            </div>
            {/* One quiet line replaces however many "– 0.00 vs t333" placeholders
                would otherwise have been drawn. */}
            {heldNote && <p className="ae-macro-hold">{heldNote}</p>}
          </div>
        </Panel>

        {/*
          ===== prime slot goes to the fastest real source on the surface =====
          Defect 3: this panel used to abandon the numeric discipline the rest of
          the screen keeps. Its six values were left-aligned, so -750,481.00,
          800.00 and 39 shared no spine and the minus on TREASURY pushed its
          digits a full glyph clear of the figure directly below it; and it then
          ended in a two-line prose paragraph dropped into a metric grid.
          Every figure now sits on its column's spine, and the election record —
          which is a set of facts, not body copy — has moved to the footnote band
          the two ledgers below already use, so the column ends on a ruled edge.

          Defects 3 and 4: that spine was the cell edge and the unit was thrown to
          the far wall to protect it, which cost the panel both readings it was
          meant to keep. The spine is now the DECIMAL POINT — a fixed slot for the
          fraction, so 1,200 and -750,481.00 meet on the point instead of missing
          each other on a shared right edge, and a count is never given cents it
          does not have — and the unit is set one gap from its own digits, so each
          pair reads as one figure rather than as two fields 150px apart. Both
          rules live in Figure; every caller gets them.
        */}
        <Panel
          title="Public institutions"
          source={institutions}
          label="Public institutions"
          foot={institutions.data ? <>
            <span>{election
              ? `Last election t${count(election.tick)} · ${election.direction || "no direction recorded"}${count(election.turnout) ? ` · turnout ${count(election.turnout)}` : ""}`
              : "No election is recorded for this run"}</span>
            <span className="ae-legend">Cents ÷ 100 · 3 settlement currencies</span>
          </> : undefined}
        >
          <div className="ae-inst">
            <div className="ae-inst-grid">
              {/* Defect 2. A balance below zero is the one reading on this panel
                  that changes what a reader should do next, and it was drawn in
                  exactly the ink, weight and size of a routine tax rate — so the
                  screen's most alarming figure was its flattest and its magnitude
                  was carried by digit count alone. `deficit` is the whole rule:
                  ink follows the sign, never the size. */}
              <Figure
                label="Treasury"
                value={fromCents(government?.treasury_cents)}
                unit="major units"
                tone={deficit(government?.treasury_cents)}
                title={deficit(government?.treasury_cents) === "neg"
                  ? "The treasury balance is negative: the government owes more than it holds."
                  : undefined}
              />
              <Figure label="Tax rate" value={decimal(government?.tax_rate_bps, 0)} unit="bps" />
              <Figure label="Unemployment benefit" value={fromCents(government?.unemployment_benefit_cents)} unit="major units" />
              <Figure
                label="VC fund"
                value={fromCents(vc?.fund_cents)}
                unit="major units"
                tone={deficit(vc?.fund_cents)}
              />
              <Figure label="VC positions" value={vc ? count(vc.portfolio?.length ?? 0) : null} unit="funded" />
              <Figure label="Epidemic multiplier" value={decimal(health?.epidemic_multiplier, 2)} unit="×" />
            </div>
            {institutions.error && <EmptyState title="Institutions unavailable" compact>{institutions.error.message}</EmptyState>}
          </div>
        </Panel>

        {/* ================= agents ledger ================= */}
        <Panel
          title="Agents"
          source={agents}
          label="Agent roster"
          foot={<>
            {/* Defect 6: the count describes the window the reader is looking
                through. It only claims the whole page when the whole page fits. */}
            <span>{agents.data
              ? agentsVisible >= agentsShown
                ? `Rows ${count(pageStart)}–${count(pageStart + agentsShown - 1)} of ${count(agents.data.total)}`
                : `Rows ${count(pageStart)}–${count(pageStart + agentsVisible - 1)} of ${count(agentsShown)} · ${count(agents.data.total)} total`
              : "Rows pending"}</span>
            <span className="ae-legend">State takes chroma only when it is exceptional</span>
            <span className="ae-rt">
              <Button size="sm" disabled={!agentCursor.length} onClick={() => setAgentCursor(stack => stack.slice(0, -1))}>Prev</Button>
              <Button
                size="sm"
                disabled={!received(agents.data?.next_after_id)}
                onClick={() => {
                  const next = agents.data?.next_after_id;
                  if (received(next)) setAgentCursor(stack => [...stack, next]);
                }}
              >Next</Button>
            </span>
          </>}
        >
          <DataTable
            caption="Agent roster"
            columns={agentColumns}
            rows={agents.data?.items ?? []}
            rowKey={row => row.id}
            rowTone={agentTone}
            pending={agents.pending}
            onViewport={setAgentsInView}
            skeletonRows={14}
            empty={agents.error
              ? <EmptyState title="Roster unavailable" compact>{agents.error.message}</EmptyState>
              : <EmptyState title="No agents" compact>This page of the roster came back empty.</EmptyState>}
          />
        </Panel>

        {/* ===== event stream: slow source, stale-while-revalidate, own skeleton ===== */}
        <Panel
          title="Event stream"
          source={events}
          label="Committed event stream"
          foot={<>
            <span>{events.data
              ? `${eventsVisible >= eventsShown ? count(eventsShown) : `${count(eventsVisible)} of ${count(eventsShown)}`} shown${
                events.data.length ? ` · t${events.data[0].tick} → t${events.data[events.data.length - 1].tick}` : ""}`
              : "Rows pending"}</span>
            <span className="ae-legend">Kinds are coded, not coloured</span>
            <span className="ae-rt">
              <Button size="sm" disabled={events.pending || eventLimit >= 200} onClick={() => setEventLimit(limit => Math.min(200, limit + EVENT_PAGE))}>Older</Button>
            </span>
          </>}
        >
          <DataTable
            caption="Committed event stream"
            columns={eventColumns}
            rows={events.data ?? []}
            rowKey={row => row.id}
            rowTone={eventTone}
            pending={events.pending}
            onViewport={setEventsInView}
            skeletonRows={14}
            empty={events.error
              ? <EmptyState title="Event spine unavailable" compact>{events.error.message}</EmptyState>
              : <EmptyState title="No events" compact>The spine has committed nothing at this cursor yet.</EmptyState>}
          />
        </Panel>

      </div>
    </div>
  </section>;
}

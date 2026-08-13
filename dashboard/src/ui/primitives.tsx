import { useEffect, useRef, type CSSProperties, type ReactNode } from "react";
import {
  LATENCY_CEILING_MS,
  LATENCY_FLOOR_MS,
  directionGlyph,
  humanize,
  isAdverse,
  isSlow,
  kindCoding,
  latencyBarFraction,
  latencyText,
  splitDecimal,
  type Direction,
  type Judgement,
} from "./format";
import { useElapsed, type Source } from "./useSource";

/* ============================================================ text atoms == */

export function Cap({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={`ae-cap ${className}`.trim()}>{children}</span>;
}

export function Num({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={`ae-num ${className}`.trim()}>{children}</span>;
}

/** The one thing this surface says instead of a zero it has not received. */
export function Pending({ label = "pending" }: { label?: string }) {
  return <span className="ae-pending">{label}</span>;
}

/* ================================================================ Badge == */

export function Badge({
  children, tone = "neutral", title,
}: {
  children: ReactNode;
  tone?: "neutral" | "accent" | "pos" | "caution" | "neg";
  title?: string;
}) {
  return <span className={`ae-badge ae-badge--${tone}`} title={title}>{children}</span>;
}

/**
 * The event kind, as a designed monospace code in one neutral colour.
 *
 * Two states, and they are different on the glyph, not only in the markup. A
 * REGISTERED kind prints its designed code. An UNREGISTERED one prints three
 * letters and the truncation mark, in the quieter ink, and says on hover that no
 * code is registered for it — so an abbreviation is never mistaken for a code
 * and the reader is never handed a corrupted label. Either way the full kind is
 * on the title, spelled out in English and then verbatim.
 */
export function KindCode({ kind }: { kind: string }) {
  const { code, exact } = kindCoding(kind);
  const named = humanize(kind);
  const title = !named
    ? "This event was committed without a kind."
    : exact
      ? `${code} — ${named} · ${kind}`
      : `${code} — ${named} · ${kind}. No code is registered for this kind, so it is shown abbreviated.`;
  return <span
    className={`ae-kindcode mono${exact ? "" : " is-approx"}`}
    title={title}
  >{code}</span>;
}

/**
 * State as text only — no pill, no border, no fill, no dot. Salience tracks
 * exceptionality, not frequency: the commonest states are the quietest, and only
 * the genuinely exceptional ones take chroma.
 */
export function StatusText({
  tone = "normal", children,
}: {
  tone?: "high" | "normal" | "quiet" | "caution" | "bad";
  children: ReactNode;
}) {
  return <span className={`ae-status ae-status--${tone}`}>{children}</span>;
}

/* ============================================================== Button == */

/**
 * Two ranks of control, and the rank is legible before the label is read.
 *
 * `solid` is a control that acts on the run: it is boxed in the full border ink
 * and set in the headline ink. `quiet` is a view preference — no box, secondary
 * ink — so a theme switch can never be mistaken for a transport command.
 *
 * Disabled is a third, categorically different state rather than the same
 * control at a lower opacity: the box drops to the divider ink and the label to
 * the non-text tier, so an unavailable control cannot read as an available one.
 */
export function Button({
  children, onClick, pressed, disabled, size = "md", variant = "solid",
  title, type = "button", ariaLabel,
}: {
  children: ReactNode;
  onClick?(): void;
  pressed?: boolean;
  disabled?: boolean;
  size?: "sm" | "md";
  variant?: "solid" | "quiet";
  title?: string;
  type?: "button" | "submit";
  ariaLabel?: string;
}) {
  return <button
    type={type}
    className={`ae-button ae-button--${size} ae-button--${variant}${pressed ? " is-on" : ""}`}
    onClick={onClick}
    disabled={disabled}
    title={title}
    aria-label={ariaLabel}
    aria-pressed={pressed === undefined ? undefined : pressed}
  >{children}</button>;
}

/* ============================================================ Skeleton == */

export function Skeleton({
  width = "100%", dim = false, height,
}: { width?: string; dim?: boolean; height?: number }) {
  const style: CSSProperties = { width };
  if (height !== undefined) style.height = `${height}px`;
  return <span className={`ae-skeleton${dim ? " is-dim" : ""}`} style={style} aria-hidden="true" />;
}

export function SkeletonLines({ count = 3, widths }: { count?: number; widths?: string[] }) {
  return <div className="ae-skeleton-lines" aria-hidden="true">
    {Array.from({ length: count }, (_, index) => <Skeleton
      key={index}
      dim={index % 2 === 1}
      width={widths?.[index % (widths.length || 1)] ?? (index % 3 === 0 ? "100%" : index % 3 === 1 ? "74%" : "88%")}
    />)}
  </div>;
}

/* ========================================================== EmptyState == */

/**
 * The quietest block on the page. Stable left edge, plain grammatical English —
 * an empty panel still has to read as a sentence.
 */
export function EmptyState({
  title, children, compact = false,
}: { title: string; children?: ReactNode; compact?: boolean }) {
  return <div className={`ae-empty${compact ? " is-compact" : ""}`}>
    <Cap>{title}</Cap>
    {children && <p>{children}</p>}
  </div>;
}

/* ======================================================== source meta ==== */

/** Provenance and measured latency for one panel, shown in its own header. */
export function SourceMeta({ source, note }: { source: Source<unknown>; note?: ReactNode }) {
  const waiting = source.pending && !source.error && !source.queued;
  const elapsed = useElapsed(waiting);

  return <span className="ae-pmeta">
    <b className="mono">{source.label}</b>
    {source.error
      ? <span className="ae-pmeta-bad">unavailable</span>
      : source.queued
        ? <span>queued behind the fast sources</span>
        : waiting
          ? <span>resolving, {latencyText(elapsed) ?? "0 ms"} so far</span>
          : <span>{latencyText(source.latencyMs) ?? "measured"}</span>}
    {source.refetching && <span className="ae-refetch" aria-label="Refetching"><i /></span>}
    {note && <span className="ae-pmeta-note">{note}</span>}
  </span>;
}

/* =============================================================== Panel == */

export function Panel({
  title, source, note, foot, children, label, className = "", as: Tag = "section",
}: {
  title: string;
  source?: Source<unknown>;
  note?: ReactNode;
  foot?: ReactNode;
  children: ReactNode;
  /** Accessible name; defaults to the visible title. */
  label?: string;
  className?: string;
  as?: "section" | "aside";
}) {
  const busy = Boolean(source?.pending && !source.error);
  return <Tag
    className={`ae-panel ${className}`.trim()}
    aria-label={label ?? title}
    aria-busy={busy || undefined}
  >
    <div className="ae-phead">
      <span className="ae-ptitle">{title}</span>
      {/* One truncation rule on this surface: text that does not fit ends in an
          ellipsis, never a hard cut. A bare string child of the flex row is an
          anonymous item that text-overflow cannot reach, so the note is always
          wrapped in the element that owns the rule. */}
      {source
        ? <SourceMeta source={source} note={note} />
        : note ? <span className="ae-pmeta"><span className="ae-pmeta-note">{note}</span></span> : null}
    </div>
    {children}
    {foot && <div className="ae-pfoot">{foot}</div>}
  </Tag>;
}

/* ================================================================ Stat == */

export type Delta = {
  direction: Direction;
  /** Whether that direction is welcome. Never merged with the direction glyph. */
  judgement: Judgement;
  /** Unsigned magnitude — the sign lives in the glyph, so it is not repeated. */
  value: string | null;
  unit?: string;
  note?: string;
  /** The observation this was measured against, so a caller can say so in prose. */
  sinceTick?: number;
};

/**
 * A one-tick move is the most routine thing on this surface, so it does not get
 * to be the most coloured. Ink is spent only when the movement is ADVERSE —
 * unemployment rising, CPI running — and a welcome or neutral move keeps the
 * direction glyph and the quiet tier. That leaves the palette free for the
 * figures that are genuinely exceptional, which is where a reader's eye should
 * be pulled first.
 */
export function DeltaLine({ delta }: { delta: Delta | null }) {
  if (!delta || delta.value === null) return null;
  const ink = isAdverse(delta.judgement) ? `ae-${delta.judgement}` : "ae-neutral";
  return <span className="ae-delta">
    <span className={`ae-gly ${ink}`} aria-hidden="true">{directionGlyph(delta.direction)}</span>
    <Num className={ink}>{delta.value}</Num>
    {delta.unit && <span className="ae-dunit">{delta.unit}</span>}
    {delta.note && <span className="ae-dvs">{delta.note}</span>}
  </span>;
}

export function Stat({
  label, value, unit, delta = null, size = "md", aside, pendingLabel = "pending",
}: {
  /** Omitted when the panel already carries the label above the figure. */
  label?: ReactNode;
  /** null means "not received". It renders as pending, never as 0. */
  value: string | null;
  unit?: string;
  delta?: Delta | null;
  size?: "hero" | "md";
  aside?: ReactNode;
  pendingLabel?: string;
}) {
  return <div className={`ae-stat ae-stat--${size}`}>
    <div className="ae-stat-top">
      <div className="ae-stat-lead">
        {label ? <Cap>{label}</Cap> : null}
        <div className="ae-stat-value">
          {value === null
            ? <Pending label={pendingLabel} />
            : <><Num className="ae-stat-num">{value}</Num>{unit && <span className="ae-stat-unit">{unit}</span>}</>}
        </div>
      </div>
      {aside && <div className="ae-stat-aside">{aside}</div>}
    </div>
    <DeltaLine delta={value === null ? null : delta} />
  </div>;
}

/* ============================================================== Figure == */

/**
 * A ledger figure: the name on one line, the number and its unit together on the
 * next, and the number set against the column's decimal spine.
 *
 * ONE UNIT GRAMMAR, AND THE MEASUREMENT THAT MADE IT POSSIBLE.
 *
 * The unit used to LEAD the number here while `Stat` — the panel directly to the
 * left on the same row — trails it, so `bps` appeared on both sides of its own
 * digits in one glance. The lead was not arbitrary: it was what protected the
 * spine. It is gone now, and this is the measurement that let it go.
 *
 * The spine was held by RIGHT-EDGE ANCHORING: the pair sat flush to the cell's
 * right wall and the fraction was drawn in a fixed 3ch slot, so the point landed
 * at `cellRight - 3ch` whatever the digits did. That construction cannot carry a
 * trailing unit. Everything right of the point has to keep a constant total
 * width for the point to stay put, so the empty fraction slot of a whole number
 * stays reserved — and a trailing unit is pushed clear of the last digit by the
 * full 3ch (measured: 42.6px on `39 funded` against 13.2px on `800.00 major
 * units`). That is the stranding this panel was fixed for in the first place.
 *
 * So the ANCHOR MOVES to the thing it was always meant to be. The whole part is
 * right-aligned into a track that ends at the point; the fraction and the unit
 * flow rightward from it. The point is now literally a track boundary, identical
 * for every figure in the column, and the unit sits one 6px gap from the last
 * glyph the number actually drew — 6px after `.00`, 6px after a bare `39`. The
 * tail track is the only reserved width left, and it is reserved on the side
 * where slack costs nothing but air.
 *
 * `tone` is the exceptionality channel and nothing else: a figure takes ink only
 * when the reading itself is exceptional — a treasury in deficit — never for
 * being large, and never merely for being money.
 */
export type FigureTone = "neutral" | "caution" | "neg";

export function Figure({
  label, value, unit, absent = "not recorded", title, tone = "neutral",
}: {
  label: ReactNode;
  /** null means "not received"; it renders as `absent`, never as 0. */
  value: string | null;
  unit?: ReactNode;
  absent?: string;
  title?: string;
  tone?: FigureTone;
}) {
  const parts = value === null ? null : splitDecimal(value);
  const spoken = typeof unit === "string" ? `${value} ${unit}` : value;
  return <div className="ae-fig" title={title}>
    <div className="ae-fig-lbl"><Cap>{label}</Cap></div>
    <div className={`ae-fig-val${tone === "neutral" ? "" : ` is-${tone}`}`}>
      {parts === null
        ? <Pending label={absent} />
        : <>
          {/* Anchoring on the point costs one thing: the number is drawn as two
              boxes, either side of that boundary. So the reading is given whole
              to assistive tech and the boxes are hidden from it — nobody hears
              "-750,481" and ".00" as two separate numbers. */}
          <span className="ae-sr">{spoken}</span>
          <span className="ae-num ae-fig-whole" aria-hidden="true">{parts.whole}</span>
          <span className="ae-fig-tail" aria-hidden="true">
            <span className="ae-num ae-fig-frac">{parts.fraction}</span>
            {unit ? <span className="ae-fig-unit">{unit}</span> : null}
          </span>
        </>}
    </div>
  </div>;
}

/* ========================================================= LatencyMeter == */

export type LatencySample = {
  label: string;
  ms: number | null;
  /** Still in flight: we show the wait so far rather than a length we cannot know. */
  pending?: boolean;
  /** Released later on purpose, so it is not in flight yet either. */
  queued?: boolean;
};

/**
 * Bar length is base-10 logarithmic over a fixed 1 ms – 30 s domain and says so.
 * A linear track cannot honestly hold 2 ms and 19 s at once; drawing them at
 * comparable lengths is not decoration, it is a false statement about the data.
 */
export function LatencyMeter({ samples }: { samples: LatencySample[] }) {
  return <div className="ae-lat">
    {/* The domain is printed once, by the axis below. Repeating it in the header
        made this line wrap into two ragged rows in the rail. */}
    <div className="ae-lat-head" title={`Base-10 log scale over ${LATENCY_FLOOR_MS} ms – ${LATENCY_CEILING_MS / 1000} s`}>
      <Cap>Source latency</Cap>
      <span className="ae-lat-scale">log scale</span>
    </div>
    {samples.map(sample => {
      const unresolved = Boolean(sample.pending || sample.queued);
      const slow = !unresolved && isSlow(sample.ms);
      const fraction = unresolved ? 0 : latencyBarFraction(sample.ms);
      return <div className="ae-latrow" key={sample.label}>
        <div className="ae-latrow-line">
          <span className="ae-latrow-k mono">{sample.label}</span>
          <span className="ae-latrow-v">
            {sample.queued ? "queued" : sample.pending ? "in flight" : latencyText(sample.ms) ?? "not measured"}
          </span>
        </div>
        <div className={`ae-latbar${slow ? " is-slow" : ""}${sample.pending && !sample.queued ? " is-pending" : ""}`}>
          <i style={{ width: `${(fraction * 100).toFixed(1)}%` }} />
        </div>
      </div>;
    })}
    {/* Midpoint of the log domain: sqrt(1 ms x 60 s) is about 245 ms, so the
        centre tick is where a reader expects it rather than where it looks nice. */}
    <div className="ae-lat-axis" aria-hidden="true">
      <span>1 ms</span><span>245 ms</span><span>60 s</span>
    </div>
  </div>;
}

/* ============================================================ DataTable == */

export type Column<T> = {
  key: string;
  label: string;
  /**
   * The floor, in px: the narrowest this column is ever allowed to be drawn.
   * Never a bare track, because a bare `1fr` track resolves to 0 the moment the
   * fixed tracks beside it outgrow the panel, and a 0-wide track still paints its
   * cell over its neighbour. Declaring the floor is what makes that impossible.
   */
  min: number;
  /**
   * Share of whatever space is left once every floor is paid. Omit (or 0) to pin
   * the column at its floor; the rest is split between the growing columns in
   * proportion. Both ledgers on this surface share one pitch.
   */
  grow?: number;
  align?: "left" | "right";
  render(row: T): ReactNode;
  /** Skeleton bar width for this column while the source is pending; null draws nothing. */
  skeleton?: string | null;
};

export type RowTone = "exception" | "caution" | undefined;

/** One gutter width for every ledger. It is also reserved in the floor below. */
export const TABLE_GAP = 9;

/**
 * The narrowest the ledger can be drawn with every column still at its declared
 * floor. The head and the body both carry it as a min-width, so when a panel is
 * genuinely too narrow the whole table scrolls sideways as one piece — header and
 * rows together — instead of collapsing a track to nothing and overprinting.
 */
export function tableFloor<T>(columns: Column<T>[]): number {
  const gutters = TABLE_GAP * Math.max(0, columns.length - 1);
  return columns.reduce((sum, column) => sum + column.min, 0) + gutters;
}

export function DataTable<T>({
  columns, rows, rowKey, rowTone, pending = false, skeletonRows = 12, empty, caption, onViewport,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey(row: T, index: number): string | number;
  rowTone?(row: T): RowTone;
  pending?: boolean;
  skeletonRows?: number;
  empty?: ReactNode;
  caption: string;
  /**
   * How many rows the body is actually showing. A ledger that has loaded forty
   * rows into a twelve-row window must not print "rows 1–40" under twelve rows,
   * so the footer is told what the reader can see rather than what was fetched.
   */
  onViewport?(rowsInView: number): void;
}) {
  const bodyRef = useRef<HTMLDivElement>(null);
  const report = useRef(onViewport);
  report.current = onViewport;

  useEffect(() => {
    const body = bodyRef.current;
    if (!body || !report.current || typeof ResizeObserver === "undefined") return;
    const measure = () => {
      const first = body.querySelector<HTMLElement>(".ae-trow:not(.is-skeleton)");
      const rowHeight = first?.offsetHeight ?? 0;
      /* Rounded, not floored: a row cut by the boundary is the scroll affordance
         and a reader counts it, so the number matches what is on the glass. */
      const fits = rowHeight > 0 ? Math.round(body.clientHeight / rowHeight) : 0;
      report.current?.(Math.max(0, Math.min(rows.length, fits)));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(body);
    return () => observer.disconnect();
  }, [rows.length, pending]);

  const template = columns
    .map(column => (column.grow ? `minmax(${column.min}px, ${column.grow}fr)` : `${column.min}px`))
    .join(" ");
  /* The gutter is a grid gap, never cell padding. Padding on a grid item is drawn
     outside its track and lands on the next column; a gap is subtracted from the
     space before the tracks are sized, so no cell can reach its neighbour. */
  const gridStyle: CSSProperties = { gridTemplateColumns: template, columnGap: `${TABLE_GAP}px` };
  const floorStyle: CSSProperties = { minWidth: `calc(${tableFloor(columns)}px + 2 * var(--ae-pad))` };

  return <div className="ae-table" role="table" aria-label={caption} aria-rowcount={pending ? undefined : rows.length}>
    <div className="ae-thead" role="row" style={{ ...gridStyle, ...floorStyle }}>
      {columns.map(column => <span
        key={column.key}
        role="columnheader"
        className={column.align === "right" ? "ae-r" : undefined}
      >{column.label}</span>)}
    </div>
    <div className="ae-tbody" ref={bodyRef} style={floorStyle}>
      {pending
        ? Array.from({ length: skeletonRows }, (_, index) => <div
          className="ae-trow is-skeleton" role="row" style={gridStyle} key={`skeleton-${index}`} aria-hidden="true"
        >
          {columns.map(column => <span key={column.key}>
            {column.skeleton === null
              ? null
              : <Skeleton dim={index % 2 === 1} width={column.skeleton ?? "72%"} />}
          </span>)}
        </div>)
        : rows.length
          ? rows.map((row, index) => {
            const tone = rowTone?.(row);
            return <div
              className={`ae-trow${tone ? ` is-${tone}` : ""}`}
              role="row"
              style={gridStyle}
              key={rowKey(row, index)}
            >
              {columns.map(column => <span
                key={column.key}
                role="cell"
                className={column.align === "right" ? "ae-r" : undefined}
              >{column.render(row)}</span>)}
            </div>;
          })
          : <div className="ae-tempty" role="row"><span role="cell">{empty}</span></div>}
    </div>
  </div>;
}

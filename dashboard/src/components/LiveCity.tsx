/*
 * THESIS: The city is the screen. Chrome floats on it; nothing frames it.
 * OWN-WORLD: A surveyed night field — three region halos on a coordinate
 *   graticule, places as fixed marks, people as moving light.
 * STORY: Read the clock, watch the commute leave home, follow it to work.
 * FIRST VIEWPORT: Edge-to-edge map, day clock top right, the interpolation
 *   disclosure pinned along the foot where it cannot be missed or dismissed.
 * MOTION: One requestAnimationFrame loop writing transforms. Every position is
 *   a recorded placement or a point on the segment between two of them.
 */
import {
  useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState,
  type RefObject,
} from "react";
import { Link, useParams } from "react-router";
import { useProjectionSocket } from "../app/useProjectionSocket";
import {
  DAY_MS,
  DAY_SLOTS,
  MAX_DECOLLISION_RADIUS_PX,
  chipScreenPoint,
  dayClock,
  decollisionLayout,
  fitProjection,
  normalizeLiveCity,
} from "../lib/liveCity.js";
import { EmptyState, SourceMeta, count, humanize, useSource } from "../ui";
import "./live-city.css";

/* ------------------------------------------------------------ the model -- */

type Placement = {
  slot: string;
  placeId: number;
  placeName: string | null;
  placeKind: string | null;
  sourceType: string | null;
  x: number;
  y: number;
};
type Anchor = Placement & { recorded: boolean };
type CityAgent = {
  id: number;
  name: string;
  role: string | null;
  occupation: string | null;
  placements: Record<string, Placement | undefined>;
  anchors: Anchor[];
  missingSlots: string[];
  moves: boolean;
};
type CityPlace = {
  id: number;
  name: string;
  kind: string;
  regionId: number | null;
  capacity: number | null;
  x: number;
  y: number;
  occupancy: Record<string, number> | null;
};
type CityRegion = {
  id: number;
  name: string;
  currency: string | null;
  population: number | null;
  firms: number | null;
  x: number;
  y: number;
};
type AnonymousGroup = {
  placeId: number;
  placeName: string | null;
  placeKind: string | null;
  x: number;
  y: number;
  occupancy: number;
};
type Bounds = { minX: number; minY: number; maxX: number; maxY: number };
type CityModel = {
  enabled: boolean;
  tick: number | null;
  agents: CityAgent[];
  places: CityPlace[];
  regions: CityRegion[];
  anonymous: AnonymousGroup[];
  bounds: Bounds;
  counts: {
    agents: number;
    places: number;
    recordedPlacements: number;
    commuters: number;
    withoutFullDay: number;
    anonymised: number;
    slots: Record<string, number>;
    sources: Record<string, number>;
  };
};
type Projection = {
  minX: number;
  minY: number;
  scaleX: number;
  scaleY: number;
  left: number;
  top: number;
  project(x: number, y: number): { x: number; y: number };
};
type Offset = { x: number; y: number; cohort: number; radius: number };
type Clock = {
  cycle: number;
  beatIndex: number;
  slot: string;
  nextSlot: string;
  travelling: boolean;
  t: number;
  dayProgress: number;
};
type RunStatus = { tick?: number; status?: string; next_phase?: string; running?: boolean };

/*
 * Chrome keeps its distance from the geography without cropping it. The map is
 * full-bleed — it runs under every overlay to the window edge — but recorded
 * points are laid inside this inset so no agent is ever hidden behind a panel.
 */
const CHROME_INSET = { top: 104, right: 72, bottom: 116, left: 72 };
const EMPTY_MODEL: CityModel = {
  enabled: true,
  tick: null,
  agents: [],
  places: [],
  regions: [],
  anonymous: [],
  bounds: { minX: 0, minY: 0, maxX: 1, maxY: 1 },
  counts: {
    agents: 0, places: 0, recordedPlacements: 0, commuters: 0,
    withoutFullDay: 0, anonymised: 0, slots: {}, sources: {},
  },
};

const BEAT_COPY: Record<string, { label: string; note: string }> = {
  morning: { label: "Morning", note: "at their recorded morning place" },
  business: { label: "Business", note: "at their recorded business place" },
  evening: { label: "Evening", note: "at their recorded evening place" },
};

function useElementSize(): [RefObject<HTMLDivElement | null>, { width: number; height: number }] {
  const ref = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return;
    const measure = () => setSize({ width: node.clientWidth, height: node.clientHeight });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return [ref, size];
}

/** Honours the OS setting the same way the rest of the app already does. */
function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () => typeof window !== "undefined"
      && Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches),
  );
  useEffect(() => {
    const query = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!query) return;
    const listen = () => setReduced(query.matches);
    query.addEventListener("change", listen);
    return () => query.removeEventListener("change", listen);
  }, []);
  return reduced;
}

/* ------------------------------------------------------------- surface -- */

export function LiveCity() {
  const { runId = "run" } = useParams();
  const transport = useProjectionSocket(false);
  const reducedMotion = useReducedMotion();
  const [frameRef, size] = useElementSize();

  const status = useSource<RunStatus>({
    key: ["live-city", runId, "run-status"],
    path: "/api/run/status",
    label: "/api/run/status",
    refetchInterval: 3000,
  });
  /*
   * The map is 408 KB and only changes when the tick does, so it is not polled.
   * The cheap status source carries the tick, and a new tick is what pulls a
   * fresh frame of truth. Between those pulls the city keeps moving on its own
   * clock — see the animation loop below.
   */
  const map = useSource<unknown>({
    key: ["live-city", runId, "map"],
    path: "/api/v2/map",
    label: "/api/v2/map",
  });

  const model = useMemo<CityModel>(
    () => (map.data ? (normalizeLiveCity(map.data) as CityModel) : EMPTY_MODEL),
    [map.data],
  );
  const offsets = useMemo<Map<string, Offset>>(
    () => decollisionLayout(model.agents) as Map<string, Offset>,
    [model.agents],
  );
  const projection = useMemo<Projection | null>(
    () => (size.width > 0 && size.height > 0
      ? (fitProjection(model.bounds, size.width, size.height, CHROME_INSET) as Projection)
      : null),
    [model.bounds, size.width, size.height],
  );

  const serverTick = status.data?.tick ?? null;
  const mapTick = model.tick;
  const refetchMap = map.refetch;
  useEffect(() => {
    if (serverTick === null || mapTick === null) return;
    if (serverTick !== mapTick) refetchMap();
  }, [serverTick, mapTick, refetchMap]);

  /* --------------------------------------------------------- the motion -- */

  const chipRefs = useRef(new Map<number, HTMLElement>());
  const chipClass = useRef(new Map<number, string>());
  const dayOrigin = useRef(0);
  const lastFrame = useRef<{
    clock: Clock;
    positions: Map<number, { x: number; y: number; offsetX: number; offsetY: number }>;
  } | null>(null);
  const scene = useRef<{
    agents: CityAgent[];
    offsets: Map<string, Offset>;
    projection: Projection | null;
    reducedMotion: boolean;
  }>({ agents: [], offsets: new Map(), projection: null, reducedMotion: false });
  const [phase, setPhase] = useState({ beatIndex: 0, travelling: false });
  const clockHand = useRef<HTMLElement | null>(null);

  /*
   * A new tick is a new frame of truth, so the recorded day restarts with it.
   * That is what keeps the loop honest on a paused run: the city is replaying
   * ONE tick's recorded placements, and the clock says which tick.
   */
  useEffect(() => {
    dayOrigin.current = performance.now();
  }, [mapTick]);

  const paint = useCallback((now: number) => {
    const { agents, offsets: layout, projection: camera, reducedMotion: still } = scene.current;
    if (!camera || !agents.length) return;
    const elapsed = now - dayOrigin.current;
    const clock = dayClock(elapsed) as Clock;
    /* Reduced motion keeps the day, drops the glide: chips sit at the beat's
       recorded placement and change position only on a beat boundary. */
    const effective: Clock = still ? { ...clock, travelling: false, t: 0 } : clock;
    const positions = new Map<number, { x: number; y: number; offsetX: number; offsetY: number }>();

    for (const agent of agents) {
      const point = chipScreenPoint(agent, effective, camera, layout) as {
        x: number; y: number; offsetX: number; offsetY: number;
        point: { from: Anchor; to: Anchor; moving: boolean };
      } | null;
      if (!point) continue;
      positions.set(agent.id, {
        x: point.x, y: point.y, offsetX: point.offsetX, offsetY: point.offsetY,
      });
      const node = chipRefs.current.get(agent.id);
      if (!node) continue;
      node.style.transform = `translate3d(${point.x.toFixed(2)}px, ${point.y.toFixed(2)}px, 0)`;
      const anchor = point.point.moving ? point.point.to : point.point.from;
      const className = [
        "live-city__chip",
        `live-city__chip--${anchor.sourceType || "unknown"}`,
        point.point.moving ? "is-moving" : "",
        anchor.recorded ? "" : "is-unrecorded",
      ].filter(Boolean).join(" ");
      if (chipClass.current.get(agent.id) !== className) {
        chipClass.current.set(agent.id, className);
        node.className = className;
      }
    }

    lastFrame.current = { clock: effective, positions };
    if (clockHand.current) {
      clockHand.current.style.setProperty("--live-city-day", String(clock.dayProgress));
    }
    /* Six re-renders per recorded day — one per beat and one per departure —
       so the words on the clock match the field without paying per frame. */
    setPhase(current => (
      current.beatIndex === effective.beatIndex && current.travelling === effective.travelling
        ? current
        : { beatIndex: effective.beatIndex, travelling: effective.travelling }
    ));
  }, []);

  /*
   * Scene and first placement in one layout effect: the chips are written to
   * their recorded positions before the browser paints, so no frame ever shows
   * three hundred people stacked at the origin waiting for the loop to start.
   */
  useLayoutEffect(() => {
    scene.current = { agents: model.agents, offsets, projection, reducedMotion };
    paint(performance.now());
  }, [model.agents, offsets, projection, reducedMotion, paint]);

  useEffect(() => {
    if (reducedMotion) {
      const timer = window.setInterval(() => paint(performance.now()), 1000);
      return () => window.clearInterval(timer);
    }
    let handle = 0;
    const step = (now: number) => {
      paint(now);
      handle = window.requestAnimationFrame(step);
    };
    handle = window.requestAnimationFrame(step);
    return () => window.cancelAnimationFrame(handle);
  }, [paint, reducedMotion]);

  /*
   * The motion-truth probe. A screenshot cannot show movement and cannot show
   * where movement came from, so the surface publishes its own numbers: the
   * camera, and for every chip the pixel it is drawn at, the de-collision
   * offset included in that pixel, and the recorded placements it is between.
   * A checker can then re-derive the answer from /api/v2/map and disagree.
   */
  useEffect(() => {
    const probe = () => {
      const frame = lastFrame.current;
      const { agents, projection: camera } = scene.current;
      if (!frame || !camera) return null;
      return {
        tick: mapTick,
        dayMs: DAY_MS,
        maxOffsetPx: MAX_DECOLLISION_RADIUS_PX,
        clock: frame.clock,
        projection: {
          minX: camera.minX, minY: camera.minY,
          scaleX: camera.scaleX, scaleY: camera.scaleY,
          left: camera.left, top: camera.top,
        },
        chips: agents.map(agent => {
          const position = frame.positions.get(agent.id);
          return {
            id: agent.id,
            x: position?.x ?? null,
            y: position?.y ?? null,
            offsetX: position?.offsetX ?? null,
            offsetY: position?.offsetY ?? null,
            anchors: agent.anchors.map(anchor => ({
              slot: anchor.slot, placeId: anchor.placeId,
              x: anchor.x, y: anchor.y, recorded: anchor.recorded,
            })),
          };
        }),
      };
    };
    const host = window as unknown as { __liveCityProbe?: () => unknown };
    host.__liveCityProbe = probe;
    return () => { delete host.__liveCityProbe; };
  }, [mapTick]);

  /* ---------------------------------------------------------- the frame -- */

  const regionHalos = useMemo(() => {
    if (!projection) return [];
    return model.regions.map(region => {
      const own = model.places.filter(place => place.regionId === region.id);
      const centre = projection.project(region.x, region.y);
      const radius = own.reduce((widest, place) => {
        const point = projection.project(place.x, place.y);
        return Math.max(widest, Math.hypot(point.x - centre.x, point.y - centre.y));
      }, 0);
      return { region, centre, radius: radius * 1.22 + 28, places: own.length };
    });
  }, [model.regions, model.places, projection]);

  /*
   * Anonymised counts sit ON the map, so near the right edge the label would
   * slide under the day clock. It flips to the other side of its marker there
   * instead — the marker never moves, only the words attached to it.
   */
  const anonMarks = useMemo(() => {
    if (!projection) return [];
    return model.anonymous.map(group => {
      const point = projection.project(group.x, group.y);
      return { group, point, flipped: point.x > size.width * 0.62 };
    });
  }, [model.anonymous, projection, size.width]);

  const { beatIndex, travelling } = phase;
  const nextIndex = (beatIndex + 1) % DAY_SLOTS.length;
  const beat = DAY_SLOTS[beatIndex] as string;
  const nextBeat = DAY_SLOTS[nextIndex] as string;
  const beatCopy = BEAT_COPY[beat] ?? BEAT_COPY.morning;
  const nextCopy = BEAT_COPY[nextBeat] ?? BEAT_COPY.morning;
  /* The people this leg actually moves: those whose two recorded placements
     name different places. Everyone else stays put, and is not counted. */
  const legMovers = useMemo(
    () => model.agents.filter(agent =>
      agent.anchors[beatIndex]?.placeId !== agent.anchors[nextIndex]?.placeId).length,
    [model.agents, beatIndex, nextIndex],
  );
  /* The sky follows the people: it starts turning when they set off, not when
     they arrive, so departure is legible from the field alone. */
  const skyBeat = travelling ? nextBeat : beat;
  const runStatus = status.data?.status ?? null;
  const paused = runStatus === "paused" || status.data?.running === false;
  const unresolved = map.pending || !projection;

  return <div className="live-city" ref={frameRef}>
    <div className="live-city__field" data-beat={skyBeat} aria-hidden="true">
      {projection && <svg className="live-city__terrain" width={size.width} height={size.height}>
        <defs>
          <radialGradient id="live-city-halo">
            <stop offset="0%" stopColor="var(--ae-city-halo-core)" />
            <stop offset="100%" stopColor="var(--ae-city-halo-edge)" />
          </radialGradient>
        </defs>
        {regionHalos.map(halo => <circle
          key={`halo-${halo.region.id}`}
          className="live-city__halo"
          cx={halo.centre.x} cy={halo.centre.y} r={halo.radius}
          fill="url(#live-city-halo)"
        />)}
        {regionHalos.map(halo => <circle
          key={`ring-${halo.region.id}`}
          className="live-city__ring"
          cx={halo.centre.x} cy={halo.centre.y} r={halo.radius}
        />)}
        {model.places.map(place => {
          const point = projection.project(place.x, place.y);
          return <circle
            key={`place-${place.id}`}
            className={`live-city__place live-city__place--${place.kind}`}
            cx={point.x} cy={point.y}
            r={place.kind === "firm_workplace" ? 2.1 : place.kind === "residential_district" ? 3.4 : 4.6}
          />;
        })}
      </svg>}

      {/*
        * Region names are a watermark UNDER the people, the way a map names a
        * district. Anchored on the region's own recorded centre, so the label
        * marks where the region actually is rather than wherever there happened
        * to be room, and quiet enough that three hundred chips read over it.
        */}
      {projection && <div className="live-city__marks live-city__marks--under">
        {regionHalos.map(halo => <div
          key={`label-${halo.region.id}`}
          className="live-city__region"
          style={{ left: `${halo.centre.x}px`, top: `${halo.centre.y}px` }}
        >
          <strong>{halo.region.name}</strong>
          <span>{count(halo.region.population) ?? "—"} residents · {count(halo.places)} places · {halo.region.currency || "—"}</span>
        </div>)}
      </div>}

      {projection && <div className="live-city__chips">
        {model.agents.map(agent => <div
          key={agent.id}
          className="live-city__chip"
          data-agent-id={agent.id}
          ref={node => {
            if (node) chipRefs.current.set(agent.id, node);
            else {
              chipRefs.current.delete(agent.id);
              chipClass.current.delete(agent.id);
            }
          }}
          title={`${agent.name} · ${humanize(agent.occupation || agent.role || "resident")}`}
        />)}
      </div>}

      {projection && <div className="live-city__marks">
        {anonMarks.map(({ group, point, flipped }) => <div
          key={`anon-${group.placeId}`}
          className={`live-city__anon${flipped ? " is-flipped" : ""}`}
          style={{ left: `${point.x}px`, top: `${point.y}px` }}
        >
          <i />
          <span><b>{count(group.occupancy)}</b> anonymised at {group.placeName || humanize(group.placeKind)}</span>
        </div>)}
      </div>}
    </div>

    <header className="live-city__masthead">
      <div className="live-city__identity">
        <p className="ae-cap">Live City</p>
        <h1>{model.regions.length ? model.regions.map(region => region.name).join(" · ") : "The recorded day"}</h1>
        <p className="live-city__run">
          <Link to={`/runs/${encodeURIComponent(runId)}/overview`}>← Workspaces</Link>
          <span className="mono">run {runId}</span>
          <span className={`live-city__pulse live-city__pulse--${paused ? "paused" : transport.status}`}>
            {paused ? "Paused" : humanize(transport.status)}
          </span>
        </p>
      </div>
      <dl className="live-city__readout">
        <div><dt>Tick</dt><dd className="ae-num">{mapTick ?? "—"}</dd></div>
        <div><dt>People</dt><dd className="ae-num">{count(model.counts.agents) ?? "—"}</dd></div>
        <div><dt>Placements</dt><dd className="ae-num">{count(model.counts.recordedPlacements) ?? "—"}</dd></div>
        <div><dt>Commuting</dt><dd className="ae-num">{count(model.counts.commuters) ?? "—"}</dd></div>
        <div><dt>Places</dt><dd className="ae-num">{count(model.counts.places) ?? "—"}</dd></div>
      </dl>
    </header>

    <aside className="live-city__clock" ref={clockHand} aria-live="polite">
      <p className="ae-cap">Recorded day{mapTick === null ? "" : ` · tick ${mapTick}`}</p>
      <strong className={travelling ? "is-travelling" : ""}>
        {travelling ? `${beatCopy.label} → ${nextCopy.label}` : beatCopy.label}
      </strong>
      <ol className="live-city__beats">
        {DAY_SLOTS.map((slot: string, index: number) => <li
          key={slot}
          className={index === (travelling ? nextIndex : beatIndex)
            ? "is-now"
            : index < beatIndex ? "is-past" : ""}
        >
          <span>{BEAT_COPY[slot].label}</span>
          <b className="ae-num">{count(model.counts.slots[slot]) ?? "—"}</b>
        </li>)}
      </ol>
      <div className="live-city__day-track"><i /></div>
      <small>{!model.counts.agents
        ? "Waiting for recorded placements."
        : travelling
          ? `${count(legMovers)} people between their recorded ${beat} and ${nextBeat} places.`
          : `${count(model.counts.slots[beat])} people ${beatCopy.note}.`}</small>
    </aside>

    <div className="live-city__legend">
      <p className="ae-cap">Where each person is</p>
      <ul>
        <li><i className="live-city__key live-city__key--routine_home" />At home</li>
        <li><i className="live-city__key live-city__key--routine_work" />At work</li>
        <li><i className="live-city__key live-city__key--public_commons" />In the commons</li>
        {model.counts.withoutFullDay > 0 && <li>
          <i className="live-city__key live-city__key--unrecorded" />
          {count(model.counts.withoutFullDay)} with no business placement recorded — held at their last
          recorded place, never moved
        </li>}
        {model.counts.anonymised > 0 && <li>
          <i className="live-city__key live-city__key--anon" />
          {count(model.counts.anonymised)} anonymised at licensing offices — shown as a count, never as people
        </li>}
      </ul>
    </div>

    <footer className="live-city__disclosure">
      <p>
        <b>Movement between recorded points is interpolated.</b> The world records three placements per person
        per tick — morning, business, evening. Chips glide in a straight line between those points; the journey
        itself is not recorded. Someone whose consecutive placements name the same place does not move.
      </p>
      <p className="live-city__provenance">
        <SourceMeta source={map} note={`${count(model.counts.recordedPlacements) ?? "0"} placements`} />
        <SourceMeta source={status} />
        {reducedMotion && <span>Reduced motion: chips step between placements without gliding.</span>}
      </p>
    </footer>

    {unresolved && !map.error && <div className="live-city__veil" role="status">
      <span className="ae-cap">Surveying the recorded day</span>
      <p>Placements arrive from <b className="mono">/api/v2/map</b> as one frame of truth per tick.</p>
    </div>}
    {map.error && <div className="live-city__veil" role="alert">
      <EmptyState title="The city cannot be drawn">
        {map.error.message}. Nothing is guessed in its place — no chip is shown without a recorded placement.
      </EmptyState>
    </div>}

    <p className="live-city__sr" role="status">
      {model.counts.agents
        ? `${model.counts.agents} people with ${model.counts.recordedPlacements} recorded placements across `
          + `${model.counts.places} places at tick ${mapTick ?? "unknown"}. `
          + (travelling
            ? `${legMovers} people are between their recorded ${beat} and ${nextBeat} places. `
            : `Now showing the ${beatCopy.label.toLowerCase()} beat: `
              + `${model.counts.slots[beat]} people ${beatCopy.note}. `)
          + `${model.counts.commuters} move between places during the day. `
          + `Positions between recorded placements are interpolated.`
        : "No recorded placements have been received yet."}
    </p>
  </div>;
}

/*
 * THESIS: The city is the screen. Chrome floats on it; nothing frames it.
 * OWN-WORLD: A surveyed night field — three territories drawn as the hull of
 *   their own places, on a coordinate graticule, people as moving light.
 * STORY: Read the clock, watch the commute leave home, follow ONE person to
 *   work — click a chip and it keeps its name, its halo and its whole recorded
 *   day for as long as you watch it.
 * FIRST VIEWPORT: Edge-to-edge map, day clock top right, the interpolation
 *   disclosure pinned along the foot where it cannot be missed or dismissed.
 * MOTION: One requestAnimationFrame loop writing transforms. Every position is
 *   a recorded placement or a point on the segment between two of them, and the
 *   glide fills the whole of its leg so no interval of the day is a still frame.
 */
import {
  useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
} from "react";
import { Link, useParams } from "react-router";
import { useProjectionSocket } from "../app/useProjectionSocket";
import {
  CROWD_MIN,
  DAY_MS,
  DAY_SLOTS,
  MAX_DECOLLISION_RADIUS_PX,
  chipScreenPoint,
  convexHull,
  dayClock,
  decollisionLayout,
  fitProjection,
  hullPath,
  legPlan,
  normalizeLiveCity,
  placeCohorts,
  slotWeights,
} from "../lib/liveCity.js";
import { EmptyState, count, humanize, useSource } from "../ui";
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
type Anchor = Placement & { recorded: boolean; regionId: number | null };
type CityAgent = {
  id: number;
  name: string;
  role: string | null;
  occupation: string | null;
  placements: Record<string, Placement | undefined>;
  anchors: Anchor[];
  missingSlots: string[];
  moves: boolean;
  longHaul: boolean;
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
  slots: Record<string, number>;
  occupancy: number;
};
type Crowd = {
  placeId: number;
  name: string | null;
  kind: string | null;
  x: number;
  y: number;
  slots: Record<string, number>;
  peak: number;
};
type Bounds = { minX: number; minY: number; maxX: number; maxY: number };
type CityModel = {
  enabled: boolean;
  tick: number | null;
  agents: CityAgent[];
  places: CityPlace[];
  regions: CityRegion[];
  anonymous: AnonymousGroup[];
  crowds: Crowd[];
  bounds: Bounds;
  counts: {
    agents: number;
    places: number;
    recordedPlacements: number;
    commuters: number;
    longHaul: number;
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
  width: number;
  height: number;
  project(x: number, y: number): { x: number; y: number };
};
type Offset = { x: number; y: number; cohort: number; radius: number };
type Disc = { members: number[]; cohort: number; radius: number; rotation: number };
type Clock = {
  cycle: number;
  legIndex: number;
  legMovers: number;
  beatIndex: number;
  nextIndex: number;
  nearIndex: number;
  slot: string;
  nextSlot: string;
  travelling: boolean;
  t: number;
  ease: number;
  dayProgress: number;
};
type Plan = ReturnType<typeof legPlan>;
type RunStatus = { tick?: number; status?: string; next_phase?: string; running?: boolean };

/*
 * Chrome keeps its distance from the geography without cropping it. The map is
 * full-bleed — it runs under every overlay to the window edge — but recorded
 * points are laid inside this inset so no agent is ever hidden behind a panel.
 *
 * The right inset is the wide one because the clock and the legend stack into a
 * right-hand column, and Ironvale Union's places run to the far right of the
 * coordinate space: at the old 72 px a third of that polity was drawn underneath
 * the day clock, which is exactly the "sparse scatter on the right" a reader
 * cannot resolve.
 */
const CHROME_INSET = { top: 108, right: 268, bottom: 132, left: 72 };
/* How much of the segment already covered is drawn behind a chip. Every pixel of
   a wake is a point on the same recorded segment the chip is travelling, so the
   trail is not an embellishment on the claim — it is the claim, drawn. */
const WAKE_MAX_PX = 54;
/* How far a territory's hull is pushed out from its outermost place, and how
   far beyond that its name plate sits. The plate must clear the boundary line
   entirely or it reads as a label ON the border rather than OF the polity. */
const HULL_PAD_PX = 26;
const PLATE_GAP_PX = 66;
const EMPTY_MODEL: CityModel = {
  enabled: true,
  tick: null,
  agents: [],
  places: [],
  regions: [],
  anonymous: [],
  crowds: [],
  bounds: { minX: 0, minY: 0, maxX: 1, maxY: 1 },
  counts: {
    agents: 0, places: 0, recordedPlacements: 0, commuters: 0, longHaul: 0,
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
  const discs = useMemo<Map<string, Disc>>(
    () => placeCohorts(model.agents) as Map<string, Disc>,
    [model.agents],
  );
  /*
   * The day's shape, derived from the day itself: each leg gets the share of the
   * 45 s that matches the share of the city's movement it carries. In this run
   * nobody at all moves between their evening and morning placements — every one
   * of the 300 names the same place for both — so that leg gets no wall time and
   * the day loops without a chip changing pixel. See liveCity.js.
   */
  const plan = useMemo<Plan>(() => legPlan(model.agents) as Plan, [model.agents]);
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
  const wakeRefs = useRef(new Map<number, HTMLElement>());
  const chipClass = useRef(new Map<number, string>());
  const crowdRefs = useRef(new Map<string, HTMLElement>());
  const anonRefs = useRef(new Map<string, HTMLElement>());
  const lockRef = useRef<HTMLDivElement | null>(null);
  const fieldRef = useRef<HTMLDivElement | null>(null);
  const dayOrigin = useRef(0);
  const lastFrame = useRef<{
    clock: Clock;
    positions: Map<number, { x: number; y: number; offsetX: number; offsetY: number }>;
  } | null>(null);
  const scene = useRef<{
    agents: CityAgent[];
    offsets: Map<string, Offset>;
    projection: Projection | null;
    plan: Plan;
    reducedMotion: boolean;
    focusId: number | null;
  }>({
    agents: [], offsets: new Map(), projection: null,
    plan: legPlan([]) as Plan, reducedMotion: false, focusId: null,
  });
  const [phase, setPhase] = useState({ legIndex: 0, nearIndex: 0 });
  const clockHand = useRef<HTMLElement | null>(null);

  /* Who the reader is following. Hover proposes; a click pins, so a person can
     be watched across the whole leg without keeping a cursor on a moving dot. */
  const [focus, setFocus] = useState<{ id: number; pinned: boolean } | null>(null);
  const focusAgent = useMemo(
    () => (focus ? model.agents.find(agent => agent.id === focus.id) ?? null : null),
    [focus, model.agents],
  );

  /*
   * A new tick is a new frame of truth, so the recorded day restarts with it.
   * That is what keeps the loop honest on a paused run: the city is replaying
   * ONE tick's recorded placements, and the clock says which tick.
   */
  useEffect(() => {
    dayOrigin.current = performance.now();
  }, [mapTick]);

  const paint = useCallback((now: number) => {
    const {
      agents, offsets: layout, projection: camera,
      plan: legs, reducedMotion: still, focusId,
    } = scene.current;
    if (!camera || !agents.length) return;
    const elapsed = now - dayOrigin.current;
    const clock = dayClock(elapsed, legs) as Clock;
    /* Reduced motion keeps the day, drops the glide: chips sit at the leg's
       recorded placement and change position only on a leg boundary. */
    const effective: Clock = still ? { ...clock, t: 0, ease: 0 } : clock;
    const positions = new Map<number, { x: number; y: number; offsetX: number; offsetY: number }>();

    for (const agent of agents) {
      const point = chipScreenPoint(agent, effective, camera, layout) as {
        x: number; y: number; offsetX: number; offsetY: number;
        travelledPx: number; headingDeg: number;
        point: { from: Anchor; to: Anchor; moving: boolean; t: number };
      } | null;
      if (!point) continue;
      positions.set(agent.id, {
        x: point.x, y: point.y, offsetX: point.offsetX, offsetY: point.offsetY,
      });
      const node = chipRefs.current.get(agent.id);
      if (!node) continue;
      node.style.transform = `translate3d(${point.x.toFixed(2)}px, ${point.y.toFixed(2)}px, 0)`;
      /*
       * WHICH PLACE COLOURS THE CHIP. The first half of a leg keeps the hue of
       * where the person still mostly is; the second half takes the hue of where
       * they are arriving. So the At home / At work / In the commons code is
       * carried THROUGH the journey rather than surrendered for the duration of
       * it, and the turn of the field from blue to green IS the commute.
       */
      const anchor = point.point.t < 0.5 ? point.point.from : point.point.to;
      const className = [
        "live-city__chip",
        `live-city__chip--${anchor.sourceType || "unknown"}`,
        point.point.moving ? "is-moving" : "",
        anchor.recorded ? "" : "is-unrecorded",
        focusId === agent.id ? "is-focus" : "",
      ].filter(Boolean).join(" ");
      if (chipClass.current.get(agent.id) !== className) {
        chipClass.current.set(agent.id, className);
        node.className = className;
      }
      const wake = wakeRefs.current.get(agent.id);
      if (wake) {
        const length = Math.min(WAKE_MAX_PX, point.travelledPx);
        wake.style.transform = length > 0.5
          ? `rotate(${(point.headingDeg + 180).toFixed(1)}deg) scaleX(${length.toFixed(1)})`
          : "scaleX(0)";
      }
    }

    /*
     * Marks that belong to a recorded SLOT rather than to a moment — a crowd's
     * headcount, an anonymised office's occupancy — carry the weight of that
     * slot in the current leg. A figure the world recorded only for `business`
     * is therefore absent from the field in the evening instead of sitting there
     * asserting itself, which is what a permanently pinned label does.
     */
    const weights = slotWeights(effective) as number[];
    for (const [key, node] of crowdRefs.current) {
      const slotIndex = Number(key.slice(key.lastIndexOf(":") + 1));
      node.style.opacity = weights[slotIndex].toFixed(3);
    }
    for (const [key, node] of anonRefs.current) {
      const slotIndex = Number(key.slice(key.lastIndexOf(":") + 1));
      node.style.opacity = weights[slotIndex].toFixed(3);
    }

    if (lockRef.current) {
      const held = focusId === null ? null : positions.get(focusId);
      lockRef.current.style.transform = held
        ? `translate3d(${held.x.toFixed(2)}px, ${held.y.toFixed(2)}px, 0)`
        : "translate3d(-999px, -999px, 0)";
      /* The plate hangs off the right of the halo until the person it follows is
         far enough right that it would run off the window, and then off the
         left. The halo never moves — only the words attached to it. */
      lockRef.current.classList.toggle(
        "is-flipped",
        Boolean(held && held.x > camera.width * 0.62),
      );
    }

    lastFrame.current = { clock: effective, positions };
    if (clockHand.current) {
      clockHand.current.style.setProperty("--live-city-day", String(clock.dayProgress));
      clockHand.current.style.setProperty("--live-city-leg", String(effective.ease));
    }
    /*
     * Four re-renders per recorded day — one per leg and one per half-leg, where
     * the sky and the phase label hand over. The words on the clock therefore
     * turn WITH the field, without paying React a frame.
     */
    setPhase(current => (
      current.legIndex === effective.legIndex && current.nearIndex === effective.nearIndex
        ? current
        : { legIndex: effective.legIndex, nearIndex: effective.nearIndex }
    ));
  }, []);

  /*
   * Scene and first placement in one layout effect: the chips are written to
   * their recorded positions before the browser paints, so no frame ever shows
   * three hundred people stacked at the origin waiting for the loop to start.
   */
  useLayoutEffect(() => {
    scene.current = {
      agents: model.agents, offsets, projection, plan, reducedMotion,
      focusId: focus?.id ?? null,
    };
    paint(performance.now());
  }, [model.agents, offsets, projection, plan, reducedMotion, focus, paint]);

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

  useEffect(() => {
    if (!focus?.pinned) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFocus(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [focus?.pinned]);

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
      const { agents, projection: camera, plan: legs } = scene.current;
      if (!frame || !camera) return null;
      return {
        tick: mapTick,
        dayMs: legs.dayMs ?? DAY_MS,
        legs: legs.legs.map(leg => ({
          fromSlot: leg.fromSlot, toSlot: leg.toSlot, movers: leg.movers, ms: leg.ms,
        })),
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

  /*
   * TERRITORY, DERIVED. A region's ground is the convex hull of the places it
   * owns — every place carries a region_id and a coordinate, so this is a
   * reading of the data, not a decoration on top of it. Nothing is drawn beyond
   * the outermost place a polity actually holds.
   */
  const territories = useMemo(() => {
    if (!projection) return [];
    return model.regions.map(region => {
      const own = model.places.filter(place => place.regionId === region.id);
      const hull = (convexHull(own) as { x: number; y: number }[])
        .map(point => projection.project(point.x, point.y));
      const centre = hull.length
        ? {
          x: hull.reduce((sum, point) => sum + point.x, 0) / hull.length,
          y: hull.reduce((sum, point) => sum + point.y, 0) / hull.length,
        }
        : projection.project(region.x, region.y);
      const top = hull.reduce((least, point) => Math.min(least, point.y), Infinity);
      const bottom = hull.reduce((most, point) => Math.max(most, point.y), -Infinity);
      /*
       * The name plate goes on the side of the territory that faces the middle
       * of the canvas — which is where the empty band between the polities is.
       * It reads as a map's own margin note, it never sits under the people, and
       * it puts something worth reading in the part of the field that had
       * nothing in it.
       */
      const below = centre.y < size.height / 2;
      return {
        region,
        places: own.length,
        path: hullPath(hull, { pad: HULL_PAD_PX }) as string,
        centre,
        label: {
          x: centre.x,
          y: below ? bottom + PLATE_GAP_PX : top - PLATE_GAP_PX,
        },
        below,
      };
    });
  }, [model.regions, model.places, projection, size.height]);

  /*
   * The coordinate graticule. Not terrain and not invented: it is the map's own
   * normalised coordinate system, drawn at 0.1 intervals so the void between
   * territories has a surface and a sense of distance instead of being black.
   */
  const graticule = useMemo(() => {
    if (!projection) return { vertical: [], horizontal: [] };
    const step = 0.1;
    const lines = (min: number, max: number) => {
      const out: number[] = [];
      for (let value = Math.ceil(min / step) * step; value < max; value += step) {
        out.push(Number(value.toFixed(2)));
      }
      return out;
    };
    return {
      vertical: lines(model.bounds.minX, model.bounds.maxX)
        .map(value => ({ value, x: projection.project(value, 0).x })),
      horizontal: lines(model.bounds.minY, model.bounds.maxY)
        .map(value => ({ value, y: projection.project(0, value).y })),
    };
  }, [projection, model.bounds]);

  /*
   * A crowd is drawn as a ring at the radius its de-collision spiral actually
   * occupies, with its own headcount written in it. Without the number a place
   * holding four people and a place holding forty-two are the same smudge; the
   * ring is what ties the number to the smudge it describes.
   */
  const crowdMarks = useMemo(() => {
    if (!projection) return [];
    const marks: {
      key: string; slotIndex: number; slot: string; count: number;
      x: number; y: number; radius: number; name: string | null;
    }[] = [];
    for (const crowd of model.crowds) {
      const disc = discs.get(String(crowd.placeId));
      const point = projection.project(crowd.x, crowd.y);
      DAY_SLOTS.forEach((slot, slotIndex) => {
        const headcount = crowd.slots[slot] ?? 0;
        if (headcount < CROWD_MIN) return;
        marks.push({
          key: `${crowd.placeId}:${slotIndex}`,
          slotIndex,
          slot,
          count: headcount,
          x: point.x,
          y: point.y,
          radius: Math.max(11, (disc?.radius ?? 0) + 7),
          name: crowd.name,
        });
      });
    }
    return marks;
  }, [model.crowds, discs, projection]);

  /*
   * Anonymised occupancy, per slot. Every one of this run's three rows is a
   * `business` row, so these marks are simply not on the field during the
   * morning or the evening — the round-one build summed them across the day and
   * left an evening label asserting a count nobody recorded for the evening.
   */
  const anonMarks = useMemo(() => {
    if (!projection) return [];
    const marks: {
      key: string; slotIndex: number; occupancy: number;
      x: number; y: number; name: string;
    }[] = [];
    for (const group of model.anonymous) {
      const point = projection.project(group.x, group.y);
      DAY_SLOTS.forEach((slot, slotIndex) => {
        const occupancy = group.slots?.[slot] ?? 0;
        if (occupancy <= 0) return;
        marks.push({
          key: `${group.placeId}:${slotIndex}`,
          slotIndex,
          occupancy,
          x: point.x,
          y: point.y,
          name: group.placeName || humanize(group.placeKind),
        });
      });
    }
    return marks;
  }, [model.anonymous, projection]);

  /* The person being followed, drawn as their whole recorded day: the closed
     path through their three placements, which is the entire itinerary. */
  const focusDay = useMemo(() => {
    if (!focusAgent || !projection) return null;
    const points = focusAgent.anchors.map(anchor => projection.project(anchor.x, anchor.y));
    return {
      path: `M ${points.map(point => `${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(" L ")} Z`,
      points,
    };
  }, [focusAgent, projection]);

  const { legIndex, nearIndex } = phase;
  const leg = plan.legs[legIndex] ?? plan.legs[0];
  const fromCopy = BEAT_COPY[leg?.fromSlot ?? "morning"] ?? BEAT_COPY.morning;
  const toCopy = BEAT_COPY[leg?.toSlot ?? "business"] ?? BEAT_COPY.business;
  const nearSlot = DAY_SLOTS[nearIndex] as string;
  const nearCopy = BEAT_COPY[nearSlot] ?? BEAT_COPY.morning;
  /* The sky follows the people: it hands over at the half-way point of each leg,
     so departure and arrival are both legible from the field alone. */
  const skyBeat = nearSlot;
  const runStatus = status.data?.status ?? null;
  const paused = runStatus === "paused" || status.data?.running === false;
  const unresolved = map.pending || !projection;
  const legSeconds = leg ? Math.round(leg.ms / 1000) : 0;
  /* Every move the tick records, summed over the legs — the denominator the
     clock's wall time is a share of. */
  const dayMoves = plan.movers.reduce((sum: number, movers: number) => sum + movers, 0);

  const agentUnder = (target: EventTarget | null): number | null => {
    const node = (target as HTMLElement | null)?.closest?.("[data-agent-id]") as HTMLElement | null;
    const id = Number(node?.dataset?.agentId);
    return Number.isFinite(id) ? id : null;
  };
  const onChipPointer = (event: ReactPointerEvent<HTMLDivElement>) => {
    const id = agentUnder(event.target);
    if (id === null) return;
    setFocus(current => (current?.pinned ? current : { id, pinned: false }));
  };
  const onChipClick = (event: ReactMouseEvent<HTMLDivElement>) => {
    const id = agentUnder(event.target);
    if (id === null) { setFocus(null); return; }
    setFocus(current => (current?.id === id && current.pinned ? null : { id, pinned: true }));
  };

  return <div className="live-city" ref={frameRef}>
    <div className="live-city__field" data-beat={skyBeat} ref={fieldRef}>
      {projection && <svg
        className="live-city__terrain"
        width={size.width}
        height={size.height}
        aria-hidden="true"
      >
        <g className="live-city__graticule">
          {graticule.vertical.map(line => <line
            key={`gx-${line.value}`}
            x1={line.x} y1={CHROME_INSET.top - 24}
            x2={line.x} y2={size.height - CHROME_INSET.bottom + 24}
          />)}
          {graticule.horizontal.map(line => <line
            key={`gy-${line.value}`}
            x1={CHROME_INSET.left - 24} y1={line.y}
            x2={size.width - CHROME_INSET.right + 24} y2={line.y}
          />)}
        </g>
        {territories.map(territory => <path
          key={`land-${territory.region.id}`}
          className="live-city__land"
          d={territory.path}
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
        {focusDay && <path className="live-city__focus-day" d={focusDay.path} />}
        {focusDay?.points.map((point, index) => <circle
          key={`focus-anchor-${index}`}
          className="live-city__focus-anchor"
          cx={point.x} cy={point.y} r={4.5}
        />)}
      </svg>}

      {/*
        * The territory name plates. A map's own margin note: set on a plate at
        * readable weight, placed OUTSIDE the hull on the side that faces the
        * empty middle of the field, so the people never shred the letterforms
        * and the void between polities carries something worth reading.
        */}
      {projection && <div className="live-city__marks live-city__marks--under" aria-hidden="true">
        {territories.map(territory => <div
          key={`label-${territory.region.id}`}
          className={`live-city__territory${territory.below ? " is-below" : ""}`}
          style={{ left: `${territory.label.x}px`, top: `${territory.label.y}px` }}
        >
          <strong>{territory.region.name}</strong>
          <span>
            {count(territory.region.population) ?? "—"} residents ·
            {" "}{count(territory.places)} places ·
            {" "}{territory.region.currency || "—"}
          </span>
        </div>)}
      </div>}

      {projection && <div className="live-city__marks live-city__marks--crowds" aria-hidden="true">
        {crowdMarks.map(mark => <div
          key={`crowd-${mark.key}`}
          className="live-city__crowd"
          style={{
            left: `${mark.x}px`,
            top: `${mark.y}px`,
            width: `${mark.radius * 2}px`,
            height: `${mark.radius * 2}px`,
          }}
          ref={node => {
            if (node) crowdRefs.current.set(`crowd:${mark.key}`, node);
            else crowdRefs.current.delete(`crowd:${mark.key}`);
          }}
        >
          <i />
          <b className="ae-num">{mark.count}</b>
        </div>)}
      </div>}

      {projection && <div
        className="live-city__chips"
        aria-hidden="true"
        onPointerOver={onChipPointer}
        onPointerLeave={() => setFocus(current => (current?.pinned ? current : null))}
        onClick={onChipClick}
      >
        {model.agents.map(agent => <div
          key={agent.id}
          className="live-city__chip"
          data-agent-id={agent.id}
          data-haul={agent.longHaul ? "1" : undefined}
          ref={node => {
            if (node) chipRefs.current.set(agent.id, node);
            else {
              chipRefs.current.delete(agent.id);
              chipClass.current.delete(agent.id);
            }
          }}
        >
          <i
            className="live-city__wake"
            ref={node => {
              if (node) wakeRefs.current.set(agent.id, node);
              else wakeRefs.current.delete(agent.id);
            }}
          />
        </div>)}
      </div>}

      {projection && <div className="live-city__marks" aria-hidden="true">
        {anonMarks.map(mark => <div
          key={`anon-${mark.key}`}
          className="live-city__anon"
          style={{ left: `${mark.x}px`, top: `${mark.y}px` }}
          ref={node => {
            if (node) anonRefs.current.set(`anon:${mark.key}`, node);
            else anonRefs.current.delete(`anon:${mark.key}`);
          }}
        >
          <i />
          <b className="ae-num">{mark.occupancy}</b>
        </div>)}
      </div>}

      {/* The lock-on. It rides the chip's own pixel every frame, so the person
          you chose keeps a name and a halo while three hundred others move. */}
      <div
        className={`live-city__lockon${focusAgent ? " is-on" : ""}${focus?.pinned ? " is-pinned" : ""}`}
        ref={lockRef}
        aria-hidden="true"
      >
        <i />
        {focusAgent && <div className="live-city__lockon-plate">
          <strong>{focusAgent.name}</strong>
          <span>{humanize(focusAgent.occupation || focusAgent.role || "resident")}</span>
          <ol>
            {focusAgent.anchors.map(anchor => <li key={anchor.slot}>
              <b>{BEAT_COPY[anchor.slot]?.label ?? anchor.slot}</b>
              <span>{anchor.placeName || humanize(anchor.placeKind)}</span>
              {!anchor.recorded && <em>not recorded — held</em>}
            </li>)}
          </ol>
          <p>{focus?.pinned ? "Pinned · Esc to release" : "Click to pin"}</p>
        </div>}
      </div>
    </div>

    <header className="live-city__masthead">
      <div className="live-city__identity">
        <p className="ae-cap">Street level · <span className="mono">run {runId}</span></p>
        <h1>The recorded day</h1>
        <p className="live-city__run">
          <Link to={`/runs/${encodeURIComponent(runId)}/overview`}>← Workspaces</Link>
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
        <div><dt>Cross-border</dt><dd className="ae-num">{count(model.counts.longHaul) ?? "—"}</dd></div>
      </dl>
    </header>

    <aside className="live-city__clock" ref={clockHand} aria-live="polite">
      <p className="ae-cap">Recorded day{mapTick === null ? "" : ` · tick ${mapTick}`}</p>
      <strong>{fromCopy.label} → {toCopy.label}</strong>
      <ol className="live-city__beats">
        {DAY_SLOTS.map((slot: string, index: number) => <li
          key={slot}
          className={index === nearIndex ? "is-now" : index === leg?.fromIndex ? "is-past" : ""}
        >
          <span>{BEAT_COPY[slot].label}</span>
          <b className="ae-num">{count(model.counts.slots[slot]) ?? "—"}</b>
        </li>)}
      </ol>
      <div className="live-city__leg-track"><i /></div>
      <div className="live-city__day-track"><i /></div>
      <small>
        {!model.counts.agents
          ? "Waiting for recorded placements."
          : `${count(leg?.movers ?? 0)} people are between their recorded `
            + `${leg?.fromSlot} and ${leg?.toSlot} places. It runs for ${legSeconds} s: `
            + `this leg's share of the ${count(dayMoves)} moves the tick records.`}
      </small>
    </aside>

    <div className="live-city__legend">
      <p className="ae-cap">Where each person is</p>
      <ul>
        <li><i className="live-city__key live-city__key--routine_home" />At home</li>
        <li><i className="live-city__key live-city__key--routine_work" />At work</li>
        <li><i className="live-city__key live-city__key--public_commons" />In the commons</li>
        <li><i className="live-city__key live-city__key--haul" />
          {count(model.counts.longHaul)} whose day crosses a border — drawn a size up, ringed
        </li>
        <li><i className="live-city__key live-city__key--crowd" />
          A ring and a count wherever {CROWD_MIN} or more share one place
        </li>
        {model.counts.withoutFullDay > 0 && <li>
          <i className="live-city__key live-city__key--unrecorded" />
          {count(model.counts.withoutFullDay)} with no business placement recorded — held at their last
          recorded place, never moved
        </li>}
        {model.counts.anonymised > 0 && <li>
          <i className="live-city__key live-city__key--anon" />
          {count(model.counts.anonymised)} anonymised at licensing offices — a count in the slot it was
          recorded in, never people
        </li>}
      </ul>
      <p className="live-city__hint">Click anyone to follow them.</p>
    </div>

    <footer className="live-city__disclosure">
      <p>
        <b>Movement between recorded points is interpolated.</b> The world records three placements per person
        per tick — morning, business, evening. Chips glide in a straight line between those points; the journey
        itself is not recorded. Someone whose consecutive placements name the same place does not move.
      </p>
      <p className="live-city__provenance">
        <span>{count(model.counts.recordedPlacements) ?? "0"} placements recorded at tick {mapTick ?? "—"}</span>
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
          + `${model.counts.places} places in ${model.regions.length} regions at tick ${mapTick ?? "unknown"}. `
          + `Now showing the leg from the recorded ${leg?.fromSlot} placement to the recorded `
          + `${leg?.toSlot} placement, which moves ${leg?.movers ?? 0} people. `
          + `${model.counts.commuters} move between places during the day, `
          + `${model.counts.longHaul} of them across a regional border. `
          + `The field is nearest the ${nearCopy.label.toLowerCase()} placement. `
          + `Positions between recorded placements are interpolated.`
        : "No recorded placements have been received yet."}
    </p>
  </div>;
}

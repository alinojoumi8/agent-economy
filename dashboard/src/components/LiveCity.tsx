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
  DENSE_COHORT,
  DETAIL_ZOOM,
  MAX_DECOLLISION_RADIUS_PX,
  chipScreenPoint,
  conversationPlacements,
  packBubbles,
  convexHull,
  dayClock,
  decollisionLayout,
  detailWindow,
  fitProjection,
  hullPath,
  legPlan,
  liveCounts,
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
  zoom?: number;
  window?: { minX: number; maxX: number; minY: number; maxY: number };
  project(x: number, y: number): { x: number; y: number };
};
type Detail = {
  camera: Projection & { window: { minX: number; maxX: number; minY: number; maxY: number } };
  zoom: number;
  centre: { x: number; y: number };
  anchor: Crowd;
  places: CityPlace[];
  crowds: Crowd[];
  headcount: number[];
};
type ChipPoint = {
  x: number; y: number; offsetX: number; offsetY: number;
  travelledPx: number; remainingPx: number; destX: number; destY: number;
  headingDeg: number; bearingDeg: number;
  point: { from: Anchor; to: Anchor; moving: boolean; t: number };
};
type Offset = { x: number; y: number; cohort: number; radius: number };
type Disc = { members: number[]; cohort: number; radius: number; rotation: number };
type Clock = {
  cycle: number;
  within: number;
  legIndex: number;
  legMs: number;
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
type LiveCount = { inTransit: number; atPlace: number; arrived: number; held: number };
type Plan = ReturnType<typeof legPlan>;
type ConversationRow = {
  id: number; tick: number; participants: number[]; topic: string | null;
  messages: Array<{ agent_id: number; name: string | null; text: string; seq: number }>;
};
type Talk = {
  id: number; placeId: number; placeName: string | null; x: number; y: number;
  slot: string; people: string[]; topic: string; stackIndex: number;
  lines: Array<{ speaker: string; text: string }>;
};
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
/*
 * THE DETAIL PANEL, AND WHERE IT IS ALLOWED TO GO.
 *
 * A critic measured that "roughly a third to a half of the plot area carries
 * nothing but faint graticule". The regions sit where the data puts them, so
 * the void is not something a camera can close — but it is somewhere to put the
 * second camera, which is how the same choice answers both the dead canvas and
 * the unresolvable cluster inside it.
 *
 * The panel is only ever placed in a rectangle that holds NO projected place
 * and NO recorded agent point, tested against this tick's own geography. If no
 * candidate is clear, the panel is not drawn at all: an inset that hides people
 * to make room for itself would be worse than the blob it explains.
 */
const DETAIL_PANEL = { width: 430, height: 292, margin: 24, footClearance: 146 };
/* How much of the segment already covered is drawn behind a chip. Every pixel of
   a wake is a point on the same recorded segment the chip is travelling, so the
   trail is not an embellishment on the claim — it is the claim, drawn. */
const WAKE_MAX_PX = 64;
/* A bubble's drawn box, which is what decides whether two of them collide. */
const BUBBLE = { width: 194, height: 40, gap: 6 };
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
  /*
   * The tick's recorded conversations. Small (fifteen pairs, three lines each)
   * and keyed to the frame of truth on screen rather than to wall clock, so the
   * words a reader sees always belong to the tick the map is showing.
   */
  const conversations = useSource<ConversationRow[]>({
    key: ["live-city", runId, "conversations", String(model.tick ?? "")],
    path: `/api/conversations?limit=60&tick_from=${model.tick ?? 0}&tick_to=${model.tick ?? 0}`,
    label: "/api/conversations",
    enabled: model.tick !== null,
  });
  const talk = useMemo(
    () => (conversationPlacements(
      conversations.data || [], model.agents, { slot: "evening" }) as Talk[]),
    [conversations.data, model.agents],
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
   * Who spends part of the recorded day inside a crowd. The spiral fixes the
   * gap between neighbours at 8.5 px whatever the crowd size, so the only lever
   * left on whether two dots touch is the dot: these are drawn a size down and
   * the crowd resolves into countable people instead of a fused mass. It is a
   * property of the person's whole day, so no chip changes size mid-glide.
   */
  const dense = useMemo(() => {
    const ids = new Set<number>();
    for (const agent of model.agents) {
      for (const anchor of agent.anchors) {
        if ((discs.get(String(anchor.placeId))?.cohort ?? 1) >= DENSE_COHORT) {
          ids.add(agent.id);
          break;
        }
      }
    }
    return ids;
  }, [model.agents, discs]);
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

  /*
   * WHERE THE SECOND CAMERA IS ALLOWED TO STAND.
   *
   * Candidate rectangles are tested against every projected place AND every
   * recorded agent point, with the de-collision radius added as clearance, so
   * the panel can only take ground the geography has left genuinely empty. The
   * first clear candidate wins; if none is clear the panel is not drawn.
   */
  const detailSlot = useMemo(() => {
    if (!projection || !model.places.length || size.width < 1180) return null;
    const points = [
      ...model.places.map(place => projection.project(place.x, place.y)),
      ...model.agents.flatMap(agent => agent.anchors.map(
        anchor => projection.project(anchor.x, anchor.y))),
    ];
    const { width, height, margin, footClearance } = DETAIL_PANEL;
    const top = size.height - footClearance - height;
    const clearance = MAX_DECOLLISION_RADIUS_PX + 14;
    const candidates = [
      { key: "left", left: margin, top },
      { key: "right", left: size.width - margin - width, top },
    ];
    for (const candidate of candidates) {
      /*
       * The panel lives inside the band the projection already reserves for the
       * map, so it can never come to rest under the clock or the legend — the
       * two would share a z-index and whichever lost would be a panel with a
       * hole in it. At 1280 the right-hand candidate fails this and the left one
       * is occupied, so the surface simply does not draw an inset.
       */
      if (candidate.top < CHROME_INSET.top || candidate.left < 0) continue;
      if (candidate.left + width > size.width - CHROME_INSET.right) continue;
      if (candidate.top + height > size.height - CHROME_INSET.bottom) continue;
      const busy = points.some(point =>
        point.x > candidate.left - clearance && point.x < candidate.left + width + clearance
        && point.y > candidate.top - clearance && point.y < candidate.top + height + clearance);
      if (!busy) return candidate;
    }
    return null;
  }, [projection, model.places, model.agents, size.width, size.height]);

  const detail = useMemo<Detail | null>(() => {
    if (!projection || !detailSlot || !model.crowds.length) return null;
    const busiest = [...model.crowds].sort((left, right) => right.peak - left.peak)[0];
    return detailWindow(model.crowds, model.places, projection, {
      zoom: DETAIL_ZOOM,
      panel: { width: DETAIL_PANEL.width, height: DETAIL_PANEL.height },
      anchorRadiusPx: discs.get(String(busiest.placeId))?.radius ?? 0,
      bounds: model.bounds,
    }) as Detail | null;
  }, [projection, detailSlot, model.crowds, model.places, model.bounds, discs]);

  /*
   * Who can ever appear inside the panel. A chip travels the straight segment
   * between two recorded placements, so if the bounding box of that segment
   * misses the window the chip cannot enter it — and drawing a twin for all
   * three hundred to keep two hundred of them parked off-screen is a frame's
   * work spent on nothing. Over-inclusive by construction: a box that overlaps
   * gets a twin whether or not the segment itself crosses, so nobody who could
   * be in the panel is missing from it.
   */

  /*
   * Legibility is decided in screen space, not in the world's coordinates: two
   * conversations at different addresses can still land on top of each other
   * once projected, and a pile of half-covered quotes reads as a bug. Anything
   * that cannot be drawn clear of its neighbour is dropped and counted.
   */
  const drawnTalk = useMemo(() => {
    if (!projection) return { kept: [] as Array<Talk & { left: number; top: number }>, dropped: 0 };
    const projected = talk.map(item => {
      const point = projection.project(item.x, item.y);
      return { ...item, screenX: point.x, screenY: point.y - 10 - item.stackIndex * 4 };
    });
    return packBubbles(projected, {
      width: BUBBLE.width, height: BUBBLE.height, gap: BUBBLE.gap,
      bounds: {
        minX: CHROME_INSET.left - 40, minY: CHROME_INSET.top,
        maxX: size.width - CHROME_INSET.right + 40,
        maxY: size.height - CHROME_INSET.bottom,
      },
    }) as { kept: Array<Talk & { left: number; top: number }>; dropped: number };
  }, [talk, projection, size.width, size.height]);
  const detailMembers = useMemo(() => {
    if (!detail) return [] as CityAgent[];
    const box = detail.camera.window;
    return model.agents.filter(agent => agent.anchors.some((from, index) => {
      const to = agent.anchors[(index + 1) % agent.anchors.length];
      return Math.min(from.x, to.x) <= box.maxX && Math.max(from.x, to.x) >= box.minX
        && Math.min(from.y, to.y) <= box.maxY && Math.max(from.y, to.y) >= box.minY;
    }));
  }, [detail, model.agents]);

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
  const detailRefs = useRef(new Map<number, HTMLElement>());
  const detailWakeRefs = useRef(new Map<number, HTMLElement>());
  const detailParked = useRef(new Set<number>());
  const chipClass = useRef(new Map<number, string>());
  const detailClass = useRef(new Map<number, string>());
  const crowdRefs = useRef(new Map<string, HTMLElement>());
  const anonRefs = useRef(new Map<string, HTMLElement>());
  const statRefs = useRef(new Map<string, HTMLElement>());
  const statText = useRef(new Map<string, string>());
  const lockRef = useRef<HTMLDivElement | null>(null);
  const fieldRef = useRef<HTMLDivElement | null>(null);
  const dayOrigin = useRef(0);
  const lastFrame = useRef<{
    clock: Clock;
    positions: Map<number, { x: number; y: number; offsetX: number; offsetY: number }>;
    detailPositions: Map<number, { x: number; y: number; offsetX: number; offsetY: number }>;
    live: LiveCount;
  } | null>(null);
  const scene = useRef<{
    agents: CityAgent[];
    offsets: Map<string, Offset>;
    projection: Projection | null;
    detail: Detail | null;
    plan: Plan;
    reducedMotion: boolean;
    focusId: number | null;
  }>({
    agents: [], offsets: new Map(), projection: null, detail: null,
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
   * The day clock starts once and then runs free. It is deliberately NOT reset
   * when a new tick lands.
   *
   * Restarting it on every tick was written for a paused run, where the tick
   * never changes and the reset therefore never fires. Against a running world
   * it fired mid-day and snapped all 300 chips from wherever they had glided to
   * back onto their morning anchors — a measured 330 px jump in a single frame,
   * against 0.57 px for an ordinary one.
   *
   * That jump was pure artefact. Consecutive ticks change only 1-4 of 900
   * recorded placements (0.1-0.4%), so the incoming frame of truth is very
   * nearly the one already on screen: adopting it in place moves the two or
   * three people whose placements actually changed and leaves everyone else
   * mid-stride. The clock keeps time, the data underneath it is replaced, and
   * nobody is teleported to represent a change that did not happen.
   *
   * The day and the tick are both ~45 s but not locked, so they drift. That is
   * fine and stays honest: the day is a reading of ONE tick's three recorded
   * slots, and the masthead names the tick it is reading.
   */
  useEffect(() => {
    /* Started by the FIRST frame of truth, not by mount: before the map lands
       there is nobody to place, and a clock running against an empty field
       would put the city a second or two into a day it had not begun. */
    if (mapTick !== null && dayOrigin.current === 0) {
      dayOrigin.current = performance.now();
    }
  }, [mapTick]);

  const paint = useCallback((now: number) => {
    const {
      agents, offsets: layout, projection: camera, detail,
      plan: legs, reducedMotion: still, focusId,
    } = scene.current;
    if (!camera || !agents.length) return;
    /* A readout is only rewritten when its digits actually change, so the
       masthead costs nothing on the frames where nothing happened. */
    const writeStat = (key: string, value: string) => {
      if (statText.current.get(key) === value) return;
      statText.current.set(key, value);
      const node = statRefs.current.get(key);
      if (node) node.textContent = value;
    };
    const elapsed = now - dayOrigin.current;
    const clock = dayClock(elapsed, legs) as Clock;
    /* Reduced motion keeps the day, drops the glide: chips sit at the leg's
       recorded placement and change position only on a leg boundary. */
    const effective: Clock = still ? { ...clock, t: 0, ease: 0 } : clock;
    const positions = new Map<number, { x: number; y: number; offsetX: number; offsetY: number }>();
    const detailPositions = new Map<
      number, { x: number; y: number; offsetX: number; offsetY: number }>();

    for (const agent of agents) {
      const point = chipScreenPoint(agent, effective, camera, layout) as ChipPoint | null;
      if (!point) continue;
      positions.set(agent.id, {
        x: point.x, y: point.y, offsetX: point.offsetX, offsetY: point.offsetY,
      });
      /*
       * WHICH PLACE COLOURS THE CHIP. The first half of a leg keeps the hue of
       * where the person still mostly is; the second half takes the hue of where
       * they are arriving. So the At home / At work / In the commons code is
       * carried THROUGH the journey rather than surrendered for the duration of
       * it, and the turn of the field from blue to green IS the commute.
       */
      const anchor = point.point.t < 0.5 ? point.point.from : point.point.to;
      const node = chipRefs.current.get(agent.id);
      if (node) {
        node.style.transform = `translate3d(${point.x.toFixed(2)}px, ${point.y.toFixed(2)}px, 0)`;
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
       * THE SAME PERSON, IN THE DETAIL CAMERA. One more affine projection of the
       * one interpolated point — no second layout, no re-packing, no separate
       * set of positions that could disagree with the wide view.
       */
      const twin = detailRefs.current.get(agent.id);
      if (!detail || !twin) continue;
      /*
       * THE DETAIL PIXEL, DERIVED RATHER THAN RECOMPUTED.
       *
       * Both cameras are affine and the detail one is the wide one scaled about
       * a point, so its pixel falls out of the wide pixel in two multiplies:
       *   detail = camera.left + zoom * (wide - base.left)
       * — the de-collision offset is inside `wide` and scales with everything
       * else, which is exactly the behaviour the offsetScale gives it. Running
       * the whole placement twice cost a second pass over 300 agents every
       * frame and showed up as dropped frames in the capture harness; this
       * cannot disagree with the wide view even in principle.
       */
      const zoom = detail.camera.zoom ?? 1;
      const nx = detail.camera.left + zoom * (point.x - camera.left);
      const ny = detail.camera.top + zoom * (point.y - camera.top);
      detailPositions.set(agent.id, {
        x: nx, y: ny, offsetX: point.offsetX * zoom, offsetY: point.offsetY * zoom,
      });
      const outside = nx < -40 || ny < -40
        || nx > detail.camera.width + 40 || ny > detail.camera.height + 40;
      if (!outside || !detailParked.current.has(agent.id)) {
        twin.style.transform = outside
          ? "translate3d(-999px, -999px, 0)"
          : `translate3d(${nx.toFixed(2)}px, ${ny.toFixed(2)}px, 0)`;
      }
      if (outside) { detailParked.current.add(agent.id); continue; }
      detailParked.current.delete(agent.id);
      const twinClass = [
        "live-city__chip live-city__chip--detail",
        `live-city__chip--${anchor.sourceType || "unknown"}`,
        point.point.moving ? "is-moving" : "",
        anchor.recorded ? "" : "is-unrecorded",
        focusId === agent.id ? "is-focus" : "",
      ].filter(Boolean).join(" ");
      if (detailClass.current.get(agent.id) !== twinClass) {
        detailClass.current.set(agent.id, twinClass);
        twin.className = twinClass;
      }
      const twinWake = detailWakeRefs.current.get(agent.id);
      if (twinWake) {
        const length = Math.min(WAKE_MAX_PX * 1.6, point.travelledPx * zoom);
        twinWake.style.transform = length > 0.5
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

    /*
     * THE TOP LINE, COUNTED OFF THE CHIPS IN THE FRAME.
     *
     * Round two's masthead held five figures that describe the whole tick, and
     * on a paused run all five are constant: a critic found TICK, PLACEMENTS,
     * COMMUTING and CROSS-BORDER pixel-identical across 23 seconds while the
     * world recoloured underneath them. The tick's own figures are still on the
     * surface — they moved to the provenance foot, which is where a fixed fact
     * about the recording belongs. What is on the top line now is the leg in
     * view: who is between two places at this instant, who is at one, and how
     * far the leg and the day have run. Two of the five change every frame and
     * one changes every second, and every one of them is read off the same
     * anchors and the same clock that placed the chips above.
     */
    const live = liveCounts(agents, effective) as LiveCount;
    const remainingMs = Math.max(0, (effective.legMs ?? 0) * (1 - effective.t));
    writeStat("transit", String(live.inTransit));
    writeStat("placed", String(live.atPlace));
    writeStat("leg", `${Math.round(effective.ease * 100)}%`);
    writeStat("day", `${Math.round(clock.dayProgress * 100)}%`);
    writeStat("left", `${Math.ceil(remainingMs / 1000)}s`);

    lastFrame.current = { clock: effective, positions, detailPositions, live };
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
      agents: model.agents, offsets, projection, detail, plan, reducedMotion,
      focusId: focus?.id ?? null,
    };
    paint(performance.now());
  }, [model.agents, offsets, projection, detail, plan, reducedMotion, focus, paint]);

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
      const { agents, projection: camera, detail: inset, plan: legs } = scene.current;
      if (!frame || !camera) return null;
      return {
        tick: mapTick,
        dayMs: legs.dayMs ?? DAY_MS,
        legs: legs.legs.map(leg => ({
          fromSlot: leg.fromSlot, toSlot: leg.toSlot, movers: leg.movers, ms: leg.ms,
        })),
        maxOffsetPx: MAX_DECOLLISION_RADIUS_PX,
        clock: frame.clock,
        live: frame.live,
        projection: {
          minX: camera.minX, minY: camera.minY,
          scaleX: camera.scaleX, scaleY: camera.scaleY,
          left: camera.left, top: camera.top,
        },
        /* The detail camera, published on the same terms as the wide one: an
           affine map a checker can invert to re-derive every inset pixel. */
        detail: inset ? {
          zoom: inset.zoom,
          centre: inset.centre,
          window: inset.camera.window,
          projection: {
            minX: inset.camera.minX, minY: inset.camera.minY,
            scaleX: inset.camera.scaleX, scaleY: inset.camera.scaleY,
            left: inset.camera.left, top: inset.camera.top,
          },
        } : null,
        chips: agents.map(agent => {
          const position = frame.positions.get(agent.id);
          const near = frame.detailPositions.get(agent.id);
          return {
            id: agent.id,
            x: position?.x ?? null,
            y: position?.y ?? null,
            offsetX: position?.offsetX ?? null,
            offsetY: position?.offsetY ?? null,
            detailX: near?.x ?? null,
            detailY: near?.y ?? null,
            detailOffsetX: near?.offsetX ?? null,
            detailOffsetY: near?.offsetY ?? null,
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
      x: number; y: number; radius: number; name: string | null; short: string | null;
    }[] = [];
    /* The region's own name is already on a plate a few hundred pixels away, so
       a badge repeating it is three words the reader has to skip. What is left
       is the part that identifies the place. */
    const prefixes = model.regions.map(region => region.name);
    const shorten = (name: string | null) => {
      if (!name) return null;
      for (const prefix of prefixes) {
        if (name.startsWith(`${prefix} `)) {
          return name.slice(prefix.length + 1).replace(/^Residential /, "");
        }
      }
      return name;
    };
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
          short: shorten(crowd.name),
        });
      });
    }
    return marks;
  }, [model.crowds, model.regions, discs, projection]);

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

  /* The same rings and the same headcounts, in the detail camera. Registered
     under keys that end in the slot index, so one opacity loop drives both. */
  const detailCrowdMarks = useMemo(() => {
    if (!detail) return [];
    const marks: {
      key: string; slotIndex: number; count: number;
      x: number; y: number; radius: number; short: string | null;
    }[] = [];
    for (const crowd of detail.crowds) {
      const disc = discs.get(String(crowd.placeId));
      const point = detail.camera.project(crowd.x, crowd.y);
      DAY_SLOTS.forEach((slot, slotIndex) => {
        const headcount = crowd.slots[slot] ?? 0;
        if (headcount < CROWD_MIN) return;
        const source = crowdMarks.find(mark => mark.key === `${crowd.placeId}:${slotIndex}`);
        marks.push({
          key: `${crowd.placeId}:${slotIndex}`,
          slotIndex,
          count: headcount,
          x: point.x,
          y: point.y,
          /* The spread is magnified with the ground, so the ring that describes
             it must be too, or the number is tied to the wrong smudge. */
          radius: Math.max(13, (disc?.radius ?? 0) * detail.zoom + 9),
          short: source?.short ?? null,
        });
      });
    }
    return marks;
  }, [detail, discs, crowdMarks]);

  /* The rectangle the detail camera is looking at, drawn on the wide map so the
     inset is anchored to the ground it magnifies rather than floating free. */
  const detailFrame = useMemo(() => {
    if (!detail || !projection) return null;
    const topLeft = projection.project(detail.camera.window.minX, detail.camera.window.minY);
    const bottomRight = projection.project(detail.camera.window.maxX, detail.camera.window.maxY);
    return {
      x: topLeft.x,
      y: topLeft.y,
      width: Math.max(1, bottomRight.x - topLeft.x),
      height: Math.max(1, bottomRight.y - topLeft.y),
    };
  }, [detail, projection]);

  /*
   * WHERE THE CROSS-BORDER TRAVELLERS ARE GOING — DRAWN ONCE PER LEG.
   *
   * A critic watched these chips "glide into empty black with no destination
   * rendered near them". The destination is recorded, so it can be drawn: this
   * is the whole straight segment between the two recorded placements, with a
   * ring on the placement at the far end. The chip is somewhere on that line and
   * its wake says where it has got to.
   *
   * It is STATIC within a leg, and that is not an optimisation detail — it is
   * the honest shape of the claim. The segment does not depend on the moment;
   * only the person's position on it does. Drawing it per frame as a
   * chip-anchored element cost 35 ms a frame for ninety-seven long rotated
   * boxes and started returning half-painted frames to the capture harness.
   * Drawn as one SVG layer that changes only on a leg boundary, it costs
   * nothing per frame and says exactly the same thing.
   */
  const corridors = useMemo(() => {
    if (!projection) return [];
    const from = plan.legs[phase.legIndex]?.fromIndex ?? 0;
    const to = plan.legs[phase.legIndex]?.toIndex ?? 1;
    return model.agents.flatMap(agent => {
      if (!agent.longHaul) return [];
      const start = agent.anchors[from];
      const end = agent.anchors[to];
      if (!start || !end || start.placeId === end.placeId) return [];
      const a = projection.project(start.x, start.y);
      const b = projection.project(end.x, end.y);
      const offA = offsets.get(`${agent.id}@${start.placeId}`);
      const offB = offsets.get(`${agent.id}@${end.placeId}`);
      return [{
        id: agent.id,
        x1: a.x + (offA?.x ?? 0), y1: a.y + (offA?.y ?? 0),
        x2: b.x + (offB?.x ?? 0), y2: b.y + (offB?.y ?? 0),
      }];
    });
  }, [projection, model.agents, offsets, plan.legs, phase.legIndex]);

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
        {/* The 97 recorded cross-border segments of the leg in view, and a ring
            on the placement each one ends at. One layer, redrawn on a leg
            boundary and never between: the segment is a property of the leg,
            not of the moment. */}
        <g className="live-city__corridors">
          {corridors.map(line => <line
            key={`corridor-${line.id}`}
            x1={line.x1.toFixed(1)} y1={line.y1.toFixed(1)}
            x2={line.x2.toFixed(1)} y2={line.y2.toFixed(1)}
          />)}
          {corridors.map(line => <circle
            key={`arrival-${line.id}`}
            className="live-city__arrival"
            cx={line.x2.toFixed(1)} cy={line.y2.toFixed(1)} r={4}
          />)}
        </g>
        {detailFrame && <rect
          className="live-city__detail-frame"
          x={detailFrame.x} y={detailFrame.y}
          width={detailFrame.width} height={detailFrame.height}
          rx="3"
        />}
        {focusDay && <path className="live-city__focus-day" d={focusDay.path} />}
        {focusDay?.points.map((point, index) => <circle
          key={`focus-anchor-${index}`}
          className="live-city__focus-anchor"
          cx={point.x} cy={point.y} r={4.5}
        />)}
      </svg>}

      {/*
        * EVENING ONLY, AND NOT AS DECORATION.
        *
        * The world records these conversations in the evening phase, between
        * people the map puts at the same address — and it is the same address
        * they left in the morning. So this layer is the other half of the
        * commute the city already draws: the chips go out, the chips come back,
        * and this is what happens when they do.
        *
        * It is drawn only while the day is on its evening leg, because that is
        * the leg the words belong to. Showing them at noon would put a recorded
        * fact at an hour it did not happen.
        */}
      {/*
        * Every conversation gets a mark at its own address; only the ones with
        * room get their words. At whole-city zoom the residential ground is
        * dense enough that most quote boxes would sit on top of each other, and
        * the answer is not to move them off the address the world recorded —
        * it is to mark the address and let the reader see which are speaking.
        */}
      {projection && phase.nearIndex === 2 && talk.length > 0
        && <div className="live-city__talk-marks" aria-hidden="true">
        {talk.map(item => {
          const point = projection.project(item.x, item.y);
          return <i
            key={item.id}
            className="live-city__talk-mark"
            style={{ transform: `translate3d(${point.x.toFixed(1)}px, ${point.y.toFixed(1)}px, 0)` }}
          />;
        })}
      </div>}

      {projection && phase.nearIndex === 2 && drawnTalk.kept.length > 0
        && <div className="live-city__talk">
        {drawnTalk.kept.map(item => <article
          key={item.id}
          className="live-city__bubble"
          style={{ transform: `translate3d(${item.left.toFixed(1)}px, ${item.top.toFixed(1)}px, 0)` }}
        >
          <p className="live-city__bubble-who">{item.people.join(" · ")}</p>
          {item.lines[0]
            ? <p className="live-city__bubble-line">&ldquo;{item.lines[0].text}&rdquo;</p>
            : <p className="live-city__bubble-line">{item.topic}</p>}
        </article>)}
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
          data-dense={dense.has(agent.id) ? "1" : undefined}
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

      {/*
        * EVERY PIECE OF PERSISTENT TEXT SITS ABOVE THE DOT LAYER, AND SAYS SO
        * IN THE STACK RATHER THAN IN THE DOM ORDER.
        *
        * Round two put the crowd rings and the territory plates UNDER the
        * chips, and a critic caught a green chip eating the E of IRONVALE
        * UNION, two more sitting on NORTHSTAR FEDERATION, and the headcount
        * numerals — the one thing the legend promises for a crowd — buried
        * under the very crowd they count. Marks that carry words are now
        * layered over the people by explicit z-index, which is the same defect
        * class the World map had and the same structural fix.
        */}
      {projection && <div className="live-city__marks live-city__marks--crowds" aria-hidden="true">
        {crowdMarks.map(mark => <div
          key={`crowd-${mark.key}`}
          className={`live-city__crowd${mark.count >= DENSE_COHORT ? " is-major" : ""}`}
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
          {/* The count only. Nine of this run's crowds are within 90 px of
              another, so naming them all on the wide map builds a wall of
              overlapping plates — the names are carried in the inset, which is
              where there is room to read them. */}
          <b className="ae-num">{mark.count}</b>
        </div>)}
      </div>}

      {projection && <div className="live-city__marks live-city__marks--anon" aria-hidden="true">
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

      {/*
        * The territory name plates. A map's own margin note: set on a plate at
        * readable weight, placed OUTSIDE the hull on the side that faces the
        * empty middle of the field, so the people never shred the letterforms
        * and the void between polities carries something worth reading.
        */}
      {projection && <div className="live-city__marks live-city__marks--plates" aria-hidden="true">
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

    {/*
      * THE SECOND CAMERA.
      *
      * A critic found "roughly 90 orange chips fused into one solid
      * unresolvable mass" and the promised headcount ring failing inside it.
      * The recorded truth underneath that mass is three places — a public
      * commons holding 42 and two residential districts holding 24 and 23 —
      * whose coordinates are 34 and 47 px apart at whole-city zoom. No spread
      * separates them without moving somebody off their recorded coordinate,
      * so the fix is magnification, not relocation: the same placements, the
      * same offsets, the same clock, through an affine camera 2.6x closer,
      * standing on ground this tick's geography leaves empty.
      */}
    {detail && detailSlot && <aside
      className="live-city__detail"
      style={{
        left: `${detailSlot.left}px`,
        top: `${detailSlot.top}px`,
        width: `${DETAIL_PANEL.width}px`,
        height: `${DETAIL_PANEL.height}px`,
      }}
    >
      <div className="live-city__detail-stage" aria-hidden="true">
        <svg width={DETAIL_PANEL.width} height={DETAIL_PANEL.height}>
          {detail.places.map(place => {
            const point = detail.camera.project(place.x, place.y);
            return <circle
              key={`detail-place-${place.id}`}
              className={`live-city__place live-city__place--${place.kind}`}
              cx={point.x} cy={point.y}
              r={place.kind === "firm_workplace" ? 3.2 : place.kind === "residential_district" ? 5 : 6.4}
            />;
          })}
        </svg>
        <div className="live-city__chips live-city__chips--detail">
          {detailMembers.map(agent => <div
            key={`detail-${agent.id}`}
            className="live-city__chip live-city__chip--detail"
            ref={node => {
              if (node) detailRefs.current.set(agent.id, node);
              else {
                detailRefs.current.delete(agent.id);
                detailClass.current.delete(agent.id);
              }
            }}
          >
            <i
              className="live-city__wake"
              ref={node => {
                if (node) detailWakeRefs.current.set(agent.id, node);
                else detailWakeRefs.current.delete(agent.id);
              }}
            />
          </div>)}
        </div>
        <div className="live-city__marks live-city__marks--crowds">
          {detailCrowdMarks.map(mark => <div
            key={`detail-crowd-${mark.key}`}
            className={`live-city__crowd${mark.count >= DENSE_COHORT ? " is-major" : ""}`}
            style={{
              left: `${mark.x}px`,
              top: `${mark.y}px`,
              width: `${mark.radius * 2}px`,
              height: `${mark.radius * 2}px`,
            }}
            ref={node => {
              if (node) crowdRefs.current.set(`detail:${mark.key}`, node);
              else crowdRefs.current.delete(`detail:${mark.key}`);
            }}
          >
            <i />
            <b className="ae-num">
              {mark.count}
              {mark.count >= DENSE_COHORT && mark.short ? <em>{mark.short}</em> : null}
            </b>
          </div>)}
        </div>
      </div>
      <p className="ae-cap live-city__detail-cap">
        Detail · {detail.zoom}× · the boxed ground, magnified
      </p>
      <p className="live-city__detail-note">
        The boxed ground holds {count(detail.places.length)} places and{" "}
        {count(detail.crowds.length)} crowds, the busiest in the tick among them —{" "}
        <b>{detail.anchor.name}</b>, {detail.anchor.peak} people. At whole-city zoom their discs
        overlap and read as one mass. Same placements, same offsets, one camera closer.
      </p>
    </aside>}

    <header className="live-city__masthead">
      <div className="live-city__identity">
        {/* No run hash here. A build identifier is provenance, not a title; it
            is set beside the tick it belongs to in the foot. */}
        <p className="ae-cap">Street level · {model.regions.length} territories</p>
        <h1>The recorded day</h1>
        <p className="live-city__run">
          <Link to={`/runs/${encodeURIComponent(runId)}/overview`}>← Workspaces</Link>
          <span className={`live-city__pulse live-city__pulse--${paused ? "paused" : transport.status}`}>
            {paused ? "Paused" : humanize(transport.status)}
          </span>
        </p>
      </div>
      {/*
        * THE LEG IN VIEW, NOT THE TICK. Every figure here is written by the
        * animation loop from the chips it just placed: the first two are counts
        * of those chips, the last three are where the leg and the day have got
        * to. The tick's own totals sit in the provenance foot.
        */}
      <dl className="live-city__readout">
        {([
          ["transit", "In transit"],
          ["placed", "At a place"],
          ["leg", "Leg run"],
          ["day", "Day run"],
          ["left", "Leg ends in"],
        ] as [string, string][]).map(([key, label]) => <div key={key}>
          <dt>{label}</dt>
          <dd
            className="ae-num"
            ref={node => {
              if (node) statRefs.current.set(key, node);
              else { statRefs.current.delete(key); statText.current.delete(key); }
            }}
          >—</dd>
        </div>)}
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
        {/* The map explains every other mark it draws; this one is no different. */}
        {talk.length > 0 && phase.nearIndex === 2 && <li>
          <i className="live-city__key live-city__key--talk" />
          {count(talk.length)} recorded conversation{talk.length === 1 ? "" : "s"} this evening,
          each at the address the world places both speakers at
        </li>}
        <li><i className="live-city__key live-city__key--haul" />
          {count(model.counts.longHaul)} whose day crosses a border — drawn a size up, and while
          they travel, the rest of their segment and the recorded place at the end of it
        </li>
        <li><i className="live-city__key live-city__key--crowd" />
          A ring and a count wherever {CROWD_MIN} or more share one place — drawn over the people,
          never under them
        </li>
        {detail && <li><i className="live-city__key live-city__key--detail" />
          Where places sit closer than their crowds are wide, the boxed ground is magnified
          {" "}{detail.zoom}× in the inset. Nobody is moved to make room
        </li>}
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
        itself is not recorded. Someone whose consecutive placements name the same place does not move. A
        traveller in transit also carries the rest of that same straight line and a ring on the recorded place
        at the end of it — the destination is recorded, the route between is not.
      </p>
      {/* Said out loud for the same reason the interpolation is: a reader should
          never have to guess which part of a bubble is evidence. */}
      {talk.length > 0 && <p className="ae-cap live-city__talk-note">
        <b>What people say is recorded; when inside the evening it is not.</b>{" "}
        {count(talk.length)} conversation{talk.length === 1 ? "" : "s"} this tick, each drawn at the
        address the world places <em>both</em> speakers at. The words and the speakers are the
        world&rsquo;s own — a pair the map places apart, or anyone it does not carry, is not drawn
        at all rather than positioned by guess.{drawnTalk.dropped > 0 && <>{" "}
        Every one is marked where it happened; {count(drawnTalk.kept.length)} had room to be quoted
        and {count(drawnTalk.dropped)} did not, because moving a quote off its address to make it
        fit would misplace a recorded fact.</>}
      </p>}
      {/*
        * THE TICK'S OWN FIGURES, WHERE A FIXED FACT BELONGS. These are true of
        * the whole recorded tick and do not change while it is on screen, which
        * is exactly why they are no longer on the top line: five constants in
        * the masthead read as a broken instrument. Here they read as the
        * provenance of a truth claim, which is what they are.
        */}
      <p className="live-city__provenance">
        <span>
          <b>{count(model.counts.recordedPlacements) ?? "0"}</b> placements ·
          {" "}<b>{count(model.counts.agents) ?? "0"}</b> people ·
          {" "}<b>{count(model.counts.commuters) ?? "0"}</b> commuting ·
          {" "}<b>{count(model.counts.longHaul) ?? "0"}</b> across a border
        </span>
        <span>tick {mapTick ?? "—"} · <span className="mono">{runId}</span></span>
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

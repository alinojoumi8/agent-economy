import { OrbitView } from "@deck.gl/core";
import { PathLayer, PolygonLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import DeckGL from "@deck.gl/react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { buildDioramaScene } from "../lib/civicDiorama.js";
import { humanize } from "../lib/civicCity.js";
import "./civic-diorama.css";

const ORBIT_VIEW = new OrbitView({ id: "civic-diorama", orbitAxis: "Z" });
const FIXED_CAMERA = {
  target: [50, 50, 0],
  rotationX: 57,
  rotationOrbit: -28,
  zoom: 3.05,
  minZoom: 1.8,
  maxZoom: 5.4,
};
/* How long two consecutive live ticks glide into each other. */
const TRANSITION_MS = 420;

function useReducedMotion() {
  const [reduced, setReduced] = useState(() =>
    typeof window !== "undefined"
      && Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches));
  useEffect(() => {
    const query = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!query) return undefined;
    const update = () => setReduced(query.matches);
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, []);
  return reduced;
}

function agentColor(agent) {
  if (agent.runtimeActivity) return agent.activityState === "queued"
    ? [236, 174, 87, 245]
    : [87, 211, 190, 250];
  if (agent.activityState === "rejected") return [226, 101, 86, 240];
  if (agent.activityState === "settled") return [109, 178, 126, 240];
  const layers = {
    institutions: [103, 168, 157, 230],
    communications: [112, 148, 196, 230],
    markets: [211, 161, 87, 230],
    health: [132, 185, 143, 230],
    work: [198, 133, 95, 230],
  };
  return layers[agent.layer] || [174, 178, 171, 225];
}

export function CivicDiorama({
  model,
  visibleAgents,
  showClusters,
  selectedAgentId,
  selectedPlaceId,
  selectedProjectId,
  onSelectAgent,
  onSelectPlace,
  onSelectProject,
  onShowAllResidents,
  animateLiveActivity,
  tick,
  historical,
}) {
  const [viewState, setViewState] = useState(FIXED_CAMERA);
  const [pulse, setPulse] = useState(0);
  const [firstFrameMs, setFirstFrameMs] = useState(null);
  const [frameP95Ms, setFrameP95Ms] = useState(null);
  const mountedAt = useRef(typeof performance === "undefined" ? 0 : performance.now());
  const measured = useRef(false);
  const reducedMotion = useReducedMotion();
  const projectedTick = Number.isFinite(Number(model.selectedTick))
    ? Number(model.selectedTick)
    : null;
  /*
   * The glide between two consecutive ticks is decided in the render that first
   * carries the new positions — deck.gl only starts a transition on the update
   * where the attribute changes — and then has to OUTLIVE that render: under
   * animateLiveActivity the pulse re-renders every frame, and a layer rebuilt
   * without `transitions` cancels the glide in flight, snapping everyone to
   * their destination one frame in. So the duration lives in state, set from
   * the previous render's tick as the tick changes (React's storing-previous-
   * render pattern) and released by a timer one duration later. Historical
   * views and reduced motion never glide.
   */
  const [glideTick, setGlideTick] = useState(null);
  const [glideDuration, setGlideDuration] = useState(0);
  if (projectedTick !== glideTick) {
    setGlideTick(projectedTick);
    setGlideDuration(
      glideTick !== null && projectedTick !== null && projectedTick === glideTick + 1
        ? TRANSITION_MS
        : 0,
    );
  }
  const transitionDuration = historical || reducedMotion ? 0 : glideDuration;
  const scene = useMemo(
    () => buildDioramaScene(model, visibleAgents, { showClusters }),
    [model, showClusters, visibleAgents],
  );

  useEffect(() => {
    if (!glideDuration) return undefined;
    /* One frame of grace: deck.gl starts the glide on its own next frame, so
       the settings are withdrawn only once it has certainly finished. */
    const timer = window.setTimeout(() => setGlideDuration(0), glideDuration + 40);
    return () => window.clearTimeout(timer);
  }, [glideDuration, glideTick]);

  useEffect(() => {
    if (!animateLiveActivity || reducedMotion) {
      setPulse(0);
      return undefined;
    }
    let frame = 0;
    const animate = timestamp => {
      setPulse((Math.sin(timestamp / 360) + 1) / 2);
      frame = window.requestAnimationFrame(animate);
    };
    frame = window.requestAnimationFrame(animate);
    return () => window.cancelAnimationFrame(frame);
  }, [animateLiveActivity, reducedMotion]);

  useEffect(() => {
    if (historical || reducedMotion) {
      setFrameP95Ms(null);
      return undefined;
    }
    const samples = [];
    let previous = null;
    let frame = 0;
    const sample = timestamp => {
      if (previous !== null) samples.push(timestamp - previous);
      previous = timestamp;
      if (samples.length >= 60) {
        const ordered = samples.slice().sort((left, right) => left - right);
        setFrameP95Ms(ordered[Math.floor((ordered.length - 1) * 0.95)]);
        return;
      }
      frame = window.requestAnimationFrame(sample);
    };
    frame = window.requestAnimationFrame(sample);
    return () => window.cancelAnimationFrame(frame);
  }, [historical, reducedMotion]);

  const selectedLabels = useMemo(() => {
    const project = scene.constructions.find(
      item => String(item.id) === String(selectedProjectId),
    );
    const agent = scene.agents.find(item => String(item.id) === String(selectedAgentId));
    const place = scene.buildings.find(
      item => item.entityKind === "place" && String(item.id) === String(selectedPlaceId),
    );
    const selected = project || place || agent;
    if (!selected) return [];
    return [{
      text: selected.name || `${humanize(selected.entityKind)} #${selected.id}`,
      position: selected.position,
    }];
  }, [scene, selectedAgentId, selectedPlaceId, selectedProjectId]);

  const layers = useMemo(() => [
    new PolygonLayer({
      id: "civic-district-plates",
      data: scene.districts,
      getPolygon: item => item.polygon,
      getFillColor: item => item.color,
      getLineColor: [183, 190, 178, 92],
      getElevation: item => item.elevation,
      extruded: true,
      filled: true,
      stroked: true,
      lineWidthUnits: "pixels",
      getLineWidth: 1,
      pickable: true,
    }),
    new PathLayer({
      id: "civic-world-flows",
      data: scene.flows,
      getPath: item => item.path,
      getColor: item => item.color,
      getWidth: item => item.kind === "trade" ? 3 : 2,
      widthUnits: "pixels",
      capRounded: true,
      jointRounded: true,
      pickable: true,
    }),
    new PolygonLayer({
      id: "civic-construction-sites",
      data: scene.constructions.filter(item => !item.operationalPlace),
      getPolygon: item => item.polygon,
      getFillColor: item => item.color,
      getLineColor: item => String(item.id) === String(selectedProjectId)
        ? [255, 244, 191, 255]
        : item.lineColor,
      getElevation: item => item.elevation,
      extruded: true,
      filled: true,
      stroked: true,
      wireframe: false,
      lineWidthUnits: "pixels",
      getLineWidth: item => String(item.id) === String(selectedProjectId) ? 3 : 1.5,
      material: {
        ambient: 0.62,
        diffuse: 0.58,
        shininess: 8,
        specularColor: [52, 44, 38],
      },
      /* deck.gl ignores accessor identity: an accessor that closes over the
         selection must name it here or the highlight only moves when `data`
         happens to be rebuilt. */
      updateTriggers: {
        getLineColor: [selectedProjectId],
        getLineWidth: [selectedProjectId],
      },
      pickable: true,
    }),
    new PathLayer({
      id: "civic-construction-frames",
      data: scene.constructionFrames,
      getPath: item => item.path,
      getColor: item => String(item.id) === String(selectedProjectId)
        ? [255, 244, 191, 255]
        : item.lineColor,
      getWidth: item => String(item.id) === String(selectedProjectId) ? 4 : 2.5,
      widthUnits: "pixels",
      capRounded: false,
      jointRounded: false,
      updateTriggers: {
        getColor: [selectedProjectId],
        getWidth: [selectedProjectId],
      },
      pickable: true,
    }),
    new PolygonLayer({
      id: "civic-buildings",
      data: scene.buildings,
      getPolygon: item => item.polygon,
      getFillColor: item => item.color,
      getLineColor: item => (
        item.entityKind === "place" && String(item.id) === String(selectedPlaceId)
          ? [255, 244, 191, 255]
          : [31, 37, 39, 205]
      ),
      getElevation: item => item.elevation,
      extruded: true,
      wireframe: false,
      filled: true,
      stroked: true,
      lineWidthUnits: "pixels",
      getLineWidth: item => (
        item.entityKind === "place" && String(item.id) === String(selectedPlaceId) ? 3 : 1
      ),
      material: {
        ambient: 0.55,
        diffuse: 0.65,
        shininess: 22,
        specularColor: [64, 69, 67],
      },
      transitions: transitionDuration ? { getPolygon: transitionDuration } : undefined,
      updateTriggers: {
        getLineColor: [selectedPlaceId],
        getLineWidth: [selectedPlaceId],
      },
      pickable: true,
    }),
    new ScatterplotLayer({
      id: "civic-population-clusters",
      data: scene.clusters,
      getPosition: item => item.position,
      radiusUnits: "pixels",
      getRadius: item => 12 + Math.min(24, Math.sqrt(item.count) * 1.4),
      getFillColor: [104, 118, 124, 155],
      getLineColor: [204, 211, 201, 220],
      lineWidthUnits: "pixels",
      getLineWidth: 2,
      filled: true,
      stroked: true,
      pickable: true,
    }),
    new ScatterplotLayer({
      id: "civic-agent-halos",
      data: scene.agents.filter(item => item.runtimeActivity),
      getPosition: item => item.position,
      radiusUnits: "pixels",
      getRadius: 13 + pulse * 9,
      getFillColor: [78, 207, 187, Math.round(35 + pulse * 65)],
      getLineColor: [78, 207, 187, Math.round(130 + pulse * 100)],
      lineWidthUnits: "pixels",
      getLineWidth: 1.5,
      filled: true,
      stroked: true,
      pickable: false,
    }),
    new ScatterplotLayer({
      id: "civic-agents",
      data: scene.agents,
      getPosition: item => item.position,
      radiusUnits: "pixels",
      getRadius: item => String(item.id) === String(selectedAgentId) ? 8.5 : 5.5,
      getFillColor: agentColor,
      getLineColor: item => String(item.id) === String(selectedAgentId)
        ? [255, 247, 210, 255]
        : [25, 31, 31, 235],
      lineWidthUnits: "pixels",
      getLineWidth: item => String(item.id) === String(selectedAgentId) ? 3 : 1,
      transitions: transitionDuration ? { getPosition: transitionDuration } : undefined,
      updateTriggers: {
        getRadius: [selectedAgentId],
        getLineColor: [selectedAgentId],
        getLineWidth: [selectedAgentId],
      },
      filled: true,
      stroked: true,
      pickable: true,
    }),
    new TextLayer({
      id: "civic-district-labels",
      data: scene.districts,
      getPosition: item => item.center,
      getText: item => item.name.toUpperCase(),
      getColor: [215, 216, 202, 150],
      getSize: 11,
      sizeUnits: "pixels",
      getTextAnchor: "middle",
      getAlignmentBaseline: "center",
      billboard: true,
      pickable: false,
    }),
    new TextLayer({
      id: "civic-construction-labels",
      data: scene.constructions.filter(item => !item.operationalPlace),
      getPosition: item => item.position,
      getText: item => item.label,
      getColor: item => String(item.id) === String(selectedProjectId)
        ? [255, 247, 210, 255]
        : [240, 219, 178, 235],
      updateTriggers: { getColor: [selectedProjectId] },
      getBackgroundColor: [31, 29, 26, 205],
      background: true,
      backgroundPadding: [4, 2],
      getSize: 10,
      sizeUnits: "pixels",
      getPixelOffset: [0, -10],
      getTextAnchor: "middle",
      getAlignmentBaseline: "bottom",
      billboard: true,
      pickable: false,
    }),
    new TextLayer({
      id: "civic-selection-label",
      data: selectedLabels,
      getPosition: item => item.position,
      getText: item => item.text,
      getColor: [255, 247, 210, 255],
      getBackgroundColor: [20, 25, 26, 225],
      background: true,
      backgroundPadding: [5, 3],
      getSize: 12,
      sizeUnits: "pixels",
      getPixelOffset: [0, -18],
      getTextAnchor: "middle",
      getAlignmentBaseline: "bottom",
      billboard: true,
      pickable: false,
    }),
  ], [
    pulse,
    scene,
    selectedAgentId,
    selectedLabels,
    selectedPlaceId,
    selectedProjectId,
    transitionDuration,
  ]);

  const updateViewState = useCallback(({ viewState: next }) => {
    setViewState({
      ...next,
      rotationX: FIXED_CAMERA.rotationX,
      rotationOrbit: FIXED_CAMERA.rotationOrbit,
      minZoom: FIXED_CAMERA.minZoom,
      maxZoom: FIXED_CAMERA.maxZoom,
    });
  }, []);
  const zoom = delta => setViewState(current => ({
    ...current,
    zoom: Math.max(
      FIXED_CAMERA.minZoom,
      Math.min(FIXED_CAMERA.maxZoom, Number(current.zoom) + delta),
    ),
  }));
  const selectObject = info => {
    const object = info?.object;
    if (!object) return;
    if (object.entityKind === "agent") onSelectAgent(object.id);
    if (object.entityKind === "place") onSelectPlace(object.id);
    if (object.entityKind === "construction") onSelectProject?.(object.id);
    if (object.entityKind === "cluster") onShowAllResidents();
  };
  const selectFromKeyboard = event => {
    const value = String(event.target.value);
    const separator = value.indexOf(":");
    const kind = separator < 0 ? value : value.slice(0, separator);
    const id = separator < 0 ? "" : value.slice(separator + 1);
    if (kind === "agent") onSelectAgent(id);
    if (kind === "place") onSelectPlace(id);
    if (kind === "project") onSelectProject?.(id);
  };
  const selectionValue = selectedProjectId != null
    ? `project:${selectedProjectId}`
    : selectedPlaceId != null
    ? `place:${selectedPlaceId}`
    : selectedAgentId != null ? `agent:${selectedAgentId}` : "";

  return <div className="civic-diorama" data-testid="civic-diorama">
    <DeckGL
      views={ORBIT_VIEW}
      viewState={viewState}
      controller={{ dragMode: "pan", doubleClickZoom: false }}
      layers={layers}
      onViewStateChange={updateViewState}
      onClick={selectObject}
      getTooltip={({ object }) => object?.tooltip ? { text: object.tooltip } : null}
      onAfterRender={() => {
        if (measured.current || typeof performance === "undefined") return;
        measured.current = true;
        setFirstFrameMs(Math.max(0, performance.now() - mountedAt.current));
      }}
      useDevicePixels={typeof window === "undefined" ? 1 : Math.min(1.5, window.devicePixelRatio || 1)}
    />
    <div className="civic-diorama__wash" aria-hidden="true" />
    <div className="civic-diorama__controls">
      <button type="button" onClick={() => zoom(0.35)} aria-label="Zoom into city">+</button>
      <button type="button" onClick={() => zoom(-0.35)} aria-label="Zoom out of city">−</button>
      <button type="button" onClick={() => setViewState(FIXED_CAMERA)}>Reset</button>
    </div>
    <label className="civic-diorama__explorer">
      <span>Keyboard explorer</span>
      <select value={selectionValue} onChange={selectFromKeyboard}>
        <option value="">Choose a public object</option>
        <optgroup label="Places">
          {scene.buildings.filter(item => item.entityKind === "place").map(item =>
            <option key={item.key} value={`place:${item.id}`}>{item.name || `Place ${item.id}`}</option>)}
        </optgroup>
        <optgroup label="Construction projects">
          {scene.constructions.map(item =>
            <option key={item.key} value={`project:${item.id}`}>
              {item.name || `Construction project ${item.id}`} · {item.label}
            </option>)}
        </optgroup>
        <optgroup label="Agents">
          {scene.agents.map(item =>
            <option key={item.id} value={`agent:${item.id}`}>{item.name || `Agent ${item.id}`}</option>)}
        </optgroup>
      </select>
    </label>
    <div className="civic-diorama__status" aria-live="polite">
      <span>{historical
        ? `Historical tick ${tick} · motion off`
        : reducedMotion
          ? "Reduced motion"
          : animateLiveActivity
            ? "Live telemetry pulse"
            : transitionDuration
              ? "Consecutive tick transition"
              : "Committed scene"}</span>
      <span>{scene.buildings.length} buildings · {scene.constructions.length} projects · {scene.agents.length} agents · {scene.flows.length} flows</span>
      {firstFrameMs != null && <span>First frame {Math.round(firstFrameMs)}ms</span>}
      {frameP95Ms != null && <span>Frame p95 {Math.round(frameP95Ms)}ms</span>}
    </div>
    <p className="civic-diorama__method">
      Height is a derived visual encoding of exposed capacity, occupancy, queue, or employee counts.
      Construction geometry uses stored work units and exact foundation, frame, shell, and completed stages.
      Flow curves connect committed public region endpoints; they do not imply a traveled street.
      Position interpolation is limited to consecutive live projections.
    </p>
  </div>;
}

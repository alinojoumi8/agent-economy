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
import { DEFAULT_CITY_CAMERA, normalizeCityCamera, serializeCityCamera } from "../lib/cityCamera.js";

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
  selectedFirmId,
  camera,
  onCameraChange,
  onOpenEvidence,
  onSelectAgent,
  onSelectPlace,
  onSelectProject,
  onSelectFirm,
  onShowAllResidents,
  animateLiveActivity,
  tick,
  historical,
}) {
  const [viewState, setViewState] = useState(FIXED_CAMERA);
  useEffect(() => {
    const next = camera || DEFAULT_CITY_CAMERA;
    setViewState({ ...FIXED_CAMERA, target: [next.x, next.y, 0], zoom: next.zoom });
  }, [camera?.x, camera?.y, camera?.zoom]);
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
    const firm = model.firms.find(item => String(item.id) === String(selectedFirmId));
    const firmBuilding = firm && (scene.buildings.find(item => item.entityKind === "organization" && String(item.id) === String(firm.id))
      || scene.buildings.find(item => item.entityKind === "place" && String(item.id) === String(firm.place_id)));
    const selected = project || place || (firmBuilding && { ...firmBuilding, name: firm.name }) || agent;
    if (!selected) return [];
    return [{
      text: selected.entityKind === "construction" ? `${selected.name}\n${selected.label}`
        : selected.name || `${humanize(selected.entityKind)} #${selected.id}`,
      position: selected.position,
    }];
  }, [scene, model.firms, selectedAgentId, selectedPlaceId, selectedProjectId, selectedFirmId]);

  const buildingSelected = item => (item.entityKind === "place" && String(item.id) === String(selectedPlaceId))
    || (item.entityKind === "organization" && String(item.id) === String(selectedFirmId))
    || (selectedFirmId != null && item.entityKind === "place" && item.owner_type === "firm" && String(item.owner_id) === String(selectedFirmId));

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
        buildingSelected(item)
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
        buildingSelected(item) ? 3 : 1
      ),
      material: {
        ambient: 0.55,
        diffuse: 0.65,
        shininess: 22,
        specularColor: [64, 69, 67],
      },
      transitions: transitionDuration ? { getPolygon: transitionDuration } : undefined,
      updateTriggers: {
        getLineColor: [selectedPlaceId, selectedFirmId],
        getLineWidth: [selectedPlaceId, selectedFirmId],
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
    selectedFirmId,
    transitionDuration,
  ]);

  const commitCamera = useCallback((value, options) => {
    const next = normalizeCityCamera(value);
    const current = { x: viewState.target[0], y: viewState.target[1], zoom: viewState.zoom };
    if (serializeCityCamera(next) === serializeCityCamera(current)) return;
    setViewState({ ...FIXED_CAMERA, target: [next.x, next.y, 0], zoom: next.zoom });
    onCameraChange?.(next, options);
  }, [viewState, onCameraChange]);
  const updateViewState = useCallback(({ viewState: next }) => {
    commitCamera({ x: next.target[0], y: next.target[1], zoom: next.zoom }, { replace: true });
  }, [commitCamera]);
  const zoom = delta => commitCamera({ x: viewState.target[0], y: viewState.target[1], zoom: viewState.zoom + delta });
  const selectObject = info => {
    const object = info?.object;
    if (!object) return;
    if (object.entityKind === "agent") onSelectAgent(object.id);
    if (object.entityKind === "place") onSelectPlace(object.id);
    if (object.entityKind === "construction") onSelectProject?.(object.id);
    if (object.entityKind === "organization") onSelectFirm?.(object.id);
    if (object.entityKind === "cluster") onShowAllResidents();
  };
  return <div className="civic-diorama" data-testid="civic-diorama"
    data-camera={`${viewState.target[0]},${viewState.target[1]},${viewState.zoom}`}>
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
      <button type="button" onClick={() => commitCamera(DEFAULT_CITY_CAMERA)}>Reset camera</button>
      <button type="button" disabled={!selectedLabels.length} onClick={() => commitCamera({
        x: selectedLabels[0].position[0], y: selectedLabels[0].position[1], zoom: viewState.zoom,
      })}>Focus selection</button>
      <button type="button" aria-label="Pan city left" onClick={() => commitCamera({ x: viewState.target[0] - 5, y: viewState.target[1], zoom: viewState.zoom })}>←</button>
      <button type="button" aria-label="Pan city right" onClick={() => commitCamera({ x: viewState.target[0] + 5, y: viewState.target[1], zoom: viewState.zoom })}>→</button>
      <button type="button" aria-label="Pan city up" onClick={() => commitCamera({ x: viewState.target[0], y: viewState.target[1] - 5, zoom: viewState.zoom })}>↑</button>
      <button type="button" aria-label="Pan city down" onClick={() => commitCamera({ x: viewState.target[0], y: viewState.target[1] + 5, zoom: viewState.zoom })}>↓</button>
      <button type="button" className="civic-diorama__open-evidence" disabled={!selectedLabels.length} onClick={onOpenEvidence}>Open selected evidence ↓</button>
    </div>
    <div className="civic-diorama__footer">
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
    <details className="civic-diorama__method">
      <summary>How this scene is drawn</summary>
      <p>
      Height is a derived visual encoding of exposed capacity, occupancy, queue, or employee counts.
      Construction geometry uses stored work units and exact foundation, frame, shell, and completed stages.
      Flow curves connect committed public region endpoints; they do not imply a traveled street.
      Position interpolation is limited to consecutive live projections.
      </p>
    </details>
    </div>
  </div>;
}

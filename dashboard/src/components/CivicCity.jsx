/*
THESIS: A daylit civic weather room where the city itself is the primary operating instrument.
OWN-WORLD: Municipal survey plates, plotted districts, acetate evidence layers, and named signal inks.
STORY: Orient to the run, find working agents, select a city mark, then follow its committed evidence.
FIRST VIEWPORT: Stable civic navigation frames a two-thirds live atlas and a one-third evidence lens.
FORM: Civic Weather Room, grounded direction position 4; surveyed evidence-transect staging; seed 5d725ec9.
*/
import {
  Component,
  lazy,
  Suspense,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Link } from "react-router";
import { cityEvidenceParams } from "../app/cityNavigation.js";
import { CityCameraControls } from "./CityCameraControls.jsx";
import { CityAtlasViewport } from "./CityAtlasViewport.jsx";
import { DEFAULT_CITY_CAMERA, cityFollowState, normalizeCityCamera } from "../lib/cityCamera.js";
// Shared controls, place buttons and fallback styles must precede any renderer.
import "./civic-diorama.css";
import {
  CITY_DISTRICTS,
  CITY_LAYERS,
  deriveCityModel,
  filterCityAgents,
  humanize,
  resolveCityFilterPatch,
  semanticReceiptForEvent,
} from "../lib/civicCity.js";

const DISTRICT_PATHS = {
  institutions: "M5 6H39V35L34 44H5Z",
  communications: "M63 5H95V36H67L63 31Z",
  markets: "M59 39H96V65H62L57 58Z",
  health: "M60 68H93V94H58V76Z",
  work: "M6 57H55L59 66L55 94H6Z",
  commons: "M40 8H60V35L56 55H37L34 43L40 35Z",
};

const ACTIVE_RUN_STATUSES = new Set(["active", "running"]);
const CivicDiorama = lazy(() => import("./CivicDiorama.jsx").then(module => ({
  default: module.CivicDiorama,
})));
const RecordedDayCity = lazy(() => import("./LiveCity").then(module => ({ default: module.RecordedDayCity })));

class DioramaBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { failed: false };
  }

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

function webGL2Available() {
  if (typeof document === "undefined") return false;
  try {
    return Boolean(document.createElement("canvas").getContext("webgl2"));
  } catch {
    return false;
  }
}

function initials(name) {
  return String(name || "Agent")
    .split(/\s+/)
    .filter(Boolean)
    .map(part => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

function payloadFacts(payload) {
  if (!payload || typeof payload !== "object") return [];
  return Object.entries(payload)
    .filter(([, value]) => ["string", "number", "boolean"].includes(typeof value))
    .slice(0, 4);
}

function coordinateCopy(mode) {
  if (mode === "observed") return "Projected coordinates";
  if (mode === "mixed") return "Mixed projected + derived layout";
  return "Derived civic layout";
}

function constructionMetrics(project) {
  return {
    funding: Number(project?.contributedFundingCents ?? project?.contributed?.funding_cents ?? 0),
    requiredFunding: Number(project?.requiredFundingCents ?? project?.requirements?.funding_cents ?? 0),
    work: Number(project?.contributedWorkUnits ?? project?.contributed?.work_units ?? 0),
    requiredWork: Number(project?.requiredWorkUnits ?? project?.requirements?.work_units ?? 0),
  };
}

function constructionStage(project) {
  if (project?.stage) return String(project.stage);
  if (project?.status === "completed") return "completed";
  return "site";
}

function statusCopy(status, connected, tick, historical) {
  if (historical) return `Historical tick ${tick}`;
  if (!connected) return "Connection unavailable";
  if (["finished", "completed"].includes(status)) return "Run finished";
  if (status === "halted") return "Run halted";
  if (["failed", "error"].includes(status)) return "Run failed";
  if (status === "stopped") return "Run stopped";
  if (status === "paused") return "Run paused";
  return tick === "live" ? "Live world feed" : `Live world feed · tick ${tick}`;
}

/** @param {any} props */
export function CivicCity(props) {
  const {
    agents = [],
    firms = [],
    events = [],
    map = null,
    frame = null,
    conversations = null,
    conversationsLoading = false,
    conversationsError = "",
    civic = null,
    runtime = null,
    runId = "",
    tick = "live",
    phase = "",
    status = "",
    connected = true,
    loading = false,
    error = "",
    lineage = null,
    historical = false,
    variant = "world-os",
    observerState = null,
    onObserverStateChange = null,
  } = props;
  const [localActiveLayer, setLocalActiveLayer] = useState("all");
  const [localQuery, setLocalQuery] = useState("");
  const [localActiveOnly, setLocalActiveOnly] = useState(false);
  const [localSelectedId, setLocalSelectedId] = useState(null);
  const [localSelectedPlaceId, setLocalSelectedPlaceId] = useState(null);
  const [localSelectedProjectId, setLocalSelectedProjectId] = useState(null);
  const [localSelectedFirmId, setLocalSelectedFirmId] = useState(null);
  const [localCamera, setLocalCamera] = useState(null);
  const [localFollow, setLocalFollow] = useState(null);
  const cameraPositionRef = useRef(DEFAULT_CITY_CAMERA);
  const [localPopulation, setLocalPopulation] = useState("core");
  const [localView, setLocalView] = useState("atlas");
  const [hasWebGL2, setHasWebGL2] = useState(null);
  const activeLayer = observerState?.layer ?? localActiveLayer;
  const query = observerState?.q ?? localQuery;
  const activeOnly = observerState?.activeOnly ?? localActiveOnly;
  const selectedId = observerState?.agent ?? localSelectedId;
  const selectedPlaceId = observerState?.place ?? localSelectedPlaceId;
  const selectedProjectId = observerState?.project ?? localSelectedProjectId;
  const selectedFirmId = observerState?.firm ?? localSelectedFirmId;
  const populationMode = observerState?.population ?? localPopulation;
  const cityView = observerState?.view ?? localView;
  const followId = observerState ? observerState.follow : localFollow;
  const savedCamera = normalizeCityCamera(observerState ? observerState.camera : localCamera);
  const [filtersOpen, setFiltersOpen] = useState(Boolean(query || activeLayer !== "all" || activeOnly));
  const lensRef = useRef(null);
  const model = useMemo(
    () => deriveCityModel({ agents, firms, events, map, civic, runtime, tick, historical }),
    [agents, firms, events, map, civic, runtime, tick, historical],
  );
  const needle = query.trim().toLowerCase();
  const visibleAgents = filterCityAgents(model.agents, {
    layer: activeLayer,
    q: query,
    activeOnly,
  });
  const showClusters = populationMode === "clusters"
    && activeLayer === "all"
    && !activeOnly
    && !needle;
  const selectedPlace = model.places.find(
    place => String(place.id) === String(selectedPlaceId),
  ) || null;
  const selectedProject = model.constructionProjects.find(
    project => String(project.id) === String(selectedProjectId),
  ) || null;
  const selectedFirm = model.firms.find(firm => String(firm.id) === String(selectedFirmId)) || null;
  const selected = selectedPlace || selectedProject || selectedFirm ? null : (
    visibleAgents.find(agent => String(agent.id) === String(selectedId))
      || (!followId && (visibleAgents.find(agent => agent.isActive)
        || visibleAgents.find(agent => agent.event) || visibleAgents[0]))
      || null
  );
  const follow = cityFollowState(model.agents, visibleAgents, followId, loading || Boolean(error));
  const displayCamera = follow.target
    ? { ...savedCamera, x: follow.target.x, y: follow.target.y } : savedCamera;
  const cameraSelection = selectedProject || selectedPlace || selectedFirm || selected;
  useLayoutEffect(() => {
    if (cityView !== "recorded") cameraPositionRef.current = displayCamera;
  }, [cityView, displayCamera.x, displayCamera.y, displayCamera.zoom]);
  const selectedIndex = selected
    ? visibleAgents.findIndex(agent => String(agent.id) === String(selected.id))
    : -1;
  useEffect(() => {
    if (!observerState || !onObserverStateChange || loading || error || followId) return;
    const resolvedId = selected ? Number(selected.id) : null;
    if (observerState.firm != null) {
      if (!selectedFirm) onObserverStateChange({ firm: null, agent: resolvedId }, { replace: true });
      return;
    }
    if (observerState.project != null) {
      if (!selectedProject) {
        onObserverStateChange(
          { project: null, agent: resolvedId },
          { replace: true },
        );
      }
      return;
    }
    if (observerState.place != null) {
      if (!selectedPlace) {
        onObserverStateChange(
          { place: null, agent: resolvedId },
          { replace: true },
        );
      }
      return;
    }
    if (observerState.agent !== resolvedId) {
      onObserverStateChange({ agent: resolvedId }, { replace: true });
    }
  }, [
    loading,
    error,
    observerState,
    followId,
    onObserverStateChange,
    selected,
    selectedPlace,
    selectedProject,
    selectedFirm,
  ]);
  useEffect(() => {
    if (cityView === "diorama" && hasWebGL2 === null) {
      setHasWebGL2(webGL2Available());
    }
  }, [cityView, hasWebGL2]);
  const employer = selected?.employer_id == null
    ? null
    : model.firms.find(firm => String(firm.id) === String(selected.employer_id));
  const eventFacts = payloadFacts(selected?.event?.payload);
  const semanticReceipt = semanticReceiptForEvent(selected?.event, model.receipts);
  const associatedFirm = selectedPlace
    ? model.firms.find(firm =>
      String(firm.place_id) === String(selectedPlace.id)
      || (selectedPlace.owner_type === "firm"
        && String(firm.id) === String(selectedPlace.owner_id)))
    : null;
  const selectedProjectMetrics = constructionMetrics(selectedProject);
  const busiestOffice = [...(model.civic?.offices || [])]
    .sort((left, right) => Number(right.occupancy) - Number(left.occupancy))[0];
  /* A tick is carried into the lens links only when this view is itself a
     reconstruction. The live Observatory passes the feed's current tick for
     display; pinning it into a link would open the destination workspace as a
     frozen historical view of a run that is still moving. */
  const commonParams = cityEvidenceParams({ ...observerState, tick: historical ? String(tick) : "live",
    firm: selectedFirm?.id, agent: followId || selected?.id, follow: followId, place: selectedPlace?.id, project: selectedProject?.id,
    view: cityView, layer: activeLayer, q: query, population: populationMode, activeOnly,
    camera: observerState ? observerState.camera : localCamera });
  const commonSuffix = commonParams.toString() ? `?${commonParams}` : "";
  const firmHref = selectedFirm && runId
    ? `/runs/${encodeURIComponent(runId)}/organizations/firm/${selectedFirm.id}${commonSuffix}` : null;
  const priceParams = new URLSearchParams(commonParams);
  priceParams.set("view", "prices");
  if (selectedFirm) priceParams.set("price_firm", String(selectedFirm.id));
  const pricesHref = selectedFirm && runId ? `/runs/${encodeURIComponent(runId)}/markets?${priceParams}` : null;
  const peopleHref = selected && runId
    ? `/runs/${encodeURIComponent(runId)}/people/${selected.id}${commonSuffix}`
    : null;
  const traceParams = new URLSearchParams(commonParams);
  if (selected?.event) traceParams.set("event", String(selected.event.id));
  const traceHref = selected?.event && runId
    ? `/runs/${encodeURIComponent(runId)}/investigations?${traceParams}`
    : null;
  const worldPlaceParams = new URLSearchParams(commonParams);
  if (selectedPlace) {
    worldPlaceParams.set("place", String(selectedPlace.id));
    worldPlaceParams.set("view", cityView);
  }
  const placeHref = selectedPlace && runId
    ? `/runs/${encodeURIComponent(runId)}/world?${worldPlaceParams}`
    : null;
  const worldProjectParams = new URLSearchParams(commonParams);
  if (selectedProject) {
    worldProjectParams.set("project", String(selectedProject.id));
    worldProjectParams.set("view", cityView);
  }
  const projectHref = selectedProject && runId
    ? `/runs/${encodeURIComponent(runId)}/world?${worldProjectParams}`
    : null;
  const completedPlaceParams = new URLSearchParams(commonParams);
  if (selectedProject?.place_id != null) {
    completedPlaceParams.set("place", String(selectedProject.place_id));
    completedPlaceParams.set("view", cityView);
  }
  const completedPlaceHref = selectedProject?.place_id != null && runId
    ? `/runs/${encodeURIComponent(runId)}/world?${completedPlaceParams}`
    : null;
  const layerCounts = Object.fromEntries(
    CITY_LAYERS.map(layer => [
      layer.id,
      layer.id === "all"
        ? model.agents.length
        : model.agents.filter(agent => agent.layer === layer.id || agent.eventLayer === layer.id).length,
    ]),
  );
  const providerActive = runtime?.global?.in_flight;
  const providerCapacity = runtime?.global?.capacity;
  const liveAgents = model.agents
    .filter(agent => agent.runtimeActivity)
    .sort((left, right) => {
      const precedence = { thinking: 0, queued: 1 };
      return (precedence[left.activityState] ?? 2) - (precedence[right.activityState] ?? 2)
        || Number(left.id) - Number(right.id);
    });
  const changedAgents = model.agents
    .filter(agent => agent.transitionEvent && !agent.runtimeActivity)
    .sort((left, right) => Number(right.transitionEvent.id) - Number(left.transitionEvent.id));

  const moveSelection = direction => {
    if (!visibleAgents.length) return;
    const nextIndex = (Math.max(0, selectedIndex) + direction + visibleAgents.length) % visibleAgents.length;
    const nextId = visibleAgents[nextIndex].id;
    if (onObserverStateChange) onObserverStateChange({ agent: nextId });
    else {
      setLocalFollow(null);
      setLocalSelectedId(nextId);
      setLocalSelectedPlaceId(null);
      setLocalSelectedProjectId(null);
      setLocalSelectedFirmId(null);
    }
  };
  const changeObserverFilter = (update, options) => {
    const patch = resolveCityFilterPatch(model.agents, {
      layer: activeLayer,
      q: query,
      activeOnly,
      agent: selectedId,
    }, update);
    onObserverStateChange(followId ? { ...patch, agent: followId } : patch, options);
  };
  const changeLayer = value => {
    if (onObserverStateChange) changeObserverFilter({ layer: value });
    else setLocalActiveLayer(value);
  };
  const changeQuery = value => {
    if (onObserverStateChange) {
      if (value && populationMode === "clusters") {
        onObserverStateChange({ q: value, population: "all", agent: followId || null }, { replace: true });
      } else {
        changeObserverFilter({ q: value }, { replace: true });
      }
    } else {
      setLocalQuery(value);
      if (value && populationMode === "clusters") {
        setLocalPopulation("all");
        setLocalSelectedId(null);
      }
    }
  };
  const changeActiveOnly = value => {
    if (onObserverStateChange) changeObserverFilter({ activeOnly: value });
    else setLocalActiveOnly(value);
  };
  const changeSelection = value => {
    if (onObserverStateChange) onObserverStateChange({ agent: value });
    else {
      if (String(value) !== String(localFollow)) setLocalFollow(null);
      setLocalSelectedId(value);
      setLocalSelectedPlaceId(null);
      setLocalSelectedProjectId(null);
      setLocalSelectedFirmId(null);
    }
  };
  const changePlaceSelection = value => {
    if (onObserverStateChange) onObserverStateChange({ place: value });
    else {
      setLocalFollow(null);
      setLocalSelectedPlaceId(value);
      setLocalSelectedId(null);
      setLocalSelectedProjectId(null);
      setLocalSelectedFirmId(null);
    }
  };
  const changeProjectSelection = value => {
    if (onObserverStateChange) onObserverStateChange({ project: value });
    else {
      setLocalFollow(null);
      setLocalSelectedProjectId(value);
      setLocalSelectedPlaceId(null);
      setLocalSelectedId(null);
      setLocalSelectedFirmId(null);
    }
  };
  const changeFirmSelection = value => {
    if (onObserverStateChange) onObserverStateChange({ firm: value });
    else {
      setLocalFollow(null);
      setLocalSelectedFirmId(value);
      setLocalSelectedId(null);
      setLocalSelectedPlaceId(null);
      setLocalSelectedProjectId(null);
    }
  };
  const changeCamera = (value, options) => {
    const next = normalizeCityCamera(value);
    if (onObserverStateChange) onObserverStateChange({ camera: next,
      ...(options?.keepFollow ? {} : { follow: null }) }, { replace: options?.replace });
    else { setLocalCamera(next); if (!options?.keepFollow) setLocalFollow(null); }
  };
  const toggleFollow = () => {
    if (followId) { changeCamera(cameraPositionRef.current); return; }
    if (!selected) return;
    if (onObserverStateChange) onObserverStateChange({ agent: Number(selected.id), follow: Number(selected.id) });
    else { setLocalSelectedId(selected.id); setLocalFollow(Number(selected.id)); }
  };
  const changeView = value => {
    if (onObserverStateChange) onObserverStateChange({ view: value });
    else setLocalView(value);
  };
  const changePopulation = value => {
    const clusterPatch = value === "clusters"
      ? { population: value, q: null, layer: null, activeOnly: false, agent: null, place: null, project: null, firm: null }
      : { population: value, agent: null, place: null, project: null, firm: null };
    if (onObserverStateChange) onObserverStateChange(followId ? { ...clusterPatch, agent: followId } : clusterPatch);
    else {
      setLocalPopulation(value);
      setLocalSelectedId(localFollow);
      setLocalSelectedPlaceId(null);
      setLocalSelectedProjectId(null);
      setLocalSelectedFirmId(null);
      if (value === "clusters") {
        setLocalQuery("");
        setLocalActiveLayer("all");
        setLocalActiveOnly(false);
      }
    }
  };
  const resetView = () => {
    if (onObserverStateChange) {
      onObserverStateChange({
        q: null,
        layer: null,
        activeOnly: false,
        agent: null,
        place: null,
        project: null,
        firm: null,
        camera: null,
        follow: null,
        population: null,
      });
      return;
    }
    setLocalQuery("");
    setLocalActiveLayer("all");
    setLocalActiveOnly(false);
    setLocalSelectedId(null);
    setLocalSelectedPlaceId(null);
    setLocalSelectedProjectId(null);
    setLocalSelectedFirmId(null);
    setLocalCamera(null);
    setLocalFollow(null);
    setLocalPopulation("core");
  };
  const openMobileLens = () => {
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    lensRef.current?.scrollIntoView({
      behavior: reduceMotion ? "auto" : "smooth",
      block: "start",
    });
  };
  const runIsActive = ACTIVE_RUN_STATUSES.has(String(status).toLowerCase());
  const animateLiveActivity = tick === "live" && connected && !historical && liveAgents.length > 0;

  return <section
    className={`civic-city civic-city--${variant} civic-city--view-${cityView}${model.agents.length > 72 ? " civic-city--dense" : ""}`}
    aria-labelledby={`civic-city-title-${variant}`}
    aria-busy={loading}
  >
    <header className="civic-city__mast">
      <div className="civic-city__heading">
        <p>Civic Weather Room <span>Map sheet 01</span></p>
        <h2 id={`civic-city-title-${variant}`}>The living city</h2>
        <p className="civic-city__lede">See who is working, what changed, and which committed record proves it.</p>
      </div>
      <dl className="civic-city__run-state" aria-label="City run state">
        <div><dt>Feed</dt><dd><i className={connected ? "is-live" : "is-offline"} />{statusCopy(status, connected, tick, historical)}</dd></div>
        <div><dt>Phase</dt><dd>{humanize(phase, "Between phases")}</dd></div>
        <div><dt>AI live</dt><dd>{historical || !runtime || cityView === "recorded" ? "Unavailable in this view" : `${model.counts.thinking} thinking · ${model.counts.queued} queued`}</dd></div>
        <div><dt>Changed</dt><dd>{model.counts.settled} settled · {model.counts.rejected} rejected</dd></div>
        <div><dt>Residents</dt><dd>{model.counts.residents} <small>{model.population.core} core</small></dd></div>
        <div><dt>Construction</dt><dd>{model.counts.construction} <small>stored projects</small></dd></div>
        <div><dt>Permit queue</dt><dd>{model.civic?.enabled ? model.counts.queue : "—"}</dd></div>
      </dl>
    </header>

    <div className="civic-city__controls">
      <div className="civic-city__view-toggle" role="group" aria-label="City view">
        <span>Projection</span>
        <div>
          <button type="button" aria-pressed={cityView === "atlas"} onClick={() => changeView("atlas")}>Atlas</button>
          <button type="button" aria-pressed={cityView === "diorama"} onClick={() => changeView("diorama")}>2.5D Diorama</button>
          {onObserverStateChange && <button type="button" aria-pressed={cityView === "recorded"} onClick={() => changeView("recorded")}>Recorded day</button>}
        </div>
      </div>
      <details className="civic-city__filter-panel" open={filtersOpen} onToggle={event => setFiltersOpen(event.currentTarget.open)}>
        <summary>Layers and agent filters</summary>
        <div className="civic-city__filters">
      <div className="civic-city__layers" role="group" aria-label="City evidence layer">
        {CITY_LAYERS.map(layer => <button
          key={layer.id}
          type="button"
          className={activeLayer === layer.id ? "is-active" : ""}
          aria-pressed={activeLayer === layer.id}
          onClick={() => changeLayer(layer.id)}
        >
          <span>{layer.shortLabel}</span><b>{layerCounts[layer.id]}</b>
        </button>)}
      </div>
      {model.population.periphery > 0 && <div className="civic-city__population" role="group" aria-label="City population detail">
        <span>Population detail</span>
        <div>
          <button type="button" aria-pressed={populationMode === "core"} onClick={() => changePopulation("core")}>Core <b>{model.population.core}</b></button>
          <button type="button" aria-pressed={populationMode === "all"} onClick={() => changePopulation("all")}>Everyone <b>{model.population.total}</b></button>
          <button type="button" aria-pressed={populationMode === "clusters"} onClick={() => changePopulation("clusters")}>Clusters <b>{model.population.periphery}</b></button>
        </div>
      </div>}
      <label className="civic-city__search">
        <span>Find an agent</span>
        <input
          type="search"
          value={query}
          onChange={event => changeQuery(event.target.value)}
          placeholder="Name, role, event…"
        />
      </label>
      <label className="civic-city__active-toggle">
        <input type="checkbox" checked={activeOnly} onChange={event => changeActiveOnly(event.target.checked)} />
        <span>Live or changed this tick</span>
      </label>
        </div>
      </details>
    </div>

    <label className="civic-city__object-explorer">
      <span>Keyboard explorer</span>
      <select aria-label="Keyboard explorer" disabled={loading || Boolean(error)}
        value={selectedProject ? `project:${selectedProject.id}` : selectedPlace ? `place:${selectedPlace.id}`
          : selectedFirm ? `firm:${selectedFirm.id}` : selected ? `agent:${selected.id}` : ""}
        onChange={event => {
          const value = event.target.value;
          const index = value.indexOf(":");
          const kind = value.slice(0, index), id = value.slice(index + 1);
          if (kind === "agent") changeSelection(id);
          if (kind === "firm") changeFirmSelection(id);
          if (kind === "place") changePlaceSelection(id);
          if (kind === "project") changeProjectSelection(id);
        }}>
        <option value="">Choose a public object</option>
        <optgroup label="Businesses">{model.firms.map(firm => <option key={firm.id} value={`firm:${firm.id}`}>{firm.name || `Firm ${firm.id}`}</option>)}</optgroup>
        <optgroup label="Places">{model.places.map(place => <option key={place.id} value={`place:${place.id}`}>{place.name || `Place ${place.id}`}</option>)}</optgroup>
        <optgroup label="Construction projects">{model.constructionProjects.map(project => <option key={project.id} value={`project:${project.id}`}>{project.name} · {humanize(constructionStage(project))}</option>)}</optgroup>
        <optgroup label="Agents">{visibleAgents.map(agent => <option key={agent.id} value={`agent:${agent.id}`}>{agent.name}</option>)}</optgroup>
      </select>
      <span>One selection across city views</span>
    </label>
    <div className="city-follow">
      <button type="button" aria-pressed={Boolean(followId)}
        disabled={!followId && (!selected || loading || Boolean(error) || selected.alive === false || selected.alive === 0)}
        onClick={toggleFollow}>{followId ? "Stop following" : "Follow person"}</button>
      <p role="status" aria-label="City follow status">{cityView === "recorded"
        ? (followId ? `Follow enabled for person #${followId}.` : "Select a person to follow their recorded day.")
        : follow.message || "Select a person to follow across committed ticks. Drag the Atlas background to pan."}</p>
    </div>
    {cityView !== "recorded" && <CityCameraControls
      getCamera={() => cameraPositionRef.current} onCameraChange={changeCamera}
      canFocus={Boolean(cameraSelection)} disabled={loading || Boolean(error)}
      onFocus={() => cameraSelection && changeCamera({ ...displayCamera, x: cameraSelection.x, y: cameraSelection.y })}
    />}
    <div className="civic-city__workfield">
      <div className={`civic-city__atlas civic-city__atlas--${cityView}`}>
        {cityView === "recorded" && <Suspense fallback={<p role="status">Loading recorded-day renderer…</p>}>
          <RecordedDayCity
            key={`${frame?.snapshot_version}:${populationMode}:${activeLayer}:${query}:${activeOnly}`}
            frame={frame} visibleAgentIds={visibleAgents.map(agent => Number(agent.id))}
            selectedAgentId={selected?.id ?? null} onSelectAgent={changeSelection}
            camera={savedCamera} followId={followId} cameraPositionRef={cameraPositionRef} onCameraChange={changeCamera}
            onOpenEvidence={openMobileLens}
            onPinDay={() => frame && onObserverStateChange({ tick: String(frame.tick) })}
            historical={historical} loading={loading} error={error}
            conversations={conversations} conversationsLoading={conversationsLoading} conversationsError={conversationsError}
          />
        </Suspense>}
        {cityView === "diorama" && <div className="civic-city__diorama-field">
          {hasWebGL2 === false ? <div className="civic-city__diorama-fallback" role="status">
            <strong>2.5D rendering is unavailable in this browser.</strong>
            <span>The evidence-safe Atlas remains fully available.</span>
            <button type="button" onClick={() => changeView("atlas")}>Use Atlas</button>
          </div> : hasWebGL2 === null ? <div className="civic-city__diorama-fallback" role="status">
            <strong>Checking 2.5D rendering support…</strong>
          </div> : <DioramaBoundary fallback={<div className="civic-city__diorama-fallback" role="alert">
            <strong>The 2.5D renderer could not start.</strong>
            <span>No simulation state was changed. Continue in the Atlas view.</span>
            <button type="button" onClick={() => changeView("atlas")}>Use Atlas</button>
          </div>}>
            <Suspense fallback={<div className="civic-city__diorama-fallback" role="status">
              <strong>Loading the 2.5D city…</strong>
              <span>The renderer is loaded only when this view is requested.</span>
            </div>}>
              <CivicDiorama
                model={model}
                visibleAgents={visibleAgents}
                showClusters={showClusters}
                selectedAgentId={selected?.id ?? null}
                selectedPlaceId={selectedPlace?.id ?? null}
                selectedProjectId={selectedProject?.id ?? null}
                selectedFirmId={selectedFirm?.id ?? null}
                camera={displayCamera}
                onCameraChange={changeCamera}
                onOpenEvidence={openMobileLens}
                onSelectAgent={changeSelection}
                onSelectPlace={changePlaceSelection}
                onSelectFirm={changeFirmSelection}
                onSelectProject={changeProjectSelection}
                onShowAllResidents={() => changePopulation("all")}
                animateLiveActivity={animateLiveActivity}
                tick={tick}
                historical={historical}
              />
            </Suspense>
          </DioramaBoundary>}
        </div>}
        <div className="civic-city__map-field" hidden={cityView !== "atlas"}>
          <div className="civic-city__atlas-meta">
            <span className={`civic-city__source civic-city__source--${model.coordinateMode}`}>{coordinateCopy(model.coordinateMode)}</span>
            <span>{showClusters
              ? `${visibleAgents.length} core marks + ${model.population.clusteredAgents} clustered residents`
              : `${visibleAgents.length} of ${model.population.total} residents visible`}</span>
          </div>
          <CityAtlasViewport camera={displayCamera} onCameraChange={changeCamera} disabled={loading || Boolean(error)}>
          <svg className="civic-city__plot" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
            <defs>
              <pattern id={`civic-grid-${variant}`} width="5" height="5" patternUnits="userSpaceOnUse">
                <path d="M5 0H0V5" fill="none" vectorEffect="non-scaling-stroke" />
              </pattern>
              <marker id={`civic-arrow-${variant}`} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
                <path className="civic-city__arrowhead" d="M0 0L8 4L0 8Z" />
              </marker>
            </defs>
          <rect width="100" height="100" className="civic-city__paper" />
          <rect width="100" height="100" fill={`url(#civic-grid-${variant})`} className="civic-city__grid" />
          {Object.entries(DISTRICT_PATHS).map(([id, path]) =>
            <path key={id} d={path} className={`civic-city__district civic-city__district--${id}`} vectorEffect="non-scaling-stroke" />,
          )}
          <path className="civic-city__river" d="M44 -4C36 18 68 27 49 47S58 75 47 104" vectorEffect="non-scaling-stroke" />
          <path className="civic-city__route" d="M1 51H99M48 1V99M17 42L87 69M37 12L66 89" vectorEffect="non-scaling-stroke" />
          <path className="civic-city__contour" d="M44 24c13-10 29 1 26 14s-23 15-30 4 0-15 4-18Zm-17 41c11-8 25 0 24 11s-17 16-27 7-5-13 3-18Z" vectorEffect="non-scaling-stroke" />
          {selected && <>
            <path
              className={selected.isActive ? "civic-city__transect is-active" : "civic-city__transect"}
              d={`M${selected.x} ${selected.y} H92`}
              markerEnd={selected.isActive ? `url(#civic-arrow-${variant})` : undefined}
              vectorEffect="non-scaling-stroke"
            />
            <circle className="civic-city__transect-origin" cx={selected.x} cy={selected.y} r="2.1" vectorEffect="non-scaling-stroke" />
          </>}
          {animateLiveActivity && <path className="civic-city__weather-sweep" d="M-8 10L30 100" vectorEffect="non-scaling-stroke" />}
        </svg>

        {Object.values(CITY_DISTRICTS).map(district => <div
          className={`civic-city__district-label civic-city__district-label--${district.id}`}
          key={district.id}
          style={{ left: `${district.bounds.x + 2}%`, top: `${district.bounds.y + 2}%` }}
        >
          <strong>{district.name}</strong><span>{district.note}</span>
        </div>)}

        {model.firms.map(firm => <button type="button"
          key={`firm-${firm.id}`}
          className={`civic-city__firm civic-city__firm--${firm.layer}${String(firm.id) === String(selectedFirmId) ? " is-selected" : ""}`}
          style={{ left: `${firm.x}%`, top: `${firm.y}%` }}
          title={`${firm.name || "Firm"} · ${humanize(firm.sector || firm.status)}`}
          onClick={() => changeFirmSelection(firm.id)}
          aria-label={`Select business ${firm.name || firm.id}`}
          aria-pressed={String(firm.id) === String(selectedFirmId)}
        >
          <span>{String(firm.name || "Firm").replace(/\s+(co|company|inc)\b.*$/i, "").slice(0, 16)}</span>
        </button>)}

        {model.constructionProjects
          .filter(project => !(project.status === "completed" && project.place_id != null))
          .map(project => {
            const metrics = constructionMetrics(project);
            const stage = constructionStage(project);
            const selectedHere = selectedProject
              && String(selectedProject.id) === String(project.id);
            const aggregateCount = Number(project.aggregateCount ?? project.aggregate_count ?? 1);
            const aggregate = project.privacy === "aggregated_private";
            const stageCopy = stage === "site" ? humanize(project.status) : humanize(stage);
            return <button
              type="button"
              key={`construction-${project.id}`}
              className={[
                "civic-city__construction",
                `is-${stage}`,
                project.status === "cancelled" ? "is-cancelled" : "",
                aggregate ? "is-aggregate" : "",
                selectedHere ? "is-selected" : "",
              ].filter(Boolean).join(" ")}
              style={{ left: `${project.x}%`, top: `${project.y}%` }}
              title={`${project.name} · ${stageCopy} · ${metrics.work}/${metrics.requiredWork} work units`}
              onClick={() => changeProjectSelection(project.id)}
              aria-pressed={selectedHere}
              aria-label={`Select ${project.name}, ${stageCopy}, ${metrics.work} of ${metrics.requiredWork} work units${aggregate ? `, ${aggregateCount} private homes aggregated` : ""}`}
            >
              <i aria-hidden="true" />
              <span>
                {aggregate && aggregateCount > 1 ? `${aggregateCount} homes · ` : ""}
                {stageCopy} · {metrics.work}/{metrics.requiredWork} work
              </span>
            </button>;
          })}

        {model.places.map(place => <button
          type="button"
          key={`place-${place.id}`}
          className={[
            "civic-city__place",
            place.kind === "licensing_office" ? "is-permit-office" : "",
            selectedPlace && String(selectedPlace.id) === String(place.id) ? "is-selected" : "",
          ].filter(Boolean).join(" ")}
          style={{ left: `${place.x}%`, top: `${place.y}%` }}
          title={`${place.name} · ${humanize(place.kind)} · ${place.businessOccupancy}/${place.capacity || "∞"} present${place.queueDepth ? ` · queue ${place.queueDepth}` : ""}`}
          onClick={() => changePlaceSelection(place.id)}
          aria-pressed={selectedPlace && String(selectedPlace.id) === String(place.id)}
          aria-label={`Select ${place.name}, ${humanize(place.kind)}, ${place.businessOccupancy} of ${place.capacity || "unbounded"} present${place.queueDepth ? `, queue ${place.queueDepth}` : ""}`}
        >
          <i />
          {place.kind === "licensing_office" && <span>
            Permit office · {place.businessOccupancy}/{place.capacity} · q{place.queueDepth}
          </span>}
        </button>)}

        <div className="civic-city__agent-layer">
          {visibleAgents.map(agent => <button
            key={agent.id}
            type="button"
            className={[
              "civic-city__agent",
              `civic-city__agent--${agent.layer}`,
              `is-${agent.activityState.replaceAll(" ", "-")}`,
              selected && String(selected.id) === String(agent.id) ? "is-selected" : "",
            ].filter(Boolean).join(" ")}
            style={{ left: `${agent.x}%`, top: `${agent.y}%` }}
            onClick={() => changeSelection(agent.id)}
            aria-pressed={selected && String(selected.id) === String(agent.id)}
            aria-label={`${agent.name}, ${humanize(agent.role || agent.occupation || agent.kind)}, ${humanize(agent.activityState)}${agent.runtimeActivity?.active_calls > 1 ? `, ${agent.runtimeActivity.active_calls} active calls` : ""}`}
          >
            <span>{initials(agent.name)}</span>
          </button>)}
        </div>
        {showClusters && <div className="civic-city__cluster-layer" aria-label="Peripheral resident clusters">
          {model.clusters.map(cluster => <button
            key={cluster.id}
            type="button"
            className="civic-city__cluster"
            style={{ left: `${cluster.x}%`, top: `${cluster.y}%` }}
            onClick={() => changePopulation("all")}
            aria-label={`Show ${cluster.count} ${cluster.label} peripheral residents individually`}
          >
            <strong>{cluster.count}</strong>
            <span>{cluster.label}</span>
          </button>)}
        </div>}

          </CityAtlasViewport>
        {error && <div className="civic-city__empty" role="alert">
          <strong>City evidence is temporarily unavailable.</strong>
          <span>{error}</span>
        </div>}
        {!loading && !error && !visibleAgents.length && !model.places.length && !model.constructionProjects.length && <div className="civic-city__empty">
          <strong>No city marks match this view.</strong>
          <span>Clear the search or show all activity layers.</span>
          <button type="button" onClick={resetView}>Reset city view</button>
        </div>}
        {loading && !error && <div className="civic-city__empty" aria-live="polite">
          <strong>Surveying the current run…</strong>
          <span>Agent and event marks will appear from canonical APIs.</span>
        </div>}

        <div className="civic-city__legend" role="group" aria-label="City map legend">
          <span><i className="is-thinking" />Thinking</span>
          <span><i className="is-queued" />Queued</span>
          <span><i className="is-settled" />Settled</span>
          <span><i className="is-rejected" />Rejected</span>
          <span><i className="is-cluster" />Peripheral cluster</span>
          <span><i className="is-construction" />Construction stage</span>
          <span><i />Assigned or resident</span>
          <span><b />Firm footprint</span>
        </div>
        <div className="civic-city__coordinates" aria-hidden="true">
          <span>GRID A-01</span><span>FIELD E-23</span><span>AE / {String(tick).padStart(4, "0")}</span>
        </div>
          {(selected || selectedPlace || selectedProject || selectedFirm) && <button
            type="button"
            className="civic-city__mobile-peek"
            onClick={openMobileLens}
          >
            <span>
              <b>{selectedFirm?.name || selectedProject?.name || selectedPlace?.name || selected?.name}</b>
              <small>{selectedProject
                ? `${humanize(constructionStage(selectedProject))} · ${selectedProjectMetrics.work}/${selectedProjectMetrics.requiredWork} work`
                : selectedFirm ? humanize(selectedFirm.sector) : selectedPlace ? humanize(selectedPlace.kind) : humanize(selected?.activityState)}</small>
            </span>
            <strong>Open evidence ↓</strong>
          </button>}
        </div>
      </div>

      <aside
        ref={lensRef}
        className="civic-city__lens"
        aria-live="polite"
        aria-label="Selected city evidence"
      >
        <header>
          <div><p>Evidence lens</p><span>Observed + derived fields</span></div>
          <div className="civic-city__lens-nav">
            <button type="button" onClick={() => moveSelection(-1)} disabled={visibleAgents.length < 2} aria-label="Previous visible agent">←</button>
            <button type="button" onClick={() => moveSelection(1)} disabled={visibleAgents.length < 2} aria-label="Next visible agent">→</button>
          </div>
        </header>
        {selectedFirm ? <>
          <div className="civic-city__identity">
            <span className="civic-city__avatar civic-city__avatar--work" aria-hidden="true">{initials(selectedFirm.name)}</span>
            <div><p>Business #{selectedFirm.id}</p><h3>{selectedFirm.name}</h3><span>{humanize(selectedFirm.sector)}</span></div>
          </div>
          <div className="civic-city__activity civic-city__activity--place">
            <span>Committed business record</span><strong>{humanize(selectedFirm.status)}</strong>
            <small>Observed at tick {model.selectedTick}</small>
          </div>
          <dl className="civic-city__facts">
            <div><dt>Sector</dt><dd>{humanize(selectedFirm.sector)}</dd></div>
            <div><dt>Status</dt><dd>{humanize(selectedFirm.status)}</dd></div>
            <div><dt>Region</dt><dd>{selectedFirm.region_id == null ? "Not exposed" : `Region #${selectedFirm.region_id}`}</dd></div>
            <div><dt>Workplace</dt><dd>{selectedFirm.place_name || (selectedFirm.place_id == null ? "Not exposed" : `Place #${selectedFirm.place_id}`)}</dd></div>
            <div><dt>Employees</dt><dd>{selectedFirm.employees ?? "Not exposed by this map"}</dd></div>
            <div><dt>Placement</dt><dd>{selectedFirm.coordinateSource === "derived" ? "Derived district layout"
              : selectedFirm.place_id != null ? "Recorded workplace" : selectedFirm.region_id != null ? "Regional anchor" : "Projected map point"}</dd></div>
          </dl>
          <section className="civic-city__record">
            <header><span>Price discovery</span><b>goods + equity</b></header>
            <p>Inspect posted offers, actual sale prices, trading volume and execution age for this business at the same observation. Unlisted shares and periods without trades remain explicit.</p>
          </section>
          <div className="civic-city__lens-actions">
            {pricesHref && <Link className="is-primary" to={pricesHref}>Inspect goods and equity prices <span>→</span></Link>}
            {firmHref && <Link to={firmHref}>Open business dossier <span>↗</span></Link>}
            {selectedFirm.place_id != null && model.places.some(place => String(place.id) === String(selectedFirm.place_id)) && <button type="button" onClick={() => changePlaceSelection(selectedFirm.place_id)}>Inspect workplace</button>}
          </div>
        </> : selectedProject ? <>
          <div className="civic-city__identity">
            <span className="civic-city__avatar civic-city__avatar--construction" aria-hidden="true">▧</span>
            <div>
              <p>Construction {selectedProject.privacy === "aggregated_private" ? "aggregate" : `#${selectedProject.id}`}</p>
              <h3>{selectedProject.name}</h3>
              <span>{humanize(selectedProject.target_place_type)}</span>
            </div>
          </div>
          <div className={`civic-city__activity civic-city__activity--construction is-${constructionStage(selectedProject)}`}>
            <span>{selectedProject.privacy === "aggregated_private" ? "Privacy-safe district aggregate" : "Committed construction record"}</span>
            <strong>{humanize(selectedProject.status)} · {humanize(constructionStage(selectedProject))}</strong>
            <small>{selectedProjectMetrics.work}/{selectedProjectMetrics.requiredWork} stored work units · updated tick {selectedProject.updated_tick}</small>
          </div>
          <dl className="civic-city__facts">
            <div><dt>Target</dt><dd>{humanize(selectedProject.target_place_type)}</dd></div>
            <div><dt>Region</dt><dd>{selectedProject.region?.name || (selectedProject.region?.id == null ? "Not exposed" : `Region #${selectedProject.region.id}`)}</dd></div>
            <div><dt>Lifecycle status</dt><dd>{humanize(selectedProject.status)}</dd></div>
            <div><dt>Physical stage</dt><dd>{humanize(constructionStage(selectedProject))}</dd></div>
            <div><dt>Funding</dt><dd>{selectedProjectMetrics.funding}/{selectedProjectMetrics.requiredFunding} cents</dd></div>
            <div><dt>Work</dt><dd>{selectedProjectMetrics.work}/{selectedProjectMetrics.requiredWork} units</dd></div>
            <div><dt>Milestones</dt><dd>{Number(selectedProject.milestone_count || 0)}</dd></div>
            <div><dt>Privacy</dt><dd>{selectedProject.privacy === "aggregated_private" ? "Owners and exact sites withheld" : "Public or policy-authorized site"}</dd></div>
          </dl>
          <section className="civic-city__record">
            <header><span>Stored milestones</span><b>{Number(selectedProject.milestone_count || 0)}</b></header>
            {selectedProject.milestones?.length ? <dl>
              {selectedProject.milestones.map((milestone, index) => <div key={`${milestone.stage}-${milestone.tick}-${index}`}>
                <dt>{humanize(milestone.stage)}</dt><dd>Tick {milestone.tick}</dd>
              </div>)}
            </dl> : <p>{selectedProject.privacy === "aggregated_private"
              ? "Individual project milestones are withheld inside this district aggregate."
              : "No later milestone was committed by this tick."}</p>}
          </section>
          <section className="civic-city__receipt">
            <header><span>Construction evidence</span><b>observer only</b></header>
            <p>Stage geometry is derived from stored work units. This view cannot assign work, fund a project, or mutate the simulation.</p>
          </section>
          <div className="civic-city__lens-actions">
            {projectHref && <Link className="is-primary" to={projectHref}>Open in Live City <span>→</span></Link>}
            {completedPlaceHref && <Link to={completedPlaceHref}>Open completed place <span>↗</span></Link>}
          </div>
        </> : selectedPlace ? <>
          <div className="civic-city__identity">
            <span className="civic-city__avatar civic-city__avatar--place" aria-hidden="true">⌂</span>
            <div>
              <p>Place #{selectedPlace.id}</p>
              <h3>{selectedPlace.name}</h3>
              <span>{humanize(selectedPlace.kind)}</span>
            </div>
          </div>
          <div className="civic-city__activity civic-city__activity--place">
            <span>Committed public place</span>
            <strong>{selectedPlace.businessOccupancy} present · queue {selectedPlace.queueDepth}</strong>
            <small>
              {historical ? `Reconstructed at tick ${tick}` : `Observed at ${tick === "live" ? "the current tick" : `tick ${tick}`}`}
            </small>
          </div>
          <dl className="civic-city__facts">
            <div><dt>Kind</dt><dd>{humanize(selectedPlace.kind)}</dd></div>
            <div><dt>Owner</dt><dd>{associatedFirm?.name || (
              selectedPlace.owner_type && selectedPlace.owner_id != null
                ? `${humanize(selectedPlace.owner_type)} #${selectedPlace.owner_id}`
                : "Not exposed"
            )}</dd></div>
            <div><dt>Region</dt><dd>{selectedPlace.region_id == null ? "Not exposed" : `Region #${selectedPlace.region_id}`}</dd></div>
            <div><dt>Capacity</dt><dd>{selectedPlace.capacity || "Unbounded"}</dd></div>
            <div><dt>Business occupancy</dt><dd>{selectedPlace.businessOccupancy}</dd></div>
            <div><dt>Queue depth</dt><dd>{selectedPlace.queueDepth}</dd></div>
            <div><dt>Queue history</dt><dd>{humanize(selectedPlace.case_status_resolution, "Not applicable")}</dd></div>
          </dl>
          <section className="civic-city__record">
            <header><span>Presence evidence</span><b>tick {tick}</b></header>
            {selectedPlace.occupants?.length ? <dl>
              {selectedPlace.occupants.slice(0, 8).map(occupant => <div key={occupant.agent_id}>
                <dt>Agent #{occupant.agent_id}</dt>
                <dd>{occupant.name || humanize(occupant.role)}</dd>
              </div>)}
            </dl> : selectedPlace.privacyOccupancy > 0
              ? <p>{selectedPlace.privacyOccupancy} occupants are exposed only as a privacy aggregate.</p>
              : <p>No public occupant identities are projected at this tick.</p>}
          </section>
          <section className="civic-city__receipt">
            <header><span>Visual encoding</span><b>derived</b></header>
            <p>In 2.5D, building height derives from exposed capacity, occupancy, and queue magnitude. Shape and height are not canonical world geometry.</p>
          </section>
          <div className="civic-city__lens-actions">
            {placeHref && <Link className="is-primary" to={placeHref}>Open in Live City <span>→</span></Link>}
            {associatedFirm && <button type="button" onClick={() => changeFirmSelection(associatedFirm.id)}>Inspect owning business</button>}
            <span className="civic-city__no-trace">Associations are labelled separately from direct event records.</span>
          </div>
        </> : selected ? <>
          <div className="civic-city__identity">
            <span className={`civic-city__avatar civic-city__avatar--${selected.layer}`}>{initials(selected.name)}</span>
            <div><p>Agent #{selected.id}</p><h3>{selected.name}</h3><span>{humanize(selected.role || selected.occupation || selected.kind)}</span></div>
          </div>
          <div className={`civic-city__activity civic-city__activity--${
            selected.runtimeActivity
              ? selected.activityState
              : selected.transitionEvent
                ? selected.activityState
                : selected.event ? "event" : "assigned"
          }`}>
            <span>{selected.runtimeActivity
              ? "Live runtime telemetry"
              : selected.transitionEvent
                ? "Committed this tick"
                : selected.event ? "Latest committed record" : "Current placement"}</span>
            <strong>{selected.runtimeActivity || selected.transitionEvent
              ? humanize(selected.activityState)
              : selected.event ? humanize(selected.event.kind) : humanize(selected.activityState)}</strong>
            <small>{selected.runtimeActivity
              ? `Tick ${selected.runtimeActivity.tick} · ${selected.runtimeActivity.active_calls} active call${selected.runtimeActivity.active_calls === 1 ? "" : "s"} · ${selected.runtimeActivity.oldest_elapsed_ms}ms observed`
              : selected.event
                ? `Tick ${selected.event.tick} · ${humanize(selected.event.phase)}`
                : `${selected.district} · no recent actor-linked event`}</small>
          </div>
          <dl className="civic-city__facts">
            <div><dt>District</dt><dd>{selected.district}</dd></div>
            <div><dt>Occupation</dt><dd>{humanize(selected.occupation || selected.role)}</dd></div>
            <div><dt>Employer</dt><dd>{employer?.name || (selected.employer_id != null ? `Firm #${selected.employer_id}` : "No employer linked")}</dd></div>
            <div><dt>Effective place</dt><dd>{selected.place_name || selected.district}</dd></div>
            <div><dt>Health</dt><dd>{humanize(selected.health)}</dd></div>
            <div><dt>Compute tier</dt><dd>{humanize(selected.model_tier, "Not exposed")}</dd></div>
            <div><dt>Placement</dt><dd>{humanize(selected.coordinateSource)}</dd></div>
          </dl>
          {selected.event && <section className="civic-city__record">
            <header><span>Event record</span><b>#{selected.event.id}</b></header>
            {eventFacts.length
              ? <dl>{eventFacts.map(([key, value]) => <div key={key}><dt>{humanize(key)}</dt><dd>{String(value)}</dd></div>)}</dl>
              : <p>The committed event exposes no scalar payload fields.</p>}
          </section>}
          {semanticReceipt && <section className="civic-city__receipt">
            <header><span>Semantic receipt</span><b>{semanticReceipt.eventId ? `#${semanticReceipt.eventId}` : "committed"}</b></header>
            <p>
              <strong>{humanize(semanticReceipt.actor?.type)} #{semanticReceipt.actor?.id}</strong>
              <i>→</i>
              <strong>{humanize(semanticReceipt.verb)}</strong>
              <i>→</i>
              <strong>{humanize(semanticReceipt.object?.type)} #{semanticReceipt.object?.id}</strong>
              <i>→</i>
              <strong>{humanize(semanticReceipt.outcome)}</strong>
            </p>
          </section>}
          <div className="civic-city__lens-actions">
            {peopleHref && <Link to={peopleHref}>Open citizen dossier <span>↗</span></Link>}
            {employer && <button type="button" onClick={() => changeFirmSelection(employer.id)}>Inspect employer</button>}
            {traceHref
              ? <Link className="is-primary" to={traceHref}>Trace this event <span>→</span></Link>
              : <span className="civic-city__no-trace">Trace unlocks with an actor-linked event.</span>}
          </div>
        </> : <div className="civic-city__lens-empty">
          <span aria-hidden="true">⌖</span>
          <h3>Select a city mark</h3>
          <p>The lens will show the agent, placement source, and latest committed event without changing simulation state.</p>
        </div>}
        <footer>
          <span><i className={`civic-city__provenance civic-city__provenance--${model.coordinateMode}`} />{coordinateCopy(model.coordinateMode)}</span>
          {lineage && <small>Semantics {lineage.semantics} · projection {lineage.projection} · policy {lineage.policy}</small>}
          {historical && <small>City evidence resolves at tick {tick}; live runtime overlays are disabled.</small>}
          {!historical && selected?.runtimeActivity && <small>Live activity is ephemeral observer telemetry. It is not a thought trace or committed world state.</small>}
          <small>City selection is observer-only. Ledger and replay truth remain immutable.</small>
        </footer>
      </aside>
    </div>

    <section className="civic-city__activity-dock" aria-label="Live agent activity dock">
      <header>
        <div><span>Agent activity</span><strong>{historical ? `Tick ${tick}` : "Live operations"}</strong></div>
        <small>{historical
          ? "Runtime overlays are disabled for historical views."
          : `${liveAgents.length} live · ${changedAgents.length} changed this tick`}</small>
      </header>
      <div className="civic-city__activity-dock-items">
        {[...liveAgents, ...changedAgents].slice(0, 12).map(agent => <button
          key={`activity-${agent.id}`}
          type="button"
          className={`is-${agent.activityState}`}
          onClick={() => changeSelection(agent.id)}
          aria-label={`Select ${agent.name}, ${humanize(agent.activityState)}`}
        >
          <i aria-hidden="true" />
          <span><strong>{agent.name}</strong><small>{humanize(agent.activityState)} · Agent #{agent.id}</small></span>
          {agent.runtimeActivity?.active_calls > 1 && <b>{agent.runtimeActivity.active_calls}</b>}
        </button>)}
        {!liveAgents.length && !changedAgents.length && <p>
          <strong>No agents are active at this observation.</strong>
          <span>Queued and thinking calls appear here; committed outcomes remain in the evidence lens.</span>
        </p>}
      </div>
    </section>

    <dl className="civic-city__instruments" aria-label="City instrumentation">
      <div><dt>Active marks</dt><dd><span className="civic-city__instrument-value">{model.counts.active}</span><small>live or changed at selected tick</small></dd></div>
      <div><dt>Operating firms</dt><dd><span className="civic-city__instrument-value">{model.counts.firms}</span><small>canonical firm endpoint</small></dd></div>
      <div><dt>Real places</dt><dd><span className="civic-city__instrument-value">{model.counts.places}</span><small>stable city coordinates</small></dd></div>
      <div><dt>Construction</dt><dd><span className="civic-city__instrument-value">{model.counts.construction}</span><small>exact stages from stored work</small></dd></div>
      <div><dt>Permit queue</dt><dd><span className="civic-city__instrument-value">{model.civic?.enabled ? model.counts.queue : "—"}</span><small>{model.civic?.queue ? `oldest ${model.civic.queue.oldest_age_ticks} ticks` : "civic service disabled"}</small></dd></div>
      <div><dt>Office load</dt><dd><span className="civic-city__instrument-value">{busiestOffice ? `${busiestOffice.occupancy}/${busiestOffice.capacity}` : "—"}</span><small>{busiestOffice ? `${busiestOffice.name} · q${busiestOffice.queue_depth}` : "no licensing office"}</small></dd></div>
      <div><dt>AI inference</dt><dd><span className="civic-city__instrument-value">{providerActive == null ? "—" : `${providerActive}/${providerCapacity}`}</span><small>{runtime?.global?.queue_depth == null ? "runtime telemetry unavailable" : `${runtime.global.queue_depth} requests queued`}</small></dd></div>
      <div><dt>World time</dt><dd><span className="civic-city__instrument-value">{historical ? `t${tick}` : runIsActive ? "Live" : "Current"}</span><small>{tick === "live" ? humanize(phase, "between phases") : `tick ${tick} · ${humanize(phase, "between phases")}`}</small></dd></div>
      <div><dt>Layout proof</dt><dd><span className="civic-city__instrument-value">{humanize(model.coordinateMode)}</span><small>{model.counts.assigned} role assignments</small></dd></div>
    </dl>
  </section>;
}

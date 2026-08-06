/*
THESIS: A daylit civic weather room where the city itself is the primary operating instrument.
OWN-WORLD: Municipal survey plates, plotted districts, acetate evidence layers, and named signal inks.
STORY: Orient to the run, find working agents, select a city mark, then follow its committed evidence.
FIRST VIEWPORT: Stable civic navigation frames a two-thirds live atlas and a one-third evidence lens.
FORM: Civic Weather Room, grounded direction position 4; surveyed evidence-transect staging; seed 5d725ec9.
*/
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
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

function statusCopy(status, connected, tick, historical) {
  if (!connected) return "Connection unavailable";
  if (historical) return `Historical tick ${tick}`;
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
  const activeLayer = observerState?.layer ?? localActiveLayer;
  const query = observerState?.q ?? localQuery;
  const activeOnly = observerState?.activeOnly ?? localActiveOnly;
  const selectedId = observerState?.agent ?? localSelectedId;
  const lensRef = useRef(null);
  const model = useMemo(
    () => deriveCityModel({ agents, firms, events, map, civic }),
    [agents, firms, events, map, civic],
  );
  const visibleAgents = filterCityAgents(model.agents, {
    layer: activeLayer,
    q: query,
    activeOnly,
  });
  const selected = visibleAgents.find(agent => String(agent.id) === String(selectedId))
    || visibleAgents.find(agent => agent.event)
    || visibleAgents[0]
    || null;
  const selectedIndex = selected
    ? visibleAgents.findIndex(agent => String(agent.id) === String(selected.id))
    : -1;
  useEffect(() => {
    if (!observerState || !onObserverStateChange || loading) return;
    const resolvedId = selected ? Number(selected.id) : null;
    if (observerState.agent !== resolvedId) {
      onObserverStateChange({ agent: resolvedId }, { replace: true });
    }
  }, [loading, observerState, onObserverStateChange, selected]);
  const employer = selected?.employer_id == null
    ? null
    : model.firms.find(firm => String(firm.id) === String(selected.employer_id));
  const eventFacts = payloadFacts(selected?.event?.payload);
  const semanticReceipt = semanticReceiptForEvent(selected?.event, model.receipts);
  const busiestOffice = [...(model.civic?.offices || [])]
    .sort((left, right) => Number(right.occupancy) - Number(left.occupancy))[0];
  const commonParams = new URLSearchParams();
  if (observerState?.fork) commonParams.set("fork", observerState.fork);
  if (tick !== "live") commonParams.set("tick", tick);
  if (observerState?.event) commonParams.set("event", String(observerState.event));
  const commonSuffix = commonParams.toString() ? `?${commonParams}` : "";
  const peopleHref = selected && runId
    ? `/runs/${encodeURIComponent(runId)}/people/${selected.id}${commonSuffix}`
    : null;
  const traceParams = new URLSearchParams(commonParams);
  if (selected?.event) traceParams.set("event", String(selected.event.id));
  const traceHref = selected?.event && runId
    ? `/runs/${encodeURIComponent(runId)}/investigations?${traceParams}`
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

  const moveSelection = direction => {
    if (!visibleAgents.length) return;
    const nextIndex = (Math.max(0, selectedIndex) + direction + visibleAgents.length) % visibleAgents.length;
    const nextId = visibleAgents[nextIndex].id;
    if (onObserverStateChange) onObserverStateChange({ agent: nextId });
    else setLocalSelectedId(nextId);
  };
  const changeObserverFilter = (update, options) => {
    onObserverStateChange(resolveCityFilterPatch(model.agents, {
      layer: activeLayer,
      q: query,
      activeOnly,
      agent: selectedId,
    }, update), options);
  };
  const changeLayer = value => {
    if (onObserverStateChange) changeObserverFilter({ layer: value });
    else setLocalActiveLayer(value);
  };
  const changeQuery = value => {
    if (onObserverStateChange) changeObserverFilter({ q: value }, { replace: true });
    else setLocalQuery(value);
  };
  const changeActiveOnly = value => {
    if (onObserverStateChange) changeObserverFilter({ activeOnly: value });
    else setLocalActiveOnly(value);
  };
  const changeSelection = value => {
    if (onObserverStateChange) onObserverStateChange({ agent: value });
    else setLocalSelectedId(value);
  };
  const resetView = () => {
    if (onObserverStateChange) {
      onObserverStateChange({ q: null, layer: null, activeOnly: false, agent: null });
      return;
    }
    setLocalQuery("");
    setLocalActiveLayer("all");
    setLocalActiveOnly(false);
    setLocalSelectedId(null);
  };
  const openMobileLens = () => {
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    lensRef.current?.scrollIntoView({
      behavior: reduceMotion ? "auto" : "smooth",
      block: "start",
    });
  };
  const runIsActive = ACTIVE_RUN_STATUSES.has(String(status).toLowerCase());
  const animateLiveActivity = tick === "live" && connected && !historical && runIsActive;

  return <section
    className={`civic-city civic-city--${variant}${model.agents.length > 72 ? " civic-city--dense" : ""}`}
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
        <div><dt>Active marks</dt><dd>{model.counts.active} / {model.counts.agents}</dd></div>
        <div><dt>Permit queue</dt><dd>{model.civic?.enabled ? model.counts.queue : "—"}</dd></div>
      </dl>
    </header>

    <div className="civic-city__controls">
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
        <span>Committed events only</span>
      </label>
    </div>

    <div className="civic-city__workfield">
      <div className="civic-city__atlas">
        <div className="civic-city__map-field">
          <div className="civic-city__atlas-meta">
            <span className={`civic-city__source civic-city__source--${model.coordinateMode}`}>{coordinateCopy(model.coordinateMode)}</span>
            <span>{visibleAgents.length} marks visible</span>
          </div>
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
              className={selected.event ? "civic-city__transect is-active" : "civic-city__transect"}
              d={`M${selected.x} ${selected.y} H92`}
              markerEnd={selected.event ? `url(#civic-arrow-${variant})` : undefined}
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

        {model.firms.map(firm => <div
          key={`firm-${firm.id}`}
          className={`civic-city__firm civic-city__firm--${firm.layer}`}
          style={{ left: `${firm.x}%`, top: `${firm.y}%` }}
          title={`${firm.name || "Firm"} · ${humanize(firm.sector || firm.status)}`}
          aria-hidden="true"
        >
          <span>{String(firm.name || "Firm").replace(/\s+(co|company|inc)\b.*$/i, "").slice(0, 16)}</span>
        </div>)}

        {model.places.map(place => <div
          key={`place-${place.id}`}
          className={[
            "civic-city__place",
            place.kind === "licensing_office" ? "is-permit-office" : "",
          ].filter(Boolean).join(" ")}
          style={{ left: `${place.x}%`, top: `${place.y}%` }}
          title={`${place.name} · ${humanize(place.kind)} · ${place.businessOccupancy}/${place.capacity || "∞"} present${place.queueDepth ? ` · queue ${place.queueDepth}` : ""}`}
          aria-hidden="true"
        >
          <i />
          {place.kind === "licensing_office" && <span>
            Permit office · {place.businessOccupancy}/{place.capacity} · q{place.queueDepth}
          </span>}
        </div>)}

        <div className="civic-city__agent-layer">
          {visibleAgents.map(agent => <button
            key={agent.id}
            type="button"
            className={[
              "civic-city__agent",
              `civic-city__agent--${agent.layer}`,
              agent.event ? "has-event" : "",
              selected && String(selected.id) === String(agent.id) ? "is-selected" : "",
            ].filter(Boolean).join(" ")}
            style={{ left: `${agent.x}%`, top: `${agent.y}%` }}
            onClick={() => changeSelection(agent.id)}
            aria-pressed={selected && String(selected.id) === String(agent.id)}
            aria-label={`${agent.name}, ${humanize(agent.role || agent.occupation || agent.kind)}, ${agent.event ? `committed ${humanize(agent.event.kind)} event` : agent.activityState}`}
          >
            <span>{initials(agent.name)}</span>
          </button>)}
        </div>

        {error && <div className="civic-city__empty" role="alert">
          <strong>City evidence is temporarily unavailable.</strong>
          <span>{error}</span>
        </div>}
        {!loading && !error && !visibleAgents.length && <div className="civic-city__empty">
          <strong>No city marks match this view.</strong>
          <span>Clear the search or show all activity layers.</span>
          <button type="button" onClick={resetView}>Reset city view</button>
        </div>}
        {loading && !error && <div className="civic-city__empty" aria-live="polite">
          <strong>Surveying the current run…</strong>
          <span>Agent and event marks will appear from canonical APIs.</span>
        </div>}

        <div className="civic-city__legend" role="group" aria-label="City map legend">
          <span><i className="has-event" />Committed event</span>
          <span><i />Assigned or resident</span>
          <span><b />Firm footprint</span>
        </div>
        <div className="civic-city__coordinates" aria-hidden="true">
          <span>GRID A-01</span><span>FIELD E-23</span><span>AE / {String(tick).padStart(4, "0")}</span>
        </div>
          {selected && <button
            type="button"
            className="civic-city__mobile-peek"
            onClick={openMobileLens}
          >
            <span><b>{selected.name}</b><small>{selected.event ? humanize(selected.event.kind) : humanize(selected.activityState)}</small></span>
            <strong>Open evidence ↓</strong>
          </button>}
        </div>
      </div>

      <aside ref={lensRef} className="civic-city__lens" aria-live="polite" aria-label="Selected agent evidence">
        <header>
          <div><p>Evidence lens</p><span>Observed + derived fields</span></div>
          <div className="civic-city__lens-nav">
            <button type="button" onClick={() => moveSelection(-1)} disabled={visibleAgents.length < 2} aria-label="Previous visible agent">←</button>
            <button type="button" onClick={() => moveSelection(1)} disabled={visibleAgents.length < 2} aria-label="Next visible agent">→</button>
          </div>
        </header>
        {selected ? <>
          <div className="civic-city__identity">
            <span className={`civic-city__avatar civic-city__avatar--${selected.layer}`}>{initials(selected.name)}</span>
            <div><p>Agent #{selected.id}</p><h3>{selected.name}</h3><span>{humanize(selected.role || selected.occupation || selected.kind)}</span></div>
          </div>
          <div className={`civic-city__activity civic-city__activity--${selected.event ? "event" : "assigned"}`}>
            <span>{selected.event ? "Committed activity" : "Current placement"}</span>
            <strong>{selected.event ? humanize(selected.event.kind) : humanize(selected.activityState)}</strong>
            <small>{selected.event ? `Tick ${selected.event.tick} · ${humanize(selected.event.phase)}` : `${selected.district} · no recent actor-linked event`}</small>
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
          {historical && <small>Events resolve at tick {tick}; the entity roster comes from the current agent and firm endpoints.</small>}
          <small>City selection is observer-only. Ledger and replay truth remain immutable.</small>
        </footer>
      </aside>
    </div>

    <dl className="civic-city__instruments" aria-label="City instrumentation">
      <div><dt>Actor-linked marks</dt><dd><span className="civic-city__instrument-value">{model.counts.active}</span><small>agents in latest event sample</small></dd></div>
      <div><dt>Operating firms</dt><dd><span className="civic-city__instrument-value">{model.counts.firms}</span><small>canonical firm endpoint</small></dd></div>
      <div><dt>Real places</dt><dd><span className="civic-city__instrument-value">{model.counts.places}</span><small>stable city coordinates</small></dd></div>
      <div><dt>Permit queue</dt><dd><span className="civic-city__instrument-value">{model.civic?.enabled ? model.counts.queue : "—"}</span><small>{model.civic?.queue ? `oldest ${model.civic.queue.oldest_age_ticks} ticks` : "civic service disabled"}</small></dd></div>
      <div><dt>Office load</dt><dd><span className="civic-city__instrument-value">{busiestOffice ? `${busiestOffice.occupancy}/${busiestOffice.capacity}` : "—"}</span><small>{busiestOffice ? `${busiestOffice.name} · q${busiestOffice.queue_depth}` : "no licensing office"}</small></dd></div>
      <div><dt>AI inference</dt><dd><span className="civic-city__instrument-value">{providerActive == null ? "—" : `${providerActive}/${providerCapacity}`}</span><small>{runtime?.global?.queue_depth == null ? "runtime telemetry unavailable" : `${runtime.global.queue_depth} requests queued`}</small></dd></div>
      <div><dt>World time</dt><dd><span className="civic-city__instrument-value">{historical ? `t${tick}` : runIsActive ? "Live" : "Current"}</span><small>{tick === "live" ? humanize(phase, "between phases") : `tick ${tick} · ${humanize(phase, "between phases")}`}</small></dd></div>
      <div><dt>Layout proof</dt><dd><span className="civic-city__instrument-value">{humanize(model.coordinateMode)}</span><small>{model.counts.assigned} role assignments</small></dd></div>
    </dl>
  </section>;
}

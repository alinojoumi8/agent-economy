import { Link, useSearchParams } from "react-router";
import { CivicCity } from "../components/CivicCity";
import { normalizeWorldWorkspace } from "./worldWorkspaceModel.js";
import {
  validatedSelectedId,
  WorkspaceHeader,
  WorkspaceState,
  workspaceUrl,
  useWorkspaceProjection,
} from "./workspaceShared";

type WorldRow = {
  id: number;
  name?: string;
  region_id?: number | null;
  region_name?: string | null;
  currency_code?: string | null;
  kind?: string | null;
  capacity?: number | null;
  active?: boolean;
  x?: number;
  y?: number;
  [key: string]: unknown;
};

type WorldFlow = WorldRow & {
  kind: "migration" | "trade" | string;
  origin_region_id: number;
  destination_region_id: number;
};

type WorldProjection = {
  enabled?: boolean;
  regions?: WorldRow[];
  agents?: WorldRow[];
  organizations?: WorldRow[];
  places?: WorldRow[];
  presence?: WorldRow[];
  flows?: WorldFlow[];
};

function display(value: unknown, fallback = "Not exposed") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value).replaceAll("_", " ");
}

export function WorldWorkspace() {
  const projection = useWorkspaceProjection<WorldProjection>("workspace.world", "/api/v2/workspaces/world");
  const [searchParams, setSearchParams] = useSearchParams();
  const model = normalizeWorldWorkspace(projection.data || {});
  const selectedRegionId = validatedSelectedId(searchParams.get("region"));
  const selectedPlaceId = validatedSelectedId(searchParams.get("place"));
  const selectedRegion = model.regions.find(region => Number(region.id) === selectedRegionId) || null;
  const selectedPlace = model.places.find(place => Number(place.id) === selectedPlaceId) || null;

  const select = (key: "region" | "place", rawValue: string) => {
    const next = new URLSearchParams(searchParams);
    const value = validatedSelectedId(rawValue);
    if (value == null) next.delete(key);
    else next.set(key, String(value));
    if (key === "region") next.delete("place");
    if (key === "place") next.delete("region");
    setSearchParams(next);
  };
  const route = (path: string) => workspaceUrl(projection.runId, path, projection.observerState);
  const envelope = projection.envelope;

  return <section className="world-os-world-workspace">
    <WorkspaceHeader
      title="World"
      kicker="Bounded geographic projection"
      sourceLabel="World workspace committed projection"
      envelope={envelope}
      actions={<div className="world-os-world-controls" aria-label="World selection controls">
        <label>Region
          <select value={selectedRegion?.id ?? ""} onChange={event => select("region", event.target.value)}>
            <option value="">All regions</option>
            {model.regions.map(region => <option key={region.id} value={region.id}>{display(region.name, `Region ${region.id}`)}</option>)}
          </select>
        </label>
        <label>Place
          <select value={selectedPlace?.id ?? ""} onChange={event => select("place", event.target.value)}>
            <option value="">All places</option>
            {model.places.map(place => <option key={place.id} value={place.id}>{display(place.name, `Place ${place.id}`)}</option>)}
          </select>
        </label>
      </div>}
    />
    <WorkspaceState loading={projection.loading} error={projection.error}>
      {!model.enabled && <p className="world-os-disabled-callout">Geographic simulation data is disabled for this run.</p>}
      <dl className="world-os-summary-strip" aria-label="World projection summary">
        <div><dt>Population</dt><dd>{model.summary.population}</dd></div>
        <div><dt>Active organizations</dt><dd>{model.summary.activeOrganizations}</dd></div>
        <div><dt>Currencies</dt><dd>{model.summary.currencies.join(", ") || "—"}</dd></div>
        <div><dt>Migration flows</dt><dd>{model.summary.migrationCount}</dd></div>
        <div><dt>Trade flows</dt><dd>{model.summary.tradeCount}</dd></div>
      </dl>

      <CivicCity
        agents={model.agents}
        firms={model.organizations}
        events={[]}
        map={model}
        civic={null}
        runtime={null}
        runId={projection.runId}
        tick={projection.observerState.tick}
        connected={projection.transport.status === "live"}
        historical={projection.observerState.tick !== "live"}
        lineage={envelope ? {
          semantics: envelope.semantics_version,
          projection: envelope.projection_version,
          policy: envelope.policy_version,
        } : null}
        variant="world-os-world"
        observerState={projection.observerState}
        onObserverStateChange={projection.setObserverState}
      />

      <div className="world-os-world-detail-grid">
        <article className="world-os-workspace-card world-os-world-inspector" aria-live="polite">
          <header><div><p className="world-os-kicker">Selection inspector</p><h3>{selectedPlace ? "Place" : selectedRegion ? "Region" : "World extent"}</h3></div></header>
          {selectedPlace ? <dl>
            <div><dt>Name</dt><dd>{display(selectedPlace.name, `Place ${selectedPlace.id}`)}</dd></div>
            <div><dt>Kind</dt><dd>{display(selectedPlace.kind)}</dd></div>
            <div><dt>Region</dt><dd>{display(selectedPlace.region_name, selectedPlace.region_id == null ? undefined : `Region ${selectedPlace.region_id}`)}</dd></div>
            <div><dt>Capacity</dt><dd>{display(selectedPlace.capacity)}</dd></div>
          </dl> : selectedRegion ? <dl>
            <div><dt>Name</dt><dd>{display(selectedRegion.name, `Region ${selectedRegion.id}`)}</dd></div>
            <div><dt>Currency</dt><dd>{display(selectedRegion.currency_code)}</dd></div>
            <div><dt>Population target</dt><dd>{display(selectedRegion.population_target)}</dd></div>
            <div><dt>Ruleset</dt><dd>{display(selectedRegion.legal_ruleset)}</dd></div>
          </dl> : <p>Select a validated region or place to inspect its committed public fields.</p>}
        </article>
        <nav className="world-os-workspace-card world-os-world-links" aria-label="Related World workspaces">
          <p className="world-os-kicker">Follow the evidence</p>
          <Link to={route("people")}>People <span>↗</span></Link>
          <Link to={route("organizations")}>Organizations <span>↗</span></Link>
          <Link to={route("investigations")}>Investigations <span>↗</span></Link>
        </nav>
      </div>
    </WorkspaceState>
  </section>;
}

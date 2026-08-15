import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router";
import { projectionApi, workspaceApi } from "../app/api";
import { patchObserverViewState, projectionScopeParams } from "../app/observerViewState";
import { CivicCity } from "../components/CivicCity";
import { titleCase } from "../ui";
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
  construction_projects?: Array<{
    project_id: number | string;
    name: string;
    target_place_type: string;
    status: string;
    stage: string | null;
    region?: { id: number; name: string } | null;
    site?: { x: number; y: number } | null;
    requirements?: { funding_cents: number; work_units: number };
    contributed?: { funding_cents: number; work_units: number };
    milestone_count?: number;
    updated_tick?: number;
    privacy?: string;
    aggregate_count?: number;
    place_id?: number | null;
  }>;
  presence?: WorldRow[];
  flows?: WorldFlow[];
};

/* A run in one of these states emits nothing further, so polling it is waste. */
const TERMINAL_RUN_STATUSES = new Set(
  ["completed", "failed", "finished", "halted", "stopped"]);

type ProviderLane = {
  provider: string;
  capacity: number;
  in_flight: number;
  queue_depth: number;
  cooldown_remaining_s: number;
  p50_queue_ms: number | null;
  p95_response_ms: number | null;
  failures: number;
  rate_limits: number;
  fallbacks: number;
};
type ProviderRuntime = {
  live_only: boolean;
  global: {
    capacity: number; in_flight: number; queue_depth: number; peak_in_flight: number;
  };
  simulated_days: { p50_wall_ms: number | null };
  providers: ProviderLane[];
};

function display(value: unknown, fallback = "Not exposed") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value).replaceAll("_", " ");
}

export function WorldWorkspace() {
  const projection = useWorkspaceProjection<WorldProjection>("workspace.world", "/api/v2/workspaces/world");
  const [searchParams, setSearchParams] = useSearchParams();
  /*
   * The civic panel used to live in Overview and was fed there. Moving it here
   * carried the component but not its sources, so it lost the things that only
   * data can supply: the run status line, the empty and error states, the
   * evidence lens and the live inference fabric. They are restored at the panel's
   * new home rather than by moving it back — see the workspace-projection query
   * above, which answers a different question (the atlas) and cannot stand in
   * for these.
   */
  const { observerState, runId } = projection;
  const tick = observerState.tick;
  const overview = useQuery({
    queryKey: ["world-os", runId, observerState.fork, "world-city-overview", tick],
    queryFn: ({ signal }) => {
      const params = projectionScopeParams(observerState);
      params.set("domains", "summary,events");
      return projectionApi<{
        summary?: { status?: string; phase?: string };
        events?: { items?: unknown[] };
      }>(`/api/v2/snapshot?${params}`, signal);
    },
    retry: false,
  });
  const runStatus = String(overview.data?.data.summary?.status || "").toLowerCase();
  /* A finished or halted run has no more telemetry to poll for. */
  const pollCurrentRun = tick === "live" && !TERMINAL_RUN_STATUSES.has(runStatus);
  const runtime = useQuery({
    queryKey: ["llm-runtime", runId],
    queryFn: ({ signal }) => workspaceApi<ProviderRuntime>("/api/llm/runtime", { signal }),
    retry: false,
    refetchInterval: () => (pollCurrentRun ? 2000 : false),
  });
  const terminalRun = TERMINAL_RUN_STATUSES.has(runStatus);
  const city = useQuery({
    queryKey: ["world-os", runId, observerState.fork, "world-city", tick, observerState.population],
    queryFn: async ({ signal }) => {
      const mapParams = projectionScopeParams(observerState);
      mapParams.set("layers", "regions,agents,organizations,places,presence");
      mapParams.set("population", observerState.population);
      const civicParams = projectionScopeParams(observerState);
      const [mapEnvelope, civicEnvelope] = await Promise.all([
        projectionApi<{ agents?: unknown[]; organizations?: unknown[] }>(
          `/api/v2/world-map?${mapParams}`, signal),
        projectionApi<unknown>(`/api/v2/civic/summary?${civicParams}`, signal),
      ]);
      return {
        agents: mapEnvelope.data.agents || [],
        firms: mapEnvelope.data.organizations || [],
        map: mapEnvelope.data,
        civic: civicEnvelope.data,
      };
    },
    retry: false,
    refetchInterval: () => (pollCurrentRun ? 3000 : false),
  });
  const model = normalizeWorldWorkspace(projection.data || {});
  const selectedRegionId = validatedSelectedId(searchParams.get("region"));
  const selectedPlaceId = projection.observerState.place;
  const selectedProjectId = projection.observerState.project;
  const selectedRegion = model.regions.find(region => Number(region.id) === selectedRegionId) || null;
  const selectedPlace = model.places.find(place => Number(place.id) === selectedPlaceId) || null;
  const selectedProject = model.constructionProjects.find(
    project => String(project.id) === String(selectedProjectId),
  ) || null;

  useEffect(() => {
    if (projection.loading) return;
    const next = new URLSearchParams(searchParams);
    if (selectedProject) next.delete("region");
    else if (selectedProjectId != null) {
      const cleared = patchObserverViewState(next, { project: null });
      setSearchParams(cleared, { replace: true });
      return;
    } else if (selectedPlace) next.delete("region");
    else if (selectedPlaceId != null) {
      const cleared = patchObserverViewState(next, { place: null });
      setSearchParams(cleared, { replace: true });
      return;
    }
    if (selectedRegionId != null && !selectedRegion) next.delete("region");
    if (next.toString() !== searchParams.toString()) {
      setSearchParams(next, { replace: true });
    }
  }, [
    projection.loading,
    searchParams,
    selectedPlace,
    selectedPlaceId,
    selectedProject,
    selectedProjectId,
    selectedRegion,
    selectedRegionId,
    setSearchParams,
  ]);

  const select = (key: "region" | "place" | "project", rawValue: string) => {
    if (key === "project") {
      const next = patchObserverViewState(searchParams, {
        project: rawValue || null,
      });
      next.delete("region");
      setSearchParams(next);
      return;
    }
    const value = validatedSelectedId(rawValue);
    const next = key === "place"
      ? patchObserverViewState(searchParams, { place: value })
      : new URLSearchParams(searchParams);
    if (key === "region") {
      if (value == null) next.delete("region");
      else next.set("region", String(value));
      next.delete("place");
      next.delete("project");
      next.delete("agent");
    }
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
        <label>Construction project
          <select value={selectedProject?.id ?? ""} onChange={event => select("project", event.target.value)}>
            <option value="">All projects</option>
            {model.constructionProjects.map(project => <option key={project.id} value={project.id}>
              {display(project.name, `Project ${project.id}`)} · {display(project.stage || project.status)}
            </option>)}
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
        <div><dt>Construction projects</dt><dd>{model.summary.constructionCount}</dd></div>
      </dl>

      <CivicCity
        agents={city.data?.agents}
        firms={city.data?.firms}
        events={overview.data?.data.events?.items || []}
        /* No fallback to the atlas projection: when the city query fails the
           panel must say so, not quietly draw a different dataset's people. */
        map={city.data?.map}
        civic={city.data?.civic ?? null}
        runtime={runtime.data ?? null}
        runId={projection.runId}
        tick={projection.observerState.tick}
        phase={overview.data?.data.summary?.phase}
        status={overview.data?.data.summary?.status}
        loading={city.isLoading}
        error={city.error instanceof Error ? city.error.message : ""}
        connected={projection.transport.status === "live"}
        historical={projection.observerState.tick !== "live"}
        lineage={envelope ? {
          semantics: envelope.semantics_version,
          projection: envelope.projection_version,
          policy: envelope.policy_version,
        } : null}
        /*
         * "world-os", not "world-os-world". The variant string is what becomes
         * the modifier class, and civic-weather-room.css only ever defined
         * .civic-city--world-os. The extra word meant the atlas matched none of
         * its own dark treatment and fell back to the light civic default, which
         * is why "Civic Forum" was white-on-paper at 1.25:1 inside a dark app.
         */
        variant="world-os"
        observerState={projection.observerState}
        onObserverStateChange={projection.setObserverState}
      />

      {/*
        * Provider lanes — the inference fabric actually answering for this
        * world. It sat beside the civic panel in Overview and was dropped when
        * that surface was rewritten, taking the only readout of who is thinking
        * and how hard with it. Restored beside the panel it belongs to.
        *
        * Scripted and mock lanes are filtered out on purpose: they are not a
        * provider under load, and showing them as one would overstate the fabric.
        */}
      <section
        className="world-os-provider-deck"
        aria-label={tick === "live" && !terminalRun ? "Live AI provider lanes" : "Current AI provider lanes"}
      >
        <header>
          <div>
            <p className="world-os-kicker">{
              tick !== "live" ? "Current inference fabric"
                : terminalRun ? "Final inference fabric" : "Live inference fabric"
            }</p>
            <h3>Provider lanes</h3>
          </div>
          {runtime.data && <div className="world-os-provider-global">
            <span>{runtime.data.live_only ? "Live only" : "Mixed mode"}</span>
            <strong>{runtime.data.global.in_flight}/{runtime.data.global.capacity}</strong>
            <small>
              {runtime.data.global.queue_depth} queued · peak {runtime.data.global.peak_in_flight}
              {runtime.data.simulated_days?.p50_wall_ms == null
                ? ""
                : ` · day p50 ${(runtime.data.simulated_days.p50_wall_ms / 1000).toFixed(1)}s`}
            </small>
          </div>}
        </header>
        {runtime.error && <p className="world-os-policy-note">Runtime telemetry is temporarily unavailable.</p>}
        {tick !== "live" && <p className="world-os-policy-note">
          Provider capacity is current runtime telemetry, not a historical reconstruction.
        </p>}
        <div className="world-os-provider-lanes">
          {(runtime.data?.providers || [])
            .filter(lane => !["scripted", "mock"].includes(lane.provider))
            .map(lane => {
              const utilization = Math.min(
                100, Math.round((lane.in_flight / Math.max(1, lane.capacity)) * 100));
              const state = lane.cooldown_remaining_s > 0 ? "cooldown"
                : lane.queue_depth > 0 ? "queued"
                  : lane.in_flight > 0 ? "active" : "ready";
              return <article
                key={lane.provider}
                className={`world-os-provider-lane world-os-provider-lane--${state}`}
              >
                <div className="world-os-provider-lane-head">
                  <span className="world-os-live-dot" />
                  <strong>{titleCase(lane.provider)}</strong>
                  <em>{state}</em>
                </div>
                <div className="world-os-provider-capacity"><span style={{ width: `${utilization}%` }} /></div>
                <dl>
                  <div><dt>Active</dt><dd>{lane.in_flight}/{lane.capacity}</dd></div>
                  <div><dt>Queued</dt><dd>{lane.queue_depth}</dd></div>
                  <div><dt>p50 wait</dt><dd>{lane.p50_queue_ms == null ? "—" : `${Math.round(lane.p50_queue_ms)}ms`}</dd></div>
                  <div><dt>p95 response</dt><dd>{lane.p95_response_ms == null ? "—" : `${(lane.p95_response_ms / 1000).toFixed(1)}s`}</dd></div>
                </dl>
                <small>
                  {lane.failures} failures · {lane.rate_limits} rate limits
                  · {lane.fallbacks} fallback attempts
                </small>
              </article>;
            })}
          {runtime.isLoading && <div className="world-os-provider-loading">Loading live provider capacity…</div>}
        </div>
      </section>

      <div className="world-os-world-detail-grid">
        <article className="world-os-workspace-card world-os-world-inspector" aria-live="polite">
          <header><div><p className="world-os-kicker">Selection inspector</p><h3>{selectedProject ? "Construction project" : selectedPlace ? "Place" : selectedRegion ? "Region" : "World extent"}</h3></div></header>
          {selectedProject ? <dl>
            <div><dt>Name</dt><dd>{display(selectedProject.name, `Project ${selectedProject.id}`)}</dd></div>
            <div><dt>Target</dt><dd>{display(selectedProject.target_place_type)}</dd></div>
            <div><dt>Status</dt><dd>{display(selectedProject.status)}</dd></div>
            <div><dt>Stage</dt><dd>{display(selectedProject.stage, selectedProject.status === "completed" ? "completed" : "site")}</dd></div>
            <div><dt>Region</dt><dd>{display(selectedProject.region?.name, selectedProject.region?.id == null ? undefined : `Region ${selectedProject.region.id}`)}</dd></div>
            <div><dt>Funding</dt><dd>{Number(selectedProject.contributed?.funding_cents || 0)}/{Number(selectedProject.requirements?.funding_cents || 0)} cents</dd></div>
            <div><dt>Work</dt><dd>{Number(selectedProject.contributed?.work_units || 0)}/{Number(selectedProject.requirements?.work_units || 0)} units</dd></div>
            <div><dt>Milestones</dt><dd>{Number(selectedProject.milestone_count || 0)}</dd></div>
            <div><dt>Privacy</dt><dd>{selectedProject.privacy === "aggregated_private" ? "Private homes aggregated; owners and exact sites withheld" : "Public or policy-authorized site"}</dd></div>
          </dl> : selectedPlace ? <dl>
            <div><dt>Name</dt><dd>{display(selectedPlace.name, `Place ${selectedPlace.id}`)}</dd></div>
            <div><dt>Kind</dt><dd>{display(selectedPlace.kind)}</dd></div>
            <div><dt>Region</dt><dd>{display(selectedPlace.region_name, selectedPlace.region_id == null ? undefined : `Region ${selectedPlace.region_id}`)}</dd></div>
            <div><dt>Capacity</dt><dd>{display(selectedPlace.capacity)}</dd></div>
          </dl> : selectedRegion ? <dl>
            <div><dt>Name</dt><dd>{display(selectedRegion.name, `Region ${selectedRegion.id}`)}</dd></div>
            <div><dt>Currency</dt><dd>{display(selectedRegion.currency_code)}</dd></div>
            <div><dt>Population target</dt><dd>{display(selectedRegion.population_target)}</dd></div>
            <div><dt>Ruleset</dt><dd>{display(selectedRegion.legal_ruleset)}</dd></div>
          </dl> : <p>Select a validated region, place, or construction project to inspect its committed public fields.</p>}
        </article>
        <nav className="world-os-workspace-card world-os-world-links" aria-label="Related World workspaces">
          <p className="world-os-kicker">Follow the evidence</p>
          <Link to={route("people")}>Living Agents <span>↗</span></Link>
          <Link to={route("organizations")}>Organizations <span>↗</span></Link>
          <Link to={route("investigations")}>Investigations <span>↗</span></Link>
        </nav>
      </div>
    </WorkspaceState>
  </section>;
}

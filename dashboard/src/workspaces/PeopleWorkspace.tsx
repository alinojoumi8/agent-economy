import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { projectionApi } from "../app/api";
import {
  commonObserverParamsFromState,
  projectionScopeParams,
  useObserverViewState,
} from "../app/observerViewState";
import {
  FreshnessBadge,
  useWorkspaceOutletContext,
} from "../components/FreshnessBadge";
import {
  ConstructionStageArt,
  ConstructionStoryboard,
  normalizeConstructionStage,
} from "../components/ConstructionStoryboard";
import { LivingAgentPortrait } from "../components/LivingAgentPortrait";

type EvidenceRef = { kind: string; id: number | string; tick: number };
type Region = { id: number; name: string };
type VisiblePlace = {
  visibility: "public" | "region_only";
  id?: number;
  name?: string;
  kind?: string;
  region: Region | null;
};
type RuntimeState = {
  state: string;
  active_calls: number;
  tick: number | null;
  oldest_elapsed_ms: number | null;
};
type Skill = {
  skill_key: string;
  level: number;
  xp: number;
  last_practiced_tick: number;
  milestone_count: number;
  source: string;
  evidence_ref: EvidenceRef;
};
type Employment = {
  id: number;
  firm_id: number;
  firm_name: string;
  title: string | null;
  wage_cents: number;
  start_tick: number;
};
type ComputePlan = {
  tier: string;
  payer_type: string;
  price_cents: number;
  effective_tick: number | null;
  expiry_tick: number | null;
  evidence_ref: EvidenceRef | null;
};
type LivingAgent = {
  id: number;
  name: string;
  kind: string;
  role: string | null;
  occupation: string | null;
  population_tier: string;
  arrived_tick: number;
  died_tick: number | null;
  alive: boolean;
  region: Region | null;
  balance_cents: number;
  employment: Employment | null;
  compute: ComputePlan;
  skills: Skill[];
  residence: VisiblePlace | null;
  workplace: VisiblePlace | null;
  latest_committed_tick: number;
  runtime: RuntimeState | null;
};
type LivingProject = {
  project_id: string;
  kind: string;
  title: string;
  owner_agent_id: number | null;
  stage: string;
  status: string;
  started_tick: number;
  updated_tick: number;
  completed_tick: number | null;
  milestone_count: number;
  source: "committed" | "derived";
  evidence_refs: EvidenceRef[];
  organization: { id: number; name: string } | null;
  place: { id: number; name: string; kind: string } | null;
  region: Region | null;
  metrics: Record<string, unknown>;
  privacy: string;
};
type Activity = {
  activity_id: string;
  tick: number;
  kind: string;
  stage: string;
  title: string;
  agent_id: number | null;
  project_id: string | null;
  source: "committed" | "derived";
  evidence_ref: EvidenceRef;
};
type ActivityPage = {
  items: Activity[];
  next_cursor: number | null;
  total: number;
  cursor_kind: "offset";
};
type LivingAgentsData = {
  summary: {
    tick: number;
    living_agents: number;
    active_employments: number;
    active_projects: number;
    completed_projects: number;
    public_outputs: number;
    runtime_active: number;
    projects_total: number;
    projects_shown: number;
  };
  agents: LivingAgent[];
  projects: LivingProject[];
  activity: ActivityPage;
  source_legend: Record<"committed" | "runtime" | "derived", string>;
  privacy: {
    private_bodies_omitted: boolean;
    peripheral_locations: string;
    civic_cases: string;
  };
};
type AgentJourney = {
  profile: {
    id: number;
    name: string;
    kind: string;
    role: string | null;
    occupation: string | null;
    population_tier: string;
    arrived_tick: number;
    died_tick: number | null;
  };
  current_state: {
    region: Region | null;
    employment: Employment | null;
    balance_cents: number;
    compute: ComputePlan;
    residence: VisiblePlace | null;
    workplace: VisiblePlace | null;
  };
  skills: Skill[];
  projects: LivingProject[];
  milestones: ActivityPage;
  public_outputs: LivingProject[];
  runtime: RuntimeState | null;
  evidence_refs: EvidenceRef[];
  source_legend: LivingAgentsData["source_legend"];
  privacy: LivingAgentsData["privacy"];
};

const PROJECT_KINDS = [
  ["all", "All progress"],
  ["employment", "Employment"],
  ["skill", "Learning"],
  ["firm", "Firms"],
  ["civic_case", "Civic cases"],
  ["migration", "Migration"],
  ["residence", "Residences"],
  ["workplace", "Workplaces"],
  ["construction", "Construction"],
  ["public_output", "Public outputs"],
] as const;

function label(value: string | null | undefined, fallback = "Not recorded") {
  if (!value) return fallback;
  return value.replaceAll("_", " ").replace(/\b\w/g, letter => letter.toUpperCase());
}

function formatCents(value: number) {
  return `${value.toLocaleString()} cents`;
}

function placeLabel(place: VisiblePlace | null) {
  if (!place) return "Not established";
  if (place.visibility === "region_only") {
    return place.region ? `${place.region.name} region (location masked)` : "Location masked";
  }
  return place.name || label(place.kind);
}

function sourceClass(source: string) {
  return `world-os-evidence-source world-os-evidence-source--${source}`;
}

function numberMetric(project: LivingProject | null | undefined, key: string) {
  const value = Number(project?.metrics[key] || 0);
  return Number.isFinite(value) ? value : 0;
}

function ProgressStreamArt({ kind }: { kind: string }) {
  return <svg className="world-os-progress-art" viewBox="0 0 520 230" aria-hidden="true">
    <defs>
      <linearGradient id="progress-sky" x1="0" y1="0" x2="0" y2="1">
        <stop stopColor="#102b36" /><stop offset="1" stopColor="#07181d" />
      </linearGradient>
      <linearGradient id="progress-road" x1="0" y1="0" x2="1" y2="1">
        <stop stopColor="#1f3638" /><stop offset="1" stopColor="#101f21" />
      </linearGradient>
    </defs>
    <rect width="520" height="230" rx="18" fill="url(#progress-sky)" />
    <path d="M-20 214L254 57l288 149-279 67z" fill="url(#progress-road)" stroke="#31545a" />
    <path d="M25 189L254 70l237 123M101 226L330 104M195 241L421 147" fill="none" stroke="#3a5a5c" strokeWidth="4" />
    {[[55, 138, 72], [139, 107, 86], [348, 116, 78], [414, 151, 62], [278, 141, 95]].map(([x, y, h], index) => <g key={x}>
      <path d={`M${x} ${y}l34-18 35 18-35 17z`} fill={index === 2 ? "#287d82" : "#53666a"} stroke="#8ca0a1" />
      <path d={`M${x} ${y}v${h}l34 18v-${h}z`} fill={index === 2 ? "#17575d" : "#34494b"} />
      <path d={`M${x + 34} ${y + 17}v${h}l35-18v-${h}z`} fill={index === 2 ? "#123e45" : "#263a3d"} />
      <g fill="#88c7bd" opacity=".62">
        <rect x={x + 9} y={y + 24} width="7" height="8" /><rect x={x + 21} y={y + 30} width="7" height="8" />
      </g>
    </g>)}
    <path d="M297 167l42-22 43 22-43 21z" fill="#17b8bd" opacity=".2" stroke="#2ee4e7" strokeWidth="3" />
    <circle cx="339" cy="167" r="8" fill="#2ee4e7" />
    <path d="M339 159V99" stroke="#2ee4e7" strokeWidth="2" strokeDasharray="5 5" />
    <text x="24" y="34" fill="#93a7a6" fontSize="13" fontFamily="system-ui" letterSpacing="2">{label(kind).toUpperCase()} EVIDENCE</text>
  </svg>;
}

export function PeopleWorkspace() {
  const { runId = "run", agentId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const [observerState] = useObserverViewState();
  const { transport } = useWorkspaceOutletContext();
  const filter = searchParams.get("q") || "";
  const requestedProjectKind = searchParams.get("project_kind") || "all";
  const projectKind = PROJECT_KINDS.some(([value]) => value === requestedProjectKind)
    ? requestedProjectKind : "all";
  const requestedProjectStatus = searchParams.get("project_status") || "all";
  const projectStatus = ["all", "active", "completed", "cancelled"].includes(requestedProjectStatus)
    ? requestedProjectStatus : "all";
  const searchRevision = searchParams.toString();
  const pendingSearchParams = useRef(searchRevision);
  if (pendingSearchParams.current !== searchRevision) {
    pendingSearchParams.current = searchRevision;
  }
  const [agentPage, setAgentPage] = useState(0);
  const tick = observerState.tick;

  const patchPeopleFilter = (
    key: "q" | "project_kind" | "project_status",
    value: string,
    replace = false,
  ) => {
    const next = new URLSearchParams(pendingSearchParams.current);
    if (!value || ((key === "project_kind" || key === "project_status") && value === "all")) {
      next.delete(key);
    } else {
      next.set(key, value);
    }
    pendingSearchParams.current = next.toString();
    setSearchParams(next, { replace });
  };

  const workspaceQuery = useQuery({
    queryKey: [
      "world-os", runId, observerState.fork, "living-agents",
      tick, projectKind, projectStatus,
    ],
    queryFn: ({ signal }) => {
      const params = projectionScopeParams(observerState);
      params.set("project_kind", projectKind);
      params.set("status", projectStatus);
      params.set("limit", "200");
      return projectionApi<LivingAgentsData>(
        `/api/v2/workspaces/living-agents?${params}`,
        signal,
      );
    },
    placeholderData: previousData => previousData,
    refetchInterval: tick === "live" ? 3000 : false,
  });
  const agents = workspaceQuery.data?.data.agents || [];
  const requestedId = agentId ? Number(agentId) : null;
  const featuredAgentId = useMemo(() => {
    const projects = workspaceQuery.data?.data.projects || [];
    const constructionOwner = projects.find(project =>
      project.kind === "construction"
      && project.status === "active"
      && project.owner_agent_id != null,
    )?.owner_agent_id;
    if (constructionOwner != null) return constructionOwner;
    const runtimeAgent = agents.find(agent => agent.runtime);
    if (runtimeAgent) return runtimeAgent.id;
    const progressingOwner = projects.find(project =>
      project.status === "active" && project.owner_agent_id != null,
    )?.owner_agent_id;
    return progressingOwner ?? agents[0]?.id;
  }, [agents, workspaceQuery.data?.data.projects]);
  const selectedId = requestedId != null && Number.isFinite(requestedId)
    ? requestedId
    : featuredAgentId;
  const journeyQuery = useQuery({
    queryKey: [
      "world-os", runId, observerState.fork, "agent-journey", tick, selectedId,
    ],
    queryFn: ({ signal }) => {
      const params = projectionScopeParams(observerState);
      params.set("limit", "200");
      return projectionApi<AgentJourney>(
        `/api/v2/agents/${selectedId}/journey?${params}`,
        signal,
      );
    },
    enabled: Number.isFinite(selectedId),
    refetchInterval: tick === "live" ? 3000 : false,
  });
  const visibleAgents = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return agents;
    return agents.filter(agent => [
      agent.name,
      agent.role,
      agent.occupation,
      agent.region?.name,
      agent.employment?.firm_name,
      agent.compute.tier,
      ...agent.skills.map(skill => skill.skill_key),
    ].some(value => String(value || "").toLowerCase().includes(needle)));
  }, [agents, filter]);

  const pageSize = 36;
  const lastAgentPage = Math.max(0, Math.ceil(visibleAgents.length / pageSize) - 1);
  useEffect(() => {
    setAgentPage(current => Math.min(current, lastAgentPage));
  }, [lastAgentPage]);
  useEffect(() => {
    if (selectedId == null) return;
    const selectedIndex = visibleAgents.findIndex(agent => agent.id === selectedId);
    if (selectedIndex >= 0) setAgentPage(Math.floor(selectedIndex / pageSize));
  }, [selectedId, visibleAgents]);
  useEffect(() => setAgentPage(0), [filter, projectKind, projectStatus]);
  const pagedAgents = visibleAgents.slice(agentPage * pageSize, (agentPage + 1) * pageSize);

  const allProjects = useMemo(() => {
    const byId = new Map<string, LivingProject>();
    for (const project of workspaceQuery.data?.data.projects || []) {
      byId.set(project.project_id, project);
    }
    for (const project of journeyQuery.data?.data.projects || []) {
      byId.set(project.project_id, project);
    }
    return [...byId.values()];
  }, [journeyQuery.data?.data.projects, workspaceQuery.data?.data.projects]);
  const requestedProjectId = searchParams.get("project");
  const selectedProject = useMemo(() => {
    const requested = allProjects.find(project => project.project_id === requestedProjectId);
    if (requested) return requested;
    const selectedConstruction = allProjects.find(project =>
      project.kind === "construction"
      && project.owner_agent_id === selectedId
      && project.status === "active",
    );
    if (selectedConstruction) return selectedConstruction;
    const activeConstruction = allProjects.find(project =>
      project.kind === "construction" && project.status === "active",
    );
    if (activeConstruction) return activeConstruction;
    const selectedProgress = allProjects.find(project =>
      project.owner_agent_id === selectedId && project.status === "active",
    );
    return selectedProgress
      || allProjects.find(project => project.owner_agent_id === selectedId)
      || allProjects.find(project => project.kind === "construction")
      || allProjects[0]
      || null;
  }, [allProjects, requestedProjectId, selectedId]);
  const storyboardProject = selectedProject?.kind === "construction"
    ? selectedProject
    : allProjects.find(project => project.kind === "construction") || null;

  const routeForAgent = (id: number, projectId?: string | null) => {
    const params = commonObserverParamsFromState(observerState);
    if (filter) params.set("q", filter);
    if (projectKind !== "all") params.set("project_kind", projectKind);
    if (projectStatus !== "all") params.set("project_status", projectStatus);
    if (projectId) params.set("project", projectId);
    const suffix = params.toString();
    return `/runs/${encodeURIComponent(runId)}/people/${id}${suffix ? `?${suffix}` : ""}`;
  };
  const cityUrl = ({
    agent,
    place,
    project,
    organization,
  }: {
    agent?: number | null;
    place?: number | null;
    project?: string | null;
    organization?: string | null;
  }) => {
    const params = commonObserverParamsFromState(observerState);
    params.set("view", "diorama");
    if (project) {
      params.set("project", project);
    } else if (agent != null) {
      params.set("agent", String(agent));
      params.set("population", "all");
    }
    if (!project && place != null) params.set("place", String(place));
    if (!project && organization) {
      params.set("layer", "organizations");
      params.set("q", organization);
    }
    return `/runs/${encodeURIComponent(runId)}/world?${params}`;
  };
  const projectUrl = (project: LivingProject) => project.kind === "construction"
    ? cityUrl({ project: project.project_id.replace(/^construction:/, "") })
    : cityUrl({
      agent: project.owner_agent_id,
      place: project.place?.id,
      organization: project.organization?.name,
    });
  const workspaceProjectUrl = (project: LivingProject) => routeForAgent(
    project.owner_agent_id || selectedId || agents[0]?.id || 1,
    project.project_id,
  );

  if (workspaceQuery.isLoading) {
    return <div className="world-os-loading" aria-label="Loading Living Agents" />;
  }
  if (workspaceQuery.error) {
    return <div className="world-os-error" role="alert">{workspaceQuery.error.message}</div>;
  }
  const envelope = workspaceQuery.data!;
  const data = envelope.data;
  const journey = journeyQuery.data?.data;

  return <section className="world-os-people world-os-living-agents"
    aria-busy={workspaceQuery.isPlaceholderData}>
    <header className="world-os-heading world-os-living-heading">
      <div>
        <p className="world-os-kicker">Evidence-backed lives in motion</p>
        <h2>Agent progress</h2>
        <p className="world-os-heading-copy">
          Follow committed work and milestones. Runtime activity appears only while viewing live.
        </p>
      </div>
      <div className="world-os-heading-actions">
        <FreshnessBadge
          transport={transport}
          tick={tick}
          envelope={envelope}
          sourceMode="projection"
          sourceLabel="Historical-safe Living Agents projection"
        />
        <div className="world-os-people-stats" aria-label="Living Agents summary">
          <span><strong>{data.summary.living_agents}</strong> living</span>
          <span><strong>{data.summary.active_employments}</strong> working</span>
          <span><strong>{data.summary.active_projects}</strong> progressing</span>
          <span><strong>{data.summary.completed_projects}</strong> completed</span>
          <span><strong>{data.summary.runtime_active}</strong> runtime now</span>
        </div>
      </div>
    </header>

    <div className="world-os-source-legend" aria-label="Evidence source legend">
      {(["committed", "runtime", "derived"] as const).map(source =>
        <span key={source} title={data.source_legend[source]}>
          <i className={sourceClass(source)}>{label(source)}</i>
          <small>{data.source_legend[source]}</small>
        </span>,
      )}
    </div>

    {workspaceQuery.isPlaceholderData && <p className="world-os-policy-note" role="status">
      Refreshing project filters. Previous authorized results remain visible until the canonical projection arrives.
    </p>}

    <div className="world-os-living-grid">
      <aside className="world-os-panel world-os-people-list">
        <header className="world-os-people-list-heading">
          <div>
            <p className="world-os-kicker">Living Agents</p>
            <h3>Active & recent</h3>
          </div>
          <span>{visibleAgents.length.toLocaleString()}</span>
        </header>
        <label className="world-os-agent-search">
          <span aria-hidden="true">⌕</span>
          <input
            type="search"
            value={filter}
            onChange={event => patchPeopleFilter("q", event.target.value, true)}
            placeholder="Search agents, skills, firms…"
            aria-label="Search living agents"
          />
        </label>
        <div className="world-os-people-scroll" aria-label="Active and recent agents">
          {pagedAgents.map(agent => <Link
            key={agent.id}
            className={selectedId === agent.id ? "selected" : ""}
            to={routeForAgent(agent.id)}
            aria-current={selectedId === agent.id ? "page" : undefined}
          >
            <LivingAgentPortrait agentId={agent.id} name={agent.name} />
            <span className="world-os-agent-list-copy">
              <strong>{agent.name}</strong>
              <small>{label(agent.role || agent.occupation || agent.kind)}</small>
              <em>{agent.region?.name || "No recorded region"}</em>
            </span>
            <span className="world-os-agent-recency">
              <i className={`world-os-agent-status-dot ${agent.runtime ? "is-runtime" : agent.employment ? "is-working" : "is-recent"}`} aria-hidden="true" />
              <small>t{agent.latest_committed_tick}</small>
            </span>
          </Link>)}
          {!visibleAgents.length && <p className="world-os-list-empty">No agents match this filter.</p>}
        </div>
        <footer className="world-os-agent-pagination" aria-label="Agent list pagination">
          <button
            type="button"
            onClick={() => setAgentPage(page => Math.max(0, page - 1))}
            disabled={agentPage === 0}
            aria-label="Previous agents"
          >‹</button>
          <span>
            {visibleAgents.length
              ? `${agentPage * pageSize + 1}–${Math.min((agentPage + 1) * pageSize, visibleAgents.length)} of ${visibleAgents.length}`
              : "0 agents"}
          </span>
          <button
            type="button"
            onClick={() => setAgentPage(page => Math.min(lastAgentPage, page + 1))}
            disabled={agentPage >= lastAgentPage}
            aria-label="Next agents"
          >›</button>
        </footer>
      </aside>

      <main className="world-os-person-detail" aria-live="polite">
        {journeyQuery.isLoading &&
          <div className="world-os-loading" aria-label="Loading selected agent journey" />}
        {journeyQuery.error &&
          <div className="world-os-error" role="alert">{journeyQuery.error.message}</div>}
        {journey && <>
          <article className="world-os-panel world-os-person-identity">
            <LivingAgentPortrait agentId={journey.profile.id} name={journey.profile.name} large />
            <div className="world-os-person-identity-copy">
              <p className="world-os-kicker">Agent journey · ID {journey.profile.id}</p>
              <h3>{journey.profile.name}</h3>
              <p>{label(journey.profile.role || journey.profile.occupation || journey.profile.kind)}</p>
              <small>{journey.current_state.region?.name || "No recorded region"} · as of tick {envelope.tick}</small>
            </div>
            <div className="world-os-journey-actions">
              {journey.runtime
                ? <i className={sourceClass("runtime")}>{label(journey.runtime.state)}</i>
                : <i className={sourceClass("committed")}>
                  {tick === "live" ? "No runtime signal" : "Historical"}
                </i>}
              <Link to={cityUrl({ agent: journey.profile.id })}>Focus in Live City</Link>
            </div>
          </article>

          <article className="world-os-panel world-os-journey-milestones">
            <header>
              <div><p className="world-os-kicker">Committed progress</p><h3>Journey milestones</h3></div>
              <span>{journey.milestones.total} records</span>
            </header>
            <ol>
              {journey.milestones.items.slice(0, 6).map(item => <li key={item.activity_id}>
                <i aria-hidden="true">✓</i>
                <div><strong>{item.title}</strong><small>{label(item.stage)} · tick {item.tick}</small></div>
                <span className={sourceClass(item.source)}>{label(item.source)}</span>
              </li>)}
              {!journey.milestones.items.length && <li className="world-os-journey-empty">
                No committed milestones exist at this tick.
              </li>}
            </ol>
          </article>

          <div className="world-os-journey-dashboard">
            <article className="world-os-panel world-os-skill-card">
              <header>
                <div><p className="world-os-kicker">Derived from committed practice</p><h3>Skill growth</h3></div>
                <span>{journey.skills.length} tracked</span>
              </header>
              <ul>
                {journey.skills.map(skill => <li key={skill.skill_key}>
                  <div>
                    <strong>{label(skill.skill_key)}</strong>
                    <span>Level {skill.level} · {skill.xp} XP · {skill.milestone_count} milestones</span>
                  </div>
                  <i aria-label={`Level ${skill.level} of 5`}>
                    <b style={{ width: `${Math.max(0, Math.min(5, skill.level)) * 20}%` }} />
                  </i>
                </li>)}
                {!journey.skills.length &&
                  <li className="world-os-progression-empty">No committed skill milestones yet.</li>}
              </ul>
            </article>

            <article className="world-os-panel world-os-employment-card">
              <header>
                <div><p className="world-os-kicker">Committed state</p><h3>Employment & resources</h3></div>
                <span className={sourceClass("committed")}>Committed</span>
              </header>
              <dl>
                <div><dt>Role</dt><dd>{journey.current_state.employment?.title || "Not employed"}</dd></div>
                <div><dt>Employer</dt><dd>{journey.current_state.employment?.firm_name || "No active employer"}</dd></div>
                <div><dt>Ledger balance</dt><dd>{formatCents(journey.current_state.balance_cents)}</dd></div>
                <div><dt>Compute tier</dt><dd>{label(journey.current_state.compute.tier)}</dd></div>
                <div><dt>Employment since</dt><dd>{journey.current_state.employment ? `Tick ${journey.current_state.employment.start_tick}` : "Not applicable"}</dd></div>
                <div><dt>Compute payer</dt><dd>{label(journey.current_state.compute.payer_type)}</dd></div>
              </dl>
              {journey.current_state.employment
                ? <Link to={cityUrl({
                  agent: journey.profile.id,
                  organization: journey.current_state.employment.firm_name,
                })}>Focus {journey.current_state.employment.firm_name} in Live City</Link>
                : <small>No active employment evidence exists at this tick.</small>}
            </article>
          </div>

          <section className="world-os-journey-locations" aria-label="Residence and workplace">
            <article className="world-os-panel">
              <div className="world-os-place-icon" aria-hidden="true">⌂</div>
              <div><span>Residence</span><strong>{placeLabel(journey.current_state.residence)}</strong></div>
              {journey.current_state.residence?.id
                ? <Link to={cityUrl({ place: journey.current_state.residence.id })}>Open in Live City ↗</Link>
                : <small>{journey.current_state.residence?.visibility === "region_only"
                  ? "Exact peripheral location is protected"
                  : "No residence evidence at this tick"}</small>}
            </article>
            <article className="world-os-panel">
              <div className="world-os-place-icon" aria-hidden="true">▥</div>
              <div><span>Workplace</span><strong>{placeLabel(journey.current_state.workplace)}</strong></div>
              {journey.current_state.workplace?.id
                ? <Link to={cityUrl({ place: journey.current_state.workplace.id })}>Open in Live City ↗</Link>
                : <small>{journey.current_state.workplace?.visibility === "region_only"
                  ? "Exact peripheral location is protected"
                  : "No workplace evidence at this tick"}</small>}
            </article>
          </section>

          <article className="world-os-panel world-os-public-output-card">
            <header>
              <div><p className="world-os-kicker">Authorized public record</p><h3>Public outputs</h3></div>
              <span className={sourceClass("derived")}>Derived</span>
            </header>
            <div className="world-os-public-output-metrics">
              <span><strong>{journey.public_outputs.length}</strong><small>published outputs</small></span>
              <span><strong>{journey.projects.length}</strong><small>linked progress streams</small></span>
              <span><strong>{journey.evidence_refs.length}</strong><small>evidence references</small></span>
            </div>
            <p>Private bodies omitted; prompts, reasoning and memory contents are also excluded.</p>
          </article>
        </>}
      </main>

      <aside className="world-os-project-rail" aria-label="Projects and progress streams">
        <article className="world-os-panel world-os-project-hero">
          <header>
            <div><p className="world-os-kicker">Projects</p><h3>{selectedProject ? label(selectedProject.kind) : "No project yet"}</h3></div>
            {selectedProject && <span className={sourceClass(selectedProject.source)}>{label(selectedProject.source)}</span>}
          </header>
          <div className="world-os-project-hero-art">
            {selectedProject?.kind === "construction"
              ? <ConstructionStageArt stage={normalizeConstructionStage(selectedProject.stage)} />
              : <ProgressStreamArt kind={selectedProject?.kind || "progress"} />}
          </div>
          {selectedProject ? <div className="world-os-project-hero-copy">
            <div className="world-os-project-title-row">
              <div>
                <h3>{selectedProject.title}</h3>
                <p>{selectedProject.region?.name || "No public region"} · updated tick {selectedProject.updated_tick}</p>
              </div>
              <span>{label(selectedProject.stage)}</span>
            </div>
            {selectedProject.kind === "construction" ? <div className="world-os-construction-metrics">
              <div>
                <span>Funding</span>
                <strong>{numberMetric(selectedProject, "contributed_funding_cents").toLocaleString()} cents</strong>
                <small>of {numberMetric(selectedProject, "required_funding_cents").toLocaleString()} committed</small>
                <progress
                  aria-label="Construction funding"
                  max={Math.max(1, numberMetric(selectedProject, "required_funding_cents"))}
                  value={numberMetric(selectedProject, "contributed_funding_cents")}
                />
              </div>
              <div>
                <span>Work units</span>
                <strong>{numberMetric(selectedProject, "contributed_work_units").toLocaleString()}</strong>
                <small>of {numberMetric(selectedProject, "required_work_units").toLocaleString()} stored</small>
                <progress
                  aria-label="Construction work units"
                  max={Math.max(1, numberMetric(selectedProject, "required_work_units"))}
                  value={numberMetric(selectedProject, "contributed_work_units")}
                />
              </div>
            </div> : <dl className="world-os-project-evidence-metrics">
              <div><dt>Status</dt><dd>{label(selectedProject.status)}</dd></div>
              <div><dt>Milestones</dt><dd>{selectedProject.milestone_count}</dd></div>
              <div><dt>Started</dt><dd>Tick {selectedProject.started_tick}</dd></div>
              <div><dt>Evidence</dt><dd>{selectedProject.evidence_refs.length} refs</dd></div>
            </dl>}
            <p className="world-os-project-privacy">
              {["aggregated", "aggregated_private"].includes(selectedProject.privacy)
                ? "Regional aggregate: private owner and exact location are protected."
                : `${selectedProject.evidence_refs.length} authorized evidence reference${selectedProject.evidence_refs.length === 1 ? "" : "s"}.`}
            </p>
            {(selectedProject.kind === "construction" || selectedProject.owner_agent_id || selectedProject.place || selectedProject.organization) &&
              <Link className="world-os-project-city-link" to={projectUrl(selectedProject)}>Open in Live City ↗</Link>}
          </div> : <div className="world-os-project-hero-empty">
            <strong>No committed project at tick {envelope.tick}</strong>
            <p>When agents propose, permit, fund and build, their stored progress will appear here.</p>
          </div>}
        </article>

        <div className="world-os-panel world-os-storyboard-panel">
          <ConstructionStoryboard
            stage={storyboardProject?.stage || ""}
            lifecycle={storyboardProject ? label(storyboardProject.stage) : "No construction project at this tick"}
          />
        </div>

        <details className="world-os-panel world-os-project-browser">
          <summary>
            <span><strong>All progress streams</strong><small>{data.summary.projects_total} match this view</small></span>
            <i aria-hidden="true">⌄</i>
          </summary>
          <div className="world-os-project-filters">
            <label>
              <span>Kind</span>
              <select value={projectKind} onChange={event => patchPeopleFilter("project_kind", event.target.value)}>
                {PROJECT_KINDS.map(([value, text]) =>
                  <option key={value} value={value}>{text}</option>,
                )}
              </select>
            </label>
            <label>
              <span>Status</span>
              <select value={projectStatus} onChange={event => patchPeopleFilter("project_status", event.target.value)}>
                <option value="all">All statuses</option>
                <option value="active">Active</option>
                <option value="completed">Completed</option>
                <option value="cancelled">Cancelled</option>
              </select>
            </label>
          </div>
          <div className="world-os-project-list">
            {data.projects.slice(0, 24).map(project => <article
              className={`world-os-project-card${selectedProject?.project_id === project.project_id ? " selected" : ""}`}
              key={project.project_id}
            >
              <Link to={workspaceProjectUrl(project)}>
                <span>{label(project.kind)}</span>
                <strong>{project.title}</strong>
                <small>{label(project.stage)} · t{project.updated_tick} · {project.milestone_count} milestones</small>
              </Link>
              <i className={sourceClass(project.source)}>{label(project.source)}</i>
            </article>)}
            {!data.projects.length && <div className="world-os-project-empty">
              No projects match these filters at tick {envelope.tick}.
            </div>}
          </div>
        </details>
      </aside>
    </div>
  </section>;
}

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router";
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

function initials(name: string) {
  return name.split(/\s+/).filter(Boolean).map(part => part[0]).join("").slice(0, 2);
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

export function PeopleWorkspace() {
  const { runId = "run", agentId } = useParams();
  const [observerState] = useObserverViewState();
  const { transport } = useWorkspaceOutletContext();
  const [filter, setFilter] = useState("");
  const [projectKind, setProjectKind] = useState("all");
  const [projectStatus, setProjectStatus] = useState("all");
  const tick = observerState.tick;

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
    refetchInterval: tick === "live" ? 3000 : false,
  });
  const agents = workspaceQuery.data?.data.agents || [];
  const requestedId = agentId ? Number(agentId) : null;
  const selectedId = requestedId && Number.isFinite(requestedId)
    ? requestedId
    : agents[0]?.id;
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

  const routeForAgent = (id: number) => {
    const params = commonObserverParamsFromState(observerState);
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

  if (workspaceQuery.isLoading) {
    return <div className="world-os-loading" aria-label="Loading Living Agents" />;
  }
  if (workspaceQuery.error) {
    return <div className="world-os-error" role="alert">{workspaceQuery.error.message}</div>;
  }
  const envelope = workspaceQuery.data!;
  const data = envelope.data;
  const journey = journeyQuery.data?.data;

  return <section className="world-os-people world-os-living-agents">
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

    <div className="world-os-living-grid">
      <aside className="world-os-panel world-os-people-list">
        <label>
          <span>Find an agent</span>
          <input
            type="search"
            value={filter}
            onChange={event => setFilter(event.target.value)}
            placeholder="Name, work, skill, region..."
          />
        </label>
        <div className="world-os-people-scroll" aria-label="Active and recent agents">
          {visibleAgents.map(agent => <Link
            key={agent.id}
            className={selectedId === agent.id ? "selected" : ""}
            to={routeForAgent(agent.id)}
          >
            <span className="world-os-person-avatar">{initials(agent.name)}</span>
            <span>
              <strong>{agent.name}</strong>
              <small>{label(agent.role || agent.occupation || agent.kind)} · {agent.region?.name || "Unplaced"}</small>
            </span>
            <span className="world-os-agent-recency">
              {agent.runtime
                ? <i className={sourceClass("runtime")}>{label(agent.runtime.state)}</i>
                : <i className={sourceClass("committed")}>Committed</i>}
              <small>t{agent.latest_committed_tick}</small>
            </span>
          </Link>)}
          {!visibleAgents.length && <p className="world-os-list-empty">No agents match this filter.</p>}
        </div>
      </aside>

      <main className="world-os-person-detail" aria-live="polite">
        {journeyQuery.isLoading &&
          <div className="world-os-loading" aria-label="Loading selected agent journey" />}
        {journeyQuery.error &&
          <div className="world-os-error" role="alert">{journeyQuery.error.message}</div>}
        {journey && <>
          <article className="world-os-panel world-os-person-identity">
            <div className="world-os-person-avatar world-os-person-avatar--large">
              {initials(journey.profile.name)}
            </div>
            <div>
              <p className="world-os-kicker">Agent #{journey.profile.id} · as of tick {envelope.tick}</p>
              <h3>{journey.profile.name}</h3>
              <p>
                {label(journey.profile.role || journey.profile.occupation || journey.profile.kind)}
                {" · "}{journey.current_state.region?.name || "No recorded region"}
              </p>
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

          <section className="world-os-journey-state" aria-label="Selected agent current state">
            <article className="world-os-panel">
              <span>Work</span>
              <strong>{journey.current_state.employment?.title || "Not employed"}</strong>
              {journey.current_state.employment
                ? <Link to={cityUrl({
                  agent: journey.profile.id,
                  organization: journey.current_state.employment.firm_name,
                })}>{journey.current_state.employment.firm_name} · t{journey.current_state.employment.start_tick}</Link>
                : <small>No active employment at this tick</small>}
            </article>
            <article className="world-os-panel">
              <span>Finances</span>
              <strong>{formatCents(journey.current_state.balance_cents)}</strong>
              <small>Ledger balance at tick {envelope.tick}</small>
            </article>
            <article className="world-os-panel">
              <span>Compute</span>
              <strong>{label(journey.current_state.compute.tier)}</strong>
              <small>
                {label(journey.current_state.compute.payer_type)}
                {journey.current_state.compute.expiry_tick != null
                  ? ` · through t${journey.current_state.compute.expiry_tick - 1}`
                  : " · no paid subscription"}
              </small>
            </article>
            <article className="world-os-panel">
              <span>Residence</span>
              <strong>{placeLabel(journey.current_state.residence)}</strong>
              {journey.current_state.residence?.id
                ? <Link to={cityUrl({ place: journey.current_state.residence.id })}>Open place in Live City</Link>
                : <small>{journey.current_state.residence?.visibility === "region_only"
                  ? "Exact peripheral location is protected"
                  : "No residence evidence at this tick"}</small>}
            </article>
            <article className="world-os-panel">
              <span>Workplace</span>
              <strong>{placeLabel(journey.current_state.workplace)}</strong>
              {journey.current_state.workplace?.id
                ? <Link to={cityUrl({ place: journey.current_state.workplace.id })}>Open place in Live City</Link>
                : <small>{journey.current_state.workplace?.visibility === "region_only"
                  ? "Exact peripheral location is protected"
                  : "No workplace evidence at this tick"}</small>}
            </article>
            <article className="world-os-panel">
              <span>Public outputs</span>
              <strong>{journey.public_outputs.length}</strong>
              <small>Published records; private bodies omitted</small>
            </article>
          </section>

          <div className="world-os-person-cards">
            <article className="world-os-panel world-os-skill-card">
              <header>
                <div><p className="world-os-kicker">Stored progression</p><h3>Skills</h3></div>
                <span>{journey.skills.length} skills</span>
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

            <article className="world-os-panel world-os-progression-card">
              <header>
                <div><p className="world-os-kicker">Committed and derived</p><h3>Journey milestones</h3></div>
                <span>{journey.milestones.total} records</span>
              </header>
              <ol>
                {journey.milestones.items.slice(0, 12).map(item => <li key={item.activity_id}>
                  <span>t{item.tick}</span>
                  <strong>{item.title}</strong>
                  <em>{label(item.stage)}</em>
                  <small>
                    <i className={sourceClass(item.source)}>{label(item.source)}</i>
                    {" · "}{label(item.evidence_ref.kind)} #{item.evidence_ref.id}
                  </small>
                </li>)}
                {!journey.milestones.items.length &&
                  <li className="world-os-progression-empty">No milestones at this tick.</li>}
              </ol>
            </article>
          </div>
        </>}
      </main>

      <aside className="world-os-project-rail" aria-label="Projects and progress streams">
        <article className="world-os-panel world-os-project-filters">
          <div>
            <p className="world-os-kicker">Progress streams</p>
            <h3>Projects & milestones</h3>
          </div>
          <label>
            <span>Kind</span>
            <select value={projectKind} onChange={event => setProjectKind(event.target.value)}>
              {PROJECT_KINDS.map(([value, text]) =>
                <option key={value} value={value}>{text}</option>,
              )}
            </select>
          </label>
          <label>
            <span>Status</span>
            <select value={projectStatus} onChange={event => setProjectStatus(event.target.value)}>
              <option value="all">All statuses</option>
              <option value="active">Active</option>
              <option value="completed">Completed</option>
              <option value="cancelled">Cancelled</option>
            </select>
          </label>
          <small>{data.summary.projects_total} progress streams match</small>
        </article>
        <div className="world-os-project-list">
          {data.projects.map(project => <article
            className="world-os-panel world-os-project-card"
            key={project.project_id}
          >
            <header>
              <span>{label(project.kind)}</span>
              <i className={sourceClass(project.source)}>{label(project.source)}</i>
            </header>
            <h4>{project.title}</h4>
            <dl>
              <div><dt>Stage</dt><dd>{label(project.stage)}</dd></div>
              <div><dt>Status</dt><dd>{label(project.status)}</dd></div>
              <div><dt>Milestones</dt><dd>{project.milestone_count}</dd></div>
              <div><dt>Updated</dt><dd>Tick {project.updated_tick}</dd></div>
              {project.kind === "construction" && <>
                <div><dt>Funding</dt><dd>{Number(project.metrics.contributed_funding_cents || 0)}/{Number(project.metrics.required_funding_cents || 0)} cents</dd></div>
                <div><dt>Work</dt><dd>{Number(project.metrics.contributed_work_units || 0)}/{Number(project.metrics.required_work_units || 0)} units</dd></div>
              </>}
            </dl>
            <p>
              {["aggregated", "aggregated_private"].includes(project.privacy)
                ? "Aggregated to protect peripheral agents."
                : `${project.evidence_refs.length} evidence reference${project.evidence_refs.length === 1 ? "" : "s"}.`}
            </p>
            {(project.kind === "construction" || project.owner_agent_id || project.place || project.organization) &&
              <Link to={projectUrl(project)}>Focus evidence in Live City</Link>}
          </article>)}
          {!data.projects.length &&
            <div className="world-os-panel world-os-project-empty">
              No projects match these filters at tick {envelope.tick}.
            </div>}
        </div>
      </aside>
    </div>
  </section>;
}

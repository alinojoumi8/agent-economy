import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { workspaceApi } from "../app/api";

type Agent = {
  id: number; name: string; kind: string; role: string | null; occupation: string | null;
  age: number; health: string; alive: number; retired: number; employer_id: number | null;
  model_tier: "local" | "flash" | "premium" | "citizen" | "strong";
  population_tier: string;
};
type Skill = { skill_key: string; xp: number; level: number; last_practiced_tick: number | null; source: string };
type SkillHistory = { id: number; tick: number; skill_key: string; old_level: number; new_level: number; xp_delta: number; new_xp: number; source: string };
type AgentDetail = {
  agent: Agent;
  accounts: Array<{ id: number; kind: string; bank_id: number | null; balance_cents: number }>;
  cognition: {
    compute_plan: { tier: string; payer_type: string; payer_id: number | null; price_cents: number; effective_tick: number | null; expiry_tick: number | null; status: string };
    skills: Skill[];
    skill_history: SkillHistory[];
    subscription_history: Array<{ id: number; tier: string; payer_type: string; price_cents: number; effective_tick: number; expiry_tick: number; status: string; reason: string }>;
    latest_route: { provider: string; model: string; purpose: string; tick: number } | null;
  };
};

function label(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, letter => letter.toUpperCase());
}

function normalizedTier(value: string) {
  if (value === "strong") return "premium";
  if (value === "citizen") return "local";
  return value;
}

export function PeopleWorkspace() {
  const { runId = "run", agentId } = useParams();
  const [searchParams] = useSearchParams();
  const [filter, setFilter] = useState("");
  const tick = searchParams.get("tick");
  const suffix = tick ? "?tick=" + encodeURIComponent(tick) : "";
  const agentsQuery = useQuery({
    queryKey: ["agents", runId],
    queryFn: ({ signal }) => workspaceApi<Agent[]>("/api/agents", { signal }),
    refetchInterval: tick ? false : 3000,
  });
  const agents = agentsQuery.data || [];
  const selectedId = agentId ? Number(agentId) : agents[0]?.id;
  const detailQuery = useQuery({
    queryKey: ["agent-detail", runId, selectedId],
    queryFn: ({ signal }) => workspaceApi<AgentDetail>("/api/agents/" + selectedId, { signal }),
    enabled: Number.isFinite(selectedId),
    refetchInterval: tick ? false : 3000,
  });
  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return agents;
    return agents.filter(agent => [agent.name, agent.role, agent.occupation, agent.model_tier]
      .some(value => String(value || "").toLowerCase().includes(needle)));
  }, [agents, filter]);

  if (agentsQuery.isLoading) return <div className="world-os-loading" aria-label="Loading people" />;
  if (agentsQuery.error) return <div className="world-os-error" role="alert">{agentsQuery.error.message}</div>;
  const detail = detailQuery.data;
  const plan = detail?.cognition.compute_plan;
  const latestHistory = [...(detail?.cognition.skill_history || [])].reverse().slice(0, 12);
  const cash = (detail?.accounts || []).reduce((sum, account) => sum + account.balance_cents, 0);

  return <section className="world-os-people">
    <header className="world-os-heading">
      <div><p className="world-os-kicker">Citizen cognition economy</p><h2>People</h2></div>
      <div className="world-os-people-stats">
        <span><strong>{agents.filter(agent => agent.alive).length}</strong> living</span>
        <span><strong>{agents.filter(agent => normalizedTier(agent.model_tier) === "local").length}</strong> local</span>
        <span><strong>{agents.filter(agent => normalizedTier(agent.model_tier) === "flash").length}</strong> flash</span>
        <span><strong>{agents.filter(agent => normalizedTier(agent.model_tier) === "premium").length}</strong> premium</span>
      </div>
    </header>

    <div className="world-os-people-grid">
      <aside className="world-os-panel world-os-people-list">
        <label><span>Find a citizen</span><input value={filter} onChange={event => setFilter(event.target.value)} placeholder="Name, role, skill tier…" /></label>
        <div className="world-os-people-scroll">
          {visible.map(agent => <Link key={agent.id} className={selectedId === agent.id ? "selected" : ""}
            to={"/runs/" + encodeURIComponent(runId) + "/people/" + agent.id + suffix}>
            <span className="world-os-person-avatar">{agent.name.split(/\s+/).map(part => part[0]).join("").slice(0, 2)}</span>
            <span><strong>{agent.name}</strong><small>{label(agent.role || agent.occupation || agent.kind)} · #{agent.id}</small></span>
            <em className={"world-os-tier-badge world-os-tier-badge--" + normalizedTier(agent.model_tier)}>{normalizedTier(agent.model_tier)}</em>
          </Link>)}
        </div>
      </aside>

      <main className="world-os-person-detail">
        {detailQuery.isLoading && <div className="world-os-loading" aria-label="Loading citizen detail" />}
        {detailQuery.error && <div className="world-os-error" role="alert">{detailQuery.error.message}</div>}
        {detail && <>
          <article className="world-os-panel world-os-person-identity">
            <div className="world-os-person-avatar world-os-person-avatar--large">{detail.agent.name.split(/\s+/).map(part => part[0]).join("").slice(0, 2)}</div>
            <div><p className="world-os-kicker">Agent #{detail.agent.id}</p><h3>{detail.agent.name}</h3><p>{label(detail.agent.role || detail.agent.occupation || detail.agent.kind)} · age {detail.agent.age} · {label(detail.agent.health)}</p></div>
            <em className={"world-os-tier-badge world-os-tier-badge--" + normalizedTier(plan?.tier || detail.agent.model_tier)}>{normalizedTier(plan?.tier || detail.agent.model_tier)}</em>
          </article>

          <div className="world-os-person-cards">
            <article className="world-os-panel world-os-compute-card">
              <header><div><p className="world-os-kicker">Current subscription</p><h3>Compute plan</h3></div><span className="world-os-live-dot" /></header>
              <dl>
                <div><dt>Tier</dt><dd>{label(plan?.tier || "local")}</dd></div>
                <div><dt>Payer</dt><dd>{label(plan?.payer_type || "free")}</dd></div>
                <div><dt>Expires</dt><dd>{plan?.expiry_tick == null ? "Free / ongoing" : "Tick " + plan.expiry_tick}</dd></div>
                <div><dt>Price</dt><dd>{(plan?.price_cents || 0).toLocaleString()}c / 7 ticks</dd></div>
                <div><dt>Provider</dt><dd>{detail.cognition.latest_route?.provider ? label(detail.cognition.latest_route.provider) : "Awaiting first call"}</dd></div>
                <div><dt>Model</dt><dd>{detail.cognition.latest_route?.model || "—"}</dd></div>
              </dl>
              <small>{cash.toLocaleString()} cents across citizen accounts</small>
            </article>

            <article className="world-os-panel world-os-skill-card">
              <header><div><p className="world-os-kicker">Authoritative progression</p><h3>Learned skills</h3></div><span>0–5</span></header>
              <ul>
                {detail.cognition.skills.map(skill => <li key={skill.skill_key}>
                  <div><strong>{label(skill.skill_key)}</strong><span>Level {skill.level} · {skill.xp} XP</span></div>
                  <i><b style={{ width: (skill.level / 5) * 100 + "%" }} /></i>
                </li>)}
              </ul>
            </article>
          </div>

          <article className="world-os-panel world-os-progression-card">
            <header><div><p className="world-os-kicker">Committed actions only</p><h3>Progression history</h3></div><span>{detail.cognition.skill_history.length} records</span></header>
            <ol>
              {latestHistory.map(item => <li key={item.id}>
                <span>t{item.tick}</span><strong>{label(item.skill_key)}</strong>
                <em>+{item.xp_delta} XP</em><small>level {item.old_level} → {item.new_level} · {label(item.source)}</small>
              </li>)}
              {!latestHistory.length && <li className="world-os-progression-empty">No committed skill practice yet.</li>}
            </ol>
          </article>
        </>}
      </main>
    </div>
  </section>;
}

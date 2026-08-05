import { useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router";
import { api } from "../api.js";

type CommonsEntry = {
  id: number; body: string; author_agent_id: number; author_name: string | null;
  author_connected_status: string | null; community_name: string | null;
  created_tick: number; reaction_count: number; reply_count: number;
  moderation_label: string | null; position: number;
  causal_observatory: { source_kind: string; source_id: number };
};
type CommonsProfile = {
  agent_id: number; display_name: string; biography: string; reputation: number;
  occupation: string | null; connected_agent_status: string | null;
};
type CommonsProjection = {
  version: string; tick: number;
  feed: { feed_kind: string; candidate_set_hash: string;
    policy: { key: string; version: number; algorithm: string }; entries: CommonsEntry[] };
  communities: Array<{ id: number; slug: string; name: string; description: string; member_count: number }>;
  profiles: CommonsProfile[];
  moderation: { action_count: number; open_appeals: number };
};

export function CommonsWorkspace() {
  const { runId = "run" } = useParams();
  const [search, setSearch] = useSearchParams();
  const kind = search.get("feed") === "hot" ? "hot" : "chronological";
  const query = useQuery({
    queryKey: ["world-os", runId, "commons", kind],
    queryFn: () => api(`/api/commons?kind=${kind}&limit=60`) as Promise<CommonsProjection>,
    refetchInterval: 5_000,
  });
  if (query.isLoading) return <div className="world-os-loading" aria-label="Loading Agent Commons" />;
  if (query.error) return <div className="world-os-error" role="alert">{query.error.message}</div>;
  const data = query.data!;
  return <section>
    <div className="world-os-heading">
      <div><p className="world-os-kicker">Public information economy</p><h2>Agent Commons</h2></div>
      <dl className="world-os-lineage">
        <div><dt>Tick</dt><dd>{data.tick}</dd></div>
        <div><dt>Policy</dt><dd>{data.feed.policy.key} v{data.feed.policy.version}</dd></div>
        <div><dt>Moderation</dt><dd>{data.moderation.action_count}</dd></div>
        <div><dt>Open appeals</dt><dd>{data.moderation.open_appeals}</dd></div>
      </dl>
    </div>
    <div className="world-os-filters" aria-label="Commons feed policy">
      <button className={`button ${kind === "chronological" ? "button-primary" : ""}`}
        onClick={() => setSearch({ feed: "chronological" })}>Chronological</button>
      <button className={`button ${kind === "hot" ? "button-primary" : ""}`}
        onClick={() => setSearch({ feed: "hot" })}>Hot</button>
      <span className="text-xs text-slate-500">Candidate set {data.feed.candidate_set_hash.slice(0, 12)}…</span>
    </div>
    <div className="world-os-columns">
      <article className="world-os-panel">
        <header><div><p className="world-os-kicker">Deterministic {kind} feed</p><h3>Threads and posts</h3></div><span>{data.feed.entries.length}</span></header>
        <ol className="divide-y divide-mint-300/10">
          {data.feed.entries.map(entry => <li className="p-4" key={entry.id}>
            <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
              <strong className="text-slate-200">{entry.author_name || `Agent ${entry.author_agent_id}`}</strong>
              {entry.author_connected_status && <span className="rounded-full border border-mint-300/20 px-2 py-0.5 text-mint-300">connected · {entry.author_connected_status}</span>}
              <span>t{entry.created_tick} · #{entry.position}</span>
              {entry.community_name && <span>c/{entry.community_name}</span>}
            </div>
            <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-slate-300">{entry.body}</p>
            {entry.moderation_label && <p className="mt-2 text-xs text-gold-300">Label: {entry.moderation_label}</p>}
            <div className="mt-3 flex items-center gap-3 text-xs text-slate-500">
              <span>{entry.reaction_count} reactions</span><span>{entry.reply_count} replies</span>
              <Link to={`/runs/${encodeURIComponent(runId)}/investigations?kind=${encodeURIComponent(entry.causal_observatory.source_kind)}&id=${entry.causal_observatory.source_id}`}>Open causal trace</Link>
            </div>
          </li>)}
          {!data.feed.entries.length && <li className="muted p-5">No public Commons entries yet.</li>}
        </ol>
      </article>
      <div className="space-y-4">
        <article className="world-os-panel">
          <header><div><p className="world-os-kicker">Public groups</p><h3>Communities</h3></div><span>{data.communities.length}</span></header>
          <ul className="divide-y divide-mint-300/10">{data.communities.map(community => <li className="p-4" key={community.id}><strong className="text-sm text-slate-200">c/{community.name}</strong><p className="mt-1 text-xs text-slate-500">{community.description || "No description"}</p><small>{community.member_count} members</small></li>)}</ul>
        </article>
        <article className="world-os-panel">
          <header><div><p className="world-os-kicker">Reputation and identity</p><h3>Profiles</h3></div><span>{data.profiles.length}</span></header>
          <ul className="divide-y divide-mint-300/10">{data.profiles.map(profile => <li className="p-4" key={profile.agent_id}><div className="flex justify-between gap-3"><strong className="text-sm text-slate-200">{profile.display_name}</strong><span className="text-xs text-mint-300">rep {profile.reputation}</span></div><p className="mt-1 text-xs text-slate-500">{profile.occupation || "citizen"}{profile.connected_agent_status ? ` · external ${profile.connected_agent_status}` : ""}</p><p className="mt-2 text-xs text-slate-400">{profile.biography}</p></li>)}</ul>
        </article>
      </div>
    </div>
    <p className="world-os-policy-note">Rendering this human Observatory view creates no simulated impression or belief update. An in-world agent must explicitly read a delivered item before factual exposure occurs.</p>
  </section>;
}

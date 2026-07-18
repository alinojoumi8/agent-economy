import { NavLink, Outlet, useParams, useSearchParams } from "react-router-dom";
import { useProjectionSocket } from "./useProjectionSocket";

const routes = [
  ["overview", "Overview"],
  ["world", "World"],
  ["people", "People"],
  ["organizations", "Organizations"],
  ["markets", "Markets"],
  ["politics-law", "Politics & Law"],
  ["news-communications", "News & Communications"],
  ["investigations", "Investigations"],
  ["experiments", "Experiments"],
];

export function WorkspaceShell() {
  const { runId = "run" } = useParams();
  const [search] = useSearchParams();
  const tick = search.get("tick") || "live";
  const transport = useProjectionSocket(tick !== "live");
  const suffix = search.toString() ? `?${search.toString()}` : "";

  return <div className="world-os-shell min-h-screen bg-ink-950 text-slate-200">
    <a href="#workspace-main" className="world-os-skip">Skip to workspace</a>
    <header className="world-os-topbar">
      <div>
        <p className="world-os-kicker">World OS / Semantics 8</p>
        <h1>Run {runId}</h1>
      </div>
      <div className="world-os-status" aria-live="polite">
        <span className={`world-os-health world-os-health--${transport.status}`} />
        {tick === "live" ? "LIVE" : `Tick ${tick}`}
        <span>Cursor {transport.cursor}</span>
        <span>{transport.status === "stale" ? `Stale: ${transport.staleReason}` : transport.status}</span>
      </div>
    </header>
    <div className="world-os-frame">
      <nav className="world-os-nav" aria-label="World OS workspaces">
        {routes.map(([path, label]) => <NavLink
          key={path}
          to={`/runs/${encodeURIComponent(runId)}/${path}${suffix}`}
          className={({ isActive }) => isActive ? "active" : ""}
        >{label}</NavLink>)}
        <a href="/">Classic Observatory</a>
      </nav>
      <main id="workspace-main" className="world-os-main" tabIndex={-1}>
        {transport.status === "stale" && <div className="world-os-alert" role="alert">
          Live updates are stale. The workspace is refetching the canonical projection.
        </div>}
        <Outlet />
      </main>
    </div>
  </div>;
}

import { useEffect, useRef, useState, type FormEvent } from "react";
import { NavLink, Outlet, useLocation, useNavigate, useParams, useSearchParams } from "react-router";
import worldOsEmblem from "../assets/world-os-emblem.png";
import { CitizenMenu } from "../components/CitizenMenu";
import { useProjectionSocket } from "./useProjectionSocket";

type GlyphName =
  | "overview" | "world" | "people" | "organizations" | "markets"
  | "politics" | "communications" | "commons" | "investigations"
  | "experiments" | "panel" | "search";

type RouteItem = {
  path: string;
  label: string;
  caption: string;
  icon: GlyphName;
};

const routeGroups: Array<{ label: string; items: RouteItem[] }> = [
  { label: "Observe", items: [
    { path: "overview", label: "Live City", caption: "Agents at work, evidence in motion", icon: "overview" },
    { path: "world", label: "World", caption: "Population and environment", icon: "world" },
    { path: "people", label: "People", caption: "Agents, lives, and memory", icon: "people" },
    { path: "organizations", label: "Organizations", caption: "Firms and institutions", icon: "organizations" },
  ] },
  { label: "Flows", items: [
    { path: "markets", label: "Markets", caption: "Goods, capital, and prices", icon: "markets" },
    { path: "politics-law", label: "Politics & Law", caption: "Power and public rules", icon: "politics" },
    { path: "news-communications", label: "Communications", caption: "Authorized information flow", icon: "communications" },
    { path: "commons", label: "Agent Commons", caption: "Public information economy", icon: "commons" },
  ] },
  { label: "Reason", items: [
    { path: "investigations", label: "Investigations", caption: "Trace cause and evidence", icon: "investigations" },
    { path: "experiments", label: "Experiments", caption: "Fork and compare worlds", icon: "experiments" },
  ] },
];

const routes = routeGroups.flatMap(group => group.items.map(item => ({ ...item, group: group.label })));

function Glyph({ name }: { name: GlyphName }) {
  let paths;
  switch (name) {
    case "overview": paths = <><rect x="3" y="3" width="7" height="7" rx="2" /><rect x="14" y="3" width="7" height="7" rx="2" /><rect x="3" y="14" width="7" height="7" rx="2" /><path d="M14 17.5h7M17.5 14v7" /></>; break;
    case "world": paths = <><circle cx="12" cy="12" r="9" /><path d="M3.5 9h17M3.5 15h17M12 3c2.2 2.5 3.3 5.5 3.3 9S14.2 18.5 12 21M12 3C9.8 5.5 8.7 8.5 8.7 12s1.1 6.5 3.3 9" /></>; break;
    case "people": paths = <><circle cx="9" cy="8" r="3" /><circle cx="17" cy="9" r="2.5" /><path d="M3.5 20c.4-4 2.2-6 5.5-6s5.1 2 5.5 6M14 15.5c.8-.7 1.8-1 3-1 2.4 0 3.7 1.5 4 4.5" /></>; break;
    case "organizations": paths = <><path d="M4 21V6l8-3 8 3v15M8 8h2M14 8h2M8 12h2M14 12h2M8 16h2M14 16h2M10 21v-3h4v3" /></>; break;
    case "markets": paths = <><path d="M4 20V10M10 20V4M16 20v-7M22 20V7M2 20h21" /></>; break;
    case "politics": paths = <><path d="M12 3v18M5 6h14M7 6l-4 8h8L7 6ZM17 6l-4 8h8l-4-8ZM8 21h8" /></>; break;
    case "communications": paths = <><path d="M4 5h16v11H9l-5 4V5Z" /><path d="M8 9h8M8 12h5" /></>; break;
    case "commons": paths = <><circle cx="12" cy="5" r="2.5" /><circle cx="5" cy="17" r="2.5" /><circle cx="19" cy="17" r="2.5" /><path d="m10.8 7.2-4.6 7.6M13.2 7.2l4.6 7.6M7.5 17h9" /></>; break;
    case "investigations": paths = <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m15.5 15.5 5 5M8 10.5h5M10.5 8v5" /></>; break;
    case "experiments": paths = <><path d="M9 3h6M10 3v6l-6 10a1.4 1.4 0 0 0 1.2 2h13.6a1.4 1.4 0 0 0 1.2-2L14 9V3" /><path d="M7.5 15h9" /></>; break;
    case "panel": paths = <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16M5.5 8h1M5.5 12h1" /></>; break;
    default: paths = <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m15.5 15.5 5 5" /></>;
  }
  return <svg className="world-os-glyph" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths}</svg>;
}

export function WorkspaceShell() {
  const { runId = "run" } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const [search, setSearch] = useSearchParams();
  const tick = search.get("tick") || "live";
  const transport = useProjectionSocket(tick !== "live");
  const [railCollapsed, setRailCollapsed] = useState(false);
  const [commandOpen, setCommandOpen] = useState(false);
  const [commandQuery, setCommandQuery] = useState("");
  const [draftTick, setDraftTick] = useState(tick === "live" ? "" : tick);
  const commandInput = useRef<HTMLInputElement>(null);
  const activeRoute = routes.find(route => location.pathname.includes("/" + route.path)) || routes[0];
  const tickSuffix = tick === "live" ? "" : "?tick=" + encodeURIComponent(tick);
  const filteredRoutes = routes.filter(route =>
    (route.label + " " + route.caption + " " + route.group).toLowerCase().includes(commandQuery.trim().toLowerCase()),
  );

  useEffect(() => setDraftTick(tick === "live" ? "" : tick), [tick]);
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommandOpen(value => !value);
        setCommandQuery("");
      }
      if (event.key === "Escape") setCommandOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);
  useEffect(() => {
    if (commandOpen) window.requestAnimationFrame(() => commandInput.current?.focus());
  }, [commandOpen]);

  const workspaceUrl = (path: string) =>
    "/runs/" + encodeURIComponent(runId) + "/" + path + tickSuffix;
  const setTick = (value: string | null) => {
    const next = new URLSearchParams(search);
    if (value) next.set("tick", value); else next.delete("tick");
    setSearch(next, { replace: true });
  };
  const submitTick = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const value = draftTick.replace(/\D/g, "");
    if (value) setTick(value);
  };
  const openWorkspace = (route: RouteItem) => {
    setCommandOpen(false);
    navigate(workspaceUrl(route.path));
  };

  return <div className={"world-os-shell min-h-screen text-slate-200" + (railCollapsed ? " world-os-shell--collapsed" : "")}>
    <a href="#workspace-main" className="world-os-skip">Skip to workspace</a>
    <aside className="world-os-rail">
      <div className="world-os-brand">
        <img src={worldOsEmblem} alt="" />
        <div className="world-os-brand-copy"><strong>WORLD OS</strong><span>Agent Economy</span></div>
        <button className="world-os-rail-toggle" type="button" onClick={() => setRailCollapsed(value => !value)} aria-label={railCollapsed ? "Expand workspace rail" : "Collapse workspace rail"} aria-pressed={railCollapsed}>
          <Glyph name="panel" />
        </button>
      </div>
      <nav className="world-os-nav" aria-label="World OS workspaces">
        {routeGroups.map(group => <div className="world-os-nav-group" key={group.label}>
          <p className="world-os-nav-group-title">{group.label}</p>
          <div className="world-os-nav-group-items">
            {group.items.map(route => <NavLink
              key={route.path}
              to={workspaceUrl(route.path)}
              aria-label={route.label}
              title={railCollapsed ? route.label : undefined}
              className={({ isActive }) => "world-os-nav-link" + (isActive ? " active" : "")}
            >
              <span className="world-os-nav-icon"><Glyph name={route.icon} /></span>
              <span className="world-os-nav-copy"><strong>{route.label}</strong><small>{route.caption}</small></span>
              <span className="world-os-nav-indicator" aria-hidden="true" />
            </NavLink>)}
          </div>
        </div>)}
      </nav>
      <div className="world-os-rail-footer">
        <a href="/"><span className="world-os-rail-orbit" aria-hidden="true" /><span className="world-os-rail-footer-copy"><strong>Classic Observatory</strong><small>Open full legacy surface</small></span></a>
      </div>
    </aside>

    <section className="world-os-workbench">
      <header className="world-os-topbar">
        <div className="world-os-context">
          <p className="world-os-kicker">{activeRoute.group} workspace</p>
          <div><h1>{activeRoute.label}</h1><span className="world-os-run-pill" title={runId}>Run {runId}</span></div>
        </div>
        <CitizenMenu runId={runId} variant="dropdown" />
        <div className="world-os-top-actions">
          <form className="world-os-tick-control" onSubmit={submitTick} aria-label="Simulation tick travel">
            <button type="button" className={tick === "live" ? "active" : ""} onClick={() => setTick(null)} aria-pressed={tick === "live"}>Live</button>
            <label><span className="world-os-visually-hidden">Inspect tick</span><input aria-label="Inspect tick" inputMode="numeric" value={draftTick} onChange={event => setDraftTick(event.target.value.replace(/\D/g, ""))} placeholder="Tick" /></label>
            <button type="submit" aria-label="Go to tick">Go</button>
          </form>
          <button className="world-os-command-button" type="button" onClick={() => { setCommandOpen(true); setCommandQuery(""); }} aria-label="Open command menu" aria-haspopup="dialog">
            <Glyph name="search" /><span>Navigate</span><kbd>Ctrl K</kbd>
          </button>
          <div className="world-os-transport" aria-live="polite">
            <span className={"world-os-health world-os-health--" + transport.status} aria-hidden="true" />
            <div><strong>{tick === "live" ? "Live sync" : "Historical"}</strong><small>{transport.status} · cursor {transport.cursor}</small></div>
          </div>
        </div>
      </header>
      <main id="workspace-main" className="world-os-main" tabIndex={-1}>
        {transport.status === "stale" && <div className="world-os-alert" role="alert">
          Live updates are stale. The workspace is refetching the canonical projection: {transport.staleReason}.
        </div>}
        <Outlet />
      </main>
    </section>

    {commandOpen && <div className="world-os-command-backdrop" onMouseDown={event => { if (event.currentTarget === event.target) setCommandOpen(false); }}>
      <section className="world-os-command" role="dialog" aria-modal="true" aria-labelledby="world-os-command-title">
        <header><div><p className="world-os-kicker">World OS command</p><h2 id="world-os-command-title">Go to a workspace</h2></div><button type="button" onClick={() => setCommandOpen(false)} aria-label="Close command menu">Esc</button></header>
        <label className="world-os-command-search"><Glyph name="search" /><input ref={commandInput} value={commandQuery} onChange={event => setCommandQuery(event.target.value)} onKeyDown={event => {
          if (event.key === "Enter" && filteredRoutes[0]) { event.preventDefault(); openWorkspace(filteredRoutes[0]); }
        }} placeholder="Search people, markets, evidence…" /></label>
        <div className="world-os-command-results">
          {filteredRoutes.map(route => <button type="button" key={route.path} onClick={() => openWorkspace(route)}>
            <span className="world-os-nav-icon"><Glyph name={route.icon} /></span>
            <span><strong>{route.label}</strong><small>{route.caption}</small></span>
            <span className="world-os-command-arrow" aria-hidden="true">↗</span>
          </button>)}
          {!filteredRoutes.length && <p className="world-os-command-empty">No workspace matches “{commandQuery}”.</p>}
        </div>
        <footer><span><kbd>Enter</kbd> open</span><span><kbd>Esc</kbd> close</span><span>Tick {tick}</span></footer>
      </section>
    </div>}
  </div>;
}

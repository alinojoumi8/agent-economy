import { useEffect, useReducer, useState } from "react";
import { api, shortKind } from "../api";
import { conversationSearchPath, normalizeConversationQuery } from "../conversations";
import { eventMatchesRegion } from "../observatoryInteraction";
import { inspectionButtonProps, useObservatoryInteraction } from "./ObservatoryInteraction";
import { Badge, Empty, Panel } from "./ui";

export function NewsPanel({ news }) {
  const { inspect } = useObservatoryInteraction();
  return (
    <Panel title="Newsroom" eyebrow="Event-grounded stories" className="col-span-full md:col-span-6 xl:col-span-4">
      <div className="scrollbar max-h-[390px] overflow-y-auto px-4">
        {news.length ? news.map(article => <article key={article.id} className="border-b border-mint-300/10 py-3 last:border-0">
          <div className="mb-1 flex items-center gap-2"><Badge>{article.outlet_name || "Outlet"}</Badge><span className="tabular text-[10px] text-slate-600">day {article.tick}</span></div>
          <h3 className="text-sm font-semibold leading-snug text-slate-200"><button className="inspectable-card !inline !w-auto text-left" {...inspectionButtonProps(
            inspect,
            { kind: "news", id: article.id, title: article.headline },
            article,
            `Inspect news article ${article.headline}`,
          )}>{article.headline}</button></h3>
          <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-slate-500">{article.body}</p>
        </article>) : <Empty>Stories publish after the newsroom has events to cover.</Empty>}
      </div>
    </Panel>
  );
}

export function ConversationsPanel({ conversations }) {
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");

  useEffect(() => {
    const normalized = normalizeConversationQuery(query);
    if (!normalized) {
      setMatches(null);
      setSearching(false);
      setSearchError("");
      return undefined;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setSearching(true);
      api(conversationSearchPath(normalized)).then(items => {
        if (!cancelled) {
          setMatches(items);
          setSearchError("");
        }
      }).catch(reason => {
        if (!cancelled) {
          setMatches([]);
          setSearchError(reason instanceof Error ? reason.message : String(reason));
        }
      }).finally(() => {
        if (!cancelled) setSearching(false);
      });
    }, 200);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query]);

  const visible = matches ?? conversations;
  return (
    <Panel title="Conversations" eyebrow="Rumor transmission layer" className="col-span-full md:col-span-6 xl:col-span-4">
      <div className="border-b border-mint-300/10 px-4 py-3">
        <label className="block text-[10px] uppercase tracking-wider text-slate-500" htmlFor="conversation-search">Search stored conversations</label>
        <div className="mt-1 flex items-center gap-2">
          <input id="conversation-search" type="search" value={query}
            onChange={event => setQuery(event.target.value)} maxLength={200}
            placeholder="Message, speaker, or topic" className="field !py-2" />
          {query && <button className="button !min-h-9 !px-3" onClick={() => setQuery("")}>Clear</button>}
        </div>
        {searching && <p className="mt-1 text-[10px] text-slate-500" role="status">Searching the full run...</p>}
        {searchError && <p className="mt-1 text-[10px] text-coral-300" role="alert">Search failed: {searchError}</p>}
      </div>
      <div className="scrollbar max-h-[390px] overflow-y-auto px-4">
        {visible.length ? visible.map(conversation => <article key={conversation.id} className="border-b border-mint-300/10 py-3 last:border-0">
          <div className="mb-2 text-[10px] uppercase tracking-wider text-slate-600">Day {conversation.tick} · {conversation.messages.length} turns</div>
          {conversation.topic && <div className="mb-2 text-[10px] text-slate-500">{conversation.topic}</div>}
          <div className="space-y-1.5">{conversation.messages.map((message, index) => <p key={`${conversation.id}-${index}`} className="text-xs leading-relaxed"><strong className="mr-1.5 text-mint-300">{message.name || `Agent ${message.agent_id}`}</strong><span className="text-slate-400">{message.text}</span></p>)}</div>
        </article>) : <Empty>{query ? "No stored conversation matches that search." : "Connected agents begin talking during each evening phase."}</Empty>}
      </div>
    </Panel>
  );
}

export function eventPanelReducer(state, action) {
  if (action.type === "toggle-raw") return { ...state, raw: !state.raw };
  if (action.type === "toggle-show-all") return { ...state, showAll: !state.showAll };
  if (action.type === "region-changed") return { ...state, showAll: false };
  return state;
}

export function EventsPanel({ events, onShock = null }) {
  const { regionFocus, inspect } = useObservatoryInteraction();
  const [{ raw, showAll }, dispatch] = useReducer(eventPanelReducer, { raw: false, showAll: false });
  useEffect(() => dispatch({ type: "region-changed" }), [regionFocus?.regionId]);
  return <EventsPanelView events={events} onShock={onShock} regionFocus={regionFocus} inspect={inspect}
    raw={raw} showAll={showAll}
    onToggleRaw={() => dispatch({ type: "toggle-raw" })}
    onToggleShowAll={() => dispatch({ type: "toggle-show-all" })} />;
}

export function EventsPanelView({ events, onShock, regionFocus, inspect, raw, showAll, onToggleRaw, onToggleShowAll }) {
  const related = regionFocus
    ? events.filter(event => eventMatchesRegion(event, regionFocus.regionId))
    : events;
  const visible = regionFocus && !showAll ? related : events;
  return (
    <Panel title="Event spine" eyebrow="If it is not here, it did not happen" className="col-span-full xl:col-span-4" action={<div className="flex gap-1"><button type="button" className="button !min-h-7 !px-2 !py-1" onClick={onToggleRaw}>{raw ? "Human" : "Raw"}</button>{regionFocus && <button type="button" className="button !min-h-7 !px-2 !py-1" aria-pressed={showAll}
      onClick={onToggleShowAll}>{showAll ? "Related only" : "Show all"}</button>}{onShock && <button type="button" className="button !min-h-7 !px-2 !py-1" onClick={onShock}>Shock</button>}</div>}>
      <div className="scrollbar max-h-[390px] overflow-y-auto px-4 font-mono">
        {visible.length ? visible.map(event => <article key={event.id} className="grid grid-cols-[2.5rem_1fr] gap-2 border-b border-mint-300/[.07] py-2 text-[11px] last:border-0">
          <span className="tabular text-slate-600">d{event.tick}</span>
          <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><button className="inspectable-card !inline !w-auto text-left" {...inspectionButtonProps(
            inspect,
            { kind: "event", id: event.id, title: shortKind(event.kind) },
            event,
            `Inspect event ${shortKind(event.kind)} from day ${event.tick}`,
          )}><span className="font-sans font-semibold text-slate-300">{shortKind(event.kind)}</span></button>{event.importance >= 3 && <Badge tone="warn">material</Badge>}</div>{raw && <pre className="mt-1 overflow-x-auto whitespace-pre-wrap text-[10px] text-slate-500">{JSON.stringify(event.payload, null, 2)}</pre>}</div>
        </article>) : regionFocus
          ? <Empty>No region-tagged events for {regionFocus.regionName} appear in the current event window.</Empty>
          : <Empty>Events stream here as the world advances.</Empty>}
      </div>
    </Panel>
  );
}

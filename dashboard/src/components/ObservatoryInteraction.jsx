import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import { inspectionPresentation, makeInspection, nextRegionFocus, normalizeRegion } from "../observatoryInteraction";

const NOOP = () => {};
const FALLBACK = {
  regionFocus: null, inspection: null, announcement: "",
  selectRegion: NOOP, clearRegion: NOOP, inspect: NOOP, closeInspection: NOOP,
};
export const ObservatoryInteractionContext = createContext(FALLBACK);

export function useObservatoryInteraction() {
  return useContext(ObservatoryInteractionContext);
}

export function inspectionButtonProps(inspect, reference, snapshot, ariaLabel) {
  return {
    type: "button",
    "aria-label": ariaLabel,
    onClick: () => inspect(reference, snapshot),
  };
}

export function RegionFocusBar({ regionFocus, onClear }) {
  if (!regionFocus) return null;
  return <aside className="observatory-focus-bar" aria-label="Active region filter"
    onKeyDown={event => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      onClear();
    }}>
    <div>
      <div className="eyebrow">Regional focus</div>
      <strong>{regionFocus.regionName}</strong>
      <p>Firms, agents, and region-tagged events are filtered. Other panels remain global.</p>
    </div>
    <button type="button" className="button" onClick={onClear}
      aria-label={`Clear ${regionFocus.regionName} region filter`}>Clear region</button>
  </aside>;
}

function renderValue(value) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") {
    try { return JSON.stringify(value, null, 2); }
    catch { return "Unable to serialize this snapshot."; }
  }
  return String(value);
}

export function InspectorDrawer({ inspection, data, onClose, headingRef }) {
  if (!inspection) return null;
  const view = inspectionPresentation(inspection, data);
  return <aside className="observatory-drawer" aria-label="Observatory inspector">
    <header>
      <div>
        <div className="eyebrow">Inspector</div>
        <h2 ref={headingRef} tabIndex="-1">{view.title}</h2>
        {view.subtitle && <p>{view.subtitle}</p>}
      </div>
      <button type="button" className="button" onClick={onClose} aria-label="Close inspector">Close</button>
    </header>
    {view.lastObserved && <div className="observatory-last-observed">Last observed · this item is outside the current live window.</div>}
    {view.narrative && <p className="observatory-drawer-narrative">{view.narrative}</p>}
    {view.fields.length > 0 && <dl>{view.fields.map(field => <div key={field.label}>
      <dt>{field.label}</dt><dd>{field.value}</dd>
    </div>)}</dl>}
    <details><summary>Raw data</summary><pre>{renderValue(view.raw)}</pre></details>
  </aside>;
}

export function ObservatoryInteractionProvider({ data, children }) {
  const [regionFocus, setRegionFocus] = useState(null);
  const [inspection, setInspection] = useState(null);
  const [announcement, setAnnouncement] = useState("");
  const triggerRef = useRef(null);
  const headingRef = useRef(null);

  function clearRegion() {
    setRegionFocus(null);
    setAnnouncement("Region filter cleared.");
  }

  function selectRegion(region) {
    setRegionFocus(current => {
      const next = nextRegionFocus(current, region);
      setAnnouncement(next ? `${next.regionName} region filter applied.` : "Region filter cleared.");
      return next;
    });
  }

  function inspect(reference, fallbackSnapshot) {
    triggerRef.current = typeof document === "undefined" ? null : document.activeElement;
    setInspection(makeInspection(reference, fallbackSnapshot));
  }

  function closeInspection() {
    setInspection(null);
    const trigger = triggerRef.current;
    triggerRef.current = null;
    if (trigger?.isConnected) requestAnimationFrame(() => trigger.focus());
  }

  useEffect(() => {
    if (!inspection) return undefined;
    headingRef.current?.focus();
    const onKeyDown = event => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      closeInspection();
    };
    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [inspection]);

  useEffect(() => {
    if (!regionFocus) return;
    const regions = Array.isArray(data?.v2?.map?.regions) ? data.v2.map.regions : [];
    const current = regions.find(region => Number(region.id) === regionFocus.regionId);
    if (!current) {
      setRegionFocus(null);
      setAnnouncement(`${regionFocus.regionName} is no longer available; the region filter was cleared.`);
      return;
    }
    const normalized = normalizeRegion(current);
    if (normalized && (normalized.regionKey !== regionFocus.regionKey || normalized.regionName !== regionFocus.regionName)) {
      setRegionFocus(normalized);
    }
  }, [data?.v2?.map?.regions, regionFocus]);

  const value = useMemo(() => ({
    regionFocus, inspection, announcement, selectRegion, clearRegion, inspect, closeInspection,
  }), [regionFocus, inspection, announcement]);

  return <ObservatoryInteractionContext.Provider value={value}>
    {children}
    <InspectorDrawer inspection={inspection} data={data} onClose={closeInspection} headingRef={headingRef} />
    <div className="sr-only" aria-live="polite" aria-atomic="true">{announcement}</div>
  </ObservatoryInteractionContext.Provider>;
}

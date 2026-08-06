import React, { useEffect } from "react";
import { createRoot } from "react-dom/client";

import { useObservatory } from "../../../src/hooks/useObservatory.js";

function ObservatoryHarness() {
  const observatory = useObservatory();
  useEffect(() => {
    window.__observatoryHarness = observatory;
  }, [observatory]);
  return <main>
    <output aria-label="Observatory connection">{observatory.connected ? "connected" : "disconnected"}</output>
    <output aria-label="Observatory loading">{observatory.loading ? "loading" : "ready"}</output>
    <output aria-label="Observatory freshness">{observatory.statusFresh ? "fresh" : "stale"}</output>
  </main>;
}

export function mountObservatoryHarness(container) {
  return createRoot(container).render(<ObservatoryHarness />);
}

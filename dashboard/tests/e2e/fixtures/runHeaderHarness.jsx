import React from "react";
import { createRoot } from "react-dom/client";

import { RunHeader } from "../../../src/components/RunHeader.jsx";

export function mountRunHeaderHarness(container) {
  const requests = [];
  const resolvers = new Map();
  const act = path => {
    requests.push(path);
    return new Promise(resolve => {
      const queued = resolvers.get(path) || [];
      queued.push(resolve);
      resolvers.set(path, queued);
    });
  };
  window.__runHeaderHarness = {
    requests,
    resolve(path) {
      const queued = resolvers.get(path) || [];
      const resolve = queued.shift();
      if (!resolve) throw new Error(`No pending request for ${path}`);
      resolve({ ok: true });
    },
  };
  return createRoot(container).render(<RunHeader
    status={{
      run_id: "control-test", tick: 4, status: "running", running: true,
      speed_delay_s: 0, governor: {},
    }}
    participant={{}}
    connected
    loading={false}
    statusFresh
    act={act}
    onShock={() => {}}
    onReplay={() => {}}
  />);
}

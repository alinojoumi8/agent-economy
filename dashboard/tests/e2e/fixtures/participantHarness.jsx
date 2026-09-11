import React from "react";
import { createRoot } from "react-dom/client";

import { ParticipantPanel } from "../../../src/components/ParticipantPanel";

export function mountParticipantHarness(container, initialParticipant, options = {}) {
  const root = createRoot(container);
  let participant = initialParticipant;
  const requests = [];
  const payloads = [];
  const act = async (path, payload) => {
    requests.push(path);
    payloads.push(payload);
    if (options.acceptActions) return {};
    throw new Error(path.endsWith("/release") ? "release rejected" : "queue rejected");
  };
  const render = () => root.render(
    <ParticipantPanel participant={participant} act={act} />,
  );
  render();
  return {
    requests,
    payloads,
    update(patch) {
      participant = { ...participant, ...patch };
      render();
    },
  };
}

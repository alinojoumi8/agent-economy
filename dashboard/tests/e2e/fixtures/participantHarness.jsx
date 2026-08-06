import React from "react";
import { createRoot } from "react-dom/client";

import { ParticipantPanel } from "../../../src/components/ParticipantPanel";

export function mountParticipantHarness(container, initialParticipant) {
  const root = createRoot(container);
  let participant = initialParticipant;
  const requests = [];
  const act = async path => {
    requests.push(path);
    throw new Error(path.endsWith("/release") ? "release rejected" : "queue rejected");
  };
  const render = () => root.render(
    <ParticipantPanel participant={participant} act={act} />,
  );
  render();
  return {
    requests,
    update(patch) {
      participant = { ...participant, ...patch };
      render();
    },
  };
}

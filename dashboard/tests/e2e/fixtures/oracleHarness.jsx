import React from "react";
import { createRoot } from "react-dom/client";

import { OraclePanel } from "../../../src/components/OracleAndCost";

export function mountOracleHarness(container) {
  const act = async (_path, { question }) => {
    if (question === "First forecast") {
      return { p: 0.6, reasoning: "Initial evidence", drivers: [] };
    }
    throw new Error("oracle unavailable");
  };
  createRoot(container).render(
    <OraclePanel oracle={{ predictions: [], scorecard: {} }} act={act} />,
  );
}

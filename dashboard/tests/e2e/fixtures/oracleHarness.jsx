import React from "react";
import { createRoot } from "react-dom/client";

import { OraclePanel } from "../../../src/components/OracleAndCost";

export function mountOracleHarness(container) {
  const act = async () => {
    throw new Error("oracle unavailable");
  };
  createRoot(container).render(
    <OraclePanel oracle={{ predictions: [], scorecard: {} }} act={act} />,
  );
}

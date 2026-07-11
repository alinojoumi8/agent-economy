import assert from "node:assert/strict";
import test from "node:test";

import { calibrationView } from "../src/calibration.js";


test("calibrationView exposes empty and failed scopes safely", () => {
  assert.deepEqual(calibrationView(null), {
    empty: true, n: 0, runs: null, brier: null, naiveBrier: null,
    reliability: null, resolution: null, uncertainty: null, baseRate: null,
    beatsNaive: null, points: [],
  });
  assert.equal(calibrationView({ error: "offline" }).empty, true);
});


test("calibrationView maps pooled decomposition and clamps chart points", () => {
  const view = calibrationView({
    n: 12, runs: 3, brier: 0.18, naive_brier: 0.25,
    reliability: 0.03, resolution: 0.08, uncertainty: 0.23,
    base_rate: 0.4, beats_naive: true,
    bins: [
      { bin: "0.1-0.2", n: 5, mean_forecast: -0.2, observed: 0.25 },
      { bin: "0.8-0.9", n: 7, mean_forecast: 0.85, observed: 1.2 },
    ],
  });

  assert.equal(view.empty, false);
  assert.equal(view.n, 12);
  assert.equal(view.runs, 3);
  assert.equal(view.beatsNaive, true);
  assert.deepEqual(view.points.map(point => [point.forecast, point.observed]), [
    [0, 0.25], [0.85, 1],
  ]);
});

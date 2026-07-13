import assert from "node:assert/strict";
import test from "node:test";

import { rollingSumSeries } from "../src/metrics.js";


test("rollingSumSeries keeps periodic payroll visible between paydays", () => {
  const series = Array.from({ length: 41 }, (_, index) => ({
    tick: index + 1,
    value: index === 9 || index === 39 ? 16_100 : 0,
  }));

  const rolling = rollingSumSeries(series, 30);

  assert.equal(rolling.find(point => point.tick === 39).value, 16_100);
  assert.equal(rolling.find(point => point.tick === 40).value, 16_100);
  assert.equal(rolling.find(point => point.tick === 41).value, 16_100);
  assert.deepEqual(series.at(-1), { tick: 41, value: 0 });
});


test("rollingSumSeries expires values by tick even when observations are sparse", () => {
  const rolling = rollingSumSeries([
    { tick: 10, value: 100 },
    { tick: 20, value: 20 },
    { tick: 39, value: 5 },
    { tick: 40, value: 7 },
  ], 30);

  assert.deepEqual(rolling.map(point => point.value), [100, 120, 125, 32]);
});


test("rollingSumSeries handles missing and invalid values safely", () => {
  assert.deepEqual(rollingSumSeries(null), []);
  assert.deepEqual(rollingSumSeries([
    { tick: 1, value: "10" },
    { tick: 2, value: "not-a-number" },
  ], 0).map(point => point.value), [10, 0]);
});

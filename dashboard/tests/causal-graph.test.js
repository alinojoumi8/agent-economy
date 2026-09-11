import assert from "node:assert/strict";
import test from "node:test";
import { createServer } from "vite";

test("causal graph zoom steps land exactly on their bounds", async () => {
  const vite = await createServer({
    appType: "custom", logLevel: "silent", server: { middlewareMode: true },
  });
  try {
    const { clampGraphZoom } = await vite.ssrLoadModule("/src/visualizations/CausalGraph.tsx");

    /* Four .2 steps in floating point give 1.7999999999999998: a readout of
       180% beside a + button that is still enabled and does nothing. */
    let zoom = 1;
    for (let step = 0; step < 4; step += 1) zoom = clampGraphZoom(zoom + .2);
    assert.equal(zoom, 1.8);
    assert.equal(clampGraphZoom(zoom + .2), 1.8);

    let out = 1;
    for (let step = 0; step < 2; step += 1) out = clampGraphZoom(out - .2);
    assert.equal(out, .7);
    assert.equal(clampGraphZoom(out - .2), .7);

    assert.equal(clampGraphZoom(1.2 + .2), 1.4);
    assert.equal(clampGraphZoom(1), 1);
  } finally {
    await vite.close();
  }
});

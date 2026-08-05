import assert from "node:assert/strict";
import test from "node:test";
import { createServer } from "vite";


test("an in-flight Step is shown as running while Pause and Stop remain available", async () => {
  const vite = await createServer({
    appType: "custom",
    logLevel: "silent",
    server: { middlewareMode: true },
  });
  try {
    const { runControlState } = await vite.ssrLoadModule("/src/components/RunHeader.jsx");

    assert.deepEqual(runControlState?.({ status: "paused", running: false }, "step"), {
      running: true,
      displayStatus: "running",
      pauseDisabled: false,
      stopDisabled: false,
    });
  } finally {
    await vite.close();
  }
});

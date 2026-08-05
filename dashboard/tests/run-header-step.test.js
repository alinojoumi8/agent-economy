import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { createServer } from "vite";

const observatorySource = readFileSync(
  new URL("../src/components/Observatory.jsx", import.meta.url), "utf8",
);


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

test("all terminal and unknown run states fail closed across controls", async () => {
  const vite = await createServer({
    appType: "custom",
    logLevel: "silent",
    server: { middlewareMode: true },
  });
  try {
    const { isTerminalRunStatus, runControlState } = await vite.ssrLoadModule(
      "/src/components/RunHeader.jsx",
    );
    for (const status of [
      "halted", "completed", "failed", "finished", "stopped", "snapshot_failed",
    ]) {
      assert.equal(isTerminalRunStatus?.(status), true, status);
      assert.equal(runControlState({ status, running: false }).stopDisabled, true, status);
    }
    for (const status of ["created", "paused", "running", "active"]) {
      assert.equal(isTerminalRunStatus?.(status), false, status);
    }
    assert.match(observatorySource, /const terminal = isTerminalRunStatus\(status\?\.status\)/);
    assert.match(observatorySource, /const dayZero = [^;]+&& !terminal;/);
  } finally {
    await vite.close();
  }
});

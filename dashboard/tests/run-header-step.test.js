import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
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
    const terminalStatuses = [
      "halted", "completed", "failed", "finished", "stopped", "snapshot_failed",
    ];
    for (const status of terminalStatuses) {
      assert.equal(isTerminalRunStatus?.(status), true, status);
    }
    for (const status of [...terminalStatuses, "unrecognized"]) {
      for (const running of [false, true]) {
        assert.equal(
          runControlState({ status, running }).stopDisabled,
          true,
          `${status}:${running}`,
        );
      }
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

test("missing or stale status disables every simulation control", async () => {
  const vite = await createServer({
    appType: "custom",
    logLevel: "silent",
    server: { middlewareMode: true },
  });
  try {
    const { RunHeader } = await vite.ssrLoadModule("/src/components/RunHeader.jsx");
    const markup = renderToStaticMarkup(React.createElement(RunHeader, {
      status: { tick: 7, status: "paused", running: false, governor: {} },
      statusFresh: false,
      participant: {}, connected: true, loading: false,
      act: async () => {}, onShock: () => {}, onReplay: () => {},
    }));
    for (const label of ["Run", "Step", "Pause", "Stop + report"]) {
      const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      assert.match(markup, new RegExp(`<button[^>]*disabled=""[^>]*>[^<]*${escaped}`));
    }
    assert.match(markup, /<select[^>]*disabled=""[^>]*id="run-speed"|<select[^>]*id="run-speed"[^>]*disabled=""/);
    assert.match(observatorySource, /statusFresh/);
  } finally {
    await vite.close();
  }
});

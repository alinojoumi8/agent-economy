import assert from "node:assert/strict";
import test from "node:test";

import React from "react";
import { act, create } from "react-test-renderer";
import { createServer } from "vite";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances = [];

  constructor(url) {
    this.url = url;
    this.readyState = FakeWebSocket.CONNECTING;
    this.listeners = new Map();
    FakeWebSocket.instances.push(this);
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  dispatch(type, event = {}) {
    for (const listener of this.listeners.get(type) || []) listener(event);
  }

  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.dispatch("open");
  }

  fail() {
    this.dispatch("error");
  }

  close() {
    if (this.readyState === FakeWebSocket.CONNECTING) {
      this.readyState = FakeWebSocket.CLOSING;
      this.dispatch("error");
      this.readyState = FakeWebSocket.CLOSED;
      this.dispatch("close", { code: 1006, wasClean: false, reason: "" });
      return;
    }
    this.readyState = FakeWebSocket.CLOSED;
  }

  send() {}
}

test("StrictMode ignores failures from the disposed socket but logs an active socket failure", async () => {
  const originalWindow = globalThis.window;
  const originalWebSocket = globalThis.WebSocket;
  const originalFetch = globalThis.fetch;
  const originalConsole = {
    error: console.error,
    info: console.info,
    warn: console.warn,
  };
  const records = [];
  let nextTimer = 1;
  const capture = (message) => {
    try {
      const record = JSON.parse(message);
      if (record.event?.startsWith("dashboard.websocket.")) records.push(record);
    } catch {
      // Ignore React's react-test-renderer deprecation notice.
    }
  };
  globalThis.window = {
    location: { protocol: "http:", host: "127.0.0.1:4173" },
    setInterval: () => nextTimer++,
    clearInterval: () => {},
  };
  globalThis.WebSocket = FakeWebSocket;
  globalThis.fetch = async () => ({
    ok: true,
    status: 200,
    statusText: "OK",
    json: async () => ({}),
  });
  console.error = capture;
  console.info = capture;
  console.warn = capture;
  FakeWebSocket.instances = [];

  const vite = await createServer({ appType: "custom", logLevel: "silent", server: { middlewareMode: true } });
  let renderer;
  try {
    const { useObservatory } = await vite.ssrLoadModule("/src/hooks/useObservatory.js");
    const Harness = () => {
      useObservatory();
      return null;
    };
    await act(async () => {
      renderer = create(React.createElement(React.StrictMode, null, React.createElement(Harness)));
    });

    assert.equal(FakeWebSocket.instances.length, 2, "StrictMode should create a replacement socket");
    const activeSocket = FakeWebSocket.instances[1];
    await act(async () => { activeSocket.open(); });
    await act(async () => { activeSocket.fail(); });

    assert.deepEqual(records.map(record => record.event), [
      "dashboard.websocket.connected",
      "dashboard.websocket.failed",
    ]);
  } finally {
    if (renderer) await act(async () => { renderer.unmount(); });
    await vite.close();
    globalThis.window = originalWindow;
    globalThis.WebSocket = originalWebSocket;
    globalThis.fetch = originalFetch;
    console.error = originalConsole.error;
    console.info = originalConsole.info;
    console.warn = originalConsole.warn;
  }
});

import assert from "node:assert/strict";
import test from "node:test";
import { createServer } from "vite";

async function withObservatoryModule(callback) {
  const vite = await createServer({
    appType: "custom", logLevel: "silent", server: { middlewareMode: true },
  });
  try {
    return await callback(await vite.ssrLoadModule("/src/hooks/useObservatory.js"));
  } finally {
    await vite.close();
  }
}

test("observatory request settlement retains successes beside failed panels", async () => {
  await withObservatoryModule(async ({ settleObservatoryRequests }) => {
    const result = await settleObservatoryRequests({
      status: Promise.resolve({ tick: 7 }),
      news: Promise.reject(new Error("news unavailable")),
      metrics: Promise.resolve({ output: [1, 2] }),
    });
    assert.deepEqual(result.values, {
      status: { tick: 7 },
      metrics: { output: [1, 2] },
    });
    assert.deepEqual(result.errors, [{ key: "news", message: "news unavailable" }]);
  });
});

test("observatory reconnect delay is exponential and bounded", async () => {
  await withObservatoryModule(async ({ observatoryReconnectDelay }) => {
    assert.equal(observatoryReconnectDelay(0), 500);
    assert.equal(observatoryReconnectDelay(1), 1_000);
    assert.equal(observatoryReconnectDelay(4), 8_000);
    assert.equal(observatoryReconnectDelay(5), 10_000);
    assert.equal(observatoryReconnectDelay(100), 10_000);
    assert.equal(observatoryReconnectDelay(-3), 500);
  });
});

test("observatory refresh deadlines abort and can be cancelled", async () => {
  await withObservatoryModule(async ({ observatoryRefreshDeadline }) => {
    const expiring = observatoryRefreshDeadline(1);
    await new Promise(resolve => setTimeout(resolve, 10));
    assert.equal(expiring.signal.aborted, true);

    const cancelled = observatoryRefreshDeadline(1);
    cancelled.cancel();
    await new Promise(resolve => setTimeout(resolve, 10));
    assert.equal(cancelled.signal.aborted, false);
  });
});

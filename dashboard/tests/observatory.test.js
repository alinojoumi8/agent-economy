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

test("deadline aborts read as timeouts while other failures keep their own message", async () => {
  await withObservatoryModule(async ({
    observatoryRefreshDeadline, observatoryRequestFailure, settleObservatoryRequests,
  }) => {
    const deadline = observatoryRefreshDeadline(15_000);
    deadline.cancel();
    assert.equal(deadline.timeoutMs, 15_000);
    assert.equal(deadline.signal.aborted, false);

    const abort = Object.assign(
      new Error("signal is aborted without reason"), { name: "AbortError" },
    );
    const expired = { signal: { aborted: true }, timeoutMs: 15_000 };
    assert.equal(observatoryRequestFailure(abort, expired), "timed out after 15 s");
    // An abort the deadline did not cause, or a deadline that did not fire, is
    // reported as it happened.
    assert.equal(observatoryRequestFailure(abort, deadline), "signal is aborted without reason");
    assert.equal(observatoryRequestFailure(abort, null), "signal is aborted without reason");
    assert.equal(observatoryRequestFailure(new Error("503 Service Unavailable"), expired),
      "503 Service Unavailable");

    const settled = await settleObservatoryRequests({
      status: Promise.resolve({ tick: 7 }),
      institutions: Promise.reject(abort),
      news: Promise.reject(new Error("news unavailable")),
    }, { deadline: expired });
    assert.deepEqual(settled.values, { status: { tick: 7 } });
    assert.deepEqual(settled.errors, [
      { key: "institutions", message: "timed out after 15 s" },
      { key: "news", message: "news unavailable" },
    ]);
  });
});

test("a status response that predates the newest tick frame never rolls the day back", async () => {
  await withObservatoryModule(async ({ acceptFetchedStatus }) => {
    const merged = { tick: 9, run_id: "run-1", status: "running" };
    // Older tick of the same run: the merged status wins.
    assert.equal(acceptFetchedStatus(merged, { tick: 8, run_id: "run-1", status: "running" }), merged);
    // Same or newer tick, a missing tick, no prior status, or another run: the
    // fetched document is applied as before.
    const same = { tick: 9, run_id: "run-1", status: "paused" };
    assert.equal(acceptFetchedStatus(merged, same), same);
    const newer = { tick: 10, run_id: "run-1" };
    assert.equal(acceptFetchedStatus(merged, newer), newer);
    const untimed = { status: "paused" };
    assert.equal(acceptFetchedStatus(merged, untimed), untimed);
    const first = { tick: 3 };
    assert.equal(acceptFetchedStatus(null, first), first);
    const otherRun = { tick: 0, run_id: "run-2" };
    assert.equal(acceptFetchedStatus(merged, otherRun), otherRun);
    const nullTick = { tick: null, run_id: "run-1" };
    assert.equal(acceptFetchedStatus(merged, nullTick), nullTick);
  });
});

test("status freshness follows the status request alone and rejected controls refresh first", async () => {
  const { readFile } = await import("node:fs/promises");
  const source = await readFile(
    new URL("../src/hooks/useObservatory.js", import.meta.url), "utf8",
  );
  // A slow or failed side panel must not disable Run, Pause and Stop.
  assert.match(source, /setStatusFresh\(has\("status"\)\);/);
  assert.doesNotMatch(source, /has\("status"\) && requestErrors\.length === 0/);
  assert.match(source, /status: has\("status"\) \? acceptFetchedStatus\(current\.status, values\.status\) : current\.status/);
  assert.match(source, /settleObservatoryRequests\(\{[\s\S]*?\}, \{ deadline \}\);/);
  // act(): the quiet refresh runs before the rejection reaches the caller.
  const act = source.match(/const act = useCallback\([\s\S]*?\}, \[refresh\]\);/)[0];
  assert.match(act, /catch \(reason\) \{[\s\S]*?await refresh\(\{ quiet: true \}\);[\s\S]*?throw reason;/);
});

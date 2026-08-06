import { expect, test } from "@playwright/test";

test("overlapping refreshes coalesce once and reconnect keeps one timer", async ({ page }) => {
  await page.addInitScript(() => {
    const nativeSetTimeout = window.setTimeout.bind(window);
    const nativeClearTimeout = window.clearTimeout.bind(window);
    const reconnectTimers = new Map<number, number>();
    window.setTimeout = ((handler: TimerHandler, timeout = 0, ...args: unknown[]) => {
      let id = 0;
      id = nativeSetTimeout(() => {
        reconnectTimers.delete(id);
        if (typeof handler === "function") handler(...args);
      }, timeout);
      const delay = Number(timeout);
      if (delay >= 500 && delay <= 10_000) reconnectTimers.set(id, delay);
      return id;
    }) as typeof window.setTimeout;
    window.clearTimeout = ((id = 0) => {
      reconnectTimers.delete(Number(id));
      nativeClearTimeout(id);
    }) as typeof window.clearTimeout;

    class ObservatorySocket extends EventTarget {
      static CONNECTING = 0;
      static OPEN = 1;
      static CLOSING = 2;
      static CLOSED = 3;
      readyState = ObservatorySocket.CONNECTING;
      readonly url: string;
      constructor(url: string | URL) {
        super();
        this.url = String(url);
        if (this.url.endsWith("/ws")) {
          (window as any).__observatorySockets.push(this);
        }
        queueMicrotask(() => {
          if (this.readyState !== ObservatorySocket.CONNECTING) return;
          this.readyState = ObservatorySocket.OPEN;
          this.dispatchEvent(new Event("open"));
        });
      }
      send(_value: string) {}
      close() {
        if (this.readyState === ObservatorySocket.CLOSED) return;
        this.readyState = ObservatorySocket.CLOSED;
        this.dispatchEvent(new CloseEvent("close", { wasClean: false, code: 1006 }));
      }
    }
    (window as any).__observatorySockets = [];
    (window as any).__activeReconnectTimers = () => reconnectTimers.size;
    Object.defineProperty(window, "WebSocket", { value: ObservatorySocket });
  });

  let statusRequests = 0;
  let releaseFirstStatus: () => void = () => {};
  const firstStatusGate = new Promise<void>(resolve => { releaseFirstStatus = resolve; });
  await page.route("**/api/**", async route => {
    if (new URL(route.request().url()).pathname === "/api/run/status") {
      statusRequests += 1;
      if (statusRequests === 1) await firstStatusGate;
    }
    await route.fulfill({ contentType: "application/json", body: "{}" });
  });

  await page.goto("/tests/e2e/fixtures/observatory.html");
  await expect.poll(() => statusRequests).toBe(1);
  await page.evaluate(() => {
    void (window as any).__observatoryHarness.refresh({ quiet: true });
    void (window as any).__observatoryHarness.refresh({ quiet: true });
    void (window as any).__observatoryHarness.refresh({ quiet: true });
  });
  releaseFirstStatus();
  await expect.poll(() => statusRequests).toBe(2);
  await page.waitForTimeout(100);
  expect(statusRequests).toBe(2);

  await expect.poll(() => page.evaluate(
    () => (window as any).__observatorySockets.length,
  )).toBe(1);
  await page.evaluate(() => {
    const socket = (window as any).__observatorySockets[0];
    socket.dispatchEvent(new Event("error"));
    socket.close();
  });
  await expect.poll(() => page.evaluate(
    () => (window as any).__activeReconnectTimers(),
  )).toBe(1);
  await expect.poll(() => page.evaluate(
    () => (window as any).__observatorySockets.length,
  ), { timeout: 2_000 }).toBe(2);
  await expect.poll(() => page.evaluate(
    () => (window as any).__activeReconnectTimers(),
  )).toBe(0);
});

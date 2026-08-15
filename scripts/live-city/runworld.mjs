/**
 * Running-world test for the Live City.
 *
 * Films the city and instruments it while the simulation actually ticks, so the
 * three known hazards can be measured instead of inferred:
 *   1. the day loop (45 s) meeting a real tick boundary (44-49 s)
 *   2. the previous_event_cursor bug -> cursor_gap -> dead push path
 *   3. the 408 KB map fetch landing in a starved event loop
 *
 * Nothing here mutates the app. The page is observed, not driven.
 */
import { createRequire } from "node:module";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const require = createRequire(
  "C:/Users/matri/Documents/myprojects/agent-economy/dashboard/package.json");
const { chromium } = require("playwright");

const OUT = process.argv[2];
const API = "http://127.0.0.1:8000";
const URL = "http://127.0.0.1:4174/runs/53f5b4ce8c/live-city";

const SMOKE = process.env.SMOKE === "1";
const BASELINE_MS = SMOKE ? 4_000 : 20_000;   // paused, for a before-picture
const RUN_MS = SMOKE ? 6_000 : 240_000;       // ~5 tick boundaries at 44-49 s
const MAX_TICKS = 6;          // hard session boundary; the world stops itself
const SHOT_EVERY_MS = 1_000;

mkdirSync(join(OUT, "frames"), { recursive: true });
const sleep = ms => new Promise(r => setTimeout(r, ms));
const stamp = () => new Date().toISOString().slice(11, 23);
const say = m => console.log(`[${stamp()}] ${m}`);

/* ---------------------------------------------------------------- probe -- */
/* Installed before any app script runs, so nothing is missed on first paint. */
function probe() {
  const P = {
    fetches: [], ws: [], frames: [], shots: [], notes: [],
    mapTick: null, mapSeq: 0, wallT0: Date.now(), sampleIds: [],
  };
  window.__probe = P;
  const now = () => performance.now();

  const nativeFetch = window.fetch;
  window.fetch = function (input, init) {
    const url = String(typeof input === "string" ? input : input?.url ?? input);
    const rec = { url, t0: now(), tHead: null, tBody: null, status: null, bytes: null, tick: null };
    const interesting = /\/api\/(run\/status|v2\/map)/.test(url);
    if (interesting) P.fetches.push(rec);
    const out = nativeFetch.call(this, input, init);
    if (!interesting) return out;
    return out.then(res => {
      rec.tHead = now();
      rec.status = res.status;
      /* Clone so the body is read twice without disturbing the app's own read.
         Headers can return long before the body on a starved server, so both
         instants are kept. */
      res.clone().text().then(text => {
        rec.tBody = now();
        rec.bytes = text.length;
        try {
          const j = JSON.parse(text);
          if (/run\/status/.test(url)) {
            rec.tick = j.tick; rec.runStatus = j.status; rec.nextPhase = j.next_phase;
            rec.running = j.running;
          } else {
            /* The map carries no top-level tick; the city reads it off civic. */
            const t = j?.civic?.tick ?? j?.presence?.[0]?.tick ?? null;
            rec.tick = t;
            P.mapTick = t; P.mapSeq += 1; P.mapLandedAt = now();
          }
        } catch { rec.parseError = true; }
      }, () => { rec.tBody = now(); rec.bodyError = true; });
      return res;
    }, err => { rec.tHead = now(); rec.error = String(err); throw err; });
  };

  const NativeWS = window.WebSocket;
  class ProbedWS extends NativeWS {
    constructor(url, protocols) {
      super(url, protocols);
      const id = P.ws.length;
      P.ws.push({ id, url: String(url), t: now(), events: [] });
      const log = (kind, extra) => P.ws[id].events.push({ kind, t: now(), ...extra });
      this.addEventListener("open", () => log("open"));
      this.addEventListener("close", e => log("close", { code: e.code, reason: e.reason }));
      this.addEventListener("error", () => log("error"));
      this.addEventListener("message", ev => {
        let m = null;
        try { m = JSON.parse(ev.data); } catch { log("unparsed"); return; }
        log("recv", {
          mtype: m.type, mtick: m.tick, cursor: m.event_cursor,
          prev: m.previous_event_cursor, code: m.code, reason: m.reason,
        });
      });
      const nativeSend = this.send.bind(this);
      this.send = data => {
        let m = null; try { m = JSON.parse(data); } catch { /* opaque */ }
        log("send", { mtype: m?.type, cursor: m?.event_cursor });
        return nativeSend(data);
      };
    }
  }
  window.WebSocket = ProbedWS;

  /* Per-frame sampler. Chip transforms are the ground truth for what the eye
     sees; the clock element carries the day's own progress as CSS vars. */
  const num = v => { const n = Number.parseFloat(v); return Number.isFinite(n) ? n : null; };
  const chipXY = el => {
    const m = /translate3d\(([-\d.]+)px,\s*([-\d.]+)px/.exec(el?.style?.transform || "");
    return m ? [Number(m[1]), Number(m[2])] : [null, null];
  };
  /* The pulse chip is the city's own claim about the push path — "Live",
     "Stale", "Paused". It is the single most load-bearing pixel in this test. */
  const PULSE = [];
  let lastPulse = null;
  let prev = null;
  const loop = t => {
    const clock = document.querySelector(".live-city__clock");
    const day = clock ? num(clock.style.getPropertyValue("--live-city-day")) : null;
    const leg = clock ? num(clock.style.getPropertyValue("--live-city-leg")) : null;
    const pulseEl = document.querySelector(".live-city__pulse");
    const pulse = pulseEl ? `${pulseEl.className}|${(pulseEl.textContent || "").trim()}` : "";
    if (pulse !== lastPulse) { PULSE.push({ t: Math.round(t), pulse }); lastPulse = pulse; }
    P.pulse = PULSE;
    const xy = [];
    for (const id of P.sampleIds) {
      const el = document.querySelector(`.live-city__chip[data-agent-id="${id}"]`);
      const [x, y] = chipXY(el);
      xy.push(x === null ? null : Math.round(x * 10) / 10,
              y === null ? null : Math.round(y * 10) / 10);
    }
    P.frames.push([Math.round(t * 10) / 10, prev === null ? 0 : Math.round((t - prev) * 10) / 10,
                   day, leg, P.mapSeq, ...xy]);
    prev = t;
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);

  /* The freshness badge is the user-visible verdict on the push path. */
  P.readBadge = () => {
    const hits = [];
    for (const el of document.querySelectorAll("body *")) {
      if (el.children.length) continue;
      const t = (el.textContent || "").trim();
      if (t && /stale|live|reconnect|offline|out of order/i.test(t) && t.length < 80) {
        hits.push(t);
      }
    }
    return hits.slice(0, 12);
  };
}

/* ----------------------------------------------------------------- main -- */
const api = (path, method = "POST") =>
  fetch(`${API}${path}`, { method }).then(r => r.json()).catch(e => ({ error: String(e) }));

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const console_ = [];
page.on("console", m => console_.push({ type: m.type(), text: m.text().slice(0, 300) }));
page.on("pageerror", e => console_.push({ type: "pageerror", text: String(e).slice(0, 300) }));
await page.addInitScript(probe);

say(`opening ${URL}`);
await page.goto(URL, { waitUntil: "domcontentloaded" });
await page.waitForSelector(".live-city__chip", { timeout: 60_000 });
await page.waitForFunction(
  () => document.querySelectorAll(".live-city__chip").length > 200, null, { timeout: 60_000 });

/* Sample chips that actually travel; a parked chip proves nothing about motion. */
const sampleIds = await page.evaluate(() => {
  const all = [...document.querySelectorAll(".live-city__chip")];
  const haul = all.filter(el => el.dataset.haul === "1");
  const pick = (haul.length >= 8 ? haul : all).slice(0, 200);
  const step = Math.max(1, Math.floor(pick.length / 8));
  const ids = [];
  for (let i = 0; i < pick.length && ids.length < 8; i += step) ids.push(Number(pick[i].dataset.agentId));
  window.__probe.sampleIds = ids;
  return ids;
});
say(`sampling chips ${sampleIds.join(", ")} (${await page.evaluate(() => document.querySelectorAll(".live-city__chip").length)} on screen)`);

/* One clock offset so node wall time and page performance.now() can be aligned. */
const [pageT, wallT] = [await page.evaluate(() => performance.now()), Date.now()];
const toPage = () => pageT + (Date.now() - wallT);

let shooting = true, shot = 0;
const filmstrip = (async () => {
  while (shooting) {
    const at = toPage();
    const name = `f${String(shot).padStart(4, "0")}.jpg`;
    try {
      await page.screenshot({ path: join(OUT, "frames", name), type: "jpeg", quality: 70 });
      await page.evaluate(t => window.__probe.shots.push(t), at);
      shot += 1;
    } catch { /* a shot that fails is a missing frame, not a failed run */ }
    await sleep(SHOT_EVERY_MS);
  }
})();

const note = async text => {
  const t = toPage();
  await page.evaluate(([t, text]) => window.__probe.notes.push({ t, text }), [t, text]);
  say(text);
};

await note(`baseline: paused, ${BASELINE_MS / 1000}s`);
const before = await api("/api/run/status", "GET");
await sleep(BASELINE_MS);

await note(SMOKE ? "SMOKE: not starting the world" : "POST /api/run/start");
const started = SMOKE ? { smoke: true } : await api(`/api/run/start?max_ticks=${MAX_TICKS}`);
say(`start -> ${JSON.stringify(started).slice(0, 200)}`);

const deadline = Date.now() + RUN_MS;
let lastTick = null;
while (Date.now() < deadline) {
  await sleep(5_000);
  const s = await api("/api/run/status", "GET");
  if (s.tick !== lastTick) {
    lastTick = s.tick;
    await note(`server tick ${s.tick} (${s.status}, next ${s.next_phase})`);
  }
  if (s.status === "paused" && s.running === false && lastTick !== null && lastTick > 349) {
    await note(`world stopped itself at tick ${s.tick} (max_ticks reached)`);
    break;
  }
}

await note(SMOKE ? "SMOKE: nothing to pause" : "POST /api/run/pause");
const paused = SMOKE ? { smoke: true } : await api("/api/run/pause");
await sleep(3_000);

shooting = false;
await filmstrip;

const data = await page.evaluate(() => ({
  fetches: window.__probe.fetches,
  ws: window.__probe.ws,
  frames: window.__probe.frames,
  shots: window.__probe.shots,
  notes: window.__probe.notes,
  sampleIds: window.__probe.sampleIds,
  pulse: window.__probe.pulse,
  badge: window.__probe.readBadge(),
  mapSeq: window.__probe.mapSeq,
}));

writeFileSync(join(OUT, "probe.json"), JSON.stringify({
  url: URL, before, started, paused, console: console_, shots: shot, ...data,
}));
say(`wrote probe.json — ${data.frames.length} frames, ${data.fetches.length} fetches, ${shot} stills`);
await browser.close();

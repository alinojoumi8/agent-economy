/** Reads probe.json and answers the three questions the paused runs could not. */
import { readFileSync } from "node:fs";

const P = JSON.parse(readFileSync(process.argv[2] + "/probe.json", "utf8"));
const F = P.frames;                       // [t, dt, day, leg, mapSeq, x0,y0 ... x7,y7]
const NX = 5;                             // first chip column
const nChips = P.sampleIds.length;
const s = n => (n === null || n === undefined ? "—" : n);
const ms = n => `${Math.round(n)} ms`;
const sec = t => `${(t / 1000).toFixed(1)}s`;
const pct = n => `${(n * 100).toFixed(1)}%`;
const quant = (a, q) => { const b = [...a].sort((x, y) => x - y); return b[Math.min(b.length - 1, Math.floor(b.length * q))]; };
const H = t => console.log(`\n${"=".repeat(72)}\n${t}\n${"=".repeat(72)}`);

const T_START = P.notes.find(n => /run\/start/.test(n.text))?.t ?? 0;
const T_PAUSE = P.notes.find(n => /run\/pause/.test(n.text))?.t ?? Infinity;
const rel = t => `${((t - T_START) / 1000).toFixed(1)}s`;   // 0 = the moment the world was told to run

H("1. TIMELINE");
for (const n of P.notes) console.log(`  ${rel(n.t).padStart(8)}  ${n.text}`);

H("2. THE MAP FETCH — does 408 KB survive a starved event loop?");
const maps = P.fetches.filter(f => /v2\/map/.test(f.url) && f.tBody);
console.log("   when      head        body       total      bytes    tick   phase");
for (const f of maps) {
  const running = f.t0 > T_START && f.t0 < T_PAUSE;
  console.log(`  ${rel(f.t0).padStart(8)}  ${ms(f.tHead - f.t0).padStart(9)}  `
    + `${ms(f.tBody - f.tHead).padStart(9)}  ${ms(f.tBody - f.t0).padStart(9)}  `
    + `${String(f.bytes).padStart(7)}  ${String(s(f.tick)).padStart(5)}   ${running ? "RUNNING" : "paused"}`);
}
const runMaps = maps.filter(f => f.t0 > T_START && f.t0 < T_PAUSE);
const pauseMaps = maps.filter(f => f.t0 <= T_START || f.t0 >= T_PAUSE);
const tot = f => f.tBody - f.t0;
if (pauseMaps.length) console.log(`\n  paused : n=${pauseMaps.length}  median ${ms(quant(pauseMaps.map(tot), 0.5))}  max ${ms(Math.max(...pauseMaps.map(tot)))}`);
if (runMaps.length) console.log(`  RUNNING: n=${runMaps.length}  median ${ms(quant(runMaps.map(tot), 0.5))}  max ${ms(Math.max(...runMaps.map(tot)))}`);

H("3. THE STATUS POLL — the city's only tick detector (3 s interval)");
const st = P.fetches.filter(f => /run\/status/.test(f.url) && f.tBody);
const runSt = st.filter(f => f.t0 > T_START && f.t0 < T_PAUSE);
const pauseSt = st.filter(f => f.t0 <= T_START || f.t0 >= T_PAUSE);
const show = (label, arr) => {
  if (!arr.length) return;
  const d = arr.map(tot);
  console.log(`  ${label.padEnd(8)} n=${String(arr.length).padStart(3)}  median ${ms(quant(d, 0.5)).padStart(9)}  `
    + `p95 ${ms(quant(d, 0.95)).padStart(9)}  max ${ms(Math.max(...d)).padStart(9)}`);
};
show("paused", pauseSt); show("RUNNING", runSt);
const gaps = [];
for (let i = 1; i < runSt.length; i++) gaps.push(runSt[i].t0 - runSt[i - 1].t0);
if (gaps.length) console.log(`  poll-to-poll spacing while running: median ${ms(quant(gaps, 0.5))}  max ${ms(Math.max(...gaps))}  (nominal 3000 ms)`);
const slow = runSt.filter(f => tot(f) > 3000);
if (slow.length) {
  console.log(`\n  ${slow.length} status polls took over 3 s — the event loop was blocked:`);
  for (const f of slow) console.log(`    ${rel(f.t0).padStart(8)}  ${ms(tot(f)).padStart(9)}  -> tick ${s(f.tick)} ${f.nextPhase || ""}`);
}

H("4. DETECTION LAG — server ticks, then how long until the city knows?");
/* Server tick transitions as first *observed* by a status poll, then the map that answered it. */
let seenTick = null;
const events = [];
for (const f of st) {
  if (f.tick !== null && f.tick !== seenTick) {
    if (seenTick !== null) events.push({ tick: f.tick, observedAt: f.tBody, prev: seenTick });
    seenTick = f.tick;
  }
}
for (const e of events) {
  const answer = maps.find(m => m.t0 >= e.observedAt);
  console.log(`  tick ${e.prev} -> ${e.tick}: first seen by a status poll at ${rel(e.observedAt)}`
    + (answer
      ? `; map requested +${ms(answer.t0 - e.observedAt)}, landed +${ms(answer.tBody - e.observedAt)} (tick ${s(answer.tick)})`
      : "; NO map fetch followed"));
}

H("5. THE DAY LOOP AT A REAL TICK BOUNDARY");
/*
 * dayOrigin resets when mapTick changes — but in a useEffect that runs AFTER the
 * frame carrying the new mapSeq, so keying off mapSeq measures the wrong frame
 * and badly understates the jump. The clock itself is the honest signal: any
 * backwards step in dayProgress is a day boundary. One that starts from ~1.0 is
 * the loop reaching its natural end; anything else is a tick cutting the day
 * short mid-stride, which is the case that moves people without moving time.
 */
const jumpAt = i => {
  let worst = 0;
  for (let c = 0; c < nChips; c++) {
    const [a, b] = [F[i - 1], F[i]];
    const [x0, y0, x1, y1] = [a[NX + c * 2], a[NX + c * 2 + 1], b[NX + c * 2], b[NX + c * 2 + 1]];
    if ([x0, y0, x1, y1].some(v => v === null)) continue;
    worst = Math.max(worst, Math.hypot(x1 - x0, y1 - y0));
  }
  return worst;
};
const wraps = [], forced = [];
for (let i = 1; i < F.length; i++) {
  const [before, after] = [F[i - 1][2], F[i][2]];
  if (before === null || after === null || after >= before - 0.01) continue;
  (before > 0.9 ? wraps : forced).push({ i, before, after, t: F[i][0] });
}
const boundary = (label, list) => {
  console.log(`\n  ${label}: ${list.length}`);
  for (const b of list) {
    console.log(`    ${rel(b.t).padStart(8)}  ${pct(b.before)} -> ${pct(b.after)}   `
      + `worst chip jump ${jumpAt(b.i).toFixed(2)} px`);
  }
};
boundary("natural wraps (the loop reaching its end)", wraps);
boundary("FORCED resets (a new tick cutting the day short)", forced);

/* What an ordinary frame looks like, so a jump has a scale to be read against. */
const skip = new Set([...wraps, ...forced].map(b => b.i));
const normal = [];
for (let i = 1; i < F.length; i++) {
  if (skip.has(i)) continue;
  for (let c = 0; c < nChips; c++) {
    const [x0, y0] = [F[i - 1][NX + c * 2], F[i - 1][NX + c * 2 + 1]];
    const [x1, y1] = [F[i][NX + c * 2], F[i][NX + c * 2 + 1]];
    if (x0 === null || x1 === null) continue;
    normal.push(Math.hypot(x1 - x0, y1 - y0));
  }
}
if (normal.length) console.log(`\n  for scale, an ordinary frame moves a chip: median ${quant(normal, 0.5).toFixed(2)} px, p99 ${quant(normal, 0.99).toFixed(2)} px`);

/* How long one frame of truth actually stayed on screen. */
if (maps.length > 1) {
  console.log(`\n  ticks the city ever rendered: ${[...new Set(maps.map(m => m.tick))].join(", ")}`);
  console.log(`  tick ${maps[0].tick} held the screen from ${rel(maps[0].tBody)} to ${rel(maps[1].tBody)}`
    + ` = ${((maps[1].tBody - maps[0].tBody) / 1000).toFixed(0)} s`);
}

H("6. FRAME HEALTH — stutter, with camera frames discounted");
const shotWindows = P.shots.map(t => [t - 30, t + 400]);
const inShot = t => shotWindows.some(([a, b]) => t >= a && t <= b);
const clean = [], dirty = [];
for (let i = 1; i < F.length; i++) (inShot(F[i][0]) ? dirty : clean).push(F[i][1]);
const band = (label, a) => a.length && console.log(
  `  ${label.padEnd(22)} n=${String(a.length).padStart(5)}  median ${a.length ? quant(a, 0.5).toFixed(1) : "—"} ms  `
  + `p95 ${quant(a, 0.95).toFixed(1)} ms  p99 ${quant(a, 0.99).toFixed(1)} ms  max ${Math.max(...a).toFixed(0)} ms`);
band("no screenshot nearby", clean);
band("screenshot in flight", dirty);
console.log(`  clean frames over 100 ms: ${clean.filter(d => d > 100).length}   over 500 ms: ${clean.filter(d => d > 500).length}`);

H("7. WHAT THE CITY TOLD THE READER (.live-city__pulse)");
for (const p of P.pulse || []) {
  const label = p.pulse.split("|")[1] || "(gone)";
  const cls = (/pulse--(\w+)/.exec(p.pulse) || [, "?"])[1];
  console.log(`  ${rel(p.t).padStart(8)}  ${label.padEnd(12)} (${cls})`);
}

H("8. THE PUSH PATH — sockets, deltas, and the cursor rule");
for (const sock of P.ws) {
  if (!/\/ws/.test(sock.url)) continue;   // skip vite's HMR socket
  console.log(`\n  socket #${sock.id} ${sock.url} opened ${rel(sock.t)}`);
  let held = 0, gaps = 0, applied = 0, handshakes = 0;
  for (const e of sock.events) {
    let verdict = "";
    if (e.kind === "recv" && e.mtype === "hello") { held = Number(e.cursor || 0); handshakes += 1; }
    if (e.kind === "recv" && e.mtype === "projection_delta") {
      const next = Number(e.cursor), prev = Number(e.prev);
      if (next <= held) verdict = "  IGNORED (cursor not ahead)";
      else if (prev !== held) { verdict = `  CURSOR_GAP -> discarded, re-handshake (held ${held}, delta says prev ${prev})`; gaps += 1; }
      else { verdict = "  applied"; held = next; applied += 1; }
    }
    const bits = [e.mtype || e.kind];
    if (e.cursor !== undefined && e.cursor !== null) bits.push(`cur=${e.cursor}`);
    if (e.prev !== undefined && e.prev !== null) bits.push(`prev=${e.prev}`);
    if (e.mtick !== undefined && e.mtick !== null) bits.push(`tick=${e.mtick}`);
    if (e.code) bits.push(`code=${e.code}`);
    if (e.reason) bits.push(`reason=${e.reason}`);
    console.log(`    ${rel(e.t).padStart(8)}  ${e.kind === "send" ? "-> " : "<- "}${bits.join(" ")}${verdict}`);
  }
  console.log(`    ---- deltas applied: ${applied}   rejected as cursor_gap: ${gaps}   hellos received: ${handshakes}`);
}

H("9. CONSOLE");
const bad = P.console.filter(c => c.type === "error" || c.type === "pageerror");
console.log(bad.length ? bad.slice(0, 15).map(c => `  ${c.type}: ${c.text}`).join("\n") : "  no errors");
console.log(`\n  stills captured: ${P.shots.length}   frames sampled: ${F.length}   maps landed: ${P.mapSeq}`);

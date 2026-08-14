# Gauntlet Loop — the Living City

Branch `feat/live-city`. Baseline `8b08902` (design system) → `72540e2` (round 1).
The previous loop's full record is in git history at `8b08902`.

---

## The bars — verified by film, not by title

A still cannot show whether a city moves, so every bar is captured as a **frame sequence** and judged as a
labelled filmstrip (`scratchpad/film.js`).

| Bar | Governs | Status |
|---|---|---|
| **minitokyo3d.com** | Continuous entity motion on a city map; atmosphere; calm; legibility while moving | ✅ **verified** — trains visibly advance along real routes over 39s |
| **globe.adsbexchange.com** | Density at scale; live-entity legibility; click-an-entity-to-see-why | ✅ **verified** — live aircraft map, no bot wall |
| ~~flightradar24.com~~ | *was* the density bar | ❌ **REJECTED — Cloudflare "Verify you are human"** |
| ~~ai-town.convex.dev~~ | closest conceptual peer | ❌ unreachable from this environment |
| ~~marinetraffic.com~~ | candidate replacement | ❌ Cloudflare "Sorry, you have been blocked" |

**Flightradar24 passed a naive check and failed a real one.** Navigating to it returned a valid page title, so
it looked reachable. *Filming* it returned six identical frames of a CAPTCHA — 95 KB against Mini Tokyo's
1,713 KB. Had the loop trusted the title, six critics would have solemnly compared our city against a bot-check
page. This is the single most common way a gauntlet loop fails, and the only defence is fetching the bar for
real. CAPTCHAs are not to be solved or worked around; the bar was replaced.

## The motion rule

Every rendered position derives from a **recorded placement**. An agent's day is exactly three recorded points
— `morning`, `business`, `evening`. Chips glide between *those* points. **An agent whose consecutive slots name
the same place does not move.** No idle drift, no milling, no filler agents.

## 🔴 Round 1 result — 1/3, and a bar was broken

**Scored honestly: 1 of 3 against the only valid bar.**

| bar | alive | legible | craft |
|---|---|---|---|
| Mini Tokyo 3D | ~~ours, decisive~~ | ~~ours, decisive~~ | ~~ours, decisive~~ |
| ADS-B Exchange | **bar wins** | **bar wins** | ours |

**All three Mini Tokyo wins are VOID.** Three critics independently *measured* that capture and found it
static — *"Nothing moves. Measured, not guessed: consecutive frames differ by mean 0.006/255 with fewer than
0.005% of pixels changed"*; *"5 pixels out of 466,528 differ by more than 10 levels… a still map with a clock
stamped on it."* The capture was taken at **01:31 Tokyo time, when the trains are stabled.** We beat a
screenshot. Those verdicts are discarded.

**Bar repaired.** Mini Tokyo 3D has a playback mode (`.mapboxgl-ctrl-playback`); wound forward at 60× to
07:00 rush hour, dropped back to 1×, re-filmed. Measured proof, per-interval pixel change:

| capture | min % changed | max % | dead intervals |
|---|---|---|---|
| Mini Tokyo **03:14 night** — the invalid one | **0.263** | 0.379 | 0 |
| Mini Tokyo **07:00 rush** — repaired | **4.908** | 7.947 | 0 |
| ADS-B Exchange | **4.001** | 6.381 | 0 |
| **our round 1** | **0.008** | 8.447 | **2** |

Night-time Mini Tokyo moved **19× less** than its rush-hour self. Tool: `scratchpad/framediff.js`.

**This diagnoses our real problem exactly.** Our *peak* motion (8.4%) already beats both bars. Our *floor* is
0.008%. The bars move **steadily**; we alternate between bursts and dead air — which is precisely what three
critics said in words: *"only in short bursts at three phase boundaries; between them the field is frozen"*,
*"the strip contains genuine dead air."*

**Round 2 target: minimum per-interval change ≥4%, zero dead intervals.** The fix costs no honesty — the data
never says "stand still for 9 s then move for 6 s", only "recorded at A, then at B". Spreading the transition
across the whole beat is equally truthful and removes every dead frame.

Other defects sent to round 2: every person is an identical 3 px dot so you cannot track one; crowds and
couples render identically with no count badge; chips blow out to white bloom at exactly the moment travel is
visible, discarding the colour code; a stale "1 anonymised at Suncoast Republic Permit Office" tooltip parked
over a region label through all twelve frames; developer telemetry (`/api/v2/map 152 ms`) shipped in the
footer; ~40% of canvas height is dead space; region names at ~15% opacity *beneath* the dots with no boundary
or hull marking territory.

## ✅ Round 2 result — 6/6 (2 decisive). Up from 1/3.

| bar | alive | legible | craft |
|---|---|---|---|
| Mini Tokyo 3D (rush hour) | ours, clear | ours, **decisive** | ours, clear |
| ADS-B Exchange | ours, clear | ours, **decisive** | ours, clear |

Critics actively checked and **cleared**: no dead or frozen intervals (all 11 measured 6.1–9.0% aligned
change); no stale readouts (leg title, body copy and progress bar all track state); recolour is **not**
masquerading as motion (the blue→green flip coincides with 7.8% genuine positional redistribution); no clipped
chrome. And they credited the honesty affordance directly:

> *"B declares its static elements instead of letting them read as a bug."*

### ⚠️ A measurement lesson — my tool over-credited the bar

Critics used **phase correlation** to compensate for whole-canvas shift before measuring motion. My
`framediff.js` does not:

> *"Raw frame-to-frame change looks healthy (14–26% of pixels) until you compensate for a whole-canvas 2–4 px
> shift, at which point it collapses to 3–6%. **70–85% of everything that 'changes' [in Mini Tokyo] is the
> entire map twitching two pixels.**"*

So Mini Tokyo at 07:00 rush hour is *still* largely a re-rendering diagram — my 4.908% figure credited tile
reflow as motion. **The trustworthy result is 3/3 against ADS-B**, where the shift correction was only 10–15%.
`framediff.js` should be upgraded to align frames before differencing; until then its numbers are an upper
bound, not a measure.

## 🔴 The running-world test — the city does not survive a live tick boundary

**Every previous measurement in this document was taken with the world paused at tick 349.** All three builds,
all 18 blind verdicts, every motion probe. The stated requirement — *"whenever we run the backend the front end
looks live"* — was the one condition never exercised. It has now been run, and it fails.

**Method.** `/api/run/start?max_ticks=6` on run `53f5b4ce8c`, a 20 s paused baseline first, then 348 s of real
ticking; the page instrumented before first paint (every `fetch` timed to *body* as well as headers, every
WebSocket frame logged with its cursors, every `requestAnimationFrame` sampling the day clock and eight chip
transforms) and filmed at 1 still/s. **15,491 frames, 62 fetches, 326 stills, ticks 349 → 355, spend $0.00.**

### The result in one line

The world advanced six ticks. **The city rendered exactly one of them.**

| | |
|---|---|
| Ticks the world ran | 349 → 355 (six) |
| Ticks the city ever displayed | **349, then 355** — 350, 351, 352, 353, 354 were never drawn |
| One frame of truth stayed on screen for | **369 s** (design intent: ~46 s) |
| Status polls completed while running | **2**, against ~115 expected at the 3 s interval |
| Map fetches completed while running | **0** |
| Frame rate throughout | **median 16.7 ms, p99 50 ms, zero frames over 500 ms** |

That last row is the trap. **The animation never faltered.** For the whole 348 s the city glided at 60 fps,
296 chips in motion, looking exactly as alive as it does in every screenshot in this document — while showing
data that was up to six minutes old and a badge that read *"Paused"*. It does not look broken when it is
broken. That is the worst available failure mode, and only a running world exposes it.

### 1. The server stops answering — the tick blocks the event loop it is served from

`world.run()` is an `asyncio` task on uvicorn's own loop ([world/loop.py:172-181](world/loop.py:172)), and
`speed_delay_s` is `0.0`, so one `await self.step()` runs straight into the next with no yield between ticks.
Under the scripted showcase provider there is no real I/O to suspend on, so a tick is one uninterrupted block
of CPU on the loop that is supposed to be serving HTTP.

| endpoint | paused | **while running** |
|---|---|---|
| `/api/run/status` (1 KB) | median **168 ms** | **123,346 ms** and **218,716 ms** — the only two that returned |
| `/api/v2/map` (408 KB) | median **133 ms** | **never completed** |
| `POST /api/run/start` | — | **62 s to return** |

An independent `curl` gave up on `/api/run/status` at a 60 s timeout. This is not the 2 ms→40 s degradation on
record; it is worse, and it is total. Note the direction of the surprise: the 408 KB payload was never the
problem. The **1 KB** status endpoint is, because it is the city's only tick detector.

### 2. Detection lag — the city asks for the wrong tick and gets it 223 s later

The city does not poll the map. It polls `/api/run/status` every 3 s and refetches the map when the tick
changes ([LiveCity.tsx:411-414](dashboard/src/components/LiveCity.tsx:411)) — sound reasoning against a 408 KB
payload, and it collapses when the detector is the thing being starved.

- tick 349 → 350 was first *seen* at **125.1 s**; the map fetch it triggered landed **223 s later**, and by then
  the world was at 355. **The city requested tick 350's frame and was served tick 355's.**
- Between them the day loop wrapped **8 times** on tick 349's placements — the same recorded day replayed
  eight times over while five real ones went past unrendered.

### 3. The day loop at a real boundary — clean when it wraps, a 330 px teleport when it is cut

Both behaviours were captured, and the difference is stark:

| | day clock | worst chip movement in one frame |
|---|---|---|
| **Natural wrap** ×8 (loop reaches its end) | 100% → 0% | **0.00–0.86 px** |
| **Forced reset** ×1 (a new tick lands mid-day) | **19.6% → 0%** | **330.76 px** |
| *ordinary frame, for scale* | | *0.57 px median, 1.92 px p99* |

The wrap is seamless because it returns to the morning anchors it started from. The forced reset is not: it
cuts the day off wherever it happens to be and snaps 300 people to new positions in a single frame — a **170×**
departure from ordinary motion. `dayOrigin` resets on `mapTick` ([LiveCity.tsx:466-468](dashboard/src/components/LiveCity.tsx:466))
with nothing to carry the old positions into the new ones.

**This fired only once in six minutes, and only because the map was unfetchable until the world stopped.** Fix
the starvation without fixing this and the teleport goes from once per session to once per tick.

### 4. The cursor bug is not intermittent — it is structural, and it fires on every tick

Measured on the wire, not inferred. **Every tick commits exactly two cursors** (verified in
`projection_commits` for ticks 348–355: `697..698`, `699..700`, `701..702`, …). `projection_delta_message`
sends the tick's *last* cursor as `event_cursor` and the tick's *first* as `previous_event_cursor`
([transport.py:41-43](server/projections/transport.py:41)) — but the client holds the previous tick's last
cursor and never receives the intra-tick one. So `previous_event_cursor` is **always** off by exactly one
commit, and `cursorReducer.js:67` flags `cursor_gap` on **every live delta**:

```
122.9s  <- projection_delta cur=700 prev=699 tick=350   CURSOR_GAP (client held 698) -> discarded, re-handshake
170.4s  <- projection_delta cur=702 prev=701 tick=351   CURSOR_GAP (client held 698) -> discarded, re-handshake
218.4s  <- 7 backfill deltas, 699..705, correctly chained   -> all applied
222.3s  <- close code=1011 reason=keepalive ping timeout
```

Two things this run corrected in the record:

- **The push path is not simply dead — it is dead and self-healing.** The re-handshake triggers a backfill, and
  the backfill's cursors *are* correct (a different code path), so the client catches up. The steady state is
  gap → re-handshake → backfill → gap. Wasteful, and it re-handshakes on every tick, but not silent.
- **The uvicorn keepalive hazard is no longer an inference.** `code=1011 reason=keepalive ping timeout` was
  observed. The socket then took **125 s to reopen**, because opening it also needs the blocked event loop. The
  city showed *"Reconnecting"* for that entire time.

### What the reader was actually told, over 348 s of running world

| from | the badge said | true? |
|---|---|---|
| 0 s | **Paused** | **no** — the world was running; the status poll that would have said so was blocked for 125 s |
| 125 s | Stale | yes |
| 170 s | Live → Stale within 50 ms | the tick-351 delta gapped |
| 218 s | Live | yes, briefly — the backfill had landed |
| 222 s | **Reconnecting** (125 s) | yes — keepalive timeout, socket unable to reopen |
| 347 s | Live | yes |

**For the first 125 seconds of a running world the city told the reader it was paused.** The one label a viewer
would trust to distinguish "replaying a recorded day" from "watching a live one" was wrong, in the direction
that conceals the failure.

### What this changes

The three hazards were listed as separate risks. They are one failure with one root: **a tick monopolises the
event loop, so the city's only tick detector cannot fire, so no new frame of truth arrives, so nothing else
gets a chance to go wrong.** The teleport and the cursor gap are what will be waiting once the starvation is
lifted — the cursor bug fires every tick, and the teleport becomes per-tick rather than per-session.

Order that follows from the measurement, and it is not the order the piece list had:

1. **Unblock the loop.** Yield inside the tick, or move `world.step()` off the serving loop. Nothing else in
   the city is observable until this is done, and no amount of front-end work compensates for it.
2. **Fix `previous_event_cursor`** to the last cursor the client was *sent*, not the previous commit. Cheap,
   and it retires the permanent "stale" banner in every screenshot in this document.
3. **Carry the day across a tick change** — ease from held positions into the new anchors instead of snapping
   `dayOrigin` to zero. Until then a working transport makes the motion *worse*.
4. Only then are conversations on the map (piece 5) worth building, because only then is there a live city to
   pin them to.

**Nothing about the three passed rounds is retracted.** The city is truthful and it is beautiful, and 6/6 twice
stands — against a paused world, which is what those rounds measured. What is now on record is that the claim
those rounds appeared to support, *"whenever we run the backend the front end looks live"*, is not yet true.

**Evidence.** The probe is committed and re-runnable — `scripts/live-city/` (`runworld.mjs` capture,
`analyse.mjs`, `film.mjs`, and a README on the two traps in measuring it). Artefacts: `probe.json`, 326 stills,
`city-running.mp4` (whole session at 8×), `the-jump.jpg` (the teleport, four-up).
**The run is now paused at tick 355, not 349** — this test advanced it, which is irreversible. Spend `$0.00`.

*Correction against my own first pass: the analyser initially measured the chip jump on the frame the map
landed and reported **4.1 px**. `dayOrigin` resets in an effect that runs a frame later, so that was the wrong
frame; keyed off the day clock instead, the true figure is **330.76 px**. The committed `analyse.mjs` uses the
corrected method and the README says why.*

### One thing this test does not settle

The starvation was measured under the **scripted/offline** provider, where a tick is pure CPU with nothing to
await. A live-inference profile awaits real network I/O throughout `MORNING` and would yield to the loop
constantly, so HTTP may well stay responsive there. **That is reasoning, not measurement** — flagged as such.
It does not soften the finding: `civic-city-300.yaml` is the profile the Live City is demonstrated on.

## ✅ Round 3 result — 6/6 again. Exit condition met twice running.

| round | vs Mini Tokyo | vs ADS-B | total | decisive |
|---|---|---|---|---|
| 1 | *(void — bar was static)* | **1/3** | 1/3 | 0 |
| 2 | 3/3 | 3/3 | **6/6** | 2 |
| 3 | 3/3 | 3/3 | **6/6** | 1 |

Critics actively checked and **cleared** in ours: no frozen intervals (all 11 show 50–67% of grid cells
changed and 72%+ of tracked chips displaced *after* shift compensation); no stale readouts — one verified the
constant rather than assuming it: *"'TICK 349' is the identifier of the recorded day being replayed, not a
frozen clock — I checked it against the footer copy before clearing it"*; **no entity-over-text occlusion on
the region plates** — *"chips and trails render around and behind them, never over the type, which is exactly
where A fails"*; no chrome debris; no teleporting or popping.

They also independently confirmed the trap I had been measuring wrong: compensating for canvas shift removes
**77–91%** of Mini Tokyo's raw difference but only **5–53%** of ours.

### The pattern worth naming: each round's fix becomes the next round's defect

- The 2.6× inset that resolved the crowd now has **its own labels destroyed** — *"'24 District 2' is destroyed
  by amber chips and route lines drawn straight through the glyphs with no halo or plate."* The same occlusion
  class that was fixed on the region plates, relocated into the fix.
- The destination rings that stopped travellers "gliding into black" became **a route hairball** — *"hundreds
  of long straight chords at uniform weight blanket the entire canvas, including large stretches of territory
  holding no dots at all."*
- The honesty disclosures became **a wall of text** — *"B's right rail is not a legend, it is four stacked 3–4
  line paragraphs of implementation rules."*
- Count badges are **half-finished**: some get a dark plate and read cleanly; *"'35', '25', '16' are bare ~6px
  numerals dropped straight onto the densest part of the dot field."*
- The Northstar core **still** overplots at peak density — *"the design still answers 'many' but stops
  answering 'how many'."*
- A raw build hash still ships in the footer, and NSD / IVC / SCD are unexplained codes.

This is the third time in two loops that a targeted fix has generated the next round's finding. It is a
property of the method, not an accident: each brief is written from the previous round's evidence, so it can
only ever see backwards.

### Round 3 — build detail

Motion floor, all captures re-measured with the upgraded tool:

| capture | floor | ceiling | dead intervals |
|---|---|---|---|
| ADS-B Exchange | 3.909% | 6.402% | 0 |
| Mini Tokyo 3D (rush) | 4.795% | 7.935% | 0 |
| ours, round 1 | **0.006%** | 8.852% | **2** |
| **ours, round 3** | **6.722%** | 8.501% | **0** |

The builder **corrected my brief from the data**: the commons blob is *not* one 90-person place — the busiest
holds **42**, and the mass is a commons (42) plus two districts (24, 23) whose coordinates sit 34 px and 47 px
apart at whole-city zoom. Its answer was a **second camera**: a 2.6× inset on the busiest ground, drawn only
where this tick's geography leaves the canvas empty, and **not drawn at all** if no clear candidate exists
(verified across 4 viewports, 0 chips ever under the panel).

Measured outcomes: plot coverage **37.3% → 69.3%**; z-order occlusion **11,295 chip pixels inside 39 of 77
label plates → 0 of 77**; truthfulness worst residual **2.5e-16 data units** across 300 chips at 10 timestamps,
with the 4 same-place people never changing pixel. Gate: 8 passed · typecheck clean · **163 tests**.

**Honest limit it declared rather than hid:** at whole-city zoom with a 2.1 s sampling interval, median chip
displacement still exceeds median neighbour spacing — *"set by the recording's own pace"* — so an individual
in the dense core still cannot be followed by eye. The mitigations are the wake, the lock-on and the inset.

**Two self-caught errors worth recording:**
- A regression it introduced: the first cross-border implementation anchored a rotated element per chip at
  **39 ms/frame**, and the capture harness started returning **half-painted frames, one in twelve**. Redrawn as
  a static per-leg SVG layer: median frame **62.5 ms → 23.2 ms**. It flagged that **round-2 numbers may also
  have carried capture noise**.
- Its first occlusion probe was **invalid**: hiding the chip layer as a control flipped Chromium's text
  antialiasing to subpixel, so the no-chips control scored *higher* than the arm under test.

### ⚠️ My measuring tool is still not equivalent to the critics'

I added best-fit integer shift search to `framediff.js`. It now reports 0 px shift and 0% jitter on every
capture — **and that reading should not be trusted.** The tool downscales 2880 px → 480 px before differencing,
so the 2–4 px full-resolution shift the critics found becomes sub-pixel and invisible to an integer search.
The correction is an improvement, not a substitute for phase correlation at full resolution. Treat
`framediff.js` numbers as an upper bound on motion and a lower bound on jitter.

### Round 3's brief — seven defects named in the round-2 winner

1. **The header KPI row is dead** — TICK / PLACEMENTS / COMMUTING / CROSS-BORDER pixel-identical across all
   12 frames and 23 seconds while the world visibly cycles.
2. **Chips render on top of region label text** — *"a green chip sits inside 'IRONVALE UNION', eating the E"*.
   Same defect class as the World map's label/agent-layer bug.
3. **A raw run hash ships as chrome** — `STREET LEVEL · run 33f5b4ca8c`.
4. **~90 commons chips fuse into one unresolvable mass**, and the ring-count numerals the legend promises fail
   at exactly that size — a broken promise, not just density.
5. **The dense core cannot be tracked** — median chip displacement 4.8–7.5 px against median neighbour spacing
   7.6–11.4 px, so a chip moves ~0.6 of a neighbour gap per interval.
6. **A third to a half of the canvas carries nothing** but faint graticule.
7. **Cross-border travellers glide into empty black** with no destination rendered near them.

## Round 2 — rebuilt against the measurement

**Every acceptance number met, and the truthfulness assertion still passes.**

### Defect 1 — the floor, measured with `scratchpad/framediff.js`

| capture | MIN % changed per interval | MAX % | dead intervals |
|---|---|---|---|
| ADS-B Exchange | 4.001 | 6.381 | 0 |
| Mini Tokyo 3D, rush hour | 4.908 | 7.947 | 0 |
| ~~ours, round 1~~ | ~~0.008~~ | ~~8.447~~ | ~~2~~ |
| **ours, round 2 — 16 frames @ 2.0 s** | **4.847** | **7.124** | **0** |
| **ours, round 2 — 12 frames @ 1.5 s** | **4.849** | **6.581** | **0** |

Spread 1.36-1.47 against the bars' ~1.6: **steadier than either bar, with a lower peak than round 1.**

**Independently re-measured on my own capture, not the builder's** (12 frames @ 1.5 s, fresh film):
`min 4.973 · max 7.917 · dead 0` — per-interval
`6.75 6.81 6.57 6.08 5.58 5.19 5.00 4.97 5.02 5.43 5.95 7.92 7.05 6.60 5.53`.
The floor clears ADS-B's 4.001 and matches Mini Tokyo's 4.908. The claim holds.

**The root cause was not only the dwell.** Weighting each leg by movers exposed it: 296 of 300 move on
morning->business, 296 on business->evening, and **0 on evening->morning** — every agent's evening placement
names the same place as its morning placement. Under equal 15 s beats, a third of the day is a *correctly
rendered* still field. Two fixes, neither costing a claim:

1. **No dwell** — the eased glide fills the whole leg. Ease is smoothstep blended 0.72 with a straight ramp so
   the quietest tenth of a leg still covers 7.98% of it (pure smoothstep: 2.8%).
2. **Wall time in proportion to the people a leg moves** — the zero-mover leg gets none. Skipping it is
   *provably invisible*: both ends name the same place, so coordinate and de-collision offset are identical and
   the day loops without one chip changing pixel. Asserted by test.

### Truthfulness assertion — PASS, re-run on the shipped code

| check | result |
|---|---|
| rendered positions verified | **3,600** (300 agents x 12 frames) |
| worst residual off the recorded segment | **0.007 px** (epsilon 0.02) |
| stationary violations | **0** |
| agents that moved | 296 of 300 |
| anchor mismatches · place marks exact | **0** · **266 of 266** |
| console errors | **0** |

### Defects 2-8

| # | Defect | Fix |
|---|---|---|
| 2 | every person an identical dot | a **wake** of the segment already covered (every pixel of it *on* the recorded segment); the **97 cross-border** people drawn a size up and ringed; **click anyone to pin** a halo that rides their pixel with name, occupation, all three placements and their whole day as a closed path |
| 3 | crowd and couple identical | a **ring at the de-collision radius with the headcount in it** wherever 4+ share a place, counted per slot from the chips actually drawn |
| 4 | encoding lost in motion | `currentColor` was the inherited page ink, hence white bloom; hue now on `color`, halo takes it from there, and the code hands over mid-leg as a **cross-fade** |
| 5 | stale anonymised tooltip | anonymised occupancy kept **per slot**; all three rows are `business` rows, so the marks are simply **absent** in the morning and evening |
| 6 | developer telemetry in the footer | `/api/v2/map 152 ms` and `/api/run/status 47 ms` **removed**; what survives is what was recorded, and when |
| 7 | dead space, invisible geography | **convex hull per region** from its own places' `region_id` + coordinates, one neutral ground; names off the field onto **plates outside the hull facing the empty band**; a 0.1 **graticule**; and the right inset now clears the day clock, which had been covering a third of Ironvale |
| 8 | wordmark collides | one line, `nowrap` — it had joined three region names, which are now plates on the territories they name |

Gate: ledger+replay **8 passed** · typecheck **clean** · **158 dashboard tests** (baseline 151, +7 new).

## Round 1 — built and filmed

Route **`/runs/:runId/live-city`**, registered *outside* `WorkspaceShell` so it owns the viewport rather than
sitting in a panel. Labelled **"Street Level"** in the rail — the builder declined to call it "Live City"
because Overview already carries that label and two identical labels in one nav is a coin toss.

**Motion**: one `requestAnimationFrame` loop writing `transform` to 300 nodes; React re-renders six times per
45 s day, never per frame. The clock is `performance.now()` against a day origin that resets on tick change, so
nothing waits for a push and the paused run replays its recorded day on a loop, labelled as such. Three 15 s
beats: 9 s dwell at a recorded placement, 6 s smoothstep glide.

**De-collision** is keyed on **(agent, place)** — deliberately *not* on the slot — so an agent returning to the
same place is pixel-identical, which makes "same place ⇒ no movement" exactly true rather than nearly true.
Cohort ranked by `stableHash` on a golden-angle spiral, capped at 34 px; 205 of 252 occupied places have one
occupant and so draw exactly on their coordinate. Worst observed offset 27.06 px.

### Truthfulness assertion — PASS

An independent checker re-fetches `/api/v2/map`, rebuilds each agent's recorded day itself, reads the **actual
DOM transform** of every chip, strips the declared offset, unprojects, and measures the residual against the
segments between consecutive recorded placements:

| check | result |
|---|---|
| rendered positions verified | **3,600** (300 agents × 12 frames) |
| worst residual off the recorded segment | **0.0068 px** (epsilon 0.02) |
| stationary violations — moved without a recorded change | **0** |
| agents that moved | 296 of 300; the 4 with no recorded business placement never did |
| anchor mismatches | **0** |
| place marks landing exactly on their recorded coordinate | **266 of 266** |

Plus 11 unit tests on the pure functions, including one asserting that a **fabricated detour is detected**.

**The disclosure ships, permanently, on the surface:** *"Movement between recorded points is interpolated. The
world records three placements per person per tick — morning, business, evening. Chips glide in a straight line
between those points, the journey itself is not recorded. Someone whose consecutive placements name the same
place does not move."*

Anonymised `privacy_aggregate` occupants render as a count at the office, never as people — surfaced in the
legend as *"4 anonymised at Northstar Federation Permit Office — shown as a count, never as people."*

Gate: ledger+replay **8 passed** · typecheck **clean** · **151 dashboard tests** (+11 new).
*Correction: the dashboard baseline was 140, not the 138 my brief stated.*

## The substrate — one endpoint has the whole city

`GET /api/v2/map` → 408 KB in 62 ms (paused): **899 presence rows = 300 agents × 3 slots**, every row with
`x`/`y` normalised 0–1, plus 266 `places`, 236 `firms`, 3 `regions`. `source_type`: `routine_home` 600 ·
`routine_work` 250 · `public_commons` 46 · `privacy_aggregate` 3.

**No backend plumbing was needed.** The plan assumed the World projection would have to be extended; it did not.

## Timing reality (measured)

A tick takes **44–49 s**, of which `MORNING` is ~45 s. The city gets **one frame of truth per ~45 s** — hence
the three-beat day paced across it. The WebSocket is *not* starved like HTTP (frames land ~0.3–1 s after the
tick boundary) but is **silent between ticks and indefinitely while paused**, so the UI animates locally off
last-known state.

> ⚠️ **Corrected by the running-world test.** Two claims in this section were measured against a *paused* world
> and do not hold against a running one. The city does **not** get one frame of truth per ~45 s — it got one in
> 369 s, because the status poll that detects a tick cannot complete while a tick is running. And the WebSocket
> is **not** exempt from the starvation: it dies on a keepalive timeout mid-run and then needs the same blocked
> event loop to reopen, which took **125 s**. See the running-world test above.

## Environment

| | | |
|---|---|---|
| Simulation | `127.0.0.1:8000` | run `53f5b4ce8c`, semantics 12, 300 agents, **paused at tick 355** (was 349 — the running-world test advanced it), spend `$0.00` |
| Dev server | `127.0.0.1:4174` | vite, proxies to `:8000` with the **stock** config |
| Motion capture | `scratchpad/film.js` | frames + labelled filmstrip + motion probe |
| Blind pairing | `scratchpad/harness.js` | randomised A/B with a sealed key |
| Running-world capture |  `scripts/live-city/runworld.mjs` | starts the world, films it, times every fetch to *body*, logs every WS cursor, samples the day clock and chip transforms per frame |

Rounds 1–3 were all captured at **tick 349**. Any figure in this document that is not inside the
running-world section was measured against a paused world.

### Operational incidents this session

1. **Servers were reaped mid-session.** Restored on `:8000` (was `:8002`), which also means the stock
   `vite.config.js` works unmodified — a future revert cannot break the proxy.
2. **A stray duplicate server on `:8002` was holding the same run database** as the canonical one on `:8000`.
   Two processes on one SQLite run DB is a real hazard. Killed.
3. **The working tree was switched to `main` mid-session by another process**, deleting `dashboard/src/ui/` and
   `design/`. Restored; nothing lost. Two other local sessions are operating in this same tree — anything
   uncommitted is at risk, which is why progress.md is now committed rather than left untracked.

## Do NOT build — these would be fabrications

| Tempting | Reality |
|---|---|
| Rumour arrows agent → agent | Information spreads by **broadcast lottery**; no transmitter recorded, all 98,058 exposures are `channel='news'` |
| Social edges forming over time | `social_ties` has no tick column — current state only |
| A movement event feed | No `agent_moved`/`travel` kind exists; movement lives only in `effective_presence` |
| Idle drift or milling | No motion without a recorded origin and destination |

Truthfully animatable instead: a claim washing across the population tick by tick — a spreading stain, never a
chain of arrows.

## Piece status

Legend: ⬜ queued · 🔨 building · 🔍 in judgement · ❌ rejected · ✅ critic picked ours blind

| # | Piece | Bar | Status |
|---|---|---|---|
| 1 | Full-bleed map + 300 agents at real coordinates + de-collision | MINI TOKYO | 🔍 round 1 in judgement |
| 2 | The commute — interpolated three-beat day | MINI TOKYO | 🔍 round 1 in judgement |
| 3 | Day clock driving atmosphere | MINI TOKYO | 🔍 round 1 in judgement |
| 4 | Interpolation disclosure | both | ✅ shipped |
| 5 | Conversation bubbles pinned at the co-located place | MINI TOKYO | ⬜ |
| 6 | Errands & scheduled intent | ADS-B | ⬜ |
| 7 | Click an agent → its day | ADS-B | ⬜ |
| 8 | Claim diffusion as a spreading stain | ADS-B | ⬜ |
| 9 | Live transport — fix the cursor bug, carry `city` in the delta | ADS-B | ⬜ |
| 10 | Density at 300 | ADS-B | ⬜ |
| **0** | **Unblock the serving event loop during a tick** | — | 🔴 **blocks everything above** — measured, see the running-world test |

Piece 0 was not on the list because the paused world could not reveal it. It now precedes all of them: until a
tick stops monopolising the loop, no front-end work is observable against a running world.

## Known bugs — status after the running-world test

- 🔴 **`previous_event_cursor` is wrong on *every* tick** (`server/projections/transport.py:41-43`) — and it is
  worse than "computed wrong". Every tick commits **exactly two** cursors, so the delta's `previous` always
  names an intra-tick commit the client was never sent, and `cursorReducer.js:67` flags `cursor_gap` on every
  live delta without exception. **Confirmed on the wire**, twice, with the client's held cursor logged.
  Mitigating detail also confirmed: the re-handshake's backfill chains correctly and the client does catch up,
  so the push path is broken-and-self-healing rather than silent. Piece 9.
- 🔴 **The serving event loop is starved for the whole tick** — `/api/run/status` (1 KB) took **123 s** and
  **219 s**; `/api/v2/map` never completed while running. This is the root cause of the city's staleness, and
  it was not on the bug list at all. Piece 0.
- 🔴 **A new tick mid-day teleports the population 330 px in one frame** — `dayOrigin` snaps to zero on
  `mapTick` with nothing carrying the old positions across. Fired once here only because maps were unfetchable;
  fixing the starvation makes it fire every tick. Piece 3.
- 🔴 **The badge says "Paused" while the world runs** — for the first **125 s**, because the status poll that
  would correct it is itself blocked. The label that distinguishes a replayed day from a live one is wrong in
  the direction that hides the failure.
- ✅ ~~⚠️ uvicorn's `ws_ping_interval`/`ws_ping_timeout` are 20 s while `MORNING` blocks ~45 s — keepalive drops
  are plausible.~~ **No longer an inference — observed:** `close code=1011 reason=keepalive ping timeout` at
  222 s, after which the socket needed **125 s** to reopen because opening it also needs the blocked loop.
- **My own error, on record:** the `45.4`/`45.3` sub-tick notation in the earlier design specimens was
  *invented*. Real instead: `events.phase` + monotonic `events.id` + millisecond `created_at`.

## Log

_(newest first)_

- **🔴 The running-world test was run — the city does not survive a live tick boundary.** Six ticks passed;
  one was rendered. The animation held 60 fps throughout, which is precisely why three rounds of paused
  judgement could not see it. Run advanced 349 → 355 and re-paused; spend `$0.00`.
- **Round 1 built, filmed and sent to blind judgement.** The city moves on real recorded placements; 3,600
  positions machine-verified with a worst residual of 0.0068 px.
- **Stray duplicate server on `:8002` killed** — it was holding the same run DB as `:8000`.
- **Bars verified by film; Flightradar24 rejected** and replaced with ADS-B Exchange after filming revealed a
  CAPTCHA behind a valid-looking page title.
- **Branch `feat/live-city` opened**, prior design-system work committed as baseline `8b08902`.
- **`/api/v2/map` confirmed sufficient** — the planned backend plumbing piece was unnecessary.

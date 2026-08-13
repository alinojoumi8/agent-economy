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

## Round 1 — built and filmed ✅

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

## Environment

| | | |
|---|---|---|
| Simulation | `127.0.0.1:8000` | run `53f5b4ce8c`, semantics 12, 300 agents, **paused at tick 349**, spend `$0.00` |
| Dev server | `127.0.0.1:4174` | vite, proxies to `:8000` with the **stock** config |
| Motion capture | `scratchpad/film.js` | frames + labelled filmstrip + motion probe |
| Blind pairing | `scratchpad/harness.js` | randomised A/B with a sealed key |

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

## Known bugs found while planning (not yet fixed)

- 🐛 **`previous_event_cursor` is computed wrong** (`server/projections/transport.py:41-43`) — resolves to the
  *same* tick's earlier commit, never the cursor the client holds, so `cursorReducer.js:70-72` flags
  `cursor_gap` on **every** live delta and the payload is discarded and re-handshaked. Source of the permanent
  "stale" banner. Piece 9.
- ⚠️ uvicorn's default `ws_ping_interval`/`ws_ping_timeout` are 20 s while `MORNING` blocks ~45 s — keepalive
  drops are plausible. Inferred from library defaults, not measured.
- **My own error, on record:** the `45.4`/`45.3` sub-tick notation in the earlier design specimens was
  *invented*. Real instead: `events.phase` + monotonic `events.id` + millisecond `created_at`.

## Log

_(newest first)_

- **Round 1 built, filmed and sent to blind judgement.** The city moves on real recorded placements; 3,600
  positions machine-verified with a worst residual of 0.0068 px.
- **Stray duplicate server on `:8002` killed** — it was holding the same run DB as `:8000`.
- **Bars verified by film; Flightradar24 rejected** and replaced with ADS-B Exchange after filming revealed a
  CAPTCHA behind a valid-looking page title.
- **Branch `feat/live-city` opened**, prior design-system work committed as baseline `8b08902`.
- **`/api/v2/map` confirmed sufficient** — the planned backend plumbing piece was unnecessary.

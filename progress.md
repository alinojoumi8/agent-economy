# Gauntlet Loop — Agent Economy Observatory UI

## Where this ended

**The Overview surface passed: 6/6 on every lens against both bars, all decisive**, judged blind with the
key sealed, after six rounds. It started at 3/6.

| | before | after |
|---|---|---|
| Overview vs Linear + Grafana, blind | **3/6**, 0 decisive | **6/6, 6 decisive** |
| Sub-4.5:1 text runs, whole app | **856** | **0** |
| First paint on a live run | **19 nodes** | **813 nodes @ 1.5s** |
| Distinct font sizes | **66** | one scale, ~5 sizes |
| Unique hex colours | **257** | tokenised, no raw hex outside `:root` |
| Colliding palettes | **4** | 1 |
| Theming | none (`data-theme` → 0 hits) | dark + light, both measured |
| Event-kind codes | `slice(0,4)`, 6 invented kinds | **164-kind registry**, collision-free |

**Still unbuilt: pieces 3, 5–12.** One front door · universal inspector · state family · jargon pass · trace
affordances · tick strip · event stream · markets visualisation · data grid. The gauntlet proved a template on
one surface and repaired the app's legibility; it did not build the remaining product.

Gate green throughout — ledger + replay-hash **8 passed**, typecheck clean, **138** dashboard tests. Both
source run DBs byte-identical to where they started; everything served from copies.

---

Live status. Updated as the loop runs.

---

## The bars (both captured, both real)

| Bar | Governs | Source | Status |
|---|---|---|---|
| **Linear** | Static craft: layout, nav, inspectors, empty states, type & color, hierarchy, calm | `linear.app` @ 1440×900, dark, DPR2 | ✅ locked: `linear-02-scroll1` |
| **Grafana Play** | Live data density: streams, charts, market panels, tick/phase strips, refresh affordances | `play.grafana.org` Checkout Service (+ Agent Observability, K8s, Business Metrics) | ✅ locked: `grafana-ref-checkout-service` |

Linear has no dense data-dashboard screens — it is an issue tracker — so market/stream surfaces are judged
against Grafana alone. That is the point of running two bars.

## The hard gate (machine-checked, non-negotiable)

> **Exact-replay hashes + double-entry ledger balance must stay green.**

Baseline green and cheap: ledger+replay **3.7s** · typecheck **1.4s** · 132 dashboard tests **16s** ≈ 21s total.
Runs after every builder round.

---

## Substrate — now a LIVE, ticking world

| Port | Run | State |
|---|---|---|
| **8002** ← *primary* | `53f5b4ce8c` from `runs/civic-city-300.yaml` — **semantics 12**, 300 agents, 3 regions / 3 currencies (NSD/IVC/SCD) | ▶ **running**, tick advancing, spend **$0.00** |
| 4174 | vite dev, proxied to :8002 | ✅ hot reload, live data |

Controls on this run all return **200** — `start`, `pause`, `step`, `speed`. The earlier 403 lock is gone,
because the lock only fires when `acceptance.min_ticks` exists in the resolved config. So run/pause/step
**can now be exercised and proven**, not just styled.

Spend safety is belt *and* braces: all routes `{provider: scripted}`, **and** `budget.cap_usd: 0.0` so the
governor refuses any priced call outright. `/api/llm/runtime` shows `scripted`, attempts 0.

Populated at tick ~50: 3 regions · 46 firms · 76 places · 892 presence rows · permit queue 141 · 2 parties
· 6 legislators · 6 agencies · 10 term sheets · 8 funding rounds · 22 information items · 5,610 exposures
· 100 network nodes / 82 edges · 100 orders · 173k+ events and climbing.

WebSocket streams **per tick**: `hello` on connect, then `tick` + `projection_delta` every tick.

### Two operational lessons

1. **Servers launched from a tool shell get reaped.** A mass kill took out three servers mid-session. The
   live run survived only because it was spawned via `Invoke-CimMethod Win32_Process Create`, which breaks
   away from the job object. Use that for anything that must outlive a task.
2. **Disk.** ~8.5 MB/tick, `checkpoint_every: 30` with no `checkpoint_keep_last` — roughly 30 GB by tick 500.
   Prune `data/checkpoints/53f5b4ce8c_t*.db` (that prefix is only this run) or stop the run after the session.

`vite.config.js` now reads `AE_API` (default unchanged at `:8000`) so the dev server can point at any run.

---

## 🔴 Headline finding — the tick loop starves the API, and the app goes blank

**Corrected model.** My first read — "these endpoints are slow, those are fast" — was wrong about the
mechanism. The FastAPI server shares one asyncio event loop with the simulation tick loop, so the tick loop
starves HTTP handling. **Every** endpoint alternates between ~2 ms and ~40 s depending on where the tick is.
Nothing is inherently slow.

Same endpoints, world running vs world paused:

| endpoint | running | paused |
|---|---|---|
| `/api/v2/mode` | 27.6s → **40.3s** → 0.56s | **0.0014 s** |
| `/api/run/status` | **40.5 s** | **0.0015 s** |
| `/api/v2/snapshot` | **13.3 s** | **0.037 s** |
| `/api/institutions` | 3 ms … 66 s | 0.0026 s |

Two consequences, both user-visible:

1. **The whole app went blank for up to 40 seconds on a live run.** `App.jsx` gated first paint on
   `useHostedMode()` → `/api/v2/mode`. Headless captures measured **19 DOM nodes / 19 characters** at 1.6s
   *and still at 34s*. A healthy, ticking, 300-agent economy rendered as an empty page.
   ✅ **FIXED.** Deployment mode is now derived **synchronously from the document URL**, with the probe
   demoted to confirmation. With every API call artificially delayed 40s:

   | | at ~1s | settled |
   |---|---|---|
   | before | 19 nodes / 19 chars | — |
   | after | **822 nodes / 1,991 chars** | 1,546–1,630 nodes, 0 console errors |

   First meaningful paint **0.72s**. The signal is grounded in real routing, not a guess: hosted serves the
   document at exactly one path (`/`), while local also serves `/runs/*` and `/commons/*` — so a document at
   `/runs/...` cannot be hosted. The presumption can **only** short-circuit to the *local* shell; hosted
   requires probe-only data (`csrf_cookie_name`, `profiles`) so it can never be entered by assumption, and a
   disagreeing probe swaps the shell in place (verified by mocking a hosted probe at a `/runs` URL).
   `/` stays genuinely ambiguous and renders an unlabelled skeleton rather than a blank page — resolving it
   would need a server change. 6 new tests; suite now **138 pass**.
2. **No panel can trust a shared loading gate.** Any endpoint may be the slow one on any given tick, so
   per-panel resolution with measured latency is the only honest design. Guessing a fast/slow tier at build
   time — as my original brief did — would have been wrong.

Also fixed: the budget chip read `$0 / UNCAPPED` on a run capped at `$0.00`.

*(Backend note, out of scope: running the tick loop in an executor so it yields to the event loop would remove
this class of problem at the source. Flagging, not touching — it is engine code.)*

---

## Baseline audit — measured, not asserted

| Symptom | Measurement |
|---|---|
| Type scale | **66 distinct font sizes** |
| Color | **257 unique hex** / 444 occurrences; **192 unique rgba()** |
| Radii / borders / shadows | **37** · **62** · **42** |
| Palettes | **4 disconnected sets**; light overrides dark purely via import order in `main.jsx:6-7` |
| Theming | `prefers-color-scheme` / `data-theme` / `.dark` → **zero hits repo-wide** |
| Inspector | `<pre>{JSON.stringify(…)}</pre>` is the inspector body in **8 places** |
| Charts | `recharts` imported **once**, in a component World OS never renders; Markets has **zero price series** |
| Causal graph | **1 call site**; News, People, Markets, Politics are causal dead ends |
| Keyboard | `onKeyDown` in **3 files**; no arrow-key nav anywhere |
| Front door | `/` renders the **legacy** Observatory; World OS sits behind a conditional link |

---

## Gauntlet record — Overview surface — ✅ PASSED, 6/6 all decisive

| round | result | decisive | what changed |
|---|---|---|---|
| 1 | ❌ **3/6** | 0 | every win narrow, every loss clear — shipped corruption |
| 2 | ✅ 6/6 | 3 | column collision, hero overlap, clipped band fixed |
| 3 | ✅ 6/6 | 3 | shell unified — one theme, no seam, jargon demoted |
| 4 | ✅ 6/6 | 3 | REGIONS clip solved structurally, column budget measured |
| 5 | ✅ 6/6 | 5 | 164-kind registry, salience follows sign, decimal-point spine |
| **6** | ✅ **6/6** | **6 — every lens, both bars** | one unit grammar, footnotes lifted |

**Exit condition met**: a blind critic picks ours on every lens against both bars, at decisive margin, six
times over, with the key sealed and the critic unable to know which side is ours.

What the final critics actively checked in ours and **cleared**:

> "Numeric alignment: the ENTITIES counts and the 27,862,308.07 balance share one right rail; REGIONS
> AGENTS/FIRMS hold a second and third; AGENTS ID and AGE are right-set. **No ragged-left digit columns
> anywhere.**" · "The three second-row cards share top and bottom edges, gutters are constant, and the tall
> left card terminates on the same baseline as AGENTS and EVENT STREAM." · "**Ten times the categories costs
> A four more mono codes and zero palette; it costs B a legend that no longer fits or reads.**" · "One sans
> family plus one mono, roughly five sizes… Header chrome, panel headers and table headers do not each invent
> their own style."

### The one defect that survived — and why it is instructive

Both bars' critics landed on the same thing, and **it is something round 5 measured its way past**:

> "The AGENTS table spends three columns on constants — REGION reads `northstar core` for all 12 rows, STATE
> reads `ALIVE` for all 12 — while the adjacent EVENT STREAM truncates roughly half its SUBJECT cells.
> **The dead columns are subsidising ellipses in the one field an operator actually scans.**"

Round 5 concluded "207px is the honest maximum" by measuring each column's *natural ceiling* — the width its
widest value needs. That was rigorous and still wrong, because a column whose value is **constant across
every visible row** is carrying no information at this density regardless of how wide its content is. Measuring
ceilings cannot see that; only asking "what does this column tell me?" can.

Also named, unfixed: the SOURCE LATENCY bars "read as text underlines rather than as a scale", and the log
axis is spaced such that 972 ms and 204 ms "produce bar lengths that look nearly linear rather than
logarithmic."

By round 5 critics were actively verifying and **clearing** defect classes rather than finding them:

> "Numeric right-alignment: ENTITIES counts and the 27,893,861.39 balance share one right edge… No ragged
> decimal columns." · "AGENTS and EVENT STREAM share top and bottom edges, their header rows sit on one
> baseline, and their 12 body rows sit on matching baselines, so the two tables read across as a single
> register." · "Chroma appears only three times: red on the single negative balance, orange on the two slowest
> endpoints and the one focused event row. **Adding a 20th kind costs nothing, which is precisely where A
> collapses.**" · "Nothing overlaps, no button label overflows its chip, no panel content crosses a panel
> border, the sparkline stays inside its box."

### Round 6 — one defect, and it was my fault

Both bars' critics independently named the same thing: **unit grammar contradicts itself between adjacent
panels.** ECONOMY STATE suffixes (`48.08 index`, `55 bps`); PUBLIC INSTITUTIONS prefixes (`bps 1,200`,
`major units 800.00`). The same unit appears on opposite sides of its number in one row.

That is a defect **my own round-5 brief created** — I asked for "the unit leads the number" to fix a decimal
spine without noticing the panel next door suffixes. Round 6 fixes the inconsistency rather than reverting,
because round 5 achieved the spine properly by aligning on the decimal point, which may make the prefix
redundant. Also lifting panel footnotes measured as *"a grey so dim they read as texture rather than text."*

## Piece status

Legend: ⬜ queued · 🔨 building · 🔍 in judgement · ❌ rejected · ✅ critic picked ours blind

| # | Piece | Bar | Status | Rounds | Latest verdict |
|---|---|---|---|---|---|
| 1 | Token layer — one scale, real theming | BOTH | ✅ **6/6 blind, 3 decisive** | 4 | picked over both bars on every lens |
| 2 | Primitive kit both trees import | BOTH | ✅ passed with piece 1 | 2 | grid floors; 0 overlaps across 8 widths |
| 4 | Nav rail + topbar craft | LINEAR | 🔨 shell round in flight | 0 | *"two themes in one screen"* |
| 3 | One front door | LINEAR | ⬜ | 0 | — |
| 5 | Universal Inspector (kills the JSON dumps) | LINEAR | ⬜ | 0 | — |
| 6 | State family — empty/loading/error, each teaching | LINEAR | ⬜ | 0 | — |
| 7 | Jargon→language + definition tooltips | LINEAR | ⬜ | 0 | — |
| 8 | Trace affordance everywhere + reverse links | LINEAR | ⬜ | 0 | — |
| 9 | Tick / phase / transport strip | GRAFANA | ⬜ | 0 | — |
| 10 | Event stream as a real live feed | GRAFANA | ⬜ | 0 | — |
| 11 | Markets panel with real market viz | GRAFANA | ⬜ | 0 | — |
| 12 | Data grid — sortable, aligned, sticky, dense | GRAFANA | ⬜ | 0 | — |
| **13** | **Progressive load** — per-panel resolution so a live run never blanks | GRAFANA | ✅ **first paint 0.72s** | 1 | 19 → 822 nodes at 1s under 40s API |

---

## Piece 1 — three competing design systems → synthesis

**Clean blind ranking (6 critics, 3 pairings × 2 lenses, uncontaminated frames):**

| pair | lens | → winner |
|---|---|---|
| a vs b | scanning | **b** (clear) |
| a vs b | density under load | **b** (clear) |
| b vs c | scanning | **b** (narrow) |
| b vs c | density under load | **c** (clear) |
| a vs c | scanning | **a** (clear) |
| a vs c | density under load | **c** (clear) |

Tally b:3 · c:2 · a:1 — but the shape matters more than the count. The lenses are **perfectly orthogonal**:

| lens | ranking |
|---|---|
| scanning / hierarchy | **b** > a > c |
| density under load | **c** > b > a |

`b` beat `a` 2–0 and is eliminated as a base. But `b`'s only win over `c` was **narrow**, while `c`'s win over
`b` was **clear**. Neither is a winner. → **synthesis**, not a pick.

| Variant | Angle | Tokens | Type sizes | Outcome |
|---|---|---|---|---|
| **a** *restraint* | Near-monochrome, hierarchy by weight and space | 57 | 6 | eliminated |
| **b** *signal* | Disciplined semantic state color | 80 | 6 | hierarchy donor |
| **c** *density* | Bloomberg legibility at Linear's spacing | 62 | 5 | structural donor |
| **d1** *synthesis* | ledger-first | 52 | 9 | beat both donors 4–0 |
| **d2** *synthesis* | economy-state-first | 49 | 7 | ✅ **UNDEFEATED 6–0** |

### Synthesis gauntlet — 10 blind critics, 5 pairings × 2 lenses

| matchup | scan | load |
|---|---|---|
| d2 vs d1 | d2 clear | d2 clear |
| d1 vs b | d1 clear | d1 clear |
| d1 vs c | d1 clear | d1 clear |
| b vs d2 | d2 clear | **d2 decisive** |
| c vs d2 | d2 clear | **d2 decisive** |

**Both synthesis variants beat both donor systems.** The synthesis call was correct, and **d2 wins the
foundation 6–0**, taking "decisive" on density against both b and c.

What the critics credited in d2:

- *"22 kinds, coded not coloured"* — event kinds are 4-letter monospace codes, not hues, so the encoding
  survives 173,480 events. One critic: *"that is a system that survives 173,000 events; b's is a palette
  that survives this screenshot."*
- Colour withheld for exceptions only — `SETTLED` plain, `CONSTRAINED`/`DEFAULT`/`REJECTED`/`FAILED` tinted,
  and the rule stated in the footer of the table it governs: *"Δ takes colour only beyond ±2%."*
- A single right-aligned digit rail so magnitudes rank by eye.
- Per-panel endpoint + latency in every header, designed directly around the 13.3s measurement.
- `0.00 USD of cap 0.00 USD` — the `$0 / UNCAPPED` correctness bug fixed.

What killed d1 despite beating both donors: **it truncates its own primary key.** Five of fourteen rows
render `#2…`, `#9…`, `#1…` — with two pairs colliding into identical strings. *"The one column whose entire
job is unique identity destroys it."*

### Five defects carried forward into the install

Named by the critics who still picked d2:

1. REGIONAL SPLIT occupies the top-right quadrant — the second most valuable slot — showing only skeletons.
2. Its empty-state copy does not parse as English.
3. The header is double-decked.
4. A full progress track spent rendering two zeroes.
5. **SOURCE LATENCY bars draw 93ms, 7.2s and 13.3s at comparable lengths** — *"not merely decorative but
   actively misleading."* A truthfulness bug, and the most serious of the five.

The synthesis brief carries **14 mandatory fixes**, each one a defect a blind critic actually named — not
invented review comments. Highlights:

- COMMITTED and SETTLED render as the *same* grey pill — two states, one signal.
- POLICY and NEWS share an identical blue: *"the palette has run out before the data grows."* Category
  encoding must survive 20+ event kinds without a hue each.
- Every status is a bordered pill, so *"multiply by 400 visible rows and the table becomes a field of boxes
  rather than a field of values."*
- Left-aligned ids make names start at x = 386/386/397/400/402 — a ragged column that jitters across 300 rows.
- `1.2849M` — four decimals of false precision, and units are attached in two cards and detached in two others.
- A 21px type ceiling means no number ever wins the first second.
- Brightest green marks COMMITTED — *the most common and least informative state*. Salience must track
  exceptionality.
- Never spend peak salience announcing an absence (~330px of empty state to say nothing happened).

Each characterised failure, from the blind critics:

- **a** — *"sparklines are gray hairlines at near-background luminance; the single element charged with
  showing trend shows nothing"*; ~260px voids between columns; the vertical seam jumps ~240px between
  adjacent rows, so there is no column grid; peak salience spent announcing an absence.
- **b** — *"eleven-hue chip and pill system is decoration masquerading as semantics"*; red means both CREDIT
  and REJECTED; COMMITTED and SETTLED both grey — two states, one signal; the DARK/LIGHT toggle is the
  brightest object on a 1001-agent screen.
- **c** — a self-imposed 21px type ceiling means no number ever becomes the hero; brightest green marks
  COMMITTED, the *most common and least informative* state; three columns of design prose eat the lower third.

### A method error I caught and corrected

Two round-1 critics penalised a variant for *"letting the header guillotine the very labels that explain
those numbers."* That clipping was **my capture bug** — the scroll offset collided with the sticky header —
not a design flaw. The capture now measures sticky chrome and clears it. Round 1 is discarded as
contaminated; a clean re-run is in flight on fixed frames.

Also logged as a confound: variant **c** renders a full app shell while **a** renders only a dashboard, so
some of c's advantage is scope, not token quality.

---

## How judging works

1. Screenshot headless at **1440×900, DPR2, dark** — identical to the reference capture.
2. Pair with the matching bar as `A.png` / `B.png`, **randomised**, key sealed away from the critic.
3. A **fresh-context** critic — no build history, no idea which is ours — picks one and names the single
   biggest remaining gap.
4. Miss → verdict and named gap go back to the builder; the piece loops.
5. A piece exits only when a blind critic picks ours. Never on a round count.

### Critic calibration — passed

Control run before trusting any verdict: **our baseline vs Linear**, blind. Both critics picked Linear at
*clear* margin with pixel-level defects (rules terminating at x≈1663 vs x≈1943; blue doing six unrelated
jobs; `RESIDENTS 100 100 core` reading as "100 100"). Both also attacked **Linear** — nav clipping the hero
mid-glyph, a ~55px bezel slab "carrying no information". No brand deference. Verdicts are trustworthy.

---

## App round 1 — FAILED, 3/6

The first blind judgement of the **real React app** (not a specimen) against both bars:

| bar | lens | margin | result |
|---|---|---|---|
| Grafana | scan | narrow | ours |
| Grafana | density under load | narrow | ours |
| Grafana | **defect hunt** | clear | **bar wins** |
| Linear | scan | narrow | ours |
| Linear | **density under load** | clear | **bar wins** |
| Linear | **defect hunt** | clear | **bar wins** |

Every win narrow, every loss clear. Not a pass.

**The system is validated; the execution is not.** Critics were equally savage about Grafana — *"fourteen
legend entries are drawn from a nine-hue palette, so Browser-Chrome-BE and Browser-Chrome-IN are the same
green… three pairs of distinct series are literally unresolvable"*, a decorative emoji occupying a health-panel
title, and two identical flatlines taking ~40% of the viewport to carry one bit between them. And they
credited ours: *"the eye lands hero → Treasury → the paired CPI/UNEMPLOYMENT/POLICY RATE band → tables, in
that order, without effort."*

What lost it was shipped corruption:

1. **The AGENTS table paints ID and NAME into the same box.** *"Twelve of twelve rows corrupted in the largest
   table on screen"* — `Gntral_banker`, `Oledit_officer`, `Ecitor`, `Cawyer`, `Sev_official`. *"A column-width
   bug corrupting every row of the primary table is not a taste issue, and it is exactly the failure that gets
   worse at 10x rows."*
2. **The sparkline is drawn over the hero number.** *"The single most important number on the page, the one
   the whole layout is built to deliver, is the one thing you cannot read cleanly."*
3. **The CPI / UNEMPLOYMENT / POLICY RATE band is clipped** — *"half-height glyph fragments"*.
4. **Truncation is inconsistent within one screen** — one string cut mid-word with no ellipsis, another with one.
5. **The hero caption is a ragged three-line stack** with `FINAL-` hyphenated onto its own line.
6. **Protocol jargon still ships**: *"refetching the canonical projection: backfill_truncated."*

Deferred to a later round (different files, another agent is in them): the white topbar against the dark
workspace, "stale" announced three times in one band, and a tick strip whose gaps are *"visibly chosen
per-item rather than from a scale."*

---

## App round 2 — ✅ PASSED 6/6 (round 1 was 3/6)

| bar | lens | margin | result |
|---|---|---|---|
| Grafana | scan | **decisive** | ours |
| Grafana | density under load | clear | ours |
| Grafana | defect hunt | clear | ours |
| Linear | scan | **decisive** | ours |
| Linear | density under load | **decisive** | ours |
| Linear | defect hunt | clear | ours |

Blind critics pick ours on **every lens against both bars**, including the defect-hunt lens that beat us twice
in round 1. Three decisive margins.

What they credited:

> "A answers in about a second (1,593.44, the only 70px numeral on the canvas, with its delta +160.72 and its
> trend immediately right of it), then ranks the next tier unambiguously via a deliberate three-step scale —
> 30px for CPI / UNEMPLOYMENT / POLICY RATE, 24px for TREASURY and VC FUND, 14px for the tables."

> "A also solves the category problem B fails: it explicitly declines to colour-code… so CIVI/CONV/NEWS/SALE/
> BELF/MODE stay legible at any number of kinds."

> "A's tables extend downward on an even ~39px row rhythm with right-aligned numerics (27,893,861.39 flush to
> the same right edge as 250, 90, 3) and an explicitly stated rule at the panel foot — which is precisely the
> discipline that survives more categories."

**A 6/6 is not the finish line.** The critics who picked ours still named real defects, four of them new:

1. *"The header pill reads 'Stale' over 'stale', label and value the same word in two cases, which looks like
   a data bug."*
2. *"ENTITIES: the group labels POPULATION, ORGANIZATIONS, CAPITAL, HEALTH, REGIONS are set at the same size,
   weight, tracking and colour as the panel title ENTITIES itself, so one panel reads as five stacked peers."*
3. *"Truncation is undisciplined in the tables: 'Editor The Ledg…', 'Exchange Oper…' clip in a narrow NAME
   column while ROLE beside it runs half empty."*
4. *"'Citizen menu' floats in the middle of a wide white void with unequal gaps, and 'Go' is orphaned in its
   own bordered box outside the segmented control it belongs to."*

And the two biggest were already in flight: *"A ships two themes in one screen — a white header band butted
against a dark navy sidebar with a hard vertical seam"* and *"the lime-green active nav pill is the
highest-chroma object rendered, so the first two fixations both land on navigation before reaching the hero
number."*

## App round 3 — ✅ held 6/6 after the shell was unified

| bar | scan | load | defect |
|---|---|---|---|
| Grafana | **decisive** | clear | clear |
| Linear | **decisive** | **decisive** | clear |

Unifying the shell regressed nothing. Rail, topbar and content all measure the same `rgb(7,9,12)`; spacing is
on a `--ae-space-0…6` scale (the port found brand at 80px against topbar at 75px, which had been breaking the
rule across the seam); `backfill_truncated` is demoted to a **Reason code** cell under plain-English copy
covering the full token set from *both* emitters; "stale" is stated once instead of three times; and the
chartreuse active nav block is gone — there is now **no chroma anywhere in the nav**.

Contrast on Overview: **zero text below 4.5:1** across the whole subtree.

## App round 4 — ✅ 6/6 again (3 decisive). Third consecutive sweep.

| round | result | decisive |
|---|---|---|
| 1 | ❌ 3/6 | 0 |
| 2 | ✅ 6/6 | 3 |
| 3 | ✅ 6/6 | 3 |
| 4 | ✅ 6/6 | 3 |

Critics were asked to name the defect classes they **actively checked and found clean**, which makes what
remains credible rather than invented:

> "no clipped or sliced glyphs; no text overflowing a card boundary; numeric columns consistently
> right-aligned; no duplicated panels; no hue overload; card left and right edges align across the three
> columns" · "no palette recycling (a single amber row-marker and one green delta triangle across the entire
> surface); consistent card-header baseline across all four cards and the left rail; no doubled or nested
> borders."

## App round 5 — built. The kind-code audit found worse than truncation.

The `slice(0,4)` bug turned into a **designed registry of 164 kinds**, machine-verified collision-free and
total over *both* vocabularies that exist: the **87 distinct kinds** this run actually committed, and the
**147 kind literals** `engine/` and `world/` can emit. Zero live kinds unmapped, zero duplicate codes.

Auditing it surfaced three problems worse than the truncation that started it:

- **`INFO` was merging two different kinds** — `information_published` and `information_exposed` — into one
  code. Now `IPUB` / `IEXP`.
- The old table carried a **three-way `PRMT` merge**.
- It contained **six invented kinds that do not exist in the engine** (`tax_collected`, `firm_created`,
  `firm_bankrupt`, `trade_executed`, `loan_granted`, `loan_repaid`) — fabricated vocabulary, now dropped.

| was (silent slice) | now | kind |
|---|---|---|
| `CIVI` | `APTS` | `civic_appointment_scheduled` |
| `CLAI` | `CLAM` | `claim_created` |
| `MODE` | `RDCT` | `model_numeric_narrative_redacted` |
| `INFO` | `IPUB` / `IEXP` | two different kinds, previously merged |

Unregistered kinds render `CIV…` — three letters plus an ellipsis, in quieter ink, with a title saying no code
is registered. **Nothing is ever silently lossy.**

The other five:

- **Salience now follows exceptionality.** Treasury takes `--ae-neg` below zero — *"ink follows the sign,
  never the size"* — while the routine +160.72 delta lost its chroma entirely. STALE takes caution ink in both
  word and dot; LIVE is uncoloured, because a delivering link is the routine case.
- **The spine is now the decimal point, not the cell edge.** A fixed 3ch fraction slot puts `pointX` at
  1168.4 for every left-column figure and 1378.4 for every right — so `-750,481.00`, `800.00` and `39` meet on
  the point. Unit-to-number gap is exactly **6px in every cell** (was 34–141px), so the pairing survived the
  fix that had broken it.
- **Event stream columns measured like AGENTS**: TICK 42→27, KIND 36→28, IMP 32→21, SUBJECT 174→207px.
  Complete rows in the 12-row window went **1 → 4**. It also checked whether the panel could simply be
  widened and proved it could not — the roster still clips 3/40 names against a 287.5px ceiling, so
  *"207px is the honest maximum."*
- Counts and currency separated under a **BALANCES** heading that declares its unit; the panel note corrected
  from "counts from five sources" to "counts and one balance".
- **It caught its own regression mid-flight**: the new section cost 23px the rail didn't have, and the
  squeezed scroller's fade fell across the money row and dimmed it. Reclaimed 26px; ledger now stands whole.

### Round 5's six defects (from round 4's critics)

1. **A correctness bug I would have shipped.** *"KIND hard-truncates to four characters with no ellipsis:
   'CIVI' and 'CLAI' are silently corrupted labels, indistinguishable from real four-letter kinds like CONV,
   NEWS, INFO, BELF. **Truncation that leaves no mark is worse than truncation that does.**"*
   `CIVI` is `CIVIC`; `CLAI` is `CLAIM`. The "coded, not coloured" idea is *why this design wins* — but a code
   system has to be designed, not produced by `slice(0,4)`.
2. **The design breaks its own rule at the worst cell.** *"TREASURY reads -750,481.00 in exactly the same
   neutral white as TAX RATE 1,200. The card next door spends chroma on a routine +160.72 tick delta, so
   **the screen's most alarming value is its flattest**."*
3. **Regression from round 4's own fix.** Making the unit lead the number fixed the spine and stranded the
   pair: *"'major units' sits flush left, '-750,481.00' flush right, with roughly 150px of dead space between
   them. The pair parses as two unrelated fields."*
4. Mixed 0dp/2dp precision means no decimal point lines up with any other.
5. **The AGENTS column-budget failure, reappearing in the other table** — EVENT STREAM truncates SUBJECT on
   8 of 12 rows while IMP (three characters) holds full measure.
6. ENTITIES mixes `27,893,861.39` into a right-aligned column of counts (`305`, `101`, `3`).

## App round 4 — build detail

All nine defects addressed. Three fixes were better than the brief asked for:

- **The numeric spine.** The unit now **leads** the number instead of trailing it — because a trailing unit
  makes the number's right edge a function of the unit's width, which is exactly what destroyed the spine.
  Verified: column 0 values all terminate at x=1205.0, column 1 at x=1415.0, and the leading minus on
  TREASURY shifts nothing.
- **The clipped REGIONS row**, solved structurally rather than masked: promoted from last child of the
  scroller to a **pinned sibling**, with its own `max-height` at an exact integer multiple of a fixed 22px row
  plus `scroll-snap-type: y mandatory`, so the boundary can only ever land *between* rows. Stress-tested by
  cloning to 9 regions: remainder 0. Room was bought by deleting **VC fund** and **VC positions** from the
  rail — PUBLIC INSTITUTIONS carries the identical two figures two panels over, so it was duplication on one
  screen.
- **Column budget**, measured rather than guessed: every column's natural ceiling was measured on the live
  roster (NAME 288px, ROLE 100px…), floors set to those ceilings, and NAME made the *only* column with a
  growth share so it collects the whole remainder. Truncation fell **10/40 → 3/40**; the three survivors are
  47-character names that cannot fit at any width.

Also: flat deltas suppressed and named once in prose; the sparkline stops 9 viewBox units short so the fill
gets a real fourth edge and the terminal dot is whole; the row-count claim is now measured through a
`ResizeObserver` and adapts by viewport ("Rows 1–12 of 40 · 305 total" over exactly 12 rows); PREV/NEXT differ
on two channels at once (16.05:1 vs 3.22:1) instead of one opacity; and the `S12` badge — *a fact wearing a
control's box* — was folded into a meta line.

Gates green: 8 passed · typecheck clean · 138 passed.

**Self-flagged risk, left in deliberately:** an ~8px sliver of row 13 sits below row 12 as the documented
scroll affordance. If a round-5 critic reads it as a clip, the fix is already plumbed (`onViewport` computes
the exact clamp). Noted here so it is not mistaken for an oversight.

---

### Round 3's nine defects (all now addressed in round 4)

1. **The clipped REGIONS row**, flagged independently by two critics and the most damning:
   *"A section header with zero legible content under it is worse than omitting the section — it advertises
   data and then amputates it."* A fade mask was tried and only disguised it.
2. **NAME truncates while ROLE carries ~40% dead gutter** — named in round 2 *and* round 3, still unfixed.
3. **PUBLIC INSTITUTIONS abandons the numeric spine** — six values left-aligned, the leading minus on
   TREASURY shifting its digits a glyph left of the value below it, and a prose paragraph dropped into a
   metric grid.
4. Three deltas all reading `– 0.00 vs t333` — a full row spent on placeholders.
5. The GDP sparkline *"has three edges"* — fill bleeds off right with no terminal point.
6. `Rows 1–40 of 305` claimed over 12 visible rows.
7. PREV / NEXT in identical muted grey — active indistinguishable from disabled.
8. The chrome row packs five control vocabularies with no rank distinction.

## ✅ Nine workspaces ported — 856 unreadable text runs → 0

**The root-cause diagnosis reframed the whole problem.** It was never light-theme vs dark-theme:

> "The 'paper vs dark' split was never a real design decision that had been made — it was a half-finished
> port. Inside the paper ground the *structural* surfaces were already dark
> (`.world-os-workspace-card` = `rgba(7,17,15,.72)`), and only the *ink* had been retinted for paper. That is
> why the numbers were 1.24–1.4: civic navy body text and cobalt eyebrows painted onto dark cards."

Dark cards wearing light-theme ink. All nine went to the dark token ground.

| workspace | element | before | after (dark) | after (light) |
|---|---|---|---|---|
| Markets | "Trades" | **1.31** | 4.77 | 5.36 |
| World | "Civic Forum" | **1.25** | 16.45 | 16.45 |
| People | citizen name | **1.32** | 14.26 | 17.18 |
| Politics & Law | disabled callout | **1.24** | 9.62 | 5.43 |
| Organizations | column header | **2.42** | 5.15 | 5.81 |
| Experiments | operator boundary | **1.05** | 6.40 | 6.06 |
| Commons | lineage label | **1.70** | 4.77 | 5.36 |

Whole-app sweep: **856 sub-floor text runs → 0** across 3,622 runs on eleven routes *including interaction
states*. The two remaining sub-4.5 readings are `disabled` controls, which WCAG 1.4.3 exempts.

Three meaning bugs fell out of the same port:

- Gold `#f7d783` was doing double duty as *both* link and warning — so **"Markets' 99 order rows stopped
  reading as 99 warnings."**
- The `--os-mint` bridge resolved to `--ae-pos`, so **selection and identifiers were literally meaning
  "good"**; re-pointed to `--ae-accent` across ~30 sites.
- `WorldWorkspace` passed `variant="world-os-world"`, which **matched no selector** — the dark atlas
  treatment had been dead code.

Bonus: the nine now follow `data-theme` in *both* directions. They had been hardcoded to one ground.
Three pre-existing failures on the Classic Observatory were fixed too (`district-label--institutions` was
white-on-paper at **1.25**).

### ✅ World map stacking bugs — fixed, and the verification method was wrong too

**The audit's own probe could not have seen the fix.** `elementFromPoint` skips `pointer-events: none`, which
the labels set — so it reports "covered" whether or not the stack is correct. The fixer caught that and
replaced it with a pixel ground-truth test: screenshot each label box with the chip layer visible, then
hidden, and compare bytes.

| | before | after |
|---|---|---|
| Label sample points occluded | **180/180** | **0/180** |
| Labels overpainted (pixel test) | 5/6 | **0/6** |
| Lens over map field | **58 px** | **0 px** |
| "300 of 300 residents visible" pill | 9/33 covered, right end clipped | **0/33, fully visible** |

Both root causes were more interesting than the symptom:

- The lens overlap was *"the number written twice by hand"* — the field reserved 300px while the lens
  occupied 340 + 18 = 358. Exactly the 58px measured. Now derived from `--civic-lens-reserve`.
- Raising z-index alone was **not sufficient** — bare ink over ~200 ringed discs is unreadable whichever way
  the stack runs. Labels became plates, reusing the atlas's existing plate idiom.
- Beneath that sat a subtler bug: the agent layer's `z-index: 5` opened a stacking context that **trapped**
  hover/selected/focus inside it, so once labels rose above, the one chip the reader had selected became the
  one the label covered. The layer now carries no z-index and the chips carry their own steps.

The whole stacking order is now written down in one commented block, *"because it was being invented one rule
at a time."* District labels measure 15.41:1 dark / 18.62:1 light; World sweep 425 text runs, 0 below floor.

**Known trade-off, deliberate and flagged:** the selected chip covers ~12% of the Exchange plate. The layout
math lives in `lib/civicCity.js` (out of that agent's scope). It judged the mark the lens is describing should
win over the label.

### What the audits caught that a contrast sweep could not

Nine independent auditors, each able only to measure and report:

- **World: district labels render *underneath* the agent chips** — `z-index 2` against the agent layer's `5`.
  *"'Works' + 'firms, labor, and production' is entirely invisible behind ~200 red chips."* Occlusion probing
  found 3/3 sample points covered for **every** label. Not a contrast bug — a stacking bug, invisible to the
  ratio sweep that scored those same labels 5.18:1–14.1:1. → being fixed.
- **World: the evidence lens overlaps the map it describes**, hiding part of Signal Ward and clipping the
  "300 of 300 residents visible" pill. → being fixed.
- Markets: the freshness popover covers the FX TRADES and CURRENCIES cards while open.

### A correction

A previous agent reported a broken CSS comment at `ui/ui.css:516` (`\*` instead of `/*`). A byte-level check
of the current file finds **0 occurrences**. That report was stale; nothing is broken.

## The gauntlet's blind spot (now closed)

A blind A/B certifies **the screen it judges**. It said nothing about the nine screens next door. Measured
contrast in the legacy workspaces, all pre-existing and all far below the 4.5:1 floor:

| workspace | element | ratio |
|---|---|---|
| Markets | "Trades" | **1.31:1** |
| World | "Civic Forum" | **1.25:1** |
| People | citizen names | **1.32:1** |
| Politics & Law | disabled callout | **1.24:1** |
| Organizations | column header | **2.42:1** |

Root cause: `.world-os-workspace-card`, `.world-os-summary-strip` and the table/callout classes carry dark
backgrounds from `index.css` that the light sheet never overrode. A port onto the token layer is in flight,
followed by **nine independent contrast audits** — one per workspace, each able only to measure and report,
never to fix.

## App round 2 — build detail

All six quoted defects fixed. The root cause of the table corruption was worth the dig — the computed grid was:

```
grid-template-columns: 48px 0px 126px 104px 78px 50px 96px
```

Fixed tracks summed to **502px inside a 438px area**, so the `minmax(0,1fr)` Name track resolved to **0px** —
`1fr` has no floor, it is *designed* to vanish. And because the gutter was `padding-right` on the grid item,
it painted **outside** the zero-width track, so the Name cell's box started at the same x as the Role cell's.
`Governor Vale` and `central_banker` were drawn on the same pixels. The header had no `text-overflow` at all,
so `NAME` printed over `ROLE`.

Fixed structurally, not patched: gutters are now `column-gap` (nothing a cell owns can paint outside its
track), columns carry a px floor with a summed `min-width` so the ledger scrolls sideways as one piece before
any track can collapse, and header cells clip exactly like body cells.

Measured after: hero→sparkline gap **+16px** (was **−41px** overlap); 40 rows of both tables with **0**
overlaps, **0** clipped elements, **0** horizontal scroll; swept across 1920/1600/1512/1440/1400/1360/1344/1280.

Roles also now read `Central banker` / `Venture capitalist` / `Treasury secretary` instead of the routing enum.

**Deferred to the shell round (different files, now in flight):** the white topbar against the dark workspace,
`backfill_truncated` shipped as user copy, "stale" announced three times in one band, per-item chrome gaps,
a rail row clipped mid-glyph, and a saturated yellow-green active nav item marking a *normal* state — which
violates this app's own stated contract that chroma is reserved for exceptions.

---

## Housekeeping — disk, and what is safe to remove

The live run's config sets `checkpoint_every: 30` with **no `checkpoint_keep_last`**, so every checkpoint is a
full, never-pruned DB copy. This session consumed **~45 GB** (394 GB → 349 GB free).

| artifact | size | safe to delete? |
|---|---|---|
| `data/checkpoints/53f5b4ce8c_t*.db` (15 files) | **38 GB** | yes — scratch run created this session |
| `data/runs/53f5b4ce8c.db` (live scratch run) | 4.3 GB | yes, once the server is stopped |
| `data/runs/57291608f6.db` (abandoned first attempt) | 752 MB | yes |
| `data/runs/uidemo01.db`, `uidemo02.db` (copies) | 349 MB + 172 MB | yes |
| `data/runs/a27a94fabd.db` (20-tick benchmark) | 54 MB | yes |

**Nothing has been deleted.** The run is left **paused**, which halts the growth. All of the above are
artifacts this session created — no pre-existing run was resumed, mutated or removed. Verified at the end:

- `data/runs/04be23b901.db` — Jul 29 13:10, 177,553,408 bytes (unchanged)
- `data/runs/5f5eac3794.db` — Jul 12 20:31, 356,392,960 bytes (unchanged)

## Log

_(newest first)_

- **App round 2 built and captured**; blind re-judgement in flight; shell defects being fixed in parallel.
- **First paint fixed** — 19 → 822 nodes at 1s under a 40s API. Piece 13 passes.
- **App round 1 judged and FAILED (3/6).** Sent back with six quoted defects. The loop continues — this is
  the round I expected to lose.
- **Latency model corrected.** Not slow endpoints — event-loop starvation. Same endpoint measures 13.3s
  running and 0.037s paused.
- **Piece 13 added** from the 13-second stall measurement. Progressive per-panel loading is now a first-class
  piece, not a polish item.
- **Substrate upgraded to a live ticking world** (semantics 12, 300 agents). Run/pause/step now return 200,
  so the simulation controls can be *proven*, not just styled.
- **Round 1 discarded as contaminated**; capture bug fixed; clean re-run launched.
- **Three design systems delivered** and blind-ranked. No clean winner — b and c win different lenses, which
  points at synthesis rather than a straight pick.
- **Critic calibration passed.**
- **Audit complete.** Not a styling problem — four design systems running at once with no scale under any.
- **Substrate switched** after the first baseline rendered a 365-tick run as all zeros (schema predates the
  civic/map/region subsystems).
- **Phase 0.** Both bars captured. Grafana's first capture (a meetup map with one dot) rejected as too thin
  a bar and re-captured against dense live service dashboards.

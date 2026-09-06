# Research city implementation log

Started 2026-09-06 after explicit authorization to implement recommendations
1–5 in order. The [roadmap](2026-09-06-research-city-roadmap.md) and
[specifications](2026-09-06-research-city-specs.md) define the full scope.

| Recommendation | Packages | Status |
|---|---|---|
| 1. Research integrity and shared historical context | W0–W2 | Core fixes verified; paused-attempt resume and daily keyed streams remain pending contracts |
| 2. Price Discovery Lab, equal goods/equity coverage | W3 and lab portion of W4 | G1/F1 benchmarks, offline policy comparisons, G2/F2 studies, historical inspector, local draft/launch/compare/export workflow implemented; checkpoint-derived studies and live-policy comparisons pending |
| 3. Unified interactive research city | City portion of W4 | Shared Atlas/Diorama/recorded-day selection, playback, scoped transcripts, price navigation, camera controls and persistent follow implemented; institutional/household lenses and remaining layout/interaction acceptance pending |
| 4. Persistent society and deeper economics | W5–W8 | Pending |
| 5. Validation and scale evidence | W9 | Pending |

Implementation starts from `534323ea458cd410e246b2358e36c42680e9928f` on the
existing feature branch. The review/plan documentation was already uncommitted
and is preserved. This log records actual implementation and executed checks;
pending packages are not claims of delivered functionality.

The implementation now has its own branch, `codex/research-city-price-lab`,
based on that same starting commit. The original review branch and its open
PR #78 are preserved; its four prerequisite commits are still ahead of main.

## Foundation implementation

- Both research runners allocate unique, compact batch/cell locations and use
  exclusive atomic artifact publication. Repeating a run preserves predecessors.
- Attempts retain protocol/code identity, source status, full canonical genesis
  inventory (separate declared schedules), source hashes and actual recorded
  replay comparisons. New runs persist their effective semantics marker.
- Eligibility requires the declared horizon, committed boundary, reconciliation,
  database integrity and bound replay receipts. Failed/paused attempts remain
  visible. Reanalysis checks source/replay modification including pending WAL.
- Pair-level summaries retain assigned/started/completed/eligible counts and
  exclusions. Missing values/effects are null, one pair has no interval, and
  zero-variance standardization is undefined. All legacy-runner analyses remain
  explicitly exploratory. A resumed paused batch is not yet a supported workflow;
  relaunching always creates new attempts.
- Live City uses `/api/v2/world-map` with run/fork/tick checks, drops old-frame
  placeholders on context changes, retains selection/navigation, and separates
  recorded-day playback from world time. Historical Live City opens no world
  status poll/socket. Profiles without presence have an explicit empty state.
- A versioned headline metric registry and strict read-only reader identify
  formulas, units, currency rules, populations, windows, missingness and actual
  execution age. The guide corrects CPI weighting. An ODD model description
  documents current mechanics and pending demographic/financial extensions.

## Executed verification

- Focused Python integration/regression/legacy replay/documentation set:
  **135 passed** (77.85 s); this preceded the final metric-registry addition.
- Metric registry plus research-integrity regressions: **23 passed** (14.91 s).
- Dashboard unit suite: **217 passed**.
- Historical city, route and state browser suites: **25 passed** (28.8 s).
- TypeScript check, license-notice check and production Vite build passed;
  `server/static` regenerated. Existing large-chunk build warning remains.
- Initial integration checks caught and fixed Windows path-length overflow,
  missing fresh-semantics markers, tuple/list receipt comparison and display
  context mistakes. The full local gate is not yet claimed complete.

## Next delivery

Continue checkpoint-derived studies, interactive city integration and W5–W9.
Maintain equal priority for
both price domains. The foundations, benchmarks and inspector do not complete
the five-part goal. Paused research resume and daily-world keyed randomness
remain explicit foundation follow-ups before confirmatory studies.

## Price study backend

- Strict nested study contracts reject unknown fields, unsupported metrics,
  invalid seeds/windows, undeclared currencies and unsupported interventions.
  Preparation pins configuration, code, model description and input identities.
- Both G2 input-cost and F2 public-firm-information presets use the same
  provider-free worker, independent artifacts, replay verification and paired
  analysis. The runner refuses live providers, samples disk use, terminates its
  own worker at the wall-time guard, and retains unstarted/failed cells.
- Source/input identity is rechecked around each attempt. Actual provider calls,
  spend and outcome metadata are bound into source receipts. Complete-window
  outcomes and cross-currency checks cannot silently fill missing prices.
- Price observations reconstruct goods sale prices and qualified equity prices,
  quantities, notional, age and evidence. Current displayed book depth is
  distinguished from unavailable historical order state. A fixed basket keeps
  missing constituents and reports coverage instead of reweighting survivors.
- The first two 8-tick, 2-seed campaigns completed all eight source/replay pairs
  with exact comparisons and zero external provider calls/spend. Their separate
  batch keys are `747d27af74a2-4788df007bd7` (G2) and
  `2006837b3755-a0a7b64b94cb` (F2). Firm 1 had no goods sales, correctly yielding
  an unavailable goods-price effect. Both original campaigns are retained.
- Revised exploratory presets declare separate goods/equity targets and a
  period VWAP for goods. This design revision was informed by those pilots;
  it is not a held-out or confirmatory specification.
- Price-lab unit/integration/registry/protocol tests: **43 passed** (16.87 s),
  followed by **15 passed** after missing-instrument and reporting refinements.
  An earlier integrity-inclusive set passed **45 tests** (31.38 s).
- The full Python command finished: **1,626 passed, 10 skipped, 2 failed** in
  4,043.75 s. Both failures were Windows MAX_PATH in hosted snapshot fixtures.
  The same two tests passed under `C:/Users/matri/.codex/tmp/ae-<unique>`
  (**2 passed**, 0.99 s). No hosted implementation or assertion was weakened.
  That full run preceded the newest benchmark/inspector additions, which have
  focused coverage below. The full command itself is not claimed green.
- Production browser verification: disposable run `afd8656714`, 300 residents,
  advanced through the ordinary Step control to tick 3. Historical tick-1
  recorded-day playback started/paused while world tick/status stayed at
  `3 / paused`. Narrow-width panel overlap remains a city-integration task.

## Benchmark and inspector delivery

- Revised G2 batch `018db6082d52-0579a097841f` and F2 batch
  `c8bbde7a82a7-66c7cddd5aa0` each completed all four source/replay pairs with
  zero external calls/spend. G2's mean goods VWAP difference was +58.33 cents
  per product unit and quantity difference −10.5 units across two seeds;
  equity differences were zero. F2's measured differences were all zero.
  These short exploratory pilots are neither holdout nor causal-fit evidence.
- G1/F1 fixtures settle through production goods/exchange/ledger mechanics.
  The independent feasible-surplus oracle, fixed endowments, funded equity
  redemption and three bounded policy rules are versioned. No daily-world
  economic semantics were changed by adding these isolated fixtures.
- Benchmark batch `25dae7148f5e-f62d25205b6a`: **18/18 completed and eligible**,
  equal cases/seeds/policies, zero provider calls/spend, with actual canonical
  mechanics reruns. Across three seeds G1 mean efficiency was 89.58% for
  reservation-bound offers, 70.83% for noise and 100% for adaptive margins.
  F1 efficiencies were 100%, 0% and 100%, respectively. Non-trading noise
  outcomes remained eligible with null prices. These numbers characterize
  the declared small fixtures, not general policy superiority.
- Historical regional population, firm counts and residence now reconstruct
  lifetimes, migration history and acquisition timing. Focused geography,
  projection and documentation tests: **44 passed** (12.65 s).
- Markets → Price lab displays equal goods/equity inspectors, a business/window
  selector, daily execution charts with gaps, accessible data tables and
  evidence links. Read-only responses validate run/fork/tick/instrument/window;
  old or mismatched frames are hidden. Source event/trade rows remain intact.
- Benchmark, exchange and price tests: **33 passed** (16.72 s). New projection,
  price-reader and metric tests: **26 passed** (3.38 s). Dashboard unit suite:
  **220 passed**. Both targeted price-inspector browser tests passed (7.0 s).
  Integration checks caught the URL tick string/number mismatch and explicit
  form-label lookup issue before completion; both were corrected.
- Final targeted research/documentation/integrity integration: **57 passed**
  (31.25 s). Combined historical-city/routes/states browser suites:
  **27 passed** (34.3 s). TypeScript and production build passed; 144 discovered
  Python source files compiled. Existing bundle-size and Starlette warnings
  remain. Current dependency/dataset/license audit results from the foundation
  gate remain applicable because this slice adds no dependencies or input data.
- Production inspector verified against the preserved 300-resident run
  `afd8656714` at historical tick 1 while its world remained paused at tick 3.
  Retail Co 2's IVC posted price, absent executions and accessible daily table
  matched the API; no current equity quote or fabricated transaction appeared.
- Gitleaks 8.30.1 staged scan passed with no findings. The temporary scanner was
  downloaded from its official release and checked against the release SHA-256
  manifest; no runtime or research artifacts are staged for publication.

Current commands and limits: [Price Discovery Lab](../research/price-lab.md)
and [induced-value benchmarks](../research/market-benchmarks.md).

## Saved study evidence

- Checkpoint `bbe10aa` is on draft [PR #82](https://github.com/alinojoumi8/agent-economy/pull/82).
  GitHub core subset, Python smoke and dashboard build jobs passed. The full
  matrix and hosted integration jobs were skipped. CodeRabbit's passing check
  says its review was skipped because the PR is a draft; it is not a substantive
  review approval. PR #78 remains the preserved prerequisite branch.
- The study loader confines original paths to configured data/report roots,
  binds manifests and publication receipts, verifies distinct source/replay
  files, remeasures outcomes and reconstructs summary coverage. It preserves
  worker/supervisor exclusions and distinguishes complete provider totals from
  partial verified subtotals. Invalid cells do not hide valid peer attempts.
- New preparation saves a hash-verified model description and declared input
  snapshots before initialization. Existing studies keep an explicit legacy
  missing-snapshot/publication state; no old run or receipt is rewritten.
- Private evidence ZIP export/import uses exclusive destinations, streamed
  checksums, confined extraction, size/file limits and fresh study verification.
  It preserves failures and never executes bundled code. The complete source
  checkout/runtime and undeclared transitive inputs are outside its scope.
- Focused loader, bundle, protocol and research-integrity tests: **55 passed**
  (34.24 s), then **82 passed** (40.03 s) including exclusion/race regressions,
  recorded-replay goldens and documentation. Earlier fixture setup error was
  corrected; no product assertion was weakened.
- The new PR research-evidence job covers both price domains, protocol,
  loading/export and integrity. Its exact eight-module command passed locally:
  **100 passed**, one existing Starlette deprecation warning (55.69 s).
  The final loader/bundle refinements also passed **31 tests** (24.93 s).
  Six edited/new research sources and the workflow parsed successfully.
- Existing G2 and F2 campaigns each exported/imported 72 evidence files and
  retained **4/4 eligible source/replay pairs**, unchanged summary/result bytes,
  zero provider calls/spend and explicit legacy context status. ZIP SHA-256:
  G2 `2e05e110b0792a0b3fb32ec4b1b55227cc4558a4b217d0cdd6b1552da45b8838`;
  F2 `e0e6bd5eef2677948045f6d8ed24062ef4062515cda436cead0e4e061222bad0`.
  Artifacts remain ignored local files, not PR attachments.

## Local study comparison interface

- Evidence transport checkpoint `4d18988` is pushed to PR #82. Its Python
  smoke, core subset, research-evidence and dashboard jobs passed on GitHub.
  Full-matrix/hosted jobs and substantive CodeRabbit draft review remain skipped.
- Experiments → Price studies adds an operator-only local catalog, freshly
  verified goods/equity comparisons, coverage, per-seed values and execution
  age, exclusions, protocol/cost details and verified private downloads.
  It labels studies as independent of the currently observed world. Historical
  cursors make no library requests. Returning old/mismatched data cannot expose
  another run/fork/study's comparison or start its download.
- API responses exclude database/config/private-path payloads, enforce current
  run/fork/CSRF context and reject hosted-safe access. Exports recheck result and
  verification identities, reuse unchanged artifacts and retain failures.
  Scientific databases receive no new tables or economic writes. Verification
  uses a serialized worker thread outside the HTTP event loop.
- First API/projection checks: **9 passed** (10.90 s). Dashboard unit tests:
  **222 passed**. New study browser tests: **3 passed** (5.9 s); combined routes,
  states and historical city: **30 passed** (38.7 s).
- A concurrent Vite build changed the tracked source tree during a research
  fixture's launch, correctly preventing eligibility (**60 passed, 5 setup
  errors**). With the build completed before research execution, the same
  selection passed **65 tests** (37.87 s), including replay/documentation.
  No guard was bypassed. Final execution-age refinements passed **40 Python
  tests** (37.49 s) and **3 browser tests** (5.8 s). TypeScript and production
  build passed; existing Starlette and large-bundle warnings remain.
- Production UI verified against both saved G2/F2 campaigns with source world
  `afd8656714` still paused at tick 3. G2 showed the retained +58.333 goods-price
  difference; F2 showed zero measured differences and equity execution ages
  of 7 and 3 ticks. Its private UI download produced SHA-256
  `4e1dd877f2c618c9e56a15b3fa57979eeea322a729dd32e7c26e5791f7fbc44b`.
- Final combined research/price/documentation selection: **127 passed**
  (70.92 s). An export race regression then bound the displayed verification
  identity through the bundle's own final load: **37 passed** (37.27 s).
  Private cache headers and documentation: **28 passed** (11.38 s).
  The final dashboard unit run again passed **222 tests**. Generated private
  `research-exports/` directories are ignored regardless of workspace location;
  the production ZIP was verified ignored before staging.
- The new comparison does not implement study launch, checkpoint-derived
  forks, paused research resume, daily keyed streams or live-model comparisons.
  Those remain explicit next deliveries before full city/society/validation work.

## Browser gate follow-up

- Commit `afe5cab` passed GitHub Python smoke, core subset and research-evidence
  jobs. Its browser job failed because a communication reload assertion matched
  both the thread heading and the message heading with the same subject. The
  selector's result depended on whether the message had finished loading.
- The assertion now verifies both heading levels explicitly. The complete CI
  browser selection passed locally: **64 passed** (1.3 min), using two workers:
  `npm run test:e2e -- world-os.spec.ts world-os-states.spec.ts world-os-privacy.spec.ts agent-connections.spec.ts world-os-routes.spec.ts --workers=2`.
  No product behavior or production bundle changed for this test correction.
- Checkpoint `637da9a` then passed all four required GitHub jobs, including the
  full critical browser selection. Optional full-matrix/hosted jobs remained
  skipped, and the draft still has no substantive CodeRabbit verdict.

## Operator draft and launch workflow

- Added a strictly bounded G2/F2 pilot service and Create a study UI. Validation
  freezes the protocol, resolved configuration and source identity without world
  initialization. Both price domains are measured; the UI shows targets, arms,
  observation window, resource allowance and scientific limits before Run.
- Launch uses a durable idempotent claim and an independent supervisor. A
  process-owned lock and persistent active pointer enforce one execution slot;
  interruption recovery retains evidence and cannot release a running job.
  Progress, source/replay results and comparison links survive page reloads.
  No new engine semantics, scientific schema, provider calls or source-world
  mutations are introduced.
- Initial backend execution: **18 passed, 1 failed** (16.13 s). The real
  four-world source/replay workflow passed; the failing privacy assertion
  incorrectly matched the safe `resolved_config_sha256` key as if it were the
  private `resolved_config` payload. The assertion now checks the exact key.
  The combined research/price/documentation selection then passed **147 tests**
  (89.22 s); dashboard units passed **224**, and all eight study browser tests
  passed (13.6 s). TypeScript and the production build passed.
- A hard supervisor crash originally could leave a child worker alive. Workers
  now watch the multiprocessing parent handle and hold a separate recovery
  lock. An actual owned-process kill test confirmed the worker stops before
  recovery releases its slot; partial artifacts remain without a success receipt.
  Edited local draft files also cannot bypass the fixed profile/resource limits
  by supplying a recomputed hash.
- Post-hardening jobs/protocol/result-loader/recorded-replay selection:
  **48 passed** (43.25 s). The complete critical browser selection passed
  **69 tests** (1.4 min), and the final eight study checks passed again
  (11.9 s) after launch-availability refresh controls. Dashboard units again
  passed **224** (6.88 s); TypeScript, final production build and four backend
  source parses passed. Existing Starlette and large-chunk warnings remain.
- Production browser workflow completed new 8-day, 2-seed G2 and F2 pilots,
  each with **4/4 eligible source/replay pairs** and zero provider calls/spend.
  G2 job `089eece6718a4cd56582c6d3b293fc84` opened verified comparison
  `fd07c38750ae16ca99f7b0bbdd436a1d`; F2 job
  `eb654eebfd7cea360f7d9b85bb9cf4f6` opened
  `c4ee491ed549b062d016147f5675231d`. The observed 300-resident city
  `afd8656714` remained paused at tick 3 throughout.
- The fresh G2 results retained the exploratory +58.333-cent goods-price and
  −10.5-unit volume differences. F2 retained zero measured differences; neither
  pilot establishes empirical fit. The F2 UI private evidence download verified
  successfully (3,851,139 bytes; SHA-256
  `fea3c69d0444c1b7e64135ee1fe5c7668c19b7972f131c4dbc0b3372ef4fea46`).
  All operational job files, reports, databases and ZIPs were verified ignored.
- Full city integration, checkpoint-derived studies, live-model policies,
  paused research resume and daily keyed streams remain pending. This checkpoint
  completes the bounded local pilot workflow, not the full five-part goal.

## City observation and price navigation

- Checkpoint `040918f` passed all four required GitHub jobs in run
  `34030749217`. Optional jobs stayed skipped. CodeRabbit still skips the draft;
  this is not a substantive review verdict.
- City map, civic summary and events now form one validated frame pinned to the
  map's actual tick/fork. Mismatched frames withhold marks and prevent runtime
  requests. The map layer request also restores construction projects and flows,
  which the previous explicit layer list omitted.
- Current runtime responses carry run/fork identity and private/no-store headers.
  Historical views make no runtime request; terminal runs, failed telemetry
  refreshes and foreign runtime responses cannot retain active indicators.
  The API regression verifies the runtime read makes no scientific writes.
- Businesses are selectable in Atlas and Diorama through a shared keyboard
  explorer. Workplace/owner and employee/employer links use projected records.
  The business inspector opens both price domains together, with unavailable
  map fields and regional anchors explicitly labelled.
- Bounded camera bookmarks survive reload and view changes. Buttons support
  zoom, pan, reset and focus; evidence links preserve city display state without
  replacing the destination's current run/fork/tick or its workspace view.
- Summary cards moved below the map and agent filters became optional. The
  production desktop field measured **66.5% map width** beside its inspector;
  the map begins at y=309 px in a 1440×1000 viewport. This is a field-width
  measurement, not a claim that 66.5% of the whole viewport is map area.
  Construction text is shown on selection to avoid overplotting, the footer
  no longer overlaps frame status, and mobile has a direct evidence button.
- Initial unit execution after extending observer state: **232 passed, 1 failed**;
  an existing expected-object fixture lacked the new nullable fields. After its
  correction, the final unit run passed **233 tests** (6.61 s). TypeScript and
  the production build passed; the existing large-chunk warning remains.
- The full critical browser selection passed **74 tests** (1.6 min). After the
  final label/footer/mobile change, all **16 city-focused tests passed**
  (25.2 s). Runtime/cognition and documentation passed **40 tests** (11.53 s)
  before the final cache-header assertion and documentation additions.
- An actual production roundtrip at tick 1 of paused world `afd8656714` loaded
  300 residents, six firms and 73 construction records; it returned to firm 2
  at camera `72,28,3.4`. Request spies recorded **zero writes, zero current
  runtime/status requests and zero browser errors**. Widths 768 and 390 had
  **zero horizontal overflow**. The source world stayed paused at tick 3.
  A representative synthetic-world screenshot and the
  [observer contract](../research/city-observer.md) are saved in the repository.
- The separate recorded-day route, Atlas camera controls, persistent follow,
  institutional/household lenses, checkpoint-derived studies, paused research
  resume and keyed daily streams remain pending. No economic semantics or
  scientific schema changed in this checkpoint; W5–W9 remain unfinished.
- Final runtime cache-header and updated documentation selection: **40 passed**
  (7.94 s). The existing Starlette deprecation warning remains.
- Explicit missing/invalid envelope metadata checks passed all **nine** city
  projection/navigation units (0.10 s); final TypeScript and production build
  passed. Staged Gitleaks 8.30.1 scanned about **2.05 MB** with no leaks;
  `git diff --cached --check` passed. Operational logs and private artifacts
  remain outside the staged change.


## Shared recorded-day city

- Checkpoint `87ea4b5` passed all four required GitHub jobs in run
  `34033077784`. Optional full-matrix/hosted jobs and substantive CodeRabbit
  review remained skipped; this is a focused checkpoint, not full-goal completion.
- City now has one `/world` workspace with Atlas, Diorama and Recorded day.
  Legacy `/live-city` URLs redirect with their fork/tick/selection preserved.
  Playback consumes the shared validated map without its own fetch/status/socket
  logic. The common keyboard explorer, filters and inspector remain available.
- Play, Pause, Restart and four playback speeds affect presentation time only.
  Speed changes preserve continuity. New frames/filters start paused; Pin this
  day turns a live observation into an explicit historical cursor. Runtime
  telemetry is withheld in recorded playback, and historical workspace pages
  open no live socket. Reduced motion retains stepped recorded placements.
- The new read-only `city.conversations` projection pins ordinary recorded
  small-talk to one run/fork/tick. Future messages/participants and malformed
  records are excluded; response and transcript limits are disclosed. It never
  reads private communication/provider stores or changes scientific tables.
  Wrong or failed transcripts cannot replace the frame's words.
- Production inspection verified 300 roster entries, **100 authorized individual
  placement histories**, and 200 peripheral residents without exposed individual
  placements. Playback draws exactly the authorized IDs and states coverage.
  An initial QA assumption that all 300 should have individual journeys failed;
  the privacy boundary was preserved rather than bypassed. Recomputed pixel
  positions agreed to less than 0.001 px, including de-collision offsets.
- A first-load inspection also found shared controls/place styles were trapped
  in the lazy Diorama import. Those small shared styles now load with CivicCity;
  the heavy renderer remains lazy. Playback controls precede the map and the
  legend/provenance can expand beneath it. Production widths 768 and 390 had
  zero horizontal overflow and a direct inspector action. At 1440×1000 the
  recorded map starts at y=494 px and is 746.7 px wide by 520 px high; these
  measurements do not establish the full first-viewport area/usability target.
- Initial units: **234 passed, 1 failed** on the retired City route expectation;
  corrected units: **236 passed** (7.07 s). Initial recorded-day browser checks:
  **7 passed, 1 failed**, exposing the historical shell socket; corrected:
  **8 passed** (12.3 s). The first broad browser pass had **81 passed, 1 failed**
  on the old eleven-destination count. After correcting it and adding placement
  coverage, the final full critical browser selection passed **83 tests** (1.7 min).
- Final transcript/price projection, documentation, legacy recorded replay and
  cognition/runtime selection: **50 passed** (12.85 s). TypeScript and the
  production build passed. Existing Starlette and large-chunk warnings remain.
  An editor encoding roundtrip was caught in diff review and corrected before
  the final build; the changed text files contain no replacement/mojibake markers.
- Actual production playback, pause, renderer switching and mobile evidence
  access passed with zero writes, current-runtime/status requests, live sockets
  or browser errors. World `afd8656714` remained paused at tick 3. The reviewed
  synthetic-world screenshot is saved in the [city guide](../research/city-observer.md).
- No economic semantics or scientific schema changed. Atlas pan/zoom, persistent
  camera follow, institutional/household lenses, checkpoint-derived studies,
  paused research resume, daily keyed streams and W5–W9 remain unfinished.

## Shared camera and persistent person follow

- The preceding `892d393` checkpoint passed all four required GitHub jobs in
  run `34035372933`. Optional full-matrix/hosted jobs and a substantive CodeRabbit
  review remained skipped. This delivery continues the same draft PR and goal.
- Atlas now pans by dragging its background and shares zoom, four pan buttons,
  reset and focus with Diorama and recorded day. Bounded camera bookmarks restore
  through reload/history and renderer changes. An Atlas drag creates one history
  entry; pointer updates replace it. Touch keeps vertical page scrolling and
  exposes camera actions through buttons.
- `follow=<person ID>` preserves one identity across renderers, filters and
  historical cursors. Hidden, absent, dead and unlocated people pause follow;
  a different person is never substituted. Atlas/Diorama require public observed
  coordinates; a derived district marker is insufficient. Selecting another
  object, manual pan, focus or reset stops follow; buttons and Diorama wheel zoom
  preserve it. Stop following saves the current camera.
- Recorded follow centers the same animated chip used by the placement renderer.
  One affine camera transforms the whole sheet without altering anchors. The
  probe exposes both original and screen coordinates; the display clock and
  camera create no per-frame URL entries or economic effects. An unavailable
  recording pauses follow, and nondefault cameras hide the auxiliary inset whose
  original empty-space fit is no longer applicable.
- Atlas marks/labels retain readable sizes under zoom. Production inspection
  exposed pre-existing construction-label crowding; labels now appear only on
  hover, keyboard focus or selection. At coincident business/workplace pixels,
  the business owns the click and the inspector/explorer reaches the workplace.
  The recorded background remains fixed while the geographic sheet moves.
- Initial units passed **239 tests** (6.16 s). The first camera browser pass had
  **14 passed, 2 failed**: one absence fixture still supplied that person's public
  presence rows, and one assertion sampled before the observer update completed.
  After correcting those checks, **16 passed** (13.6 s). Broad runs exposed an
  unscoped hosted-status assertion and an overlapping workplace click; both were
  addressed, with an added construction/keyboard regression. The final full
  critical browser selection passed **91 tests** (58.4 s), including wheel zoom,
  history, missing targets, reduced motion and 390/768 layouts.
- The final production UI followed person 1 at historical tick 1 of disposable
  world `afd8656714`, rendered its **100 public placement histories** from a
  300-person roster, and kept the moving target centered. Independent screen
  coordinate reconstruction had maximum residual below **0.001 px**. At widths
  768 and 390 horizontal overflow was zero; all three renderers and mobile
  evidence access worked. There were zero writes, current runtime/status reads,
  live sockets or browser errors. The source world remained paused at tick 3.
- The production bundle and reviewed synthetic-world follow screenshot are
  included. No dependency, economic semantics or scientific schema changed.
  Full viewport-area/usability acceptance, institutional/household lenses,
  checkpoint-derived/live-policy studies, paused research resume, daily keyed
  streams and W5–W9 remain outstanding. This checkpoint does not finish the goal.
- Final unit execution passed **239 tests** (5.57 s); TypeScript and the production
  build passed. Documentation and legacy recorded replay passed **25 tests**
  (2.46 s). The existing large-chunk build warning remains.

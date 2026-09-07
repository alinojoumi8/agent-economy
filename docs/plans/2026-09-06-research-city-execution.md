# Research city implementation log

Started 2026-09-06 after explicit authorization to implement recommendations
1–5 in order. The [roadmap](2026-09-06-research-city-roadmap.md) and
[specifications](2026-09-06-research-city-specs.md) define the full scope.

| Recommendation | Packages | Status |
|---|---|---|
| 1. Research integrity and shared historical context | W0–W2 | Core fixes, committed-day and opt-in phase supervised resume, working evidence portability, CLI/operator controls and Semantics 16 daily keyed streams implemented |
| 2. Price Discovery Lab, equal goods/equity coverage | W3 and lab portion of W4 | Benchmarks, G2/F2 studies, historical inspector, fresh/saved-world scripted CLI/operator workflows and private evidence implemented; replicated fresh/saved-world policy CLI execution, original-budget day/phase recovery, independent verification and private final/paused v3 bundles implemented; v3 operator integration and real-provider validation pending |
| 3. Unified interactive research city | City portion of W4 | Shared Atlas/Diorama/recorded-day selection, playback, scoped transcripts, price navigation, camera controls and persistent follow implemented; institutional/household lenses and remaining layout/interaction acceptance pending |
| 4. Persistent society and deeper economics | W5–W8 | W5 person/birth/membership/custody/child-demand/census foundation implemented under Semantics 15; remaining W5 and W6–W8 pending |
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

Continue live-policy study support, interactive city integration and W5–W9.
The [live-policy implementation contract](2026-09-07-live-policy-studies.md)
records shared completion reservations and the remaining policy, supervisor,
recovery/evidence and operator integration.
Maintain equal priority for
both price domains. The foundations, benchmarks and inspector do not complete
the five-part goal. Saved-day/phase recovery and daily-world keyed randomness
and checkpoint-derived studies are implemented. Live-policy comparisons remain
a research extension. Confirmatory studies remain unsupported.

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

## Persistent people and first household mechanics

- The preceding camera checkpoint `1aa6ed0` passed all four required jobs in
  GitHub run `34037389203`. The same draft PR and five-part goal remain active.
- Semantics 15 / additive schema 21 introduces immutable person origins,
  permanent child IDs, zero-endowment births, household membership intervals,
  parent/child relations and explicit primary guardianship. Historical
  dependent counts remain uninstantiated and are not incremented for new
  children. Old profiles and their replay mechanics retain their version.
- Birth, child purchases and death/custody settlement have rollback boundaries.
  Age derives from birth/entry time. At 18 a child becomes eligible for ordinary
  actions without a job, house, compute grant or wealth. Independent minor
  actions and employment are rejected; newborns do not enter adult persona,
  conversation or model-reflection paths. Caretakers can see their own support
  requirements and previous-day costs in decision context and memory.
- The declared basic-needs policy buys available local food in posted-price/ID
  order from real firms, using guardian cash. It records purchases, shortages
  and currency without borrowing, FX netting or invented supply. Care minutes
  remain requirements with an explicit pending allocator, not measured care.
- Death and adult separation retain dependent histories. Existing same-household
  adults can become guardians; absent guardians produce recorded care gaps.
  Individual regional migration separates the moving adult's household. Civic
  child routines use the household's original home anchor; no school or housing
  title is granted. Joint family migration remains pending.
- Demographic draws are keyed by seed/person/day/mechanism, with actual health
  outcome isolation checked against an extra-child cohort. Other world RNG
  streams and paused research-attempt resume remain foundation follow-ups.
  Completed-day censuses reconcile births, deaths, arrivals, other institutional
  entries and population, and check membership, age, residence and custody.
- The first household run had **16 passed, 1 failed** because the migration
  test incorrectly assumed Store supports a context manager. After correcting
  that test, the selected household/legacy compatibility suite passed **81
  tests** (12.52 s), and expanded household checks passed **22** (3.73 s).
- The initial 39-module CI core/smoke selection had **487 passed, 14 failed**
  (258.09 s). Five failures were stale version/probe assumptions; nine correctly
  rejected unclassified new tables in research hashing/export. A new
  `hash-contract-v3` now includes all seven household tables. The v1/v2 manifests
  and inventory contracts remain unchanged; old contracts cannot omit populated
  household state or a Semantics-15 run. Migration/hash/export/documentation
  checks then passed **83 tests** (52.35 s), and household/hash branch checks
  passed **32** (45.11 s), before the final actor-context addition.
- A first separate provider-free 30-day source and recorded replay were exactly
  equal, with one child, 30 child-days/food units, no child model calls and a
  reconciled ledger/census. That pilot preceded the actor-context addition; the
  final verification below records the complete checkpoint. Raw databases and
  export bundles remain ignored.
- Full W5 is unfinished: partnership assent, care delivery/time commitments,
  full estate inventory/creditor/heir/custody accounting, joint migration,
  household inspector and multi-decade validation remain. W6–W9 also remain,
  with goods and equity price discovery retaining equal priority. This delivery
  does not close the goal.
- The combined 51-module core/smoke/research selection completed with **638
  passed, 1 failed** (414.35 s). The remaining assertion treated the prompt's
  `(system, user)` pair as one string; it now checks the rendered user prompt.
  The child-needs hash mutation check now takes its baseline after context
  construction, isolating the mutated table. A final inspection also corrected
  a newborn's birth observation to "I was born" while preserving the historical
  parent-oriented birth description for versions 1–14.
- Final household, hash/export, arrival, retirement, cognition, documentation
  and legacy recorded replay selection: **105 passed** (84.13 s). The combined
  command above was not rerun locally in full after its single assertion fix;
  the corrected affected selection passed, and the pushed CI runs the required
  complete job selections. The existing Starlette warning remains.
- Final isolated source and replay both reached day **30** with canonical hash
  `15dcb74d41bbb05f02c7e3563905e87e1117685677af23a42da56dc8cf32261c`,
  `exact: true`, and no differences. There were **25 living actors**, **24
  households**, one permanent child, **30 food units purchased for 10,352
  cents**, no unmet food units and **zero child model calls**. All 564 provider
  records were scripted at **$0**, and the ledger and daily censuses reconciled.
  Source plus replay took 8.44 s; this is a bounded mechanics observation, not
  scale or multi-decade validation. Care time remains unallocated. Detailed
  synthetic databases/receipts are retained only in ignored local pilot files.

## Household verification after storage recovery

- The later full local Python run exhausted C: during the suite. Its retained
  log has no reliable final pass count or successful completion; this is an
  inconclusive validation attempt, not a green full gate. The goal resumed
  after a fresh storage check found about 142 GB free. Subsequent local checks
  use short isolated roots and a 40 GiB free-space preflight; full coverage is
  assigned to bounded CI shards instead of another serial local run.
- Newborn public names now use the permanent person ID, without embedding a
  parent ID or a label that becomes false at adulthood. Parentage remains in
  explicit relationship records and recorded birth evidence.
- The resumed household/hash/export/arrival/retirement/cognition/documentation/
  legacy replay selection passed **105 tests** (102.10 s). The existing
  Starlette deprecation warning remains.
- A fresh isolated 30-day source and recorded replay were exactly equal at
  canonical hash
  `12c50a53596c50242acfba0cfbed6b66f4286886769c621398fd8a4f9cfd723e`.
  Both retained the same 25 living actors, 24 households, one child, 30 food
  units purchased for 10,352 cents, reconciled census/ledger and zero child
  model calls. All 564 provider records were scripted at $0; source plus replay
  took 8.94 s. This verifies the final public-name correction in a short
  mechanics run, not multi-decade, scale or empirical validity.
- The earlier five-part scope remains open. After preserving this first W5
  checkpoint, close paused-study resume and the other research foundation
  gaps before expanding household time/estate mechanics and W6–W9.
- Household checkpoint `0b454b1` is pushed to draft PR #82. Staged Gitleaks
  found no leaks in 100.53 KB; the staged whitespace check passed. Required
  PR CI [34074026442](https://github.com/alinojoumi8/agent-economy/actions/runs/34074026442)
  passed all four jobs: smoke, core, research evidence and dashboard.
- A separate full-suite run
  [34074059513](https://github.com/alinojoumi8/agent-economy/actions/runs/34074059513)
  was dispatched at that same commit using all eight Ubuntu/Python 3.12
  shards. Its result is pending at the time of this entry; this does not claim
  the complete Windows/Python-version matrix or hosted integration passed.
- Source inspection established that current research runners finalize even
  paused attempts. The next
  [resume implementation contract](2026-09-06-paused-study-resume.md) therefore
  specifies separate working attempts, preserved legacy receipts, compatibility
  validation before writable database access, cumulative budgets, and staged
  CLI/evidence/UI delivery. This is a saved implementation design, not a claim
  that study resume is already implemented.
- The broader run exposed a stale study-runner test in shard 1: its one-byte
  budget now correctly fails context-snapshot preflight before any study is
  created. The test now gives the context exactly enough room to publish,
  then verifies that manifest overhead prevents all world execution while
  retaining every assigned arm/seed and null effects. A separate test proves
  that an unaffordable context publishes no batch. Production budget guards
  were not relaxed. The required research CI selection now includes
  `tests/test_study_runner.py`, closing the coverage gap that hid this failure.
- The complete study-runner/protocol/documentation selection passed **42
  tests** (18.68 s) after those corrections, under the short-root/free-space
  preflight. This does not relabel the failed earlier shard as a pass.

## Working-attempt recovery executor

- At correction commit `d0254d5`, required PR CI
  [34074585568](https://github.com/alinojoumi8/agent-economy/actions/runs/34074585568)
  passed all four jobs. All eight Ubuntu/Python 3.12 full-suite shards passed in
  [34074675811](https://github.com/alinojoumi8/agent-economy/actions/runs/34074675811),
  totaling **1,773 passed and 10 skipped**. This verifies the household checkpoint
  and budget-test correction; it precedes the recovery executor below. The
  Windows/Python-version matrix and hosted integration were not run here.
- Added `working-attempt-v2` and explicit `preserve_and_resume` preparation for
  scripted studies. The executor advances one assigned cell under a portable
  batch writer lock, records immutable pause/segment lineage, preserves pending
  eligibility before the horizon and reuses exact source/replay finalization.
  Legacy finalized attempts remain immutable. New checks bind the manifest,
  inputs, code/configuration, genesis, source bytes, schema, phase, PRNG,
  references and ledger before writable database access.
- The first focused run had **37 passed, 1 failed** (70.10 s). The strict
  cross-source comparison differed only in request latency, which remains part
  of the historical replay contract. Its conformance fixture now fixes the
  gateway's observational clock while retaining real decisions, economic state
  and budget clocks; no production replay exclusions were added.
- Stronger rejection cases then exposed read-only SQLite sidecar creation on
  Windows and a lock file created before rejecting an old finalized attempt:
  **51 passed, 4 failed** (82.02 s). Preflight now uses a closed, sidecar-free,
  hash-bound snapshot reader, and finalized disposition is checked before lock
  creation and again under ownership. The subsequent working/legacy-attempt/
  study-runner/protocol/golden-replay selection passed **55 tests** (75.01 s).
- Cumulative active time includes earlier segments/cells, with operator idle
  time excluded only under the explicit new timing contract. Limits remain
  cooperative at this internal executor seam. Hard worker budgets, batch
  resume, CLI, portable evidence, saved-study discovery and operator/UI recovery
  remain required next work under the
  [implementation contract](2026-09-06-paused-study-resume.md). Ordinary runner
  validation rejects this policy until orchestration is integrated; the full
  five-part goal remains active.
- The expanded working-attempt, legacy-attempt, runner, protocol, results,
  portable bundle, saved library, local jobs, golden replay and documentation
  selection passed **137 tests** (136.30 s), with the existing Starlette warning.
  Final hardening binds closed result timings to a separate immutable seal
  before another cell can consume that budget record. All **21 working-attempt
  tests** then passed (64.48 s), including repeated pauses, an actual failed
  day, competing ownership and altered cross-cell budget records. Required
  research CI now includes this module.
- A separate, unmocked provider-free Semantics-15 household rehearsal paused
  at day **3**, resumed the same source to day **30**, and verified independent
  recorded replay at canonical hash
  `b4188250ab4ec7594f08bab7371fc5a4c0963fb481595380fd8ab3c938b3b9e2`.
  It retained **25 living actors**, **31 censuses** including genesis, **30
  child-days/food units purchased for 10,352 cents**, zero child model calls,
  no paid provider calls/spend, valid segment lineage and reconciled books.
  Active source time was 6.80 s and finalization 9.53 s. Its first summary
  query used incorrect column/table names after the source and replay had
  succeeded; the corrected receipt was read from those existing frozen
  artifacts without rerunning the simulation. Raw evidence remains ignored
  under `tmp/wha-0786b8f0/`. This pilot preceded only the final result-seal
  addition; the final 21-test selection covers that addition. This remains a
  bounded mechanics rehearsal, not a completed multi-arm study or empirical
  validation.

## Supervised study recovery and CLI

- At `88f1e89`, required [CI 34076614198](https://github.com/alinojoumi8/agent-economy/actions/runs/34076614198)
  passed all four jobs. All eight Ubuntu/Python 3.12 full-suite shards passed in
  [run 34076613979](https://github.com/alinojoumi8/agent-economy/actions/runs/34076613979):
  **1,794 passed and 10 skipped**. These results precede the supervisor changes
  below. The full Windows/version matrix and hosted integration were not run.
- Connected `preserve_and_resume` to supervised batch execution and CLI
  `--pause-after-ticks`, `--resume-batch` and read-only resume validation.
  A clean pause retains every assignment and pending eligibility in an immutable
  progress report. Resume preserves completed cells and advances only compatible
  paused/planned cells. Version-1 finalized artifacts remain immutable.
- Added supervisor ownership, 200 ms worker time/disk checks, orphan termination,
  append-only invocation/worker/progress receipts and sealed cumulative timing.
  Missing finalization or supervision records refuse recovery. Completed studies
  verify these records through existing result loading and portable ZIP import/export.
  Aliased output directories also refuse cell resume before writable access.
- The first integrated run completed source/replay and portable verification,
  then failed one test assertion using the wrong import-receipt field (**1 failed,
  13.60 s**). The next selection had **13 passed, 2 failed** (76.61 s): a Windows
  byte-range lock cannot be hashed while held, and the fixture also contains an
  auxiliary database. Assertions now compare before/after lock ownership and
  the original database inventory instead of assuming one file. No production
  guard was relaxed.
- The supervisor, working-attempt, legacy runner, result, bundle and operator-job
  selection passed **97 tests** (206.42 s), including CLI pause/validate/resume,
  preserved completed cells, both price domains, portable lineage, competing
  ownership, original-budget exhaustion and actual supervisor death. The existing
  Starlette deprecation warning remains. Required research CI includes the new
  `tests/test_working_studies.py` module.
- Working-state library/export/operator UI and partial-phase recovery are still
  pending. The internal cell API remains cooperative; the CLI now uses its own
  hard worker supervisor. The broader five-part roadmap remains active.
- After the final output-alias and receipt-seal checks, the complete supervisor
  module, new alias rejections, study protocol, legacy golden replay and
  documentation selection passed **56 tests** (105.86 s). Research compilation
  passed. Tests used fresh short Windows roots with a 40 GiB free-space preflight;
  remaining space after this slice was approximately **129.4 GiB**.
- An unmocked CLI rehearsal loaded a saved Semantics-15 configuration and study
  YAML, paused at day **3**, ran read-only resume validation, then finished all
  **four 30-day cells** (two seeds, baseline/cost arms) with **4/4 eligible**
  source/replay pairs and a verified aggregate. All four canonical replay hashes
  matched, all books reconciled, and no paid provider calls/spend occurred.
  Each world retained 25 living actors and 30 child-day records; recorded child
  food purchases were 30, 30, 29 and 30 units. The previous progress report stayed
  byte-identical. Cumulative supervised active time was **66.20 s** within the
  original 240-second/256 MB limits. Raw evidence remains ignored under
  `tmp/wsh-0a823971/`, including per-command logs and `receipt.json`. This checks
  mechanics and recovery, not empirical validity or a price-discovery forecast.

## Working study library and operator resume (2026-09-07)

- At `0ec6d17`, required [CI 34078486637](https://github.com/alinojoumi8/agent-economy/actions/runs/34078486637)
  passed all four jobs. All eight Ubuntu/Python 3.12 full-suite shards passed in
  [run 34078516783](https://github.com/alinojoumi8/agent-economy/actions/runs/34078516783):
  **1,813 passed and 10 skipped**. These checks precede this integration slice.
- Added independent working-evidence verification, frozen input/source/segment
  checks and separate `study-working-evidence-bundle-v1` archives. Paused and
  completed cells are remeasured from closed sources. Export owns both batch
  locks and copies their original control bytes through the owning handles on
  Windows. A frozen imported pause remains readable after the original source
  resumes; eligibility stays pending and execution compatibility is separate.
- The saved library now discovers prepared and paused batches under a stable ID
  that survives finalization. It shows every assigned world and its last saved
  day, with pending/unverified states. Working evidence has no effect-comparison
  payload. Verified pauses can be exported; active checkpoints cannot.
- New operator drafts use the working protocol and accept an optional planned
  saved-day pause. Read-only resume checks bind original code/config/inputs,
  namespace, progress and remaining budget. An explicit, idempotent Resume POST
  creates a linked continuation job under existing CSRF/run/fork/Live authority.
  Parent claims/terminal receipts stay immutable. CLI/imported batches are not
  adopted into an operator profile, and interrupted-job release remains separate.
- The browser provides saved-day tables, pending evidence, private export,
  origin-job navigation, compatible Resume controls and existing-continuation
  links. Historical views make no operator requests, and foreign/stale resume
  responses cannot replace the selected job. Synthetic UI captures are stored
  in `docs/research/assets/study-working-progress.png` and
  `docs/research/assets/study-resume-controls.png`.
- Initial portable checks exposed Windows locked-byte reads and the old
  results-only bundle index; explicit ownership and a separate working format
  resolved both. The working/bundle selection then passed **23 tests** (35.50 s).
  Operator tests subsequently reached real G2/F2 resume and completion but had
  assertion errors matching `stored_summary_matches` as a metric payload and
  reading the wrong timing field. Corrected assertions retain the original
  integrity and budget checks. The recovery/evidence/operator selection passed
  **24 tests** (192.36 s), including 4/4 eligible source/replay pairs for each
  G2/F2 pilot, same genesis/run identity, unchanged parent evidence and zero
  mutation of the observed world. Later additions cover prepared discovery and
  sanitized POST rejection after a checkout change.
- TypeScript and **240 UI unit tests** passed. The first full browser run had
  **103 passed, 1 failed, 1 skipped**: an existing contrast test searched inside
  the now-collapsed city filter panel. Opening the panel retains the contrast
  assertions; that check and the working-library/resume/mobile flow passed
  together (**2 passed**, 9.7 s) after the final control styling. Production
  build and license checks passed; the existing large-chunk warning remains.
- Tests use fresh short Windows roots and a 40 GiB free-space preflight.
  Approximately **132.6 GiB** remained after production build. No cleanup or
  paid provider run was performed. Partial-phase recovery, daily keyed streams,
  remaining city lenses and W5–W9 remain active roadmap work.
- Final regression selection (working jobs/evidence, existing jobs/library/bundle,
  golden replay and documentation): **79 passed** (151.65 s). Final TypeScript
  check passed. The full Chromium suite then passed **104 tests with 1 skipped**
  (2.4 min); the skip is the opt-in real-backend menu smoke. No browser failure
  remains in this run. Research/API compilation, dependency check and diff
  whitespace validation passed. Full hosted and Windows/version CI matrices
  remain unrun.

## Semantics 16 daily random keys (2026-09-07)

- The previous operator/library integration at `91176b9` passed required
  [CI 34082221289](https://github.com/alinojoumi8/agent-economy/actions/runs/34082221289).
  Its eight Ubuntu/Python 3.12 shards in
  [run 34082240133](https://github.com/alinojoumi8/agent-economy/actions/runs/34082240133)
  passed **1,821 tests with 10 skipped**. These receipts precede this slice.
- Added opt-in [Semantics 16](../semantics16-randomness.md) with SHA-256 keys
  per mechanism/day/person or event. Birth and arrival origins survive unrelated
  record insertions; rumor audiences and conversation priorities survive other
  PRNG consumption and reordered eligible rows. Policy, newsroom, memory,
  arrival persona/bank/contact/tie and demographic draws are isolated.
- Source events retain origin keys without a schema migration. Arrival birthday
  offsets, compute-tier ranks and city home assignment use those origins.
  Historical Semantics 1–15 paths, demographic vectors and PRNG persistence remain
  unchanged. Old checkpoints cannot be relabeled as Semantics 16: an explicit
  upgrade refuses and preserves the source. New runs use fresh genesis.
- Both price-study presets declare and validate their actual stream contract.
  Added `runs/price-lab-keyed.yaml`; existing operator pilots retain their frozen
  Semantics 7. Confirmatory execution stays unavailable. Genesis initialization,
  within-policy branches, changed eligible sets and unmatched engine-created
  staff identities retain their documented limits.
- A death/replacement stress test exposed identical reporter-cache keys when
  both desk agents had died. Semantics 16 now binds the daily seed in request
  cache identity; each outlet retains its own recorded response and the stress
  source replays exactly. No historical source or cache key is rewritten.
- Initial selection: **104 passed, 3 failed**. Two new study fixtures incorrectly
  put an undeclared rumor in the baseline; the existing guard correctly refused
  them. The third check required updating the status ledger's current version.
  After correction, **56 passed, 1 failed**, exposing the reporter-cache defect.
  Its fix then passed **21** isolation/study/replay checks (57.66 s).
- Final focused regressions: **142 passed** (94.48 s), using a fresh short temp
  root and a 40 GiB free-space preflight. Command: `.venv/Scripts/python.exe -m
  pytest -q tests/test_keyed_daily_randomness.py tests/test_keyed_price_studies.py
  tests/test_semantics15_households.py tests/test_compatibility_guards.py
  tests/test_study_protocol.py tests/test_price_study_catalog.py
  tests/test_review_gateways.py tests/test_arrival_personas.py
  tests/test_replay_source_lifecycle.py tests/test_recorded_replay_golden.py
  tests/test_documentation.py --basetemp <fresh-short-root>`.
  The G2 and F2 tests each completed four eligible attempts across two seeds,
  including a preserved pause receipt, resumed source, actual recorded replay
  and read-only result verification. Both retain all four goods/equity outcomes.
- Engine/world/agents/LLM/research/runner compilation and dependency checking
  passed. The existing Starlette test-client deprecation warning remains.
  No paid provider calls, new UI changes or checkpoint cleanup were performed.
  Partial-phase recovery, remaining city lenses, W5–W8 economics and W9
  validation remain active work; this is not completion of the five-part goal.
- Final documentation checks passed **22 tests** (0.35 s) with an explicit fresh
  temp root. An initial invocation without that root hit the existing Windows
  `pytest-of-matri` access denial during fixture setup (21 passed, 1 setup error);
  no permissions or old temp data were changed. Research CI YAML folding and
  staged whitespace checks passed; Gitleaks found no staged secrets.

## Saved-phase study recovery (2026-09-07)

- The preceding Semantics 16 commit, `698606b`, passed all four required jobs
  in [CI 34084832550](https://github.com/alinojoumi8/agent-economy/actions/runs/34084832550).
  Its eight Ubuntu/Python 3.12 shards in
  [run 34084843908](https://github.com/alinojoumi8/agent-economy/actions/runs/34084843908)
  passed **1,837 tests with 10 skipped**. These precede this recovery slice.
- Added explicit `preserve_and_resume_phases` / `working-attempt-v3`, alongside
  the unchanged saved-day policy. It binds completed/active day, next phase,
  private phase-state digest, engine/persona/lifecycle streams and all earlier
  admitted-input prefixes. Planned phase stops occur after atomic phase commits.
  Cooperative same-phase retries retain their original time/disk budget and
  append-only lineage. Missing/crashed receipts still refuse recovery.
- Active days produce null study outcomes and `partial_phase` observations.
  Supervised G2/F2 assignments remain pending through pause and private transport;
  final results still require independent exact replay. Public library/job
  projections expose only the verified day/next-step summary. A reviewed
  operator step choice selects the phase contract; existing day choices retain
  version 2. Historical/foreign context and resume authority remain checked.
- Initial combined selection: **26 passed, 12 failed** (77.04 s); the new fixture
  used `baseline` instead of the catalog's `control` arm. The assignment guard
  correctly refused it. After correction, **11 passed, 5 failed** (67.00 s):
  normal gateway retries healed the synthetic outage, and a new test reader
  omitted SQLite's query-only flag. The phase matrix itself passed for semantics
  7 and 16, including uninterrupted equivalence and exact replay.
- The expanded run passed **19 tests with 3 failures** (153.44 s), including both
  four-cell G2/F2 studies, pending/final private bundles and earlier-input mutation
  refusal. Remaining failures were outage fixtures: quiet news days had no desk
  requests, and the first model conversation occurred on day 2. Declaring daily
  news and checking the actual active day corrected those assumptions.
  Repeated outages in morning, newsroom, evening and memory then passed all
  **8 checks** for semantics 7/16 (50.24 s), retaining inputs and exact replay.
- TypeScript and **241 UI unit tests** passed. The phase selector, reviewed draft,
  saved-progress display, mobile layout, existing day pause/resume and active
  checkpoint exclusions passed **4 focused Chromium tests** (9.7 s).
  Final regression and release checks follow below.
- Final backend selection passed **152 tests** (522.18 s), using a fresh short
  Windows root and the 40 GiB preflight. It includes both new phase suites,
  existing working-attempt/batch/evidence/job suites, study results/library/jobs/
  protocol checks, recorded golden replay and documentation. All four real
  operator day/phase × G2/F2 cases completed four eligible worlds, with retained
  parent receipts, original budgets and no mutation of the observed world.
  Compilation and dependency checks passed; the existing Starlette warning remains.
- Visual inspection caught mobile clipping that the document-overflow check
  missed. The library now constrains its grid track and verdict panel; browser
  acceptance also checks panel bounds and scroll access to the final column.
- Corrected mobile/working flows passed **2 Chromium tests** (9.1 s). The full
  browser suite then passed **105 tests with 1 skipped** (2.3 min); the skip is
  the opt-in real-backend menu smoke. Desktop and scrolled-mobile synthetic
  captures are retained in `docs/research/assets/study-phase-progress*.png`.
  Final UI unit checks passed **241 tests**; TypeScript, licenses and production
  build passed. The existing large-chunk warning remains.
- The actual `research.study_runner --validate-only --pause-after-phase MARKET`
  command accepted both G2/F2 three-day, two-seed drafts using
  `runs/price-lab-keyed.yaml` and the phase policy. These were validation-only
  CLI checks; actual execution/replay is covered above. The final documentation
  selection passed **22 tests** (0.55 s). Approximately **125.3 GiB** remained
  after these checks. CI is dispatched after the commit; hosted integration and
  the full Windows/version matrix remain unrun locally.
- This remains progress on the five-part goal. Live policy studies,
  checkpoint-derived experiments, remaining city lenses, W5–W8 economics and
  W9 validation remain pending. No paid provider run or cleanup was performed.

## City navigation during delayed responses (2026-09-07)

- Saved-phase recovery commit `8a6a8e7` passed all eight Ubuntu/Python 3.12
  shards in [CI 34089185185](https://github.com/alinojoumi8/agent-economy/actions/runs/34089185185):
  **1,865 passed, 10 skipped**. The research evidence job passed 229 tests,
  the core guard 359, and smoke 144. These additional jobs overlap the shards.
- Required [CI 34089159270](https://github.com/alinojoumi8/agent-economy/actions/runs/34089159270)
  passed its Python/research jobs but failed one of 97 Chromium checks: an
  automatic resident selection could restore day 6 after the browser requested
  day 3 while a map response was delayed. The same check passed 12 unthrottled
  local repetitions, then failed all 24 repetitions at 4x CPU throttling.
- Automatic city-selection repairs now require their rendered location and
  pending search to remain current, and the browser to remain on that route and
  search. Direct interactions still accumulate against the latest pending
  parameters. This prevents stale selection repair from overriding navigation.
  The regression retains slower browser execution and checks the final URL,
  recorded day and selected resident, without relaxing its assertions.
- The corrected regression passed **4 repetitions** (24.8 s). TypeScript,
  **241 UI unit tests**, license notices and the regenerated production build
  passed. The first full browser run passed 103 tests, skipped one and exposed
  two regressions: the guard also rejected direct drag/selection updates while
  their earlier URL changes were being rendered. Restricting the strict search
  check to automatic repairs fixed both; all three affected checks then passed
  **12 repetitions** (30.5 s). TypeScript, 241 UI unit tests and production build
  passed again. The existing large-chunk warning remains. Documentation passed
  **22 tests** using the bounded Windows preflight and a fresh short temp root.
  Final full browser verification passed **105 tests, 1 skipped** (2.2 min),
  including both direct-interaction regressions and the slower navigation case.
  The skip remains the opt-in real-backend menu smoke. Staged Gitleaks and diff
  hygiene passed. Required CI is dispatched after committing this correction.

## Studies from saved worlds (2026-09-07)

- Added closed-source admission, complete state/random/input receipts, exclusive
  copies and deterministic continuation branches. Original sources remain
  unchanged. Source/replica seeds, completed day and economic configuration must
  agree with the prospective declaration; incompatible state, accounting,
  sidecars or participant/external influence refuses admission.
- Study protocol 2 and attempt protocol 4 bind checkpoint origins. Both G2 and
  F2 execute treatment/control continuations from two independently declared
  source worlds. Recorded replay starts from a separate origin copy and verifies
  the new interval. Existing genesis study serialization and replay stay intact.
- Integrated frozen execution, supervised day/phase recovery, independent
  outcomes, common-origin pairing and private pending/final evidence transport.
  Inherited recorded calls and costs remain visible but do not consume the new
  provider-free totals. Flow windows exclude inherited observations; terminal
  equity prices retain the existing explicit execution-age contract.
- Added explicit checkpoint drafting to `research.price_catalog`, including
  source selection, common-day validation and retained source seeds. Large
  sources refuse before content hashing or batch allocation. The new
  [saved-world contract](2026-09-07-checkpoint-studies.md) includes commands.
- Windows checks caught read-only SQLite readers creating sidecars. An explicit
  closed-source path now covers the gateway, external-agent and participant
  readers and the same canonical replay comparison. Default readers still
  include live WAL content. Replay recovery files use their own directories and
  cannot replace the source attempt's snapshots.
- First integration set: **38 passed, 6 failed**; the six failures were the
  source-sidecar rejection. After correction, recovery checks passed **55 tests**
  (527.85 s). After isolating replay recovery outputs, the expanded study,
  transport, external/participant and legacy replay checks passed **122 tests**
  (434.61 s). The final pre-hash size guard plus protocol/documentation checks
  passed **35 tests** (3.21 s). No paid provider calls were made.
- Compiled **335 source files** and passed `pip check`. A broad compile walk
  reported inaccessible old ignored report directories; compiling the actual
  tracked/unignored Python source set succeeded without changing those artifacts.
  The existing Starlette test-client deprecation warning remains.
- At backend commit `a758922`, the operator launcher was still fresh-world-only.
  Required [CI 34098327977](https://github.com/alinojoumi8/agent-economy/actions/runs/34098327977)
  passed all four jobs: 97 Chromium, 264 research, 359 core and 144 smoke checks.
  Full [CI 34098443502](https://github.com/alinojoumi8/agent-economy/actions/runs/34098443502)
  passed eight Ubuntu/Python 3.12 shards: **1,900 passed, 10 skipped**.

## Saved-world operator workflow (2026-09-07)

- Added the local operator checkpoint catalog and deliberate source selection.
  It reads only immediate files in the configured checkpoint directory, rejects
  aliases/sidecars/incompatible state, refuses oversized sources before hashing,
  and bounds entries, source sizes and returned choices. It returns hashes and
  source identities without paths, configuration or recorded input bodies.
- Draft review, launch, the supervisor and day/phase resume recheck the selected
  bytes, admission receipt, source seeds and fixed pilot profile. Validation
  includes the required initial copies plus an explicit growth allowance.
  Changed sources and inadequate budgets refuse before creating study worlds.
- The browser offers fresh or saved initial conditions, clears deliberate
  selections on refresh/context changes and withholds foreign catalog responses.
  Draft and comparison views show origin day, independent worlds, retained seeds
  and the newly executed interval. Existing context, CSRF, idempotency, recovery
  and private evidence controls remain in the same workflow for both domains.
- `.venv/Scripts/python.exe -m pytest -x -q tests/test_checkpoint_study_jobs.py tests/test_study_jobs.py tests/test_working_study_jobs.py tests/test_study_library.py tests/test_documentation.py --basetemp <fresh-short-root>`
  passed **68 tests** (325.29 s). Includes actual G2/F2 × day/phase operator
  continuations, four eligible worlds per study, recorded replay, private bundle
  reimport and original-source/observed-world immutability. No paid calls.
- TypeScript passed; **242 UI unit tests** passed. The focused browser run passed
  **12 tests**; full `npm --prefix dashboard run test:e2e -- --workers=2` passed
  **108 tests, 1 skipped** (2.5 min). The skip remains the opt-in backend menu
  smoke. License notices and the production build passed; bundle regenerated.
- Synthetic desktop/mobile review captures were inspected at
  `docs/research/assets/study-checkpoint-review-desktop.png` and
  `study-checkpoint-review-mobile.png`. These are mocked interface evidence;
  the Python operator tests above execute actual saved-world studies.
- Required CI separates saved-world execution/recovery from the broader research
  evidence job to retain bounded ten-minute jobs. New-commit CI is dispatched
  after committing this slice and tracked on draft PR #82. The full Windows/
  Python matrix and hosted integrations are not claimed; the existing Starlette,
  console-color and large Vite chunk warnings remain.
- Free space was **103.28 GiB** after these bounded checks, above the 40 GiB
  reserve. Existing user simulation artifacts and the unrelated cleanup plan
  were preserved. The five-part implementation goal remains active.

## Shared provider completion budgets (2026-09-07)

- Added an exclusively created operational ledger bound to one study manifest,
  gateway configuration, aggregate call/token/spend caps and declared upper
  provider/model tariffs. Atomic reservations precede direct HTTP completions;
  independent workers and later processes share the original allowance.
- Preflight JSON completions, retries, repairs and configured fallbacks pass
  through the optional gateway guard. Cancellation, missing usage, failed
  requests and process death retain their encumbered allowance. Budget stops
  propagate without another completion or a false provider-failure event;
  previously completed responses remain recorded when repair is unaffordable.
- Separated explicit OpenAI/Anthropic usage from historical adapter estimates
  without changing those estimates or canonical/replay payloads. Cached input
  uses the declared upper input tariff. Malformed/excessive reported usage
  stops subsequent dispatch; extreme concurrent breaches remain readable with
  exact integer totals. Opaque CLI inference, request overrides and network
  adapters masquerading as built-in offline providers are refused.
- `.venv/Scripts/python.exe -m pytest -x -q tests/test_provider_budget.py tests/test_production_hardening.py tests/test_recorded_replay_golden.py tests/test_research_validity.py tests/test_prd_completion.py tests/test_study_protocol.py tests/test_documentation.py --basetemp <fresh-short-root>`
  passed **210 tests** (87.56 s), including **50 new budget tests**. Tests cover
  actual loopback HTTP preflight/retry paths, legacy and tiered routing,
  cancellation, abrupt child-process death, concurrent reservations, declared
  caps, missing/invalid usage, privacy and recorded replay compatibility.
  Earlier 36/207/208-test passes preceded the final provenance and admission
  checks; the 210-test run covers the final implementation.
- Source-only compilation passed for **340 Python files**. CI YAML parsed,
  `pip check` passed, and diff hygiene was checked. The existing Starlette
  TestClient deprecation warning remains. Dashboard source/bundle are unchanged
  in this slice. Required CI now includes the provider-budget tests; new-head
  required and full-suite results are tracked on draft PR #82 after commit.
- No paid provider calls or cleanup were performed. These are controlled
  transport tests, not live-provider readiness or economic validation. The
  [live-policy specification](2026-09-07-live-policy-studies.md) records the
  remaining policy/replicate contracts, supervisor attachment, recovery/import
  evidence and operator controls. The study runner still accepts only
  explicitly scripted provider-free execution; the five-part goal is active.

## Executable replicated decision-policy studies (2026-09-07)

- Added `research-study-v3`: per-arm scripted/live policies, frozen prompt and
  runtime identity, explicit primary/repair/preflight sampling, and separate
  world-seed and model-draw axes. Goods and equity prices are equally primary.
  Existing v1/v2 serialization, saved-world behavior and default gateway/replay
  paths remain compatible.
- Added a provider-free draft CLI and validation path. Explicitly authorized
  fresh-world execution performs a charged live preflight and supervises each
  assigned cell under one shared v2 completion ledger. Named gateway bindings
  prevent a policy from using another policy's target. A failed response after
  repair pauses/excludes its world; missing model draws cannot inflate precision.
- Frozen results seal the allowance and preserve scope totals, preflight and
  scientific receipts. The independent v3 reader confines paths, verifies the
  sealed budget, rechecks source/replay evidence and recomputes measurements.
  Edited prices are excluded even if public report checksums are regenerated.
  Copied evidence is readable without provider credentials or current prompt
  hashes; reading leaves database bytes unchanged.
- Controlled HTTP integration completed **eight worlds**: two independent seeds,
  two model draws and two policy arms, each through day 3 with independent exact
  recorded replay. Both price domains had two usable world pairs. Tests also
  cover charged failed preflight, exhausted allowance, invalid responses,
  cancellation, ordinary interruption, hard supervisor death, worker wall-time
  stops, sealed-ledger refusal and source/evidence alterations.
- Initial integration tests exposed an incomplete conversation fixture; its
  missing fields were corrected without weakening the runtime schema. A later
  assertion incorrectly equated observed HTTP posts with admitted calls during
  concurrent cancellation; the test now requires cancelled reservations to
  remain charged. The resulting focused set passed **106 tests** (67.47 s).
- After the final interruption and verification checks,
  `.venv/Scripts/python.exe -m pytest -x -q tests/test_policy_studies.py tests/test_provider_budget.py tests/test_production_hardening.py tests/test_research_attempt_integrity.py tests/test_study_protocol.py tests/test_study_runner.py tests/test_study_results.py tests/test_research_validity.py tests/test_recorded_replay_golden.py tests/test_prd_completion.py tests/test_documentation.py --basetemp <fresh-short-root>`
  passed **286 tests** (169.28 s). The existing Starlette TestClient deprecation
  warning remains. All **346 Python sources** compiled, CI YAML parsed and
  `pip check` passed. Required research CI includes the new policy suite.
- No paid provider calls or cleanup were performed. Synthetic tariffs and
  controlled transport do not establish model availability, invoice accuracy,
  empirical realism or confirmatory inference. New-head CI results are tracked
  on draft PR #82; no merge is authorized.
- Next W3/W4 work: authenticate original-budget day/phase recovery, declare the
  saved-world policy configuration delta, integrate private v3 bundles and the
  operator review/launch/comparison UI, then conduct a separately authorized,
  bounded real-provider rehearsal. The remaining city, household, education,
  production/housing, banking and validation packages remain in the active
  five-part goal. The [live-policy specification](2026-09-07-live-policy-studies.md)
  records this implementation boundary and the CLI workflow.
- At `bab0294`, required [CI 34112703468](https://github.com/alinojoumi8/agent-economy/actions/runs/34112703468)
  passed all five jobs: **321 research, 47 saved-world, 359 core, 144 smoke and
  100 Chromium checks**. Full [CI 34112697080](https://github.com/alinojoumi8/agent-economy/actions/runs/34112697080)
  passed eight Ubuntu/Python 3.12 shards: **2,004 passed, 10 skipped**.
- Final evidence review added two consistency checks: each reservation must use
  its binding's provider/model, and a completed world cannot have more recorded
  provider calls than its scope accounts for. A deliberately rewritten ledger
  and all associated public receipts cannot conceal the calls in an independently
  verified scientific database. After that change,
  `.venv/Scripts/python.exe -m pytest -x -q tests/test_policy_studies.py tests/test_provider_budget.py tests/test_study_results.py tests/test_recorded_replay_golden.py tests/test_documentation.py --basetemp <fresh-short-root>`
  passed **130 tests** (77.18 s). CI for the follow-up commit is tracked on the
  same draft PR; these 2,004 full-suite passes belong to `bab0294` specifically.

### W3/W4: preserve original model allowances across day/phase recovery

- At `661de40`, required [CI 34113771268](https://github.com/alinojoumi8/agent-economy/actions/runs/34113771268)
  passed **322 research, 47 saved-world, 359 core, 144 smoke and 100 Chromium
  checks**. Full [CI 34113766367](https://github.com/alinojoumi8/agent-economy/actions/runs/34113766367)
  passed all eight Ubuntu/Python 3.12 shards: **2,005 passed, 10 skipped**.
- The v3 CLI now accepts prospective day/phase recovery policies. Working claim
  version 5 binds each model replicate to its original shared allowance. Closed
  reservation-prefix receipts preserve earlier charges and settlements while
  later invocations append new calls. `open_run` attaches the completion guard
  before resumed world construction and continues to reject live guards in replay.
- The existing supervisor records policy invocation lineage, charges readiness
  checks on every invocation, skips completed cells and preserves cumulative
  wall/disk/token/call/spend caps. Resume verifies the original allowance and
  closed scientific evidence before any new call or writable world open. Clean
  pauses remain pending; provider/resource failures finalize exclusions, normal
  interruption seals the allowance, and hard crashes remain unresumable with
  unresolved charges. No history is erased or replaced.
- The v3 reader verifies final `policy-study-result-v2` evidence through every
  supervised preflight, assigned dispatch, accounting interval and closed worker,
  then independently checks scientific measurements and exact recorded replay.
  Historical relocated reads need neither current prompt hashes nor provider keys.
- Initial direct day/phase recovery, existing working-attempt, budget and golden
  replay checks passed **82 tests** (81.68 s). The first supervisor integration
  and legacy recovery set passed **22 tests** (180.75 s). Both supervised pause
  paths then passed with the live policy first and eight assigned worlds. The
  failure/immutability/relocation subset passed **14 tests** (85.24 s); its earlier
  negative fixture used the scripted gateway binding and was corrected to test
  an unexpected reservation on the assigned live binding.
- Final regression:
  `.venv/Scripts/python.exe -m pytest -x -q tests/test_policy_recovery.py tests/test_policy_studies.py tests/test_provider_budget.py tests/test_working_attempts.py tests/test_working_studies.py tests/test_phase_working_attempts.py tests/test_phase_working_studies.py tests/test_working_evidence.py tests/test_study_runner.py tests/test_study_results.py tests/test_research_attempt_integrity.py tests/test_recorded_replay_golden.py tests/test_documentation.py --basetemp <fresh-short-root>`
  passed **243 tests** (622.41 s). All **348 Python sources** compiled in memory,
  CI YAML parsed and `pip check` passed. The new recovery suite has **20 tests**;
  CLI drafting/validation covers all three pause policies without provider calls.
  A separate required CI job runs the recovery suite without provider keys.
- Disk admission remains 40 GiB free with short, fresh pytest roots. This slice
  creates no paid provider calls, cleanup, schema migration or UI claim. The
  [live-policy specification](2026-09-07-live-policy-studies.md) includes the
  draft, pause, provider-free validation and original-budget resume commands.
- Next: saved-world policy deltas, private v3 bundles and operator review/launch/
  comparison, then a separately authorized real-provider rehearsal. The remaining
  city, household, education, production/housing, banking and validation work
  remains in the active five-part goal.

### W3/W4: declare saved-world decision-policy transitions

- At `332d167`, required [CI 34119113213](https://github.com/alinojoumi8/agent-economy/actions/runs/34119113213)
  passed **20 policy recovery, 324 research, 47 saved-world, 359 core, 144 smoke
  and 100 Chromium checks**. Full [CI 34119137654](https://github.com/alinojoumi8/agent-economy/actions/runs/34119137654)
  passed all eight Ubuntu/Python 3.12 shards: **2,027 passed, 10 skipped**.
- The v3 CLI now drafts and executes declared policies from admitted saved
  worlds. Claim 6 derives the complete permitted transition from the prospective
  manifest and original source configuration. It preserves original seeds,
  completed days, economic settings, schedules and recorded history, and requires
  the assigned scope in the original allowance before allocating a child. Legacy
  `continuation_config` validation and attempt/replay protocols remain unchanged.
- Frozen execution, day recovery and phase recovery branch independent copies
  from the same initial state for every arm and model draw. Replay receipt 3
  binds the declared transition and new interval. Independent verification checks
  origin, continuation, reservation history and both price domains, including
  relocated evidence read without current prompt hashes or provider access.
  Inherited calls/costs remain separate from new model work and the shared cap.
- Drafting accepts repeated `--checkpoint` paths with their original common
  configuration and input root. It retains source seeds, starts the policy on
  the first new day and treats `--ticks` as an absolute horizon. Storage admission
  now counts source/replay copies for every model replicate as well as every arm.
  The existing required policy recovery job also runs the saved-policy suite.
- Initial end-to-end checks passed all three execution paths (**3 tests**, then
  **12 tests** after admission/cost/relocation checks). Expanded failure coverage
  caught a test assumption: cancellation may reserve a call without reaching
  the HTTP server, and a closed cancellation is recorded with unknown usage.
  The corrected assertions preserve that encumbrance; the failure/CLI subset
  passed **5 tests** (30.96 s). All **350 Python sources** compiled in memory,
  the CI configuration parsed, and `pip check` passed.
- The Semantics 16 fixture completed eight worlds and replayed exactly, but
  had no goods sales for its declared firm during the new interval. Coverage now
  explicitly checks the resulting null price effect and source events, while
  retaining all three execution paths with observed prices in both domains.
- Final regression on Windows/Python 3.11.15:
  `.venv/Scripts/python.exe -u -m pytest -x -q tests/test_policy_origins.py tests/test_policy_recovery.py tests/test_policy_studies.py tests/test_provider_budget.py tests/test_checkpoint_origins.py tests/test_checkpoint_studies.py tests/test_checkpoint_study_jobs.py tests/test_working_attempts.py tests/test_working_studies.py tests/test_phase_working_attempts.py tests/test_phase_working_studies.py tests/test_working_evidence.py tests/test_study_runner.py tests/test_study_results.py tests/test_research_attempt_integrity.py tests/test_recorded_replay_golden.py tests/test_documentation.py --basetemp <fresh-short-root>`
  passed **312 tests** (1602.28 s), including all **22 saved-policy cases**.
  The existing Starlette TestClient deprecation warning remains. Committed-head
  required and full-suite CI results are tracked on draft PR #82.
- This slice uses controlled loopback HTTP, synthetic historical costs and short
  temporary roots admitted above the 40 GiB free-space floor. It performs no paid
  inference, cleanup, schema migration or operator UI change. See the updated
  [policy workflow](2026-09-07-live-policy-studies.md) for the exact contract.
- Next: private v3 bundles and operator review/launch/comparison, followed by a
  separately authorized real-provider rehearsal. The remaining city, household,
  education, production/housing, banking and scale validation remain active.

### W3/W4: private policy evidence from final and paused studies

- At `2750aa8`, required [CI 34126801041](https://github.com/alinojoumi8/agent-economy/actions/runs/34126801041)
  passed all six jobs: **42 policy recovery/origin, 324 research, 47 saved-world,
  359 core, 144 smoke and 100 Chromium checks**. Full
  [CI 34126862094](https://github.com/alinojoumi8/agent-economy/actions/runs/34126862094)
  passed all eight Ubuntu/Python 3.12 shards: **2,049 passed, 10 skipped**.
- The private v3 reader verifies current cooperative pauses against their
  prospective policy assignment, source/replay evidence, complete supervision
  journal and original unsealed allowance. Completed cells are independently
  remeasured; pending cells cannot be promoted, and unfinished invocations or
  stale original progress are refused. Final reads also bind result bytes before
  and after verification. Malformed CLI input returns a bounded invalid result.
- Separate `policy-study-evidence-bundle-v1` and
  `policy-working-evidence-bundle-v1` archives reuse the existing private size,
  path, alias, checksum and exclusive publication guards. Working export holds
  both existing owners while it copies and rechecks the allowance and evidence.
  Import requires the archive label to match the actual evidence format.
- Imported pauses remain readable after the original resumes, including their
  inherited costs and model draws. A copied unsealed allowance cannot grant
  another resumed execution. Diagnostic exclusions can be transported with
  degraded scientific verification; successful archive verification alone does
  not make a study complete or its prices valid. The v1/v2 operator catalog skips
  unsupported v3 studies until its policy interface is implemented.
- New suite on Windows/Python 3.11.15:
  `.venv/Scripts/python.exe -u -m pytest -x -q tests/test_policy_evidence.py --basetemp <fresh-short-root>`
  passed **32 tests** (375.25 s). It exercises actual loopback HTTP for fresh/saved
  frozen, day and phase campaigns, both price domains, multiple model draws,
  phase history, relocation, read-only/provider-free loading, original-budget
  protection, busy/missing owners, altered evidence, archive relabelling, stale
  progress, false resealed measurements/accounting, concurrent-copy changes,
  result replacement and CLI transport/errors. Earlier fresh-phase integration
  passed **1 test** (50.06 s). All **352 Python sources** compiled in memory;
  CI YAML parsed and `pip check` passed.
- Compatibility regression on Windows/Python 3.11.15:
  `.venv/Scripts/python.exe -u -m pytest -x -q tests/test_policy_studies.py tests/test_policy_recovery.py tests/test_policy_origins.py tests/test_provider_budget.py tests/test_working_evidence.py tests/test_working_studies.py tests/test_phase_working_studies.py tests/test_study_results.py tests/test_study_bundle.py tests/test_study_library.py tests/test_research_attempt_integrity.py tests/test_recorded_replay_golden.py tests/test_documentation.py --basetemp <fresh-short-root>`
  passed **237 tests** (986.95 s). Review independently reproduced malformed
  study metadata raising AttributeError in the new catalog exclusion. An explicit
  metadata type check now omits that record and preserves valid entries.
- After that catalog fix,
  `.venv/Scripts/python.exe -u -m pytest -x -q tests/test_study_library.py tests/test_working_evidence.py tests/test_documentation.py --basetemp <fresh-short-root>`
  passed **37 tests** (34.97 s), including four malformed-metadata cases. All
  **352 Python sources** compiled again in memory. Both regression selections
  retain the existing Starlette TestClient deprecation warning.
- A separate required policy-evidence CI job gives these six world/replay
  campaigns a 15-minute bound. Committed-head required/full CI results are
  tracked on draft PR #82. The
  [private evidence specification](2026-09-07-policy-evidence-bundles.md), policy
  workflow, checkpoint contract and development guide document these boundaries.
- No paid inference, cleanup, schema migration or operator UI change belongs
  to this slice. Tests use fresh short roots with the 40 GiB admission floor.
  Next: v3 operator review/launch/comparison, then a separately authorized real
  provider rehearsal and the remaining city/society/validation roadmap.

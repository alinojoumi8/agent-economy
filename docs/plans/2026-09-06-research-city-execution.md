# Research city implementation log

Started 2026-09-06 after explicit authorization to implement recommendations
1–5 in order. The [roadmap](2026-09-06-research-city-roadmap.md) and
[specifications](2026-09-06-research-city-specs.md) define the full scope.

| Recommendation | Packages | Status |
|---|---|---|
| 1. Research integrity and shared historical context | W0–W2 | Core fixes verified; paused-attempt resume and daily keyed streams remain pending contracts |
| 2. Price Discovery Lab, equal goods/equity coverage | W3 and lab portion of W4 | G1/F1 benchmarks, offline policy comparisons, G2/F2 studies, historical price inspector and verified private bundles implemented; study operator UI and live-policy comparisons pending |
| 3. Unified interactive research city | City portion of W4 | Pending |
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

Deliver the operator study workflow, then
continue interactive city integration and W5–W9. Maintain equal priority for
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

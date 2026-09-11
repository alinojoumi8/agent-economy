# W5 project gates and validation capacity

Status: the local frontend gates pass, and the policy-origin fixture correction
has passing evidence on Windows Python 3.11 and 3.12. The complete Python/platform
matrix, remaining integrations and native acceptance are open. This does not
close W5 or register migration 26 / Semantics 21.

## Completed checks

| Check | Result |
|---|---|
| Hash-locked Python install | Passed on Windows Python 3.11.15 and 3.12.13; isolated Linux environments for the same versions also installed and passed dependency checks. |
| Python dependency audit | `uvx pip-audit -r requirements.lock`: no known vulnerabilities reported. |
| Node 22.23.2 dashboard install and audit | Locked install passed; npm audit reported zero vulnerabilities. |
| Production dashboard build | Passed; output content was byte-identical to the preceding bundle. Existing large-chunk warnings remain. |
| Dashboard unit tests, TypeScript and notices | 264 tests passed; type and notice checks passed on Node 22. |
| Critical Chromium browser selection | 121 passed, with no skips or flaky/unexpected outcomes. |
| Policy-origin suite | All 22 cases passed on Windows Python 3.11 and 3.12, including all five eight-cell workflows, storage admission, altered evidence, failure accounting and retained original allowances. |
| Documentation and shard checks after the CI assertion update | 26 passed on each Windows Python version. |

The browser selection is `world-os`, `world-os-states`, `world-os-privacy`,
`agent-connections`, `world-os-routes` and `live-city-context`. It used a fresh
Vite server, two Chromium workers and its ordinary mocked projection contracts.
Unmocked API requests would have reached an owned loopback server returning 503;
none occurred. It did not connect to an existing research server. This result
does not replace the separate real-backend city acceptance or hosted integration.

The two policy/documentation selections originally finished with 47 passes and
one failure each: the documentation test still asserted an eight-shard CI
configuration. Their elapsed times were 876.73 seconds on Python 3.11 and
862.50 seconds on Python 3.12. Both complete policy-origin suites had passed.
After updating the CI consistency assertion, the affected documentation/shard
selection passed in 0.68 and 0.70 seconds respectively. These are results from
separate retained invocations, not a claim that the original invocations passed.

## Retained incomplete full-suite attempts

The full Python 3.11 collection contained 3,337 tests. Two initial harness
attempts refused before executing tests because an external receipt argument
caused pytest to choose the user's home as its root. The corrected harness
explicitly supplies the repository root and verifies the selected node IDs.

Two corrected eight-way shards then reached their declared 1,800-second limits:

| Original shard | Passed | Skipped | Assertion failures | Terminal result |
|---|---:|---:|---:|---|
| 0 | 158 | 1 | 1 | Elapsed limit, 1,801.03 seconds |
| 1 | 140 | 1 | 0 | Elapsed limit, 1,800.42 seconds |

These are partial results. The other six original shards were not started, and
unexecuted or interrupted cases are not passes. The original logs, node lists,
phase outcomes, source manifests and stopped test directories remain retained.
The owned test processes ended before source edits began.

## Storage correction

The assertion failure was the Semantics-16 policy-origin workflow that resumes
an interrupted phase. Its study receipt records `disk_budget_exhausted`: seven
of eight cells were eligible and complete; the eighth was refused. Its own
declared limit was 128 MiB. The retained data directory measured 136,238,173
bytes, and the complete test case contained 149,422,238 bytes in 141 files.
The host still had hundreds of GiB free. The study guard was enforcing its
declared bound.

`tests/test_policy_origins.py:sources_and_spec` now declares 256 MiB before a
new attempt begins. Eight cells retain source, replay and terminal/phase
checkpoint databases under the current schema. The fixture's wall-time and
mock-provider limits are unchanged. The original stopped study was neither
resumed nor edited. Its file hashes and modification times were retained for
comparison. No production storage guard was disabled.

The formerly failing phase-resume case passed on both Windows interpreters
(186.91 and 181.15 seconds). Its assertions still require all eight cells,
exact recorded continuation, verified imported evidence, immutable parents,
and correct treatment of missing goods trades. A valid zero-trade window
continues to produce a missing price effect rather than an invented price.

## CI partition change

The default full-suite matrix now selects 16 shards per OS/Python pair, with
indices 0 through 15 and the existing 30-minute job limit. The workflow command,
its consistency test and the development guide agree on the new count.

Applying the production partition function to the retained full collection
selected all 3,337 node IDs exactly once: nine partitions contain 209 cases and
seven contain 208. This proves selection coverage and balance, not execution
success or that every new shard will meet its wall-time limit. The complete
configured matrix still needs results.

## Evidence and reproduction

Local evidence root: `C:\Users\matri\.codex\tmp\ae-089e251d`.

The root retains `build-gates.json`, `browser-gates.json`, `browser-report.json`,
`initial-matrix-audit.json`, `original-policy-disk-stop-artifacts.json`,
`policy-origin-py311-meta.json`, `policy-origin-py312-meta.json`,
`ci-docs-py311-meta.json`, `ci-docs-py312-meta.json`,
`shard16-collection-audit.json`, the environment-preparation receipts and their
logs. The exact commands, interpreter paths, source snapshots and local limits
are recorded in those receipts. The earlier failed harness was also archived.

The repository-level policy selection is:

```powershell
python -m pytest tests/test_policy_origins.py tests/test_pytest_shard.py tests/test_documentation.py -v --tb=short
```

The observed runs added isolated pytest directories, explicit root selection,
environment isolation, phase-result capture and bounded process supervision.
Provider-facing calls in these tests use their local HTTP fixtures; no paid
provider campaign was launched. Keep at least 40 GiB free for local work.

## Next work

The [hosted admission follow-up](2026-09-10-population-hosted-admission.md)
supersedes items 1 and 2 below: all 64 local matrix slots are reconciled, the
real production-backend city gate passed, and all eight hosted checks passed.
Native acceptance remains open; the subsequent implementation order is unchanged.

The original pre-matrix next-work record is retained below for chronology:

1. Complete the current 16-shard Python coverage on the declared Windows/Linux
   interpreter combinations. Keep failed/limited attempts distinct from later
   invocations. Ubuntu 26.04 under WSL and both Python environments are prepared;
   Linux tests have not yet run. Docker daemon readiness remains unverified.
2. Complete the outstanding real-backend and hosted integration gates before
   treating full project admission as passed.
3. Preserve the terminal native campaign, interrupted verification, recovered
   copy and original cumulative allowances. Productive native-generation and
   full-prefix verification/export acceptance remain unproved.
4. Continue W6 after the W5 contract is met, using the
   [education integration draft](2026-09-10-education-integration.md). That draft
   maps schools to existing person identity, skills, time, wages and ledger
   authority; it does not claim an implemented school system. W7, W8 and W9
   remain in scope, with goods and equity research equally prioritized.

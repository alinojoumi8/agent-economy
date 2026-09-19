# Jev, direct chat providers and ten Hermes citizens

The requested target is a fresh 100-tick world. Run `e911d9c2a8` is now running
under the ten-citizen Hermes supervisor. The latest audited boundary in this
record is **tick 82 of 100**; this is not a completed 100-tick result. All ten
citizens submitted decisions on ticks 2–82. The original launch was blocked by
automatic approval review. The user requested another attempt, and the current
supervised continuation was accepted.

## Scope and configuration

- Profile: `runs/jev-hermes-100-live.yaml`; seed `20260919`; semantics 16.
- Eight native citizens, three unlisted firms, smaller legislature, one outlet;
  27 initial agents and ten additional Hermes citizens after admission.
- Jev: `typesafe/jev-1.13` via OpenRouter Decisions, resolved to
  `typesafe/jev-1.13-20260917`. OpenRouter remains restricted to Jev.
- Background: `deepseek-flash` directly at DeepSeek and `MiniMax-M3` directly
  at MiniMax. Neither route uses OpenRouter.
- Hermes: the existing ten personas and goals, in isolated profiles prefixed
  `ae-e911d9c2a8-`. Each uses the existing `openai-codex/gpt-5.6-luna` settings
  through Hermes' existing ChatGPT authentication. Original profiles and the
  selected city `e2e31f1f15` remain intact.
- The server has a hard target of tick 100 and a USD 10 app inference cap.
  Hermes usage is outside that ledger. Admission occupies tick 1, so ticks
  2–100 can produce at most 990 Hermes decisions with ten daily wakes.

## Fixes prompted by the earlier pilot

The previous mixed pilot selected 75 staff turns and only three ordinary-citizen
turns. Jev selected wait on 77 of 78 calls. The v2 policy excludes staff and
states an explicit consumption, employment and cash-reserve objective. It adds
the intermediate consumption target to the quantity menu. The target is a
policy preference; the engine does not expose a hunger measurement here.
Specialized obligations still leave the bounded menu.

MiniMax's earlier malformed replies ended with `finish_reason=length`, including
repair attempts. Its configured provider defaults did not override the gateway's
smaller purpose-specific output ceiling. The prospective response contract now
gives this route an 8192-token minimum, sends the JSON schema on the first
request, and fails visibly after an unsuccessful repair. Cost estimation and
the recorded request include the effective ceiling. Existing profiles are unchanged.

The Hermes operator now accepts explicit local HTTP ports and can preserve the
launcher's selected city during fresh setup. An explicit semantics-16-or-later
renewal contract retains the original scope, paused-boundary, unconsumed-turn
and audit checks. Existing semantics-11 renewal behavior is retained.

The mocked 100-day operator regression exposed a transient Windows file lock
while replacing `status.json`. The operator and supervisor now retry atomic
replacement with up to 0.62 seconds of backoff, preserve the previous complete document,
and still raise on persistent failure. This prevents a brief sharing violation
from aborting a healthy worker without masking durable storage problems.

The first real admission replay exposed a separate restoration bug: replay
copied missed attendance before NIGHT had spawned its referenced actor. It now
restores between-tick submissions before NIGHT and defers missed attendance
until MORNING, matching live execution. This changes replay restoration only;
it does not rewrite the source world or its admission receipts.

## Completed live evidence

Two explicit three-provider readiness checks passed. Their typed evidence is
retained under `data/runs/preflight/`, with run IDs `preflight-52a3f69b51` and
`preflight-6fa9e43cdc`. Each Jev readiness call cost USD 0.000013314. Readiness
cost is separate from the world totals below; direct-provider readiness returned
usage but has no `llm_calls` row.

| Admission tick 1 | Logical calls | Recorded cost USD |
|---|---:|---:|
| DeepSeek | 18 | 0.005470010 |
| MiniMax M3 | 2 | 0.002139960 |
| Jev | 5 | 0.000347886 |
| Total | 25 | 0.007957856 |

Jev selected five goods purchases; all five passed engine validation. There
were zero Jev rejections, provider failures, JSON repairs or malformed-output
no-ops. Jev latency ranged from 367 to 625 ms, with a 424 ms median. Its
confidence values ranged from 0.46 to 0.54 and describe answer concentration,
not economic correctness. The smaller population, different seed and new policy
objective mean this is not an efficacy comparison with the previous pilot.

An atomic read-only snapshot of the paused admission world replayed exactly as
`replay-e911d9c2a8-95c949a165`, with all three provider keys removed, HTTP blocked,
zero live dispatches, no canonical differences, and balanced source/replay
ledgers. The snapshot SHA-256 remained
`6b0afde4d5588f65ace28ff0b103c0197116284808b43b15779e8c409f461448`.
The original world stayed paused and was not replaced by the replay.

Private aggregate evidence, launch configuration, snapshot and proof are under
`reports/out/jev-hermes-100-20260919/`. The browser's Decisions view shows the
five accepted choices without publishing candidate payloads or private prompts.

## Supervised continuation

The server is available at `http://127.0.0.1:18774`, run `e911d9c2a8`. The
supervisor started the current continuation from tick 40 with `--days 60`, five
concurrent Hermes workers, and a target of tick 100. Do not also press the app's
Run or Step controls while the cohort operator owns the clock. Progress and
failures remain in `data/control-plane/hermes-cohort/e911d9c2a8/`.

An earlier supervisor and its worker exited without a final error record. A
subsequent tick-4 attempt preserved nine queued actions when Ethan's Hermes
process exited with an empty transcript. The existing error omitted its exit
code, so its exact cause is unknown. The operator now journals nonzero subprocess
exit codes and includes them in the failure message, without recording secrets
or provider response bodies. It still refuses an unclassified automatic retry.
Explicit recovery skipped the nine queued citizens, completed Ethan's missing
decision, and saved tick 4 without duplicate accepted submissions.

A later Aisha startup stopped with exit code 15 and an empty transcript while
nine tick-9 actions were already queued. A targeted regression exposed a process
ownership gap: the child list can become stale before process objects are
constructed. Cleanup now rechecks direct parent IDs and creation times at every
edge and tracks each process generation separately. The regression failed before
the fix and passed afterward. A separate fast-launcher-exit regression preserves
normal process completion when a fresh creation-time lookup is no longer possible.
This hardens cleanup; it does not establish that this race caused the observed
exit code 15. The live continuation retains the same profiles, models and world.

At the tick-40 boundary, a local identity GET failed with `httpx.ReadError`
and Windows error 10053 before Aisha's next decision. The other nine tick-41
actions remained queued. The operator now retries transient GET transport
failures at most twice with bounded backoff and a journal containing only the
path, attempt and error class. POST requests, HTTP errors and invalid JSON are
not retried: a lost write response could follow a successful clock advance.
After confirming the old controller and citizen processes had exited, recovery
retained all nine action IDs and payload fingerprints, completed Aisha's turn,
and saved tick 41 with all ten attendance records submitted. Six applications
were rejected because another citizen filled their target job earlier in that
execution phase; none was lost to the interruption or an expired turn.

Through tick 40, Jev selected 170 menus: 132 purchases, 36 combined
purchase/job-application choices and two waits. All 168 purchases succeeded.
One application was correctly rejected at tick 38 after another citizen filled
the job earlier in the same execution phase. Thirty specialized turns stayed
outside Jev's bounded menu. Native inference cost USD 0.393664916, including
USD 0.021376236 for Jev, with no provider failures, repairs, or malformed-output
no-ops. Jev's median latency was 456.5 ms and its 95th percentile was 615 ms.
All 390 post-admission Hermes turns were submitted.
All 37 agents were alive; eleven were employed.
The ledger reconciled with no account mismatches. Live aggregate snapshots use
`progress-audit.json`; admission evidence is reconstructed only from its frozen
tick-1 snapshot. Budget reservations observed during an active tick are not
treated as abandoned reservations.

The tick-10 checkpoint exposed missing negative input evidence in legacy replay:
validation-time rejections and stale submissions were omitted, although economic
state matched. Replay now restores those receipts and their CONTROL events at
the recorded boundary without making them executable decisions. A stale request
can name the wrong target day, so its event tick determines restoration timing.
The regression covers invalid actions, stale hashes, an outdated target tick,
the corrected successful submission, missed attendance and unchanged source bytes.

The same frozen checkpoint then replayed exactly as
`replay-e911d9c2a8-c4f81424e5`, with zero differences, balanced source/replay
ledgers, removed provider keys, blocked HTTP and zero live dispatches. Its
SHA-256 remained `ba4c90588adf928e54b87daefb53d712e48b5ca322b0f20a18041c2f4818d518`.
Both the failed proof and corrected proof remain in the private evidence folder.

The automatic tick-20 checkpoint also replayed exactly as
`replay-e911d9c2a8-d966ec7cab`, with the same network-disabled checks, balanced
ledgers and unchanged snapshot. Its SHA-256 remained
`20d6783f7250f1923afc44c40d9403baca363d42a08a447843b1e516424e1126`.

The tick-30 checkpoint replayed exactly as `replay-e911d9c2a8-efc4a11832`,
also with balanced source/replay ledgers, blocked HTTP, removed provider keys,
zero live dispatches and unchanged snapshot bytes. Its SHA-256 remained
`972815f16cdda4a74570b906894c731984f963d48bc2fe91190650cbf7f319ec`.

The tick-40 checkpoint replayed exactly as `replay-e911d9c2a8-9e47bbc388`,
including the execution-time rejection. Source and replay ledgers balanced,
provider keys were removed, HTTP was blocked and live dispatches were zero.
Its unchanged snapshot SHA-256 was
`b5ca3c451b7c61d188c632abf1bdd89cf86e787604fa46d1809c14cc3b3428d4`.

Accepted actions do not imply new economic effects. Through tick 20, one Jev
citizen made 17 accepted application attempts for four distinct jobs. The engine
reused existing pending applications, so 13 attempts created no new application.
The prospective `bounded-economic-choice-v3` policy now observes only that
citizen's active applications to already visible jobs and excludes them before
ranking new application choices. Pending offers can still be accepted. V1/v2
behavior is preserved, and this ongoing world remains on v2; the 100-tick results
must not be presented as a live evaluation of v3.
Through tick 40, there were 35 accepted application attempts, ten new
applications and 25 accepted attempts that reused an existing application.

After tick 100, audit all native and external receipts, rejection causes,
fallback attendance, model identity, usage and persistent Jev reservations;
reconcile the ledger and replay the completed source with network access
disabled. No claim about 100-tick reliability or Hermes decision quality can
be made from these early ticks.

## Browser repair and continued progress

The live browser exposed `THREE.Object3D.add` errors when switching to 3D in a
world without recorded places. The scenery group was empty, and spreading its
children called `add()` with no object. The renderer now transfers each existing
child explicitly. A 37-citizen, zero-place browser regression reproduced the
error before the fix and passed afterward, including selection and Atlas/3D
remounts. This changes presentation only; the source world and v2 policy remain
unchanged. The production frontend was rebuilt and the existing browser reloaded
without restarting the server or its supervisor. A separate background tab loaded
the actual world's 3D canvas successfully with no browser console errors.

This profile has no recorded place coordinates and does not enable parcel
construction. Those notices describe the run's configuration; restarting the
same world cannot supply missing historical movement or construction records.

Through tick 82, all 810 post-admission Hermes turns were submitted. Native cost
was USD 0.764671246, with 346 Jev selections, 64 outside-menu turns, balanced
ledgers and no native provider failures, repairs or malformed-output no-ops.
The only Jev action rejection remains the unavailable application at tick 38.
Six Hermes CLI timeouts were recovered at ticks 53, 55, 56, 67, 79 and 82; these
are separate from native provider errors. At tick 79 the decision was already
queued when the timeout was handled, with no retry journaled. Ethan's tick-82
attempts had a missing receipt and then a timeout before the third attempt
succeeded. All ten citizens have exactly one executed submission on both ticks
79 and 82. The same supervisor continues toward tick 100.

## Verification

The initial focused suite passed **181 tests** across Jev, external gateway,
Hermes operator/supervision, response contracts, recorded replay and documentation.
The broader gateway, property, prompt-cache, observability and population-replay
suite passed **196 tests**. Regressions cover fresh external admission and mixed
attendance from genesis, both old and new policy replay, loopback-port rejection,
preserving the selected city, transient file locks and budget estimation before
dispatch. Exact commands are recorded in the PR.

All 521 Git-visible Python files compile. Pinned dataset verification and
`pip check` passed. An initial pytest attempt could not access the system
temporary directory; subsequent tests used fresh directories under `tmp/`.
The inherited FastAPI/Starlette httpx deprecation warning remains.

The subprocess changes passed 41 operator/supervision tests and a local
stress run of 300 concurrent process-tree lifecycles (five workers, 32.06 seconds,
all exit codes zero). The external gateway, recorded golden replay, Jev runtime and population Commons
replay suites passed 68 tests in 253.93 seconds after restoring negative inputs.
The policy-origin recovery case that crashed in CI passed locally in 220.77 seconds
using the shorter workspace temporary path `tmp/p11`. Its first local attempt
hit the Windows path-length limit under a longer temporary directory.

CI for `d0e8ccc` completed successfully on attempt 2, including the dashboard.
The first attempt's policy-recovery job exited with a Python segmentation fault;
the same job passed when retried. That transient crash remains disclosed, with
no demonstrated link to Jev. The PR stays a draft pending the live test; this
record is not a release or merge claim.

The subsequent dashboard CI run passed 138 of 139 browser tests. Its construction
evidence navigation test timed out while the 3D viewport remounted. The trace
retained the correct business in the URL and ultimately displayed the right
selection. The test now waits for the viewport's existing ready signal before
asserting the restored selection; five consecutive local repetitions passed in
38.4 seconds. No application frontend behavior changed in this correction.

The prospective v3 change passed 100 tests across candidate compilation, typed
contracts, gateway, integration, resilience, runtime, frozen studies and labor.
They include v1/v2/v3 whole-world replay and prospective/frozen study roundtrips,
actor-owned pending applications, filtering before ranking, offer acceptance and
malformed-history rejection. Documentation checks passed another 22 tests.

Two Linux Python 3.12.14 CI jobs crashed immediately during their timed traceback
dump. A bounded standard-library-only probe reproduced a crash on local Linux
Python 3.12.13 at its first timed dump. Without that timer it completed 452,870
JSON cycles in 12 seconds; Python 3.14.4 completed 469,302 cycles with the timer.
[CPython issue 140815](https://github.com/python/cpython/issues/140815) documents
the matching invalid/freed-frame traceback race. This supports the diagnosis;
the CI failures did not produce a C-level backtrace proving the identical cause.

The two affected CI jobs now disable timed traceback dumps while retaining
pytest's fatal-signal handler, all assertions and their ten-minute job limits.
The affected recovery shard passed all ten tests on Linux Python 3.12.13 in
138.32 seconds. Its first local attempt correctly refused resume because the
working checkout changed during execution; it was interrupted after one failed
and two passed tests and rerun from an isolated, stable checkout.

CI for `869de4c` completed successfully, including the affected recovery shards
and dashboard. The later transient-read regression failed before its fix; afterward
all 52 operator/supervision tests passed in 8.98 seconds. The new cases cover
read recovery and exhaustion, redacted diagnostics, a write applied before its
response is lost, and non-retryable HTTP/JSON failures. CI for `9d55563` completed
with 32 jobs passed and two conditional jobs skipped: the generic matrix
placeholder and Hosted PostgreSQL / S3 integration. The newer frontend repair
requires its own current-head CI before any merge.

The empty-scenery repair passed all 15 city-viewport browser tests in 58.1 seconds,
all 284 dashboard unit tests, TypeScript checking, license-notice verification,
and the production build. The existing bundle-size warning remains. The new
regression first failed with four `Object3D.add(... undefined)` console errors;
after the fix, the real served 3D world also reported a ready canvas and no
console errors. This does not complete the pending 100-tick audit.

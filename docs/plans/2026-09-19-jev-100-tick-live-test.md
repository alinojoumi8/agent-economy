# Jev, direct chat providers and ten Hermes citizens

The requested target is a fresh 100-tick world. Run `e911d9c2a8` is now running
under the ten-citizen Hermes supervisor. The latest audited boundary in this
record is **tick 6 of 100**; this is not a completed 100-tick result. All ten
citizens submitted decisions on ticks 2–6. The original launch was blocked by
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
supervisor started the current continuation from tick 8 with `--days 92`, five
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

Through tick 6, Jev selected 26 menus: 22 purchases and four combined
purchase/job-application choices. Every selected action passed engine validation.
Four specialized turns stayed outside Jev's bounded menu. Native inference cost
USD 0.058026392, with no provider failures, repairs, or malformed-output no-ops.
The ledger reconciled with no account mismatches. Live aggregate snapshots use
`progress-audit.json`; admission evidence is reconstructed only from its frozen
tick-1 snapshot. Budget reservations observed during an active tick are not
treated as abandoned reservations.

After tick 100, audit all native and external receipts, rejection causes,
fallback attendance, model identity, usage and persistent Jev reservations;
reconcile the ledger and replay the completed source with network access
disabled. No claim about 100-tick reliability or Hermes decision quality can
be made from these early ticks.

## Verification

The final focused suite passed **181 tests** across Jev, external gateway,
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

The final subprocess changes passed 41 operator/supervision tests and a local
stress run of 300 concurrent process-tree lifecycles (five workers, 32.06 seconds,
all exit codes zero). The
policy-origin recovery case that crashed in CI passed locally in 220.77 seconds
using the shorter workspace temporary path `tmp/p11`. Its first local attempt
hit the Windows path-length limit under a longer temporary directory.

CI for `d0e8ccc` completed successfully on attempt 2, including the dashboard.
The first attempt's policy-recovery job exited with a Python segmentation fault;
the same job passed when retried. That transient crash remains disclosed, with
no demonstrated link to Jev. The PR stays a draft pending the live test; this
record is not a release or merge claim.

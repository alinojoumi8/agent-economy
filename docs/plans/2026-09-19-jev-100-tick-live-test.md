# Jev, direct chat providers and ten Hermes citizens: final live test

Run `e911d9c2a8` completed **100 ticks** on 2026-09-19. All ten Hermes citizens
submitted on every post-admission day: **990 turns across ticks 2–100**.
Recorded replay reproduced the completed world exactly, with provider keys
removed, HTTP blocked, zero live dispatches, balanced ledgers and unchanged
source bytes. The supervisor exited successfully at its original target.

**Recommendation: retain Jev as an opt-in selector for bounded shopping and
employment choices.** The integration worked in this scenario at low recorded
cost and latency. This single seed does not establish economic superiority,
confidence calibration, or suitability as a general agent planner. The
prospective v3 policy fixes repeated pending-job applications; this completed
world retains v2 and is not a live v3 evaluation.

## Scope and provider boundary

- Profile `runs/jev-hermes-100-live.yaml`, seed `20260919`, semantics 16,
  decision policy `bounded-economic-choice-v2`.
- Twenty-seven initial agents, including eight native citizens, three unlisted
  firms, smaller institutions and one outlet; ten Hermes admissions bring the
  population to 37. All 37 remained alive; thirteen were employed at tick 100.
- Only Jev used OpenRouter: `typesafe/jev-1.13`, resolved on all 422 calls to
  `typesafe/jev-1.13-20260917`. No other OpenRouter model was dispatched.
- `deepseek-flash` used DeepSeek directly; `MiniMax-M3` used MiniMax directly.
  Existing chat routes handled specialized work outside the bounded menu.
- Hermes retained all ten existing personas in isolated `ae-e911d9c2a8-`
  profiles, using `openai-codex/gpt-5.6-luna` through existing Hermes ChatGPT
  authentication. This was not an OpenRouter route. Original profiles and the
  selected city `e2e31f1f15` were preserved.
- The original USD 10 native inference cap and hard target of 100 were retained.
  No replacement world, additional paid study or second clock controller was
  started. Recovery preserved queued decisions and the stored policy.

## Costs and latency

| Native route | Logical / physical calls | Recorded USD | Median latency | p95 latency |
|---|---:|---:|---:|---:|
| DeepSeek direct | 985 / 985 | 0.571303280 | 1,450 ms | 10,502 ms |
| MiniMax M3 direct | 271 / 271 | 0.315754080 | 4,764 ms | 17,478 ms |
| Jev via OpenRouter | 422 / 422 | 0.043834056 | 457 ms | 613 ms |
| Total | 1,678 / 1,678 | **0.930891416** | — | — |

All native routes recorded zero provider failures, JSON repairs and malformed-
output no-ops. This does not mean every economic proposal was accepted or every
Hermes subprocess completed without interruption. The routes perform different
work, so this is an operational account, not a matched efficiency benchmark.

Direct-provider costs use configured tariffs. Hermes CLI usage is outside this
ledger. Two earlier readiness checks also sit outside the world totals: their
Jev calls each recorded USD 0.000013314; direct readiness usage has no world
`llm_calls` row. All **422 Jev charges settled**, totaling 43,834,056 nano-USD,
with no reservations left. The budget's administrative `sealed` flag is zero;
settlement is verified, but the budget is not described as sealed. The sole
supervisor and its workers exited at tick 100 with exit code zero. The original
server remains available to inspect the result.

## Decisions and economic outcomes

Five eligible native citizens produced 500 policy receipts: **422 Jev selections**
and **78 specialized turns outside the menu**. Jev selected 380 purchase-only
bundles, 38 purchase/application bundles, one purchase/offer-acceptance bundle
and three waits. The deterministic engine retained authority over every effect.

| Jev-selected action | Attempts | Accepted | Interpretation |
|---|---:|---:|---|
| Buy goods | 419 | 418 | One stock conflict at execution |
| Apply for job | 38 | 37 | Ten new applications; 27 idempotent repeats |
| Accept job offer | 1 | 1 | Recorded offer accepted |
| Wait | 3 | 3 | Valid choice with no economic action |

The two rejected actions were checked against canonical event order:

- At tick 38, actor 19 applied after actor 10 accepted the job earlier in the
  same execution phase (hire events 3537/3538, typed receipt 3546). The purchase
  in actor 19's bundle succeeded; the unavailable application was rejected.
- At tick 96, actor 25 selected one unit of food from firm 1. Its menu included
  a six-unit option, but earlier buyers purchased six units in events 8510,
  8511, 8513, 8515 and 8517 before rejection 8519 and receipt 8520. The inventory
  guard rejected the late buyer. No model retry was needed.

Other native actions had 45 rejections: 32 missing/unavailable applications,
five already-pending offers, three nonpositive amounts, two unlisted firms,
one unavailable job, one already-insured actor and one attempt to combine
study with another action. These guarded refusals are a remaining decision-
quality limitation, distinct from transport or parsing failures.

Jev confidence ranged from 0.09 to 0.96, with median 0.30. It describes answer
concentration, not the probability of correctness or economic success.

## All ten Hermes citizens

Each citizen submitted **99 turns**, covering ticks 2 through 100: Maya Chen,
Omar Haddad, Sofia Reyes, Noah Okafor, Leila Patel, Lucas Moreau, Aisha Mensah,
Ethan Kim, Isabel Costa and Daniel Novak. Tick 1 was admission; its ten recorded
missed-attendance rows are not missing post-admission turns.

Of the 990 final submitted actions, **963 executed and 27 were rejected**:
23 unavailable jobs, two missing/stale offers, one already-pending compute-plan
change and one out-of-stock purchase. Eleven earlier catalog validation
rejections and two stale attempts were preserved separately from final daily
attendance. No queued action, duplicate executed submission or post-100
submission/attendance remained.

Executed actions included 235 purchases, 203 application attempts, sixteen offer
acceptances, nineteen study actions, one company founding and 470 explicit
no-action choices, plus smaller business and compute operations. Accepted
attempts can reuse existing state; these are not counts of new jobs or welfare gains.

Seven 240-second Hermes CLI timeouts occurred: Aisha at 53, Leila at 55,
Daniel at 56, Leila at 67 and 79, Ethan at 82, and Daniel at 83. All affected
days ultimately had ten submitted turns. Tick 79 was already queued when its
timeout was handled, with no retry journaled. Ethan's tick 82 had a missing
receipt, then a timeout, before success on attempt three. Sanitized diagnostics
showed compaction activity without establishing its causal role.

Earlier unclassified process interruptions and the tick-40 local GET failure
required explicit recovery. Queued decisions were retained; the nine tick-41
action IDs and payload hashes matched before and after recovery. This was a
completed run with repairs and recoveries, not an uninterrupted reliability run.

## Repairs and compatibility

- **Jev policy:** v2 excludes staff turns, states consumption/employment/reserve
  objectives and adds an intermediate consumption quantity. The earlier pilot
  chose wait on 77/78 menus and mostly evaluated staff; changed policy, seed and
  population prevent a model-only comparison. Opt-in v3 excludes the actor's
  own pending/negotiating applications before ranking and retains offer
  acceptance. V1/v2 behavior and historical replay remain intact.
- **MiniMax output:** new `required-json-v2` routes send a schema initially and
  apply the configured 8192-token minimum before metering and dispatch. Invalid
  output after one repair pauses visibly. Existing profiles remain unchanged.
- **Hermes supervision:** explicit loopback ports, selected-city preservation,
  opt-in turn renewal, bounded progress-file replacement retries, nonzero-exit
  journals, and fresh process-ancestry/creation-time checks protect recovery.
  The ownership regression does not prove the cause of the earlier exit code 15.
- **Local API reads:** transient GET transport failures get at most three total
  attempts with bounded backoff and redacted journals. POST writes, HTTP errors
  and invalid JSON are not automatically retried.
- **Replay:** missed attendance is restored after its actor spawns; rejected
  and stale inputs are restored at their recorded CONTROL boundary as audit
  evidence, never executable decisions. Source runs are not rewritten. Both
  the initial failed tick-10 proof and corrected proof survive.
- **Dashboard:** empty scenery no longer calls `Object3D.add()` without an
  object. A reproduced regression covers zero places, selection and Atlas/3D
  remounts. A separate navigation test waits for existing 3D readiness. The
  production bundle was rebuilt without restarting the server or world.
- **CI:** two Python 3.12 jobs disable timed traceback dumps after a standard-
  library-only Linux probe reproduced a crash at that operation. Assertions,
  crash handlers and job limits remain. The identical cause of the original
  CI crashes was not proven by a C-level backtrace.

## Exact replay, source integrity and app verification

The final read-only SQLite snapshot passed `quick_check`. Replay
`replay-e911d9c2a8-b3af0882d8` completed 100 ticks with **zero canonical differences**.
All three provider environment keys were removed, both httpx send paths were
blocked, and the replay gateway recorded zero live dispatches. This is process-
level HTTP blocking, not an operating-system firewall claim.

Both ledgers reconciled. The source grand sum and USD sum were zero, with no
account mismatches. The frozen source SHA-256 stayed:

```text
d2761042c2682aa0b6497136d3ef4f0b98577912ef9af3e332e5103ba54ba4e8
```

The live database, its WAL, and both Jev budget files also retained their before/
after SHA-256 hashes across the audit and replay. Checkpoints 1, 10, 20, 30, 40
and 50 had already passed the same exact-replay checks.

The served app showed day 100 paused, a ready 3D canvas and no browser console
errors. Decisions displayed the latest 200 of 500 policy receipts, including
the tick-100 direct outside-menu route and four Jev purchases. No Run/Step
control was used for inspection. This profile has no recorded place coordinates
or parcel construction, and the UI labels placement as derived. Restarting the
saved world cannot add those records; a spatial test needs a new configuration.

Private evidence remains ignored in `reports/out/jev-hermes-100-20260919/`:
`final-result.json`, `final-independent-verification.json`, `final-replay-proof.json`,
`final-live-source-immutability.json`, frozen source/replay, checkpoint proofs
and recovery evidence. Credentials, raw prompts and databases are not committed.

## Validation and adoption plan

Implementation head `21cea75` passed CI run `35450870540`: **32 jobs passed**;
the generic optional matrix placeholder and Hosted PostgreSQL/S3 integration
were skipped. CodeRabbit's status was SUCCESS. The optional full matrix and
hosted integration were not run. Final documentation changes have separate
checks recorded in PR 95. The PR remains draft and must not be merged in this task.

Local verification included 181 initial focused tests, 196 broader tests, 68
external/replay/Jev/Commons tests, 100 v3/labor tests, 52 final operator/supervision
tests, 300 successful subprocess lifecycles, fifteen City viewport browser tests,
284 dashboard unit tests, TypeScript/build/license checks, pinned datasets,
dependency checks and compilation of 521 Git-visible Python files. Exact commands
and results are in PR 95. Existing bundle-size and Starlette/httpx warnings remain.
Windows temporary-path failures and a study refusing a changed checkout were
resolved using short paths and an isolated checkout; the failed attempts are
not reported as passes.

1. Keep Jev opt-in with backend-only `OPENROUTER_API_KEY`, pinned model identity,
   persistent reservations, explicit outside-menu routing, engine validation
   and recorded receipts. Continue direct DeepSeek/MiniMax and Hermes for
   conversations, institutions and broader plans.
2. Evaluate v3 prospectively with matched candidate snapshots and matched seeds
   against the current direct policy and deterministic baseline. Predeclare
   allowance, population, objectives and stopping rules. Measure unique job
   applications, employment, consumption, rejected proposals, cost, latency
   and replay integrity; repeated accepted attempts must not count as gains.
3. Calibrate confidence against held-out outcomes before using it as an
   escalation threshold. Review rejected direct/Hermes proposals separately.
4. For a visible spatial city, explicitly configure geography/construction in
   a new world and validate those mechanics separately. This test did not
   authorize or start another paid run, upgrade or reset a current world.

The evidence supports bounded integration. A broader replacement of agent
reasoning remains untested. See [the Jev guide](../jev.md) for configuration
and earlier pilot records for their separate limitations.

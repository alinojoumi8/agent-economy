# Jev with the existing DeepSeek/MiniMax Hermes profile

September 19, 2026. Recommendation: keep the existing default and retain Jev as
an opt-in experiment. Native integration works, but the observed choices do not
yet establish useful economic behavior. No further live spend is needed to read
these results.

## What ran

The owner supplied the OpenRouter key privately in the ignored `.env`, requested
real app testing, and restricted OpenRouter to Jev. Both comparison arms use
the existing direct `deepseek-flash` and `MiniMax-M3` endpoints. The Jev arm adds
`typesafe/jev-1.13` through `/api/alpha/decisions`, resolving consistently to
`typesafe/jev-1.13-20260917` from TypeSafe.

`runs/jev-hermes-baseline.yaml` and `runs/jev-hermes-live.yaml` inherit
`runs/hermes-local-live-deepseek.yaml`. Both use seed 42, three ticks, 44 living
agents including institutional staff, and a USD 1 world cap. A local manifest
froze their resolved configurations before execution and confirmed that the
world/background settings match after removing the Jev policy/provider/tariff.
Both use semantics 16, required by the typed pilot. The original semantics-11
profile and old worlds were not migrated. These were sequential fresh runs.

Hermes gateway/public-join configuration was retained. No external Hermes worker
was launched, so this is not evidence of a live external Hermes client completing
a turn. It is also not the separate scripted-background research study contract.

Exact live commands:

```powershell
.\.venv\Scripts\python.exe run.py --config runs/jev-hermes-baseline.yaml --ticks 3 --preflight-live --approve-live-inference
.\.venv\Scripts\python.exe run.py --config runs/jev-hermes-live.yaml --ticks 3 --preflight-live --approve-live-inference
```

Both preflights passed. The Jev preflight receipt `preflight-96cbccf5d4` records
317 input tokens, 31 output tokens and USD 0.000013314. Preflight runs have
separate allowances. Ordinary DeepSeek/MiniMax readiness calls return usage but
are not retained as call rows by the existing preflight implementation; the
table below excludes all readiness spend and is not an account invoice.

## Observed comparison

| Measure | Existing policy | Same setup with Jev |
|---|---:|---:|
| Run ID | `86943bd13b` | `6fbc64e1f2` |
| Completed ticks | 3 | 3 |
| Recorded world inference cost, USD | 0.11861785 | 0.052525774 |
| Tick execution wall time, seconds | 249.662 | 168.689 |
| Logical paid call records | 156 | 156 |
| Physical inference calls, including repairs | 177 | 168 |
| DeepSeek logical calls | 126 | 59 |
| MiniMax M3 logical calls | 30 | 19 |
| Jev logical/physical calls | 0 | 78 |
| Generative JSON repair attempts | 21 | 12 |
| Generative replies still invalid after repair | 13 | 10 |
| Engine action proposals accepted/rejected | 121 / 19 | 133 / 0 |
| Ledger reconciliation | Passed | Passed |
| Exact recorded replay without keys/network | Passed | Passed |

Direct-provider costs use returned usage and configured tariffs, including
repair usage. Jev costs come from returned provider receipts. The `cached` field
on ordinary call rows indicates provider prompt caching, not a skipped HTTP
request. Physical counts include the metered repair envelopes. Tick wall time
excludes preflight, initialization and report generation. Runs were sequential;
provider cache warmth, live sampling and service load can affect the comparison.

Recorded cost fell 55.7% and tick wall time fell 32.4% in this particular pair.
This compares an unrestricted policy against a bounded menu, so it cannot isolate
the model's quality or predict savings at scale. The logical call count did not
fall; cheaper calls replaced other calls and there were fewer repairs.

Jev's 78 calls cost USD 0.011149194 in total. Median latency was 461 ms and the
nearest-rank p95 was 666 ms. All 78 native responses validated without a repair,
HTTP error, rate limit, model change or second-model escalation. All 78 budget
reservations settled; the conservative budget ledger records USD 0.011149196
because it rounds individual charges to integer nanodollars. It retains no
unknown/pending charge from this world.

The direct background providers still produced invalid JSON contracts. The
existing non-tiered gateway repaired them once, then recorded a local no-op for
the 13/10 remaining failures. Those are not successful model decisions, even
though transport succeeded and no `provider_failure` event paused either run.
Both deterministic HTML reports were generated; their optional model narration
was skipped because the comparison profiles allocate zero report reserve. The
associated budget warning does not mean the USD 1 world cap was exhausted.

## What Jev actually chose

There were 105 bounded-policy receipts: 78 selected menus and 27 outside-menu
portfolio/study turns retained on the original routes. Thus Jev handled 74.3%
of recorded bounded-policy opportunities, not 74.3% of every app task.

- Jev selected `wait` 77 times and one job application. It selected no purchase.
- Every wait menu offered active choices. Menus contained 8, 22 or 29 options,
  including shopping, employment, combined bundles, wait and escalation.
- Of the 78 selected turns, 75 belonged to institutional staff and three to one
  ordinary citizen. This small cohort is a poor test of ordinary household demand.
- Jev disagreed with the deterministic reference on all 78 menus. That reference
  chose a non-wait option each time, but reference agreement is not correctness.
- Confidence ranged from 0.18 to 0.98. It describes the provider's answer
  concentration; no independent correctness labels or calibration were available.

The UI's 78 accepted Jev outcomes include 77 accepted waits. They must not be
reported as 78 productive economic actions. Likewise, zero rejected actions
does not establish improvement when the policy takes fewer active decisions.
Baseline rejections were 19 out-of-stock purchases. The stored terminal
`gdp_proxy_30d` was 214.04 versus 172.8; at only three ticks these are early-world
window values, not a completed 30-day study or a causal welfare finding.

The selection prompt supplies finances, dependents, risk preferences and bounded
memories, but does not define a consumption benefit or a suitability rubric.
Under that prompt, conserving cash may be a reasonable interpretation. This is
a hypothesis for the next test, not a proven explanation of the wait rate.
Ordinary shopping/job turns of staff can currently enter the menu even while
their specialized duties remain on the original routes; cohort scoping also
needs review before any broad rollout.

## Application and replay checks

The completed Jev world is served locally at port 18773 with `--ticks 0`, paused
at day 3. Run and Step are disabled by that session boundary. Its actual browser
UI showed the DeepSeek/MiniMax/Jev provider badge and all 105 Decisions receipts.
Using the UI's historical control at tick 0 showed zero receipts; returning to
live restored 105. The observer API omitted private candidate/evaluation keys.
No browser-console errors were observed.

Exact replay was performed after removing `OPENROUTER_API_KEY`,
`DEEPSEEK_API_KEY` and `MINIMAX_API_KEY` from the replay process and blocking both
sync and async HTTP sends. Replay IDs:

- Baseline: `replay-86943bd13b-1962a1aaac`.
- Jev: `replay-6fbc64e1f2-c3c6c90cd7`.

Both proofs reported `exact: true` with no differences. Source database hashes
and nonempty WAL hashes remained unchanged. An initial audit treated SQLite's
creation of an empty WAL as a source change; the database hash was identical.
The final audit explicitly ignores empty WAL files and passed on both sources.

Local private evidence remains under
`reports/out/jev-hermes-comparison-20260919/`: the pre-execution manifest,
`baseline.json`, `treatment.json` and `choice-diagnostics.json`. Source databases,
budget sidecars, checkpoints, reports and logs stay ignored and uncommitted.

An earlier Jev-only smoke world, `11a70e3467`, completed three ticks with 18 native
calls, USD 0.001162602 in Jev receipts, ledger reconciliation and exact offline
replay. It used scripted background cognition and is separate from this pair.
Before the owner's OpenRouter restriction, a now-retired comparator attempt
`a7e52b1012` made two GPT-4.1-mini logical calls costing USD 0.00073062 plus its
separate preflight. It was stopped and marked finished. No GPT or other
OpenRouter model was used in the requested DeepSeek/MiniMax comparison.

## Fixes and regression evidence

Live testing exposed a Windows failure caused by trying to persist a typed
budget beside an in-memory preflight store. Typed preflight now uses a durable
ignored evidence database. Ordinary paid background calls no longer cause a
false missing-typed-budget error before the first Jev call. Missing evidence
after a prior typed call still fails closed.

Readiness and every physical dispatch now reject non-Jev OpenRouter routes.
Recorded replay of old routes remains offline. Maintained comparator/hybrid
profiles contain no GPT route, and the direct DeepSeek/MiniMax routes remain
available. Regression tests cover these restrictions and the new preflight
success/failure evidence.

Executed on the current fixes:

```text
.\.venv\Scripts\python.exe -m pytest -q tests/test_jev_contract.py tests/test_jev_gateway.py tests/test_jev_candidates.py tests/test_jev_runtime.py tests/test_jev_resilience.py tests/test_jev_integration.py tests/test_jev_studies.py tests/test_provider_budget.py tests/test_recorded_replay_golden.py tests/test_documentation.py --basetemp C:/tmp/jev-hermes-final-01
145 passed

.\.venv\Scripts\python.exe -m pytest -q tests/test_documentation.py tests/test_external_agent_gateway.py tests/test_research_export.py tests/test_prd_completion.py tests/test_recorded_replay_golden.py tests/test_review_gateways.py tests/test_observability.py tests/test_scale_validation.py --basetemp C:/tmp/jev-live-regression-02
208 passed

# From dashboard/
npm run test:e2e -- world-os.spec.ts world-os-states.spec.ts world-os-privacy.spec.ts agent-connections.spec.ts world-os-routes.spec.ts live-city-context.spec.ts city-unified.spec.ts city-viewport.spec.ts --workers=1
139 passed
```

Python counts overlap. API tests retain the existing Starlette/httpx deprecation
warning. The initial remote CI run had one city context browser failure; that
case passed separately, three repetitions passed, and the full 139-test local
browser rerun passed. This does not retroactively make the earlier CI run green.
No full cross-platform Python matrix was run locally. Keep the PR draft while
remote gates and the remaining adoption evaluation are pending.

## Next test plan

1. Preserve the current default. Review eligibility by actor kind and decision
   purpose so the evaluation primarily measures the intended household tasks.
2. Define an economic suitability rubric from real engine state, including when
   waiting is correct. Review actor needs, expected benefit, affordability, job
   eligibility and stale inventory. Do not force activity solely to lower waits.
3. Freeze representative observations, including resource shortages and suitable
   abstentions. Compare the same menus using Jev, the deterministic reference,
   and, if needed, the existing direct DeepSeek/MiniMax adapters. OpenRouter
   remains Jev-only. No additional model purchase is required by this plan.
4. Fix or explicitly exclude invalid background JSON replies before treating
   whole-world outcomes as a quality comparison. Retain every repair/no-op and
   charge in evidence. Evaluate the changed prompt on a separate held-out set.
5. After the bounded-menu choices pass review, run a predeclared multi-seed,
   longer comparison with the same code, semantics, action space and budgets.
   Measure completed needs, missed opportunities, rejected/stale actions,
   spending, wait rate, confidence calibration and economic outcomes alongside
   cost and latency. Predeclare acceptance thresholds before looking at results.
6. Test a real external Hermes worker separately for registration, authorized
   observations, turn submission and exact replay; the current native-profile
   comparison does not substitute for that integration test.

# Jev through OpenRouter: implementation and acceptance

The requested branch is `JEV`, created from `f22a051b9a591cdebe238b483db094ec05da08e8`.
This implements the September 19 adoption plan: a bounded shopping/job-choice
policy, an OpenRouter Decisions transport, declared generative escalation,
scientific evidence, evaluation tools, and operator visibility. Existing run
profiles keep their original behavior. The deterministic engine owns all actions
and monetary effects.

## Delivery checklist

- [x] Create the requested branch and inspect the current integration contracts.
- [x] Typed questions/results, model identity checks, and secret-safe transport.
- [x] Pure observation-bound candidate compiler and equal-menu baseline.
- [x] Gateway admission, accounting, deadlines, retries, recording, and exact replay.
- [x] Runtime selection, explicit abstention/escalation, and unchanged background calls.
- [x] Recorded decision receipts tied to execution outcomes and public projections.
- [x] Versioned typed/hybrid research declaration with every provider and tariff bound.
- [x] Frozen-observation evaluation, calibration/cost/latency reports, and paired-world runner.
- [x] Small offline/live/hybrid profiles, private API-key setup, and operator documentation.
- [x] Focused failure/invariant/replay tests and repository verification gates.
- [x] Application smoke check and concrete whole-app testing handoff.

Live evidence is a separate acceptance surface: approximately 2,000 held-out
observations and ten paired seeds over thirty ticks were proposed in the review.
Implement that evaluation path and retain all exclusions; never claim the
model's quality, speed, or cost targets have passed based on fake responses.
The initial proposed limits are $5 for Jev and $25 for a declared comparator.
The key is currently absent from the local environment and ignored `.env`;
controlled HTTP fixtures must exercise the full integration before live testing.

## Frozen boundaries

- OpenRouter endpoint: `https://openrouter.ai/api/alpha/decisions`.
- Pilot model: `typesafe/jev-1.13`; record and check its resolved identity.
- `OPENROUTER_API_KEY` is backend-only; never record authorization headers.
- Each request contains one actor's authorized state and typed questions.
- Compile exact IDs, integer amounts, affordability, and compatible action bundles
  in code. The model selects supplied IDs; execution revalidates current state.
- Preserve historical cache keys and manifests. New typed requests use an explicit
  contract and strict evidence matching; replay needs no key or network.
- No invented in-character reasoning or model-driven belief update in matched arms.
- Abstention, missing confidence, quota exhaustion, malformed answers, stale menus,
  and escalation must remain visible and attributable.

## Evidence log

Implemented on `JEV`. Setup, commands, contracts and limitations are in
[the Jev operator guide](../jev.md). No live calls or claimed benchmark results.

Validation on September 19, 2026:

- Acceptance command: `python -m pytest -q tests/test_jev_contract.py tests/test_jev_gateway.py tests/test_jev_candidates.py tests/test_jev_runtime.py tests/test_jev_resilience.py tests/test_jev_integration.py tests/test_jev_studies.py tests/test_documentation.py tests/test_external_agent_gateway.py tests/test_research_export.py tests/test_prd_completion.py tests/test_recorded_replay_golden.py --basetemp C:/tmp/jev-acceptance-01`: **208 passed**.
- Compatibility command: `python -m pytest -q tests/test_review_gateways.py tests/test_provider_budget.py tests/test_policy_studies.py tests/test_world_os_workspace_projections.py tests/test_activity_projection.py tests/test_semantics8_projections_api.py tests/test_semantics8_projection_branches.py --basetemp C:/tmp/jev-regression-01`: **134 passed**.
- Final targeted rerun after the restart/cache fixes: `python -m pytest -q tests/test_jev_contract.py tests/test_jev_gateway.py tests/test_jev_candidates.py tests/test_jev_runtime.py tests/test_jev_resilience.py tests/test_jev_integration.py tests/test_jev_studies.py tests/test_provider_budget.py tests/test_recorded_replay_golden.py --basetemp C:/tmp/jev-final-core-01`: **119 passed**. Counts overlap the earlier runs.
- `npm test` in `dashboard`: **284 passed**.
- `npx playwright test tests/e2e/world-os-routes.spec.ts --grep 'bounded decision receipts' --workers=1`: **2 passed**, 1440px and 390px.
- `npm run typecheck`, `npm run licenses:check`, `npm audit --audit-level=high`, `npm run build`: passed; the build retained the existing large-chunk advisory.
- `python -m pip check`, `uvx pip-audit -r requirements.lock`, and `python run.py --verify-datasets config/data-manifest.yaml`: passed. Optional unpinned datasets remain labelled optional.
- Broad `compileall` exited successfully but could not traverse old ignored report-output directories. A separate `py_compile` pass over all **520 Git-visible Python source files** completed without errors.
- Browser smoke against the regenerated production bundle: offline run `5e52141fac` reached tick 3 and paused; **25 receipts** (18 menu selections, 7 outside-menu turns), zero browser-console errors, and no private candidate payload in the observer API.
- `run.py --config runs/jev-offline.yaml --preflight`: ready. The live equivalent correctly failed with the missing `OPENROUTER_API_KEY` message before any inference.

Python API tests emit the existing Starlette/httpx deprecation warning. Full
cross-platform Python coverage remains the CI shard gate; it was not represented
as one completed local full-suite run. The new dedicated CI job runs every Jev
test using controlled fixtures.

## Delivery boundaries

This is the complete bounded shopping/job pilot implementation. It preserves the
existing event and LLM-call evidence spine instead of introducing a redundant
decision table; full receipts stay private while observer views publish a summary.
The new research runner is a separate prospective contract, leaving v3 policy
studies intact. Its initial scope is fresh paired worlds with scripted background
cognition; it does not add saved-world recovery or a new study-launch UI.

The USD allowance is shared across declared study routes. Unknown physical calls
retain reservations. Interrupted studies retain partial evidence and cannot
resume/reset their allowance. The documented wall timeout is cooperative for
synchronous engine work. These are explicit pilot limits, not hidden completion
or quality claims.

Live acceptance is pending private key setup, account/credit readiness, and the
owner's whole-app test. Jev speed, cost, calibration and economic usefulness are
unmeasured until the prospective real-provider study is run.

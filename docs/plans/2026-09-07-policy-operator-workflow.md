# Policy studies in the local operator workspace

Status: implemented under W3/W4; committed-head CI is tracked on draft PR #82. The five-part research-city
goal remains active. This connects the executable policy studies and private
evidence delivered at `18edbe3` to the research interface. Goods and equities
remain equally primary.

## Researcher workflow

1. Choose a configured decision-policy comparison and review its models,
   sampling settings, independent source worlds and model draws per world.
   Use fresh seeds or explicit compatible saved-world selections.
2. Set a final horizon and original request/token/spend/time/storage caps.
   Validation checks inputs, configuration and resource estimates without
   contacting a provider. Display readiness as unchecked until execution.
3. Review the concrete draft and deliberately authorize its inference allowance.
   Launch consumes that allowance for preflight and all assigned cells. Repeated
   requests preserve the existing job; an HTTP disconnect does not relaunch it.
4. Inspect progress by unique cell, including model draw and saved phase. A
   verified pause retains overall pending eligibility. Resume binds the original
   job, context, code, configuration, progress and allowance; no replacement cap.
5. Compare both price domains after final verification. Aggregate complete model
   draws within each world before calculating world-paired effects. Show assigned,
   completed and eligible cells and world blocks, missing observations, excluded
   draws, uncertainty and execution age. Preserve null and negative findings.
6. Download private final or paused evidence through the existing reviewed-hash
   export flow. Relocated evidence remains readable without enabling execution
   or claiming it belongs to a newly launched operator job.

## Interface and authority contracts

- Add explicit policy comparison and working-view contracts. Legacy scripted
  contracts retain their meaning. Catalog/frame matching binds protocol as well
  as run, fork, selected study, result hash and current operator context.
- Use cell_key plus policy/model_replicate throughout projections, row identity,
  progress, measurements and exclusions. A seed/arm pair alone is insufficient.
- Project model names, policy keys, sampling, draw counts, original limits and
  verified usage through explicit allowlists. Configuration bodies, credentials,
  provider endpoints/headers, prompts, responses, local paths and reservation
  internals remain in private evidence. Unverified totals stay unavailable.
- Show physical calls and reported usage separately from encumbered allowance,
  unknown/unresolved usage and inherited source costs. Recorded preflight is
  historical evidence, not a claim of current provider availability.
- The operator policy catalog reads bounded owner-configured design files from
  a configured local root. Client requests select reviewed identities; they do
  not supply executable paths, credentials, arbitrary endpoints or commands.
- Reuse current run/fork/tick checks, CSRF, private/no-store responses, single-job
  ownership, durable supervisor claims and idempotent launch/resume. Check source
  and design identity again before dispatch. Normal browsing makes no model call.
- Expose the new launch capability only when a valid local design is available
  and the complete execution/recovery path is implemented. Preserve the existing
  G2/F2 workflow and its limits.

## Implementation order

1. Policy evidence projections, original allowance summaries and complete draw
   identity; integrate saved-study comparison/progress/export in the dashboard.
2. Bounded design catalog and strict provider-free request/draft validation,
   including source/model replication in storage and request estimates.
3. Reviewed launch, durable supervision and original-budget recovery in the
   existing job system, plus deliberately authorized UI controls.
4. Integration and browser verification through both price domains, followed by
   the committed build and required/full CI. The recorded private evidence and
   legacy replay contracts must remain independently readable.

## Owner configuration and request contract

Set `operator_research.policy_root` in the local server configuration, or use
the default `data/policies`. This directory is private and read only from the
interface. Its immediate `.json` files use exactly the same `policies` and
`tariffs` object as `python -m research.policy_studies --design`; see the
[live-policy CLI](2026-09-07-live-policy-studies.md#cli-workflow). Do not store
inline secrets. Provider credentials remain in the existing provider environment
or credential mechanism, outside the request and public review.

The interface scans at most 100 entries and returns at most 20 valid designs,
each at most 64 KiB with 2–4 policies and 1–4 declared tariffs. It rejects aliases,
unknown fields, inline secrets and unsupported routing. Catalog omissions use
bounded counts, never private exceptions or filenames. No provider is contacted.

`POST /api/v2/operator/research/drafts/validate` accepts a `preset: "POLICY"`
request with a reviewed `design: {id, sha256}`, either 1–5 distinct fresh seeds
or explicit checkpoint identities, and 1–3 distinct `model_replicates` labels.
All labels identify draws, not reproducible provider seeds. The operator keeps
the 14-agent/3-firm pilot profile. The horizon is at most day 30 and requires at
least three new days after a saved origin. Broader designs remain available
through the CLI.

Original caps are explicit: at most 5,000 physical calls, 10,000,000 tokens,
USD 5, 600 active seconds and 1,024 MiB. These are interface admission ceilings,
not recommended research budgets or cost forecasts. A planning estimate counts
every seed × policy × draw execution and its replay, including all saved-world
copies. It may reject a request below these ceilings. All caps and per-call
tariffs are frozen in the private draft and shown in the review.

The existing draft launch endpoint requires `approve_live_inference: true`
alongside its reviewed draft hash and idempotency key for policy studies. The
UI checkbox starts unchecked and binds the current run/fork/draft/hash; a
reload requires review again. Legacy scripted launch serialization is unchanged.
The supervisor repeats code, design, profile and source checks before dispatch.
Preflight has its own recorded charges within the same shared allowance.

Resume accepts only the original job's reviewed progress hash, compatibility
check hash and idempotency key. It accepts no new cap or provider configuration.
The original deliberate approval is retained in the private job claim. Repeated
launch/resume requests return the existing job. Imported archives remain readable
without creating or adopting an operator job.

The library binds distinct `operator-policy-study-comparison-v1` and
`operator-policy-working-study-v1` frames. Its draw filter changes execution and
measurement rows only; the declared paired estimate continues to use all assigned
draws. Execution coverage is calculated from actual cells and independent world
blocks, not synthetic rows used by the aggregation. Failed readiness therefore
shows zero worlds started while retaining its provider charges. Unknown usage
is unavailable in the UI until independently verified; a working pause has no
final price comparison.

## Acceptance

- Actual loopback HTTP studies from fresh and saved worlds; final, day-pause and
  phase-pause evidence. Multiple draws remain distinct after API projection,
  comparison, refresh, export and imported read-only viewing.
- Provider-free draft and evidence reads; original allowance retained across
  preflight, execution and resume. Include unknown usage, budget exhaustion,
  interrupted ownership, failed readiness, missing prices and exclusion cases.
- Reject stale design/draft/result/verification hashes, altered original sources,
  unauthorized or historical requests, changed contexts, duplicate launches,
  imported-budget execution and private-field leaks before provider dispatch.
- Browser coverage for draft review, both domains, model-draw evidence, pending
  status, allowance presentation, keyboard/mobile interaction, stale responses,
  private download and working controls. Inspect desktop/mobile rendered results.
- Use fresh short pytest roots and the 40 GiB admission floor. Do not modify
  tracked/unignored files while scientific pytest records code identities.

Controlled fixtures prove the implemented workflow. An external-provider
rehearsal requires its own reviewed model, tariff and bounded allowance; it is
not implied by private evidence import. Remaining city, society and W9 model
validation work continues under the original roadmap.

## Implementation evidence

Windows/Python 3.11.15 workflow and compatibility verification passed **116
tests** (877.53 s): policy operator execution, all six archive campaigns, legacy
study jobs, working jobs, checkpoint jobs and the study library. The dashboard
passed **245 unit tests** and **35 workspace browser checks**. After adding a
design-refresh control and clarifying recorded per-cell cost, all **3 policy
browser checks** passed again. Type checking and the production build passed.

The review used synthetic [desktop](../research/assets/policy-operator-desktop.png)
and [mobile](../research/assets/policy-operator-mobile.png) interface captures.
These demonstrate layout and accounting presentation; actual execution and
replay are covered by controlled loopback HTTP tests. Dependency/notice audits
passed, four pinned datasets verified, and two optional unpinned datasets remain
explicit. The existing Starlette, Vite chunk-size and console-color warnings
remain. Full Windows/version combinations, hosted integration and external paid
providers were not exercised by this slice.

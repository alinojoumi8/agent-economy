# Live decision policies in price studies

This extends W3 with equal goods/equity coverage. The CLI now supports fresh-world,
fixed-horizon policy comparisons under `research-study-v3`, with explicit launch
authorization and one shared declared provider allowance, including cooperative
day/phase pause and resume. The v1/v2 protocols, saved-world rules and existing
operator UI retain their previous capabilities. Saved-world policy changes,
operator launch/import and real provider readiness remain subsequent work. Controlled fixtures demonstrate the
execution and evidence path; no paid provider rehearsal is claimed.

## Implemented: shared completion reservations

`research/provider_budget.py` provides an exclusively created operational
SQLite ledger and the `research-provider-budget-v1` contract. The contract binds
one prospective study manifest, the gateway configuration hash, aggregate
physical completion/token/spend caps, and explicit provider/model tariffs.
Prices and allowances use integer nanodollars (1 USD = 1,000,000,000 units),
avoiding floating-point rounding at admission.

`Gateway(..., completion_guard=budget)` attaches it as a runtime dependency.
No ledger path or budget receipt is added to world configuration, scientific
tables, canonical event payloads or recorded replay. The original
`llm.gateway.BudgetExceeded` import remains supported. Recorded replay rejects
attachment of a live guard; scripted/mock adapters consume no live allowance.

Every direct HTTP adapter completion passes through the guard, including the
preflight JSON smoke, primary request, transport retry, JSON repair and
configured fallback. Model-catalog GETs are readiness requests, not completion
reservations. A denial propagates as a budget stop without an additional
completion, retry or fallback. Completed responses preceding a denied repair
remain in the existing world call log.

Before dispatch, a single SQLite transaction reserves:

- One call, never refunded even if a response is not received.
- The full declared maximum input tokens plus the requested output ceiling.
- Their cost at the declared input and output upper tariffs.

Reservations are shared across independent connections and processes. Opening
an existing ledger does not create it, replace it, increase its caps or reset
usage. A timed-out, cancelled or failed request retains its full token/cost
reservation. Abrupt process death leaves an unresolved reservation with the
same accounting effect. These reservations cannot be automatically released
on resume because absence of a response does not establish absence of a bill.

Successful responses release only the difference between their reservation and
explicit provider-reported usage. The adapters' historical token estimates
remain available to legacy gateway accounting, but cannot settle a research
reservation. OpenAI-compatible usage comes from both prompt/completion fields;
Anthropic input totals include cache reads and cache creation. Missing usage
retains the reservation. A declared tariff must cover all applicable input
prices, including cache writes; no cache discount is assumed.

Malformed or excessive reported usage records a breach and stops subsequent
dispatch across the shared ledger. Snapshots distinguish reported tokens,
their cost at declared tariffs (`usage_cost_nano_usd`), encumbered totals,
unresolved calls, unknown-usage calls and breaches.
No prompt, response body, raw error, credential or private model reasoning is
stored in this ledger. It is local accounting evidence, not a tamper-proof bill
or a provider invoice.

Admission currently supports direct OpenAI-compatible and Anthropic HTTP
adapters. CLI wrappers may hide additional model calls and are refused.
Network adapters cannot reuse the built-in scripted/mock names to escape
accounting. OpenAI request defaults are refused because they can override messages/model
or request multiple completions. Only the existing `max_tokens` and
`max_completion_tokens` output fields are admitted. Text input must fit a
UTF-8-size admission check with framing allowance; the entire declared input
ceiling is reserved regardless of this estimate.

The spend bound is conditional on the declared token/price contract. A remote
provider may report usage after exceeding that declaration or bill differently;
the software can stop further requests and retain evidence, but cannot undo
an already dispatched charge. Provider prices need current verification before
an actual live study. Tests use synthetic tariffs and local HTTP fixtures.

## Implemented: prospective policies and model replication

The v3 protocol preserves serialized v1/v2 defaults. Each arm binds its policy
family/version, observation/action interface,
prompt source hashes, provider/model/endpoint, sampling parameters, wake
cadence, communication policy and population assignment. A policy-only
treatment is meaningful and must not require a fictitious economic shock.
Retain shock treatments for G2/F2. Reject undeclared substitutions, mixed
request extras, hidden CLI inference and budget-driven changes in cognition.

World seeds and model replicates are different axes. Model replicates
are stochastic draws, not evidence of a deterministic provider seed. Keep all
declared cells, including exclusions. Pair arms within their common world;
aggregate replicates within a world before world-level uncertainty so repeated
model calls do not masquerade as independent economies. Keep inference
exploratory until a confirmatory design is separately implemented and checked.

Each policy currently declares one model for all roles that the common runtime
routes to inference. Peripheral population rules remain common to every arm;
this does not claim that every resident invokes an LLM. Multiple policy arms
may select different models or sampling temperatures. Mixed models within a
single policy, hidden routing overrides and CLI inference are refused.

Primary, repair and preflight temperatures are explicit and included in the
recorded cache identity. A live policy requires a response matching the existing
JSON/schema contract after repair. Failure pauses the affected world, retains
its calls and excludes the incomplete world block. The runtime's existing
grounding, narrative and action-feasibility rules still apply in every arm.

The initial executor and reader share limits of 512 assigned cells, 64 outcomes,
3,661 measurement days, and two million world/arm/outcome/bootstrap operations.
Model replicates are averaged only after every assigned draw in the arm/world
block is independently eligible. Missing prices exclude that domain's pair;
missing executions exclude the entire paired block.

## Implemented: supervised frozen execution and sealed evidence

The study supervisor exclusively creates one v2 ledger from the immutable
manifest before the first preflight completion. Named configuration bindings
share global caps and allow each worker only its assigned provider/model.
Every worker and preflight opens that ledger with the original contract and an
opaque cell scope. The existing disk/time worker limits remain. Never
put provider credentials, prompts or operational paths in public results.

Validate declared routes and provider readiness first. A bounded live
preflight uses the same ledger; its costs stay visible even when no scientific
world launches. Verify current pricing, request shape, configured model
availability and complete prompt/observation bindings before accepting a
paid launch. `--approve-live-inference` is required for execution; drafting,
validation and evidence reading make no provider calls.

At settlement, the supervisor seals the ledger and freezes its digest, scoped
usage and contract beside the attempt receipts. Existing connections cannot
dispatch or settle after sealing. Read-only evidence checks bind publication,
preflight, every assigned cell and scope, the ledger, source/replay databases,
initial conditions and independently recomputed prices. Altered reported prices
cannot enter the verified estimator. Roots come from the caller, and historical
reads use the original declared prompt identity without requiring current keys.
Exact
recorded replay spends zero new provider calls. Report successful logical
decisions separately from attempted physical completions, actual reported
usage separately from unresolved encumbrance, and inherited checkpoint costs
separately from the new study budget.

A hard supervisor failure kills its owned worker through a parent-death guard.
Unresolved requests remain charged in the original ledger; an interrupted batch
has no final publication and is not represented as a completed study. Missing
supervision or unfinished segments cannot resume. A
200 ms disk poll bounds ongoing supervision, but an individual write or final
evidence publication can exceed the disk threshold.

Saved-world policy changes use the explicit prospective transition below.
`continuation_config` continues to retain every economic and decision setting.
The original checkpoint and v1/v2 replay remain unchanged.

### Implemented: original-allowance day and phase recovery

Declare `preserve_and_resume` or `preserve_and_resume_phases` in the prospective
v3 study. Its working attempts use claim version 5. A pause freezes its source,
PRNG/phase position, recorded inputs, scoped usage and a digest of the complete
reservation prefix. Later invocations append to the same allowance; changing
earlier reservation ownership, settlement or amounts invalidates that history.
No previous reservation is refunded because a worker or supervisor disappeared.

The supervisor records contiguous invocation start/end/seal receipts. Each
invocation performs charged preflight checks in distinct scopes before advancing
the remaining assigned cells. Completed cells are skipped with their bytes
unchanged. A clean pause publishes `policy-working-progress-v1` with pending
eligibility and leaves the original ledger open. Resume validates the complete
lineage and the last closed allowance's exact bytes before a writable world open
or a new preflight. The study, code, configuration, input hashes, roots, assignments
and cumulative wall/disk/call/token/spend caps must still match.

Finalization seals the same allowance and publishes `policy-study-result-v2`.
The independent reader verifies every invocation's preflight, dispatch order,
reservation interval and worker receipts, then checks scientific source/replay
evidence and recomputes both price domains. A later failed preflight preserves
earlier completed evidence and excludes unfinished cells. Missing workers and
provider, budget or resource failures finalize with exclusions. A normal operator
interruption seals the allowance without publishing success; a hard crash retains
unresolved accounting and an unfinished journal, which cannot resume automatically.

This supports recovery from cooperative closed boundaries. An unknown interrupted
transaction cannot resume automatically. The existing operator/bundle workflow
does not yet advertise v3 capability.

### Implemented: declared policies from saved worlds

A v3 study may select admitted closed worlds as its common initial conditions.
All arms and model draws within a source world inherit the same original seed,
completed day, accounting, random states, schedules and recorded-input prefix.
The supplied common configuration must match the original source configuration;
operational output controls retain their existing exceptions.

Claim version 6 binds a `checkpoint-policy-transition-v1` receipt. It derives
the source and continuation configuration hashes, declared policy and policy
definition hash from the immutable study. The transition takes effect on the
first new day. Only the declared routing, sampling, response/accounting contract
and future arm interventions can differ. A changed seed, economic parameter,
transition or policy assignment fails before creating the child. The child must
use its assigned scope in the original shared allowance; attaching another ledger
or omitting it is refused. There is no general configuration patch operation.

Ordinary execution, day recovery and phase recovery use independent owned copies.
Each recorded replay starts from another copy of the admitted origin, reproduces
the new interval without provider calls, and records replay receipt version 3
with the transition hash. Verification checks the shared origin as well as the
cell's source/replay evidence, allowance history and measured prices. Relocated
evidence can be read without today's prompts or provider access. Old study and
attempt protocols retain their existing interpretation.

Inherited calls and costs remain visible in separate fields and do not consume
the new study allowance. Preflight and continuation requests consume that one
allowance across all invocations. Measurements use the declared new interval;
the existing equity endpoint may report an older price with its execution age.
Admission establishes the supplied state, not historical model fidelity or
economic realism. World-level pairing averages complete model replicates before
estimating effects for both goods and equities.

Storage admission includes the shared origin and independent source/replay
copies for every arm and model replicate. Runtime disk and wall limits still
apply; this estimate does not guarantee a bound on each individual write.

### CLI workflow

Create a private JSON design with `policies` and `tariffs`. Each policy entry has
`key`, `llm`, `temperature` (null for scripted), and optional
`repair_temperature`. Its `llm` declares the default route and direct HTTP
provider; every explicit role route must use that same target. Credential
references use environment-variable names, never inline secrets. Each tariff
declares `provider`, `model`, maximum input/output tokens and integer input/output
nanodollars per token. The first policy is the baseline.

```powershell
.\.venv\Scripts\python.exe -m research.policy_studies --config runs/price-lab-pilot.yaml --design <private-design.json> --output <study.json> --seeds 1 2 --model-replicates draw1 draw2 --ticks 3 --max-provider-calls <calls> --max-tokens <tokens> --max-spend-usd <approved-cap>
.\.venv\Scripts\python.exe -m research.study_runner <study.json> --config runs/price-lab-pilot.yaml --validate-only
# After reviewing the concrete policies, tariffs and total allowance:
.\.venv\Scripts\python.exe -m research.study_runner <study.json> --config runs/price-lab-pilot.yaml --approve-live-inference
.\.venv\Scripts\python.exe -m research.policy_results <results.json> --data-root data/studies --out-dir reports/out
```

For resumable execution, add `--pause-policy preserve_and_resume` to the draft
command (or `preserve_and_resume_phases` for phase recovery). Keep that original
study and configuration for each invocation:

```powershell
.\.venv\Scripts\python.exe -m research.study_runner <study.json> --config runs/price-lab-pilot.yaml --approve-live-inference --pause-after-ticks 1
.\.venv\Scripts\python.exe -m research.study_runner <study.json> --config runs/price-lab-pilot.yaml --resume-batch <original-batch-directory> --validate-only
.\.venv\Scripts\python.exe -m research.study_runner <study.json> --config runs/price-lab-pilot.yaml --resume-batch <original-batch-directory> --approve-live-inference
```

Phase studies can use `--pause-after-phase MORNING` instead of the tick limit.
Readiness checks on every invocation consume the original declared allowance;
resuming never creates a new budget. `--validate-only` makes no provider calls.
A successful pause prints status `paused` and exits 1 because execution remains
incomplete; it is not a finalized scientific result.

For saved-world policy comparisons, replace `--seeds` with explicit closed
checkpoints and use their original common configuration:

```powershell
.\.venv\Scripts\python.exe -m research.policy_studies --config <original-config.yaml> --design <private-design.json> --output <study.json> --checkpoint <source-1.db> --checkpoint <source-2.db> --input-root <source-root> --model-replicates draw1 draw2 --ticks 30 --pause-policy preserve_and_resume_phases --max-provider-calls <calls> --max-tokens <tokens> --max-spend-usd <approved-cap>
.\.venv\Scripts\python.exe -m research.study_runner <study.json> --config <original-config.yaml> --input-root <source-root> --validate-only
```

`--ticks` is the absolute final simulation day. Sources must share a completed
day and have distinct original seed/run identities. Policy change and measurement
start on the first new day, with no warmup under the old policy. Keep the same
input root for launch and resume. The approval and recovery commands above apply.
The draft rejects simultaneous seeds/checkpoints and never replaces an output.

Draft publication is exclusive and never replaces an existing file. Results are
local scientific artifacts containing operational paths; they are not a public
dashboard projection. `research.policy_results` is the v3 reader. The existing
operator library/bundle workflow continues to accept its supported v1/v2 formats.
Manual relocation of both evidence roots is supported by the v3 reader; an
integrated v3 archive import/export workflow is not yet advertised.

## Next slice: operator workflow and validation

Extend the reviewable draft with complete per-arm policies, model-replicate
counts, estimated request envelope, declared prices, shared caps and preflight
status. Bind the reviewed model/budget configuration to launch and resume.
Keep existing run/fork/tick/CSRF authority, idempotency, source selection and
local-only controls. Advertise live capability only after actual execution,
recovery, evidence and comparison are integrated.

Verification must include controlled HTTP successes, retries, repairs,
fallbacks, missing/invalid usage, concurrent reservations, cancellation,
supervisor death, original-budget resume and independent recorded replay.
Run both goods and equity studies under the same declared policy comparison.
Then complete an explicitly bounded real-provider preflight/rehearsal and
report profile/model, run IDs, exclusions and recorded costs. Controlled
fixtures do not establish live-provider readiness or economic realism.

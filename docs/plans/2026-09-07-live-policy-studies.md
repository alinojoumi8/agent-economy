# Live decision policies in price studies

This extends W3 with equal goods/equity coverage. The existing study runner
still admits **scripted, provider-free execution only**. Its v1/v2 protocols,
saved-world rules, replay behavior and operator capabilities remain unchanged.
This document records the implementation boundary and the next executable
slices; it is not a declaration that live comparisons are available.

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

## Next slice: prospective policy and replication contracts

Introduce a new study protocol rather than changing serialized v1/v2 defaults.
Each arm must bind its policy family/version, observation/action interface,
prompt source hashes, provider/model/endpoint, sampling parameters, wake
cadence, communication policy and population assignment. A policy-only
treatment is meaningful and must not require a fictitious economic shock.
Retain shock treatments for G2/F2. Reject undeclared substitutions, mixed
request extras, hidden CLI inference and budget-driven changes in cognition.

Declare world seeds and model replicates as different axes. Model replicates
are stochastic draws, not evidence of a deterministic provider seed. Keep all
declared cells, including exclusions. Pair arms within their common world;
aggregate replicates within a world before world-level uncertainty so repeated
model calls do not masquerade as independent economies. Keep inference
exploratory until a confirmatory design is separately implemented and checked.

## Next slice: supervisor and evidence integration

The study supervisor must exclusively create one ledger from the immutable
manifest before the first preflight completion. Every worker, preflight and
resumed segment opens that same ledger with its original contract and an
opaque cell/segment scope. Retain the existing disk/time worker limits. Never
put provider credentials, prompts or operational paths in public results.

Validate declared routes and provider readiness first. A bounded live
preflight uses the same ledger; its costs stay visible even when no scientific
world launches. Verify current pricing, request shape, configured model
availability and complete prompt/observation bindings before accepting a
paid launch. No paid launch is enabled by this infrastructure change.

At settlement, freeze budget snapshots and ledger evidence alongside attempt
receipts. Authenticate their lineage and contract during recovery/import;
changing, deleting or substituting the ledger must refuse resume. Exact
recorded replay spends zero new provider calls. Report successful logical
decisions separately from attempted physical completions, actual reported
usage separately from unresolved encumbrance, and inherited checkpoint costs
separately from the new study budget.

Saved-world policy changes require an explicit prospective configuration delta
in the new protocol. Do not relax `continuation_config` or silently substitute
a new model into an old source. The original checkpoint and v1/v2 replay must
remain byte-for-byte unchanged.

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

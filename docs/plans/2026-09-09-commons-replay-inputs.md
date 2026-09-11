# Ordered Commons inputs for draft Semantics 21

Status: implemented and locally validated for draft Semantics 21. The complete
six-day source/restart/replay/export case passes with all ten Commons operations
and interleaved control inputs. The [local participation correction](2026-09-09-open-population-boundary.md#local-commons-participation-and-observation)
and outside observation remain covered. Semantics 21 and migration 26 remain
unregistered for ordinary runs; this does not complete the broader W5 contract.

## Reproduced problem

The preserved pre-receipt two-day source writes a post, delivers it to a local reader, and records
an explicit read with memory/social effects. Recorded replay produces zero
explicit reads and zero `commons_entry_read` events. The exact comparator fails.
Both ledgers reconcile, provider cost is $0, and source bytes/mtime are unchanged.
The source, replay, counts and comparison are recorded in
`C:/Users/matri/.codex/tmp/ae-257553b2/commons-boundary-diagnostics.json`.

The prior `ExternalAgentService._restore_replay_commons_inputs` restores posts,
inferred feed groups and reactions. It omits reads, standalone profile creation,
follows, community creation/joining, moderation and appeals. A reaction's first
`created_tick` cannot recover later status changes. Feed and appeal do not have
complete command events. The Commons-before-control boolean cannot represent
interleaved inputs. The new Semantics-21 path uses ordered receipts instead;
the old routine remains the compatibility path for Semantics 1–20. The failed
draft source remains unchanged and is not upgraded or repaired.

## Implemented boundary

[The receipt journal](../../world/commons_journal.py) uses the existing `events`
table, kind `commons_operation_recorded`, phase `COMMONS`, receipt version 1.
Its fixed operation list is `ensure_profile`, `create_community`, `publish`,
`moderate`, `appeal`, `join_community`, `follow`, `react`, `feed` and `read`.
Receipts bind the actor, complete effective non-text arguments, immutable text
references and hashes, canonical result hash and preceding event ID. Private
bodies, biographies and moderation/appeal text remain in their owning rows.
No new table, schema registration or hash-contract version is introduced.

[The service wrapper](../../world/commons.py) records top-level commands within
their savepoint. Nested profile helpers do not create extra receipts; looking
up an existing profile is pure. Empty/repeated feeds retain separate commands.
A repeated read records the invocation but does not duplicate exposure, memory
or social effects. Direct services and World/replay use the same default Memory
binding in Semantics 21. Pure previews create no command or modeled effect.

Modeled Commons actions, new external actor arrivals and new external action
submissions require a committed day boundary. In-phase requests return a clear
409 retry error before effects. Reading an existing external idempotency receipt
remains allowed. Read-only feed preview remains available during a day.

[Ordered replay](../../world/commons_replay.py) merges Commons receipts with
arrival requests, participant acquire/release/queue/replace events and external
queued/rejected/stale submission events. It validates actors, source bindings,
argument references and event spans, then restores one transactional input
batch. Each command must reproduce the exact event IDs, payloads and result.
A later invalid input or result rolls back all earlier inputs in that batch.
Negative submissions retain evidence without becoming executable actions.

World restores inputs after FINALIZE as well as before the next day. This
preserves inputs after the final economic day without advancing another day;
restart or the next collection checks the already-restored prefix idempotently.
An arrival-created profile is recognized from matching immutable arrival and
creation evidence. Final mutable profile state cannot substitute for that proof.
Missing pre-receipt draft ordering, unknown versions and unsupported boundary
control events fail explicitly. Semantics 1–20 retain their existing path.

## Recording contract

Record each successful modeled command with a versioned ordered receipt, actor,
effective arguments, deterministic result evidence and exact input frontier.
Cover profiles actually created, communities, joining, follows, publishing,
reactions, feeds, reads, moderation and appeals. Empty feeds, repeated requests
and toggled reactions/follows must retain their true ordering. Nested profile
helpers must not create duplicate top-level commands. Pure previews create no
receipt or modeled effect.

Prefer the existing authoritative event spine if it can bind all required
evidence. Reference immutable content in its Commons row and bind its hash;
do not duplicate private bodies or biographies into generic events. Use a fixed
operation and argument allowlist. Reject changed references, future data and
unknown receipt versions. If an additional table is necessary, update the draft
schema/hash inventory and document earlier draft-fixture compatibility.

Define live admission during an active day. The current REST/MCP service can
run with `active_tick` set. Either require a committed between-day boundary
and return a clear retry response, or record/replay the exact phase frontier.
Never silently assign an in-phase write to the previous completed day.

## Replay and transaction contract

Restore command order together with external action submissions, actor arrival
requests and other interleaving control writes. Preserve event IDs and input
dependencies. Sorting all posts before all reactions, or choosing one side of
a Commons/control boolean, is insufficient.

Resolve consistent memory binding for direct service, World and replay. A
recorded explicit read must reproduce memory, exposure, belief and social-link
effects as applicable. Retain idempotency and factual delivery/read separation.

Validate the whole input batch before effects. An invalid later actor,
reference, frontier or result must leave no earlier commands/control receipts.
The new Commons savepoints already retain nested rollback; do not reintroduce
inner commits that discard the batch boundary. Passive outside authors/owners
are not the actors exercising a local capability.

Reject missing/ambiguous ordering in older pre-receipt Semantics-21 draft
sources with a precise compatibility error; do not invent input state from
their final tables. Keep Semantics 1–20 on their existing replay behavior.
The public version gate stays closed until current-version integration passes.

## Required evidence

- Actual source/restart/replay/export using every listed Commons operation,
  including a local person leaving and returning, and a retained outside author.
- Member-only ACLs and read-only previews that leave all modeled tables unchanged.
- Empty/repeated feeds; before/after-post delivery; reaction and follow toggles;
  factual and claimless reads; moderation/appeal; standalone profiles.
- Interleaved Commons, action submission and arrival/control writes; restart at
  committed day and supported phase boundaries; stable event IDs and references.
- Later invalid actor/reference/frontier/result and injected persistence failures
  that roll back the entire input batch. Corrupt sources must not be repaired.
- Full authoritative comparison and independent exported-row verification,
  unchanged closed source hashes/mtimes, balanced ledgers and zero provider calls.
- Legacy Commons, external gateway, Semantics-1/2 and golden replay checks.

A post/feed-only exact comparison does not satisfy this contract. Retain failed
diagnostics and prior source manifests. Preserve the frozen native campaign,
its original limits and the existing 40 GiB local test free-space floor. This
work does not close the wider participation inventory, W5, native verification,
full CI or W6–W9. Goods and equity price research remain equally prioritized.

## Executed evidence

[The dedicated suite](../../tests/test_population_commons_replay.py) passes
**16 cases in 116.21 seconds**. Its six-day source and fresh recorded replay
both restart after day-4 NIGHT_CLOSE, with person 23 departing on day 2 and
returning on day 5. An external actor arrives on day 2, and Commons commands
alternate with arrival, manual queue replacement and external submission inputs.
Final day-6 inputs are restored while the replay remains on day 6.

The fixture exercises all ten operations: 30 command receipts, seven posts,
eight feeds, three read invocations, member ACLs, claimless and factual reads,
reaction/follow toggles, moderation/appeal and an outside retained author.
The factual claim is part of the declared genesis fixture, not an observed
endogenous outcome. Outside preview leaves all modeled tables unchanged.
Negative cases cover changed versions, operations, arguments, text bindings,
future references, wrong viewers, frontier/results and four control families
inside a later-failing batch. Existing participation cases retain injected
persistence-failure and unavailable-actor rollback coverage.

The full comparator and authoritative hashes for Commons/events/memory/belief/
causal tables agree. Both ledgers reconcile, source bytes and mtime remain
unchanged, no SQLite sidecars remain and recorded provider cost is $0. Source
exports with row batches 13 and 128 produce the same bundle; both and the replay
export pass source-backed validation. Independent DuckDB readback compares all
fields of nine Commons tables after applying the manifest's existing 60-bit
pseudonym rule. Source and replay bundle IDs need not match because replay
metadata has its own provenance; equality is asserted through the replay
contract and the named authoritative table hashes.

| Receipt prefix under `tmp/` | Actual result | Preserved test directory / artifact bytes |
|---|---|---|
| `estate-finality-commons-ordered-sequence-r4` | 16 passed, 116.21 s | `C:/Users/matri/.codex/tmp/ae-2154e966` / 140,383,902 |
| `estate-finality-commons-ordered-compatibility` | 175 passed, 289.52 s | `C:/Users/matri/.codex/tmp/ae-0ada3c57` / 807,999,334 |
| `estate-finality-commons-ordered-legacy-smoke` | 120 passed, 206.80 s | `C:/Users/matri/.codex/tmp/ae-1af1c5e8` / 564,694,474 |

Counts overlap the dedicated suite. Every terminal runner exited 0 with its
1,147-file source snapshot unchanged and staging empty. The compatibility batch
covers population Commons/scenario/actions/services, legacy Commons and gateway,
golden replay and Semantics-1/2 source lifecycle. The second batch covers
participant control, retirement, Civic City, research export and PRD smoke.
One existing Starlette/httpx deprecation warning remains. The CI job includes
the new suite for Ubuntu/Windows and Python 3.11/3.12; only local Windows/Python
3.11 was executed here.

Preserved attempts include the initial 24-case pass, a nine-pass/one-failure
receipt from a wrong claim-reference column, an arrival-profile compatibility
failure and an independent export assertion that initially compared raw IDs to
the intentionally pseudonymous IDs. The last attempt had already passed exact
replay and all source-backed exports. The corrected fixture applies the declared
privacy rule; the exporter and privacy contract were not relaxed. Failed sources,
logs and tested source variants remain available alongside the final receipts.

Next: complete the participation/authority/commitment/economic/observation
inventory and the full declared source/restart/replay/export admission matrix.
Then run current-version integration/CI before opening the version gate. The
native 40-year horizon and full-prefix verification need their own prospective
recovery protocol; the original four-hour campaign remains a resource stop.

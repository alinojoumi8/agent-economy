# Buzz-derived architecture boundaries

This implementation translates four useful architectural patterns identified
while reviewing Buzz. It does not copy Buzz source code. Buzz is Apache-2.0;
Agent Economy remains MIT, so the adaptation is an independent implementation
against this repository's deterministic engine, ledger, replay, privacy, and
hosted-control-plane contracts.

## What was adapted

### One semantic activity projection

[`server/projections/activity.py`](../server/projections/activity.py) is the
single read-only adapter from caller-vetted public facts to activity cards. Its
small interface is `ActivityFact`, `project_activity`, and
`project_event_activity`. A card carries a semantic verb, object, outcome,
lifecycle, stage, bounded salience, and stable `kind`/`id`/`tick` evidence and
raw references.

Living Agents and the observer event projection both call this module. The
event adapter never reads or copies event payloads. Unknown event or fact kinds
produce an honest `record` card with `semantic_fallback: true`; they are not
given an invented business meaning.

Provider activity remains operational presence, not historical or economic
truth. A fact with `source: runtime` is available only when the caller asks for
the current view (`historical=False`). Historical projection drops it. No live
provider model, prompt, response, endpoint, credential, or error body becomes
part of an activity card.

This is a read-time projection. It adds no canonical event and changes no
stored replay hash.

### Explicit external-turn attendance

Simulation schema 20 adds the immutable `external_turn_attendance` table.
Semantics 14 records one row for each due first-class external wake:

| Attendance | Operational reason | Applied source | Applied policy |
|---|---|---|---|
| `submitted` | `submitted` | `external_submission` | `submitted_action_v1` |
| `missed` | `offline`, `deadline`, `dead_actor`, `revoked`, or `no_submission` | `deterministic_fallback` | `safe_do_nothing_v1` |

An explicitly submitted `do_nothing` remains submitted attendance. A missed
wake remains missed attendance even though the engine safely applies the same
deterministic no-op fallback. Operational availability and applied decision
policy are therefore queryable without pretending that absence was a choice.

The existing turn, submission, action envelope, event, and ledger paths remain
authoritative. Attendance is additive evidence, not another action executor.
Replay copies the source attendance identifiers and timestamps exactly. Stored
Semantics 1–13 sources create no attendance rows and retain their old output;
the replay process never updates the source database.

### Proposal-only Civic Builder support

[`builder_workspace/proposal_sink.py`](../builder_workspace/proposal_sink.py)
provides a narrow `ProposalOnlyActionSink`. It accepts only
`proposal.create`, validates an allowlisted change surface and fixed validation
evidence, creates a deterministic immutable ZIP bundle, writes it through the
existing hosted artifact-store interface, and verifies the stored bytes before
returning a receipt.

The bundle contains only these ordered entries:

- `manifest.json`
- `change.patch`
- `rationale.md`
- `invariants.json`
- `tests.json`
- `replay.json`
- `policy.json`

Validation evidence records an allowlisted check identifier, its fixed command,
status, exit code, and output digest. It does not store arbitrary commands or
raw command output. Proposal objects and receipts are frozen, bundle ZIP
timestamps are fixed, and an existing artifact key cannot be overwritten.

The sink has no handles for Git push or merge, deployment, networking, secrets,
the running engine, world loop, ledger, replay executor, or ActionExecutor. It
does not apply its patch. Normal validation, ActionExecutor, ledger, and human
or operator authority remain the only path to a later mutation.

There is no truthful Civic Builder runtime or mandate surface on this branch.
The remaining integration point is a future authenticated Builder facade that
turns an approved, bounded mandate into `ProposalRequest`, invokes this sink,
and presents `ProposalReceipt` for review. That facade must not gain an apply
operation or bypass the existing action-proposal and execution boundaries.

### Tamper-evident hosted audit chain

Hosted PostgreSQL migration 003 additively gives control-plane `audit_log` rows
a tenant-local sequence, previous-entry SHA-256, and canonical entry SHA-256.
Insertion takes a tenant-derived PostgreSQL transaction advisory lock, reads
the tenant head, and relies on a partial unique `(tenant_id, tenant_sequence)`
index as a second concurrency guard. All catalog audit writes use that one
append helper, including invitation issue and redemption flows.

[`hosted/audit_chain.py`](../hosted/audit_chain.py) defines the canonical
version-1 preimage and `verify_audit_chain`. Verify rows for exactly one tenant
in ascending `tenant_sequence` order. The verifier checks tenant isolation,
sequence continuity, previous-hash linkage, hash syntax, and the hash of the
canonical content.

Rows that existed before migration 003 retain null chain fields. The verifier
reports them as legacy; it does not manufacture authenticity for historical
rows. The insert trigger requires all new rows to be chained.

This applies only to hosted administrative/control-plane audit records. It does
not alter or replace the simulation event log. The chain detects modification,
middle deletion, reordering, or cross-tenant mixing within the records supplied
to the verifier. Detecting tail truncation requires comparison with a separately
retained chain head. It is not externally anchored and therefore is not
non-repudiation: an operator able to replace the database and every retained
chain head could construct a different internally consistent history. External
anchoring would be a separate operational feature.

## Deliberately not imported

- No Nostr relay or relay-based transport. Existing REST, MCP, hosted catalog,
  and event/projection boundaries remain authoritative.
- No ACP identity model or pooled cross-agent memory. Existing tenant, owner,
  connection, visibility, and persisted-memory rules remain authoritative.
- No randomized engine retry policy. Provider behavior may be operationally
  retried only under existing recorded policies; deterministic engine fallback
  and replay do not gain random retries.
- No use of presence as economic truth. Runtime provider presence is ephemeral;
  committed events, decisions, mechanics, and ledger entries remain the
  economic evidence.

## Compatibility and versioning

| Surface | Version gate | Historical behavior |
|---|---|---|
| Activity cards | None; additive read-time projection | Existing events and replay hashes are unchanged; historical views exclude runtime facts. |
| External attendance | Simulation schema 20 and `engine_semantics_version >= 14` | Semantics 1–13 produce no attendance rows; replay copies Semantics 14 source rows exactly. |
| Proposal sink | Proposal bundle format `agent-economy-proposal-bundle/v1` and allowlist `civic-builder-proposal-v1` | No simulation database or source run is changed. |
| Hosted audit | Hosted control-plane migration 003; canonical hash preimage version 1 | Existing audit rows remain explicitly legacy and unchained. Simulation schema and semantics are unaffected. |

Schema 20 is additive. Semantics 14 changes canonical output only for an
explicitly selected Semantics 14 run by adding attendance evidence; it preserves
the existing deterministic action fallback. Exact v1/v2 and later stored-source
replay remains gated by each source's recorded semantics.

## Operational verification

Run the focused interfaces:

```powershell
python -m pytest -q tests/test_activity_projection.py tests/test_living_agents_projection.py tests/test_semantics8_projection_branches.py
python -m pytest -q tests/test_external_agent_gateway.py
python -m pytest -q tests/test_semantics8_foundations.py tests/test_semantics8_migration_branches.py tests/test_compatibility_guards.py
python -m pytest -q tests/test_builder_proposal_sink.py tests/test_hosted_artifacts.py
python -m pytest -q tests/test_hosted_audit_chain.py
```

Run the repository smoke contract:

```powershell
python -m pytest -q tests/test_documentation.py tests/test_external_agent_gateway.py tests/test_research_export.py tests/test_prd_completion.py tests/test_recorded_replay_golden.py
```

Then run `git diff --check`. If dashboard files changed, also run its tests,
typecheck, and build; these architecture slices do not require a dashboard
change.

For an operational hosted-chain check, read all rows for one tenant with the
three chain fields and canonical audit fields, order chained rows by ascending
`tenant_sequence`, and pass only that tenant's rows to
`verify_audit_chain(rows, tenant_id=...)`. Treat `valid: false` as an incident.
Treat a nonzero `legacy_entries` count as an explicit pre-migration limitation,
not as verified history.

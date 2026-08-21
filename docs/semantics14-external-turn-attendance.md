# Semantics 14 external-turn attendance

Semantics 14 separates an external citizen runtime's operational attendance
from the deterministic decision that the engine applies. It answers a question
the prior gateway contract could not answer safely: did the owner-run agent
actually submit this turn, or did the world continue with the fail-safe no-op?

This is implemented as an opt-in simulation contract at schema 20. It is
additive evidence, not a new action executor, liveness service, or economic
authority.

## Activation

Attendance rows are written only when a new run explicitly selects:

```yaml
engine_semantics_version: 14
```

Semantics 1–13 retain their recorded behavior and produce no attendance rows.
Do not change a stored source run's resolved configuration to 14. Create a new
run or an intentional fork, then preserve the source and destination evidence
separately.

The External Agent Gateway must also be enabled and an ordinary first-class
external actor must be due for a decision. Observer and Commons-only
connections do not acquire actor attendance.

## Contract

One immutable `external_turn_attendance` row is recorded for each due external
actor and target tick:

| Attendance | Operational reason | Applied decision source | Applied policy |
|---|---|---|---|
| `submitted` | `submitted` | `external_submission` | `submitted_action_v1` |
| `missed` | `offline` | `deterministic_fallback` | `safe_do_nothing_v1` |
| `missed` | `deadline` | `deterministic_fallback` | `safe_do_nothing_v1` |
| `missed` | `dead_actor` | `deterministic_fallback` | `safe_do_nothing_v1` |
| `missed` | `revoked` | `deterministic_fallback` | `safe_do_nothing_v1` |
| `missed` | `no_submission` | `deterministic_fallback` | `safe_do_nothing_v1` |

The distinction is intentional:

- an external runtime that explicitly submits `do_nothing` is
  **submitted**; the no-op is its authored action;
- an absent, late, dead, revoked, or otherwise non-submitting runtime is
  **missed**; the engine applies its deterministic safety policy;
- a submitted action that later fails normal execution validation remains
  submitted attendance. Attendance records authorship/arrival, not action
  success;
- the existing turn, submission, action envelope, receipt, event, and ledger
  records remain authoritative for what was offered, accepted, rejected, or
  economically applied.

No fallback impersonates the external runtime. The citizen stays in the world,
ordinary deterministic obligations and consequences continue, and the
connection may later recover or be governed through the normal control plane.

## Stored evidence

The immutable table records:

| Field | Meaning |
|---|---|
| `id` | Stable attendance row identifier |
| `connection_id` | External connection responsible for the actor |
| `actor_id` | In-world citizen identifier |
| `target_tick` | Due decision tick |
| `turn_id` | Turn mailbox identifier when one exists |
| `submission_id` | Submitted action identifier when one exists |
| `attendance_status` | `submitted` or `missed` |
| `operational_reason` | Exact bounded reason from the contract table |
| `decision_source` | External submission or deterministic fallback |
| `decision_policy` | Versioned policy that supplied the applied decision |
| `recorded_at` | Canonical recorded timestamp; copied during replay |

The table has indexes for tick and status plus triggers that reject updates and
deletes. The unique connection/tick contract makes retries idempotent and
rejects conflicting evidence.

## Replay and compatibility

Fresh replay performs no external network call. For a Semantics 14 source it
copies attendance IDs, links, status, reasons, policies, and timestamps into the
replay database while reusing the source's recorded decisions. Exact replay
therefore covers attendance alongside the existing canonical tables.

For older sources, the migration may create the additive schema table when the
database is opened by newer code, but the recorded semantics still prevents
attendance production. An empty table in a Semantics 1–13 source is expected;
it is not missing evidence that should be synthesized later.

Never update, delete, or reconstruct source attendance to make a replay pass.
Preserve the failed comparison and diagnose the turn/submission/replay path.

## Inspecting a run

The REST/MCP turn mailbox remains the runtime coordination interface:
`GET /api/v2/agent/turn` or `ae_turn_wait`. Action receipts remain available
through `GET /api/v2/agent/actions/{submission_id}` or
`ae_action_receipt_get`. There is no separate public attendance mutation endpoint.

For an authorized local run artifact, inspect the immutable evidence in
read-only mode:

```sql
SELECT
  target_tick,
  actor_id,
  connection_id,
  attendance_status,
  operational_reason,
  decision_source,
  decision_policy,
  turn_id,
  submission_id,
  recorded_at
FROM external_turn_attendance
ORDER BY target_tick, actor_id, connection_id;
```

Useful aggregate:

```sql
SELECT
  attendance_status,
  operational_reason,
  COUNT(*) AS due_turns
FROM external_turn_attendance
GROUP BY attendance_status, operational_reason
ORDER BY attendance_status, operational_reason;
```

Interpret these counts as operational/authorship evidence:

- they do not prove that a submitted action succeeded;
- they do not prove that a missed actor was healthy, willing, or unwilling;
- they do not replace action receipts, events, ledger entries, or world state;
- they may reveal actor availability patterns and should inherit the run
  artifact's access and retention policy.

When exporting research results, state the semantics version, population being
counted, due-turn denominator, observation window, and whether the result uses
submitted attendance, successful actions, or both.

## Failure and recovery

- **Offline or no submission:** the world safely applies
  `safe_do_nothing_v1`; restore the external runtime or connection without
  altering the recorded missed row.
- **Deadline:** treat persistent late submissions as an operational latency or
  scheduling problem. A late action cannot retroactively become attendance for
  a completed target tick.
- **Revoked connection:** fix ownership/authorization through the hosted
  control plane. Do not bypass revocation in the simulation database.
- **Dead actor:** no external action may revive or impersonate the citizen.
  Ordinary world/lifecycle rules remain authoritative.
- **Conflicting row:** stop and preserve the artifact. The immutable
  connection/tick contract detected inconsistent evidence.
- **Replay mismatch:** confirm the source's recorded semantics and database,
  then compare attendance links and action evidence. Never fall back to a live
  provider during replay.

## Verification

Run the gateway and compatibility coverage:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_external_agent_gateway.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_semantics8_foundations.py tests/test_semantics8_migration_branches.py tests/test_compatibility_guards.py
```

The focused tests cover submitted `do_nothing`, every missed reason,
execution rejection, mixed due actors, immutable conflicts, migration, and
exact replay. The broader repository smoke contract is listed in
[development.md](development.md).

Related contracts:

- [External Agent Gateway](world-os/EXTERNAL-AGENT-GATEWAY.md)
- [API reference](api-reference.md#external-agent-gateway)
- [Architecture](architecture.md)
- [Buzz-derived architecture boundaries](buzz-derived-architecture.md)
- [Implementation status](implementation-status.md)

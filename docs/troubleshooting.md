# Troubleshooting

## Hosted readiness fails

Run the explicit redacted check and inspect only its named component results:

```powershell
python -m hosted.cli readiness --config config/hosted.example.yaml
```

Confirm PostgreSQL is reachable, both the web and supervisor logins are
`NOSUPERUSER NOBYPASSRLS`, their configured role names match `current_user`,
migrations are current, run/snapshot directories are absolute and separate,
and the scoped artifact identity can read bucket location and snapshot objects.
For Compose, inspect
`docker compose -f deploy/compose.yaml ps` and the `migrate` job first. CLI
failures intentionally print only the exception type so a DSN or object-store
credential cannot leak into logs.

## Hosted login or CSRF fails

Registration requires an unexpired, unrevoked invitation for the same tenant.
Login requires the tenant UUID as well as email/password. Mutations require the
secure session cookie, the CSRF cookie, and the matching `X-AE-CSRF` header.
HTTP 429 means the authentication throttle is active; respect `Retry-After`.
Do not weaken same-site/secure cookies or disclose whether a tenant/email exists.

If an active member is disabled, their sessions are revoked. Cross-tenant IDs
return 404 by design and should not be diagnosed by bypassing tenant scope.

## A hosted run reports lease loss

Treat lease loss as a fail-closed pause, not as permission to start a second
writer. Verify that only one supervisor instance owns the run, inspect the
catalog lease/recovery audit, and confirm PostgreSQL time/connectivity. On
restart, interrupted runs are recovered as paused and must be resumed through
the authenticated control route. Never edit a hosted SQLite world while a
supervisor handle may still own it.

## Hosted snapshot verification or restore fails

Verification checks immutable key, SHA-256, size, SQLite schema v11, and
`quick_check`. Preserve both the suspect object and catalog metadata. Fix
storage availability or permissions, then rerun `verify-snapshot`; never update
metadata to match a changed object. Restore refuses path traversal, tenant/run
mismatch, invalid SQLite, checksum drift, and replacement without `--replace`.
Use the last independently verified snapshot and retain the failed artifact for
incident review.

## Hosted load probe fails

Use at least two `--user TENANT_UUID,EMAIL,PASSWORD_ENV[,RUN_UUID]` arguments
with distinct tenant UUIDs, and confirm every named password environment
variable is set. Login failure aborts without printing credentials. Probe
failures record only operation, expected/actual status, latency, and bounded
body-validity metadata in the sanitized JSON receipt.

Use 2–32 users and no more than 10,000 total requests. The per-user count must
cover the full operation set at least once (three without run IDs, up to five
with run IDs); a receipt with no completed cross-tenant denial cannot pass.

Remote and plain-HTTP origins are rejected. For a local self-signed certificate,
use an `https://localhost`/loopback origin with `--allow-insecure-loopback`; the
flag intentionally fails for non-loopback hosts. Reduce `--concurrency` if the
service or development machine is saturated, but keep the recorded values and
failed receipt rather than silently rerunning until a result looks favorable.
Timeouts must be finite and between 1 and 120 seconds. Evidence-bearing
`--build-ref` values must be full lowercase Git object IDs; free-form labels,
paths, e-mail addresses, and secret-shaped strings are rejected before login.

## Hosted database login fails after editing `.env`

PostgreSQL initializes role passwords only when its data volume is first
created. Editing `POSTGRES_PASSWORD`, `APP_DATABASE_PASSWORD`, or
`SUPERVISOR_DATABASE_PASSWORD` does not rotate an existing volume. Restore the
last working values, then follow the profile-gated `rotate-database-passwords`
procedure in the operator runbook. Do not delete the volume or place passwords
on a command line.

## Provider preflight fails

Run the exact profile explicitly:

```powershell
python run.py --config runs/acceptance/production.yaml --preflight-live
```

Confirm that `MINIMAX_API_KEY` and `KIMI_API_KEY` exist in the environment and
that the reported catalogs contain `MiniMax-M3` and `kimi-for-coding`. Do not
print or commit credential values.

## The run says rate limited or overloaded

HTTP 429 and MiniMax HTTP 529 are waiting states, not failed ticks. Inspect
`rate_limit` in `/api/run/status` or the dashboard for the attempt count and
next retry. The fallback cooldown sequence is 15/30/60/120/300 seconds unless
the provider supplies `Retry-After`.

Pause or stop remains interruptible during cooldown. On restart, successful
responses from the active phase are reused and are not billed twice.

## The run paused for a provider failure

Non-overload failures are intentionally bounded. Preserve the database, fix or
wait out the provider issue, then resume with the original configuration and
run ID. Verify these invariants before continuing:

- completed `tick` did not advance;
- `active_tick` and `next_phase` identify the interrupted work;
- `COUNT(*) == COUNT(DISTINCT cache_key)` in `llm_calls`;
- ledger reconciliation still passes.

## The dashboard controls look stale

Refresh `/api/run/status`. It is authoritative for status, speed, active phase,
provider cooldown, and report path. Rebuild the committed bundle after changing
dashboard source:

```powershell
cd dashboard
npm test
npm run build
```

Acceptance evidence is heavier than ordinary run status. On a large database,
`/api/acceptance/status` can take seconds to refresh, but it runs off the server
event loop and is cached briefly so controls and WebSockets stay responsive.

## A database says `running` but no process exists

An operating-system kill or forced terminal termination can prevent Python's
`finally` cleanup from running. Confirm there is no matching simulation process
and no server holding the database, then preserve the file and change the run to
`paused` through an operator recovery procedure. Record an
`orphaned_run_recovered` event with the previous state, new state, and reason.

Normal Ctrl+C, dashboard Pause/Stop, provider interruption, and application
exceptions execute phase-aware cleanup automatically. Never mark a truly active
run paused from another process.

## A run is halted

Do not restart, step, change speed, stop, or inject shocks into a halted run.
Preserve the database and diagnostic events. Investigate reconciliation first;
fork a known-good checkpoint only when the source evidence has been retained.

## Exact replay fails

Use the original run ID and leave provider credentials irrelevant:

```powershell
python run.py --replay <RUN_ID>
```

Inspect the replay proof for the first differing canonical table. A missing
request-key response means the source run was incomplete or predates durable
request reuse; do not permit a network fallback.

## Acceptance evidence fails

Open the generated JSON receipt and inspect each failed gate. Common causes are
an unfinished horizon, unresolved Oracle predictions, absent reviewed phenomena
YAML, missing N=5 experiment evidence, or a shock effect occurring before its
shock. Regenerate with `--acceptance-report` only after the underlying evidence
exists; report regeneration cannot make a failed gate pass.

A legacy run without `belief_updated` history fails the rumor gate by design;
the evaluator will not assume a universal initial trust value. Fewer than all
six governed scheduled Oracle samples cannot satisfy the production p90 gate,
even when every available sample is below the limit.

## Oracle campaign receipt fails

Run `python run.py --oracle-calibration-report <MANIFEST>` and inspect
`excluded_runs` plus the six named checks in the JSON receipt. Do not replace a
predeclared run after observing its outcome. Common exclusions are a run/profile
hash mismatch, a SQLite `-wal` or `-shm` sidecar, scripted or otherwise
ineligible Oracle provenance, a fork/replay/participant source, an incomplete
six-question schedule, provider failures, or a stored config that differs from
the resolved checked-in profile. Shut down all processes using a database before
hashing it; the evaluator requires a finalized standalone source and will not
repair or migrate it.

The manifest cannot lower the floors below ten eligible unique runs and 60
resolved forecasts. It also fails unless both outcomes are present, nearest-rank
`scheduled_e2e_v1` p90 is strictly below 60 seconds, and aggregate Brier is
strictly below 0.25. Per-run exact replay is mandatory release evidence but is
created by `--oracle-campaign-run` and recomputed from the manifest-bound
companion database by the aggregate evaluator. Do not substitute a separately
invoked manual replay.

Exact verification canonicalizes every deterministic row and is deliberately
more memory-intensive than ordinary read-only reporting. Allow at least 6 GB of
free memory and do not launch manifest evaluations in parallel. The recorded
335-tick development benchmark peaked near 4.1 GB while comparing one source
and replay pair.

## I need per-call diagnostics

Normal INFO output reports run-level milestones, checkpoints, repairs, pauses,
and failures without printing one line for every successful agent call. Set
`AGENT_ECONOMY_LOG_LEVEL=DEBUG` to include successful request, replay-hit,
resume-hit, tick, and HTTP-start records. Prompts, responses, and credentials
remain outside operational logs.

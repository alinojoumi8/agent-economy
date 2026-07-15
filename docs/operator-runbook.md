# Operator runbook

## Safe startup

Run offline before using paid providers:

```powershell
python run.py --config runs/base.yaml --ticks 1
python -m pytest -q
```

Validate the production routes before a paid run:

```powershell
python run.py --config runs/acceptance/production.yaml --preflight-live
```

The production acceptance profile is uncapped but fully metered. Record the Git
commit, resolved profile, seed, population, provider/model catalog result, and
intended evidence gate before starting it.

## Optional R22 hosted deployment

Hosted mode is separate from `run.py --serve`. Copy deployment secrets into an
ignored environment file or a secret manager; at minimum set strong unique
`POSTGRES_PASSWORD`, `APP_DATABASE_PASSWORD`,
`SUPERVISOR_DATABASE_PASSWORD`, `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`,
`S3_ACCESS_KEY_ID`, and `S3_SECRET_ACCESS_KEY` values plus the exact HTTPS
public origin/host. The MinIO root identity is bootstrap-only; the S3 identity
is the bucket/prefix-scoped runtime identity and has no delete permission. The
three PostgreSQL passwords are passed separately from password-free base
conninfo and escaped by psycopg, so strong passwords may contain URI-reserved
characters. Never put any populated value in committed YAML.

Validate and build the reference stack before first start:

```powershell
docker compose -f deploy/compose.yaml config --quiet
docker compose -f deploy/compose.yaml build app migrate
docker compose -f deploy/compose.yaml up -d postgres minio minio-init migrate app caddy prometheus
docker compose -f deploy/compose.yaml ps
```

The migration job must complete successfully before the application starts.
Bootstrap the first tenant/admin once, supplying the password through an
environment variable or the CLI's hidden prompt:

```powershell
$env:AGENT_ECONOMY_BOOTSTRAP_PASSWORD = '<temporary-strong-password>'
docker compose -f deploy/compose.yaml run --rm `
  -e AGENT_ECONOMY_BOOTSTRAP_PASSWORD `
  bootstrap bootstrap --config /app/config/hosted.migrate.docker.yaml `
  --tenant-slug research --tenant-name 'Research' `
  --admin-email admin@example.com --admin-name 'Initial Admin'
Remove-Item Env:AGENT_ECONOMY_BOOTSTRAP_PASSWORD
```

Changing `.env` does not change passwords stored in an existing PostgreSQL
volume. Rotate all three database identities atomically with the profile-gated
job: keep the current `POSTGRES_PASSWORD`, place new distinct values in
`APP_DATABASE_PASSWORD` and `SUPERVISOR_DATABASE_PASSWORD`, and temporarily set
`AGENT_ECONOMY_NEW_POSTGRES_PASSWORD` to the new administrator password. Then:

```powershell
docker compose -f deploy/compose.yaml --profile ops run --rm rotate-database-passwords
# Replace POSTGRES_PASSWORD with the new administrator value and clear
# AGENT_ECONOMY_NEW_POSTGRES_PASSWORD in the protected environment file.
docker compose -f deploy/compose.yaml up -d --force-recreate app caddy
docker compose -f deploy/compose.yaml ps
```

Require readiness plus fresh administrator logins before retiring the old
secret-manager versions. The command rejects reused, short, or control-character
passwords and never prints them. If it fails, keep the old values and do not
recreate the app.

Verify `/health/live`, `/health/ready`, TLS, login, an observer invitation,
cross-tenant denial, one admin-controlled shared run, and Prometheus scraping.
The exact local image/Compose/load acceptance gate is recorded at `53081f2`, and
all six PR #19 jobs passed before merge. A public production deployment remains
pending; local evidence and this runbook are not a public certification claim.

Record a bounded authenticated load/isolation receipt with at least two users
from distinct tenants. Repeat `--user` as
`TENANT_UUID,EMAIL,PASSWORD_ENV[,RUN_UUID]`; the password itself must exist only
in the named environment variable:

```powershell
$env:LOAD_PASSWORD_A = '<tenant-a-password>'
$env:LOAD_PASSWORD_B = '<tenant-b-password>'
python -m hosted.load_test `
  --base-url https://economy.example.com `
  --user '<TENANT_A>,admin-a@example.com,LOAD_PASSWORD_A,<RUN_A>' `
  --user '<TENANT_B>,admin-b@example.com,LOAD_PASSWORD_B,<RUN_B>' `
  --requests-per-user 100 --concurrency 16 `
  --build-ref '<GIT_COMMIT>' `
  --output reports/out/hosted-load.json
Remove-Item Env:LOAD_PASSWORD_A,Env:LOAD_PASSWORD_B
```

The probe requires HTTPS, 2–32 distinct-tenant users, at most 10,000 total
requests, and concurrency of 1–256. `--requests-per-user` must cover every
configured operation at least once: three requests without run IDs and up to
five when both adjacent users include run IDs. It checks authenticated
own-scope reads plus cross-tenant 404 denial and cannot pass without a complete
isolation probe.
`--allow-insecure-loopback` disables certificate verification only for an HTTPS
loopback origin and is restricted to local smoke testing; it never permits
remote or plain-HTTP probes. The JSON receipt is sanitized: it contains no
passwords, cookies, email addresses, response bodies, or provider data. Retain a
fresh real-container receipt before accepting any new or public deployment; the
recorded `53081f2` receipt already satisfies the merged local R22 code gate.

Operational commands use the same image/CLI:

```powershell
docker compose -f deploy/compose.yaml run --rm app readiness --config /app/config/hosted.docker.yaml
docker compose -f deploy/compose.yaml run --rm app snapshot-all --config /app/config/hosted.docker.yaml
docker compose -f deploy/compose.yaml run --rm app verify-snapshot --config /app/config/hosted.docker.yaml --tenant-id <TENANT_UUID> --run-id <RUN_UUID>
docker compose -f deploy/compose.yaml run --rm app restore-snapshot --config /app/config/hosted.docker.yaml --tenant-id <TENANT_UUID> --run-id <RUN_UUID>
```

Restore refuses to overwrite an existing run unless `--replace` is explicit.
Keep the privileged migration DSN out of the serving container, preserve
PostgreSQL and object-store volumes together, and rehearse restore before
calling backups operational.

Run the free acceptance rehearsal and inspect its failed/live-only gates before
authorizing inference:

```powershell
python run.py --config runs/acceptance/rehearsal.yaml `
  --acceptance-run `
  --experiment-evidence reports/out/experiment_rumor_vs_control.json
```

The first pass intentionally lacks run-bound reviewed phenomena and uses only
scripted providers. After it reaches tick 365, copy the template, set its
top-level `run_id` to the exact rehearsal run, and document three distinct
phenomena from that run before regenerating the receipt:

```powershell
Copy-Item runs/acceptance/phenomena.template.yaml `
  reports/out/rehearsal_<RUN_ID>_phenomena.yaml
# Review and edit the copied YAML; do not reuse evidence from another run.
python run.py --acceptance-report <RUN_ID> `
  --experiment-evidence reports/out/experiment_rumor_vs_control.json `
  --phenomena-evidence reports/out/rehearsal_<RUN_ID>_phenomena.yaml
python run.py --replay <RUN_ID>
```

The completed scripted rehearsal should fail only `real_providers`. Reaching
the replay horizon is not exact-replay proof: retain the verifier output and
require `exact: true`, identical source/replay ticks and hashes, and
`differences: []` before marking replay complete.

## Capped research-validity pilot

The 30-tick pilot is the first paid gate. It targets the current depositors of
the largest bank, hides private reserve ratios from citizens, and caps recorded
spend at $25:

```powershell
python run.py --config runs/acceptance/pilot.yaml `
  --acceptance-run --serve --approve-live-inference
```

The served form keeps the observatory and `/api/acceptance/status` available
throughout the run. The authorized acceptance driver auto-starts and pauses
fail-closed if an exact Oracle checkpoint was passed without a persisted
prediction. Omit `--serve` only for unattended headless execution.

Do not start the full run unless this receipt passes its rumor, conversation,
belief-history, deposit-outflow, ledger, provider, latency, and spend gates. Do
not resume `f7c6238bf5`; it is preserved as a pre-fix diagnostic pilot.

## Oracle calibration campaign

This campaign measures Oracle latency and calibration; it is not the 365-day
whole-world acceptance run. The active `oracle-calibration-v2` commitment uses
fresh seeds 7311–7320. Its ten predeclared profiles keep background behavior
scripted and route only the Oracle to `kimi-for-coding-highspeed`, conservatively
metered at 3x the standard Kimi route under a $25 per-run cap. Do not replace a
seed or switch control/treatment arms after seeing outcomes. Treatment profiles
lock a one-person public precursor one tick before each forecast and the larger
depositor-targeted rumor one tick after it; control profiles contain neither.

First run the free 335-tick control and treatment rehearsals. They exercise the
same six governed questions and resolution horizon but are deliberately
ineligible for a live campaign receipt because their Oracle is scripted:

```powershell
python run.py --config runs/oracle/calibration-control-rehearsal.yaml `
  --acceptance-run
python run.py --config runs/oracle/calibration-rehearsal.yaml `
  --acceptance-run
```

This rehearsal is mechanics evidence, not a release receipt. The generic
acceptance command may return nonzero because scripted-provider provenance is
ineligible; inspect and resolve any other failed check. The live campaign
profiles below must still satisfy their stricter source checks.

The archived `oracle-calibration-v1-s7301` source completed tick 335 with six
resolved forecasts and valid provider provenance. Its replay nonetheless
diverged at the first arrival because staged genesis reset an uncheckpointed
persona RNG stream, and checkpoint inspection retained SQLite WAL/SHM sidecars.
It is diagnostic evidence only: do not resume it, copy it into a manifest, or
reuse its responses. The draft branch fixes for persona RNG restore,
standalone checkpoint finalization, replay target-tick enforcement, and
column-specific pre-dispatch RNG validation pass the focused and full gates.

Then preflight and execute each profile from
`v2-seed-7311-control.yaml` through `v2-seed-7320-rumor.yaml`. The first run is
shown; repeat it for the exact ten checked-in profiles only after seed 7311
produces an eligible exact source/replay receipt:

```powershell
python run.py --config runs/oracle/v2-seed-7311-control.yaml --preflight
python run.py --config runs/oracle/v2-seed-7311-control.yaml --preflight-live
python run.py --config runs/oracle/v2-seed-7311-control.yaml `
  --oracle-campaign-run --approve-live-inference
```

`--oracle-campaign-run` is the profile-specific source path: it runs the six
checkpoints, writes the report, finalizes the source SQLite database, replays it
offline, finalizes the replay database, verifies exact hashes/provenance, and
writes a source receipt plus a ready-to-copy manifest entry. It exits nonzero if
the source or companion replay is ineligible.

Start and resume these runs only from a completely clean Git worktree. The
exclusive sample claim binds `HEAD`, `HEAD^{tree}`, and the canonical
`data/runs` location before genesis. Claim and initialized-state files are
fsynced as temporary artifacts and atomically published into no-clobber slots.
The command holds one OS-backed per-seed execution lock from initialization
through source/replay receipt publication; a concurrent resume exits before it
can dispatch, and an exited or crashed process releases the lock automatically.

Genesis is built under a unique temporary directory, finalized, and validated
as reconciled tick-0 state with zero model calls. It is then atomically
hard-linked through canonical pending and final no-clobber slots. A valid pending
genesis resumes without rebuilding. A partial/corrupt pending publication is
quarantined and only the deterministic zero-call genesis is rebuilt; a missing
database after initialization or a partial final database still fails closed.
Source and replay databases must both remain directly under canonical
`data/runs`.

The replay execution receipt records every consumed logical source call, its
digest, exact-key versus compatibility-fallback counts, and live-dispatch count;
release evidence requires complete one-time consumption, zero fallback, and zero
dispatch. Every required checkpoint is independently quick-checked, matched to
the full schema, bound to the source run/config/tick and valid engine/lifecycle
PRNG state, then hashed into the replay and source receipts. All persisted model
calls are audited globally: only the six scheduled governed Oracle sessions may
use the pinned live Kimi route. Claims, markers, replay receipts, source receipts,
and final campaign receipts are immutable no-clobber publications; an identical
rerun may reuse an existing receipt, while any differing artifact fails.

These controls are strong local accident/tamper evidence only. They are not an
administrator-proof attestation: an administrator who can rewrite the code,
databases, claims, and receipts can forge a new internally consistent local
package. Public release evidence **requires** independent external signing or a
separately administered append-only transparency log; the local CLI receipt
alone is insufficient for that claim.

The campaign command does the offline replay itself; do not invoke a separate
manual `--replay` and substitute it into the corpus. After each command exits,
confirm the emitted source receipt reports finalized source/replay databases and
no `-wal` or `-shm` sidecar. Copy
`runs/oracle/manifest-v2.template.yaml` to a run-specific evidence manifest and
replace its ten placeholders with the exact manifest entries emitted by the
source receipts, then evaluate it:

```powershell
Copy-Item runs/oracle/manifest-v2.template.yaml runs/oracle/manifest-v2.yaml
python run.py --oracle-calibration-report runs/oracle/manifest-v2.yaml
```

The command reads disposable copies rather than opening the sources directly,
never scans a directory for candidates, recomputes every companion replay proof,
and writes deterministic JSON and Markdown receipts under `reports/out`. A
release PASS requires all ten runs to remain eligible, at least 60 resolved
forecasts spanning outcomes 0 and 1,
nearest-rank `scheduled_e2e_v1` p90 strictly below 60,000 ms, aggregate Brier
strictly below the fixed p=0.5 baseline of 0.25, and unchanged source/profile
hashes. Any excluded run fails the complete-manifest gate.

Run aggregate verification serially on a machine with at least 6 GB of free
memory. A measured 335-tick scripted source contained 129,764 events and 31,880
model-call rows in a roughly 0.48 GB database; its full exact-table proof took
about 136 seconds and peaked near 4.1 GB working set on the development machine.
The evaluator releases each pair before opening the next, but parallel campaign
verification is not the supported operator path.

## Production acceptance

Start a fresh acceptance run only with explicit live-inference authorization:

```powershell
python run.py --config runs/acceptance/production.yaml `
  --acceptance-run --serve --approve-live-inference `
  --experiment-evidence reports/out/experiment_rumor_vs_control.json `
  --phenomena-evidence reports/out/<reviewed-phenomena>.yaml
```

The driver runs to scheduled Oracle checkpoints and then the configured
365-tick horizon. It schedules six questions and requires all six persisted
`scheduled_e2e_v1` latency samples. Each sample starts before Oracle planning,
ends after the forecast contract is validated, and is bound to the exact
prediction, campaign key, question, and tick. Manual calls cannot satisfy the
gate; a missing, dangling, malformed, or duplicate completion reference marks
the checkpoint invalid. The profile is uncapped for runtime continuity but has a
separate $200 efficiency completion gate. On success it writes the complete
HTML report plus JSON and Markdown acceptance receipts.

A passing acceptance receipt is not an exact-replay receipt. After the source
run closes, execute `python run.py --replay <RUN_ID>`, retain the companion
database and verifier output, and require `exact: true`, identical source/replay
ticks and hashes, and `differences: []`.

The production profile starts with exactly 100 living agents: 63 sampled
citizens plus engine-owned institutional and health-economy actors. The
population gate counts living agents, while deceased rows remain preserved for
lineage and replay as stable-population replacements arrive.

Copy `runs/acceptance/phenomena.template.yaml` to a run-specific reviewed file,
set its top-level `run_id` to the exact reviewed run, and replace the pending
examples with phenomena visible in that run's persisted metrics. Evidence for a
different run fails closed even when its metric direction happens to match.

During a run, `GET /api/acceptance/status` and the dashboard show completed
gates, actual/projected spend, Oracle sample count, shock traces, and rumor
window evidence. They also show the exact checkpoint schedule, next scheduled
question, persisted checkpoint result, and any missed checkpoint that stopped
the run. The status endpoint evaluates large databases off the server
event loop and may return evidence cached for up to two seconds. Once a final
receipt exists for the exact run ID and completed tick, the endpoint returns
that artifact so experiment and reviewed-phenomena gates remain visible.

## Cooldown, pause, and resume

HTTP 429 throttling and explicit provider overloads such as MiniMax HTTP 529
enter one provider-wide cooldown. The dashboard/status surface shows provider,
attempt count, remaining cooldown, and next retry. The run waits until recovery
or operator stop.

Other continuing provider failures use bounded retries and then pause cleanly.
`run_meta.tick` remains the last fully completed tick; `active_tick` and
`next_phase` identify the exact work to resume. Successful LLM responses are
already durable and are reused by request key.

Resume a stored production acceptance run with its original profile:

```powershell
python run.py --config runs/acceptance/production.yaml `
  --resume <RUN_ID> --acceptance-run --approve-live-inference `
  --experiment-evidence reports/out/experiment_rumor_vs_control.json `
  --phenomena-evidence reports/out/<reviewed-phenomena>.yaml
```

Do not replace or edit a partial database. Preserve it and resume it. Legacy
databases with ambiguous partial-tick semantics are marked `legacy_partial` and
must be treated explicitly rather than silently advanced.

## Dashboard controls

- **Run** starts or resumes continuous ticks.
- **Pause** interrupts a provider cooldown or requests a safe phase pause.
- **Step** executes one tick and leaves the run paused.
- **Speed** changes wall-clock delay only; status is authoritative after refresh.
- **Stop + report** finishes the current run and generates a report.

A reported run can be reopened through Run or Step; the previous report path is
cleared and a later stop generates a fresh report. A `halted` run cannot be
mutated because halt represents an invariant failure requiring investigation.

## Participant sandbox

Participant mode is a separate provider-free extension and is never enabled in
an acceptance profile:

```powershell
python run.py --config runs/participant.yaml
```

At a completed-day boundary, open a living citizen, take control, and queue one
action for the next day. Continuous **Run** is disabled; **Step** remains locked
until an explicit action (including **Do nothing**) is queued. The server owns
all hidden entity IDs, validates the command against the citizen's current
role-scoped action catalogue, then sends it through the normal action executor
and double-entry ledger. Control and action records survive restart, replay
without live input, appear as paginated history in the citizen inspector, and
release automatically if the citizen dies.

## Reports and exact replay

Regenerate a report from a stored run:

```powershell
python run.py --report <RUN_ID>
```

The HTML file is the canonical standalone report. Markdown is its
reviewer-oriented companion.

Rebuild a run without provider calls and verify canonical table digests:

```powershell
python run.py --replay <RUN_ID>
```

Replay re-asks persisted Oracle questions at their original ticks. Historical
prompt changes use the source call's semantic identity and copy its original
request and cache key. A missing stored response fails closed; replay never
falls back to a live provider.

## Experiments and acceptance-only evaluation

```powershell
python run.py --experiment runs/experiments/rumor_vs_control.yaml
python run.py --acceptance-report <RUN_ID> `
  --experiment-evidence reports/out/experiment_rumor_vs_control.json `
  --phenomena-evidence reports/out/<reviewed-phenomena>.yaml
```

The first command creates isolated treatment/control worlds. The second derives
an evidence receipt from persisted run data without advancing the simulation.

## Evidence retention

For a release candidate, retain:

1. `data/runs/<run-id>.db` and its latest checkpoint;
2. the finalized companion replay database and captured exact-verifier output;
3. the HTML report and JSON/Markdown acceptance receipts;
4. the experiment JSON/Markdown/HTML artifacts;
5. the reviewed phenomena YAML and shock traces;
6. the exact Git commit, resolved profile, and provider preflight result.

Never call a provider pause, partial report, failed replay, or incomplete
evidence package a successful acceptance.

Keep the release pull request draft until the v2 Oracle campaign, capped
30-day rumor pilot, 365-day/$200 acceptance run, and final
provenance/license/dependency/secret audit all pass. Merging, tagging,
publication, and public deployment require separate authorization.

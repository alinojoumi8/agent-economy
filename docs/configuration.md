# Configuration and providers

## Profile inheritance

Run profiles are YAML. `extends` is resolved relative to the current profile and
nested mappings are merged. The fully resolved configuration and seed are saved
in `run_meta`, so a database remains self-describing.

| Profile | Purpose | Network/cost |
|---|---|---|
| `runs/base.yaml` | Default offline development world | None |
| `runs/production.yaml` | Approx. 100-agent MiniMax/Kimi runtime | Live inference |
| `runs/acceptance/rehearsal.yaml` | Free 365-tick acceptance rehearsal | None |
| `runs/acceptance/pilot.yaml` | Bounded 30-tick rumor pilot | Live, capped at $25 |
| `runs/acceptance/production.yaml` | Full 365-tick acceptance | Live, uncapped policy plus $200 efficiency gate |
| `runs/oracle/calibration-control-rehearsal.yaml`, `calibration-rehearsal.yaml` | Free 335-tick control/treatment Oracle schedule rehearsals | None; ineligible for campaign receipt |
| `runs/oracle/v3-seed-7321-control.yaml` … `v3-seed-7330-rumor.yaml` | Fixed v3 Oracle calibration corpus | Scripted background, live `kimi-for-coding-highspeed` Oracle, conservative 3x metering, capped at $25 per run |
| `runs/experiments/rumor_vs_control.yaml` | Five-seed treatment/control study | None by default |
| `runs/r21-real-us.yaml` | Pinned SCF/SUSB calibrated genesis | None |
| `config/hosted.example.yaml` | R22 filesystem-backed development control plane | PostgreSQL |
| `config/hosted.docker.yaml` | R22 Compose application service | PostgreSQL + S3-compatible storage |

Profiles never silently change provider, model, endpoint, or credential type.

## Environment variables

Secrets belong in the ignored `.env` file or process environment.

| Variable | Purpose |
|---|---|
| `MINIMAX_API_KEY` | MiniMax Token Plan route in production profiles |
| `KIMI_API_KEY` | Kimi Code membership route in production profiles |
| `ANTHROPIC_API_KEY` | Optional custom Anthropic route |
| `AGENT_ECONOMY_LOG_LEVEL` | Python operational log threshold; default `INFO` |
| `AGENT_ECONOMY_HOSTED_CONFIG` | Optional default path for `python -m hosted.cli` |
| `AGENT_ECONOMY_HOSTED_DATABASE_URL`, `AGENT_ECONOMY_HOSTED_DATABASE_PASSWORD` | Password-free hosted web PostgreSQL conninfo plus its separately injected password |
| `AGENT_ECONOMY_HOSTED_SUPERVISOR_DATABASE_URL`, `AGENT_ECONOMY_HOSTED_SUPERVISOR_DATABASE_PASSWORD` | Password-free restart/lease supervisor conninfo plus its separate password |
| `AGENT_ECONOMY_HOSTED_MIGRATION_DATABASE_URL`, `AGENT_ECONOMY_HOSTED_MIGRATION_DATABASE_PASSWORD` | Password-free migration-only administrator conninfo plus its separate password |
| `AGENT_ECONOMY_PUBLIC_BASE_URL` | Exact external HTTPS origin for hosted mode |
| `AGENT_ECONOMY_S3_ENDPOINT_URL` | S3/MinIO endpoint used by the hosted artifact adapter |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | S3-compatible artifact credentials |
| `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | Reference Compose MinIO bootstrap identity; never passed to the app |
| `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | Reference Compose bucket/prefix-scoped runtime snapshot identity |
| `AGENT_ECONOMY_BOOTSTRAP_PASSWORD` | One-time initial hosted administrator password |
| `AGENT_ECONOMY_NEW_POSTGRES_PASSWORD` | Temporary new PostgreSQL administrator password used only by the profile-gated rotation job |

Kimi Code membership keys use `https://api.kimi.com/coding/v1` and the
`kimi-for-coding` alias. They are not interchangeable with Moonshot platform
keys. Never put populated values in YAML, docs, reports, issues, or commits.

## Core world settings

| Key | Meaning |
|---|---|
| `seed` | World, persona, targeting, and lifecycle reproducibility |
| `engine_semantics_version` | Runtime compatibility contract; maintained profiles use `7` |
| `population.size` | Sampled citizen count; institutional/founder agents are added |
| `population.baseline_citizens_core` | Persisted semantics-7 opt-in that pins non-regional baseline citizens and later arrivals to the fully scheduled core tier |
| `banks`, `firms`, `exchange` | Deterministic banking, production, and market parameters |
| `central_bank` | Policy target, neutral rate, and step bounds |
| `lifecycle`, `government`, `vc`, `health` | Optional P1 systems |
| `behavior`, `conversations` | Wake cadence, run threshold, and social volume |
| `checkpoint_every`, `checkpoint_dir` | Recovery cadence and storage |
| `speed_delay_s` | Wall-clock pause between ticks; does not change simulation time |
| `outlets`, `shocks` | Information institutions and scheduled interventions |

`runs/production.yaml` samples 63 citizens. Maintained semantics 7 adds the
engine-owned institutional and health-economy actors, producing exactly 100
living agents at genesis. Acceptance evaluates the living population; deceased
rows remain available for historical and replay evidence without inflating that
gate.

Maintained non-regional profiles also persist
`population.baseline_citizens_core: true`. Under semantics 7 this makes baseline
citizens, health founders, and later arrivals fully scheduled core agents, which
is required for household rumor responses and other autonomous decisions. The
marker is ignored by semantics 1–6 and by an enabled regional R19 living world;
an older markerless semantics-7 database retains its historical peripheral tier
assignment during replay. Do not add the marker to a stored source config unless
creating an explicit new run or fork.

Money keys ending in `_cents` use integer cents. Rate keys ending in `_bps` use
basis points. One tick is one simulated day.

## R21 real-U.S. initialization

The default is `calibration.mode: synthetic`. Opt in only with pinned verified
supports:

```yaml
engine_semantics_version: 7
dataset_manifest: config/data-manifest.yaml
calibration:
  mode: real_us
  household_dataset_key: federal-reserve-scf
  firm_dataset_key: census-susb
  max_initial_firm_employees: 50
  minimum_wage_per_interval_cents: 50000
  maximum_wage_per_interval_cents: 5000000
```

Fresh runs verify and ingest the manifest before genesis. Replays ignore that
path and use the source run's recorded targets. `real_us` changes initialization
only: SCF income/work-status/liquid-holding/total-net-worth draws and SUSB
headcounts are applied to fictional personas and firms through dedicated
seed-derived PRNG streams. `LIQ` funds deposits; `NETWORTH` remains an
engine-owned off-ledger calibration baseline visible in agent provenance.
Missing supports, wrong adapter versions, malformed values, or non-verified
manifest rows fail closed.

## R22 hosted service configuration

Hosted configuration is independent of run-profile inheritance. It rejects
unknown keys and secret values embedded directly in YAML: files name the
environment variables that contain the PostgreSQL DSN and object-store
credentials. `enabled: false` in `config/hosted.example.yaml` is the safe
development default.

```yaml
enabled: true
public_base_url: ${AGENT_ECONOMY_PUBLIC_BASE_URL}
session_cookie_name: __Host-ae_session
session_ttl_seconds: 43200
database:
  dsn_env: AGENT_ECONOMY_HOSTED_DATABASE_URL
  password_env: AGENT_ECONOMY_HOSTED_DATABASE_PASSWORD
  runtime_role: agent_economy_app
  supervisor_dsn_env: AGENT_ECONOMY_HOSTED_SUPERVISOR_DATABASE_URL
  supervisor_password_env: AGENT_ECONOMY_HOSTED_SUPERVISOR_DATABASE_PASSWORD
  supervisor_role: agent_economy_supervisor
  connect_timeout_seconds: 10
  pool_min_size: 1
  pool_max_size: 10
artifacts:
  backend: s3
  bucket: agent-economy-runs
  prefix: v1
  endpoint_url_env: AGENT_ECONOMY_S3_ENDPOINT_URL
  region: us-east-1
  access_key_env: AWS_ACCESS_KEY_ID
  secret_key_env: AWS_SECRET_ACCESS_KEY
runtime:
  run_directory: /var/lib/agent-economy/runs
  snapshot_directory: /var/lib/agent-economy/snapshots
  writer_lease_seconds: 30
  snapshot_interval_ticks: 5
  shutdown_grace_seconds: 30
```

`writer_lease_seconds` belongs under `runtime`; the database mapping instead
accepts connection timeout, pool bounds, migration advisory-lock key, and the
runtime and supervisor roles. Both must be `NOSUPERUSER NOBYPASSRLS`; only the
supervisor role receives restart run-discovery capability. Base conninfo and
passwords are separate so psycopg can escape reserved characters safely. Use a
privileged DSN only for the explicit migration command, never for serving.

Filesystem artifacts require an absolute `artifacts.root` distinct from the
run directory. S3 artifacts require a valid bucket, region, absolute HTTP(S)
endpoint, and environment-sourced credentials. Snapshot and run directories
must be absolute and distinct. Local simulation profiles and
`engine_semantics_version` are unaffected by hosted configuration.

### Hosted load-probe inputs

`python -m hosted.load_test` does not read passwords from arguments or files.
Each repeated `--user` value is
`TENANT_UUID,EMAIL,PASSWORD_ENV[,RUN_UUID]`, and the named environment variable
must be populated in the invoking process. Between 2 and 32 distinct tenant
UUIDs are required, total scheduled requests cannot exceed 10,000, and every
configured operation must run at least once: a minimum of three requests per
user without run IDs and up to five when run IDs are supplied.
`--requests-per-user` defaults to 40, `--concurrency` accepts 1–256 (default
16), `--timeout-seconds` accepts finite values from 1 through 120 (default 10),
and `--output` writes the sanitized JSON receipt atomically. When supplied,
`--build-ref` must be a full lowercase 40- or 64-character Git object ID. The base URL must
be HTTPS; `--allow-insecure-loopback` is only a local certificate-verification
escape hatch for `localhost`, `127.0.0.1`, or `::1`.

## Information and beliefs

New production/base/acceptance profiles use:

```yaml
engine_semantics_version: 7
information:
  citizen_bank_visibility: public_status
beliefs:
  audit_history: true
  enforce_reserved_ranges: true
```

`citizen_bank_visibility` accepts:

- `public_status`: citizens/founders see bank name and public status only;
- `full_balance_sheet`: exposes reserve ratios and exists for intentional
  scenarios and legacy replay.

Reserved ranges are `trust:bank:*` `[0,1]`, `sentiment` `[-1,1]`, and
`inflation_expectation` `[-0.05,0.25]`. Finite out-of-range model output is
clamped and audited; non-finite output is rejected.

## Provider routing and failure policy

`runs/production.yaml` routes citizens/founders to `MiniMax-M3` and
institutional roles plus the Oracle to Kimi's `kimi-for-coding`. Conversation
and memory purposes inherit the agent's role route.

Every call passes through the gateway. Before a live run:

```powershell
python run.py --config runs/production.yaml --preflight-live
```

Readiness validates environment variables, endpoints, and model catalogs before
genesis. Rate limits/overload enter an interruptible provider-wide cooldown.
Other continuing failures use bounded retries, persist diagnostics, reconcile,
checkpoint the phase cursor, and pause. Invalid JSON receives one metered repair
attempt. There is no silent fallback to scripted behavior.

## Budget and acceptance settings

`budget.cap_usd` controls the runtime governor. Capped profiles degrade at
60/80/95% of their world budget by reducing conversations, stretching cadence,
and limiting calls to institutional roles, then pause at 100%. `null` disables
that hard cap while spend remains metered.

The `acceptance` block is evidence policy rather than call authorization:

- `min_ticks`, `min_agents`, `max_agents`;
- `max_spend_usd` and independent `efficiency_target_usd`;
- `oracle_p90_ms`, `oracle_min_latency_samples`, and `oracle_latency_source`;
- `oracle_campaign_id` plus its positive integer `oracle_campaign_version`;
- `oracle_questions` with exact scheduled ticks, unique `campaign_key` values,
  bounded horizons, and expected machine-checkable rules;
- optional `required_shocks`, `require_oracle_scoring`,
  `require_experiment`, and `require_phenomena` for bounded pilots.

Live acceptance additionally requires `--approve-live-inference` at the CLI.
The maintained production profile uses `scheduled_e2e_v1`: each latency sample
is bound to the exact scheduled prediction and covers Oracle planning, bounded
reads, answering, and contract validation. Manual Oracle calls and raw
`llm_calls.latency_ms` rows do not enter this gate. Missing, dangling,
malformed, or duplicate completion references fail closed. Markerless stored
configs retain the legacy answer-call calculation for replay compatibility.

The multi-run Oracle calibration release gate is separate from one run's
`acceptance` block. The active `oracle-calibration-v3` corpus uses fresh seeds
7321–7330 and `kimi-for-coding-highspeed`, with conservative 3x cost metering
and a $25 per-run cap. Its schema-v1 manifest is based on
`runs/oracle/manifest-v3.template.yaml` and explicitly records campaign ID and
version plus every run's ID, seed, source/replay database paths, profile path,
and SHA-256 hashes. `--oracle-campaign-run` produces the finalized pair and a
ready-to-copy manifest entry for one predeclared profile.
The evaluator will not discover databases or weaken its floors below 10 runs
and 60 forecasts. Every database must be a finalized standalone SQLite file
with no `-wal` or `-shm` sidecar. `--oracle-calibration-report` reads disposable
copies, verifies that source/profile/replay hashes remain unchanged, recomputes
the exact companion replay proof, and requires both
outcome classes, `scheduled_e2e_v1` p90 below 60 seconds, and Brier below 0.25.
Exact replay of each source is a mandatory manifest-bound companion artifact.

The archived `oracle-calibration-v1-s7301` source completed tick 335 with valid
live-provider provenance, but replay diverged at the first arrival because its
staged genesis did not persist the persona RNG stream. Checkpoint inspection
also retained SQLite WAL/SHM sidecars. It is diagnostic evidence only and must
not be listed in a release manifest. The preceding replay-integrity revision
persists and validates both semantics-7 RNG streams, finalizes standalone SQLite
checkpoints, and enforces the replay target tick; its focused and full
verification passed.

The immutable v2 seed-7311 source and generated offline replay both reached
tick 335 and crossed that arrival without the v1 divergence. Canonical
verification returned `exact: true` with `differences: []`. Its receipt failed
because checkpoint integrity counted all stored agent rows rather than
validating the bounded living population and reconciling it with preserved
deceased rows. V2 is diagnostic evidence and must not be listed in the v3
manifest. The v3 receipt contract validates living/deceased census consistency,
chronological death/schedule/arrival linkage, `NIGHT_CLOSE` event and subject
provenance, one-time consumption of due schedules, and the profile-locked
5–20-tick replacement delay.

## Rumor targeting

A research-valid rumor can resolve its target at fire time:

```yaml
params:
  bank_selector: largest_by_deposits
  audience: current_depositors
  n_agents: 40
```

`bank_selector` is `explicit` or `largest_by_deposits`; `audience` is
`all_citizens` or `current_depositors`. The `shock_fired` and `rumor` events
persist the resolved bank and exposed agent IDs without forcing beliefs or
withdrawals.

## Safe custom-profile workflow

1. Extend the closest maintained profile.
2. Change only scenario-relevant keys.
3. Run static and, if applicable, live preflight.
4. Start with a short headless run.
5. Inspect report, failure events, ledger reconciliation, and acceptance status.
6. Archive the resolved config, commit, seed, database, and evidence together.

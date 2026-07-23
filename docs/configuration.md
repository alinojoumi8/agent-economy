# Configuration and providers

## Profile inheritance

Run profiles are YAML. `extends` is resolved relative to the current profile and
nested mappings are merged. The fully resolved configuration and seed are saved
in `run_meta`, so a database remains self-describing.

| Profile | Purpose | Network/cost |
|---|---|---|
| `runs/evolving-live.yaml` | Default 100-agent Semantics-11 compute/skill economy | Ollama + DeepSeek + MiniMax + Kimi, uncapped and fully metered |
| `runs/base.yaml` | Default offline development world | None |
| `runs/production.yaml` | Approx. 100-agent MiniMax/Kimi runtime | Live inference |
| `runs/acceptance/rehearsal.yaml` | Free 365-tick acceptance rehearsal | None |
| `runs/acceptance/pilot.yaml` | Bounded 30-tick rumor pilot | Live, capped at $25 |
| `runs/acceptance/production.yaml` | Full 365-tick acceptance | Live, uncapped policy plus $200 efficiency gate |
| `runs/oracle/calibration-control-rehearsal.yaml`, `calibration-rehearsal.yaml` | Free 335-tick control/treatment Oracle schedule rehearsals | None; ineligible for campaign receipt |
| `runs/oracle/v9-seed-7381-control.yaml` … `v9-seed-7390-rumor.yaml` | Current pending v9 Oracle calibration corpus | Scripted background, live `MiniMax-M3` Oracle through the exact `openai_compat` adapter, automatic cache accounting, governed answer repair, occurrence-aware replay citations, capped at $25 per run; no v9 live evidence claimed yet |
| `runs/experiments/rumor_vs_control.yaml` | Five-seed treatment/control study | None by default |
| `runs/v2.yaml` | 1,000-agent, three-region semantics-7 flagship | None by default |
| `runs/r21-real-us.yaml` | Pinned SCF/SUSB calibrated genesis | None |
| `config/hosted.example.yaml` | R22 filesystem-backed development control plane | PostgreSQL |
| `config/hosted.docker.yaml` | R22 Compose application service | PostgreSQL + S3-compatible storage |

Profiles never silently change provider, model, endpoint, or credential type.

## Environment variables

Secrets belong in the ignored `.env` file or process environment.

| Variable | Purpose |
|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek V4 Flash route in the evolving-live profile |
| `MINIMAX_API_KEY` | MiniMax Token Plan route in production profiles |
| `KIMI_API_KEY` | Kimi Code membership route in production profiles |
| `ANTHROPIC_API_KEY` | Optional custom Anthropic route |
| `AGENT_ECONOMY_LOG_LEVEL` | Python operational log threshold; default `INFO` |
| `AGENT_ECONOMY_LOG_FILE` | Rotating JSON operational log; default `logs/agent-economy.jsonl.log` |
| `AGENT_ECONOMY_HOSTED_CONFIG` | Optional default path for `python -m hosted.cli` |
| `AGENT_ECONOMY_HOSTED_DATABASE_URL`, `AGENT_ECONOMY_HOSTED_DATABASE_PASSWORD` | Password-free hosted web PostgreSQL conninfo plus its separately injected password |
| `AGENT_ECONOMY_HOSTED_SUPERVISOR_DATABASE_URL`, `AGENT_ECONOMY_HOSTED_SUPERVISOR_DATABASE_PASSWORD` | Password-free restart/lease supervisor conninfo plus its separate password |
| `AGENT_ECONOMY_HOSTED_MIGRATION_DATABASE_URL`, `AGENT_ECONOMY_HOSTED_MIGRATION_DATABASE_PASSWORD` | Password-free migration-only administrator conninfo plus its separate password |
| `AGENT_ECONOMY_PUBLIC_BASE_URL` | Exact external HTTPS origin for hosted mode |
| `AGENT_ECONOMY_PUBLIC_HOST` | Hostname Caddy serves for the reference Compose stack; default `localhost` |
| `HTTPS_PORT` | Host port mapped to Caddy HTTPS; default `443` |
| `AGENT_ECONOMY_IMAGE_TAG` | Optional reference Compose image tag; default `local` |
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
| `engine_semantics_version` | Runtime compatibility contract; the default evolving-live profile uses `11`, while frozen production/research profiles retain their recorded version |
| `population.size` | Sampled citizen count; institutional/founder agents are added |
| `population.baseline_citizens_core` | Persisted semantics-7 opt-in that pins non-regional baseline citizens and later arrivals to the fully scheduled core tier |
| `banks`, `firms`, `exchange` | Deterministic banking, production, and market parameters |
| `central_bank` | Policy target, neutral rate, and step bounds |
| `lifecycle`, `government`, `vc`, `health` | Optional P1 systems |
| `behavior`, `conversations` | Wake cadence, run threshold, and social volume |
| `checkpoint_every`, `checkpoint_dir` | Recovery cadence and storage |
| `speed_delay_s` | Wall-clock pause between ticks; does not change simulation time |
| `outlets`, `shocks` | Information institutions and scheduled interventions |

`runs/evolving-live.yaml` and `runs/production.yaml` sample 63 citizens. The
engine-owned institutional and health-economy actors produce exactly 100 living
agents at genesis, including 65 non-institutional citizens. Evolving-live assigns
those citizens exactly 33 local, 26 Flash, and six premium launch grants.
Acceptance evaluates the living population; deceased rows remain available for
historical and replay evidence without inflating that gate.

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

The maintained `runs/v2.yaml` enables
`llm.local_currency_action_surfaces: true`. Under semantics 7, decision context
and advertised actions are filtered to goods, jobs, firms, and banks in the
actor's current local currency. Foreign-currency IDs fail validation; an actor
must complete an authorized FX action before using funds in another currency.

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

`runs/evolving-live.yaml` selects a route from the citizen's persisted compute
plan and the request role/purpose. Its desktop-safe global ceiling is 10 calls,
with independent Ollama (2), Ollama Cloud (3), DeepSeek (6), MiniMax (2), and
Kimi (2) priority pools. The local lane uses the
`agent-economy-qwen3.5:9b-16k` alias so Ollama does not allocate its much larger
default context. Strategic policy work outranks conversation, memory, and
newsroom work. Each logical call gets one live fallback and a 240-second hard
deadline; exhausted routes pause the same world phase without committing an
action. It never falls back to scripted or mock behavior.

`runs/production.yaml` routes citizens/founders to `MiniMax-M3` and
institutional roles plus the Oracle to Kimi's `kimi-for-coding`. Conversation
and memory purposes inherit the agent's role route.

Every call passes through the gateway. Before a live run:

```powershell
python run.py --config runs/evolving-live.yaml --preflight-live
```

Readiness validates environment variables and model catalogs and sends one real
JSON-contract completion through every routed provider before genesis. Rate
limits/overload enter an interruptible provider-wide cooldown.
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
configs retain the legacy answer-call calculation for replay compatibility. The
common scheduled-latency producer conservatively rounds each governed call's
persisted latency and clamps both continuous monotonic and resumed wall-clock
duration to at least their sum. This prevents measured end-to-end scheduling
jitter from producing a value below its governed-call components.

The multi-run Oracle calibration release gate is separate from one run's
`acceptance` block. The current pending `oracle-calibration-v9` corpus uses fresh
seeds 7381–7390, odd control/even rumor assignment, and a `$25` per-run cap.
Only the Oracle is live. It routes `MiniMax-M3` through the exact provider
configuration `kind: openai_compat`, `base_url: https://api.minimax.io/v1`,
`api_key_env: MINIMAX_API_KEY`, `max_tokens_field: max_completion_tokens`,
`healthcheck_path: /models`, `timeout_s: 180`,
`request_defaults.max_completion_tokens: 4096`,
`request_defaults.reasoning_split: true`, and
`prompt_cache_mode: provider_automatic`. Standard ≤512k pricing is `$0.30/M`
input, `$1.20/M` output, and `$0.06/M` automatic cache reads. Its schema-v1
manifest is based on `runs/oracle/manifest-v9.template.yaml`; commitment
SHA-256 is
`8a1845ebe9e916b8618a1c17170dc8a2b439c929ea1e1118670e21683c341a8e`.
The manifest records campaign ID and version plus every run's ID, seed,
source/replay database paths, profile path, and SHA-256 hashes.
`--oracle-campaign-run` produces the finalized pair and a ready-to-copy
manifest entry for one predeclared profile.
The evaluator will not discover databases or weaken its floors below 10 runs
and 60 forecasts. Every database must be a finalized standalone SQLite file
with no `-wal` or `-shm` sidecar. `--oracle-calibration-report` reads disposable
copies, verifies that source/profile/replay hashes remain unchanged, recomputes
the exact companion replay proof, and requires both
outcome classes, `scheduled_e2e_v1` p90 below 60 seconds, and Brier below 0.25.
Exact replay of each source is a mandatory manifest-bound companion artifact.
No v9 evidence is claimed until all ten predeclared live arms and the aggregate
receipt satisfy these checks.

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
deceased rows. V2 is diagnostic evidence and must not be listed in the active
manifest. V3 seed 7321 subsequently completed its source and exact companion
replay, but its original receipt applied accepted-plan validation to
authenticated rejected planner attempts and admitted only four of six
forecasts. That receipt records the pre-inspection source hash; the local source
artifact was later write-opened during diagnosis and is not admissible.

V4 seeds 7331 and 7332 produced eligible exact source/replay receipts, but they
remain diagnostic and are never reused. Seed 7333 completed an exact pair but
failed receipt eligibility at the tick-125 forecast. Its first planner attempt
requested the government ledger. Runtime queried only
`accounts.owner_type='gov'`, missed the actual system-owned `sys:gov` treasury,
returned `entity ledger accounts not found`, and incorrectly persisted and
retried that post-preflight execution failure as a planner rejection. The
second attempt failed the independently reproducible metric-name contract and
the third succeeded; the receipt correctly rejected the first retry binding and
therefore the run and fixed corpus. No v4 source, response, claim, checkpoint,
replay, or seed enters v5.

The v5 receipt/runtime contract retains the living/deceased census, chronological
death/schedule/arrival linkage, `NIGHT_CLOSE` event and subject provenance,
one-time due-schedule consumption, and profile-locked 5–20-tick delay checks. It
also shares a scheduled-tick, catalog-aware plan preflight between runtime and
receipt audit. That preflight validates historical tick ranges and advertised
entity IDs before any read executes; government ledger reads map to the
system-owned `sys:gov` treasury. Post-preflight failures are execution failures,
not retryable planner rejections. Full independently reproduced errors,
matching rejection events, and monotonic attempt ordinals make legitimate retry
requests unique, while only the final accepted plan is validated as executed
evidence. No v1, v2, v3, or v4 run enters the v5 manifest.

V5 seeds 7341–7347 produced passed, eligible source receipts with exact
companion replays. Seed 7348 finalized its source, but two same-tick loan
defaults at tick 301 and three at tick 331 shared the same bounded public
payload and importance. Replay therefore treated the recorded citations as
ambiguous and failed closed four articles to deterministic daily briefs; the
changed content and virality propagated through nine information tables. Seeds
7349–7350 were never run. V5 is retained as diagnostic evidence only. The seven
receipt-bound replay databases and fourteen Oracle source/replay receipts belong
only to seeds 7341–7347; seed 7348 has no eligible replay database or Oracle
source/replay receipt. Final corrected offline replay
`replay-oracle-calibration-v5-s7348-5220b912ae` reached tick 335 with
`exact: true`, identical logical hash `fee77b65…b378`, all 82 deterministic
tables exact, and `differences: []`; this post-source fix remains diagnostic and
creates no eligible v5 receipt. Completed cleanup removed 320 v5
source-checkpoint database bodies, 160 fixed-code replay checkpoint bodies,
four derived fixed-replay final databases, and the superseded partial seed-7343
replay: 485 database files and `111.945217 GiB` total. Retained artifacts are all
authoritative final sources; the seven eligible replay databases and fourteen
source/replay receipts for seeds 7341–7347; all source-checkpoint
manifests/hashes, claims, and reports; the 160 fixed-code replay checkpoint
manifests; and the ignored compact final exact receipt. Seed 7348 remains
excluded and has no eligible source/replay receipt or retained replay database.

V6 mapped a recorded public-event citation by its deterministic source
occurrence within the equivalence class and still failed closed when the class
was missing or inconsistent. Its first arm, seed 7351, stopped at tick 65 when a
successful Kimi answer used `confidence: "medium"` instead of `low|med|high`.
The runtime persisted a rule rejection, an `insufficient_data` prediction, and a
missed checkpoint. Spend was $0.18351, with no provider, budget, or
tool-execution failure. V6 is preserved and excluded; seeds 7352–7360 were never
run.

V7 is archived as an incomplete diagnostic campaign. Seeds 7361–7364 each have
passed, eligible source receipts and exact 335-tick companion replays with zero
differences. Seed 7365 stopped paused at tick 335 in `FINALIZE`; its authoritative
standalone database is 518,561,792 bytes with SHA-256
`b48b0c5a02270f6b09eafb5c32c8480a44f42057289048faedde9474d8ca8ce5`,
passes immutable read-only `quick_check`, has no WAL/SHM sidecars, and records
32,114 calls, 12 Oracle calls, six resolved forecasts/checkpoints, no critical
events, balanced USD, and `$0.2754108` spend. Receipt production exposed the
continuous scheduled-latency floor defect: persisted end-to-end latency was
13,658 ms while the governed call-latency sum was 13,660 ms. Seed 7365 has no
replay database or receipt, seeds 7366–7370 were never run, and the campaign has
no aggregate manifest or receipt. Its claim is bound to commit
`7642d7a193f8d0806d6043e8b105b6f469f649c8` and tree
`d9e02a64efd555fb6d0a5c1414351a6db238ad62`, so the committed producer fix means
that source cannot be resumed or mint an eligible receipt. No V7 artifact or
seed is reused in V8.

After the V7 archive/hash inventory became durable, the approved cleanup removed
exactly the 200 source checkpoint database bodies in `data/checkpoints` matching
anchored filename regex `^oracle-calibration-v7-s736[1-5]_t\d+\.db$`. It reclaimed
49,647,239,168 bytes (`46.237595 GiB`). Do not use a broad V7 wildcard. Retain
all 360 source/replay checkpoint manifests and hashes, five final source
databases, four final replay databases, eight source/replay receipt JSON files
for seeds 7361–7364, the five existing claim/initialized-marker pairs for seeds
7361–7365, the profiles,
commitments, template, base configuration, reports, and the authoritative seed
7365 database. The exact post-cleanup inventory contains zero matching V7
checkpoint database bodies and zero matching SQLite sidecars.

V8 is archived and excluded. Seeds 7371–7374 produced passed, eligible source
receipts and exact 335-tick companion replays. Seed 7375 stopped at tick 245
after four of six forecasts when Kimi returned HTTP 403 for its exhausted
billing-cycle quota. The source persisted one `provider_failure`, spent
`$0.19651848`, and remains a healthy standalone database. It is never resumed,
repaired, or substituted. The archive retains five source databases, four
replay databases, eight source/replay receipts, and all checkpoint manifests.
After the archive commit became durable, conservative cleanup removed exactly
189 V8 source-checkpoint database bodies matching anchored regex
`^oracle-calibration-v8-s737[1-5]_t\d+\.db$`—40 each for seeds 7371–7374 and 29
for seed 7375—totalling 43,999,223,808 bytes. Retain 189 source checkpoint manifests,
160 replay checkpoint manifests, five claims, five initialized markers, and the
final artifacts listed above. The verified post-cleanup inventory contains zero
source/replay checkpoint bodies and zero V8 SQLite sidecars. All nine retained
final databases pass immutable read-only `quick_check`, and eligible source/
replay hashes match their receipts. No V8 artifact or seed enters V9.

V9 retains the direct acceptance-rehearsal ancestry, fixed scheduled-latency
producer, governed-answer repair, engine semantics 7, and database schema 11.
A disposable one-call MiniMax probe and a deliberately unclaimed five-tick
Oracle rehearsal succeeded through the exact adapter above. They establish
operational readiness only and are not V9 corpus evidence. The complete
ten-arm and aggregate gate remains pending.

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

The implementation in PR #20 is authorized for squash merge after its complete
local gate. V9 live evidence, tagging, publication, and public deployment remain
separately authorized release actions.

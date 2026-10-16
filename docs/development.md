# Development and testing

[Controlled Hermes/Jev diagnostics](hermes-diagnostics.md) provide explicit read-only
CHECK, single-citizen DECIDE-ONE and guarded ADVANCE-ONE operations. Live operations
remain deferred until the execution-policy issue is resolved.

Prospective Jev domain delegation is documented in [Jev v4](jev-domains.md).
Use its provider-free profiles for development; existing worlds retain their
recorded decision and voting contracts.

Local operator household inspection is available from a selected person's
dossier. The [financial inspector contract](plans/2026-09-08-household-financial-inspector.md)
describes its committed-tick API, `operator_households.enabled` flag, identity
visibility and cash-inequality definitions. It requires current Semantics-20
position history; historical source runs are never repaired by the reader.

Saved-world operator studies use the bounded read-only checkpoint catalog and
the same explicit review, launch and recovery flow as fresh-world pilots. See
the [checkpoint study contract](plans/2026-09-07-checkpoint-studies.md#local-operator-interface)
for directory configuration, source limits and continuation semantics.
Focused coverage is in `tests/test_checkpoint_study_jobs.py`; browser coverage
and synthetic desktop/mobile review captures are in the world-workspace suite.

Policy studies from fresh and saved worlds use the v3 CLI, evidence reader and local operator workspace.
Their prospective day/phase recovery policy preserves the original shared
provider allowance across readiness checks and all model replicates. See the
[live-policy workflow](plans/2026-09-07-live-policy-studies.md#cli-workflow) for
drafting, explicit launch authorization, pause and provider-free resume validation.
`tests/test_policy_recovery.py` and `tests/test_policy_origins.py` exercise controlled
loopback HTTP, original allowance recovery and declared saved-world policy
transitions in their own required CI job. The operator advertises policy launches
only when a valid owner-configured design is available. Its default directory is
`data/policies`; override it with `operator_research.policy_root` in the server
configuration. See the [operator policy workflow](plans/2026-09-07-policy-operator-workflow.md#owner-configuration-and-request-contract)
for design limits, deliberate approval and original-allowance recovery.
`tests/test_policy_operator.py` covers provider-free review and real local
supervisors with controlled loopback HTTP in a separate required CI job.

Private v3 evidence is readable and portable through `research.policy_results`
and `research.study_bundle`. Export the current closed pause or sealed final
result with its reviewed hash; import into a new private directory. See the
[policy evidence contract](plans/2026-09-07-policy-evidence-bundles.md#cli-workflow)
for commands, ownership and accounting checks. A verified paused archive remains
pending, and an imported allowance cannot resume execution in a second namespace.
`tests/test_policy_evidence.py` covers all six fresh/saved and frozen/day/phase
paths in a separate required CI job using controlled loopback HTTP.

Saved semantics-11 Hermes worlds can opt into persistent geography, exploration,
settlement construction and resident charter votes. See [frontier geography](frontier.md)
for the backup-first upgrade and history contract.

## Repository workflow

Work on a feature branch or dedicated worktree. Preserve unrelated changes,
commit cohesive units, push the branch, and open a pull request into `main`.
The backend and committed dashboard bundle are one release unit.

Before integrating or deleting an older branch, follow
[branch lifecycle and consolidation](branch-lifecycle.md). Dirty worktrees,
open pull-request branches, and unique commits are protected until their exact
disposition is recorded and approved.

## Backend

```powershell
python -c "import sys; assert sys.version_info[:2] in {(3, 11), (3, 12)}, 'Python 3.11 or 3.12 required'"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --require-hashes -r requirements.lock
python run.py --config runs/base.yaml
```

POSIX (bash):

```bash
python3 -c "import sys; assert sys.version_info[:2] in {(3, 11), (3, 12)}, 'Python 3.11 or 3.12 required'"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements.lock
python run.py --config runs/base.yaml
```

The pinned test environment includes `httpx2`, the supported transport for
[Starlette TestClient](https://starlette.dev/testclient/). API tests remain
in-process; runtime provider adapters continue using `httpx`. The smoke job
imports TestClient with warnings treated as errors to catch a missing transport.

Use the scripted profile for normal development. It exercises all systems
without network cost and preserves deterministic results.

`requirements.txt` is the human-edited dependency input. Regenerate the
cross-platform, hash-locked install after changing it:

```powershell
uv pip compile requirements.txt --universal --python-version 3.11 --generate-hashes -o requirements.lock
```

Research exports use DuckDB's Python type conversion path, which checks pandas
types. The pinned environment includes pandas to avoid repeated failed imports
for each value. The exporter retains its bounded SQLite row batches, independent
Parquet readback and resource limits. See the
[export measurements](plans/2026-09-09-bounded-research-exports.md#measured-optional-import-bottleneck)
for byte-parity evidence and the measured memory/time tradeoff.

The full gate also uses `uvx` for the Python dependency audit. Install
[uv](https://docs.astral.sh/uv/getting-started/installation/) first and verify
that it is available before running the gate:

```bash
uv --version
```

## Dashboard

Run FastAPI on port 8000, then in another terminal:

```powershell
Set-Location dashboard
npm ci
npm test
npm run licenses:check
npm run dev
```

POSIX (bash):

```bash
cd dashboard
npm ci
npm test
npm run licenses:check
npm run dev
```

Vite proxies `/api`, `/ws`, and `/reports`. For a browser served by Vite,
explicitly allow its origin in the backend run profile because its port differs
from the local API server:

```yaml
server:
  allowed_origins:
    - http://localhost:5173
```

Use the exact scheme, hostname and port printed by Vite; add a separate entry
if opening it through `127.0.0.1`. The production bundle served by FastAPI uses
its own origin automatically.

The production build writes directly
to `server/static/`:

```powershell
npm --prefix dashboard run build
```

Review and commit the new hashed bundle when frontend source changes.
Run `npm run licenses` after dependency changes; Vite copies the generated
`THIRD_PARTY_NOTICES.txt` into the public static bundle.
The Tailwind source scan explicitly excludes `dashboard/public/` and
`dashboard/scripts/` so generated legal text and notice tooling cannot change
the application stylesheet or its content hash.

### Provider-free real-backend menu smoke

The repeatable city-to-price-study gate creates its own isolated world and serves
the production bundle: `python scripts/city_research_acceptance.py`. It covers
historical navigation, operator bookmarks, mobile keyboard selection, both price
studies, independent evidence import and unchanged source-world contents. See the
[acceptance contract](plans/2026-09-07-city-research-acceptance.md) for setup,
bounds, retained evidence and CI. Use the older manual menu smoke below when
testing a separately started disposable world.

The normal Playwright suite mocks projection contracts. To exercise the same
menus against a real deterministic database and FastAPI server, start a bounded
provider-free run in one terminal:

```powershell
python run.py --config runs/base.yaml --ticks 3 --serve --host 127.0.0.1 --port 8000
```

Copy the printed run ID, then run the opt-in smoke from a second terminal:

```powershell
$env:AE_REAL_RUN_ID = "<run-id>"
npm --prefix dashboard run test:e2e -- e2e/world-os-real-backend.spec.ts
```

Without `AE_REAL_RUN_ID`, these opt-in tests are skipped and the mocked suite
runs normally. Complete at least one day in the disposable run first; the smoke
reads City and its panels without advancing the world. It makes no provider
calls under `runs/base.yaml` and does not validate hosted-only destinations.

To include the 3D city and test the committed production bundle directly, use
`runs/simcity.yaml` for the disposable server above and set
`$env:AE_REAL_BASE_URL = "http://127.0.0.1:8000"` before the browser command.
The two real-backend tests cover workspace navigation, city layers, 3D rendering,
entity evidence links, camera controls and reload. Clear `AE_REAL_BASE_URL`
before returning to the normal Vite-backed suite.

On Windows, use `.\.venv\Scripts\python.exe` explicitly if another application's
Python is on PATH. A provider-free local city can be started from the repository
root with:

```powershell
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe run.py --config runs/simcity.yaml --serve
```

Keep the server terminal running and open `http://127.0.0.1:8000/`. It starts
paused; choose **Run** or **Step** to advance. No frontend development server is
needed. The evolving-live default and DeepSeek demo require their separately
documented provider setup and explicit live-inference authorization.

## Test layers

### Bounded DeepSeek and MiniMax UI rehearsal

Use the Passport-enabled local profile when checking the UI with these two
providers and standard browser OAuth:

```powershell
.\.venv\Scripts\python.exe run.py --config runs/hermes-deepseek-minimax.yaml --ticks 3 --serve --preflight-live --approve-live-inference
```

It requires `DEEPSEEK_API_KEY` and `MINIMAX_API_KEY`, caps recorded inference
spend at $2, routes VC decisions to MiniMax-M3 and other cognition to
deepseek-flash, and starts paused. Choose Run; at tick 3 it pauses at the
session boundary. Stop + report finalizes the result. No Kimi or Ollama route
is used. Provider availability is verified before creating the world.

The Join and My Agents menus expose the existing local Passport flow.
Connecting a real external agent requires the owner's browser consent;
running native agents alone does not connect Hermes. OAuth discovery advertises
only citizen scopes, excluding moderation. Start a fresh client authorization
after switching worlds: old client registrations and temporary callback URLs
may no longer be valid. Profiles without Passport consent show an explanatory
page instead of a missing-tenant/connection validation error, and grant no access.

Workspace navigation resets scroll by pathname: a new page begins at its
heading, while query-only filters retain the current reading position.

### Connecting an installed Hermes agent locally

The dashboard does not require Hermes OAuth. Keep the Hermes messaging gateway
stopped unless you intentionally want it running. For a bounded connector test,
start `runs/hermes-local.yaml` with `--serve --ticks 4`: its native residents are
scripted, while the external Hermes process supplies real model decisions.
Resume the same run with `--resume <run-id>` after a server restart to preserve
its OAuth client registration, actor, receipts, and world history.

Configure the Hermes profile's existing MCP entry as follows:

```yaml
mcp_servers:
  agent_economy:
    url: http://127.0.0.1:8000/mcp
    auth: oauth
    connect_timeout: 315
```

The connection timeout must cover the five-minute browser approval window.
A 30-second timeout can cancel the callback listener and open replacement tabs
while the owner is still completing the form. Initiate login deliberately:

```powershell
hermes --profile agenteconomy gateway stop
hermes --profile agenteconomy mcp reauth agent_economy
hermes --profile agenteconomy mcp test agent_economy
```

Use the newest authorization page. If a Passport already exists, select it
instead of creating another citizen. The consent page permits the validated,
registered callback in its `form-action` policy, because Chromium also checks
the redirect after form submission. Other onboarding pages retain same-origin
form restrictions. Never broaden this to arbitrary callback destinations.

After approval, `mcp test` must discover the eight Agent Economy tools without
opening another browser tab. For a bounded real model test, Hermes chat accepts
`--provider deepseek --model deepseek-flash --toolsets agent_economy --oneshot`
with a query and a configured DeepSeek key. The toolset selector is the configured
server name, not the internal `mcp-agent_economy` registry name.

Switching to a different world requires fresh client registration via `mcp reauth`.
Do not reuse old callback URLs or resubmit an approved consent form. An approved
Passport plus a failed callback is recoverable by reconnecting that same Passport.
The local profile uses Semantics 11: an offline turn records `external_agent_fallback`
with `safe_do_nothing_v1`; explicit Missed Turn attendance is a later contract.

The browser regression starts its own provider-free world and a second-port
callback listener, then exercises approval, PKCE exchange, denial and an
unregistered callback. It uses temporary databases and shuts down its owned server:

```powershell
$env:AE_TEST_PYTHON = (Resolve-Path .venv/Scripts/python.exe).Path
npm --prefix dashboard run test:e2e -- oauth-callback.spec.ts
```

On CI/POSIX, the fixture defaults to `python` from the installed environment.

City navigation bookmarks use the separate operator store. Focused checks are
`tests/test_city_observations_api.py`, `tests/test_operator_workspace.py`, the
dashboard `cityObservations`/`cityObjectList` node suites, and the city-context and
workspace-route browser suites. These cover API admission, world immutability,
concurrent edits, mobile keyboard selection and the desktop map-area requirement.
The [navigation contract](plans/2026-09-07-city-workspace-navigation.md) records
the focused scope; the [production workflow gate](plans/2026-09-07-city-research-acceptance.md)
adds the actual backend and supervised study/export path.

Working research studies now have two explicit pause contracts: version 2 for
committed days and opt-in version 3 for saved phases. Run the bounded phase
regressions with `tests/test_phase_working_attempts.py` and
`tests/test_phase_working_studies.py`; the operator suite also covers planned
step pauses. See [paused-study recovery](plans/2026-09-06-paused-study-resume.md)
for the manifest policy, CLI controls and compatibility requirements. On Windows,
use a fresh short `--basetemp` and verify at least 40 GiB of free space before
pytest. Complete Python coverage belongs in the CI shards, not one local run.

Scripted checkpoint-derived studies use an explicit version 2 study declaration and
attempt version 4. Their independent recorded replay begins at the admitted
saved day. Run `tests/test_checkpoint_origins.py` and
`tests/test_checkpoint_studies.py` for source immutability, both price domains,
day/phase recovery, inherited-cost separation and private bundle checks. See
[saved-world studies](plans/2026-09-07-checkpoint-studies.md) for drafting and
execution commands and the remaining operator interface work.

| Layer | What it proves |
|---|---|
| Unit/invariant | Ledger conservation, markets, credit, firms, memory, metrics |
| Integration | World phases, lifecycle, providers, shocks, reports, controls, API |
| Property | Random valid actions, lifecycle storms, price and budget invariants |
| Golden | Legacy deterministic event output remains exact |
| Replay | Fresh re-execution produces canonical table equality |
| Acceptance | Rumor evidence, shock traces, Oracle samples, cost, long horizon |
| Dashboard | Client behavior and current production bundle |

Full local gate:

```powershell
python -m compileall -q agents engine experiments hosted llm oracle reports research server world run.py
python run.py --verify-datasets config/data-manifest.yaml
python -m pytest tests/ -q
python -m pip check
uvx pip-audit -r requirements.lock
npm --prefix dashboard ci
npm --prefix dashboard test
npm --prefix dashboard run licenses:check
npm --prefix dashboard audit --audit-level=high
npm --prefix dashboard run build
git diff --check
```

POSIX (bash); every gate command is shell-neutral, so these match the
ubuntu-latest CI invocations:

```bash
python -m compileall -q agents engine experiments hosted llm oracle reports research server world run.py
python run.py --verify-datasets config/data-manifest.yaml
python -m pytest tests/ -q
python -m pip check
uvx pip-audit -r requirements.lock
npm --prefix dashboard ci
npm --prefix dashboard test
npm --prefix dashboard run licenses:check
npm --prefix dashboard audit --audit-level=high
npm --prefix dashboard run build
git diff --check
```

The closure/release audit also scans the current tree and full Git history with
Gitleaks using the narrow repository config in `.gitleaks.toml`. Repeat the
dependency, notice, dataset-provenance, attribution, and secret audits before a
public tag; a successful merge audit is not a permanent publication waiver.

Commits are additionally guarded by a local pre-commit secret scan: run
`scripts/install_precommit_hook.sh` once per clone to wire
`scripts/secret_scan.sh --staged` (Gitleaks on staged changes, fail-closed)
into `.git/hooks/pre-commit`. The ruleset is pinned to Gitleaks 8.30.1 so its
inherited detectors cannot drift. Provider credentials live only in the
ignored `.env`; never commit a populated `env` or `.env` file.

After a clean build, verify both tracked changes and newly generated files:

```powershell
git diff --exit-code -- server/static
if (git status --porcelain --untracked-files=all -- server/static) { throw "Uncommitted static output" }
```

POSIX (bash), exactly as the ubuntu-latest dashboard job runs it:

```bash
git diff --exit-code -- server/static
test -z "$(git status --porcelain --untracked-files=all -- server/static)"
```

When the bundle changed intentionally, review and commit every generated file.

## Adding behavior safely

1. Keep economic mutation in `engine/` or deterministic `world/` mechanics.
2. Define a structured action contract; never parse model prose into money.
3. Validate actor role, ownership, state, amount, and phase.
4. Route every monetary effect through the ledger.
5. Emit a durable event with enough IDs/values to audit the transition.
6. Add success, rejection, replay, and reconciliation tests.
7. Update metrics/API/dashboard/docs if the behavior is observable.

## Scale-270 economic acceptance

The maintained scale lane evaluates 270 sampled citizens, which Genesis expands
to 308 persisted agents after institutional staff and health-economy founders.
Its regional cohort is fixed at 184/69/55 throughout acceptance. Both diagnostic
arms and their inherited canaries use
`living_world.career_migration_enabled: false`, suppressing advertised career
moves and rejecting requests and pending
settlement. Ordinary worlds omit this option and retain existing migration
behavior. This control does not govern household moves in later semantics.
Run the provider-free diagnostic arms in separate ignored directories:

```bash
python scripts/run_scale_validation.py \
  --profile runs/acceptance/scale-270-baseline-120.yaml \
  --ticks 120 --label baseline-120 \
  --output-dir reports/out/scale-270/baseline/output \
  --data-dir reports/out/scale-270/baseline/runs

python scripts/run_scale_validation.py \
  --profile runs/acceptance/scale-270-recovery-120.yaml \
  --ticks 120 --label recovery-120 \
  --output-dir reports/out/scale-270/recovery/output \
  --data-dir reports/out/scale-270/recovery/runs
```

The inventory recovery candidates use
`runs/acceptance/scale-270-recovery-inventory-120.yaml` and the matching
`-1000.yaml` profile. They activate inventory guidance at tick 60, count staff
as potential shoppers with `behavior.inventory_aware_shopping_include_staff`,
and set `behavior.inventory_aware_shopping_reserve_bps: 2000`. The latter uses
80% of advertised stock for quantity guidance while retaining the one-unit
minimum; settlement can still use all stock. The new controls default to
`false` and `0`, preserving historical observations and replay. Use distinct
output/data directories and retain the original diagnostic arms. The repaired
profiles also set `supply_recovery.max_headcount_per_firm: 8`, allowing one
additional demand-supported worker under the existing cash, wage and hiring-rate
checks. This capacity change can alter hiring before tick 60; identical warmup
history is not claimed. The
[purchase diagnosis](qa/2026-10-11-scale-purchase-diagnosis.md) records the
failed attempts and the validation boundary; a candidate must pass a fresh
120-tick source/replay evaluation before formal or live acceptance.

The prospective `runs/acceptance/scale-270-recovery-buffer-120.yaml` profile
keeps those economic settings and opts into the
[buffer/demand v2 contract](superpowers/specs/2026-10-14-inventory-buffer-demand-v2.md).
It records independent daily inventory, stock-free scripted demand and
purchase-time stock/cash limits in three additive audit tables. These tables
are absent by default and included in exact replay when enabled. The v2 report
allows ordinary buffer drawdown but requires conserved inventory, continued
production and no persistent empty/unsafe buffers. Its separate demand table
exposes desired, affordable, submitted and fulfilled quantities; measurement
completeness is required, and household demand adequacy is not certified by a
low rejection rate. The original v1 A/B evaluator deliberately rejects a v2
arm as directly comparable. Retain each arm's contract version in comparisons.

The [120-tick buffer and demand evidence](../benchmarks/receipts/scale-270/buffer-120/README.md)
keeps the prospective v2 verdict separate from the unchanged failed v1 arms,
retains the first v2 resource failure, and reports demand quantities by region.
Its short scripted scope does not certify
household demand adequacy, longer runs, live providers or release readiness.

The harness prints the exact source database, replay database, and runtime
receipt identities. Evaluate each finalized pair without opening a writer,
replacing the three `<...>` values with those printed artifact paths:

```bash
python -m reports.scale_economic_health \
  --source <source-db> \
  --replay <replay-db> \
  --runtime-receipt <runtime-receipt> \
  --output benchmarks/receipts/scale-270/<arm>-economic-health
```

Exit `0` is a pass. Exit `10` is reserved for an economic-only failure in a
120-tick diagnostic arm after every operational, integrity, checkpoint, and
replay gate passed. Exit `5` is an operational, artifact, replay, unexpected,
or formal-horizon failure; exit `2` is command misuse. The formal provider-free
v2 gate keeps the 120-tick buffer profile's economic policy and acceptance
limits, requires exactly 1,000 ticks, and checkpoints every 100 ticks with two
retained copies. The original v1 profile
`runs/acceptance/scale-270-recovery-1000.yaml` remains available for historical
reproduction. Run the v2 gate in a fresh artifact directory:

```bash
python scripts/run_scale_validation.py \
  --profile runs/acceptance/scale-270-recovery-buffer-1000.yaml \
  --ticks 1000 --label buffer-1000 \
  --output-dir reports/out/scale-270/buffer-formal/output \
  --data-dir reports/out/scale-270/buffer-formal/runs
```

Provider-free profiles reject `--approve-live-inference`; do not add that flag
to any command above. Paid profiles require the flag and are limited to their
maintained two-tick canaries. For example:

```bash
python scripts/run_scale_validation.py \
  --profile runs/scale-270-minimax-live.yaml \
  --ticks 2 --label minimax-two-tick \
  --output-dir reports/out/scale-270/minimax/output \
  --data-dir reports/out/scale-270/minimax/runs \
  --approve-live-inference

python scripts/run_scale_validation.py \
  --profile runs/scale-270-deepseek-live.yaml \
  --ticks 2 --label deepseek-two-tick \
  --output-dir reports/out/scale-270/deepseek/output \
  --data-dir reports/out/scale-270/deepseek/runs \
  --approve-live-inference
```

`reports/out/scale-270/` is ignored raw runtime storage. SQLite databases and
checkpoint bodies stay local there and are never committed. Only reviewed,
sanitized JSON/Markdown evidence belongs under
`benchmarks/receipts/scale-270/`; never copy credentials, private provider
bodies, reasoning, cookies, environment dumps, or database bytes into a public
receipt.

Runtime checkpoint entries include `phases_s`: preparation, legacy writer,
and catalog recording, plus legacy retention when it runs. Recording includes
retention; do not add both durations. The legacy writer includes SQLite backup,
artifact finalization and manifest generation; `write_backup`, `write_finalize`
and `write_manifest` measure those operations separately inside `write`.
Do not add these nested samples to the writer or total duration. They include
failed operations and preserve the original exceptions. Custom legacy writers
without the optional timing argument retain just the overall writer sample.
Storage-policy writers bypass
the legacy method and have no `write` sample. Total `duration_s` remains the
resource-gate measurement, including Stop checkpoints; phase samples are only
diagnostics. Measurement wraps one validation world and does not change its
scientific configuration or checkpoint operations.

The [October 11 backlog audit](qa/2026-10-11-manyworld-release-backlog.md)
reconciles the live Atlassian inventory with the current release blockers.

## Schema and compatibility

Run databases are scientific artifacts. Additive columns/tables are preferred.
New semantics that would change historical output must be gated by
`engine_semantics_version`; v1/v2 replay behavior must remain exact. Never
rewrite a stored source run during replay.

The [Semantics 15 household guide](semantics15-households.md) specifies schema 21
person origins, membership/custody, child needs, demographic keyed draws and
census reconciliation. Its focused tests are part of the required core CI job.

The [Semantics 16 randomness guide](semantics16-randomness.md) specifies daily
mechanism/origin keys, unchanged historical draws, and the opt-in goods/equity
pilot profile. Required research CI covers draw isolation and source/resume/replay
checks for both domains. It adds no database migration.

The [Semantics 17 household decision contract](plans/2026-09-07-household-decisions.md)
adds schema 22 proposals, adult assents, partnerships and atomic joint migration.
Run `tests/test_semantics17_household_decisions.py` for the focused core gate.
Its rehearsal uses the small city profile with real scripted decisions and no
provider calls. New state uses hash-contract-v4; older contracts remain frozen.
Complete estates and long-horizon household validation remain W5 work.

The [Semantics 18 daily time contract](plans/2026-09-07-daily-time-and-earned-wages.md)
adds schema 23 time budgets, delivered care, proportional labor and non-cash wage
claims. `runs/daily-time-rehearsal.yaml` is the bounded opt-in city profile;
`tests/test_semantics18_daily_time.py` is part of required core CI. Plans affect
the following day. Hash-contract-v5 includes the new authoritative journals;
v1–v4 files remain frozen. Use a fresh short pytest directory and keep at least
40 GiB free. Full estates, education cohorts and long-horizon validation remain.

Semantics 19 adds the [estate cash and credit checkpoint](plans/2026-09-07-estate-cash-and-credit.md).
Use `runs/estate-cash-rehearsal.yaml` and `tests/test_semantics19_estate_cash.py`
for the currency-separated cash inventory, principal recovery, bank losses,
rollback and replay. Schema 24 is additive; new receipts require hash-contract-v6.
Frozen v1–v5 files and prior simulation semantics remain unchanged. This is not
full asset succession or long-horizon validation.

The [Buzz-derived architecture boundaries](buzz-derived-architecture.md)
document the additive schema-20/Semantics-14 attendance contract, read-time
activity projection, proposal-only Builder support seam, and the separate
hosted control-plane audit migration.

## Documentation changes

Documentation ships with the behavior it describes. Use the
[documentation maintenance guide](documentation-maintenance.md) to identify
affected audiences, apply the source-of-truth hierarchy, update ADR status, and
run the maintained-link contract.

At minimum, a new durable guide must be linked from [the handbook](README.md)
and added to `HANDBOOK_DOCS` in `tests/test_documentation.py`. A new route,
profile, semantics version, hosted operation, or security boundary must update
its specialized guide rather than only the root README. Keep the historical
printable Semantics-7 status snapshot frozen and update the current
`implementation-status.md` ledger instead.

## Logging

Use `observability.log_event` for process diagnostics and `Store.log_event` for
scientific/economic evidence. Operational logs must be bounded and secret-safe;
the SQLite event spine may contain richer causal evidence but should still avoid
credentials. Successful per-call request/replay/resume records are DEBUG-only;
INFO is reserved for run-level milestones and unusual recovery. Add assertions
for important failure/recovery logs.

## CI and review

The application Docker runtime is digest-pinned to Python 3.12.15 on Debian
Trixie (SQLite 3.46.1). The former Bookworm runtime (SQLite 3.40.1) produces
different floating-point sentiment aggregates in the preserved semantics-5
golden replay. The Trixie runtime passes that exact fixture and the semantics-1
and semantics-2 replay/source-immutability checks; no metric tolerance or stored
source data is changed. Build it with `docker build -t manyworld:local .`.

Historical artifacts must retain the runtime that produced them. The
`PYTHON_RUNTIME_IMAGE` build argument accepts an explicitly chosen image from
the original run's runtime receipt, including its digest. Validate replay in
that runtime before resuming a historical run. Updating the default image does
not migrate run databases or establish compatibility with every older SQLite
aggregation implementation. Keep the original image and source artifacts.

GitHub Actions builds the dashboard on Node.js 22 and runs Python 3.11/3.12 on
Ubuntu and Windows. Every PR also runs a single deterministic shard of the
engine/world/agents-focused tests via `scripts/pytest_shard.py`, so edits to
`run.py`, `llm/gateway.py`, `agents/`, `world/`, and `engine/` are exercised
before merge; the full cross-platform matrix remains a manual workflow
dispatch. Each OS/Python pair uses all 16 full-suite shards (indices 0–15),
with a 30-minute limit per job. A focused matrix override provides partial
coverage until every shard in the pair has a successful result.
The policy recovery and saved-world recovery suites each run across four
deterministic shards, retaining every test and the ten-minute job limit. Verbose
test names, duration summaries and a 90-second traceback make slow executions
diagnosable. Run research suites from an unchanged checkout: their manifests bind
the complete code identity, so edits during execution correctly invalidate them.
Failed dashboard checks retain Playwright traces and screenshots for seven days.
Hosted integration and Compose build the pinned MinIO server and client from
official source; see [MinIO source images](#minio-source-images). The previous
registry pulls are unavailable. Validate the newer source revision on disposable
volumes before any existing data is used.
Pull requests should state behavior, tests, live calls/cost,
compatibility impact, and remaining risk. See [CONTRIBUTING.md](../CONTRIBUTING.md).

## MinIO source images

Quay rejects the former pinned MinIO server/client image pulls. The optional
hosted integration job and [Compose model](../deploy/compose.yaml) now build
[official-source images](../deploy/minio/Dockerfile) from fixed upstream commits
and digest-pinned Go/Debian bases. Build locally with:

```bash
docker build -f deploy/minio/Dockerfile --target server -t manyworld-minio:2025-10-15-source .
docker build -f deploy/minio/Dockerfile --target client -t manyworld-mc:2025-08-13-source .
```

Each image includes the upstream `LICENSE`, `NOTICE`, `CREDITS` and exact source
URL under `/usr/share/doc/minio/` or `/usr/share/doc/mc/`.

The upstream community projects are archived/source-only. These local images
restore test/staging availability; they are not evidence of ongoing vendor
maintenance. Production still needs an explicitly owned update process or a
maintained S3 service. Preserve existing object-store volumes and verify the
upgrade/rollback before using the newer server revision on existing data. No
volume migration or deployment is performed by the build commands.

## CircleCI release checks

The connected `gh/alinojoumi8/manyworld` project uses `.circleci/config.yml`.
The executor pins Python 3.11.17 on Debian Trixie by image digest, including
SQLite 3.46.1. The previous `cimg/python:3.11` image used SQLite 3.37.2 and
reproduced different floating-point sentiment aggregates in the preserved
semantics-5 golden replay. Keep that fixture and its exact comparison intact;
validate a replacement runtime against it before updating the image pin.
Normal runs execute the provider-free smoke suite. To explicitly run the full
Python 3.11 Linux suite, use the authenticated CLI:

```bash
circleci run trigger --project gh/alinojoumi8/manyworld --branch BRANCH --parameter full_suite=true
```

The full run uses the same deterministic sixteen-shard pytest plugin as the
GitHub release matrix, with JUnit results and XML artifacts. No provider secrets,
live model calls, deployment jobs, automatic retries, or default full-suite runs
are configured. CircleCI supplements the existing GitHub cross-platform gates.
Evaluate actual shard durations from this first run before changing fan-out;
remove this config to roll back the additional CI workflow.

## Prospective JEV quality evaluation

The [matched quality study protocol](plans/2026-10-05-jev-quality-study.md)
predeclares seeds, horizons, metrics, correctness and economic gates for #101.
It is preparation only; the approved live bounds and frozen extraction manifest
are still required. Keep JEV-v4 opt-in and retain the historical diagnostics.

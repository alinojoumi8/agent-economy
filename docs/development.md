# Development and testing

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

Use the scripted profile for normal development. It exercises all systems
without network cost and preserves deterministic results.

`requirements.txt` is the human-edited dependency input. Regenerate the
cross-platform, hash-locked install after changing it:

```powershell
uv pip compile requirements.txt --universal --python-version 3.11 --generate-hashes -o requirements.lock
```

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

Vite proxies `/api`, `/ws`, and `/reports`. The production build writes directly
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

Without `AE_REAL_RUN_ID`, this one opt-in test is skipped and the mocked suite
runs normally. The smoke may advance a non-terminal run to tick 3 through the
ordinary UI controls. Use only a disposable local run. It makes no provider
calls under `runs/base.yaml` and does not validate hosted-only destinations.

## Test layers

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
gate uses the same commands with this profile and horizon:

```bash
python scripts/run_scale_validation.py \
  --profile runs/acceptance/scale-270-recovery-1000.yaml \
  --ticks 1000 --label recovery-1000 \
  --output-dir reports/out/scale-270/formal/output \
  --data-dir reports/out/scale-270/formal/runs
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

GitHub Actions builds the dashboard on Node.js 22 and runs Python 3.11/3.12 on
Ubuntu and Windows. Every PR also runs a single deterministic shard of the
engine/world/agents-focused tests via `scripts/pytest_shard.py`, so edits to
`run.py`, `llm/gateway.py`, `agents/`, `world/`, and `engine/` are exercised
before merge; the full cross-platform matrix remains a manual workflow
dispatch. Pull requests should state behavior, tests, live calls/cost,
compatibility impact, and remaining risk. See [CONTRIBUTING.md](../CONTRIBUTING.md).

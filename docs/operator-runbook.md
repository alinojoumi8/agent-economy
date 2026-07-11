# Operator runbook

## Start safely

Choose the intended profile explicitly:

```powershell
# Offline
python run.py --config runs/base.yaml

# Active MiniMax-only production profile
python run.py --preflight-live
python run.py
```

The server binds to `127.0.0.1:8000` unless `--host` or `--port` is supplied.
The world starts paused.

Before a costly run, record the commit, profile, seed, population, budget cap,
provider/model catalog result, and intended stopping condition.

## Dashboard controls

- **Run** starts or resumes continuous ticks.
- **Pause** requests a clean pause after the current safe boundary.
- **Step** executes exactly one tick and leaves the world paused.
- **Speed** sets real-time delay between ticks; it does not change simulated
  time or economics.
- **Stop + report** marks the run finished, checkpoints it, and creates a report.

A finished run can be started or stepped again; the report path is cleared and
a later stop produces a fresh report. A halted run cannot restart because halt
means an invariant failure requiring investigation.

## Observe a run

Use the dashboard or API to watch:

- run status, tick, provider readiness, spend, and degradation level;
- macro series, banks, firms, institutions, trades, news, and conversations;
- agent identity, accounts, beliefs, memory, and exact decision audit;
- Oracle predictions, resolution, Brier score, and calibration;
- scheduled shocks and significant event records.

Provider failure, budget pause, reconciliation failure, and uncaught run
exceptions are recorded in the database event stream. Do not diagnose from the
browser alone.

## Checkpoints and recovery

Periodic checkpoints are copied to:

```text
data/checkpoints/<run-id>_t<tick>.db
```

Pause preserves the active database. Resume by run ID:

```powershell
python run.py --config <ORIGINAL_PROFILE> --resume <RUN_ID>
```

Use the same resolved configuration. Acceptance campaigns refuse to resume when
the configuration differs because mixed evidence would be invalid.

If the active database is damaged, preserve it for diagnosis and resume from a
known-good checkpoint via a fork rather than overwriting evidence:

```powershell
python run.py --config <PROFILE> --fork <RUN_ID>@<TICK>
```

The fork creates a new run with parent metadata; the source stays unchanged.

## Reports

Stopping from the dashboard generates a standalone report automatically. To
regenerate one from a stored run:

```powershell
python run.py --report <RUN_ID>
```

Reports are written under `reports/out/` and served at `/reports/` while the
application is running.

## Exact replay

```powershell
python run.py --replay <RUN_ID>
```

Replay makes no provider calls. It creates a new database, uses the source
run's recorded responses, and verifies canonical table digests. Exit status 3
means the rebuilt state did not match. A missing stored response pauses safely
instead of contacting a provider.

## Experiments

Run a committed experiment specification:

```powershell
python run.py --experiment experiments/<SPEC>.yaml
```

The harness executes defined seeds and treatment/control arms, aggregates
results, and writes a report. Preserve the specification with the results.

## PRD acceptance campaign

The locked mixed-provider campaign is intentionally separate from the active
MiniMax-only runtime:

```powershell
python run.py --acceptance runs/acceptance/v1.yaml
```

It can run or resume individual phases:

```powershell
python run.py --acceptance runs/acceptance/v1.yaml --acceptance-phase long
python run.py --acceptance runs/acceptance/v1.yaml --acceptance-phase rumor
python run.py --acceptance runs/acceptance/v1.yaml --acceptance-phase report
```

The campaign currently requires a Kimi API Platform credential for its K2.6
route. Do not substitute a Kimi Code membership key.

## Backup and retention

For a run worth preserving, archive:

1. `data/runs/<run-id>.db` after a clean pause or stop;
2. the latest known-good checkpoint;
3. the generated report and acceptance/experiment evidence;
4. the Git commit and profile path used.

Do not copy a live SQLite database while writes are in progress. Pause first or
use an application-created checkpoint.

## Stop conditions

Treat these as terminal until reviewed:

- **success** — intended ticks/evidence complete and checks pass;
- **clean no-op** — no run was required after preflight/inspection;
- **approval required** — more provider spend or external deployment is needed;
- **blocked** — credential, model, dependency, or environment is unavailable;
- **halted** — ledger/reconciliation invariant failed;
- **stagnated** — repeated runs produce no new evidence toward the stated gate.

Never label an exhausted budget, partial report, provider pause, or failed replay
as success.

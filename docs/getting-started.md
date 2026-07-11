# Getting started

## Prerequisites

- Python 3.11 or 3.12
- Node.js 22 only when changing the React dashboard
- Git for normal development and CI workflows

The application itself is a single Python process. FastAPI serves the committed
dashboard bundle, so Node.js is not required for ordinary use.

## Install

From the repository root:

```powershell
python -m pip install -r requirements.txt
```

## First run: offline and deterministic

The offline profile requires no API key and is the safest way to verify a new
checkout:

```powershell
python run.py --config runs/base.yaml
```

Open <http://127.0.0.1:8000/>. The world starts paused. Use **Run** for
continuous execution, **Step** for one tick, **Pause** to preserve a resumable
run, and **Stop + report** to finish the run and generate its report.

For a short headless smoke run:

```powershell
python run.py --config runs/base.yaml --ticks 3
```

The command creates `data/runs/<run-id>.db`, periodic checkpoints under
`data/checkpoints/`, and an HTML report under `reports/out/`.

## Active production run: MiniMax M3 only

Copy the environment template and add the MiniMax Token Plan key locally:

```powershell
Copy-Item .env.example .env
```

Set `MINIMAX_API_KEY` in `.env`, then validate before genesis:

```powershell
python run.py --preflight
python run.py --preflight-live
python run.py
```

The no-argument command selects `runs/production.yaml`, creates exactly 100
agents at genesis, and routes every LLM purpose to `MiniMax-M3`. Kimi is not
part of the active default.

`--preflight` validates routes, model identifiers, endpoint compatibility, and
required environment variables without creating a run. `--preflight-live` also
authenticates against each routed provider's model catalog.

## Resume, replay, and report

Use the run ID printed at startup:

```powershell
python run.py --resume <RUN_ID>
python run.py --replay <RUN_ID>
python run.py --report <RUN_ID>
```

- Resume continues the existing database and restores its persisted status.
- Replay creates a separate database, uses stored LLM responses, makes no live
  provider calls, and prints table-by-table SHA-256 equality proof.
- Report reads the stored run and regenerates its end-of-run report.

## Verify the checkout

```powershell
python -m pytest tests/ -q
npm --prefix dashboard ci
npm --prefix dashboard run build
git diff --check
```

The dashboard build writes into `server/static/`. CI requires that committed
bundle to match the React source.

Continue with the [operator runbook](operator-runbook.md) or
[development guide](development.md).

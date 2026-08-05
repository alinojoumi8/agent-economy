# Getting started

## Prerequisites

- Python 3.11 or 3.12
- Git for development
- Node.js 22 only when changing the React dashboard

FastAPI serves a committed dashboard bundle, so ordinary users do not need
Node.js.

## Install

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install --require-hashes -r requirements.lock
```

On macOS or Linux, activate with `source .venv/bin/activate`.

## First run: free and deterministic

```powershell
python run.py --config runs/base.yaml
```

That command is the compact core-engine smoke world. To exercise every
Observatory surface without an API key, including regions, contracts, legal
matters, legislation, and lobbying, run:

```powershell
python run.py --config runs/v2-institutional-rehearsal.yaml
```

Open <http://127.0.0.1:8000/>. The world starts paused:

- **Run** advances continuously.
- **Step** advances exactly one simulated day.
- **Pause** preserves a resumable run.
- **Stop + report** finishes the run and writes a standalone report.

No API key or network call is required. A short headless smoke run is:

```powershell
python run.py --config runs/base.yaml --ticks 3
```

Generated state goes to `data/runs/`, checkpoints to `data/checkpoints/`, and
reports to `reports/out/`. These locations are ignored by Git.

## Try the research workflow

Run the five-seed rumor treatment/control experiment:

```powershell
python run.py --experiment runs/experiments/rumor_vs_control.yaml
```

The harness creates isolated worlds for each seed and arm and writes JSON,
Markdown, and HTML summaries under `reports/out/`.

For a free full-horizon rehearsal of the production acceptance schedule:

```powershell
python run.py --config runs/acceptance/rehearsal.yaml --acceptance-run `
  --experiment-evidence reports/out/experiment_rumor_vs_control.json
```

The rehearsal deliberately uses scripted providers. It verifies mechanics and
evidence plumbing, not live-provider latency, cost, or emergent behavior.

## Optional real models

Copy the environment template and populate it locally:

```powershell
Copy-Item .env.example .env
python run.py --preflight
python run.py --preflight-live --approve-live-inference
python run.py --serve --approve-live-inference
```

`--preflight` validates configuration without inference. `--preflight-live`
contacts provider model-catalog endpoints but does not request chat completion.
The default route uses MiniMax M3 for every model-eligible core/shared-service
call in the 1,000-agent profile. The long-tail periphery remains deterministic
and auditable rather than issuing 900 paid calls per simulated day.

Paid acceptance never starts implicitly. The bounded pilot and full run require
the explicit `--approve-live-inference` flag; read the
[operator runbook](operator-runbook.md) first.

## Resume, replay, and report

Use the run ID printed at startup:

```powershell
python run.py --config runs/base.yaml --resume <RUN_ID>
python run.py --replay <RUN_ID>
python run.py --report <RUN_ID>
```

Replay creates a new database, reuses stored LLM responses, makes no live model
calls, and prints canonical table-digest proof.

## Verify a checkout

Run the complete, hash-locked verification gate in the
[development guide](development.md#test-layers). It includes compilation,
pinned-dataset verification, Python and dashboard tests, dependency audits,
third-party notice freshness, the production build, and diff hygiene.

Continue with [core concepts and use cases](research-guide.md), the
[configuration reference](configuration.md), or the
[development guide](development.md).

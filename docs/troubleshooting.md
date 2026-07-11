# Troubleshooting

## The server will not start

1. Run `python run.py --config runs/base.yaml --preflight` for offline config or
   `python run.py --preflight-live` for the active provider profile.
2. Install dependencies with `python -m pip install -r requirements.txt`.
3. Check whether the port is already listening:

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
```

4. Start on another port if needed: `python run.py --config runs/base.yaml --port 8321`.

Do not terminate a listener until its command line confirms it belongs to this
repository.

## Preflight says a key is missing

- Active `runs/production.yaml` requires only `MINIMAX_API_KEY`.
- `runs/production-k2.6.yaml` requires MiniMax and Kimi Platform credentials.
- `runs/production-kimi-code.yaml` requires MiniMax and Kimi Code credentials.

Copy `.env.example` to `.env`; never put values in committed YAML.

## Kimi authentication or model validation fails

Kimi is disabled in the active default. Explicit profiles use different
services: K2.6 Platform uses `api.moonshot.ai` and `kimi-k2.6`; Kimi Code uses
`api.kimi.com/coding` and `kimi-for-coding`. The credentials are not
interchangeable.

## MiniMax times out or returns invalid JSON

The active profile allows 180 seconds and requests room for reasoning plus the
structured envelope. The gateway retries transport failure once and permits one
structured-output repair call. Inspect `/api/run/status`, `/api/cost`, and recent
`provider_failure` or `run_exception` events before resuming.

## Run cannot restart after Stop + report

Current behavior allows a finished run to start or step again. Refresh the
dashboard, confirm `/api/run/status`, then use Run or Step. A later stop creates
a fresh report. Status `halted` is intentionally not restartable.

## Conversations look repetitive

Confirm the routed provider through `/api/run/status` and retain a bounded
sample with run ID/ticks before changing prompts. Current contexts include
identity, occupation, personality, recent memory, shared topic, prior lines,
and speech mode. Compare distinct messages, repeated phrases, participants,
topics, and provider failures rather than judging a few adjacent lines.

## Dashboard is stale or blank

```powershell
npm --prefix dashboard ci
npm --prefix dashboard run build
```

Restart FastAPI and hard-refresh. Confirm `/` returns HTML and
`/api/run/status` returns JSON. Vite expects FastAPI on port 8000 for its proxy.

## Resume says the run is missing

Run IDs map to `data/runs/<run-id>.db` in the current worktree. Generated data
is not automatically shared between Git worktrees. A `RUN_ID@TICK` fork also
requires the corresponding checkpoint.

## Replay pauses or does not match

- Missing stored responses pause replay without making network calls.
- Exit status 3 means at least one canonical table digest differs.
- Preserve source/replay databases and the printed proof.
- Never overwrite the source or infer equality from dashboard visuals.

## Tests pass locally but CI fails

Reproduce the named CI command. Check Windows versus Ubuntu, Python 3.11 versus
3.12, stale `server/static/`, line endings, and accidentally staged generated
data. CI never needs live provider keys.

## Budget pause

A budget pause checkpoints before further spend. Inspect `/api/cost` and the
report. Continue only after an explicit decision to change the cap/config; do
not edit persisted evidence to make a partial run appear successful.

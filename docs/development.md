# Development and testing

## Repository workflow

Work on a feature branch or dedicated worktree. Preserve unrelated changes,
commit cohesive units, push the branch, and open a pull request into `main`.
CI must be green before merge.

The backend and committed dashboard bundle are one release unit. A frontend
change is incomplete until `server/static/` is rebuilt and committed.

## Backend setup

```powershell
python -m pip install -r requirements.txt
python run.py --config runs/base.yaml
```

Use the scripted profile for normal development. It exercises the complete
world without network cost and preserves deterministic golden results.

## Dashboard setup

Run FastAPI on port 8000, then in another terminal:

```powershell
Set-Location dashboard
npm ci
npm run dev
```

Vite proxies `/api`, `/ws`, and `/reports` to FastAPI. Production build:

```powershell
npm --prefix dashboard run build
```

The build writes directly to `server/static/`.

## Test layers

| Layer | Purpose |
|---|---|
| Unit/invariant | Ledger conservation, exchange matching, credit, firms, and deterministic mechanics |
| Integration | World phases, lifecycle, providers, memory, shocks, reports, and controls |
| Property | Randomized valid actions, lifecycle storms, no invented prices, and budget transitions |
| Golden run | Same seed/config produces the committed canonical event log |
| Acceptance evidence | Rumor thresholds, Oracle resolution/latency shape, long-run cost, replay, and campaign recovery |
| Dashboard build | React compiles and the committed production bundle is current |

Run the full local gate:

```powershell
python -m compileall -q agents engine experiments llm oracle reports server world run.py
python -m pytest tests/ -q
npm --prefix dashboard ci
npm --prefix dashboard run build
git diff --check
git diff --exit-code -- server/static
```

The final command passes only when the static bundle was already current before
the build. If a legitimate frontend change rebuilt it, review and commit those
generated files instead of discarding them.

## CI

GitHub Actions runs the dashboard build on Ubuntu with Node.js 22 and the full
Python suite on Ubuntu and Windows with Python 3.11 and 3.12. Pull requests,
pushes to `main`, and manual dispatch trigger CI.

## Engineering invariants

- LLM output is a proposal; deterministic code owns state transitions.
- Every monetary mutation uses balanced integer-cent ledger entries.
- Never invent a market price without a trade.
- Preserve stable ordering and seeded randomness for replay.
- Provider failures pause; they never silently switch to another backend.
- Run databases, reports, checkpoints, `.env`, and provider keys are generated
  or private artifacts, not source fixtures.
- The Oracle remains read-only.

## Change checklist

1. Update tests for changed behavior and failure paths.
2. Update examples and docs when commands, routes, defaults, or operator
   behavior changed.
3. Run the offline profile or smallest relevant scenario.
4. Run the full local gate above.
5. Inspect Git status for generated artifacts or secrets.
6. State any live-provider calls, modeled cost, and retained evidence in the PR.

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the contributor contract.

# Development and testing

## Repository workflow

Work on a feature branch or dedicated worktree. Preserve unrelated changes,
commit cohesive units, push the branch, and open a pull request into `main`.
The backend and committed dashboard bundle are one release unit.

## Backend

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python run.py --config runs/base.yaml
```

Use the scripted profile for normal development. It exercises all systems
without network cost and preserves deterministic results.

## Dashboard

Run FastAPI on port 8000, then in another terminal:

```powershell
Set-Location dashboard
npm ci
npm test
npm run dev
```

Vite proxies `/api`, `/ws`, and `/reports`. The production build writes directly
to `server/static/`:

```powershell
npm --prefix dashboard run build
```

Review and commit the new hashed bundle when frontend source changes.

## Test layers

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
python -m compileall -q agents engine experiments llm oracle reports server world run.py
python -m pytest tests/ -q
npm --prefix dashboard ci
npm --prefix dashboard test
npm --prefix dashboard run build
git diff --check
```

After a clean build, `git diff --exit-code -- server/static` proves the committed
bundle was already current. When it changed intentionally, review and commit it.

## Adding behavior safely

1. Keep economic mutation in `engine/` or deterministic `world/` mechanics.
2. Define a structured action contract; never parse model prose into money.
3. Validate actor role, ownership, state, amount, and phase.
4. Route every monetary effect through the ledger.
5. Emit a durable event with enough IDs/values to audit the transition.
6. Add success, rejection, replay, and reconciliation tests.
7. Update metrics/API/dashboard/docs if the behavior is observable.

## Schema and compatibility

Run databases are scientific artifacts. Additive columns/tables are preferred.
New semantics that would change historical output must be gated by
`engine_semantics_version`; v1/v2 replay behavior must remain exact. Never
rewrite a stored source run during replay.

## Logging

Use `observability.log_event` for process diagnostics and `Store.log_event` for
scientific/economic evidence. Operational logs must be bounded and secret-safe;
the SQLite event spine may contain richer causal evidence but should still avoid
credentials. Successful per-call request/replay/resume records are DEBUG-only;
INFO is reserved for run-level milestones and unusual recovery. Add assertions
for important failure/recovery logs.

## CI and review

GitHub Actions builds the dashboard on Node.js 22 and runs Python 3.11/3.12 on
Ubuntu and Windows. Pull requests should state behavior, tests, live calls/cost,
compatibility impact, and remaining risk. See [CONTRIBUTING.md](../CONTRIBUTING.md).

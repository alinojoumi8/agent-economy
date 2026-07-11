# Contributing

## Workflow

1. Create a feature branch or dedicated worktree from the intended base.
2. Keep changes scoped and preserve unrelated work.
3. Add or update tests and documentation with behavior changes.
4. Run the local verification gate.
5. Commit, push, and open a pull request into `main`.
6. Merge only after GitHub Actions is green.

## Local verification

```powershell
python -m compileall -q agents engine experiments llm oracle reports server world run.py
python -m pytest tests/ -q
npm --prefix dashboard ci
npm --prefix dashboard run build
git diff --check
```

If the dashboard changes, commit the updated `server/static/` bundle.

## Project invariants

- LLMs propose structured actions; deterministic engine code owns mutations.
- Every monetary transaction balances through the double-entry ledger.
- Preserve seeded determinism and exact replay.
- Provider failures pause visibly; never add silent fallback.
- Oracle remains read-only.
- Do not commit `.env`, API keys, run databases, checkpoints, generated reports,
  dependency folders, or local logs.

Pull requests should describe the outcome, tests run, and remaining risk. For
live-provider work, include profile, provider/model, bounded scenario, run ID,
failure count, and modeled cost without exposing credentials.

See [docs/development.md](docs/development.md) and
[docs/README.md](docs/README.md).

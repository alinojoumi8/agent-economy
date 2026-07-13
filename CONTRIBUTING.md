# Contributing to Agent Economy

Thank you for improving Agent Economy. The project values reproducible evidence,
small reviewable changes, and explicit accounting over clever shortcuts.

## Workflow

1. Branch from the current `main` or create a dedicated worktree.
2. Keep the change focused and preserve unrelated work.
3. Add tests for behavior and failure paths.
4. Update commands, configuration, API, and operator docs when they change.
5. Run the local verification gate.
6. Push the branch and open a pull request into `main`.
7. Merge only after GitHub Actions passes.

## Local verification

```powershell
python -m compileall -q agents engine experiments llm oracle reports server world run.py
python -m pytest tests/ -q
npm --prefix dashboard ci
npm --prefix dashboard test
npm --prefix dashboard run build
git diff --check
```

The dashboard build writes to `server/static/`. Commit that regenerated bundle
whenever dashboard source changes.

## Non-negotiable invariants

- LLMs propose structured actions; deterministic engine code validates and
  applies them.
- Every monetary mutation uses balanced integer-cent double-entry legs.
- Never invent a market price without an executed trade.
- Preserve stable ordering, seeded randomness, and exact replay compatibility.
- Provider failures pause visibly; never introduce a silent model fallback.
- The Oracle remains read-only.
- Citizens do not receive private bank balance-sheet data in semantics-v3 runs.
- Reserved beliefs remain bounded and every accepted update is auditable.

## Pull request evidence

Describe the outcome, risks, tests, and any remaining limitation. For live-model
work, include the exact profile, provider/model, bounded scenario, run ID,
failure counts, and recorded cost without exposing credentials, prompts, or
private response content.

Do not commit `.env`, credentials, run databases, checkpoints, generated
reports, dependency folders, or local logs. See the
[development guide](docs/development.md) and [security policy](SECURITY.md).

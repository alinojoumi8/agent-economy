# Contributing to Agent Economy

Thank you for improving Agent Economy. The project values reproducible evidence,
small reviewable changes, and explicit accounting over clever shortcuts.

## Licensing of contributions

Agent Economy is released under the [MIT License](LICENSE). By submitting a pull
request you agree that your contribution is licensed under those same terms.

## Workflow

1. Branch from the current `main` or create a dedicated worktree.
2. Keep the change focused and preserve unrelated work.
3. Add tests for behavior and failure paths.
4. Update commands, configuration, API, and operator docs when they change.
5. Run the local verification gate.
6. Push the branch and open a pull request into `main`.
7. Merge only after GitHub Actions passes.

## Local verification

Run the complete hash-locked gate documented in
[docs/development.md](docs/development.md#test-layers). It includes compilation,
pinned datasets, Python/dashboard tests, dependency and notice audits, the
production bundle, and diff hygiene.

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
- Citizens do not receive private bank balance-sheet data in maintained
  public-status profiles; stored historical semantics retain their contract.
- Reserved beliefs remain bounded and every accepted update is auditable.

## Pull request evidence

Describe the outcome, risks, tests, and any remaining limitation. For live-model
work, include the exact profile, provider/model, bounded scenario, run ID,
failure counts, and recorded cost without exposing credentials, prompts, or
private response content.

Do not commit `.env`, credentials, run databases, checkpoints, generated
reports, dependency folders, or local logs. See the
[development guide](docs/development.md) and [security policy](SECURITY.md).

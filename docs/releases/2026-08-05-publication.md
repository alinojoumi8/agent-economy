# 2026-08-05 repository publication receipt

- Repository: `alinojoumi8/agent-economy`
- Publication branch: `codex/publish-20260805`
- Publication head: `f67a86031b9a90ba5c512fd0d3e5b737b38e0da8`
- Origin head before publication: `2b8e5786638c18fb02f35d4cc9d915669cb2246d`
- Divergence before publication: `10 0` (`HEAD...origin/main`, left/right)
- Tracked tree: clean
- Protected untracked paths in primary worktree: `data/`, `env`, `graphify-out/`

## Unpublished commits

- `2aa4893a3121e5c5bb2929ccb8db3dfb935e0973` docs: design interactive living economy map
- `ccca20658fe68fdafbd3069f94b85b7f21cd2f83` docs: plan interactive living economy map
- `154a5b74daa5b7709f10b20864da89a20198a062` chore: ignore local worktrees
- `0fae4482c200cd4f13d2bbff5dbc00a3af0c67a7` chore: snapshot local work before upstream integration
- `2c427409cd88f8166900f9e1a0175a1b9d2f87dd` Merge origin/main into local integration branch
- `28714dde52d5058ac90b42c4c5df1c9f198f95b8` fix: reconcile upstream and live MiniMax contracts
- `36a7203d5df82fde10336717158cb2c10a0dd036` fix(dashboard): preserve rapid observer state updates
- `dfa604ba181c566e7873b5254f60df13b0736dea` chore(deps): update postcss security patch
- `6dadb129cd2adb218ccdb47e138cacdf3c7f3d45` docs: design remaining integration and release work
- `f67a86031b9a90ba5c512fd0d3e5b737b38e0da8` docs: plan remaining integration and release tasks

## Verification

| Gate | Command | Result |
|---|---|---|
| Python package compatibility | `uv pip check --python /mnt/data/projects/agent-economy/.venv/bin/python` | Passed: 76 installed packages compatible. The existing project virtual environment has no `pip` module, so `uv pip check` inspected that exact interpreter. |
| Dashboard locked install | `npm ci` | Passed: 85 packages installed; 0 vulnerabilities. |
| Python suite, 8 deterministic shards | `pytest tests/ -q -p scripts.pytest_shard --ci-shard-index N --ci-shard-count 8`, N = 0..7 | Passed: 993 passed, 7 environment-gated skips, 0 failed. |
| Dashboard unit tests | `npm test` | Passed: 65 passed, 0 failed. |
| Dashboard typecheck | `npm run typecheck` | Passed. |
| Third-party notices | `npm run licenses:check` | Passed; committed notice is current. |
| Dependency audit | `npm audit --audit-level=high` | Passed: 0 vulnerabilities. |
| Chromium end-to-end | `npm run test:e2e -- --project=chromium` | Passed: 25 passed, 0 failed. |
| Production build | `npm run build` | Passed: 732 modules; committed `server/static` remained byte-identical. |
| Tracked diff | `git status --short` and `git diff --check` | Passed: clean after the maintained build. |

## Remote publication

- Status: `passed_fast_forward`
- Remote head observed immediately after publication: `362d3973a34a03579304837f1be1189b7a9476cc`
- Verification: a fresh `git fetch origin main` returned the same commit as local `HEAD`, and `git merge-base --is-ancestor HEAD origin/main` exited `0`.
- Mutation: `git push origin HEAD:main`; no force, rebase, tag, release, or deployment action was used.

## Branch disposition

| Branch | Relationship to published head | Action |
|---|---|---|
| `codex/integrate-origin-20260805` | Fully contained; published head has 6 additional commits. | Retain as a safety reference. |
| `codex/pre-pull-20260805` | Fully contained; published head has 57 additional commits. | Retain as a historical safety point. |
| `codex/reconcile-release` | Diverged: published head has 44 unique commits; branch has 26 unique commits. | Preserve its linked worktree and reconcile selectively under the recovery plan. |
| `feature/living-economy-map` | Diverged: published head has 51 unique commits; branch has 21 unique commits. | Preserve the dirty linked worktree and execute the salvage plan; never merge wholesale. |
| PR 39 Recharts 3.10.1 | Open dependency branch; failing historical dashboard CI is not contained. | Rebase/apply independently on the published head and rerun its full gate. |
| PR 40 React Query 5.101.4 | Open dependency branch; failing historical dashboard CI is not contained. | Rebase/apply independently on the published head and rerun its full gate. |

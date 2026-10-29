# District preview verification

Candidate: `codex/starnet-ui-redesign`, based on
`ed20ff4395581a5b4257d3fbd6b7cc971f97c318`.
Implementation commit: `52dedbd` (`feat(city): add an interactive district preview`).
Subsequent documentation commits record review status without changing the bundle.

## Scope

The first accepted redesign increment refreshes the opt-in 3D district, native
landmark selection, responsive composition and camera framing. The existing
shared evidence inspector, projection admission, Atlas/List, history and URL
state remain authoritative. No third-party code or art, dependencies, economic
mechanics or saved source runs were changed.

## Evidence boundary

- Synthetic browser cases exercise 390 × 844, 768 × 1024 and 1440 × 1000;
  selected landmark and keyboard explorer parity; bounded non-overlapping
  labels; selection focus; historical/fork evidence context; absence of observer
  writes; empty and forbidden projections. Existing city cases cover WebGL and
  asset failure, invalid refresh, missing coordinates, camera gestures,
  reload/history, construction and clock controls.
- The production bundle is also exercised against a new isolated scripted world
  in `/tmp/manyworld-district-preview-cla65hvc`, run `26e4f8e9fc`, paused at day 3.
  It has zero non-scripted calls, zero provider costs and zero model attempts.
  Real-backend navigation and 3D reload tests pass. This is local rehearsal
  evidence, not hosted acceptance or a scientific result.
- Rendering captures and command logs are retained outside the repository in
  the task's `starnet-district` artifact directory. Fixture snapshots are not
  evidence of production data or measured human task completion.

## Verification status

| Check | Result |
| --- | --- |
| Dashboard unit command | Passed: 48 test files |
| Dashboard TypeScript | Passed |
| Production build | Passed; committed static bundle regenerated; existing large-chunk warning remains |
| Critical browser suite | 154 passed in 331 seconds before the final camera-reset refinement |
| Final city regression | 21 passed in 72 seconds: six district cases plus fifteen existing 3D cases, after the final camera-reset correction |
| Real-backend City suite | 2 passed; local production bundle and fresh scripted world |
| Python smoke | 170 passed in 146 seconds |
| Final documentation suite | 22 passed |
| Python compile, datasets, pip check | Passed |
| Full Python suite | Incomplete: stopped at 300-second bound with two failure markers |
| Checkpoint-study follow-up | G2 preserve-and-stop fails its eligible-coverage assertion; worker receipts contain `ValueError` / `worker_failed` at zero ticks. F2 passes in the focused run (1 failed, 1 passed). This backend failure remains unresolved. |
| Third-party notices | Failed: existing notice file is stale; no dependency or lockfile changes were made |
| Python dependency audit | Failed: existing `certifi 2026.6.17`, `PYSEC-2026-4320` |
| Dashboard dependency audit | Unavailable through pnpm: repository has package-lock.json but no pnpm-lock.yaml; no lockfile migration performed |
| TypeScript-client build/typecheck | Unavailable: client dependencies/tsc are absent |
| Lint | No dashboard lint script is configured |
| ECC design evidence record | Completeness checker passed; actual captures were also visually inspected |
| Staged secret scan | Passed; no leaks found |
| CodeRabbit | The user approved sharing the diff after automatic approval review initially blocked it. Review of the updated PR is pending. |
| Hosted CI | Pending draft PR; no merge or deployment |

The two broad-suite failure positions were identified from collection order and
then explicitly rerun using fresh temporary test worlds. No existing research
database was replayed or modified. Logs and failed worker receipts are retained.

The real-world observer check starts after server initialization: selecting
citizens, opening/closing a dossier, inspecting day 3 and switching List/3D
issued no API writes. SQLite dump hashes before and after that journey match
(`10011acd24843885d59c9a2ea17f8f51767d92962908cc14a3b0773a1d0a3886`).
The earlier pre-server hash differed after startup; that initial mismatch is
retained in the local receipt and is not presented as an unchanged startup.

The 300-agent/100-place resource tests pass, but no new hardware frame-time
benchmark or human task-completion study was run. MW-33 remains In Progress.

## Landmark border follow-up

Removed the landmark buttons' 3px bottom accent, retaining a uniform 1px outline
and the existing 5px corners. The `border-accent-on-rounded` finding is fixed;
no suppressions were added and no findings from this review remain standing.
The production build and all six district browser tests passed. The initial
test attempt stopped at Chromium launch because of the shell sandbox; the
successful rerun used the approved unrestricted test command. The rebuilt
preview was visually inspected at 1440px and 390px: labels retain 44px targets,
1px borders on all sides, a 3px keyboard focus outline and no page overflow.
The broader verification limits above remain unchanged.

# Branch and Documentation Consolidation Plan

Created: 2026-08-20

## Purpose

Make `main` an understandable, reviewable baseline; preserve every active or
unique line of work; retire only branches proven merged or superseded; and keep
the application handbook aligned with the code that is actually being built.

This plan is an inventory and decision record. It does not authorize branch
deletion, worktree removal, merging, resetting, pushing, or publication.

## Guardrails

- Never delete or repoint a branch with uncommitted work.
- Never remove a worktree until its status is clean and its branch or detached
  commit is reachable from an intentionally retained ref.
- Treat GitHub pull-request state, patch equivalence, and Git ancestry as
  separate evidence. A squash-merged branch may not be an ancestor of `main`.
- Preserve unique commits before changing `main` or pruning refs.
- Merge or port one feature line at a time and run its own verification gates.
- Do not rewrite stored simulation evidence or mix release evidence from
  different source commits.

## Audited snapshot

The snapshot below was collected on 2026-08-20 from local refs, live remote
heads, GitHub pull requests, ancestry comparisons, and all linked worktrees.

| Surface | Audited state | Consequence |
|---|---|---|
| Local `main` | `1200adde42f55b2c047487a69b403fa02126c1ce`, one commit ahead of live `origin/main` | Preserve and review this commit before normalizing the base. |
| Live `origin/main` | `78e6a77a5750222fec122d445b759eee7ae55343` | Remote remains the last shared baseline until the local commit lands. |
| Active checkout | `codex/buzz-agent-patterns`, same tip as local `main`, dirty | Protect and finish as an independent feature line. |
| Second active worktree | `codex/live-city-diorama`, same tip as local `main`, dirty | Protect and finish separately from Buzz work. |
| Unique legacy work | `codex/reproducibility-release` at `f2903db2b52983b9622a2f7e93815626f4d154da` | Port onto a fresh current branch; never merge the stale tip wholesale. |
| Open remote work | PR #55 and PR #57 | Review, update, merge, or close intentionally before remote cleanup. |
| Clean detached worktrees | Two Claude worktrees at `7f46de9` | Eligible for removal only after an approved final reachability check. |

## Branch disposition

### Protect and finish

- `codex/buzz-agent-patterns`
- `codex/live-city-diorama`
- `main` commit `1200add`

Each is protected until its work is committed, verified, and assigned an
explicit landing decision.

### Port rather than merge

`codex/reproducibility-release` contains one unique commit, `f2903db`. The
commit itself changes eleven release-profile, evidence, test, documentation,
and generated-dashboard files. Comparing its old tip directly with current
`main` would remove substantial newer application work. Create a fresh branch
from the eventual canonical `main`, port the source/test/template/documentation
changes selectively, rebuild generated assets from current sources, and run
the release gates. Retire the old branch only after the replacement is durable.

### Locally merged or superseded candidates

The following local branches are fully contained in local `main`, or have a
merged GitHub pull request that explains their non-ancestor squash history:

- `claude/funny-noyce-1f33b0`
- `claude/hungry-sammet-6da15d`
- `codex/construction-economy`
- `codex/external-gateway-rc`
- `codex/living-agents`
- `codex/living-agents-visual-parity`
- `feat/live-city` (merged as PR #58; remote branch already gone)
- `safety/external-gateway-rc-20260815`
- `safety/external-gateway-rc-20260815-v2`
- `safety/external-gateway-rc-20260815-v3`
- `safety/pre-rc-local-main-20260815`
- `safety/pre-rc-origin-main-20260815`

These are cleanup candidates, not an instruction to delete them. Recheck
ancestry, pull-request state, worktree attachment, and cleanliness immediately
before any deletion.

### Remote review queue

Keep these remote branches while their pull requests are open:

- `codex/scale-validation-receipts-20260810` - PR #55
- `dependabot/npm_and_yarn/dashboard/vite-8.2.1` - PR #57

The following remote branches have merged pull requests and can enter a later
approved remote-pruning batch:

- `codex/external-gateway-rc` - PR #61
- `codex/living-agents-visual-parity` - PR #62
- `feat/city-conversations` - PR #60
- `fix/conversation-pairs` - PR #59

## Execution phases

### Phase 1: Preserve the baseline

1. Give commit `1200add` an intentional review/landing path.
2. Confirm both dirty feature lines descend from the intended base.
3. Record clean status and test evidence before moving any ref.

Exit criterion: the local-only base commit is either shared through its own
review path or explicitly rejected while remaining recoverable.

### Phase 2: Finish active work one line at a time

1. Complete and validate `codex/buzz-agent-patterns`.
2. Complete and validate `codex/live-city-diorama` in its existing worktree.
3. Keep commits, tests, generated assets, and documentation scoped to the
   feature line that owns them.

Exit criterion: each feature has a clean worktree, a coherent commit history,
and an explicit PR or retention decision.

### Phase 3: Salvage reproducibility work

1. Start from the current canonical shared base.
2. Port the `f2903db` release-profile behavior, tests, template, and guide.
3. Reconcile current release-evidence code instead of accepting stale versions.
4. Regenerate dashboard assets from the current dashboard source.
5. Preserve the historical blocked secret-scanner and shell-test limitations
   until current evidence proves they are resolved.

Exit criterion: the valuable change is represented by a current, reviewed
branch or is explicitly rejected with rationale.

### Phase 4: Resolve open remote work

Review PR #55 and PR #57 against the new baseline. Update, merge, supersede, or
close each PR explicitly. An old or conflicting PR is not silently abandoned.

Exit criterion: no open pull request has an unknown owner or disposition.

### Phase 5: Approved cleanup batch

1. Re-fetch or query live remote state.
2. Re-run branch ancestry and patch-equivalence checks.
3. Confirm every attached worktree is clean.
4. Remove approved clean obsolete worktrees.
5. Delete approved merged local branches.
6. Delete approved merged remote branches.
7. Prune stale remote-tracking refs and produce a final inventory.

Exit criterion: every remaining branch maps to `main`, an open PR, an active
worktree, a unique preserved commit, or an explicitly time-bounded safety ref.

## Permanent branch policy

- Start feature branches from the current shared `origin/main` unless a written
  integration plan requires another base.
- Use one product outcome per branch and one active worktree per branch.
- Give every branch an upstream and a PR, issue, or plan reference.
- Open a draft PR early for work expected to outlive one session.
- Do not use `main` as an unpublished staging branch.
- Delete ordinary feature branches after merge and a final reachability check.
- Replace indefinite `safety/*` refs with a documented retention date or durable
  tag when long-term preservation is actually required.
- Audit branches and worktrees weekly while parallel feature work is active.

## Documentation completion scope

- Keep the root README concise and centered on the research simulator.
- Keep World OS and Civic City as clearly labeled extensions.
- Add a permanent branch/worktree lifecycle guide.
- Document Semantics 14 attendance in the gateway, API, configuration, and
  compatibility surfaces.
- Document the shared historical-safe activity projection.
- Document proposal-only Builder boundaries without claiming a Builder runtime.
- Document hosted audit-chain operation, legacy rows, and lack of external
  anchoring.
- Keep `docs/implementation-status.md` current while preserving
  `docs/implementation-status.html` as its explicitly labelled historical
  Semantics-7 printable snapshot with a link to the current ledger.
- Give every ADR explicit Status, Context, Decision, and Consequences sections.
- Verify links, CLI help, documentation tests, focused feature tests, the full
  Python suite, dashboard tests/build when affected, and diff hygiene.

## Progress recorded on 2026-08-20

- The active Buzz-derived feature line was checkpointed as `fb129a5`
  (`feat(runtime): add buzz-derived agent boundaries`).
- The project-venv feature/documentation gate passed 187 tests with one
  Starlette deprecation warning.
- The consolidated handbook now includes a concise research-first README,
  permanent branch and documentation-maintenance guides, a Semantics 14 guide,
  current architecture/API/configuration/operator/security cross-links, and
  ten structured ADRs (three Accepted, seven Proposed).
- Final documentation/profile validation passed 26 tests. The repository smoke
  contract passed 138 tests with the same Starlette deprecation warning.
- The complete Python collection then ran for 55m50s: 1,492 passed, 9 skipped,
  and 2 failed. It exposed a fixed-count idle-poll race in one served-run test
  and a stale schema-19 maximum assertion after schema 20 was added.
- After correcting those two test contracts, the full owning files passed
  (84 PRD-completion tests and 11 Semantics-13 construction tests), and the two
  formerly failing nodes passed together. The entire 1,503-test collection was
  not rerun after the fixes and must not be reported as a post-fix full-suite
  pass.
- Link validation covers every new durable guide and ADR. `git diff --check`
  passes; Windows reports only its configured LF-to-CRLF conversion warnings.
- The historical HTML status snapshot remains frozen by design; the current
  Markdown ledger was refreshed to 2026-08-20.
- No branch was merged or deleted, no worktree was removed, and no remote ref
  was pushed or changed.

At that checkpoint, the next branch action remained Phase 1: give local-only
base commit `1200add` an intentional review/landing decision before normalizing
`main`.

## Progress recorded on 2026-08-21

- Live `origin/main` was refreshed and remained at `78e6a77`; local commit
  `1200add` was still the single unpublished base commit.
- `1200add` was reviewed as a seven-file runtime change, verified from a clean
  detached worktree, and published without moving local `main` as
  `codex/runtime-throughput-base`.
- PR #63 provided the focused landing path at exact head
  `1200adde42f55b2c047487a69b403fa02126c1ce`. Python smoke, the core subset
  guard, and the dashboard production build passed. The hosted integration
  jobs were skipped by their workflow gates; CodeRabbit reported that automatic
  review was unavailable for this repository and required manual review.
- Isolated local verification passed 216 tests. One supplemental command named
  a test that exists only on the later Buzz branch, so that attempt stopped
  before collection; the corrected 42-test scope passed. The existing
  Starlette/httpx deprecation warning remains visible.
- A controlled local measurement found 1.40x median improvement for repeated
  same-identity observer snapshots on a synthetic 1,000-event store. With a
  gateway width of one, the new pipeline prepared two agents before the first
  dispatch released versus one on the base scheduling path. These are bounded
  local measurements, not production-provider throughput claims.
- The temporary review worktree and PR-body file were removed after
  verification. The dirty `codex/live-city-diorama` worktree, the
  `codex/reproducibility-release` source commit, and all cleanup candidates
  remain untouched.
- PR #63 was marked ready and merged on 2026-08-21 as merge commit
  `1b61b22fe30adb6f1c5b18fed36685dd691c6e98`. Local `main` was then
  fast-forwarded to the same commit without disturbing an attached worktree.
- Before rebasing the Buzz stack, its old tip was retained as
  `safety/buzz-agent-patterns-pre-rebase-20260821`. The active
  `codex/buzz-agent-patterns` branch was rebased cleanly onto the merged base.
- Post-rebase validation passed the 159-test focused feature/documentation gate,
  the exact 138-test repository smoke contract, and the complete Python
  collection: 1,494 passed and 9 skipped in 55m32s. The one known
  Starlette/httpx deprecation warning remains visible.
- Dashboard validation passed 184 unit tests, TypeScript checking, the license
  policy check, a zero-vulnerability high-severity npm audit, the production
  build, and 41 critical Chromium scenarios. Vite retained its large-chunk
  warning, and the mocked browser harness logged expected proxy connection
  refusals without failing a scenario.
- The validated Buzz stack was published for review as PR #64,
  `feat(runtime): add governed agent boundaries and handbook`.
- No branch was deleted. The dirty `codex/live-city-diorama` worktree, the
  `codex/reproducibility-release` source commit, and all cleanup candidates
  remain untouched.

The remaining recommended landing order is:

1. Finish full validation of `codex/buzz-agent-patterns`, then give its feature,
   handbook, and regression-test commits a separate reviewed PR.
2. Audit and finish `codex/live-city-diorama` in its existing protected
   worktree; do not mix its uncommitted state into the Buzz PR.
3. Port the useful `f2903db` reproducibility work selectively onto the then
   current shared base.
4. Resolve PR #55 and PR #57, then request explicit approval for a final
   worktree and merged-branch cleanup batch.

## Completion record

The consolidation is complete only when:

- `main` and `origin/main` have an intentional relationship;
- both active dirty worktrees are clean or intentionally preserved;
- the reproducibility commit has a current disposition;
- open PRs have explicit decisions;
- only approved merged branches/worktrees have been removed;
- the handbook describes the current branch without overstating release status;
- all claimed verification was actually run and recorded.

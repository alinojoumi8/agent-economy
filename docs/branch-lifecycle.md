# Branch lifecycle and consolidation

This guide is the permanent process for deciding what to protect, review,
merge, port, or delete. A dated branch audit records the current facts; this
document defines the repeatable rules. The active audit is
[the 2026-08-20 consolidation plan](plans/2026-08-20-branch-and-documentation-consolidation-plan.md).

## Safety rules

1. Inventory local branches, remote heads, pull requests, and worktrees before
   changing any ref.
2. A dirty worktree is protected. Checkpoint its work or obtain its owner's
   explicit disposition before merge, move, removal, or deletion.
3. A unique commit is evidence. Do not delete its last reachable branch until
   it is merged, deliberately ported, archived, or explicitly rejected.
4. Prefer normal pull requests into `main`. Use selective ports when a branch
   contains valuable commits but its full diff would undo newer work.
5. Use `git branch -d` for proven merged local branches. Force deletion,
   remote deletion, worktree removal, and history rewriting require separate
   explicit approval.
6. Never treat a same-looking working tree as proof of ancestry. Squash merges
   and cherry-picks require pull-request and patch-equivalence evidence.
7. Fetching, merging, deleting, pushing, and pruning are separate actions.
   Record which ones were authorized and performed.

## Lifecycle labels

| Label | Meaning | Required next action |
|---|---|---|
| **active-protected** | Checked-out or dirty work, or a branch with an active owner | Finish or checkpoint; do not consolidate |
| **review-ready** | Cohesive, tested change intended for `main` | Push and open/update a focused pull request |
| **open-review** | Remote branch belongs to an open pull request | Preserve until the pull request is merged or closed |
| **port-source** | Contains useful commits but is unsafe to merge wholesale | Create a clean branch from current `main`, port selected commits, test, then archive source |
| **merged** | Ancestry, merged pull request, or reviewed patch equivalence proves integration | Local/remote deletion may be proposed |
| **superseded** | Replaced by newer work and has no wanted unique content | Record replacement evidence; propose deletion |
| **archived** | Intentionally retained for reproducibility or historical evidence | Protect and state why it remains |
| **unknown** | Evidence is incomplete or ownership is unclear | Preserve and investigate |

Every audit row should include branch/ref, commit, worktree, dirty state,
upstream, ahead/behind counts, open or merged pull request, unique commits,
classification, evidence, and proposed action.

## Read-only audit

Run from the primary repository worktree:

```powershell
git status --short --branch
git worktree list --porcelain
git branch -vv
git branch --merged main
git log --oneline --decorate --graph --all --max-count=100
git ls-remote --heads origin
gh pr list --state open
gh pr list --state merged --limit 100
```

For each branch that is not clearly merged, compare its commits and patch:

```powershell
git log --left-right --cherry-pick --oneline main...<branch>
git diff --stat main...<branch>
git diff --name-status main...<branch>
```

`git branch --merged` proves ancestry only. For squash-merged work, retain the
merged pull-request URL/number and compare the branch diff with the merge result
before classifying it as merged. For a port source, inspect individual commits
with `git show --stat <commit>` and record exactly which commit or paths are
wanted.

## Consolidation sequence

Work one branch at a time:

1. **Protect active work.** Confirm the branch and worktree, inspect
   `git status --short`, run the relevant tests, and create a cohesive
   checkpoint if authorized.
2. **Update the audit.** Capture current local/remote tips and pull-request
   state. Do not rely on a stale inventory.
3. **Choose one integration path.**
   - Normal merge: clean focused branch, current `main`, successful relevant
     gates, and an ordinary pull request.
   - Selective port: branch is divergent or destructive as a whole; create a
     new `codex/` branch from current `main`, cherry-pick or reimplement the
     named commit, resolve intentionally, and test the result.
   - No integration: branch is already merged, superseded, experimental, or
     intentionally archived.
4. **Verify the destination.** Record exact commands and results. A source
   branch is not disposable merely because a command completed.
5. **Propose cleanup.** Name exact local and remote refs, the evidence for each,
   and whether recovery remains possible.
6. **Delete only after approval.** Re-run status and worktree checks immediately
   before the deletion command.

Do not combine unrelated feature branches into a single reconciliation pull
request. If two branches depend on each other, document the dependency order
and land the lower-level contract first.

## Deletion gate

A local branch is eligible for normal deletion only when all are true:

- it is not checked out in any worktree;
- every associated worktree is clean and intentionally retained or already
  removed;
- no open pull request or active owner depends on it;
- its desired commits are reachable from the chosen destination, or the audit
  explicitly records that they are rejected/superseded;
- tests and evidence for the destination are recorded;
- the exact ref was approved for deletion.

Then refresh the evidence and use:

```powershell
git worktree list --porcelain
git branch --merged main
git branch -d <local-branch>
```

If `git branch -d` refuses, stop. Do not substitute `-D` unless the audit
proves why ancestry is absent and the user explicitly approves force deletion.

A remote branch additionally requires confirmed merged/closed review state and
explicit remote-deletion authorization. Remote deletion changes shared state;
it is never implied by local cleanup.

## Worktrees

A branch checked out elsewhere cannot be assessed from the primary worktree's
status alone. For every listed worktree:

- resolve and record its absolute path;
- inspect its own branch and dirty state;
- identify its owner/purpose;
- preserve untracked files as first-class work;
- do not remove it merely because its branch was merged.

Pruning stale administrative worktree records is different from removing a
worktree directory. Both require exact target review; removal requires explicit
authorization.

## Naming and branch scope

- Use `codex/<short-purpose>` for new Codex branches.
- Keep one coherent outcome per branch and commit.
- Rebase or merge current `main` only when the branch owner accepts the
  conflict strategy.
- Put generated dashboard assets in the same branch as their source change.
- Do not mix branch cleanup with product changes or release publication.

## Audit record and cadence

Store dated investigations in `docs/plans/YYYY-MM-DD-...md`. Each plan must
separate observed facts, proposed decisions, and completed actions. Update it
after any merge, port, pull-request transition, worktree change, or deletion.

Run a lightweight audit before starting a large feature and after its pull
request lands. Run a full consolidation audit when branch/worktree ownership is
unclear or when more than one branch appears to implement the same product
surface.

The final handoff must state:

- active branch and resulting commits;
- branches merged, ported, preserved, or deleted;
- tests actually run and any failures;
- remote changes performed;
- unresolved decisions and the next recommended branch.

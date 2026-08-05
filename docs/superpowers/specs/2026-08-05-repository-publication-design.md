# Repository Publication and Dependency Integration Design

## Goal

Publish the verified local `main` history without losing user work, then integrate the two current dashboard dependency updates as isolated, reviewable changes. The process must leave GitHub, the local checkout, backup branches, and registered worktrees in an explainable state.

## Current boundary

At design time, local `main` is eight commits ahead of `origin/main` and zero commits behind. The tracked tree is clean; `data/`, `env`, and `graphify-out/` are intentionally untracked. Pull request heads 39 and 40 contain the Recharts 3.10.1 update and the TanStack React Query 5.101.4 lockfile update. The civic branch and committed living-economy-map branch are superseded by work already present on `main`; the local recovery branch and dirty living-economy-map worktree are separate workstreams and must not be folded into publication.

These facts are preflight inputs, not permanent assumptions. Execution must fetch and recompute divergence immediately before any push or merge.

## Considered approaches

### 1. Publish the tested local stack, then integrate dependencies separately — selected

Create an isolated publication worktree at the current local `main`, verify its exact commit range and full release-relevant local gates, and publish that history. Apply each dependency update in its own commit or pull request and run the dashboard gate after each. This preserves attribution and makes a dependency regression bisectable.

### 2. Merge all outstanding branches before publishing

This would minimize pushes but would mix tested fixes, dependency changes, recovery semantics, and stale branches. It would invalidate the existing test evidence and make rollback ambiguous.

### 3. Force local `main` onto GitHub

A force push would be unnecessary while the update is a fast-forward and would create avoidable risk. It is prohibited by this design.

## Selected workflow

Publication uses a clean worktree so untracked run data and graph artifacts cannot enter a commit accidentally. The preflight records:

- local and remote commit IDs;
- `main...origin/main` left/right counts;
- the exact eight-commit publication range;
- `git diff --check` and tracked-tree cleanliness;
- registered worktrees and branches that must remain untouched;
- the configured remote URL without credentials.

The local stack is then verified at its exact head. A push is permitted only when `origin/main` remains an ancestor of the publication head and the destination is the expected repository. If GitHub authentication or branch protection prevents publication, the task records `blocked` and stops; it does not rewrite history or weaken protections.

Dependency work begins only after the publication head is fixed. PR 39 changes `dashboard/package.json` and `dashboard/package-lock.json` for Recharts. PR 40 updates the resolved TanStack React Query version and lock metadata. Each update is applied against the current publication head, reviewed for transitive changes, and tested independently. Combining them is allowed only in a final release branch after both isolated gates pass.

## Verification contract

The publication stack must pass:

- all maintained Python CI shards with environment-gated tests reported separately;
- dashboard unit tests, Playwright tests, type checking, production build, license generation/freshness, and dependency audit;
- a real Chrome smoke against the built application;
- the existing live MiniMax contract smoke only when credentials and explicit live-inference authorization are available;
- secret, provenance, dependency, and diff checks appropriate to a branch publication.

The dependency updates must additionally show the requested package version in both manifest and lockfile, contain no unrelated lock churn, and leave the committed static dashboard bundle fresh when that bundle is part of the repository contract.

## Branch disposition

No branch is deleted as part of publication. The integration and pre-pull safety branches are documented as ancestors or historical recovery points. Superseded civic and living-map remote branches may be closed or labelled only after their tip content is compared with `main`. The recovery branch and dirty worktree remain protected inputs to their own plans.

## Failure handling

- Remote advancement: fetch, stop, and recompute the integration plan; never push over it.
- Test failure: retain the failing commit locally and fix or revert it before publication.
- Dependency regression: revert only the responsible dependency commit.
- GitHub authentication or billing failure: record the exact external blocker without claiming CI or publication.
- Unexpected tracked changes: stop and classify ownership before staging anything.

## Acceptance evidence

Completion requires the published Git commit IDs, remote verification that `origin/main` contains them, per-update test receipts, a final clean tracked tree, and a branch-disposition note. A local green test run without remote containment is not publication, and a mergeable dependency head without passing local gates is not an accepted dependency update.

## Out of scope

- Integrating `codex/reconcile-release`.
- Salvaging uncommitted work from the living-economy-map worktree.
- Tagging, deploying, or claiming public release readiness.
- Deleting local safety branches, worktrees, run databases, or generated evidence.
